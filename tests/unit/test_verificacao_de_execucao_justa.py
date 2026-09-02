"""
A verificacao de execucao reprovava codigo CERTO, por dois motivos.

1. O stub de `addonHandler.initTranslation()` era um no-op.

   No NVDA de verdade essa funcao injeta `_` (e as variantes de gettext) nos
   GLOBAIS DO MODULO QUE CHAMOU -- e por isso que todo addon correto faz
   `import addonHandler` + `addonHandler.initTranslation()` e depois usa
   `_("texto")` livremente. Com o stub sem efeito, um addon minimamente correto
   pela propria regra NVDA-019 deste projeto falhava com NameError.

   Medido: 6 steps reprovados por "Erro de execucao real", 1.757.209 tokens
   gastos recusando codigo certo. A verificacao estava errada, nao o addon.

2. O nucleo importa modulos que outro step ainda vai gerar.

   Desde que o ponto de entrada passou a ser gerado PRIMEIRO (planner 2.40.0),
   o __init__.py legitimamente importa features que ainda nao existem -- e essa
   e a ordem correta, porque e ele que declara o contrato. Na rodada 6, cg_core
   foi reprovado com "Erro de execucao real" em `from .configSpec import ...`:
   344.333 tokens por importar um arquivo que o plano ainda ia gerar. Cobrar de
   um step a existencia de arquivo que nao e dele e testar uma condicao
   impossivel.
"""

import inspect

from nvdastudio.builder.code_sandbox import CodeSandbox
from nvdastudio.core.orchestrator import MODULE_VERSION, Orchestrator

NL = chr(10)
TAB = chr(9)

_ADDON_CORRETO = (
	"import addonHandler" + NL
	+ "import globalPluginHandler" + NL
	+ "addonHandler.initTranslation()" + NL + NL + NL
	+ "class GlobalPlugin(globalPluginHandler.GlobalPlugin):" + NL
	+ TAB + 'scriptCategory = _("Meu Addon")' + NL + NL
	+ TAB + "def terminate(self):" + NL
	+ TAB + TAB + "super().terminate()" + NL
)


def test_versao():
	assert MODULE_VERSION == "5.82.0"


class TestStubDeTraducao:
	def test_addon_correto_passa_na_execucao(self):
		"""O caso canonico do NVDA -- e o que a regra NVDA-019 EXIGE."""
		r = CodeSandbox().validate_addon_execution(
			{"globalPlugins/Teste/__init__.py": _ADDON_CORRETO},
		)
		assert r.success, (r.stdout or r.stderr or r.error)[:400]

	def test_gettext_sem_inicializar_continua_falhando(self):
		"""Injetar nos globais do CHAMADOR, e nao em builtins, preserva a
		semantica real: o defeito que a regra NVDA-003 existe para pegar
		continua sendo pego."""
		ruim = (
			"import globalPluginHandler" + NL + NL + NL
			+ "class GlobalPlugin(globalPluginHandler.GlobalPlugin):" + NL
			+ TAB + 'scriptCategory = _("Sem init")' + NL
		)
		r = CodeSandbox().validate_addon_execution(
			{"globalPlugins/Teste/__init__.py": ruim},
		)
		assert not r.success

	def test_variantes_de_gettext_tambem_sao_injetadas(self):
		codigo = (
			"import addonHandler" + NL
			+ "import globalPluginHandler" + NL
			+ "addonHandler.initTranslation()" + NL + NL + NL
			+ "class GlobalPlugin(globalPluginHandler.GlobalPlugin):" + NL
			+ TAB + 'um = ngettext("item", "itens", 1)' + NL
			+ TAB + 'ctx = pgettext("menu", "Abrir")' + NL
			+ TAB + 'ctxn = npgettext("menu", "item", "itens", 2)' + NL
		)
		r = CodeSandbox().validate_addon_execution(
			{"globalPlugins/Teste/__init__.py": codigo},
		)
		assert r.success, (r.stdout or r.stderr or r.error)[:400]


