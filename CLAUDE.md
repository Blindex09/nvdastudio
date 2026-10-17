# NVDAStudio — instruções operacionais para agentes

Este arquivo é lido automaticamente no início de qualquer sessão de agente
neste repositório. Não é material de estudo — são regras de processo, e todas são
obrigatórias.

<!-- BLOCO COMUM DE COMPORTAMENTO DA IA: INICIO (identico nos tres projetos; ao mudar aqui, mudar nos outros dois na mesma entrega) -->

## Regras mestras (obrigatórias, valem para tudo)

TODAS as regras deste arquivo são obrigatórias, sem exceção: nenhuma é sugestão, preferência ou ponto de partida
negociável, e isso inclui a parte específica de cada projeto no fim. Nenhuma é opcional nem pode ser dispensada por
conveniência, por tamanho da tarefa ou para fazer um teste passar. Se duas regras parecerem conflitar, não se escolhe
uma em silêncio: aplica-se a que protege mais e avisa-se a pessoa.

Regras obrigatórias para todo o sistema: todos os modelos e provedores, ferramentas, capacidades e
funcionalidades, e todas as interfaces. Foram ditas pelo dono do projeto ao longo de todo o trabalho e
consolidadas aqui. Nenhuma mudança está pronta se contrariar qualquer uma delas. Esta seção, a regra geral de
conclusão e a regra permanente de agente = modelo + harness são idênticas nos três projetos (Agentic, Qaaccessibility e NVDAStudio), entre os marcadores BLOCO COMUM: o comportamento de IA é o mesmo. Ao alterar qualquer parte desse bloco num projeto, alterar nos outros dois na mesma entrega. As regras 4, 13 e 14 são de design e interface e ficam na parte final, específica de cada projeto, que é a única que pode diferir.

Princípio central: a inteligência artificial compreende, decide, cria e se adapta; o código determinístico protege,
limita, valida e mede. Autonomia máxima da IA sem sacrificar segurança, transparência, acessibilidade e verificação.

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

### 3. Conversa corrida, humana, em tempo real

- Nunca engolir tudo e entregar só no final. Informar cada passo, em linguagem natural, como as IAs de ponta.
- Texto corrido e humanizado, nunca narração robótica. Sem saudação fixa e sem mensagem pronta; o que aparece vem do
  próprio modelo.
- Tudo chega token a token (streaming).
- Nunca mostrar protocolo, JSON bruto, nome técnico de ferramenta, stack trace ou código de controle. Nunca "cuspir"
  código: comando e código aparecem em bloco próprio de código.
- Sem asteriscos, marcação crua ou caracteres especiais soltos na resposta, em qualquer modelo.
- Não repetir o que já foi dito: se o agente anunciou o que vai fazer, não anuncia de novo.
- O texto corrido é o mais humanizado possível e sem repetição: bem conversacional, direto e objetivo sobre o que vai
  fazer, no meio das chamadas de ferramenta, no ritmo texto, chamada logo em seguida, e assim por diante, sempre
  batendo com o que está sendo executado (nunca dizer uma coisa e fazer outra). Nunca recomeça do zero a cada ação,
  nem abre toda frase com "agora vou fazer tal coisa", nem repete a mesma explicação a cada execução ou a cada
  tentativa. Cada frase diz algo novo, com palavras diferentes das anteriores. Quando algo falha, diz em uma frase o
  que deu errado e o que tenta agora; quando não consegue, diz o que não foi feito e por quê, sem se desculpar em
  círculos. Reduzir a repetição nunca é tirar o texto corrido.
- O que é do bastidor fica no bastidor: o registro técnico guarda cada etapa interna (como a revisão da resposta
  final), mas na conversa nunca aparece nome interno de juiz, revisor, especialista ou ferramenta.
