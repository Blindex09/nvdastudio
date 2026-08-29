from unittest.mock import MagicMock, patch



class TestOnDemandWebSearch:
    def test_on_demand_web_search_usa_ollama_web_search_quando_disponivel(self):
        from nvdastudio.sub_agents.web_researcher import on_demand_web_search

        fake_client = MagicMock(spec=["web_search"])
        fake_client.web_search.return_value = "Resultados da web para: como usar requests\n[1] Requests"

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client", return_value=fake_client):
            result = on_demand_web_search("como usar requests")

        fake_client.web_search.assert_called_once_with("como usar requests")
        assert "Requests" in result

    def test_on_demand_web_search_usa_native_web_search_para_outros_provedores(self):
        from nvdastudio.sub_agents.web_researcher import on_demand_web_search

        fake_client = MagicMock(spec=["native_web_search", "_provider"])
        fake_client._provider = "openai"
        fake_client.native_web_search.return_value = "Requests e uma biblioteca HTTP para Python."

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client", return_value=fake_client):
            result = on_demand_web_search("como usar requests")

        fake_client.native_web_search.assert_called_once_with("como usar requests")
        assert "biblioteca HTTP" in result

    def test_on_demand_web_search_vazio_se_client_nao_suporta_pesquisa(self):
        from nvdastudio.sub_agents.web_researcher import on_demand_web_search

        fake_client = MagicMock(spec=[])
        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client", return_value=fake_client):
            result = on_demand_web_search("como usar requests")

        assert result == ""

    def test_on_demand_web_search_vazio_se_falha_criar_client(self):
        from nvdastudio.sub_agents.web_researcher import on_demand_web_search
        from nvdastudio.ai.llm_client import LLMClientError

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client", side_effect=LLMClientError("sem chave")):
            result = on_demand_web_search("como usar requests")

        assert result == ""

    def test_on_demand_web_search_vazio_se_pesquisa_lanca_excecao(self):
        from nvdastudio.sub_agents.web_researcher import on_demand_web_search

        fake_client = MagicMock(spec=["web_search"])
        fake_client.web_search.side_effect = RuntimeError("timeout")

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client", return_value=fake_client):
            result = on_demand_web_search("como usar requests")

        assert result == ""

    def test_nao_importa_mais_ddgs(self):
        """Regressao: web_researcher.py nao deve mais importar/usar ddgs em
        codigo real (a palavra pode aparecer em prosa no changelog)."""
        import inspect
        import nvdastudio.sub_agents.web_researcher as mod
        src = inspect.getsource(mod)
        assert "from ddgs import" not in src
        assert "import ddgs" not in src
        assert "DDGS()" not in src

