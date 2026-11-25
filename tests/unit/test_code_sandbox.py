class TestRunTestSuitePerformance:
	"""
	_run_pytest) levava 3.9s de wall-clock pra rodar UM teste trivial
	rapido). Sob contencao real de CPU (suite completa rodando em
	paralelo), essa sobrecarga sozinha ja chegava perto do teto de
	_TEST_SUITE_TIMEOUT (25s) -- causa raiz do timeout flaky visto nesta
	mesma sessao em test_test_generator_por_feature.py.
	"""

	def test_run_pytest_desliga_plugin_autoload(self):
		from types import SimpleNamespace
		from unittest.mock import patch
		from nvdastudio_mcp.code_sandbox import CodeSandbox

		fake_proc = SimpleNamespace(returncode=0, stdout="1 passed", stderr="", error="", timed_out=False, isolated=True, backend="docker")
		with patch.object(CodeSandbox, "_isolated_python", return_value=fake_proc) as isolated:
			CodeSandbox()._run_pytest("/tmp/qualquer", ["test_x.py"], timeout=25)

		env = isolated.call_args.args[3]
		assert env.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") == "1"

	def test_run_pytest_nao_repassa_ambiente_nem_credenciais(self):
		"""O contêiner recebe uma allowlist, nunca APPDATA/PATH/chaves."""
		from types import SimpleNamespace
		from unittest.mock import patch
		from nvdastudio_mcp.code_sandbox import CodeSandbox

		fake_proc = SimpleNamespace(returncode=0, stdout="1 passed", stderr="", error="", timed_out=False, isolated=True, backend="docker")
		with patch.object(CodeSandbox, "_isolated_python", return_value=fake_proc) as isolated:
			CodeSandbox()._run_pytest("/tmp/qualquer", ["test_x.py"], timeout=25)

		env = isolated.call_args.args[3]
		assert set(env) == {"PYTEST_DISABLE_PLUGIN_AUTOLOAD"}


class TestValidateAddonExecution:
	"""
	1.2.0: validate_addon_execution() -- importa e INSTANCIA de verdade a
	classe principal do addon gerado, em subprocesso isolado com os modulos
	NVDA simulados (builder/nvda_runtime_stubs.py). Fecha a lacuna real:
	validate_addon_imports()/run_python_code() (1.0.0) nunca eram chamados
	por ninguem em producao porque importar contra os modulos REAIS do
	NVDA sempre falha (so existem dentro do processo do NVDA).
	"""

	_GOOD_ADDON = (
		"import addonHandler\n"
		"import globalPluginHandler\n"
		"import ui\n"
		"from scriptHandler import script\n\n"
		"addonHandler.initTranslation()\n\n"
		"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
		"\tdef __init__(self, *args, **kwargs):\n"
		"\t\tsuper().__init__(*args, **kwargs)\n"
		"\t\tui.message(\"ola\")\n\n"
		"\t@script(description=\"Testa\")\n"
		"\tdef script_teste(self, gesture):\n"
		"\t\tui.message(\"testando\")\n"
	)

	def test_addon_valido_passa(self):
		from nvdastudio_mcp.code_sandbox import CodeSandbox
		result = CodeSandbox().validate_addon_execution(
			{"globalPlugins/MeuAddon/__init__.py": self._GOOD_ADDON}
		)
		assert result.success is True
		assert "OK" in result.stdout

	def test_nameerror_real_e_detectado(self):
		"""Diferente de uma checagem so de sintaxe, isso executa de verdade
		e pega erro que so aparece em runtime."""
		from nvdastudio_mcp.code_sandbox import CodeSandbox
		bad = (
			"import addonHandler\n"
			"import globalPluginHandler\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef __init__(self, *args, **kwargs):\n"
			"\t\tsuper().__init__(*args, **kwargs)\n"
			"\t\tprint(variavel_nunca_definida)\n"
		)
		result = CodeSandbox().validate_addon_execution(
			{"globalPlugins/MeuAddon/__init__.py": bad}
		)
		assert result.success is False
		assert "NameError" in result.stderr
		assert "variavel_nunca_definida" in result.stderr

	def test_chamada_de_api_do_nvda_nao_gera_falso_positivo(self):
		"""Chamadas legitimas a API do NVDA (ui.message, tones.beep, etc)
		nao devem ser tratadas como erro -- o stub permissivo aceita
		qualquer atributo/chamada dos modulos NVDA sem lancar excecao."""
		from nvdastudio_mcp.code_sandbox import CodeSandbox
		code = (
			"import addonHandler\n"
			"import globalPluginHandler\n"
			"import ui\n"
			"import tones\n"
			"import config\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef __init__(self, *args, **kwargs):\n"
			"\t\tsuper().__init__(*args, **kwargs)\n"
			"\t\tui.message(\"x\")\n"
			"\t\ttones.beep(500, 100)\n"
			"\t\tconfig.conf[\"algumaChave\"] = True\n"
		)
		result = CodeSandbox().validate_addon_execution(
			{"globalPlugins/MeuAddon/__init__.py": code}
		)
		assert result.success is True

	def test_sem_globalplugin_nao_falha(self):
		"""Arquivo sem classe principal reconhecida (ex: so funcoes
		utilitarias) nao deve ser tratado como erro."""
		from nvdastudio_mcp.code_sandbox import CodeSandbox
		result = CodeSandbox().validate_addon_execution(
			{"globalPlugins/MeuAddon/__init__.py": "def util():\n\treturn 1\n"}
		)
		assert result.success is True
		assert "SEM_CLASSE_PRINCIPAL_ENCONTRADA" in result.stdout

	def test_sem_arquivo_globalplugins_retorna_sucesso_sem_validar(self):
		"""Nada pra validar (ex: so manifest.ini/docs) -- nao e erro."""
		from nvdastudio_mcp.code_sandbox import CodeSandbox
		result = CodeSandbox().validate_addon_execution(
			{"manifest.ini": "name = X\n"}
		)
		assert result.success is True

	def test_settings_panel_tambem_e_reconhecido(self):
		from nvdastudio_mcp.code_sandbox import CodeSandbox
		code = (
			"import gui\n\n"
			"class MinhasConfiguracoes(gui.SettingsPanel):\n"
			"\tdef makeSettings(self, sizer):\n"
			"\t\tpass\n"
		)
		result = CodeSandbox().validate_addon_execution(
			{"globalPlugins/MeuAddon/__init__.py": code}
		)
		assert result.success is True
		assert "OK" in result.stdout


