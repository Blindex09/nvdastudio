# Auditoria de arquitetura — 2026-08-26

Sessão iniciada com "roda os testes e coloca tudo verde". No caminho,
apareceram 2 achados arquiteturais pedidos explicitamente pelo Felipe
(classificador duplicado, recovery duplicado) e 2 bugs reais descobertos
durante a própria tentativa de rodar a suíte completa (guard de API faltando
no e2e, roteador de modelo quebrando o orçamento de custo). Este documento
cobre os 4. O quinto achado da noite (prompt caching / structured output) já
tem documento próprio: `docs/auditoria-prompt-caching-structured-output-
2026-08-26.md`.

---

## 1. Classificador de complexidade duplicado

**Onde**: `core/orchestrator.py`

**O que havia**: dois sistemas calculando "quão complexo é este pedido",
sem nunca se reconciliarem:

1. `Planner.create_plan()` — a própria LLM de planejamento emite um campo
   `complexity: low|medium|high` dentro do JSON do plano, já usado por
   `ai/model_router.py` para escalação real de modelo.
2. `Orchestrator.classify_query_complexity()` — uma **segunda** chamada de
   LLM, separada, com vocabulário próprio (`simple|medium|complex`), chamada
   em 3 pontos diferentes só para rotular a métrica de sucesso do step em
   `session_memory` (`memory.log_step_metric(..., complexity_level=...)`).

**Por que era um problema real, não só estético**:
- Custo/latência desperdiçados: uma chamada de rede extra por step, só para
  gerar um *label* de log.
- Os dois nunca liam um ao outro — a métrica registrada podia dizer
  `"complex"` enquanto o roteamento de modelo, para o MESMO step, operava
  sob `"high"`/`"low"`, sem nenhuma correlação garantida.