class TestFallbackWebSearch:
    """
    v4.4.0: on_demand_web_search() cai em _fallback_web_search() (Tavily
    primeiro, depois Exa) quando a busca nativa do provedor ativo nao esta
    disponivel ou falha/retorna vazio. Ambas as chaves sao opcionais.
    """

    def test_fallback_sem_nenhuma_chave_retorna_vazio(self):
        from nvdastudio.sub_agents.web_researcher import _fallback_web_search

        with patch("nvdastudio.gui.settings_panel.get_api_key", return_value=""):
            result = _fallback_web_search("como usar requests")

        assert result == ""

    def test_fallback_usa_tavily_quando_chave_configurada(self):
        from nvdastudio.sub_agents.web_researcher import _fallback_web_search

        with patch(
            "nvdastudio.gui.settings_panel.get_api_key",
            side_effect=lambda p: "tavily-key" if p == "tavily" else "",
        ):
            with patch(
                "nvdastudio.sub_agents.web_researcher._tavily_search",
                return_value="Tavily: requests e uma lib HTTP",
            ) as mock_tavily:
                result = _fallback_web_search("como usar requests")

        mock_tavily.assert_called_once_with("como usar requests", "tavily-key")
        assert "Tavily" in result

    def test_fallback_cai_para_exa_se_tavily_sem_chave(self):
        from nvdastudio.sub_agents.web_researcher import _fallback_web_search

        with patch(
            "nvdastudio.gui.settings_panel.get_api_key",
            side_effect=lambda p: "exa-key" if p == "exa" else "",
        ):
            with patch(
                "nvdastudio.sub_agents.web_researcher._exa_search",
                return_value="Exa: requests e uma lib HTTP",
            ) as mock_exa:
                result = _fallback_web_search("como usar requests")

        mock_exa.assert_called_once_with("como usar requests", "exa-key")
        assert "Exa" in result

    def test_fallback_cai_para_exa_se_tavily_falha(self):
        from nvdastudio.sub_agents.web_researcher import _fallback_web_search

        with patch(
            "nvdastudio.gui.settings_panel.get_api_key",
            side_effect=lambda p: {"tavily": "tavily-key", "exa": "exa-key"}.get(p, ""),
        ):
            with patch(
                "nvdastudio.sub_agents.web_researcher._tavily_search",
                side_effect=RuntimeError("timeout"),
            ):
                with patch(
                    "nvdastudio.sub_agents.web_researcher._exa_search",
                    return_value="Exa: resultado de backup",
                ) as mock_exa:
                    result = _fallback_web_search("query")

        mock_exa.assert_called_once()
        assert "Exa" in result

    def test_fallback_retorna_vazio_se_ambos_falham(self):
        from nvdastudio.sub_agents.web_researcher import _fallback_web_search

        with patch(
            "nvdastudio.gui.settings_panel.get_api_key",
            side_effect=lambda p: {"tavily": "k1", "exa": "k2"}.get(p, ""),
        ):
            with patch(
                "nvdastudio.sub_agents.web_researcher._tavily_search",
                side_effect=RuntimeError("down"),
            ):
                with patch(
                    "nvdastudio.sub_agents.web_researcher._exa_search",
                    side_effect=RuntimeError("down"),
                ):
                    result = _fallback_web_search("query")

        assert result == ""

    def test_on_demand_web_search_usa_fallback_quando_client_nao_suporta(self):
        from nvdastudio.sub_agents.web_researcher import on_demand_web_search

        fake_client = MagicMock(spec=[])
        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client", return_value=fake_client):
            with patch(
                "nvdastudio.sub_agents.web_researcher._fallback_web_search",
                return_value="Resultado via fallback",
            ) as mock_fallback:
                result = on_demand_web_search("como usar requests")

        mock_fallback.assert_called_once_with("como usar requests")
        assert "fallback" in result.lower()

    def test_on_demand_web_search_usa_fallback_quando_nativa_lanca_excecao(self):
        from nvdastudio.sub_agents.web_researcher import on_demand_web_search

        fake_client = MagicMock(spec=["web_search"])
        fake_client.web_search.side_effect = RuntimeError("timeout")
        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client", return_value=fake_client):
            with patch(
                "nvdastudio.sub_agents.web_researcher._fallback_web_search",
                return_value="Resultado via fallback",
            ) as mock_fallback:
                result = on_demand_web_search("como usar requests")

        mock_fallback.assert_called_once_with("como usar requests")
        assert "fallback" in result.lower()

    def test_on_demand_web_search_usa_fallback_quando_nativa_retorna_vazio(self):
        from nvdastudio.sub_agents.web_researcher import on_demand_web_search

        fake_client = MagicMock(spec=["web_search"])
        fake_client.web_search.return_value = ""
        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client", return_value=fake_client):
            with patch(
                "nvdastudio.sub_agents.web_researcher._fallback_web_search",
                return_value="Resultado via fallback",
            ) as mock_fallback:
                result = on_demand_web_search("como usar requests")

        mock_fallback.assert_called_once_with("como usar requests")
        assert "fallback" in result.lower()

    def test_on_demand_web_search_nao_chama_fallback_quando_nativa_funciona(self):
        from nvdastudio.sub_agents.web_researcher import on_demand_web_search

        fake_client = MagicMock(spec=["web_search"])
        fake_client.web_search.return_value = "Resultado nativo real"
        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client", return_value=fake_client):
            with patch("nvdastudio.sub_agents.web_researcher._fallback_web_search") as mock_fallback:
                result = on_demand_web_search("como usar requests")

        mock_fallback.assert_not_called()
        assert "nativo" in result


