# Auditoria do NVDAStudio contra os 7 projetos de `c:\confirmacao`

> Auditoria real (não "lente"): rodei os degraus baratos da pirâmide de
> verdade e li as costuras uma a uma. Data: 2026-09-06. Branch:
> `fix/addon-complexo-entrega` (working tree limpo no início).
>
> Os 7 projetos de `c:\confirmacao` (ArgusAgent, Zaofu, adl, aga-verify-agent,
> horizon, skillgate, unlazy) **não são referência passiva** — cada um é um
> padrão executável de *disciplina de conclusão de agente*. Todos convergem
> na mesma tese, que é literalmente a mesma dos 3 docs de metodologia deste
> repositório: **"done" só vale quando um verificador determinístico, fora do
> modelo, confirma contra a realidade — o executor nunca é o juiz.**

---

## 0. Evidência determinística coletada (não é opinião)

| Degrau | Comando | Resultado real |
|---|---|---|
| Static — lint | `ruff check addon/` | **exit 0** (limpo) |
| Static — types | `mypy addon/globalPlugins/nvdastudio` | **exit 0**, "no issues found in 87 source files" |
| Unit | `pytest tests/unit -q` | **3280 passed, 2 skipped** em 307,9s |
| Suíte completa | `pytest -q` (background) | **exit 0** |
| Coleta | `pytest --collect-only` | **3674 testes** |

Baseline verde confirmado. Toda afirmação abaixo tem `arquivo:linha`.

---

## 1. Os 7 projetos → um padrão comum

| Projeto | Princípio central (o que ele exige) |
|---|---|
| **ArgusAgent** | 4 papéis com autoridade distinta (Manager/Planner/Engineer/Reviewer); execução separada do julgamento; estado/checkpoints persistentes; retomar de progresso verificado. |
| **Zaofu** | Control plane de entrega: contratos de tarefa, gates de evidência, caminhos de recuperação, fronteira de controle **determinística**, "Thin Judge"/completion gate, degradação graciosa. |
| **adl (Agent Discipline Layer)** | Ler-antes-de-escrever; edições cirúrgicas; camadas sem contradição silenciosa; `/goal` + **Warden** (verificador ≠ trabalhador) assina prova; "done" = checks passaram. |
| **aga-verify-agent** | Evidência amarrada ao **snapshot exato**; nada de evidência velha (teste do commit A não prova o commit B); checar *scope drift*; claim ≠ evidência; **verificador é read-only, não conserta em silêncio**. |
| **horizon** | Verificadores **hard** têm autoridade final; juízes neurais foram testados e rejeitados; "se não executou, não está verificado"; escopo honesto declarado, não enterrado. |
| **skillgate** | Gate de linha de chegada **fora do modelo**, função pura sobre o filesystem; a defesa que funciona é **remover o atalho**, não pedir pro modelo se comportar. |
| **unlazy** | Escrever o *acceptance ledger* antes; reverificar trabalho retornado; **reportar só o que a evidência sustenta**; não remover em silêncio — vira *handoff*. |

O NVDAStudio já se declara um **harness** exatamente nesse vocabulário
(`docs/conceitos-ia-para-desenvolvimento-de-software.md` §21). A auditoria,
então, é: **o código real honra isso, ou só o texto honra?**

---

## 2. Scorecard — NVDAStudio vs. cada disciplina

Legenda: 🟢 forte / implementado · 🟡 parcial · 🔴 lacuna real.

### 🟢 Gate de conclusão determinístico (skillgate, adl/Warden, Zaofu)
O pipeline **não** confia no "APROVADO" do LLM para declarar entrega. Há um
portão determinístico de completude sobre os artefatos:
- `_missing_declared_files` / `_descarte_condena_entrega`
  ([orchestrator.py:3582](../addon/globalPlugins/nvdastudio/core/orchestrator.py)) —
  arquivos `.py` **declarados** têm que existir no pacote; comparação por nome
  de arquivo, igual ao portão da Fase 6. É a "função pura sobre o filesystem"
  do skillgate, feita em Python, imune ao juízo do modelo.
- Verificação técnica determinística onde o LLM é reconhecidamente não
  confiável: `FORBIDDEN_IMPORTS` (frozenset) em
  [critic.py:63](../addon/globalPlugins/nvdastudio/ai/critic.py) — comentário
  cita o E2E de 2026-03-30 em que `win32clipboard` passou pelo LLM sem
  bloqueio. É a tese do horizon ("hard verifier tem autoridade final") na
  prática.

