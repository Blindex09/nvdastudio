"""
Analise estatica (ruff + mypy) sobre o codigo GERADO -- code_sandbox 1.5.0.

Lacuna real fechada nesta sessao: o CI do NVDAStudio sempre exigiu `ruff
check` e `mypy` limpos no codigo do PROPRIO projeto, mas o addon entregue ao
usuario nunca passava por nenhum dos dois -- a verificacao parava em AST,
import/instanciacao e pytest. Um `F821 undefined name` ou um `B006` default
mutavel passavam batido por todos os degraus existentes.

Os testes abaixo travam as tres decisoes de design que nao sao obvias:
  1. gettext (`_`) NAO pode virar F821 -- e injetado em runtime pelo
     addonHandler.initTranslation(), entao todo addon corretamente
     traduzido (NVDA-019) levaria erro em cada string.
  2. regra de ESTILO nao entra no select -- o NVDA indenta com TAB e o
     pipeline entraria em retry infinito por algo que nao e defeito.
  3. ferramenta ausente e FAIL-OPEN -- o Python embutido do NVDA nao tem
     ruff nem mypy, e quebrar o addon de quem nao tem dev tooling seria
     pior que nao lintar.
"""

from unittest.mock import MagicMock, patch

from nvdastudio.builder.code_sandbox import MODULE_VERSION, CodeSandbox

assert MODULE_VERSION == "1.10.0"


_ADDON_LIMPO = (
	"import globalPluginHandler\n"
	"import addonHandler\n\n"
	"addonHandler.initTranslation()\n\n\n"
	"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
	"\tdef terminate(self):\n"
	"\t\t# Translators: mensagem de saida\n"
	"\t\tself.msg = _(\"tchau\")\n"
	"\t\tsuper().terminate()\n"
)


class TestLintDetectaDefeitoReal:
	def test_nome_indefinido_reprova(self):
		code = "def f():\n\treturn variavel_que_nao_existe\n"
		result = CodeSandbox().lint_check({"globalPlugins/X/__init__.py": code})
		assert result.success is False
		# error vazio == o ruff rodou de verdade e achou defeito. Se estivesse
		# preenchido seria infraestrutura (ferramenta ausente/timeout).
		assert result.error == ""
		assert "F821" in result.stdout

	def test_default_mutavel_reprova(self):
		code = "def f(acumulador=[]):\n\tacumulador.append(1)\n\treturn acumulador\n"
		result = CodeSandbox().lint_check({"globalPlugins/X/__init__.py": code})
		assert result.success is False
		assert "B006" in result.stdout

	def test_import_morto_reprova(self):
		code = "import os\n\n\ndef f():\n\treturn 1\n"
		result = CodeSandbox().lint_check({"globalPlugins/X/__init__.py": code})
		assert result.success is False
		assert "F401" in result.stdout


class TestLintNaoReprovaCodigoCorreto:
	def test_addon_nvda_idiomatico_passa(self):
		result = CodeSandbox().lint_check({"globalPlugins/X/__init__.py": _ADDON_LIMPO})
		assert result.success is True, result.stdout

	def test_gettext_nao_vira_undefined_name(self):
		"""REGRESSAO: `_` vem de addonHandler.initTranslation() em runtime.
		Sem `builtins` na config, TODO addon traduzido levaria F821 -- o
		lint puniria exatamente o addon que segue a NVDA-019."""
		code = (
			"# Translators: titulo\n"
			"TITULO = _(\"Meu Addon\")\n"
			"# Translators: plural\n"
			"N = ngettext(\"1 item\", \"%d itens\", 3)\n"
		)
		result = CodeSandbox().lint_check({"globalPlugins/X/__init__.py": code})
		assert result.success is True, result.stdout

	def test_indentacao_com_tab_nao_reprova(self):
		"""REGRESSAO: TAB e o estilo oficial do NVDA (README Regra 20). Se o
		select incluisse W191/E101, todo addon correto seria reprovado."""
		code = "def f():\n\tif True:\n\t\treturn 1\n\treturn 0\n"
		result = CodeSandbox().lint_check({"globalPlugins/X/__init__.py": code})
		assert result.success is True, result.stdout

	def test_linha_longa_nao_reprova(self):
		"""E501 fica fora do select -- linha longa nao e defeito."""
		code = "VALOR = " + repr("x" * 300) + "\n"
		result = CodeSandbox().lint_check({"globalPlugins/X/__init__.py": code})
		assert result.success is True, result.stdout


