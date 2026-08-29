from nvdastudio.ai.model_pricing import (
	MODULE_VERSION, ModelPrice, MODEL_PRICING, PRICING_GAPS,
	get_model_price, get_pricing_gap_reason, estimate_call_cost,
)


class TestModulo:
	def test_versao(self):
		assert MODULE_VERSION == "1.0.1"


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
		"""Ollama Cloud e assinatura, nao $/token -- nunca deve aparecer em
		MODEL_PRICING (so em PRICING_GAPS com o motivo)."""
		assert get_model_price("ollama", "qwen3.5:397b") is None
		assert get_model_price("ollama", "kimi-k2.7-code") is None


class TestGetPricingGapReason:
	def test_grok43_tem_motivo_documentado(self):
		reason = get_pricing_gap_reason("xai", "grok-4.3")
		assert reason is not None
		assert len(reason) > 10

	def test_ollama_modelos_tem_motivo_assinatura(self):
		for model_id in ("qwen3.5:397b", "kimi-k2.7-code", "gpt-oss:20b"):
			reason = get_pricing_gap_reason("ollama", model_id)
			assert reason is not None, f"{model_id} sem motivo em PRICING_GAPS"
			assert "assinatura" in reason.lower() or "cota" in reason.lower()

	def test_modelo_sem_gap_documentado_retorna_none(self):
		assert get_pricing_gap_reason("openai", "gpt-5.6-sol") is None


class TestEstimateCallCost:
	def test_modelo_com_preco_real_calcula_custo(self):
		cost = estimate_call_cost("openai", "gpt-5.6-sol", 1_000_000, 1_000_000)
		# 1M de entrada + 1M de saida ao preco de gpt-5.6-sol ($5 + $30)
		assert cost == 35.0

	def test_ollama_sem_preco_retorna_zero_assinatura(self):
		"""Ollama Cloud: custo marginal ~$0 (assinatura ja paga), nao None."""
		assert estimate_call_cost("ollama", "qwen3.5:397b", 4000, 3000) == 0.0

	def test_opencode_go_sem_preco_retorna_zero_assinatura(self):
		assert estimate_call_cost("opencode_go", "gpt-5.6-luna", 4000, 3000) == 0.0

	def test_modelo_desconhecido_sem_assinatura_retorna_none(self):
		"""Provider pago mas modelo nao catalogado: None (nao e $0 real,
		e falta de dado -- nunca tratar como gratis silenciosamente)."""
		assert estimate_call_cost("openai", "modelo-nao-catalogado-xyz", 4000, 3000) is None


class TestSemModeloComPrecoSemFonteDocumentada:
	def test_todo_preco_catalogado_tem_source_url(self):
		for provider, models in MODEL_PRICING.items():
			for model_id, price in models.items():
				assert price.source_url.startswith("https://"), (
					f"{provider}/{model_id} sem source_url valida"
				)

	def test_todo_gap_tem_motivo_nao_vazio(self):
		for provider, models in PRICING_GAPS.items():
			for model_id, reason in models.items():
				assert reason and len(reason.strip()) > 5, (
					f"{provider}/{model_id} com motivo vazio/curto demais em PRICING_GAPS"
				)
