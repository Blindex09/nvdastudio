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


class TestWXA11Y001ButtonSetName:
	"""WX-A11Y-001: wx.Button sem .SetName() e inutilizavel por leitores de tela."""

	def test_button_sem_setname_gera_wxa11y001(self, tmp_path):
		"""
		Codigo com wx.Button(self) sem label= nem .SetName() deve gerar WX-A11Y-001.
		Botoes sem nome acessivel sao anunciados apenas como 'Botao' por leitores de tela.

		NOTA: label="..." satisfaz o fix primario de WX-A11Y-001 (fonte oficial:
		wxpython-specialist.agent.md) -- por isso o botao aqui e criado SEM label
		para continuar exercitando o caminho de violacao real. O comentario no
		codigo do addon nao pode mencionar '.SetName(' pois o validador usa busca
		simples de substring e o comentario geraria falso negativo.
		"""
		codigo = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import wx\n\n"
			"addonHandler.initTranslation()\n\n"
			"class MeuDialog(wx.Dialog):\n"
			'\t\tdef __init__(self, parent):\n'
			'\t\t\tsuper().__init__(parent, title="Teste")\n'
			"\t\t\tself.btn = wx.Button(self)\n"
			"\t\t\t# nome acessivel nao configurado — violacao de acessibilidade\n"
			"\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo)
		problems = validate_addon_structure(addon_folder)

		wxa11y001_problems = [p for p in problems if "WX-A11Y-001" in p]
		assert wxa11y001_problems, (
			f"Esperado problema WX-A11Y-001 para wx.Button sem .SetName(). "
			f"Todos os problemas: {problems}"
		)

	def test_button_com_setname_nao_gera_wxa11y001(self, tmp_path):
		"""
		Codigo com wx.Button e .SetName("label") nao deve gerar WX-A11Y-001.
		Nome acessivel presente — leitores de tela podem anunciar corretamente.
		"""
		codigo = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import wx\n\n"
			"addonHandler.initTranslation()\n\n"
			"class MeuDialog(wx.Dialog):\n"
			'\t\tdef __init__(self, parent):\n'
			'\t\t\tsuper().__init__(parent, title="Teste")\n'
			"\t\t\tself.btn = wx.Button(self, label=\"OK\")\n"
			"\t\t\tself.btn.SetName(\"Confirmar\")\n"
			"\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo)
		problems = validate_addon_structure(addon_folder)

		wxa11y001_problems = [p for p in problems if "WX-A11Y-001" in p]
		assert not wxa11y001_problems, (
			f"Nao deveria gerar WX-A11Y-001 quando .SetName() esta presente. "
			f"Problemas WX-A11Y-001 encontrados: {wxa11y001_problems}"
		)


class TestWXA11Y002PanelAcceleratorTable:
	"""WX-A11Y-002: wx.Panel ou wx.Frame sem AcceleratorTable impede navegacao por teclado."""

	def test_panel_sem_acelerador_gera_wxa11y002(self, tmp_path):
		"""
		wx.Panel sem AcceleratorTable deve gerar WX-A11Y-002.
		Usuarios de teclado nao conseguem ativar acoes sem tabela de atalhos.

		NOTA: O validador busca 'wx.Panel(' (com parentese) para detectar instanciacao.
		A declaracao 'class MeuPanel(wx.Panel):' nao dispara o validador — precisa
		de instanciacao como 'panel = wx.Panel(parent)' ou equivalente.
		Tambem nao pode mencionar 'AcceleratorTable' em comentarios.
		"""
		codigo = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import wx\n\n"
			"addonHandler.initTranslation()\n\n"
			"class MeuDialog(wx.Dialog):\n"
			'\tdef __init__(self, parent):\n'
			'\t\tsuper().__init__(parent, title="Teste")\n'
			"\t\tself.panel = wx.Panel(self)\n"
			"\t\tself.btn = wx.Button(self.panel, label=\"OK\")\n"
			"\t\tself.btn.SetName(\"Confirmar\")\n"
			"\t\t# tabela de atalhos nao configurada\n"
			"\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo)
		problems = validate_addon_structure(addon_folder)

		wxa11y002_problems = [p for p in problems if "WX-A11Y-002" in p]
		assert wxa11y002_problems, (
			f"Esperado problema WX-A11Y-002 para wx.Panel sem AcceleratorTable. "
			f"Todos os problemas: {problems}"
		)


class TestWXA11Y003EventoMouse:
	"""WX-A11Y-003: EVT_LEFT_DOWN sem equivalente de teclado e inacessivel."""

	def test_evt_left_down_sem_teclado_gera_wxa11y003(self, tmp_path):
		"""
		Bind(wx.EVT_LEFT_DOWN, ...) sem EVT_CHAR_HOOK nem EVT_KEY_DOWN deve gerar WX-A11Y-003.
		Acao acessivel apenas por mouse exclui usuarios de teclado.

		NOTA: O comentario no codigo do addon nao pode mencionar 'EVT_CHAR_HOOK' pois
		o validador usa busca simples de substring e o comentario geraria falso negativo.
		"""
		codigo = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import wx\n\n"
			"addonHandler.initTranslation()\n\n"
			"class MeuPanel(wx.Panel):\n"
			'\t\tdef __init__(self, parent):\n'
			'\t\t\tsuper().__init__(parent)\n'
			"\t\t\tself.Bind(wx.EVT_LEFT_DOWN, self._on_click)\n"
			"\t\t\t# apenas evento de mouse — sem suporte a teclado\n"
			"\n"
			"\t\tdef _on_click(self, event):\n"
			"\t\t\tevent.Skip()\n"
			"\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo)
		problems = validate_addon_structure(addon_folder)

		wxa11y003_problems = [p for p in problems if "WX-A11Y-003" in p]
		assert wxa11y003_problems, (
			f"Esperado problema WX-A11Y-003 para EVT_LEFT_DOWN sem equivalente de teclado. "
			f"Todos os problemas: {problems}"
		)

	def test_evt_left_down_com_char_hook_nao_gera_wxa11y003(self, tmp_path):
		"""
		Bind(wx.EVT_LEFT_DOWN, ...) + Bind(wx.EVT_CHAR_HOOK, ...) nao deve gerar WX-A11Y-003.
		Equivalente de teclado presente — acao acessivel por mouse E teclado.
		"""
		codigo = (
			"import globalPluginHandler\n"
			"import addonHandler\n"
			"import wx\n\n"
			"addonHandler.initTranslation()\n\n"
			"class MeuPanel(wx.Panel):\n"
			'\t\tdef __init__(self, parent):\n'
			'\t\t\tsuper().__init__(parent)\n'
			"\t\t\tself.Bind(wx.EVT_LEFT_DOWN, self._on_click)\n"
			"\t\t\tself.Bind(wx.EVT_CHAR_HOOK, self._on_key)\n"
			"\n"
			"\t\tdef _on_click(self, event):\n"
			"\t\t\tevent.Skip()\n"
			"\n"
			"\t\tdef _on_key(self, event):\n"
			"\t\t\tevent.Skip()\n"
			"\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef terminate(self):\n"
			"\t\tsuper().terminate()\n"
		)
		addon_folder = _criar_addon(tmp_path, codigo)
		problems = validate_addon_structure(addon_folder)

		wxa11y003_problems = [p for p in problems if "WX-A11Y-003" in p]
		assert not wxa11y003_problems, (
			f"Nao deveria gerar WX-A11Y-003 quando EVT_CHAR_HOOK esta presente. "
			f"Problemas WX-A11Y-003 encontrados: {wxa11y003_problems}"
		)

