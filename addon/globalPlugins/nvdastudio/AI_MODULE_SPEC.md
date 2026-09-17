# Contrato de arquitetura do NVDAStudio

Este documento descreve somente a arquitetura ativa. Histórico pertence ao controle de versão, não ao runtime nem a este contrato.

## Princípio central

O NVDAStudio usa um único fluxo agêntico para criar e corrigir addons. A IA interpreta a intenção, escolhe estratégia, edita arquivos, usa ferramentas, avalia resultados e conversa durante a execução. Código determinístico fica restrito a fronteiras objetivas: permissões, confinamento de caminhos, cancelamento, sintaxe, contratos técnicos do NVDA, acessibilidade verificável, execução isolada e integridade do pacote.

Não existem pipeline staged, plano obrigatório por fases, subagentes fixos, roteamento por palavras-chave, editor paralelo, registry duplicado de ferramentas ou caminho legado de geração.

## Fluxo ativo

1. `studio_dialog.py` recebe a conversa e usa saída estruturada da IA para decidir entre responder, esclarecer ou executar.
2. `clarifier.py` faz perguntas quando faltam decisões que alterariam materialmente o addon. A mesma resposta semântica registra se o usuário pediu empacotamento.
3. `orchestrator.py` inicia uma execução única, resolve uma rota manual ou o ranking do Studio, publica progresso e chama o driver adequado.
4. `agentic_driver.py` executa o loop comum. Factory usa Droid stream-JSON-RPC; os demais provedores usam function calling pelo mesmo contrato de ferramentas.
5. `agent_tools.py` oferece leitura, escrita, listagem, testes, validação e pergunta ao usuário dentro de um workspace confinado.
6. `agent_checkpoint.py` persiste estado mínimo recuperável e `agent_evaluation.py` registra trajetória e resultado.
7. `studio_dialog.py` aplica a decisão semântica de empacotar e valida o `.nvda-addon` antes de oferecê-lo.

## Provedores e roteamento

- `llm_factory.py` cria o cliente do provedor selecionado.
- `model_registry.py` é a fonte única de modelos, capacidades e tiers.
- `model_router.py::select_model` seleciona um modelo dentro de um provedor manual.
- `model_router.py::select_routes` só faz roteamento cross-provider quando a configuração é `Studio + Alto`.
- Studio considera provedores configurados, saúde observada, capacidades, contexto estimado, complexidade, preferência, custo, velocidade e confiabilidade. A decisão completa é persistida no resultado e registrada no log.
- Falha no Studio preserva o workspace e tenta até três rotas compatíveis. Em preferência de privacidade, usa somente uma para não replicar o contexto.
- Factory recebe `auto`; o Droid escolhe o modelo concreto segundo a tarefa.
- Ollama, OpenAI, Gemini, Anthropic, xAI e OpenCode Go usam o mesmo loop agêntico e as mesmas ferramentas canônicas.
- `reliability.py` mantém retry, circuit breaker e degradação de infraestrutura. Não decide conteúdo.

## Contratos de segurança e qualidade

- Toda escrita fica sob `iteration_workspace.py`; traversal e caminhos externos são recusados.
- Ferramentas sensíveis passam por `approval.py` e a decisão humana é fail-closed.
- Código gerado é analisado e executado somente por `code_sandbox.py`/`isolation.py`, preferencialmente em Docker.
- O gate do agente chama Ruff, mypy, importação/instanciação, testes gerados e validação de acessibilidade antes da entrega.
- O cancelamento é observado também enquanto uma ferramenta está em execução; o pipeline não espera o timeout integral para responder ao usuário.
- `addon_builder.py` valida e empacota a estrutura real no disco.
- `ast_validator.py` cobre apenas invariantes decidíveis de compatibilidade e acessibilidade; não tenta inferir intenção do usuário.
- `injection_guard.py` fornece detecção observável, não um classificador semântico substituto.
- Falhas devem produzir mensagem natural e acionável; detalhes técnicos permanecem nos logs.

