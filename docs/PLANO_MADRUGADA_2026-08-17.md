# Plano para o loop de E2E real — madrugada 2026-08-17/18

Documento deixado a pedido do Felipe: "deixa anotado para fazer esse teste
e2e real na madruga... vai fazer um loop... qualquer problema que voce ver
mesmo quando o teste passar, voce vai corrijir, e ir executando, e
corrijindo e ir executando até dar certo".

## AUTORIZAÇÃO PADRÃO — ATUALIZADO (mensagem final do Felipe antes de dormir)

> "vou estar dormindo, a api rodar e2e mesmo para as correções se der erro
> no e2e real. voce tem que fazer o que a api falar pra fazer. sempre
> quando ver um erro nos testes, é a api real quem vai dizer onde está o
> erro. voce vai corrijindo, eu vou estar dormindo, eu quero acordar depois
> de 8h com tudo feito entendeu, o app funcionando de verdade, voce vai
> fazer o que é possível e o que nao for, só se nao tiver jeito mesmo, ai
> vou me deparar com esbarramento seu... nao queoro saber, voce é meu
> funcionário, tem que trabalhar."

**Isso muda o nível de autorização pra esta sessão especificamente, pelas
próximas ~8h:**

- **NÃO perguntar antes de continuar o loop.** Rodar → ler o erro real que
  a API devolveu → corrigir a causa raiz → validar barato (ruff/mypy/
  pirâmide) → rodar de novo. Repetir sozinho, sem pausar pra confirmação,
  durante toda a janela de ~8h.
- **A API real é quem manda o que corrigir.** Não especular bug antes de
  ver o erro real acontecer — deixar o `test_e36` (e qualquer outro E2E
  necessário) rodar, ler o erro de verdade, e SÓ AÍ decidir o fix. Não
  inventar problema que a API não mostrou.
- **Pesquisar na web quando precisar.** Documentação oficial de NVDA,
  addons, providers (Ollama, OpenCode Go/opencode.ai, OpenAI) — sempre
  priorizando fontes/práticas de **2026**, nunca memória de treino
  desatualizada. Mesma disciplina já usada o dia inteiro hoje (fatos
  técnicos confirmados via busca real, não suposição).
- **Só interromper e esperar o Felipe se travar de verdade, sem jeito
  nenhum** — ex: ação destrutiva irreversível necessária, custo/limite de
  API estourado sem alternativa, ambiguidade que exige decisão de produto
  (não técnica) que só o Felipe pode tomar. Qualquer coisa tecnicamente
  resolvível — resolver e seguir.
- **Meta ao final das ~8h:** o app funcionando de verdade, o máximo
  possível do que for tecnicamente alcançável nesse tempo. Se sobrar algo
  genuinamente impossível de resolver sozinho, documentar claramente o
  motivo (não só "não deu tempo") pro Felipe ver ao acordar.
- Ser o especialista sênior aqui: julgamento técnico é meu, execução é
  minha, só escalo o que for realmente insolúvel sem a decisão dele.

Este arquivo é o contrato do que fazer, sem precisar perguntar de novo.

## Estado no momento em que este documento foi escrito

- Pirâmide completa (`tests/unit` + `tests/integration`): verde, 2635+
  passed, 0 failed (última rodada confirmada: 09:05 min).
