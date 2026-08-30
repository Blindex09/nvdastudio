# NVDAStudio

Addon para o leitor de telas NVDA que cria, revisa, documenta, empacota e itera outros addons usando IA agentica conversacional multi-provider, com interface acessivel em `wxPython` dentro do proprio NVDA.

**Arquitetura de IA revisada de ponta a ponta em 2026-07-19** — Os cinco provedores do painel usam clientes HTTP nativos. No modo `Alto`, no maximo 20% das etapas usam o modelo topo; as demais usam o modelo leve. Memoria resumida, recuperacao semantica, cache de prompt e compressao de contexto permanecem ativos. Um modelo concreto escolhido manualmente continua sendo respeitado em todas as chamadas. O gateway executa ferramentas locais sem bridge externa. Raciocinio interno, Markdown decorativo, emojis e relatorios tecnicos nao entram no historico conversacional.

**Auditoria de gaps 2026-08-03** — `claude-opus-5` (24/07/2026) adicionado ao registry como novo modelo near-frontier default da Anthropic; `claude-opus-4-8` marcado DEPRECATED. `native_web_search()` (OpenAI/xAI/Anthropic/Gemini) passa a preservar citacoes/provenance (URLs/titulos das fontes) em vez de descartar tudo exceto o texto puro; bug real corrigido no parsing de resposta de busca do Gemini (lia um campo que a Interactions API nao garante em tool calls). Removidos 4 modulos de `tools/` orfaos com respostas simuladas/hardcoded (nunca importados por nada no projeto) — ver nota em `tools/` no mapa de modulos. Tabelas de versao deste README resincronizadas com as constantes `MODULE_VERSION` reais do codigo (estavam ate 6 versoes atrasadas em alguns modulos). `ruff` confirmado limpo em todo o codigo proprio do projeto (0 erros fora de `lib/`, que e vendorizado e agora explicitamente excluido do lint).

**Camada de engenharia 2026-08-29** — Auditoria confirmou que o projeto treinava a IA profundamente no DOMINIO NVDA (base de ~600K chars com codigo-fonte real do NVDA, ~50 regras catalogadas, fiscalizacao deterministica por AST/import/pytest) mas nao em ENGENHARIA como disciplina — engenharia e o que sobra quando o catalogo de regras acaba. Quatro lacunas fechadas: (1) o addon GERADO agora passa por `ruff` e `mypy` (`code_sandbox.lint_check()`/`typecheck()`), fechando a assimetria em que o CI exigia lint e tipos do proprio NVDAStudio mas nao do que ele entrega ao usuario — config curada (so `F`/`E9`/`B`, defeito real, nunca estilo), gettext declarado como builtin para nao punir addon traduzido, e FAIL-OPEN quando a ferramenta nao esta instalada; (2) novo `STEP_ENGINEERING_REVIEW` (`sub_agents/engineering_reviewer.py`) julga o que nenhum ID de regra descreve — fronteira de modulo errada, erro engolido, recurso sem dono, complexidade sem motivo, testabilidade; (3) os 3 documentos de metodologia de `docs/`, ate aqui obrigatorios so para agentes externos e nunca presentes em nenhum prompt, foram destilados em `utils/engineering_principles.py` e injetados no planner, no critic, no gerador de codigo e no revisor — cada principio ancorado na consequencia real para o usuario cego; (4) o addon gerado ganha ciclo de vida (`utils/addon_versioning.py`): versionamento semantico orientado por prompt e monotonicidade de versao garantida deterministicamente.

**v2.0.0 (2026-05-15): Pipeline Conversacional com Wiring Completo** — A IA agora conversa com voce, pesquisa o dominio do addon, monta um plano, mostra pra voce aprovar, e implementa explicando cada passo. Fluxo: CONVERSA → PESQUISA → PLANO → APROVACAO → EXECUCAO → REVISAO → PRONTO. O orchestrator agora wireia automaticamente `evaluation_framework`, `code_sandbox`, `agent_memory` e outros 4 módulos na pipeline de execução.

Referencias:
- https://community-access.org/
- https://github.com/nvaccess/nvda
- https://github.com/nvdaaddons

---

## Regras Obrigatorias do Sistema

### 1. Fonte de Verdade

- Este `README.md` define as regras globais do projeto.
- O contrato central e [`addon/globalPlugins/nvdastudio/AI_MODULE_SPEC.md`](C:/nvdastudio/addon/globalPlugins/nvdastudio/AI_MODULE_SPEC.md).
- A cobertura de regras NVDA/WX/ARCH/UX e mantida em [`rule_registry.py`](C:/nvdastudio/addon/globalPlugins/nvdastudio/rule_registry.py) e documentada em [`docs/rule-coverage.md`](C:/nvdastudio/docs/rule-coverage.md).
- Em caso de divergencia entre documentacao antiga e codigo atual, o contrato central e o codigo prevalecem.
- Toda mudanca estrutural, contratual ou comportamental deve atualizar o codigo, o `README.md` e o `AI_MODULE_SPEC.md` na mesma entrega.

### 2. Baseline de Compatibilidade

- O baseline oficial do NVDAStudio e `NVDA 2026.1.1+`.
- Addons novos gerados pelo projeto devem usar:
  - `minimumNVDAVersion = 2026.1.1`
  - `lastTestedNVDAVersion = 2026.1.1`
- Compatibilidade abaixo de `2026.1.1` nao faz parte do escopo ativo do projeto.
- Regras de forward-compatibility para `NVDA 2026.1+` permanecem obrigatorias quando envolverem binarios, ABI, `winBindings` ou outras mudancas de arquitetura.

### 3. Regra Rigida Anti-Legado e Anti-Deprecacao

- Codigo legado, caminhos mortos, arquivos sem uso real, shims de compatibilidade obsoletos e documentacao depreciada nao devem permanecer no projeto.
- Ao encontrar legado ou comportamento depreciado, a regra padrao e remover ou substituir imediatamente, nao acumular.
- Nao manter compatibilidade ativa com versoes anteriores ao baseline oficial so por precaucao.
- Nao manter dois fluxos equivalentes quando um ja substituiu o outro.
- Nao documentar ferramentas ou etapas que nao participam mais do build, runtime, testes ou distribuicao.

### 4. Arquitetura e Contratos

- O contrato central atual cobre os modulos do pacote `addon/globalPlugins/nvdastudio/`.
- O projeto usa um contrato central versionado, nao uma colecao dispersa de specs parciais por pasta.
- Cada modulo deve ter responsabilidade clara, entradas, saidas, dependencias e invariantes compreensiveis.

