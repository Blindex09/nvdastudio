# Re-auditoria REAL do NVDAStudio contra os 7 projetos de `c:\confirmacao`

> Segunda passada, pedida pelo Felipe: "audite de novo de forma real, não só
> lente". Reflete o estado NOVO (HEAD `d3d7158`), depois das 6 mudanças da
> sessão + o driver agêntico (Caminho 3, Slices 0 e 1). Ferramentas dos repos
> EXECUTADAS de verdade, não mapeadas conceitualmente.

## 0. O que rodou (ferramentas reais, não lente)

| Ferramenta (origem) | Rodou | Resultado |
|---|---|---|
| `ruff` (pirâmide degrau 1) | ✅ | exit 0 |
| `mypy` (degrau 1) | ✅ | exit 0 (88 arquivos) |
| `pytest` suíte completa | ✅ | 3463 passed, 221 skipped |
| **skillgate** `audit` (CLI local do repo) | ✅ | instruction-sync ✓, no-secrets ✓, no-stray-todos ✓; `tests-pass` ✗ é JS-shaped (`npm test`), inaplicável a Python |
| **unlazy** `gate-check.mjs --approve` | ✅ | **ALL MET (4)** — ruff, mypy, bandit(sem média/alta), driver+fitness; evidência carimbada |
| **aga-verify** (disciplina + snapshot) | ✅ | snapshot LIMPO e commitado (HEAD `d3d7158`) — evidência amarrada a commit, não a tree sujo |
| **bandit** (SAST) | ✅ | 10 Low, **0 Medium, 0 High** |
| **vulture** (dead code) | ✅ | 1 achado → corrigido → **limpo** |
| **pip-audit** (SCA) | ✅ | No known vulnerabilities |
| E2E real (Factory) | ✅ | 2 addons agênticos gerados e válidos (RelogioFalante, ContadorPalavras) |

Não rodável como auditor-de-repo: argus/zaofu/horizon (frameworks, aplicados
como padrão). adl (instalaria hooks no repo — não feito).

## 1. O que MUDOU desde a 1ª auditoria (achados fechados)

A 1ª auditoria (`auditoria-confirmacao-2026-09-06.md`) listou lacunas. Estado agora:

| Achado da 1ª passada | Status |
|---|---|
| `ToolExecutor` morto (dead code) | ✅ **removido** (commit 0e7e6e9) |
| `tool_gateway` vazava thread (pool compartilhado) — bug VIVO | ✅ **corrigido** + regressão (0e7e6e9) |
| `accessibility_audit` pulado em silêncio com success=True | ✅ **corrigido**: aviso honesto no chat + fala (27789e0) |
| 4 `try/except: pass` sem log (bandit B110) | ✅ **corrigido** (5862750) — bandit B110 agora = 0 |
| `sucesso` variável morta (vulture) | ✅ **corrigido** (este commit) |
| E2E single-shot / §12 multi-run declarado não implementado | ⚠️ **ainda aberto** (design; single-shot por custo) |
| `mypy --check-untyped-defs` off nos arquivos grandes | ⚠️ **ainda aberto** (slice própria) |

## 2. A virada de arquitetura MUDA o veredito de fundo

A 1ª auditoria disse: NVDAStudio tem **gate forte + loop fraco** (staged). Os 7
projetos convergem num híbrido: **loop agêntico + gate determinístico**. O
Caminho 3 (Slices 0 e 1, agora commitados) começa a fechar exatamente essa
lacuna:

| Princípio dos repos | Antes | Agora (com `agentic_driver`) |
|---|---|---|
| **horizon**: "se não executou, não está verificado"; loop de reparo agêntico | loop staged de tiro único + 1 retry | o droid **RODA** o que escreve e **itera** contra o erro real (`--auto medium`) |
| **skillgate/unlazy/adl**: gate determinístico FORA do modelo | ✅ já tinha | ✅ **mantido** — `run_agentic_build` exige manifest+entry+sintaxe; Slice 2 pluga `code_sandbox` |
| **segurança** (blast radius / least privilege) | sandbox de validação | workdir descartável + `--auto medium` (sem push/sudo/produção), nunca `--skip-permissions-unsafe` |
| **aga-verify**: proveniência / snapshot | — | mudanças commitadas, evidência por commit |

Ou seja: o projeto está **andando para a arquitetura que os próprios 7 projetos
pregam**, não se afastando dela. A 1ª auditoria era "gate bom, loop do passado";
esta registra que o loop começou a virar agêntico, mantendo o gate.

## 3. Achados novos desta passada

- **bandit**: os 10 Low são todos `subprocess` dual-use (`B404`/`B603`) em
  `code_sandbox`, `factory_client`, `hidden_process` e o novo `agentic_driver` —
  legítimos (rodam droid/python/pip com argumentos controlados, não input do
  usuário) — mais 1 `B311` (`random`) que é jitter de backoff, já com `# nosec`
  explícito. **Nenhum é vulnerabilidade real.** Zero Medium/High.
- **Cobertura do novo módulo**: `agentic_driver` entrou nas DUAS fitness
  functions (órfãos + spec de módulos) na hora em que nasceu — a lição da 1ª
  sessão aplicada de imediato (declarar a peça nova antes de a suíte reprovar).

## 4. Lacunas que permanecem (honestas)

1. **Multi-run (§12):** E2E/spikes ainda são single-shot. O A/B do Slice 1 foi
   1 addon representativo, não a distribuição do golden set. Continua sendo o
   degrau mais fraco vs. o que os repos pedem ("1 execução não é evidência").
2. **A/B formal do golden set:** o Caminho 3 precisa medir agêntico × staged no
   `test_e35`/`e36` inteiro para justificar aposentar o staged (Slice 3). Ainda
   não medido — custa saldo e tempo.
3. **`--check-untyped-defs`:** os arquivos grandes (orchestrator/agentic_loop)
   seguem com corpos não checados pelo mypy.

## 5. Veredito

O NVDAStudio, no estado `d3d7158`, passa em TODAS as ferramentas
determinísticas executáveis dos repos (ruff, mypy, pytest 3463, skillgate nos
checks aplicáveis, unlazy ALL MET, bandit sem média/alta, vulture limpo,
pip-audit limpo). As lacunas de disciplina da 1ª passada foram fechadas, exceto
as duas de design (multi-run e untyped-defs), explicitamente registradas. E o
eixo estrutural — "loop do passado" — começou a virar o loop agêntico das
ferramentas de ponta, sem abrir mão do gate determinístico que é a tese central
dos 7 projetos. **Próximo degrau real: o A/B do golden set (Slice 1.5) para
transformar "parece melhor" em evidência estatística (§12).**
