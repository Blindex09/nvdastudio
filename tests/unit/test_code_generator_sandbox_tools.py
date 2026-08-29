from unittest.mock import MagicMock, patch

import nvdastudio.sub_agents.code_generator as code_generator_mod


def _fake_client(provider, content="```python:globalPlugins/X/__init__.py\npass\n```"):
	client = MagicMock()
	client._provider = provider
	resp = MagicMock()
	resp.content = content
	resp.tool_calls = None
	resp.tokens_used = 10
	client.chat.return_value = resp
	return client


class TestSandboxToolPorProvedor:
	def test_openai_recebe_code_interpreter(self):
		client = _fake_client("openai")
		with patch.object(code_generator_mod, "create_llm_client", return_value=client), \
			 patch.object(code_generator_mod, "_verificar_codigo_gerado", side_effect=lambda c, m, **kw: c):
			code_generator_mod.run("cria um addon simples", "gpt-5.6-sol", {})

		sent_tools = client.chat.call_args.kwargs["tools"]
		assert {"type": "code_interpreter", "container": {"type": "auto"}} in sent_tools

	def test_anthropic_recebe_code_execution(self):
		client = _fake_client("anthropic")
		with patch.object(code_generator_mod, "create_llm_client", return_value=client), \
			 patch.object(code_generator_mod, "_verificar_codigo_gerado", side_effect=lambda c, m, **kw: c):
			code_generator_mod.run("cria um addon simples", "claude-opus-5", {})

		sent_tools = client.chat.call_args.kwargs["tools"]
		assert {"type": "code_execution_20260521", "name": "code_execution"} in sent_tools

	def test_gemini_nao_recebe_sandbox_nativo(self):
		client = _fake_client("gemini")
		with patch.object(code_generator_mod, "create_llm_client", return_value=client), \
			 patch.object(code_generator_mod, "_verificar_codigo_gerado", side_effect=lambda c, m, **kw: c):
			code_generator_mod.run("cria um addon simples", "gemini-3.1-pro-preview", {})

		sent_tools = client.chat.call_args.kwargs["tools"]
		assert not any(t.get("type") == "code_interpreter" for t in sent_tools)
		assert not any(t.get("type", "").startswith("code_execution") for t in sent_tools)

	def test_ollama_nao_recebe_sandbox_nativo(self):
		"""OllamaClient nao tem atributo _provider (so ProviderClient tem) --
		getattr(client, "_provider", "") deve cair no default vazio, sem tool nativa."""
		client = MagicMock(spec=["chat"])
		resp = MagicMock()
		resp.content = "```python:globalPlugins/X/__init__.py\npass\n```"
		resp.tool_calls = None
		resp.tokens_used = 10
		client.chat.return_value = resp
		with patch.object(code_generator_mod, "create_llm_client", return_value=client), \
			 patch.object(code_generator_mod, "_verificar_codigo_gerado", side_effect=lambda c, m, **kw: c):
			code_generator_mod.run("cria um addon simples", "kimi-k2.7-code", {})

		sent_tools = client.chat.call_args.kwargs["tools"]
		assert not any(t.get("type") == "code_interpreter" for t in sent_tools)
		assert not any(str(t.get("type", "")).startswith("code_execution") for t in sent_tools)
