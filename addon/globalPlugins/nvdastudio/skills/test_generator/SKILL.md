---
name: test_generator
version: 2.0.0
description: Gera testes unitários e de integração para addons NVDA
toolset: quality
trust_level: builtin
handler: globalPlugins.nvdastudio.sub_agents.test_generator
schema:
  inputs:
    - name: code
      type: str
      description: Código Python do addon
    - name: spec
      type: str
      description: Especificação do addon
  outputs:
    - name: tests
      type: str
      description: Código dos testes gerados
dependencies: []
enabled: true
---

# Test Generator Skill

Gera testes unitários e de integração para addons NVDA.
