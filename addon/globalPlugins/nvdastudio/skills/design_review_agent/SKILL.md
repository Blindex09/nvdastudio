---
name: design_review_agent
version: 2.0.0
description: Revisão de design arquitetural em três estágios (challenger, guardian, advocate) para addons NVDA
toolset: quality
trust_level: builtin
handler: globalPlugins.nvdastudio.sub_agents.design_review_agent
schema:
  inputs:
    - name: spec
      type: str
      description: Especificação completa do addon
    - name: context
      type: dict
      description: Contexto do projeto
    - name: model_id
      type: str
      description: ID do modelo LLM
  outputs:
    - name: review
      type: str
      description: Revisão de design completa com recomendações
    - name: score
      type: int
      description: Score de qualidade (0-100)
dependencies: []
enabled: true
---

# Design Review Agent Skill

Executa revisão de design em três estágios independentes:
1. **Challenger**: Questiona premissas e identifica riscos
2. **Guardian**: Verifica segurança, acessibilidade e compliance
3. **Advocate**: Defende o design e sugere melhorias
