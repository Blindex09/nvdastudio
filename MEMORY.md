# NVDAStudio — Progresso da Implementacao

## Sessao Atual (2026-07-21) — parte 24: causa raiz real do "esgotou N rodadas de tool-calling" (pesquisa web + fix pros 4 provedores)

Continuacao direta da parte 23: Felipe testou de novo ao vivo (mesmo addon GeminiChatWeb) e o
pipeline falhou de verdade na etapa de codigo -- nao foi so o bug de narracao vazando codigo, foi
uma falha real de geracao. Perguntou se os logs diziam se o addon tinha sido gerado ou nao.

**Diagnostico via log real** (`nvdastudio_2026-07-21.log`, cruzando timestamps com os testes
automatizados rodando em paralelo no MESMO arquivo -- log compartilhado entre sessao real e
pytest, exige filtragem cuidadosa): a 1a geracao de codigo (6 arquivos) foi APROVADA pelo
SpecCritic (score 95), mas o QualityCritic pediu CORRIGIR (score 75 -- faltava
`NVDAState.shouldWriteToDisk()` e flags do `@script`). A rodada de correcao que seguiu esgotou
as 3 tentativas de tool-calling sem nunca fechar com codigo (`kimi-k2.7-code` insistindo em
`tool_calls`), e as tentativas seguintes vieram com violacoes estruturais novas (indentacao com
espaco em vez de TAB, `version` invalida) ate o orchestrator desistir de vez: "Pipeline sem
artefatos essenciais... nenhum arquivo Python valido do addon foi gerado e aprovado." Resposta
direta: NAO, o GeminiChatWeb nao terminou de ser gerado -- chegou a existir uma vez em memoria,
mas o ciclo de correcao automatica nunca convergiu.

Felipe insistiu explicitamente em pesquisa web de verdade ANTES de corrigir ("é por isso que eu
te falo pra pesquisar na web sempre... quero que voce resolva antes mesmo de acontecer"), e pediu
que o fix cobrisse TODOS os modelos, nao so o que falhou ao vivo. 3 subagentes de pesquisa
dedicados disparados em paralelo, 1 por familia de provedor:

- **OpenAI/xAI**: `tool_choice: "none"` (string, nivel raiz do payload) forca resposta so em
  texto, compativel com streaming e Structured Outputs. Manter `tools` presente + `tool_choice:
  "none"` -- padrao demonstrado nos exemplos oficiais e no OpenAI Agents SDK
  (`reset_tool_choice=True` por padrao apos cada tool call).
- **Anthropic**: `tool_choice: {"type": "none"}` -- formato antigo, existe desde bem antes da
  geracao atual de modelos Claude. Omitir `tools` inteiramente na rodada final tambem e seguro
  (API so valida pareamento `tool_use`/`tool_result` no historico, nao exige `tools` presente na
  chamada atual).
- **Gemini**: migrou pra Interactions API (GA 2026-06) -- equivalente agora e um campo
  `tool_choice` no nivel raiz (nao mais `tool_config.function_calling_config.mode` do
  `generateContent` classico), aceita `"auto"|"any"|"none"|"validated"`.
- **Ollama**: API nativa `/api/chat` NAO TEM `tool_choice` documentado (confirmado direto na doc
  oficial -- so o shim de compatibilidade OpenAI `/v1/chat/completions` tem). Mitigacao adotada:
  omitir `tools` do payload por completo na ultima rodada -- combinacao nao documentada
  oficialmente, mas e o padrao de comunidade e consistente com o mesmo principio do OpenAI Agents
  SDK. Pesquisa tambem trouxe um achado paralelo: modelos de raciocinio (Kimi K2, DeepSeek) tem
  bug conhecido (issues reais no GitHub de outros backends, ex: sglang, OmniRoute) de reentrar em
  loop de tool_calls quando o campo de raciocinio nao volta pro historico entre turnos --
  confirmado que este projeto JA lida com isso corretamente (thinking gravado no historico do
  assistant quando o modelo suporta), nao precisou de mudanca adicional.

**Fix aplicado**: `code_generator.py` (3.23.0) agora forca `tool_choice="none"` na ultima rodada
permitida do loop de tool-calling (`_round == max_tool_rounds - 1`). `provider_client.py` (2.8.0)
passou a repassar `tool_choice` tambem pra Anthropic/Gemini (antes so ia pra OpenAI/xAI) e traduz
pro formato de cada provedor. `ollama_client.py` (2.14.0) omite `tools` do payload quando
`tool_choice="none"` e pedido. 4 testes novos cobrindo os 3 arquivos.

Suite completa apos o fix: ver resultado no proximo log de sessao.

## Sessao Atual (2026-07-21) — parte 23: remocao do ReasoningNarrator + 2 bugs reais de live-test

Felipe pediu "quero remover esse antigo" (o ReasoningNarrator da parte 21/22) e depois colou um
historico REAL de live-test (criando o addon "GeminiChatWeb") mostrando 2 problemas novos.

**Remocao**: `ReasoningNarrator` (sub_agents/_base.py) e os parametros `on_reasoning_chunk`/
`include_reasoning` (provider_client.py, ollama_client.py) removidos por completo -- ficaram
sem nenhum consumidor em producao depois que o planejamento passou a narrar via tool call em
vez de reescrever o resumo de raciocinio. `_SentenceChunkBuffer` (base compartilhada) mantido --
`LiveNarrator` continua usando.

**Bug real #1 -- causa raiz da auto-fala que Felipe reportou (de novo, com frustracao)**:
`_set_status()` (studio_dialog.py) chamava `self._status.SetLabel(...)` -- isso muda o texto de
um controle Win32 NATIVO por baixo (SetWindowText da API do Windows), o que dispara
`EVENT_OBJECT_NAMECHANGE` automaticamente; o NVDA anuncia essa mudanca sozinho, como
comportamento BUILT-IN do proprio sistema operacional/NVDA -- SEM NENHUMA chamada
`ui.message()`/`_speak_message()` do addon envolvida (essas ja tinham sido removidas em rodadas
anteriores desta sessao -- o bug NUNCA esteve la, era um efeito colateral de um widget visual).
`_set_status()` parou de tocar no widget -- unico jeito confiavel de garantir "nunca falado
automaticamente, sempre so historico". As 3 mensagens estaticas de abertura de fase
("Pesquisando APIs...", "Criando o plano...", "Construindo X...") viraram `narrate()` de
verdade, fundamentadas em dado real (user_query/addon_name).

**Bug real #2 -- o mais serio, achado analisando o proprio historico que Felipe colou**:
`LiveNarrator.feed()` repassava TODO texto recebido pro buffer de narracao, sem NENHUMA
consciencia de estar dentro de um bloco ` ```fence``` `. A protecao de `extract_code_blocks()`
(orchestrator.py) so vale pro ARTEFATO FINAL salvo em disco -- nunca existiu pra proteger o que
e exibido AO VIVO via `conversation.emit_status()`. Resultado visivel no historico real: dezenas
de linhas de codigo Python/HTML/JSON/manifest.ini apareciam uma por uma como se fossem a IA
"narrando" ("Assistente: import wx", "Assistente: self._api_key = api_key", etc.) -- exatamente
o "veio codigo junto" que Felipe reportou. Raiz do erro de raciocinio original: eu tinha validado
que o texto FORA dos fences era seguro de narrar (a extracao final ignora prosa solta), mas
esqueci que o LiveNarrator tambem EXIBE ao vivo tudo que passa por ele, incluindo o conteudo
DENTRO dos fences, antes de qualquer extracao acontecer. Corrigido: `feed()` agora rastreia
entrada/saida de blocos ` ``` ` (mesmo fragmentados entre deltas de streaming consecutivos, via
buffer `_raw_tail` que junta um delimitador partido em dois deltas) e SO repassa texto de FORA
de um fence pro buffer de frases/emit_status() -- o conteudo dentro do fence fica intacto no
content bruto (usado normalmente pra extrair os arquivos), so nao aparece mais como narracao.

**Achados NAO corrigidos, reportados a Felipe pra decisao** (via analise do mesmo log real):
- Retry de tool-calling exaurido em code_generation: `[AVISO] code_generator esgotou 3
  rodada(s) de tool-calling sem resposta final (modelo ainda pedia tool_calls)` -- o modelo
  (kimi-k2.7-code, tier heavy do Ollama) ficou pedindo tool_calls repetidamente sem nunca
  finalizar o codigo. Pode ser variabilidade normal do modelo (padrao ja aceito em investigacao
  anterior desta sessao) ou pode ter sido exacerbado pela nova `_TOOL_PREAMBLE_INSTRUCTION` --
  NAO CONFIRMADO, precisa de mais live-tests pra isolar.
- `web_researcher.py` retornando codigo Python INTEIRO em vez de resumo de pesquisa quando a
  consulta e sobre a API do Gemini (proxima demais de "geracao de codigo" como topico) --
  rejeitado 2x pelo Critic com score=0 ("it is Python code... not relevant"), mesmo apos
  fix_instructions explicito pedindo pra nao usar codigo. Pode ser fraqueza pre-existente do
  `_SYSTEM` prompt (a linha "Exemplo minimo: codigo Python funcional de 3-5 linhas" pode nao
  estar sendo respeitada pelo modelo leve `deepseek-v4-flash` quando o topico em si e sobre uma
  API de codigo) -- NAO CONFIRMADO se e regressao desta sessao ou bug pre-existente.

Suite completa: 1845 passed, 2 skipped, 0 falhas. Cache/logs limpos, build recompilado, entregue.

## Sessao Atual (2026-07-21) — parte 22: "eu quero fazer em tudo" -- final_tool + planejamento convertido

Felipe, depois de ver o resultado da parte 21 (6 de 10 sub-agentes + planejamento ainda
sem narracao ao vivo de verdade): "por que que nao deu para fazer em tudo? eu quero
fazer em tudo! ... eu sei que tem, tem projetos que eles fazem isso, ate mesmo projetos
opensources." Pediu pesquisa de novo.

Achado: padrao real de producao 2026, confirmado via pesquisa (nao inventado) --
**"final answer as tool call"**. Em vez de forcar o modelo a devolver SO texto cru (que
vira o entregavel direto, sem filtro) ou SO JSON forcado (que nao aceita narracao
solta), da pra ele uma ferramenta obrigatoria de "entregar resultado". O modelo narra
livre no content ANTES de chamar essa tool, e o resultado limpo vem do ARGUMENTO da
tool -- narracao e entregavel ficam estruturalmente separados, o mesmo mecanismo
texto+tool_call que ja tinha sido validado (parte 21) pros sub-agentes com fence.

Implementado:
- `_run_sub_agent(..., final_tool={"name","description","param_name","param_description"})`
  novo em `sub_agents/_base.py` (1.13.0): liga live_narrate automaticamente, monta uma
  tool com um unico parametro string via `_final_tool_schema()`, injeta
  `_FINAL_TOOL_INSTRUCTION` no prompt pedindo pro modelo chamar a tool no final, extrai
  o resultado via `_extract_final_tool_result()` -- fallback gracioso pro content bruto
  se o modelo nao chamar a tool (nao forcado via tool_choice, so instruido -- Anthropic
  documenta tool_choice forcado como incompativel com alguns modos, e nem todo
  provedor tem esse parametro implementado no projeto).
- Aplicado nos 4 sub-agentes que ficaram de fora na parte 21 (fan-out de 4 subagents
  paralelos): `accessibility_auditor.py` (1.14.2), `agent_template_agent.py` (1.4.1,
  regra "texto puro sem blocos de codigo" clarificada pra valer so no argumento da
  tool), `design_review_agent.py` (2.9.2, 3 tools distintas -- uma por estagio
  Challenger/Guardian/Advocate), `web_researcher.py` (4.1.1, aplicado MANUALMENTE
  porque esse arquivo nao usa `_run_sub_agent()` -- reaproveita os helpers exportados
  de `_base.py` diretamente nos 2 pontos que chamam o LLM).
- **Planejamento tambem convertido** (o ultimo buraco): `planner.py` (2.13.0) --
  `_call_planner_llm()` ganha 2 caminhos. Sem `on_narration_chunk`: json_schema como
  sempre foi (preserva TODA a suite de testes antiga, minimiza risco no modulo mais
  central do pipeline). Com `on_narration_chunk`: troca json_schema por uma tool call
  obrigatoria ("entregar_plano") cujo parametro reusa o MESMO dict de schema que o
  json_schema ja usava -- o modelo narra de verdade no content antes de entregar o
  plano estruturado. `_plan_json_from_tool_call()` normaliza o argumento da tool pra
  JSON string, entao `_parse_plan()`/`_build_steps()` NAO mudam nada -- o contrato de
  retorno de `_call_planner_llm()` e identico nos dois caminhos.
  `create_plan()`/`replan_with_feedback()` tiveram o parametro renomeado de
  `on_reasoning_chunk` pra `on_narration_chunk` (nome antigo ficaria enganoso -- nao
  carrega mais resumo de raciocinio, carrega narracao real). `orchestrator.py` (5.14.0)
  troca `ReasoningNarrator` por `LiveNarrator` nas 2 chamadas de planejamento visivel.

Decisao registrada sobre `ReasoningNarrator`: ficou sem nenhum consumidor em producao
apos essa mudanca (so `planner.py` o usava, e agora usa `LiveNarrator`). NAO removido --
mantido como infraestrutura testada e reutilizavel (mesmo precedente ja usado no
projeto pra utilitarios testados-mas-nao-conectados, ex: `addon_builder.
validate_manifest`/`validate_python_structure`). O `on_reasoning_chunk` continua
implementado e testado em `provider_client.py`/`ollama_client.py` tambem, sem
consumidor direto agora, pelo mesmo motivo.

Resultado: **todo o pipeline narra ao vivo agora**, do planejamento ate o fim da
execucao -- sub-agentes com resposta fenced narram direto no content (mais simples),
sub-agentes de prosa crua e o planejamento narram via tool call de entrega (mais
seguro, sem contaminar o resultado). Suite completa: 1842 passed, 2 skipped, 0 falhas
(varredura de orfaos via AST + grep manual: nada de novo encontrado, so o falso
positivo ja conhecido `from __future__ import annotations`). Cache/logs limpos, build
recompilado (`nvdastudio-2.4.0.nvda-addon`, 481 arquivos, 9844.9 KB), entregue.

## Sessao Atual (2026-07-21) — parte 21: narracao "tool preamble" (conversa de verdade, nao mais robo)

Felipe, depois de ver o `ReasoningNarrator` da parte 20 funcionando: "na verdade esse modo
narrativa, eu nao queria em todo fluxo... quero um modo de conversa mesmo... igual as ias
de ponta fazem... nao tem como trocar esse modo narrativa por algo mais conversacional?
parece robo... sem vazar o pensamento interno em ingles?"

Diagnostico: o `narrate()` (usado em todo sub-agente) e uma SEGUNDA chamada de IA, separada,
disparada DEPOIS de cada acao -- sem memoria do que ja foi dito, cada frase nasce isolada.
Soa como um narrador externo comentando de fora, nao a propria IA "pensando em voz alta".

Pesquisa (5 subagentes dedicados, 1 por provedor, retomados apos o primeiro round cair por
limite de sessao) confirmou o termo oficial da OpenAI: "tool preambles" -- o MESMO modelo que
faz o trabalho narra, na propria resposta, ANTES/ENTRE chamadas de tool, no mesmo turno.
Confirmado com exemplos reais das docs que texto e tool_calls convivem no mesmo stream nos
5 provedores (Anthropic: "texto -> tool_use -> texto -> tool_use" no mesmo turno; Ollama e
best-effort, issue ollama/ollama#12557 documentada -- alguns modelos as vezes so mandam a
tool_call sem narrar nada antes).

Implementado:
- `provider_client.py` (2.6.0) / `ollama_client.py` (2.12.0): streaming passou a funcionar
  com tools ativo (antes a condicao `on_chunk and not tools` desligava streaming assim que
  havia tools). `_stream_sse()` trocou o contrato `extract()->(kind,text)` por `on_event(data)`,
  permitindo acumular argumentos de tool call por item/index EM PARALELO ao texto. Gemini
  precisou de ajuste extra: o tipo do evento vem no NOME do evento SSE, nao num campo JSON --
  `_stream_sse()` agora injeta isso em `data["_sse_event"]`.
- `sub_agents/_base.py` (1.12.0): `LiveNarrator` novo (base compartilhada `_SentenceChunkBuffer`
  com o `ReasoningNarrator` da parte 20) -- NAO reescreve como narrate(), emite direto via
  `conversation.emit_status()` porque o texto ja sai natural/PT-BR por instrucao direta no
  prompt (`_TOOL_PREAMBLE_INSTRUCTION`, novo). `_run_sub_agent(..., live_narrate=True)` liga
  tudo automaticamente (prompt + LiveNarrator + flush garantido).
- **Ressalva de seguranca que quase passou despercebida**: nem todo sub-agente pode misturar
  narracao no proprio content -- so os que tem a resposta final extraida de blocos com fence
  (```lang:arquivo```, onde texto solto e descartado na extracao por `extract_code_blocks()`
  no orchestrator). Classificacao confirmada por arquivo (contagem de ``` + leitura do
  system prompt de cada um):
  - **Seguro (ganhou `live_narrate=True`)**: code_generator.py (wiring manual no proprio
    loop de tool use, ja que nao usa `_run_sub_agent()` no caminho principal), test_generator.py,
    assembler.py, doc_generator.py, manifest_builder.py, agent_runner_agent.py.
  - **NAO seguro (mantido narrate())**: accessibility_auditor.py, agent_template_agent.py,
    web_researcher.py, design_review_agent.py -- a resposta crua destes E o entregavel
    direto (relatorio de auditoria, template markdown, resumo de pesquisa, critica de design);
    misturar narracao ali contaminaria o proprio resultado.
