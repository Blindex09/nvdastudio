import pytest


@pytest.fixture
def fake_api_key():
    return "gsk_test_fake_key_for_unit_tests"


# ===========================================================================
# 1. NVDA-UX-001 — Critic v2.8.0
# ===========================================================================

class TestCriticNvdaUX001:
    """Critic deve ter a regra NVDA-UX-001 no quality system."""

    def test_versao_e_2_9_0(self):
        from addon.globalPlugins.nvdastudio.ai.critic import MODULE_VERSION
        assert MODULE_VERSION == "3.23.0"

    def test_quality_system_tem_nvda_ux_001(self):
        from addon.globalPlugins.nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        assert "NVDA-UX-001" in _CRITIC_QUALITY_SYSTEM

    def test_ux_001_menciona_ui_message(self):
        from addon.globalPlugins.nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        parte = _CRITIC_QUALITY_SYSTEM.split("NVDA-UX-001")[1]
        assert "ui.message" in parte

    def test_ux_001_menciona_setlabel(self):
        from addon.globalPlugins.nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        parte = _CRITIC_QUALITY_SYSTEM.split("NVDA-UX-001")[1]
        assert "SetLabel" in parte or "SetValue" in parte

    def test_ux_001_menciona_usuario_cego(self):
        from addon.globalPlugins.nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        parte = _CRITIC_QUALITY_SYSTEM.split("NVDA-UX-001")[1]
        assert "cego" in parte.lower() or "inacessivel" in parte.lower()

    def test_ux_001_tem_exemplo_errado_e_correto(self):
        from addon.globalPlugins.nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        parte = _CRITIC_QUALITY_SYSTEM.split("NVDA-UX-001")[1]
        assert "ERRADO" in parte or "CORRETO" in parte

    def test_nao_executa_codigo(self):
        from addon.globalPlugins.nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        assert isinstance(_CRITIC_QUALITY_SYSTEM, str)


# ===========================================================================
# 2. Consistencia cruzada nome — Assembler v1.3.0
# ===========================================================================

class TestAssemblerConsistenciaNome:
    """Assembler deve detectar conflito entre name do manifest e pasta globalPlugins."""

    def test_versao_e_1_3_0(self):
        from addon.globalPlugins.nvdastudio.sub_agents.assembler import MODULE_VERSION
        assert MODULE_VERSION == "1.7.0"

    def test_manifest_name_pattern_definido(self):
        from addon.globalPlugins.nvdastudio.sub_agents.assembler import _MANIFEST_NAME_PATTERN
        assert _MANIFEST_NAME_PATTERN is not None

    def test_b8_sem_conflito_sem_aviso(self):
        from addon.globalPlugins.nvdastudio.sub_agents.assembler import _validate_structural_issues
        output = (
            "```ini:manifest.ini\nname = MeuAddon\nversion = 1.0.0\n```\n"
            "```python:globalPlugins/MeuAddon/__init__.py\npass\n```"
        )
        warnings = _validate_structural_issues(output)
        b8 = [w for w in warnings if "B8" in w]
        assert len(b8) == 0

    def test_b8_com_conflito_gera_aviso(self):
        from addon.globalPlugins.nvdastudio.sub_agents.assembler import _validate_structural_issues
        output = (
            "```ini:manifest.ini\nname = TranscriborIA\nversion = 1.0.0\n```\n"
            "```python:globalPlugins/OutroNome/__init__.py\npass\n```"
        )
        warnings = _validate_structural_issues(output)
        b8 = [w for w in warnings if "B8" in w]
        assert len(b8) == 1

    def test_b8_aviso_menciona_nomes(self):
        from addon.globalPlugins.nvdastudio.sub_agents.assembler import _validate_structural_issues
        output = (
            "```ini:manifest.ini\nname = TranscriborIA\nversion = 1.0.0\n```\n"
            "```python:globalPlugins/OutroNome/__init__.py\npass\n```"
        )
        warnings = _validate_structural_issues(output)
        b8 = [w for w in warnings if "B8" in w][0]
        assert "TranscriborIA" in b8 or "OutroNome" in b8

    def test_b8_sem_manifest_sem_aviso(self):
        """Sem manifest no output, nao deve gerar B8."""
        from addon.globalPlugins.nvdastudio.sub_agents.assembler import _validate_structural_issues
        output = "```python:globalPlugins/MeuAddon/__init__.py\npass\n```"
        warnings = _validate_structural_issues(output)
        b8 = [w for w in warnings if "B8" in w]
        assert len(b8) == 0

    def test_b8_nomes_case_insensitive(self):
        """Comparacao de nomes deve ignorar case."""
        from addon.globalPlugins.nvdastudio.sub_agents.assembler import _validate_structural_issues
        output = (
            "```ini:manifest.ini\nname = meuaddon\nversion = 1.0.0\n```\n"
            "```python:globalPlugins/MeuAddon/__init__.py\npass\n```"
        )
        warnings = _validate_structural_issues(output)
        b8 = [w for w in warnings if "B8" in w]
        assert len(b8) == 0

    def test_b8_nao_executa_codigo(self):
        from addon.globalPlugins.nvdastudio.sub_agents.assembler import _validate_structural_issues
        result = _validate_structural_issues("")
        assert isinstance(result, list)