### 5. Codigo e Qualidade

- Zero duplicacao intencional de fluxos, endpoints, helpers ou regras de negocio.
- Toda alteracao deve deixar o sistema mais simples, previsivel e auditavel.
- Refatoracao que remove ruido, legado ou duplicacao e considerada manutencao obrigatoria, nao opcional.

### 6. Imports

- Todos os imports ficam no topo do arquivo.
- Excecoes permitidas:
  1. Import condicional por plataforma.
  2. Dependencia opcional com `try/except ImportError`.
  3. Import local para quebrar ciclo circular, com comentario.

### 7. LLM e Comportamento Semantico

- Proibido usar keywords hardcoded, regex ou blacklists para “simular” entendimento semantico da LLM.
- A camada semantica decide interpretacao, classificacao, geracao e contexto.
- A camada deterministica decide validacoes tecnicas, seguranca, autenticacao, integridade, retries, baseline e empacotamento.
- Agentes sao selecionados por escopo/evidencia do plano: o `planner.py` gera `step_type` especializados e o `dispatcher.py` executa apenas handlers declarados. `step_type` desconhecido falha explicitamente, sem fallback para `code_generator`.
- Conhecimento de ENGENHARIA (estrutura, modos de falha, complexidade, testabilidade) tem fonte unica em `utils/engineering_principles.py`, destilada dos 3 documentos de `docs/` e consumida por `planner.py`, `critic.py`, `code_generator.py` e `engineering_reviewer.py`. Nunca duplicar esses textos num prompt local: o catalogo de regras diz o que NAO fazer, os principios dizem como decidir quando nenhuma regra se aplica — e as duas coisas precisam evoluir juntas.
- Analise estatica do codigo GERADO (`ruff` bloqueante com config curada, `mypy` consultivo) e integridade de versao do addon entregue sao decisoes DETERMINISTICAS, nunca delegadas ao modelo.

### 8. Integracoes Externas

- APIs externas sao dinamicas e exigem validacao de documentacao atual antes de qualquer mudanca relevante.
- O modelo unico foi substituido por roteamento multi-modelo e multi-provider.
- No modo `Alto`, o sistema resolve os modelos leve e topo pelo registry local auditado contra a documentacao oficial de cada provedor.
- O planejamento aplica um orcamento mensuravel: no maximo 20% das etapas usam o modelo topo. Geracao de codigo pode usar o topo; conversa, planejamento, pesquisa, esclarecimento, critica, auditoria, documentacao e testes usam o leve. Falhas podem provocar escalada controlada.
- Um modelo concreto selecionado manualmente sobrescreve o roteamento automatico e e usado em todas as chamadas.
- O contexto usa memoria resumida, recuperacao semantica pelo modelo leve, cache exato temporario de prompts de sub-agentes e compressao de trajetoria da conversa.

### 9. Observabilidade

- Modulos de IA devem registrar input, output e decisoes relevantes.
- Prompts e parametros de chamada devem ser versionados.
- O comportamento precisa ser rastreavel e reproduzivel por logs e testes.
- Logs persistentes devem ser gravados em `logs/` na raiz do projeto e espelhados
  em `%APPDATA%\nvda\nvdastudio_logs` quando o addon roda dentro do NVDA.
- Toda inicializacao local/carregamento do addon deve manter logs persistentes ativos por padrao.
- Logs e caches so devem ser apagados quando isso for solicitado explicitamente.
- Quando for solicitada limpeza de logs/cache, usar `scripts/clean_runtime_artifacts.ps1`.

### 10. Versionamento e Migracoes

- Todo modulo relevante deve expor versao explicita.
- Mudancas de comportamento exigem incremento de versao e atualizacao contratual.
- Migracoes de baseline e remocoes de legado devem ser explicitas na documentacao.

### 11. Seguranca de IA

- Saida da LLM nunca e executada automaticamente.
- Toda acao sensivel precisa de verificacao deterministica antes de salvar, empacotar ou instalar.
- Prompt injection, jailbreak e tool abuse devem ser tratados como risco nativo do sistema.

### 12. Testes

- Toda mudanca em codigo, contrato ou baseline exige ajuste de testes na mesma entrega.
- A suite atual coletada em `2026-07-20` contem:
  - `1786` testes coletados em `tests/unit` + `tests/integration` (mais suites `e2e` que exigem Ollama real)
  - `pytest.ini` limita a coleta ao projeto e ignora bibliotecas empacotadas

### 13. Logging e Encoding

- Sem emojis em logs ou saida de terminal.
- Mensagens devem permanecer compativeis com `cp1252`.

### 14. Acessibilidade

- Acessibilidade e parte do contrato do sistema.
- Dialogs `wx` devem usar labels explicitos, ordem logica de tabulacao, `wx.BoxSizer`, foco previsivel e anuncios falados via NVDA.

---

## Mapa Atual de Modulos

Versoes auditadas diretamente do codigo em 2026-07-14. Modulos marcados com `—` nao declaram `MODULE_VERSION` (pendencia da Regra 10).

### Raiz do pacote

| Modulo | Versao | Responsabilidade |
|--------|--------|------------------|
| `__init__.py` | 2.3.0 | GlobalPlugin, atalhos e registro do painel de configuracoes |

### core/