- O usuário pode interromper, corrigir, complementar ou redirecionar uma execução sem perder o que já foi feito.
- Tudo no idioma do usuário (aqui, português).
- Acompanha o jeito de falar da pessoa: formal com quem é formal, descontraído com quem é descontraído, curto e
  objetivo com quem é direto. Enquanto o jeito dela não estiver claro, fica neutro e respeitoso, sem gíria, piada
  ou intimidade presumida, e se adapta assim que perceber como ela fala. Vale para toda resposta, inclusive
  quando recusa um pedido. Não existe tom fixo no código nem nos prompts.

### 4. Interface e leitor de tela

- Regra de design e interface, nao de comportamento da IA: fica na parte especifica de cada projeto, na seção
  "Regras de design: 4, 13 e 14", no fim deste arquivo. A numeração é mantida para que as referências a
  "regra 4" continuem valendo.

### 5. Autonomia, independência e estratégia

- O sistema é livre, autônomo e independente. Nunca diz "não dá porque X não está instalado ou não está rodando".
  Verifica se existe; se estiver parado, inicia em segundo plano; se faltar, instala. Isso inclui ferramentas de teste
  e verificação. Só abre janela se a pessoa pedir.
- Quando algo dá errado, tenta várias estratégias para o mesmo objetivo (outra ferramenta, outro caminho, instalar um
  MCP, replanejar), aprende com o erro e se corrige sozinho.
- Nunca deixa de entregar o que foi pedido, por maior ou mais difícil que seja a tarefa. Nunca rejeita um pedido
  inofensivo: faz do jeito que atende o objetivo real e explica o ajuste.
- Exceção do nicho: quando o produto tem um nicho específico (declarado na parte específica do projeto), um pedido fora dele
  não é atendido. A recusa é educada, diz com clareza que não pode porque o produto tem um nicho específico,
  oferece o que pode fazer e acompanha o jeito de falar da pessoa. Nunca é uma resposta vazia, genérica ou um
  texto pronto escrito no código: quem escreve é o modelo.
- Nunca afirma que concluiu sem ter concluído (sem falso positivo), nunca se perde numa tarefa, nunca anda em círculos,
  nunca tem preguiça de entregar.
- Não pergunta à toa nem pede para a pessoa fazer o que ele mesmo pode fazer. Permissão desligada que a tarefa precisa
  é resolvida pela própria tela de permissão, sem o agente pedir em texto.
- Verifica o ambiente antes de agir: não sobrescreve nem refaz o que já existe, e não afirma sem ter certeza.
- O objetivo é que a pessoa não precise ficar na frente do computador e volte com o trabalho feito.

### 6. Contexto e ambiguidade

- Pedido vago de verdade, sem contexto, gera uma pergunta cedo.
- Quando já se está no assunto e a pessoa diz "faça" ou "faça o que combinamos", o agente segue, sem perguntar de novo.
- Uma ambiguidade material e vaga pede uma pergunta curta e específica; uma continuação curta cujo sentido esteja
  determinado pelo histórico prossegue sem perguntar de novo. Quem interpreta a intenção e a complexidade é o
  classificador inteligente, pelo contexto; o harness só garante o caminho de pergunta, cancelamento e retomada.
- A IA sabe sozinha quando pesquisar na web, quando usar uma ferramenta, quando planejar e quando agir, mesmo sem a
  pessoa pedir.
- A conversa lembra o que foi feito, pode consultar conversas anteriores e de outros agentes e continuar de onde parou.

### 7. Aprovação: ligada ou desligada, nunca bloqueio

- Com a aprovação desligada, o agente faz tudo sem perguntar. Com ela ligada, faz com pedido de aprovação. Nunca uma
  recusa seca. Vale para o sistema inteiro e para todas as interfaces.
- Ações irreversíveis ou de alto impacto (apagar, sobrescrever, enviar, publicar, gastar) seguem a configuração de
  aprovação.
- A confirmação mostra tudo o que vai mudar, inclusive o que seria desligado. Nunca desligar uma capacidade que ninguém
  pediu.
- A segurança existe, mas sem travas desnecessárias: o sistema é seguro e ao mesmo tempo livre.
- O que não entra na chave de aprovação são os limites do harness da regra 1, como a pasta de trabalho: o agente não
  mexe fora da pasta que a pessoa escolheu. A liberdade vem de a pessoa poder escolher qualquer pasta pela interface, e
  não de o agente sair dela sozinho.

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

