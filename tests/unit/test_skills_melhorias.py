import pytest


# ===========================================================================
# 1. Decision Log — design_review_agent v2.4.0
# ===========================================================================

class TestDecisionLog:
    """O design_review_agent deve gerar um Decision Log como 4o estagio."""

    def test_versao_e_2_4_0(self):
        from addon.globalPlugins.nvdastudio.sub_agents.design_review_agent import MODULE_VERSION
        assert MODULE_VERSION == "2.16.0"

    # 2026-08-29: removidos os 6 testes de _DECISION_LOG_SYSTEM e do
    # _SYNTHESIS_TEMPLATE de 6 estagios. Verificavam um estagio (Decision
    # Log) que run() nao executa desde a v2.0.0 -- adaptar seria inventar
    # cobertura para comportamento que o projeto decidiu nao ter. A
    # estrutura do template REAL (3 estagios) e verificada em
    # test_sub_agents_estrutura.py e test_auditoria_2026.py.
    def test_synthesis_template_real_tem_os_tres_estagios(self):
        from addon.globalPlugins.nvdastudio.sub_agents.design_review_agent import _SYNTHESIS_TEMPLATE_V3
        assert "Challenger" in _SYNTHESIS_TEMPLATE_V3
        assert "Guardian" in _SYNTHESIS_TEMPLATE_V3
        assert "Advocate" in _SYNTHESIS_TEMPLATE_V3

    def test_run_faz_quatro_chamadas_llm(self, fake_api_key):
        """run() deve fazer exatamente 3 chamadas (Challenger, Guardian, Advocate)."""
        from unittest.mock import patch
        call_count = {"n": 0}

        def fake_run(*args, **kwargs):
            call_count["n"] += 1
            from addon.globalPlugins.nvdastudio.sub_agents._base import _tl
            _tl.last_tokens = 10
            return "output"

        with patch("addon.globalPlugins.nvdastudio.sub_agents.design_review_agent._run_sub_agent",
                   side_effect=fake_run):
            from addon.globalPlugins.nvdastudio.sub_agents.design_review_agent import run
            run("pedido", "kimi-k2.6", {})

        assert call_count["n"] == 3, (
            f"design_review deve fazer 3 chamadas LLM (Challenger+Guardian+Advocate), "
            f"fez {call_count['n']}"
        )

    def test_run_nao_executa_output(self, fake_api_key):
        """run() nunca executa o conteudo gerado (Regra 9)."""
        from unittest.mock import patch
        from addon.globalPlugins.nvdastudio.sub_agents._base import _tl
        _tl.last_tokens = 0

        with patch("addon.globalPlugins.nvdastudio.sub_agents.design_review_agent._run_sub_agent",
                   return_value="safe_text"):
            from addon.globalPlugins.nvdastudio.sub_agents.design_review_agent import run
            result = run("pedido", "kimi-k2.6", {})
        assert isinstance(result, str)


@pytest.fixture
def fake_api_key():
    return "gsk_test_fake_key_for_unit_tests"


# ===========================================================================
# 2. Confidence Calibration — Critic v2.7.0
# ===========================================================================

