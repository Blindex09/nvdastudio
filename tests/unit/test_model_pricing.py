from nvdastudio.ai.model_pricing import (
	MODULE_VERSION, ModelPrice, MODEL_PRICING, get_model_price,
)


class TestModulo:
	def test_versao(self):
		assert MODULE_VERSION == "1.1.0"


class TestGetModelPrice:
	def test_modelo_catalogado_retorna_preco(self):
		price = get_model_price("openai", "gpt-5.6-sol")
		assert isinstance(price, ModelPrice)
		assert price.input_per_million > 0
		assert price.output_per_million > 0
		assert price.source_url.startswith("https://")

	def test_modelo_nao_catalogado_retorna_none(self):
		assert get_model_price("openai", "modelo-inexistente-xyz") is None

	def test_provider_nao_catalogado_retorna_none(self):
		assert get_model_price("provider-inexistente", "qualquer") is None

	def test_ollama_nao_tem_preco_catalogado(self):
		"""Ollama Cloud e assinatura, nao $/token."""
		assert get_model_price("ollama", "qwen3.5:397b") is None
		assert get_model_price("ollama", "kimi-k2.7-code") is None


class TestSemModeloComPrecoSemFonteDocumentada:
	def test_todo_preco_catalogado_tem_source_url(self):
		for provider, models in MODEL_PRICING.items():
			for model_id, price in models.items():
				assert price.source_url.startswith("https://"), (
					f"{provider}/{model_id} sem source_url valida"
				)