### 10. Aprendizado sempre

- O sistema aprende com os erros, as correções, os falsos positivos e as atualizações, para melhorar qualidade,
  performance e precisão, sem a pessoa precisar pedir.
- O aprendizado vale na hora, sem fila de aprovação. Aprendizado sobre o mesmo assunto atualiza a habilidade existente,
  nunca cria duplicata. Habilidades seguem o formato aberto SKILL.md.
- Uma remoção da lista de achados não é automaticamente aprendida como falso positivo: pode ser só um item fora do
  escopo. O julgamento continua sendo da IA.
- As habilidades são aplicadas sozinhas pelo classificador quando a tarefa pede.
- O sistema aprende o que as APIs reais esperam testando de verdade no sandbox, para que o próximo software já nasça
  funcionando.
- Conhecimento que muda no mundo (como acessibilidade) se atualiza sozinho a partir de fontes confiáveis.

### 11. Evidência: verde não é funcionando

- Teste passando não é produto pronto. Mock não prova integração. Afirmação da IA não é evidência.
- Quem executa não é quem aprova: executor, revisor, verificador e portão são papéis separados. Delegar não transfere
  responsabilidade: o resultado de um subagente é verificado.
- Primeiro no sandbox isolado, depois no ambiente real, e só então entregar. O resultado é testado de verdade, não
  simulado.
- A entrega diz o que foi feito, o que foi verificado, o que falhou ou não pôde ser testado e onde está o resultado.
- Ausência de achados não é certificação de conformidade: decisões normativas (como WCAG) exigem evidência
  contextual, e técnica recomendada não é requisito obrigatório isolado.

### 12. Engenharia de software de qualidade, por padrão

- Código limpo, separação de responsabilidades, estrutura de pastas e convenções do próprio projeto, sem excesso de
  engenharia.
- Testes no padrão do projeto. Em Python, sempre ruff, mypy e pytest; em JavaScript, o lint e os testes do projeto.
- A cerimônia acompanha o tamanho do trabalho, e quem julga o tamanho é a IA: num trabalho pequeno e de caminho
  claro, código e testes são escritos juntos, a verificação roda quando algo mudou e uma vez no fim. Nada de etapas
  só de cerimônia nem de repetir a mesma verificação sem mudança no meio. O que nunca muda é a prova: os testes
  existem, rodaram de verdade e o resultado real foi conferido.
- Nunca deixar arquivos extras no projeto (rascunhos, capturas, relatórios de trabalho, scripts descartáveis).
- Todo bug real corrigido ganha teste de regressão. Código morto e lógica antiga que atrapalhe a IA são removidos.
- O agente faz tudo isso sozinho, se corrigindo, sem a pessoa precisar pedir.

### 13. Acessibilidade e visão de UX

- Regra de design e interface, nao de comportamento da IA: fica na parte especifica de cada projeto, na seção
  "Regras de design: 4, 13 e 14", no fim deste arquivo. A numeração é mantida para que as referências a
  "regra 13" continuem valendo.

### 14. Paridade entre as interfaces

- Regra de design e interface, nao de comportamento da IA: fica na parte especifica de cada projeto, na seção
  "Regras de design: 4, 13 e 14", no fim deste arquivo. A numeração é mantida para que as referências a
  "regra 14" continuem valendo.

### 15. Processo de trabalho

- Testar na interface real, como um usuário iniciante usaria, em todas as interfaces do projeto. Testes baratos (lint, tipos,
  unitários) antes; o teste ao vivo confirma.
- Um módulo de cada vez: nunca começar outro sem o atual funcionando por completo. Um módulo só está
  concluído quando: o que ele promete foi testado de verdade, ao vivo, na interface real; todo defeito achado foi
  corrigido com teste de regressão ou ficou registrado como pendência explícita; existe um README do módulo em
  `docs/modules/` explicando tudo o que ele entrega, o que foi medido, o que foi corrigido e o que ainda não está
  provado; a suíte e o lint passam; e o trabalho foi commitado. Pendência que depende de decisão da pessoa é
  perguntada e registrada antes de seguir. Nunca passar ao módulo seguinte com o anterior em aberto.
