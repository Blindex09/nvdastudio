---
name: manifest_builder
version: 2.0.0
description: Gera manifest.ini estruturado para addons NVDA com validação de campos obrigatórios
toolset: core
trust_level: builtin
handler: globalPlugins.nvdastudio.sub_agents.manifest_builder
schema:
  inputs:
    - name: spec
      type: str
      description: Especificação do addon
    - name: context
      type: dict
      description: Contexto do projeto
  outputs:
    - name: manifest
      type: str
      description: Conteúdo do manifest.ini
dependencies: []
enabled: true
---

# Manifest Builder Skill

Gera o arquivo manifest.ini para addons NVDA, validando todos os campos obrigatórios.