| Modulo | Versao | Responsabilidade |
|--------|--------|------------------|
| `orchestrator.py` | 5.61.0 | Pipeline conversacional com artefatos isolados por etapa, retries recuperaveis, imports locais reconhecidos, respostas do plano geradas pela IA e raciocinio interno fora da interface; erro de sintaxe propagado pro proximo retry; escalacao 100% dinamica; cross-model escalation no replan via `_diversify_failed_models()`; `_build_retry_query()` orfao removido; `_FALLBACK_MODEL`/concorrencia atualizados para `kimi-k2.7-code`; bug real corrigido -- WIRING de `evaluation_framework` usava `PipelineEvaluator()` novo a cada chamada em vez da instancia global `evaluation`, historico de regressao nunca acumulava; `_run_pipeline()` ganha `resume_plan`/`resume_completed` pra retomada real (base do fix de `surgical_replan`); analise estatica do addon gerado ligada ao pipeline -- `ruff` BLOQUEIA e gera retry (config curada: so defeito real), `mypy` e advisory e entra no contexto do proximo passo; roda depois de execucao/resiliencia de proposito (quando o addon nem importa, o erro de import e o sinal util); 5.57.0 fecha a lacuna mais cara achada ate hoje: nos 379 relatorios de `tests/e2e/relatorios/`, **9 addons foram entregues com success=True e nao seriam carregados pelo NVDA** -- Python gerado, manifest valido, empacotado, e sem `globalPlugins/<Addon>/__init__.py`. O NVDA carrega addon por CONVENCAO DE CAMINHO: sem o `__init__.py` do pacote, todo o resto e ignorado e o addon instala sem erro e nao faz nada -- o usuario cego nao tem como descobrir por que. `_validate_minimum_addon_artifacts()` (o portao de "recusa conclusao falsa") passa a exigir ponto de entrada carregavel e, quando o plano declara `expected_gestures`, que os atalhos pedidos existam de fato no AST do codigo aprovado; 5.58.0/5.59.0 fecham o ciclo de "o addon funciona?": injeta o layout declarado nos prompts de geracao, exige coerencia dos imports ENTRE os arquivos do addon (`_broken_internal_imports`) e -- causa raiz da nao-convergencia -- alimenta o orcamento EM VOO. O circuit breaker existia e era consultado a cada tentativa desde a 5.28.0, mas o medidor so era alimentado nos pontos TERMINAIS do pipeline: durante a execucao `tokens_used` ficava em zero e nada parava (ha relatorio com 41 retries e 4,6 MILHOES de tokens contra um teto de 500 mil). `_track_model_tokens()` -- ja chamado em TODO ponto de consumo -- passa a registrar no orcamento, e o registro terminal para de contar em dobro; 5.60.0/5.61.0 fecham o que o E2E real de 2026-08-29 revelou em tres rodadas. **Teto por complexidade**: o freio ligado na 5.59.0 expos que o teto era UNICO e fixo em 500 mil, calibrado sem querer para addon simples -- nenhum addon complexo jamais teve sucesso abaixo disso (mediana real: 821 mil), entao o freio virou 'para cedo e nunca funciona'. **Degradacao graciosa**: ao estourar, o laco parava de percorrer os steps restantes so para receber nota zero (a media do relatorio caia para 7.1 quando um step tinha sido aprovado com 98), e a mensagem final passa a dizer a causa REAL em vez de 'nenhum arquivo Python foi gerado'. **Problemas acumulados entre tentativas**: `last_issues = crit.issues` SUBSTITUIA a lista a cada avaliacao, entao a tentativa 2 nao via o que a 1 apontou -- o modelo corrigia o ultimo defeito e reintroduzia o anterior. A lista acumulada vive SEPARADA de `last_issues` de proposito: a deteccao de loop semantico compara a assinatura da avaliacao ATUAL, e acumular teria feito a assinatura crescer sempre e matado a deteccao em silencio |
| `agentic_loop.py` | 2.4.0 | Motor FSM autonomo com 14 estados/estrategias (mental_simulation, ensemble_verify, self_play_adversarial, tool_creation, ...); `surgical_replan()` agora e cirurgico de verdade -- reusa o plano/steps aprovados da tentativa anterior em vez de rerodar tudo do zero |
| `planner.py` | 2.33.0 | addon_name canonico + decomposicao semantica em step_type + roteamento por tipo/provedor via model_registry + apresentacao e confirmacoes completas do plano geradas pela IA + replan_with_feedback() (enum no step_type); requires_web_research orientado a pesquisar mais em caso de duvida sobre API/IA externa pouco difundida OU sobre funcionalidade avancada (streaming, tools, visao, structured output, thinking, cache) de um provedor ja conhecido; model_map do replan agora funciona de verdade (cross-model escalation); `_STEP_FALLBACK_MODEL`/`COMPLEXITY_MAP` atualizados para `kimi-k2.7-code`; `_ALLOWED_MODELS` (dead code, nunca consultado, desalinhado do registry real) removido; novo `STEP_ENGINEERING_REVIEW` injetado deterministicamente apos todos os `code_generation` e antes do `assembly` (depende de TODOS eles: defeito de engenharia costuma so aparecer no conjunto); criterio de decomposicao e ordem de verificacao por custo agora explicitos no `_PLAN_SYSTEM_PROMPT`; novo campo `expected_gestures` no schema do plano -- a IA DECLARA os atalhos que o addon deve expor (decisao semantica, Regra 7: extrair da frase do usuario com regex seria simular entendimento semantico) e o orchestrator VERIFICA deterministicamente que existem no codigo gerado; 2.32.0 adiciona `expected_files`: a IA declara o LAYOUT de arquivos ANTES da geracao, e `_normalize_expected_files()` GARANTE deterministicamente um ponto de entrada carregavel (invariante tecnica, nao decisao semantica -- sem ele o NVDA nao carrega nada). O reparo usa o pacote que a IA ja declarou; criar um pacote novo a partir de addon_name deixaria DOIS pacotes, com o ponto de entrada vazio ao lado dos arquivos reais; 2.33.0 troca a decomposicao por FEATURE pela decomposicao por ARQUIVO. Medido no E2E real: os `code_generation` que falham consomem sempre ~419 mil tokens em 3 tentativas e sao reprovados por entrega parcial; o unico aprovado gastou 127 mil nas MESMAS 3 tentativas -- a diferenca era quantos arquivos o step tentava produzir de uma vez. Novo campo `ExecutionStep.target_files` (normalizado no `__post_init__`, para valer tambem nos steps criados pelos injetores), guarda `oversized_...` passa a contar ARQUIVOS (teto 2; o comprimento da descricao vira rede, era proxy fraco) e o prompt de replanejamento -- que pedia literalmente "um step por feature/subpacote", a causa do problema -- passa a pedir divisao por arquivo, justificada com o dado medido |
| `checkpoint_manager.py` | 2.0.0 | Snapshots + checkpoint interativo (CONTINUAR/REFAZER/PAUSAR) com rollback |
| `orch_types.py` | — | Tipos compartilhados: StepResult, OrchestrationResult, PipelinePhase, DomainContext, PlanApproval, CheckpointResult |

### ai/

