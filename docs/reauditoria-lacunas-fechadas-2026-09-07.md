# Re-auditoria do NVDAStudio contra os 7 projetos de `c:\confirmacao`

> Quarta passada, depois de **atacar as 4 lacunas** que a re-auditoria
> pós-demolição (`reauditoria-pos-demolicao-2026-09-06.md`) nomeou. Estado:
> HEAD `7d91364`. Auditoria real — as ferramentas rodaram, não é lente.

## 0. O que esta rodada fechou

A passada anterior terminou honesta: o pipeline staged tinha sido demolido, o
loop virara 100% agêntico, e sobraram **4 lacunas nomeadas** (não escondidas).
Esta rodada atacou **todas**, uma de cada vez, com gate verde a cada commit:

| # | Lacuna (re-auditoria anterior) | Como foi fechada | Commit |
|---|---|---|---|
| 1 | Gate de acessibilidade mais fraco (saiu com o staged) | `_run_accessibility_gate` roda os validadores AST do `ast_validator` (NVDA-019, wx a11y, controlTypes, MessageDialog-em-thread) dentro de `_run_gates` — determinístico, não LLM | `b706cf6` |
| 4 | Tokens do agente não capturados | `parse_droid_tokens` lê o envelope `droid exec -o json` (input+output+cache-creation, ignora cache-read); somados por rodada em `AgenticBuildResult.tokens` | `b706cf6` |
| 2 | ~50 helpers/constantes orfanados pelo staged | Limpeza dedicada: constantes+funções do orchestrator/timeouts, **5 módulos inteiros mortos** (anthropic_memory_tool, external_search, addon_versioning, cost_tracker, controller_client_context) e órfãos-membro de módulos que sobrevivem | `bfe1533`, `84028c4` |
| 3 | Um provedor só (motor = droid) | Costura `AgenticBackend` (Protocol) + `DroidBackend`; `get_backend()` por arg > env > droid. Um segundo motor é uma classe nova, não uma reescrita | `7d91364` |

### Achado de segurança (bônus da lacuna #2, não era só código morto)

Rastreando `injection_guard.sanitize_untrusted_block` (órfão), descobri que a
demolição do staged tinha **desligado a fronteira de injeção**: o request do
usuário ia **cru** para o `prompt.txt` do droid, que roda com ferramentas de
edição + terminal (blast radius real, doc 3 de segurança). Religado:
`detect_injection(request)` no driver — **avisa, não bloqueia** (o request é
instrução legítima, não dado inerte; o `--auto medium` contém o estrago). Com
regressão. Foi a demolição que abriu; esta rodada fechou.

## 1. Ferramentas dos repos EXECUTADAS no estado novo (`7d91364`)

| Ferramenta | Resultado |
|---|---|
| `ruff check` | exit 0 (addon + tests) |
| `mypy` | **Success, 66 arquivos** |
| `pytest` | **1173 passed, 136 skipped, 0 failed** |
| bandit | **0 Medium/High** (só Low de subprocess dual-use, esperado) |
| vulture (nosso código) | **1** achado — um parâmetro de contrato de callback (`domain_ctx`), não código morto |
| pip-audit | 1 vuln de dependência do AMBIENTE (`setuptools 65.5.0`, PYSEC-2026-1918/3447) — não é código do addon, é o Python local; anotado para atualizar o venv |

Módulos de produção: 70 → **66** (5 mortos apagados, 1 novo: `agentic_backends`).
Testes: 115 → **112** arquivos (removidos os que cobriam código deletado; sem
falso verde). A cada gap, o gate rodou antes do commit — nenhum subiu vermelho.

## 2. Veredito de fundo: mais alinhado do que na passada anterior

Cada uma das 4 correções **aprofundou** a tese dos 7 projetos, não só a manteve:

- **horizon** (loop de reparo agêntico) — segue sendo o único caminho, e agora o
  loop é **agnóstico ao motor** (lacuna #3): a costura `AgenticBackend` prova, com
  um backend fake nos testes, que o `editar→rodar→corrigir` não depende do droid.
  O loop do horizon nunca foi sobre um CLI específico; agora o código também não é.
- **skillgate / unlazy / adl** (gate determinístico fora do modelo) — o gate ficou
  **mais forte**: além de `code_sandbox` (execução real), agora também acessibilidade
  determinística por AST (lacuna #1). O juiz continua não sendo o executor.
- **aga-verify** ("se não executou, não está verificado" + evidência ligada ao
  snapshot) — a captura de tokens (lacuna #4) fecha a evidência de custo por rodada;
  o gate de execução real segue intacto.
- **ArgusAgent / Zaofu** (agente age, verificador confere) — a forma é a mesma; a
  costura de backend torna o "agente" plugável sem tocar o "verificador".
- **segurança (doc 3, blast radius)** — **melhorou de verdade**: a fronteira de
  injeção no request, que a demolição tinha aberto, foi religada exatamente na
  dimensão que os repos de segurança cobram.

## 3. Anti-legado aplicado à própria correção

A lição da lacuna #2 (código morto é o defeito mais caro) foi aplicada à lacuna
#3: a abstração de backend **não** carrega um `CodexBackend`/`ClaudeCodeBackend`
vazio e especulativo. Só existe o `DroidBackend`, o único CLI instalado. A prova
de que é plugável é a **costura + um backend fake nos testes**, não um segundo
motor morto no repositório. Fechar uma lacuna não pode reabrir a outra.

## 4. Lacunas restantes (honestas, não escondidas)

1. **`sanitize_untrusted_block`** continua aceito como órfão (primitivo de
   segurança correto): seu consumidor real era o wrapping de resultado de busca
   web, que saiu com o staged. Volta a ter uso quando a busca web voltar ao
   prompt. Não foi apagado (não se apaga primitivo de segurança correto por uma
   feature temporariamente ausente) nem fake-religado (envolver o request como
   "dado inerte" seria semanticamente errado).
2. **`setuptools` do ambiente** com vuln conhecida — é o venv local, não o addon;
   atualizar quando conveniente.
3. **`domain_ctx`** em `_on_conversational_plan_ready` — parâmetro de contrato de
   callback, não código morto; único achado do vulture no nosso código.
4. **Segundo backend real** (Claude Code/Codex) — trabalho futuro *quando* outro
   CLI for instalado; a costura já espera por ele.

## 5. Veredito

O NVDAStudio, em `7d91364`, fecha as **4 lacunas** que a auditoria anterior
nomeou, passa em **todas** as ferramentas determinísticas executáveis dos 7
repos, e sai desta rodada **mais** alinhado à arquitetura que
ArgusAgent/Zaofu/adl/aga-verify/horizon/skillgate/unlazy descrevem — inclusive
com um ganho de segurança que só apareceu porque a limpeza de órfãos foi feita
rastreando cada peça até o consumidor, não apagando às cegas. Descoberto e
provado **executando de verdade**, não por lente.
