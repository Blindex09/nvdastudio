from unittest.mock import MagicMock, patch

import nvdastudio.sub_agents.code_generator as code_generator_mod


def _fake_client(content="```python:globalPlugins/X/__init__.py\npass\n```"):
	client = MagicMock()
	client._provider = "ollama"
	resp = MagicMock()
	resp.content = content
	resp.tool_calls = None
	resp.tokens_used = 10
	client.chat.return_value = resp
	return client


class TestLiveNarratorLigadoNoToolUseLoop:
	def test_primeira_chamada_recebe_on_chunk(self):
		client = _fake_client()
		with patch.object(code_generator_mod, "create_llm_client", return_value=client), \
			 patch.object(code_generator_mod, "_verificar_codigo_gerado", side_effect=lambda c, m, **kw: c):
			code_generator_mod.run("cria um addon simples", "kimi-k2.7-code", {})

		assert callable(client.chat.call_args.kwargs.get("on_chunk"))

	def test_system_prompt_inclui_instrucao_de_tool_preamble(self):
		client = _fake_client()
		with patch.object(code_generator_mod, "create_llm_client", return_value=client), \
			 patch.object(code_generator_mod, "_verificar_codigo_gerado", side_effect=lambda c, m, **kw: c):
			code_generator_mod.run("cria um addon simples", "kimi-k2.7-code", {})

		system_sent = client.chat.call_args.kwargs["system_override"]
		assert "NARRACAO EM TEMPO REAL" in system_sent

	def test_live_narrator_flush_chamado_mesmo_com_sucesso(self):
		"""flush() precisa rodar (via finally) mesmo no caminho feliz, pra
		narrar qualquer resto do preambulo que nao fechou frase."""
		client = _fake_client()
		with patch.object(code_generator_mod, "create_llm_client", return_value=client), \
			 patch.object(code_generator_mod, "_verificar_codigo_gerado", side_effect=lambda c, m, **kw: c), \
			 patch.object(code_generator_mod, "LiveNarrator") as mock_narrator_cls:
			mock_narrator = MagicMock()
			mock_narrator_cls.return_value = mock_narrator
			code_generator_mod.run("cria um addon simples", "kimi-k2.7-code", {})

		mock_narrator.flush.assert_called_once()

	def test_live_narrator_flush_chamado_mesmo_com_excecao(self):
		client = MagicMock()
		client._provider = "ollama"
		client.chat.side_effect = RuntimeError("falhou")
		with patch.object(code_generator_mod, "create_llm_client", return_value=client), \
			 patch.object(code_generator_mod, "_run_sub_agent", return_value="fallback"), \
			 patch.object(code_generator_mod, "_verificar_codigo_gerado", side_effect=lambda c, m, **kw: c), \
			 patch.object(code_generator_mod, "LiveNarrator") as mock_narrator_cls:
			mock_narrator = MagicMock()
			mock_narrator_cls.return_value = mock_narrator
			code_generator_mod.run("cria um addon simples", "kimi-k2.7-code", {})

		mock_narrator.flush.assert_called_once()

	def test_rodada_de_tool_results_tambem_recebe_on_chunk(self):
		validate_call = MagicMock()
		validate_call.function.name = "validate_import"
		validate_call.function.arguments = '{"module_name": "requests"}'
		validate_call.id = "call_1"

		resp_com_tool_call = MagicMock()
		resp_com_tool_call.content = ""
		resp_com_tool_call.tool_calls = [validate_call]
		resp_com_tool_call.tokens_used = 5

		resp_final = MagicMock()
		resp_final.content = "```python:globalPlugins/X/__init__.py\npass\n```"
		resp_final.tool_calls = None
		resp_final.tokens_used = 10

		client = MagicMock()
		client._provider = "ollama"
		client.chat.side_effect = [resp_com_tool_call, resp_final]

		with patch.object(code_generator_mod, "create_llm_client", return_value=client), \
			 patch.object(code_generator_mod, "_verificar_codigo_gerado", side_effect=lambda c, m, **kw: c):
			code_generator_mod.run("cria um addon simples", "kimi-k2.7-code", {})

		assert client.chat.call_count == 2
		for call in client.chat.call_args_list:
			assert callable(call.kwargs.get("on_chunk"))

	def test_ultima_rodada_de_tool_calling_forca_tool_choice_none(self):
		"""Causa raiz de "code_generator esgotou N rodadas de tool-calling sem
		resposta final" (2026-07-21, GeminiChatWeb travou aqui ao vivo): sem
		isso, nada impede o modelo de pedir mais uma tool na ultima rodada
		permitida em vez de fechar com a resposta final. max_tool_rounds=3 --
		a 3a chamada a client.chat() (indice 2, apos a inicial + 2 rodadas de
		tool_results) deve vir com tool_choice="none"; as anteriores, sem forcar."""
		def _fake_tool_call(n):
			call = MagicMock()
			call.function.name = "validate_import"
			call.function.arguments = '{"module_name": "requests"}'
			call.id = f"call_{n}"
			resp = MagicMock()
			resp.content = ""
			resp.tool_calls = [call]
			resp.tokens_used = 5
			return resp

		resp_final = MagicMock()
		resp_final.content = "```python:globalPlugins/X/__init__.py\npass\n```"
		resp_final.tool_calls = None
		resp_final.tokens_used = 10

		client = MagicMock()
		client._provider = "ollama"
		# 1a chamada (fora do loop) + 3 rodadas do loop (max_tool_rounds=3):
		# as 2 primeiras ainda pedem tool_calls, a 3a (ultima permitida) finalmente
		# responde -- mas so porque tool_choice="none" foi forcado nela.
		client.chat.side_effect = [
			_fake_tool_call(0), _fake_tool_call(1), _fake_tool_call(2), resp_final,
		]

		with patch.object(code_generator_mod, "create_llm_client", return_value=client), \
			 patch.object(code_generator_mod, "_verificar_codigo_gerado", side_effect=lambda c, m, **kw: c):
			code_generator_mod.run("cria um addon simples", "kimi-k2.7-code", {})

		assert client.chat.call_count == 4
		tool_choices = [call.kwargs.get("tool_choice") for call in client.chat.call_args_list]
		assert tool_choices == [None, None, None, "none"]

	def test_narracao_de_estrutura_usa_truncate_at_word_nao_slice_bruto(self):
		"""v3.24.0: bug real -- prompt[:200] cortava no meio de uma palavra
		e narrate() ecoava o fragmento quebrado pro usuario."""
		import inspect
		src = inspect.getsource(code_generator_mod.run)
		assert "_truncate_at_word(prompt, 200)" in src
		assert "prompt[:200]" not in src

	def test_nao_narra_mais_antes_de_validate_import(self):
		"""Regressao: narrate() 'verificando se o pacote X existe' (antes)
		foi removido -- duplicava a narracao ao vivo do proprio modelo."""
		import inspect
		src = inspect.getsource(code_generator_mod.run)
		assert 'narrate(f"verificando se o pacote' not in src

	def test_ainda_narra_resultado_real_do_search_web(self):
		"""'encontrei resultados' fica -- e um fato que o modelo so veria
		no proximo turno, nao duplica a narracao ao vivo.

		v3.25.0: a chamada narrate() saiu de run() e foi pro helper
		_dispatch_tool_call() (extraido pra permitir parallel tool calling)."""
		import inspect
		src = inspect.getsource(code_generator_mod._dispatch_tool_call)
		assert 'narrate(f"encontrei resultados sobre' in src
