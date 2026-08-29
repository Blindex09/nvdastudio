from nvdastudio.builder.addon_builder import extract_code_blocks
from nvdastudio.core.planner import (
    STEP_DOCUMENTATION, STEP_MODEL_MAP, STEP_REASONING_MAP,
)
from nvdastudio.core.orchestrator import _NON_BLOCKING_STEP_TYPES
from nvdastudio.sub_agents.dispatcher import dispatch_step
from unittest.mock import patch, MagicMock


class TestStepDocumentationConstante:
    def test_constante_definida(self):
        assert STEP_DOCUMENTATION == "documentation"

    def test_no_model_map(self):
        assert STEP_DOCUMENTATION in STEP_MODEL_MAP

    def test_no_reasoning_map(self):
        assert STEP_DOCUMENTATION in STEP_REASONING_MAP

    def test_nao_bloqueante_no_orchestrator(self):
        # Q8.3: falha em documentation agora BLOQUEIA o pipeline (usuario decidiu).
        # documentation foi removida de _NON_BLOCKING_STEP_TYPES.
        assert STEP_DOCUMENTATION not in _NON_BLOCKING_STEP_TYPES


class TestExtractCodeBlocksHtml:
    def test_extrai_bloco_html_anotado(self):
        texto = '```html:doc/pt_BR/userGuide.html\n<html></html>\n```'
        blocks = extract_code_blocks(texto)
        assert len(blocks) == 1
        assert blocks[0]["language"] == "html"
        assert blocks[0]["filename"] == "doc/pt_BR/userGuide.html"
        assert "<html>" in blocks[0]["code"]

    def test_extrai_html_junto_com_python_e_ini(self):
        texto = (
            '```python:globalPlugins/Test/__init__.py\npass\n```\n'
            '```ini:manifest.ini\nname = Test\n```\n'
            '```html:doc/pt_BR/userGuide.html\n<html></html>\n```'
        )
        blocks = extract_code_blocks(texto)
        langs = {b["language"] for b in blocks}
        assert "python" in langs
        assert "ini" in langs
        assert "html" in langs
        assert len(blocks) == 3

    def test_html_sem_path_usa_fallback(self):
        texto = '```html\n<html></html>\n```'
        blocks = extract_code_blocks(texto)
        assert len(blocks) == 1
        assert blocks[0]["language"] == "html"
        assert blocks[0]["filename"].endswith(".html")

    def test_html_nao_executado(self):
        texto = '```html:doc/pt_BR/userGuide.html\n<script>evil()</script>\n```'
        blocks = extract_code_blocks(texto)
        # Retorna como string — nunca executa
        assert "evil()" in blocks[0]["code"]


class TestDispatcherDocumentation:
    def test_documentation_tem_handler(self):
        mock_resp = MagicMock()
        mock_resp.content = "doc html"
        mock_resp.reasoning = None
        mock_resp.tool_calls = []
        mock_resp.executed_tools = []
        mock_resp.usage = MagicMock(total_tokens=10)

        with patch("nvdastudio.sub_agents.doc_generator._run_sub_agent", return_value="doc html"):
            result = dispatch_step(
                step_type=STEP_DOCUMENTATION,
                prompt="Gere documentacao",
                model_id="kimi-k2.6",
                reasoning_params={},
            )
        assert isinstance(result, str)


class TestMinimalPlanTemDocumentation:
    def test_plano_minimo_tem_step_documentation(self):
        from nvdastudio.core.planner import Planner
        plan_dict = Planner._minimal_plan()
        step_types = [s["step_type"] for s in plan_dict["steps"]]
        assert STEP_DOCUMENTATION in step_types

    def test_documentation_antes_do_assembly(self):
        from nvdastudio.core.planner import Planner, STEP_ASSEMBLY
        plan_dict = Planner._minimal_plan()
        step_types = [s["step_type"] for s in plan_dict["steps"]]
        doc_idx = step_types.index(STEP_DOCUMENTATION)
        asm_idx = step_types.index(STEP_ASSEMBLY)
        assert doc_idx < asm_idx

    def test_assembly_depende_de_documentation(self):
        from nvdastudio.core.planner import Planner, STEP_ASSEMBLY
        plan_dict = Planner._minimal_plan()
        assembly = next(s for s in plan_dict["steps"] if s["step_type"] == STEP_ASSEMBLY)
        doc_step = next(s for s in plan_dict["steps"] if s["step_type"] == STEP_DOCUMENTATION)
        assert doc_step["step_id"] in assembly["depends_on"]
