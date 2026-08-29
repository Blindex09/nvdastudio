---
name: syntax_validator
version: 2.0.0
description: Valida sintaxe Python via AST e verifica compliance com padrões NVDA
toolset: quality
trust_level: builtin
handler: globalPlugins.nvdastudio.sub_agents.syntax_validator
schema:
  inputs:
    - name: code
      type: str
      description: Código Python a ser validado
  outputs:
    - name: valid
      type: bool
      description: True se código é sintaticamente válido
    - name: errors
      type: list
      description: Lista de erros de sintaxe
dependencies: []
enabled: true
---

# Syntax Validator Skill

Valida sintaxe Python via AST com regras específicas para addons NVDA.
