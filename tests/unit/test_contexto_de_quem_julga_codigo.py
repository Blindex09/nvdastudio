"""Regressao: quem JULGA codigo tem que RECEBER o codigo.

Medido na rodada AssistenteEscrita (2026-09-03). `__init__.py` tinha ~8.900
chars e chegava ao assembly comprimido em 3.000 pelo teto
_MAX_CONTEXT_CHARS_PER_STEP. O veredito reprovou 3 vezes (113.070 tokens)
alegando que o arquivo usava `api.getFocusObject()`, `config.conf` e
`log.exception` "sem importar esses modulos" -- os imports estao nas linhas 1
a 9 e tinham sido comidos pela compressao. Citou ainda `correct_text` e
`simplify_text`, nomes que nao existem em arquivo nenhum do addon.

O mesmo padrao no test_generation (141.577 tokens, 3 reprovacoes citando
`correct_grammar`) e no engineering_review, que reclamou por escrito dos
"snippets comprimidos". Somados: 310.336 tokens -- 32% da rodada -- gastos
julgando um codigo que ninguem mostrou.

Compressao semantica e boa para prosa e destrutiva para codigo. A diferenca
importa porque o leitor seguinte nao tem como saber que o que ele recebeu
nao e o arquivo.
"""

from nvdastudio.core.orchestrator import (
	_MAX_CONTEXT_CHARS_CODIGO,
	_MAX_CONTEXT_CHARS_PER_STEP,
	_STEPS_QUE_JULGAM_CODIGO,
	Orchestrator,
)
from nvdastudio.core.planner import (
	STEP_ASSEMBLY,
	STEP_CODE_GENERATION,
	STEP_DESIGN_REVIEW,
	STEP_ENGINEERING_REVIEW,
	STEP_TEST_GENERATION,
	ExecutionStep,
)


def _step(step_type: str, context_from=None) -> ExecutionStep:
	return ExecutionStep(
		step_id="alvo",
		step_type=step_type,
		description="Step de teste",
		model_id="kimi-k2.6",
		reasoning_params={},
		depends_on=[],
		context_from_steps=context_from or ["cg1"],
		expected_output="codigo",
		max_retries=3,
	)


# Reproduz a forma do arquivo real: imports no topo, corpo longo o bastante
# para estourar o teto de compressao.
_IMPORTS = (
	"import api\n"
	"import ui\n"
	"import config\n"
	"import globalVars\n"
	"import globalPluginHandler\n"
	"import addonHandler\n"
	"from logHandler import log\n"
	"from scriptHandler import script\n"
)


def _output_de_code_generation() -> str:
	corpo = "".join(
		f"\tdef _metodo_de_apoio_{i}(self):\n"
		f"\t\t# preenchimento para ultrapassar o teto de compressao\n"
		f"\t\treturn api.getFocusObject()\n"
		for i in range(90)
	)
	codigo = (
		_IMPORTS
		+ "\n\nclass GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
		+ "\tdef script_revisar(self, gesture):\n"
		+ "\t\tlog.exception(config.conf)\n"
		+ corpo
	)
	texto = (
		"Segue o arquivo principal.\n\n"
		"```python:globalPlugins/MeuAddon/__init__.py\n" + codigo + "```\n"
	)
	assert len(texto) > _MAX_CONTEXT_CHARS_PER_STEP * 2, len(texto)
	return texto


class TestQuemJulgaCodigoRecebeCodigo:

	def setup_method(self):
		self.orch = Orchestrator.__new__(Orchestrator)

	def test_imports_sobrevivem_ate_o_assembly(self):
		"""O veredito real acusou falta de import. Este teste falha se os
		imports nao chegarem literalmente ao step que julga."""
		ctx = self.orch._build_context(
			_step(STEP_ASSEMBLY), {"cg1": _output_de_code_generation()}
		)

		for linha in _IMPORTS.strip().splitlines():
			assert linha in ctx, f"import comido pela compressao: {linha!r}"

	def test_codigo_chega_verbatim_e_sem_marca_de_compressao(self):
		ctx = self.orch._build_context(
			_step(STEP_ASSEMBLY), {"cg1": _output_de_code_generation()}
		)

		assert "[COMPRIMIDO]" not in ctx
		assert "def script_revisar(self, gesture):" in ctx
		assert "globalPlugins/MeuAddon/__init__.py" in ctx

	def test_vale_para_os_quatro_steps_que_julgam(self):
		saida = {"cg1": _output_de_code_generation()}

		for tipo in (
			STEP_ASSEMBLY, STEP_ENGINEERING_REVIEW,
			STEP_DESIGN_REVIEW, STEP_TEST_GENERATION,
		):
			ctx = self.orch._build_context(_step(tipo), saida)
			assert "from logHandler import log" in ctx, tipo
			assert tipo in _STEPS_QUE_JULGAM_CODIGO


class TestNaoMudaOQueNaoPrecisavaMudar:
	"""A compressao continua valendo onde ela nunca fez mal."""

	def setup_method(self):
		self.orch = Orchestrator.__new__(Orchestrator)

	def test_step_que_nao_julga_codigo_segue_comprimindo(self):
		"""code_generation recebe contexto de apoio, nao julga codigo alheio.
		Mudar o caminho dele aqui seria efeito colateral nao pedido."""
		ctx = self.orch._build_context(
			_step(STEP_CODE_GENERATION), {"cg1": _output_de_code_generation()}
		)

		assert len(ctx) <= _MAX_CONTEXT_CHARS_PER_STEP * 2

	def test_output_sem_codigo_continua_comprimido(self):
		"""Pesquisa e prosa: nao ha codigo que um resumo possa deturpar, e o
		orcamento de contexto continua valendo."""
		prosa = "Resultado da pesquisa sobre a API. " * 400

		ctx = self.orch._build_context(_step(STEP_ASSEMBLY), {"cg1": prosa})

		assert len(ctx) < len(prosa)


class TestQuandoNaoCabe:
	"""Omitir arquivo inteiro e dizer que omitiu; nunca entregar meio arquivo
	com cara de arquivo."""

	def setup_method(self):
		self.orch = Orchestrator.__new__(Orchestrator)

	def _output_gigante(self, nome: str) -> str:
		enorme = "x = 1\n" * (_MAX_CONTEXT_CHARS_CODIGO // 6)
		return f"```python:{nome}\n{enorme}```\n"

	def test_arquivo_que_nao_cabe_e_anunciado_por_nome(self):
		ctx = self.orch._build_context(
			_step(STEP_ASSEMBLY, context_from=["cg1", "cg2"]),
			{
				"cg1": _output_de_code_generation(),
				"cg2": self._output_gigante("globalPlugins/MeuAddon/enorme.py"),
			},
		)

		assert "AVISO DE CONTEXTO" in ctx
		assert "globalPlugins/MeuAddon/enorme.py" in ctx
		assert "Nao afirme nada sobre o conteudo" in ctx
		# O que coube continua inteiro.
		assert "from logHandler import log" in ctx

	def test_contexto_respeita_o_teto(self):
		ctx = self.orch._build_context(
			_step(STEP_ASSEMBLY, context_from=["cg1", "cg2"]),
			{
				"cg1": _output_de_code_generation(),
				"cg2": self._output_gigante("enorme.py"),
			},
		)

		assert len(ctx) <= _MAX_CONTEXT_CHARS_CODIGO + 2000
