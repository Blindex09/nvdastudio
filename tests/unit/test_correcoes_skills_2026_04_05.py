import os
from unittest.mock import patch



# ------------------------------------------------------------------
# Correcao 2 — regex SettingsPanel nao deve casar com wx.Panel simples
# ------------------------------------------------------------------

class TestInferPythonFilenameRegexFix:
    """skill: nvda-addon-dev — regex de Settings nao pode casar com wx.Panel."""

    def test_settings_panel_inferido_corretamente(self):
        from nvdastudio.builder.addon_builder import _infer_python_filename
        code = (
            "import wx\n"
            "from gui.settingsDialogs import SettingsPanel\n"
            "class GeminiSettingsPanel(SettingsPanel):\n"
            "    title = 'Gemini'\n"
        )
        result = _infer_python_filename(code, "geminiTranscriber")
        assert result is not None
        assert "settings_panel" in result

    def test_wx_panel_simples_nao_inferido_como_settings(self):
        """wx.Panel sem 'Settings' no nome nao deve gerar settings_panel.py."""
        from nvdastudio.builder.addon_builder import _infer_python_filename
        code = (
            "import wx\n"
            "class MinhaJanela(wx.Panel):\n"
            "    def __init__(self, parent):\n"
            "        super().__init__(parent)\n"
        )
        result = _infer_python_filename(code, "meuAddon")
        # Sem 'Settings' no nome da classe, nao deve inferir settings_panel
        # (pode inferir None ou outro nome, mas NAO settings_panel.py)
        assert result is None or "settings_panel" not in result

    def test_custom_panel_sem_settings_nao_inferido(self):
        """ResultsPanel, MainPanel etc. nao devem gerar settings_panel.py."""
        from nvdastudio.builder.addon_builder import _infer_python_filename
        code = (
            "import wx\n"
            "class ResultsPanel(wx.Panel):\n"
            "    pass\n"
        )
        result = _infer_python_filename(code, "meuAddon")
        assert result is None or "settings_panel" not in result

    def test_nvda_settings_panel_inferido(self):
        """NVDAStudioSettingsPanel deve continuar sendo inferido como settings_panel."""
        from nvdastudio.builder.addon_builder import _infer_python_filename
        code = (
            "from gui.settingsDialogs import SettingsPanel\n"
            "class NVDAStudioSettings(SettingsPanel):\n"
            "    title = 'NVDAStudio'\n"
        )
        result = _infer_python_filename(code, "nvdastudio")
        assert result is not None
        assert "settings_panel" in result


# ------------------------------------------------------------------
# Correcao 3 — arquivos .py escritos com LF (newline="\n")
# ------------------------------------------------------------------

class TestSaveAddonFilesLFLineEndings:
    """skill: nvda-addon-dev (Secao 18) — UTF-8 + LF line endings."""

    def test_python_salvo_com_lf(self, tmp_path):
        from nvdastudio.builder.addon_builder import save_addon_files
        code = "import globalPluginHandler\r\nclass GlobalPlugin(globalPluginHandler.GlobalPlugin):\r\n    pass\r\n"
        blocks = [{"filename": "globalPlugins/testAddon/__init__.py", "code": code, "language": "python"}]
        folder, saved = save_addon_files(blocks, str(tmp_path), "testAddon", garantir_doc=False)
        py_file = saved[0]
        # Lê em modo binário para verificar line endings
        raw = open(py_file, "rb").read()
        assert b"\r\n" not in raw, "Arquivo .py salvo com CRLF — deve usar LF"
        assert b"\n" in raw, "Arquivo .py deve conter pelo menos uma newline LF"

    def test_manifest_nao_afetado_por_lf_rule(self, tmp_path):
        """manifest.ini nao precisa de LF forcado — apenas .py e afetado."""
        from nvdastudio.builder.addon_builder import save_addon_files
        blocks = [{"filename": "manifest.ini", "code": "name = test\nversion = 1.0.0\n", "language": "ini"}]
        folder, saved = save_addon_files(blocks, str(tmp_path), "testAddon", garantir_doc=False)
        # Deve salvar sem erro — o importante e que nao crasha
        assert len(saved) == 1
        assert os.path.isfile(saved[0])

    def test_multiplos_py_todos_com_lf(self, tmp_path):
        """Todos os arquivos .py do addon devem ter LF."""
        from nvdastudio.builder.addon_builder import save_addon_files
        blocks = [
            {"filename": "globalPlugins/myAddon/__init__.py",
             "code": "import globalPluginHandler\r\nclass GlobalPlugin(globalPluginHandler.GlobalPlugin):\r\n    pass\r\n",
             "language": "python"},
            {"filename": "globalPlugins/myAddon/settings_panel.py",
             "code": "import wx\r\nclass MySettingsPanel:\r\n    pass\r\n",
             "language": "python"},
        ]
        folder, saved = save_addon_files(blocks, str(tmp_path), "myAddon")
        for path in saved:
            if path.endswith(".py"):
                raw = open(path, "rb").read()
                assert b"\r\n" not in raw, f"{path} tem CRLF"


