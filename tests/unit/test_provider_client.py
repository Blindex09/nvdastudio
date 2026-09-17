import pytest

from nvdastudio.ai.provider_client import ProviderClient
from nvdastudio.ai.reliability import RETRYABLE_STATUS


def test_anthropic_overloaded_status_e_retentavel():
	"""v2.1.0: 529 ("overloaded_error") e o codigo especifico da Anthropic
	para sobrecarga do servidor -- documentado como retentavel, mas nao
	estava no set ate esta auditoria.

	2.15.0: RETRYABLE_STATUS mudou de provider_client.py pra
	ai/reliability.py (fonte unica compartilhada com os outros clientes)."""
	assert 529 in RETRYABLE_STATUS


def test_openai_native_uses_responses_api_structured_output_and_normalizes_tools(monkeypatch):
	"""v2.0.0: migrado de /v1/chat/completions (Chat Completions) para
	/v1/responses (Responses API) -- recomendacao oficial da OpenAI para
	projetos novos desde 2026. Tools passam a ser flat (sem aninhar em
	"function"); saida estruturada vira text.format; reasoning_effort vira
	reasoning.effort; mensagens viram "input" e system vira "instructions"."""
	client = ProviderClient("openai", "secret", "gpt-5.6-luna")
	captured = {}

	def fake_request(url, headers, payload):
		captured.update(url=url, headers=headers, payload=payload)
		return {
			"output": [{"type": "message", "content": [{"type": "output_text", "text": "{\"ok\":true}"}]}],
			"usage": {"total_tokens": 12},
		}

	monkeypatch.setattr(client, "_request", fake_request)
	response = client.chat(
		"teste",
		system_override="sistema estavel",
		tools=[{"type": "function", "function": {"name": "validar", "description": "v", "parameters": {"type": "object"}}}],
		response_format={"type": "json_schema", "json_schema": {"name": "x", "schema": {"type": "object"}}},
		reasoning_effort="low",
	)
	assert captured["url"].endswith("/v1/responses")
	assert captured["payload"]["instructions"] == "sistema estavel"
	assert captured["payload"]["input"][-1] == {"role": "user", "content": "teste"}
	assert captured["payload"]["tools"][0] == {
		"type": "function", "name": "validar", "description": "v", "parameters": {"type": "object"},
	}
	assert captured["payload"]["text"]["format"]["type"] == "json_schema"
	assert captured["payload"]["text"]["format"]["schema"] == {"type": "object"}
	assert captured["payload"]["reasoning"]["effort"] == "low"
	assert response.content == '{"ok":true}'
	assert response.tokens_used == 12


def test_anthropic_native_uses_prompt_cache_and_normalizes_tool_call(monkeypatch):
	client = ProviderClient("anthropic", "secret", "claude-haiku-4-5")
	captured = {}

	def fake_request(url, headers, payload):
		captured["payload"] = payload
		return {
			"content": [
				{"type": "text", "text": "pronto"},
				{"type": "tool_use", "id": "call-1", "name": "validar", "input": {"x": 1}},
			],
			"usage": {"input_tokens": 4, "output_tokens": 3},
		}

	monkeypatch.setattr(client, "_request", fake_request)
	response = client.chat(
		"teste",
		system_override="instrucao",
		tools=[{"type": "function", "function": {"name": "validar", "description": "v", "parameters": {"type": "object"}}}],
	)
	assert captured["payload"]["system"][0]["cache_control"]["ttl"] == "1h"
	assert captured["payload"]["tools"][-1]["cache_control"]["ttl"] == "1h"
	assert response.tool_calls[0]["function"]["arguments"] == {"x": 1}
	assert response.tokens_used == 7


def test_anthropic_forca_tool_choice_none_para_fechar_loop_de_tool_calling(monkeypatch):
	"""Causa raiz de "code_generator esgotou N rodadas de tool-calling sem
	resposta final" (2026-07-21): sem tool_choice, nada impede o modelo de
	pedir mais uma tool na ultima rodada permitida. Anthropic espera
	{"type": "none"} -- confirmado via pesquisa dedicada na Messages API."""
	client = ProviderClient("anthropic", "secret", "claude-haiku-4-5")
	captured = {}

	def fake_request(url, headers, payload):
		captured["payload"] = payload
		return {"content": [{"type": "text", "text": "pronto"}], "usage": {}}

	monkeypatch.setattr(client, "_request", fake_request)
	client.chat(
		"teste",
		tools=[{"type": "function", "function": {"name": "validar", "description": "v", "parameters": {"type": "object"}}}],
		tool_choice="none",
	)
	assert captured["payload"]["tool_choice"] == {"type": "none"}


def test_anthropic_native_uses_official_structured_output_field(monkeypatch):
	client = ProviderClient("anthropic", "secret", "claude-haiku-4-5")
	captured = {}

	def fake_request(url, headers, payload):
		captured["payload"] = payload
		return {"content": [{"type": "text", "text": '{"ok":true}'}], "usage": {}}

	monkeypatch.setattr(client, "_request", fake_request)
	client.chat(
		"teste",
		response_format={"type": "json_schema", "json_schema": {"schema": {"type": "object"}}},
	)
	assert captured["payload"]["output_config"]["format"]["type"] == "json_schema"
	assert captured["payload"]["output_config"]["format"]["schema"] == {"type": "object"}


