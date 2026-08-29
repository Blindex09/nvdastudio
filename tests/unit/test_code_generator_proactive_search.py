import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ===========================================================================
# 1. _search_web_tool — funcao auxiliar
# ===========================================================================

class TestSearchWebTool:
    """_search_web_tool deve: checar cache, chamar researcher, retornar dict."""

    def test_cache_hit_nao_chama_researcher(self, tmp_path):
        """Com cache quente, _search_web_tool nao deve chamar web_researcher."""
        from unittest.mock import patch
        import nvdastudio.memory.session_memory as sm_mod
        orig = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "mem.json")
        from nvdastudio.memory.session_memory import SessionMemory
        mem = SessionMemory()
        mem.save_web_knowledge(
            topic="elevenlabs",
            content="ElevenLabs SDK 1.x: client = ElevenLabs(api_key=...)",
            source_url="",
            year=2026,
        )
        try:
            with patch("nvdastudio.sub_agents.web_researcher.create_llm_client") as mock_client:
                from nvdastudio.sub_agents.code_generator import _search_web_tool
                result = _search_web_tool("elevenlabs", _mem=mem)
                mock_client.assert_not_called()
                assert result["status"] == "cached"
                assert "ElevenLabs" in result["content"]
        finally:
            mem.close()

            sm_mod._DB_PATH = orig

    def test_cache_miss_chama_researcher(self, tmp_path):
        """Com cache vazio, deve chamar web_researcher."""
        from unittest.mock import patch, MagicMock
        import nvdastudio.memory.session_memory as sm_mod
        orig = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "mem.json")
        from nvdastudio.memory.session_memory import SessionMemory
        empty_mem = SessionMemory()

        mock_resp = MagicMock()
        mock_resp.content = "R " * 200
        mock_resp.executed_tools = []
        mock_resp.tokens_used = 0
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_resp

        try:
            with patch("nvdastudio.sub_agents.web_researcher.create_llm_client",
                       return_value=mock_client):
                from nvdastudio.sub_agents.code_generator import _search_web_tool
                result = _search_web_tool("google-generativeai", _mem=empty_mem)
                assert mock_client.chat.call_count >= 1
                assert result["status"] == "searched"
        finally:
            empty_mem.close()
            sm_mod._DB_PATH = orig

    def test_retorna_dict_com_campos_obrigatorios(self, tmp_path):
        """Resultado sempre tem status, query e content."""
        from unittest.mock import patch, MagicMock
        import nvdastudio.memory.session_memory as sm_mod
        orig = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "mem.json")
        from nvdastudio.memory.session_memory import SessionMemory
        empty_mem = SessionMemory()

        mock_resp = MagicMock()
        mock_resp.content = "S " * 200
        mock_resp.executed_tools = []
        mock_resp.tokens_used = 0
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_resp

        try:
            with patch("nvdastudio.sub_agents.web_researcher.create_llm_client",
                       return_value=mock_client):
                from nvdastudio.sub_agents.code_generator import _search_web_tool
                result = _search_web_tool("requests", _mem=empty_mem)
                assert "status" in result
                assert "query" in result
                assert "content" in result
        finally:
            empty_mem.close()
            sm_mod._DB_PATH = orig

    def test_erro_no_researcher_retorna_status_error(self, tmp_path):
        """Se web_researcher falhar, retorna dict com status='error' sem lancar excecao."""
        from unittest.mock import patch
        import nvdastudio.memory.session_memory as sm_mod
        orig = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "mem.json")
        from nvdastudio.memory.session_memory import SessionMemory
        empty_mem = SessionMemory()

        try:
            with patch("nvdastudio.sub_agents.web_researcher.create_llm_client",
                       side_effect=RuntimeError("Falha simulada")):
                from nvdastudio.sub_agents.code_generator import _search_web_tool
                result = _search_web_tool("qualquer-pacote", _mem=empty_mem)
                assert result["status"] == "error"
                assert "content" in result
        finally:
            empty_mem.close()
            sm_mod._DB_PATH = orig


