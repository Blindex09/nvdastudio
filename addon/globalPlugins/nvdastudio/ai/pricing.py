MODULE_VERSION = "1.0.0"

# USD por 1M tokens, blendado (input+output)/2. 0.0 = plano de assinatura
# fixa (custo marginal por chamada e efetivamente zero -- OpenCode Go,
# Ollama Cloud) ou desconhecido (fica de fora do calculo, nao gera custo
# fantasma).
_PRICE_PER_1M_TOKENS_USD: dict[str, float] = {
    # --- Claude / Anthropic (platform.claude.com/docs, pesquisa 2026-08-09) ---
    "claude-opus-5": 15.0,       # $5 input / $25 output -> blend 15
    "claude-opus-4-8": 15.0,
    "claude-sonnet-5": 9.0,      # $3 input / $15 output -> blend 9
    "claude-haiku-4-5": 2.0,     # $0.80 input / $4 output -> blend ~2.4, arredondado

    # --- OpenAI (platform.openai.com/pricing, familia gpt-5.6) ---
    "gpt-5.6-sol": 10.0,
    "gpt-5.6-terra": 4.0,
    "gpt-5.6-luna": 0.6,

    # --- Google / Gemini (ai.google.dev/pricing) ---
    "gemini-2.5-pro": 7.0,
    "gemini-3.6-flash": 0.5,
    "gemini-3.5-flash": 0.5,
    "gemini-3.5-flash-lite": 0.2,
    "gemini-3.1-flash-lite": 0.2,

    # --- Ollama Cloud (ollama.com/pricing, plano de assinatura por credito) ---
    # Modelos servidos via Ollama Cloud tem preco por credito do PLANO, nao da
    # API nativa do fabricante -- aproximado aqui pelo custo relativo do plano.
    "kimi-k2.7-code": 1.5,
    "kimi-k2.6": 1.2,
    "deepseek-v4-flash": 0.3,
    "glm-5.2": 1.8,
    "minimax-m3": 1.0,
    "gpt-oss:20b": 0.3,

    # --- xAI (docs.x.ai/developers/models) ---
    "grok-build-0.1": 3.0,
    "grok-4.5": 2.0,
    "grok-4.3": 1.9,  # $1.25/$2.50 por 1M abaixo de 200k prompt -> blend ~1.9

    # --- OpenCode Go (plano de assinatura fixa mensal, opencode.ai) ---
    # Custo marginal por chamada e $0 -- ja pago no plano fixo.
    "gpt-5.6-luna@opencode_go": 0.0,
}

# Taxa de cambio USD -> BRL, constante manual (nao ha API de FX no projeto e
# adicionar uma so pra isso seria over-engineering pra visibilidade interna
# de custo). Felipe pode ajustar aqui quando o cambio mudar muito.
USD_TO_BRL_RATE: float = 5.4


def get_price_per_1m_tokens_usd(model_id: str, provider: str = "") -> float:
    """
    Retorna o preco USD por 1M tokens (blendado input/output) do modelo.
    0.0 quando o modelo nao esta na tabela (plano de assinatura fixa ou
    preco ainda nao auditado) -- nao inventa numero.

    provider="opencode_go" usa a chave namespaced "@opencode_go" quando
    existir (evita colisao com o mesmo model_id noutro provider -- mesmo
    padrao de namespacing ja usado em model_registry.py 1.11.0).
    """
    if provider == "opencode_go":
        namespaced = f"{model_id}@opencode_go"
        if namespaced in _PRICE_PER_1M_TOKENS_USD:
            return _PRICE_PER_1M_TOKENS_USD[namespaced]
    return _PRICE_PER_1M_TOKENS_USD.get(model_id, 0.0)


def estimate_cost_usd(model_id: str, tokens: int, provider: str = "") -> float:
    """Estima custo em USD para uma quantidade de tokens de um modelo."""
    price = get_price_per_1m_tokens_usd(model_id, provider)
    if price <= 0.0 or tokens <= 0:
        return 0.0
    return round((tokens / 1_000_000) * price, 6)
