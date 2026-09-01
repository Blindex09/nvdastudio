"""
NVDA-003 valia so para o __init__.py principal, embora a regra sempre tenha
dito "modulo que usa gettext sem chamar addonHandler.initTranslation()".

Defeito real, medido em E2E (AssistenteLeituraGemini, 2026-08-30): o Critic
reprovou `cg_settings` com "settings_panel.py usa _() sem definir ou importar a
funcao de traducao, causando NameError". O step custou 412 mil tokens em 3
tentativas e nunca foi aprovado. A verificacao determinista que teria pego isso
na primeira leitura do arquivo existia -- so nao olhava esse arquivo.

E nao da para delegar ao ruff: `code_sandbox` declara `_`, `ngettext`,
`pgettext` e `npgettext` como builtins de proposito, senao TODO addon
gettext-correto seria reprovado com F821. Silenciado la, o defeito precisa ser
visto aqui.
"""

import os

from nvdastudio.builder.addon_builder import validate_addon_structure


_MANIFEST = "\n".join([
	"name = A", 'summary = "A"', 'description = "A"',
	"author = a <a@a.com>", "url = http://a", "version = 1.0.0",
	"minimumNVDAVersion = 2024.1", "lastTestedNVDAVersion = 2025.1",
])


def _monta_addon(raiz, arquivos: dict[str, str]) -> str:
	arquivos = {"manifest.ini": _MANIFEST, **arquivos}
	for caminho, conteudo in arquivos.items():
		destino = os.path.join(str(raiz), caminho)
		os.makedirs(os.path.dirname(destino) or str(raiz), exist_ok=True)
		with open(destino, "w", encoding="utf-8") as fh:
			fh.write(conteudo)
	return str(raiz)


_INIT_OK = (
	"import addonHandler\n"
	"import globalPluginHandler\n"
	"addonHandler.initTranslation()\n"
	"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
	"\tdef terminate(self):\n\t\tpass\n"
)


def _nvda003(problemas: list[str], arquivo: str) -> bool:
	return any(p.startswith(f"NVDA-003: {arquivo}") for p in problemas)


def test_painel_com_gettext_sem_init_translation_e_apontado(tmp_path):
	"""O caso literal do relatorio E2E."""
	pasta = _monta_addon(tmp_path, {
		"globalPlugins/A/__init__.py": _INIT_OK,
		"globalPlugins/A/settings_panel.py": (
			"import wx\n"
			"class Painel(wx.Panel):\n"
			"\tdef makeSettings(self, sizer):\n"
			"\t\tself.label = _(\"Chave de API\")\n"
		),
	})
	assert _nvda003(validate_addon_structure(pasta), "settings_panel.py")


def test_painel_que_inicializa_traducao_passa(tmp_path):
	pasta = _monta_addon(tmp_path, {
		"globalPlugins/A/__init__.py": _INIT_OK,
		"globalPlugins/A/settings_panel.py": (
			"import addonHandler\n"
			"addonHandler.initTranslation()\n"
			"class Painel:\n"
			"\tdef makeSettings(self):\n"
			"\t\treturn _(\"Chave de API\")\n"
		),
	})
	assert not _nvda003(validate_addon_structure(pasta), "settings_panel.py")


def test_modulo_sem_gettext_nao_e_cobrado(tmp_path):
	"""Um cliente HTTP puro nao traduz nada -- exigir initTranslation() ali seria
	falso positivo, e e exatamente o que o prompt do Critic manda nao fazer."""
	pasta = _monta_addon(tmp_path, {
		"globalPlugins/A/__init__.py": _INIT_OK,
		"globalPlugins/A/cliente.py": (
			"import json\n"
			"def buscar(url):\n"
			"\tfor _ in range(3):\n"
			"\t\tpass\n"
			"\treturn json.loads(url)\n"
		),
	})
	assert not _nvda003(validate_addon_structure(pasta), "cliente.py")


def test_gettext_importado_direto_passa(tmp_path):
	"""initTranslation() e o caminho do NVDA, mas importar gettext e valido --
	o defeito e o NameError, nao a falta de uma chamada especifica."""
	pasta = _monta_addon(tmp_path, {
		"globalPlugins/A/__init__.py": _INIT_OK,
		"globalPlugins/A/util.py": (
			"from gettext import gettext as _\n"
			"MSG = _(\"oi\")\n"
		),
	})
	assert not _nvda003(validate_addon_structure(pasta), "util.py")


def test_underscore_como_descartavel_nao_dispara(tmp_path):
	pasta = _monta_addon(tmp_path, {
		"globalPlugins/A/__init__.py": _INIT_OK,
		"globalPlugins/A/loop.py": "for _ in range(3):\n\tpass\n",
	})
	assert not _nvda003(validate_addon_structure(pasta), "loop.py")


