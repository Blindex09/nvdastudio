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


# ---------------------------------------------------------------------------
# Classe 1: _needs_replan() — logica deterministica (sem LLM)
# ---------------------------------------------------------------------------

class TestNeedsReplanDeterministico:
    """
    _needs_replan() e puramente deterministica: verifica se step critico falhou.
    Regra 5: sem LLM nesta decisao — testavel sem chave de API.
    """

    def test_retorna_true_para_step_critico_rejeitado(self):
        """code_generation rejeitado (approved=False) deve disparar replan."""
        from nvdastudio.core.orchestrator import Orchestrator, StepResult

        orch = Orchestrator()
        level_results = [
            StepResult(
                step_id="code_gen_1",
                step_type="code_generation",
                output="",
                approved=False,
                score=20,
                issues=["Codigo invalido", "Falta GlobalPlugin"],
                model_used="kimi-k2.6",
            )
        ]

        assert orch._needs_replan(level_results) is True, (
            "_needs_replan deve retornar True quando code_generation nao aprovado"
        )

    def test_retorna_false_para_manifest_builder_rejeitado(self):
        """
        manifest_builder rejeitado NAO deve disparar replan.
        Motivo: manifest_builder e nao-bloqueante — assembly pode regenerar manifest.
        Incluir manifest_builder em _CRITICAL_STEP_TYPES causaria replan desnecessario.
        """
        from nvdastudio.core.orchestrator import Orchestrator, StepResult

        orch = Orchestrator()
        level_results = [
            StepResult(
                step_id="manifest_1",
                step_type="manifest_builder",
                output="",
                approved=False,
                score=10,
                issues=["Campo minimumNVDAVersion ausente"],
                model_used="kimi-k2.6",
            )
        ]

        assert orch._needs_replan(level_results) is False, (
            "manifest_builder e nao-bloqueante: sua falha nao deve disparar replan"
        )

    def test_retorna_true_para_agent_runner_rejeitado(self):
        """agent_runner rejeitado deve disparar replan (critico)."""
        from nvdastudio.core.orchestrator import Orchestrator, StepResult

        orch = Orchestrator()
        level_results = [
            StepResult(
                step_id="agent_runner_1",
                step_type="agent_runner",
                output="",
                approved=False,
                score=5,
                issues=["AgentRunner sem reset_session()"],
                model_used="kimi-k2.6",
            )
        ]

        assert orch._needs_replan(level_results) is True

    def test_retorna_false_para_step_nao_critico_rejeitado(self):
        """
        Steps nao-criticos rejeitados NAO devem disparar replan.
        design_review, accessibility_audit, syntax_validation sao nao-criticos.
        """
        from nvdastudio.core.orchestrator import Orchestrator, StepResult

        orch = Orchestrator()
        level_results = [
            StepResult(
                step_id="design_review_1",
                step_type="design_review",
                output="",
                approved=False,
                score=30,
                issues=["Faltou secao de invariantes"],
                model_used="kimi-k2.6",
            ),
            StepResult(
                step_id="accessibility_audit_1",
                step_type="accessibility_audit",
                output="",
                approved=False,
                score=40,
                issues=["Touch target abaixo de 44px"],
                model_used="kimi-k2.6",
            ),
        ]

        assert orch._needs_replan(level_results) is False, (
            "_needs_replan nao deve retornar True para steps nao-criticos"
        )

    def test_retorna_false_quando_step_critico_aprovado(self):
        """Step critico aprovado (approved=True) nao deve disparar replan."""
        from nvdastudio.core.orchestrator import Orchestrator, StepResult

        orch = Orchestrator()
        level_results = [
            StepResult(
                step_id="code_gen_1",
                step_type="code_generation",
                output="import globalPluginHandler\nclass GlobalPlugin(...): pass",
                approved=True,
                score=85,
                issues=[],
                model_used="kimi-k2.6",
            )
        ]

        assert orch._needs_replan(level_results) is False

    def test_retorna_false_para_lista_vazia(self):
        """Lista vazia de resultados nao deve disparar replan."""
        from nvdastudio.core.orchestrator import Orchestrator

        orch = Orchestrator()
        assert orch._needs_replan([]) is False

    def test_mistura_critico_nao_critico_retorna_true(self):
        """Se qualquer step critico falhou, deve replaneja mesmo com outros aprovados."""
        from nvdastudio.core.orchestrator import Orchestrator, StepResult

        orch = Orchestrator()
        level_results = [
            StepResult(
                step_id="accessibility_audit_1",
                step_type="accessibility_audit",
                output="ok",
                approved=True,
                score=90,
                issues=[],
                model_used="kimi-k2.6",
            ),
            StepResult(
                step_id="code_gen_1",
                step_type="code_generation",
                output="",
                approved=False,
                score=15,
                issues=["Sintaxe invalida"],
                model_used="kimi-k2.6",
            ),
        ]

        assert orch._needs_replan(level_results) is True