# ===========================================================================
# 2. code_generator — tool search_web na lista de tools
# ===========================================================================

class TestCodeGeneratorSearchWebTool:
    """O code_generator deve expor search_web como tool disponivel para o LLM."""

    def test_tools_contem_search_web(self):
        """A lista de tools deve incluir search_web alem de validate_import."""
        # Inspeciona o codigo fonte — tools sao definidas dentro do run()
        import inspect
        from nvdastudio.sub_agents import code_generator
        src = inspect.getsource(code_generator)
        assert '"search_web"' in src or "'search_web'" in src, (
            "Tool search_web nao encontrada no code_generator. "
            "O LLM nao conseguira pesquisar proativamente."
        )

    def test_search_web_tem_descricao_semantica(self):
        """Descricao da tool search_web deve orientar o modelo a usá-la."""
        import inspect
        from nvdastudio.sub_agents import code_generator
        src = inspect.getsource(code_generator)
        idx = src.find('"search_web"')
        if idx == -1:
            idx = src.find("'search_web'")
        assert idx != -1, "search_web nao encontrada"
        trecho = src[idx:idx+500]
        assert "description" in trecho or "descricao" in trecho.lower(), (
            "Tool search_web precisa de descricao para o LLM saber quando usar"
        )


# ===========================================================================
# 3. code_generator — model chama search_web, resultado volta ao modelo
# ===========================================================================

