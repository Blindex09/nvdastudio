import pytest

from nvdastudio_mcp.addon_builder import validate_addon_structure, write_addon_file
from nvdastudio_mcp.scaffold import ScaffoldError, build_scaffold


def _materialize(tmp_path, files: dict[str, str]) -> str:
    for rel, content in files.items():
        assert write_addon_file(str(tmp_path), rel, content)
    return str(tmp_path)


def test_esqueleto_de_global_plugin_passa_no_validador(tmp_path):
    folder = _materialize(tmp_path, build_scaffold("MeuAddon", "globalPlugin", "Teste").files)
    assert validate_addon_structure(folder) == []


def test_esqueleto_de_app_module_passa_no_validador(tmp_path):
    scaffold = build_scaffold("MeuAddon", "appModule", "Teste", app_name="notepad")
    assert "appModules/notepad.py" in scaffold.files
    assert validate_addon_structure(_materialize(tmp_path, scaffold.files)) == []


def test_esqueleto_usa_o_baseline_do_projeto(tmp_path):
    manifest = build_scaffold("MeuAddon").files["manifest.ini"]
    assert "minimumNVDAVersion = 2026.1.1" in manifest
    assert "lastTestedNVDAVersion = 2026.2.0" in manifest


def test_codigo_do_esqueleto_usa_tab(tmp_path):
    code = build_scaffold("MeuAddon").files["globalPlugins/MeuAddon/__init__.py"]
    assert "\n\tdef terminate" in code
    assert "\n    " not in code


@pytest.mark.parametrize("nome", ["", "1Addon", "meu addon", "a", "Meu-Addon", "x" * 41])
def test_nome_invalido(nome):
    with pytest.raises(ScaffoldError):
        build_scaffold(nome)


def test_tipo_invalido():
    with pytest.raises(ScaffoldError):
        build_scaffold("MeuAddon", "synthDriver")


@pytest.mark.parametrize("app", ["", "Notepad", "note pad", "../x"])
def test_app_module_exige_nome_de_app_valido(app):
    with pytest.raises(ScaffoldError):
        build_scaffold("MeuAddon", "appModule", app_name=app)


def test_resumo_multilinha_nao_quebra_o_manifest():
    manifest = build_scaffold("MeuAddon", summary="linha um\nlinha dois").files["manifest.ini"]
    assert "summary = linha um linha dois\n" in manifest
