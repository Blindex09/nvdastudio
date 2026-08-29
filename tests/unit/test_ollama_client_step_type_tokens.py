from unittest.mock import MagicMock, patch

import nvdastudio.ai.ollama_client as ollama_client_mod
from nvdastudio.ai.ollama_client import OllamaClient


def _fake_streaming_httpx(lines):
	fake_stream_ctx = MagicMock()
	fake_stream_ctx.__enter__.return_value = fake_stream_ctx
	fake_stream_ctx.__exit__.return_value = False
	fake_stream_ctx.raise_for_status.return_value = None
	fake_stream_ctx.iter_lines.return_value = lines

	fake_client_instance = MagicMock()
	fake_client_instance.__enter__.return_value = fake_client_instance
	fake_client_instance.__exit__.return_value = False
	fake_client_instance.stream.return_value = fake_stream_ctx

	fake_httpx = MagicMock()
	fake_httpx.Client.return_value = fake_client_instance
	return fake_httpx


def _make_client():
	return OllamaClient(api_key="secret", model_id="kimi-k2.7-code")


def _chat_and_get_payload(step_type: str = "") -> dict:
	lines = ['{"message":{"content":"ok"}}', '{"done":true}']
	fake_httpx = _fake_streaming_httpx(lines)
	with patch.object(ollama_client_mod, "_httpx", fake_httpx):
		client = _make_client()
		kwargs = {"on_chunk": lambda _: None}
		if step_type:
			kwargs["step_type"] = step_type
		client.chat("gere o codigo", **kwargs)
	return fake_httpx.Client.return_value.stream.call_args.kwargs["json"]


class TestNumPredictPorStepType:
	def test_step_type_vazio_usa_teto_default(self):
		payload = _chat_and_get_payload("")
		assert payload["options"]["num_predict"] == ollama_client_mod._MAX_TOKENS_DEFAULT

	def test_code_generation_usa_teto_estendido(self):
		payload = _chat_and_get_payload("code_generation")
		assert payload["options"]["num_predict"] == ollama_client_mod._MAX_TOKENS_EXTENDED

	def test_agent_runner_usa_teto_estendido(self):
		payload = _chat_and_get_payload("agent_runner")
		assert payload["options"]["num_predict"] == ollama_client_mod._MAX_TOKENS_EXTENDED

	def test_assembly_usa_teto_estendido(self):
		"""2.19.0: bug real do golden eval set (test_e36) -- assembly
		consolida TODOS os steps aprovados, contexto grande o bastante pra
		estourar o teto padrao num addon complexo real (confirmado ao vivo:
		"Critic: resposta cortada pelo teto de tokens (step_type=assembly)")."""
		payload = _chat_and_get_payload("assembly")
		assert payload["options"]["num_predict"] == ollama_client_mod._MAX_TOKENS_EXTENDED

	def test_step_type_nao_estendido_usa_teto_default(self):
		payload = _chat_and_get_payload("web_research")
		assert payload["options"]["num_predict"] == ollama_client_mod._MAX_TOKENS_DEFAULT