class TestArquivosPendentesDoPlano:
	def _orq(self, expected_files, alvos_do_step):
		orq = Orchestrator.__new__(Orchestrator)
		plano = type("P", (), {"expected_files": expected_files})()
		orq._current_plan = plano
		step = type("S", (), {"target_files": alvos_do_step})()
		return orq, step

	def test_arquivo_de_outro_step_entra_como_pendente(self):
		orq, step = self._orq(
			["globalPlugins/A/__init__.py", "globalPlugins/A/configSpec.py"],
			["globalPlugins/A/__init__.py"],
		)
		pendentes = orq._arquivos_de_outros_steps(
			step, {"globalPlugins/A/__init__.py": "x"},
		)
		assert pendentes == ["globalPlugins/A/configSpec.py"]

	def test_arquivo_do_proprio_step_nunca_e_pendente(self):
		"""Se o step declarou e nao entregou, isso e falta DELE -- e a
		verificacao de entrega ja cobra isso."""
		orq, step = self._orq(
			["globalPlugins/A/__init__.py"], ["globalPlugins/A/__init__.py"],
		)
		assert orq._arquivos_de_outros_steps(step, {}) == []

	def test_arquivo_ja_produzido_nao_e_pendente(self):
		orq, step = self._orq(
			["globalPlugins/A/servico.py"], ["globalPlugins/A/__init__.py"],
		)
		assert orq._arquivos_de_outros_steps(
			step, {"globalPlugins/A/servico.py": "conteudo"},
		) == []

	def test_nao_python_e_ignorado(self):
		orq, step = self._orq(["manifest.ini", "doc/pt_BR/readme.html"], [])
		assert orq._arquivos_de_outros_steps(step, {}) == []

	def test_sem_plano_devolve_vazio(self):
		"""Sem plano em maos, o comportamento anterior e o seguro."""
		orq = Orchestrator.__new__(Orchestrator)
		orq._current_plan = None
		step = type("S", (), {"target_files": []})()
		assert orq._arquivos_de_outros_steps(step, {}) == []

	def test_o_orchestrator_usa_os_pendentes_na_verificacao(self):
		"""A costura: calcular os pendentes nao adianta se a checagem nao os
		recebe."""
		src = inspect.getsource(Orchestrator)
		assert "_arquivos_de_outros_steps(step, py_files)" in src
		i = src.index("_arquivos_de_outros_steps(step, py_files)")
		trecho = src[i:i + 700]
		assert "validate_addon_execution(" in trecho
		assert "_arquivos_exec" in trecho


class TestSubmodulosNVDA:
	"""
	Cada submodulo NVDA precisava estar listado a mao no stub, e um que faltasse
	derrubava a verificacao com ModuleNotFoundError.

	Medido na rodada 7: `from gui.message import MessageDialog` reprovou o
	cg_core. E `gui/message.py` e um dos arquivos que o PROPRIO projeto injeta
	nos prompts (_DOCS_CORE em nvda_context.py) -- ensinavamos o modelo a usar
	uma API e reprovavamos quem usasse.
	"""

	def test_submodulo_nvda_nao_listado_resolve(self):
		codigo = (
			"import addonHandler" + NL
			+ "import globalPluginHandler" + NL
			+ "from gui.message import MessageDialog" + NL
			+ "addonHandler.initTranslation()" + NL + NL + NL
			+ "class GlobalPlugin(globalPluginHandler.GlobalPlugin):" + NL
			+ TAB + 'scriptCategory = _("X")' + NL
		)
		r = CodeSandbox().validate_addon_execution(
			{"globalPlugins/T/__init__.py": codigo},
		)
		assert r.success, (r.stdout or r.stderr or r.error)[:300]

	def test_biblioteca_de_terceiros_inexistente_continua_falhando(self):
		"""O stub cobre so submodulo de pacote NVDA. Import de dependencia que
		nao existe e defeito real -- e o que esta verificacao existe para pegar."""
		codigo = (
			"import globalPluginHandler" + NL
			+ "import biblioteca_que_nao_existe" + NL + NL + NL
			+ "class GlobalPlugin(globalPluginHandler.GlobalPlugin): pass" + NL
		)
		r = CodeSandbox().validate_addon_execution(
			{"globalPlugins/T/__init__.py": codigo},
		)
		assert not r.success


class TestPlaceholderAceitaOContrato:
	"""
	Modulo VAZIO nao bastava: `from .configSpec import apply_config_spec` falha
	com "cannot import name" em vez de "no module named". Medido na rodada 7 --
	o cg_core foi reprovado assim mesmo com o placeholder ja no lugar.
	"""

	def test_import_de_nome_no_contrato_pendente_resolve(self):
		from nvdastudio.core.orchestrator import _MODULO_PENDENTE

		nucleo = (
			"import addonHandler" + NL
			+ "import globalPluginHandler" + NL
			+ "from .configSpec import apply_config_spec" + NL
			+ "from .servico import Servico" + NL
			+ "addonHandler.initTranslation()" + NL + NL + NL
			+ "class GlobalPlugin(globalPluginHandler.GlobalPlugin):" + NL
			+ TAB + 'scriptCategory = _("X")' + NL
		)
		r = CodeSandbox().validate_addon_execution({
			"globalPlugins/T/__init__.py": nucleo,
			"globalPlugins/T/configSpec.py": _MODULO_PENDENTE,
			"globalPlugins/T/servico.py": _MODULO_PENDENTE,
		})
		assert r.success, (r.stdout or r.stderr or r.error)[:300]

	def test_placeholder_e_python_valido(self):
		import ast

		from nvdastudio.core.orchestrator import _MODULO_PENDENTE

		ast.parse(_MODULO_PENDENTE)
