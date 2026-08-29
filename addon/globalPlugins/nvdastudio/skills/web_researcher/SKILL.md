---
name: web_researcher
version: 2.0.0
description: Pesquisa web via DuckDuckGo para coletar informações sobre domínios e APIs
toolset: research
trust_level: builtin
handler: globalPlugins.nvdastudio.sub_agents.web_researcher
schema:
  inputs:
    - name: query
      type: str
      description: Termo de pesquisa
    - name: max_results
      type: int
      description: Número máximo de resultados
  outputs:
    - name: results
      type: list
      description: Lista de resultados da pesquisa
dependencies: []
enabled: true
---

# Web Researcher Skill

Pesquisa web via DuckDuckGo para coletar informações sobre APIs, bibliotecas e boas práticas.
