# NVDAStudio

NVDAStudio é um addon para o leitor de telas NVDA que cria, corrige, testa e empacota outros addons por meio de uma IA agêntica conversacional.

## Como funciona

O usuário conversa em linguagem natural. Quando o pedido estiver ambíguo, a IA faz perguntas antes de alterar arquivos. Durante a execução, ela informa o que está fazendo, usa ferramentas reais, aceita interrupção e novas instruções e continua a partir do estado atual.

Há um único fluxo de criação e correção:

1. A IA interpreta o pedido e decide se precisa esclarecer algo.
2. No provedor Studio, o roteador seleciona provedor e modelo conforme a tarefa; nos provedores manuais, seleciona somente o modelo.
3. O agente trabalha em uma pasta confinada, lê e edita arquivos, roda testes e corrige falhas.
4. Gates objetivos verificam sintaxe, estrutura NVDA, acessibilidade, execução isolada e integridade.
5. Se o usuário pediu empacotamento, o addon é gerado no formato `.nvda-addon` e validado antes da entrega.

O provedor `Studio`, com o modelo `Alto`, entrega à IA os candidatos que satisfazem fatos objetivos (provedor saudável, capacidade exigida, contexto que cabe) junto com preço, janela de contexto e confiabilidade observada; a IA ordena qual cobre melhor a tarefa (tarefa simples vai para modelo econômico, tarefa difícil para o mais capaz). A decisão é uma chamada barata e em cache por situação; se a IA não responder, vale uma ordem de contingência por confiabilidade observada. Se uma rota falhar, preserva os arquivos e tenta outra rota compatível. A preferência de privacidade limita a execução a um único provedor para não replicar contexto entre serviços.

Economia é tratada como fato do harness, não como ajuste manual: o esforço de raciocínio de cada chamada segue a complexidade que a própria IA já declarou; o histórico de ferramentas de turnos antigos é encolhido antes do próximo turno; e cada build tem um teto agregado de tokens que interrompe preservando os arquivos, do mesmo jeito que uma interrupção do usuário. Tokens e custo estimado em dólar (quando o modelo tem tarifa catalogada) aparecem ao final de cada build.

Factory usa também o roteamento automático nativo do Droid. Ollama, OpenAI, Gemini, Anthropic, xAI e OpenCode Go usam o mesmo contrato agêntico e as mesmas ferramentas do projeto.

## Princípio híbrido

A IA decide:

- intenção e necessidade de perguntas;
- arquitetura e estratégia de implementação;
- quais arquivos alterar;
- uso e sequência de ferramentas;
- diagnóstico e correção;
- se o pedido inclui empacotamento.

Código determinístico decide somente fronteiras objetivas:

- permissões e confirmação de ações sensíveis;
- confinamento de caminhos e prevenção de traversal;
- cancelamento, timeout e isolamento;
- sintaxe e contratos verificáveis do NVDA/wxPython;
- integridade do pacote instalável.

Complexidade, preferência e capacidades declaradas pela IA viajam como dado tipado, nunca como marcadores dentro do texto do usuário. A fala do assistente aparece token a token, no chat e durante a execução. Não há roteamento semântico por palavras-chave, pipeline staged, plano obrigatório por fases, editores paralelos, subagentes fixos ou lógica antiga mantida por compatibilidade.

## Configuração

No painel de configurações do NVDAStudio, escolha o provedor e informe a credencial correspondente quando necessária. `Studio + Alto` permite seleção automática entre provedores e modelos. Nos demais provedores, `Alto` escolhe apenas um modelo daquele serviço; um modelo concreto selecionado manualmente é respeitado.

Studio não possui chave própria: usa somente provedores que já tenham credencial configurada, além da Factory quando o Droid estiver instalado e autenticado. A decisão e o resultado de cada tentativa ficam registrados nos logs.

O baseline do projeto é NVDA `2026.1.1+`. Addons novos devem usar:

- `minimumNVDAVersion = 2026.1.1`
- `lastTestedNVDAVersion = 2026.2.0`

## Desenvolvimento

O contrato central da arquitetura está em [AI_MODULE_SPEC.md](addon/globalPlugins/nvdastudio/AI_MODULE_SPEC.md). As regras operacionais estão em [CLAUDE.md](CLAUDE.md), fonte única para qualquer agente; não manter cópias.

Verificação mínima para qualquer alteração:

```powershell
python -m ruff check addon/globalPlugins/nvdastudio tests build.py --exclude addon/globalPlugins/nvdastudio/lib --exclude addon/globalPlugins/nvdastudio/nvda_docs_cache
python -m mypy addon/globalPlugins/nvdastudio
python -m pytest -q tests/unit tests/integration
python build.py
```

Bibliotecas vendorizadas em `addon/globalPlugins/nvdastudio/lib/` e o cache de fonte do NVDA em `nvda_docs_cache/` não são código próprio e ficam fora do lint/mypy.

## Plano para os conceitos agênticos de 2026 (ainda não implementado)

Esta seção é um plano. Ela não descreve o comportamento atual do projeto.

Quando começar: só depois de terminar o teste real ponta a ponta de todos os módulos que existem hoje. Depois disso, seguir a
regra 15 do `CLAUDE.md`: um item de cada vez, testado ao vivo na interface real, com teste de regressão, README do módulo
em `docs/modules/` e commit. Não começar um item com o anterior em aberto.

O que é exigido e por quê está na regra 18 do `CLAUDE.md`. Última revisão: 2026-10-08. Os estados abaixo vieram de busca no
código nessa data. Antes de começar cada item, conferir de novo se ainda é lacuna.

