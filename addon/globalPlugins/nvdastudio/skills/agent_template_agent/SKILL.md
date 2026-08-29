---
name: agent_template_agent
version: 2.0.0
description: Gera templates de agentes reutilizáveis para tarefas comuns de desenvolvimento NVDA
toolset: meta
trust_level: builtin
handler: globalPlugins.nvdastudio.sub_agents.agent_template_agent
schema:
  inputs:
    - name: task_type
      type: str
      description: Tipo de tarefa (ex: 'audio', 'clima', 'email')
    - name: context
      type: dict
      description: Contexto adicional
  outputs:
    - name: template
      type: str
      description: Template de agente gerado
dependencies: []
enabled: true
---

# Agent Template Agent Skill

Gera templates de agentes reutilizáveis para tarefas comuns de desenvolvimento NVDA.