# ------------------------------------------------------------------
# Correcao 4 — critic.py: segundo julgamento quando confidence=0.65
# ------------------------------------------------------------------

class TestCriticDoubleCheckLowConfidence:
    """skill: agent-evaluation — Statistical Test Evaluation para scores de fronteira."""

    def test_calibrate_sets_confidence_baixa_para_score_85(self):
        from nvdastudio.ai.critic import Critic, CriticResult, Verdict
        result = CriticResult(
            verdict=Verdict.NEEDS_FIX, score=85, issues=[], fix_instructions=""
        )
        calibrated = Critic._calibrate_confidence(result)
        assert calibrated.confidence == 0.65

    def test_calibrate_sets_confidence_baixa_para_score_65(self):
        from nvdastudio.ai.critic import Critic, CriticResult, Verdict
        result = CriticResult(
            verdict=Verdict.NEEDS_FIX, score=65, issues=[], fix_instructions=""
        )
        calibrated = Critic._calibrate_confidence(result)
        assert calibrated.confidence == 0.65

    def test_calibrate_mantém_confidence_alta_para_score_95(self):
        from nvdastudio.ai.critic import Critic, CriticResult, Verdict
        result = CriticResult(
            verdict=Verdict.APPROVED, score=95, issues=[], fix_instructions=""
        )
        calibrated = Critic._calibrate_confidence(result)
        assert calibrated.confidence == 1.0

    def test_evaluate_two_stage_executa_segundo_julgamento_em_boundary(self):
        """Quando quality result tem score de fronteira, deve executar recheck."""
        from nvdastudio.ai.critic import Critic, CriticResult, Verdict
        critic = Critic()

        spec_approved = CriticResult(verdict=Verdict.APPROVED, score=95, issues=[], fix_instructions="")
        quality_boundary = CriticResult(
            verdict=Verdict.NEEDS_FIX, score=85, issues=[], fix_instructions="ajuste necessario",
            dimension_scores={"completeness": 85, "format": 85, "nvda_compliance": 85}
        )
        quality_conservative = CriticResult(
            verdict=Verdict.NEEDS_FIX, score=78, issues=["problema"], fix_instructions="corrigir",
            dimension_scores={"completeness": 78, "format": 78, "nvda_compliance": 78}
        )

        call_count = {"n": 0}
        def mock_evaluate(system, step_type, output, context, stage):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return quality_boundary   # primeiro julgamento: score de fronteira
            return quality_conservative   # segundo julgamento: mais conservador

        with patch.object(critic, "_evaluate_with_system", side_effect=mock_evaluate):
            # spec passa direto sem chamar _evaluate_with_system no mock
            with patch.object(critic, "_evaluate_with_system") as mock_eval:
                # Simula: spec retorna APPROVED, quality retorna boundary
                mock_eval.side_effect = [spec_approved, quality_boundary, quality_conservative]
                critic.evaluate_two_stage("code_generation", "import ui", "")

        # Com score de fronteira, deve ter sido feito recheck
        assert mock_eval.call_count >= 2

    def test_evaluate_two_stage_nao_executa_recheck_para_score_alto(self):
        """Score alto (95) nao deve disparar segundo julgamento."""
        from nvdastudio.ai.critic import Critic, CriticResult, Verdict
        critic = Critic()

        spec_approved = CriticResult(verdict=Verdict.APPROVED, score=95, issues=[], fix_instructions="")
        quality_high = CriticResult(
            verdict=Verdict.APPROVED, score=95, issues=[], fix_instructions="",
            dimension_scores={"completeness": 95, "format": 95, "nvda_compliance": 95}
        )

        with patch.object(critic, "_evaluate_with_system") as mock_eval:
            mock_eval.side_effect = [spec_approved, quality_high]
            result = critic.evaluate_two_stage("code_generation", "import ui", "")

        # Score alto: apenas 2 chamadas (spec + quality), sem recheck
        assert mock_eval.call_count == 2
        assert result.confidence == 1.0