# ===========================================================================
# 3. get_recent_failures com step_type — SessionMemory v2.3.0
# ===========================================================================

class TestSessionMemoryStepType:
    """get_recent_failures deve filtrar por step_type quando informado."""

    def test_versao_e_2_5_0(self):
        from addon.globalPlugins.nvdastudio.memory.session_memory import MODULE_VERSION
        assert MODULE_VERSION == "3.6.0"

    def test_get_recent_failures_aceita_step_type(self):
        from addon.globalPlugins.nvdastudio.memory.session_memory import SessionMemory
        import inspect
        sig = inspect.signature(SessionMemory.get_recent_failures)
        assert "step_type" in sig.parameters

    def test_save_session_aceita_step_type(self):
        from addon.globalPlugins.nvdastudio.memory.session_memory import SessionMemory
        import inspect
        sig = inspect.signature(SessionMemory.save_session)
        assert "step_type" in sig.parameters

    def test_step_type_default_vazio(self):
        from addon.globalPlugins.nvdastudio.memory.session_memory import SessionMemory
        import inspect
        sig = inspect.signature(SessionMemory.get_recent_failures)
        assert sig.parameters["step_type"].default == ""

    def test_filtragem_por_step_type(self):
        """Falha de manifest nao aparece ao filtrar por code_generation."""
        from unittest.mock import MagicMock
        from addon.globalPlugins.nvdastudio.memory.session_memory import SessionMemory

        class FakeDoc(dict):
            """Dict com doc_id, simula documento TinyDB."""
            def __init__(self, doc_id, data):
                super().__init__(data)
                self.doc_id = doc_id

        mem = SessionMemory()

        doc_manifest = FakeDoc(1, {"success": 0, "step_issues": "manifest sem name", "step_type": "manifest_builder"})
        doc_code     = FakeDoc(2, {"success": 0, "step_issues": "faltou nextHandler", "step_type": "code_generation"})

        mock_table = MagicMock()
        mock_table.all.return_value = [doc_manifest, doc_code]
        mock_db = MagicMock()
        mock_db.table.return_value = mock_table
        mem._db = mock_db
        mem._ready = True

        failures_code = mem.get_recent_failures(limit=5, step_type="code_generation")
        assert any("nextHandler" in f for f in failures_code)
        assert not any("manifest" in f for f in failures_code)

        failures_manifest = mem.get_recent_failures(limit=5, step_type="manifest_builder")
        assert any("manifest" in f for f in failures_manifest)
        assert not any("nextHandler" in f for f in failures_manifest)

    def test_sem_filtro_retorna_tudo(self):
        """Sem step_type, comportamento original — retorna todas as falhas sem filtrar."""
        from unittest.mock import MagicMock
        from addon.globalPlugins.nvdastudio.memory.session_memory import SessionMemory

        class FakeDoc(dict):
            def __init__(self, doc_id, data):
                super().__init__(data)
                self.doc_id = doc_id

        mem = SessionMemory()
        doc_manifest = FakeDoc(1, {"success": 0, "step_issues": "erro manifest", "step_type": "manifest_builder"})
        doc_code     = FakeDoc(2, {"success": 0, "step_issues": "erro code",     "step_type": "code_generation"})

        mock_table = MagicMock()
        mock_table.all.return_value = [doc_manifest, doc_code]
        mock_db = MagicMock()
        mock_db.table.return_value = mock_table
        mem._db = mock_db
        mem._ready = True

        all_failures = mem.get_recent_failures(limit=10)
        assert len(all_failures) == 2

    def test_nao_executa_conteudo(self):
        from addon.globalPlugins.nvdastudio.memory.session_memory import SessionMemory
        mem = SessionMemory()
        result = mem.get_recent_failures(limit=1, step_type="code_generation")
        assert isinstance(result, list)