def test_identificador_terminado_em_underscore_nao_dispara(tmp_path):
	"""`buffer_(x)` nao e gettext -- a borda a esquerda do regex existe por isso."""
	pasta = _monta_addon(tmp_path, {
		"globalPlugins/A/__init__.py": _INIT_OK,
		"globalPlugins/A/buf.py": "def buffer_(x):\n\treturn x\n\nbuffer_(1)\n",
	})
	assert not _nvda003(validate_addon_structure(pasta), "buf.py")


def test_init_principal_continua_com_a_regra_antiga(tmp_path):
	"""O __init__.py principal e cobrado por AUSENCIA de initTranslation()
	mesmo sem usar gettext -- e o ponto de entrada, precisa inicializar."""
	pasta = _monta_addon(tmp_path, {
		"globalPlugins/A/__init__.py": (
			"import globalPluginHandler\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef terminate(self):\n\t\tpass\n"
		),
	})
	assert _nvda003(validate_addon_structure(pasta), "__init__.py")


def test_subpacote_com_gettext_e_apontado(tmp_path):
	"""Subpacote legitimo nao pode voltar a ser falso positivo de
	ESTRUTURA-005/NVDA-004, mas se ELE usa gettext o NameError e real."""
	pasta = _monta_addon(tmp_path, {
		"globalPlugins/A/__init__.py": _INIT_OK,
		"globalPlugins/A/historico/__init__.py": "MSG = _(\"historico\")\n",
	})
	problemas = validate_addon_structure(pasta)
	assert _nvda003(problemas, "__init__.py")
	assert not any(
		p.startswith("ESTRUTURA-005") or p.startswith("NVDA-004")
		for p in problemas
	), "subpacote nao pode voltar a ser cobrado por GlobalPlugin/terminate"


def test_mencao_em_comentario_ou_docstring_nao_dispara(tmp_path):
	"""Varredura textual acusou 3 arquivos do proprio NVDAStudio, todos falsos:
	`_()` escrito dentro de comentario "# Translators:", docstring e string de
	prompt. Codigo gerado para o NVDA e cheio dos tres. Por isso a deteccao e
	por AST, nao por texto."""
	pasta = _monta_addon(tmp_path, {
		"globalPlugins/A/__init__.py": _INIT_OK,
		"globalPlugins/A/regras.py": (
			'"""Regra NVDA-019: todo _() precisa de # Translators: antes."""\n'
			"# Exemplo de chamada: _(\"texto\")\n"
			"REGRA = 'use _() para traduzir'\n"
			"def checar(x):\n"
			"\treturn x\n"
		),
	})
	assert not _nvda003(validate_addon_structure(pasta), "regras.py")


def test_arquivo_com_erro_de_sintaxe_nao_vira_nvda003(tmp_path):
	"""Quem reporta sintaxe quebrada e a validacao de sintaxe. Um NVDA-003 em
	cima de um arquivo que nem compila so confunde o diagnostico."""
	pasta = _monta_addon(tmp_path, {
		"globalPlugins/A/__init__.py": _INIT_OK,
		"globalPlugins/A/quebrado.py": "def f(:\n\treturn _(\"x\")\n",
	})
	assert not _nvda003(validate_addon_structure(pasta), "quebrado.py")


def test_gettext_aninhado_em_outra_chamada_dispara(tmp_path):
	"""`ui.message(_("x"))` e o padrao mais comum em addon NVDA."""
	pasta = _monta_addon(tmp_path, {
		"globalPlugins/A/__init__.py": _INIT_OK,
		"globalPlugins/A/aviso.py": (
			"import ui\n"
			"def avisar():\n"
			"\tui.message(_(\"pronto\"))\n"
		),
	})
	assert _nvda003(validate_addon_structure(pasta), "aviso.py")


class TestPortaoPorStep:
	"""A deteccao existia no empacotamento (validate_addon_structure) e nunca no
	step de code_generation -- ou seja, o defeito era descoberto quando ja nao
	dava para corrigir barato. Medido: cg_settings reprovado 3 vezes por isso,
	412 mil tokens, nunca aprovado.

	Estes testes fixam os dois lados da costura: a funcao e publica e o
	orchestrator a consome no gate por step."""

	def test_funcao_e_publica_e_consumida_pelo_orchestrator(self):
		import inspect

		from nvdastudio.core import orchestrator

		assert hasattr(orchestrator, "chama_gettext"), (
			"o gate por step precisa da MESMA funcao usada no empacotamento -- "
			"reimplementar aqui duplicaria a regra (README Regra 5)"
		)
		src = inspect.getsource(orchestrator.Orchestrator)
		assert "chama_gettext(" in src, "gate por step nao chama a verificacao"
		assert "initTranslation" in src, (
			"a instrucao de retry precisa dizer o que fazer, nao so que falhou"
		)

	def test_instrucao_de_retry_e_acionavel(self):
		"""Um issue que so nomeia a regra faz o modelo adivinhar; o que diz o
		arquivo e a correcao faz ele corrigir na tentativa seguinte."""
		import inspect

		from nvdastudio.core import orchestrator

		src = inspect.getsource(orchestrator.Orchestrator)
		assert "gettext_sem_init" in src
		assert "NameError" in src, "a instrucao deve dizer a consequencia real"
