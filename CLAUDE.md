# NVDAStudio — instruções operacionais para agentes

Este arquivo é lido automaticamente no início de qualquer sessão de agente
neste repositório. Não é material de estudo — são regras de processo.

## Antes de declarar qualquer implementação concluída

**Não é opcional.** Antes de dizer "pronto" pra qualquer mudança de código
neste projeto, consulte e aplique o que for cabível dos 3 documentos abaixo.
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

3. **`docs/conceitos-ia-seguranca-confiabilidade.md`** — segurança e
   confiabilidade de agente (sandboxing, permission boundaries, blast
   radius, adversarial evals, recovery/resilience). Aplicável sempre que a
   mudança tocar execução de código gerado, ferramentas expostas a um
   sub-agente, ou conteúdo vindo de fora (busca web, input do usuário).

## Regra geral de conclusão

Uma implementação só está "concluída" quando: lint limpo, testes relevantes
passando (incluindo os novos de regressão do bug corrigido), e — quando a
mudança tocar a costura entre módulos — confirmação de que o que um lado
promete é literalmente o que o outro consome. "Parece certo" não é
suficiente; "os degraus baratos da pirâmide confirmam" é.

Isso não substitui julgamento — para mudanças triviais e isoladas, aplicar
o bom senso sobre qual subconjunto do checklist é proporcional. O objetivo é
processo real de engenharia, não burocracia por burocracia.

## Regra permanente: agente = modelo + harness (determinismo só onde protege)

**Obrigatória para todo código, teste e correção deste projeto, para toda integração de
modelo/provider presente ou futura, sem exceção** — nenhum modelo, provider ou ferramenta
tem tratamento especial que o isente desta regra. Esta seção é intencionalmente
**genérica e portável**: não nomeia nenhum provider, arquivo ou módulo específico deste
projeto de propósito, para poder ser copiada para o `CLAUDE.md` de qualquer outro software
agentic sem edição. Onde este projeto tiver detalhe concreto de como a regra se aplica aqui
(nomes de arquivo, endpoints, histórico de correções), ele fica isolado na nota final desta
seção — apague só aquela nota ao portar esta regra para outro projeto.

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
  quando explicitamente concedida; nunca "disponível a menos que alguém desligue".
- **Isolamento e sandbox**: execução de código, navegador ou comando roda num limite que não
  alcança mais do que o necessário, e cujo vazamento não compromete o resto do sistema.
- **Validação de caminho e de comando**: nenhuma operação de arquivo ou processo sai do
  workspace/escopo autorizado; comandos são validados antes de rodar, nunca depois.
- **Cancelamento e interrupção**: parar uma execução em andamento é sempre possível e sempre
  determinístico — nunca depende do modelo "decidir" parar.
- **Timeouts e limites operacionais, sempre com tempo adaptativo**: todo laço, retry ou
  orçamento de execução tem um teto agregado imposto pelo código, não apenas a soma de laços
  independentes sem controle central — e esse teto **escala com a complexidade real da
  tarefa**, nunca é um número fixo igual pra qualquer tarefa. Dois erros documentados e já
  corrigidos neste projeto (ver nota final) mostram as duas formas como isso quebra: (1) um
  orçamento fixo que não cresce com o esforço que a própria complexidade declarada já
  autorizou; (2) **dois tetos independentes competindo pelo mesmo recurso** — um teto real
  (turnos/tokens, já adaptativo) e um teto artificial por cima dele (ex.: "número de rodadas de
  correção") que sempre para PRIMEIRO, mesmo com o teto real ainda com margem. Regra prática:
  se existe um orçamento real e adaptativo pro recurso, nenhum outro contador paralelo pode
  interromper o laço antes dele — um único teto central, nunca dois competindo.
- **Guarded loops + autosubmit (nunca bloquear tudo atrás de "100% ou nada")**: ao esgotar o
  orçamento real (turnos, tokens, custo, tempo) ou detectar que o laço não converge mais
  (loop-detector determinístico), o harness entrega o **melhor artefato que já existe**
  (autosubmit) em vez de descartar todo o trabalho atrás de uma tela de erro que só oferece
  "tentar de novo do zero". Esse é o padrão real usado por agentes de código de produção
  (SWE-agent: "guarded loops + autosubmit" — todo motivo de parada roda um diff final e
  entrega o patch parcial existente, transformando o que seria uma falha em um "sucesso
  degradado"). Na prática: distinguir sempre **bloqueante** (o artefato não funciona/não
  carrega — nunca entregar disfarçado de pronto) de **qualidade/política pendente** (o
  artefato funciona, só não está 100% limpo — entregar com a lista clara do que falta, não
  bloquear). A distinção entre as duas categorias é sempre um fato objetivo e verificável
  sobre o próprio relatório do harness (ex.: "erro real de execução" vs. "estilo/comentário
  ausente"), nunca um palpite sobre a gravidade.
- **Validação de schema/contrato**: entrada e saída estruturada são validadas contra um
  contrato explícito antes de seguir adiante.
- **Sintaxe e integridade de arquivo**: uma edição/gravação só é aceita se preservar a
  integridade sintática do que já existia.
- **Proteção contra operação destrutiva e portão de aprovação**: qualquer ação irreversível
  (apagar, sobrescrever, enviar, publicar, gastar) exige aprovação explícita antes de
  executar — nunca só depois, nunca implícita.
- **Registro de evento e recuperação de falha**: toda decisão de permissão, erro e retry fica
  auditável; uma falha parcial deve poder ser retomada sem repetir trabalho já provado.
- **Escalonamento para humano**: quando a ambiguidade for material ao resultado ou a ação for
  de alto risco, o harness garante que existe um caminho real de parar e perguntar — a decisão
  de *quando* perguntar continua sendo da IA, o harness só garante que o caminho existe e
  funciona.

### O que nunca vira regra fixa

**Nunca** transformar uma decisão subjetiva (intenção, se uma tarefa está clara o bastante,
qual ferramenta "parece" certa, se uma resposta "parece" completa) em árvore fixa de
palavras-chave/regex/condição — isso é determinismo em excesso disfarçado de segurança, e
é exatamente o tipo de regressão que trava um agente sem de fato protegê-lo. Uma regra
determinística nova só é aceitável quando protege um dos itens da lista acima ou valida um
**fato objetivo e verificável** (ex.: uma URL literalmente presente no texto, um limite de
tamanho, um schema) — nunca para "deixar o comportamento mais previsível" ou "fazer um teste
passar mais fácil". Ao escrever ou revisar um teste: se ele exige que o código adivinhe ou
force uma categoria de intenção por palavra-chave em vez de deixar o modelo julgar, o teste
está pedindo o tipo errado de determinismo — não aceitar.

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

### Nota concreta deste projeto (apague ao portar esta regra pra outro software)

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

---