class TestFailOpenDeInfraestrutura:
	"""Ausencia de ferramenta e falha de INFRAESTRUTURA, nunca defeito do
	addon. Sempre success=True + `error` preenchido, para o orchestrator
	distinguir "limpo" de "nao verificado" (ele so bloqueia quando
	success=False E error vazio)."""

	def test_ruff_ausente_nao_reprova(self):
		fake = MagicMock(returncode=1, stdout="No module named ruff", stderr="")
		with patch("nvdastudio.builder.code_sandbox.subprocess.run", return_value=fake):
			result = CodeSandbox().lint_check({"globalPlugins/X/__init__.py": "x = 1\n"})
		assert result.success is True
		assert result.error == "ruff_indisponivel"

	def test_mypy_ausente_nao_reprova(self):
		fake = MagicMock(returncode=1, stdout="No module named mypy", stderr="")
		with patch("nvdastudio.builder.code_sandbox.subprocess.run", return_value=fake):
			result = CodeSandbox().typecheck({"globalPlugins/X/__init__.py": "x = 1\n"})
		assert result.success is True
		assert result.error == "mypy_indisponivel"

	def test_timeout_da_ferramenta_nao_reprova(self):
		import subprocess

		with patch(
			"nvdastudio.builder.code_sandbox.subprocess.run",
			side_effect=subprocess.TimeoutExpired(cmd="ruff", timeout=20),
		):
			result = CodeSandbox().lint_check({"globalPlugins/X/__init__.py": "x = 1\n"})
		assert result.success is True
		assert result.timed_out is True
		assert result.error != ""

	def test_python_ausente_no_path_nao_reprova(self):
		with patch(
			"nvdastudio.builder.code_sandbox.subprocess.run", side_effect=FileNotFoundError
		):
			result = CodeSandbox().lint_check({"globalPlugins/X/__init__.py": "x = 1\n"})
		assert result.success is True
		assert result.error == "ruff_indisponivel"

	def test_sem_arquivo_python_nao_reprova(self):
		result = CodeSandbox().lint_check({"manifest.ini": "name = X\n"})
		assert result.success is True
		assert result.error == "sem arquivo Python"


class TestContratoComOOrchestrator:
	"""COSTURA: o orchestrator so BLOQUEIA um step quando
	`not success and not error` -- ou seja, ele trata `error` preenchido como
	"nao verificado" e `error` vazio como "verificado e reprovado".

	Todo o fail-open depende dessa invariante: se algum caminho de
	infraestrutura devolvesse success=False com `error` vazio, o orchestrator
	leria como defeito do addon e entraria em retry por algo que o addon nao
	causou. Este teste trava os dois lados do contrato num lugar so."""

	def _infra_falha_sempre_preenche_error(self, result):
		assert result.success is True, "infra nunca reprova o addon"
		assert result.error != "", "infra sempre identifica a si mesma em `error`"

	def test_todos_os_caminhos_de_infra_respeitam_a_invariante(self):
		import subprocess

		sb = CodeSandbox()
		arquivos = {"globalPlugins/X/__init__.py": "x = 1\n"}

		fake_ausente = MagicMock(returncode=1, stdout="No module named ruff", stderr="")
		with patch("nvdastudio.builder.code_sandbox.subprocess.run", return_value=fake_ausente):
			self._infra_falha_sempre_preenche_error(sb.lint_check(arquivos))

		with patch(
			"nvdastudio.builder.code_sandbox.subprocess.run",
			side_effect=subprocess.TimeoutExpired(cmd="ruff", timeout=20),
		):
			self._infra_falha_sempre_preenche_error(sb.lint_check(arquivos))

		with patch("nvdastudio.builder.code_sandbox.subprocess.run", side_effect=FileNotFoundError):
			self._infra_falha_sempre_preenche_error(sb.lint_check(arquivos))

		with patch("nvdastudio.builder.code_sandbox.subprocess.run", side_effect=OSError("disco cheio")):
			self._infra_falha_sempre_preenche_error(sb.lint_check(arquivos))

		self._infra_falha_sempre_preenche_error(sb.lint_check({"manifest.ini": "name = X"}))

	def test_defeito_real_e_a_unica_forma_de_reprovar(self):
		"""O espelho da invariante: quando o ruff realmente acha defeito,
		`error` fica VAZIO -- e so por isso o orchestrator bloqueia."""
		result = CodeSandbox().lint_check(
			{"globalPlugins/X/__init__.py": "def f():\n\treturn indefinido\n"}
		)
		assert result.success is False
		assert result.error == ""
		assert result.stdout.strip() != "", "precisa entregar o achado pro prompt do retry"


class TestIsolamentoDeCaminho:
	def test_path_traversal_e_descartado(self):
		"""_write_files() ja rejeita `..`; a analise estatica herda isso por
		usar o mesmo helper -- nenhum arquivo escapa do tmpdir."""
		result = CodeSandbox().lint_check({"../fora.py": "import os\n"})
		# Nenhum arquivo valido sobra dentro do tmpdir, entao o ruff nao
		# encontra defeito -- o que importa e nao ter escrito fora.
		assert result.success is True


class TestTypecheckIgnoraImportsDoNVDA:
	def test_import_de_modulo_do_nvda_nao_vira_erro(self):
		"""REGRESSAO: sem --ignore-missing-imports, 100% do resultado seria
		import-not-found -- globalPluginHandler/addonHandler/ui/wx so existem
		dentro do processo do NVDA (mesmo motivo das secoes do mypy.ini)."""
		result = CodeSandbox().typecheck({"globalPlugins/X/__init__.py": _ADDON_LIMPO})
		assert result.success is True, result.stdout
		assert "import-not-found" not in result.stdout
