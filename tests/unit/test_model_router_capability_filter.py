class TestSelectModelFiltraPorCapacidadeReal:
	"""
	1.5.0: padrao portado de C:\\agentic (providers_auto.py::_ordered_models()) --
	select_model() agora filtra candidatos por ModelInfo.capabilities ANTES de
	pontuar, quando o chamador exige uma capacidade especifica. Generaliza o
	que antes era so um chain hardcoded pra structured output
	(model_registry.py::STRUCTURED_OUTPUT_MODEL_CHAIN).
	"""

	def test_filtra_candidatos_sem_a_capacidade_exigida(self):
		from nvdastudio.ai.model_router import select_model
		from nvdastudio.core.planner import STEP_CODE_GENERATION

		# provider="anthropic": todos os candidatos tem vision (registro real,
		# ver model_registry.py) -- pedir uma capacidade que NENHUM tem deve
		# cair no fallback gracioso (nao filtra, so pontua e avisa), nunca crash.
		result = select_model(
			"anthropic", STEP_CODE_GENERATION, "alto", complexity="medium",
			required_capabilities=frozenset({"capacidade_que_nao_existe_em_nenhum_modelo"}),
		)
		assert isinstance(result, str) and result

	def test_capacidade_que_existe_em_alguns_restringe_o_pool(self):
		from nvdastudio.ai.model_router import select_model
		from nvdastudio.ai.model_registry import registry
		from nvdastudio.core.planner import STEP_CODE_GENERATION

		candidates = registry.get_active_models_for_ui_provider("anthropic")
		with_computer_use = [m for m in candidates if "computer_use" in m.capabilities]
		without = [m for m in candidates if "computer_use" not in m.capabilities]
		if not with_computer_use or not without:
			return  # dado do registro mudou; nao ha o que testar aqui hoje

		result = select_model(
			"anthropic", STEP_CODE_GENERATION, "alto", complexity="medium",
			required_capabilities=frozenset({"computer_use"}),
		)
		assert result in {m.model_id for m in with_computer_use}

	def test_ollama_nao_tem_json_schema_real_em_nenhum_candidato(self):
		"""
		2026-08-26: achado real de auditoria -- 4 modelos servidos via Ollama
		Cloud (kimi-k2.7-code, kimi-k2.6, gpt-oss:120b, gpt-oss:20b) estavam
		incorretamente marcados com "json_schema" na lista de capacidades,
		contradizendo o teste ao vivo (nenhum modelo Ollama honra json_schema
		estrito de verdade). Corrigido no mesmo commit -- este teste tranca
		que a correcao nao volta silenciosamente.
		"""
		from nvdastudio.ai.model_registry import registry
		candidates = registry.get_active_models_for_ui_provider("ollama")
		com_json_schema = [m.model_id for m in candidates if "json_schema" in m.capabilities]
		assert com_json_schema == [], (
			f"Modelos Ollama com json_schema incorretamente marcado: {com_json_schema}"
		)

	def test_sem_required_capabilities_comportamento_identico_a_antes(self):
		"""None (default) nao filtra nada -- retrocompatibilidade garantida."""
		from nvdastudio.ai.model_router import select_model
		from nvdastudio.core.planner import STEP_CODE_GENERATION

		com_default = select_model("ollama", STEP_CODE_GENERATION, "alto", complexity="low")
		sem_filtro_explicito = select_model(
			"ollama", STEP_CODE_GENERATION, "alto", complexity="low",
			required_capabilities=None,
		)
		assert com_default == sem_filtro_explicito
