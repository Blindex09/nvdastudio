from nvdastudio.builder.addon_builder import validate_addon_structure


_MANIFEST_VALIDO = (
	"name = TestAddon\n"
	"version = 1.0.0\n"
	"minimumNVDAVersion = 2026.1.1\n"
	"lastTestedNVDAVersion = 2026.1.1\n"
)


def _criar_addon(tmp_path, plugin_code: str) -> str:
	"""Cria estrutura minima de addon em tmp_path e retorna o path da pasta."""
	(tmp_path / "manifest.ini").write_text(_MANIFEST_VALIDO, encoding="utf-8")
	gp = tmp_path / "globalPlugins" / "testAddon"
	gp.mkdir(parents=True)
	(gp / "__init__.py").write_text(plugin_code, encoding="utf-8")
	return str(tmp_path)


class TestNVDA008ScriptDescription:
	"""NVDA-008: @script sem kwarg 'description' fica invisivel no dialogo de gestos."""

	def test_script_sem_description_gera_nvda008(self, tmp_path):
		"""
		@script(gesture="kb:NVDA+t") sem description= deve gerar NVDA-008.
		Scripts sem description ficam invisiveis no dialogo 'Gestos de Entrada' do NVDA.
		"""
		codigo = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import ui\n"
			"from scriptHandler import script\n\n"
			"addonHandler.initTranslation()\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			'\t@script(gesture="kb:NVDA+t")\n'
			"\tdef script_anuncia_titulo(self, gesture):\n"
			"\t\tui.message('titulo')\n"
			"\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo)
		problems = validate_addon_structure(addon_folder)

		nvda008_problems = [p for p in problems if "NVDA-008" in p]
		assert nvda008_problems, (
			f"Esperado problema NVDA-008 mas nenhum foi gerado. "
			f"Todos os problemas: {problems}"
		)

	def test_script_com_description_nao_gera_nvda008(self, tmp_path):
		"""
		@script(description=_('Minha desc'), gesture="kb:NVDA+t") nao deve gerar NVDA-008.
		"""
		codigo = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import ui\n"
			"from scriptHandler import script\n\n"
			"addonHandler.initTranslation()\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			'\t@script(description=_("Anuncia o titulo da janela"), gesture="kb:NVDA+t")\n'
			"\tdef script_anuncia_titulo(self, gesture):\n"
			"\t\tui.message('titulo')\n"
			"\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo)
		problems = validate_addon_structure(addon_folder)

		nvda008_problems = [p for p in problems if "NVDA-008" in p]
		assert not nvda008_problems, (
			f"Nao deveria gerar NVDA-008 quando description esta presente. "
			f"Problemas NVDA-008 encontrados: {nvda008_problems}"
		)

	def test_script_bare_sem_parenteses_gera_nvda008(self, tmp_path):
		"""
		@script sem parenteses nenhum tambem deve gerar NVDA-008.
		Sem argumentos nao ha como ter description.
		"""
		codigo = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import ui\n"
			"from scriptHandler import script\n\n"
			"addonHandler.initTranslation()\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\t@script\n"
			"\tdef script_sem_args(self, gesture):\n"
			"\t\tui.message('sem args')\n"
			"\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo)
		problems = validate_addon_structure(addon_folder)

		nvda008_problems = [p for p in problems if "NVDA-008" in p]
		assert nvda008_problems, (
			f"Esperado problema NVDA-008 para @script sem parenteses. "
			f"Todos os problemas: {problems}"
		)

