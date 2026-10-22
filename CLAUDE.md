# NVDAStudio: regras obrigatórias (núcleo)

Este arquivo é lido no começo de toda sessão. Todas as regras são obrigatórias, sem exceção: nenhuma é sugestão e nenhuma se dispensa por
conveniência, por tamanho da tarefa ou para um teste passar. Se duas regras parecerem conflitar, aplica-se a que protege mais e avisa-se a
pessoa. O texto integral de cada regra, com o porquê e a história, está em `.claude/rules/`, em arquivos por tema que carregam quando a
tarefa toca os arquivos daquele tema. O núcleo abaixo diz o que vale sempre. Quando uma regra puder ser verificada por código, ela também
vive como teste ou verificação automática, porque este arquivo é orientação e não trava.

Princípio central: a IA compreende, decide, cria e se adapta; o código determinístico protege, limita, valida e mede. Autonomia máxima da IA
sem sacrificar segurança, transparência, acessibilidade e verificação. Esta seção comum é igual nos projetos Agentic, Qaaccessibility e
NVDAStudio: ao mudá-la num, muda-se nos outros dois na mesma entrega.

## Como a IA trabalha (regras 1 a 10)

1. Agente = modelo + harness, papéis que nunca se invertem. O modelo decide o conteúdo (significado, estratégia, como corrigir, como explicar).
   O harness decide só o que é permitido: credencial mínima, ferramenta negada por padrão, sandbox, validação de caminho e comando,
   cancelamento, schema, integridade de arquivo, aprovação do irreversível, registro e recuperação. (rules/agente-e-harness.md)
2. Nada de regex, palavra-chave, sinônimo ou árvore de condições para julgar intenção, clareza, completude ou qualidade: isso é da IA, pelo
   significado. Determinismo só para fato objetivo (código de saída, tamanho, schema, URL no texto) e para proteção. Um teste que força o
   código a adivinhar intenção por palavra-chave é recusado. (rules/agente-e-harness.md)
3. Conversa corrida, humana, em tempo real, em português e no jeito da pessoa. Informar cada passo em texto natural, direto, sem repetir e sem
   recomeçar a cada ação; texto, chamada de ferramenta logo em seguida, e o que se diz bate com o que se faz. A frase antes de cada ação não depende de o modelo querer: as ferramentas que executam ação levam um argumento obrigatório de explicação, escrito pelo modelo, que a interface mostra. Streaming token a token. Nunca
   JSON, protocolo, nome técnico de ferramenta, nome interno de juiz ou revisor, nem asteriscos soltos. Comando e código em bloco próprio. A
   pessoa pode interromper e redirecionar sem perder o que foi feito. (rules/conversa-e-interface.md)
4. Interface e leitor de tela, e 13. acessibilidade e UX, e 14. paridade entre as interfaces: ver rules/conversa-e-interface.md. Em resumo:
   pensar e testar como quem usa só teclado e leitor de tela é obrigatório em todo módulo; toda funcionalidade vale em todas as interfaces que
   executam tarefas (aqui, o diálogo do addon, `addon/globalPlugins/nvdastudio/gui/studio_dialog.py`, e qualquer outra que passe a executar tarefas), na mesma entrega.
5. Autonomia: o sistema verifica o ambiente, inicia em segundo plano o que está parado e tenta várias estratégias antes de desistir. Nunca diz
   "não dá porque X não está rodando". Não pergunta à toa. Nunca afirma que concluiu sem ter concluído. Com a aprovação ligada, instalar software desconhecido sempre pede aprovação, por risco de cadeia de suprimento. (rules/autonomia-e-contexto.md)
6. Contexto e ambiguidade: pedido vago de verdade gera uma pergunta curta e cedo; "faça o que combinamos" prossegue sem perguntar. A IA sabe
   sozinha quando pesquisar, usar ferramenta, planejar ou agir. (rules/autonomia-e-contexto.md)