- Viola a regra do projeto de fonte única por decisão (`CLAUDE.md`: "Zero
  duplicação de fluxos... zero coexistência de versões paralelas do mesmo
  fluxo, contrato ou módulo").

**Correção** (`orchestrator.py` 5.55.0): `classify_query_complexity()`
deixou de ser um classificador por IA — virou um tradutor determinístico de
vocabulário, mapeando a complexidade que o Planner já decidiu
(`self._current_complexity()`, low/medium/high) para o vocabulário das
métricas (simple/medium/complex: `low→simple`, `medium→medium`,
`high→complex`). Zero chamadas de rede novas, fonte única de verdade.

**Testes**: `tests/unit/test_skills_melhorias_v8.py::TestQueryComplexityClassifier`
reescrito para testar o mapeamento determinístico (incluindo um teste que
verifica que o código-fonte não chama `create_llm_client`/`client.chat`).

---

## 2. Recovery duplicado: `AgenticLoop` vs escalação interna do pipeline

**Onde**: `core/agentic_loop.py` (FSM externa) vs `core/orchestrator.py`
(escalação interna de um único `_run_pipeline()`)

**O que havia**: duas camadas de recuperação de erro, desenvolvidas em
momentos diferentes, sem nunca se coordenarem sobre uma decisão específica:
qual é o "próximo modelo a tentar" quando um step falha.

- **Escalação interna** (dentro de UMA tentativa de pipeline):
  `_get_resilience_model(step_type, complexity)` usa `ai/model_router.py::
  select_model()` — pontuação real por qualidade/custo/velocidade/
  confiabilidade, específica pro `step_type` que falhou.
- **`SWAP_MODEL` da FSM externa** (entre tentativas completas de pipeline):
  tinha lógica **própria e cega** — só alternava entre tier `"light"` e
  `"heavy"` do provider ativo, sem olhar `step_type` nem complexidade.

**Por que era um problema real**: as duas podiam escolher modelos
DIFERENTES para o mesmo `step_type` na mesma sessão — a escalação interna
já tinha promovido o step pra um modelo específico via pontuação real, e o
`SWAP_MODEL` da FSM podia "trocar" pra outro modelo pior escolhido às
cegas, desfazendo a decisão informada.

**Escopo da correção — deliberadamente cirúrgico**: a arquitetura de duas
camadas (recovery por-step dentro do pipeline vs recovery por-tentativa na
FSM) em si **não foi considerada um bug** — é um design incomum (confirmado
por pesquisa externa: nenhuma referência pública documenta um padrão
equivalente), mas funcional e testado por 2500+ testes calibrados no
comportamento atual. Uma fusão completa das duas camadas foi avaliada e
descartada por risco desproporcional ao ganho. O bug real e concreto era
só essa única inconsistência de qual modelo escolher.

**Correção**: `Orchestrator.get_resilience_model(step_type)` virou
interface pública (mesma lógica de `_get_resilience_model`), e
`agentic_loop.py::StrategyExecutor.swap_model()` passou a delegar nela em
vez de ter lógica própria. As duas camadas agora nunca podem discordar
sobre qual é o próximo modelo pra um `step_type`.

**Testes**: 2 testes de regressão novos em
`tests/unit/test_agentic_quality_fixes.py` (`swap_model` não tinha
cobertura direta antes) — cobrem o caso normal (delega pro orchestrator) e
o caso em que o modelo de resiliência já é o atual (não deveria crashar).

---

## 3. Bug real: guard de API faltando em 13 arquivos e2e (travava a suíte inteira)

**Onde**: `tests/e2e/*.py` — 13 arquivos

**Como foi descoberto**: ao tentar rodar a suíte completa (unit +
integration + e2e) pela primeira vez na sessão, o processo ficava pendurado
indefinidamente sem nunca terminar nem reportar progresso. Diagnosticado
isolando testes com `timeout` do shell — confirmado que um teste específico
travava sozinho, sem limite de tempo.

**Causa raiz**: vários arquivos e2e definem (ou importam) um guard
`skip_unless_ollama = pytest.mark.skipif(not HAS_OLLAMA or not
HAS_OPENCODE_GO, ...)` — mas **nunca aplicavam esse guard em nenhuma
classe ou fixture**. A fixture de módulo `fluxo_report` (ou equivalente)
rodava o pipeline completo com LLM real incondicionalmente. Sem as chaves
de API configuradas no ambiente, a chamada de rede sem timeout ficava
esperando pra sempre — em vez de fazer skip limpo como os arquivos
"irmãos" (`test_e35`–`test_e38`) já faziam corretamente.

**Arquivos corrigidos** (guard aplicado a nível de classe ou módulo,
conforme cada arquivo tinha ou não classes puramente determinísticas que
não deveriam ser puladas):

- `test_criacao_completa.py`, `test_e20_regras_qualidade_codigo.py`,
  `test_e21_regras_configuracoes.py`, `test_fluxo_completo_nvda.py`,
  `test_full_pipeline.py`, `test_e33_proactive_search_integrado.py` — guard
  a nível de módulo (`pytestmark = skip_unless_ollama`), todas as classes
  exigem API real.
- `test_e22_regras_features_avancadas.py`, `test_e23` a `test_e30` (8
  arquivos) — não definiam o guard; importado da fonte única
  (`test_fluxo_completo_nvda`) e aplicado a nível de módulo.
- `test_e31_clarifier_real.py` — guard por classe (`@skip_unless_ollama`),
  preservando `TestClarifierBuildEnrichedQuery` sem guard (documentado no
  próprio código como "determinística — não usa LLM").
- `test_e32_test_generator_pipeline.py` — guard por classe/método; achado
  extra dentro do achado: um método específico dentro de uma classe
  "AST" (supostamente pura) também chamava a API real e precisou de guard
  individual.
- `test_e34_replanejamento_forcado.py` — só faltava guard numa classe
  específica (`TestDoReplanComAPIReal`); as outras 3 classes do arquivo já
  estavam corretas (2 deterministas sem guard, 1 já guardada).

**Resultado**: a pasta `tests/e2e` inteira, que antes travava
indefinidamente, agora fecha em ~15 segundos (209+ testes corretamente
pulados sem chave configurada).

---

## 4. Bug real: roteador deixava o modelo "frontier" vencer em baixa complexidade

**Onde**: `ai/model_router.py`

**Como foi descoberto**: ao investigar 3 falhas em
`test_model_budget_por_complexidade.py` que só apareciam rodando a suíte
completa (nunca isoladas) — sinal de dependência de estado externo, não bug
de lógica pura à primeira vista.

**Causa raiz real** (não a hipótese inicial): `apply_model_budget()`
(`core/planner.py`) espera que a maioria dos steps de `code_generation`
fique num modelo barato, reservando só uma fração pro modelo "frontier"
(o mais caro/capaz, só usado quando `complexity="high"` pede
explicitamente). Isso depende de `select_model()` diferenciar corretamente
o custo entre o modelo frontier e os modelos "baratos" candidatos.

Só que, para o Ollama Cloud (assinatura/cota, sem preço real por token —
ver documento de prompt caching/structured output), `_cost_score()` cai
inteiramente no fallback grosseiro de 3 baldes (`low`/`medium`/`high`).
`qwen3.5:397b` (o modelo frontier) e `deepseek-v4-flash` (um dos modelos
baratos elegíveis) **acabaram os dois classificados como `cost_tier=
"medium"`** — cada classificação individualmente correta e pesquisada
contra `ollama.com` (o "Usage:" oficial da página de cada modelo), mas a
colisão entre as duas nunca foi percebida. Com o custo empatado, o termo
de qualidade (deliberadamente mais alto pro frontier, de propósito)
sempre vencia — inclusive quando `complexity="low"` deveria favorecer
custo.

**Por que só aparecia na suíte completa**: com estado real acumulado em
`session_memory` (arquivo `memory.json`, não isolado por teste), o sinal de
confiabilidade empírica ocasionalmente mascarava o empate de custo — dando
a impressão de que o teste passava isolado "por sorte" dependendo de qual
dado histórico estava no arquivo real do usuário no momento do teste.

**Correção** (`model_router.py` 1.4.0): fora de `complexity="high"`, o
modelo frontier do provider é **excluído da competição** de pontuação —
ele é reservado, não um candidato comum que por acaso pontua alto.
Corrige o problema estruturalmente (não depende de recalibrar dados de
custo, que continuam corretos individualmente) e elimina a dependência do
estado real de `session_memory` — o teste agora passa de forma
determinística, isolado ou na suíte completa.

**Testes**: `test_model_budget_por_complexidade.py` (14 testes, já
existentes) voltou a passar de forma determinística sem nenhum mock de
`session_memory` — confirma que a correção resolve a causa raiz, não
mascara o sintoma.

---

## Convenção de versionamento usada nesta sessão

Cada módulo tocado teve `MODULE_VERSION` incrementado e um comentário de
changelog no próprio arquivo, no padrão já usado no projeto (ex: linha
`# 5.55.0: achado real de auditoria...`). Testes que fixam
`MODULE_VERSION == "X"` foram atualizados junto — são scripts espalhados
por dezenas de arquivos de teste que fixam a versão exata do módulo no
momento em que o teste foi escrito; ver `docs/rule-coverage.md` se for
necessário localizar todos os pontos que fixam versão de um módulo
específico.
