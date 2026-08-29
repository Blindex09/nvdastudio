# Maturidade de avaliacao do NVDAStudio -- estado em 2026-08-09

Doc de referencia, nao um plano de execucao. Registra (1) o inventario real
de testes por camada, mapeado no framework de maturidade de avaliacao de
agentes de IA (Anthropic, referencia da industria em 2026: component-level
-> trajectory-level -> environment/e2e-level), e (2) uma melhoria adiada por
falta de saldo de API, pra nao se perder.

## 1. Smoke test de conectividade real (IMPLEMENTADO em 2026-08-09)

`tests/e2e/test_smoke_conectividade_providers.py` -- confirmado ao vivo: um
teste por provider, gated na propria chave (5 pulados por falta de chave,
Ollama passou, OpenAI pegou um 429 real -- rate limit genuino da API, nao
bug do teste, confirma que o smoke test detecta problema de conectividade
de verdade). Esboco original abaixo, mantido como historico.

Ideia: um teste rapido e barato que chama cada provider REAL configurado
(Ollama, OpenAI, Gemini, Anthropic, xAI, OpenCode Go) com uma pergunta
trivial de ~1 token, so pra confirmar "a chave funciona, o endpoint
responde, o formato da resposta bate com o parser" -- sem rodar o pipeline
inteiro (que custa ~15-20min e gasta tokens de verdade por causa dos
sub-agentes + critic em 2 estagios).

Por que interessa: hoje a unica forma de descobrir que uma integracao de
provider quebrou (chave expirada, endpoint mudou, formato de resposta
mudou) e rodando um `test_e36` completo (caro) ou descobrindo em producao.
Um smoke test ficaria entre `tests/integration` (mockado, gratis, mas nao
prova que a API real responde) e `tests/e2e` (real, mas caro) -- cobertura
"component-level real" sem o custo de "environment-level real".

Esboco de implementacao futura (nao feito ainda):
- Novo arquivo `tests/e2e/test_smoke_conectividade_providers.py`.
- Um teste por provider, cada um gated no proprio `_API_KEY_ENV_VARS`
  (mesmo padrao de `skip_unless_ollama`), pra so rodar quando a chave
  daquele provider especifico estiver disponivel -- nao exige TODAS as
  chaves de uma vez.
- Chamada minima: `create_llm_client(model_id=..., provider=...).chat("Responda apenas: ok")`,
  assert que a resposta nao e vazia e nao levanta excecao.
- Custo estimado por execucao completa: poucos centavos (1 chamada curta
  por provider), rodavel em segundos, nao minutos.

Retomar quando houver saldo de API pra validar contra as APIs reais antes
de declarar pronto.

## 2. Inventario de testes por camada (2026-08-09)

| Camada | Local | Testes | Custo | O que prova |
|---|---|---|---|---|
| Unit (mockado) | `tests/unit/` | 2225 | gratis, segundos | Cada funcao/classe isolada se comporta certo |
| Integration (mockado) | `tests/integration/` | 147 | gratis, segundos | Orchestrator+Planner+Critic+dispatcher+sub-agentes se ENCAIXAM certo (a fiacao), com a resposta da IA fake |
| E2E mockado | `tests/e2e/test_e2{2,3,4,5,6,7,8,9},30}*.py` | 68 | gratis, segundos | Pipeline local completo (addon_builder, packaging, validacao estrutural) sem custo de API |
| E2E real, componente/agente | `tests/e2e/test_e2{0,1},3{1,2,3,4}*.py` | 82 | API real, mas alvo estreito (1 sub-agente ou 1 regra por vez) | Um sub-agente/regra especifico responde certo com IA de verdade |
| E2E real, pipeline completo ("environment") | `test_criacao_completa.py`, `test_3_addons_reais.py`, `test_full_pipeline.py`, `test_fluxo_completo_nvda.py`, `test_e35_golden_eval_set.py`, `test_e36_golden_eval_set_complexo.py` | 76 | API real, caro (varios minutos por caso complexo) | O addon INTEIRO fecha de ponta a ponta com IA de verdade |
| **Total** | | **2598** | | |

Mapeamento pro framework de maturidade (Anthropic, 2026):
- **Component-level** = Unit + Integration (mockado) + parte do E2E mockado -- 2440 testes.
- **Trajectory-level** = parcialmente coberto pelos testes de Integration que checam retry/escalacao/replan (ex: `TestOrchestratorCrossProviderRescue`), mas nao ha ainda um teste dedicado que audite o CAMINHO de decisao (quantos replans, por que motivo, se foi eficiente) como metrica propria -- e o que `scripts/eval_metrics.py` (2026-08-09) comecou a cobrir, lendo `total_retries`/`replan_count` do historico real.
- **Environment/E2E-level** = os 76 testes reais de pipeline completo, com destaque pro golden eval set (`test_e35`/`test_e36`) que promove bugs reais achados manualmente em casos de regressao permanentes.

## 3. "Estamos quase terminando?"

Nao no sentido de "falta pouco pra fechar" -- e no sentido certo: **o
sistema de avaliacao esta maduro o suficiente pra continuar melhorando
sozinho**, o que e o objetivo real desse tipo de projeto (nao existe
"pronto" definitivo pra um pipeline de geracao de codigo via IA, existe
"o loop de deteccao e correcao funciona"). Evidencia concreta desta mesma
sessao: `test_e36` real achou um deadlock genuino
(`manifest_builder` preso esperando `code_generation` que esgotou todas as
tentativas, inclusive escalacao cross-provider) e a correcao determinística
(`planner.py::_sanitize_manifest_dependencies()`, 2.24.0) foi validada de
volta no mesmo dia.

O que ainda falta pra "producao" no sentido formal (ver tambem pesquisa de
2026-08-09 sobre production-readiness): metrica continua de taxa de sucesso
do golden eval set ao longo do tempo (agora existe via `scripts/eval_metrics.py`,
mas ainda e rodado manualmente, nao agendado), e uma auditoria de seguranca
adversarial do codigo GERADO pelo addon (OWASP Agentic Skills Top 10) --
hoje o critic julga qualidade/conformidade ao spec, nao seguranca
adversarial.