class TestKeyboardFocusManagementVerification:
	"""
	1.3.0: verificacao de Keyboard/Focus Management -- item #5 da lista de
	melhorias priorizadas. bindGesture() via dict de classe __gestures e o
	padrao estatico normal (limpo automaticamente com a instancia), mas
	self.bindGesture() DINAMICO sem removeGestureBinding() correspondente
	acumula gestures duplicados a cada rebind.
	"""

	def test_bindgesture_dinamico_sem_unbind_gera_aviso(self):
		from nvdastudio_mcp.code_sandbox import CodeSandbox
		code = (
			"import globalPluginHandler\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef atualizarAtalho(self, gesture):\n"
			"\t\tself.bindGesture(gesture, \"minhaAcao\")\n"
		)
		result = CodeSandbox().validate_addon_execution(
			{"globalPlugins/MeuAddon/__init__.py": code}
		)
		assert result.success is True
		assert "AVISO_BINDGESTURE_SEM_UNBIND: GlobalPlugin" in result.stdout

	def test_bindgesture_com_unbind_correspondente_nao_gera_aviso(self):
		from nvdastudio_mcp.code_sandbox import CodeSandbox
		code = (
			"import globalPluginHandler\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef atualizarAtalho(self, gestureAntigo, gestureNovo):\n"
			"\t\tself.removeGestureBinding(gestureAntigo)\n"
			"\t\tself.bindGesture(gestureNovo, \"minhaAcao\")\n"
		)
		result = CodeSandbox().validate_addon_execution(
			{"globalPlugins/MeuAddon/__init__.py": code}
		)
		assert result.success is True
		assert "AVISO_BINDGESTURE_SEM_UNBIND" not in result.stdout

	def test_gestures_estatico_via_dict_de_classe_nao_gera_aviso(self):
		"""Padrao NVDA normal (__gestures = {...}) nao chama self.bindGesture()
		em lugar nenhum -- nao deve disparar o aviso."""
		from nvdastudio_mcp.code_sandbox import CodeSandbox
		code = (
			"import globalPluginHandler\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\t__gestures = {\"kb:NVDA+shift+x\": \"minhaAcao\"}\n\n"
			"\tdef script_minhaAcao(self, gesture):\n"
			"\t\tpass\n"
		)
		result = CodeSandbox().validate_addon_execution(
			{"globalPlugins/MeuAddon/__init__.py": code}
		)
		assert result.success is True
		assert "AVISO_BINDGESTURE_SEM_UNBIND" not in result.stdout
