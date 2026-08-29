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
	# Escreve o arquivo sem processamento de escapes — o conteudo ja tem TABs ou espacos literais
	(gp / "__init__.py").write_bytes(plugin_code.encode("utf-8"))
	return str(tmp_path)


class TestNVDA021IndentationStyle:
	"""NVDA-021: indentacao com espacos em vez de TABs causa IndentationError no NVDA."""

	def test_espacos_geram_nvda021(self, tmp_path):
		"""
		Arquivo Python com indentacao de 4 espacos deve gerar NVDA-021.
		O NVDA e o core NVDA usam TABs — misturar causaria IndentationError.

		NOTA: As linhas do metodo abaixo usam 4 espacos LITERAIS para simular
		o codigo com indentacao errada que o validador deve detectar.
		"""
		# Codigo com indentacao de 4 espacos (proposital — e o que o validador deve detectar)
		codigo_com_espacos = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import ui\n\n"
			"addonHandler.initTranslation()\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"    def event_gainFocus(self, obj, nextHandler):\n"
			"        ui.message('foco')\n"
			"        nextHandler()\n"
			"\n"
			"    def terminate(self):\n"
			"        super().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo_com_espacos)
		problems = validate_addon_structure(addon_folder)

		nvda021_problems = [p for p in problems if "NVDA-021" in p]
		assert nvda021_problems, (
			f"Esperado problema NVDA-021 para indentacao com espacos. "
			f"Todos os problemas: {problems}"
		)

	def test_tabs_nao_geram_nvda021(self, tmp_path):
		"""
		Arquivo Python com indentacao de TABs nao deve gerar NVDA-021.
		TABs e o padrao correto para addons NVDA.
		"""
		# Codigo com indentacao de TABs (correto para NVDA)
		codigo_com_tabs = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import ui\n\n"
			"addonHandler.initTranslation()\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef event_gainFocus(self, obj, nextHandler):\n"
			"\t\tui.message('foco')\n"
			"\t\tnextHandler()\n"
			"\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo_com_tabs)
		problems = validate_addon_structure(addon_folder)

		nvda021_problems = [p for p in problems if "NVDA-021" in p]
		assert not nvda021_problems, (
			f"Nao deveria gerar NVDA-021 para indentacao com TABs. "
			f"Problemas NVDA-021 encontrados: {nvda021_problems}"
		)

	def test_nvda021_menciona_arquivo(self, tmp_path):
		"""
		A mensagem de erro NVDA-021 deve mencionar o nome do arquivo afetado.
		Isso permite ao desenvolvedor identificar qual arquivo corrigir.
		"""
		codigo_com_espacos = (
			"import globalPluginHandler\n"
			"import addonHandler\n\n"
			"addonHandler.initTranslation()\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"    def terminate(self):\n"
			"        super().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo_com_espacos)
		problems = validate_addon_structure(addon_folder)

		nvda021_problems = [p for p in problems if "NVDA-021" in p]
		assert nvda021_problems, (
			f"Esperado NVDA-021 para indentacao com espacos. "
			f"Todos os problemas: {problems}"
		)
		mensagem = nvda021_problems[0]
		# Mensagem deve mencionar o nome do arquivo (__init__.py)
		assert "__init__.py" in mensagem, (
			f"Mensagem NVDA-021 deve mencionar '__init__.py'. "
			f"Mensagem recebida: {mensagem}"
		)