| Modulo | Versao | Responsabilidade |
|--------|--------|------------------|
| `clarifier.py` | 1.5.0 | Diagnostico arquitetural LLM (external/driver/deep_integration/ambiguous) antes do pipeline |
| `critic.py` | 3.21.0 | Avaliacao em dois estagios com escopo por artefato e regras alinhadas ao NVDA 2026.1; o QualityCritic passa a julgar tambem ENGENHARIA -- os defeitos que nenhum ID de regra descreve (erro engolido, operacao externa sem timeout, recurso sem fim de vida, complexidade sem motivo, logica impossivel de testar) |
| `llm_client.py` | — | Tipos base LLMClientError, LLMResponse |
| `llm_factory.py` | 5.0.0 | Factory unica para os clientes HTTP nativos dos 5 provedores |
| `provider_client.py` | 2.10.0 | Cliente nativo OpenAI/xAI (Responses API, /v1/responses) e Gemini (Interactions API, /v1/interactions); Anthropic com retry em 529 (overloaded); `native_web_search()` preserva citacoes/provenance (url_citation da OpenAI/xAI/Gemini, web_search_result_location da Anthropic) em vez de descartar tudo exceto o texto; bug real corrigido: `_native_web_search_gemini()` so lia `output_text` (campo nao garantido pela Interactions API em tool calls) -- agora le `steps`/`model_output` igual ao caminho principal de chat |
| `ollama_client.py` | 2.27.0 | Cliente Ollama Cloud com thinking separado do conteudo visivel; kimi-k2.7-code adicionado as capabilities e como _DEFAULT_MODEL; `web_search()`; `web_fetch()` novo -- busca conteudo completo de uma URL via `https://ollama.com/api/web_fetch`; `_adapt_structured_output()` agora aterra o schema JSON como texto no prompt tambem no caminho nativo (Kimi), nao so no caminho GLM -- pratica recomendada pela doc oficial mesmo com `format` nativo ligado; teto de tokens de saida escala com step_type (`_MAX_TOKENS_EXTENDED`, code_generation/agent_runner) -- causa raiz real de codigo cortado no meio de metodos, achado 2026-08-04; `gpt-oss:20b` ganha entrada propria em `_MODEL_CAPABILITIES` e recebe nivel string ("low"/"medium"/"high") no campo `think` em vez de booleano -- doc oficial confirma que GPT-OSS ignora booleano, so aceita nivel (achado 2026-08-04); 2.27.0 acrescenta `engineering_review` a `_EXTENDED_TIMEOUT_STEP_TYPES` -- o step recebe o codigo gerado inteiro como entrada, mesmo perfil de contexto longo de `design_review` |
| `model_registry.py` | 1.12.0 | Registry auditado de modelos e resolucao Alto heavy/light; modelos superados por geracao mais nova marcados DEPRECATED (claude-opus-4-7, claude-opus-4-8, claude-sonnet-4-6, gpt-5.5/5.4/5.4-mini, gemini-2.5-pro/flash, gemini-3-flash-preview); claude-fable-5 REMOVIDO por completo do registry (nao so excluido dos defaults); claude-opus-5 e o tier heavy da Anthropic; gemini-3.6-flash e o novo tier light do Gemini; kimi-k2.7-code e o tier heavy default do Ollama (Kimi K3 esta no catalogo mas retorna HTTP 402, extra usage gated -- nao aplicavel, confirmado via teste real da API); glm-5.2/minimax-m3/gpt-oss:20b adicionados ao catalogo Ollama e a `_FALLBACK_CHAINS["ollama"]`, ainda nao promovidos a default; grok-build-0.1 (coding agentico) e o tier heavy do xAI; grok-4.20-0309-reasoning/non-reasoning/multi-agent-0309 adicionados por completude de catalogo (confirmados na tabela de precos oficial, mas sem descricao de proposito -- nao promovidos a nenhum tier); "Grok 4.6" investigado e descartado -- rastreado a sites agregadores nao-oficiais, nao existe em docs.x.ai; `get_active_models_for_ui_provider()` novo -- fonte unica de modelos pro dropdown da UI (settings_panel.py 6.5.0 nao mantem mais lista propria); `ModelInfo.context_window` novo, populado por pesquisa dedicada -- fonte unica de janela de contexto por modelo (era so context_compressor.py, tabela parcial e com deepseek-v4-flash errado) |
| `anthropic_memory_tool.py` | 1.0.0 | Handler client-side do memory tool nativo da Anthropic (memory_20250818) -- 6 comandos (view/create/str_replace/insert/delete/rename) contra `%APPDATA%/NVDAStudio/claude_memory/`, protecao contra path traversal |
| `prompt_optimizer.py` | 1.0.0 | A/B testing de variantes de prompt; record_result() e select_best_variant() |

### builder/

| Modulo | Versao | Responsabilidade |
|--------|--------|------------------|
| `addon_builder.py` | 4.14.0 | Extracao, salvamento e empacotamento; dependencias miram CPython 3.13 win_amd64 e a ABI e validada antes da instalacao; 4.14.0 corrige um FALSO POSITIVO real medido nos relatorios: NVDA-015 era avaliada arquivo a arquivo, entao um addon com `configSpec.py` proprio e consumo espalhado levava um aviso POR ARQUIVO mandando criar o arquivo que ja existia -- 11 dos 14 disparos (79%) eram falsos, e TODOS em addon multi-arquivo (zero em arquivo unico), punindo exatamente a classe que o projeto tem mais dificuldade de fazer convergir. A spec e do ADDON, nao do arquivo: agora basta existir em um lugar |
| `addon_loader.py` | 1.2.0 | Carrega addon existente para iteracao; exclui lib/, __pycache__ e *.pyc |
| `nvda_context.py` | 3.28.0 | Regras NVDA-001..061 e prompts de contexto NVDA para geracao; chat exige conversa (nao auditoria) tambem no modo analise/revisao; cobre TreeInterceptor, padrao _get_/_set_, AccumulatingDecider e ordem de propagacao de evento; secao de integracao com os 5 provedores de IA/LLM (endpoint/auth/request do chat basico) para addons gerados, orientando pesquisa web mesmo para provedor conhecido quando o pedido precisa de streaming/tools/visao/structured output/thinking/cache |
| `api_key_validator.py` | 1.0.0 | Detector deterministico de API keys hardcoded em codigo gerado |
| `code_sandbox.py` | 1.5.0 | Executor de codigo em subprocess isolado com timeout; syntax_check() valida runtime sem executar; novo `run_test_suite()` roda de verdade os testes gerados (achado 2026-08-04: nunca eram executados antes); 1.5.0 adiciona `lint_check()` (ruff com config curada -- so F/E9/B, defeito real, nunca estilo) e `typecheck()` (mypy consultivo) sobre o codigo GERADO, fechando a assimetria historica em que o CI exigia lint/tipos do proprio NVDAStudio mas o addon entregue ao usuario nao passava por nenhum dos dois; gettext (`_`) declarado como builtin para nao reprovar todo addon traduzido com F821; ambos FAIL-OPEN quando a ferramenta nao esta instalada |
| `context_compressor.py` | 3.0.0 | Compressor semantico com streaming scrubber, token budget aware; janela de contexto por modelo agora vem de `ai/model_registry.py` (fonte unica) em vez de tabela hardcoded propria (so 3 de ~20 modelos cobertos, deepseek-v4-flash errado em 64k quando a janela real e 1M) |
| `trajectory_compressor.py` | 1.0.0 | Compressor de trajetoria de conversa (Hermes-inspired) |

