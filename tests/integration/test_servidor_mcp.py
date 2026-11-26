"""Servidor MCP pelo protocolo de verdade (cliente em memoria e por stdio)."""

import asyncio
import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from nvdastudio_mcp.server import build_server
from nvdastudio_mcp.workspace import Workspace

EXPECTED_TOOLS = {
    "nvda_guide", "nvda_rules", "nvda_source", "addon_list", "addon_create", "addon_tree",
    "addon_read", "addon_write", "addon_delete", "addon_validate", "addon_fix_structure",
    "addon_test", "addon_dependencies", "addon_package", "package_inspect",
    "package_open_in_nvda", "store_submission",
}


def _run(workspace: Workspace, scenario):
    async def main():
        async with create_connected_server_and_client_session(build_server(workspace)._mcp_server) as client:
            return await scenario(client)

    return asyncio.run(main())


async def _call(client, tool: str, /, **args: Any) -> dict[str, Any]:
    result = await client.call_tool(tool, args)
    payload = result.structuredContent
    if payload is None:
        text = result.content[0].text  # type: ignore[union-attr]
        payload = {"_error": text} if result.isError else json.loads(text)
    if result.isError:
        return {"_error": result.content[0].text}  # type: ignore[union-attr]
    return payload.get("result", payload)


@pytest.fixture
def ws(tmp_path):
    workspace = Workspace(tmp_path / "trabalho")
    workspace.ensure()
    return workspace


def test_lista_todas_as_ferramentas_e_os_roteiros(ws):
    async def scenario(client):
        tools = {t.name for t in (await client.list_tools()).tools}
        prompts = {p.name for p in (await client.list_prompts()).prompts}
        return tools, prompts

    tools, prompts = _run(ws, scenario)
    assert tools == EXPECTED_TOOLS
    assert prompts == {"create_addon", "fix_addon", "review_accessibility"}


def test_fluxo_criar_gravar_validar_empacotar_inspecionar(ws):
    async def scenario(client):
        created = await _call(client, "addon_create", name="Ola", summary="Diz ola")
        assert created["validation"]["ok"], created
        listed = await _call(client, "addon_list")
        written = await _call(
            client, "addon_write", addon="Ola",
            files=[{"path": "../fora.py", "content": "x = 1"},
                      {"path": "extra.txt", "content": "oi"}],
        )
        packed = await _call(client, "addon_package", addon="Ola")
        inspected = await _call(client, "package_inspect", package=packed["package"])
        return created, listed, written, packed, inspected

    created, listed, written, packed, inspected = _run(ws, scenario)
    assert listed["addons"] == ["Ola"]
    assert written["blocked"] == ["../fora.py"] and written["written"] == ["extra.txt"]
    assert not (ws.root.parent / "fora.py").exists()
    assert packed["packaged"] is True and packed["package"] == "dist/Ola-0.1.0.nvda-addon"
    with zipfile.ZipFile(ws.root / packed["package"]) as archive:
        assert "manifest.ini" in archive.namelist()
    assert inspected["name"] == "Ola" and inspected["read_errors"] == []


def test_empacotar_recusa_addon_com_problemas(ws):
    async def scenario(client):
        await _call(client, "addon_create", name="Ola")
        await _call(client, "addon_delete", addon="Ola", path="globalPlugins/Ola/__init__.py")
        return await _call(client, "addon_package", addon="Ola")

    result = _run(ws, scenario)
    assert result["packaged"] is False and not result["validation"]["ok"]
    assert not (ws.root / "dist").exists()


def test_nome_com_caminho_vira_error_de_ferramenta(ws):
    async def scenario(client):
        return await _call(client, "addon_validate", addon="../fora")

    assert "invalido" in _run(ws, scenario)["_error"]


def test_manifest_nao_pode_ser_apagado(ws):
    async def scenario(client):
        await _call(client, "addon_create", name="Ola")
        return await _call(client, "addon_delete", addon="Ola", path="manifest.ini")

    assert "manifest" in _run(ws, scenario)["_error"]


def test_testar_sintaxe_acha_error_e_nao_executado_nao_vira_sucesso(ws):
    async def scenario(client):
        await _call(client, "addon_create", name="Ola")
        await _call(client, "addon_write", addon="Ola",
                    files=[{"path": "globalPlugins/Ola/quebrado.py", "content": "def (:\n"}])
        return await _call(client, "addon_test", addon="Ola", stages=["syntax"])

    result = _run(ws, scenario)
    assert result["failed"] == ["syntax"]
    assert "quebrado.py" in result["stages"][0]["error"]


