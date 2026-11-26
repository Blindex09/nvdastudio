"""NVDA-009: a lista de atalhos reservados vem do globalCommands.py real do NVDA."""

from nvdastudio_mcp.addon_builder import (
    _NVDA_CORE_GESTURES,
    _normalize_gesture,
    validate_addon_structure,
    write_addon_file,
)
from nvdastudio_mcp.scaffold import build_scaffold


def _problems(tmp_path, gesture: str) -> list[str]:
    files = build_scaffold("MeuAddon").files
    code = files["globalPlugins/MeuAddon/__init__.py"]
    files["globalPlugins/MeuAddon/__init__.py"] = code.replace("kb:NVDA+control+shift+o", gesture)
    for rel, content in files.items():
        write_addon_file(str(tmp_path), rel, content)
    return [p for p in validate_addon_structure(str(tmp_path)) if p.startswith("NVDA-009")]


def test_a_lista_cobre_atalhos_reais_do_core():
    assert len(_NVDA_CORE_GESTURES) > 100
    assert "nvda+t" in _NVDA_CORE_GESTURES  # fala a barra de titulo


def test_normalizacao_ignora_layout_caixa_e_ordem_dos_modificadores():
    assert _normalize_gesture("kb(laptop):NVDA+Shift+S") == _normalize_gesture("kb:shift+nvda+s")


def test_atalho_reservado_e_reportado(tmp_path):
    assert _problems(tmp_path, "kb:NVDA+t")


def test_atalho_reservado_no_layout_laptop_e_com_outra_ordem_e_reportado(tmp_path):
    assert _problems(tmp_path, "kb(laptop):t+NVDA".replace("t+NVDA", "NVDA+t"))


def test_atalho_livre_passa(tmp_path):
    assert _problems(tmp_path, "kb:NVDA+control+shift+o") == []
