---
paths:
  - "addon/globalPlugins/nvdastudio/gui/**"
  - "addon/globalPlugins/nvdastudio/ai/**"
---

# Conversa corrida e interface (regras 3, 4, 13 e 14)

> Carrega quando se mexe na interface, nos chats ou na apresentação das respostas. Texto integral, sem mudança.

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
- A frase antes de cada ação não pode depender de o modelo querer (achado de 20/out/2026: um modelo que o roteador escolheu não escreveu frase
  nenhuma em 48 rodadas, nem com a instrução no sistema nem na descrição da ferramenta). As ferramentas que executam ação levam um argumento
  obrigatório de explicação, uma frase natural escrita pelo modelo, e a interface a mostra no lugar do texto quando o modelo não escreveu outro.
  O harness só mostra o que o modelo escreveu; nunca escreve a frase. Com a frase no argumento, o mesmo modelo preencheu 24 de 24 rodadas.
- O que é do bastidor fica no bastidor: o registro técnico guarda cada etapa interna (como a revisão da resposta
  final), mas na conversa nunca aparece nome interno de juiz, revisor, especialista ou ferramenta.
- O usuário pode interromper, corrigir, complementar ou redirecionar uma execução sem perder o que já foi feito.
- Tudo no idioma do usuário (aqui, português).
- Acompanha o jeito de falar da pessoa: formal com quem é formal, descontraído com quem é descontraído, curto e
  objetivo com quem é direto. Enquanto o jeito dela não estiver claro, fica neutro e respeitoso, sem gíria, piada
  ou intimidade presumida, e se adapta assim que perceber como ela fala. Vale para toda resposta, inclusive
  quando recusa um pedido. Não existe tom fixo no código nem nos prompts.

### Regras de design: 4, 13 e 14

Estas três regras são de interface e design, não de comportamento da IA, por isso não fazem parte do bloco comum. A
numeração é mantida porque o restante do projeto as cita. Complemento da regra 3: comando e código aparecem em bloco
próprio de código, com botão de copiar.

### 4. Interface e leitor de tela

- Ações em andamento aparecem no presente e viram passado ao terminar, na mesma linha: "pensando" vira "pensou por
  Xs", "executando" vira "executou", "lendo" vira "leu", "navegando em site" vira "navegou em N sites". Nunca repetir
  "executou" ou "pensou" duas vezes: vale só a última.
- Essas mensagens curtas ficam no meio da conversa, como o modelo falando, sem cabeçalho H2 e sem URL bruta (só o nome
  do site).
- O pensamento do modelo vai para uma área recolhida, com o texto do próprio modelo em linguagem natural.
- A resposta final de cada turno ganha o cabeçalho H2 ("NVDAStudio disse"). Um
  subitem que a IA traz também aparece como H2.
- Nada é falado automaticamente pelo leitor de tela, exceto a mensagem final, que é falada sozinha mesmo depois de uma
  execução longa. O resto se lê navegando com as setas.
- Mensagens da pessoa têm os botões copiar e editar. Blocos de código têm o botão copiar (que copia de verdade e
  anuncia "código copiado"), mostrado depois de "ver o comando executado".
- Mensagens de espera ("aguardando o provedor há Xs") atualizam no lugar, sem repetir e sem H2.
- Imagem enviada ou gerada é sempre transcrita na interface; imagem gerada aparece com link pelo nome da imagem e a
  transcrição logo abaixo, sem frase do tipo "gerei a imagem".
- Documentos citados aparecem como link local que abre ou baixa com Enter.

### 13. Acessibilidade e visão de UX

- O sistema é feito para todos, e pensar em quem usa leitor de tela é obrigatório em todos os módulos, sem exceção:
  é o que o diferencia. Em toda entrega ele executa e testa de verdade como uma pessoa que usa leitor de tela e só
  teclado usaria; revisar o código não basta.
- Acessibilidade é obrigatória em tudo: interface, código, arquivos, edição, engenharia, documentos (Word, PDF) e
  imagens. Nunca a acessibilidade genérica: aprendida, atualizada e testada como uma pessoa real usaria.
- Toda interface é julgada como alguém que navega só por teclado e leitor de tela, e com o olhar de um profissional de
  UX: o controle certo (escolher entre opções conhecidas é uma lista pelas setas, nunca um campo para adivinhar e
  digitar), cada coisa no lugar certo, o nome do botão diz o que ele faz, a navegação segue o padrão de cada
  componente. Não basta estar conforme: tem que ser fácil de usar.

### 14. Paridade entre as interfaces

- Toda funcionalidade de comportamento vale em todas as interfaces que executam tarefas, na mesma entrega, em perfeita
  conformidade, com aprovação ligada ou desligada. Quais são as interfaces de cada projeto está na parte específica no
  fim deste arquivo.
- O assistente conversacional não é só um criador de agentes: é um assistente geral que executa tarefas reais.
