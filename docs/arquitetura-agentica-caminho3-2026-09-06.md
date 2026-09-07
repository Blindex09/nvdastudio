# Caminho 3 — NVDAStudio como harness agêntico (igual às ferramentas de ponta)

> Plano de arquitetura, não código. Objetivo: o NVDAStudio codar addons como
> Cursor / Claude Code / droid — a IA dirige o loop **editar → rodar → testar →
> corrigir**, iterando contra a realidade — mantendo os **gates determinísticos**
> e o **contexto NVDA** que já são o valor do projeto.
> Data: 2026-09-06. Baseado num levantamento real do que já existe.

## 1. A descoberta que simplifica tudo: o motor já existe

O `droid exec` **já é** um harness agêntico completo. Confirmado ao vivo nesta
máquina (`droid exec --help`, `--list-tools`):

- **Loop agêntico nativo:** tools embutidas **Read, Grep, Glob, LS, Create,
  Edit, Execute** (rodar comandos), **TodoWrite** (planejar), WebSearch, FetchUrl.
- **Autonomia em camadas:** `--auto low|medium|high`. `medium` = editar arquivos
  + instalar deps + **build/testes locais** + git local, **sem** push/sudo/produção.
- **Blast radius resolvido de graça:** `-w/--worktree` roda num **git worktree
  isolado** (branch próprio); nada toca o projeto real até você aprovar.
- **Injeção de contexto:** `--append-system-prompt-file <arquivo>` — é por aqui
  que o conhecimento NVDA entra.
- **Controle programático:** `--input-format stream-jsonrpc`, `--session-id`,
  `--fork` — dá pra dirigir o droid por programa e continuar a mesma sessão.
- **Multi-agente opcional:** `--mission` (workers + validators), `--validator-model`.

**Conclusão:** o NVDAStudio não precisa CONSTRUIR o loop agêntico. Precisa
**delegar o loop ao droid** e continuar sendo o **harness** (contexto + gates +
GUI + observabilidade). É a virada de "motor na jaula de texto" para "motor solto
dentro de trilhos determinísticos".

## 2. Mapa do que já existe — por destino

Levantamento do código atual, agrupado por o que acontece com cada peça.

### 🟢 PRESERVAR — o valor único do NVDAStudio (não se joga fora)

| Peça | Papel novo |
|---|---|
| `builder/nvda_context.py` (2736 linhas: `get_docs_code_generation`, `get_docs_accessibility_audit`, `extract_nvda_topics`, regras, assinaturas de API NVDA) | **Vira o system prompt do droid** (`--append-system-prompt-file`). É o conhecimento que o droid genérico não tem. |
| `rule_registry`, `utils/engineering_principles`, `nvda_docs_cache/` | Idem — contexto/regras injetadas no droid. |
| `builder/code_sandbox.py` (executa o addon isolado) | **Gate determinístico pós-loop**: valida execução real do que o droid produziu. |
| Gates de entrega: `_missing_declared_files`, portão final do pacote, `_collect_quality_gaps` (aviso honesto), accessibility gate | **Continuam sendo o "done" fora do modelo** — a lição inegociável dos 7 projetos auditados. |
| `gui/studio_dialog.py` (UX leitor de tela) | Mantém — passa a ser o **condutor** do droid (mostra progresso, aprova, entrega). |
| `ai/model_router`, `ai/factory_client` | Mantêm — mas o `factory_client` muda de "droid só-texto" para **driver do droid agêntico**. |
| `core/checkpoint_manager`, `memory/session_memory`, `utils/iteration_budget`, observabilidade/trajetória | Mantêm — é o harness ao redor (custo, checkpoint, replay). |
| `builder/addon_builder` (empacotar `.nvda-addon`) | Mantém — empacota o resultado do worktree. |

### 🔴 SUBSTITUIR — o loop staged (é o que te trava hoje)

| Peça | Por quê sai |
|---|---|
| `core/planner.py` (plano de steps rígido) | O droid planeja sozinho (TodoWrite / `--use-spec`). |
| Pipeline staged do `core/orchestrator.py` (steps paralelos, critic por step, montagem) | Vira **1 sessão droid agêntica + gates**. O loop grosso "gera tudo de uma vez → valida → 1 retentativa" some. |
| Sub-agentes: `code_generator`, `manifest_builder`, `assembler`, `syntax_validator`, `ast_validator`, `doc_generator`, `test_generator` | O droid faz tudo isso **num loop só**, iterando. A maioria deixa de existir. |
| `tools/tool_gateway` + `tool_system/builtins` (`file_editor`, `search_web`, `ast_parser`, `nvda_validator`) | **Redundantes**: o droid tem Edit/Create/Execute/Grep/WebSearch nativos. (Ironia: o `file_editor` que acabamos de blindar vira desnecessário neste caminho — mas o trabalho não foi perdido: as lições viraram gates.) |

### 🟡 REPENSAR — depende de medição

| Peça | Decisão |
|---|---|
| `ai/critic.py` (juiz-LLM, 2 estágios, rubrica) | Ou vira o **validator do droid** (`--validator-model`), ou um **gate pós-loop** que reinjeta feedback. A rubrica (ARCH/NVDA) é valiosa — vira instrução do validator. |
| `core/agentic_loop.py` | O loop agêntico agora é o droid; sobra só o que for orquestração de alto nível. |
| Sub-agentes consultivos (`accessibility_auditor`, `engineering_reviewer`, `design_review`) | Viram **gates pós-loop** (rodam sobre o resultado) ou skills do droid via MCP. O `accessibility_audit` é o mais importante preservar como gate. |

