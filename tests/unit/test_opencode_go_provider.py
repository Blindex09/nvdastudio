from unittest.mock import MagicMock, patch

import pytest


class TestOpenCodeGoClientPayload:
	def _fake_httpx_non_stream(self, response_json):
		fake_resp = MagicMock()
		fake_resp.raise_for_status.return_value = None
		fake_resp.json.return_value = response_json
		fake_client_instance = MagicMock()
		fake_client_instance.__enter__.return_value = fake_client_instance
		fake_client_instance.__exit__.return_value = False
		fake_client_instance.post.return_value = fake_resp
		fake_httpx = MagicMock()
		fake_httpx.Client.return_value = fake_client_instance
		return fake_httpx

	def test_chat_envia_model_id_nu_sem_prefixo(self):
		import nvdastudio.ai.opencode_go_client as mod
		fake_httpx = self._fake_httpx_non_stream({
			"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
			"usage": {"total_tokens": 42},
		})
		with patch.object(mod, "_httpx", fake_httpx):
			client = mod.OpenCodeGoClient(api_key="sk-test", model_id="kimi-k2.6")
			resp = client.chat("pesquisa sobre X", system_override="voce e pesquisador")
		payload = fake_httpx.Client.return_value.post.call_args.kwargs["json"]
		assert payload["model"] == "kimi-k2.6"
		assert resp.content == "ok"
		assert resp.tokens_used == 42

	def test_chat_repassa_response_format_no_payload(self):
		"""
		1.1.0: response_format era aceito como parametro mas nunca entrava
		no payload enviado -- achado real de auditoria 2026-08-26 (Critic
		chama com response_format=json_object esperando que isso va pra
		API; nunca ia). Confirmado ao vivo que o endpoint aceita
		response_format normalmente (compativel com OpenAI).
		"""
		import nvdastudio.ai.opencode_go_client as mod
		fake_httpx = self._fake_httpx_non_stream({
			"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
			"usage": {},
		})
		response_format = {"type": "json_object"}
		with patch.object(mod, "_httpx", fake_httpx):
			client = mod.OpenCodeGoClient(api_key="sk-test", model_id="kimi-k2.6")
			client.chat("pergunta", response_format=response_format)
		payload = fake_httpx.Client.return_value.post.call_args.kwargs["json"]
		assert payload["response_format"] == response_format

	def test_chat_sem_response_format_nao_inclui_chave_no_payload(self):
		import nvdastudio.ai.opencode_go_client as mod
		fake_httpx = self._fake_httpx_non_stream({
			"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
			"usage": {},
		})
		with patch.object(mod, "_httpx", fake_httpx):
			client = mod.OpenCodeGoClient(api_key="sk-test")
			client.chat("pergunta")
		payload = fake_httpx.Client.return_value.post.call_args.kwargs["json"]
		assert "response_format" not in payload

	def test_chat_inclui_system_override_nas_messages(self):
		import nvdastudio.ai.opencode_go_client as mod
		fake_httpx = self._fake_httpx_non_stream({
			"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
			"usage": {},
		})
		with patch.object(mod, "_httpx", fake_httpx):
			client = mod.OpenCodeGoClient(api_key="sk-test", model_id="kimi-k2.6")
			client.chat("pergunta", system_override="regra do sistema")
		payload = fake_httpx.Client.return_value.post.call_args.kwargs["json"]
		roles = [m["role"] for m in payload["messages"]]
		assert roles[0] == "system"
		assert payload["messages"][0]["content"] == "regra do sistema"

	def test_finish_reason_length_marca_truncated(self):
		import nvdastudio.ai.opencode_go_client as mod
		fake_httpx = self._fake_httpx_non_stream({
			"choices": [{"message": {"content": "cortado"}, "finish_reason": "length"}],
			"usage": {"total_tokens": 10},
		})
		with patch.object(mod, "_httpx", fake_httpx):
			client = mod.OpenCodeGoClient(api_key="sk-test", model_id="kimi-k2.6")
			resp = client.chat("pergunta")
		assert resp.truncated is True

	def test_api_key_vazia_levanta_erro(self):
		import nvdastudio.ai.opencode_go_client as mod
		with pytest.raises(mod.OpenCodeGoClientError):
			mod.OpenCodeGoClient(api_key="")

	def test_tool_calls_repassados_no_response(self):
		import nvdastudio.ai.opencode_go_client as mod
		tool_calls = [{"id": "call_1", "type": "function",
					   "function": {"name": "entregar", "arguments": '{"resposta":"x"}'}}]
		fake_httpx = self._fake_httpx_non_stream({
			"choices": [{"message": {"content": "", "tool_calls": tool_calls}, "finish_reason": "tool_calls"}],
			"usage": {},
		})
		with patch.object(mod, "_httpx", fake_httpx):
			client = mod.OpenCodeGoClient(api_key="sk-test", model_id="kimi-k2.6")
			resp = client.chat("pergunta", tools=[{"type": "function", "function": {"name": "entregar"}}])
		assert resp.tool_calls == tool_calls


