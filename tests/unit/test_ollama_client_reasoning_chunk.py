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


class TestStreamAindaAcumulaThinkingParaLLMResponse:
	def test_thinking_e_content_acumulados_corretamente(self):
		lines = [
			'{"message":{"thinking":"avaliando a arquitetura","content":""}}',
			'{"message":{"thinking":"","content":"{\\"ok\\":true}"}}',
			'{"done":true,"prompt_eval_count":10,"eval_count":5}',
		]
		fake_httpx = _fake_streaming_httpx(lines)
		content_seen = []
		with patch.object(ollama_client_mod, "_httpx", fake_httpx):
			client = _make_client()
			resp = client.chat(
				"crie um plano",
				on_chunk=content_seen.append,
				reasoning_effort="high",
			)
		assert content_seen == ['{"ok":true}']
		assert resp.content == '{"ok":true}'
		assert resp.reasoning == "avaliando a arquitetura"

	def test_on_reasoning_chunk_removido(self):
		"""v2.13.0: on_reasoning_chunk e include_reasoning removidos --
		chat() nao aceita mais esses kwargs."""
		import inspect
		sig = inspect.signature(OllamaClient.chat)
		assert "on_reasoning_chunk" not in sig.parameters
		assert "include_reasoning" not in sig.parameters


class TestStreamComToolsAtivo:
	"""v2.12.0: streaming passa a funcionar com tools ativo (antes desligava
	streaming por completo se `tools` estivesse presente). Confirmado por
	pesquisa dedicada: content narra antes, tool_calls chega consolidado
	num chunk proprio (nao fragmentado) -- fonte: ollama.com/blog/streaming-tool."""

	def test_narra_conteudo_e_monta_tool_call_no_mesmo_stream(self):
		lines = [
			'{"message":{"content":"Vou verificar o pacote antes.","tool_calls":[]}}',
			'{"message":{"content":"","tool_calls":[{"function":{"name":"validate_import","arguments":{"module_name":"requests"}}}]}}',
			'{"done":true,"prompt_eval_count":8,"eval_count":4}',
		]
		fake_httpx = _fake_streaming_httpx(lines)
		narrated = []
		with patch.object(ollama_client_mod, "_httpx", fake_httpx):
			client = _make_client()
			resp = client.chat(
				"gere o codigo",
				on_chunk=narrated.append,
				tools=[{"type": "function", "function": {"name": "validate_import"}}],
			)
		assert narrated == ["Vou verificar o pacote antes."]
		assert resp.content == "Vou verificar o pacote antes."
		assert len(resp.tool_calls) == 1
		assert resp.tool_calls[0]["function"]["name"] == "validate_import"

	def test_tool_choice_none_omite_tools_do_payload(self):
		"""Causa raiz de "code_generator esgotou N rodadas de tool-calling sem
		resposta final" (2026-07-21): a API nativa /api/chat do Ollama nao tem
		tool_choice (confirmado via pesquisa dedicada em docs.ollama.com/api/chat
		-- so o shim /v1/chat/completions tem). Mitigacao: quando o chamador
		pede tool_choice="none" (ultima rodada do loop em code_generator.py),
		`tools` e omitido do payload por completo -- sem ferramentas
		oferecidas, o modelo so pode responder em texto."""
		lines = ['{"message":{"content":"codigo final aqui"}}', '{"done":true}']
		fake_httpx = _fake_streaming_httpx(lines)
		with patch.object(ollama_client_mod, "_httpx", fake_httpx):
			client = _make_client()
			client.chat(
				"gere o codigo",
				on_chunk=lambda _: None,
				tools=[{"type": "function", "function": {"name": "validate_import"}}],
				tool_choice="none",
			)
		sent_payload = fake_httpx.Client.return_value.stream.call_args.kwargs["json"]
		assert "tools" not in sent_payload

	def test_fallback_quando_modelo_so_manda_tool_calls_sem_narracao(self):
		"""issue ollama/ollama#12557: alguns modelos mandam so tool_calls,
		sem nenhum content antes -- nao deve quebrar, so nao narra nada."""
		lines = [
			'{"message":{"content":"","tool_calls":[{"function":{"name":"search_web","arguments":{"query":"x"}}}]}}',
			'{"done":true}',
		]
		fake_httpx = _fake_streaming_httpx(lines)
		narrated = []
		with patch.object(ollama_client_mod, "_httpx", fake_httpx):
			client = _make_client()
			resp = client.chat(
				"pesquise",
				on_chunk=narrated.append,
				tools=[{"type": "function", "function": {"name": "search_web"}}],
			)
		assert narrated == []
		assert resp.content == ""
		assert len(resp.tool_calls) == 1

	def test_tool_results_nao_duplica_mensagem_de_usuario_no_historico(self):
		lines = ['{"message":{"content":"ok","tool_calls":[]}}', '{"done":true}']
		fake_httpx = _fake_streaming_httpx(lines)
		with patch.object(ollama_client_mod, "_httpx", fake_httpx):
			client = _make_client()
			client.chat(
				"continuando",
				on_chunk=lambda _: None,
				tool_results=[{"tool_call_id": "1", "tool_name": "x", "content": "resultado"}],
			)
		user_entries = [h for h in client.history if h.get("role") == "user"]
		assert user_entries == []