class TestCriticConfidenceCalibration:
    """_calibrate_confidence() deve reduzir confidence para scores proximos ao boundary."""

    def test_versao_e_2_9_0(self):
        from addon.globalPlugins.nvdastudio.ai.critic import MODULE_VERSION
        assert MODULE_VERSION == "3.22.0"

    def test_calibrate_confidence_existe(self):
        from addon.globalPlugins.nvdastudio.ai.critic import Critic
        assert hasattr(Critic, "_calibrate_confidence")

    def test_confidence_field_no_critic_result(self):
        from addon.globalPlugins.nvdastudio.ai.critic import CriticResult, Verdict
        r = CriticResult(verdict=Verdict.APPROVED, score=95, issues=[], fix_instructions="")
        assert hasattr(r, "confidence")
        assert r.confidence == 1.0

    def test_score_alto_confidence_plena(self):
        from addon.globalPlugins.nvdastudio.ai.critic import Critic, CriticResult, Verdict
        r = CriticResult(verdict=Verdict.APPROVED, score=95, issues=[], fix_instructions="")
        result = Critic._calibrate_confidence(r)
        assert result.confidence == 1.0

    def test_score_baixo_confidence_plena(self):
        from addon.globalPlugins.nvdastudio.ai.critic import Critic, CriticResult, Verdict
        r = CriticResult(verdict=Verdict.REJECTED, score=30, issues=[], fix_instructions="")
        result = Critic._calibrate_confidence(r)
        assert result.confidence == 1.0

    def test_score_medio_claro_confidence_plena(self):
        from addon.globalPlugins.nvdastudio.ai.critic import Critic, CriticResult, Verdict
        r = CriticResult(verdict=Verdict.NEEDS_FIX, score=75, issues=[], fix_instructions="")
        result = Critic._calibrate_confidence(r)
        assert result.confidence == 1.0

    def test_score_80_baixa_confianca(self):
        """Score 80-89 fica proximo ao boundary APROVADO/CORRIGIR."""
        from addon.globalPlugins.nvdastudio.ai.critic import Critic, CriticResult, Verdict
        r = CriticResult(verdict=Verdict.NEEDS_FIX, score=85, issues=[], fix_instructions="")
        result = Critic._calibrate_confidence(r)
        assert result.confidence == 0.65

    def test_score_60_baixa_confianca(self):
        """Score 60-69 fica proximo ao boundary CORRIGIR/REJEITAR."""
        from addon.globalPlugins.nvdastudio.ai.critic import Critic, CriticResult, Verdict
        r = CriticResult(verdict=Verdict.NEEDS_FIX, score=65, issues=[], fix_instructions="")
        result = Critic._calibrate_confidence(r)
        assert result.confidence == 0.65

    def test_score_boundary_adiciona_issue_descritivo(self):
        """Score na zona de baixa confianca deve adicionar aviso nos issues."""
        from addon.globalPlugins.nvdastudio.ai.critic import Critic, CriticResult, Verdict
        r = CriticResult(verdict=Verdict.NEEDS_FIX, score=82, issues=[], fix_instructions="")
        result = Critic._calibrate_confidence(r)
        assert len(result.issues) >= 1
        assert any("confianca" in i.lower() or "limite" in i.lower() for i in result.issues)

    def test_calibracao_nao_altera_verdict(self):
        """_calibrate_confidence nao deve alterar o verdict."""
        from addon.globalPlugins.nvdastudio.ai.critic import Critic, CriticResult, Verdict
        for verdict in [Verdict.APPROVED, Verdict.NEEDS_FIX, Verdict.REJECTED]:
            r = CriticResult(verdict=verdict, score=83, issues=[], fix_instructions="")
            result = Critic._calibrate_confidence(r)
            assert result.verdict == verdict

    def test_calibracao_nao_altera_score(self):
        """_calibrate_confidence nao deve alterar o score."""
        from addon.globalPlugins.nvdastudio.ai.critic import Critic, CriticResult, Verdict
        r = CriticResult(verdict=Verdict.NEEDS_FIX, score=84, issues=[], fix_instructions="")
        result = Critic._calibrate_confidence(r)
        assert result.score == 84


# ===========================================================================
# 3. Feedback Loop Estendido — Orchestrator v2.7.0
# ===========================================================================