Em todos os itens, o princípio das regras 1 a 17 continua valendo: a IA decide o significado, o código só protege e mede, e
nenhum limite fixo de tempo, tokens ou etapas pode cortar uma execução que continua avançando.

### Ordem sugerida para o NVDAStudio

1. Convergir com a regra 8. Hoje o código impõe limites fixos: a tabela de rodadas de correção por complexidade em
   `core/orchestrator.py` (`_AGENTIC_CORRECTION_ROUNDS_BY_COMPLEXITY`) e o teto agregado de tokens derivado de `max_turns` em
   `builder/agentic_driver.py` (`_token_budget`). O que fazer: trocar esses tetos por encerramento por travamento (sem
   progresso ou decisão repetida), por cancelamento ou por orçamento de custo que a própria pessoa configurou, mantendo a
   entrega com ressalvas já existente. Pronto quando uma build grande real passar do antigo teto e concluir, com teste de
   regressão.
2. Skills em SKILL.md com carregamento progressivo. Hoje só há referências em comentários. O que fazer: um carregador com
   índice leve (nome e descrição) e instruções completas só quando a IA pede; pasta de skills da pessoa; varredura de
   segurança de skill de terceiros antes de habilitar; aprendizado que atualiza a skill existente em vez de duplicar (regra
   10). Pronto quando um teste mostrar a skill entrando no contexto só sob demanda e o tamanho do índice medido.
3. Cliente MCP. Hoje não existe nenhum módulo. O que fazer: permitir que o construtor use servidores MCP (por exemplo o
   Accessibility MCP e a documentação do NVDA), com ferramenta negada por padrão, aprovação, validação de schema e a descrição
   da ferramenta tratada como dado. Cuidado a verificar primeiro: o addon roda no Python embutido do NVDA e já traz
   dependências dentro de `lib/`, então confirmar se o SDK do MCP cabe nesse esquema. Pronto quando um teste real chamar uma
   ferramenta MCP e o registro mostrar a chamada.
4. Conteúdo de fora é dado, nunca instrução. O que fazer: auditar toda ferramenta que traz conteúdo externo (busca, cache da
   documentação do NVDA, arquivos do usuário) e criar testes adversariais de injeção. Pronto quando os testes passarem e a
   cobertura estiver listada.
5. Hooks de ciclo de vida. Hoje só `tools/tool_gateway.py`. O que fazer: eventos antes e depois de ferramenta, início e fim de
   turno e parada, usados só para proteger, medir ou registrar.
6. Observabilidade e replay. O que fazer: registro estruturado de cada decisão, chamada ao modelo, ferramenta e aprovação, com
   custo por tipo de chamada, e replay determinístico de uma trajetória gravada. Pronto quando uma falha real puder ser
   reproduzida a partir do registro (regra 17).
7. Contexto. O que fazer: confirmar que o que sai do contexto é guardado inteiro e volta por identificador (regra 9) e
   carregar ferramentas sob demanda, sem mudar a lista no meio da tarefa.
8. Evals. O que fazer: conjunto dourado alimentado por falha real, avaliação da trajetória, estatística sobre várias
   execuções (já existe `scripts/multi_run_eval.py`), testes adversariais e detecção de deriva.
9. Matriz de cobertura executável nos moldes da do Qaaccessibility (`scripts/run_2026_agentic_coverage_matrix.py`).
10. Memória em camadas, visível e editável pela pessoa, sem guardar segredo.

Não se aplica: servidor MCP e A2A, porque o addon roda dentro do NVDA para uma pessoa e não há outro agente para delegar a ele
nem para receber tarefas dele. Reavaliar se isso mudar.

### Quando o plano estará concluído

- Todos os itens acima têm módulo, teste de regressão, teste real ponta a ponta na interface e README do módulo.
- A matriz de cobertura da regra 18 roda contra o sistema real e passa, com o resultado verdadeiro registrado.
- Os evals rodam sem o andaime antigo a cada modelo novo, e o que o modelo já dispensa foi removido.
- A parte específica do `CLAUDE.md` deixa de listar pendências e registra a data da última revisão.

## Regras de manutenção

- Não manter código, arquivos, shims ou documentação sem consumidor real.
- Não duplicar registries, ferramentas, endpoints ou caminhos de execução.
- Não substituir compreensão semântica da IA por regex, listas de palavras ou tabelas de pontuação de modelos escritas à mão.
- Todo bug real corrigido recebe teste de regressão.
- Saída de IA não é executada diretamente no processo do NVDA.
- Logs devem redigir segredos e permanecer úteis para diagnóstico.
- A interface deve ser operável por teclado, anunciar progresso e usar linguagem natural.
- Compilar uma atualização não exige incrementar a versão do addon por si só.

## Estrutura

```text
addon/globalPlugins/nvdastudio/
  ai/           clientes, registry e roteamento de modelos
  builder/      agente, ferramentas, workspace, validação e pacote
  core/         orquestração e tipos de resultado
  gui/          diálogo conversacional e configurações
  memory/       contexto efêmero da sessão
  sub_agents/   validador AST objetivo consumido pelo gate
  tool_system/  aprovação de ações sensíveis
  tools/        gateway local por execução
  utils/        logging, políticas, timeouts e segurança
```

Histórico de mudanças deve ser consultado no controle de versão. Este README documenta o comportamento atual; a única exceção é a seção do plano dos conceitos agênticos de 2026, marcada como não implementada.