## Mapa completo dos módulos ativos

### Raiz

- `rule_registry.py`: catálogo canônico de regras técnicas.

### ai

- `clarifier.py`: esclarecimento e intenção de empacotamento por IA.
- `factory_client.py`: integração Droid stream-JSON-RPC.
- `llm_client.py`: protocolos e tipos comuns dos clientes.
- `llm_factory.py`: construção provider-agnostic dos clientes.
- `studio_client.py`: roteamento e failover do provedor virtual Studio em chamadas comuns.
- `model_pricing.py`: metadados de custo consumidos pelo roteador.
- `model_registry.py`: catálogo único de modelos e capacidades.
- `model_router.py`: seleção dentro de um provedor e ranking cross-provider exclusivo do Studio.
- `ollama_client.py`: cliente Ollama Cloud.
- `opencode_go_client.py`: cliente de recuperação para saída estruturada.
- `pricing.py`: normalização de preço usada pelo roteamento.
- `provider_client.py`: clientes nativos OpenAI, Gemini, Anthropic e xAI.
- `reliability.py`: resiliência de chamadas externas.

### builder

- `addon_builder.py`: materialização, saneamento, validação estrutural e pacote `.nvda-addon`.
- `addon_loader.py`: leitura segura de addon existente.
- `agent_checkpoint.py`: retomada mínima do loop ativo.
- `agent_evaluation.py`: métricas e trajetória do agente.
- `agent_tools.py`: schemas e execução das ferramentas canônicas.
- `agentic_backends.py`: adaptação dos formatos de tool call dos provedores.
- `agentic_driver.py`: único loop de criação e correção.
- `code_sandbox.py`: lint, tipos, importação e execução isolada.
- `isolation.py`: backend de isolamento e política de disponibilidade.
- `iteration_workspace.py`: workspace confinado e operações de arquivo.
- `nvda_context.py`: contexto técnico atual do NVDA para a IA.
- `nvda_runtime_stubs.py`: stubs usados exclusivamente na validação isolada.
- `trajectory_compressor.py`: compactação semântica do histórico ativo.

### core

- `orch_types.py`: `StepResult` e `OrchestrationResult` do fluxo ativo.
- `orchestrator.py`: ciclo de vida, roteamento e integração do agente com a GUI.

### gui

- `agent_progress.py`: eventos de progresso acessíveis.
- `settings_panel.py`: provedores, modelos e credenciais.
- `studio_dialog.py`: conversa, interrupção, redirecionamento e entrega.

### memory

- `conversation_manager.py`: callbacks e eventos da conversa em execução.
- `narration.py`: tradução de eventos técnicos para atualização natural.
- `relevance.py`: seleção semântica de contexto conversacional.
- `session_memory.py`: estado efêmero da sessão atual.

### sub_agents, tool_system e tools

- `ast_validator.py`: validadores AST objetivos consumidos pelo gate ativo.
- `approval.py`: política e fila de aprovação de ferramentas.
- `tool_gateway.py`: gateway por execução, timeout e despacho local.

### utils

- `engineering_principles.py`: princípios de engenharia injetados no agente.
- `hidden_process.py`: subprocessos sem janela no Windows.
- `injection_guard.py`: proteção de conteúdo não confiável.
- `logger.py`: logging persistente com redação de segredos.
- `project_policy.py`: baseline atual do NVDA.
- `timeouts.py`: timeouts das ferramentas ativas.
- `user_visible_text.py`: saneamento de texto mostrado e falado.

## Fitness functions

- Todo módulo real deve aparecer neste contrato.
- Toda função ou constante de topo deve ter consumidor em produção; não há allowlist de lógica órfã.
- Todo bug corrigido recebe teste de regressão.
- Mudanças entre módulos verificam produtor e consumidor do contrato.
- O pacote só é concluído após lint, mypy, testes relevantes e validação do artefato.