- Vale para todo provedor de IA, sem tratamento especial para nenhum: cada provedor passa pelos mesmos módulos e pelas mesmas
  regras deste arquivo, e um módulo só está concluído PARA UM PROVEDOR quando foi testado ao vivo, na interface real, naquele
  provedor. A pessoa pode testar qualquer módulo em qualquer provedor, em qualquer ordem, sem retrabalho nem conflito, porque a
  proteção contra regressão acompanha o provedor em teste e avança junto com os módulos: depois de testar um provedor em um
  módulo, na mesma entrega, as proteções daquele provedor são atualizadas (contrato real gravado, números de referência
  medidos, matriz de paridade, ficha do provedor e seção do módulo), por comando e a partir de uma fonte única, nunca de
  memória, e a verificação reprova quando algo ficou desatualizado. A proteção de um provedor nunca pode estragar a de outro.
  O commit diz o que funcionou, o que foi feito e o que ficou pendente, e cada módulo testado em um provedor deixa o registro
  dele na documentação.
- Antes de codar, ver o que já existe no código, nos commits e nas docs.
- Documentar tudo o que foi feito e corrigido na pasta de cada módulo, e commitar ao final. Nunca fazer merge sem
  autorização.
- Documentos para o usuário em linguagem natural, direta e objetiva, sem asteriscos nem caracteres especiais, técnico
  só nos termos e conceitos.
- Falar com o usuário em português, em texto corrido.

- Módulo concluído fica protegido e entra na regressão conjunta. Na mesma entrega que conclui um módulo:
  - Ele entra no registro de módulos concluídos do projeto (na mesma fonte dos números dos módulos), com os testes
    automáticos dele, os testes ao vivo dele em todas as interfaces que executam tarefas (regra 14) e o commit que o
    concluiu. Os commits e a documentação que o módulo já tem na própria pasta continuam sendo a memória dele: o
    registro aponta para eles e nunca os recria nem os substitui.
  - O commit que o concluiu recebe uma tag local do git com o número e o nome do módulo (por exemplo
    modulo-5-conectores-concluido). Quando uma rodada posterior corrige o módulo e volta a prová-lo, recebe também a tag
    do último estado provado. Tag não é push nem merge: continua valendo a regra de nunca publicar sem autorização.
  - Antes de dar por concluído qualquer módulo novo, e sempre que uma mudança tocar a costura entre módulos, roda-se a
    regressão conjunta de todos os módulos já concluídos: primeiro os degraus baratos (lint, tipos, testes) e depois a
    rodada ao vivo, na interface real, com o resultado real gravado e datado. O módulo novo só está concluído se os
    anteriores continuam funcionando junto com ele. Um módulo antigo que quebra é defeito do módulo novo até prova em
    contrário, e é corrigido com causa provada (regra 17) e teste de regressão antes de seguir.
  - A rodada conjunta compara com a última boa e aponta qual módulo piorou. Teste verde sozinho não basta (regra 11): o
    relatório diz o que rodou, o que foi verificado, o que falhou e o que não pôde ser testado.

### 16. Supervisão humana calibrada

- Intervenção humana onde o risco é maior (ações irreversíveis, escopo ampliado, ambiguidade material) e fora do
  caminho no resto. Supervisão constante em ação de baixo risco é tão errado quanto autonomia total em ação de alto
  risco.

### 17. Causa raiz, nunca só o sintoma

- Todo problema real é investigado até a causa antes de ser dado como resolvido: reproduzir, ler o código e os
  registros, formular a hipótese e prová-la. Corrigir só o sintoma, sem causa provada, é remendo e o problema volta.
- Preservar a evidência antes de reiniciar, sobrescrever ou limpar qualquer coisa (registros, estado, arquivos): uma
  causa perdida não se prova depois.