def test_gemini_native_sends_interactions_api_json_schema_and_normalizes_function_call(monkeypatch):
	"""v2.0.0: migrado de generateContent (v1beta) para a Interactions API
	(v1, GA desde 2026-06). v2.12.0 (achado de teste E2E real ao vivo,
	2026-08-04): "input" NAO reaproveita o shape role/parts da API antiga --
	e so o conteudo NOVO (aqui, a string simples), confirmado via reproducao
	direta contra a API (HTTP 400 "Unknown parameter 'turns' at 'input'" no
	formato antigo). Resposta real usa steps[]/model_output/content[], nunca
	um campo "output_text" (que nunca existiu de verdade)."""
	client = ProviderClient("gemini", "secret", "gemini-3.5-flash")
	captured = {}

	def fake_request(url, headers, payload):
		captured.update(url=url, payload=payload)
		return {
			"steps": [
				{"type": "model_output", "content": [{"type": "text", "text": "{\"ok\":true}"}]},
				{"type": "function_call", "id": "g1", "name": "validar", "arguments": {"x": 2}},
			],
			"usage": {"total_tokens": 9},
		}

	monkeypatch.setattr(client, "_request", fake_request)
	response = client.chat(
		"teste",
		tools=[{"type": "function", "function": {"name": "validar", "description": "v", "parameters": {"type": "object"}}}],
		response_format={"type": "json_schema", "json_schema": {"schema": {"type": "object"}}},
	)
	assert captured["url"] == "https://generativelanguage.googleapis.com/v1/interactions"
	assert captured["payload"]["model"] == "gemini-3.5-flash"
	assert captured["payload"]["input"] == "teste"
	assert captured["payload"]["tools"][0] == {
		"type": "function", "name": "validar", "description": "v", "parameters": {"type": "object"},
	}
	assert captured["payload"]["response_format"][0]["schema"] == {"type": "object"}
	assert response.content == '{"ok":true}'
	assert response.tool_calls[0]["function"]["arguments"] == {"x": 2}
	assert response.tokens_used == 9


def test_gemini_forca_tool_choice_none_para_fechar_loop_de_tool_calling(monkeypatch):
	"""Mesma causa raiz do teste equivalente de Anthropic. Interactions API
	(GA 2026-06) espera tool_choice como string no nivel raiz do payload
	("auto"|"any"|"none"|"validated"), nao aninhado em generation_config --
	confirmado via pesquisa dedicada."""
	client = ProviderClient("gemini", "secret", "gemini-3.5-flash")
	captured = {}

	def fake_request(url, headers, payload):
		captured["payload"] = payload
		return {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "pronto"}]}], "usage": {}}

	monkeypatch.setattr(client, "_request", fake_request)
	client.chat(
		"teste",
		tools=[{"type": "function", "function": {"name": "validar", "description": "v", "parameters": {"type": "object"}}}],
		tool_choice="none",
	)
	assert captured["payload"]["tool_choice"] == "none"


def test_gemini_primeira_chamada_sem_interaction_id_manda_so_o_input_novo(monkeypatch):
	"""v2.12.0 (achado de teste E2E real ao vivo, 2026-08-04): sem interaction
	anterior, "input" e SO o conteudo novo (a API e inteiramente stateful,
	nunca aceitou reconstrucao manual de historico -- a suposicao anterior
	de "reenviar self._history" causava HTTP 400 em producao real)."""
	client = ProviderClient("gemini", "secret", "gemini-3.5-flash")
	captured = {}

	def fake_request(url, headers, payload):
		captured["payload"] = payload
		return {
			"steps": [{"type": "model_output", "content": [{"type": "text", "text": "ok"}]}],
			"id": "interaction-abc123", "usage": {"total_tokens": 5},
		}

	monkeypatch.setattr(client, "_request", fake_request)
	client.chat("primeira mensagem")

	assert "previous_interaction_id" not in captured["payload"]
	assert captured["payload"]["input"] == "primeira mensagem"
	assert client._gemini_interaction_id == "interaction-abc123"


def test_gemini_segunda_chamada_usa_previous_interaction_id(monkeypatch):
	"""v2.4.0: com interaction anterior no MESMO client, a segunda chamada
	manda previous_interaction_id. v2.12.0: "input" continua sendo SO o
	turno novo (nunca foi correto reenviar o historico completo -- ver
	teste da primeira chamada acima)."""
	client = ProviderClient("gemini", "secret", "gemini-3.5-flash")
	calls = []

	def fake_request(url, headers, payload):
		calls.append(payload)
		return {
			"steps": [{"type": "model_output", "content": [{"type": "text", "text": "ok"}]}],
			"id": f"interaction-{len(calls)}", "usage": {},
		}

	monkeypatch.setattr(client, "_request", fake_request)
	client.chat("primeira mensagem")
	client.chat("segunda mensagem")

	assert "previous_interaction_id" not in calls[0]
	assert calls[1]["previous_interaction_id"] == "interaction-1"
	assert calls[1]["input"] == "segunda mensagem"


