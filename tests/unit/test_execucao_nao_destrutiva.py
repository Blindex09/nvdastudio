"""O carregamento de um addon so executa depois de uma triagem de operacoes destrutivas."""


class TestNaoExecutaCodigoDestrutivoNoCarregamento:
	def _valida(self, codigo: str):
		from nvdastudio_mcp.code_sandbox import CodeSandbox
		return CodeSandbox().validate_addon_execution(
			{"globalPlugins/X/__init__.py": codigo}
		)

	def test_os_remove_em_nivel_de_modulo_pula_execucao(self):
		codigo = (
			"import os\n"
			"os.remove('arquivo_qualquer.txt')\n"
			"import globalPluginHandler\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tpass\n"
		)
		r = self._valida(codigo)
		assert "PULADO_POR_SEGURANCA" in r.stdout
		assert "os.remove" in r.stdout

	def test_rmtree_no_init_pula_execucao(self):
		codigo = (
			"import shutil\n"
			"import globalPluginHandler\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef __init__(self, *a, **k):\n"
			"\t\tsuper().__init__(*a, **k)\n"
			"\t\tshutil.rmtree('uma_pasta')\n"
		)
		r = self._valida(codigo)
		assert "PULADO_POR_SEGURANCA" in r.stdout

	def test_op_destrutiva_em_metodo_de_script_ainda_executa(self):
		"""Falso positivo aqui recusaria addon legitimo: rmtree DENTRO de um
		script (so roda quando o usuario aciona) nao roda na validacao -- nao
		deve pular. O helper so varre nivel de modulo e __init__."""
		codigo = (
			"import shutil\n"
			"import globalPluginHandler\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef limparCache(self, gesture):\n"
			"\t\tshutil.rmtree('cache')\n"
		)
		r = self._valida(codigo)
		assert "PULADO_POR_SEGURANCA" not in r.stdout


def test_op_destrutiva_helper_direto():
	from nvdastudio_mcp.code_sandbox import _op_destrutiva_no_carregamento

	assert _op_destrutiva_no_carregamento(
		{"a.py": "import os\nos.remove('x')\n"}
	)
	assert _op_destrutiva_no_carregamento(
		{"a.py": "from shutil import rmtree\ndef f():\n\trmtree('x')\n"}
	) == "", "rmtree dentro de funcao nao-carregada nao deve disparar"
