# Auditoria: prompt caching e structured output — Ollama Cloud vs OpenCode Go

Data: 2026-08-26. Testado ao vivo com as chaves reais da conta do Felipe
(Ollama Cloud e OpenCode Go), não com documentação ou suposição. Todos os
resultados abaixo vieram de chamadas reais às APIs, capturadas e verificadas
neste dia.

## Resumo executivo

- **Ollama Cloud não tem prompt caching, em nenhum modelo da conta.** Isso é
  uma limitação da API inteira (`https://ollama.com/api/chat`), não de um
  modelo específico.
- **Ollama Cloud não tem structured output confiável, em nenhum modelo da
  conta.** O parâmetro `format` (schema ou `"json"`) não tem efeito
  observável real hoje — testado com schema estrito nos 17 modelos da conta,
  nenhum seguiu corretamente, incluindo o Kimi k2.6 (que o código do
  NVDAStudio assumia, erroneamente, ter suporte nativo).
- **OpenCode Go tem as duas coisas, mas só em parte do catálogo.** Dos 31
  modelos testados, 13 respeitam `response_format` com `json_schema`
  estrito, e desses, 8 também confirmaram prompt caching real (tokens
  reaproveitados numa segunda chamada com o mesmo prefixo).
- Por causa disso, o NVDAStudio agora força toda chamada que precisa de JSON
  garantido a passar pelo OpenCode Go, numa cadeia de 4 modelos verificados,
  com fallback automático se um estiver fora do ar (ver seção final).

---

## 1. Ollama Cloud — por que não tem nenhuma das duas capacidades

### Prompt caching: ausente

Confirmado via documentação oficial e issues abertas no GitHub do projeto
Ollama, sem resposta até a data desta auditoria. A API `/api/chat` não expõe
nenhum campo de estatística de cache no `usage` da resposta, e chamadas
repetidas com o mesmo prefixo não mostram redução de custo/tempo
correspondente a reaproveitamento de contexto.

Isso não é por modelo — é a arquitetura do serviço. Ollama Cloud fatura por
assinatura/cota de uso (não por token), e não expõe a infraestrutura de KV
cache entre requisições que serviços pagos por token (OpenAI, Anthropic,
OpenCode Go) mantêm para cobrar menos em prefixos repetidos.

### Structured output: ausente, apesar do parâmetro `format` existir

O Ollama tem um parâmetro `format` que aceita `"json"` (JSON genérico) ou um
schema completo. Documentação oficial (`docs.ollama.com/capabilities/
structured-outputs`) descreve isso como suporte a *constrained decoding*.

**O teste ao vivo mostrou que isso não funciona na prática, hoje, na API
Cloud**, para nenhum dos 17 modelos da conta:

| Modelo | Resultado com `format=<schema estrito>` |
|---|---|
| kimi-k2.6 | ❌ ignorou o schema, inventou campos próprios, `plataforma` virou array em vez do enum pedido |
| kimi-k2.7-code | ❌ resposta embrulhada em texto/markdown |
| kimi-k3 | ❌ embrulhado em texto/markdown |
| glm-5.2, glm-5.1 | ❌ embrulhado em texto/markdown |
| deepseek-v4-flash | ❌ embrulhado em texto/markdown |
| deepseek-v4-pro | ❌ campo obrigatório ausente |
| qwen3.5:397b | ❌ campo obrigatório ausente |
| mistral-large-3:675b | ❌ embrulhado em texto/markdown |
| gpt-oss:20b, gpt-oss:120b | ❌ embrulhado em texto/markdown |
| minimax-m2.7, minimax-m3 | ❌ embrulhado em texto/markdown |
| gemma4:31b | ❌ embrulhado em texto/markdown |
| nemotron-3-super, nemotron-3-nano:30b, nemotron-3-ultra | ❌ violação de schema ou embrulhado |

**Teste de controle decisivo** (Kimi k2.6): comparar `format="json"` (modo
simples) contra **nenhum `format`** — os dois deram resultado idêntico,
byte a byte. Ou seja, o parâmetro `format` não tem efeito observável real
hoje via essa API, para nenhum modo, em nenhum modelo testado.

**Por quê**: a hipótese mais provável, dado que o mesmo nome de modelo
("kimi-k2.6") funciona corretamente via OpenCode Go, é que a infraestrutura
de *constrained decoding* (que precisa mascarar tokens inválidos durante a
geração para garantir aderência ao schema) não está ativada no serving da
Ollama Cloud para esses modelos — mesmo peso do modelo, deployment
diferente, capacidade diferente. Isso bate com o comentário que já existia
no código do NVDAStudio antes desta auditoria (`ollama_client.py`,
pesquisa de 2026-08-08): "Ollama Cloud NÃO suporta tool_choice forçado nem
structured output real."

### Consequência que isso já causava (corrigida nesta auditoria)

O NVDAStudio tinha `json_schema_native=True` hardcoded para kimi-k2.6 e
kimi-k2.7-code, o que **pulava a validação local de schema** (rede de
segurança que existe pros outros modelos). Ou seja: o único modelo Ollama
que rodava sem NENHUMA garantia — nem nativa (não existe) nem local (pulada
por engano). Corrigido para `False` em `ollama_client.py` 2.25.0.

---

## 2. OpenCode Go — o que funciona de verdade

Testados os 31 modelos da conta (`GET /v1/models`), com `response_format`
tipo `json_schema` estrito na chamada `/v1/chat/completions`.

### Structured output confirmado (schema seguido corretamente)

