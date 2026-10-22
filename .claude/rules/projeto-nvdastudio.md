---
paths:
  - "addon/globalPlugins/nvdastudio/**"
  - "tests/**"
  - "scripts/**"
---

# Regras específicas do NVDAStudio

> Carrega quando se mexe no addon, nos testes ou nos scripts. Texto da parte específica deste projeto, com as decisões do dono de 20/out/2026.

### Interface que executa tarefas (regra 14)

O diálogo do addon (`addon/globalPlugins/nvdastudio/gui/studio_dialog.py`). Toda funcionalidade de comportamento vale em todas as interfaces que passarem a executar
tarefas, na mesma entrega. A regra dos dois chats separados é só do projeto Agentic.

### Nicho (regra 5)

Nenhum nicho declarado. O NVDAStudio cria, corrige, testa e empacota addons do leitor de telas NVDA por conversa.

### Regras de design: 4, 13 e 14 (decisões do dono, 20/out/2026)

- Durante o trabalho o leitor de telas não fala nada sozinho: só a mensagem final é falada sozinha. O resto se lê com as setas. É o mesmo
  jeito do Agentic.
- Comando e código aparecem em bloco próprio de código, com botão de copiar.
- Quando o dono consolidar o resto (botões, cabeçalhos), registrar aqui. Até lá valem o `README.md` e o `AI_MODULE_SPEC.md` do módulo de IA.

### Entrega com ressalvas

Um addon que carrega de verdade no NVDA é entregue com a lista das ressalvas em frases simples, mesmo com avisos de qualidade; só se bloqueia
quando nada do que existe é seguro para instalar. Nunca se chama de perfeito um resultado com ressalva (decisão do dono, 20/out/2026: é assim que deve ser).

### Instalar no NVDA da pessoa

Segue a chave de aprovação (regra 7): ligada, mostra o que vai instalar e pede; desligada, instala sem perguntar (decisão do dono, 20/out/2026).

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

### Nota concreta: tempo adaptativo e entrega com ressalvas (estado anterior a 20/out/2026)

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

Pelas decisões de 20/out/2026, o `correction_rounds` por complexidade e o orçamento de tokens derivado de `max_turns` (`_token_budget()`) são
dívida a remover, e a entrega com ressalvas descrita acima continua valendo.

## Decisões do dono de 20/out/2026 para este projeto

- A chave de API de cada provedor fica no cofre de credenciais do Windows, nunca em texto simples no arquivo de configuração do NVDA.
- Enquanto o assistente trabalha, a pessoa continua usando o computador e o NVDA normalmente: a janela do assistente nunca trava o NVDA nem o resto; só a mensagem final é falada sozinha.
- Instalar o addon criado no NVDA da pessoa segue só a chave de aprovação, sem outra rede de segurança (decisão do dono); o risco de um addon com defeito impedir o NVDA de abrir foi dito e aceito.
- No modo Studio, uma linha de status com o provedor e o modelo que estão trabalhando fica visível, lida com as setas e nunca falada sozinha; muda se o roteador trocar.

## Decisão do dono de 21/out/2026: o agente é autônomo (a mesma do Agentic)