# ---------------------------------------------------------------------------
# Classe 2: _do_replan() com API real — Planner.replan() retorna steps validos
# ---------------------------------------------------------------------------

@skip_unless_ollama
class TestDoReplanComAPIReal:
    """
    _do_replan() chama Planner.replan() com API real e retorna lista de steps.
    Invariante: lista nao vazia com step_types validos.
    """

    def test_do_replan_retorna_lista_nao_vazia(self):
        """
        _do_replan() com API real deve retornar pelo menos 1 step.
        Se Planner.replan() falhar, retorna os steps originais (graceful).
        """
        from nvdastudio.core.orchestrator import Orchestrator, StepResult
        from nvdastudio.core.planner import ExecutionStep, STEP_CODE_GENERATION, STEP_ASSEMBLY

        orch = Orchestrator()
        orch.initialize()

        # Simula contexto de replan: um step de codigo falhou
        remaining_steps = [
            ExecutionStep(
                step_id="code_gen_retry_1",
                step_type=STEP_CODE_GENERATION,
                description="Gerar codigo do addon corrigindo os problemas identificados",
                model_id="kimi-k2.6",
                reasoning_params={},
                dependencies=[],
            ),
            ExecutionStep(
                step_id="assembly_1",
                step_type=STEP_ASSEMBLY,
                description="Montar artefatos finais do addon",
                model_id="kimi-k2.6",
                reasoning_params={},
                dependencies=["code_gen_retry_1"],
            ),
        ]

        failed_results = [
            StepResult(
                step_id="code_gen_1",
                step_type=STEP_CODE_GENERATION,
                output="",
                approved=False,
                score=20,
                issues=["GlobalPlugin nao herda de globalPluginHandler.GlobalPlugin"],
                model_used="kimi-k2.6",
            )
        ]

        new_steps = orch._do_replan(
            original_query="Crie um addon NVDA que anuncia a hora",
            outputs={},
            remaining=remaining_steps,
            failed_level=failed_results,
        )

        assert isinstance(new_steps, list), "_do_replan deve retornar lista"
        assert len(new_steps) >= 1, (
            "_do_replan nao pode retornar lista vazia "
            "(se replan falhar, mantem steps originais)"
        )
        for step in new_steps:
            assert step.step_id, "Cada step deve ter step_id"
            assert step.step_type, "Cada step deve ter step_type"
            assert step.model_id, "Cada step deve ter model_id (atribuido pelo Planner)"

    def test_do_replan_mantém_steps_originais_se_planner_falhar(self):
        """
        Se Planner.replan() levantar excecao, _do_replan deve retornar
        os steps originais (nao pode crashar o pipeline).
        Invariante de graceful degradation.
        """
        from nvdastudio.core.orchestrator import Orchestrator
        from nvdastudio.core.planner import ExecutionStep, STEP_CODE_GENERATION

        orch = Orchestrator()
        orch.initialize()

        remaining_steps = [
            ExecutionStep(
                step_id="code_gen_1",
                step_type=STEP_CODE_GENERATION,
                description="Gerar codigo",
                model_id="kimi-k2.6",
                reasoning_params={},
                dependencies=[],
            )
        ]

        # Planner falha
        with patch.object(orch._planner, "replan", side_effect=Exception("Timeout da API")):
            new_steps = orch._do_replan(
                original_query="Addon de hora",
                outputs={},
                remaining=remaining_steps,
                failed_level=[],
            )

        # Deve retornar os steps originais, nao crashar
        assert new_steps == remaining_steps, (
            "_do_replan deve retornar steps originais quando Planner falha"
        )

    def test_planner_replan_com_api_real(self):
        """
        Planner.replan() com API real deve retornar lista de steps para
        corrigir os problemas identificados.
        Testa diretamente o metodo, nao atraves do Orchestrator.
        """
        from nvdastudio.core.planner import Planner, ExecutionStep, STEP_CODE_GENERATION, STEP_ASSEMBLY

        planner = Planner()

        remaining = [
            ExecutionStep(
                step_id="code_gen_1",
                step_type=STEP_CODE_GENERATION,
                description="Gerar codigo corrigido do addon",
                model_id="kimi-k2.6",
                reasoning_params={},
                dependencies=[],
            ),
            ExecutionStep(
                step_id="assembly_1",
                step_type=STEP_ASSEMBLY,
                description="Montar addon",
                model_id="kimi-k2.6",
                reasoning_params={},
                dependencies=["code_gen_1"],
            ),
        ]

        new_steps = planner.replan(
            original_query="Crie um globalPlugin NVDA que anuncia a hora",
            outputs_summary={"design_review_1": "Design aprovado com ressalvas"},
            remaining_steps=remaining,
            issues=["GlobalPlugin nao chama super().__init__()", "Falta terminate()"],
        )

        assert isinstance(new_steps, list)
        assert len(new_steps) >= 1, "Replan deve retornar pelo menos 1 step"

        # Steps devem ter campos obrigatorios
        for step in new_steps:
            assert hasattr(step, "step_id")
            assert hasattr(step, "step_type")
            assert hasattr(step, "model_id")
            assert step.model_id, f"model_id nao pode ser vazio: {step}"