kimi-k3, kimi-k2.7-code, kimi-k2.6, longcat-2.0, glm-5.2, glm-5.1, glm-5,
deepseek-v4-flash, qwen3.7-max, qwen3.8-max, qwen3.7-plus, mimo-v2.5, hy3
— **13 de 31**.

### Prompt caching confirmado (2ª chamada com mesmo prefixo reaproveitou tokens)

Testado nos 13 acima, usando um prefixo de sistema longo (~2800 chars)
repetido em 2 chamadas sequenciais, checando `cached_tokens` no `usage` da
resposta:

| Modelo | Structured output | Prompt caching |
|---|---|---|
| **kimi-k2.6** | ✅ | ✅ 1024/1164 tokens cacheados (88%) |
| **kimi-k3** | ✅ | ✅ 1024/1249 (82%) |
| **glm-5.2** | ✅ | ✅ 1041/1045 (99,6%) |
| **glm-5.1** | ✅ | ✅ 1044/1045 — já cacheou na 1ª chamada |
| **glm-5** | ✅ | ✅ 1044/1045 — já cacheou na 1ª chamada |
| **deepseek-v4-flash** | ✅ | ✅ 1024/1176 (87%) |
| **qwen3.8-max** | ✅ | ✅ 1024/1054 (97%) |
| **mimo-v2.5** | ✅ | ✅ 1024/1073 (95%) |
| kimi-k2.7-code | ✅ | ❌ nenhum sinal de cache |
| longcat-2.0 | ✅ | ❌ `cached_tokens=0` nas 2 chamadas |
| qwen3.7-max | ✅ | ❌ `cached_tokens=0` |
| qwen3.7-plus | ✅ | ❌ `cached_tokens=0` |
| hy3 | ✅ | ❌ `cached_tokens=0` |

**8 modelos confirmados com as duas capacidades ao mesmo tempo.**

### Modelos que falharam no schema (não testados pra caching)

minimax-m3, minimax-m2.7, minimax-m2.5, kimi-k2.5, glm-5.3, ox-alpha-free,
deepseek-v4-pro, deepseek-v4-flash-vision-exp, qwen3.6-plus, qwen3.5-plus,
mimo-v2-pro, mimo-v2-omni, mimo-v2.5-pro, hy3-preview, muse-spark — maioria
com erro HTTP (400/500), não é questão de formato do teste.

### Correção: `gpt-5.6-luna` nunca esteve fora do ar — era o endpoint errado

**Atualização, mesma data**: o teste inicial via `/v1/chat/completions`
retornava 500 para `gpt-5.6-luna`, interpretado a princípio como o modelo
fora do ar. Comparação com `C:\agentic` (outro projeto do Felipe, mesmo
gateway OpenCode Go, provider já implementado lá) revelou a causa real:
**`gpt-5.6-luna` é o único modelo OpenAI-family do catálogo do OpenCode Go
e exige a Responses API (`/v1/responses`), nunca Chat Completions**
(`/v1/chat/completions`, usada por todo o resto do catálogo — Kimi, GLM,
DeepSeek, Qwen etc.).

Testado de novo via `/v1/responses`: **200 limpo, `json_schema` estrito
seguido à risca, E prompt caching real** (confirmado via
`previous_response_id` encadeado — `cached_tokens=2212/2215`, 99,9%). É o
modelo com o melhor resultado de todos os testados nesta auditoria.

`grok-4.5` (o fallback original do Critic) segue genuinamente indisponível
(503 "Endpoint is unavailable"), e `grok-4.6` (mais novo, também no
catálogo) não é compatível com nenhum dos dois endpoints OpenAI-compatíveis
(`401: Model grok-4.6 is not supported for format oa-compat`).

O NVDAStudio agora implementa os dois endpoints (`ai/opencode_go_client.py`
1.2.0: roteamento automático por modelo — `gpt-5.6-luna` vai para
`/responses`, todo o resto continua em `/chat/completions`), e
`gpt-5.6-luna` voltou a ser o primeiro da cadeia de fallback (era o
modelo original escolhido para o Critic desde 3.19.0).

---

## 3. O que o NVDAStudio faz agora

Cadeia verificada, em ordem de preferência (`ai/model_registry.py::
STRUCTURED_OUTPUT_MODEL_CHAIN`):

```
gpt-5.6-luna → kimi-k2.6 → glm-5.1 → deepseek-v4-flash → qwen3.8-max
```

Toda chamada do projeto que exige JSON garantido (`response_format` tipo
`json_schema`) passa por essa cadeia via OpenCode Go, nunca mais pelo
provider ativo do usuário (que pode ser Ollama, sem nenhuma garantia). Se um
modelo da cadeia estiver fora do ar, o próximo é tentado automaticamente
(`ai/llm_factory.py::call_with_structured_output`) — pedido explícito do
Felipe: "nunca pode ficar sem prompt caching nem sem structured output".

Pontos do projeto que usam essa cadeia:

- `ai/critic.py` — avaliação de todo step do pipeline (já usava OpenCode Go
  desde 3.19.0; só os modelos específicos foram trocados pros verificados)
- `ai/clarifier.py` — classificação de intent/arquitetura do pedido
- `core/planner.py` — geração do plano inteiro (steps, complexidade, DAG)
- `core/agentic_loop.py` — árbitro do `ensemble_verify`
- `gui/studio_dialog.py` — decisão semântica do chat (reply/clarify/run_pipeline)
- `memory/memory_manager.py` — resumo semântico de sessão

Isso não muda o provider usado para gerar código/documentação/testes do
addon em si (`code_generation`, `web_research`, etc.) — esses continuam
seguindo o provider que o usuário escolheu nas configurações, sem exigir
JSON garantido.
