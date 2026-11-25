import pytest

from nvdastudio_mcp.workspace import Workspace, WorkspaceError


@pytest.fixture
def ws(tmp_path):
    workspace = Workspace(tmp_path / "trabalho")
    workspace.ensure()
    return workspace


def _make_addon(ws: Workspace, name: str = "Meu") -> None:
    folder = ws.root / name
    folder.mkdir()
    (folder / "manifest.ini").write_text("name = Meu\n", encoding="utf-8")


@pytest.mark.parametrize("bad", ["", " ", ".", "..", "a/b", "a\\b", "C:\\x", "../fora", "x" * 65])
def test_nome_de_addon_invalido_e_recusado(ws, bad):
    with pytest.raises(WorkspaceError):
        ws.addon_dir(bad, must_exist=False)


def test_addon_inexistente_e_erro(ws):
    with pytest.raises(WorkspaceError):
        ws.addon_dir("Nada")


@pytest.mark.parametrize("rel", ["../fora.txt", "a/../../fora.txt", "/etc/passwd", "C:/Windows/x", ""])
def test_arquivo_nao_escapa_do_addon(ws, rel):
    _make_addon(ws)
    with pytest.raises(WorkspaceError):
        ws.file_in_addon("Meu", rel)


def test_arquivo_dentro_do_addon_resolve(ws):
    _make_addon(ws)
    path = ws.file_in_addon("Meu", "globalPlugins/Meu/__init__.py")
    assert ws.root in path.parents


def test_link_simbolico_para_fora_e_recusado(ws, tmp_path):
    _make_addon(ws)
    outside = tmp_path / "segredo"
    outside.mkdir()
    link = ws.root / "Meu" / "atalho"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("sem permissao para criar link simbolico")
    with pytest.raises(WorkspaceError):
        ws.file_in_addon("Meu", "atalho/arquivo.txt")


def test_listar_so_mostra_pastas_com_manifest(ws):
    _make_addon(ws, "Um")
    (ws.root / "SemManifest").mkdir()
    assert ws.list_addons() == ["Um"]


def test_pacote_precisa_da_extensao_e_existir(ws):
    with pytest.raises(WorkspaceError):
        ws.package_path("x.zip")
    with pytest.raises(WorkspaceError):
        ws.package_path("nao-existe.nvda-addon")


def test_pacote_fora_da_pasta_e_recusado(ws, tmp_path):
    fora = tmp_path / "fora.nvda-addon"
    fora.write_bytes(b"PK")
    with pytest.raises(WorkspaceError):
        ws.package_path(str(fora))
