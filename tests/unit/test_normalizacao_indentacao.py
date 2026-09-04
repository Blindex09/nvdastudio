"""
NVDA-021 -- indentacao com espacos em vez de TAB -- reprovava steps inteiros de
code_generation. Medido nos relatorios E2E: 17 reprovacoes, 838 mil tokens.

E uma transformacao mecanica, sem nenhuma decisao semantica, consumindo
tentativas de um modelo que custam ~100 mil tokens cada. README Regra 7: o que
e deterministico o codigo resolve; a IA decide conteudo, nao formatacao.

A parte dificil nao e converter -- e nao estragar nada convertendo. Espacos a
esquerda dentro de docstring ou de literal multilinha sao CONTEUDO: viram texto
que o usuario cego vai ouvir. Por isso a conversao usa `tokenize` para saber
quais linhas sao codigo, e compara a AST antes e depois como rede final.
"""

import ast

from nvdastudio.builder.addon_builder import (
	MODULE_VERSION,
	extract_code_blocks,
	normalizar_indentacao,
)

TAB = "\t"


def _ast_igual(antes: str, depois: str) -> bool:
	return ast.dump(ast.parse(antes)) == ast.dump(ast.parse(depois))


def test_versao():
	assert MODULE_VERSION == "4.25.0"


def test_converte_indentacao_de_codigo():
	src = "class A:\n    def f(self):\n        return 1\n"
	out = normalizar_indentacao(src)
	assert out == "class A:\n\tdef f(self):\n\t\treturn 1\n"
	assert _ast_igual(src, out)


def test_preserva_espacos_dentro_de_docstring():
	"""O texto da docstring e conteudo. Trocar por tab muda o que o usuario le."""
	src = 'def f():\n    """Doc.\n\n        exemplo indentado\n    """\n    return 1\n'
	out = normalizar_indentacao(src)
	assert "        exemplo indentado" in out, "a docstring foi alterada"
	assert out.startswith("def f():\n\t")
	assert _ast_igual(src, out)


def test_preserva_string_multilinha_de_dados():
	src = 'X = """\n    linha um\n    linha dois\n"""\n\n\ndef f():\n    return X\n'
	out = normalizar_indentacao(src)
	assert "    linha um" in out
	assert "\treturn X" in out
	assert _ast_igual(src, out)


def test_arquivo_que_ja_usa_tab_fica_intacto():
	src = "class A:\n\tdef f(self):\n\t\treturn 1\n"
	assert normalizar_indentacao(src) == src


def test_arquivo_com_indentacao_misturada_nao_e_tocado():
	"""Mistura nao compila -- o erro de sintaxe e o sinal util. Mexer na
	indentacao de codigo quebrado so atrapalha o diagnostico."""
	src = "class A:\n\tdef f(self):\n        return 1\n"
	assert normalizar_indentacao(src) == src


def test_erro_de_sintaxe_nao_e_tocado():
	assert normalizar_indentacao("def f(:\n    pass\n") == "def f(:\n    pass\n"


def test_continuacao_dentro_de_parenteses():
	src = "x = foo(1,\n        2)\n"
	assert _ast_igual(src, normalizar_indentacao(src))


def test_indentacao_nao_multipla_de_quatro_preserva_o_resto():
	src = "def f():\n      return 1\n"
	out = normalizar_indentacao(src)
	assert out == "def f():\n\t  return 1\n"
	assert _ast_igual(src, out)


def test_arquivo_sem_indentacao_nenhuma():
	src = "X = 1\nY = 2\n"
	assert normalizar_indentacao(src) == src


def test_extracao_entrega_blocos_ja_normalizados():
	"""A costura: normalizar so vale se acontece no ponto por onde TODO bloco
	passa -- sandbox, lint, coerencia e gravacao consomem daqui."""
	texto = (
		"```python:globalPlugins/A/__init__.py\n"
		"class GlobalPlugin:\n"
		"    def terminate(self):\n"
		"        pass\n"
		"```\n"
	)
	bloco = extract_code_blocks(texto)[0]
	assert TAB + "def terminate" in bloco["code"]
	assert "    def terminate" not in bloco["code"]


def test_extracao_nao_mexe_em_bloco_que_nao_e_python():
	texto = "```ini:manifest.ini\nname = A\n    indentado = 1\n```\n"
	bloco = extract_code_blocks(texto)[0]
	assert "    indentado = 1" in bloco["code"]
