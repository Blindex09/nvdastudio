from pydantic import BaseModel

MODULE_VERSION = "1.0.1"


class ModelPrice(BaseModel):
	input_per_million: float
	output_per_million: float
	source_url: str


_OPENAI_SOURCE = "https://openai.com/api/pricing/"
_ANTHROPIC_SOURCE = "https://platform.claude.com/docs/en/pricing"
_GEMINI_SOURCE = "https://ai.google.dev/gemini-api/docs/pricing"
_XAI_SOURCE = "https://docs.x.ai/developers/pricing"

# Precos "standard" (pos-introdutorio quando aplicavel) -- mesma convencao de
# C:\agentic: guardar a tarifa que vale na maior parte do tempo de vida do
# modelo, nao a promocao temporaria de lancamento.
MODEL_PRICING: dict[str, dict[str, ModelPrice]] = {
	"openai": {
		"gpt-5.6-sol": ModelPrice(input_per_million=5.00, output_per_million=30.00, source_url=_OPENAI_SOURCE),
		"gpt-5.6-terra": ModelPrice(input_per_million=2.50, output_per_million=15.00, source_url=_OPENAI_SOURCE),
		# Corte de preco oficial em 2026-07-30 (anunciado pela propria OpenAI):
		# Luna caiu de $1.00/$6.00 (lancamento) pra $0.20/$1.20 -- confirmado
		# via busca dedicada 2026-08-17 contra o anuncio oficial da OpenAI.
		"gpt-5.6-luna": ModelPrice(input_per_million=0.20, output_per_million=1.20, source_url=_OPENAI_SOURCE),
	},
	"anthropic": {
		"claude-opus-5": ModelPrice(input_per_million=5.00, output_per_million=25.00, source_url=_ANTHROPIC_SOURCE),
		# Preco introdutorio de $2.00/$10.00 vale ate 2026-08-31; esta tabela
		# guarda a tarifa padrao pos-introducao que assume depois (mesma
		# convencao documentada em C:\agentic pro mesmo modelo).
		"claude-sonnet-5": ModelPrice(input_per_million=3.00, output_per_million=15.00, source_url=_ANTHROPIC_SOURCE),
		"claude-haiku-4-5": ModelPrice(input_per_million=1.00, output_per_million=5.00, source_url=_ANTHROPIC_SOURCE),
	},
	"gemini": {
		# Tier <=200K contexto; >200K e 2.50/15.00 (nao modelado aqui -- o
		# NVDAStudio nao rastreia tamanho de contexto por chamada).
		"gemini-2.5-pro": ModelPrice(input_per_million=1.25, output_per_million=10.00, source_url=_GEMINI_SOURCE),
		"gemini-3.6-flash": ModelPrice(input_per_million=1.50, output_per_million=7.50, source_url=_GEMINI_SOURCE),
	},
	# Mesma entrada duplicada sob "google" -- model_registry.py usa os dois
	# nomes de provider pro mesmo catalogo (achado ja documentado la).
	"google": {
		"gemini-2.5-pro": ModelPrice(input_per_million=1.25, output_per_million=10.00, source_url=_GEMINI_SOURCE),
		"gemini-3.6-flash": ModelPrice(input_per_million=1.50, output_per_million=7.50, source_url=_GEMINI_SOURCE),
	},
	"xai": {
		"grok-build-0.1": ModelPrice(input_per_million=1.00, output_per_million=2.00, source_url=_XAI_SOURCE),
		# Tier <200K contexto; >=200K e 4.00/12.00 (nao modelado aqui, mesma
		# razao do gemini acima).
		"grok-4.5": ModelPrice(input_per_million=2.00, output_per_million=6.00, source_url=_XAI_SOURCE),
	},
}