class TestLlmFactoryRoteiaOpenCodeGo:
	def test_create_llm_client_opencode_go_sem_chave_levanta_erro(self):
		from nvdastudio.ai.llm_factory import create_llm_client, LLMFactoryError
		with patch("nvdastudio.gui.settings_panel.get_api_key", return_value=""):
			with pytest.raises(LLMFactoryError):
				create_llm_client(model_id="gpt-5.6-luna", provider="opencode_go")

	def test_create_llm_client_opencode_go_com_chave_retorna_client(self):
		from nvdastudio.ai.llm_factory import create_llm_client
		from nvdastudio.ai.opencode_go_client import OpenCodeGoClient
		with patch("nvdastudio.gui.settings_panel.get_api_key", return_value="sk-test"):
			client = create_llm_client(model_id="gpt-5.6-luna", provider="opencode_go")
		assert isinstance(client, OpenCodeGoClient)

	def test_model_id_com_prefixo_provider_forca_esse_provider(self):
		"""5.2.0: convencao "<provider>::<model_id>" -- usada pela escalacao
		cross-provider (ai/model_router.py::select_model_and_provider())
		pra rotear um step especifico sem mudar a assinatura de nenhum
		sub-agente. Ignora tanto o parametro provider= quanto
		get_llm_provider() quando o model_id vem com o prefixo."""
		from nvdastudio.ai.llm_factory import create_llm_client
		from nvdastudio.ai.opencode_go_client import OpenCodeGoClient
		with patch("nvdastudio.gui.settings_panel.get_api_key", return_value="sk-test"), \
			patch("nvdastudio.gui.settings_panel.get_llm_provider", return_value="ollama"):
			client = create_llm_client(model_id="opencode_go::gpt-5.6-luna")
		assert isinstance(client, OpenCodeGoClient)
		assert client.current_model_id == "gpt-5.6-luna"


class TestModelRegistryOpenCodeGoSemColisao:
	def test_gpt_5_6_luna_openai_nao_foi_sobrescrito(self):
		"""O model_id 'gpt-5.6-luna' ja existia pro provider 'openai' --
		a entrada nova do OpenCode Go usa chave de registry namespaced
		('opencode-go/gpt-5.6-luna') pra nao colidir e sobrescrever essa."""
		from nvdastudio.ai.model_registry import registry
		info = registry.get_model_info("gpt-5.6-luna")
		assert info is not None
		assert info.provider == "openai"

	def test_opencode_go_entry_tem_provider_correto(self):
		from nvdastudio.ai.model_registry import registry
		info = registry.get_model_info("opencode-go/gpt-5.6-luna")
		assert info is not None
		assert info.provider == "opencode_go"
		assert info.model_id == "gpt-5.6-luna"

	def test_opencode_go_aparece_na_ui(self):
		from nvdastudio.ai.model_registry import registry
		modelos = registry.get_active_models_for_ui_provider("opencode_go")
		assert any(m.model_id == "gpt-5.6-luna" for m in modelos)