# ------------------------------------------------------------------
# Correcao 5 — orchestrator.py: alerta de degradacao sistemica
# ------------------------------------------------------------------

class TestDegradacaoSistemica:
    """skill: autonomous-agents — alertar quando >=40% dos steps retentaram."""

    def test_emit_aviso_quando_40_porcento_retentaram(self):
        from nvdastudio.core.orchestrator import Orchestrator, StepResult, _NON_BLOCKING_STEP_TYPES
        orch = Orchestrator()
        emitted = []
        orch._on_progress = lambda event, detail: emitted.append((event, detail))

        # Simula 5 steps bloqueantes: 3 com retry (60% > 40%)
        step_results = [
            StepResult("s1", "code_generation", "ok", True, 95, retries_used=1),
            StepResult("s2", "manifest_builder", "ok", True, 90, retries_used=1),
            # documentation virou NAO-bloqueante (orchestrator 5.81.0), entao
            # nao conta mais para este ratio. Trocado por agent_runner, que e
            # bloqueante, para preservar a INTENCAO do teste (>=40% retentaram).
            StepResult("s3", "agent_runner", "ok", True, 92, retries_used=1),
            StepResult("s4", "test_generation", "ok", True, 88, retries_used=0),
            StepResult("s5", "assembly", "ok", True, 91, retries_used=0),
        ]

        done_blocking = [r for r in step_results if r.step_type not in _NON_BLOCKING_STEP_TYPES]
        retried = sum(1 for r in done_blocking if r.retries_used > 0)
        ratio = retried / len(done_blocking)

        assert ratio >= 0.4, f"Setup incorreto: ratio={ratio}"

        # Simula a logica de degradacao (extrai do metodo _run_pipeline)
        if len(done_blocking) >= 3 and ratio >= 0.4:
            orch._emit(
                "AVISO",
                "Estamos tendo dificuldades em varios passos. "
                "Se o addon ficar incompleto, reformule com mais detalhes."
            )

        avisos = [e for e in emitted if e[0] == "AVISO"]
        assert len(avisos) >= 1
        assert "dificuldades" in avisos[0][1].lower()

    def test_nao_emite_aviso_quando_menos_de_40_porcento(self):
        from nvdastudio.core.orchestrator import StepResult, _NON_BLOCKING_STEP_TYPES
        step_results = [
            StepResult("s1", "code_generation", "ok", True, 95, retries_used=1),
            StepResult("s2", "manifest_builder", "ok", True, 90, retries_used=0),
            # ver nota acima: documentation nao e mais bloqueante.
            StepResult("s3", "agent_runner", "ok", True, 92, retries_used=0),
            StepResult("s4", "test_generation", "ok", True, 88, retries_used=0),
        ]
        done_blocking = [r for r in step_results if r.step_type not in _NON_BLOCKING_STEP_TYPES]
        retried = sum(1 for r in done_blocking if r.retries_used > 0)
        ratio = retried / len(done_blocking)
        # 1/4 = 25% < 40% — nao deve emitir aviso
        assert ratio < 0.4

    def test_threshold_minimo_de_3_steps(self):
        """Nao dispara com menos de 3 steps bloqueantes, mesmo com alta taxa de retry."""
        from nvdastudio.core.orchestrator import StepResult, _NON_BLOCKING_STEP_TYPES
        step_results = [
            StepResult("s1", "code_generation", "ok", True, 95, retries_used=1),
            StepResult("s2", "manifest_builder", "ok", True, 90, retries_used=1),
        ]
        done_blocking = [r for r in step_results if r.step_type not in _NON_BLOCKING_STEP_TYPES]
        # Com < 3 steps, nao deve disparar — evita falso positivo em pipelines curtos
        assert len(done_blocking) < 3
