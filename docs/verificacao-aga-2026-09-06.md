# Aga Verify Agent — verificação da mudança (ToolExecutor + tool_gateway 3.4.0)

> Aplicação formal do skill `aga-verify-agent` (c:\confirmacao) sobre a mudança
> feita nesta sessão. Isto é verificação de conclusão de tarefa amarrada ao
> snapshot exato — **não** é code review. Standard Mode, com área de alto risco
> sinalizada (execução de ferramentas / concorrência).

```
Agent Work Verification

Verification Verdict:
VERIFIED  (para o snapshot identificado abaixo; ver Cannot Verify)

Why:
A tarefa autorizada — remover o ToolExecutor morto se os repos permitissem, e
depois portar a proteção de pool descartável + regressão para o tool_gateway —
foi cumprida. Toda evidência (lint, types, suíte, gate unlazy) foi reexecutada
contra ESTE working tree sujo, não contra um commit anterior. Maior risco
residual: a mudança toca um caminho de concorrência vivo (execução de tools);
mitigado por uma regressão comportamental que falha se o vazamento voltar.

Task Contract:
- Required:
  1. Remover ToolExecutor (gêmeo morto-em-produção) SE os repos permitirem.
  2. Portar pool descartável de 1 worker por chamada para o tool_gateway.
  3. Adicionar regressão que prova que o pool não vaza (tools travadas não
     esgotam o gateway).
- Out of scope: corrigir outros achados da auditoria (multi-run, proveniência,
  mypy untyped-defs); instalar adl/bandit/vulture; alterar produção fora do
  território de ferramentas.
- Verification expected: ruff + mypy limpos; suíte completa verde; a regressão
  nova falhando ANTES do fix e passando depois.
- High-risk areas: `_execute_with_retry` (concorrência, timeout, vazamento de
  thread); remoção de subsistema com testes que o fixavam.

Contract Authority:
- Level: Authoritative (instrução direta do usuário no chat).
- Source: "o antigo pode remover, se assim os repos disserem que pode remover";
  depois "sim" explícito para o pool descartável + regressão.
- Conflicts or assumptions: a disciplina dos próprios repos (aga-verify: não
  consertar em silêncio; unlazy: remoção vira handoff) foi respeitada — a
  remoção foi feita como slice contratada, não como efeito colateral.

Evidence Identity:
- Repository / branch: nvdastudio / fix/addon-complexo-entrega
- Base: 0995c2fec645a8bb1dc254c90111eb576bb9aa21
- Candidate snapshot: WORKING TREE SUJO (não commitado) sobre a base acima.
- Worktree state and dirty snapshot identity:
  `git diff | sha256sum` = b61f16575486dbb63f12b262a8191102a20be300dd22666b6c3f6d823d8f3e6a
  5 files changed, +85 / -451.
    M tool_system/__init__.py
    D tool_system/executor.py        (263 linhas removidas)
    M tools/tool_gateway.py
    D tests/unit/test_tool_executor_retry.py  (163 linhas removidas)
    M tests/unit/test_tool_gateway_timeout.py
    ?? docs/auditoria-confirmacao-2026-09-06.md, docs/verificacao-aga-2026-09-06.md (docs, não-código)
- Pre-existing changes: nenhuma — o working tree estava limpo no início da sessão.
- Evidence source and environment: execução local, Python 3.11, este mesmo tree.
- Commands / exit codes / executed against (todos contra o snapshot sujo acima):
  - `python -m ruff check addon/` → exit 0
  - `python -m mypy addon/globalPlugins/nvdastudio` → exit 0 (87 arquivos)
  - `python -m pytest -q` (suíte completa) → 3447 passed, 221 skipped, exit 0
  - unlazy `gate-check.mjs --approve` (G1 ruff / G2 mypy / G3 regressão+órfãos)
    → ALL MET (3 met), cada um exit=0; EXPECT=matched; output-sha256 carimbado.

Agent Claims:
- "Removi o ToolExecutor sem quebrar import vivo."
- "Portei o pool descartável e a regressão para o gateway."
- "Resolvi o órfão calculate_backoff_delay conectando-o ao retry do gateway."
- "Suíte completa verde."

Evidence Inventory:
- Bound evidence: os 4 comandos acima, reexecutados contra este tree; a coleta
  pytest (3667) sem import quebrado; a regressão nova passa; a fitness function
  de órfãos passa (antes reprovava por calculate_backoff_delay).
- Rejected as stale or unbound: nenhuma — nenhuma evidência foi herdada de um
  snapshot anterior.
- Missing: E2E de fidelidade total (ver Cannot Verify).

Claim Vs Evidence:
| Claim | Evidência amarrada ao snapshot | Status | Notas |
|---|---|---|---|
| ToolExecutor removido sem import vivo | grep sem `ToolExecutor`/`tool_system.executor` fora de comentário; coleta 3667 ok | VERIFICADO | refs restantes são histórico |
| Pool descartável no gateway | diff de `_execute_with_retry` (pool por tentativa, shutdown(wait=False)) | VERIFICADO | espelha o executor recuperado do git |
| Regressão prova não-vazamento | `TestPoolDescartavelNaoVaza` passa; 5 tools travadas + tool rápida < 2s | VERIFICADO | comportamental, não checa interno |
| Órfão resolvido | `test_mecanismos_orfaos` passa (antes: FAIL em calculate_backoff_delay) | VERIFICADO | um fix resolve os dois |
| Suíte completa verde | pytest -q → 3447 passed, 0 failed | VERIFICADO | reexecutado neste tree |

Scope Drift And Attribution:
- Dentro do escopo: os 5 arquivos de código/teste. O fix do órfão
  (calculate_backoff_delay) NÃO é drift — era pré-condição para a suíte ficar
  verde após a remoção, e foi resolvido no consumidor certo.
- Fora do código: 2 docs de auditoria (adicionais, não alteram produção).
- Nenhum arquivo não-relacionado (auth, config, produção fora de ferramentas)
  foi tocado.

Verification Fit:
- Appropriate. Os degraus baratos + a regressão comportamental cobrem a classe
  de bug relevante (vazamento de thread). Exact proof needed next: E2E real
  exercendo o gateway sob concorrência com um provedor de tool use nativo.

Docs Truth Check:
- Required: docstrings que citavam o executor removido; changelog do módulo.
- Status: `test_tool_gateway_timeout.py` docstring atualizada para passado +
  aponta a nova regressão; `tool_gateway` bumpado 3.3.0 → 3.4.0; `__init__.py`
  com nota da remoção. Consistente com o código.

Cannot Verify:
- Item: comportamento end-to-end do gateway sob N tools travadas em PRODUÇÃO
  real (NVDA + provedor com tool use).
  Missing access/environment/authority: provedor com tool use nativo e saldo
  (a Factory, único com saldo, não aceita ferramentas passadas inline pela
  integração atual — ela FAZ tool use via MCP; é lacuna da integração, não
  limite da Factory. Ver auditoria §4.5, corrigido após pesquisa web).
  What would prove it: um E2E que force timeouts reais concorrentes.
  Blocking the next gate: não bloqueia; a regressão unitária cobre a mecânica.

Human Inspection First:
1. `tools/tool_gateway.py::_execute_with_retry` — confirmar que shutdown(wait=False)
   não reintroduz espera na thread travada.
2. `tests/unit/test_tool_gateway_timeout.py::TestPoolDescartavelNaoVaza` — confirmar
   que o limite de 5 > 4 e o `< 2.0s` de fato distinguem fixo de quebrado.

Next Action:
- Verification verdict: VERIFIED para o snapshot b61f165 (working tree sujo).
- Workflow action: PROCEED TO CODE REVIEW.
- Code review status: required — verificação não substitui code review.
- Human next action: revisar os 2 pontos acima; se ok, commitar o slice.
- Agent next instruction: ao commitar, manter os docs de auditoria juntos ou à
  parte, conforme preferência; não misturar com outros achados não-contratados.
- Human inspection first: ver "Human Inspection First" acima.
- Verification needed before merge: rodar a suíte completa uma vez no snapshot
  COMMITADO (a evidência atual é do tree sujo; após commit, o candidate snapshot
  muda de identidade e a evidência deve ser reconfirmada — princípio central do
  aga-verify).
- Do not: mergear enquanto a evidência estiver amarrada só ao tree sujo e não ao
  commit final.
```