class TestSelectModelAndProvider:
	"""ai/model_router.py 1.1.0: escalacao cross-provider real -- pontua
	candidatos de TODOS os providers com chave configurada."""

	def test_sem_nenhum_provider_com_chave_retorna_none(self):
		from nvdastudio.ai.model_router import select_model_and_provider
		with patch("nvdastudio.gui.settings_panel.get_api_key", return_value=""):
			result = select_model_and_provider("web_research", "medium", exclude_provider="ollama")
		assert result is None

	def test_exclude_provider_nunca_aparece_no_resultado(self):
		"""Mesmo com chave configurada, o provider excluido (ja tentado e
		falhou) nunca deve ser retornado -- so os OUTROS providers."""
		from nvdastudio.ai.model_router import select_model_and_provider
		with patch("nvdastudio.gui.settings_panel.get_api_key",
				   side_effect=lambda p: "sk-test" if p == "opencode_go" else ""):
			result = select_model_and_provider("web_research", "medium", exclude_provider="ollama")
		assert result is not None
		provider, model_id = result
		assert provider == "opencode_go"
		assert model_id == "gpt-5.6-luna"

	def test_so_o_proprio_provider_ativo_com_chave_retorna_none(self):
		"""Se so o provider ja excluido tem chave, nao ha candidato --
		fail-open, comportamento identico a antes deste mecanismo existir."""
		from nvdastudio.ai.model_router import select_model_and_provider
		with patch("nvdastudio.gui.settings_panel.get_api_key",
				   side_effect=lambda p: "sk-test" if p == "ollama" else ""):
			result = select_model_and_provider("web_research", "medium", exclude_provider="ollama")
		assert result is None