### gui/

| Modulo | Versao | Responsabilidade |
|--------|--------|------------------|
| `studio_dialog.py` | 5.40.0 | UI acessivel e conversacional; apresentacao/confirmacoes do plano e esclarecimentos inline no chat (sem dialogo modal); status/heartbeat/troca de fase/checkpoint vao para o historico mas NAO sao narrados automaticamente pelo NVDA (so prompts que exigem resposta continuam falados); checkpoints NUNCA param o pipeline (removido o fluxo bloqueante `_ask_checkpoint_inline` -- a IA decide sozinha e continua, so avisa); classificador de intencao (plano/empacotamento/esclarecimento) narra via `narrate()` em vez do texto fixo "Processando resposta." falado; historico nunca e apagado ao disparar o pipeline — so o Reset explicito limpa; inicio/fim de empacotamento vao pro historico; `_show_error` sem popup modal, agora sanitiza texto de excecao antes de exibir/falar (achado 2026-08-04); PostGenerationDialog/_DiscardConfirmDialog/ClarificationDialog/NVDAStudioStatsDialog removidos — uma janela so; `_collect_web_sources()` exibe "Fontes consultadas" no historico quando um step web_research encontra citacoes (o relatorio tecnico completo continua interno); `_on_progress` (fluxo de MODIFICAR addon existente) agora escreve no historico navegavel -- antes 8 de 12 tipos de evento ficavam mudos; foco pos-entrega vai pro campo de input, nao mais pro log (achado 2026-08-04) |
| `settings_panel.py` | 6.5.0 | Configuracao e validacao nativa dos provedores; dropdown de modelo por provedor derivado em tempo real de `model_registry.get_active_models_for_ui_provider()` (bug real corrigido: a lista era hand-maintained e tinha desalinhado do registry) |

### memory/

| Modulo | Versao | Responsabilidade |
|--------|--------|------------------|
| `session_memory.py` | 3.0.0 | web_knowledge + dep_failures + get_similar_sessions(); TinyDB + pruning automatico |
| `agent_memory.py` | 2.0.0 | Memoria por agente com recuperacao semantica, sem pontuacao lexical por palavras coincidentes |
| `memory_loop.py` | 4.0.0 | Memory loop com 4 tipos (episodic, semantic, procedural, user model) |
| `memory_manager.py` | 2.1.0 | Memoria persistente proativa (agente decide o que salvar); `_detect_injection()` delega para `utils/injection_guard.py` |
| `conversation_manager.py` | 2.2.0 | Conversacao agentica: status curto so no historico (sem fala automatica desde v5.31.0 do studio_dialog); heartbeat de execucao so na barra de status (efemero); conteudo longo so no historico |
| `session_recap.py` | 1.0.0 | Resumo automatico da sessao |

### tools/

| Modulo | Versao | Responsabilidade |
|--------|--------|------------------|
| `domain_researcher.py` | 1.4.0 | Pesquisa dominio, APIs, boas praticas e seguranca para uso interno do Planner e dos agentes; o relatorio tecnico nao e exposto no historico; grounding real via `external_search.py` (Tavily/Exa) quando configurado -- `research_sources` passa a ser sempre URLs reais da busca, nunca o LLM "lembrando" fontes do treinamento |
| `external_search.py` | 1.0.0 | Busca web externa via Tavily + Exa (chaves `TAVILY_API_KEY`/`EXA_API_KEY` em env), combinada e deduplicada por URL; sem nenhuma chave configurada, retorna vazio (fallback pro conhecimento do LLM, comportamento anterior preservado) |
| `skills_hub.py` | 4.0.0 | Catalogo local de skills nativas |
| `tool_gateway.py` | 3.0.0 | Gateway local de ferramentas com controle e seguranca |

MCP, A2A (Agent-to-Agent), browser-use e computer-use **nao fazem parte do escopo atual** do projeto -- pesquisa web nativa por provedor (`native_web_search()`/`web_search()`) ja cobre a necessidade de acesso a informacao externa, e nenhum fluxo do pipeline depende de comunicacao federada entre agentes ou de controle de tela/browser externo. Removidos em 2026-08-03 (auditoria de codigo morto): `tools/mcp_connector_stateless.py`, `tools/a2a_protocol.py`, `tools/browser_use.py`, `tools/computer_use.py` -- 4 modulos datados 2026-07-24, nunca importados por nenhum outro modulo do projeto nem por testes, e cujas implementacoes retornavam respostas **simuladas/hardcoded** disfarcadas de chamadas reais (ex.: `# Simula a resposta bem-sucedida do discovery stateless`). Se uma dessas integracoes se tornar necessaria no futuro, deve ser implementada de verdade (chamada real, sem simulacao) e documentada nesta tabela e no `AI_MODULE_SPEC.md` antes de entrar no repositorio -- nao como stub.

### tool_system/

| Modulo | Versao | Responsabilidade |
|--------|--------|------------------|
| `__init__.py` | 2.0.0 | Wiring do pacote -- importa ToolRegistry/ApprovalWorkflow/ToolExecutor e auto-registra os 3 builtins como efeito colateral do proprio import |
| `registry.py`, `approval.py`, `builtins/` | — | Tool registry, approval workflow (hardline sempre o 1o gate -- bug real corrigido 2026-08-04), path security, output limits |
| `executor.py` | 1.2.0 | Executor com timeout por tool, stale detection e retry com jittered backoff (Hermes agent/retry_utils.py) em timeout transiente ; pool descartavel por chamada |

### utils/