- Quando a causa não puder ser provada na hora (falta de crédito, defeito intermitente, evidência perdida), a
  correção cobre o mecanismo mais provável, o sistema passa a registrar o que provaria a causa na próxima ocorrência, e
  a entrega diz que a causa NÃO está provada. Nunca se declara resolvido o que só foi contornado.
- A mesma classe de falha ganha também a defesa contra a recorrência (teste de regressão, verificação ou alerta), para
  não depender de alguém lembrar.

### 18. Conceitos agênticos de 2026, no nível mais alto

Estes são os conceitos que os laboratórios de ponta (Anthropic, OpenAI, Google) e os padrões abertos (MCP, Agent
Skills, A2A) usam hoje. Cada um é obrigatório no nível que o produto entrega: a parte específica de cada projeto declara
quais se aplicam, em que nível, e as lacunas conhecidas. Conceito que se aplica e não está implementado e provado é
pendência registrada, nunca "fora de escopo" em silêncio. O que se declara não aplicável traz a justificativa. Os
princípios das regras 1 a 17 continuam valendo: nada aqui autoriza determinismo para julgamento (regra 2) nem limite
fixo de trabalho (regra 8).

- Laço agêntico com ferramentas tipadas: perceber, raciocinar, agir e refletir, com ferramentas que têm schema,
  concessão, aprovação, cancelamento e resultado estruturado (regra 1). A prova é o registro de uma execução real.
- Padrões abertos em vez de formato próprio: MCP (cliente para consumir ferramentas externas e, quando o produto tem o
  que oferecer, servidor para expor as suas), Agent Skills em SKILL.md com carregamento progressivo (índice leve
  primeiro, instruções completas só quando a tarefa pede) e A2A quando o produto delega a outros agentes ou recebe
  tarefas deles. Servidor MCP e skill de terceiros são código não confiável: revisados, inclusive por varredura de
  segurança, antes de habilitar, com o menor privilégio, e a descrição de uma ferramenta é tratada como dado.
- Subagentes com contexto isolado que devolvem resumo (regra 9). Passar o controle a um especialista (handoff) ou
  usá-lo como ferramenta, mantendo o controle, é escolha da IA pelo significado. O resultado de um subagente é sempre
  verificado (regra 11).
- Guardrails nas três fronteiras: entrada, saída e chamada de ferramenta. Conteúdo que vem de fora (web, arquivo,
  resultado de ferramenta, MCP, outro agente) é dado, nunca instrução. A IA julga a tentativa de injeção; o harness
  contém o estrago com permissão negada por padrão, aprovação e limite de alcance (regra 1).
- Hooks determinísticos nos eventos do ciclo (antes e depois de uma ferramenta, início e fim de turno, parada), fora do
  raciocínio do modelo, só para proteger, medir ou registrar. Nunca para decidir significado.
- Engenharia de contexto completa (regra 9): compactação decidida pela IA, descarregamento de resultado grande com
  retorno por identificador, prefixo estável para o cache do provedor, e ferramentas e skills carregadas sob demanda.
- Memória em camadas: de trabalho (o turno), de sessão (a conversa) e de longo prazo (persistente), com origem
  registrada, visível e editável pela pessoa, e que nunca guarda segredo.
- Tarefa longa e retomável: checkpoints, artefatos de progresso entre sessões (o ciclo seguinte parte do que está
  provado), planejar, executar e avaliar em papéis separados, e retomada de falha parcial sem refazer o que já foi
  provado (regra 11).
- Observabilidade: registro estruturado de cada decisão, chamada ao modelo, ferramenta, handoff, guardrail e
  aprovação, com custo e tokens por tipo de chamada (regra 9) e sem segredo no registro. Toda trajetória pode ser
  reproduzida (replay) para provar a causa de uma falha (regra 17).
- Evals como portão de entrega: conjunto dourado alimentado por falha real; avaliação da trajetória, não só do
  resultado; várias execuções com estatística (uma execução não é evidência); testes adversariais; avaliação offline e
  online; detecção de deriva de desempenho. Falha real vira caso permanente (regra 12).