- 4 bugs reais corrigidos hoje e confirmados **ao vivo** contra a API real
  do Ollama:
  1. `orchestrator.py` 5.52.0 — escalação com `reasoning_effort=high` não
     disparava de verdade depois do switch proativo de modelo.
  2. `orchestrator.py` 5.53.0 — `_try_escalation()` reportava
     `retries_used` errado e nunca chamava `memory.log_step_metric()`
     (achado pela própria suíte de testes ao rodar a pirâmide após o fix
     #1).
  3. `planner.py` 2.28.0 — `_inject_core_step()`: garante que sempre exista
     um step `code_generation` final integrando todos os outros, quando o
     pedido decompõe em 3+ features (ARCH-010). Sem isso, o addon final
     podia sair sem `__init__.py`/`class GlobalPlugin` — NVDA nunca
     carrega.
  4. `orchestrator.py` 5.54.0 — `syntax_validation` (sub-agente 100%
     determinístico, só `ast.parse()`) estava sendo julgado pelo Critic
     (LLM) sem regra específica, e era rejeitado sistematicamente por
     devolver "SKIP" (resposta correta quando não há bloco Python no
     contexto) — gastava retries/tokens à toa. Agora
     `_evaluate_syntax_validation_deterministically()` interpreta o
     contrato `RESULTADO: PASS/FAIL/SKIP` direto, sem chamar LLM.
- Confirmado com teste E2E real pequeno (`tests/e2e/
  test_e38_inject_core_step_multi_feature_simples.py`, pedido trivial de 3
  features locais sem API externa): pipeline `success=True`, `__init__.py`
  com `class GlobalPlugin` de verdade no disco, os 4 steps
  `syntax_validation` aprovando com `score=100 retries=0 tokens=0`.
- **NOVO hoje, ainda sem validação E2E real**: `critic.py` 3.19.0 — o
  Critic (avaliador de TODOS os steps) agora é roteado SEMPRE pro OpenCode
  Go (`gpt-5.6-luna` primário, `grok-4.5` fallback), independente do
  provider ativo do usuário (Ollama continua sendo usado por
  `code_generation` e todos os outros sub-agentes — só o Critic mudou).
  Motivo: prompt caching real confirmado ao vivo no OpenCode Go (2ª chamada
  com mesmo prefixo = 99.5% cache hit), que o Ollama Cloud não tem. Testes
  unitários mockados passam (182/182), mypy limpo, ruff limpo. **Chave
  `apiKeyOpenCodeGo` foi adicionada ao `nvda.ini` do Felipe** (copiada da
  chave que ele já tinha configurada no addon VisionAssistant, mesma conta
  opencode.ai) — sem isso o Critic quebraria em toda avaliação.

## O que fazer no loop (ordem exata)

1. **Confirmar a chave.** Antes de qualquer coisa, confirme que
   `apiKeyOpenCodeGo` está em `C:\Users\olive\AppData\Roaming\nvda\nvda.ini`
   seção `[nvdastudio]`. Se não estiver (por qualquer motivo), o Critic vai
   falhar em TODO step — isso não é um bug de código pra "corrigir", é
   configuração ausente. Se sumiu, restaure do backup
   `nvda.ini.bak_pre_opencode_key_20260817_190305` (mesma pasta) e reaplique
   a linha, ou pergunte ao Felipe.

2. **Rodar o E2E real GRANDE**: `tests/e2e/test_e36_golden_eval_set_complexo.py`
   (os 2 casos: `assistente_leitura_gemini`, `gemini_multimodal_midia`).
   Comando exato (rodar em background, sem duplicar processos — confirme com
   `wmic process where "name='python.exe' and commandline like '%pytest%'"
   get ProcessId,CommandLine` antes de lançar):
   ```
   cd C:\nvdastudio
   python -u -m pytest tests/e2e/test_e36_golden_eval_set_complexo.py -v -s > /tmp/e2e_madrugada_N.log 2>&1; echo "EXIT=$?" >> /tmp/e2e_madrugada_N.log
   ```
   Isso é CARO e DEMORADO (rodadas anteriores levaram de ~30min a 3h+ por
   caso, com custo real de API tanto no Ollama quanto agora no OpenCode Go
   via Critic). Esperado e autorizado por Felipe.

3. **Ler o relatório completo, não só `PASSED`/`FAILED` do pytest.** O
   teste em si só verifica que os 5 bugs históricos específicos que ele
   guarda não voltaram (ver docstring do arquivo) — ele passar NÃO significa
   que o addon gerado está perfeito. Leia a seção `--- STEPS INDIVIDUAIS
   ---`, `--- VALIDACAO ESTRUTURAL ---` e `--- EVENTOS DE PROGRESSO ---` do
   log pra cada caso. Preste atenção especial em:
   - `__init__.py: AUSENTE` ou `ESTRUTURA-008` na lista de problemas —
     deveria estar resolvido pelo fix #3 acima, mas CONFIRME de verdade,
     não assuma.
   - Steps `syntax_validation` (`sv_*`) — devem aprovar rápido
     (`retries=0 tokens=0`), confirmando o fix #4. Se algum voltar a gastar
     retries, o bypass determinístico quebrou — investigue
     `_evaluate_syntax_validation_deterministically()` em orchestrator.py.
   - Qualquer step que esgota `retries=3` e nunca aprova — leia o `ISSUE:`
     completo (não só a primeira linha truncada no relatório resumido; o
     `.json` completo em `tests/e2e/relatorios/` tem o texto integral).
   - Orçamento de tokens (`iteration_budget`) — se estourar de novo (como
     aconteceu numa rodada de hoje, chegou a 1M+ contra teto de 500k),
     isso é sintoma de outro problema real gastando retries à toa, não
     "aceitar e seguir".
   - Confirme que o Critic está de fato usando OpenCode Go agora (procure
     no log por `opencode_go` ou pelo client sendo inicializado com
     `gpt-5.6-luna`/`grok-4.5` — deve aparecer contexto de inicialização
     de client como já aconteceu com Ollama/OllamaClient antes).

4. **Qualquer problema real encontrado (mesmo que o teste passe no pytest):
   investigar a causa raiz e corrigir.** Mesmo padrão usado o dia inteiro
   hoje:
   - Confirmar se é regressão real de código ou variabilidade normal de
     LLM (o próprio `test_e36` documenta que nem todo passo aprovar é
     esperado/exigido — não force "100% de aprovação" como critério, force
     "nenhum bug de CÓDIGO real, mesmo que o modelo falhe uma vez por
     limitação genuína dele").
   - Se for bug real: ler o código relevante, aplicar o fix mínimo e bem
     escopado (nunca reescrever módulo inteiro), bump de `MODULE_VERSION` +
     changelog datado explicando a causa raiz encontrada, comentário no
     código só onde o "porquê" não é óbvio.
   - Escrever teste de regressão NOVO (mockado, sem custo de API) que prove
     que o bug existia (falha sem o fix) e que o fix resolve (passa com o
     fix) — mesmo padrão usado em `test_orchestrator_replan.py::
     TestEscalacaoDeVerdadeAposSwitchProativo` e `test_planner.py::
     TestInjectCoreStep` hoje.
   - Rodar `ruff check` no(s) arquivo(s) tocado(s).
   - Rodar `python -m mypy <arquivo(s)>` no(s) arquivo(s) tocado(s).
   - Rodar `python scripts/check_version_asserts.py` e corrigir qualquer
     pin de versão desatualizado que aparecer (são sempre triviais — só
     atualizar o número esperado no teste pra bater com o MODULE_VERSION
     real).
   - Rodar a suíte de testes unitários relevante ao módulo tocado.
   - Rodar a pirâmide completa (`tests/unit tests/integration`) ANTES de
     rodar o E2E de novo — mais barato, pega regressão óbvia sem gastar
     API.

5. **Repetir o loop, SOZINHO, sem pausar pra perguntar.** Depois de
   qualquer fix, relançar o MESMO `test_e36` completo (os 2 casos) de novo,
   do zero. Continuar o ciclo rodar → ler de verdade o erro que a API real
   devolveu → corrigir a causa raiz → validar barato (ruff/mypy/pirâmide)
   → rodar de novo. A API é quem aponta o próximo problema — não
   especular, deixar ela mostrar.

6. **Quando ampliar o escopo do E2E:** se `test_e36` rodar limpo (sem bug
   de código novo) antes das ~8h acabarem, não parar aí — usar o tempo que
   sobrar pra rodar outros cenários reais (outros pedidos de addon,
   variações de complexidade, outros step_types como `agent_runner`) que
   ainda não foram exercitados hoje, sempre pelo mesmo ciclo
   rodar → ler → corrigir → validar → rodar de novo. A meta é "app
   funcionando de verdade" o mais abrangente possível, não só os 2 casos
   fixos do golden set.

7. **Quando parar de vez:** quando as ~8h se esgotarem, OU quando travar
   em algo genuinamente sem solução técnica sozinho (ver seção de
   bloqueios reais abaixo). Ao parar, escrever um resumo final claro e
   honesto: o que foi corrigido, o que foi validado de verdade (ao vivo,
   não só mockado), e o que ficou pendente com o motivo real (não "não deu
   tempo" genérico).

## Coisas aprendidas hoje que valem a pena não esquecer

- **Nunca duplicar processos pytest em background.** Isso já causou lentidão
  severa uma vez hoje (pirâmide de 17min virou 1h34min por contenção de
  CPU com 4 processos duplicados rodando ao mesmo tempo). Sempre `wmic
  process where "name='python.exe' and commandline like '%pytest%'" get
  ProcessId,CommandLine` antes de lançar qualquer teste novo em background.
- **`narrate()` é deliberadamente silenciosa em testes pytest** — ausência
  de saída no log NÃO significa hang. Pra confirmar que um processo E2E
  ainda está vivo e trabalhando de verdade (não travado), usar
  `netstat -ano | grep ESTABLISHED` procurando conexão ativa do PID do
  processo, ou comparar `UserModeTime`/`KernelModeTime` via wmic entre dois
  checks (se o tempo de CPU avança, está processando; se IP estabelecido
  existir mas CPU não avançar, pode estar esperando resposta de rede
  normalmente — isso também é esperado, não é hang).
- **Editar um arquivo `.py` enquanto um processo pytest já rodando faz
  `inspect.getsource()` nele** pode causar falha espúria (linha
  deslocada) — se isso acontecer, rode o teste isolado de novo antes de
  assumir regressão real.
- **`scripts/check_version_asserts.py` só pega `assert MODULE_VERSION ==`
  literal ou com alias explícito** (`MODULE_VERSION as X`) — já foi
  corrigido hoje pra pegar alias, mas fique atento a qualquer padrão novo
  de import que ainda escape dele.
- **`test_e36` NÃO exige `success=True` nem 100% de aprovação por
  design** — ler a docstring do próprio arquivo antes de tratar qualquer
  rejeição isolada como bug obrigatório de corrigir.

## Progresso registrado (atualizado durante o loop, não reescrever o histórico acima)

- **Rodada 1** (imediatamente após o Critic mudar pra OpenCode Go): FALHOU
  imediatamente em ambos os casos — `apiKeyOpenCodeGo` não estava no
  ambiente do processo pytest (só no `nvda.ini`, que os stubs de teste não
  leem). Corrigido: chave adicionada como `apiKeyOpenCodeGo` no `nvda.ini`
  real E os 14 arquivos `tests/e2e/test_*.py` tiveram o skip guard
  atualizado pra exigir `OPENCODE_GO_API_KEY` também (senão "passam" no
  pytest sem testar nada de verdade — achado real, corrigido).
- **Rodada 2** (com as 2 chaves certas): rodou de verdade (2.5M+2.2M
  tokens, ~38-43min por caso). Confirmado que os bugs de escalação/cg_core
  NÃO voltaram (`ESCALANDO` disparou 14x com sucesso). Mas taxa de
  aprovação caiu bastante (3/13, 3/16) e nenhum addon foi montado — Critic
  mais rigoroso pegando bugs reais (imports proibidos, apply_config_spec()
  nunca chamado, erros de sintaxe) que antes passavam.
- **Rodada 3**: confirmou taxa de aprovação baixa persistente no caso 1
  (1/10) — não foi acaso da rodada 2. Caso 2 travou em 17s com **429 Too
  Many Requests do Ollama Cloud logo na primeira chamada do Planner**
  (achado real: sessão de horas rodando pipelines pesados sem pausa
  esgotou o rate limit da conta). BUG REAL corrigido:
  `ollama_client.py` 2.24.0 — `_retry_after_seconds()` agora lê e honra o
  header HTTP `Retry-After` (confirmado via pesquisa 2026 que a Ollama
  Cloud manda esse header em 429), em vez do backoff fixo de 15s que era
  insuficiente pra um rate limit real. 10 testes de regressão novos, ruff/
  mypy limpos, pirâmide rodando de novo antes da rodada 4.
- **Ainda em aberto**: a taxa de aprovação baixa do Critic mais rigoroso
  (rodadas 2/3) pode estar LIGADA ao 429 (Ollama sob pressão de capacidade
  gerando qualidade pior de geração, não só julgamento mais rigoroso) —
  com o fix de Retry-After, rodadas futuras devem ter menos contenção de
  rede/rate-limit; observar se a taxa de aprovação melhora naturalmente
  antes de considerar isso um problema separado a corrigir.

- **Ainda na verificação pós-fix (pirâmide)**: um teste UNITÁRIO
  (`test_session_memory.py`, deveria ser 100% mockado/sem rede) quebrou
  porque fez chamada de rede real e tomou o mesmo 429 — revelou bug real
  separado: `memory/relevance.py::rank_relevant()` devolvia lista VAZIA
  sempre que a seleção semântica LLM falhava por qualquer motivo,
  apagando TODA a memória de sessões passadas exatamente quando o
  provedor está instável. Corrigido (`relevance.py` 2.1.0): fallback
  agora devolve os primeiros `limit` candidatos na ordem recebida em vez
  de lista vazia — graceful degradation de verdade. 5 testes de
  regressão novos, ruff/mypy limpos.

- **Rodada 4**: 429 imediato em AMBOS os casos (22s/20s), mesmo com o fix
  de Retry-After já aplicado — confirmado que a Ollama simplesmente não
  mandou o header desta vez (fallback caiu certinho pro backoff antigo
  5s/10s, comportamento esperado e correto). A conta continua sob rate
  limit mesmo ~3h30 depois do início do loop e várias rodadas pesadas
  seguidas. Mudança de estratégia: parar de insistir cegamente com rodadas
  completas caras — usar `tests/e2e/test_smoke_conectividade_providers.py::
  TestSmokeConectividadeOllama::test_ollama_responde` (chamada única,
  barata) pra confirmar que a conta se recuperou ANTES de comprometer outra
  rodada completa de `test_e36`. Esperar mais tempo entre tentativas
  (30-60min) em vez dos ~20-40min usados até aqui.

## Pesquisa na web — autorizada e esperada

Sempre que a causa raiz de um erro real envolver comportamento de API/SDK/
provider (Ollama, OpenCode Go/opencode.ai, OpenAI, formato de resposta,
limites, mudança de comportamento) ou de documentação NVDA/addon, pesquisar
na web antes de assumir — **priorizar sempre fontes/práticas de 2026**
(o ano corrente), nunca confiar em memória de treino desatualizada pra
fato técnico específico de API externa. Mesmo padrão usado o dia inteiro
hoje (confirmação real de prompt caching do Ollama Cloud vs OpenCode Go,
por exemplo, veio de busca + teste ao vivo, não suposição).

## Bloqueios reais (os únicos motivos válidos pra parar e esperar o Felipe)

Autorização do Felipe é ampla pra esta janela de ~8h — só interromper e
esperar se acontecer algo desta lista, não por incerteza técnica comum
(essa é sempre pra resolver sozinho):

- Ação destrutiva irreversível necessária pra continuar (ex: precisar
  apagar dado real do usuário, forçar algo em produção fora do escopo de
  teste).
- Custo/limite de API genuinamente estourado sem alternativa (ex: crédito
  zerado em TODOS os providers disponíveis, não só um deles).
- Decisão de PRODUTO (não técnica) sem resposta óbvia — ex: "esse addon
  deveria fazer X ou Y" quando os dois são igualmente válidos e mudam o
  resultado visível pro usuário final. Decisão técnica de COMO implementar
  não entra aqui — essa é sempre minha, sozinho.
- Trocar o provider de qualquer sub-agente ALÉM do Critic pra OpenCode Go
  — Felipe foi explícito que o escopo é só o Critic ("somente o gpt vai
  fazer as capacidades que o ollama nao faz"). Ampliar esse escopo por
  conta própria não é uma decisão técnica de bug-fix, é uma escolha de
  arquitetura que fica de fora da autorização desta madrugada.

Fora esses casos: resolver sozinho, documentar a decisão tomada e por quê,
e seguir o loop.
