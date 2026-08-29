class TestModelosDaUIVemDoRegistryReal:
	def test_ollama_inclui_o_heavy_default_atual(self):
		from nvdastudio.gui.settings_panel import _MODELS_BY_PROVIDER
		codes = {code for _, code in _MODELS_BY_PROVIDER["ollama"]}
		assert "kimi-k2.7-code" in codes, (
			"Dropdown do Ollama deveria incluir o tier heavy default atual"
		)

	def test_ollama_inclui_os_3_modelos_novos_de_2026_08_04(self):
		from nvdastudio.gui.settings_panel import _MODELS_BY_PROVIDER
		codes = {code for _, code in _MODELS_BY_PROVIDER["ollama"]}
		for novo in ("glm-5.2", "minimax-m3", "gpt-oss:20b"):
			assert novo in codes, f"Dropdown do Ollama deveria incluir {novo}"

	def test_ollama_nao_inclui_modelo_fantasma_glm_z1(self):
		from nvdastudio.gui.settings_panel import _MODELS_BY_PROVIDER
		codes = {code for _, code in _MODELS_BY_PROVIDER["ollama"]}
		assert "glm-z1" not in codes, (
			"glm-z1 nunca existiu em nenhum catalogo real -- nao deveria estar na UI"
		)

	def test_anthropic_nao_inclui_claude_fable_5(self):
		"""claude-fable-5 foi removido do registry por completo (Felipe:
		'tire fable 5 do claude') -- nao pode sobrar na UI."""
		from nvdastudio.gui.settings_panel import _MODELS_BY_PROVIDER
		codes = {code for _, code in _MODELS_BY_PROVIDER["anthropic"]}
		assert "claude-fable-5" not in codes

	def test_anthropic_inclui_o_heavy_default_atual(self):
		from nvdastudio.gui.settings_panel import _MODELS_BY_PROVIDER
		codes = {code for _, code in _MODELS_BY_PROVIDER["anthropic"]}
		assert "claude-opus-5" in codes
		assert "claude-opus-4-8" not in codes, "claude-opus-4-8 esta DEPRECATED, nao deveria aparecer"

	def test_gemini_inclui_o_light_default_atual(self):
		from nvdastudio.gui.settings_panel import _MODELS_BY_PROVIDER
		codes = {code for _, code in _MODELS_BY_PROVIDER["gemini"]}
		assert "gemini-3.6-flash" in codes

	def test_xai_inclui_o_heavy_default_atual(self):
		from nvdastudio.gui.settings_panel import _MODELS_BY_PROVIDER
		codes = {code for _, code in _MODELS_BY_PROVIDER["xai"]}
		assert "grok-build-0.1" in codes

	def test_todo_provedor_comeca_com_alto(self):
		from nvdastudio.ai.model_registry import ALTO_MODEL
		from nvdastudio.gui.settings_panel import _MODELS_BY_PROVIDER
		for provider, models in _MODELS_BY_PROVIDER.items():
			assert models[0][1] == ALTO_MODEL, f"{provider}: 'Alto' deveria ser a 1a opcao"

	def test_nenhum_provedor_lista_modelo_deprecated_ou_retired(self):
		"""Todo model_id que aparece em qualquer dropdown da UI deve estar
		ACTIVE ou PREVIEW no registry (ou ser o sentinela 'alto')."""
		from nvdastudio.ai.model_registry import ALTO_MODEL, registry
		from nvdastudio.gui.settings_panel import _MODELS_BY_PROVIDER

		for provider, models in _MODELS_BY_PROVIDER.items():
			for _label, code in models:
				if code == ALTO_MODEL:
					continue
				assert not registry.is_deprecated(code), (
					f"{provider}: modelo '{code}' esta deprecated/retired mas aparece na UI"
				)

	def test_todo_modelo_ativo_do_registry_aparece_em_algum_provedor_da_ui(self):
		"""Nenhum modelo ACTIVE/PREVIEW do registry pode ficar invisivel na
		UI -- exatamente a classe de bug que motivou esta correcao."""
		from nvdastudio.ai.model_registry import registry
		from nvdastudio.gui.settings_panel import _MODELS_BY_PROVIDER

		todos_visiveis = {
			code for models in _MODELS_BY_PROVIDER.values() for _label, code in models
		}
		for info in registry.get_active_models():
			assert info.model_id in todos_visiveis, (
				f"Modelo ativo '{info.model_id}' (provider={info.provider}) "
				f"nao aparece em nenhum dropdown da UI"
			)


class TestPrettifyModelId:
	def test_modelo_sem_rotulo_curado_ainda_aparece_legivel(self):
		from nvdastudio.gui.settings_panel import _prettify_model_id
		assert _prettify_model_id("um-modelo-novo-2027") == "Um Modelo Novo 2027"

	def test_nao_retorna_vazio_nunca(self):
		from nvdastudio.gui.settings_panel import _prettify_model_id
		assert _prettify_model_id("x") != ""
