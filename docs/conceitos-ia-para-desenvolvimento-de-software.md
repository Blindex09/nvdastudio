# AI Engineering, Agentic Engineering, Harness Engineering e Agent Evals

> Documento de referência pessoal (Felipe) — conceitos aprendidos nesta sessão
> de trabalho no NVDAStudio, mas que valem pra qualquer projeto onde IA
> participa do desenvolvimento (gerando código, revisando, orquestrando
> agentes). Complementa `metodologia-verificacao-arquitetura.md` (a pirâmide
> de testes) com o lado "como pensar sobre IA no processo", não só "como
> testar o resultado".
> Criado em 2026-08-09.

## 1. Roteamento determinístico + conteúdo da IA — um princípio arquitetural, não lei universal

**Princípio arquitetural adotado neste projeto** (NVDAStudio), não uma regra
obrigatória de todo sistema agêntico: **a IA decide o QUÊ (conteúdo,
estratégia, julgamento semântico) — código determinístico decide o
COMO/QUANDO (roteamento entre modelos, validação de contrato, escalação).**

Por quê essa escolha aqui: se a própria IA decide pra onde a chamada vai
(qual modelo, qual fallback), o sistema fica difícil de auditar e de prever
custo. Fixando isso em código determinístico, e deixando a IA decidir só o
conteúdo dentro do escopo já roteado, o sistema fica previsível e testável
— mas ainda flexível onde importa (julgamento sobre código, texto,
contexto).

**Isso não é a única arquitetura válida.** Existem sistemas agênticos
legítimos e bem-sucedidos onde o próprio agente escolhe ferramentas,
sub-agentes, estratégia, sequência de execução e quando parar — delegando
justamente o roteamento pra IA. A escolha aqui prioriza previsibilidade e
custo auditável sobre adaptabilidade máxima; outro projeto, com outra
tolerância a risco/custo, pode legitimamente escolher o oposto. Vale decidir
essa escolha conscientemente, não assumi-la como padrão universal da
indústria.

Isso também evita **keywords/blacklists hardcoded** pra decisões de conteúdo
(ex: nunca usar uma lista fixa de palavras proibidas pra filtrar resposta da
IA — isso deveria ser julgamento semântico do próprio modelo em contexto, não
regex). Regex/keyword fixo só é aceitável pra validação técnica estrita (ex:
"esse import existe na stdlib?"), nunca pra decidir se um CONTEÚDO é
apropriado.

## 2. O padrão "Gateway" de múltiplos provedores de IA

Quando um sistema usa vários provedores/modelos de IA, existem 2
arquiteturas comuns em 2026:

- **LLM Gateway** (o padrão mais comum): roteamento
  inicial é decidido por regra/config; failover entre provedores é um
  mecanismo SEPARADO, acionado só quando o provedor escolhido falha.
- **"Exceção sofisticada"**: cada chamada é pontuada dinamicamente contra
  TODOS os provedores disponíveis (qualidade + custo + confiabilidade
  observada), escolhendo o melhor a cada vez — mais caro de manter, mas mais
  adaptativo.

Nenhuma é "certa" universalmente — a escolha depende de quanto o sistema
precisa se adaptar a variações de qualidade entre modelos vs. quanto ele
precisa de previsibilidade/simplicidade.

## 3. Por que IA generativa não entrega "certo" sempre — mesmo com modelos bons

Ponto que gerou frustração real nesta sessão: um teste falhou mesmo usando
modelos "bons" (qwen3.5:397b, gpt-oss:20b). A causa raiz quase nunca é "o
modelo é ruim" — geralmente é uma das duas coisas:

1. **Bug de integração/wiring**: um módulo do PIPELINE (não o modelo) não
   está passando a informação certa pro próximo estágio — o modelo está
   respondendo corretamente à pergunta ERRADA que recebeu. Foi exatamente o
   caso do bug do Critic nesta sessão: o modelo gerava código correto, mas
   era julgado com um critério que não fazia sentido pro que ele foi pedido
   a fazer.
2. **Limite genuíno de capacidade multi-arquivo**: benchmarks 2026 (SWE-EVO,
   ProjDevBench) mostram que MESMO modelos frontier caem de ~70-80% de
   sucesso em tarefa única pra ~25% em tarefas que exigem coerência através
   de MUITOS arquivos/steps ao mesmo tempo. Isso é um limite real da
   indústria em 2026, não falha de configuração.

