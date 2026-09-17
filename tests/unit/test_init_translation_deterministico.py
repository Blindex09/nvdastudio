"""
Modulo de addon que chama `_()` sem `addonHandler.initTranslation()` levanta
NameError na primeira string traduzida -- a inicializacao injeta o nome nos
globals do modulo que a CHAMA, entao vale so para aquele arquivo.

Medido nos 391 relatorios E2E: 12 steps de code_generation reprovados por isso,
3.285.409 tokens. E o maior desperdicio identificado no corpus -- maior que a
indentacao (838 mil) -- para uma correcao de DUAS linhas, sem nenhuma decisao
semantica.

Na rodada de 13:20 o defeito apareceu duas vezes no mesmo addon: `cg_settings`
reprovado 3 vezes (266.557 tokens) e `cg_resumo` com "usa a funcao de traducao
`_()` varias vezes, mas nao importa". A verificacao deterministica ja apontava
o erro com precisao; o modelo simplesmente nao corrigia. README Regra 7: o que
e deterministico o codigo resolve.
"""

import ast

from nvdastudio.builder.addon_builder import (
	MODULE_VERSION,
	extract_code_blocks,
	garantir_init_translation,
)

NL = chr(10)


def _compila(code: str) -> bool:
	try:
		ast.parse(code)
		return True
	except SyntaxError:
		return False


def test_versao():
	assert MODULE_VERSION == "4.28.0"


def test_modulo_com_gettext_recebe_inicializacao():
	src = "import wx" + NL + 'X = _("Chave de API")' + NL
	out = garantir_init_translation(src)
	assert "addonHandler.initTranslation()" in out
	assert "import addonHandler" in out
	assert _compila(out)


def test_chamada_vem_depois_do_import():
	"""Inserir a chamada antes do import so mudaria a linha do NameError."""
	for src in (
		"import wx" + NL + 'X = _("a")' + NL,
		"import addonHandler" + NL + "import wx" + NL + 'X = _("a")' + NL,
		"import wx" + NL + "import addonHandler" + NL + 'X = _("a")' + NL,
	):
		out = garantir_init_translation(src)
		assert out.index("import addonHandler") < out.index("addonHandler.initTranslation()")
		assert _compila(out)


def test_import_existente_nao_e_duplicado():
	src = "import addonHandler" + NL + 'X = _("a")' + NL
	out = garantir_init_translation(src)
	assert out.count("import addonHandler") == 1


def test_modulo_que_ja_inicializa_fica_intacto():
	src = "import addonHandler" + NL + "addonHandler.initTranslation()" + NL + 'X = _("a")' + NL
	assert garantir_init_translation(src) == src


def test_modulo_sem_gettext_nao_e_tocado():
	"""Um cliente HTTP puro nao traduz nada -- acrescentar a chamada seria
	ruido, e e exatamente o falso positivo que o prompt do Critic proibe."""
	src = "import json" + NL + "def f(x):" + NL + "\tfor _ in range(3):" + NL + "\t\tpass" + NL + "\treturn x" + NL
	assert garantir_init_translation(src) == src


def test_gettext_importado_direto_nao_e_tocado():
	src = "from gettext import gettext as _" + NL + 'X = _("a")' + NL
	assert garantir_init_translation(src) == src


def test_docstring_do_modulo_continua_em_primeiro():
	"""Inserir antes da docstring transformaria a documentacao do modulo numa
	string solta no meio do arquivo."""
	src = '"""Painel de configuracoes."""' + NL + "import wx" + NL + 'X = _("a")' + NL
	out = garantir_init_translation(src)
	assert out.startswith('"""Painel de configuracoes."""')
	assert ast.get_docstring(ast.parse(out)) == "Painel de configuracoes."


def test_from_future_continua_antes_de_tudo():
	"""A linguagem EXIGE `from __future__` como primeira instrucao -- inserir
	antes dele nao compila."""
	src = ("from __future__ import annotations" + NL + "import wx" + NL + 'X = _("a")' + NL)
	out = garantir_init_translation(src)
	assert _compila(out)
	assert out.index("from __future__") < out.index("import addonHandler")


def test_arquivo_com_erro_de_sintaxe_nao_e_tocado():
	src = "def f(:" + NL + '\treturn _("a")' + NL
	assert garantir_init_translation(src) == src


def test_ngettext_tambem_conta():
	src = "import wx" + NL + 'X = ngettext("a", "b", 2)' + NL
	assert "initTranslation" in garantir_init_translation(src)


def test_extracao_entrega_blocos_ja_corrigidos():
	"""A costura: so vale se acontece no ponto por onde TODO bloco passa antes
	do sandbox, do lint, da coerencia e da gravacao."""
	texto = (
		"```python:globalPlugins/A/settings_panel.py" + NL
		+ "import wx" + NL
		+ "class Painel(wx.Panel):" + NL
		+ "    def makeSettings(self, sizer):" + NL
		+ '        self.label = _("Chave de API")' + NL
		+ "```" + NL
	)
	bloco = extract_code_blocks(texto)[0]
	assert "addonHandler.initTranslation()" in bloco["code"]
	assert _compila(bloco["code"])
	# e a normalizacao de indentacao continua valendo no mesmo bloco
	assert chr(9) + "def makeSettings" in bloco["code"]


def test_import_dentro_de_funcao_nao_serve_de_ancora():
	"""`import addonHandler` no corpo de uma funcao nao deixa o nome no escopo
	global, e ancorar a chamada nele colocaria codigo de modulo dentro da
	funcao."""
	src = (
		"import wx" + NL
		+ "def f():" + NL
		+ chr(9) + "import addonHandler" + NL
		+ chr(9) + 'return _("a")' + NL
	)
	out = garantir_init_translation(src)
	assert _compila(out)
	linhas = out.split(NL)
	assert linhas[0] == "import addonHandler"
	assert linhas[1] == "addonHandler.initTranslation()"
	arvore = ast.parse(out)
	assert any(
		isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
		for n in arvore.body
	), "a chamada precisa ficar no nivel do modulo"
