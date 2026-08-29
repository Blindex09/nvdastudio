---
name: ast_validator
version: 2.0.0
description: Valida código Python via AST com regras específicas para addons NVDA
toolset: quality
trust_level: builtin
handler: globalPlugins.nvdastudio.sub_agents.ast_validator
schema:
  inputs:
    - name: code
      type: str
      description: Código Python a ser validado
  outputs:
    - name: valid
      type: bool
      description: True se código é válido
    - name: errors
      type: list
      description: Lista de erros de AST
dependencies: []
enabled: true
---

# AST Validator Skill

Valida código Python via AST com regras específicas para addons NVDA.
