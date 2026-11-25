# NVDAStudio

Servidor MCP que dá ao Claude as ferramentas para criar, corrigir, testar e empacotar addons do leitor de telas NVDA.
O Claude entende o pedido e escreve o código; o NVDAStudio guarda o conhecimento do NVDA, confina os arquivos numa pasta de trabalho,
valida, testa, empacota e abre o pacote no NVDA.

## Usar

Requisitos: Python 3.11+ e `pip install -r requirements.txt`. Docker com a imagem `python:3.11-slim` é opcional: sem ele, as etapas que
executam código do addon voltam como `nao_executado`.

Claude Code: o arquivo `.mcp.json` na raiz já registra o servidor (pasta de trabalho `workspace/`).

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "nvdastudio": {
      "command": "python",
      "args": ["-m", "nvdastudio_mcp"],
      "env": { "PYTHONPATH": "C:\projetos IA\nvdastudio\src", "NVDASTUDIO_WORKSPACE": "C:\Users\voce\NVDAStudio" }
    }
  }
}
```

## Ferramentas

- Conhecimento: `nvda_guia`, `nvda_regras`, `nvda_fonte`.
- Addons: `addon_listar`, `addon_criar`, `addon_arvore`, `addon_ler`, `addon_gravar`, `addon_apagar`.
- Verificação: `addon_validar`, `addon_corrigir_estrutura`, `addon_testar` (sintaxe, lint, tipos, carregamento, resiliência, testes).
- Pacote: `addon_dependencias`, `addon_empacotar`, `pacote_inspecionar`, `pacote_abrir_no_nvda`, `loja_submissao`.
- Roteiros: `criar_addon`, `corrigir_addon`, `revisar_acessibilidade`. Recursos: `nvdastudio://guia` e `nvdastudio://guia/{topico}`.

Baseline dos addons novos: NVDA 2026.1.1+, testado em 2026.2.0.

## Desenvolver

```powershell
python -m ruff check .
python -m mypy src
python -m pytest -q
```

Regras de trabalho em [CLAUDE.md](CLAUDE.md).
