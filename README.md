# NVDAStudio

Servidor MCP que dá ao Claude as ferramentas para criar, corrigir, testar e empacotar addons do leitor de telas NVDA.
O Claude entende o pedido e escreve o código; o NVDAStudio guarda o conhecimento do NVDA, confina os arquivos numa pasta de trabalho,
valida, testa, empacota e abre o pacote no NVDA.

## Usar

Requisitos: Python 3.11+, `pip install -r requirements.txt` e Docker Desktop. O servidor sobe o Docker sozinho quando é chamado (abre o
Docker Desktop, espera o motor ficar pronto e baixa a imagem `python:3.13-slim`, a mesma versão de Python do NVDA 2026). As etapas que executam
código do addon rodam nesse contêiner, sem rede. Se o Docker não existir ou não subir, elas voltam como `not_run` com o motivo.

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

- Conhecimento: `nvda_guide`, `nvda_rules`, `nvda_source`.
- Addons: `addon_list`, `addon_create`, `addon_tree`, `addon_read`, `addon_write`, `addon_delete`.
- Verificação: `addon_validate`, `addon_fix_structure`, `addon_test` (sintaxe, lint, tipos, carregamento, resiliência, testes).
- Pacote: `addon_dependencies`, `addon_package`, `package_inspect`, `package_open_in_nvda`, `store_submission`.
- Roteiros: `create_addon`, `fix_addon`, `review_accessibility`. Recursos: `nvdastudio://guide` e `nvdastudio://guide/{topico}`.

Baseline dos addons novos: NVDA 2026.1.1+, testado em 2026.2.0.

## Desenvolver

```powershell
python -m ruff check .
python -m mypy src
python -m pytest -q
```

Regras de trabalho em [CLAUDE.md](CLAUDE.md).
