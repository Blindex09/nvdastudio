---
name: assembler
version: 2.0.0
description: Monta a saída final do addon (estrutura de pastas, arquivos, pacote .nvda-addon)
toolset: core
trust_level: builtin
handler: globalPlugins.nvdastudio.sub_agents.assembler
schema:
  inputs:
    - name: manifest
      type: str
      description: Conteúdo do manifest.ini
    - name: code
      type: str
      description: Código Python do addon
    - name: docs
      type: str
      description: Documentação em HTML
  outputs:
    - name: addon_path
      type: str
      description: Caminho do pacote .nvda-addon gerado
dependencies:
  - manifest_builder
  - code_generator
enabled: true
---

# Assembler Skill

Monta o pacote final .nvda-addon com estrutura de pastas correta.