class TestTavilyExaSearchFormatoRequisicao:
    """Formato de request confirmado via pesquisa dedicada 2026-08-04 contra
    docs.tavily.com/documentation/api-reference/endpoint/search e
    docs.exa.ai/reference/search."""

    def test_tavily_search_monta_request_correto(self):
        from nvdastudio.sub_agents import web_researcher as mod

        fake_response = MagicMock()
        fake_response.json.return_value = {
            "results": [
                {"title": "Requests: HTTP for Humans", "url": "https://requests.readthedocs.io", "content": "lib HTTP"},
            ]
        }
        fake_response.raise_for_status.return_value = None
        fake_httpx = MagicMock()
        fake_httpx.post.return_value = fake_response

        with patch("nvdastudio.ai.provider_client._httpx_module", return_value=fake_httpx):
            result = mod._tavily_search("como usar requests", "tavily-key")

        args, kwargs = fake_httpx.post.call_args
        assert args[0] == mod._TAVILY_URL
        assert kwargs["headers"]["Authorization"] == "Bearer tavily-key"
        assert kwargs["json"]["query"] == "como usar requests"
        assert "Requests: HTTP for Humans" in result
        assert "requests.readthedocs.io" in result

    def test_tavily_search_sem_resultados_retorna_vazio(self):
        from nvdastudio.sub_agents import web_researcher as mod

        fake_response = MagicMock()
        fake_response.json.return_value = {"results": []}
        fake_response.raise_for_status.return_value = None
        fake_httpx = MagicMock()
        fake_httpx.post.return_value = fake_response

        with patch("nvdastudio.ai.provider_client._httpx_module", return_value=fake_httpx):
            result = mod._tavily_search("query", "tavily-key")

        assert result == ""

    def test_exa_search_monta_request_correto(self):
        from nvdastudio.sub_agents import web_researcher as mod

        fake_response = MagicMock()
        fake_response.json.return_value = {
            "results": [
                {"title": "Requests docs", "url": "https://requests.readthedocs.io", "text": "lib HTTP"},
            ]
        }
        fake_response.raise_for_status.return_value = None
        fake_httpx = MagicMock()
        fake_httpx.post.return_value = fake_response

        with patch("nvdastudio.ai.provider_client._httpx_module", return_value=fake_httpx):
            result = mod._exa_search("como usar requests", "exa-key")

        args, kwargs = fake_httpx.post.call_args
        assert args[0] == mod._EXA_URL
        assert kwargs["headers"]["x-api-key"] == "exa-key"
        assert kwargs["json"]["query"] == "como usar requests"
        assert "Requests docs" in result

    def test_exa_search_sem_resultados_retorna_vazio(self):
        from nvdastudio.sub_agents import web_researcher as mod

        fake_response = MagicMock()
        fake_response.json.return_value = {"results": []}
        fake_response.raise_for_status.return_value = None
        fake_httpx = MagicMock()
        fake_httpx.post.return_value = fake_response

        with patch("nvdastudio.ai.provider_client._httpx_module", return_value=fake_httpx):
            result = mod._exa_search("query", "exa-key")

        assert result == ""


class TestSynthesizeWebResults:
    def test_synthesize_com_resultados(self):
        from nvdastudio.sub_agents.web_researcher import _synthesize_web_results

        mock_resp = MagicMock()
        mock_resp.content = (
            "**Pacote:** requests\n"
            "**Versao estavel:** 2.31.0\n"
            "**Instalacao:** `pip install requests`"
        )

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client") as MC:
            MC.return_value.chat.return_value = mock_resp
            result = _synthesize_web_results("como usar requests", "Resultado web...")

        assert "requests" in result
        assert "pip install" in result

    def test_synthesize_sem_resultados_retorna_vazio(self):
        from nvdastudio.sub_agents.web_researcher import _synthesize_web_results
        result = _synthesize_web_results("query", "")
        assert result == ""


class TestExtractSourcesBlock:
    """4.2.0: 'Fontes consultadas' no historico -- extracao deterministica da
    secao 'Fontes:' que native_web_search()/web_search() anexam ao resultado
    bruto, sem depender da sintese do LLM preservar URLs."""

    def test_extrai_bloco_de_fontes_quando_presente(self):
        from nvdastudio.sub_agents.web_researcher import _extract_sources_block

        raw = (
            "Resultados da web para: spotify api\n\n"
            "[1] Spotify Web API\ndetalhe\nFonte: https://developer.spotify.com/docs\n\n"
            "Fontes:\n"
            "- Spotify Web API: https://developer.spotify.com/docs"
        )
        result = _extract_sources_block(raw)
        assert "developer.spotify.com" in result
        assert not result.startswith("Fontes:")  # cabecalho bruto removido, sera relabeled pelo caller

    def test_retorna_vazio_quando_nao_ha_secao_de_fontes(self):
        from nvdastudio.sub_agents.web_researcher import _extract_sources_block
        assert _extract_sources_block("texto qualquer sem citacoes") == ""

    def test_retorna_vazio_para_string_vazia(self):
        from nvdastudio.sub_agents.web_researcher import _extract_sources_block
        assert _extract_sources_block("") == ""


