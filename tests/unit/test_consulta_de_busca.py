"""Regressao: a busca web recebia o PROMPT INTEIRO como consulta.

`on_demand_web_search(prompt, ...)` era chamada com o prompt do step -- dezenas
de milhares de caracteres, com tarefa original, contexto NVDA e objetivo -- e
isso ia direto para as APIs de busca como se fosse uma pergunta.

Medido na rodada de 2026-09-03 01:35:

    [WEB_SEARCH] fonte tavily falhou: Client error '400 Bad Request'

O Tavily recusa consulta desse tamanho. O Exa aceita, mas responde a um bloco
de prompt em vez de a uma pergunta -- por isso a pesquisa vinha generica e o
Critic reprovava por falta de especificidade, 3 tentativas por rodada.

Verificado ao vivo em 2026-09-03 com as chaves reais:
    prompt inteiro (18.211 chars) -> Tavily 400 Bad Request
    objetivo extraido (111 chars) -> Tavily OK, 7.237 chars, fontes relevantes

`_extract_topic()` ja existia e ja fazia essa extracao -- so era usada como
chave de cache, nunca como consulta.
"""
import inspect

from nvdastudio.sub_agents import web_researcher as wr


_PROMPT_REAL = (
    "Tarefa original do usuario: Crie um addon NVDA chamado AssistenteEscrita.\n"
    + ("Contexto NVDA irrelevante para a busca. " * 800)
    + "Seu objetivo neste step: Pesquisar a API de chat completions da OpenAI: "
      "nome do pacote pip, versao estavel e codigos de erro.\n"
)


class TestConsultaExtraida:
    def test_prompt_gordo_vira_consulta_curta(self):
        t = wr._extract_topic(_PROMPT_REAL)
        assert len(_PROMPT_REAL) > 10_000
        assert len(t) <= wr._MAX_QUERY_CHARS
        assert t.startswith("Pesquisar a API de chat completions")

    def test_nao_leva_o_contexto_nvda_junto(self):
        """O contexto e o que estourava o limite do Tavily."""
        assert "Contexto NVDA" not in wr._extract_topic(_PROMPT_REAL)

    def test_sem_marcador_cai_num_recorte_seguro(self):
        """Chamada direta/teste, sem passar por _build_step_prompt."""
        t = wr._extract_topic("como usar requests em python " * 100)
        assert 0 < len(t) <= wr._MAX_QUERY_CHARS

    def test_teto_e_conservador_para_as_tres_fontes(self):
        assert wr._MAX_QUERY_CHARS <= 400


class TestBuscaRecebeAConsultaNaoOPrompt:
    def _client(self, resultado=""):
        from unittest.mock import MagicMock
        c = MagicMock()
        del c.native_web_search
        c.web_search = MagicMock(return_value=resultado)
        return c

    def test_paralelo_recebe_os_termos_extraidos(self, monkeypatch):
        capturado = {}

        def _fake(termos, client):
            capturado["q"] = termos
            return "T\nhttps://x.com\ntexto"

        monkeypatch.setattr(wr, "_buscar_em_paralelo", _fake)
        monkeypatch.setattr(wr, "_synthesize_web_results", lambda *a, **k: "sintese")
        monkeypatch.setattr(wr, "create_llm_client", lambda **k: self._client())
        monkeypatch.setattr(wr, "narrate", lambda *a, **k: None)

        wr.on_demand_web_search(_PROMPT_REAL, model_id="m")

        assert capturado["q"].startswith("Pesquisar a API de chat completions")
        assert len(capturado["q"]) <= wr._MAX_QUERY_CHARS
        assert capturado["q"] != _PROMPT_REAL, (
            "o prompt inteiro voltou a ser usado como consulta -- Tavily devolve 400"
        )


class TestCosturaDoMarcador:
    """O marcador so serve se for LITERALMENTE o que o orchestrator escreve.

    Se as duas pontas divergirem, _extract_topic cai no fallback dos primeiros
    caracteres -- que sao o preambulo da tarefa, IDENTICO para todos os steps do
    mesmo addon. Isso quebraria de uma vez a consulta de busca E a chave de
    cache (fazendo pesquisas diferentes colidirem), sem erro visivel.
    """

    def test_marcador_bate_com_o_que_build_step_prompt_emite(self):
        from nvdastudio.core import orchestrator as orch

        fonte = inspect.getsource(orch)
        i = fonte.index("def _build_step_prompt")
        corpo = fonte[i:i + 8000]
        assert wr._OBJECTIVE_MARKER in corpo, (
            f"_build_step_prompt nao emite mais {wr._OBJECTIVE_MARKER!r} -- "
            "a extracao do objetivo caiu no fallback silenciosamente"
        )

    def test_marcador_do_critic_e_outro_de_proposito(self):
        """_critic_context usa 'Objetivo deste step:' (sem o 'Seu'). Sao
        prompts diferentes; confundir os dois foi erro meu ao investigar, e o
        teste acima e que garante a ponta que importa."""
        from nvdastudio.core import orchestrator as orch

        fonte = inspect.getsource(orch)
        assert "Objetivo deste step:" in fonte
        assert wr._OBJECTIVE_MARKER != "Objetivo deste step:"