class TestCodeGeneratorSearchWebIntegrado:
    """O LLM pode chamar search_web e receber o resultado como tool_result."""

    def test_tool_call_search_web_processado(self, tmp_path):
        """
        Quando o modelo emite tool_call search_web, o code_generator deve
        executar _search_web_tool e retornar o resultado ao modelo.
        """
        from unittest.mock import patch, MagicMock
        import json
        import nvdastudio.memory.session_memory as sm_mod
        orig = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "mem.json")

        # Primeira resposta do LLM: tool_call para search_web
        tc = MagicMock()
        tc.id = "tc_001"
        tc.function.name = "search_web"
        tc.function.arguments = json.dumps({"query": "google-generativeai 2026"})

        resp_with_tool = MagicMock()
        resp_with_tool.content = ""
        resp_with_tool.tool_calls = [tc]
        resp_with_tool.tokens_used = 10

        # Segunda resposta: codigo gerado apos receber resultado da pesquisa
        tool_results_received = []
        resp_final = MagicMock()
        resp_final.content = "```python:globalPlugins/X/__init__.py\npass\n```"
        resp_final.tool_calls = None
        resp_final.tokens_used = 50

        call_count = [0]
        def fake_chat(prompt, system_override=None, tools=None,
                      tool_results=None, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return resp_with_tool
            # Segunda chamada: verifica que tool_results chegou
            if tool_results:
                tool_results_received.extend(tool_results)
            return resp_final

        mock_client = MagicMock()
        mock_client.chat.side_effect = fake_chat

        fake_mem = MagicMock()
        fake_mem.get_dep_failures.return_value = []
        fake_mem.get_web_knowledge.return_value = []

        try:
            with patch("nvdastudio.sub_agents.code_generator.create_llm_client",
                       return_value=mock_client):
                with patch("nvdastudio.sub_agents.code_generator.memory", fake_mem):
                    with patch("nvdastudio.sub_agents.code_generator.get_docs_code_generation",
                               return_value=""):
                        # Mocka o researcher para nao chamar PyPI real
                        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client",
                                   return_value=MagicMock(chat=MagicMock(
                                       return_value=MagicMock(
                                           content="T " * 200,
                                           executed_tools=[],
                                           tokens_used=0
                                       )
                                   ))):
                            from nvdastudio.sub_agents.code_generator import run
                            run("crie addon com google-generativeai", "modelo", {})

            # Verifica que o resultado da tool chegou ao modelo
            assert len(tool_results_received) >= 1, (
                "O resultado de search_web deve ter sido enviado de volta ao LLM"
            )
            # Verifica que algum tool_result tem tool_call_id da nossa tool call
            ids = [tr.get("tool_call_id", "") for tr in tool_results_received]
            assert "tc_001" in ids, (
                f"tool_call_id tc_001 deve estar nos resultados enviados ao LLM. "
                f"IDs recebidos: {ids}"
            )
        finally:
            sm_mod._DB_PATH = orig

    def test_resultado_search_web_contem_conteudo(self, tmp_path):
        """
        O conteudo retornado pela tool search_web deve chegar ao LLM
        como JSON com campo 'content'.
        """
        from unittest.mock import patch, MagicMock
        import json
        import nvdastudio.memory.session_memory as sm_mod
        orig = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "mem.json")

        tc = MagicMock()
        tc.id = "tc_002"
        tc.function.name = "search_web"
        tc.function.arguments = json.dumps({"query": "elevenlabs SDK python 2026"})

        resp_with_tool = MagicMock()
        resp_with_tool.content = ""
        resp_with_tool.tool_calls = [tc]
        resp_with_tool.tokens_used = 10

        tool_content_received = []
        resp_final = MagicMock()
        resp_final.content = "```python:globalPlugins/X/__init__.py\npass\n```"
        resp_final.tool_calls = None
        resp_final.tokens_used = 50

        call_count = [0]
        def fake_chat(prompt, system_override=None, tools=None,
                      tool_results=None, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return resp_with_tool
            if tool_results:
                for tr in tool_results:
                    tool_content_received.append(tr.get("content", ""))
            return resp_final

        mock_client = MagicMock()
        mock_client.chat.side_effect = fake_chat

        fake_mem = MagicMock()
        fake_mem.get_dep_failures.return_value = []
        fake_mem.get_web_knowledge.return_value = []

        try:
            with patch("nvdastudio.sub_agents.code_generator.create_llm_client",
                       return_value=mock_client):
                with patch("nvdastudio.sub_agents.code_generator.memory", fake_mem):
                    with patch("nvdastudio.sub_agents.code_generator.get_docs_code_generation",
                               return_value=""):
                        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client",
                                   return_value=MagicMock(chat=MagicMock(
                                       return_value=MagicMock(
                                           content="U " * 200,
                                           executed_tools=[],
                                           tokens_used=0
                                       )
                                   ))):
                            from nvdastudio.sub_agents.code_generator import run
                            run("crie addon elevenlabs", "modelo", {})

            assert len(tool_content_received) >= 1
            # O conteudo deve ser JSON com campo 'content'
            for content_str in tool_content_received:
                try:
                    parsed = json.loads(content_str)
                    assert "content" in parsed, (
                        f"Resultado da tool deve ter campo 'content'. Recebido: {parsed}"
                    )
                    break
                except json.JSONDecodeError:
                    pass
            else:
                # Se nenhum era JSON valido, verifica se ao menos tinha conteudo
                assert any(c for c in tool_content_received), (
                    "Tool result deve ter conteudo"
                )
        finally:
            sm_mod._DB_PATH = orig



