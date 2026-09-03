"""
`_` como variavel de descarte, no mesmo escopo que traduz, quebra o addon.

Em addon NVDA, `_` e a funcao de traducao. Usar `_` tambem como descarte --
`_, ext = os.path.splitext(caminho)` -- torna o nome LOCAL a funcao, e toda
chamada `_("texto")` anterior naquela funcao passa a referenciar variavel ainda
nao atribuida: UnboundLocalError na hora em que o usuario cego abre o painel.

Medido na rodada 8: QUATRO reprovacoes de "F823 Local variable `_` referenced
before assignment" em settings_panel.py, nos dois addons, a ~270 mil tokens
cada. O ruff esta certo em apontar -- e defeito real -- mas a correcao e
mecanica.
"""

import ast

from nvdastudio.builder.addon_builder import (
	MODULE_VERSION,
	extract_code_blocks,
	renomear_descarte_que_sombreia_traducao,
)

NL = chr(10)
TAB = chr(9)


def test_versao():
	assert MODULE_VERSION == "4.23.0"


def test_descarte_em_funcao_que_traduz_e_renomeado():
	src = (
		"import os" + NL + NL
		+ "def makeSettings(self, sizer):" + NL
		+ TAB + 'rotulo = _("Chave de API")' + NL
		+ TAB + '_, ext = os.path.splitext("a.txt")' + NL
		+ TAB + "return rotulo, ext" + NL
	)
	out = renomear_descarte_que_sombreia_traducao(src)
	assert "_descartado, ext" in out
	assert '_("Chave de API")' in out, "a chamada de traducao nao pode ser tocada"
	ast.parse(out)


def test_funcao_que_nao_traduz_fica_intacta():
	"""Renomear descarte onde nao ha traducao seria mexer em codigo correto."""
	src = (
		"import os" + NL + NL
		+ "def f(p):" + NL
		+ TAB + "_, ext = os.path.splitext(p)" + NL
		+ TAB + "return ext" + NL
	)
	assert renomear_descarte_que_sombreia_traducao(src) == src


def test_descarte_em_for_tambem_conta():
	src = (
		"def f(itens):" + NL
		+ TAB + 'titulo = _("Lista")' + NL
		+ TAB + "for _, valor in itens:" + NL
		+ TAB + TAB + "print(valor)" + NL
		+ TAB + "return titulo" + NL
	)
	out = renomear_descarte_que_sombreia_traducao(src)
	assert "for _descartado, valor" in out
	ast.parse(out)


def test_chamada_de_traducao_nunca_e_renomeada():
	"""`_(` e chamada, nao atribuicao -- confundir as duas apagaria a traducao."""
	src = (
		"def f(p):" + NL
		+ TAB + 'a = _("um")' + NL
		+ TAB + "_ = p" + NL
		+ TAB + 'b = _("dois")' + NL
		+ TAB + "return a, b" + NL
	)
	out = renomear_descarte_que_sombreia_traducao(src)
	assert out.count('_("um")') == 1
	assert out.count('_("dois")') == 1
	assert "_descartado = p" in out


def test_arquivo_sem_gettext_nao_e_tocado():
	src = "def f(p):" + NL + TAB + "_, b = p" + NL + TAB + "return b" + NL
	assert renomear_descarte_que_sombreia_traducao(src) == src


def test_sintaxe_invalida_nao_e_tocada():
	src = "def f(:" + NL + TAB + '_ = _("x")' + NL
	assert renomear_descarte_que_sombreia_traducao(src) == src


def test_extracao_aplica_a_correcao():
	"""A costura: so vale no ponto por onde todo bloco passa."""
	texto = (
		chr(96) * 3 + "python:globalPlugins/A/settings_panel.py" + NL
		+ "import os" + NL
		+ "def makeSettings(self, sizer):" + NL
		+ '    self.label = _("Chave")' + NL
		+ '    _, ext = os.path.splitext("a.b")' + NL
		+ "    return ext" + NL
		+ chr(96) * 3 + NL
	)
	bloco = extract_code_blocks(texto)[0]
	assert "_descartado, ext" in bloco["code"]
	ast.parse(bloco["code"])