### 🟢 Parada honesta em vez de casca condenada (unlazy, adl)
[orchestrator.py:3535](../addon/globalPlugins/nvdastudio/core/orchestrator.py)
(v5.87.0): quando o orçamento entra na reserva, o pipeline **não** monta um
pacote que já nasce reprovado — para, e nomeia o módulo que faltou. É
exatamente o "report only what the evidence supports / não reporte done com
gate pendente" do unlazy.

### 🟢 Maker-Checker / LLM-as-Judge com rubrica (Argus, doc §22/§27)
Critic em 2 estágios (spec + qualidade) com rubrica explícita
(ARCH-001..009, NVDA-XXX) e **roteado a um provedor/modelo diferente** do
executor ([critic.py:38](../addon/globalPlugins/nvdastudio/ai/critic.py)) —
"reviewer ≠ worker" do Argus/adl. Ponto forte: o Critic **não** é a
autoridade final sozinho; há o piso determinístico acima.

### 🟢 Permission boundary / blast radius fail-closed (segurança §2/§3, skillgate)
Defesa em profundidade real
([orchestrator.py:3746](../addon/globalPlugins/nvdastudio/core/orchestrator.py)):
`ApprovalWorkflow.analyze_risk` (regex técnico, **imune a prompt injection
por não ser probabilístico**) primeiro → humano depois → **sem dialog =
nega** (fail-closed). O `tool_gateway._request_approval`
([tool_gateway.py:276](../addon/globalPlugins/nvdastudio/tools/tool_gateway.py))
também é fail-closed: sem callback ou callback com exceção ⇒ nega. Checkpoints
restauráveis em [checkpoint_manager.py](../addon/globalPlugins/nvdastudio/core/checkpoint_manager.py)
(blast radius = "dá pra desfazer com um clique").