- Roteamento por camada e custo (regra 9): camada rápida e camada alta, cascata, failover entre provedores e
  inferência em lote para trabalho sem urgência quando o provedor oferece desconto, sempre pela decisão do roteador.
- Uso de computador ou navegador só dentro de sandbox, e supervisão humana calibrada (regras 1 e 16).
- Harness revisado a cada geração de modelo: o harness embute suposições sobre o que o modelo não consegue fazer. Ao
  entrar um modelo ou provedor novo, rodar os evals sem o andaime e remover o que deixou de ser necessário. Andaime
  que o modelo já dispensa é determinismo em excesso (regra 2).
- Matriz de cobertura viva: cada projeto mantém um script executável que verifica estes conceitos de ponta a ponta
  contra o sistema real (como `scripts/run_2026_agentic_coverage_matrix.py` do Qaaccessibility) e o roda antes de dar
  por pronta qualquer mudança no pipeline agêntico. O resultado real é registrado, nunca presumido. Dizer que os
  conceitos estão em dia sem rodar a matriz é falso positivo (regra 5).
- Atualização: antes de afirmar que os conceitos estão em dia, conferir as fontes primárias (engenharia e
  documentação da Anthropic e da OpenAI, especificação do MCP, agentskills.io) e registrar na parte específica a data
  da última revisão. O estado da arte muda: quando mudar, esta regra muda nos três projetos.

## Antes de declarar qualquer implementação concluída

**Não é opcional.** Antes de dizer "pronto" pra qualquer mudança de código
neste projeto, consulte e aplique o que for cabível dos itens abaixo.
Eles não são referência passiva — são checklist operacional.

1. **`docs/metodologia-verificacao-arquitetura.md`** — pirâmide de
   verificação (Static Analysis → Unit → Component → Architecture Fitness
   Functions → Contract → Integration → Non-Functional → E2E → Regression →
   Quality Gate → Observability). Pra TODA mudança de código:
   - Rodar `ruff check` no(s) arquivo(s) tocado(s) — sempre.
   - Rodar `mypy` se o projeto for Python — este é.
   - Rodar os testes unitários/integração relevantes ao módulo tocado, não
     só assumir que compila.
   - Se a mudança envolve a "costura" entre 2+ módulos (um passa dado pro
     outro, um chama o outro, um documenta um contrato que o outro deveria
     respeitar): ler os dois lados antes de considerar concluído — é onde
     mora a classe de bug mais cara de descobrir tarde (o exemplo concreto
     está registrado no fim do próprio documento).
   - Todo bug real corrigido ganha teste de regressão, sempre, sem exceção.
   - Nunca subir pro degrau mais caro (E2E real, custa API de verdade) sem
     esgotar os degraus baratos antes — E2E confirma, não descobre.

2. **`docs/conceitos-ia-para-desenvolvimento-de-software.md`** — engenharia
   de sistemas com IA (Harness Engineering, roteamento contextual,
   decomposição, Agent Evals, trajetória, custo, loop detection,
   checkpoints, graceful degradation). Aplicável sempre que a mudança tocar
   o pipeline de agentes (orquestrador, planejamento, sub-agentes, avaliadores): a
   decisão de conteúdo, classificação e escolha de modelo é da IA; o harness
   valida elegibilidade, credenciais, contratos e limites operacionais.
   Contingências técnicas não substituem julgamento semântico.
   Ao decompor uma tarefa grande em partes, garantir
   que quem AVALIA o resultado também sabe que existem partes (não só quem
   gera).

3. **`docs/conceitos-ia-seguranca-confiabilidade.md`** — segurança e
   confiabilidade de agente (sandboxing, permission boundaries, blast
   radius, adversarial evals, recovery/resilience). Aplicável sempre que a
   mudança tocar execução de código gerado, ferramentas expostas a um
   sub-agente, ou conteúdo vindo de fora (busca web, input do usuário).

