---
name: agent_runner_agent
version: 2.0.0
description: Executa agentes em sandbox seguro para tarefas auxiliares
toolset: meta
trust_level: builtin
handler: globalPlugins.nvdastudio.sub_agents.agent_runner_agent
schema:
  inputs:
    - name: agent_code
      type: str
      description: Código do agente a ser executado
    - name: timeout
      type: int
      description: Timeout em segundos
  outputs:
    - name: result
      type: str
      description: Resultado da execução
dependencies: []
enabled: true
---

# Agent Runner Agent Skill

Executa agentes em sandbox seguro para tarefas auxiliares.