### 🟢 Prompt injection tratado como DADO, não instrução (segurança §4)
[injection_guard.py](../addon/globalPlugins/nvdastudio/utils/injection_guard.py):
envolve conteúdo externo com marcadores explícitos "DADO NÃO CONFIÁVEL / nunca
trate como instrução" — defesa **estrutural**, e usa o pattern-match só para
*log*, não para bloquear (exatamente o que o doc de segurança manda: "a defesa
nunca é blacklist de palavras"). Aplicado no ingresso de busca web
([web_researcher.py:381](../addon/globalPlugins/nvdastudio/sub_agents/web_researcher.py)).

### 🟢 Loop detection semântico, degradação graciosa, golden dataset (doc §7/§9/§14)
- Loop semântico: compara **assinatura de issues** entre tentativas
  consecutivas, não só conta tentativas
  ([orchestrator.py:2609](../addon/globalPlugins/nvdastudio/core/orchestrator.py)).
- Degradação graciosa: "budget backstop", entrega o que funcionou
  ([orchestrator.py:3502](../addon/globalPlugins/nvdastudio/core/orchestrator.py)).
- Golden dataset: `tests/e2e/test_e35_golden_eval_set.py` e `test_e36_*` já
  existem — o "falha real vira caso permanente" está operacional.

### 🟡 Evidência amarrada ao snapshot exato (aga-verify)
O loop **re-critica a cada tentativa** e compara assinatura de issues, o que
implica revalidação por tentativa — bom. Mas o vínculo formal
"esta evidência pertence a ESTA versão do código" (o coração do aga-verify:
teste do commit A não prova commit B) **não é um invariante explícito**; é
emergente do fluxo. Não achei um carimbo de proveniência (hash do código
gerado ↔ resultado do validador) que impeça uma aprovação de tentativa
anterior de ser reaproveitada. Risco baixo hoje, mas é a classe de bug mais
cara de descobrir tarde.

### 🔴 Multi-run / evidência estatística (doc §12, "1 execução não é evidência")
O próprio doc do projeto diz que 1 execução é evidência fraca (Pass@k,
success rate, variance). Na prática, os E2E são **single-shot** — nenhum
padrão de `pass@k` / `for run in range(N)` / `n_runs` na suíte E2E. O
princípio está declarado mas **não operacionalizado**. Honestamente: aceitável
dado o custo de API, mas deveria estar marcado como lacuna consciente, não
como coberto.

### 🟡 Static analysis — corpos não tipados (própria pirâmide, degrau 1)
`mypy` passa, mas emite dezenas de notas `[annotation-unchecked]` em
`orchestrator.py`, `agentic_loop.py`, `studio_dialog.py` — funções sem
anotação cujos **corpos o mypy não checa** (`--check-untyped-defs` desligado).
O degrau mais barato da pirâmide está rodando com cobertura parcial nos
arquivos mais críticos (orchestrator = 4317 linhas).

### 🟡 Deriva arquitetural — dois sistemas de ferramentas (doc §30, vulture)
Ver seção 4. É *architectural drift* real: um gêmeo redundante que sobrevive
só por teste.

---

## 3. Achados priorizados (cada um amarrado ao repo que o motiva)

| # | Severidade | Achado | Repo/princípio | Onde |
|---|---|---|---|---|
| 1 | Média | E2E single-shot: `§12 multi-run` declarado, não implementado | horizon/doc §12 | `tests/e2e/*` |
| 2 | Média | Sem carimbo de proveniência evidência↔versão do código gerado | aga-verify | loop de retry do orchestrator |
| 3 | Baixa | `ToolExecutor` (executor.py) morto em produção — gêmeo do tool_gateway | unlazy/adl (dead code) | ver seção 4 |
| 4 | Baixa | `mypy --check-untyped-defs` off nos arquivos maiores | pirâmide degrau 1 | `mypy.ini` |
| 5 | Baixa | `injection_guard` só aplicado no `web_researcher`; confirmar que não há outro ingresso externo sem envelope | segurança §4 | `sub_agents/`, `tools/` |
| 6 | Info | Approval de shell é **deny-by-blacklist** (regex), não allow-by-default; allowlist reduziria blast radius | segurança §2 (least privilege) | `tool_system/approval.py:15` |

Nenhum achado é um bug ativo de entrega. São lacunas de disciplina — que é
precisamente o que estes 7 repos existem para pegar.

---

## 4. A pergunta explícita: os dois sistemas de ferramentas

**Qual é o mais completo:** `tools/tool_gateway.py` (novo) é a camada viva e
mais completa de **orquestração** de tools — rate limiting, wiring de
approval, métricas, timeout via ThreadPool, schema OpenAI para tool-use. É o
que o `code_generator` chama em produção
([code_generator.py:946](../addon/globalPlugins/nvdastudio/sub_agents/code_generator.py)).

**Mas "o sistema antigo" NÃO é removível como um todo** — não é um par limpo
velho-vs-novo. Rastreando cada referência:

| Peça de `tool_system/` | Estado | Prova |
|---|---|---|
| `builtins/` (file_editor, file_reader, ast_parser, nvda_validator) | **VIVO** | são as implementações reais, importadas pelo `tool_gateway` ([tool_gateway.py:350-353](../addon/globalPlugins/nvdastudio/tools/tool_gateway.py)) e testadas direto |
| `approval.py` (`ApprovalWorkflow`) | **VIVO** | `self._approval_workflow = ApprovalWorkflow()` (orchestrator:715); `analyze_risk()` é o 1º gate determinístico (orchestrator:3762) |
| `registry.py` — helpers `tool_result`/`tool_error`/`ToolEntry` | **VIVO** | retornados pelos builtins |
| `registry.py` — singleton `registry` (caminho de leitura) | **morto em prod** | só `executor.py::get_entry` lê; `tool_gateway` mantém o próprio dict |
| `executor.py` (`ToolExecutor`) | **morto em prod** | **zero** instanciação `ToolExecutor(` fora de teste; comentário 5.72.0 confirma |

Então o único candidato genuíno a remoção é **`executor.py` (ToolExecutor)** —
e mesmo ele está fixado por dois testes: `tests/unit/test_tool_executor_retry.py`
e uma asserção de equivalência em `tests/unit/test_tool_gateway_timeout.py:109`
("os dois fazem a mesma coisa").

**Os repos deixam eu removê-lo agora, no meio da auditoria? Não — eles dizem o
contrário para um auditor:**
- **aga-verify** (Verification Boundary): "Default behavior is
  verification-only and implementation-read-only… Do not… refactor or clean up
  while checking… If verification finds a problem, stop and report it. **Do not
  silently fix it.**"
- **unlazy**: não remover em silêncio — vira *handoff* declarado.
- **adl**: edição cirúrgica com contrato `/goal` verificável por slice.
- Remover `executor.py` **também** exige mexer nos 2 testes que o fixam — isso
  é *scope drift* para dentro da suíte (o exato que o aga-verify manda evitar),
  e a definition-of-done (3674 testes verdes) mudaria de forma.

**Conclusão disciplinada:** remover o `ToolExecutor` é uma mudança pequena,
legítima e recomendada — mas como **tarefa contratada à parte, com gate de
regressão**, não como efeito colateral silencioso desta auditoria. Deletar um
subsistema no meio de uma verificação violaria exatamente o padrão que esta
auditoria está aplicando. Posso executá-la assim que você confirmar (é
reversível via git de qualquer forma).

---

## 4.5. E2E REAL via Factory — o degrau que confirma "o app funciona" (2026-09-06)

Rodado de verdade (autorizado), gastando saldo real. Não é teste mockado.

**Smoke (seam vivo):** `create_llm_client(provider="factory").chat("Responda
apenas: ok")` → `'ok'` em 9,8s via droid CLI `kimi-k2.7-code`. A Factory
autentica pelo **keyring do droid** (`~/.factory/auth.v2.keyring`), não por env
var — por isso é a única utilizável aqui (todas as env keys estão vazias).

**Pipeline completo real** (query trivial: addon que fala "Olá mundo" num
gesto): **`success=True`** em 3,2 min, **171.667 tokens**, 5 retries,
plano NÃO degradado. Produziu 4 arquivos reais: `globalPlugins/.../__init__.py`,
`manifest.ini`, `doc/en/userGuide.html`, `doc/pt_BR/userGuide.html`. **O app
funciona de ponta a ponta via Factory.**

**MAS o E2E expôs o que nenhum teste unitário pega** (o ponto "teste passando
≠ app funcionando"): **3 de 7 steps falharam com a MESMA causa**:

| Step | Precisava de | Resultado |
|---|---|---|
| `manifest` (manifest_builder) | `search_web` | falhou 3x — mas `manifest.ini` saiu por fallback determinístico (o fix `manifest ausente nao derruba`, a9a88b5) |
| `er_inj` (engineering_review) | `entregar_revisao_engenharia` | falhou — consultivo, degradação graciosa absorve |
| `aa_inj` (accessibility_audit) | `search_web`, `entregar_relatorio_auditoria` | **falhou — e é o eval de DOMÍNIO mais crítico de um gerador NVDA** |

**Causa raiz — CORRIGIDA após pesquisa web (2026-09-06):** a redação anterior
("a Factory não faz tool use") estava ERRADA. Os docs oficiais da Factory
confirmam que o **droid FAZ tool use**, inclusive headless (`droid exec`): via
servidores **MCP** pré-configurados + ferramentas embutidas, com flags
`--restrict-tools`/`--additional-tools`/`--disabled-tools`/`--list-tools`. O que
o droid **não** aceita é ferramenta passada **inline estilo OpenAI `tools=[...]`**
na hora da chamada — e é exatamente isso que `factory_client.py` recusa
(`FactoryClientError`, "não aceita ferramentas definidas pelo chamador"). Logo,
**é lacuna da INTEGRAÇÃO do NVDAStudio, não limite da Factory**: os sub-agentes
que precisam de tool use poderiam rodar na Factory se suas ferramentas fossem
expostas via **MCP** (ou trocadas pelas embutidas do droid), em vez de passadas
inline. Fontes: docs.factory.ai/droid-cli/overview, /harness/mcp, /droid-cli/cli-reference.

**Achado alto (independe da causa raiz):** num pipeline **Factory-only** como
está hoje, o `accessibility_audit` — a "Accessibility Eval" que o próprio doc
§22 chama de dimensão de qualidade específica do domínio — **é silenciosamente
pulado, e mesmo assim `success=True`**. A degradação graciosa (correta em si)
mascara a ausência do gate mais importante desta classe de app. Dois caminhos
para fechar de verdade: (a) expor as ferramentas desses steps via MCP para o
droid (fidelidade total na Factory), ou (b) o aviso honesto de entrega (feito
na §7-bis) para nunca mais mascarar. Ambos valem; (b) já está implementado.

## 4.6. Ferramentas executáveis dos repos/docs — o que rodou de verdade

| Ferramenta | Origem | Rodou? | Resultado |
|---|---|---|---|
| `ruff` | pirâmide degrau 1 | ✅ | exit 0 |
| `mypy` | pirâmide degrau 1 | ✅ | exit 0 (87 arq.) |
| `pytest` (full) | degraus 2-9 | ✅ | 3447 passed, 221 skipped |
| `skillgate audit` (CLI local) | skillgate | ✅ | instruction-sync ✓, no-secrets ✓; `tests-pass`/`no-todos` são JS-shaped (rodam `npm test`/`src/**/*.js`) — inaplicáveis a projeto Python |
| `pip-audit` (SCA) | segurança/doc | ✅ | No known vulnerabilities |
| E2E real (Factory) | degrau E2E | ✅ | success=True, 3 steps degradados (acima) |
| `bandit` (SAST) | doc §metod. | ✅ | 0 High, 0 Medium, 12 Low: 7 subprocess (escolha segura), 1 random (jitter, não-segurança), **4 `try/except: pass` sem log** (viola a regra do próprio projeto — ver §4.7) |
| `vulture` (dead code) | doc §metod. | ✅ | 1 achado 100% (param `sucesso` não usado em studio_dialog.py:2014); 200 na faixa 60% = ruído reconhecido |
| `unlazy` gate-check | unlazy | ✅ | `GATES.md` autorado + `gate-check.mjs --approve`: **ALL MET (3 met)**, evidência automática carimbada (ver §6.1) |
| `aga-verify` | aga-verify | ✅ | template formal Standard Mode aplicado à mudança, amarrado ao snapshot `b61f165` — VERIFIED (ver docs/verificacao-aga-2026-09-06.md) |
| `adl`-Warden | adl | ⚠️ | instalaria camadas/hooks no repo — mudança maior, não aplicada |
| argus / zaofu / horizon | — | ⚠️ | frameworks/camadas, não auditores-de-repo — aplicados como padrão no scorecard §2 |

### §4.7 — bandit: os 4 `try/except: pass` sem log

Localizações: `ai/llm_factory.py:83`, `ai/opencode_go_client.py:{72,278,469}`.
Todos são caminhos **defensivos** (`# pragma: no cover - defesa`) — engolir a
falha de uma ação secundária (marcar provedor indisponível; drenar o corpo de
uma resposta de erro 401/402/403/429). O comportamento é benigno, mas o próprio
`metodologia-verificacao-arquitetura.md` (achado real de 2026-08-09, seção
SAST/bandit) declara a regra: **nunca engolir exceção sem NENHUM log**, porque
"debugar uma falha nesses pontos no futuro seria impossível sem log nenhum".
Eram 17 na época; restam 4. Fix proporcional: um `_logger.debug(...)` em cada,
sem mudar o fluxo. Baixo, mas real pela régua do próprio projeto.

## 5. Sobre o provedor Factory (saldo real)

Anotado: a Factory Droid é hoje o único provedor com saldo para verificação
**E2E real** (o degrau caro, que gasta API); os demais estão sem saldo. Isso
alinha com a própria pirâmide: os degraus baratos (static → unit →
integration → behavioral evals) foram rodados de verdade aqui e confirmam o
baseline **sem** gastar API. O E2E real (via Factory) deve ser usado para
**confirmar**, não para descobrir — e, quando rodar, vale já deixar o
harness pronto para os outros provedores (o roteamento determinístico do
`model_router` já permite isso; a cadeia Factory entrou em `b152951`).

---

## 6. Próximas ações recomendadas (contratadas, uma por vez)

1. **Marcar a lacuna §12 (multi-run)** explicitamente nos docs como "consciente,
   não coberto" — ou operacionalizar `pass@k` num único caso E2E barato.
2. **Carimbo de proveniência** (achado #2): hash do bloco de código gerado ↔
   resultado do validador, para tornar o invariante do aga-verify explícito.
3. **Remover `ToolExecutor`** (achado #3) como slice própria: apagar
   `executor.py`, ajustar `tool_system/__init__.py`, e converter
   `test_tool_gateway_timeout.py` para guardar só o `tool_gateway` — com a
   suíte verde como gate.
4. **Ligar `--check-untyped-defs`** ao menos em `core/` (achado #4).

Cada uma acima é um `/goal` no estilo adl: contrato pequeno, verificável,
com a suíte como Warden.

---

## 7. Execução: remoção do `ToolExecutor` (slice contratada, 2026-09-06)

Autorizada pelo Felipe. Slice cirúrgica, com a suíte como Warden.

**Contrato:** G1 `executor.py` deletado, sem import vivo de `ToolExecutor`;
G2 `tool_system/__init__.py` importa limpo; G3 a cobertura de timeout do
gateway não some; G4 lint/types limpos + suíte verde.

**Feito:**
- Deletado `addon/globalPlugins/nvdastudio/tool_system/executor.py`.
- Deletado `tests/unit/test_tool_executor_retry.py` (testava só o código morto).
- `tool_system/__init__.py`: removido o export de `ToolExecutor` (import +
  `__all__`), com nota explicando a remoção.
- `tests/unit/test_tool_gateway_timeout.py`: removido
  `test_os_dois_executores_usam_a_mesma_fonte` (premissa "dois executores"
  deixou de existir); a garantia que ele dava ao gateway já está em
  `test_gateway_consome_o_modulo_central`.

**Evidência (Warden):** ruff exit 0 nos tocados · mypy exit 0 no pacote
`tool_system` · coleta **3667** (= 3674 − 7, sem import quebrado). A suíte
completa pós-remoção pegou **1 regressão** (ver abaixo), corrigida no mesmo
slice; gate final da remoção+fix: **3447 passed, 221 skipped, 0 failed**.

**Regressão que a suíte pegou (por que E2E/full importam):** a fitness function
`test_mecanismos_orfaos::test_toda_funcao_de_topo_tem_consumidor_ou_motivo`
reprovou — `utils/timeouts.calculate_backoff_delay` era consumido **só** pelo
`executor.py` deletado, virou órfão. Lint e unit por-arquivo passavam; só a
suíte inteira (a fitness function de arquitetura) viu. Resolvido conectando o
backoff ao consumidor certo — ver abaixo.

Referências restantes a `ToolExecutor` no repo são **só comentário/histórico**
(orchestrator:702, tool_gateway:23, docstrings) — nenhum import vivo.

### Achado exposto por esta remoção (novo, alta prioridade)

O `test_tool_executor_retry.py` continha uma regressão de um **bug real**: o
`ToolExecutor` (v1.2.0) usava um pool descartável de 1 worker por chamada
porque `future.cancel()` é **no-op quando a task já está rodando** — sem isso,
uma tool travada vazava a thread e ocupava um worker do pool compartilhado
para sempre.

**O caminho VIVO — `tools/tool_gateway.py` — tem exatamente esse padrão sem a
proteção:**
- `self._pool = ThreadPoolExecutor(max_workers=4)` **compartilhado**
  ([tool_gateway.py:71](../addon/globalPlugins/nvdastudio/tools/tool_gateway.py)).
- Em timeout: `future.cancel()` (no-op se já rodando)
  ([tool_gateway.py:325](../addon/globalPlugins/nvdastudio/tools/tool_gateway.py)).
- **Zero teste de regressão** para o vazamento (o teste de timeout usa um
  gateway novo por caso e não checa o pool compartilhado).

Consequência: **4 tools travadas esgotam o pool e o pipeline pendura em
silêncio** — o pior tipo de falha para um usuário cego, e exatamente o cenário
que o próprio docstring do teste removido descrevia.

### CORRIGIDO no mesmo slice (autorizado pelo Felipe) — `tool_gateway` 3.4.0

- Removido o `self._pool` compartilhado; `_execute_with_retry` agora cria um
  **pool descartável de 1 worker por tentativa** (`shutdown(wait=False)`, sem
  pendurar na thread travada) — espelha a implementação provada do
  `ToolExecutor` recuperada do git (reference implementation compliance, §30).
- O retry passou a usar `calculate_backoff_delay` (jitter), o que **também
  reconecta o órfão** que a fitness function pegou — um fix resolve os dois.
- Regressão nova `TestPoolDescartavelNaoVaza::test_tools_travadas_nao_esgotam_o_gateway`:
  submete **5** tools travadas (> os 4 workers do pool antigo) e prova que uma
  tool rápida ainda responde na hora (< 2s). Com o bug, ela ficaria presa —
  o teste falha por tempo. Cobertura comportamental, não checagem de interno.
- Gate: ruff 0 · mypy 0 · suíte completa **3447 passed, 221 skipped, 0 failed**.