def test_gemini_reset_history_limpa_interaction_id(monkeypatch):
	client = ProviderClient("gemini", "secret", "gemini-3.5-flash")

	def fake_request(url, headers, payload):
		return {
			"steps": [{"type": "model_output", "content": [{"type": "text", "text": "ok"}]}],
			"id": "interaction-xyz", "usage": {},
		}

	monkeypatch.setattr(client, "_request", fake_request)
	client.chat("mensagem")
	assert client._gemini_interaction_id == "interaction-xyz"

	client.reset_history()
	assert client._gemini_interaction_id is None


def test_openai_native_responses_api_reconstructs_function_call_history(monkeypatch):
	"""A Responses API e stateless por chamada (sem sessao no servidor, aqui):
	o item function_call original precisa estar de volta no "input" junto
	com o function_call_output correspondente, ou a API rejeita ("no tool
	call found for function call output"). _build_responses_input precisa
	reconstruir os dois a partir de self._history entre chamadas."""
	client = ProviderClient("openai", "secret", "gpt-5.6-luna")
	calls = []

	def fake_request(url, headers, payload):
		calls.append(payload)
		if len(calls) == 1:
			return {
				"output": [{
					"type": "function_call", "call_id": "call-1",
					"name": "validar", "arguments": "{\"x\":1}",
				}],
				"usage": {"total_tokens": 5},
			}
		return {
			"output": [{"type": "message", "content": [{"type": "output_text", "text": "pronto"}]}],
			"usage": {"total_tokens": 8},
		}

	monkeypatch.setattr(client, "_request", fake_request)
	tools = [{"type": "function", "function": {"name": "validar", "description": "v", "parameters": {"type": "object"}}}]

	first = client.chat("crie um addon", tools=tools)
	assert first.tool_calls[0]["id"] == "call-1"

	client.chat(
		"resultado da ferramenta",
		tools=tools,
		tool_results=[{"tool_call_id": "call-1", "content": "ok"}],
	)

	second_input = calls[1]["input"]
	function_call_items = [i for i in second_input if i.get("type") == "function_call"]
	output_items = [i for i in second_input if i.get("type") == "function_call_output"]
	assert function_call_items and function_call_items[0]["call_id"] == "call-1"
	assert function_call_items[0]["name"] == "validar"
	assert output_items and output_items[0]["call_id"] == "call-1"
	assert output_items[0]["output"] == "ok"


def test_native_web_search_openai_usa_tool_web_search(monkeypatch):
	"""v2.2.0: native_web_search() injeta o server tool nativo do provedor
	numa chamada isolada, fora de self._history."""
	client = ProviderClient("openai", "secret", "gpt-5.6-luna")
	captured = {}

	def fake_request(url, headers, payload):
		captured.update(url=url, payload=payload)
		return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "resultado"}]}]}

	monkeypatch.setattr(client, "_request", fake_request)
	result = client.native_web_search("google-generativeai python sdk")

	assert captured["url"].endswith("/v1/responses")
	assert captured["payload"]["tools"] == [{"type": "web_search"}]
	assert result == "resultado"
	assert client.history == []  # chamada isolada, nao entra no historico da conversa


def test_native_web_search_xai_usa_endpoint_e_tool_corretos(monkeypatch):
	client = ProviderClient("xai", "secret", "grok-4.3")
	captured = {}

	def fake_request(url, headers, payload):
		captured.update(url=url, payload=payload)
		return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}

	monkeypatch.setattr(client, "_request", fake_request)
	client.native_web_search("grok pricing 2026")

	assert captured["url"].endswith("api.x.ai/v1/responses")
	assert captured["payload"]["tools"] == [{"type": "web_search"}]


def test_native_web_search_anthropic_usa_versao_atual_do_tool(monkeypatch):
	"""v2.3.0: web_search_20260318 confirmado pela auditoria como a versao
	mais atual do server tool -- nao web_search_20250305 (basico) nem
	web_search_20260209 (intermediaria)."""
	client = ProviderClient("anthropic", "secret", "claude-haiku-4-5")
	captured = {}

	def fake_request(url, headers, payload):
		captured.update(url=url, payload=payload)
		return {"content": [{"type": "text", "text": "ok"}]}

	monkeypatch.setattr(client, "_request", fake_request)
	client.native_web_search("anthropic web search tool version")

	assert captured["url"].endswith("/v1/messages")
	assert captured["payload"]["tools"] == [{"type": "web_search_20260318", "name": "web_search"}]


