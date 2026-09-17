"""Regressao dos 4 achados da auditoria de 2026-09-03/04.

Cada correcao trava aqui o comportamento que faltava, a custo zero de API.
"""

# ---------------------------------------------------------------------------
# Achado 1 -- _infer_python_filename tinha fallback_counter mas o chamador
# nunca passava: dois blocos sem classe e sem anotacao viravam ambos
# module_1.py e o segundo sobrescrevia o primeiro no disco.
# ---------------------------------------------------------------------------

class TestBlocosSemAnotacaoNaoColidem:
	def test_infer_desambigua_por_contador(self):
		from nvdastudio.builder.addon_builder import _infer_python_filename

		a = _infer_python_filename("x = 1\n", None, fallback_counter=1)
		b = _infer_python_filename("y = 2\n", None, fallback_counter=2)
		assert a == "module_1.py"
		assert b == "module_2.py"
		assert a != b, "dois blocos sem classe nao podem colidir no mesmo arquivo"

	def test_extract_atribui_nomes_distintos(self):
		"""O caminho real: extract_code_blocks passa um contador por bloco."""
		from nvdastudio.builder.addon_builder import extract_code_blocks

		texto = "```python\nx = 1\n```\n\n```python\ny = 2\n```\n"
		nomes = sorted(
			b.get("filename", "") for b in extract_code_blocks(texto) if b.get("filename")
		)
		assert nomes == ["module_1.py", "module_2.py"], f"colisao: {nomes}"


# ---------------------------------------------------------------------------
# Achado 2 -- validate_addon_execution executava o codigo com permissoes
# completas do usuario, sem triagem. Um os.remove/shutil.rmtree no
# carregamento apagaria arquivos reais na validacao.
# ---------------------------------------------------------------------------

class TestNaoExecutaCodigoDestrutivoNoCarregamento:
	def _valida(self, codigo: str):
		from nvdastudio.builder.code_sandbox import CodeSandbox
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
	from nvdastudio.builder.code_sandbox import _op_destrutiva_no_carregamento

	assert _op_destrutiva_no_carregamento(
		{"a.py": "import os\nos.remove('x')\n"}
	)
	assert _op_destrutiva_no_carregamento(
		{"a.py": "from shutil import rmtree\ndef f():\n\trmtree('x')\n"}
	) == "", "rmtree dentro de funcao nao-carregada nao deve disparar"
