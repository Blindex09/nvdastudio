from unittest.mock import MagicMock, patch


class TestSearchWebToolSchema:
    def test_schema_tem_nome_search_web(self):
        from nvdastudio.sub_agents._base import _SEARCH_WEB_TOOL_SCHEMA
        assert _SEARCH_WEB_TOOL_SCHEMA["function"]["name"] == "search_web"

    def test_schema_exige_parametro_query(self):
        from nvdastudio.sub_agents._base import _SEARCH_WEB_TOOL_SCHEMA
        params = _SEARCH_WEB_TOOL_SCHEMA["function"]["parameters"]
        assert "query" in params["properties"]
        assert "query" in params["required"]


class TestSearchWebToolFuncao:
    """_search_web_tool: checa cache, chama web_researcher.run(), retorna dict."""

    def test_cache_hit_nao_chama_researcher(self):
        from nvdastudio.sub_agents._base import _search_web_tool

        mock_mem = MagicMock()
        mock_mem.get_web_knowledge.return_value = [{"content": "resultado em cache", "year": 2026}]

        with patch("nvdastudio.sub_agents.web_researcher.run") as mock_run:
            result = _search_web_tool("elevenlabs", _mem=mock_mem)

        mock_run.assert_not_called()
        assert result["status"] == "cached"
        assert "resultado em cache" in result["content"]

    def test_cache_miss_chama_researcher(self):
        from nvdastudio.sub_agents._base import _search_web_tool

        mock_mem = MagicMock()
        mock_mem.get_web_knowledge.return_value = None

        with patch("nvdastudio.sub_agents.web_researcher.run", return_value="resultado real da pesquisa"):
            result = _search_web_tool("google-generativeai", _mem=mock_mem)

        assert result["status"] == "searched"
        assert "resultado real" in result["content"]

    def test_erro_no_researcher_retorna_status_error(self):
        from nvdastudio.sub_agents._base import _search_web_tool

        mock_mem = MagicMock()
        mock_mem.get_web_knowledge.return_value = None

        with patch("nvdastudio.sub_agents.web_researcher.run", side_effect=RuntimeError("timeout")):
            result = _search_web_tool("qualquer-pacote", _mem=mock_mem)

        assert result["status"] == "error"

    def test_retorna_dict_com_campos_obrigatorios(self):
        from nvdastudio.sub_agents._base import _search_web_tool

        mock_mem = MagicMock()
        mock_mem.get_web_knowledge.return_value = None

        with patch("nvdastudio.sub_agents.web_researcher.run", return_value="conteudo"):
            result = _search_web_tool("requests", _mem=mock_mem)

        assert set(result.keys()) >= {"status", "query", "content"}


class TestDispatchSearchWebToolCall:
    def test_ignora_tool_call_desconhecida(self):
        from nvdastudio.sub_agents._base import _dispatch_search_web_tool_call

        fake_tc = MagicMock()
        fake_tc.function.name = "validate_import"
        fake_tc.function.arguments = "{}"

        result = _dispatch_search_web_tool_call(fake_tc)
        assert result is None

    def test_processa_search_web_e_retorna_tool_result(self):
        from nvdastudio.sub_agents._base import _dispatch_search_web_tool_call

        fake_tc = MagicMock()
        fake_tc.id = "call_1"
        fake_tc.function.name = "search_web"
        fake_tc.function.arguments = '{"query": "requests python"}'

        with patch(
            "nvdastudio.sub_agents._base._search_web_tool",
            return_value={"status": "searched", "query": "requests python", "content": "lib HTTP"},
        ):
            result = _dispatch_search_web_tool_call(fake_tc)

        assert result["tool_call_id"] == "call_1"
        assert result["tool_name"] == "search_web"
        assert result["role"] == "tool"
        assert "lib HTTP" in result["content"]

    def test_aceita_arguments_como_dict(self):
        """Alguns provedores ja entregam .arguments como dict, nao string JSON."""
        from nvdastudio.sub_agents._base import _dispatch_search_web_tool_call

        fake_tc = MagicMock()
        fake_tc.id = "call_2"
        fake_tc.function.name = "search_web"
        fake_tc.function.arguments = {"query": "requests"}

        with patch(
            "nvdastudio.sub_agents._base._search_web_tool",
            return_value={"status": "searched", "query": "requests", "content": "ok"},
        ):
            result = _dispatch_search_web_tool_call(fake_tc)

        assert result is not None


def _fake_tool_call(call_id: str, query: str):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = "search_web"
    tc.function.arguments = f'{{"query": "{query}"}}'
    return tc