def test_native_web_search_gemini_usa_tool_type_google_search(monkeypatch):
	"""v2.3.0: bug real de auditoria (subagente de pesquisa web dedicado) --
	tools=[{"google_search": {}}] estava ERRADO. A sintaxe confirmada
	contra a doc oficial de grounding da Interactions API e o mesmo padrao
	"type" plano usado pelos outros 4 provedores: {"type": "google_search"}."""
	client = ProviderClient("gemini", "secret", "gemini-3.5-flash")
	captured = {}

	def fake_request(url, headers, payload):
		captured.update(url=url, payload=payload)
		return {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "ok"}]}]}

	monkeypatch.setattr(client, "_request", fake_request)
	client.native_web_search("gemini grounding search")

	assert captured["url"].endswith("/v1/interactions")
	assert captured["payload"]["tools"] == [{"type": "google_search"}]
	assert captured["payload"]["tools"] != [{"google_search": {}}]
	# v2.12.0 (achado de teste E2E real ao vivo): "input" e a string simples,
	# nunca o formato antigo role/parts (API real rejeita com HTTP 400).
	assert captured["payload"]["input"] == "gemini grounding search"


def test_native_web_search_query_vazia_retorna_vazio():
	client = ProviderClient("openai", "secret", "gpt-5.6-luna")
	assert client.native_web_search("") == ""
	assert client.native_web_search("   ") == ""


def test_native_web_search_engole_excecao_e_retorna_vazio(monkeypatch):
	from nvdastudio.ai.provider_client import ProviderClientError
	client = ProviderClient("openai", "secret", "gpt-5.6-luna")

	def fake_request(url, headers, payload):
		raise ProviderClientError("timeout")

	monkeypatch.setattr(client, "_request", fake_request)
	assert client.native_web_search("algo") == ""


def test_openai_chat_mistura_tool_nativo_e_function_tool_sem_corromper(monkeypatch):
	"""v2.4.0: code_interpreter (server tool nativo) misturado com um
	function-tool normal no mesmo array nao pode passar pelo achatamento
	de _tool_function() -- isso corromperia o bloco nativo num
	function-tool vazio ({"type":"function","name":"","description":""})."""
	client = ProviderClient("openai", "secret", "gpt-5.6-luna")
	captured = {}

	def fake_request(url, headers, payload):
		captured.update(payload=payload)
		return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}

	monkeypatch.setattr(client, "_request", fake_request)
	client.chat(
		"gera o codigo",
		tools=[
			{"type": "function", "function": {"name": "validar", "description": "v", "parameters": {"type": "object"}}},
			{"type": "code_interpreter", "container": {"type": "auto"}},
		],
	)
	sent_tools = captured["payload"]["tools"]
	assert sent_tools[0] == {"type": "function", "name": "validar", "description": "v", "parameters": {"type": "object"}}
	assert sent_tools[1] == {"type": "code_interpreter", "container": {"type": "auto"}}


def test_anthropic_chat_mistura_tool_nativo_e_function_tool_sem_corromper(monkeypatch):
	client = ProviderClient("anthropic", "secret", "claude-haiku-4-5")
	captured = {}

	def fake_request(url, headers, payload):
		captured.update(payload=payload)
		return {"content": [{"type": "text", "text": "ok"}]}

	monkeypatch.setattr(client, "_request", fake_request)
	client.chat(
		"gera o codigo",
		tools=[
			{"type": "function", "function": {"name": "validar", "description": "v", "parameters": {"type": "object"}}},
			{"type": "code_execution_20260521", "name": "code_execution"},
		],
	)
	sent_tools = captured["payload"]["tools"]
	assert sent_tools[0] == {"name": "validar", "description": "v", "input_schema": {"type": "object"}}
	assert sent_tools[1]["type"] == "code_execution_20260521"
	assert sent_tools[1]["name"] == "code_execution"


def test_factory_uses_native_provider_without_hermes(monkeypatch):
	from nvdastudio.ai import llm_factory
	from nvdastudio.gui import settings_panel

	monkeypatch.setattr(settings_panel, "get_api_key", lambda provider: "secret")
	client = llm_factory.create_llm_client(model_id="gpt-5.6-luna", provider="openai")
	assert isinstance(client, ProviderClient)


# ---------------------------------------------------------------------------
# Streaming com tools (v2.6.0): texto (preambulo/narracao) e tool_calls
# convivem no mesmo stream, confirmado por pesquisa dedicada nos 4
# provedores. Reasoning-summary streaming (on_reasoning_chunk) foi removido
# na v2.7.0 -- ficou sem consumidor em producao depois que o planejamento
# passou a narrar de verdade via tool call (padrao "final answer as tool
# call") em vez de reescrever o resumo de raciocinio nativo.
# ---------------------------------------------------------------------------