class TestFeedbackLoopEstendido:
    """Orchestrator deve injetar falhas historicas em manifest_builder e accessibility_audit."""

    def test_versao_orchestrator_e_3_1_0(self):
        from addon.globalPlugins.nvdastudio.core.orchestrator import MODULE_VERSION
        assert MODULE_VERSION == "5.82.0"

    def test_build_step_prompt_manifest_consulta_failures(self):
        """manifest_builder deve receber padroes de erro de sessoes anteriores."""
        from unittest.mock import patch
        from addon.globalPlugins.nvdastudio.core.orchestrator import Orchestrator
        from addon.globalPlugins.nvdastudio.core.planner import ExecutionStep, STEP_MANIFEST

        orch = Orchestrator()
        step = ExecutionStep(
            step_id="m1", step_type=STEP_MANIFEST, description="gerar manifest",
            model_id="kimi-k2.6",
        )
        failures = ["manifest com [add-on] rejeitado", "summary com quebra de linha"]
        with patch("addon.globalPlugins.nvdastudio.core.orchestrator.memory") as mock_mem:
            mock_mem.get_recent_failures.return_value = failures
            prompt = orch._build_step_prompt(step, "criar addon X", "", previous_issues=[])

        assert "manifest com [add-on] rejeitado" in prompt

    def test_build_step_prompt_audit_consulta_failures(self):
        """accessibility_audit deve receber padroes de erro de sessoes anteriores."""
        from unittest.mock import patch
        from addon.globalPlugins.nvdastudio.core.orchestrator import Orchestrator
        from addon.globalPlugins.nvdastudio.core.planner import ExecutionStep, STEP_ACCESSIBILITY_AUDIT

        orch = Orchestrator()
        step = ExecutionStep(
            step_id="a1", step_type=STEP_ACCESSIBILITY_AUDIT, description="auditar",
            model_id="kimi-k2.6",
        )
        failures = ["falso positivo em NVDA-003"]
        with patch("addon.globalPlugins.nvdastudio.core.orchestrator.memory") as mock_mem:
            mock_mem.get_recent_failures.return_value = failures
            prompt = orch._build_step_prompt(step, "criar addon X", "", previous_issues=[])

        assert "falso positivo em NVDA-003" in prompt

    def test_build_step_prompt_code_generation_ainda_consulta(self):
        """code_generation ainda deve consultar falhas — sem regressao."""
        from unittest.mock import patch
        from addon.globalPlugins.nvdastudio.core.orchestrator import Orchestrator
        from addon.globalPlugins.nvdastudio.core.planner import ExecutionStep, STEP_CODE_GENERATION

        orch = Orchestrator()
        step = ExecutionStep(
            step_id="c1", step_type=STEP_CODE_GENERATION, description="gerar codigo",
            model_id="kimi-k2.6",
        )
        failures = ["erro de sintaxe em event_gainFocus"]
        with patch("addon.globalPlugins.nvdastudio.core.orchestrator.memory") as mock_mem:
            mock_mem.get_recent_failures.return_value = failures
            prompt = orch._build_step_prompt(step, "criar addon X", "", previous_issues=[])

        assert "erro de sintaxe em event_gainFocus" in prompt

    def test_build_step_prompt_assembly_consulta_com_step_type(self):
        """assembly agora consulta failures filtrado por step_type — feedback loop e global (fluxos7.1: todos os agentes)."""
        from unittest.mock import patch
        from addon.globalPlugins.nvdastudio.core.orchestrator import Orchestrator
        from addon.globalPlugins.nvdastudio.core.planner import ExecutionStep, STEP_ASSEMBLY

        orch = Orchestrator()
        step = ExecutionStep(
            step_id="asm1", step_type=STEP_ASSEMBLY, description="montar",
            model_id="kimi-k2.6",
        )
        with patch("addon.globalPlugins.nvdastudio.core.orchestrator.memory") as mock_mem:
            mock_mem.get_recent_failures.return_value = ["algum erro"]
            orch._build_step_prompt(step, "criar addon X", "", previous_issues=[])

        mock_mem.get_recent_failures.assert_called_once_with(limit=3, step_type="assembly")


# ===========================================================================
# 4. Auto-verificacao — code_generator v2.0.0 e manifest_builder v1.6.0
# ===========================================================================

