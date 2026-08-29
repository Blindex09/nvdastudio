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


class TestNVDA009ReservedGestures:
	"""NVDA-009: uso de gestures reservados pelo NVDA core pode quebrar comandos globais."""

	def test_gesture_reservado_gera_nvda009(self, tmp_path):
		"""
		gesture="kb:NVDA+n" e reservado para o menu NVDA.
		Deve gerar problema NVDA-009.
		"""
		codigo = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import ui\n"
			"from scriptHandler import script\n\n"
			"addonHandler.initTranslation()\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			'\t@script(description=_("Abre menu"), gesture="kb:NVDA+n")\n'
			"\tdef script_menu(self, gesture):\n"
			"\t\tui.message('menu')\n"
			"\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo)
		problems = validate_addon_structure(addon_folder)

		nvda009_problems = [p for p in problems if "NVDA-009" in p]
		assert nvda009_problems, (
			f"Esperado problema NVDA-009 para gesture reservado 'kb:NVDA+n'. "
			f"Todos os problemas: {problems}"
		)

	def test_gesture_nao_reservado_nao_gera_nvda009(self, tmp_path):
		"""
		gesture="kb:NVDA+shift+t" nao e reservado pelo NVDA core.
		Nao deve gerar problema NVDA-009.
		"""
		codigo = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import ui\n"
			"from scriptHandler import script\n\n"
			"addonHandler.initTranslation()\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			'\t@script(description=_("Anuncia titulo"), gesture="kb:NVDA+shift+t")\n'
			"\tdef script_titulo(self, gesture):\n"
			"\t\tui.message('titulo')\n"
			"\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo)
		problems = validate_addon_structure(addon_folder)

		nvda009_problems = [p for p in problems if "NVDA-009" in p]
		assert not nvda009_problems, (
			f"Nao deveria gerar NVDA-009 para gesture 'kb:NVDA+shift+t' (nao reservado). "
			f"Problemas NVDA-009 encontrados: {nvda009_problems}"
		)

	def test_nvda009_menciona_gesture_conflitante(self, tmp_path):
		"""
		A mensagem de erro NVDA-009 deve mencionar o gesture especifico que causou o conflito.
		Isso permite ao desenvolvedor identificar qual atalho mudar.
		"""
		codigo = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import ui\n"
			"from scriptHandler import script\n\n"
			"addonHandler.initTranslation()\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			'\t@script(description=_("Teste"), gesture="kb:NVDA+t")\n'
			"\tdef script_teste(self, gesture):\n"
			"\t\tui.message('teste')\n"
			"\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo)
		problems = validate_addon_structure(addon_folder)

		nvda009_problems = [p for p in problems if "NVDA-009" in p]
		assert nvda009_problems, (
			f"Esperado NVDA-009 para gesture reservado 'kb:NVDA+t'. "
			f"Todos os problemas: {problems}"
		)
		# A mensagem deve mencionar o gesture conflitante
		mensagem = nvda009_problems[0]
		assert "nvda+t" in mensagem.lower() or "kb:nvda+t" in mensagem.lower(), (
			f"Mensagem NVDA-009 deve mencionar o gesture 'kb:nvda+t'. "
			f"Mensagem recebida: {mensagem}"
		)
