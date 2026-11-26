"""Versoes do manifest conforme o AddonManifest e o Developer Guide do NVDA."""

from nvdastudio_mcp.addon_builder import validate_addon_structure, write_addon_file
from nvdastudio_mcp.scaffold import build_scaffold


def _problems(tmp_path, **fields: str) -> list[str]:
    files = build_scaffold("MeuAddon").files
    manifest = files["manifest.ini"]
    for key, value in fields.items():
        lines = [ln for ln in manifest.splitlines() if not ln.startswith(key + " =")]
        manifest = "\n".join(lines) + f"\n{key} = {value}\n"
    files["manifest.ini"] = manifest
    for rel, content in files.items():
        write_addon_file(str(tmp_path), rel, content)
    return [p for p in validate_addon_structure(str(tmp_path)) if p.startswith(("NVDA-005", "NVDA-013"))]


def test_versao_com_aspas_como_no_guia_do_desenvolvedor_e_aceita(tmp_path):
    assert _problems(tmp_path, minimumNVDAVersion='"2026.1.1"', lastTestedNVDAVersion='"2026.3.1"') == []


def test_minimo_maior_que_ultimo_testado_e_reportado(tmp_path):
    problems = _problems(tmp_path, minimumNVDAVersion="2026.3.1", lastTestedNVDAVersion="2026.1.0")
    assert any("is greater than" in p for p in problems)


def test_versao_do_addon_major_minor_e_valida(tmp_path):
    assert _problems(tmp_path, version="1.0") == []
