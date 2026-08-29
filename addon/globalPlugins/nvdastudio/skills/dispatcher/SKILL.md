---
name: dispatcher
version: 3.0.0
description: Roteia tarefas para sub-agentes e orquestra execução paralela. Não é uma skill executável — é o motor de dispatch.
toolset: core
trust_level: builtin
handler: globalPlugins.nvdastudio.sub_agents.dispatcher
schema:
  inputs:
    - name: plan
      type: list
      description: Lista de steps do plano de execução
    - name: context
      type: dict
      description: Contexto global do projeto
  outputs:
    - name: results
      type: dict
      description: Resultados por step
dependencies: []
enabled: true
is_dispatcher: true
---

# Dispatcher Skill

O dispatcher é o motor de roteamento do NVDAStudio. Ele não é uma skill executável — é o núcleo que orquestra todos os sub-agentes.

**Nota:** Este handler é o dispatcher nativo. Não deve ser chamado diretamente como uma skill.