class TestCodeGeneratorOllamaCloudCompat:
	"""Regressao do plano aa1600dd (2026-05-10).

	Ollama Cloud entrega function.arguments como dict ja parseado em vez de
	string JSON. O codigo chamava json.loads(tc_args) cego, todas as tool_calls
	quebravam com 'the JSON object must be str, bytes or bytearray, not dict'
	e o LLM acabava retornando 0 chars na rodada seguinte.
	"""

	def test_validate_import_aceita_arguments_como_dict(self, tmp_path):
		"""O parser deve aceitar function.arguments como dict (Ollama Cloud)."""
		from unittest.mock import patch, MagicMock
		import nvdastudio.memory.session_memory as sm_mod
		orig = sm_mod._DB_PATH
		sm_mod._DB_PATH = str(tmp_path / "mem.json")

		tc = MagicMock()
		tc.id = "tc_dict_01"
		tc.function.name = "validate_import"
		tc.function.arguments = {"module_name": "requests"}

		resp_with_tool = MagicMock()
		resp_with_tool.content = ""
		resp_with_tool.tool_calls = [tc]
		resp_with_tool.tokens_used = 10

		tool_results_received = []
		resp_final = MagicMock()
		resp_final.content = "```python:globalPlugins/X/__init__.py\npass\n```"
		resp_final.tool_calls = None
		resp_final.tokens_used = 50

		call_count = [0]
		def fake_chat(prompt, system_override=None, tools=None,
					  tool_results=None, **kwargs):
			call_count[0] += 1
			if call_count[0] == 1:
				return resp_with_tool
			if tool_results:
				tool_results_received.extend(tool_results)
			return resp_final

		mock_client = MagicMock()
		mock_client.chat.side_effect = fake_chat

		fake_mem = MagicMock()
		fake_mem.get_dep_failures.return_value = []
		fake_mem.get_web_knowledge.return_value = []

		try:
			with patch("nvdastudio.sub_agents.code_generator.create_llm_client",
					   return_value=mock_client):
				with patch("nvdastudio.sub_agents.code_generator.memory", fake_mem):
					with patch("nvdastudio.sub_agents.code_generator.get_docs_code_generation",
							   return_value=""):
						from nvdastudio.sub_agents.code_generator import run
						run("crie addon", "modelo", {})

			ids = [tr.get("tool_call_id", "") for tr in tool_results_received]
			assert "tc_dict_01" in ids, (
				"tool_call com arguments=dict deve ser processado sem crash. "
				f"Recebidos: {ids}"
			)
		finally:
			sm_mod._DB_PATH = orig


	def test_search_web_aceita_arguments_como_dict(self, tmp_path):
		"""search_web tambem precisa aceitar arguments como dict."""
		from unittest.mock import patch, MagicMock
		import nvdastudio.memory.session_memory as sm_mod
		orig = sm_mod._DB_PATH
		sm_mod._DB_PATH = str(tmp_path / "mem.json")

		tc = MagicMock()
		tc.id = "tc_dict_02"
		tc.function.name = "search_web"
		tc.function.arguments = {"query": "yt-dlp 2026"}

		resp_with_tool = MagicMock()
		resp_with_tool.content = ""
		resp_with_tool.tool_calls = [tc]
		resp_with_tool.tokens_used = 10

		tool_results_received = []
		resp_final = MagicMock()
		resp_final.content = "```python:globalPlugins/X/__init__.py\npass\n```"
		resp_final.tool_calls = None
		resp_final.tokens_used = 50

		call_count = [0]
		def fake_chat(prompt, system_override=None, tools=None,
					  tool_results=None, **kwargs):
			call_count[0] += 1
			if call_count[0] == 1:
				return resp_with_tool
			if tool_results:
				tool_results_received.extend(tool_results)
			return resp_final

		mock_client = MagicMock()
		mock_client.chat.side_effect = fake_chat

		fake_mem = MagicMock()
		fake_mem.get_dep_failures.return_value = []
		fake_mem.get_web_knowledge.return_value = []

		try:
			with patch("nvdastudio.sub_agents.code_generator.create_llm_client",
					   return_value=mock_client):
				with patch("nvdastudio.sub_agents.code_generator.memory", fake_mem):
					with patch("nvdastudio.sub_agents.code_generator.get_docs_code_generation",
							   return_value=""):
						with patch("nvdastudio.sub_agents.web_researcher.create_llm_client",
								   return_value=MagicMock(chat=MagicMock(
									   return_value=MagicMock(
										   content="V " * 200,
										   executed_tools=[],
										   tokens_used=0
									   )
								   ))):
							from nvdastudio.sub_agents.code_generator import run
							run("crie addon", "modelo", {})

			ids = [tr.get("tool_call_id", "") for tr in tool_results_received]
			assert "tc_dict_02" in ids, (
				"search_web com arguments=dict deve ser processado sem crash. "
				f"Recebidos: {ids}"
			)
		finally:
			sm_mod._DB_PATH = orig