- Em code_generator.py: os narrate() "antes" de tool call (validate_import, search_web,
  fetch_url, memory) foram removidos -- duplicavam o que o proprio modelo ja narra ao vivo.
  Mantidos: o narrate() inicial (cobre o intervalo antes do 1o token chegar) e os narrate()
  que reportam resultado REAL pos-acao (ex: "encontrei resultados sobre X" do search_web,
  que o modelo so saberia no proximo turno).

Fan-out: disparei 9 subagents em paralelo (5 pra aplicar live_narrate=True + limpeza, 4 pra
so limpeza de orfaos sem mexer em narracao) com instrucoes bem especificas sobre a ressalva
de seguranca acima. Achados reais de limpeza: `_logger` morto em accessibility_auditor.py
(nunca usado -- modulo nao tem logger proprio de proposito) e 2 blocos orfaos em
design_review_agent.py (`_REASONING_QUALITY`, `_CODE_QUALITY_SYSTEM` -- vestigios do extinto
Estagio 4 "Code Quality Architect", de antes da reducao pra 3 estagios).

Achado registrado como task separada (NAO corrigido, fora do escopo pedido): `_verificar_codigo_gerado()`
em code_generator.py roda `ast.parse()` direto no `resp.content` cru, que ja inclui os
marcadores de fence (```python:arquivo.py) -- `validate_nvda019`/`validate_wx_a11y` documentam
"Fail-open: SyntaxError retorna ok=True", entao a Fase 2 de validacao AST provavelmente JA
fail-opena silenciosamente na pratica sempre que ha blocos fenced (o caso comum), mesmo antes
desta mudanca. Nao e regressao desta sessao -- pre-existente, merece investigacao propria.

Suite completa: 1829 passed, 2 skipped, 0 falhas (12 stragglers de MODULE_VERSION hardcoded
corrigidos apos o fan-out, mais 4 mocks de teste que nao aceitavam o novo kwarg live_narrate).
Build recompilado (`nvdastudio-2.4.0.nvda-addon`, 481 arquivos, 9838.4 KB), entregue.

## Sessao Atual (2026-07-21) — parte 20: planejamento ganha narracao (ReasoningNarrator)

Felipe, olhando um live-test real (tela "Criando o plano de desenvolvimento..."
parada): "vejo que aqui a ia conversacional tambem nao ativa... pesquise na web
de novo e veja como faz para todos os provedores... o intuito e que fique toda
conversacional... assim como fazem as ias de ponta".

Causa raiz: `_call_planner_llm()` (planner.py) e uma chamada UNICA bloqueante
com `response_format=json_schema` -- diferente dos sub-agentes (loop de tool
use, narram entre chamadas), o planner nunca teve narrate() porque nao ha
"entre chamadas" nenhum.

Pesquisa (direta, os 5 subagentes dedicados cairam por limite de sessao)
confirmou, provedor por provedor, que da pra pedir um resumo de raciocinio
SEPARADO do conteudo final, em streaming, na MESMA chamada que ja usa
structured output:
- OpenAI/xAI: `reasoning: {"effort": X, "summary": "auto"}` -> evento SSE
  `response.reasoning_summary_text.delta` (separado de
  `response.output_text.delta`).
- Anthropic: `thinking: {"type":"enabled","budget_tokens":N}` -> evento
  `thinking_delta` (separado de `text_delta`). So incompativel com
  `tool_choice` forcado (nao usado aqui), NAO com `output_config`.
- Gemini (Interactions API): `generation_config.thinking_summaries="auto"`
  -> delta `type:"thought_summary"` (separado de `type:"text"`).
- Ollama: campo `"thinking"` no chunk, com `think:true` -- so quebra se
  `think:false` for setado (bug ollama/ollama#15260, ja corrigido).

Antes de implementar, achei uma CONTRADICAO com uma decisao ja registrada no
changelog de `_base.py` (v1.9.0/97.13.0 desta mesma sessao): Felipe ja tinha
decidido explicitamente NAO usar o campo reasoning/thinking nativo pra
narracao, porque "e o raciocinio bruto do modelo, sem garantia de estilo"
entre os 5 provedores. Perguntei via AskUserQuestion antes de seguir --
confirmado: manter o padrao (reescrever via narrate() antes de mostrar),
nao expor o raciocinio bruto.

Implementado:
- `ReasoningNarrator` novo (`sub_agents/_base.py` 1.11.0): acumula deltas de
  reasoning/thinking e narra cada trecho fechado (fim de frase ou >=60
  chars) via `narrate()` -- nunca o texto bruto.
- `_stream_sse()` (`provider_client.py` 2.5.0) refatorado: `extract()` agora
  retorna `(kind, text)` em vez de so `text`; "reasoning" vai pro
  `on_reasoning_chunk`, "content" pro `on_chunk`/retorno final. Compat
  retroativa com extract() antigo (string simples = kind "content").
- `chat()` ganha `on_reasoning_chunk` opcional nos 3 branches
  (OpenAI/xAI, Anthropic, Gemini) e no `OllamaClient` (2.11.0, que ja
  capturava "thinking" no streaming mas so retornava no final --
  agora tambem repassa ao vivo).
- `planner.py` (2.12.0): `create_plan()`/`replan_with_feedback()` ganham
  `on_reasoning_chunk` opcional, repassado ate o client.
- `orchestrator.py` (5.13.0): liga um `ReasoningNarrator` por chamada de
  planejamento/replan, com `flush()` garantido em `finally` (mesmo se a
  chamada falhar).

47 testes novos (ReasoningNarrator, roteamento reasoning/content nos 3
provedores + Ollama, wiring do orchestrator via inspecao de source no
padrao ja usado no arquivo). Suite completa: 1875 passed, 6 skipped, 0
falhas (1 straggler de MODULE_VERSION hardcoded corrigido). Cache/logs
limpos, build recompilado (`nvdastudio-2.4.0.nvda-addon`, 481 arquivos,
9830.1 KB), entregue.

## Sessao Atual (2026-07-20) — parte 19: segunda auditoria de orfaos (verificacao pos-entrega)

Felipe pediu, antes de testar de novo ao vivo: "removeu tudo orfam? atualizou
os testes e documentação, recompilou? apagou pichaches, caches" -- checklist
de verificacao honesta, nao retorica.

Achados (scan AST de imports nao usados + grep manual, cobrindo os arquivos
mais mexidos da sessao):
- `code_generator.py` (3.20.0 -> 3.21.0): 5 imports mortos removidos --
  `_is_known_module` (de `..builder.addon_builder`, os outros 3 nomes do
  mesmo import continuam em uso), `LLMClientError` (de `..ai.llm_client`),
  `ABSOLUTE_MIN_NVDA` / `PROJECT_LAST_TESTED_NVDA` / `PROJECT_MIN_NVDA` (de
  `..utils.project_policy`). Confirmado zero referencias reais para cada um.
- `orchestrator.py` (5.11.0 -> 5.12.0): `get_step_timeout` e `TimeoutError`
  (import de topo, de `..utils.timeouts`) removidos -- `_get_step_timeout()`
  ja fazia seu proprio import local redundante. `STEP_SYNTAX_VALIDATION`
  (de `.planner`) foi removido e DEPOIS RESTAURADO na mesma rodada: embora
  nao usado dentro do arquivo, `tests/unit/test_syntax_validator.py::
  test_step_syntax_validation_importado` depende dele como re-export deste
  modulo. **Licao importante**: checagem de import morto via AST so cobre
  uso dentro do proprio arquivo -- nao pega consumidores externos que
  importam de um modulo esperando um re-export. Sempre confirmar com grep
  em `tests/` (nao so no proprio arquivo) antes de remover um import
  "nao usado".
- `studio_dialog.py`: 1 docstring desatualizada corrigida em
  `_display_result` -- ainda dizia "abre PostGenerationDialog" (esse dialogo
  foi removido ha varias versoes, v5.28.0); corrigido pra descrever o fluxo
  real (pergunta inline no chat).

Testes: 8 asserts de `MODULE_VERSION == "5.11.0"` (orchestrator) e 7 asserts
de `MODULE_VERSION == "3.20.0"` (code_generator) hardcoded em arquivos de
teste espalhados, atualizados para as novas versoes -- padrao ja recorrente
nesta sessao apos cada bump de versao. Suite completa (unit+integration,
1845 passed / 6 skipped) rodou limpa, exceto 6 falhas em
`test_skills_melhorias_v3.py::TestValidateImportToolDesign` que sao
dependentes de ORDEM de execucao entre arquivos de teste (poluicao de
`sys.modules` ou cache de outro teste) -- confirmado rodando o arquivo
isolado: 26/26 passam. Nao e regressao desta limpeza, e um problema de
isolamento de teste pre-existente, fora do escopo do pedido atual.

Cache/logs: 0 `__pycache__`, 0 `.pytest_cache`, 0 `.log` confirmado apos
`scripts/clean_runtime_artifacts.ps1`.

Build: `dist/nvdastudio-2.4.0.nvda-addon`, 481 arquivos, 9827.0 KB --
recompilado limpo com as correcoes acima, entregue ao Felipe.

## Sessao Atual (2026-07-20) — parte 18: erro real investigado + narracao ganha grounding concreto

### Contexto (parte A: investigacao do erro real)
Felipe colou um trecho de historico real de live-test e pediu: "veja nos logs do nvda studio e do nvda tambem, deu um erro, veja da onde que e." O erro visivel no chat: "settings.py: uso de _() sem import. Adicione 'from addonHandler import _' no inicio do arquivo."

Investigado nos logs (`%APPDATA%\nvda\nvdastudio_logs\`): o QualityCritic (estagio 2, model=deepseek-v4-flash) rejeitou o `code_generation` do addon "GeminiWebChat" com 3 problemas reais: (1) `_()` usado sem import, (2) `server.py` sem checar `NVDAState.shouldWriteToDisk()` antes de ler/escrever historico, (3) indentacao com espacos em vez de TABS em todos os arquivos Python. Verdict REJEITAR, score 50.

Confirmado que os 3 problemas JA sao regras existentes no `NVDA_SYSTEM_PROMPT` (NVDA-003 gettext sem import, NVDA-016 shouldWriteToDisk, NVDA-021 TABS) -- nao e uma regra faltando. Confirmado tambem que o mecanismo de retry funciona certo: `orchestrator._execute_step_with_critique()` captura `last_issues = crit.issues` e repassa via `_build_step_prompt(previous_issues=last_issues if attempt > 0 else [])` pra tentativa seguinte (fix de uma parte anterior desta mesma sessao), e ainda troca proativamente pro modelo de resiliencia se o step e critico e ja falhou uma vez.

**Conclusao**: o sistema de deteccao+retry+escalacao funcionou como projetado (achou o erro real, tentou de novo com o feedback certo, escalou modelo), mas o modelo (kimi-k2.7-code, escalando entre si e kimi-k2.6 -- familia Kimi, blind spots parecidos) nao conseguiu corrigir a tempo de esgotar os `max_retries=3` default, e o pipeline terminou em "Pipeline sem artefatos essenciais". Isso e variabilidade probabilistica do modelo em producao, nao um bug de codigo novo -- nao teve fix de codigo pra essa parte, so a explicacao honesta.

### Contexto (parte B: narracao repetitiva)
No mesmo turno, Felipe notou no historico colado que a narracao ficava repetitiva ("Estou revisando o codigo para garantir que esta tudo certo" varias vezes, com pequenas variacoes de fraseado mas sem informacao nova) e perguntou: "nao tem como deixar estilo as plataformas de ponta quando estao executando algo? pesquise na web de novo."

### Pesquisa web
Confirmou o anti-padrao exato: "wrapping every action in natural language... that is not an execution record, it is a narration" -- a recomendacao 2026 e que toda narracao de agente seja fundamentada em dados REAIS da execucao (nomes de arquivo, contagens, resultados concretos), nunca prosa vaga tipo "revisando o codigo".

### Auditoria dos proprios narrate() da sessao
Revisando as partes 14/15 desta mesma sessao: ~15 das ~20 chamadas de `narrate()` eram strings FIXAS, sem nenhuma variacao a cada execucao -- exatamente o anti-padrao que a pesquisa apontou. Isso explica por que a narracao soava repetitiva mesmo rodando 10 sub-agentes diferentes: cada um tinha 1-2 frases estaticas que se repetiam identicas (ou quase) toda vez que aquele sub-agente rodava.

### Fix
`sub_agents/_base.py` (docstring 1.9.0 -> **1.10.0**): `_NARRATE_SYSTEM` reforcado com a exigencia explicita de grounding concreto -- "SEMPRE use os detalhes concretos fornecidos... nunca fique so na frase generica".

Todos os 9 sub-agentes com narrate() puramente estatico atualizados pra passar dado real disponivel no momento da chamada:
- `code_generator.py` (3.20.0): fim extrai os NOMES dos arquivos gerados via regex nos fences ```python:arquivo.py``` e narra quantos e quais.
- `accessibility_auditor.py` (1.14.0): fim conta ocorrencias reais de `NVDA-`/`WX-A11Y-` no resultado.
- `agent_runner_agent.py` (1.3.0), `agent_template_agent.py` (1.4.0), `assembler.py` (1.5.0): fim narra a contagem real de itens/secoes/problemas faltando (ou confirma que ficou completo).
- `doc_generator.py` (1.9.0): fim conta secoes reais escritas.
- `manifest_builder.py` (1.10.0): fim extrai o NOME REAL do addon do manifest.ini gerado (regex em `name = ...`).
- `test_generator.py` (1.5.0): fim conta `def test_` reais no resultado.
- `design_review_agent.py` (2.9.0): so o estagio Challenger ganhou grounding (trecho do pedido) -- os outros 2 (Guardian/Advocate) ja eram distintos entre si por natureza, deixados fora do escopo desta rodada por tempo.

Todos os inicios agora incluem um trecho real do `prompt` recebido, em vez de descricao generica fixa da tarefa do sub-agente.

### Testes
Nenhum teste novo dedicado (as mudancas sao de CONTEUDO de string, nao de comportamento estrutural) -- os testes existentes que checam `"narrate(" in src` continuam validos. Fix mecanico: ~28 asserts de `MODULE_VERSION` hardcoded corrigidos em 2 rodadas.

### Validacao
Suite completa em background apos este round -- ver journal se precisar confirmar o numero exato antes do rebuild final.

---

## Sessao Atual (2026-07-20) — parte 17: implementadas as 6 funcionalidades nativas listadas

### Contexto
Felipe pediu explicacao do que cada uma das 5 oportunidades (+ web_fetch do Ollama, contado a parte) melhoraria de verdade no NVDAStudio. Expliquei cada uma com ressalvas: (1) sandbox de execucao (OpenAI/Anthropic) tecnicamente ainda e "executar codigo gerado", so que remoto -- conflita com a Regra 9 do projeto; (2) memory tool da Anthropic so funciona quando Anthropic e o provedor, quebrando a consistencia entre os 5 que o projeto mantem hoje. Felipe respondeu "pode fazer tudo isso, aplique tudo isso" -- antes de implementar os 2 itens com ressalva, perguntei explicitamente via AskUserQuestion (nao presumi autorizacao so pelo "aplique tudo" depois de eu ter acabado de levantar a ressalva). Ele confirmou os 2.

### 1. Ollama: web_fetch()
Endpoint dedicado `/api/web_fetch` (irmao do `/api/web_search`), confirmado campo-por-campo contra a doc oficial via WebFetch direto (nao resumo de busca). Ligado como tool "fetch_url" em `code_generator.py` -- busca a pagina inteira quando o snippet do search_web nao tem detalhe suficiente (ex: lista completa de parametros de uma API). So funciona quando o provedor ativo suporta (`hasattr(client, "web_fetch")`); nos outros 4 retorna status='unavailable' sem travar o loop.

### 2. xAI: grok-build-0.1 vira o tier heavy
Mesmo raciocinio ja aplicado ao Ollama (kimi-k2.7-code): `_HEAVY_STEPS` em planner.py so cobre `code_generation`, entao o tier heavy de cada provedor ja e, na pratica, o "modelo de geracao de codigo" daquele provedor -- grok-build-0.1 (modelo dedicado a coding agentico, beta publica maio/2026) e um upgrade natural sobre o grok-4.5 generalista. grok-4.5 vira fallback na cadeia. Nuance documentada: o tier heavy tambem e usado como modelo de escalacao (`orchestrator._get_resilience_model()`) pra QUALQUER step que falhar, nao so code_generation -- mesmo trade-off ja aceito antes pro kimi-k2.7-code.

### 3 e 4. Sandbox de execucao nativo (OpenAI code_interpreter, Anthropic code_execution)
`{"type":"code_interpreter","container":{"type":"auto"}}` (OpenAI) e `{"type":"code_execution_20260521","name":"code_execution"}` (Anthropic) injetados condicionalmente em `code_generator.py.run()` conforme `client._provider`. O modelo pode testar o proprio codigo antes de devolver a resposta final -- roda na infra do provedor, nao na maquina do usuario nem do NVDAStudio.

**Bug real encontrado implementando isso**: `provider_client.py` achatava INCONDICIONALMENTE todo item de `tools` via `_tool_function()` (que assume formato function-calling: name/description/parameters). Misturar um server tool nativo (`{"type":"code_interpreter",...}`) no mesmo array corromperia ele num function-tool vazio (`{"type":"function","name":"","description":"","parameters":{}}`) -- eu teria introduzido esse bug se nao tivesse checado antes de rodar teste. Corrigido com `_is_native_tool()` (detecta blocos com "type" != "function") e `_build_tools_payload()` (repassa nativos intactos, achata o resto), usado nos 3 pontos que montam `payload["tools"]` (OpenAI/xAI, Anthropic, Gemini).

### 5. Gemini: modo stateful via previous_interaction_id
Quando ja existe uma interaction anterior NO MESMO objeto ProviderClient (`self._gemini_interaction_id`, capturado de `data["id"]` na resposta), a chamada seguinte manda so o turno novo + `previous_interaction_id` em vez de reenviar `self._history` inteiro -- reduz tokens/latencia em conversas de varios turnos dentro do mesmo client (ex: rodadas de tool-calling do code_generator, ate 3 por step). Primeira chamada e o caminho de streaming continuam reconstruindo tudo, sem mudanca de comportamento -- histórico continua sendo mantido em paralelo como fallback. `reset_history()` agora tambem limpa o interaction_id.

### 6. Anthropic: memory tool nativo (mais complexo dos 6)
`{"type":"memory_20250818","name":"memory"}` -- diferente dos outros server tools (web_search, code_execution), o memory tool e CLIENT-SIDE: Claude so pede operacoes de arquivo (view/create/str_replace/insert/delete/rename) contra um diretorio virtual "/memories"; quem executa e guarda os dados e a propria aplicacao. Antes de implementar, fiz um WebFetch direto na doc oficial (nao confiei no resumo de busca) pra pegar o protocolo EXATO dos 6 comandos -- campos, strings de retorno, mensagens de erro, e a exigencia explicita de protecao contra path traversal (CWE-22).

Novo modulo `ai/anthropic_memory_tool.py` com os 6 handlers, armazenamento real em `%APPDATA%/NVDAStudio/claude_memory/` (mesmo padrao de diretorio de `session_memory.py`), `_resolve_path()` validando que todo path resolve pra dentro da raiz antes de tocar o disco. Ligado em `code_generator.py` (so quando `provider == "anthropic"`).

**Simplificacao deliberada**: o campo `is_error` do protocolo (marca semantica distinta de erro no tool_result) nao e propagado ate o final -- so o texto do erro (que ja vem no formato "Error: ..." exigido pela doc). Propagar `is_error` de verdade exigiria estender o contrato generico de `tool_results` usado por TODOS os sub-agentes so pra esse 1 campo Anthropic-especifico. Documentado como trade-off, nao um bug.

### Testes
32 testes novos no total: `test_ollama_client_web.py` (8), `test_routing.py` (+2, xAI heavy tier), `test_provider_client.py` (+6, tools nativos misturados + Gemini stateful), `test_code_generator_sandbox_tools.py` (4), `test_anthropic_memory_tool.py` (20).

### Validacao
Suite completa em background apos este round -- ver journal ou proxima parte pra confirmar numero exato.

### Transparencia sobre o que NAO foi testado ao vivo
Todas as 6 funcionalidades desta rodada, exceto o web_fetch do Ollama, sao pra provedores que Felipe nao consegue testar ao vivo nesta sessao (OpenAI, Anthropic, xAI, Gemini). Implementadas per doc oficial, com testes unitarios cobrindo a logica de decisao e o formato de payload -- mas nunca confirmadas contra uma chamada real de API.

---

## Sessao Atual (2026-07-20) — parte 16: auditoria com 6 subagentes de pesquisa dedicados

### Contexto
Depois de eu reportar "nenhuma mudanca necessaria" numa pesquisa direta (sem subagentes), Felipe pediu confirmacao mais forte: "certeza? dispare cada subagent para cada pesquisa e pesquise na web de forma longa novamente". Disparei 6 agentes em paralelo: 1 por provedor (OpenAI, Anthropic, Gemini, xAI, Ollama Cloud) + 1 sobre padroes agenticos gerais de 2026 (prompt ambiguo, checkpoint autonomo, cross-model escalation, narracao).

### Achado real: bug confirmado no Gemini
`native_web_search()` usava `tools=[{"google_search":{}}]` -- **sintaxe errada**. O subagente Gemini confirmou contra a pagina oficial de grounding da Interactions API que o formato correto e `tools=[{"type":"google_search"}]` (mesmo padrao "type" plano que OpenAI/Anthropic/xAI ja usam). Corrigido em `provider_client.py` (2.2.0 -> **2.3.0**). Bonus: `native_web_search()` nunca tinha tido testes dedicados desde que foi criado (parte 12) -- 8 testes novos cobrindo os 5 provedores, incluindo regressao explicita pro bug do Gemini.

### Confirmado correto, sem mudanca necessaria
- Todos os modelos ativos do registry (GPT-5.6 Sol/Terra/Luna, Claude Fable-5/Sonnet-5/Opus-4.8/Haiku-4.5, Gemini 3.5-flash + 3.1-pro-preview, Grok 4.5/4.3, kimi-k2.7-code/kimi-k2.6/deepseek-v4-flash) -- nenhum modelo mais novo lancado que exija troca.
- `claude-fable-5` (nome que parecia estranho) confirmado real, nao alucinacao -- GA desde 9/jun/2026.
- `web_search_20260318` (Anthropic) confirmado como a versao MAIS ATUAL do tool (havia uma ambiguidade no relatorio do subagente sugerindo "upgrade necessario" que na verdade era so texto confuso -- verifiquei o codigo direto, ja estavamos na versao certa).
- `output_config.format.type=json_schema` (Anthropic) confirmado GA de verdade (nao beta) -- uma fonte generica dizia o contrario, mas era conhecimento desatualizado nao refletindo essa funcionalidade mais nova.
- Estrutura de request/response da Interactions API do Gemini (exceto o campo "input", ver abaixo) confirmada correta.
- Endpoint `/api/web_search` do Ollama Cloud confirmado campo-por-campo contra a doc oficial (query/max_results -> results com title/url/content).
- Endpoint/auth/formato do xAI confirmados 100% identicos ao padrao OpenAI (Responses API compartilhada de verdade, nao so "compativel por acaso").

### Risco sinalizado, NAO corrigido (Gemini nao e testavel ao vivo nesta sessao)
O campo `"input"` de `_chat_gemini()`/`native_web_search()` usa formato `role`+`parts` (o formato do generateContent LEGADO). A doc da Interactions API mostra `input` como string simples ou lista de content items tipados -- sem nenhum exemplo explicito confirmando que `role`+`parts` funciona como alias. Pode estar certo (aceito por compatibilidade) ou pode estar sendo mal interpretado/rejeitado -- documentado como risco conhecido em vez de mudar as cegas sem conseguir testar.

### Tensao real encontrada (nao corrigida -- decisao de Felipe prevalece)
O subagente de padroes agenticos apontou algo relevante: a decisao "checkpoint nunca pausa o pipeline" (parte 15, pedido explicito de Felipe) diverge da recomendacao 2026 de manter aprovacao previa especificamente em acoes IRREVERSIVEIS ou EXTERNAS (empacotar o addon final, sobrescrever arquivo existente) mesmo quando autonomia total e correta pra steps internos/reversiveis (rascunho de codigo, docs, testes). Reportado a Felipe pra ele decidir -- nao revertido unilateralmente, ja que foi um pedido direto e explicito dele.

### Outros achados de tensao/nuance (informativos, sem acao)
- Cross-model escalation (parte 7) confirmado como pratica preferida sobre so aumentar reasoning effort no mesmo modelo -- mas a pesquisa sugere um hibrido (escalar effort primeiro, so trocar de modelo depois) que o NVDAStudio nao faz hoje (vai direto pra diversificacao).
- Narracao via chamada de IA dedicada (parte 14) confirmada como padrao real de producao em 2026, nao uma abordagem incomum -- riscos conhecidos: latencia extra e possibilidade de dessincronia com o trabalho real.
- xAI: `reasoning.effort` tem default "high" (nao "medium" como OpenAI) -- vale conferir se o codigo sempre passa o valor explicitamente.
- Ollama: kimi-k2.7-code tem ~30% MENOS uso de tokens de thinking que k2.6 -- diferenca de comportamento real, nao so "mesma coisa, modelo melhor".

### Funcionalidades nativas nao usadas (oportunidades, nao gaps) por provedor
OpenAI: Programmatic Tool Calling, Code Interpreter hospedado, Computer Use, Skills API, conectores MCP, context compaction nativa.
Anthropic: code execution tool, memory tool, Files API, context editing/compaction (beta).
Gemini: thought signatures + `previous_interaction_id` (modo stateful, evita reenviar historico completo), code execution, Maps grounding, Managed Agent sandbox.
xAI: X Search (ferramenta separada do web_search geral), code_interpreter, filtros de dominio no web_search, Grok Build (modelo dedicado a coding agentico).
Ollama: endpoint irmao `/api/web_fetch` (busca conteudo completo de uma URL especifica).

### Testes e validacao
8 testes novos em `test_provider_client.py` (`native_web_search` pros 5 provedores + query vazia + excecao engolida). Suite completa em background apos este round.

---

## Sessao Atual (2026-07-20) — parte 15: checkpoint nunca mais para o pipeline + classificador tambem narra

### Contexto (parte A: checkpoint autonomo)
Depois da explicacao do fluxo completo em linguagem simples, Felipe reagiu a uma frase especifica: "outra IA classifica a intencao (continuar/pausar/refazer)". Ele foi direto: "essa parte ele nao deve parar e perguntar, o pipeline nao deve parar, ele deve continuar sozinho, entendeu?"

### O que existia
`checkpoint_manager.ask_checkpoint()` era chamado pelo orchestrator apos CADA step de `code_generation`/`assembly`/`agent_runner`/`manifest_builder` (varios por build tipico). `_on_checkpoint_interactive`/`_on_conversational_checkpoint` em studio_dialog.py delegavam pra `_ask_checkpoint_inline()`, que BLOQUEAVA a thread de execucao com `threading.Event.wait()` ate o usuario digitar uma resposta livre, que entao era classificada por IA (continue/pause/redo). Ou seja: o pipeline literalmente parava, varias vezes por build, esperando o usuario.

### Fix
`studio_dialog.py` (5.34.0 -> **5.35.0**):
- `_ask_checkpoint_inline()` removido por completo (o `checkpoint_manager.ask_checkpoint()` ja tinha fallback nativo pra "sem callback = CONTINUE automatico" -- so precisava parar de registrar um callback bloqueante).
- `_on_checkpoint_interactive`/`_on_conversational_checkpoint` agora chamam `_report_checkpoint_inline()` (metodo novo: so escreve no historico via `_chat_append`, sem bloquear) e retornam CONTINUE/True sempre, incondicionalmente.
- Removidos os 4 campos de estado do fluxo bloqueante (`_waiting_for_checkpoint_approval`, `_checkpoint_approval_event`, `_checkpoint_approval_result`, `_raw_checkpoint_approval_input`) e o branch morto correspondente no roteador de input do chat (`_on_run`).
- REDO e PAUSE via checkpoint deixam de ser possiveis nesse ponto (a IA nunca mais escolhe isso aqui, ja que ninguem pergunta) -- se Felipe quiser retomar controle manual sobre pausar/refazer no futuro, precisaria de um mecanismo diferente (ex: um botao explicito "Pausar" na UI, nao um checkpoint automatico pos-step).

### Contexto (parte B: classificador tambem narrando)
Felipe perguntou: "quando o classificador ta trabalhando, ele e bem conversacional tambem na interface?" -- resposta honesta: nao, mostrava e falava automaticamente o texto fixo "Processando resposta." (nao gerado pela IA, sem passar pelo narrate()).

### Fix
3 pontos em `_on_run` (aprovacao de plano, decisao de empacotamento, esclarecimento) trocaram `ui.message("Processando resposta...")` por `narrate("interpretando a resposta sobre X")` -- vai pro historico, gerado pela IA, nunca falado, consistente com o resto do app desde a v5.31.0.

### Confirmacao de zero jargao tecnico (pergunta separada de Felipe)
Confirmado e documentado: `_NARRATE_SYSTEM` (parte 14) instrui explicitamente "nunca use jargao tecnico, nomes internos de funcao/classe/step_type" e "nunca use Markdown" -- e os textos de entrada que os 10 sub-agentes passam pra narrate() ja nascem em portugues simples, sem nomes internos.

### Testes
`TestCheckpointNuncaParaOPipeline` (6 testes) + `TestClassificadorDeIntencaoNarraNaInterface` (2 testes).

### Validacao
Suite completa em background apos este round. Nota a parte: uma rodada anterior desta mesma sessao mostrou 2 falhas intermitentes em `test_web_search_temporal_learning.py` (rede real tentada via `memory_relevance.py`) que so reproduziam quando `tests/unit` + `tests/integration` rodavam juntos com ordem nao-deterministica -- reconfirmado limpo rodando com `-p no:randomly`; e uma fragilidade de isolamento de teste pre-existente, nao um bug de producao, nao investigada a fundo por estar fora do escopo pedido.

---

## Sessao Atual (2026-07-20) — parte 14: narracao granular em tempo real (rotulos de status virando dinamicos/IA)

### Contexto
Felipe pediu pra descrever o fluxo do usuario do inicio ao fim, em linguagem simples, pra conferir se estava do jeito que ele queria. Na resposta, sinalizei um ponto de transparencia: o CONTEUDO conversacional (plano, perguntas, confirmacoes) e 100% gerado pela IA, mas os ROTULOS da barra de status ("Pesquisando", "Planejando"...) eram um dicionario fixo no codigo, nao gerados pela IA a cada vez. Felipe respondeu que quer TUDO dinamico/gerado pela IA -- deu uma lista detalhada de exemplos ("pensando", "pesquisando na web", "navegando em X", "encontrei os resultados X, a versao e Y", "executando codigo X", "vejo que X", "eu acho que X, vou perguntar ao usuario Y", "pronto, terminei X", "agora vou editar os arquivos X para Y"), sempre conversacional, nunca deixando o usuario "na mao". Regras explicitas: nunca falado pelo NVDA (so lido no historico com as setas), nunca repetido, historico nunca trunca mesmo grande, tempo real (mensagem nunca "por cima" da execucao -- nao pode bloquear o trabalho real). Ele conectou isso diretamente ao motivo de ter pedido tantas pesquisas na web nos provedores: queria confirmar o que cada um suporta nativamente pra esse fluxo funcionar de verdade.

### Pesquisa web -- thinking/reasoning nativo dos 5 provedores (2026)
Confirmado que TODOS os 5 tem streaming de raciocinio nativo:
- OpenAI (Responses API): eventos `response.reasoning_summary_text.delta`.
- Anthropic (Messages API, extended thinking): eventos `thinking_delta`.
- Gemini (Interactions API): "thought steps" no array de steps, streamable.
- xAI (Grok 4.5+): campo `reasoning_content` em streaming.
- Ollama Cloud: campo `thinking` separado em streaming (ja parcialmente capturado no `ollama_client.py` desde antes desta sessao).

### Decisao de arquitetura (perguntada, nao presumida)
Duas formas possiveis de implementar a narracao ao vivo:
1. Usar o thinking/reasoning NATIVO de cada provedor (sem custo extra de chamadas de IA, streaming de verdade) -- risco: e o raciocinio BRUTO do modelo, tecnico, sem garantia de estar em portugues natural/conversacional (o "estilo" pedido por Felipe).
2. Narracao DEDICADA: a cada acao real (pesquisar, gerar codigo, editar arquivo), uma chamada de IA curta e barata gera 1 frase natural descrevendo o que esta acontecendo -- garante 100% o estilo pedido, mas custa chamadas extras de IA e nao e o raciocinio real do modelo.

Perguntei explicitamente a Felipe. Ele escolheu a **opcao 2 (narracao dedicada)**.

### Implementado
- `sub_agents/_base.py` (docstring 1.8.0 -> **1.9.0**): `narrate(action_desc)` novo -- dispara 1 chamada de IA curta (modelo LEVE do provedor ativo, via `resolve_provider_tier_model(provider, "light")`) em thread separada (fire-and-forget, nao bloqueia a tarefa real -- satisfaz "nunca por cima da execucao"), que reescreve a descricao tecnica da acao numa frase natural (system prompt `_NARRATE_SYSTEM`: 1a pessoa, max 100 chars, sem jargao/Markdown/emoji) e emite via `conversation.emit_status()`. Corpo real extraido pra `_narrate_work()` (testavel diretamente, bypassando o guard de teste). Guard: silenciosa sob pytest/unittest (sem chamada de rede nem thread solta na suite).
- **Por que reaproveitar `conversation.emit_status()` em vez de criar um canal novo**: ja satisfaz TODOS os requisitos sem plumbing novo -- vai pro historico (`_chat_append`), nao fala mais sozinho (fix da parte 10/11 desta sessao), ja tem dedup de linha repetida identica consecutiva, e o `_log` usa `wx.TE_RICH2` (sem limite de 32KB do textctrl padrao, historico nunca trunca).
- `code_generator.py` (3.15.0 -> **3.16.0**): `narrate()` chamado no inicio ("pensando em como estruturar..."), antes de `validate_import` ("verificando se o pacote X existe"), antes/depois de `search_web` ("pesquisando na web sobre X" / "encontrei resultados sobre X"), e ao terminar ("terminei de escrever o codigo, agora vou conferir").
- `web_researcher.py` (4.0.0 -> **4.1.0**): `narrate()` antes da busca ("navegando na web procurando X") e depois ("encontrei resultados sobre X, vou organizar").
- `memory/conversation_manager.py` (2.1.0 -> **2.2.0**): docstrings desatualizadas corrigidas -- ainda diziam "status falado ao vivo" depois da reversao da parte 10/11 desta mesma sessao.

### Escopo desta rodada (transparencia)
Cobri os 2 sub-agentes mais relevantes pro fluxo que Felipe descreveu (geracao de codigo + pesquisa web) -- os outros 11 sub-agentes (manifest_builder, doc_generator, test_generator, accessibility_audit, design_review_agent, etc.) ainda usam so o status de nivel-de-step (`_emit_conversation` via planner) sem narracao granular. Se Felipe quiser o mesmo tratamento nos outros, e uma extensao direta do mesmo padrao (`narrate()` ja existe, so falta chamar nos pontos certos de cada um).

### Testes
`tests/unit/test_narrate.py` novo -- 10 testes: guard de teste (no-op sob pytest), `_narrate_work` chamando o client certo com o modelo leve certo, system prompt correto, resposta vazia nao emite, excecao nao propaga, e confirmacao de que `narrate()` esta de fato conectado em `code_generator.py`/`web_researcher.py`. Fix mecanico: 8 arquivos de teste com `MODULE_VERSION == "3.15.0"` (code_generator.py) hardcoded, corrigidos para "3.16.0".

### Validacao
Suite completa em background apos esta implementacao -- ver journal ou proxima parte pra confirmar numero exato se precisar.

---

## Sessao Atual (2026-07-20) — parte 13: confirmacao de empacotamento nao aparecia + popup modal esquecido

### Contexto
Felipe: "a ia nao avisa quando ele acaba de empacotar, veja isso. por favor."

### Causa raiz
`_run_packaging_process` (inicio) e `_on_package` (sucesso, linha ~1972) so chamavam `ui.message()` -- fala efemera, nunca escrita em `_chat_append`/historico visivel. Isso ja era ruim antes, mas ficou pior depois da parte 10/11 desta mesma sessao: com status/heartbeat parando de falar sozinho por padrao (mudanca que o proprio Felipe pediu), a fala pontual do empacotamento ficou ainda mais facil de passar despercebida, e sem nenhum rastro visivel no historico pra conferir depois.

### Fix
`studio_dialog.py` (5.32.0 -> **5.33.0**):
- `_run_packaging_process`: adiciona `_chat_append("Assistente:\nIniciando o empacotamento do addon.")` antes do `ui.message`.
- `_on_package` (sucesso): adiciona `_chat_append(f"Assistente:\nAddon empacotado com sucesso. Arquivo: {safe_name}.nvda-addon")` antes do `ui.message`.
- **Achado de brinde durante a correcao**: `_show_error` (usado pelos 2 caminhos de erro de empacotamento + 2 de carregar addon) ainda chamava `gui.messageBox()` -- um popup modal que sobrou esquecido depois de toda a limpeza de dialogos modais das partes 4-9 desta sessao (checkpoint, esclarecimento, plano, post-generation -- todos ja tinham virado inline, mas erro ficou pra tras). Corrigido pro mesmo padrao: `_chat_append` + `ui.message`, sem popup.

### Testes
4 testes novos: `test_on_package_escreve_confirmacao_no_historico`, `test_run_packaging_process_escreve_inicio_no_historico`, `TestShowErrorInlineSemPopup` (2 testes: nao usa mais `gui.messageBox`, usa `_chat_append`+`ui.message`).

### Validacao
Suite completa em background apos este fix; resultado ainda nao lido nesta entrada -- ver proxima parte ou o journal se precisar confirmar o numero exato.

---

## Sessao Atual (2026-07-20) — parte 12: pesquisa web passa a ser responsabilidade do provedor

### Contexto
Felipe, direto: "busca na web, quem tem que fazer sao os provedores, entendeu? por isso que mandei voce pesquisar na web, e implementar tudo o que cada provedor espera, para a ia funcionar corretamente." Reacao ao bug real que eu tinha sinalizado como task separada na parte 9 (`No module named 'secrets'` quebrando toda busca DuckDuckGo via `ddgs`) -- ele nao queria que eu so corrigisse o erro, queria que eu trocasse a abordagem inteira: o NVDAStudio nao deveria manter seu proprio scraper, deveria usar a pesquisa nativa que cada um dos 5 provedores ja oferece.

### Pesquisa web (2026)
Confirmado que todos os 5 provedores tem busca nativa server-side:
- OpenAI (Responses API): `tools=[{"type":"web_search"}]`.
- xAI (Grok, mesmo endpoint /v1/responses OpenAI-compativel): `tools=[{"type":"web_search"}]` -- a Live Search antiga (`search_parameters`) foi desativada em 12/01/2026 (410 Gone), migrada pra essa Agent Tools API.
- Anthropic (Messages API): `tools=[{"type":"web_search_20260318","name":"web_search"}]`, server tool (roda na infra da Anthropic).
- Gemini (Interactions API): `tools=[{"google_search":{}}]`, grounding -- nao verificado ao vivo contra a Interactions API especificamente (Beta; Google recomenda generateContent pra producao estavel), so contra o padrao geral do Gemini.
- Ollama Cloud: endpoint REST dedicado `https://ollama.com/api/web_search` (fonte: docs.ollama.com/capabilities/web-search), mesma chave Bearer do `/api/chat` -- **unico caminho testavel ao vivo por Felipe**.

### Implementado
- `provider_client.py` (2.1.0 -> **2.2.0**): `native_web_search()` novo -- injeta o server tool nativo certo por provedor numa chamada isolada (fora de `self._history`), 3 helpers privados (`_native_web_search_openai_compatible`, `_native_web_search_anthropic`, `_native_web_search_gemini`).
- `ollama_client.py` (2.8.0 -> **2.9.0**): `web_search()` novo -- POST em `https://ollama.com/api/web_search`.
- `web_researcher.py` (3.0.0 -> **4.0.0**): `on_demand_web_search()` reescrito -- cria o client do provedor ATIVO via `create_llm_client()` (a mesma factory usada no resto do pipeline) e chama `.web_search()` (Ollama) ou `.native_web_search()` (demais), em vez de importar `ddgs` diretamente.
- **Removido por completo**: `ddgs` sai de `requirements.txt`; pacote vendorizado apagado (`lib/ddgs/`, `lib/ddgs-9.14.4.dist-info/`, `lib/bin/ddgs.exe`).
- **Achado de brinde**: `tools/web_search_tool.py` era um SEGUNDO scraper `ddgs`, totalmente orfao (zero import real, so um comentario com o nome em `orchestrator.py`) -- removido junto, sem relacao direta com o pedido mas no mesmo escopo de "codigo que nao presta mais".

### Validacao
`test_web_researcher_on_demand.py` reescrito (a suite antiga mockava DDGS diretamente, agora mocka o client retornado por `create_llm_client` e verifica que `.web_search()`/`.native_web_search()` sao chamados). Suite completa: **1787 passaram, 0 falhas, 6 skip**.

### Nao verificado ao vivo (transparencia)
`native_web_search()` para OpenAI/Anthropic/Gemini/xAI e implementado per doc oficial mas nunca rodou contra a API real nesta sessao -- so o path Ollama (`web_search()`) e validavel por Felipe agora. Se algum dos 4 provedores mudar o nome do tool block antes do proximo teste ao vivo com aquela chave, vai precisar de ajuste.

---

## Sessao Atual (2026-07-20) — parte 11: bug real da "janela que some" -- historico sendo apagado

### Contexto
Felipe corrigiu minha leitura da parte 10: nao era sobre a pergunta "digite sua resposta" em si, e sim que TODO o historico da conversa (a troca de esclarecimento antes do pipeline comecar) sumia quando o pipeline disparava. Frase-chave dele: "quem deve cuidar de todo pipeline, planejamento, e a ia" -- o fluxo deveria ser continuo, sem a IA "resetar a tela" no meio do caminho.

### Causa raiz encontrada
`grep` por `_log.SetValue` em `studio_dialog.py` achou 4 ocorrencias. 3 sao legitimas: `_load_addon_context` (troca de contexto ao carregar outro addon), `_on_reset` (botao Reset explicito). As outras 2 eram o bug: `_trigger_creation_pipeline` e `_trigger_iterative_pipeline` (as duas funcoes que efetivamente iniciam o pipeline, chamadas logo apos a troca de esclarecimento com o usuario) chamavam `self._log.SetValue("")` no inicio -- apagando toda a conversa que tinha acabado de acontecer. Isso confirma e explica retroativamente a hipotese "outra janela" da parte 10: o conteudo inteiro sumindo e recomecando do zero (pesquisando/planejando do zero, sem o historico da conversa anterior) parece exatamente uma janela nova, mesmo sendo tecnicamente a mesma `NVDAStudioDialog`.

### Fix
Removidas as 2 chamadas `self._log.SetValue("")` de `_trigger_creation_pipeline`/`_trigger_iterative_pipeline` (`studio_dialog.py` 5.31.0 -> **5.32.0**). O historico agora e uma unica transcricao continua do inicio ao fim da sessao -- so o Reset explicito do usuario (`_on_reset`) continua limpando de proposito. 3 testes de regressao novos em `TestPipelineNaoApagaHistoricoAoIniciar` (garantem que as 2 funcoes nao voltam a limpar o log, e que o Reset continua limpando).

### Validacao
`test_studio_dialog.py` + `test_conversational_mode.py` + `test_questionario_comportamento.py`: 166 testes, 0 falhas. Suite completa em background pra confirmar 0 falhas no total antes do rebuild final.

---

## Sessao Atual (2026-07-20) — parte 10: live-test real + fim da narracao automatica de status

### Contexto
Primeiro live-test de verdade da build desta sessao: Felipe pediu um GlobalPlugin "geminiChat" (painel de config nas Preferencias do NVDA, servidor HTTP local numa thread separada, chat com Gemini via navegador). Confirmado pelos logs reais (`%APPDATA%\nvda\nvdastudio_logs\`) que o fluxo CONVERSA -> PESQUISA -> PLANO (15:50:02) -> PLAN_APPROVAL (15:51:01) -> EXECUTING (15:52:29) rodou de ponta a ponta na build nova (orchestrator v5.11.0, ollama_client v2.8.0, kimi-k2.7-code/deepseek-v4-flash).

### "Segunda janela" do plano -- nao confirmado
Felipe reportou que depois do plano pronto aparece "outra janela" pedindo resposta. Auditoria de codigo (grep de toda classe wx.Dialog/wx.Frame no pacote) confirma que so existem 3 dialogs reais: `NVDAStudioDialog` (janela principal, singleton verificado em `__init__.py._open_dialog`), `FirstRunSetupDialog` (so aparece ANTES da janela principal, se falta API key -- nao bate com o timing descrito), e `MeuDialog` (so existe dentro de um template de codigo-fonte gerado, nao e codigo real do NVDAStudio). A aprovacao do plano (`_on_conversational_plan_ready`) e 100% inline na mesma `NVDAStudioDialog` -- muda o rotulo do campo de input e popula `self._code_view` (um `wx.TextCtrl` dentro do mesmo sizer), nao abre nenhuma janela nova. Perguntei a Felipe pra descrever exatamente o que ele via (mesma janela mudando de conteudo vs. segundo item na barra de tarefas vs. substituicao de uma janela por outra) -- ele descartou a pergunta sem responder. Fica em aberto: se o comportamento persistir, meu proximo passo seria pedir uma captura de tela ou o Alt+Tab durante o momento exato, ja que o codigo nao sustenta a hipotese de janela duplicada.

### Fim da narracao automatica de status (mudanca de comportamento padrao)
Felipe reportou que o NVDA "fala sozinho demais" -- toda troca de status, todo heartbeat, toda mudanca de fase disparava fala automatica. Perguntei explicitamente se era so incomodo dele testando visualmente (vidente lendo a tela) ou se deveria virar o padrao pra todo mundo, mesmo usuario cego real do NVDAStudio -- ele confirmou: **padrao pra todo mundo**, sem excecao. Isso reverte parte do que foi adicionado na parte 3 desta mesma sessao (unificacao de canais status/heartbeat, v5.28.0), que tinha feito status e heartbeat falarem ao vivo de proposito como requisito de acessibilidade.

Mudanca aplicada em `studio_dialog.py` (5.30.0 -> **5.31.0**):
- `_handle_status`: para de chamar `_speak_message()`. Continua escrevendo no historico (`_chat_append`) e na barra de status (`_set_status`).
- `_handle_tool_progress` (heartbeat periodico): para de chamar `_speak_message()`. So atualiza a barra de status.
- `_handle_conversational_phase`: para de chamar `ui.message()` na troca de fase (Pesquisando/Planejando/Implementando/etc.).

Mantido de proposito (categoricamente diferente de status ambiente -- sinalizam que uma ACAO do usuario e esperada): perguntas de esclarecimento (`_ask_clarification_inline`), convite de aprovacao do plano, perguntas de checkpoint (`_ask_checkpoint_inline`), resposta do chat rapido (`_chat_finish`), mensagens finais de conclusao/erro/cancelamento. Sem esses, o usuario (cego ou nao) nao teria nenhum sinal de que uma resposta e esperada.

### Bugs de teste corrigidos (achados investigando as 3 falhas da parte 9)
Durante a investigacao aprofundada pedida por Felipe ("o que sao essas 3 falhas, tem como corrigir?"), todas as 3 se revelaram bugs no PROPRIO TESTE, nao no codigo:
1. `test_clarify_nao_bloqueante_nao_chama_llm`: mockava `orchestrator.dispatch_step`, simbolo que nao existe mais (virou `dispatch_step_with_tokens` num refactor anterior a esta sessao, pra rastrear tokens). Corrigido o alvo do mock.
2. `test_addon_name_required_no_schema` e `test_campos_step_tem_description`: ambos cortam o codigo-fonte de `planner.py` numa janela fixa de 6000 chars pra achar o `_PLAN_SCHEMA`. O schema real tem 7411 chars (cresceu porque a descricao de `requires_web_research` foi bem expandida nesta sessao, parte 8), entao o `"required"` da raiz e o campo `depends_on` ficavam fora da janela -- os testes verificavam string vazia/cortada, nunca o schema de verdade (que sempre esteve correto). Corrigido: janela ampliada de 6000 -> 9000 chars nos dois arquivos.

Suite completa apos as 2 rodadas de fix: **1786 testes coletados, 1780 passaram, 0 falhas, 6 skip** (as 3 falhas anteriores nao existem mais).

### Bug real encontrado nos logs (fora do escopo desta rodada, sinalizado)
Log real mostra toda busca DuckDuckGo falhando com `No module named 'secrets'` (modulo stdlib do Python) durante `web_researcher.py` -- a pesquisa web cai silenciosamente pro fallback (so LLM). Sinalizado como task separada (`task_ea0ee99d`) em vez de investigado agora, por estar fora do pedido explicito desta rodada.

### Limpeza + rebuild
`scripts/clean_runtime_artifacts.ps1` rodado antes do build (remove `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.coverage`, logs antigos em `logs/` e `%APPDATA%\nvda\nvdastudio_logs`). `python build.py` reexecutado apos as correcoes de teste e a mudanca de comportamento de fala -- `.nvda-addon` entregue pronto pra reteste real.

---

## Sessao Atual (2026-07-20) — parte 9: limpeza de orfaos + freshness de modelo + verificacao de loop de agente

### Contexto
Felipe pediu: remover codigo e coisa orfa do projeto; modelos de IA e tudo mais tem que ser o mais recente possivel (2026); o que nao faz mais parte do projeto pode ser deletado pra manter o projeto limpo. Depois pediu tambem pesquisa web sobre loops de agente pros 5 provedores, e um relatorio se o NVDAStudio melhorou e se ja da pra criar addons.

### Auditoria de orfaos (agente Explore)
Removido de verdade — zero referencia real, producao ou teste:
- `Orchestrator._build_retry_query()` (orchestrator.py) — resquicio de antes do `AgenticLoop.run()` substituir o antigo loop autonomo manual.
- `NVDAStudioDialog._action_salvar` / `_finalizar_salvar` / `_on_save` (studio_dialog.py) — grep de todos os `.Bind(wx.EVT_BUTTON, ...)` confirmou que nenhum botao aciona `_on_save`; `_action_salvar` so era chamado por esse metodo morto. `_on_package` (chamado programaticamente pelo fluxo inline "ajustar ou empacotar?") ja cobre salvar+empacotar sozinho. O changelog da v5.29.0 tinha documentado ERRADO que `_on_save` era "o caminho real" — corrigido nesta rodada.
- Imports orfaos de `generate_quality_report`/`export_addon_zip` removidos do topo de studio_dialog.py (as funcoes continuam definidas e testadas em addon_builder.py).

Mantido de proposito (nao e orfao real — sao aliases com cobertura de teste dedicada, mesmo precedente ja usado pra `generate_store_submission`/`get_blocking_structural_issues` em addon_builder.py):
- `Orchestrator._compute_progress` / `_ESCALATION_REASONING` (alias de `_ESCALATION_REASONING_BY_TYPE`).
- `Planner.STEP_MODEL_MAP` / `STEP_MODEL_MAP_MEDIUM` — o proprio `COMPLEXITY_MAP` ja tem comentario dizendo "mantido como alias retrocompativel pra testes legados, a LLM decide o roteamento em producao".
- `addon_builder.validate_manifest` / `validate_python_structure`.
Remover qualquer um desses exigiria reescrever ou apagar testes espalhados em 20+ arquivos, por codigo que nao causa dano nenhum ficando — decisao: manter.

### Freshness de modelo
Bulk-replace de todas as ~46 ocorrencias remanescentes de `"kimi-k2.6"` em `planner.py` (`_STEP_FALLBACK_MODEL`, 13 step types, e `COMPLEXITY_MAP`, 33 ocorrencias entre tiers low/medium/high) para `"kimi-k2.7-code"`. `kimi-k2.6` so continua existindo em `model_registry.py` como fallback ATIVO dentro de `_FALLBACK_CHAINS["ollama"]` — nunca mais como default solto em nenhum outro modulo.

### Pesquisa web — loops de agente 2026 (todos os 5 provedores)
- **OpenAI/xAI (Responses API)**: agentic loop e "primeira classe" da API; dois jeitos validos de manter contexto — reconstruir o historico a cada chamada (dono do loop) OU `previous_response_id` + `store:true` (estado no servidor). NVDAStudio usa o primeiro (`_build_responses_input()` em `provider_client.py`), que e mais portavel quando o orchestrator troca de modelo entre retries/replans — nao e um gap, e escolha deliberada.
- **Anthropic (Messages API)**: loop correto e checar `stop_reason` (`tool_use` = continua, `end_turn` = para). `provider_client.py` normaliza isso via lista `tool_calls` no `LLMResponse` (populada quando ha blocos `tool_use`) — equivalente semantico, provider-agnostico.
- **Gemini (Interactions API, GA desde jun/2026)**: modelo de steps tipados (`function_call`, `tool_call`, etc.) — `provider_client.py` ja parseia `function_call` corretamente (migrado na parte 6).
- **xAI (Grok)**: formato OpenAI-compativel de `tool_call` — mesmo parser de `_build_responses_input()` cobre OpenAI e xAI.
- **Ollama Cloud**: modelo nao executa a tool sozinho; cliente le `tool_calls`, roda a funcao, devolve como mensagem `tool` na proxima chamada `chat` — e exatamente o que `ollama_client.py`/`code_generator.py` fazem.
Conclusao: a abstracao unificada de `provider_client.py` (campo `tool_calls` normalizado, independente do formato nativo do provedor) ja cobre corretamente o padrao de loop de 2026 pros 5 provedores. `code_generator.py` usa `max_tool_rounds=3` com apenas 2 tools (`validate_import`, `search_web`) — escopo estreito e intencional, nao precisa dos 10-15 turnos recomendados pra agentes SDK abertos de proposito geral.

### Testes e validacao
Sem novos testes de comportamento (mudanca e remocao de codigo morto + troca de string de modelo). Fixes mecanicos: ~17 arquivos de teste com assert `MODULE_VERSION == "X.Y.Z"` hardcoded ajustados para as novas versoes (planner.py 2.11.0, orchestrator.py 5.11.0, studio_dialog.py 5.30.0) e para `kimi-k2.7-code` onde o teste comparava o nome do modelo literal. Suite completa (`tests/unit` + `tests/integration`, exclui e2e que precisa de Ollama real): **1777 passaram, 3 falharam (as mesmas 3 pre-existentes de sempre, nao relacionadas), 6 skip** — 1786 testes coletados no total.

### Build
`python build.py` re-executado — `.nvda-addon` reconstruido com todas as mudancas desta parte 9 (e das partes 1-8 anteriores) prontas pra teste real no NVDA.

---

## Sessao Atual (2026-07-20) — parte 8: cobertura de funcionalidades nativas dos provedores

### Contexto
Felipe perguntou: alem de saber quando pesquisar pra provedor DESCONHECIDO, o sistema tambem sabe quando pesquisar pra provedor CONHECIDO (se o pedido for alem do chat basico)? Todas as funcionalidades nativas (IA conversacional, etc.) estao cobertas?

### Pesquisa
Confirmou catalogo nativo bem maior que o chat basico documentado na parte 6, pra cada um dos 5 provedores:
- OpenAI (Responses API): streaming, tool/function calling, visao (texto+imagem), saida estruturada, built-in tools (web_search, file_search, code_interpreter, image_generation, computer_use, MCP remoto), reasoning summaries, stateful via previous_response_id.
- Anthropic (Messages API): streaming (deltas de texto/tool/thinking), tool use, visao (JPEG/PNG/GIF/WebP), extended thinking (com streaming proprio), prompt caching (cache_control ephemeral, 10% do custo).
- Gemini (Interactions API): streaming, server-side state (previous_interaction_id), execucao em background, multimodal (imagem/PDF/CSV/video), tool calling multimodal, built-in tools (Google Search, Maps), steps observaveis (thinking), Live API separada pra voz/visao em tempo real.
- xAI (Grok): streaming, tool calling nativo (web search, X search, execucao de codigo), visao, Live Search dedicado (X Search com busca semantica/keyword/usuario), modos reasoning/non-reasoning.
- Ollama Cloud: streaming com tool calling (parser incremental, mais maduro do que a pesquisa anterior indicava), visao (modelos multimodais), structured output (JSON schema), thinking (toggle on/off, campo separado no streaming), embeddings (modelos dedicados).

### Decisao de design
Documentar TODAS essas funcionalidades em detalhe no prompt incharia o `nvda_context.py` e ficaria desatualizado rapido (sintaxe de tool calling, visao etc. muda mais que o endpoint basico). Em vez disso: `nvda_context.py` 3.23.0 -> **3.24.0** -- adicionado paragrafo final na secao 4 listando os NOMES das funcionalidades avancadas (sem sintaxe detalhada) e instruindo explicitamente: se o pedido precisar de qualquer uma delas, marcar `requires_web_research=true` MESMO que o provedor esteja entre os 5 conhecidos. So pula pesquisa quando for realmente so chat de texto simples.

### Testes
3 testes novos em `test_nvda_context.py`: confirma 2+ ocorrencias do gatilho de pesquisa (provedor desconhecido + funcionalidade avancada), confirma que os termos das funcionalidades avancadas sao mencionados por nome. 1 bug de wrap de texto corrigido durante a implementacao (frase "cache de prompt" quebrada por uma quebra de linha no meio, fazendo um assert de substring falhar -- ajustado o wrap do paragrafo).

### Validacao
Suite completa: **1777 passaram, 3 falharam (mesmas pre-existentes de sempre), 6 skip**. 2077 testes coletados no total.

---

## Sessao Atual (2026-07-20) — parte 7: cross-model escalation de verdade (model_map)

### Contexto
Felipe cobrou o achado da parte 5 ("pra voce decidir se vale a pena implementar de verdade" sobre `Planner.replan(model_map=...)`) e pediu pra pesquisar de novo antes de decidir, reforcando que o NVDAStudio precisa ser "super inteligente" pra criar addons de qualquer complexidade.

### Pesquisa
Web search confirmou "cross-model escalation" como pratica validada em 2026 para sistemas agenticos de codigo: apos um worker esgotar retries no mesmo modelo, escalar para um modelo de uma familia/fundacao DIFERENTE tem taxa de sucesso maior, porque modelos diferentes tem modos de falha complementares (um erro que trava um modelo geralmente esta fora da distribuicao de falhas de outro). Isso valida implementar o `model_map` de verdade, nao so documentar como achado.

### 2 bugs encadeados corrigidos (o que tornava model_map um no-op)
1. `Planner.replan()` computava `mapa = model_map or STEP_MODEL_MAP` mas nunca repassava pra `_build_steps()`.
2. Mesmo corrigindo (1), `apply_model_budget()` (chamado logo depois) reescrevia `step.model_id` de TODOS os steps incondicionalmente (orcamento heavy/light 20%/80%) -- qualquer override anterior seria apagado de qualquer forma.

### Implementacao
- `planner.py` 2.9.0 -> **2.10.0**: `_build_steps(model_overrides=...)` novo parametro (vence a resolucao dinamica normal para o step_type presente no dict); `apply_model_budget(preserve_step_types=...)` novo parametro (nao sobrescreve os step_types ja no override); `replan()` agora passa os dois de verdade.
- `orchestrator.py` 5.9.0 -> **5.10.0**: novo `_diversify_failed_models(failed_level)` -- para cada step critico (code_generation/agent_runner) que chegou ao replan (ja esgotou retry + escalacao), usa `model_registry.get_fallback_chain(modelo_que_falhou)` pra pegar o PROXIMO modelo da cadeia (kimi-k2.7-code falhou -> tenta kimi-k2.6; kimi-k2.6 falhou -> tenta deepseek-v4-flash) em vez de repetir o mesmo modelo pela 3a vez. `_do_replan` passa isso como `model_map` pro planner.
- 12 testes novos (`test_planner.py`: `_build_steps`/`apply_model_budget` isolados; `test_orchestrator_replan.py`: `TestDiversifyFailedModels` + `_do_replan` repassando o map) + o teste antigo que documentava o no-op corrigido pra afirmar o comportamento real agora.

### Bonus: confirmado que arquitetura de software geral (nao so regras NVDA) ja e coberta
Checagem rapida em `design_review_agent.py` confirmou: pra addons `complexity=high`, ja existe uma revisao de 6 estagios (Understanding Lock, Challenger, Constraint Guardian, User Advocate, Quality, Decision) que inclui SRP, coesao, acoplamento e naming conventions — nao e so checklist de regras NVDA. Nao precisou de mudanca.

### Validacao
Suite completa: **1775 passaram, 3 falharam (mesmas pre-existentes de sempre), 6 skip**. 2075 testes coletados no total.

---

## Sessao Atual (2026-07-20) — parte 6: conhecimento de provedores embutido nos addons gerados

### Contexto
Felipe explicou o objetivo final de toda a rodada de pesquisas: nao basta o NVDAStudio EM SI falar com os provedores de forma atualizada (parte 4/5) -- os ADDONS QUE ELE GERA tambem precisam, quando o pedido envolve integrar com IA/LLM. Sem isso, o `code_generator.py` fica na mao do conhecimento de treinamento do modelo (que pode estar desatualizado, ex: Chat Completions da OpenAI) ou de pesquisa web que o Planner as vezes decide pular (caso real: GroqFocusAssistant).

### Fix: `nvda_context.py` 3.22.0 -> 3.23.0
Nova secao "4. INTEGRACAO COM PROVEDORES DE IA/LLM" no bloco de arquitetura (`NVDA_SYSTEM_PROMPT`, entre a secao de SettingsPanel e AppModule -- renumerou ARCH-003/006 de 4/5 para 5/6). Endpoint, header de auth e request minimo para os 5 provedores do painel, usando a MESMA pesquisa ja aplicada em `provider_client.py`/`ollama_client.py`:
- OpenAI/xAI: `/v1/responses` (Responses API, nao Chat Completions)
- Anthropic: `/v1/messages`, `anthropic-version: 2023-06-01`
- Gemini: `/v1/interactions` (Interactions API, nao generateContent)
- Ollama Cloud: `/api/chat`

Instrucao explicita no final: qualquer provedor FORA dessa lista (Groq, ElevenLabs, DeepL, etc.) deve preferir `requires_web_research=true` em vez de o modelo inventar o formato do request -- fecha o ciclo com o fix do planner.py da parte 5 desta sessao.

### 2 bugs reais cometidos e corrigidos na propria implementacao
1. Copiei um travessao ja corrompido (mojibake, bytes `\xc3\xa2\xe2\x82\xac\xe2\x80\x9d`) do texto existente do arquivo pro texto novo -- corrigido substituindo por " - " simples em todo o bloco inserido.
2. `NVDA_SYSTEM_PROMPT` e uma f-string (`f"""..."""`); as chaves `{"model": ...}` dos exemplos JSON foram interpretadas como expressao Python, gerando `SyntaxError: f-string expressions nested too deeply`. Corrigido escapando todo `{`/`}` do bloco novo para `{{`/`}}` (mesmo padrao ja usado em outras partes do arquivo, ex: `__gestures = {{`).

### Testes
7 testes novos em `test_nvda_context.py` (`TestIntegracaoProvedoresIA`) verificando: os 5 provedores mencionados, endpoint correto de cada um (Responses API/Interactions API, nao os antigos), instrucao de pesquisa web para provedor desconhecido, ARCH-002 (thread em background) reforcado na secao.

### Validacao
Suite completa apos essa mudanca: sem regressao (mesmas 3 falhas pre-existentes de sempre). 2065 testes coletados no total.

---

## Sessao Atual (2026-07-20) — parte 5: 4 subagentes em paralelo + fixes aplicados

### Contexto
Felipe pediu pra disparar subagentes pra: (1) reauditar Ollama a fundo, (2) reauditar os 5 provedores de novo (mais fundo, "nada obsoleto, tudo de 2026 pra ca"), (3) responder se o NVDAStudio ja sabe montar addons que integram IA sem precisar pesquisar a web toda vez, (4) avaliar o pipeline inteiro por pontos de falha reais. 4 agentes rodaram em paralelo (general-purpose, background).

### Achados dos 4 agentes (resumo -- detalhe completo nas mensagens da sessao)
1. **Ollama**: quase tudo atual (endpoint /api/chat, formato de tools/tool_results, streaming, kimi-k2.6/deepseek-v4-flash ainda existem). 2 achados: `think` agora aceita niveis (nao implementado, incerto se o Ollama Cloud especificamente suporta -- NAO mexido); existem modelos mais novos (`kimi-k2.7-code`, `deepseek-v4-pro`).
2. **Provedores (2a auditoria)**: confirmou nomes de modelo, endpoints e sintaxe de todos os 5 como corretos para 2026 (inclusive resolveu a duvida do endpoint Gemini: v1 e definitivamente o certo). Unico achado real: falta 529 (Anthropic overloaded) no retry.
3. **Conhecimento embutido vs. pesquisa web**: resposta e NAO -- o sistema nao pesquisa a web por padrao quando o addon integra IA/API externa; confia no conhecimento de treinamento + regras genericas de arquitetura (ARCH-001..006, que valem pra qualquer API, nao so IA). So pesquisa se o Planner decidir `requires_web_research: true`, e no caso real (GroqFocusAssistant) decidiu que nao precisava.
4. **Pontos de falha no pipeline**: achou a causa raiz real do erro "manifest e doc saem, codigo Python nao" visto nos testes -- `code_generator.py` esgotava `max_tool_rounds` (3) com o modelo ainda pedindo tool_calls, ou devolvia conteudo vazio, e isso passava como "codigo" vazio sem virar erro. Tambem achou que erro de sintaxe no retry nao alimentava o proximo prompt.

### Fixes aplicados (aprovados por Felipe: "faca tudo oque for recomendado" + troca de modelo Ollama)
- **`provider_client.py` 2.0.0 -> 2.1.0**: 529 adicionado a `_RETRYABLE_STATUS`.
- **`code_generator.py` 3.14.0 -> 3.15.0**: apos esgotar tool rounds, se `resp.tool_calls` ainda truthy OU `resp.content` vazio, retorna `"[ERRO] ..."` explicito (aciona `_IS_SUBAGENT_ERROR_RE` no orchestrator, que ja tem retry/escalonamento). 3 testes novos (`test_code_generator_tool_rounds_esgotados.py`).
- **`orchestrator.py` 5.8.0 -> 5.9.0**: `syntax_err` agora e `.append()`ado em `last_issues` (antes so ia pro log). Descoberta de brinde: `_ESCALATION_MODEL = "kimi-k2.6"` era constante 100% orfa (nenhuma logica a lia -- o modelo real de escalacao sempre veio de `_get_resilience_model()` dinamico) -- removida. `_FALLBACK_MODEL` e `_PROVIDER_MAX_CONCURRENCY` atualizados para `kimi-k2.7-code`.
- **`planner.py` 2.8.0 -> 2.9.0**: descricao de `requires_web_research` no schema JSON refinada -- continua 100% semantico (IA decide, sem keyword/heuristica), mas agora orienta explicitamente a preferir pesquisar quando houver duvida sobre API/IA externa pouco difundida.
- **`model_registry.py` 1.4.0 -> 1.5.0**: `kimi-k2.7-code` novo tier heavy do Ollama (decisao explicita de Felipe); `kimi-k2.6` continua ACTIVE como fallback (nao quebrado, so nao e mais o padrao).
- **`ollama_client.py` 2.7.0 -> 2.8.0**: `kimi-k2.7-code` adicionado a `_MODEL_CAPABILITIES` (mesmas capacidades do k2.6 ate confirmacao ao vivo) e vira `_DEFAULT_MODEL`. Corrigido tambem um cabecalho de versao ja dessincronizado havia pelo menos uma entrada (dizia 2.6.0, constante real era 2.7.0).
- **~20 testes** com versao de modulo hardcoded corrigidos em lote (sed) apos os bumps acima.

### Achado NAO corrigido (fora do escopo aprovado, documentado)
`Planner.replan(model_map=...)`: o parametro e atribuido a uma variavel local `mapa` e NUNCA repassado pra `_build_steps()` -- e um no-op silencioso. Nenhum caller real (`orchestrator.py`) passa `model_map` hoje, entao nao quebra nada em producao, mas o parametro nao faz o que o nome promete. So foi corrigido o teste que testava esse comportamento quebrado (pra nao mascarar); a funcionalidade em si nao foi implementada -- decisao de produto de Felipe se vale a pena.

### Validacao
Suite completa (unit+integration): **1758 passaram, 3 falharam (mesmas pre-existentes de sempre, confirmadas de novo), 6 skip**. 2058 testes coletados no total.

---

## Sessao Atual (2026-07-20) — parte 4: remocao de dialogos orfaos + migracao de provedores para 2026

### Contexto
Felipe pediu 3 coisas: (1) remover dialogos orfaos do projeto, (2) garantir que nenhuma pergunta/resposta da IA seja pre-escrita/heuristica -- tudo tem que vir da IA, (3) pesquisar fundo a documentacao oficial de cada provedor e alinhar tudo com as praticas de 2026, removendo o que estiver defasado. Escopo aceito: "risco alto, mas ja tem tudo que precisa".

### (1) Dialogos removidos -- studio_dialog.py 5.28.0 -> 5.29.0
- **PostGenerationDialog + `_open_post_generation_dialog` + `_action_instalar`/`_finalizar_instalacao` + `_action_descartar` + `_DiscardConfirmDialog` + `_action_store_submission`/`_finalizar_store`**: achado que TODO esse bloco ja estava 100% orfao -- um comentario no proprio codigo ("Removido PostGenerationDialog por solicitação do usuário", linha perto de `_display_result`) confirmava que o fluxo real ja tinha sido substituido por uma pergunta inline no chat (`_waiting_for_packaging_approval` + `_process_packaging_decision`, so package/modify classificado por IA) numa versao anterior, mas o codigo morto por tras nunca foi apagado. Removido tudo; `_action_salvar`/`_finalizar_salvar` sobrevivem (unico caminho real).
- **ClarificationDialog** (perguntas de esclarecimento pre-pipeline e mid-pipeline): convertido para `_ask_clarification_inline()` -- as perguntas ja vinham da IA (`clarifier.py`), so a moldura do dialogo (wx.Dialog modal com campos de texto por pergunta) foi removida. Agora: perguntas numeradas no historico, resposta livre do usuario, uma IA extrai 1 resposta por pergunta do texto livre (sem parsing posicional/keyword).
- **NVDAStudioStatsDialog** (relatorio de observabilidade): convertido para texto direto no historico via `_on_show_stats` -- dado real sob demanda, nao decisao da IA, mas o usuario pediu "uma janela so" sem excecao.
- Import de `_DiscardConfirmDialog`/`PostGenerationDialog`/`ClarificationDialog`/`NVDAStudioStatsDialog` removidos; imports orfaos `generate_store_submission`/`get_blocking_structural_issues` tambem removidos de `studio_dialog.py` (continuam definidos e testados em `addon_builder.py`, so nao usados mais na UI).
- Testes: removidas ~14 testes que verificavam UI de dialog morto (RadioBox, botoes, etc.), adicionadas ~14 novas cobrindo os metodos inline (`_ask_clarification_inline`, `_on_clarify_needed` delegando, ausencia de `wx.MessageDialog`/`wx.Dialog`). Saldo liquido: 2068 -> 2054 testes.

### (2) Nenhuma pergunta/resposta pronta -- ja estava conforme
Auditoria confirmou: toda classificacao de intencao (aprovacao de plano, checkpoint, esclarecimento, empacotar/modificar) ja usa IA (`create_llm_client` + `response_format=json_object` + prompt "nao decida por palavras isoladas"), nunca keyword/heuristica -- alinhado com a regra global do CLAUDE.md do usuario. So a MOLDURA de texto fixo ao redor de alguns dialogos era hardcoded, resolvido no item (1).

### (3) Provedores migrados para 2026 -- provider_client.py 1.0.0 -> 2.0.0
Pesquisa profunda na doc oficial (WebFetch/WebSearch, nao memoria):
- **Anthropic**: conferido, ja atual (`anthropic-version: 2023-06-01`, `output_config.format.type=json_schema`). Sem mudanca.
- **OpenAI + xAI**: migrados de `/v1/chat/completions` (Chat Completions) para `/v1/responses` (Responses API) -- recomendacao oficial da OpenAI para todo projeto novo desde 2026 ("Chat Completions remains supported, Responses is recommended for all new projects"; achado critico: "a partir do GPT-5.4, tool calling nao e suportado em Chat Completions com reasoning:none" -- risco real ja que o registry lista gpt-5.4+). xAI segue o mesmo padrao (`/v1/responses` e a recomendacao atual la tambem). Mudancas de shape: tools viram flat (type/name/description/parameters no topo, sem aninhar em "function"); mensagens viram "input"; system prompt vira "instructions"; saida estruturada vira `text.format`; `reasoning_effort` vira `reasoning.effort`. Historico de tool-calls precisa reconstruir os itens `function_call` originais + `function_call_output` a cada chamada (a API rejeita output sem o call correspondente no mesmo request) -- implementado em `_build_responses_input()`, coberto por teste de round-trip (`test_openai_native_responses_api_reconstructs_function_call_history`).
- **Gemini**: migrado de `generateContent`/`streamGenerateContent` (v1beta, model no path da URL) para a **Interactions API** (`v1/interactions`, GA desde Junho/2026, model no corpo do request) -- "recomendamos esta API para acesso a todos os recursos e modelos mais recentes". Mesmo shape de turno (role/parts) reaproveitado sob "input" em vez de "contents"; tools ganham o mesmo formato flat da Responses API; resposta usa `output_text` (texto) + `steps` (function_call) em vez de `candidates[0].content.parts`.
- **Ollama**: pesquisado de novo, confirmado que a decisao existente (desativar streaming quando ha tools, por causa da imaturidade do streaming+tool-calling no Ollama) continua correta. Sem mudanca.
- **Fontes**: [Anthropic versioning](https://platform.claude.com/docs/en/api/versioning), [Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [OpenAI migrate to Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses), [Gemini Interactions overview](https://ai.google.dev/gemini-api/docs/interactions-overview), [Gemini migrate to Interactions](https://ai.google.dev/gemini-api/docs/migrate-to-interactions), [xAI tools overview](https://docs.x.ai/developers/tools/overview).

### `model_registry.py` 1.3.0 -> 1.4.0
Modelos superados por geracao mais nova ja presente no proprio registry (nenhum tier/fallback apontava mais pra eles) marcados `DEPRECATED`: `claude-opus-4-7` (-> `claude-opus-4-8`), `claude-sonnet-4-6` (-> `claude-sonnet-5`), `gpt-5.5`/`gpt-5.4`/`gpt-5.4-mini` (-> familia `gpt-5.6-*`), `gemini-2.5-pro`/`gemini-2.5-flash`/`gemini-3-flash-preview` (-> familia `gemini-3.1`/`3.5`).

### Validacao
- Suite completa (unit+integration, sem e2e que batem em API real e levam horas): **1754 passaram, 3 falharam (pre-existentes, confirmadas de novo -- planner.py schema + 1 clarifier test, nenhuma relacionada as mudancas desta sessao), 6 skip**.
- Build (`python build.py`) pendente de rodar apos essa parte -- fazer antes do proximo teste ao vivo do Felipe.

### Risco assumido (documentado, nao verificado ao vivo)
Felipe so consegue testar Ollama Cloud diretamente hoje. A migracao OpenAI/xAI/Gemini foi feita por pesquisa de documentacao oficial (WebFetch de paginas atuais, nao memoria) e validada com testes unitarios que simulam as respostas exatas documentadas, mas **nao foi testada contra as APIs reais** desses 3 provedores. Se Felipe configurar uma chave OpenAI/xAI/Gemini e testar, e algo falhar, o ponto de partida da investigacao e `provider_client.py` `_chat_openai_compatible`/`_chat_gemini`.

---

## Sessao Atual (2026-07-20) — parte 3: UX conversacional/acessibilidade

### Contexto
Felipe reportou 3 problemas de UX ao usar o NVDAStudio de verdade (leitor de tela):
1. Mensagens curtas da IA sao faladas mas somem — nao aparecem no historico ao navegar com as setas.
2. Silencio total durante a fase de execucao (depois do plano aprovado) — nenhuma narracao em tempo real.
3. Diaogos modais separados interrompendo o fluxo (deveria ser tudo numa unica janela).

Pesquisa na web (2026) confirmou: os 5 provedores do projeto (Anthropic, Gemini, xAI, OpenAI-compat, Ollama) ja suportam streaming com eventos de tool-call intercalados ao texto — a expectativa padrao de IA agentica conversacional em 2026 e narrar em tempo real durante a execucao, nao ficar em silencio. Fontes: [Claude streaming](https://platform.claude.com/docs/en/build-with-claude/streaming), [Gemini streaming](https://ai.google.dev/gemini-api/docs/streaming), [xAI function calling](https://docs.x.ai/developers/tools/function-calling), [Ollama streaming tool calls](https://ollama.com/blog/streaming-tool).

### Diagnostico (achado lendo o codigo, nao assumido)
- `conversation_manager.py` + `studio_dialog.py` tinham 3 canais desconectados: `emit_status`→`_handle_status` so falava (nunca ia pro `self._log`, o historico navegavel); `emit_tool_progress`→`_handle_tool_progress` so atualizava uma barra de status muda (nao falava nada); `emit_content`→`_handle_content` so ia pro historico (nao falava).
- Achado importante: o **heartbeat periodico ja existia** no backend (`orchestrator.py:1612 _dispatch_with_heartbeat`, tick a cada 2.5s via `_HEARTBEAT_INTERVAL_SECONDS`) — o problema era so a UI estar muda, nao falta de mecanismo. Nao foi preciso mexer nos LLM clients (ollama_client.py ja tem streaming pronto via `on_chunk`, so nao e usado pra narracao de UI — e nem deveria, por causa da regra do projeto contra vazar raciocinio/geracao bruta pro historico).
- 2 dialogos modais reais de checkpoint: `_on_checkpoint_interactive` (3 botoes wx.MessageDialog) e `_on_conversational_checkpoint` (2 botoes). A aprovacao de PLANO ja tinha sido corrigida antes (v2.0.0, inline no chat) — os checkpoints pos-step ainda nao.

### Fix implementado
- `studio_dialog.py` 5.27.0 → **5.28.0**: `_handle_status` agora chama `_chat_append` + `_speak_message` (unifica fala+historico). `_handle_tool_progress` agora fala de verdade (throttled via `_speak_message`) usando `_TOOL_PROGRESS_LABELS` (mapa step_type→linguagem natural, ex: "code_generation"→"Gerando o código") em vez de nomes tecnicos crus ou silencio. Os 2 dialogos modais viraram `_ask_checkpoint_inline` — aprovacao inline no chat com classificacao de intencao via IA, mesmo padrao ja usado pela aprovacao de plano; sem `wx.MessageDialog`.
- `conversation_manager.py` 2.0.0 → **2.1.0**: docstrings/comentarios atualizados pra refletir a nova filosofia (status falado+historico; heartbeat so falado; conteudo so historico — decisao deliberada de nao falar conteudo longo automaticamente, pra nao sobrecarregar o usuario).
- 5 testes novos em `test_studio_dialog.py` (`TestCanalUnificadoStatusEHeartbeat`) + `TestAcentosCheckpointDialogo` reescrita (a logica migrou pra `_ask_checkpoint_inline`, os testes de regressao de acentuacao migraram junto). Suite: 2057 → 2068 testes.
- `README.md` e `AI_MODULE_SPEC.md` atualizados (versoes dos 2 modulos + contagem de testes).

### Proximos Passos
- Felipe vai testar ao vivo no NVDA se a narracao do heartbeat e natural o suficiente (nao cansativa) e se o fluxo de checkpoint inline funciona bem
- Se quiser streaming real de conteudo (nao so heartbeat), teria que decidir quais steps sao "conversacionais o suficiente" pra streamar token a token sem violar a regra de nao vazar geracao bruta — nao implementado nesta sessao, ficou fora de escopo por decisao consciente

---

## Sessao Atual (2026-07-20) — parte 2: bug fix `addons/logs/`

### Concluido
- **Bug encontrado no log do NVDA** (`%TEMP%\nvda.log`): `ERROR - addonHandler._getAvailableAddonsFromPath` tentando carregar `%APPDATA%\nvda\addons\logs\` como addon (falta `manifest.ini`) a cada boot
- **Causa raiz**: `logger.py` calculava `_PROJECT_ROOT` subindo 4 niveis fixos a partir de `_MODULE_DIR`, assumindo o layout de dev (`.../addon/globalPlugins/nvdastudio/utils/`). No addon **instalado** dentro do NVDA o layout e um nivel mais raso (`.../addons/nvdastudio/globalPlugins/nvdastudio/utils/`, sem a pasta `addon/` extra) — o mesmo calculo aponta para `%APPDATA%\nvda\addons\` e cria `logs/` ali, que o NVDA tenta carregar como addon e falha
- **Fix**: `logger.py` v1.1.0 — nova constante `_IS_DEV_CHECKOUT` (True somente se `_PROJECT_ROOT` tiver `manifest.ini` E `build.py` diretamente nele, o que so acontece no checkout de dev real). `_ensure_log_dir()` e `get_logger()` so criam/escrevem `_PROJECT_LOG_DIR` quando `_IS_DEV_CHECKOUT` e True; o mirror `_NVDA_LOG_DIR` (`nvdastudio_logs/`) continua sempre ativo
- Validado com simulacao dos dois layouts (dev real vs. instalado simulado em `tmp_path`) — deteccao correta nos dois casos
- 3 testes novos em `tests/unit/test_logger.py` (`TestProjectRootDetection`): deteccao do checkout real, simulacao do layout instalado, e regressao garantindo que `get_logger()` nao cria `_PROJECT_LOG_DIR` fantasma quando `_IS_DEV_CHECKOUT=False`. 14/14 testes de `test_logger.py` passando
- `README.md` e `AI_MODULE_SPEC.md` atualizados: `logger.py` 1.0.0 -> 1.1.0
- Limpeza executada via `scripts/clean_runtime_artifacts.ps1` + remocao manual de `addons/logs/`: logs antigos removidos em `logs/`, `%APPDATA%\nvda\nvdastudio_logs\` e `%APPDATA%\nvda\addons\logs\`; `__pycache__`, `.pytest_cache` e afins removidos. Log de hoje (`nvdastudio_2026-07-20.log`) ficou bloqueado nas 3 pastas porque o NVDA estava rodando (Windows nao libera arquivo aberto) — apagar apos fechar o NVDA
- Achado tambem no log do NVDA: erro **nao relacionado** ao nvdastudio no addon `GeminiChat` (`ImportError: getDefaultConfigurationFilePath` — incompatibilidade com NVDA 2026.1.1), fora de escopo

### Proximos Passos
- Fechar o NVDA, apagar os 3 arquivos de log restantes (bloqueados), reabrir e confirmar que `addons/logs/` nao volta a aparecer no `nvda.log`
- Rodar a suite completa (2057 testes) uma vez limpo, sem processos pytest duplicados (causa do hang anterior: dois `pytest` orfaos rodando simultaneamente brigavam por lock de arquivo)

---

## Sessao Atual (2026-07-20)

### Concluido

#### Auditoria e sincronizacao de documentacao
- `README.md`: contagem de testes atualizada de 1897 (coletados em 2026-07-11) para **2057** (coletados em 2026-07-20, verificado via `pytest --collect-only`)
- `README.md` + `AI_MODULE_SPEC.md`: corrigida a cobertura de regras divergente do `accessibility_auditor.py` (v1.12.0) — os dois documentos afirmavam ranges diferentes e ambos incorretos frente ao codigo real (docstring do modulo). Cobertura real: `NVDA-001..038 + NVDA-040 + NVDA-042..050 + WX-A11Y-001..014 + NVDA-UX-001..003`; `NVDA-051..054` sao auditados por `code_generator.py`/`nvda_context.py`, nao pelo `accessibility_auditor.py`
- `AI_MODULE_SPEC.md` incrementado para v97.1.0 (2026-07-20)
- `MEMORY.md` (este arquivo) estava parado em 2026-06-12/v2.2.0; manifest.ini ja estava em v2.4.0 e README.md com reescrita de arquitetura de IA de 2026-07-19 — gap de duas versoes coberto abaixo
- `docs/rule-coverage.md` (2026-07-14) conferido contra `rule_registry.py`: conteudo segue correto, sem alteracao necessaria

### Historico reconstruido (v2.3.0 e v2.4.0, nao registrado anteriormente neste arquivo)

#### v2.4.0 — Reescrita da arquitetura de IA (ponta a ponta, 2026-07-19)
- Os cinco provedores do painel (`ai/provider_client.py`, `ai/ollama_client.py`, `ai/llm_factory.py`) passaram a usar clientes HTTP nativos, sem bridge externa
- Modo `Alto`: no maximo 20% das etapas usam o modelo topo; demais usam o modelo leve, resolvido via `model_registry.py` auditado contra doc oficial de cada provedor
- Um modelo concreto escolhido manualmente continua sobrescrevendo o roteamento automatico em todas as chamadas
- Memoria resumida, recuperacao semantica (`memory/relevance.py`), cache de prompt e compressao de contexto (`context_compressor.py`, `trajectory_compressor.py`) permanecem ativos
- **`hermes_bridge/` removido** do runtime e do pacote distribuido — os 11 modulos de bridge da v2.2.0 (hermes_delegate_manager, hermes_command_runner, hermes_status, etc.) saem de escopo; o gateway de ferramentas agora e local (`tool_system/`, `tools/tool_gateway.py`), sem dependencia do Hermes CLI
- Raciocinio interno, Markdown decorativo, emojis e relatorios tecnicos deixam de entrar no historico conversacional (`utils/user_visible_text.py`)

#### v2.3.0 — Consolidacao pos-Hermes
- `__init__.py` incrementado para 2.3.0 (GlobalPlugin, atalhos, registro do painel de configuracoes)
- Modulos de auditoria/geracao ganharam novas regras (`accessibility_auditor.py` 1.12.0: NVDA-049/050; `design_review_agent.py` 2.7.0: catalogo completo de 77 regras)
- Suite de testes cresceu para 2057 casos (de ~1897 na v2.1.0/v2.2.0)

### Proximos Passos
- Confirmar resultado completo da suite pytest (2057 testes) apos a rodada em background
- Avaliar se `docs/rule-coverage.md` precisa de data de revisao mais recente na proxima mudanca de `rule_registry.py`

---

## Sessao Anterior (2026-06-12)

### Concluido

#### v2.2.0 — Bridge Hermes Real
- hermes_bridge/ com 11 módulos de integração plug-and-play com Hermes CLI
- hermes_delegate_manager.py — delega tarefas genéricas ao Hermes via `hermes delegate`, fallback automático
- hermes_command_runner.py — executor de comandos Hermes com timeout e retry
- hermes_status.py — indicador de status do backend na UI do NVDAStudio
- hermes_config.py, hermes_llm_client.py, hermes_memory_client.py, hermes_tool_gateway.py, hermes_cron_client.py, hermes_mcp_client.py, hermes_ws_client.py — bridge completa
- Manifest alinhado: 2.2.0

#### v2.1.0 — Checkpoint Interativo + Memoria Proativa + Task Tracker
- checkpoint_manager.py v2.0 — snapshots + checkpoint interativo (CONTINUAR/REFAZER/PAUSAR)
- memory_manager.py v2.0 — memoria PROATIVA (agente decide o que salvar)
- task_tracker.py v1.0 — rastreador de tarefas do pipeline
- studio_dialog.py — dialogo de checkpoint com 3 botoes

#### v2.0.0 — Sistema de Conversacao Hermes-style
- conversation_manager.py v1.0 — separacao status (TTS) vs conteudo (historico)
- studio_dialog.py — callbacks conversacionais (status→TTS/barra efemera, content→historico; thinking permanece interno)
- orchestrator.py — emite status/thinking/content classificados

#### Build e Instalacao
- Build v2.2.0.nvda-addon (299 arquivos, 1082 KB)
- Instalado em %APPDATA%\\nvda\\addons\\nvdastudio
- Syntax check em todos os arquivos: OK
- Hermes CLI detectado no PATH: OK

### Proximos Passos
- Reiniciar NVDA para validar carregamento
- Testar todas as funcionalidades em conjunto
- Testar delegacao real para Hermes CLI