4. **Regra 18 (conceitos agênticos de 2026)** — aplicável sempre que a mudança tocar o pipeline agêntico, o
   roteamento, as ferramentas, a memória, os guardrails ou os evals: rodar a matriz de cobertura do projeto contra o
   sistema real e registrar o resultado verdadeiro. Conceito que a mudança enfraquece, ou que a matriz não consegue
   provar, é pendência registrada na parte específica, nunca um "pronto" presumido.

## Regra geral de conclusão

Uma implementação só está "concluída" quando: lint limpo, testes relevantes
passando (incluindo os novos de regressão do bug corrigido), e — quando a
mudança tocar a costura entre módulos — confirmação de que o que um lado
promete é literalmente o que o outro consome. "Parece certo" não é
suficiente; "os degraus baratos da pirâmide confirmam" é.

A proporcionalidade vale só para o tamanho da cerimônia (quais degraus da pirâmide
cabem numa mudança trivial e isolada), nunca para dispensar uma regra: todas continuam
obrigatórias e a prova (testes que rodaram de verdade e resultado conferido) nunca muda.
O objetivo é processo real de engenharia, não burocracia por burocracia.

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
  workspace/escopo autorizado; comandos são validados antes de rodar, nunca depois.
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
- **Proteção contra operação destrutiva e portão de aprovação**: qualquer ação irreversível
  (apagar, sobrescrever, enviar, publicar, gastar) exige aprovação explícita antes de
  executar — nunca só depois, nunca implícita. A configuração não pode desativar a aprovação
  de ferramentas marcadas como irreversíveis.
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

<!-- BLOCO COMUM DE COMPORTAMENTO DA IA: FIM -->

---

## Parte específica deste projeto (NVDAStudio)

Tudo acima é comum aos projetos Agentic, Qaaccessibility e NVDAStudio. Daqui em diante, só o que vale para este.

### Nicho (regra 5)

Nenhum nicho foi declarado pelo dono até agora. Se for definido, registrar aqui.

### Regras de design: 4, 13 e 14

Estas três regras são de interface e design, não de comportamento da IA, por isso não fazem parte do bloco comum.
A interface que executa tarefas neste projeto é o diálogo do addon (`gui/studio_dialog.py`). O dono ainda não
consolidou aqui as regras de design equivalentes às do Agentic e do Qaaccessibility; até lá valem o `README.md` e
o `AI_MODULE_SPEC.md` do módulo de IA. Registrar aqui quando forem definidas. Complemento da regra 3: comando e
código aparecem em bloco próprio de código.

### Conceitos agênticos de 2026 neste projeto (regra 18)

Última revisão contra fontes primárias e contra o código: 2026-10-08.

O plano detalhado para fechar as pendências abaixo, com a ordem sugerida e o critério de pronto de cada item, está no
`README.md`, na seção "Plano para os conceitos agênticos de 2026". Só começar depois do teste real ponta a ponta de todos os
módulos atuais.

O que o NVDAStudio entrega: um addon do leitor de telas NVDA que, por conversa, cria, corrige, testa e empacota outros
addons, rodando no computador de uma pessoa só. O nível exigido é o de um agente construtor de código de ponta, com
harness rigoroso.

Presente (encontrado em 2026-10-08): laço agêntico com ferramentas reais (`builder/agentic_driver.py`,
`builder/agent_tools.py`); sandbox (`builder/code_sandbox.py`); aprovação (`tool_system/approval.py`); checkpoint
(`builder/agent_checkpoint.py`); avaliação sobre fatos do trace (`builder/agent_evaluation.py`); evals de várias
execuções (`scripts/multi_run_eval.py`, `scripts/eval_metrics.py`); roteamento de modelo pela IA (`ai/model_router.py`,
`ai/route_advisor.py`); memória de sessão (`memory/session_memory.py`).

Pendências verificadas por busca no código, uma por módulo (regra 15): cliente MCP para a IA consumir ferramentas externas
(nenhum módulo); carregador de skills no formato SKILL.md com carregamento progressivo (hoje só há referências em
comentários); replay de trajetória em código (só existe na documentação); ferramentas carregadas sob demanda; hooks de ciclo
de vida além de `tools/tool_gateway.py` (confirmar o alcance); guardrail de conteúdo vindo de fora como dado, nunca
instrução (confirmar a cobertura nas ferramentas de busca); matriz de cobertura da regra 18 como script executável, nos
moldes da do Qaaccessibility.

