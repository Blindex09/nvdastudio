---
name: doc_generator
version: 2.0.0
description: Gera documentação de ajuda (readme.html) para addons NVDA
toolset: core
trust_level: builtin
handler: globalPlugins.nvdastudio.sub_agents.doc_generator
schema:
  inputs:
    - name: spec
      type: str
      description: Especificação do addon
    - name: manifest
      type: str
      description: Conteúdo do manifest.ini
  outputs:
    - name: docs
      type: str
      description: Documentação HTML gerada
dependencies: []
enabled: true
---

# Doc Generator Skill

Gera documentação de ajuda (readme.html) para addons NVDA.