class TestOrchestratorCrossProviderRescue:
	"""orchestrator.py 5.37.0: _try_web_research_cross_provider_rescue()
	(especifico do OpenCode Go pro web_research) generalizado pra
	_try_cross_provider_rescue() -- qualquer step_type em
	_ESCALATION_ELIGIBLE_STEP_TYPES, qualquer provider com chave
	configurada (via ai/model_router.py::select_model_and_provider())."""

	def _make_orch(self, fake_api_key):
		from nvdastudio.core.orchestrator import Orchestrator
		orch = Orchestrator()
		orch._api_key = fake_api_key
		orch.initialize()
		return orch

	def test_sem_outro_provider_configurado_retorna_none(self, fake_api_key):
		from nvdastudio.core.planner import ExecutionStep, STEP_WEB_RESEARCH
		orch = self._make_orch(fake_api_key)
		step = ExecutionStep(step_id="s1", step_type=STEP_WEB_RESEARCH,
							  description="pesquisar X", model_id="kimi-k2.7-code")
		with patch("nvdastudio.ai.model_router.select_model_and_provider", return_value=None):
			result = orch._try_cross_provider_rescue(step, "prompt", "")
		assert result is None

	def test_step_type_nao_elegivel_retorna_none(self, fake_api_key):
		"""manifest_builder nao esta em _ESCALATION_ELIGIBLE_STEP_TYPES --
		retorna None SEM sequer consultar select_model_and_provider."""
		from nvdastudio.core.planner import ExecutionStep
		orch = self._make_orch(fake_api_key)
		step = ExecutionStep(step_id="s1", step_type="manifest_builder",
							  description="gerar manifest", model_id="kimi-k2.7-code")
		with patch("nvdastudio.ai.model_router.select_model_and_provider") as mock_select:
			result = orch._try_cross_provider_rescue(step, "prompt", "")
		assert result is None
		mock_select.assert_not_called()

	def test_rescue_bem_sucedido_retorna_step_result_aprovado(self, fake_api_key):
		from nvdastudio.core.planner import ExecutionStep, STEP_WEB_RESEARCH
		from nvdastudio.ai.critic import CriticResult, Verdict
		orch = self._make_orch(fake_api_key)
		step = ExecutionStep(step_id="s1", step_type=STEP_WEB_RESEARCH,
							  description="pesquisar X", model_id="kimi-k2.7-code")
		aprovado = CriticResult(verdict=Verdict.APPROVED, score=90, issues=[], fix_instructions="")
		with patch("nvdastudio.ai.model_router.select_model_and_provider",
				   return_value=("opencode_go", "gpt-5.6-luna")), \
			patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens",
				  return_value=("**Pacote:** google-genai\n...", 123)) as mock_dispatch, \
			patch.object(orch._critic, "evaluate_two_stage", return_value=aprovado):
			result = orch._try_cross_provider_rescue(step, "prompt", "")
		assert result is not None
		assert result.approved is True
		assert result.model_used == "opencode_go/gpt-5.6-luna"
		assert result.tokens_used == 123
		assert mock_dispatch.call_args.kwargs["model_id"] == "opencode_go::gpt-5.6-luna"

	def test_rescue_funciona_pra_agent_runner_tambem(self, fake_api_key):
		"""Nao e mais especifico de web_research -- qualquer step_type
		elegivel a escalacao pode ser resgatado cross-provider."""
		from nvdastudio.core.planner import ExecutionStep
		from nvdastudio.ai.critic import CriticResult, Verdict
		orch = self._make_orch(fake_api_key)
		step = ExecutionStep(step_id="s1", step_type="agent_runner",
							  description="gerar agent", model_id="kimi-k2.7-code")
		aprovado = CriticResult(verdict=Verdict.APPROVED, score=90, issues=[], fix_instructions="")
		with patch("nvdastudio.ai.model_router.select_model_and_provider",
				   return_value=("openai", "gpt-5.6-sol")), \
			patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens",
				  return_value=("codigo gerado", 50)), \
			patch.object(orch._critic, "evaluate_two_stage", return_value=aprovado):
			result = orch._try_cross_provider_rescue(step, "prompt", "")
		assert result is not None
		assert result.model_used == "openai/gpt-5.6-sol"

	def test_rescue_que_tambem_falha_retorna_none(self, fake_api_key):
		from nvdastudio.core.planner import ExecutionStep, STEP_WEB_RESEARCH
		from nvdastudio.ai.critic import CriticResult, Verdict
		orch = self._make_orch(fake_api_key)
		step = ExecutionStep(step_id="s1", step_type=STEP_WEB_RESEARCH,
							  description="pesquisar X", model_id="kimi-k2.7-code")
		rejeitado = CriticResult(verdict=Verdict.NEEDS_FIX, score=0, issues=["ainda errado"], fix_instructions="")
		with patch("nvdastudio.ai.model_router.select_model_and_provider",
				   return_value=("opencode_go", "gpt-5.6-luna")), \
			patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens",
				  return_value=("```python:x.py\ncode\n```", 10)), \
			patch.object(orch._critic, "evaluate_two_stage", return_value=rejeitado):
			result = orch._try_cross_provider_rescue(step, "prompt", "")
		assert result is None

	def test_rescue_com_excecao_nao_propaga(self, fake_api_key):
		from nvdastudio.core.planner import ExecutionStep, STEP_WEB_RESEARCH
		orch = self._make_orch(fake_api_key)
		step = ExecutionStep(step_id="s1", step_type=STEP_WEB_RESEARCH,
							  description="pesquisar X", model_id="kimi-k2.7-code")
		with patch("nvdastudio.ai.model_router.select_model_and_provider",
				   return_value=("opencode_go", "gpt-5.6-luna")), \
			patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens",
				  side_effect=RuntimeError("boom")):
			result = orch._try_cross_provider_rescue(step, "prompt", "")
		assert result is None

	def test_exclui_o_provider_ja_tentado(self, fake_api_key):
		"""select_model_and_provider() deve ser chamado com exclude_provider
		igual ao provider ativo -- nao faz sentido re-pontuar candidatos do
		mesmo provider que ja falhou."""
		from nvdastudio.core.planner import ExecutionStep, STEP_WEB_RESEARCH
		orch = self._make_orch(fake_api_key)
		step = ExecutionStep(step_id="s1", step_type=STEP_WEB_RESEARCH,
							  description="pesquisar X", model_id="kimi-k2.7-code")
		with patch("nvdastudio.gui.settings_panel.get_llm_provider", return_value="ollama"), \
			patch("nvdastudio.ai.model_router.select_model_and_provider", return_value=None) as mock_select:
			orch._try_cross_provider_rescue(step, "prompt", "")
		assert mock_select.call_args.kwargs["exclude_provider"] == "ollama"

	def test_passa_active_provider_para_o_router(self, fake_api_key):
		"""5.48.0: achado real ao vivo (test_e36, GeminiMultimodal) -- o
		resgate escalou pra OpenAI direto so porque a chave estava presente
		no ambiente, mesmo com Ollama configurado como provider principal e
		sem credito real na OpenAI. active_provider precisa chegar ate
		select_model_and_provider() pra ele saber restringir o resgate."""
		from nvdastudio.core.planner import ExecutionStep, STEP_WEB_RESEARCH
		orch = self._make_orch(fake_api_key)
		step = ExecutionStep(step_id="s1", step_type=STEP_WEB_RESEARCH,
							  description="pesquisar X", model_id="kimi-k2.7-code")
		with patch("nvdastudio.gui.settings_panel.get_llm_provider", return_value="ollama"), \
			patch("nvdastudio.ai.model_router.select_model_and_provider", return_value=None) as mock_select:
			orch._try_cross_provider_rescue(step, "prompt", "")
		assert mock_select.call_args.kwargs["active_provider"] == "ollama"