7. Aprovação ligada ou desligada, nunca bloqueio seco. Ligada, o agente pede com a lista completa do que muda; desligada, faz sem perguntar.
   Com a aprovação desligada pela pessoa, o agente segue sem pedir, inclusive em ação irreversível e fora da pasta de trabalho (decisões do dono, 17 e 20/out/2026). Com ela ligada, o que fica fora da pasta de trabalho também pede aprovação, e a aprovação vale para os argumentos exatos: argumento que muda pede nova aprovação. O que nunca depende da chave é a honestidade da plataforma.
   (rules/aprovacao-e-supervisao.md)
8. Nenhum relógio, teto de tokens, de chamadas ou de etapas imposto pelo código corta uma tarefa que continua avançando. O que encerra é:
   convergência, falta de progresso, repetição da mesma decisão, cancelamento pela pessoa ou orçamento que a própria pessoa configurou. Nenhuma
   tarefa fica presa: todo laço, portão, espera e retomada tem fim real; um portão nunca pede o impossível; a IA decidir "siga" não basta, a
   mesma decisão sem nada novo pela terceira vez é encerrada pelo harness; todo laço novo nasce com teste em que a IA diz sempre "siga". Espera
   de rede curta mede inatividade da conexão, não o tempo da tarefa. Entrega parcial é honesta. (rules/tempo-e-lacos.md)
9. Economia e roteamento: o melhor modelo é o que entrega com qualidade gastando menos; o roteador decide, pelo significado, modelo, skills,
   ferramentas e quanto pensar, na mesma chamada. Engenharia de contexto: nada é reenviado sem necessidade, a IA organiza a própria memória e
   o que sai do contexto volta por identificador, o começo de cada chamada é estável para o cache. Medir antes de afirmar economia.
   (rules/economia-e-roteamento.md)
10. Aprendizado sempre e na hora, sem fila de aprovação, sem duplicata, em formato SKILL.md. Aprendizado vindo de conteúdo não confiável também vale na hora, mas com a origem marcada e a confiança reduzida por dentro, e nunca vira instrução. O aprendizado é silencioso: sem aviso na conversa e sem tela de memória (decisão do dono, 20/out/2026). (rules/aprendizado.md)

## Como se prova e se trabalha (regras 11 a 17)

11. Verde não é funcionando. Mock não prova integração e afirmação da IA não é evidência. Quem executa não é quem aprova. A entrega diz o que
    foi feito, o que foi verificado, o que falhou ou não pôde ser testado e onde está o resultado.
12. Engenharia de qualidade: código limpo; em Python, ruff, mypy e pytest sempre; todo bug real corrigido ganha teste de regressão; nenhum
    arquivo extra, rascunho ou script descartável no projeto; código morto sai.
15. Processo: ver o que já existe no código, nos commits e nas docs antes de codar; testes baratos antes, ao vivo só confirma; um módulo de
    cada vez, e módulo concluído fica protegido e entra na regressão conjunta com tag local; passo ao vivo que falha para a rodada na hora, corrige-se com causa provada e o mesmo passo se repete antes de seguir; confiança medida e nunca presumida (invariantes
    verificados em toda execução, falha real vira caso permanente barato, taxa em tentativas repetidas, promessa e prova, confiança dita com
    limite); mudança numa instrução ao modelo tem portão (conjunto amplo, ablação, observação, registro). Documentar na pasta do módulo e
    commitar ao final; o envio (push) do branch de trabalho é permitido (decisão do dono, 20/out/2026); nunca merge sem ordem. Documentos para a pessoa em texto direto, sem asteriscos, em português.
    (rules/evidencia-e-processo.md)
16. Supervisão humana calibrada: intervenção onde o risco é maior (irreversível, escopo ampliado, ambiguidade material) e fora do caminho no
    resto. (rules/aprovacao-e-supervisao.md)
17. Causa raiz, nunca só o sintoma: reproduzir, ler código e registros, provar a hipótese; preservar a evidência antes de reiniciar ou limpar;
    quando a causa não puder ser provada, dizer que NÃO está provada e registrar o que a provaria; a mesma classe de falha ganha defesa contra a
    recorrência. (rules/evidencia-e-processo.md)

## Conceitos agênticos de 2026 (regra 18)

