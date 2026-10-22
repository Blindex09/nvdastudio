---
paths:
  - "addon/globalPlugins/nvdastudio/ai/**"
  - "addon/globalPlugins/nvdastudio/core/**"
---

# Economia, qualidade, roteamento e engenharia de contexto (regra 9)

> Texto integral, sem mudança.

### 9. Economia, qualidade e roteamento inteligente

- Economia e qualidade são pilares: sempre inteligência, qualidade, performance, precisão, foco e economia de tokens.
- O roteador é inteligente, econômico e equilibrado. O melhor modelo não é o maior; é o que entrega com qualidade
  gastando menos. Modelos maiores só para o que é pesado, subindo aos poucos conforme o roteador decide.
- O classificador escolhe pelo significado o modelo, as skills e os especialistas. Os modelos não são fixos: cada
  tarefa vai para o modelo certo, e o mesmo comportamento vale para todos os modelos do roteamento automático
  (ajustando o que cada um espera). O vencedor nunca é fixo por nome, ordem ou palavra-chave. Quando a qualidade
  merece o custo extra, o roteador pode consultar mais de um candidato e pedir uma síntese julgada; tarefa simples usa
  uma única chamada, e se o julgamento falhar fica a melhor resposta verificável já obtida.
- Quanto o modelo pensa antes de agir também é decisão do roteador, pelo significado da tarefa, na mesma chamada em
  que ele decide a estratégia (sem chamada extra): pouco quando o caminho é claro e o trabalho é fazer, mais quando há
  decisão difícil de verdade, subindo sozinho quando uma etapa falha. Nunca pensar sem limite por falta de escolha:
  pensamento a mais faz a pessoa esperar minutos e é pago em toda chamada. Se a pessoa escolheu um nível, vale o dela.
- Exploração (decisão do dono, 22/out/2026): o roteador escolhe entre todos os modelos do provedor por evidência (taxa de sucesso, latência, custo, o que cada um oferece), sem lista de nomes. Um modelo sem evidência naquele tipo e camada recebe um bônus que diminui conforme as tentativas crescem (nenhum na camada profunda, onde errar custa mais: ali só a evidência decide), para que todos sejam experimentados e o roteador aprenda. O que cada modelo recebe de raciocínio e de capacidades é só o que ele oferece.
- Executa várias ferramentas ao mesmo tempo quando isso ajuda; especialistas independentes rodam em ondas, e o
  progresso é emitido conforme cada um termina. A economia nunca esconde uma etapa que o relatório apresenta como
  concluída.
- Não refaz trabalho: cada etapa recebe o resultado das anteriores, e fatos já provados são reaproveitados.
  Compactação de conversa é decidida pela IA, não por heurística.
- Não existe modelo padrão embutido: o padrão é a última escolha da pessoa em cada provedor.

Engenharia de contexto (vale para todo módulo, toda interface e todo laço que chama um modelo):

- Nada é reenviado ao modelo sem necessidade. Todo laço que acumula histórico (resultados de ferramentas, conteúdo de
  arquivos gravados ou lidos, saídas de comando, conversa) tem de ter um jeito de aliviar esse histórico; um laço em
  que o contexto só cresce é defeito, mesmo que a tarefa termine.
- Quem decide é a IA: o código só mede o tamanho (um fato) e, quando ele cresce, convida o modelo a organizar a
  própria memória de trabalho. O modelo escolhe o que ainda precisa ver palavra por palavra e escreve, com as
  palavras dele, a nota que fica no lugar do resto. Se decidir manter tudo, fica tudo.
- Nada se perde: o que sai do contexto é guardado inteiro antes e volta por um identificador, com uma ferramenta que
  o modelo tem à mão. Sem esse caminho de volta, não se tira nada. Arquivo já gravado é memória: guarda-se o caminho e
  relê-se quando preciso, em vez de carregar o conteúdo.
- O começo de cada chamada (instruções e lista de ferramentas) fica estável de uma chamada para a outra e o
  histórico só cresce no fim, para o provedor reaproveitar o que já processou. Nada de hora, ordem que muda ou
  ferramenta que entra e sai no meio de uma tarefa.
- As ferramentas enviadas em cada chamada são as que a tarefa precisa, e quem julga isso é o roteador, pelo
  significado, na mesma chamada em que decide a estratégia. O código só tem o catálogo (quais ferramentas existem e
  de que grupo são). Sem opinião do roteador, vai tudo. Nada fica fora de alcance: um grupo que ficou de fora entra
  na hora em que o agente pedir ou usar uma ferramenta dele, e nunca sai no meio da tarefa.
- O pensamento do modelo só volta ao provedor junto da rodada ainda em aberto (a última fala dele, cujas
  ferramentas estão sendo respondidas). O pensamento de rodadas anteriores nunca é reenviado: a pessoa continua vendo
  na área recolhida, mas ele não entra de novo em cada chamada.
- Chamadas auxiliares (classificador, roteador, checagens de escopo e de segurança, revisões) vão no modelo mais
  barato que dá conta, recebem só o que precisam para julgar e nunca se repetem para a mesma pergunta. O que elas
  gastam é medido por tipo de chamada e tem de ser uma parte pequena do total: coordenação e checagem que gastam mais
  do que o trabalho de verdade são defeito.
- Quem recebe trabalho delegado devolve o resultado resumido a quem coordena, não o histórico inteiro do que fez.
- Todo módulo novo mede antes de afirmar: quantos tokens cada tipo de chamada gasta e do que é feita a mais pesada.
  Economia é verificada com número de execução real, não suposta.