class TestRunPropagaFontesConsultadas:
    def test_run_anexa_fontes_consultadas_ao_resultado_final(self):
        from nvdastudio.sub_agents.web_researcher import run

        raw_web = (
            "[1] Spotify Web API\nconteudo\n\n"
            "Fontes:\n- Spotify Web API: https://developer.spotify.com/docs"
        )
        mock_resp = MagicMock()
        mock_resp.content = "**Pacote:** spotipy\n**Instalacao:** `pip install spotipy`"
        mock_memory = MagicMock()
        mock_memory.get_web_knowledge.return_value = None

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client") as MC:
            MC.return_value.chat.return_value = mock_resp
            with patch("nvdastudio.sub_agents.web_researcher.on_demand_web_search", return_value=raw_web):
                result = run("como usar a API do Spotify", "kimi-k2.6", {}, _memory=mock_memory)

        assert "Fontes consultadas:" in result
        assert "developer.spotify.com" in result

    def test_run_sem_fontes_nao_adiciona_secao(self):
        from nvdastudio.sub_agents.web_researcher import run

        mock_resp = MagicMock()
        mock_resp.content = "**Pacote:** requests\n**Instalacao:** `pip install requests`"
        mock_memory = MagicMock()
        mock_memory.get_web_knowledge.return_value = None

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client") as MC:
            MC.return_value.chat.return_value = mock_resp
            with patch("nvdastudio.sub_agents.web_researcher.on_demand_web_search", return_value="resultado sem citacoes"):
                result = run("como usar requests", "kimi-k2.6", {}, _memory=mock_memory)

        assert "Fontes consultadas:" not in result


class TestWebResearcherRunWithOnDemand:
    def test_run_ativa_web_por_decisao_do_agente(self):
        from nvdastudio.sub_agents.web_researcher import run

        mock_resp = MagicMock()
        mock_resp.content = "**Pacote:** requests"
        mock_resp.tokens_used = 42

        mock_memory = MagicMock()
        mock_memory.get_web_knowledge.return_value = None  # cache miss

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client") as MC:
            MC.return_value.chat.return_value = mock_resp
            with patch("nvdastudio.sub_agents.web_researcher.on_demand_web_search") as mock_web:
                mock_web.return_value = "Resultado web real"
                result = run("como usar requests python 3.12", "kimi-k2.6", {}, _memory=mock_memory)

        mock_web.assert_called_once()
        assert "requests" in result

    def test_run_fallback_knowledge_sem_web(self):
        from nvdastudio.sub_agents.web_researcher import run

        mock_resp = MagicMock()
        mock_resp.content = "**Pacote:** os  # stdlib"
        mock_resp.tokens_used = 10
        mock_memory = MagicMock()
        mock_memory.get_web_knowledge.return_value = None

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client") as MC:
            MC.return_value.chat.return_value = mock_resp
            with patch("nvdastudio.sub_agents.web_researcher.on_demand_web_search") as mock_web:
                mock_web.return_value = ""
                result = run("crie um addon simples", "kimi-k2.6", {}, _memory=mock_memory)

        mock_web.assert_called_once()
        assert "stdlib" in result or "os" in result or "ERRO" not in result