| Modulo | Versao | Responsabilidade |
|--------|--------|------------------|
| `logger.py` | 1.2.0 | Logging estruturado sem emojis; log de projeto (`logs/`) so e criado/escrito quando `_IS_DEV_CHECKOUT` detecta o checkout de dev real (manifest.ini + build.py na raiz), evitando gravar `addons/logs/` no addon instalado; poda logs com +30 dias; mascara chaves de API nos previews de LLM antes de gravar |
| `injection_guard.py` | 1.0.0 | Deteccao/neutralizacao de prompt injection em texto de origem externa (memoria persistente, resultados de busca web) |
| `project_policy.py` | 1.0.0 | Fonte unica do baseline e da politica anti-legado |
| `evaluation_framework.py` | 1.0.0 | Registro de metricas de pipeline (duracao, sucesso, tokens, issues); trending e regressao |
| `iteration_budget.py` | 1.3.0 | Controle de iteracoes, tokens, custo USD, rate limiting; 1.3.0 troca o teto unico de 500 mil por teto POR COMPLEXIDADE (low 300 mil / medium 700 mil / high 1 milhao), dimensionado pela mediana real medida nos 379 relatorios -- addon simples bem-sucedido tem mediana de 204 mil, complexo de 821 mil. `apply_complexity()` e chamado pelo orchestrator quando o plano existe (`reset()` roda antes disso e nao teria como saber); complexidade desconhecida cai em medium, nunca no alto. `reset()` restaura o padrao -- o budget e singleton de processo e uma sessao high deixaria o teto alto valendo para a query seguinte |
| `scheduler.py` | 2.1.0 | Scheduler local de tarefas agendadas em background |
| `cost_tracker.py` | — | Consciencia de custo para roteamento inteligente |
| `smart_retry.py` | 1.0.0 | Retry inteligente com analise de raiz do erro |
| `user_visible_text.py` | 1.0.0 | Contrato central de texto simples para leitor de telas; remove raciocinio e decoracao visual |
| `task_tracker.py` | 1.0.0 | Rastreador de tarefas do pipeline |
| `timeouts.py` | — | Gestao centralizada de timeouts; `engineering_review` mapeado para o teto longo (le todo o codigo gerado de uma vez; o default de 180s estouraria num addon multi-feature) |
| `engineering_principles.py` | 1.0.0 | Principios de engenharia destilados dos 3 documentos de metodologia do projeto, prontos para prompt, ancorados na consequencia real para o usuario cego; fonte unica consumida por `planner`, `critic`, `code_generator` e `engineering_reviewer` |
| `addon_versioning.py` | 1.0.0 | Ciclo de vida do addon GERADO: versionamento semantico, enforcement deterministico de monotonicidade de versao e deteccao de changelog decorativo |
| `scripts/eval_report_digest.py` | — | Agrega os relatorios de `tests/e2e/relatorios/` em sinal acionavel: separa falha de INFRAESTRUTURA de falha de capacidade, ranqueia convergencia por addon (execucoes, taxa, score, retries, tokens), lista sucessos que entregaram addon sem ponto de entrada carregavel e ranqueia as regras mais violadas -- que e a fila de prioridade para promover regra a validador deterministico. Substitui a auditoria manual que originou os achados de 2026-08-29 |

### sub_agents/

| Modulo | Versao | Responsabilidade |
|--------|--------|------------------|
| `_base.py` | — (docstring 1.17.0) | Base compartilhada; aceita extra_docs e mantem streaming/raciocinio dos sub-agentes fora da conversa; `narrate()` -- narracao granular em tempo real com grounding concreto (dados reais, nao prosa generica); `_run_sub_agent()` agora aceita `step_type` e repassa pro client.chat() (achado 2026-08-04: nenhum chamador passava isso antes) |
| `dispatcher.py` | 2.4.0 | Roteamento deterministico; resolve handlers nativos no namespace real e recusa step desconhecido sem agente generico; handler de `engineering_review` registrado |
| `code_generator.py` | 3.34.0 | 42 regras NVDA + search_web/fetch_url tools (pesquisa proativa ReAct) + dep_failures nuancado + Fase 2 AST deterministico; tool_calls/conteudo vazio apos esgotar rounds vira [ERRO] explicito; narracao granular via narrate(); sandbox de execucao nativo (OpenAI code_interpreter, Anthropic code_execution) e memory tool nativo (so Anthropic) injetados por provedor no step code_generation; parallel tool calling real via `_dispatch_tool_call()` + `ThreadPoolExecutor` quando o modelo pede 2+ tools no mesmo turno; Fase 2 (`_verificar_codigo_gerado`) corrige bug real -- agora extrai os blocos ```python:...``` antes de validar, em vez de sempre fail-abrir num SyntaxError do texto misto; as 3 chamadas `.chat()` agora passam `step_type="code_generation"` (achado 2026-08-04, ativa teto de tokens estendido); principios de engenharia destilados injetados no `_SYSTEM` via `utils/engineering_principles.py` -- o catalogo de regras diz o que NAO fazer, os principios dizem como decidir estrutura, falha e complexidade quando nenhuma regra se aplica; 3.34.0 troca as 3 chamadas soltas de validador da Fase 2 por `_AST_VALIDATORS`, tabela de (rule_id, descricao, funcao) -- adicionar validador virou uma linha em vez de repetir chamada, agregacao, log e montagem de mensagem (Regra 5); 3 validadores novos entram por ela |
| `manifest_builder.py` | 1.14.0 | Gera manifest.ini sem secao [add-on] + auto-verificacao + campos proibidos; narracao granular via narrate(); `updateChannel` removido (achado 2026-08-04: campo fabricado, nao existe no AddonManifest.configspec real do NVDA); ciclo de vida do addon gerado: orientacao de versionamento semantico e changelog util no prompt, mais enforcement DETERMINISTICO de que a versao entregue e estritamente maior que a do addon existente sendo modificado (o NVDA compara versoes para decidir se ha atualizacao; reentregar como 1.0.0 nao sinaliza nada ao usuario cego) |
| `accessibility_auditor.py` | 1.14.2 | NVDA-001..038 + NVDA-040 + NVDA-042..050 + WX-A11Y-001..014 + NVDA-UX-001..003 + atalhos NVDA (NVDA-051..054 auditados por `code_generator.py`/`nvda_context.py`, nao por este modulo); narracao granular via narrate() |
| `test_generator.py` | 1.8.0 | Gera testes unittest com analise AST + verificacao final anti-HTML; narracao granular via narrate(); gera um arquivo de teste por feature (ARCH-007) quando o addon tem 2+ modulos substanciais; testes gerados agora sao EXECUTADOS de verdade em sandbox isolado (achado 2026-08-04) |
| `web_researcher.py` | 4.3.0 | Pesquisa web real sob demanda via o provedor ATIVO (OllamaClient.web_search() ou ProviderClient.native_web_search()) -- nao mais scraper `ddgs` proprio; DeepSearch: 8 janelas temporais; narracao granular em tempo real via narrate() antes/depois da busca; `_extract_sources_block()` reanexa "Fontes consultadas" ao resultado final, extraido deterministicamente do texto bruto da busca (nao confia na sintese do LLM preservar URLs); resultado bruto da web envolvido via `sanitize_untrusted_block()` antes do prompt de sintese -- defesa contra prompt injection indireto de paginas de terceiros |
| `syntax_validator.py` | 2.0.0 | Sintaxe Python via AST local (ast.parse) — zero chamadas de rede; sem narrate() de proposito (deterministico, instantaneo) |
| `ast_validator.py` | 1.4.0 | Validador AST deterministico para NVDA-019 e WX-A11Y-001; sem narrate() de proposito (deterministico, instantaneo); 1.3.0 adiciona `normalize_gesture`/`extract_declared_gestures`/`validate_declared_gestures` (verificacao de FUNCIONALIDADE pedida vs entregue) e 3 regras novas: NVDA-060 (`controlTypes.ROLE_*`/`STATE_*`, API REMOVIDA no NVDA 2022.1 -- levanta AttributeError em runtime), WX-A11Y-013 (`EVT_KEY_DOWN`/`EVT_CHAR` em ListBox/ListCtrl/TreeCtrl/DataViewCtrl -- falha SILENCIOSA com NVDA/JAWS) e NVDA-056 (`wx.MessageDialog` em thread de background sem `wx.CallAfter` -- trava o processo do NVDA inteiro); 1.4.0 adiciona `validate_internal_imports()`: coerencia dos imports RELATIVOS entre os arquivos do proprio addon. Cada arquivo era validado isolado e ninguem perguntava se o CONJUNTO fecha -- foi assim que os addons Gemini sairam com `qa/service.py` e `summarizer/service.py` impecaveis e um `__init__.py` importando de modulos que nenhum step gerou. Tolerante de proposito: `import *` nunca e reportado e modulo com SyntaxError nao vira "nome ausente" |
| `assembler.py` | 1.7.0 | Monta saida final + consistencia cruzada de nome; narracao granular via narrate() |
| `design_review_agent.py` | 2.13.0 | Challenger (riscos e suposicoes) + Constraint Guardian (catalogo completo de regras via RULE_REGISTRY_PROMPT_TEXT) + User Advocate (perspectiva do usuario cego); narracao granular via narrate() nos 3 estagios + sintese; os 3 passam `step_type="design_review"` (achado 2026-08-04, ativa timeout estendido). 2.13.0 remove o legado da reducao de 6 para 3 estagios feita na v2.0.0 -- `_SYNTHESIS_TEMPLATE` (template de 6 secoes), `_UNDERSTANDING_LOCK_SYSTEM`, `_DECISION_LOG_SYSTEM` e `_REASONING_LOCK` sobreviveram 3+ meses como codigo morto, referenciados so por testes que verificavam um formato que `run()` nao produz desde entao |
| `doc_generator.py` | 1.10.0 | userGuide.html + DOC-A01..A09 + tabela 43 termos avoid-ai-writing; narracao granular via narrate() |
| `agent_template_agent.py` | 1.4.1 | Templates MD de agentes; narracao granular via narrate() |
| `engineering_reviewer.py` | 1.0.0 | Julga a ENGENHARIA do codigo gerado -- o que nenhum ID de regra descreve: fronteira de modulo errada, erro engolido, recurso sem dono, complexidade sem motivo, testabilidade, risco de evolucao. Proibido citar IDs de regra (isso e trabalho do `accessibility_auditor` e do `critic`) e proibido reportar estilo. Roda no modelo leve -- nao consome o orcamento de 20% do modelo topo |
| `agent_runner_agent.py` | 1.5.0 | AgentRunner com validacao estrutural; narracao granular via narrate(); run() agora passa `step_type="agent_runner"` (achado 2026-08-04, ativa timeout/teto de tokens estendidos) |