**Como distinguir os dois**: antes de concluir "o modelo não dá conta", ler o
código que decide o que o modelo recebeu de instrução/contexto. Se a
instrução em si já está errada ou incompleta, é bug de wiring (#1) — mais
comum do que parece, e mais barato de corrigir. Só depois de confirmar que a
instrução estava correta e completa vale considerar limite de capacidade
(#2).

## 4. "Delegação" — decompor em vez de pedir tudo de uma vez

Padrão real usado por ferramentas de codificação com IA em 2026: em vez de
pedir pro modelo fazer uma tarefa grande numa única chamada, decompor em
pedaços menores, independentes e paralelizáveis, cada um verificável sozinho.
Reduz a chance de qualquer UM pedaço sobrecarregar o modelo, e os pedaços que
falharem podem ser retentados/escalados independentemente dos que já
passaram.

**Armadilha real encontrada nesta sessão**: decompor sem também atualizar
TODOS os pontos do sistema que assumiam "sempre existe só 1 pedaço" quebra
tudo — nesse caso, o crítico/avaliador continuava usando uma regra pensada
pra "essa é a única chamada", rejeitando pedaços legítimos. **Decompor a
geração exige decompor também a AVALIAÇÃO** — não é só dividir o trabalho, é
garantir que quem julga sabe que agora existem várias partes com papéis
diferentes.

## 5. Verificação por execução real, não só sintaxe

`ast.parse()`/lint pega erro de SINTAXE. Só executar o código de verdade (em
sandbox isolado) pega erro de EXECUÇÃO — `NameError`, `AttributeError`,
construtor com assinatura errada, import que não resolve em runtime. Um LLM
pode gerar código sintaticamente perfeito e ainda assim quebrar na primeira
execução (esqueceu um import, chamou um método que não existe na classe
base). Vale a pena instanciar/importar de verdade o código gerado num
processo isolado, sempre que possível — é um degrau de verificação que fica
entre "sintaxe" e "teste de comportamento completo".

## 6. Observabilidade de custo e trajetória — não só sucesso/falha

Registrar só "esse step passou ou falhou" esconde informação valiosa:
- **Trajetória** (como ele chegou no resultado): aprovou de primeira? precisou
  de retry? saiu cedo por detectar que estava repetindo o mesmo erro?
  esgotou todas as tentativas sem nunca repetir? Cada rótulo aponta pra uma
  ação de melhoria diferente (prompt ruim vs. modelo genuinamente incapaz vs.
  falta de retry inteligente).
- **Custo real** (não só contagem de tokens): converter tokens em $/R$ de
  verdade por modelo/provider torna visível ONDE o orçamento está sendo
  gasto — sem isso, decisões de "vale a pena rodar de novo?" são no escuro.

## 7. Detecção de loop — quando parar de insistir

Se um sistema retenta automaticamente uma tarefa que falhou, ele precisa de
um jeito de perceber quando está apenas REPETINDO o mesmo erro (sinal de que
insistir do mesmo jeito não vai resolver) versus tentando abordagens
genuinamente diferentes a cada vez (vale continuar). Comparar a "assinatura"
do problema entre tentativas consecutivas (não só contar quantas tentativas
já passaram) evita queimar tempo/orçamento em loops inúteis.

**Cuidado**: o limiar importa. Cortar cedo demais (na 2ª repetição) corta
tentativas que ainda tinham chance real de resolver com estado limpo — vale
exigir umas 2-3 repetições consecutivas antes de considerar "loop confirmado
e sem saída", não só uma.

## 8. Checkpoints/human-in-the-loop informacionais vs. bloqueantes

Dois jeitos de envolver o humano quando a IA perde confiança numa decisão:
- **Bloqueante**: pausa a execução e espera aprovação antes de continuar.
- **Informacional**: avisa o que está acontecendo, mas a IA decide sozinha e
  segue — o humano fica ciente sem precisar agir.

Para um pipeline que roda sozinho e não deve travar esperando input a cada
incerteza, o informacional é geralmente melhor — mas só funciona se o humano
tiver acesso fácil ao histórico/log pra revisar depois, senão vira "aviso que
ninguém vê".

## 9. Degradação graciosa — entregar o que funcionou, não descartar tudo

Quando um pipeline de múltiplos estágios falha PARCIALMENTE (alguns
artefatos saíram certos, outros não), a resposta errada é descartar tudo e
pedir pra recomeçar do zero (gasta de novo o que já tinha funcionado). A
resposta certa é entregar o que funcionou, deixar claro o que faltou, e
permitir corrigir só a parte que falhou — preservando o trabalho (e o
dinheiro) já gasto no que deu certo.

## 10. Shift-Left Testing e Continuous Testing

**Shift-Left Testing**: mover a verificação pra o INÍCIO do ciclo (perto de
onde o código é escrito), em vez de deixar pra descobrir problemas só no
fim (produção, ou um teste E2E caro). É o princípio por trás da ordem inteira
da pirâmide de testes (`metodologia-verificacao-arquitetura.md`) — cada
degrau mais barato existe justamente pra empurrar a descoberta de bugs pra
mais cedo, quando corrigir custa quase nada, em vez de mais tarde, quando já
custou tempo/dinheiro real.

**Continuous Testing**: rodar a verificação (lint, testes) a cada mudança,
não só no final ou antes de um deploy. Na prática: `ruff` + testes
direcionados depois de CADA edição de código, não só uma vez no fim de uma
sessão inteira de trabalho — pega regressão no exato commit que a causou,
enquanto o contexto de por que essa linha mudou ainda está fresco.

**Verification Pipeline**: encadear os degraus da pirâmide como um pipeline
de fato (cada estágio só roda se o anterior passou), não como checagens
soltas e esporádicas. Isso é o que dá disciplina real ao "shift-left" — sem
um pipeline que force a ordem, é fácil pular direto pro teste caro achando
que vai ser mais rápido.

## 11. Trajectory Evals / Process Evals — avaliar o CAMINHO, não só o resultado

Um agente pode chegar na resposta certa por um caminho ruim: `tool errada →
retry → tool errada → busca desnecessária → resposta correta`. Um teste que
só olha o resultado final diz `PASS`. Um **Trajectory Eval** diz `FAIL` —
porque o caminho em si é o problema (desperdiçou tempo/tokens, ou só
funcionou por sorte, e da próxima vez pode não funcionar).

Camadas, da mais grosseira pra mais fina:
`Outcome Evals` (só o resultado) → `Trajectory Evals` (a sequência de passos
fez sentido?) → `Tool-call Evals` (cada chamada de ferramenta foi a certa,
com os argumentos certos?) → `State-transition Evals` (o estado interno
mudou do jeito esperado a cada passo?).

Isso é diferente de só REGISTRAR a trajetória (ver seção 6, "trajetória" como
dado observável) — aqui a trajetória vira algo que se AVALIA e pode reprovar
sozinha, mesmo com resultado final correto.

## 12. Multi-run / Statistical Evals — 1 execução não é evidência

Software tradicional é determinístico: `input X → output Y`, sempre. Um
agente de IA é `input X → talvez A, talvez B, talvez C` — mesmo com
temperatura 0, variação real acontece (confirmado em estudos de 2026 que
rodaram a mesma configuração múltiplas vezes). Isso muda a matemática de
"meu teste passou":

- **1 execução = evidência fraca.** 20/20 execuções = confiança muito maior.
- Conceitos: **Pass@k** (taxa de acerto considerando k tentativas),
  **Success Rate** (% de execuções corretas numa amostra), **Variance**
  (quanto o resultado varia entre execuções idênticas), **Flakiness**
  (falha intermitente sem mudança de input), **Confidence Intervals**
  (margem de confiança estatística sobre a taxa de sucesso, não só um
  número pontual).

Na prática: pra afirmar "esse fix funciona", rodar 1 vez não basta quando
o comportamento tem qualquer variabilidade real — vale considerar quantas
repetições são necessárias antes de confiar no resultado.

## 13. Deterministic Replay / Trace Replay

Guardar tudo que compôs uma execução — `input + contexto + estado + tool
calls + tool outputs + decisões` — permite REPRODUZIR o cenário exato
depois, sem gastar de novo o custo de rodar tudo do zero (API real, tempo).
Quando um bug aparece, o replay do trace já capturado é o primeiro passo de
debug, não uma nova rodada cara. Combina diretamente com a preocupação de
não queimar orçamento de API só pra reproduzir um problema já visto uma vez.

## 14. Golden Dataset / Regression Dataset — falha real vira caso permanente

A regra "bug → teste de regressão" (seção 8 de `metodologia-verificacao-
arquitetura.md`) se expande, em sistemas de IA, pra um ciclo mais rico:

```
falha real em producao
  -> captura o trace (input+contexto+decisoes)
  -> sanitiza (remove dado sensivel)
  -> adiciona ao dataset de avaliacao
  -> corrige o bug
  -> roda o eval contra o dataset
  -> vira caso de regressao PERMANENTE
```

Essa abordagem já foi descrita publicamente por times de ponta em 2026:
correções reais viram traces, os traces viram evals, e esses evals passam a
guiar melhorias futuras — não é só "escreveu um teste", é um dataset vivo
que cresce a cada falha real encontrada.

**Eval-Driven Development** (achado em pesquisa de agosto/2026, complementa
o ciclo acima em vez de substituir): definir os casos de avaliação ANTES de
construir o agente, não só depois de uma falha real — separar um conjunto
de DESENVOLVIMENTO (usado pra construir/ajustar o agente) de um conjunto de
TESTE reservado (só usado na medição final, nunca visto durante a
construção), pra evitar que o agente seja involuntariamente ajustado pra
"decorar" os casos de teste. É o TDD aplicado a avaliação de agente: golden
dataset é reativo (falha real vira caso), eval-driven é proativo (caso
esperado vem antes do código) — os dois se complementam.

## 15. Offline Evals × Online Evals

Duas fases distintas de verificação:
- **Offline Evals**: tudo que roda ANTES do deploy — unit, integration,
  evals, E2E.
- **Online Evals**: o que roda DEPOIS, em produção — porque é possível ter
  unit/integration/evals/E2E todos verdes e ainda assim ter comportamento
  inesperado só em produção real.

O ciclo fecha assim: `Offline Eval → Release → Production Monitoring →
Online Eval → Failure Mining → Regression Dataset → Offline Eval` (de novo).
Isso transforma produção em fonte de novos casos de teste (seção 14), sem
transformar o usuário real em "testador" — o monitoramento capta o problema,
não o usuário reportando manualmente.

## 16. Adversarial Evals / Robustness Evals

Verificação do "happy path" e falhas normais não é suficiente pra um agente
que roda perto de conteúdo não-confiável (web, input de usuário, ferramentas
externas). Categorias a testar explicitamente:
`Adversarial Evals` (tentar ativamente quebrar o agente), `Prompt Injection
Testing` (conteúdo externo tentando sequestrar instruções), `Tool Misuse
Testing` (o agente usa uma ferramenta de forma perigosa/fora do escopo),
`Permission Boundary Testing` (o agente respeita os limites do que pode
fazer), `Untrusted Input Testing` (dado de fora tratado como dado, nunca
como instrução), `Failure Injection`/`Chaos Testing` (injetar falhas de
propósito — timeout, erro de API, resposta malformada — pra ver se o
sistema degrada bem ou quebra feio).

## 17. Agent State / Memory Testing

Um agente pode dar uma resposta boa isoladamente e falhar depois de 30
interações — isso é diferente de um E2E comum (que testa 1 fluxo do início
ao fim, não a persistência de estado ao longo de MUITAS interações).
Categorias: `Memory Evals`, `Context Retention Evals`, `State Transition
Testing`, `Context Pollution Testing` (informação de um turno vazando
incorretamente pra outro contexto), `Context Isolation Testing` (dois
contextos que deveriam ser independentes continuam independentes?).

Exemplo de cenário de teste: turno 1 aprende X → turno 2 usa uma tool →
turno 3 dá erro → turno 4 tenta de novo → turno 5: **o agente ainda lembra
X?**

## 18. Context Engineering Verification

"Wiring" (seção 10 de `metodologia-verificacao-arquitetura.md`) pode ser
generalizado: **contexto é uma superfície verificável por si só**, com
dimensões próprias a testar:
`Context completeness` (tudo que era necessário chegou?), `Context
relevance` (só o que importa chegou, sem ruído?), `Context freshness`
(a informação está atualizada, não stale?), `Context ordering` (a ordem em
que a informação aparece afeta a atenção do modelo — "lost in the middle"),
`Context isolation` (contextos de tarefas diferentes não vazam um pro
outro), `Context budget` (cabe no limite de tokens sem cortar o essencial),
`Context compression` (resumir sem perder o que importa), `Context
contamination` (dado malicioso ou irrelevante contaminando o contexto).

Em sistema agêntico, o problema raramente é "modelo ruim" ou "código ruim"
— na maioria das vezes é "**modelo recebeu contexto errado**" (exatamente o
padrão da seção 3 deste documento: o modelo respondeu corretamente à
pergunta errada porque o pipeline passou informação inadequada). Vale tratar
isso como uma categoria formal de verificação, não só uma explicação
post-hoc de bug.

## 19. Quality Gates / Release Gates

Ter 500 testes não basta sem uma **condição objetiva de liberação**: um
portão que define, explicitamente, o que precisa passar antes de uma versão
avançar:

```
lint = PASS
unit = PASS
contract = PASS
integration = PASS
security = PASS
accessibility = PASS
agent eval >= threshold
regression = PASS
E2E real = PASS
cost <= budget
latency <= threshold
  -> RELEASE

qualquer requisito CRITICO falhou -> NO-GO
```

Isso transforma a metodologia de documentação em **política executável de
engenharia** — não é só "sabemos o que verificar", é "definimos o que
BLOQUEIA uma entrega".

## 20. O pipeline completo (2026, forma madura)

Juntando tudo (`metodologia-verificacao-arquitetura.md` + as seções acima):

```
Static Analysis
  -> Unit Tests
  -> Component Tests
  -> Contract Tests
  -> Integration Tests
  -> Functional Tests
  -> Non-Functional Tests
  -> Context Verification (secao 18)
  -> Agent Behavioral Evals
  -> Tool-call Evals
  -> Trajectory Evals (secao 11)
  -> Memory / State Evals (secao 17)
  -> Adversarial / Robustness Evals (secao 16)
  -> Multi-run Statistical Evals (secao 12)
  -> Real E2E
  -> Regression Suite / Golden Dataset (secao 14)
  -> Quality Gate (secao 19)
  -> Deploy
  -> Online Evals (secao 15)
  -> Observability / Tracing
  -> Failure Mining
  -> Regression Dataset
       (volta pro topo)
```

A mudança de fundo, 2026: avaliação de agente de IA está saindo de "a
resposta final estava certa?" pra avaliar **resultado + trajetória +
ferramentas + estado + custo + segurança + robustez** ao mesmo tempo.
Adotar essa disciplina como referência ANTES de considerar uma implementação
concluída é o que separa "IA escreve código → vejo se funciona" de "IA
implementa → sistema verifica → mede → reproduz → bloqueia regressão → só
então libera".

## 21. Harness Engineering — o conceito que amarra tudo

**O termo mais importante desta rodada final.** Em 2026, times de ponta
descrevem o trabalho de construir um agente não como
"escrever um prompt melhor", mas como **projetar o harness** — a
infraestrutura que coordena modelo, ferramentas, contexto, estado e
avaliação ao redor do modelo:

```
                    MODEL
                      |
              +-------+-------+
              | Agent Harness |
              +-------+-------+
                      |
     +----------------+----------------+
     |                |                |
   Context          Tools            State
     |                |                |
   Memory          Sandbox          Checkpoint
     |                |                |
     +----------------+----------------+
                      |
                 Agent Loop
                      |
              Evaluation/Evals
                      |
                 Observability
```

O modelo em si é só um componente — a QUALIDADE do sistema vem majoritariamente
do harness ao redor dele: como o contexto é montado, como as ferramentas são
expostas e sandboxed, como o estado persiste entre passos, como o loop decide
quando parar/retentar/escalar, como a avaliação mede o resultado, e como a
observabilidade expõe tudo isso pra debug. **O NVDAStudio inteiro (Planner +
Critic + Orchestrator + sub-agentes + memory + sandbox) É um harness** —
nomear esse conceito explicitamente ajuda a enxergar cada peça do projeto
como parte de uma disciplina reconhecida, não uma escolha de arquitetura
isolada.

Termos que vivem dentro do harness:
- **Agent Loop / Execution Loop**: o ciclo central que decide a próxima ação
  (chamar tool, responder, parar) a cada iteração.
- **Long-Horizon Agents**: agentes que sustentam coerência ao longo de MUITOS
  passos/chamadas (não só um par pergunta-resposta) — onde a maioria dos
  problemas reais de wiring/contexto/memória aparece.
- **Multi-Agent Orchestration**: coordenar vários agentes especializados
  (como os sub-agentes do NVDAStudio) em vez de um agente generalista único.
- **Agent Delegation** e **Parallel Agent Execution**: dividir trabalho entre
  agentes e rodá-los concorrentemente quando são independentes (ver seção 4).

## 22. Agent Evals — hierarquia e vocabulário completo

Consolidando e fechando o vocabulário de avaliação de agente (seções 11-19
já cobriram boa parte de forma dispersa — aqui é a HIERARQUIA explícita,
pra deixar claro que "Agent Evals" não é 1 técnica, é uma família com
vários tipos concretos, cada um pegando uma classe diferente de problema):

```
Agent Evals
  -> Outcome Evals           (o resultado final estava certo?)
  -> Trajectory Evals        (o CAMINHO ate o resultado fazia sentido?)
  -> Tool-Use Evals          (a ferramenta certa, com os argumentos certos?)
  -> State / Memory Evals    (persistencia correta entre passos/turnos?)
  -> Adversarial Evals       (resiste a input hostil/malicioso deliberado?)
  -> Accessibility Evals     (o resultado e utilizavel por quem depende de
                               acessibilidade -- especifico de projetos como
                               este, generaliza pra "Domain Evals": toda
                               classe de agente tem uma dimensao de
                               qualidade especifica do seu dominio que
                               nenhuma das evals genericas acima cobre)
  -> Regression Evals        (o caso que ja falhou uma vez continua
                               resolvido? -- Golden Dataset, secao 14)
  -> Online Evals            (o comportamento em PRODUCAO real, continuo,
                               nao so pre-deploy)
```

`Multi-turn Evals` (comportamento ao longo de uma conversa inteira, não um
turno isolado) e `Offline Evals` (tudo que roda antes do deploy, ver seção
15) atravessam varias linhas da hierarquia acima, não são um tipo à parte.

### O ciclo fechado que liga Evals a produção de verdade

Esse é o elo que faltava deixar 100% explícito — sem ele, "Agent Evals" e
"produção" ficam sendo tratados como coisas separadas, quando na prática
formam um ciclo único e contínuo:

```
Production Traces (secao 23, Agent Observability)
  -> Failure Mining (secao 24 -- vasculhar os traces atras de padrao de falha)
  -> vira caso NOVO no Golden Dataset (secao 14)
  -> roda como Regression Eval (linha acima)
  -> corrige / melhora o sistema
  -> volta pra producao
  -> gera Production Traces NOVOS
       (fecha o ciclo, recomeca)
```

Esse ciclo é o que torna a Seção 29 (Eval-backed / Self-improving
Engineering Loop) uma prática operacional de verdade, não só um conceito —
cada volta do ciclo é uma oportunidade real de melhoria cumulativa,
verificável, alimentada por comportamento REAL em produção, não só por
suposição de onde algo pode dar errado.

Duas técnicas de avaliação que valem nomear:
- **LLM-as-a-Judge**: usar um modelo (geralmente mais forte, ou em segundo
  estágio) pra JULGAR a saída de outro modelo — é literalmente o padrão que
  o Critic do NVDAStudio já implementa (2 estágios, spec + qualidade).
- **Rubric-based Evaluation**: julgar contra critérios EXPLÍCITOS e
  objetivos (não "parece bom?"), a mesma disciplina por trás da rubrica do
  Critic (ARCH-001..009, NVDA-XXX) — rubrica clara é o que torna
  LLM-as-a-Judge auditável e consistente, em vez de um "achismo" do modelo
  avaliador.

`Golden Dataset` / `Eval Dataset` (seção 14), `Trace Replay` / `Deterministic
Replay` (seção 13), `Quality Gates` / `Eval Gates` (seção 19) já cobertos.

## 23. Agent Observability / Agent Tracing

Observabilidade (seção 6) aplicada especificamente a agentes: rastrear cada
decisão, tool call, e transição de estado como um TRACE navegável — não só
logs soltos. É o que permite Trace Replay (seção 13) e Failure Mining (seção
15) funcionarem na prática — sem tracing estruturado, capturar "o que
aconteceu" pra reproduzir depois vira arqueologia manual de log.

## 24. Agent Decay / Performance Drift e Continuous Evaluation

Um agente pode piorar com o tempo mesmo sem nenhuma mudança de código — o
provider atualiza o modelo por trás do mesmo model_id, uma dependência muda
de comportamento, o padrão de uso real diverge do padrão testado. **Agent
Decay** (ou **Performance Drift**) é esse declínio silencioso. A defesa é
**Continuous Evaluation**: não tratar "passou nos evals uma vez" como
permanente — reavaliar periodicamente contra o mesmo dataset (seção 14),
inclusive em produção (Online Evals, seção 15), pra pegar drift antes que
vire um problema visível pro usuário.

**Production Failure Mining**: vasculhar ativamente os traces de produção
(seção 23) atrás de padrões de falha ainda não capturados no golden dataset
— fecha o ciclo de "falha real vira caso permanente" (seção 14) de forma
proativa, não só reativa a reclamação de usuário.

**Self-improving Agent Loop**: quando esse ciclo inteiro (produção → captura
→ dataset → fix → eval → produção) roda de forma cada vez mais automatizada,
o sistema começa a se auto-corrigir estruturalmente — a mesma direção
descrita na seção 14 para agentes de correção automatizada.

## 25. Agentic Software Engineering

A mudança de fundo no papel do engenheiro quando agentes assumem mais da
implementação: o valor do trabalho humano migra de "escrever cada linha" pra
**arquitetura de sistemas, coordenação de agentes, e avaliação de
qualidade** — decidir COMO o harness (seção 21) deve ser estruturado, COMO
os agentes devem ser coordenados, e COMO julgar se o resultado é bom o
suficiente. É a mesma tendência refletida em cada seção deste documento:
cada vez menos "será que o código está certo" e cada vez mais "o sistema que
verifica o código está certo".

## 26. Context Compaction e Context Isolation

Duas técnicas específicas dentro de Context Engineering Verification (seção
18), importantes o suficiente pra nomear à parte:

- **Context Compaction**: resumir/comprimir contexto acumulado (histórico
  longo de conversa, muitos passos de um agente) pra caber no orçamento de
  tokens sem perder a informação que ainda importa — diferente de truncar
  cru (que perde informação arbitrariamente), compactação tenta preservar o
  ESSENCIAL.
- **Context Isolation**: garantir que o contexto de uma tarefa/sessão não
  vaza pra outra tarefa/sessão que deveria ser independente — falha aqui
  produz um agente que "lembra" de coisas que não deveria, ou aplica
  contexto de um usuário/tarefa a outro.

## 27. Padrões de Orquestração Multi-Agente

Formas nomeadas de coordenar múltiplos agentes (complementam Multi-Agent
Orchestration, seção 21):
- **Sequential**: um agente termina, o próximo começa, em cadeia.
- **Concurrent / Parallel**: vários agentes trabalham ao mesmo tempo em
  partes independentes (ver Delegação, seção 4).
- **Handoff**: um agente ativamente transfere o controle da tarefa pra
  outro agente mais especializado no meio da execução.
- **Maker-Checker**: um agente PRODUZ (o "maker"), outro agente
  INDEPENDENTE revisa/aprova antes de aceitar o resultado — o mesmo padrão
  já usado pelo Critic em dois estágios, nomeado formalmente.

**State Management** (entre agentes/passos) e **Agent Governance**
(políticas sobre o que agentes PODEM fazer, quem aprova o quê) são as
preocupações que atravessam qualquer um desses padrões — sem gestão de
estado clara, handoff e checagem cruzada ficam inconsistentes; sem
governança, não há limite claro do que um agente pode decidir sozinho.

## 28. AI-native Observability

Observabilidade tradicional (latência, taxa de erro) não é suficiente pra
um sistema agêntico. Observabilidade nativa de IA precisa capturar também:
contexto usado em cada decisão, chamadas de ferramenta e seus argumentos,
permissões exercidas, saídas produzidas, resultados de busca/retrieval, e
identidade da requisição — o trace completo de UMA decisão de ponta a
ponta, não só métricas agregadas. Sem isso, "por que o agente fez X" vira
pergunta sem resposta possível depois do fato.

## 29. Eval-backed / Self-improving Engineering Loop

Fecha o ciclo entre observabilidade e melhoria: execução real gera traces
(seção 23) → traces viram casos de eval (Golden Dataset, seção 14) → toda
correção nova é validada contra esses casos antes de aceitar → o sistema
melhora de forma cumulativa e verificável, não por "parece que ficou
melhor". É a versão operacional de Self-improving Agent Loop (seção 24),
enquadrada como prática de engenharia repetível, não só tendência.

## 30. Repository Intelligence, Reference Implementation Compliance e Documentation Compliance

Três verificações específicas de ferramentas de codificação assistidas por
IA, cada vez mais centrais:
- **Repository Intelligence**: antes de editar, o agente entende de
  verdade a estrutura real do repositório (convenções, testes existentes,
  CI, regras do projeto) — não edita às cegas, cega ao contexto do próprio
  código que já existe.
- **Reference Implementation Compliance**: quando existe um padrão de
  referência já estabelecido no próprio código (um módulo "canônico" que
  outros deveriam imitar), verificar que código novo/gerado segue esse
  padrão, não reinventa a cada vez.
- **Documentation Compliance**: verificar que a documentação do projeto
  (este tipo de documento incluído) continua batendo com o código real —
  documentação desatualizada é tão perigosa quanto código sem teste, porque
  engana quem confia nela.

> **Nota de escopo (2026-08-09)**: os termos de segurança/isolamento
> (sandboxing, permission boundaries, blast radius, fault injection) foram
> deliberadamente separados pra um terceiro documento —
> `conceitos-ia-seguranca-confiabilidade.md` — em vez de ficarem soltos
> aqui. Harness Engineering (seção 21) e Agentic Software Engineering
> (seção 25) fecham este documento como o eixo de **AI Engineering,
> Agentic Engineering, Harness Engineering e Agent Evals**; o primeiro
> documento (`metodologia-verificacao-arquitetura.md`) continua sendo o
> eixo de **Engenharia, Arquitetura e Verification & Validation de
> Software**.

---

## v1 fechada (2026-08-09)

Este documento está fechado como v1, junto com `metodologia-verificacao-
arquitetura.md` e `conceitos-ia-seguranca-confiabilidade.md`. Os 3 juntos
cobrem os 3 eixos completos: Software Engineering/Arquitetura/Verification,
AI/Agentic/Harness Engineering, e Agent Security & Reliability. Não são
listas pra crescer indefinidamente a cada termo novo publicado — deliberadamente
NÃO incluem sinônimos do que já existe aqui (ex: "End-to-End Validation" já
é E2E Real; "Continuous Verification" já é Continuous Testing + Verification
Pipeline). Evolução futura vem de problema real encontrado na prática — o
mesmo princípio de Golden Dataset (seção 14) aplicado à própria
documentação: caso real primeiro, conceito depois, nunca o contrário.

## 26. Auditoria de contrato é mais barata que descoberta via teste real

Ver `metodologia-verificacao-arquitetura.md`, seção "Contract Tests" — o
resumo aqui: **antes de gastar em teste real caro pra achar um bug de
integração entre módulos, vale a pena primeiro ler os dois lados de cada
"costura" (o que um módulo promete vs. o que o outro realmente consome)**.
Esse tipo de auditoria não precisa nem de chamada de LLM externa — é leitura
de código cruzada, e pega exatamente a classe de bug mais comum em pipelines
de múltiplos agentes: campo que um lado escreve com um nome e o outro lê com
outro, callback que existe dos dois lados mas nunca é de fato conectado,
regra documentada num lugar mas nunca aplicada no lugar que deveria fiscalizá-la.
