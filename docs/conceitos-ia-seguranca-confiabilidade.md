# Segurança e confiabilidade de agentes de IA

> Documento de referência pessoal (Felipe), com base em práticas atuais de
> segurança e confiabilidade de agentes de IA em 2026. Guarda os conceitos
> pra reuso em qualquer projeto futuro — terceiro eixo, separado
> deliberadamente de `conceitos-ia-para-desenvolvimento-de-software.md`
> (Engenharia de Sistemas com IA) e `metodologia-verificacao-arquitetura.md`
> (Verification & Testing Engineering). Este cobre especificamente
> **Agent Security & Reliability Engineering** — isolamento, permissões,
> ataque adversarial, e recuperação de falha.
> Criado em 2026-08-09.
> Revisado em 2026-08-18 pra remover exemplos concretos amarrados a um
> projeto específico — o documento passa a ser puramente conceitual, como os
> outros dois eixos, e cada projeto que o usar deve mapear os conceitos
> contra o próprio código na hora de aplicar, não herdar exemplos de outro
> lugar.

## Por que separado dos outros dois documentos

Os outros dois eixos (verificação e engenharia de sistemas) tratam de
"o sistema funciona certo?". Este eixo trata de uma pergunta diferente:
**"o que acontece quando o sistema encontra algo hostil, ou quando algo dá
muito errado?"** — são preocupações genuinamente distintas o suficiente pra
merecer vocabulário e disciplina próprios, em vez de ficarem diluídas dentro
de "mais um tipo de eval".

## 1. Sandboxing / Isolation

Rodar código/ferramentas gerados por IA num ambiente ISOLADO do processo
principal — sem acesso à rede, ao sistema de arquivos real, ou a processos
do usuário, a menos que explicitamente permitido. Isolation é o que torna
seguro executar código de verdade (seção 5 do documento de engenharia de
sistemas) em vez de só analisar sintaxe. Formas concretas: subprocesso
separado sem herdar rede/filesystem do processo pai, container descartável,
VM efêmera, WASM sandboxed — a técnica muda por stack, o princípio não.

## 2. Permission Boundaries / Least Privilege

Um agente (ou uma ferramenta que ele controla) só deve ter acesso ao MÍNIMO
necessário pra cumprir a tarefa — nunca acesso amplo "por via das dúvidas".
Cada nova capacidade (rede, arquivo, execução) deveria ser um limite
explícito, documentado, não um padrão aberto que se restringe depois. Na
prática: uma camada que intercepta toda chamada de ferramenta e decide, por
regra explícita, se aquela ferramenta com aqueles argumentos é permitida
antes de executar — não confiar que o modelo "só vai pedir o que precisa".

## 3. Blast-Radius Containment

Quanto mais capaz um agente fica, maior o dano potencial se ele fizer algo
errado (por erro genuíno ou por ataque). **Blast radius** é o tamanho desse
dano potencial — a disciplina de contê-lo significa desenhar o sistema pra
que uma decisão ruim do agente afete o MÍNIMO possível (um sandbox isolado,
um único arquivo temporário, uma única sessão) em vez de poder se propagar
pro sistema inteiro. Isolation (item 1) e Least Privilege (item 2) são as
ferramentas concretas que reduzem blast radius na prática. Checkpoints
restauráveis antes de uma mutação arriscada são outra: se o raio de dano
máximo é "posso desfazer isso com um clique", o blast radius real de
qualquer ação fica pequeno por construção.

## 4. Adversarial Evals / Fault Injection

Já introduzidos em `conceitos-ia-para-desenvolvimento-de-software.md` seção
16 — aqui é onde pertencem de fato: testar deliberadamente contra ataque
(prompt injection, tool misuse, input não-confiável) e contra falha injetada
de propósito (timeout forçado, resposta malformada, erro de API simulado),
pra confirmar que o sistema degrada com segurança em vez de quebrar feio ou
executar algo perigoso.

**Prompt Injection** merece destaque à parte: conteúdo EXTERNO (resultado de
busca web, conteúdo de arquivo, saída de ferramenta) pode conter texto que
tenta se passar por instrução do sistema/usuário. A defesa nunca é uma
blacklist de palavras — é tratar todo conteúdo externo como DADO, nunca como
instrução, por padrão arquitetural, independente de vocabulário específico.

## 5. Recovery / Resilience

O que o sistema faz DEPOIS que algo deu errado — não só "detectar a falha",
mas voltar a um estado consistente e seguro. Conceitos já cobertos noutros
documentos que pertencem também aqui: **Loop Detection** (comparar a
assinatura do erro entre tentativas consecutivas e parar de insistir num
erro repetido, em vez de só contar tentativas), **Graceful Degradation**
(entregar o que funcionou em vez de descartar tudo quando um pipeline de
múltiplos estágios falha parcialmente), **Checkpoints informacionais**
(avisar o que está acontecendo sem travar o pipeline esperando aprovação, só
usado quando o humano tem acesso fácil ao histórico pra revisar depois). A
diferença de enquadramento aqui: tratar esses mecanismos explicitamente como
camada de RESILIÊNCIA A FALHA, não só UX/eficiência — a mesma lógica que
evita desperdício de tokens também evita que uma falha em cascata piore uma
situação já ruim.

## Como aplicar isso num projeto concreto

Este documento é intencionalmente genérico. Pra aplicar num projeto real:
1. Pra cada um dos 5 conceitos, perguntar "onde no meu código isso já existe,
   mesmo que sem esse nome formal?" — a maioria dos projetos maduros já tem
   pedaços disso espalhados sem ter sido nomeado.
2. Marcar explicitamente o que NÃO existe ainda, como candidato a fix, em vez
   de assumir cobertura por analogia com outro projeto.
3. Nunca copiar exemplo de código de um projeto pra documentação de outro —
   é exatamente o erro que motivou a revisão de 2026-08-18 deste documento.
