from unittest.mock import MagicMock, patch


class TestOpenCodeGoResponsesApiRouting:
	"""
	1.2.0: gpt-5.6-luna (unico modelo OpenAI-family do catalogo do OpenCode
	Go) exige a Responses API (/v1/responses), nao Chat Completions
	(/v1/chat/completions, usada por todo o resto do catalogo) -- achado
	real de auditoria 2026-08-26, comparando com C:\\agentic (mesmo gateway,
	provider ja implementado corretamente la). Antes desta correcao,
	gpt-5.6-luna via /chat/completions retornava 500, presumido "fora do
	ar"; era so o endpoint errado pro modelo.
	"""

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

	def test_gpt_5_6_luna_usa_endpoint_responses(self):
		import nvdastudio.ai.opencode_go_client as mod

		fake_httpx = self._fake_httpx_non_stream({
			"output_text": "ok",
			"output": [],
			"usage": {"input_tokens": 5, "output_tokens": 1, "total_tokens": 6},
		})
		with patch.object(mod, "_httpx", fake_httpx):
			client = mod.OpenCodeGoClient(api_key="sk-test", model_id="gpt-5.6-luna")
			client.chat("oi")

		url = fake_httpx.Client.return_value.post.call_args.args[0]
		assert url == mod._OPENCODE_GO_RESPONSES_URL

	def test_outro_modelo_continua_no_endpoint_chat_completions(self):
		import nvdastudio.ai.opencode_go_client as mod

		fake_httpx = self._fake_httpx_non_stream({
			"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
			"usage": {},
		})
		with patch.object(mod, "_httpx", fake_httpx):
			client = mod.OpenCodeGoClient(api_key="sk-test", model_id="kimi-k2.6")
			client.chat("oi")

		url = fake_httpx.Client.return_value.post.call_args.args[0]
		assert url == mod._OPENCODE_GO_URL

	def test_responses_api_envia_input_e_store_true(self):
		import nvdastudio.ai.opencode_go_client as mod

		fake_httpx = self._fake_httpx_non_stream({
			"output_text": "ok", "output": [], "usage": {},
		})
		with patch.object(mod, "_httpx", fake_httpx):
			client = mod.OpenCodeGoClient(api_key="sk-test", model_id="gpt-5.6-luna")
			client.chat("pergunta do usuario")

		payload = fake_httpx.Client.return_value.post.call_args.kwargs["json"]
		assert payload["model"] == "gpt-5.6-luna"
		assert payload["store"] is True
		assert any(m.get("content") == "pergunta do usuario" for m in payload["input"])

	def test_responses_api_response_format_vira_text_format_estrito(self):
		import nvdastudio.ai.opencode_go_client as mod

		fake_httpx = self._fake_httpx_non_stream({
			"output_text": '{"nome":"NVDA"}', "output": [], "usage": {},
		})
		schema = {
			"type": "object",
			"properties": {"nome": {"type": "string"}, "extra": {"type": "string"}},
			"required": ["nome"],
			"additionalProperties": False,
		}
		with patch.object(mod, "_httpx", fake_httpx):
			client = mod.OpenCodeGoClient(api_key="sk-test", model_id="gpt-5.6-luna")
			client.chat("pergunta", response_format={
				"type": "json_schema",
				"json_schema": {"name": "teste", "schema": schema, "strict": True},
			})

		payload = fake_httpx.Client.return_value.post.call_args.kwargs["json"]
		fmt = payload["text"]["format"]
		assert fmt["type"] == "json_schema"
		assert fmt["strict"] is True
		# _strict_responses_schema: TODO campo entra em "required" (extra vira
		# nullable via anyOf em vez de ficar de fora do required).
		assert set(fmt["schema"]["required"]) == {"nome", "extra"}
		assert fmt["schema"]["additionalProperties"] is False
		assert fmt["schema"]["properties"]["extra"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}

	def test_responses_api_extrai_cached_tokens_do_usage(self):
		import nvdastudio.ai.opencode_go_client as mod

		fake_httpx = self._fake_httpx_non_stream({
			"output_text": "ok",
			"output": [],
			"usage": {
				"input_tokens": 100, "output_tokens": 10, "total_tokens": 110,
				"input_tokens_details": {"cached_tokens": 80, "cache_write_tokens": 0},
			},
		})
		with patch.object(mod, "_httpx", fake_httpx):
			client = mod.OpenCodeGoClient(api_key="sk-test", model_id="gpt-5.6-luna")
			resp = client.chat("oi")

		assert resp.usage_breakdown["cached_tokens"] == 80
		assert resp.tokens_used == 110

	def test_responses_api_extrai_tool_calls(self):
		import nvdastudio.ai.opencode_go_client as mod

		fake_httpx = self._fake_httpx_non_stream({
			"output": [{
				"type": "function_call", "call_id": "call_1",
				"name": "minha_ferramenta", "arguments": '{"x": 1}',
			}],
			"usage": {},
		})
		with patch.object(mod, "_httpx", fake_httpx):
			client = mod.OpenCodeGoClient(api_key="sk-test", model_id="gpt-5.6-luna")
			resp = client.chat("oi", tools=[{
				"type": "function", "function": {"name": "minha_ferramenta", "parameters": {}},
			}])

		assert len(resp.tool_calls) == 1
		assert resp.tool_calls[0]["function"]["name"] == "minha_ferramenta"
		assert resp.tool_calls[0]["function"]["arguments"] == {"x": 1}


class TestStrictResponsesSchema:
	def test_campo_opcional_vira_anyof_com_null(self):
		import nvdastudio.ai.opencode_go_client as mod

		schema = {
			"type": "object",
			"properties": {"a": {"type": "string"}, "b": {"type": "string"}},
			"required": ["a"],
		}
		result = mod._strict_responses_schema(schema)
		assert set(result["required"]) == {"a", "b"}
		assert result["properties"]["a"] == {"type": "string"}
		assert result["properties"]["b"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
		assert result["additionalProperties"] is False

	def test_objeto_aninhado_e_normalizado_recursivamente(self):
		import nvdastudio.ai.opencode_go_client as mod

		schema = {
			"type": "object",
			"properties": {
				"filho": {
					"type": "object",
					"properties": {"x": {"type": "integer"}},
					"required": [],
				},
			},
			"required": ["filho"],
		}
		result = mod._strict_responses_schema(schema)
		filho = result["properties"]["filho"]
		assert filho["additionalProperties"] is False
		assert filho["properties"]["x"] == {"anyOf": [{"type": "integer"}, {"type": "null"}]}