class TestExtractTopicEspecificoDoObjetivo:
    """
    4.10.0: achado de auditoria de memoria (Memory Consistency) -- duas
    pesquisas DIFERENTES do mesmo pedido de addon colidiam na mesma chave
    de cache, porque _extract_topic() so pegava os primeiros 150 chars do
    prompt, que sempre comecam com "Tarefa original do usuario: <pedido
    completo>" (identico pra QUALQUER step do mesmo pedido).
    """

    def _prompt(self, objetivo):
        return (
            "Tarefa original do usuario: Crie um addon NVDA complexo chamado "
            "GeminiMultimodal: um assistente multimodal que usa a API do "
            "Google Gemini internamente para acessibilidade de midia.\n\n"
            f"Seu objetivo neste step: {objetivo}\n"
        )

    def test_dois_objetivos_diferentes_do_mesmo_pedido_geram_topicos_diferentes(self):
        from nvdastudio.sub_agents.web_researcher import _extract_topic
        topic_imagem = _extract_topic(self._prompt("Pesquisar a API de descricao de imagem do Gemini"))
        topic_audio = _extract_topic(self._prompt("Pesquisar a API de transcricao de audio do Gemini"))
        assert topic_imagem != topic_audio

    def test_extrai_a_partir_do_marcador_de_objetivo(self):
        from nvdastudio.sub_agents.web_researcher import _extract_topic
        topic = _extract_topic(self._prompt("como usar a lib X"))
        assert topic.startswith("como usar a lib X")
        assert "Tarefa original do usuario" not in topic

    def test_sem_marcador_cai_no_comportamento_antigo(self):
        """Chamada direta/teste sem passar por _build_step_prompt() --
        preserva compatibilidade com o comportamento anterior."""
        from nvdastudio.sub_agents.web_researcher import _extract_topic
        topic = _extract_topic("como usar requests")
        assert topic == "como usar requests"