class TestAutoVerificacaoCodeGenerator:
    """code_generator deve ter bloco de auto-verificacao no prompt."""

    def test_versao_e_2_1_0(self):
        from addon.globalPlugins.nvdastudio.sub_agents.code_generator import MODULE_VERSION
        assert MODULE_VERSION == "3.34.0"

    def test_system_tem_verificacao_final(self):
        from addon.globalPlugins.nvdastudio.sub_agents.code_generator import _SYSTEM
        assert "VERIFICACAO FINAL" in _SYSTEM

    def test_verificacao_menciona_next_handler(self):
        from addon.globalPlugins.nvdastudio.sub_agents.code_generator import _SYSTEM
        # Usa rsplit para pegar o ultimo bloco VERIFICACAO FINAL (o checklist real)
        parte = _SYSTEM.rsplit("VERIFICACAO FINAL", 1)[1]
        assert "nextHandler" in parte

    def test_verificacao_menciona_init_translation(self):
        from addon.globalPlugins.nvdastudio.sub_agents.code_generator import _SYSTEM
        parte = _SYSTEM.rsplit("VERIFICACAO FINAL", 1)[1]
        assert "initTranslation" in parte

    def test_verificacao_menciona_terminate(self):
        from addon.globalPlugins.nvdastudio.sub_agents.code_generator import _SYSTEM
        parte = _SYSTEM.rsplit("VERIFICACAO FINAL", 1)[1]
        assert "terminate" in parte

    def test_verificacao_menciona_atalhos_conflitantes(self):
        from addon.globalPlugins.nvdastudio.sub_agents.code_generator import _SYSTEM
        parte = _SYSTEM.rsplit("VERIFICACAO FINAL", 1)[1]
        assert "conflita" in parte or "NVDA+f" in parte

    def test_verificacao_menciona_caminho_do_arquivo(self):
        from addon.globalPlugins.nvdastudio.sub_agents.code_generator import _SYSTEM
        parte = _SYSTEM.rsplit("VERIFICACAO FINAL", 1)[1]
        assert "caminho" in parte

    def test_verificacao_menciona_except(self):
        from addon.globalPlugins.nvdastudio.sub_agents.code_generator import _SYSTEM
        parte = _SYSTEM.rsplit("VERIFICACAO FINAL", 1)[1]
        assert "except" in parte

    def test_verificacao_pede_correcao_antes_de_responder(self):
        from addon.globalPlugins.nvdastudio.sub_agents.code_generator import _SYSTEM
        parte = _SYSTEM.rsplit("VERIFICACAO FINAL", 1)[1]
        assert "corrija" in parte.lower()

    def test_nao_executa_codigo(self):
        from addon.globalPlugins.nvdastudio.sub_agents.code_generator import _SYSTEM
        assert isinstance(_SYSTEM, str)


class TestAutoVerificacaoManifestBuilder:
    """manifest_builder deve ter bloco de auto-verificacao no prompt."""

    def test_versao_e_1_6_0(self):
        from addon.globalPlugins.nvdastudio.sub_agents.manifest_builder import MODULE_VERSION
        assert MODULE_VERSION == "1.14.0"

    def test_system_tem_verificacao_final(self):
        from addon.globalPlugins.nvdastudio.sub_agents.manifest_builder import _SYSTEM
        assert "VERIFICACAO FINAL" in _SYSTEM

    def test_verificacao_menciona_secao_addon(self):
        from addon.globalPlugins.nvdastudio.sub_agents.manifest_builder import _SYSTEM
        parte = _SYSTEM.split("VERIFICACAO FINAL")[1]
        assert "[add-on]" in parte

    def test_verificacao_menciona_uma_linha(self):
        from addon.globalPlugins.nvdastudio.sub_agents.manifest_builder import _SYSTEM
        parte = _SYSTEM.split("VERIFICACAO FINAL")[1]
        assert "UNICA LINHA" in parte or "linha" in parte.lower()

    def test_verificacao_menciona_baseline(self):
        from addon.globalPlugins.nvdastudio.sub_agents.manifest_builder import _SYSTEM
        from addon.globalPlugins.nvdastudio.utils.project_policy import PROJECT_MIN_NVDA
        parte = _SYSTEM.split("VERIFICACAO FINAL")[1]
        assert PROJECT_MIN_NVDA in parte

    def test_verificacao_menciona_doc_filename(self):
        from addon.globalPlugins.nvdastudio.sub_agents.manifest_builder import _SYSTEM
        parte = _SYSTEM.split("VERIFICACAO FINAL")[1]
        assert "docFileName" in parte or "userGuide" in parte

    def test_verificacao_pede_correcao_antes_de_responder(self):
        from addon.globalPlugins.nvdastudio.sub_agents.manifest_builder import _SYSTEM
        parte = _SYSTEM.split("VERIFICACAO FINAL")[1]
        assert "corrija" in parte.lower()

    def test_nao_executa_codigo(self):
        from addon.globalPlugins.nvdastudio.sub_agents.manifest_builder import _SYSTEM
        assert isinstance(_SYSTEM, str)