class TestOllamaRescueRestritoAOpenCodeGo:
	"""
	model_router.py 1.2.0: achado real ao vivo (test_e36, GeminiMultimodal,
	2026-08-09) -- o resgate cross-provider escalou pra OpenAI direto so
	porque OPENAI_API_KEY estava presente no ambiente, mesmo sem saldo
	real la, quando o provider ATIVO configurado era "ollama". Intencao
	real de arquitetura (Felipe): quando Ollama e o provider principal, o
	UNICO fallback seguro e OpenCode Go (assinatura fixa, ja paga) --
	nunca os provedores pagos por token sem credito configurado.
	"""

	def test_ollama_ativo_com_openai_e_opencode_go_disponiveis_so_considera_opencode_go(self, fake_api_key):
		from nvdastudio.ai.model_router import select_model_and_provider
		with patch("nvdastudio.gui.settings_panel.get_api_key",
				   side_effect=lambda p: "sk-test" if p in ("openai", "opencode_go") else ""):
			result = select_model_and_provider(
				"web_research", "medium", exclude_provider="ollama", active_provider="ollama",
			)
		assert result is not None
		provider, _model_id = result
		assert provider == "opencode_go", (
			f"esperado opencode_go (unico fallback pago quando ollama e o "
			f"provider ativo), recebido {provider} -- rescue nao deveria "
			f"nunca escalar pra provedor pago direto so porque a chave "
			f"esta no ambiente, sem credito real garantido"
		)

	def test_ollama_ativo_sem_opencode_go_retorna_none_mesmo_com_openai_disponivel(self, fake_api_key):
		"""Fail-safe: se o unico fallback seguro (opencode_go) nao tem
		chave, NAO cai pra OpenAI so porque a chave dele existe -- melhor
		nao resgatar do que gastar credito que o usuario nao tem."""
		from nvdastudio.ai.model_router import select_model_and_provider
		with patch("nvdastudio.gui.settings_panel.get_api_key",
				   side_effect=lambda p: "sk-test" if p == "openai" else ""):
			result = select_model_and_provider(
				"web_research", "medium", exclude_provider="ollama", active_provider="ollama",
			)
		assert result is None

	def test_provider_ativo_nao_ollama_mantem_todos_os_providers_elegiveis(self, fake_api_key):
		"""Fora do caso Ollama, comportamento antigo preservado -- usuario
		que escolheu openai/gemini/anthropic/xai como principal
		presumivelmente tem credito la, entao o resgate pode considerar
		qualquer outro provider com chave configurada."""
		from nvdastudio.ai.model_router import select_model_and_provider
		with patch("nvdastudio.gui.settings_panel.get_api_key",
				   side_effect=lambda p: "sk-test" if p == "gemini" else ""):
			result = select_model_and_provider(
				"web_research", "medium", exclude_provider="openai", active_provider="openai",
			)
		assert result is not None
		provider, _model_id = result
		assert provider == "gemini"

	def test_active_provider_none_mantem_comportamento_antigo(self, fake_api_key):
		"""Sem active_provider informado (default None), nunca restringe --
		retrocompatibilidade com qualquer chamador que ainda nao passa o
		parametro novo."""
		from nvdastudio.ai.model_router import select_model_and_provider
		with patch("nvdastudio.gui.settings_panel.get_api_key",
				   side_effect=lambda p: "sk-test" if p == "opencode_go" else ""):
			result = select_model_and_provider("web_research", "medium", exclude_provider="ollama")
		assert result is not None
		assert result[0] == "opencode_go"
