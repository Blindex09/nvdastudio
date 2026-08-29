from unittest.mock import MagicMock, patch

from nvdastudio.sub_agents.code_generator import run
from nvdastudio.builder.controller_client_context import (
	project_type_marker, CTRL_CLIENT_SYSTEM_PROMPT,
)
from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT


def _marked_prompt(body: str = "crie um programa que fala pelo NVDA de fora") -> str:
	return project_type_marker() + body


class TestRoteamentoSystemPrompt:
	def test_prompt_controller_client_usa_ctrl_client_system(self):
		resp = MagicMock()
		resp.content = "```python:nvda_client.py\nimport ctypes\n```"
		resp.tool_calls = []
		resp.tokens_used = 20
		resp.truncated = False

		captured = {}

		def fake_chat(prompt, **kwargs):
			captured.update(kwargs)
			return resp

		fake_client = MagicMock()
		fake_client.chat.side_effect = fake_chat

		with patch("nvdastudio.sub_agents.code_generator.create_llm_client", return_value=fake_client):
			run(_marked_prompt(), "kimi-k2.7-code", {})

		assert "nvdaController_testIfRunning" in captured["system_override"]
		assert captured["system_override"].startswith(CTRL_CLIENT_SYSTEM_PROMPT[:60])

	def test_prompt_normal_continua_usando_nvda_system(self):
		"""Regressao: sem o marcador, o roteamento antigo (addon) continua intacto."""
		resp = MagicMock()
		resp.content = "```python:globalPlugins/Foo/__init__.py\nimport globalPluginHandler\n```"
		resp.tool_calls = []
		resp.tokens_used = 20
		resp.truncated = False

		captured = {}

		def fake_chat(prompt, **kwargs):
			captured.update(kwargs)
			return resp

		fake_client = MagicMock()
		fake_client.chat.side_effect = fake_chat

		with patch("nvdastudio.sub_agents.code_generator.create_llm_client", return_value=fake_client):
			run("crie um addon simples", "kimi-k2.7-code", {})

		assert captured["system_override"].startswith(NVDA_SYSTEM_PROMPT[:60])
		assert "nvdaController_testIfRunning" not in captured["system_override"]

	def test_controller_client_nao_aciona_fase3_por_causa_de_nvda019(self):
		"""_verificar_codigo_gerado(skip_nvda019=True): codigo sem
		'# Translators:' antes de _() nao pode disparar a correcao de Fase 3
		(que faria uma SEGUNDA chamada LLM) -- essa convencao e do gettext
		do proprio NVDA, nao se aplica a um programa controller_client. Se
		Fase 3 fosse acionada, chat() seria chamado 2x; aqui deve ser 1x so."""
		codigo_sem_translators = (
			"```python:nvda_client.py\n"
			"import gettext\n"
			"_ = gettext.gettext\n"
			"print(_('ola'))\n"
			"```"
		)
		resp = MagicMock()
		resp.content = codigo_sem_translators
		resp.tool_calls = []
		resp.tokens_used = 20
		resp.truncated = False

		fake_client = MagicMock()
		fake_client.chat.return_value = resp

		with patch("nvdastudio.sub_agents.code_generator.create_llm_client", return_value=fake_client):
			resultado = run(_marked_prompt(), "kimi-k2.7-code", {})

		assert resultado == codigo_sem_translators
		assert fake_client.chat.call_count == 1
