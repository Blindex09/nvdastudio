from nvdastudio.ai.ollama_client import OllamaClient, _MODEL_CAPABILITIES


class TestModelCapabilitiesGlmQwen:
	def test_glm_5_1_tem_entrada_propria_sem_json_schema_native(self):
		assert "glm-5.1" in _MODEL_CAPABILITIES
		assert _MODEL_CAPABILITIES["glm-5.1"]["json_schema_native"] is False
		assert _MODEL_CAPABILITIES["glm-5.1"]["json_object_only"] is True

	def test_qwen3_5_tem_entrada_propria(self):
		# 2.22.0: chave real e "qwen3.5:397b" (model_registry.py
		# _PROVIDER_TIER_MODELS["ollama"]["frontier"]) -- "qwen3.5" sem o
		# tag nunca batia contra o model_id de verdade usado em producao.
		assert "qwen3.5:397b" in _MODEL_CAPABILITIES

	def test_client_com_glm_nao_herda_capacidades_do_kimi(self, monkeypatch):
		monkeypatch.setattr("nvdastudio.ai.ollama_client._HTTPX_AVAILABLE", True)
		client = OllamaClient(api_key="k", model_id="glm-5.1")
		assert client._caps["json_schema_native"] is False

	def test_client_com_qwen3_5_397b_nao_herda_capacidades_do_kimi(self, monkeypatch):
		"""Achado real (auditoria de integracao 2026-08-09): o tier
		'frontier' inteiro herdava silenciosamente json_schema_native=True
		do Kimi porque a chave nao batia com o model_id real."""
		monkeypatch.setattr("nvdastudio.ai.ollama_client._HTTPX_AVAILABLE", True)
		client = OllamaClient(api_key="k", model_id="qwen3.5:397b")
		assert client._caps["json_schema_native"] is False

	def test_todos_os_modelos_do_catalogo_real_tem_entrada_propria(self):
		"""9 modelos confirmados no catalogo real da conta (model_registry.py
		1.15.0, GET https://ollama.com/api/tags) nunca tinham entrada aqui --
		cada um herdava as flags do Kimi por coincidencia do fallback."""
		esperados = [
			"glm-5.2", "minimax-m3", "gpt-oss:120b", "minimax-m2.7",
			"deepseek-v4-pro", "nemotron-3-ultra", "nemotron-3-super",
			"nemotron-3-nano:30b", "mistral-large-3:675b", "gemma4:31b",
		]
		for model_id in esperados:
			assert model_id in _MODEL_CAPABILITIES, f"{model_id} sem entrada propria"
