# Melhorias portadas de C:\agentic — 2026-08-26

Comparação pedida pelo Felipe entre o roteamento de modelo do NVDAStudio e o
de `C:\agentic` (plataforma de agente de propósito geral, mesmo autor). O
roteamento de lá é mais maduro nessa parte específica — 3 melhorias
concretas foram portadas.

## 1. Retry/backoff/detecção de loop compartilhado

**Antes**: `ollama_client.py`, `opencode_go_client.py` e `provider_client.py`
tinham 3 implementações quase idênticas de `_MAX_RETRIES`/backoff — a mesma
classe de duplicação já corrigida em `orchestrator.py`/`agentic_loop.py`
(classificador e recovery duplicados, mesma sessão).

**Agora**: `ai/reliability.py` (novo módulo, porta síncrona de
`C:\agentic\features\reliability\reliability.py`) — fonte única com:
- `RETRYABLE_STATUS` compartilhado (408, 409, 425, 429, 500, 502, 503, 504,
  529 — 529 é "overloaded_error" da Anthropic).
- `retry_delay()`: extrai tempo de espera real do texto do erro (achado
  real 2026-08-04, Gemini free-tier embute "Please retry in 24.8s." na
  mensagem) OU do header HTTP `Retry-After` padrão (delta-segundos e
  HTTP-date, RFC 7231 — lógica que já existia em `ollama_client.py`,
  preservada integralmente ao migrar).
- `call_with_retry()`: além do retry, detecta **loop** — a mesma falha se
  repetindo 3x seguidas desiste cedo em vez de insistir (`LoopDetectedError`).

Os 3 clientes (`ollama_client.py` 2.26.0, `opencode_go_client.py` 1.3.0,
`provider_client.py` 2.15.0) agora chamam `reliability.call_with_retry()` —
zero lógica de retry própria restante em nenhum dos 3.

## 2. Filtro por capacidade real do modelo

**Antes**: quando uma chamada precisava de uma capacidade específica
(structured output, por exemplo), a única solução era um chain hardcoded
de modelos verificados manualmente (`STRUCTURED_OUTPUT_MODEL_CHAIN`) — não
generaliza pra outras capacidades.

**Agora**: `model_router.py::select_model()` aceita
`required_capabilities: frozenset[str]` (padrão de
`C:\agentic\features\providers\providers_auto.py::_ordered_models()`).
Filtra candidatos por `ModelInfo.capabilities` (fatos reais por modelo, já
existentes em `model_registry.py`) **antes** de pontuar. Sem candidato
elegível: cai pro comportamento anterior (pontua sem filtro, loga aviso) —
nunca crasha.

**Achado real durante a implementação**: 4 modelos servidos via Ollama
Cloud (`kimi-k2.7-code`, `kimi-k2.6`, `gpt-oss:120b`, `gpt-oss:20b`)
estavam marcados com `"json_schema"` na lista de capacidades — contradiz
diretamente o teste ao vivo desta mesma sessão (nenhum modelo Ollama honra
`json_schema` estrito de verdade). Corrigido antes de construir o filtro
em cima — senão o filtro automatizaria o erro.

## 3. Confiabilidade com shrinkage bayesiano

**Antes**: corte binário — menos de 5 tentativas observadas usa 100% o
prior neutro (0.75); a partir de 5, usa 100% a taxa de sucesso real. A
tentativa #5 pesava 0→100% de repente — uma falha isolada por infra (503,
timeout) bem na 5ª tentativa derrubava o modelo inteiro do ranking.

**Agora**: `model_router.py::_reliability_score()` usa curva suave (mesma
constante K=20 de `C:\agentic`):

```
confidence = tentativas / (tentativas + 20)
score = (1 - confidence) * prior_neutro + confidence * taxa_observada
```

Com 1 tentativa, confiança ~4,8% (quase todo prior ainda). Com 20
tentativas, confiança exatamente 50%. Com volume grande, aproxima da taxa
observada mas **nunca chega a 100%** — o prior nunca é totalmente
descartado, mesmo com milhões de tentativas.

## Testes novos

- `tests/unit/test_ai_reliability.py` (14 testes) — módulo compartilhado.
- `tests/unit/test_ollama_client_retry_after.py` (retargeted, 9 testes) —
  parser de `Retry-After` (delta-segundos + HTTP-date).
- `tests/unit/test_llm_factory_structured_output_fallback.py` (4 testes,
  já existia da sessão anterior) — cadeia de fallback de structured output.
- `tests/unit/test_model_router_capability_filter.py` (4 testes) — filtro
  por capacidade, incluindo o trava de regressão do achado do json_schema.
- `tests/unit/test_model_router_reliability_shrinkage.py` (6 testes) —
  curva de confiança bayesiana.

## O que não foi portado (deliberado)

O classificador de complexidade de `C:\agentic` é **por LLM** (uma chamada
barata de classificação). O NVDAStudio mantém roteamento 100%
determinístico — regra explícita do próprio projeto (`CLAUDE.md`:
"roteamento é determinístico, conteúdo é decidido pela IA"). Não é uma
lacuna, é uma escolha de arquitetura consciente que diverge da de
`C:\agentic` por design.
