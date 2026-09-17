from dataclasses import dataclass

MODULE_VERSION = "1.1.0"


# dataclass, nao pydantic: pydantic_core e binario compilado por versao de
# Python/ABI e nao pode ser vendorizado em lib/ com seguranca; dentro do NVDA
# o import falhava e derrubava model_router junto. Os valores aqui sao
# literais do proprio modulo, nao entrada externa -- nao ha o que validar.
@dataclass(frozen=True)
class ModelPrice:
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

def get_model_price(provider: str, model_id: str) -> ModelPrice | None:
	"""None quando nao ha preco por token catalogado -- quem chama deve cair
	pro fallback de cost_tier (registry), nunca tratar como $0 silencioso."""
	return MODEL_PRICING.get(provider, {}).get(model_id)
