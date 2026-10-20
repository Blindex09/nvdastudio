---
paths:
  - "addon/globalPlugins/nvdastudio/tool_system/**"
  - "addon/globalPlugins/nvdastudio/tools/**"
  - "addon/globalPlugins/nvdastudio/builder/**"
  - "addon/globalPlugins/nvdastudio/core/**"
---

# Agente = modelo + harness; IA decide, código protege (regras 1 e 2)

> Carrega quando se mexe em código ou testes. Texto integral das regras, sem mudança.

### 1. Agente = modelo + harness

- O modelo decide o conteúdo: o significado do pedido, se há ambiguidade relevante, como decompor, qual estratégia
  seguir, o que examinar, como corrigir, quando revisar a própria abordagem e como explicar o progresso.
- O harness (o código em volta) decide só o que é permitido: identidade e escopo de credencial, ferramentas negadas por
  padrão, sandbox, validação de caminho e de comando, cancelamento, validação de schema e contrato, integridade de
  arquivo, aprovação para ações irreversíveis, registro de eventos e recuperação de falhas.
- Esses papéis nunca se invertem. A IA decide o conteúdo; o roteamento e a proteção são do código.

### 2. IA semântica, sem determinismo nem heurística para julgamento

- Nada de regex, palavra-chave, lista de sinônimos ou árvore fixa de condições para decidir intenção, se algo está
  claro, qual ferramenta usar, se uma resposta está completa ou se uma interface está boa. Isso é da IA, pelo
  significado.
- Determinismo só para fato objetivo e verificável (uma URL presente no texto, um tamanho, um schema, o código de saída
  de um processo, um processo que é da própria plataforma) e para segurança, permissões, isolamento, sintaxe e
  integridade.
- Nenhum determinismo exagerado que impeça a IA de trabalhar. Quanto menos, melhor, desde que não tire proteção.
- Um teste que obriga o código a adivinhar intenção por palavra-chave pede o tipo errado de determinismo e não é
  aceito.

## Regra permanente: agente = modelo + harness (determinismo só onde protege)

**Obrigatória para todo código, teste e correção deste projeto, para toda integração de
modelo/provider presente ou futura, sem exceção** — nenhum modelo, provider ou ferramenta
tem tratamento especial que o isente desta regra. Esta seção é intencionalmente
**genérica e portável**: não nomeia nenhum provider, arquivo ou módulo específico deste
projeto de propósito, para poder ser copiada para o `CLAUDE.md` de qualquer outro software
agentic sem edição. Onde este projeto tiver detalhe concreto de como a regra se aplica aqui
(nomes de arquivo, endpoints, histórico de correções), ele fica isolado na parte específica
final deste arquivo — apague só aquela parte ao portar esta regra para outro projeto.

### Princípio central

Um agente é **modelo + harness**, dois papéis que nunca se invertem:

- **O modelo** interpreta intenção, decide o que uma tarefa realmente pede, se há ambiguidade
  relevante, como decompor, qual estratégia técnica seguir, o que examinar, como corrigir,
  quando revisar a própria abordagem e como explicar progresso/resultado. Isto é julgamento —
  cabe à IA, não a uma condição fixa no código.
- **O harness** (o código determinístico ao redor do modelo) não tenta ter a mesma opinião
  que o modelo sobre o que fazer — ele impõe o que é **permitido**, independente do que o
  modelo "pretende". O modelo não se autopolicia; o harness é o limite de conformidade.

### O que o harness controla — e só ele

- **Identidade do agente e escopo de credencial**: cada agente/execução opera com a menor
  permissão suficiente para a tarefa (least privilege); prefira credenciais de curta duração
  e com escopo estreito a chaves estáticas de longa duração quando a plataforma de credencial
  permitir.
- **Acesso a ferramenta como negado-por-padrão**: uma ferramenta/capacidade só fica disponível
  quando explicitamente concedida; nunca "disponível a menos que alguém desligue". A concessão
  é capturada quando o agente nasce, e o despachante verifica concessão, schema e aprovação
  antes de chamar o handler.
- **Isolamento e sandbox**: execução de código, navegador ou comando roda num limite que não
  alcança mais do que o necessário, e cujo vazamento não compromete o resto do sistema.
- **Validação de caminho e de comando**: nenhuma operação de arquivo ou processo sai do
  workspace/escopo autorizado; comandos são validados antes de rodar, nunca depois. O escopo autorizado é a pasta de trabalho com a
  aprovação ligada; com a aprovação desligada pela pessoa, é o que ela pediu (decisão do dono, 20/out/2026).