class TestChamadoresReaisPropagamStepType:
	"""code_generator.py e _base.py._run_sub_agent() sao os 2 caminhos reais
	que chegam em client.chat() -- confirma que nenhum deles regrediu pro
	bug de "step_type nunca passado" (achado original desta auditoria)."""

	def test_code_generator_passa_step_type_code_generation(self):
		import ast
		import inspect
		from nvdastudio.sub_agents import code_generator

		src = inspect.getsource(code_generator)
		tree = ast.parse(src)
		chat_calls = [
			node for node in ast.walk(tree)
			if isinstance(node, ast.Call)
			and isinstance(node.func, ast.Attribute)
			and node.func.attr == "chat"
		]
		assert len(chat_calls) >= 3, "esperado 3 call sites de .chat() em code_generator.py"
		for call in chat_calls:
			kw_names = {kw.arg for kw in call.keywords}
			assert "step_type" in kw_names, (
				f"chamada .chat() na linha {call.lineno} nao passa step_type"
			)

	def test_run_sub_agent_aceita_step_type_e_repassa_pro_chat(self):
		import inspect
		from nvdastudio.sub_agents._base import _run_sub_agent

		sig = inspect.signature(_run_sub_agent)
		assert "step_type" in sig.parameters
		assert sig.parameters["step_type"].default == ""

		fake_client = MagicMock()
		fake_resp = MagicMock(content="ok", tokens_used=10, tool_calls=None)
		fake_client.chat.return_value = fake_resp
		import nvdastudio.sub_agents._base as base_mod
		with patch.object(base_mod, "create_llm_client", return_value=fake_client), \
			patch.object(base_mod, "_get_cached_client", return_value=None), \
			patch.object(base_mod, "_cache_client"):
			_run_sub_agent(
				"system", "prompt", "kimi-k2.7-code", {},
				step_type="agent_runner",
			)
		assert fake_client.chat.call_args.kwargs["step_type"] == "agent_runner"

	def test_run_sub_agent_sem_step_type_nao_quebra_e_nao_passa_kwarg(self):
		"""Compatibilidade: chamadores que nao passam step_type (a maioria)
		continuam funcionando exatamente como antes -- kwarg simplesmente
		nao vai no chat_kwargs."""
		from nvdastudio.sub_agents._base import _run_sub_agent

		fake_client = MagicMock()
		fake_resp = MagicMock(content="ok", tokens_used=10, tool_calls=None)
		fake_client.chat.return_value = fake_resp
		import nvdastudio.sub_agents._base as base_mod
		with patch.object(base_mod, "create_llm_client", return_value=fake_client), \
			patch.object(base_mod, "_get_cached_client", return_value=None), \
			patch.object(base_mod, "_cache_client"):
			_run_sub_agent("system", "prompt", "kimi-k2.7-code", {})
		assert "step_type" not in fake_client.chat.call_args.kwargs


class TestThinkLevelParaGptOss:
	"""Achado de auditoria full-stack 2026-08-04 (docs.ollama.com/capabilities/
	thinking): GPT-OSS e a excecao documentada -- booleano true/false no
	campo think e IGNORADO pelo modelo, so aceita string de nivel
	("low"/"medium"/"high"). payload["think"]=True nunca ativava thinking de
	verdade nesse modelo. gpt-oss:20b tambem nao tinha entrada em
	_MODEL_CAPABILITIES (herdava capabilities erradas do fallback Kimi)."""

	@staticmethod
	def _chat_and_get_payload(model_id: str, reasoning_effort: str):
		lines = ['{"message":{"content":"ok"}}', '{"done":true}']
		fake_httpx = _fake_streaming_httpx(lines)
		with patch.object(ollama_client_mod, "_httpx", fake_httpx):
			client = OllamaClient(api_key="secret", model_id=model_id)
			client.chat(
				"gere o codigo", on_chunk=lambda _: None,
				reasoning_effort=reasoning_effort,
			)
		return fake_httpx.Client.return_value.stream.call_args.kwargs["json"]

	def test_gpt_oss_recebe_string_de_nivel_nao_booleano(self):
		payload = self._chat_and_get_payload("gpt-oss:20b", "high")
		assert payload["think"] == "high"

	def test_kimi_continua_recebendo_booleano(self):
		payload = self._chat_and_get_payload("kimi-k2.7-code", "high")
		assert payload["think"] is True

	def test_gpt_oss_tem_entrada_propria_em_model_capabilities(self):
		caps = ollama_client_mod._MODEL_CAPABILITIES["gpt-oss:20b"]
		assert caps["thinking_effort"] is True
		assert caps["thinking_native"] is True


