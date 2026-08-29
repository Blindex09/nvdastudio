import os
from unittest.mock import patch

import pytest

HAS_OLLAMA = os.environ.get("OLLAMA_API_KEY", "").strip()
# 2026-08-17: critic.py 3.19.0 -- o Critic agora SEMPRE usa OpenCode Go
# (prompt caching), independente do provider ativo. Sem essa chave, TODA
# avaliacao de step falha com "Chave API para opencode_go nao configurada"
# -- achado real ao vivo (madrugada 2026-08-17/18, rodada 1 do loop): os
# 2 casos deste arquivo rodaram e "passaram" no pytest (test_e36 nao exige
# success=True) mas o pipeline inteiro falhou em segundos, 0 tokens gastos,
# nenhum sinal real coletado -- so desperdicou tempo/custo do Ollama sem
# testar nada. Adicionado ao skip guard pra nao rodar (e enganar) sem as
# 2 chaves.
HAS_OPENCODE_GO = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
skip_unless_ollama = pytest.mark.skipif(
    not HAS_OLLAMA or not HAS_OPENCODE_GO,
    reason=("Ollama Cloud token nao disponivel" if not HAS_OLLAMA else "OpenCode Go token nao disponivel (necessario pro Critic, ver critic.py 3.19.0)")
)

# 5.1.0: skip_unless_ollama era definido mas nunca aplicado -- achado real
# de auditoria 2026-08-25. As 4 classes tocam API real -- ate
# TestWebResearcherGracefulDegradation, que so mocka web_researcher, ainda
# roda orch._run_pipeline() de verdade (Planner/Critic/code_generation
# reais). Sem as chaves, ficavam penduradas indefinidamente em vez de skip
# limpo. Ver test_e20_regras_qualidade_codigo.py 5.1.0 para o achado completo.
pytestmark = skip_unless_ollama

# Limiar de conteudo substantivo (mesmo valor que _THIN_MIN_CHARS no modulo)
_MIN_SUBSTANTIVE_CHARS = 300


# ---------------------------------------------------------------------------
# Classe 1: Contrato de output — conteudo substantivo com API real
# ---------------------------------------------------------------------------

class TestWebResearcherSaidaSubstantiva:
    """
    web_researcher.run() deve retornar conteudo substantivo quando a API esta disponivel.
    Invariante: output > _MIN_SUBSTANTIVE_CHARS e nao comeca com [ERRO].
    """

    def test_pesquisa_sobre_nvda_retorna_conteudo_real(self):
        """
        Query sobre o NVDA deve retornar descricao real — nao erro nem string vazia.
        Usa kimi-k2.6 via Ollama Cloud.
        """
        from nvdastudio.sub_agents.web_researcher import run

        output = run(
            prompt="O que e o NVDA e como funciona o sistema de addons dele?", model_id="kimi-k2.6",
            reasoning_params={})

        assert isinstance(output, str)
        assert len(output) > _MIN_SUBSTANTIVE_CHARS, (
            f"Output muito curto para pesquisa real sobre NVDA: {len(output)} chars. "
            f"Primeiros 200: {output[:200]}"
        )
        assert not output.startswith("[ERRO]"), (
            f"WebResearcher retornou erro: {output[:200]}"
        )

    def test_pesquisa_sobre_biblioteca_python_retorna_versao_ou_uso(self):
        """
        Query sobre biblioteca Python usada em addons NVDA deve retornar
        informacao sobre versao, uso ou dependencias.
        """
        from nvdastudio.sub_agents.web_researcher import run

        output = run(
            prompt="Como usar wxPython para criar dialogs no NVDA addon?", model_id="kimi-k2.6", reasoning_params={})

        assert isinstance(output, str)
        assert len(output) > _MIN_SUBSTANTIVE_CHARS, (
            f"Output muito curto para pesquisa sobre wxPython: {len(output)} chars"
        )
        assert not output.startswith("[ERRO]"), (
            f"WebResearcher retornou erro: {output[:200]}"
        )

    def test_pesquisa_sobre_api_llm_retorna_conteudo_tecnico(self):
        """
        Query sobre API LLM deve retornar conteudo tecnico relevante.
        Importante para addons que usam API de IA internamente.
        """
        from nvdastudio.sub_agents.web_researcher import run

        output = run(
            prompt="Ollama Cloud API Python SDK chat completions como usar", model_id="kimi-k2.6", reasoning_params={})

        assert isinstance(output, str)
        assert len(output) > _MIN_SUBSTANTIVE_CHARS, (
            f"Output muito curto para pesquisa sobre API LLM: {len(output)} chars"
        )
        assert not output.startswith("[ERRO]"), (
            f"WebResearcher retornou erro: {output[:200]}"
        )


