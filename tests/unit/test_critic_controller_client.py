from unittest.mock import MagicMock, patch

from nvdastudio.ai.critic import Critic, Verdict
from nvdastudio.builder.controller_client_context import project_type_marker


def _mock_resp(json_str: str):
	resp = MagicMock()
	resp.content = json_str
	resp.reasoning = None
	return resp


class TestGuardImportsProibidosPulaProControllerClient:
	def test_import_proibido_reprovado_em_addon_normal(self, fake_api_key):
		"""Baseline (regressao): sem o marcador, um import da lista
		FORBIDDEN_IMPORTS (nao existe no ambiente NVDA, ver ai/critic.py)
		continua sendo pego pelo guard deterministico, sem chamar o LLM."""
		with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
			critic = Critic()
			result = critic.evaluate_two_stage(
				"code_generation", "import win32clipboard\nwin32clipboard.OpenClipboard()"
			)
		MockClient.return_value.chat.assert_not_called()
		assert result.verdict == Verdict.NEEDS_FIX

	def test_mesmo_import_nao_reprovado_com_marcador_controller_client(
		self, fake_api_key, valid_critic_json_approved
	):
		"""Com o contexto marcado como controller_client, o guard de imports
		proibidos do addonHandler nao se aplica -- o programa roda fora
		desse sandbox -- entao o guard nao deve bloquear aqui, e o fluxo
		normal (chamada ao LLM) deve prosseguir."""
		with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
			MockClient.return_value.chat.return_value = _mock_resp(valid_critic_json_approved)
			critic = Critic()
			result = critic.evaluate_two_stage(
				"code_generation",
				"import ctypes\nimport win32clipboard\nclientLib = ctypes.windll.LoadLibrary('x.dll')",
				context=project_type_marker(),
			)
		MockClient.return_value.chat.assert_called()
		assert result.verdict == Verdict.APPROVED


class TestAddendumInjetadoNoSystemPrompt:
	def test_addendum_presente_quando_contexto_marcado(
		self, fake_api_key, valid_critic_json_approved
	):
		with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
			MockClient.return_value.chat.return_value = _mock_resp(valid_critic_json_approved)
			critic = Critic()
			critic.evaluate_two_stage(
				"code_generation", "import ctypes",
				context=project_type_marker(),
			)
		full_prompt_enviado = MockClient.return_value.chat.call_args_list[0][0][0]
		assert "CTRL-CLIENT-001" in full_prompt_enviado
		assert "nvdaController_testIfRunning" in full_prompt_enviado

	def test_addendum_ausente_sem_marcador(
		self, fake_api_key, valid_critic_json_approved
	):
		with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
			MockClient.return_value.chat.return_value = _mock_resp(valid_critic_json_approved)
			critic = Critic()
			critic.evaluate_two_stage("code_generation", "codigo valido de addon")
		full_prompt_enviado = MockClient.return_value.chat.call_args_list[0][0][0]
		assert "CTRL-CLIENT-001" not in full_prompt_enviado
