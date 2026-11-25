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
    "nvda_guia", "nvda_regras", "nvda_fonte", "addon_listar", "addon_criar", "addon_arvore",
    "addon_ler", "addon_gravar", "addon_apagar", "addon_validar", "addon_corrigir_estrutura",
    "addon_testar", "addon_dependencias", "addon_empacotar", "pacote_inspecionar",
    "pacote_abrir_no_nvda", "loja_submissao",
}


def _run(workspace: Workspace, scenario):
    async def main():
        async with create_connected_server_and_client_session(build_server(workspace)._mcp_server) as client:
            return await scenario(client)

    return asyncio.run(main())


async def _call(client, name: str, **args: Any) -> dict[str, Any]:
    result = await client.call_tool(name, args)
    payload = result.structuredContent
    if payload is None:
        text = result.content[0].text  # type: ignore[union-attr]
        payload = {"_erro": text} if result.isError else json.loads(text)
    if result.isError:
        return {"_erro": result.content[0].text}  # type: ignore[union-attr]
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
    assert prompts == {"criar_addon", "corrigir_addon", "revisar_acessibilidade"}


def test_fluxo_criar_gravar_validar_empacotar_inspecionar(ws):
    async def scenario(client):
        created = await _call(client, "addon_criar", nome="Ola", resumo="Diz ola")
        assert created["validacao"]["ok"], created
        listed = await _call(client, "addon_listar")
        written = await _call(
            client, "addon_gravar", addon="Ola",
            arquivos=[{"caminho": "../fora.py", "conteudo": "x = 1"},
                      {"caminho": "extra.txt", "conteudo": "oi"}],
        )
        packed = await _call(client, "addon_empacotar", addon="Ola")
        inspected = await _call(client, "pacote_inspecionar", pacote=packed["pacote"])
        return created, listed, written, packed, inspected

    created, listed, written, packed, inspected = _run(ws, scenario)
    assert listed["addons"] == ["Ola"]
    assert written["bloqueados"] == ["../fora.py"] and written["gravados"] == ["extra.txt"]
    assert not (ws.root.parent / "fora.py").exists()
    assert packed["empacotado"] is True and packed["pacote"] == "dist/Ola-0.1.0.nvda-addon"
    with zipfile.ZipFile(ws.root / packed["pacote"]) as archive:
        assert "manifest.ini" in archive.namelist()
    assert inspected["nome"] == "Ola" and inspected["erros_de_leitura"] == []


def test_empacotar_recusa_addon_com_problemas(ws):
    async def scenario(client):
        await _call(client, "addon_criar", nome="Ola")
        await _call(client, "addon_apagar", addon="Ola", caminho="globalPlugins/Ola/__init__.py")
        return await _call(client, "addon_empacotar", addon="Ola")

    result = _run(ws, scenario)
    assert result["empacotado"] is False and not result["validacao"]["ok"]
    assert not (ws.root / "dist").exists()


def test_nome_com_caminho_vira_erro_de_ferramenta(ws):
    async def scenario(client):
        return await _call(client, "addon_validar", addon="../fora")

    assert "invalido" in _run(ws, scenario)["_erro"]


def test_manifest_nao_pode_ser_apagado(ws):
    async def scenario(client):
        await _call(client, "addon_criar", nome="Ola")
        return await _call(client, "addon_apagar", addon="Ola", caminho="manifest.ini")

    assert "manifest" in _run(ws, scenario)["_erro"]


def test_testar_sintaxe_acha_erro_e_nao_executado_nao_vira_sucesso(ws):
    async def scenario(client):
        await _call(client, "addon_criar", nome="Ola")
        await _call(client, "addon_gravar", addon="Ola",
                    arquivos=[{"caminho": "globalPlugins/Ola/quebrado.py", "conteudo": "def (:\n"}])
        return await _call(client, "addon_testar", addon="Ola", etapas=["sintaxe"])

    result = _run(ws, scenario)
    assert result["falhou"] == ["sintaxe"]
    assert "quebrado.py" in result["etapas"][0]["erro"]


def test_validar_aplica_as_regras_por_ast(ws):
    code = (
        "import controlTypes\n"
        "import globalPluginHandler\n\n\n"
        "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
        "\tROLE = controlTypes.ROLE_BUTTON\n"
    )

    async def scenario(client):
        await _call(client, "addon_criar", nome="Ola")
        return await _call(client, "addon_gravar", addon="Ola",
                           arquivos=[{"caminho": "globalPlugins/Ola/papel.py", "conteudo": code}])

    problems = _run(ws, scenario)["validacao"]["problemas"]
    assert any(p["codigo"] == "NVDA-060" and "papel.py" in p["mensagem"] for p in problems)


def test_etapa_desconhecida_e_recusada(ws):
    async def scenario(client):
        await _call(client, "addon_criar", nome="Ola")
        return await _call(client, "addon_testar", addon="Ola", etapas=["magia"])

    assert "desconhecidas" in _run(ws, scenario)["_erro"]


def test_conhecimento_do_nvda(ws):
    async def scenario(client):
        return (
            await _call(client, "nvda_guia", topico="manifest"),
            await _call(client, "nvda_regras", prefixo="WX-A11Y"),
            await _call(client, "nvda_fonte", busca="def script"),
            await _call(client, "nvda_fonte", arquivo="../../../etc/passwd"),
        )

    guia, regras, fonte, fuga = _run(ws, scenario)
    assert "minimumNVDAVersion" in guia["secoes"][0]["texto"]
    assert regras["total"] > 0 and all(r["codigo"].startswith("WX-A11Y") for r in regras["regras"])
    assert fonte["resultados"]
    assert "_erro" in fuga


def test_leitura_marca_o_conteudo_como_dado(ws):
    async def scenario(client):
        await _call(client, "addon_criar", nome="Ola")
        return await _call(client, "addon_ler", addon="Ola", caminho="manifest.ini")

    assert "DADO NAO CONFIAVEL" in _run(ws, scenario)["texto"]


def test_servidor_por_stdio_responde_e_nao_suja_o_stdout(tmp_path):
    """O stdout e do protocolo: se algo imprimir ali, a sessao quebra."""
    src = str(Path(__file__).resolve().parents[2] / "src")
    env = {**os.environ, "PYTHONPATH": src, "NVDASTUDIO_WORKSPACE": str(tmp_path / "w")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "nvdastudio_mcp"], env=env)

    async def main():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                created = await session.call_tool("addon_criar", {"nome": "Ola"})
                tools = await session.list_tools()
                return len(tools.tools), created.isError

    count, is_error = asyncio.run(asyncio.wait_for(main(), 60))
    assert count == len(EXPECTED_TOOLS) and not is_error
