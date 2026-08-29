from nvdastudio.ai.model_registry import _ALIASES, ModelRegistry


class TestAliasesNuncaApontamParaModeloDeprecated:
	def test_nenhum_alias_resolve_para_modelo_deprecated_ou_retired(self):
		registry = ModelRegistry()
		for alias, target in _ALIASES.items():
			assert not registry.is_deprecated(alias), (
				f"Alias '{alias}' resolve para '{target}', que esta deprecated/retired"
			)

	def test_gpt_fast_resolve_para_modelo_ativo(self):
		registry = ModelRegistry()
		assert _ALIASES["gpt-fast"] == "gpt-5.6-luna"
		assert registry.is_active("gpt-fast")
