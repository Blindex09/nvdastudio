---
paths:
  - "addon/globalPlugins/nvdastudio/core/**"
  - "addon/globalPlugins/nvdastudio/builder/**"
  - "addon/globalPlugins/nvdastudio/ai/**"
---

# Tempo, tokens, chamadas e laços (regra 8 e nenhuma tarefa fica presa)

> Texto integral, sem mudança.

### 8. Tempo, tokens e chamadas adaptativos, decididos pela IA

- Nenhum relógio fixo e nenhum limite fixo de tokens, de chamadas ou de etapas, imposto pelo código, encerra uma tarefa
  em andamento. Não existe prazo, deadline, teto de tempo, teto de tokens nem máximo de ações, fixo ou calculado de
  antemão, que corte uma execução que continua progredindo.
- Quanto tempo, quantos tokens e quantas etapas uma tarefa precisa é decisão da IA (o classificador e o modelo), pelo
  significado da tarefa e pelo que acontece na execução, e nunca uma conta determinística. Tarefa grande leva o que
  precisar enquanto avança. Se algum teto for atingido, isso é defeito de dimensionamento, não comportamento esperado.
- O plano que o modelo fez é mantido inteiro, nunca cortado num número fixo de etapas. Nunca se promete ao modelo um
  "máximo de N ações" nem se molda o plano por um orçamento de ações. O código só confere, de tempos em tempos, se
  algo novo aconteceu (uma etapa concluída ou uma ação nova e diferente). O que quem recebe trabalho delegado faz
  conta para o custo, nunca contra quem coordena.
- Economia: aproveitar a chamada que já existe. Nunca abrir uma chamada nova para ver tudo de novo, varrer tudo outra
  vez ou passar por tudo de novo para concluir: isso gasta muito. Cada etapa parte do resultado das anteriores e do que
  já está provado, e o que já foi lido, medido ou concluído não se refaz.
- Compactação: quando o contexto cresce, o classificador decide sozinho, pelo significado, se e quando resumir a
  conversa, e resume sem perder nada: o que sai do contexto é guardado inteiro e volta por um identificador (regra 9,
  engenharia de contexto). Nunca por contagem fixa, nem por heurística, nem sem caminho de volta.
- Comando lento não é morto: passado o tempo esperado, segue em segundo plano e o agente pode esperar ou parar.
  Chamada ao modelo que demora é tentada de novo com mais tempo e o mesmo nível de raciocínio.
- Depois de um tempo esgotado, a nova tentativa continua esperando a mesma chamada que já está em andamento, com mais
  paciência; nunca abre uma chamada nova por cima da antiga (seria trabalho e custo duplicados).
- Tempo esgotado, queda de conexão e limite de ritmo do provedor não são laço: esperam de verdade e fazem as chamadas
  se revezarem.
- O que encerra é estar travado (sem progresso, repetindo a mesma ação), o cancelamento pela pessoa, ou um orçamento de
  custo que a própria pessoa configurou de forma explícita (escolha dela, nunca um limite embutido no código).
- Vale também para testes, scripts e verificações: nenhum relógio fixo por cima do sistema. O teste espera o fim que o
  próprio sistema decide e só para se o aplicativo deixar de responder.
- Se a execução for interrompida (cancelamento, orçamento de custo da pessoa, trajetória que deixou de convergir),
  preserva-se o melhor resultado verificável e a entrega parcial é honesta: distingue artefato utilizável com
  ressalvas de falha bloqueante, e nunca chama resultado parcial de completo.

- Nenhuma tarefa fica presa em nada. Obrigatório, sem exceção, para todo laço, repetição, correção, portão, verificação,
  espera, delegação e retomada, em todos os modelos e interfaces:
  - Todo laço tem um fim real, que não é relógio nem contador de limite: convergência, falta de progresso, repetição da
    mesma decisão ou da mesma exigência, cancelamento pela pessoa, ou orçamento que a própria pessoa configurou. O freio por
    repetição compara o que importa (a mesma exigência voltando, nenhuma evidência nova registrada na rodada), nunca a
    igualdade exata de um texto que muda um pouco a cada volta.
  - Um portão ou exigência do harness nunca pode pedir o impossível. Se o trabalho não tem como satisfazer a exigência (por
    exemplo, pedir servidor e navegador para um programa de linha de comando), quem decide se ela se aplica é a IA, pelo
    significado; o código só aplica o que ela decidiu. Um portão que reprova sem poder ser cumprido é defeito do portão,
    nunca da tarefa.
  - A IA que decide continuar não é freio suficiente: a decisão de seguir com nada de novo, voltando pela terceira vez, é
    encerrada pelo harness com o que já está provado (entrega parcial honesta).
  - Todo laço novo nasce com um teste de regressão em que a IA responde sempre "siga" e a exigência nunca é cumprida: o
    teste prova que mesmo assim o laço termina.
  - Execução com gasto muito fora do normal (milhares de chamadas ou milhões de tokens numa tarefa simples) é sinal de
    laço: as rodadas ao vivo registram o gasto de cada tarefa e o relatório destaca o que fugiu do normal. Esse sinal abre a
    investigação de causa (regra 17); parar a rodada para não gastar mais é permitido, desde que a evidência seja preservada
    antes.

- Laço dentro de laço (achado de 20/out/2026): quando o laço de dentro termina porque estava preso (a IA mandou encerrar, ou a proteção contra repetição do harness encerrou), esse desfecho é um fato que sobe para o laço de fora, e o mesmo desfecho voltando pela segunda vez seguida encerra o laço de fora com o que já está provado. Sem isso, "encerrar" acabava só a volta de dentro e o laço de fora recomeçava outra, sete vezes seguidas. O revisor reescrever a objeção a cada volta não reinicia essa contagem. Todo laço de fora que chama um laço de dentro herda esta regra, e nasce com um teste em que o de dentro termina sempre preso e o revisor sempre pede algo diferente.

## Ordem de recuperação diante de um laço ou de uma chamada travada (decisões do dono, 21/out/2026)

Complementa a regra 8, sem mudar o texto acima. A rede de segurança (a mesma decisão sem nada novo pela terceira vez é encerrada) é o ÚLTIMO recurso e deve ser muito rara; antes dela o agente se resolve sozinho, sempre nesta ordem: (1) o harness diz ao modelo só o fato, sem dizer o que fazer; (2) o raciocínio sobe e o roteador leva a chamada para outro modelo do provedor (o que travou fica por último), só enquanto estiver travado; (3) o agente recomeça uma vez por etapa com o contexto reorganizado (nada se perde, volta por identificador); (4) só então a rede encerra, com entrega parcial honesta que diz onde parou e o que foi tentado. Com a pessoa acompanhando a execução (fato objetivo: há uma tela aberta seguindo aquela execução) a rede não encerra: o agente diz em uma frase que travou, o que já fez e o que tentou, e espera a pessoa redirecionar ou cancelar, sem relógio nenhum; essa espera não é laço. Sem ninguém acompanhando (tarefa agendada, tela fechada, ou a tela fechou durante a espera) a rede encerra, com a entrega parcial. Progresso se mede por trabalho de verdade (criar, editar, verificar), não por atividade. Chamada ao modelo: conexão viva e lenta espera; conexão morta (silêncio entre pedaços) é descartada e refeita em outro modelo do mesmo provedor. Nenhum relógio corta uma tarefa que avança: o único tempo aqui mede a conexão, nunca a tarefa.
