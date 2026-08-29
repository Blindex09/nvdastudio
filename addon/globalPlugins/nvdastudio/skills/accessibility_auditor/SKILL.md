---
name: accessibility_auditor
version: 2.0.0
description: Audita acessibilidade WCAG 2.1 AA e compliance NVDA para addons
toolset: quality
trust_level: builtin
handler: globalPlugins.nvdastudio.sub_agents.accessibility_auditor
schema:
  inputs:
    - name: code
      type: str
      description: Código Python do addon a ser auditado
    - name: manifest
      type: str
      description: Conteúdo do manifest.ini
  outputs:
    - name: audit
      type: str
      description: Relatório de auditoria de acessibilidade
    - name: violations
      type: list
      description: Lista de violações encontradas
dependencies: []
enabled: true
---

# Accessibility Auditor Skill

Audita código de addons NVDA para compliance WCAG 2.1 AA e padrões de acessibilidade NVDA.
