---
paths:
  - "addon/globalPlugins/nvdastudio/**"
  - "tests/**"
  - "scripts/**"
---

# Regras específicas do NVDAStudio

> Carrega quando se mexe no addon, nos testes ou nos scripts. Texto da parte específica deste projeto, com as decisões do dono de 20/out/2026.

### Interface que executa tarefas (regra 14)

O diálogo do addon (`addon/globalPlugins/nvdastudio/gui/studio_dialog.py`). Toda funcionalidade de comportamento vale em todas as interfaces que passarem a executar
tarefas, na mesma entrega. A regra dos dois chats separados é só do projeto Agentic.

### Nicho (regra 5)

Nenhum nicho declarado. O NVDAStudio cria, corrige, testa e empacota addons do leitor de telas NVDA por conversa.

### Regras de design: 4, 13 e 14 (decisões do dono, 20/out/2026)

- Durante o trabalho o leitor de telas não fala nada sozinho: só a mensagem final é falada sozinha. O resto se lê com as setas. É o mesmo
  jeito do Agentic.
- Comando e código aparecem em bloco próprio de código, com botão de copiar.
- Quando o dono consolidar o resto (botões, cabeçalhos), registrar aqui. Até lá valem o `README.md` e o `AI_MODULE_SPEC.md` do módulo de IA.

### Entrega com ressalvas

Um addon que carrega de verdade no NVDA é entregue com a lista das ressalvas em frases simples, mesmo com avisos de qualidade; só se bloqueia
quando nada do que existe é seguro para instalar. Nunca se chama de perfeito um resultado com ressalva (decisão do dono, 20/out/2026: é assim que deve ser).

### Instalar no NVDA da pessoa

Segue a chave de aprovação (regra 7): ligada, mostra o que vai instalar e pede; desligada, instala sem perguntar (decisão do dono, 20/out/2026).

### Pipeline de agentes deste projeto (detalhe do item 2 do checklist)

Documento `docs/conceitos-ia-para-desenvolvimento-de-software.md`: engenharia
de sistemas com IA (Harness Engineering, roteamento determinístico,
decomposição, Agent Evals, trajetória, custo, loop detection,
checkpoints, graceful degradation). Aplicável sempre que a mudança tocar
o pipeline de agentes (`core/orchestrator.py` chamando direto
`builder/agentic_driver.py::run_provider_agentic_build`/`run_agentic_build`
-- o pipeline staged com Planner/Critic/sub-agentes separados foi
removido; `builder/agent_evaluation.py::evaluate_agent_run` é o único
avaliador hoje, determinístico sobre fatos do trace, não um LLM-as-judge
de 2 estágios): a
decisão de CONTEÚDO e a escolha de QUAL modelo/provedor serve a tarefa são
da IA (`ai/route_advisor.py`); o harness só impõe fatos objetivos
(elegibilidade, saúde, limites, contingência quando a IA não responde) —
nunca tabelas de "força" de modelo nem marcadores lidos do texto do
usuário; ao decompor uma tarefa grande em partes, garantir
que quem AVALIA o resultado também sabe que existem partes (não só quem
gera).

### Nota concreta: tempo adaptativo e entrega com ressalvas (estado anterior a 20/out/2026)

- **Tempo adaptativo**: `core/orchestrator.py::_AGENTIC_CORRECTION_ROUNDS_BY_COMPLEXITY`
  dimensiona `correction_rounds` pela complexidade que a IA já declarou (nunca um número
  fixo igual pra toda tarefa); `builder/agentic_driver.py::_token_budget()` deriva o
  orçamento de tokens do mesmo `max_turns`. Achado ao vivo (2026-09-29, E2E real via Ollama
  Cloud): `run_provider_agentic_build` tinha um SEGUNDO teto independente
  (`corrections >= correction_rounds: break`) que parava a build bem antes do orçamento
  real de turnos/tokens se esgotar — dois tetos competindo, o mais curto sempre vencendo.
  Corrigido: só o teto real (turnos/tokens) decide quando parar; `correction_rounds`
  continua dimensionando esse teto, mas não interrompe mais o laço por conta própria.
- **Guarded loops + autosubmit**: `agentic_driver.py::AgenticBuildResult.deliverable` e
  `core/orch_types.py::OrchestrationResult.deliverable` distinguem "gate 100% limpo"
  (`success`) de "carrega de verdade no NVDA, só falta ajuste de qualidade" (`deliverable`).
  `_is_blocking_gate_failure()` classifica o relatório do próprio gate por marcadores fixos
  que o harness mesmo gera (manifest/entrada/sintaxe ausente, erro real de execução, teste
  vermelho = bloqueante; NVDA-019/024/042, RUFF, MYPY, acessibilidade = qualidade). A GUI
  (`gui/studio_dialog.py::_display_result`) entrega o addon com a lista de ressalvas quando
  `deliverable=True`, mesmo com `success=False` — só bloqueia atrás do diálogo de erro
  quando nada do que existe é seguro para instalar.

Pelas decisões de 20/out/2026, o `correction_rounds` por complexidade e o orçamento de tokens derivado de `max_turns` (`_token_budget()`) são
dívida a remover, e a entrega com ressalvas descrita acima continua valendo.
