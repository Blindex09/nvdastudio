---
name: code_generator
version: 2.0.0
description: Gera código Python para addons NVDA com validação AST e compliance NVDA 2019.3+
toolset: core
trust_level: builtin
handler: globalPlugins.nvdastudio.sub_agents.code_generator
schema:
  inputs:
    - name: spec
      type: str
      description: Especificação do addon a ser gerado
    - name: context
      type: dict
      description: Contexto do projeto (manifest, config)
    - name: model_id
      type: str
      description: ID do modelo LLM a ser usado
  outputs:
    - name: code
      type: str
      description: Código Python gerado
    - name: violations
      type: list
      description: Lista de violações de compliance encontradas
dependencies: []
enabled: true
---

# Code Generator Skill

Esta skill gera código Python para addons NVDA, seguindo os padrões de acessibilidade e compliance da API NVDA 2019.3+.

## Capabilities

- Geração de código Python estruturado
- Validação AST automática
- Verificação de compliance NVDA (terminate(), ui.message, etc.)
- Suporte a múltiplos modelos LLM

## Handler

O handler é o sub-agente nativo `globalPlugins.nvdastudio.sub_agents.code_generator`.