# ---------------------------------------------------------------------------
# Classe 3: Replanejamento no pipeline — evento e replan_count
# ---------------------------------------------------------------------------

class TestReplanejamentoPipeline:
    """
    Valida o replanejamento real no pipeline:
    1. Quando step critico falha apos retries, REPLANEJANDO e emitido
    2. replan_count >= 1 no OrchestrationResult

    Estrategia (skill: agent-evaluation adversarial testing):
    Mockamos o Critic para rejeitar sempre o primeiro code_generation,
    forcando o Orchestrator a replaneja. O Planner e real com API.
    Apos o replan, o Critic aprova normalmente.
    """
    pytestmark = skip_unless_ollama

    def test_replanejamento_emite_evento_e_incrementa_contador(self):
        """
        Com Critic mockado para rejeitar code_generation na primeira tentativa
        e apos escalacao, o Orchestrator deve:
        1. Emitir evento REPLANEJANDO
        2. Incrementar replan_count para >= 1 no resultado
        """
        from nvdastudio.core.orchestrator import Orchestrator
        from nvdastudio.ai.critic import CriticResult, Verdict

        results = []
        events = []

        orch = Orchestrator()
        orch.initialize()
        orch.set_callbacks(
            on_progress=lambda ev, det: events.append((ev, det)),
            on_complete=lambda r: results.append(r),
        )

        call_count = {"code_gen": 0}

        original_evaluate_two_stage = orch._critic.evaluate_two_stage

        def mock_evaluate_two_stage(step_type, output, context=""):
            if step_type == "code_generation":
                call_count["code_gen"] += 1
                # Rejeita nas primeiras MAX_RETRIES + 1 chamadas (original + escalacao)
                # Depois aprova para nao criar loop infinito
                if call_count["code_gen"] <= 4:
                    return CriticResult(
                        verdict=Verdict.NEEDS_FIX,
                        score=15,
                        issues=["Forcando replan — teste E2E"],
                        fix_instructions="Corrija o codigo conforme as regras NVDA",
                    )
            return original_evaluate_two_stage(step_type, output, context)

        with patch.object(orch._critic, "evaluate_two_stage", side_effect=mock_evaluate_two_stage):
            orch._run_pipeline(
                "Crie um addon NVDA simples que anuncia a hora"
            )

        assert results, "on_complete nao foi chamado"
        result = results[0]

        # Evento REPLANEJANDO deve ter sido emitido
        event_types = {e[0] for e in events}
        assert "REPLANEJANDO" in event_types, (
            "Evento REPLANEJANDO nao foi emitido. "
            f"Eventos emitidos: {sorted(event_types)}"
        )

        # replan_count deve ser >= 1
        assert result.replan_count >= 1, (
            f"replan_count deve ser >= 1, recebeu {result.replan_count}"
        )

    def test_max_replans_evita_loop_infinito(self):
        """
        _MAX_REPLANS (2) deve impedir que o Orchestrator replane indefinidamente.
        Invariante de seguranca: pipeline termina mesmo que code_generation
        continue falhando apos todos os replans.
        """
        from nvdastudio.core.orchestrator import Orchestrator, _MAX_REPLANS
        from nvdastudio.ai.critic import CriticResult, Verdict

        # Valida a constante antes do teste
        assert _MAX_REPLANS >= 1, "_MAX_REPLANS deve ser >= 1"

        results = []
        events = []

        orch = Orchestrator()
        orch.initialize()
        orch.set_callbacks(
            on_progress=lambda ev, det: events.append((ev, det)),
            on_complete=lambda r: results.append(r),
        )

        original_evaluate = orch._critic.evaluate

        def always_reject_code_gen(step_type, output, extra_context=None, query=None):
            if step_type == "code_generation":
                return CriticResult(
                    verdict=Verdict.REJECTED,
                    score=0,
                    issues=["Sempre rejeitado para testar _MAX_REPLANS"],
                    fix_instructions="",
                )
            return original_evaluate(step_type, output, extra_context=extra_context, query=query)

        with patch.object(orch._critic, "evaluate", side_effect=always_reject_code_gen):
            orch._run_pipeline(
                "Crie um addon NVDA simples"
            )

        # Pipeline DEVE ter terminado (on_complete chamado)
        assert results, (
            "on_complete nao foi chamado — _MAX_REPLANS nao evitou loop infinito"
        )

        # replan_count nao pode exceder _MAX_REPLANS
        result = results[0]
        assert result.replan_count <= _MAX_REPLANS, (
            f"replan_count={result.replan_count} excede _MAX_REPLANS={_MAX_REPLANS}"
        )

    def test_pipeline_continua_apos_replanejamento_bem_sucedido(self):
        """
        Apos replanejamento, pipeline deve continuar executando os novos steps
        e produzir um final_output nao nulo.
        Valida que o replan nao trava o pipeline.
        """
        from nvdastudio.core.orchestrator import Orchestrator
        from nvdastudio.ai.critic import CriticResult, Verdict

        results = []
        events = []

        orch = Orchestrator()
        orch.initialize()
        orch.set_callbacks(
            on_progress=lambda ev, det: events.append((ev, det)),
            on_complete=lambda r: results.append(r),
        )

        original_evaluate = orch._critic.evaluate
        first_code_gen_call = {"done": False}

        def reject_once_then_approve(step_type, output, extra_context=None, query=None):
            if step_type == "code_generation" and not first_code_gen_call["done"]:
                first_code_gen_call["done"] = True
                return CriticResult(
                    verdict=Verdict.NEEDS_FIX,
                    score=20,
                    issues=["Primeira tentativa — forcando replan E2E"],
                    fix_instructions="Inclua terminate() e addonHandler.initTranslation()",
                )
            return original_evaluate(step_type, output, extra_context=extra_context, query=query)

        with patch.object(orch._critic, "evaluate", side_effect=reject_once_then_approve):
            orch._run_pipeline(
                "Crie um addon NVDA que anuncia a hora atual ao pressionar NVDA+H"
            )

        assert results, "on_complete nao foi chamado"
        result = results[0]

        # Output final deve existir apos replanejamento
        assert result.final_output is not None, (
            "final_output nao pode ser None apos replanejamento"
        )
        assert isinstance(result.final_output, str)

        # Pipeline deve ter emitido CONCLUIDO ou ERRO (nao silenciosamente parado)
        event_types = {e[0] for e in events}
        assert "CONCLUIDO" in event_types or "ERRO" in event_types, (
            "Pipeline nao emitiu CONCLUIDO nem ERRO apos replanejamento. "
            f"Eventos: {sorted(event_types)}"
        )