def test_validar_aplica_as_regras_por_ast(ws):
    code = (
        "import controlTypes\n"
        "import globalPluginHandler\n\n\n"
        "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
        "\tROLE = controlTypes.ROLE_BUTTON\n"
    )

    async def scenario(client):
        await _call(client, "addon_create", name="Ola")
        return await _call(client, "addon_write", addon="Ola",
                           files=[{"path": "globalPlugins/Ola/papel.py", "content": code}])

    problems = _run(ws, scenario)["validation"]["problems"]
    assert any(p["code"] == "NVDA-060" and "papel.py" in p["message"] for p in problems)


def test_etapa_desconhecida_e_recusada(ws):
    async def scenario(client):
        await _call(client, "addon_create", name="Ola")
        return await _call(client, "addon_test", addon="Ola", stages=["magia"])

    assert "desconhecidas" in _run(ws, scenario)["_error"]


def test_conhecimento_do_nvda(ws):
    async def scenario(client):
        return (
            await _call(client, "nvda_guide", topic="manifest"),
            await _call(client, "nvda_rules", prefix="WX-A11Y"),
            await _call(client, "nvda_source", search="def script"),
            await _call(client, "nvda_source", file="../../../etc/passwd"),
        )

    guia, regras, fonte, fuga = _run(ws, scenario)
    assert "minimumNVDAVersion" in guia["sections"][0]["text"]
    assert regras["total"] > 0 and all(r["code"].startswith("WX-A11Y") for r in regras["rules"])
    assert fonte["results"]
    assert "_error" in fuga


def test_leitura_marca_o_conteudo_como_dado(ws):
    async def scenario(client):
        await _call(client, "addon_create", name="Ola")
        return await _call(client, "addon_read", addon="Ola", path="manifest.ini")

    assert "DADO NAO CONFIAVEL" in _run(ws, scenario)["text"]


def test_servidor_por_stdio_responde_e_nao_suja_o_stdout(tmp_path):
    """O stdout e do protocolo: se algo imprimir ali, a sessao quebra."""
    src = str(Path(__file__).resolve().parents[2] / "src")
    env = {**os.environ, "PYTHONPATH": src, "NVDASTUDIO_WORKSPACE": str(tmp_path / "w")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "nvdastudio_mcp"], env=env)

    async def main():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                created = await session.call_tool("addon_create", {"name": "Ola"})
                tools = await session.list_tools()
                return len(tools.tools), created.isError

    count, is_errorr = asyncio.run(asyncio.wait_for(main(), 60))
    assert count == len(EXPECTED_TOOLS) and not is_errorr


def test_verificacao_que_nao_rodou_nao_vira_ok(ws):
    """Resiliencia de um app module (sem globalPlugins) nao executa nada: deve voltar not_run."""

    async def scenario(client):
        await _call(client, "addon_create", name="App", kind="appModule", app="notepad")
        return await _call(client, "addon_test", addon="App", stages=["resilience"])

    result = _run(ws, scenario)
    assert result["stages"][0]["status"] == "not_run"
    assert result["not_run"] == ["resilience"]


def test_dependencias_ignoradas_voltam_com_o_motivo(ws):
    async def scenario(client):
        await _call(client, "addon_create", name="Ola")
        return await _call(client, "addon_dependencies", addon="Ola", packages=["../evil", "json", "wx"])

    result = _run(ws, scenario)
    assert result["installed"] == []
    assert [p["package"] for p in result["progress"]] == ["../evil", "json", "wx"]
    assert all(p["status"] == "ignored" and p["detail"] for p in result["progress"])


def test_loja_nao_inventa_url_de_download(ws):
    async def scenario(client):
        await _call(client, "addon_create", name="Ola")
        packed = await _call(client, "addon_package", addon="Ola")
        return await _call(client, "store_submission", package=packed["package"])

    result = _run(ws, scenario)
    assert result["metadata"]["URL"] == ""
    assert "URL" in result["missing_fields"] and "homepage" in result["missing_fields"]


def test_addon_sem_url_informada_nao_ganha_endereco_falso(ws):
    async def scenario(client):
        await _call(client, "addon_create", name="Ola")
        return await _call(client, "addon_read", addon="Ola", path="manifest.ini")

    assert "url =" not in _run(ws, scenario)["text"]
