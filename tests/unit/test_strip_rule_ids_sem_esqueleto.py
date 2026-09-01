"""
Remover o rule ID nao pode deixar o esqueleto dele.

`_strip_rule_ids` e um reforco mecanico do Hard Boundary do User Advocate (ele
nunca deve citar NVDA-XXX -- isso e trabalho do Constraint Guardian, e um ID
citado por ele ja veio factualmente errado numa execucao real). Mas a versao
anterior apagava so o identificador e deixava a pontuacao que SO existia para
segura-lo:

    "o usuario precisa (NVDA-011) de foco"  ->  "o usuario precisa () de foco"
    "Restricao NVDA-016: escrita em disco"  ->  "Restricao : escrita em disco"

Medido na rodada E2E de 2026-09-01 (14h): o Critic reprovou a revisao de design
nos DOIS addons por causa disso -- "as restricoes do User Advocate aparecem com
os IDs vazios" e "a secao do User Advocate perdeu os identificadores das
regras". Custo: 116.158 e 158.478 tokens num addon, 129.028 e 125.059 no outro.

Um reforco mecanico que produzia texto quebrado, e o texto quebrado reprovava o
step que ele deveria proteger.
"""

import re

from nvdastudio.sub_agents.design_review_agent import (
	MODULE_VERSION,
	_MARCA_ID,
	_RULE_ID_RE,
	_strip_rule_ids,
)


def test_versao():
	assert MODULE_VERSION == "2.15.0"


def test_parentese_que_so_segurava_o_id_sai_junto():
	"""O caso literal do relatorio: "IDs vazios"."""
	saida = _strip_rule_ids("O usuario cego precisa (NVDA-011) de foco correto.")
	assert "()" not in saida
	assert saida == "O usuario cego precisa de foco correto."


def test_dois_pontos_orfao_nao_sobra():
	saida = _strip_rule_ids("Restricao NVDA-016: escrita em disco em secure mode.")
	assert not re.search(r"\s:", saida)
	assert "escrita em disco" in saida


def test_lista_de_ids_nao_deixa_conectivo_solto():
	saida = _strip_rule_ids("As regras NVDA-003 e WX-A11Y-013 se aplicam aqui.")
	assert "  " not in saida
	assert saida == "As regras se aplicam aqui."


def test_todos_os_prefixos_do_catalogo():
	saida = _strip_rule_ids("Ver ARCH-001, NVDA-UX-002 e WX-A11Y-013 sobre isso.")
	assert not _RULE_ID_RE.search(saida)
	assert "  " not in saida


def test_texto_sem_id_fica_intacto():
	original = "Sem citar regra nenhuma, so a experiencia do usuario cego."
	assert _strip_rule_ids(original) == original


def test_nenhum_id_sobrevive():
	"""O proposito original continua valendo: o Advocate nao cita IDs."""
	texto = "NVDA-001 no inicio, WX-A11Y-013 no meio, e ARCH-010 no fim."
	assert not _RULE_ID_RE.search(_strip_rule_ids(texto))


def test_marca_interna_nunca_vaza():
	"""A marca e detalhe de implementacao -- se aparecer, o usuario cego ouve
	um caractere de area de uso privado no meio da frase."""
	for texto in (
		"Isso (NVDA-011) aqui.",
		"NVDA-016: coisa.",
		"NVDA-001 e NVDA-002 juntos.",
	):
		assert _MARCA_ID not in _strip_rule_ids(texto)


def test_pontuacao_de_frase_e_preservada():
	"""Limpar demais transformaria o texto em outra coisa."""
	saida = _strip_rule_ids("Primeiro ponto. Segundo ponto, com virgula; e ponto e virgula.")
	assert saida == "Primeiro ponto. Segundo ponto, com virgula; e ponto e virgula."


def test_texto_multilinha_mantem_as_quebras():
	entrada = "Linha um (NVDA-001).\nLinha dois NVDA-002: detalhe.\nLinha tres."
	saida = _strip_rule_ids(entrada)
	assert len(saida.split("\n")) == 3
	assert not _RULE_ID_RE.search(saida)


def test_entrada_vazia():
	assert _strip_rule_ids("") == ""
