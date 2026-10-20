---
paths:
  - "addon/**"
  - "tests/**"
  - "scripts/**"
  - "docs/**"
---

# Evidência, engenharia, processo de trabalho, causa raiz e conclusão (regras 11, 12, 15 e 17)

> Texto integral, sem mudança. Inclui módulo concluído protegido, confiança medida e o portão de mudança de instrução.

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

### 15. Processo de trabalho

- Testar na interface real, como um usuário iniciante usaria, em todas as interfaces do projeto. Testes baratos (lint, tipos,
  unitários) antes; o teste ao vivo confirma.
- Um módulo de cada vez: nunca começar outro sem o atual funcionando por completo. Um módulo só está
  concluído quando: o que ele promete foi testado de verdade, ao vivo, na interface real; todo defeito achado foi
  corrigido com teste de regressão ou ficou registrado como pendência explícita; existe um README do módulo em
  `docs/modules/` explicando tudo o que ele entrega, o que foi medido, o que foi corrigido e o que ainda não está
  provado; a suíte e o lint passam; o conjunto de regressão do módulo passa em tentativas repetidas e o auditor de invariantes não aponta nada (ver "Confiança medida", abaixo); e o trabalho foi commitado. Pendência que depende de decisão da pessoa é
  perguntada e registrada antes de seguir. Nunca passar ao módulo seguinte com o anterior em aberto.
- Vale para todo provedor de IA, sem tratamento especial para nenhum: cada provedor passa pelos mesmos módulos e pelas mesmas
  regras deste arquivo, e um módulo só está concluído PARA UM PROVEDOR quando foi testado ao vivo, na interface real, naquele
  provedor. A pessoa pode testar qualquer módulo em qualquer provedor, em qualquer ordem, sem retrabalho nem conflito, porque a
  proteção contra regressão acompanha o provedor em teste e avança junto com os módulos: depois de testar um provedor em um
  módulo, na mesma entrega, as proteções daquele provedor são atualizadas (contrato real gravado, números de referência
  medidos, matriz de paridade, ficha do provedor e seção do módulo), por comando e a partir de uma fonte única, nunca de
  memória, e a verificação reprova quando algo ficou desatualizado. A proteção de um provedor nunca pode estragar a de outro. Um provedor ainda não provado ao vivo num módulo funciona, com um aviso curto e honesto do estado; nunca é bloqueado (decisão do dono, 20/out/2026).
  O commit diz o que funcionou, o que foi feito e o que ficou pendente, e cada módulo testado em um provedor deixa o registro
  dele na documentação.
- Antes de codar, ver o que já existe no código, nos commits e nas docs.
- Documentar tudo o que foi feito e corrigido na pasta de cada módulo, e commitar ao final. O envio (push) do branch de trabalho é permitido (decisão do dono, 20/out/2026); nunca fazer merge sem
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

- Confiança medida, nunca presumida. Para cobrir os cenários sem depender só de teste ao vivo, vale em todos os módulos, modelos e
  interfaces:
  - Invariantes verificados em toda execução. Todo registro de execução, real ou de teste, é conferido por um verificador de código
    contra propriedades que valem sempre: nenhuma execução termina sem resposta final; nenhuma chave, segredo ou nome interno aparece
    na conversa nem nos registros; nenhum laço fica sem fim; nenhuma aprovação fica pendente sem um diálogo visível para a pessoa; um
    status de concluído só existe com evidência; o gasto de uma tarefa fica na ordem de grandeza do caso. Todo defeito novo, de qualquer
    rodada, vira uma propriedade nesse verificador.
  - Falha real vira caso permanente, barato e determinístico. Além do teste de regressão da regra 12, a trajetória que causou o defeito
    é reproduzida com o provedor roteirizado, sem gastar crédito, e roda a cada mudança. O teste ao vivo só confirma, nunca é o único
    jeito de achar um problema.
  - Taxa em tentativas repetidas, não um verde. O critério de um fluxo ao vivo que depende do modelo é uma taxa em várias tentativas
    (por exemplo, todas as três a cinco passam), e não uma execução única: uma execução que passou é evidência fraca e uma que falhou
    não prova regressão. O relatório mostra a taxa e separa intermitência do modelo de regressão do código, e quem confere é uma
    leitura de amostras das execuções, para saber se a falha é do agente ou do avaliador.
  - Promessa e prova. Cada frase de "o que o módulo entrega", na documentação do módulo, aponta o teste que a cobre. Frase sem teste
    aparece como lacuna declarada, nunca como suposição.
  - Confiança dita com limite. A entrega diz o que foi medido, com a taxa, e o que não foi medido (outros provedores, caminhos não
    testados, o que ninguém previu). "Tudo funciona" só vale dentro desse recorte, e o monitoramento das execuções reais continua depois
    da entrega.

- Mudança numa instrução ao modelo é mudança de comportamento do sistema e tem portão. Vale para qualquer texto que o modelo recebe
  (instrução de sistema, descrição e argumentos de ferramenta, diretriz de narração, prompt do roteador, do juiz ou do revisor):
  - Antes de entrar, roda-se o conjunto amplo de avaliações do módulo, em tentativas repetidas, e não só o caso que motivou a mudança.
    Uma instrução que corrige um caso pode piorar outro, e isso só aparece no conjunto amplo (visto na prática por quem faz isso melhor:
    uma mudança de instrução passou semanas de teste interno e só uma avaliação mais ampla mostrou a queda).
  - A mudança entra isolada e, quando possível, com ablação: liga e desliga a frase nova e compara a taxa. Fica declarado para qual modelo
    ou provedor ela vale; o que foi pensado para um modelo não vale para os outros sem prova.
  - Depois de entrar, há um período de observação sobre as execuções reais: os invariantes e a taxa de cada fluxo são comparados com os de
    antes, e a mudança é desfeita se algo piorar.
  - Cada mudança de instrução fica registrada com a data, o motivo, o conjunto que rodou e o resultado, para provar a causa se algo
    piorar depois.

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