class TestRunSubAgentEnableWebSearch:
    """_run_sub_agent(enable_web_search=True): oferece a tool, roda o loop,
    fecha com tool_choice='none' na ultima rodada."""

    def test_sem_enable_web_search_nao_oferece_tool(self):
        from nvdastudio.sub_agents._base import _run_sub_agent

        resp = MagicMock()
        resp.content = "resultado direto"
        resp.tool_calls = None
        resp.tokens_used = 10

        fake_client = MagicMock()
        fake_client.chat.return_value = resp

        with patch("nvdastudio.sub_agents._base.create_llm_client", return_value=fake_client):
            result = _run_sub_agent("system", "prompt", "modelo-x", {})

        assert result == "resultado direto"
        _, kwargs = fake_client.chat.call_args
        assert "tools" not in kwargs

    def test_enable_web_search_oferece_a_tool(self):
        from nvdastudio.sub_agents._base import _run_sub_agent, _SEARCH_WEB_TOOL_SCHEMA

        resp = MagicMock()
        resp.content = "resultado sem pesquisar"
        resp.tool_calls = None
        resp.tokens_used = 10

        fake_client = MagicMock()
        fake_client.chat.return_value = resp

        with patch("nvdastudio.sub_agents._base.create_llm_client", return_value=fake_client):
            _run_sub_agent("system", "prompt", "modelo-x", {}, enable_web_search=True)

        _, kwargs = fake_client.chat.call_args
        assert _SEARCH_WEB_TOOL_SCHEMA in kwargs["tools"]

    def test_resolve_tool_call_e_continua_ate_resposta_final(self):
        from nvdastudio.sub_agents._base import _run_sub_agent

        resp_com_tool_call = MagicMock()
        resp_com_tool_call.tool_calls = [_fake_tool_call("call_1", "requests python")]
        resp_com_tool_call.content = ""
        resp_com_tool_call.tokens_used = 5

        resp_final = MagicMock()
        resp_final.tool_calls = None
        resp_final.content = "resposta final apos pesquisar"
        resp_final.tokens_used = 20

        fake_client = MagicMock()
        fake_client.chat.side_effect = [resp_com_tool_call, resp_final]

        with patch("nvdastudio.sub_agents._base.create_llm_client", return_value=fake_client):
            with patch(
                "nvdastudio.sub_agents._base._search_web_tool",
                return_value={"status": "searched", "query": "requests python", "content": "ok"},
            ):
                result = _run_sub_agent("system", "prompt", "modelo-x", {}, enable_web_search=True)

        assert result == "resposta final apos pesquisar"
        assert fake_client.chat.call_count == 2
        _, second_kwargs = fake_client.chat.call_args_list[1]
        assert second_kwargs["tool_results"][0]["tool_name"] == "search_web"

    def test_forca_tool_choice_none_na_ultima_rodada(self):
        """Se o modelo insiste em tool_calls ate a ultima rodada permitida,
        a chamada final deve forcar tool_choice='none' (mesmo padrao de
        code_generator.py 3.23.0) pra garantir resposta em texto."""
        from nvdastudio.sub_agents._base import _run_sub_agent, _MAX_SEARCH_TOOL_ROUNDS

        respostas_com_tool_call = [
            MagicMock(tool_calls=[_fake_tool_call(f"call_{i}", "q")], content="", tokens_used=5)
            for i in range(_MAX_SEARCH_TOOL_ROUNDS)
        ]
        resp_final = MagicMock(tool_calls=None, content="finalizado", tokens_used=10)

        fake_client = MagicMock()
        fake_client.chat.side_effect = [*respostas_com_tool_call, resp_final]

        with patch("nvdastudio.sub_agents._base.create_llm_client", return_value=fake_client):
            with patch(
                "nvdastudio.sub_agents._base._search_web_tool",
                return_value={"status": "searched", "query": "q", "content": "ok"},
            ):
                result = _run_sub_agent("system", "prompt", "modelo-x", {}, enable_web_search=True)

        assert result == "finalizado"
        last_call_kwargs = fake_client.chat.call_args_list[-1][1]
        assert last_call_kwargs.get("tool_choice") == "none"

    def test_enable_web_search_com_final_tool_oferece_as_duas_tools(self):
        from nvdastudio.sub_agents._base import _run_sub_agent

        resp = MagicMock()
        resp.content = "relatorio bruto"
        resp.tool_calls = None
        resp.tokens_used = 10

        fake_client = MagicMock()
        fake_client.chat.return_value = resp

        final_tool = {
            "name": "entregar_resultado",
            "description": "entrega o resultado",
            "param_name": "resultado",
        }

        with patch("nvdastudio.sub_agents._base.create_llm_client", return_value=fake_client):
            _run_sub_agent(
                "system", "prompt", "modelo-x", {},
                enable_web_search=True, final_tool=final_tool,
            )

        _, kwargs = fake_client.chat.call_args
        tool_names = {t["function"]["name"] for t in kwargs["tools"]}
        assert tool_names == {"search_web", "entregar_resultado"}


class TestSubAgentesComEnableWebSearchLigado:
    """1.18.0: accessibility_auditor.py e manifest_builder.py ligam
    enable_web_search=True. design_review_agent.py fica de fora
    deliberadamente (3 chamadas sequenciais, ja confirmado nesta sessao
    como maior consumidor de tokens de um step e contribuinte de um 429
    real -- ligar busca web ali multiplicaria esse custo)."""

    def test_accessibility_auditor_liga_enable_web_search(self):
        from nvdastudio.sub_agents import accessibility_auditor as mod

        with patch.object(mod, "_run_sub_agent", return_value="relatorio") as mock_run:
            mod.run("audite este addon", "modelo-x", {})

        _, kwargs = mock_run.call_args
        assert kwargs.get("enable_web_search") is True

    def test_manifest_builder_liga_enable_web_search(self):
        from nvdastudio.sub_agents import manifest_builder as mod

        with patch.object(mod, "_run_sub_agent", return_value="name = Addon\n") as mock_run:
            mod.run("crie o manifest", "modelo-x", {})

        _, kwargs = mock_run.call_args
        assert kwargs.get("enable_web_search") is True

    def test_design_review_agent_nao_liga_enable_web_search(self):
        """Confirma a exclusao deliberada -- nenhuma das 3 chamadas
        (challenger/guardian/advocate) deve pedir enable_web_search=True."""
        from nvdastudio.sub_agents import design_review_agent as mod

        resp = MagicMock()
        resp.content = "critica"
        resp.tool_calls = None
        resp.tokens_used = 10
        fake_client = MagicMock()
        fake_client.chat.return_value = resp

        with patch("nvdastudio.sub_agents._base.create_llm_client", return_value=fake_client):
            mod.run("revise este design", "modelo-x", {})

        for call in fake_client.chat.call_args_list:
            assert "search_web" not in [
                t["function"]["name"] for t in call.kwargs.get("tools", [])
            ]
