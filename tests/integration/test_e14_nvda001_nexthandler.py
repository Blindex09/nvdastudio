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


class TestNVDA001EventSemNextHandler:
	"""NVDA-001: event_* com parametro nextHandler que nunca chama nextHandler()."""

	def test_event_sem_nexthandler_gera_nvda001(self, tmp_path):
		"""
		event_gainFocus(self, obj, nextHandler) que NAO chama nextHandler()
		deve gerar problema NVDA-001.
		"""
		codigo = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import ui\n\n"
			"addonHandler.initTranslation()\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef event_gainFocus(self, obj, nextHandler):\n"
			"\t\tui.message('foco ganho')\n"
			"\t\t# nextHandler() NAO e chamado aqui\n"
			"\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo)
		problems = validate_addon_structure(addon_folder)

		nvda001_problems = [p for p in problems if "NVDA-001" in p]
		assert nvda001_problems, (
			f"Esperado problema NVDA-001 mas nenhum foi gerado. "
			f"Todos os problemas: {problems}"
		)

	def test_event_com_nexthandler_nao_gera_nvda001(self, tmp_path):
		"""
		event_gainFocus(self, obj, nextHandler) que CHAMA nextHandler()
		nao deve gerar problema NVDA-001.
		"""
		codigo = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import ui\n\n"
			"addonHandler.initTranslation()\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef event_gainFocus(self, obj, nextHandler):\n"
			"\t\tui.message('foco ganho')\n"
			"\t\tnextHandler()\n"
			"\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo)
		problems = validate_addon_structure(addon_folder)

		nvda001_problems = [p for p in problems if "NVDA-001" in p]
		assert not nvda001_problems, (
			f"Nao deveria gerar NVDA-001 quando nextHandler() e chamado. "
			f"Problemas NVDA-001 encontrados: {nvda001_problems}"
		)

	def test_event_sem_parametro_nexthandler_nao_dispara(self, tmp_path):
		"""
		event_gainFocus(self) sem o parametro nextHandler nao deve disparar NVDA-001.
		NVDA-001 so se aplica quando o parametro nextHandler EXISTE mas nao e chamado.
		"""
		codigo = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import ui\n\n"
			"addonHandler.initTranslation()\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef event_gainFocus(self):\n"
			"\t\tui.message('foco ganho sem nextHandler no parametro')\n"
			"\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo)
		problems = validate_addon_structure(addon_folder)

		nvda001_problems = [p for p in problems if "NVDA-001" in p]
		assert not nvda001_problems, (
			f"Nao deve disparar NVDA-001 quando parametro nextHandler esta ausente. "
			f"Problemas NVDA-001 encontrados: {nvda001_problems}"
		)