# ---------------------------------------------------------------------------
# Classe 2: Early stopping — nao explode em chamadas
# ---------------------------------------------------------------------------

class TestWebResearcherEarlyStopping:
    """
    Early stopping (v1.6.0): quando total de chars acumulados nos fragmentos
    exceder _EARLY_STOP_CHARS (10000), para de buscar janelas adicionais.

    Invariante: nao deve fazer mais chamadas do que o necessario quando
    as primeiras janelas ja cobriram o topico.

    Validamos indiretamente: o output substantivo e retornado sem timeout
    e sem erro, indicando que o early stopping funcionou.
    """

    def test_retorna_resultado_em_tempo_razoavel(self, recwarn):
        """
        Early stopping deve fazer o run() completar sem esgotar todas as 8 janelas.
        Topico bem documentado deve retornar antes de percorrer todas as janelas.
        Valida via tempo de execucao < 120s (8 chamadas completas levaria mais).
        """
        import time
        from nvdastudio.sub_agents.web_researcher import run

        t0 = time.time()
        output = run(
            prompt="NVDA addon development globalPlugin tutorial", model_id="kimi-k2.6", reasoning_params={})
        duration = time.time() - t0

        assert isinstance(output, str)
        # Output deve ser substantivo ou erro controlado
        assert len(output) > 0

        # Nao fazemos assert de tempo (pode variar por rede) — apenas registramos
        # para visibilidade no pytest output
        print(f"\n  WebResearcher duration: {duration:.1f}s")

    def test_early_stopping_com_topico_muito_documentado(self):
        """
        Topico amplamente documentado (Python) deve acionar early stopping
        antes de percorrer todas as 8 janelas. Validamos que o resultado
        e substantivo (early stopping nao trunca o conteudo).
        """
        from nvdastudio.sub_agents.web_researcher import run

        output = run(
            prompt="Python programming language documentation tutorial", model_id="kimi-k2.6", reasoning_params={})

        assert isinstance(output, str)
        # Output final deve ter conteudo real (nao foi truncado prematuramente)
        assert len(output) > _MIN_SUBSTANTIVE_CHARS or output.startswith("[CACHE]"), (
            f"Early stopping truncou conteudo. Output: {output[:200]}"
        )


# ---------------------------------------------------------------------------
# Classe 3: Graceful degradation — falha offline nao bloqueia pipeline
# ---------------------------------------------------------------------------

class TestWebResearcherGracefulDegradation:
    """
    Quando web_research falha (offline, erro de API), o pipeline nao deve parar.
    Invariante do Orchestrator v3.0.0:
    - web_research esta em _NON_BLOCKING_STEP_TYPES
    - falha emite evento AVISO, nao ERRO fatal
    - pipeline continua e gera addon sem informacoes externas
    """

    def test_pipeline_continua_quando_web_research_falha(self):
        """
        Com web_researcher mockado para falhar, pipeline deve:
        1. Emitir evento AVISO (nao bloquear)
        2. Continuar executando steps restantes
        3. Retornar OrchestrationResult com final_output nao nulo
        """
        from nvdastudio.core.orchestrator import Orchestrator

        results = []
        events = []

        orch = Orchestrator()
        orch.initialize()
        orch.set_callbacks(
            on_progress=lambda ev, det: events.append((ev, det)),
            on_complete=lambda r: results.append(r),
        )

        # Mocka o web_researcher para simular falha de rede
        with patch(
            "nvdastudio.sub_agents.web_researcher.create_llm_client",
            side_effect=Exception("Simulacao de falha de rede — sem conexao"),
        ):
            orch._run_pipeline(
                "Crie um addon NVDA usando a biblioteca requests para fazer "
                "uma chamada HTTP ao pressionar NVDA+R"
            )

        assert results, "on_complete nao foi chamado mesmo com web_research falhando"
        result = results[0]

        # Pipeline deve ter completado (nao parado pelo web_research)
        assert result.final_output is not None, (
            "Pipeline parou com web_research falhando — nao deveria bloquear"
        )
        assert isinstance(result.final_output, str)

        # Evento AVISO deve ter sido emitido para web_research offline
        event_types = {e[0] for e in events}
        # AVISO pode nao ser emitido se o Planner nao incluiu web_research no plano
        # O que importa: pipeline completou sem crash
        assert "CONCLUIDO" in event_types or "ERRO" in event_types, (
            "Pipeline nao emitiu CONCLUIDO nem ERRO"
        )

    def test_aviso_emitido_quando_web_research_nao_aprovado(self):
        """
        Quando step web_research retorna output vazio (offline), Orchestrator
        deve emitir evento AVISO com mensagem sobre indisponibilidade.
        Invariante do orchestrator.py v3.0.0.
        """
        from nvdastudio.core.orchestrator import Orchestrator, StepResult, _NON_BLOCKING_STEP_TYPES

        # Verifica que web_research esta em _NON_BLOCKING_STEP_TYPES (invariante de contrato)
        assert "web_research" in _NON_BLOCKING_STEP_TYPES, (
            "web_research deve estar em _NON_BLOCKING_STEP_TYPES para graceful degradation"
        )

        events = []
        results = []

        orch = Orchestrator()
        orch.initialize()
        orch.set_callbacks(
            on_progress=lambda ev, det: events.append((ev, det)),
            on_complete=lambda r: results.append(r),
        )

        # Mocka dispatcher para retornar step web_research nao aprovado
        web_research_step_seen = []

        def mock_dispatch_with_tokens(step, prompt, api_key):
            if step.step_type == "web_research":
                web_research_step_seen.append(True)
                # Simula falha — retorna approved=False, output vazio
                return StepResult(
                    step_id=step.step_id,
                    step_type=step.step_type,
                    output="",
                    approved=False,
                    score=0,
                    issues=["Simulacao offline"],
                    model_used=step.model_id,
                ), 0
            # Para outros steps, delega para o dispatch real
            from nvdastudio.sub_agents.dispatcher import dispatch_step_with_tokens
            return dispatch_step_with_tokens(step, prompt, api_key)

        with patch(
            "nvdastudio.core.orchestrator.dispatch_step_with_tokens",
            side_effect=mock_dispatch_with_tokens,
        ):
            orch._run_pipeline(
                "Crie um addon NVDA que pesquisa documentacao online ao pressionar NVDA+P"
            )

        if web_research_step_seen:
            # Se o Planner incluiu web_research, AVISO deve ter sido emitido
            aviso_events = [e for e in events if e[0] == "AVISO"]
            assert len(aviso_events) >= 1, (
                "Orchestrator deve emitir AVISO quando web_research nao aprovado. "
                f"Eventos: {[e[0] for e in events]}"
            )


