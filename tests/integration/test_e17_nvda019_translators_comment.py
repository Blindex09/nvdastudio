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


class TestNVDA019TranslatorsComment:
	"""NVDA-019: chamadas a _() sem comentario # Translators: nao sao extraidas pelo Poedit."""

	def test_sem_translators_comment_gera_nvda019(self, tmp_path):
		"""
		ui.message(_("Hello")) sem # Translators: na linha anterior deve gerar NVDA-019.
		O Poedit nao conseguira extrair a string para traducao sem esse comentario.
		"""
		codigo = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import ui\n\n"
			"addonHandler.initTranslation()\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef event_gainFocus(self, obj, nextHandler):\n"
			'\t\tui.message(_("Foco ganho"))\n'
			"\t\tnextHandler()\n"
			"\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo)
		problems = validate_addon_structure(addon_folder)

		nvda019_problems = [p for p in problems if "NVDA-019" in p]
		assert nvda019_problems, (
			f"Esperado problema NVDA-019 para _() sem # Translators:. "
			f"Todos os problemas: {problems}"
		)

	def test_com_translators_comment_nao_gera_nvda019(self, tmp_path):
		"""
		# Translators: Message spoken when focus changes
		ui.message(_("Hello")) -> sem NVDA-019.
		Comentario Translators: presente na linha anterior — Poedit consegue extrair.
		"""
		codigo = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import ui\n\n"
			"addonHandler.initTranslation()\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef event_gainFocus(self, obj, nextHandler):\n"
			"\t\t# Translators: Mensagem falada quando o foco muda\n"
			'\t\tui.message(_("Foco ganho"))\n'
			"\t\tnextHandler()\n"
			"\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo)
		problems = validate_addon_structure(addon_folder)

		nvda019_problems = [p for p in problems if "NVDA-019" in p]
		assert not nvda019_problems, (
			f"Nao deveria gerar NVDA-019 quando # Translators: esta presente. "
			f"Problemas NVDA-019 encontrados: {nvda019_problems}"
		)

	def test_nvda019_nao_dispara_em_strings_sem_traducao(self, tmp_path):
		"""
		Codigo sem _() nao deve disparar NVDA-019.
		ui.message() com string literal direta nao e funcao de traducao.
		"""
		codigo = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import ui\n\n"
			"addonHandler.initTranslation()\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef event_gainFocus(self, obj, nextHandler):\n"
			'\t\tui.message("Foco ganho sem traducao")\n'
			"\t\tnextHandler()\n"
			"\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo)
		problems = validate_addon_structure(addon_folder)

		nvda019_problems = [p for p in problems if "NVDA-019" in p]
		assert not nvda019_problems, (
			f"Nao deve disparar NVDA-019 para codigo sem _() de traducao. "
			f"Problemas NVDA-019 encontrados: {nvda019_problems}"
		)
