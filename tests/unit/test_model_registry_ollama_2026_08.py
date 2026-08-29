from nvdastudio.ai.model_registry import (
	ModelRegistry,
	ModelStatus,
	_FALLBACK_CHAINS,
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


class TestFallbackChainOllamaInclueNovosModelos:
	def test_fallback_chain_ollama_inclui_glm_5_2_e_minimax_m3_e_gpt_oss(self):
		chain = _FALLBACK_CHAINS["ollama"]
		assert "glm-5.2" in chain
		assert "minimax-m3" in chain
		assert "gpt-oss:20b" in chain

	def test_kimi_k2_7_code_continua_primeiro_na_cadeia(self):
		"""Tier heavy default nao foi trocado nesta rodada -- so adicionado
		ao catalogo de fallback, decisao de trocar o default fica pro
		usuario (ver changelog 1.10.0)."""
		assert _FALLBACK_CHAINS["ollama"][0] == "kimi-k2.7-code"


class TestGetFallbackChainFoldDeProviderNovo:
	"""get_fallback_chain() dobra o provider do modelo pro grupo 'ollama'
	antes de consultar _FALLBACK_CHAINS -- sem isso, provider='zhipu'/
	'minimax'/'openai_oss' nao bateria com nenhuma chave de
	_FALLBACK_CHAINS (que so tem 'ollama'/'anthropic'/'openai'/'google'/
	'xai'), retornando lista vazia silenciosamente."""

	def test_glm_5_2_tem_fallback_chain_nao_vazia(self):
		registry = ModelRegistry()
		chain = registry.get_fallback_chain("glm-5.2")
		assert len(chain) > 1, "glm-5.2 deveria ter fallback chain do grupo ollama, nao vazia"
		assert chain[0] == "glm-5.2"

	def test_minimax_m3_tem_fallback_chain_nao_vazia(self):
		registry = ModelRegistry()
		chain = registry.get_fallback_chain("minimax-m3")
		assert len(chain) > 1, "minimax-m3 deveria ter fallback chain do grupo ollama, nao vazia"

	def test_gpt_oss_20b_tem_fallback_chain_nao_vazia(self):
		registry = ModelRegistry()
		chain = registry.get_fallback_chain("gpt-oss:20b")
		assert len(chain) > 1, "gpt-oss:20b deveria ter fallback chain do grupo ollama, nao vazia"

	def test_glm_5_2_fallback_chain_contem_kimi_k2_7_code(self):
		"""A cadeia de fallback de qualquer modelo do grupo ollama deve
		incluir os outros modelos do mesmo grupo (escalacao cruzada real)."""
		registry = ModelRegistry()
		chain = registry.get_fallback_chain("glm-5.2")
		assert "kimi-k2.7-code" in chain

	def test_versao_1_10_0(self):
		from nvdastudio.ai.model_registry import MODULE_VERSION
		assert MODULE_VERSION == "1.18.0"
