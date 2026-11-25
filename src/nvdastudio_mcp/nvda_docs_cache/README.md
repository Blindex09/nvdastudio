# nvda_docs_cache/

Copia de arquivos-fonte reais do NVDA (repositorio oficial
[nvaccess/nvda](https://github.com/nvaccess/nvda)) e do AddonTemplate, servida
pela ferramenta `nvda_fonte` para consultar a API do NVDA sem depender de internet.
Os arquivos sao lidos como texto puro; nunca sao importados nem executados.

## Conteudo

- `nvda/source/`: arquivos do core do NVDA (scriptHandler, globalPluginHandler,
  appModuleHandler, gui, config, speech, entre outros), branch dev, 2026-08-16.
- `AddonTemplate-master/`: `nvaccess/addonTemplate` (`manifest.ini.tpl`,
  `manifest-translated.ini.tpl`, `buildVars.py`, `readme.md`). O `manifest.ini.tpl`
  traz o campo `updateChannel`, que NAO existe no configspec real
  (`AddonManifest` em `nvda/source/addonHandler/__init__.py`): nao copie esse campo
  para o manifest de um addon.
- `developerGuide.md`: Developer Guide oficial
  (`projectDocs/dev/developerGuide/developerGuide.md`), em Markdown.

## Como atualizar

1. Clone ou atualize `nvaccess/nvda` num diretorio temporario.
2. Copie os mesmos arquivos para `nvda/source/`, mantendo a estrutura de subpastas.
3. Atualize a data acima e rode `pytest`.
