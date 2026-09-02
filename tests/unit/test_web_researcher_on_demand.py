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

class TestBuscaParalela:
    """
    v4.14.0: a cascata (nativa -> Tavily -> Exa) virou disparo SIMULTANEO das
    tres fontes, com uniao deduplicada por URL.

    A cascata parava na primeira fonte que devolvesse QUALQUER coisa, mesmo
    errada -- as seguintes nunca eram consultadas. Medido em 2026-09-02
    (entrega ResumoGemini): web_research reprovado 3x, uma das criticas sendo
    "nao ha citacao das fontes consultadas"; consultado direto no mesmo dia, o
    Exa devolvia "google-generativeai v0.8.6", o dado que faltava.
    """

    def _client(self, resultado=""):
        c = MagicMock()
        del c.native_web_search
        c.web_search = MagicMock(return_value=resultado)
        return c

    def _chaves(self, **mapa):
        return patch(
            "nvdastudio.gui.settings_panel.get_api_key",
            side_effect=lambda p: mapa.get(p, ""),
        )

    def test_sem_chaves_usa_so_a_nativa(self):
        from nvdastudio.sub_agents.web_researcher import _buscar_em_paralelo

        with patch("nvdastudio.gui.settings_panel.get_api_key", return_value=""):
            r = _buscar_em_paralelo("q", self._client("Titulo\nhttps://a.com\ntexto"))
        assert "https://a.com" in r

    def test_consulta_as_tres_fontes_ao_mesmo_tempo(self):
        """O ponto do fix: nenhuma fonte fica de fora porque outra respondeu."""
        from nvdastudio.sub_agents.web_researcher import _buscar_em_paralelo

        with self._chaves(tavily="tk", exa="ek"):
            with patch("nvdastudio.sub_agents.web_researcher._tavily_search",
                       return_value="T\nhttps://tavily.com/1\ntexto") as mt:
                with patch("nvdastudio.sub_agents.web_researcher._exa_search",
                           return_value="E\nhttps://exa.com/1\ntexto") as me:
                    r = _buscar_em_paralelo("q", self._client("N\nhttps://nativa.com/1\ntexto"))

        mt.assert_called_once_with("q", "tk")
        me.assert_called_once_with("q", "ek")
        assert "https://nativa.com/1" in r
        assert "https://tavily.com/1" in r
        assert "https://exa.com/1" in r, "a cascata antiga nunca chegaria no Exa"

    def test_nativa_com_resultado_nao_silencia_as_outras(self):
        """Regressao direta da cascata: bastava a nativa responder qualquer
        coisa para Tavily e Exa nunca serem chamados."""
        from nvdastudio.sub_agents.web_researcher import _buscar_em_paralelo

        with self._chaves(tavily="tk", exa="ek"):
            with patch("nvdastudio.sub_agents.web_researcher._tavily_search",
                       return_value="T\nhttps://t.com\nx") as mt:
                with patch("nvdastudio.sub_agents.web_researcher._exa_search",
                           return_value="E\nhttps://e.com\nx") as me:
                    _buscar_em_paralelo("q", self._client("N\nhttps://n.com\nx"))

        assert mt.called and me.called

    def test_uma_fonte_que_falha_nao_derruba_as_outras(self):
        from nvdastudio.sub_agents.web_researcher import _buscar_em_paralelo

        with self._chaves(tavily="tk", exa="ek"):
            with patch("nvdastudio.sub_agents.web_researcher._tavily_search",
                       side_effect=RuntimeError("timeout")):
                with patch("nvdastudio.sub_agents.web_researcher._exa_search",
                           return_value="E\nhttps://exa.com/2\ntexto"):
                    r = _buscar_em_paralelo("q", self._client(""))
        assert "https://exa.com/2" in r

    def test_todas_falhando_retorna_vazio(self):
        from nvdastudio.sub_agents.web_researcher import _buscar_em_paralelo

        with self._chaves(tavily="tk", exa="ek"):
            with patch("nvdastudio.sub_agents.web_researcher._tavily_search",
                       side_effect=RuntimeError("x")):
                with patch("nvdastudio.sub_agents.web_researcher._exa_search",
                           side_effect=RuntimeError("y")):
                    r = _buscar_em_paralelo("q", self._client(""))
        assert r == ""

    def test_nao_vaza_threads(self):
        """O pool tem que fechar: uma pesquisa por step, muitos steps."""
        import threading
        from nvdastudio.sub_agents.web_researcher import _buscar_em_paralelo

        antes = threading.active_count()
        with self._chaves(tavily="tk", exa="ek"):
            with patch("nvdastudio.sub_agents.web_researcher._tavily_search", return_value=""):
                with patch("nvdastudio.sub_agents.web_researcher._exa_search", return_value=""):
                    for _ in range(5):
                        _buscar_em_paralelo("q", self._client(""))
        assert threading.active_count() <= antes + 1


class TestMesclagem:
    def test_url_repetida_entre_fontes_aparece_uma_vez(self):
        from nvdastudio.sub_agents.web_researcher import _mesclar_resultados

        bloco = "Titulo\nhttps://mesma.com/a\ntexto"
        assert _mesclar_resultados([bloco, bloco]).count("https://mesma.com/a") == 1

    def test_url_com_barra_final_conta_como_a_mesma(self):
        from nvdastudio.sub_agents.web_researcher import _mesclar_resultados

        r = _mesclar_resultados(["T\nhttps://x.com/a/\nt", "T\nhttps://x.com/a\nt"])
        assert r.count("x.com/a") == 1

    def test_alterna_entre_fontes_para_nenhuma_ficar_de_fora(self):
        """Concatenar deixaria a 1a fonte encher a cota sozinha."""
        from nvdastudio.sub_agents.web_researcher import (
            _mesclar_resultados, _MERGED_MAX_RESULTS,
        )

        a = "\n\n".join(f"A{i}\nhttps://a.com/{i}\nt" for i in range(_MERGED_MAX_RESULTS + 3))
        b = "\n\n".join(f"B{i}\nhttps://b.com/{i}\nt" for i in range(3))
        assert "b.com" in _mesclar_resultados([a, b]), "a segunda fonte foi engolida pelo corte"

    def test_respeita_o_teto_de_resultados(self):
        from nvdastudio.sub_agents.web_researcher import (
            _mesclar_resultados, _MERGED_MAX_RESULTS,
        )

        a = "\n\n".join(f"A{i}\nhttps://a.com/{i}\nt" for i in range(30))
        r = _mesclar_resultados([a])
        assert len([b for b in r.split("\n\n") if b.strip()]) <= _MERGED_MAX_RESULTS

    def test_lista_vazia_nao_quebra(self):
        from nvdastudio.sub_agents.web_researcher import _mesclar_resultados
        assert _mesclar_resultados([]) == ""
        assert _mesclar_resultados(["", ""]) == ""


class TestCascataRemovida:
    def test_fallback_web_search_nao_existe_mais(self):
        """Regra 3 (anti-legado) e Regra 5 (zero duplicacao de fluxo): manter a
        cascata ao lado do paralelo seria uma segunda rota sem consumidor."""
        import nvdastudio.sub_agents.web_researcher as mod
        assert not hasattr(mod, "_fallback_web_search")


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