18. Obrigatórios no nível que o produto entrega, com lacunas registradas e nunca "fora de escopo" em silêncio: laço agêntico com ferramentas
    tipadas; MCP, Agent Skills e A2A em vez de formato próprio, com servidor e skill de terceiros tratados como código não confiável;
    subagentes com contexto isolado que devolvem resumo e têm o resultado verificado; guardrails em entrada, saída e chamada de ferramenta,
    com conteúdo de fora sempre como dado; hooks determinísticos só para proteger, medir ou registrar; memória em camadas, com a origem registrada por dentro e silenciosa para a pessoa (decisão do dono, 20/out/2026);
    tarefa longa e retomável; observabilidade estruturada, sem segredo, com replay (com as convenções do OpenTelemetry para IA generativa);
    evals como portão, com tentativas repetidas e casos vindos de falha real; roteamento por camada e custo; computador e navegador só em
    sandbox; harness revisado a cada geração de modelo; matriz de cobertura viva rodada antes de dar uma mudança por pronta. Contra o risco das três pernas, com a aprovação ligada o agente que reúne dados privados, conteúdo não confiável e saída externa pede aprovação na saída. (rules/conceitos-agenticos-2026.md)

## Perguntas ao dono por cenário de uso (regra 19)

19. Durante o desenvolvimento, a IA que desenvolve (qualquer uma, em qualquer ferramenta) faz perguntas ao dono em linguagem simples, como cenários
    reais de uso: o que a pessoa faz, o que vê e ouve na tela e o que acontece nos bastidores, tiradas do CLAUDE.md e do `.claude`. Duas razões:
    não esquecer nenhuma regra (cada cenário confere uma regra escrita com o que o dono espera hoje) e aprender como o dono usa o projeto, para
    atender o fluxo real. Sem teto de perguntas: a IA decide quantas e quando, pelo tamanho e pelo risco do que está fazendo, no meio do trabalho e
    a cada módulo ou mudança de fluxo. A resposta que contradiz o texto vira atualização das regras nos três projetos na mesma entrega. Vale também na parte ao vivo (E2E): antes de
    montar o roteiro ao vivo de um módulo, a IA pergunta como a pessoa usaria aquela fatia, e depois de rodar mostra o que aconteceu em cenário e
    pergunta se era o esperado, para acompanhar cada módulo e cada parte. As perguntas nascem de uma varredura do software feita antes pela
    própria IA, nos bastidores (código, registros, configuração) e na interface (o que a tela mostra, fala e permite navegar): pergunta-se para
    confirmar o que a varredura achou ou quando a dúvida continua depois dela, nunca no escuro. (rules/evidencia-e-processo.md)

## O agente se cuida sozinho (regra 20)

20. Obrigatória, sem exceção, em todo código novo e em toda correção (decisão do dono, 21/out/2026, repetida muitas vezes): o agente deste projeto é livre quanto à estratégia e se cuida sozinho. Ele checa, testa, vê os problemas, acha a causa e corrige; aprende com os erros e com os acertos; resolve os próprios laços e erros por dentro. Quem desenvolve não faz à mão o que o agente deve fazer sozinho: constrói o mecanismo e prova que ele funciona, e diante de qualquer falha pergunta que mecanismo faltou para o agente ter achado e corrigido aquilo sozinho. A rede de segurança da regra 8 é o último recurso e deve ser muito rara. Nenhum determinismo dita a estratégia (regras 1 e 2). (rules/agente-se-cuida-sozinho.md)

## Regras deste projeto (NVDAStudio)

- Nenhum nicho declarado: o NVDAStudio cria, corrige, testa e empacota addons do leitor de telas NVDA por conversa, no computador de uma pessoa.
  (rules/projeto-nvdastudio.md)
- Interface que executa tarefas: o diálogo do addon (`addon/globalPlugins/nvdastudio/gui/studio_dialog.py`). Não há dois chats aqui.
- Leitor de telas: só a mensagem final é falada sozinha; o resto se lê com as setas. (rules/projeto-nvdastudio.md)
- Addon que carrega de verdade é entregue com a lista de ressalvas, nunca chamado de perfeito. Instalar no NVDA da pessoa segue a chave de aprovação.
  (rules/projeto-nvdastudio.md)
