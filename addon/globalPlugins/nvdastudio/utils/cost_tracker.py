# Preco por 1M tokens (USD). Fontes oficiais Maio 2026.
# Kimi: plataforma moonshot.cn, precos em CNY convertidos a ~0.14 USD/CNY.
# DeepSeek V4 Flash: deepseek.com, estimativas conservadoras (flash tier).
_PRICING_PER_1M: dict[str, dict[str, float]] = {
	"kimi-k2.6": {
		"input_cache_hit":  0.154,   # ¥1.10
		"input_cache_miss": 0.91,    # ¥6.50
		"output":           3.78,    # ¥27.00
	},
	"deepseek-v4-flash": {
		"input_cache_hit":  0.02,   # flash tier — cache barato
		"input_cache_miss": 0.14,   # estimativa conservadora
		"output":           0.55,   # flash tier — saida barata
	},
}


def estimate_cost(
	model_id: str,
	input_tokens: int,
	output_tokens: int,
	cache_hit_ratio: float = 0.0,
) -> float:
	"""
	Estima o custo em USD de uma chamada de LLM.

	cache_hit_ratio: proporcao de input tokens que sao cache hits (0.0 a 1.0).
	Kimi/GLM atingem ~0.3-0.5 em multi-turn.
	"""
	pricing = _PRICING_PER_1M.get(model_id, _PRICING_PER_1M["kimi-k2.6"])
	cache_tokens = int(input_tokens * cache_hit_ratio)
	miss_tokens = input_tokens - cache_tokens
	cost = (
		(cache_tokens / 1_000_000) * pricing["input_cache_hit"]
		+ (miss_tokens / 1_000_000) * pricing["input_cache_miss"]
		+ (output_tokens / 1_000_000) * pricing["output"]
	)
	return cost


def estimate_pipeline_cost(tokens_by_model: dict[str, tuple[int, int]]) -> float:
	"""
	Estima custo total do pipeline dado dicionario:
	{model_id: (input_tokens, output_tokens)}.
	"""
	total = 0.0
	for model_id, (inp, out) in tokens_by_model.items():
		cache_ratio = 0.2  # estimativa conservadora para pipeline
		total += estimate_cost(model_id, inp, out, cache_ratio)
	return total


def get_model_cost_per_token(model_id: str) -> dict[str, float]:
	"""Retorna precos por 1M tokens para o modelo."""
	return dict(_PRICING_PER_1M.get(model_id, _PRICING_PER_1M["kimi-k2.6"]))


def is_discounted(model_id: str) -> bool:
	"""Retorna True se o modelo esta com desconto ativo."""
	return False


def format_cost(amount_usd: float) -> str:
	"""Formata custo em USD para exibicao."""
	if amount_usd < 0.01:
		return f"${amount_usd:.4f}"
	if amount_usd < 1.0:
		return f"${amount_usd:.3f}"
	return f"${amount_usd:.2f}"