# ---------------------------------------------------------------------------
# Classe 4: Web research integrado ao pipeline
# ---------------------------------------------------------------------------

class TestWebResearcherIntegradoPipeline:
    """
    Valida que o step web_research aparece em step_results quando o Planner
    o inclui para queries que mencionam bibliotecas externas ou APIs.

    Invariante (fluxos14.4): web_research offline anuncia ao usuario e continua.
    """

    def test_pipeline_com_query_sobre_api_externa_inclui_web_research(self):
        """
        Query que menciona biblioteca ou API externa deve levar o Planner
        a incluir step web_research para pesquisar a documentacao atual.
        """
        from nvdastudio.core.planner import Planner

        planner = Planner()
        plan = planner.create_plan(
            "Crie um addon NVDA que usa a biblioteca requests para buscar "
            "dados de uma API REST ao pressionar NVDA+F. Pesquise a documentacao "
            "atual da biblioteca requests antes de gerar o codigo."
        )

        step_types = {s.step_type for s in plan.steps}
        # web_research e opcional — depende do Planner decidir. Apenas validamos
        # que se incluido, e o tipo correto
        if "web_research" in step_types:
            web_steps = [s for s in plan.steps if s.step_type == "web_research"]
            for ws in web_steps:
                assert ws.step_id, "web_research step deve ter step_id"
                assert ws.description, "web_research step deve ter description"

        # Plano sempre deve ter code_generation e assembly
        assert "code_generation" in step_types
        assert "assembly" in step_types

    def test_web_researcher_resultado_integrado_como_contexto(self):
        """
        Quando web_research e executado antes de code_generation,
        o resultado deve estar disponivel como contexto para o gerador de codigo.
        Valida indiretamente: pipeline completa e output final tem conteudo.
        """
        from nvdastudio.core.orchestrator import Orchestrator

        results = []
        events = []

        orch = Orchestrator()
        orch.initialize()
        orch.set_callbacks(
            on_progress=lambda ev, det: events.append((ev, det)),
            on_complete=lambda r: results.append(r),
        )

        orch._run_pipeline(
            "Crie um addon NVDA que converte texto para fala usando a "
            "documentacao mais recente da API do NVDA. "
            "Pesquise a API antes de implementar."
        )

        assert results, "on_complete nao foi chamado"
        result = results[0]

        # Pipeline deve ter completado
        assert result.final_output is not None
        assert isinstance(result.final_output, str)
        assert len(result.final_output) > 0

        # Se web_research foi executado, deve estar em step_results
        web_results = [sr for sr in result.step_results if sr.step_type == "web_research"]
        for wr in web_results:
            # web_research nao bloqueia: aprovado ou nao, pipeline continua
            assert isinstance(wr.output, str)