### Templates

| Arquivo | Versao |
|---------|--------|
| `agent_templates/wxpython_specialist.md` | 1.1.0 |
| `agent_templates/braille_specialist.md` | 1.0.0 |
| `agent_templates/nvda_addon_specialist.md` | 1.0.1 |
| `agent_templates/nvda_agent_builder.md` | 1.0.1 |
| `agent_templates/nvda_accessibility_auditor.md` | 1.0.0 |

---
## Estrutura Atual do Projeto

```text
nvdastudio/
|-- README.md
|-- manifest.ini
|-- build.py
|-- requirements.txt
|-- pytest.ini
|-- docs/
|   |-- rule-coverage.md
|-- addon/
|   |-- globalPlugins/
|       |-- nvdastudio/
|           |-- __init__.py
|           |-- AI_MODULE_SPEC.md
|           |-- skill_registry.json
|           |-- ai/              (clarifier, critic, llm_client, llm_factory, ollama_client, model_registry, prompt_optimizer)
|           |-- builder/         (addon_builder, addon_loader, nvda_context, api_key_validator, code_sandbox, context_compressor, trajectory_compressor)
|           |-- core/            (orchestrator, agentic_loop, planner, orch_types, checkpoint_manager)
|           |-- gui/             (studio_dialog, settings_panel)
|           |-- memory/          (session_memory, agent_memory, memory_loop, memory_manager, conversation_manager, session_recap)
|           |-- skills/          (metadados SKILL.md das skills nativas)
|           |-- sub_agents/      (13 agentes especializados)
|           |-- tool_system/     (registry, executor, approval, builtins/)
|           |-- tools/           (domain_researcher, external_search, skills_hub, tool_gateway)
|           |-- utils/           (logger, project_policy, engineering_principles, addon_versioning, evaluation_framework, iteration_budget, scheduler, cost_tracker, smart_retry, user_visible_text, task_tracker, timeouts)
|           |-- agent_templates/
|           |-- lib/             (dependencias vendorizadas: httpx, tinydb, ...)
|-- tests/
|   |-- conftest.py
|   |-- unit/
|   |-- integration/
|   |-- e2e/
```

Arquivos removidos por politica anti-legado:
- `buildVars.py`
- `addon/globalPlugins/nvdastudio/agent_engine.py`
- `_update_tests_versions.py`
- `tests/e2e/test_nvda_real.py`
- `_verify_installed.py`
- `_build.py` (wrapper redundante de build.py)
- `_audit_rule_coverage.py` (script ad hoc de auditoria, nao usado no build/testes)
- `_ver.py` (script scratch de debug)
- `grep_readme.py` (script de migracao ja executado)
- `addon/globalPlugins/nvdastudio/ai/background_review.py`
- `addon/globalPlugins/nvdastudio/hermes_bridge/` (excluido do runtime e do pacote)
- `addon/globalPlugins/nvdastudio/tools/mcp_connector_stateless.py`, `a2a_protocol.py`, `browser_use.py`, `computer_use.py` (2026-08-03: 4 modulos orfaos com respostas simuladas/hardcoded, nunca importados por nenhum outro modulo — ver nota acima em `tools/`)

