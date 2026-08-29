from pathlib import Path
import ast


def _load_module_ast() -> tuple[str, ast.Module]:
    src_path = Path("addon/globalPlugins/nvdastudio/builder/nvda_context.py")
    src = src_path.read_text(encoding="utf-8", errors="ignore").lstrip("\ufeff")
    return src, ast.parse(src)


def _get_annotated_literal(module: ast.Module, name: str):
    for node in module.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name:
                return ast.literal_eval(node.value)
    raise AssertionError(f"Constante anotada nao encontrada: {name}")


def test_fallback_matrix_cobre_todas_as_regras():
    src, module = _load_module_ast()

    nvda_rules = _get_annotated_literal(module, "NVDA_DETECTION_RULES")
    wx_rules = _get_annotated_literal(module, "WX_A11Y_RULES")
    dtk_rules = _get_annotated_literal(module, "DTK_A11Y_RULES")
    arch_rule_ids = _get_annotated_literal(module, "ARCH_RULE_IDS")
    overrides = _get_annotated_literal(module, "_RULE_FALLBACK_OVERRIDES")

    all_rule_ids = (
        {rid for rid, _, _ in nvda_rules}
        | {rid for rid, _, _ in wx_rules}
        | {rid for rid, _, _ in dtk_rules}
        | set(arch_rule_ids)
    )

    assert len(all_rule_ids) == 96, "Esperado: 61 NVDA + 14 WX + 12 DTK + 9 ARCH = 96 regras"
    assert set(overrides.keys()).issubset(all_rule_ids), "Overrides contem IDs fora do catalogo de regras"

    # A cobertura completa depende do default STRICT_ONLY no builder + overrides.
    assert "RULE_FALLBACK_MATRIX: dict[str, tuple[str, str]] = _build_rule_fallback_matrix()" in src
    assert '("STRICT_ONLY", "Sem fallback: corrigir exatamente a violacao da regra.")' in src


def test_fallback_matrix_e_injetada_no_prompt_e_no_chat_context():
    src, _ = _load_module_ast()

    assert "RULE_FALLBACK_MATRIX_TEXT: str = _format_rule_fallback_matrix()" in src
    assert "MATRIZ DE FALLBACK POR REGRA (COBERTURA 100%)" in src

    # Uma injecao no NVDA_SYSTEM_PROMPT e outra no contexto dinamico de chat.
    assert src.count("{RULE_FALLBACK_MATRIX_TEXT}") >= 2