# Todo (provider, model_id) em _DOCUMENTED_STRENGTHS (model_router.py) sem
# entrada em MODEL_PRICING precisa estar registrado aqui com um motivo --
# nunca deixar um modelo silenciosamente com custo implicito $0 sem razao.
PRICING_GAPS: dict[str, dict[str, str]] = {
	"xai": {
		"grok-4.3": (
			"Preco por token nao encontrado em pesquisa dedicada (2026-08-17). "
			"Conferir docs.x.ai antes de usar preco real -- cai no fallback por cost_tier."
		),
	},
	# Ollama Cloud cobra por assinatura/cota de GPU-time, nao $/token -- mesma
	# razao ja documentada no governance comment de model_registry.py
	# (_OLLAMA_SERVED_MAKERS). Custo marginal por chamada tratado como ~$0
	# nas comparacoes (assinatura ja paga, nao aumenta com uso dentro da cota).
	"ollama": {
		"kimi-k2.7-code": "Ollama Cloud cobra por assinatura/cota de uso, sem preco por token publicado.",
		"kimi-k2.6": "Ollama Cloud cobra por assinatura/cota de uso, sem preco por token publicado.",
		"deepseek-v4-flash": "Ollama Cloud cobra por assinatura/cota de uso, sem preco por token publicado.",
		"deepseek-v4-pro": "Ollama Cloud cobra por assinatura/cota de uso, sem preco por token publicado.",
		"glm-5.2": "Ollama Cloud cobra por assinatura/cota de uso, sem preco por token publicado.",
		"glm-5.1": "Ollama Cloud cobra por assinatura/cota de uso, sem preco por token publicado.",
		"minimax-m3": "Ollama Cloud cobra por assinatura/cota de uso, sem preco por token publicado.",
		"minimax-m2.7": "Ollama Cloud cobra por assinatura/cota de uso, sem preco por token publicado.",
		"gpt-oss:120b": "Ollama Cloud cobra por assinatura/cota de uso, sem preco por token publicado.",
		"gpt-oss:20b": "Ollama Cloud cobra por assinatura/cota de uso, sem preco por token publicado.",
		"qwen3.5:397b": "Ollama Cloud cobra por assinatura/cota de uso, sem preco por token publicado.",
		"nemotron-3-ultra": "Ollama Cloud cobra por assinatura/cota de uso, sem preco por token publicado.",
		"nemotron-3-super": "Ollama Cloud cobra por assinatura/cota de uso, sem preco por token publicado.",
		"nemotron-3-nano:30b": "Ollama Cloud cobra por assinatura/cota de uso, sem preco por token publicado.",
		"mistral-large-3:675b": "Ollama Cloud cobra por assinatura/cota de uso, sem preco por token publicado.",
		"gemma4:31b": "Ollama Cloud cobra por assinatura/cota de uso, sem preco por token publicado.",
	},
	"opencode_go": {
		"gpt-5.6-luna": "OpenCode Go e cobrado por assinatura/cota fixa (ja paga); endpoint backend-only, sem preco tokenizado proprio nesse contexto.",
	},
}


def get_model_price(provider: str, model_id: str) -> ModelPrice | None:
	"""None quando nao ha preco por token catalogado -- quem chama deve cair
	pro fallback de cost_tier (registry), nunca tratar como $0 silencioso."""
	return MODEL_PRICING.get(provider, {}).get(model_id)


def get_pricing_gap_reason(provider: str, model_id: str) -> str | None:
	return PRICING_GAPS.get(provider, {}).get(model_id)


# Providers cujo modelo de cobranca e assinatura/cota, nao $/token real -- o
# custo marginal por chamada individual e tratado como ~$0 nas comparacoes
# (ja pago, nao aumenta com uso dentro da cota). Mesma logica de
# C:\agentic (_SUBSCRIPTION_BASED_PROVIDERS em model_router.py de la).
_SUBSCRIPTION_BASED_PROVIDERS = {"ollama", "opencode_go"}


def estimate_call_cost(
	provider: str, model_id: str, input_tokens: int, expected_output_tokens: int,
) -> float | None:
	"""
	Custo estimado (USD) de UMA chamada, dado o tamanho esperado de entrada/
	saida. None quando nao ha preco publicado E o provider nao e assinatura
	(caso em que 0.0 e o valor real, nao um placeholder).
	"""
	price = get_model_price(provider, model_id)
	if price:
		return (
			input_tokens * price.input_per_million
			+ expected_output_tokens * price.output_per_million
		) / 1_000_000
	if provider in _SUBSCRIPTION_BASED_PROVIDERS:
		return 0.0
	return None