def test_openai_narra_texto_e_monta_tool_call_no_mesmo_stream(monkeypatch):
	"""v2.6.0: streaming com tools ativo -- confirmado pela doc oficial
	(tool preambles) que texto e function_call convivem no mesmo stream.
	Preambulo narrado ao vivo via on_chunk, argumentos da tool acumulados
	via response.function_call_arguments.delta ate response.output_item.done."""
	client = ProviderClient("openai", "secret", "gpt-5.6-luna")
	captured = {}

	def fake_stream_sse(url, headers, payload, on_event):
		captured["payload"] = payload
		on_event({"type": "response.output_item.added", "item": {"id": "item_0", "type": "message"}})
		on_event({"type": "response.output_text.delta", "delta": "Vou verificar o pacote antes de usar."})
		on_event({"type": "response.output_item.added", "item": {"id": "item_1", "type": "function_call", "call_id": "call_1", "name": "validate_import"}})
		on_event({"type": "response.function_call_arguments.delta", "item_id": "item_1", "delta": '{"module_name":'})
		on_event({"type": "response.function_call_arguments.delta", "item_id": "item_1", "delta": '"requests"}'})
		on_event({"type": "response.output_item.done", "item": {"id": "item_1", "type": "function_call", "arguments": '{"module_name":"requests"}'}})

	monkeypatch.setattr(client, "_stream_sse", fake_stream_sse)
	narrated = []
	response = client.chat(
		"gere o codigo",
		on_chunk=narrated.append,
		tools=[{"type": "function", "function": {"name": "validate_import", "description": "d", "parameters": {"type": "object"}}}],
	)
	assert captured["payload"]["stream"] is True
	assert narrated == ["Vou verificar o pacote antes de usar."]
	assert response.content == "Vou verificar o pacote antes de usar."
	assert len(response.tool_calls) == 1
	assert response.tool_calls[0]["function"]["name"] == "validate_import"
	assert response.tool_calls[0]["function"]["arguments"] == '{"module_name":"requests"}'


