# Melhorias futuras vindas de C:\agentic — 2026-09-02

Segunda passada de comparação com `C:\agentic` (plataforma de agente de
propósito geral, mesmo autor). A primeira está em
`auditoria-portado-de-agentic-2026-08-26.md` e portou 3 melhorias de
roteamento/confiabilidade; **não repetir aquele trabalho** — ele já está no
código.

Esta passada foi pedida com duas perguntas: o que mais o NVDAStudio pode
aproveitar, e se o comportamento de "3 tentativas" está correto.

Nada aqui é obrigação. É registro do que foi avaliado, com o custo e o risco
de cada item, para decidir com informação depois — e para o próximo agente
não redescobrir do zero.

---

## Resposta à pergunta das 3 tentativas: está correto

O mecanismo está certo, e nesta parte **o NVDAStudio está à frente do
agentic**:

| camada | agentic | NVDAStudio |
|---|---|---|
| retry de transporte (429, 503, timeout) | `call_with_retry`, backoff + jitter | idem, **mais** HTTP 529 e leitura de `"retry in 24.8s"` em texto livre |
| detecção de loop por assinatura de **exceção** | sim | sim |
| detecção de loop por assinatura **semântica** (issues do Critic) | **não tem** | `orchestrator` 5.42.0 — escala de modelo em vez de insistir idêntico |

Verificado ao vivo na rodada AssistenteEscrita (2026-09-02): as 3 tentativas
do `web_research` tiveram issues genuinamente diferentes entre si, e por isso
a detecção de loop **corretamente não disparou**. Não é um caso de "3 por 3
sem pensar".

O ajuste que faltava não era no número de tentativas e sim em *quando nem
vale tentar* — resolvido abaixo.

---

## Já corrigido nesta passada (não é trabalho futuro)

**Falha de infraestrutura era pontuada como se fosse conteúdo**
(`orchestrator` 5.79.0, `test_erro_de_infra_nao_vai_ao_critic.py`).

`_base.py::_run_sub_agent` devolve `"[ERRO] Sub-agente nao conseguiu gerar
resposta: ..."` como se fosse a resposta. O `_IS_SUBAGENT_ERROR_RE` já
existia para reconhecer isso, mas só era consultado no ramo de fallback de
modelo; quando o fallback também falhava, o fluxo seguia sem guarda até o
Critic.

Medido: `web_research` escalou para o OpenCode Go sem saldo, e o Critic
reprovou com score 0 escrevendo *"o output é apenas uma mensagem de erro de
API (401 Unauthorized)"*. A busca tinha funcionado (`paralelo: 1/3 fontes,
exa`); morreu a síntese. O veredito culpava a pesquisa por uma falha de
conta, e as `fix_instructions` do retry mandavam consertar um problema
inexistente.

Vale para os 11 sub-agentes, não só a pesquisa.

---

## Item 1 — Orquestração adaptativa

**O que o agentic faz** (`features/orchestration/README.md`): escolhe
internamente a forma menos complexa e confiável para cada tarefa — resposta
direta, etapas dependentes, partes independentes em paralelo, pesquisa e
análise, ou produção com revisão. O usuário não escolhe arquitetura.

**Por que interessa aqui**: o NVDAStudio monta um plano de steps sempre. As
oito rodadas do golden set complexo viraram planos de 25 a 27 steps; com 47%
de aprovação por step de código, a chance de todos passarem é de 0,25%. O
`test_e39` foi criado justamente para contornar isso encurtando o pedido — ou
seja, o problema do comprimento do plano está reconhecido e contornado, não
resolvido.

**Risco real**: mexe no coração do Planner. O pipeline acabou de estabilizar
depois de seis defeitos corrigidos em 2026-09-02, e a primeira entrega
complexa é recentíssima. Uma mudança arquitetural agora tem chance concreta
de regredir o que acabou de passar a funcionar.

**Pré-requisito antes de codar**: o `CLAUDE.md` exige roteamento
determinístico (Regra 7), e a auditoria de 2026-08-26 já **recusou
deliberadamente** o classificador de complexidade do agentic por ele ser por
LLM. Qualquer orquestração adaptativa aqui tem que decidir a FORMA de modo
determinístico. O `COMPLEXITY_MAP` e o `iteration_budget.apply_plan()` já são
matéria-prima para isso.

**Como medir se valeu**: número de steps por plano e taxa de entrega do
golden set complexo, comparados antes/depois. Sem essa medição não dá para
saber se ajudou.

---

## Item 2 — Avaliações persistentes com comparação entre versões

**O que o agentic faz** (`features/evaluations/`, 720 linhas): guarda casos
de teste como "tarefa de exemplo + descrição de um bom resultado". O usuário
escolhe explicitamente uma execução para avaliar, evitando custo silencioso.
O resultado fica associado ao caso, para detectar regressão depois de mudar
o agente.

**Situação aqui**: o NVDAStudio já tem o golden set e **412 relatórios JSON
versionados** em `tests/e2e/relatorios/`. O que falta não é armazenamento — é
a *comparação* entre eles. Hoje, saber se uma mudança melhorou ou piorou a
entrega exige ler relatórios na mão, que foi exatamente o que consumiu boa
parte de 2026-09-02.

**Escopo menor e mais seguro que o item 1**: é ferramenta de análise sobre
dados que já existem, sem tocar no pipeline.

**Antes de codar — obrigatório**: auditar `scripts/` e os testes de E2E para
ver se alguma comparação já existe. Esta regra foi violada duas vezes em
2026-09-02 (um `select_model_and_provider()` duplicado e uma regra do
OpenCode Go que já estava documentada), com custo real de retrabalho.

---

## O que foi avaliado e deliberadamente NÃO trazido

- **Conectores universais, MCP, guardrails cross-provider, migração entre
  provedores.** São reais e bem construídos no agentic, e resolvem problemas
  que o NVDAStudio não tem: ele não é plataforma multi-agente de propósito
  geral, é um gerador de addons NVDA.
- **Classificador de complexidade por LLM.** Já recusado em 2026-08-26 por
  colidir com a Regra 7. Registrado de novo aqui para não ser reconsiderado
  por engano.

---

## Observação sobre os dois projetos

`C:\agentic` carrega os **mesmos três documentos de metodologia** que o
`CLAUDE.md` deste repositório manda seguir (`metodologia-verificacao-
arquitetura.md`, `conceitos-ia-para-desenvolvimento-de-software.md`,
`conceitos-ia-seguranca-confiabilidade.md`). Comparar os dois é comparar duas
aplicações da mesma metodologia em domínios diferentes — por isso a
transferência costuma valer, e por isso a divergência, quando existe, quase
sempre é escolha consciente e não lacuna.