class TestCorrecaoDeterministicaCodeFence:
    """
    4.8.0: bug 4/5 (web_research devolvendo ```python:arquivo.py``` em vez
    de texto de pesquisa) reproduzido AO VIVO 3/3 tentativas numa rodada
    real de test_e36 (2026-08-09), mesmo com o guard do critic.py (3.10.0)
    ja ativo -- depender so de "rejeita e tenta de novo" nao bastou.
    _correct_code_fence_violation() fecha isso com correcao deterministica
    no proprio web_researcher.py, ANTES do resultado chegar ao Critic.
    """

    def test_has_disallowed_code_fence_detecta_violacao(self):
        from nvdastudio.sub_agents.web_researcher import _has_disallowed_code_fence
        assert _has_disallowed_code_fence("```python:modulo.py\nprint(1)\n```")
        assert not _has_disallowed_code_fence("**Pacote:** requests")

    def test_correcao_bem_sucedida_remove_a_violacao(self):
        from nvdastudio.sub_agents.web_researcher import _correct_code_fence_violation

        mock_resp = MagicMock()
        mock_resp.content = "**Pacote:** requests\n**Confianca:** Alta"

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client") as MC:
            MC.return_value.chat.return_value = mock_resp
            result = _correct_code_fence_violation(
                "```python:modulo.py\nimport requests\n```", "kimi-k2.6",
            )

        assert "```python:" not in result
        assert "requests" in result

    def test_correcao_tambem_falha_remove_bloco_deterministicamente(self):
        """Se ate a chamada corretiva repetir o erro, o bloco proibido e
        removido no CODIGO -- nunca depende so do modelo obedecer."""
        from nvdastudio.sub_agents.web_researcher import _correct_code_fence_violation

        mock_resp = MagicMock()
        mock_resp.content = "```python:modulo.py\nimport requests\n```"

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client") as MC:
            MC.return_value.chat.return_value = mock_resp
            result = _correct_code_fence_violation(
                "Alguma informacao valida ao redor.\n```python:modulo.py\nimport requests\n```\nMais texto.",
                "kimi-k2.6",
            )

        assert "```python:" not in result

    def test_correcao_com_excecao_ainda_remove_bloco(self):
        from nvdastudio.sub_agents.web_researcher import _correct_code_fence_violation
        from nvdastudio.ai.llm_client import LLMClientError

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client",
                   side_effect=LLMClientError("sem chave")):
            result = _correct_code_fence_violation(
                "```python:modulo.py\nimport requests\n```", "kimi-k2.6",
            )

        assert "```python:" not in result

    def test_run_nunca_retorna_bloco_proibido_mesmo_apos_violacao(self):
        """Fim a fim: run() detecta a violacao no resultado do fallback
        knowledge-only e corrige antes de devolver -- o Critic nunca ve o
        padrao proibido."""
        from nvdastudio.sub_agents.web_researcher import run

        bad_resp = MagicMock()
        bad_resp.content = "```python:modulo.py\nimport requests\n```"
        bad_resp.tokens_used = 50
        good_resp = MagicMock()
        good_resp.content = "**Pacote:** requests\n**Confianca:** Alta"

        mock_memory = MagicMock()
        mock_memory.get_web_knowledge.return_value = None

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client") as MC:
            MC.return_value.chat.side_effect = [bad_resp, good_resp]
            with patch("nvdastudio.sub_agents.web_researcher.on_demand_web_search") as mock_web:
                mock_web.return_value = ""
                result = run("como usar requests", "kimi-k2.6", {}, _memory=mock_memory)

        assert "```python:" not in result

    def test_cache_hit_com_violacao_e_descartado_forca_chamada_real(self):
        """Achado real (test_e36, 2026-08-09): uma entrada cacheada com
        ```python: fazia TODA retentativa e ate a escalacao cross-provider
        devolverem o MESMO cache hit, sem nunca chamar o LLM de novo (log
        real: 4 tentativas, todas "[CACHE] hit"). Cache invalido = miss."""
        from nvdastudio.sub_agents.web_researcher import run

        good_resp = MagicMock()
        good_resp.content = "**Pacote:** requests\n**Confianca:** Alta"
        good_resp.tokens_used = 30

        mock_memory = MagicMock()
        mock_memory.get_web_knowledge.return_value = [
            {"content": "```python:modulo.py\nimport requests\n```"}
        ]

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client") as MC:
            MC.return_value.chat.return_value = good_resp
            with patch("nvdastudio.sub_agents.web_researcher.on_demand_web_search") as mock_web:
                mock_web.return_value = ""
                result = run("como usar requests", "kimi-k2.6", {}, _memory=mock_memory)

        # Nao deve ter retornado o cache invalido direto -- precisa ter
        # chamado o LLM de verdade (fallback knowledge-only).
        MC.return_value.chat.assert_called()
        assert "requests" in result
        assert "```python:" not in result

    def test_retry_nunca_consulta_cache_mesmo_valido(self):
        """4.9.0: achado real -- mesmo com cache VALIDO (passa no guard),
        um retry precisa gerar conteudo NOVO, nao reaproveitar a resposta
        da tentativa anterior que o proprio retry existe pra corrigir.
        _RETRY_MARKER e a string literal que orchestrator.py::
        _build_step_prompt() usa quando ha previous_issues."""
        from nvdastudio.sub_agents.web_researcher import run, _RETRY_MARKER

        good_resp = MagicMock()
        good_resp.content = "**Pacote:** requests\n**Confianca:** Alta"
        good_resp.tokens_used = 30

        mock_memory = MagicMock()
        mock_memory.get_web_knowledge.return_value = [
            {"content": "**Pacote:** requests (do cache)\n**Confianca:** Alta"}
        ]

        retry_prompt = (
            f"Tarefa original do usuario: como usar requests\n\n"
            f"Seu objetivo: pesquisar\n\n"
            f"\n{_RETRY_MARKER}\n- corrija o formato"
        )

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client") as MC:
            MC.return_value.chat.return_value = good_resp
            with patch("nvdastudio.sub_agents.web_researcher.on_demand_web_search") as mock_web:
                mock_web.return_value = ""
                result = run(retry_prompt, "kimi-k2.6", {}, _memory=mock_memory)

        mock_memory.get_web_knowledge.assert_not_called()
        MC.return_value.chat.assert_called()
        assert "do cache" not in result

    def test_primeira_tentativa_continua_usando_cache(self):
        """Regressao: so RETRY pula o cache -- a 1a tentativa (sem
        _RETRY_MARKER no prompt) continua se beneficiando dele normalmente."""
        from nvdastudio.sub_agents.web_researcher import run

        mock_memory = MagicMock()
        mock_memory.get_web_knowledge.return_value = [
            {"content": "**Pacote:** requests\n**Confianca:** Alta"}
        ]

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client") as MC:
            result = run("Tarefa original do usuario: como usar requests", "kimi-k2.6", {},
                         _memory=mock_memory)

        mock_memory.get_web_knowledge.assert_called_once()
        MC.return_value.chat.assert_not_called()
        assert "[CACHE]" in result

    def test_cache_hit_valido_continua_sendo_reaproveitado(self):
        """Regressao: nao deve invalidar cache VALIDO -- so o que viola o guard."""
        from nvdastudio.sub_agents.web_researcher import run

        mock_memory = MagicMock()
        mock_memory.get_web_knowledge.return_value = [
            {"content": "**Pacote:** requests\n**Confianca:** Alta"}
        ]

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client") as MC:
            result = run("como usar requests", "kimi-k2.6", {}, _memory=mock_memory)

        MC.return_value.chat.assert_not_called()
        assert "[CACHE]" in result
        assert "requests" in result
