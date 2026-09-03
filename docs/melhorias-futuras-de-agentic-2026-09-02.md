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

**Atualizado em 2026-09-03:** o Item 1 saiu de "futuro" — foi
implementado e em parte revertido no mesmo dia; a seção abaixo guarda o
que sobrou e o que não deve voltar. O Item 2 continua aberto. O Item 3
entrou depois, medido na primeira rodada inteira pela Factory: é o
candidato de corte mais claro do projeto e está esperando decisão.

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

## Item 1 — Orquestração adaptativa — FEITO, e em parte revertido

**Status (2026-09-03):** implementado em `f493280` e parcialmente revertido em
`da4427f`. Não é mais trabalho futuro. Fica registrado porque a reversão
ensinou mais que a implementação.

**O que o agentic faz** (`features/orchestration/README.md`): escolhe
internamente a forma menos complexa e confiável para cada tarefa — resposta
direta, etapas dependentes, partes independentes em paralelo, pesquisa e
análise, ou produção com revisão. O usuário não escolhe arquitetura.

**O que foi implementado** (`planner` 2.44.0): `_aplicar_teto_de_steps()`, com
`_TETO_DE_STEPS = 8`, aplicado no fim da cadeia de injeção em `create_plan` E
em replan. A poda seguia `_PRIORIDADE_DE_PODA`, ordenada por conversão MEDIDA
após retentar — engineering_review (0%), design_review (0%, 5,9M de tokens
perdidos), web_research (16%), accessibility_audit, test_generation — e nunca
podava quem produz arquivo do addon. Decisão 100% determinística, como a
Regra 7 exige: tabela de conversão medida, não modelo. Até então o projeto só
tinha pressão numa direção: `oversized_code_generation_steps()` decompõe o
plano e nada o encurtava.

**Por que foi revertido** (`planner` 2.45.0): a medição que o justificava
estava confundida. Contando `code_generation` por faixa:

| faixa | entrega | média de code_generation por plano |
|---|---|---|
| 6-8 steps | 110/117 (94%) | 1,5 |
| 9-11 steps | 3/11 (27%) | 4,4 |
| 12+ steps | 3/9 (33%) | 6,4 |

Os planos de 6-8 steps que entregavam 94% eram addons SIMPLES, de um ou dois
arquivos. O número de steps era **termômetro da dificuldade do pedido, não
causa da falha**. Encurtar o plano de um addon complexo não o torna simples —
torna cada step maior.

Confirmado na rodada de 2026-09-02 20:38, com o teto ativo: o plano caiu de 13
para 9 steps e o custo por `code_generation` SUBIU de ~100-135 mil para
252.185 e 261.138. Pior, o teto do orçamento deriva do plano, então encurtar
encolheu a caixa junto (1.398.750 → 704.550): mesmo trabalho, caixa menor.

**O que sobreviveu da investigação**: a recalibração da tabela de custos
(`utils/iteration_budget.py`, `_CUSTO_MEDIDO_POR_STEP` — `code_generation`
custava 157.105 na média medida com n=404, e a tabela dizia 87.500) e a
correção do terceiro portão de orçamento (`orchestrator` 5.82.0), que barrava
o assembly com o teto reduzido — a reserva existia e era negada justamente a
quem ela protege.

**Guardas contra reintrodução**: bloco `NAO REINTRODUZIR` no topo do
`planner.py` (linha 1034) com a medição e o confundidor, e
`tests/unit/test_orcamento_code_generation.py`, que falha se `_TETO_DE_STEPS`
ou `_aplicar_teto_de_steps` voltarem a existir.

**Armadilha de medição, registrada para não ser repetida**: a faixa de 1-5
steps aparecia com 7% de entrega em 132 rodadas e sugeria que plano curto
também fosse ruim. Conferindo, 123 dos 132 tinham erro registrado — eram
execuções ABORTADAS, e o relatório só grava os steps que chegaram a rodar.
Não eram planos curtos, eram planos truncados. Excluir os abortos inverteu a
leitura.

**O que continua valendo para quem retomar o tema**: o que a reversão fechou
foi o caminho de *encurtar o plano*, não a ideia de escolher a forma. A
adaptação determinística que existe hoje é o `COMPLEXITY_MAP` (mapa de modelo
por complexidade) e a `oversized_code_generation_steps()` (pressão para
decompor). A métrica de sucesso é taxa de entrega do golden set complexo
antes/depois — nunca número de steps, que já se provou termômetro e não causa.

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

## Item 3 — `design_review`: o step mais caro, com 0% de aproveitamento

**Status (2026-09-03):** medido, não decidido. É o candidato mais claro de
corte do projeto, e a decisão é do usuário porque envolve tirar uma etapa de
qualidade.

**O que a medição diz.** Duas fontes independentes, meses e provedores
diferentes, concordando:

- a tabela de conversão que originou a `_PRIORIDADE_DE_PODA` (planner 2.44.0,
  medida em 415 relatórios): `design_review` converte **0%**, com **5,9
  milhões de tokens perdidos** — é a pior linha da tabela inteira;
- a rodada de 2026-09-03 17:26, a primeira inteira na Factory: uma única
  chamada de `design_review` custou **157.628 créditos**, carregando ~2
  milhões de tokens de contexto. Foi o item mais caro da rodada, disparado nos
  primeiros 6 minutos.

**Por que isso não é o mesmo erro do teto de steps.** A poda foi revertida em
`da4427f` porque a premissa estava confundida: número de steps era termômetro
da dificuldade do pedido, não causa da falha. Essa reversão não invalidou a
medição de *quem converte* — invalidou a de *quantos steps*. São coisas
diferentes, e vale registrar para ninguém usar a reversão como argumento
contra este item.

**O que exatamente decidir.** Três formas, da mais conservadora à mais
agressiva:

1. **Manter e baratear:** `design_review` não precisa dos ~2M de contexto que
   recebeu. Ele é consultivo e já é não-bloqueante; `_DESIGN_REVIEW_PERSONA_DOCS`
   (nvda_context 3.33.0) já recorta contexto por persona e pode ser apertado
   mais. Custo baixo, ganho parcial.
2. **Tornar opcional por complexidade:** só injetar em `complexity="high"`.
   O planner já tem a classificação; a decisão continuaria determinística
   (Regra 7).
3. **Remover a injeção:** o `assembly` já não depende dele (`_STEPS_CONSULTIVOS`,
   planner 2.42.0), então sair não quebra o grafo.

**Como saber se valeu:** taxa de entrega do golden set complexo antes/depois.
Se não mudar, os 5,9M de tokens eram puro custo. Se cair, o step estava
fazendo algo que a medição de conversão não captura — e aí a resposta é a
forma 1, não a 3.

**Contexto de orçamento (2026-09-03):** o usuário tem assinatura Factory de
US$ 20/mês (plano Pro). A Factory não publica o total absoluto de créditos de
nenhum plano, e a Analytics API responde `403: Analytics is only available for
Enterprise organizations` — então não há como medir "quanto do teto foi
gasto". O que se sabe: o consumo é governado por três janelas rolantes (5h, 7
dias, 30 dias) e, esgotado o Standard Usage, o uso cai no **Droid Core**, pool
gratuito com rate limit separado que inclui GLM, Kimi e DeepSeek — as mesmas
famílias que o projeto já roteia. Confirmar no painel se `kimi-k2.7-code`
está listado como Droid Core: é isso que decide se a degradação é suave.

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