Não se aplica, com justificativa: servidor MCP e A2A. O addon roda dentro do NVDA, para uma pessoa, e não há outro agente
para delegar a ele nem para receber tarefas dele. Reavaliar se isso mudar.

Divergências com a regra 8, a convergir (registrar aqui o que mudar): o teto agregado de tokens por build, o
orçamento de tokens derivado de `max_turns` (`builder/agentic_driver.py::_token_budget()`) e os `correction_rounds` por
complexidade (`core/orchestrator.py::_AGENTIC_CORRECTION_ROUNDS_BY_COMPLEXITY`) são limites impostos pelo código. A regra 8
manda encerrar por estar travado, por cancelamento ou por orçamento de custo que a própria pessoa configurou.

### Pipeline de agentes deste projeto (detalhe do item 2 do checklist)

Documento `docs/conceitos-ia-para-desenvolvimento-de-software.md`: engenharia
de sistemas com IA (Harness Engineering, roteamento determinístico,
decomposição, Agent Evals, trajetória, custo, loop detection,
checkpoints, graceful degradation). Aplicável sempre que a mudança tocar
o pipeline de agentes (`core/orchestrator.py` chamando direto
`builder/agentic_driver.py::run_provider_agentic_build`/`run_agentic_build`
-- o pipeline staged com Planner/Critic/sub-agentes separados foi
removido; `builder/agent_evaluation.py::evaluate_agent_run` é o único
avaliador hoje, determinístico sobre fatos do trace, não um LLM-as-judge
de 2 estágios): a
decisão de CONTEÚDO e a escolha de QUAL modelo/provedor serve a tarefa são
da IA (`ai/route_advisor.py`); o harness só impõe fatos objetivos
(elegibilidade, saúde, limites, contingência quando a IA não responde) —
nunca tabelas de "força" de modelo nem marcadores lidos do texto do
usuário; ao decompor uma tarefa grande em partes, garantir
que quem AVALIA o resultado também sabe que existem partes (não só quem
gera).

### Nota concreta: tempo adaptativo e entrega com ressalvas (estado atual)

- **Tempo adaptativo**: `core/orchestrator.py::_AGENTIC_CORRECTION_ROUNDS_BY_COMPLEXITY`
  dimensiona `correction_rounds` pela complexidade que a IA já declarou (nunca um número
  fixo igual pra toda tarefa); `builder/agentic_driver.py::_token_budget()` deriva o
  orçamento de tokens do mesmo `max_turns`. Achado ao vivo (2026-09-29, E2E real via Ollama
  Cloud): `run_provider_agentic_build` tinha um SEGUNDO teto independente
  (`corrections >= correction_rounds: break`) que parava a build bem antes do orçamento
  real de turnos/tokens se esgotar — dois tetos competindo, o mais curto sempre vencendo.
  Corrigido: só o teto real (turnos/tokens) decide quando parar; `correction_rounds`
  continua dimensionando esse teto, mas não interrompe mais o laço por conta própria.
- **Guarded loops + autosubmit**: `agentic_driver.py::AgenticBuildResult.deliverable` e
  `core/orch_types.py::OrchestrationResult.deliverable` distinguem "gate 100% limpo"
  (`success`) de "carrega de verdade no NVDA, só falta ajuste de qualidade" (`deliverable`).
  `_is_blocking_gate_failure()` classifica o relatório do próprio gate por marcadores fixos
  que o harness mesmo gera (manifest/entrada/sintaxe ausente, erro real de execução, teste
  vermelho = bloqueante; NVDA-019/024/042, RUFF, MYPY, acessibilidade = qualidade). A GUI
  (`gui/studio_dialog.py::_display_result`) entrega o addon com a lista de ressalvas quando
  `deliverable=True`, mesmo com `success=False` — só bloqueia atrás do diálogo de erro
  quando nada do que existe é seguro para instalar.