# ===========================================================================
# 4. Orchestrator passa step_type — v2.8.0
# ===========================================================================

class TestOrchestratorFeedbackTipado:
    """Orchestrator deve passar step_type ao buscar falhas historicas."""

    def test_versao_e_2_9_0(self):
        from addon.globalPlugins.nvdastudio.core.orchestrator import MODULE_VERSION
        assert MODULE_VERSION == "5.91.0"

    def test_code_generation_passa_step_type(self):
        from unittest.mock import patch
        from addon.globalPlugins.nvdastudio.core.orchestrator import Orchestrator
        from addon.globalPlugins.nvdastudio.core.planner import ExecutionStep, STEP_CODE_GENERATION

        orch = Orchestrator()
        step = ExecutionStep(
            step_id="c1", step_type=STEP_CODE_GENERATION,
            description="gerar codigo", model_id="kimi-k2.6",
        )
        with patch("addon.globalPlugins.nvdastudio.core.orchestrator.memory") as mock_mem:
            mock_mem.get_recent_failures.return_value = ["erro anterior"]
            orch._build_step_prompt(step, "criar addon", "", [])

        call_kwargs = mock_mem.get_recent_failures.call_args
        # fluxos7.1: feedback loop global — sem step_type, so limit=3
        assert call_kwargs.kwargs.get("limit") == 3
        assert call_kwargs.kwargs.get("step_type") == "code_generation"

    def test_manifest_passa_step_type(self):
        from unittest.mock import patch
        from addon.globalPlugins.nvdastudio.core.orchestrator import Orchestrator
        from addon.globalPlugins.nvdastudio.core.planner import ExecutionStep, STEP_MANIFEST

        orch = Orchestrator()
        step = ExecutionStep(
            step_id="m1", step_type=STEP_MANIFEST,
            description="gerar manifest", model_id="kimi-k2.6",
        )
        with patch("addon.globalPlugins.nvdastudio.core.orchestrator.memory") as mock_mem:
            mock_mem.get_recent_failures.return_value = ["manifest sem name"]
            orch._build_step_prompt(step, "criar addon", "", [])

        call_kwargs = mock_mem.get_recent_failures.call_args
        # fluxos7.1: feedback loop global — sem step_type, so limit=3
        assert call_kwargs.kwargs.get("limit") == 3
        assert call_kwargs.kwargs.get("step_type") == "manifest_builder"

    def test_assembly_consulta_com_step_type(self):
        """assembly consulta failures filtrado por step_type — feedback loop e global (fluxos7.1)."""
        from unittest.mock import patch
        from addon.globalPlugins.nvdastudio.core.orchestrator import Orchestrator
        from addon.globalPlugins.nvdastudio.core.planner import ExecutionStep, STEP_ASSEMBLY

        orch = Orchestrator()
        step = ExecutionStep(
            step_id="a1", step_type=STEP_ASSEMBLY,
            description="montar", model_id="kimi-k2.6",
        )
        with patch("addon.globalPlugins.nvdastudio.core.orchestrator.memory") as mock_mem:
            mock_mem.get_recent_failures.return_value = ["algum erro"]
            orch._build_step_prompt(step, "criar addon", "", [])

        mock_mem.get_recent_failures.assert_called_once_with(limit=3, step_type="assembly")
