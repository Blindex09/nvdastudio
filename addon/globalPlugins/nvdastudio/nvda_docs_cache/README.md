# nvda_docs_cache/

Copia bundlada de arquivos-fonte reais do NVDA core (repositorio oficial
[nvaccess/nvda](https://github.com/nvaccess/nvda)), usada por
`builder/nvda_context.py` como contexto adicional (nao substitui o
catalogo de regras hardcoded NVDA-001..062, que continua sendo a fonte
principal) para o chat geral (`NVDA_ADDON_CHAT_SYSTEM`) e para todos os
sub-agentes (`get_docs_code_generation()`, `get_docs_accessibility_audit()`,
etc).

## Por que bundlado (e nao um caminho externo)?

Ate 2026-08-16, `_NVDA_DOCS_DIR` apontava para um caminho absoluto do
Windows (`c:\docs_nvda`) que so existia manualmente na maquina de um
desenvolvedor especifico -- sem nenhum script de setup, nenhum usuario
real do NVDAStudio jamais teria essa pasta, e todo o contexto adicional
degradava silenciosamente para quase vazio. Bundlar os arquivos direto no
pacote do addon garante que funcione em qualquer instalacao, sem
configuracao manual.

## Snapshot atual

- `nvda/source/`: clone raso de `nvaccess/nvda` (branch dev, ~2026.3), 2026-08-16.
  37 arquivos, ~840KB.
- `AddonTemplate-master/`: clone raso de `nvaccess/addonTemplate`, 2026-08-16
  (`manifest.ini.tpl`, `manifest-translated.ini.tpl`, `buildVars.py`, `readme.md`).
  IMPORTANTE: `manifest.ini.tpl` inclui um placeholder `updateChannel` que
  NAO existe no configspec real (`AddonManifest` em
  `nvda/source/addonHandler/__init__.py`) -- `get_docs_manifest_builder()`/
  `get_docs_assembler()`/`_build_nvda_addon_chat_system()` ja injetam um
  aviso deterministico sobre isso ANTES do template, nao remover esse aviso
  se atualizar o template.
- `developerGuide.md`: copia do Developer Guide oficial, direto do repo
  `nvaccess/nvda` (`projectDocs/dev/developerGuide/developerGuide.md`),
  2026-08-16. E Markdown, nao HTML -- o nome antigo esperado pelo codigo
  ("nvda_developer_guide_2025.html") foi corrigido pro nome real.
- `DevGuide-master/readme.md`: ainda NAO bundlado (repo de origem incerto,
  nao confirmado contra fonte oficial) -- `get_docs_*()` degrada
  graciosamente pra essa secao vazia ate alguem confirmar a fonte certa.
- Arquivos sao lidos como TEXTO PURO (nunca importados/executados) por
  `_read_docs_file()` -- Regra 9 do projeto (nao executa codigo de
  terceiros).

## Como atualizar

1. Clone/atualize `nvaccess/nvda` em algum diretorio temporario.
2. Copie os arquivos listados em `builder/nvda_context.py` (procure por
   `"nvda", "source",` no arquivo -- cada `os.path.join(docs_dir, "nvda",
   "source", ...)` marca um arquivo esperado) mantendo a mesma estrutura
   de subpastas dentro de `nvda_docs_cache/nvda/source/`.
3. Rode `pytest tests/unit -k nvda_context` para confirmar que nada quebrou.