- **Cancelamento e interrupção**: parar uma execução em andamento é sempre possível e sempre
  determinístico — nunca depende do modelo "decidir" parar. Cancelar preserva o que já foi
  recebido e encerra o que estava ativo.
- **Controle central de progresso, sem relógio fixo**: todo laço, retry ou delegação é
  acompanhado por um controle único, e não por contadores paralelos e cegos. Nenhum limite
  fixo de tempo, de tokens, de chamadas ou de etapas corta uma execução que continua avançando
  (regra 8). Retry não zera o que já foi provado nem o que já foi gasto.
- **Loop adaptativo — nunca loop infinito**: todo laço de execução (tool-loop, delegações,
  reparos de JSON, espera de steering/esclarecimento) é encerrado por algo real —
  convergência (não há mais nada útil a fazer), ausência de progresso, cancelamento do
  usuário, orçamento de custo configurado pela pessoa ou detecção de repetição (a mesma
  decisão voltou a aparecer). Uma decisão repetida encerra o laço com o que já está provado
  em vez de insistir. Esperar de verdade (conexão, ritmo do provedor, pergunta ao usuário)
  não é laço.
- **Entrega parcial honesta**: se o laço for encerrado antes da conclusão, preservar o melhor
  resultado verificável, distinguir artefato utilizável com ressalvas de falha bloqueante, e
  nunca chamar um resultado parcial de completo.
- **Validação de schema/contrato**: entrada e saída estruturada são validadas contra um
  contrato explícito antes de seguir adiante.
- **Sintaxe e integridade de arquivo**: uma edição/gravação só é aceita se preservar a
  integridade sintática do que já existia.
- **Proteção contra operação destrutiva e portão de aprovação**: com a aprovação ligada, qualquer ação irreversível
  (apagar, sobrescrever, enviar, publicar, gastar) exige aprovação explícita antes de executar, nunca só depois e nunca
  implícita, e a confirmação mostra tudo o que vai mudar. Com a aprovação desligada pela pessoa, o agente segue sem pedir,
  inclusive nessas ações (decisão do dono em 17/out/2026). O que nunca entra na chave de aprovação: a honestidade da
  plataforma (nunca enfraquecer a verificação que acabou de reprovar o trabalho) e nunca gravar segredo. Fora da pasta de
  trabalho, com a aprovação desligada, o agente segue (decisão do dono, 20/out/2026).
- **Registro de evento e recuperação de falha**: toda decisão de permissão, erro e retry fica
  auditável; uma falha parcial deve poder ser retomada sem repetir trabalho já provado.
- **Escalonamento para humano**: quando a ambiguidade for material ao resultado ou a ação for
  de alto risco, o harness garante que existe um caminho real de parar e perguntar — a decisão
  de *quando* perguntar continua sendo da IA, o harness só garante que o caminho existe e
  funciona.

### O que nunca vira regra fixa

**Nunca** transformar uma decisão subjetiva (intenção, se uma tarefa está clara o bastante,
qual ferramenta "parece" certa, se uma resposta "parece" completa, quanto tempo uma tarefa
"deveria" levar) em árvore fixa de palavras-chave/regex/condição/relógio — isso é determinismo
em excesso disfarçado de segurança, e é exatamente o tipo de regressão que trava um agente sem
de fato protegê-lo. Uma regra determinística nova só é aceitável quando protege um dos itens
da lista acima ou valida um **fato objetivo e verificável** (ex.: uma URL literalmente
presente no texto, um limite de tamanho, um schema) — nunca para "deixar o comportamento mais
previsível" ou "fazer um teste passar mais fácil". Ao escrever ou revisar um teste: se ele
exige que o código adivinhe ou force uma categoria de intenção por palavra-chave em vez de
deixar o modelo julgar, o teste está pedindo o tipo errado de determinismo — não aceitar.

### Comportamento conversacional obrigatório

Em qualquer chat/execução: narrar cada ferramenta em linguagem natural (nunca nome técnico
cru, nunca JSON/protocolo bruto na interface); nunca entregar só no final de uma tarefa longa;
permitir interromper, corrigir ou redirecionar uma execução em andamento sem perder o
progresso já feito; perguntar cedo quando a ambiguidade for material ao resultado, em vez de
assumir em silêncio ou travar sem convergir.

### Calibração de supervisão humana

Um agente de produção não roda nem totalmente livre nem totalmente supervisionado: o
harness garante que existe intervenção humana exatamente onde o risco é maior (ações
irreversíveis, escopo ampliado, ambiguidade material) e fica fora do caminho no resto —
supervisão constante em toda ação de baixo risco é tão errado quanto autonomia total em
ação de alto risco.