- O agente de IA deste projeto é livre quanto à estratégia: se ajusta sozinho, aprende com os erros e se corrige, resolve os laços e os erros por dentro e fica cada vez mais estratégico e independente. O dono já repetiu isto muitas vezes: está escrito aqui e no `CLAUDE.md`.
- Ordem diante de um laço ou de um erro, sempre nesta ordem: (1) o harness informa ao modelo apenas o fato (o que se repetiu e que nada de novo veio), sem dizer o que fazer; (2) o raciocínio sobe e o roteador leva a chamada para outro modelo, não o que travou; (3) o modelo muda de caminho por conta própria e aprende com o erro; (4) só se nada mudou depois disso, a rede de segurança da regra 8 encerra com entrega parcial honesta. O encerramento é o último recurso, deve ser muito raro, e cada vez que acontece é um sintoma a investigar.
- Nenhum determinismo dita estratégia (regras 1 e 2): nem texto pronto dizendo ao modelo o que fazer, nem lista de passos. Todo laço novo nasce com um teste em que o laço se resolve sozinho antes de ser encerrado e outro em que a IA diz sempre "siga" e ele ainda assim termina.
- O código deste projeto ainda não obedece em tudo: conferir o que cada laço faz hoje e registrar a diferença como pendência com o item nomeado, em `docs/PENDENCIAS.md`.
- Respostas do dono às perguntas de cenário sobre a autonomia (21/out/2026): (1) antes de a rede de segurança encerrar, o agente replaneja uma vez, descarta o plano atual e monta outro com o que já aprendeu; só se o segundo plano também não sair do lugar a rede encerra; (2) o outro modelo que a repetição chamou fica na tarefa só enquanto o trabalho estiver travado, e o roteador volta a escolher pela evidência e pela dificuldade assim que o trabalho volta a andar; (3) numa chamada ao modelo que demora muito, a pessoa ouve uma frase curta e calma, uma vez só ("o modelo está demorando para responder, continuo esperando"), a espera segue como a regra 8 manda e nenhuma chamada nova é aberta por cima; (4) quando o agente sai sozinho de uma repetição, a lição é guardada em silêncio, por dentro, como o resto do aprendizado (sem aviso e sem tela).
- Chamada ao modelo travada (resposta do dono, 21/out/2026, depois da pesquisa de recuperação de laços): a regra de esperar a mesma chamada vale para a conexão VIVA e lenta (chegam dados, ou o provedor está processando). Para a conexão MORTA (aberta, mas nenhum dado chega há muito tempo, enquanto o mesmo provedor responde rápido a outras chamadas), o agente detecta a falta de sinal da conexão, descarta aquela chamada e refaz a mesma pergunta em outro modelo do mesmo provedor pelo Auto, e a pessoa ouve uma frase calma ("o modelo não respondeu, troquei de modelo"). O que se mede é a inatividade da conexão (primeiro dado, intervalo entre pedaços), nunca o tempo da tarefa (regra 8). Isto ajusta a resposta anterior do mesmo dia, de só esperar.

## Como o dono usa e prova o Agentic (resposta do dono, 21/out/2026)

- Hoje só o Ollama funciona. O dono usa o Auto do Ollama para testar todos os modelos ao mesmo tempo, ver o que cada um entrega (thinking e demais capacidades) e corrigir direto e ao vivo. Toda prova ao vivo roda no Auto do Ollama; o que é de outro provedor fica pronto e testado em unidade, e é provado quando o crédito voltar.
- Thinking automático no roteador: mínimo, médio, alto ou máximo conforme a tarefa e conforme o que cada modelo oferece; o mesmo vale para as outras capacidades. A escolha da pessoa, quando existe, vale. Conferir ao vivo que cada modelo recebe só o nível que ele oferece.

## O agente checa, testa e corrige a si mesmo para tudo (decisão do dono, 21/out/2026)

- Achar a causa de uma falha na própria execução, mudar de caminho e corrigir o resultado é trabalho do agente, e não de quem desenvolve: o harness informa o fato, o raciocínio sobe, o roteador tenta outro modelo, o agente recomeça uma vez e aprende com o erro, em silêncio.
- Quem desenvolve, diante de qualquer falha, pergunta que mecanismo faltou para o agente ter achado e corrigido aquilo sozinho, e constrói esse mecanismo. O conserto à mão é só o passo para provar o mecanismo, e a entrega diz o que o agente já faz sozinho e o que ainda falta.

## Respostas do dono às perguntas de cenário depois da revisão das regras (22/out/2026)

- Exploração do roteador: só em tarefas fáceis e médias; na camada profunda o roteador escolhe só por evidência, sem experimentar. Um modelo que falha perde o bônus na hora.
- Aviso ao modelo diante de uma repetição: continua sendo só o fato (o que se repetiu e que nada de novo veio); não há conselho de método nem licença para parar. Antes de mudar isso, mede-se quantas vezes a rede de segurança ainda dispara depois das correções.
- Correção que a pessoa dá no meio da tarefa: vale em tarefas parecidas daqui em diante; entra na habilidade daquele tipo de tarefa, em silêncio, e a pessoa não precisa repetir.
- Projetos vizinhos: o código do roteador por evidência, da atualização de habilidade lendo o texto atual e das orientações da pessoa no aprendizado só chega ao Qaaccessibility e ao NVDAStudio depois de provado no Agentic, um projeto de cada vez. O texto das regras já é igual nos três.
