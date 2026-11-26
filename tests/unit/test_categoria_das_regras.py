"""A categoria de cada regra (defeito, conselho, politica) fica coerente com o que o validador emite."""

import re
from pathlib import Path

from nvdastudio_mcp.rule_registry import DEFECT_CODES, POLICY_CODES, RULE_REGISTRY, rule_kind

SRC = Path(__file__).resolve().parents[2] / "src" / "nvdastudio_mcp"
CODE = re.compile(r"\b((?:NVDA|WX-A11Y|STRUCTURE|POLICY|MANIFEST)-\d{3})\b")


def _emitted_codes() -> set[str]:
    emitted: set[str] = set()
    for name in ("addon_builder.py", "ast_validator.py"):
        text = (SRC / name).read_text(encoding="utf-8")
        emitted |= set(re.findall(r'f?"((?:NVDA|WX-A11Y|STRUCTURE|POLICY|MANIFEST)-\d{3}): ', text))
    return emitted


def test_todo_codigo_marcado_como_defeito_ou_politica_existe():
    known = set(RULE_REGISTRY) | _emitted_codes()
    assert (DEFECT_CODES | POLICY_CODES) <= known, sorted((DEFECT_CODES | POLICY_CODES) - known)


def test_defeito_so_para_o_que_quebra_o_addon():
    # conferido no codigo do NVDA 2026.3.1 e nos addons instalados (ver rule_registry.py)
    for code in ("NVDA-019", "NVDA-021", "NVDA-022", "NVDA-009", "NVDA-049", "NVDA-003", "WX-A11Y-001", "STRUCTURE-006"):
        assert rule_kind(code) == "advisory", code
    for code in ("STRUCTURE-009", "NVDA-063", "NVDA-064", "MANIFEST-001"):
        assert rule_kind(code) == "defect", code