---

## Arquitetura Atual

Fluxo principal (Pipeline Conversacional v2.0.0):

1. **CONVERSA**: A IA conversa com voce para entender o que voce quer.
2. **PESQUISA**: `domain_researcher.py` pesquisa o dominio, APIs, boas praticas e seguranca.
3. **PLANO**: `planner.py` monta o plano de desenvolvimento com etapas detalhadas.
4. **APROVACAO**: Voce ve o plano e decide: APROVAR, MODIFICAR ou CANCELAR.
5. **EXECUCAO**: O pipeline executa com checkpoints — a IA explica cada passo e pergunta se quer continuar.
6. **REVISAO**: O resultado final e mostrado para revisao.
7. **PRONTO**: Voce decide o destino: instalar, salvar, ou pedir modificacoes.

Fluxo classico (Pipeline Autonomo):

1. O usuario descreve o addon em linguagem natural.
2. `clarifier.py` decide se precisa perguntar algo antes do pipeline.
3. `orchestrator.py` delega ao `AgenticLoop` (FSM 14 estados) que gerencia o loop autonomo.
4. O `AgenticLoop` decide estrategias dinamicas (retry, swap_model, ensemble_verify, mental_simulation, self_play_adversarial, tool_creation, surgical_replan, full_replan, decompose_goal, consult_memory, ask_user_hint, forced_novel, diagnose_give_up).
5. `planner.py` cria o plano com steps especializados e modelos por tipo/provedor.
6. O plano e executado via `dispatcher.py`, que aceita apenas skills/handlers conhecidos e falha em step desconhecido.
7. `critic.py` avalia cada step em dois estagios.
8. Pesquisa web real via `web_researcher.py` (sob demanda quando keywords detectadas).
9. `assembler.py` monta a saida final.
10. `studio_dialog.py` salva, empacota, instala ou itera sobre o resultado.

Modo iterativo:

1. O usuario carrega um addon existente por pasta ou `.nvda-addon`.
2. `addon_loader.py` extrai manifesto, codigo e documentacao sem executar nada.
3. O chat rapido analisa o addon via o modelo leve resolvido dinamicamente pelo `model_registry` (Ollama: `deepseek-v4-flash`).
4. Uma acao estruturada `run_pipeline` envia a especificacao interna ao pipeline autonomo sem expo-la na conversa.

---

## Build, Instalacao e Distribuicao

Build canonico do projeto:

```bash
python build.py
```

Esse fluxo:
- empacota o addon em `dist/` a partir de `addon/` e `doc/` (nao instala dependencias; `lib/` e vendorizada no repositorio)
- exclui `__pycache__`, `*.pyc`, `bin/` e `*.dist-info` do pacote
- usa `manifest.ini` como metadado raiz do pacote

Instalacao:

1. Gerar o pacote com `python build.py`
2. No NVDA: `Ferramentas > Gerenciar Addons > Instalar`
3. Obter chave de API do Ollama Cloud: `https://ollama.com/settings/keys`
4. Configurar `OLLAMA_API_KEY` no painel de configuracoes do NVDAStudio (`NVDA+Shift+,`)
5. Abrir o studio com `NVDA+Shift+N`

---

## Notas de Compatibilidade

- O projeto suporta oficialmente `NVDA 2026.1.1+`.
- O baseline atual elimina a estrategia de “compatibilidade ampla” para versoes antigas.
- Regras de forward-compatibility para `NVDA 2026.1+` continuam documentadas porque afetam binarios, `ctypes`, `winBindings` e ABI.
- `manifest.ini` deve permanecer sem secao `[add-on]`.
- O pipeline nunca executa codigo gerado pela LLM.

---

## Estado Atual da Documentacao

- Este `README.md` foi sincronizado com o codigo em `2026-07-20`.
- Suite de testes: **1786 testes coletados em `tests/unit` + `tests/integration`**.
- O contrato central atualizado esta em [`addon/globalPlugins/nvdastudio/AI_MODULE_SPEC.md`](C:/nvdastudio/addon/globalPlugins/nvdastudio/AI_MODULE_SPEC.md).
- Este README.md e o AI_MODULE_SPEC.md sao os unicos guias operacionais mantidos; docs/dev-guide.md e docs/hermes-integration.md foram removidos por politica anti-legado em 2026-07-14 (estrutura de pastas e dependencias desatualizadas, duplicando o que ja esta aqui).

---

## Notas de Release v2.1.0

### Bugs Corrigidos

1. **Forbidden Future Import** — Removida `from __future__ import annotations` do `agentic_loop.py`. Viola regra de Python strict typing no CLAUDE.md: "NUNCA usar from __future__ import annotations — causa regressão de tipos em runtime"

2. **Missing Orchestrator Attributes** — Inicializadas 3 variáveis em `Orchestrator.__init__()`:
   ```python
   self._previous_issues: list[str] = []  # para retry_same() injetar issues
   self._last_result: OrchestrationResult | None = None  # armazena último resultado
   self._current_plan: ExecutionPlan | None = None  # plano atual em execução
   ```

3. **Synchronous Pipeline Blocking** — Substituídas 20 chamadas a `self._orch._run_pipeline()` por `self._orch.run_async()` em `StrategyExecutor`. Evita travamento da thread UI do NVDA ao executar steps longos.

### Wiring Completo (v2.1.0)

1. **evaluation_framework** — Wired ao final do pipeline bem-sucedido em `orchestrator.py` (bloco WIRING). Registra métricas: duração, token count, issues, modelo final. Bug real corrigido em 5.19.0 (2026-08-04): o wiring instanciava `PipelineEvaluator()` novo a cada chamada em vez de usar a instância global `evaluation` — histórico nunca acumulava de verdade, mesmo com o log de sucesso aparecendo.

2. **code_sandbox** — Wired na validação de sintaxe Python dentro de `_execute_step_with_critique()`. Verifica runtime sem executar via `sandbox.syntax_check()`.

3. **agent_memory** — Wired ao final do pipeline. Para cada step completado, registra padrão de sucesso e output inicial.

4. **api_key_validator** — Já wired implicitamente: criado_generator.py chama `validate_api_keys()` durante geração.

5. **model_registry** — Já wired: `planner.py`, `critic.py`, `clarifier.py`, chat rapido, domain research e fallback do orquestrador resolvem modelos pelo registry.

Próximas prioridades de wiring:
- `prompt_optimizer.py`: Conectar `record_result()` e `select_best_variant()`