class TestTruncatedDetection:
	"""Achado CRITICO de auditoria full-stack 2026-08-04: resp.truncated
	(llm_client.py 1.1.0) setado a partir de done_reason=="length" (API
	nativa /api/chat) -- ver sub_agents/code_generator.py 3.28.0 pro consumo."""

	def test_done_reason_length_marca_truncated_non_streaming(self):
		fake_client_instance = MagicMock()
		fake_client_instance.__enter__.return_value = fake_client_instance
		fake_client_instance.__exit__.return_value = False
		fake_response = MagicMock()
		fake_response.raise_for_status.return_value = None
		fake_response.json.return_value = {
			"message": {"content": "codigo cortado"},
			"done_reason": "length",
			"prompt_eval_count": 10, "eval_count": 5,
		}
		fake_client_instance.post.return_value = fake_response
		fake_httpx = MagicMock()
		fake_httpx.Client.return_value = fake_client_instance
		with patch.object(ollama_client_mod, "_httpx", fake_httpx):
			client = OllamaClient(api_key="secret", model_id="kimi-k2.7-code")
			resp = client.chat("gere o codigo")
		assert resp.truncated is True

	def test_done_reason_stop_nao_marca_truncated_non_streaming(self):
		fake_client_instance = MagicMock()
		fake_client_instance.__enter__.return_value = fake_client_instance
		fake_client_instance.__exit__.return_value = False
		fake_response = MagicMock()
		fake_response.raise_for_status.return_value = None
		fake_response.json.return_value = {
			"message": {"content": "codigo completo"},
			"done_reason": "stop",
			"prompt_eval_count": 10, "eval_count": 5,
		}
		fake_client_instance.post.return_value = fake_response
		fake_httpx = MagicMock()
		fake_httpx.Client.return_value = fake_client_instance
		with patch.object(ollama_client_mod, "_httpx", fake_httpx):
			client = OllamaClient(api_key="secret", model_id="kimi-k2.7-code")
			resp = client.chat("gere o codigo")
		assert resp.truncated is False

	def test_done_reason_length_marca_truncated_streaming(self):
		lines = [
			'{"message":{"content":"codigo cortado"}}',
			'{"done":true,"done_reason":"length","prompt_eval_count":10,"eval_count":5}',
		]
		fake_httpx = _fake_streaming_httpx(lines)
		with patch.object(ollama_client_mod, "_httpx", fake_httpx):
			client = OllamaClient(api_key="secret", model_id="kimi-k2.7-code")
			resp = client.chat("gere o codigo", on_chunk=lambda _: None)
		assert resp.truncated is True

	def test_done_reason_stop_nao_marca_truncated_streaming(self):
		lines = [
			'{"message":{"content":"codigo completo"}}',
			'{"done":true,"done_reason":"stop","prompt_eval_count":10,"eval_count":5}',
		]
		fake_httpx = _fake_streaming_httpx(lines)
		with patch.object(ollama_client_mod, "_httpx", fake_httpx):
			client = OllamaClient(api_key="secret", model_id="kimi-k2.7-code")
			resp = client.chat("gere o codigo", on_chunk=lambda _: None)
		assert resp.truncated is False


class TestTemperaturePorStepType:
	"""2.21.0: achado real do golden eval set (test_e36) -- web_research
	devolvia repetidamente ```python:arquivo.py``` em vez de pesquisa, com
	DOIS modelos diferentes (deepseek-v4-flash e kimi-k2.7-code apos
	escalonamento). Ollama Cloud nao suporta tool_choice forcado nem
	structured output real (docs.ollama.com/capabilities/structured-outputs:
	"Ollama's Cloud currently does not support structured outputs") -- a
	unica alavanca documentada pra reduzir drift de formato e temperature
	baixa. web_research saiu da lista "criativa" (0.3) pra precisa (0.0)."""

	def test_web_research_usa_temperature_precisa(self):
		payload = _chat_and_get_payload("web_research")
		assert payload["options"]["temperature"] == ollama_client_mod._TEMPERATURE_PRECISE

	def test_code_generation_continua_temperature_criativa(self):
		"""Nao regride: code_generation permanece criativo de proposito."""
		payload = _chat_and_get_payload("code_generation")
		assert payload["options"]["temperature"] == ollama_client_mod._TEMPERATURE_CREATIVE

	def test_documentation_continua_temperature_criativa(self):
		payload = _chat_and_get_payload("documentation")
		assert payload["options"]["temperature"] == ollama_client_mod._TEMPERATURE_CREATIVE
