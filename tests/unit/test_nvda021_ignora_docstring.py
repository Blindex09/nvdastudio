"""Regressao: NVDA-021 acusava prosa dentro de docstring como indentacao.

Entrega real ResumoGemini de 2026-09-02 (primeiro addon COMPLEXO entregue):
o `__init__.py` saiu com "NVDA-021: linha 20: indentacao com espacos". A linha
20 e texto dentro do docstring de CONTRATO. Medido no arquivo entregue: as 21
linhas iniciadas por espaco estavam TODAS dentro de strings, a indentacao de
codigo era 100% TAB, e o arquivo compilava (ast.parse OK).

Portao reprovando codigo correto e a classe de defeito mais cara deste projeto.
"""
import os
import pytest
from nvdastudio.builder.addon_builder import (
	_check_indentation_style, _linhas_cobertas_por_string,
)

T = chr(9)
Q = chr(34) * 3


@pytest.fixture
def addon(tmp_path):
	def _criar(nome, conteudo):
		d = tmp_path / "globalPlugins" / "Pkg"
		d.mkdir(parents=True, exist_ok=True)
		(d / nome).write_text(conteudo, encoding="utf-8")
		return str(tmp_path)
	return _criar


class TestLinhasCobertasPorString:
	def test_docstring_multilinha_conta_todas_as_linhas(self):
		src = "def f():" + os.linesep.join(["", T + Q, "    prosa", T + Q, T + "pass"])
		assert 3 in _linhas_cobertas_por_string(src)

	def test_codigo_normal_nao_e_string(self):
		assert _linhas_cobertas_por_string("x = 1" + chr(10) + "y = 2") == set()

	def test_fail_open_em_sintaxe_quebrada(self):
		"""Erro de sintaxe e assunto de outro degrau, nao vira falso NVDA-021."""
		assert _linhas_cobertas_por_string("def f(:" + chr(10)) == set()


class TestCheckIndentationStyle:
	def test_espacos_dentro_de_docstring_nao_acusam(self, addon):
		"""O caso exato da entrega ResumoGemini."""
		src = chr(10).join([
			Q, "CONTRATO DOS MODULOS DE FEATURE:", "",
			"- globalPlugins.Pkg.configSpec",
			"    Funcao: apply_config_spec() -> None",
			"        apiKey = string(default='')",
			Q, "", "def carregar():", T + "return 1", "",
		])
		assert _check_indentation_style(addon("__init__.py", src)) == []

	def test_indentacao_de_codigo_com_espaco_continua_acusando(self, addon):
		"""O afrouxamento e SO para strings -- a regra real segue valendo."""
		src = "def carregar():" + chr(10) + "    return 1" + chr(10)
		problemas = _check_indentation_style(addon("__init__.py", src))
		assert len(problemas) == 1 and "NVDA-021" in problemas[0]

	def test_acusa_codigo_mesmo_havendo_docstring_antes(self, addon):
		"""Guarda contra 'fail-open demais': a presenca de docstring nao pode
		fazer a checagem desistir do arquivo inteiro."""
		src = chr(10).join([Q, "    prosa recuada", Q, "def f():", "    return 1", ""])
		problemas = _check_indentation_style(addon("__init__.py", src))
		assert len(problemas) == 1
		assert "linha 5" in problemas[0], problemas[0]

	def test_arquivo_com_sintaxe_quebrada_nao_explode(self, addon):
		_check_indentation_style(addon("__init__.py", "def f(:" + chr(10)))