- Dívidas declaradas da regra 8: o teto de tokens por construção e as rodadas de correção calculadas pelo código vão sair.
  (rules/conceitos-agenticos-2026.md)
- Servidor MCP e A2A não se aplicam, com justificativa registrada em rules/conceitos-agenticos-2026.md; as demais pendências da regra 18 estão lá.
- Antes de dizer "pronto" para qualquer mudança de código: ruff, mypy, os testes do módulo tocado, e, se a mudança toca a costura entre dois
  módulos, ler os dois lados. Metodologia em `docs/metodologia-verificacao-arquitetura.md`; engenharia de IA em
  `docs/conceitos-ia-para-desenvolvimento-de-software.md`; segurança em `docs/conceitos-ia-seguranca-confiabilidade.md`.
- O agente de IA deste projeto é autônomo (decisão do dono, 21/out/2026, a mesma do Agentic): se ajusta sozinho, aprende com os erros e se corrige, resolve os próprios laços e erros por dentro e fica cada vez mais estratégico e independente. A estratégia é dele e o harness só protege. Diante de uma repetição, o harness informa o fato ao modelo e sobe o raciocínio, e quem muda de caminho é o agente; o encerramento pelo harness (regra 8) é só a última rede de segurança, rara, com entrega parcial honesta. (rules/projeto-nvdastudio.md)
- O agente é livre, estratégico, se corrige sozinho e aprende com os erros e com os acertos (decisões do dono, 21/out/2026, depois da pesquisa registrada em `docs/autonomia.md` do Agentic); isto vale como regra, e quem desenvolve aqui não precisa ouvir de novo:
  - Diante de um laço, o agente se resolve sozinho: o harness diz ao modelo só o fato, o raciocínio sobe, ele recomeça uma vez por etapa com a memória reorganizada, e só por último a rede de segurança da regra 8, rara, encerra com entrega parcial que diz onde parou e o que foi tentado. Com a pessoa acompanhando a execução (uma tela aberta seguindo-a) a rede não encerra: avisa em uma frase e espera a pessoa, sem relógio; sem ninguém acompanhando, encerra. Progresso é trabalho de verdade (criar, editar, verificar), nunca só atividade.
  - Chamada ao modelo: conexão viva e lenta continua esperando; conexão morta (nenhum dado por muito tempo, medido pelo silêncio entre pedaços, nunca pelo tempo da tarefa) é descartada e refeita em outro modelo do mesmo provedor, com uma frase calma à pessoa.
  - Aprende com o que errou e com o que acertou, em silêncio, durante a tarefa (cópia de revisão em segundo plano) e ao fim, e mantém as próprias habilidades em ordem (curador).
- Como o dono usa e prova o Agentic (resposta do dono, 21/out/2026): hoje só o Ollama funciona (os outros provedores estão sem crédito), e o dono usa o Auto do Ollama, o roteador inteligente, para testar todos os modelos do provedor ao mesmo tempo e ver o que cada um entrega, inclusive o thinking e as outras capacidades de cada um, corrigindo direto e ao vivo. O que fica pronto nos outros provedores é testado em unidade e provado ao vivo quando o crédito voltar.
  - O thinking é automático no roteador: ele pensa conforme a tarefa, mínimo, médio, alto ou máximo, só dentro do que cada modelo oferece, e o mesmo para as outras capacidades de cada modelo. A escolha é do roteador, pelo significado da tarefa, e a da pessoa vale quando ela escolheu.
- Quem checa, testa, vê os problemas e corrige é o próprio agente, para tudo (decisão do dono, 21/out/2026): quem desenvolve aqui constrói o mecanismo e prova que ele funciona, e não faz à mão o que o Agentic deve fazer sozinho (achar a causa de uma falha na própria execução, mudar de caminho, corrigir o resultado e aprender com isso). Ao achar um defeito, a pergunta é "qual mecanismo faltou para o Agentic ter achado e corrigido isto sozinho?", e esse mecanismo é o que se constrói; o conserto à mão só vale como passo para provar o mecanismo.