# ---------------------------------------------------------------------------
# Classe 4: Invariantes de criticos_step_types
# ---------------------------------------------------------------------------

class TestCriticalStepTypesInvariante:
    """
    Valida que os tipos de steps criticos estao corretamente definidos.
    Sem API — testa invariantes de configuracao do modulo.
    """

    def test_critical_step_types_sao_dois_tipos_esperados(self):
        """
        _CRITICAL_STEP_TYPES deve conter exatamente 2 tipos criticos:
        code_generation e agent_runner.
        manifest_builder e nao-bloqueante (assembly pode regenerar manifest)
        e portanto excluido dos tipos criticos.
        """
        from nvdastudio.core.orchestrator import _CRITICAL_STEP_TYPES

        assert "code_generation" in _CRITICAL_STEP_TYPES, (
            "code_generation deve ser step critico"
        )
        assert "agent_runner" in _CRITICAL_STEP_TYPES, (
            "agent_runner deve ser step critico"
        )
        assert "manifest_builder" not in _CRITICAL_STEP_TYPES, (
            "manifest_builder e nao-bloqueante — nao pode estar em _CRITICAL_STEP_TYPES"
        )

    def test_non_blocking_step_types_inclui_web_research(self):
        """web_research deve ser nao-bloqueante (graceful degradation offline)."""
        from nvdastudio.core.orchestrator import _NON_BLOCKING_STEP_TYPES

        assert "web_research" in _NON_BLOCKING_STEP_TYPES, (
            "web_research deve ser nao-bloqueante"
        )

    def test_critical_e_non_blocking_sao_disjuntos(self):
        """
        Step nao pode ser critico E nao-bloqueante ao mesmo tempo.
        Invariante logico: se critico, um fail deve disparar replan, nao ignorar.
        """
        from nvdastudio.core.orchestrator import _CRITICAL_STEP_TYPES, _NON_BLOCKING_STEP_TYPES

        intersecao = _CRITICAL_STEP_TYPES & _NON_BLOCKING_STEP_TYPES
        assert len(intersecao) == 0, (
            f"Steps nao podem ser criticos E nao-bloqueantes: {intersecao}"
        )

    def test_max_replans_e_positivo(self):
        """_MAX_REPLANS deve ser > 0 para permitir pelo menos um replanejamento."""
        from nvdastudio.core.orchestrator import _MAX_REPLANS

        assert _MAX_REPLANS > 0, (
            f"_MAX_REPLANS deve ser positivo, encontrou {_MAX_REPLANS}"
        )
        # Mas nao pode ser muito alto (evita loop caro)
        assert _MAX_REPLANS <= 5, (
            f"_MAX_REPLANS={_MAX_REPLANS} muito alto — risco de loop caro"
        )