def test_anthropic_narra_texto_e_monta_tool_use_no_mesmo_stream(monkeypatch):
	"""v2.6.0: replica o exemplo oficial "Streaming request with tool use"
	da doc da Anthropic -- texto (index 0) fecha, tool_use (index 1) abre e
	acumula input_json_delta ate content_block_stop."""
	client = ProviderClient("anthropic", "secret", "claude-haiku-4-5")
	captured = {}

	def fake_stream_sse(url, headers, payload, on_event):
		captured["payload"] = payload
		on_event({"type": "content_block_start", "index": 0, "content_block": {"type": "text"}})
		on_event({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Vou checar o clima."}})
		on_event({"type": "content_block_stop", "index": 0})
		on_event({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "get_weather"}})
		on_event({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"location":'}})
		on_event({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": ' "SF"}'}})
		on_event({"type": "content_block_stop", "index": 1})

	monkeypatch.setattr(client, "_stream_sse", fake_stream_sse)
	narrated = []
	response = client.chat(
		"qual o clima em SF",
		on_chunk=narrated.append,
		tools=[{"type": "function", "function": {"name": "get_weather", "description": "d", "parameters": {"type": "object"}}}],
	)
	assert narrated == ["Vou checar o clima."]
	assert response.content == "Vou checar o clima."
	assert len(response.tool_calls) == 1
	assert response.tool_calls[0]["function"]["name"] == "get_weather"
	assert response.tool_calls[0]["function"]["arguments"] == {"location": "SF"}


def test_gemini_narra_texto_e_monta_function_call_no_mesmo_stream(monkeypatch):
	"""v2.6.0: replica o exemplo oficial da Interactions API -- o tipo do
	evento vem no NOME do evento SSE (step.start/step.delta/step.stop), nao
	num campo dentro do JSON. arguments_delta acumulado ate step.stop."""
	client = ProviderClient("gemini", "secret", "gemini-3-pro")
	captured = {}

	def fake_stream_sse(url, headers, payload, on_event):
		captured["payload"] = payload
		on_event({"_sse_event": "step.start", "index": 0, "step": {"type": "model_output"}})
		on_event({"_sse_event": "step.delta", "index": 0, "delta": {"type": "text", "text": "Vou consultar o clima."}})
		on_event({"_sse_event": "step.stop", "index": 0})
		on_event({"_sse_event": "step.start", "index": 1, "step": {"id": "ktr5aysg", "type": "function_call", "name": "get_weather"}})
		on_event({"_sse_event": "step.delta", "index": 1, "delta": {"type": "arguments_delta", "arguments": '{"location":"Mount Elbrus"}'}})
		on_event({"_sse_event": "step.stop", "index": 1})

	monkeypatch.setattr(client, "_stream_sse", fake_stream_sse)
	narrated = []
	response = client.chat(
		"qual o clima no Elbrus",
		on_chunk=narrated.append,
		tools=[{"type": "function", "function": {"name": "get_weather", "description": "d", "parameters": {"type": "object"}}}],
	)
	assert narrated == ["Vou consultar o clima."]
	assert response.content == "Vou consultar o clima."
	assert len(response.tool_calls) == 1
	assert response.tool_calls[0]["id"] == "ktr5aysg"
	assert response.tool_calls[0]["function"]["name"] == "get_weather"
	assert response.tool_calls[0]["function"]["arguments"] == {"location": "Mount Elbrus"}


def test_stream_sse_repassa_nome_do_evento_sse_em_sse_event(monkeypatch):
	"""_stream_sse injeta o nome da linha "event: X" em data["_sse_event"]
	antes de chamar on_event -- necessario pra Gemini, cujo tipo de evento
	vem no nome do evento SSE, nao num campo dentro do JSON."""
	client = ProviderClient("openai", "secret", "gpt-5.6-luna")

	class _FakeStreamCtx:
		def __enter__(self):
			return self
		def __exit__(self, *a):
			return False
		def raise_for_status(self):
			pass
		def iter_lines(self):
			yield "event: step.start"
			yield 'data: {"index": 0}'
			yield "event: step.stop"
			yield 'data: {"index": 0}'
			yield "data: [DONE]"

	class _FakeHttpxClient:
		def __enter__(self):
			return self
		def __exit__(self, *a):
			return False
		def stream(self, method, url, headers=None, json=None):
			return _FakeStreamCtx()

	class _FakeHttpxModule:
		def Client(self, timeout=None):
			return _FakeHttpxClient()

	monkeypatch.setattr("nvdastudio.ai.provider_client._httpx_module", lambda: _FakeHttpxModule())
	seen = []
	client._stream_sse("https://x", {}, {}, seen.append)
	assert seen[0] == {"index": 0, "_sse_event": "step.start"}
	assert seen[1] == {"index": 0, "_sse_event": "step.stop"}


def test_anthropic_reasoning_effort_usa_thinking_adaptive(monkeypatch):
	"""
	Bug real de auditoria: chat() so repassava reasoning_effort pro branch
	OpenAI-compatible; Anthropic e Gemini descartavam silenciosamente, sem
	erro nem log. planner.py chama client.chat(..., reasoning_effort="high")
	genericamente sem saber qual provider esta ativo.
	"""
	client = ProviderClient("anthropic", "secret", "claude-sonnet-5")
	captured = {}

	def fake_request(url, headers, payload):
		captured["payload"] = payload
		return {"content": [{"type": "text", "text": "pronto"}], "usage": {}}

	monkeypatch.setattr(client, "_request", fake_request)
	client.chat("teste", reasoning_effort="high")

	assert captured["payload"]["thinking"] == {"type": "adaptive"}
	assert captured["payload"]["output_config"]["effort"] == "high"


def test_anthropic_reasoning_effort_ignorado_em_modelo_legado(monkeypatch):
	"""claude-haiku-4-5 nao suporta thinking adaptativo -- nao deve mandar o campo."""
	client = ProviderClient("anthropic", "secret", "claude-haiku-4-5")
	captured = {}

	def fake_request(url, headers, payload):
		captured["payload"] = payload
		return {"content": [{"type": "text", "text": "pronto"}], "usage": {}}

	monkeypatch.setattr(client, "_request", fake_request)
	client.chat("teste", reasoning_effort="high")

	assert "thinking" not in captured["payload"]


def test_gemini_reasoning_effort_usa_thinking_level(monkeypatch):
	"""Bug real de auditoria: mesmo gap do Anthropic, para Gemini."""
	client = ProviderClient("gemini", "secret", "gemini-3.6-flash")
	captured = {}

	def fake_request(url, headers, payload):
		captured["payload"] = payload
		return {"output": [{"type": "model_output", "content": [{"type": "text", "text": "pronto"}]}]}

	monkeypatch.setattr(client, "_request", fake_request)
	client.chat("teste", reasoning_effort="high")

	assert captured["payload"]["generation_config"]["thinking_level"] == "high"


class TestLLMResponseTruncated:
	"""Achado CRITICO de auditoria full-stack 2026-08-04 (rastreamento de
	geracao de addons grandes): quando a resposta e cortada pelo teto de
	tokens no meio de um arquivo, extract_code_blocks() descarta o bloco sem
	fechamento silenciosamente -- sem erro, sem retry. LLMResponse.truncated
	(llm_client.py 1.1.0) agora carrega esse sinal desde cada provedor."""

	def test_openai_incomplete_max_output_tokens_marca_truncated(self, monkeypatch):
		client = ProviderClient("openai", "secret", "gpt-5.6-luna")

		def fake_request(url, headers, payload):
			return {
				"output": [{"type": "message", "content": [{"type": "output_text", "text": "codigo cortado"}]}],
				"usage": {"total_tokens": 12},
				"status": "incomplete",
				"incomplete_details": {"reason": "max_output_tokens"},
			}

		monkeypatch.setattr(client, "_request", fake_request)
		response = client.chat("gere o codigo")
		assert response.truncated is True

	def test_openai_completo_nao_marca_truncated(self, monkeypatch):
		client = ProviderClient("openai", "secret", "gpt-5.6-luna")

		def fake_request(url, headers, payload):
			return {
				"output": [{"type": "message", "content": [{"type": "output_text", "text": "codigo completo"}]}],
				"usage": {"total_tokens": 12},
				"status": "completed",
			}

		monkeypatch.setattr(client, "_request", fake_request)
		response = client.chat("gere o codigo")
		assert response.truncated is False

	def test_anthropic_stop_reason_max_tokens_marca_truncated(self, monkeypatch):
		client = ProviderClient("anthropic", "secret", "claude-haiku-4-5")

		def fake_request(url, headers, payload):
			return {
				"content": [{"type": "text", "text": "codigo cortado"}],
				"usage": {"input_tokens": 10, "output_tokens": 5},
				"stop_reason": "max_tokens",
			}

		monkeypatch.setattr(client, "_request", fake_request)
		response = client.chat("gere o codigo")
		assert response.truncated is True

	def test_anthropic_end_turn_nao_marca_truncated(self, monkeypatch):
		client = ProviderClient("anthropic", "secret", "claude-haiku-4-5")

		def fake_request(url, headers, payload):
			return {
				"content": [{"type": "text", "text": "codigo completo"}],
				"usage": {"input_tokens": 10, "output_tokens": 5},
				"stop_reason": "end_turn",
			}

		monkeypatch.setattr(client, "_request", fake_request)
		response = client.chat("gere o codigo")
		assert response.truncated is False

	def test_gemini_status_incomplete_marca_truncated(self, monkeypatch):
		client = ProviderClient("gemini", "secret", "gemini-3.6-flash")

		def fake_request(url, headers, payload):
			return {
				"id": "interaction-1",
				"steps": [{"type": "model_output", "content": [{"type": "text", "text": "codigo cortado"}]}],
				"usage": {"total_tokens": 12}, "status": "incomplete",
			}

		monkeypatch.setattr(client, "_request", fake_request)
		response = client.chat("gere o codigo")
		assert response.truncated is True

	def test_gemini_status_completed_nao_marca_truncated(self, monkeypatch):
		client = ProviderClient("gemini", "secret", "gemini-3.6-flash")

		def fake_request(url, headers, payload):
			return {
				"id": "interaction-1",
				"steps": [{"type": "model_output", "content": [{"type": "text", "text": "codigo completo"}]}],
				"usage": {"total_tokens": 12}, "status": "completed",
			}

		monkeypatch.setattr(client, "_request", fake_request)
		response = client.chat("gere o codigo")
		assert response.truncated is False

	def test_llmresponse_truncated_default_false(self):
		from nvdastudio.ai.llm_client import LLMResponse
		resp = LLMResponse(content="ok", model_used="x")
		assert resp.truncated is False


class TestGeminiContentExtractionRealShape:
	"""Achado CRITICO de teste E2E real ao vivo (2026-08-04): a resposta real
	da Interactions API NUNCA tem um campo "output_text" -- o texto fica em
	steps[i].content[], steps do tipo "model_output". Confirmado via
	reproducao direta contra a API (httpx cru, fora de qualquer mock).
	Ate esta correcao, TODA resposta non-streaming do Gemini vinha com
	content="" mesmo com status="completed" e nenhum erro."""

	def test_extrai_texto_de_multiplos_steps_model_output(self, monkeypatch):
		client = ProviderClient("gemini", "secret", "gemini-3.6-flash")

		def fake_request(url, headers, payload):
			return {
				"steps": [
					{"type": "thought", "signature": "..."},
					{"type": "model_output", "content": [{"type": "text", "text": "Ola, "}]},
					{"type": "model_output", "content": [{"type": "text", "text": "mundo!"}]},
				],
				"usage": {"total_tokens": 5},
			}

		monkeypatch.setattr(client, "_request", fake_request)
		response = client.chat("oi")
		assert response.content == "Ola, mundo!"

	def test_sem_output_text_no_payload_content_fica_vazio_mas_nao_quebra(self, monkeypatch):
		"""Regressao do bug: nao deve mais depender de output_text, mas
		tambem nao pode lancar excecao se so houver steps de function_call."""
		client = ProviderClient("gemini", "secret", "gemini-3.6-flash")

		def fake_request(url, headers, payload):
			return {
				"steps": [{"type": "function_call", "id": "g1", "name": "buscar", "arguments": {}}],
				"usage": {},
			}

		monkeypatch.setattr(client, "_request", fake_request)
		response = client.chat("busque algo")
		assert response.content == ""
		assert response.tool_calls[0]["function"]["name"] == "buscar"


class TestGeminiStreamingCapturaInteractionId:
	"""Achado de teste E2E real ao vivo (2026-08-04): o comentario antigo
	dizia que streaming nunca retorna id de interaction -- reproducao direta
	contra a API confirmou o oposto: o id chega via evento SSE
	interaction.created/interaction.completed. Sem capturar isso, TODA
	conversa multi-turno via streaming perdia o contexto stateful."""

	def test_streaming_captura_interaction_id_via_evento_sse(self, monkeypatch):
		client = ProviderClient("gemini", "secret", "gemini-3.6-flash")

		def fake_stream_sse(url, headers, payload, on_event):
			on_event({
				"_sse_event": "interaction.created",
				"interaction": {"id": "int-stream-1", "status": "in_progress"},
			})
			on_event({
				"_sse_event": "step.start", "index": 0,
				"step": {"type": "model_output"},
			})
			on_event({
				"_sse_event": "step.delta", "index": 0,
				"delta": {"type": "text", "text": "oi"},
			})
			on_event({
				"_sse_event": "interaction.completed",
				"interaction": {"id": "int-stream-1", "status": "completed"},
			})

		monkeypatch.setattr(client, "_stream_sse", fake_stream_sse)
		response = client.chat("oi", on_chunk=lambda _t: None)

		assert response.content == "oi"
		assert client._gemini_interaction_id == "int-stream-1"

	def test_streaming_segunda_chamada_usa_previous_interaction_id(self, monkeypatch):
		client = ProviderClient("gemini", "secret", "gemini-3.6-flash")
		payloads = []

		def fake_stream_sse(url, headers, payload, on_event):
			payloads.append(payload)
			on_event({
				"_sse_event": "interaction.created",
				"interaction": {"id": f"int-{len(payloads)}", "status": "in_progress"},
			})
			on_event({
				"_sse_event": "interaction.completed",
				"interaction": {"id": f"int-{len(payloads)}", "status": "completed"},
			})

		monkeypatch.setattr(client, "_stream_sse", fake_stream_sse)
		client.chat("primeira", on_chunk=lambda _t: None)
		client.chat("segunda", on_chunk=lambda _t: None)

		assert "previous_interaction_id" not in payloads[0]
		assert payloads[1]["previous_interaction_id"] == "int-1"

	def test_streaming_status_incomplete_marca_truncated(self, monkeypatch):
		client = ProviderClient("gemini", "secret", "gemini-3.6-flash")

		def fake_stream_sse(url, headers, payload, on_event):
			on_event({
				"_sse_event": "interaction.completed",
				"interaction": {"id": "int-1", "status": "incomplete"},
			})

		monkeypatch.setattr(client, "_stream_sse", fake_stream_sse)
		response = client.chat("gere o codigo", on_chunk=lambda _t: None)
		assert response.truncated is True


class TestRetryDelayRespeitaMensagemDoProvedor:
	"""Achado de teste E2E real ao vivo (2026-08-04, quota gratuita
	limitada): a resposta 429 do Gemini embute o tempo real de espera na
	mensagem de erro ("Please retry in 24.8s."), sem header estruturado. O
	backoff fixo antigo (0.5s/1s) era curto demais pra esse teto real.

	2.15.0: _retry_delay() migrou pra ai/reliability.py::retry_delay()
	(fonte unica compartilhada com os outros clientes LLM) -- agora recebe
	a EXCECAO (le .response internamente), nao o objeto response direto.
	"""

	def _exc_with_response(self, status, text):
		exc = RuntimeError(f"status {status}")
		exc.response = type("R", (), {"status_code": status, "text": text, "headers": {}})()
		return exc

	def test_extrai_tempo_da_mensagem_de_erro(self):
		from nvdastudio.ai.reliability import retry_delay
		exc = self._exc_with_response(429, "Quota exceeded... Please retry in 24.805040091s.")
		assert retry_delay(exc, attempt=0) == pytest.approx(25.3, abs=0.1)

	def test_sem_dica_na_mensagem_cai_pro_backoff_exponencial(self):
		from nvdastudio.ai.reliability import retry_delay
		exc = self._exc_with_response(500, "Internal server error")
		assert 1.0 <= retry_delay(exc, attempt=0) <= 1.2
		assert 2.0 <= retry_delay(exc, attempt=1) <= 2.4

	def test_response_none_cai_pro_backoff_exponencial(self):
		from nvdastudio.ai.reliability import retry_delay
		assert 1.0 <= retry_delay(RuntimeError("sem response"), attempt=0) <= 1.2

	def test_delay_e_limitado_a_um_teto_maximo(self):
		from nvdastudio.ai.reliability import retry_delay, _MAX_RETRY_DELAY
		exc = self._exc_with_response(429, "Please retry in 9999s.")
		assert retry_delay(exc, attempt=0) == _MAX_RETRY_DELAY

	def test_request_usa_retry_delay_em_429(self, monkeypatch):
		"""Integra reliability.call_with_retry() de verdade no loop de _request()."""
		import nvdastudio.ai.provider_client as provider_client_mod
		from nvdastudio.ai import reliability
		client = ProviderClient("gemini", "secret", "gemini-3.6-flash")

		sleeps = []
		monkeypatch.setattr(reliability.time, "sleep", lambda s: sleeps.append(s))

		class FakeResp:
			def __init__(self, status, text, ok_json=None):
				self.status_code = status
				self.text = text
				self.headers = {}
				self._ok_json = ok_json

			def raise_for_status(self):
				if self.status_code >= 400:
					exc = RuntimeError(f"status {self.status_code}")
					exc.response = self
					raise exc

			def json(self):
				return self._ok_json or {}

		calls = {"n": 0}

		class FakeClient:
			def __enter__(self):
				return self

			def __exit__(self, *a):
				return False

			def post(self, url, headers, json):
				calls["n"] += 1
				if calls["n"] == 1:
					return FakeResp(429, "Please retry in 3.2s.")
				return FakeResp(200, "ok", {"steps": [{"type": "model_output", "content": [{"type": "text", "text": "ok"}]}]})

		fake_httpx = type("M", (), {"Client": lambda *a, **k: FakeClient()})
		monkeypatch.setattr(provider_client_mod, "_httpx_module", lambda: fake_httpx)

		client.chat("oi")
		assert sleeps and sleeps[0] == pytest.approx(3.7, abs=0.1)