## 3. Arquitetura alvo

```
Usuário (GUI leitor de tela)
   │  pedido em linguagem natural
   ▼
NVDAStudio (harness)
   │  monta: contexto NVDA (nvda_context) + regras + pedido  ─►  system-prompt.txt
   ▼
droid exec  --auto medium  -w (worktree isolado)
            --append-system-prompt-file system-prompt.txt
            --input-format stream-jsonrpc   (dirigido por programa)
   │   ┌──────────────── LOOP AGÊNTICO (droid dirige) ───────────────┐
   │   │  lê contexto → escreve arquivos → RODA → vê erro → corrige   │
   │   │  → roda testes → itera até achar que terminou                │
   │   └─────────────────────────────────────────────────────────────┘
   ▼
NVDAStudio pega o worktree resultante
   ▼
GATES DETERMINÍSTICOS (fora do modelo — o "done" real)
   • code_sandbox: o addon executa mesmo?
   • _missing_declared_files: os módulos declarados existem?
   • accessibility gate / rubrica
   • portão final do pacote
   │
   ├─ falhou? ──► reinjeta o erro na MESMA sessão droid (--session-id) ──► itera
   │
   └─ passou? ──► empacota .nvda-addon ──► entrega (com aviso honesto se degradou)
```

**A regra de ouro (dos 7 projetos e do próprio doc §1):** o **loop** é agêntico
(droid decide o conteúdo e as ações), o **gate** é determinístico (NVDAStudio
decide o "pronto", fora do modelo). Não se troca uma coisa pela outra — troca-se
só o **loop**, mantendo o **gate**.

## 4. O que muda no comportamento (o que você pediu)

- A IA **edita arquivos E roda comandos pra testar/validar**, iterando contra a
  realidade — igual Cursor/Claude Code. Não é mais "gera tudo e reza".
- **Multi-arquivo:** o droid mantém coerência iterando (lê/edita/roda através de
  vários arquivos), em vez do salto único que o doc §3 mostra derrubar até
  modelos de ponta pra ~25%.
- **Blast radius controlado:** worktree isolado + `--auto medium` (sem push,
  sudo, produção). Nunca `--skip-permissions-unsafe`.

## 5. Migração por slices (sem quebrar o que já funciona)

Cada slice é entregável, atrás de **feature flag** (o pipeline atual continua o
default até o novo empatar/superar).

- **Slice 0 — Spike (prova de conceito).** Um driver que roda `droid exec --auto
  medium -w` com um pedido simples ("addon que fala X num gesto"), num worktree,
  e passa o resultado pelos **gates atuais**. Mede: funciona? Custo? Compara com
  o pipeline atual no MESMO pedido.
- **Slice 1 — Contexto NVDA.** Injeta `nvda_context` como `--append-system-prompt-file`.
  A/B contra o pipeline staged nos addons do golden set (`test_e35`/`e36`).
- **Slice 2 — Loop de correção por gate.** Move `code_sandbox` + completude +
  accessibility pra pós-loop e reinjeta a falha na mesma sessão droid até passar
  ou esgotar budget. Aqui o "editar→rodar→corrigir" fecha de verdade.
- **Slice 3 — Aposentar o staged.** Quando o agêntico empatar/superar no golden
  set, desliga planner + sub-agents + tool_gateway (mantendo os gates). Remoção
  grande — cada um como slice contratada com regressão (a disciplina desta sessão).
- **Slice 4 — Backend-agnóstico.** Abstrai "agentic backend" pra Claude Code /
  Codex CLI também entrarem como motor (todos são agênticos), não amarrar na Factory.

## 6. Riscos e decisões honestas

- **Custo:** o loop agêntico itera → pode gastar mais tokens que o pipeline
  staged. Mas resolve o que hoje **não sai**. O budget/observabilidade já existem
  pra medir; a decisão "vale a pena?" vira dado, não achismo.
- **Dependência do droid:** hoje só a Factory tem saldo, e o droid é da Factory.
  Slice 4 abstrai isso — mas no começo o motor é o droid.
- **Segurança (doc de confiabilidade):** `--auto medium` + worktree = raio de
  dano contido. Checkpoints antes de aplicar o worktree no projeto real. Nunca
  autonomia total.
- **O que NÃO muda:** os gates determinísticos. Foi a lição da auditoria inteira
  (skillgate/unlazy/adl/aga-verify): "done" é decidido fora do modelo. O caminho
  3 troca o motor, não os trilhos.

## 7. Recomendação de partida

Começar pelo **Slice 0 (spike)**, atrás de flag, sem tocar no pipeline atual:
um driver mínimo que dirige `droid exec --auto medium -w` e valida pelos gates de
hoje. É barato, reversível, e responde a pergunta que decide tudo o resto:
**o loop agêntico gera um addon melhor que o pipeline staged, no mesmo pedido?**
Se sim, seguimos pelos slices. Se não, aprendemos por que — sem ter reescrito nada.
