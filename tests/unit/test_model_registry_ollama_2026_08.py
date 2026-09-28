from nvdastudio.ai.model_registry import (
	ModelStatus,
	_MODEL_REGISTRY,
)


class TestNovosModelosOllamaRegistrados:
	def test_glm_5_2_esta_no_registry_ativo(self):
		info = _MODEL_REGISTRY["glm-5.2"]
		assert info.status == ModelStatus.ACTIVE
		assert info.provider == "zhipu"
		assert info.context_window > 0

	def test_minimax_m3_esta_no_registry_ativo(self):
		info = _MODEL_REGISTRY["minimax-m3"]
		assert info.status == ModelStatus.ACTIVE
		assert info.provider == "minimax"
		assert info.context_window > 0

	def test_gpt_oss_20b_esta_no_registry_ativo(self):
		info = _MODEL_REGISTRY["gpt-oss:20b"]
		assert info.status == ModelStatus.ACTIVE
		assert info.provider == "openai_oss"
		assert info.context_window > 0

	def test_kimi_k3_nao_foi_adicionado(self):
		"""kimi-k3 aparece no catalogo /api/tags mas retorna HTTP 402
		(extra usage only, saldo vazio) -- mesmo padrao ja excluido antes
		pra kimi3/claude-fable-5. Nao deve ser adicionado ao registry."""
		assert "kimi-k3" not in _MODEL_REGISTRY


class TestModelosRetiradosPeloOllama:
	"""Achado ao vivo 2026-09-28 (curl contra ollama.com/api/chat): tres
	modelos catalogados foram retirados pelo Ollama em 2026-09-25 e devolvem
	410 Gone. Ficam no registry como historico (RETIRED), mas fora do pool
	que get_active_models()/route_advisor.py consideram."""

	def test_deepseek_v4_flash_esta_retirado(self):
		assert _MODEL_REGISTRY["deepseek-v4-flash"].status == ModelStatus.RETIRED

	def test_qwen3_5_397b_esta_retirado(self):
		assert _MODEL_REGISTRY["qwen3.5:397b"].status == ModelStatus.RETIRED

	def test_glm_5_1_esta_retirado(self):
		assert _MODEL_REGISTRY["glm-5.1"].status == ModelStatus.RETIRED

	def test_tier_light_e_frontier_do_ollama_nao_apontam_pra_modelo_retirado(self):
		from nvdastudio.ai.model_registry import _PROVIDER_TIER_MODELS
		tiers = _PROVIDER_TIER_MODELS["ollama"]
		assert _MODEL_REGISTRY[tiers["light"]].status == ModelStatus.ACTIVE
		assert _MODEL_REGISTRY[tiers["frontier"]].status == ModelStatus.ACTIVE

	def test_versao_1_24_0(self):
		from nvdastudio.ai.model_registry import MODULE_VERSION
		assert MODULE_VERSION == "1.24.0"
