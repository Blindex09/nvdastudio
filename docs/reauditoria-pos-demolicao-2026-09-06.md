# Re-auditoria FINAL do NVDAStudio contra os 7 projetos de `c:\confirmacao`

> Terceira e última passada, depois da **demolição do pipeline staged**. Estado:
> HEAD `f2fd627`. O NVDAStudio virou o que os 7 projetos pregam — sem legado.

## 0. O que mudou desde a re-auditoria anterior

O pipeline staged foi **removido por completo** (commit `f2fd627`,
**−45.169 linhas**): planner, Critic, 15 sub-agentes, agentic_loop,
domain_researcher, os corpos staged do orchestrator, e 130 arquivos de teste.
O NVDAStudio agora gera addons **só** pelo loop agêntico: o droid dirige
`editar → rodar → corrigir`, o gate determinístico (`code_sandbox`) julga.

Módulos de produção: **88 → 70**. Testes: ~254 → 115. Suíte: 3483 → **1220**
(os testes que sobraram cobrem o que sobrou de código; sem falso verde).

## 1. Ferramentas dos repos EXECUTADAS no estado novo

| Ferramenta | Resultado |
|---|---|
| `ruff` | exit 0 (addon inteiro) |
| `mypy` | **Success, 70 arquivos** |
| `pytest` | **1220 passed, 136 skipped, 0 failed** |
| skillgate | instruction-sync ✓, no-secrets ✓, no-todos ✓ (`tests-pass` é `npm test`, inaplicável) |
| unlazy `gate-check` | **ALL MET (4)** |
| bandit | 10 Low (subprocess dual-use), **0 Medium/High** |
| vulture | 3 (mínimo) |
| pip-audit | No known vulnerabilities |

## 2. Veredito de fundo: o NVDAStudio É a arquitetura dos 7 projetos

A 1ª auditoria disse "gate forte, **loop do passado**". A 2ª registrou o loop
virando agêntico. Esta fecha: **o loop do passado não existe mais.** O que
sobrou é exatamente o híbrido que os 7 convergem:

- **horizon** — o *agentic repair loop* (rode, veja o erro, corrija) é agora o
  ÚNICO caminho de geração. "Se não executou, não está verificado" virou o
  coração, não um degrau opcional.
- **skillgate / unlazy / adl** — o gate determinístico **fora do modelo**
  (`code_sandbox` valida execução; o droid não se autoaprova) é o juiz único.
- **Argus / Zaofu** — a forma (agente age, verificador confere) é o desenho.
- **segurança** — blast radius contido (workdir isolado + `--auto medium`).

Não há mais "duas arquiteturas convivendo". É uma só, limpa, agêntica.

## 3. Como chegamos aqui (para o registro)

Não foi lendo — foi **rodando**. O E2E real via Factory revelou (a) que o
staged era fraco/caro no complexo e (b) que a "falha" do agente no addon
complexo era um **falso-positivo do gate** (stub de `NVDAState`). Corrigido o
stub, o agente passou o complexo em 1 rodada. Essa evidência — obtida gastando
saldo real, não teorizando — foi o que justificou apagar o staged.

## 4. Lacunas honestas que a demolição deixou

1. **Código de suporte orfanado:** prompts do critic/planner, `get_docs_*` de
   sub-agente, `injection_guard.sanitize_untrusted_block`, e ~50 helpers/
   constantes perderam o consumidor com o staged. Foram **aceitos
   explicitamente** em `test_mecanismos_orfaos` (com motivo), não apagados às
   cegas — candidatos a uma **limpeza dedicada** (não cascatear no meio da
   demolição foi decisão consciente).
2. **Gate de acessibilidade mais fraco:** o sub-agente `accessibility_audit`
   saiu com o staged. O gate agêntico é `code_sandbox` (executa), que **não**
   audita acessibilidade. Reintroduzir uma checagem de acessibilidade no
   caminho agêntico (via MCP ou pós-gate) é o achado de maior valor agora.
3. **Um provedor só:** o motor é o droid (Factory). Abstrair "agentic backend"
   (Claude Code / Codex) segue como trabalho futuro.
4. **Tokens do agente não capturados** (comparação de custo é wall-clock).

## 5. Veredito

O NVDAStudio, em `f2fd627`, passa em todas as ferramentas determinísticas
executáveis dos 7 repos, com o pipeline staged **removido**. Deixou de ser um
projeto com um bom gate preso a um loop do passado e virou a **arquitetura
agêntica limpa** que ArgusAgent/Zaofu/adl/aga-verify/horizon/skillgate/unlazy
descrevem — descoberto e provado **executando de verdade**, não por lente. As
lacunas restantes (acessibilidade pós-staged, limpeza dos órfãos, multi-backend)
estão nomeadas, não escondidas.
