"""
Uma secao vazia reprovava a revisao inteira, e ninguem conferia.

Medido na rodada 7 (2026-09-01 21:32): o estagio Challenger devolveu ZERO
caracteres enquanto o Guardian entregou 10.896 e o Advocate 4.517. O documento
foi montado com a secao vazia e submetido assim mesmo -- o Critic reprovou com
"a secao Challenger esta vazia, sem riscos ou suposicoes identificados", e os
115.687 tokens da revisao inteira foram perdidos num resultado que ja nascia
reprovado.

Secao vazia e condicao de falha CONHECIDA e detectavel de graca: nao ha revisao
de design possivel sem riscos identificados. Repetir so o estagio que falhou
custa uma fracao de perder a revisao toda.

`_extract_final_tool_result` ja cai para `resp.content` quando o modelo nao
chama a ferramenta de entrega -- vazio aqui significa que o estagio realmente
nao produziu nada, nao falta de extracao.
"""

import inspect

from nvdastudio.sub_agents import design_review_agent
from nvdastudio.sub_agents.design_review_agent import (
	MODULE_VERSION,
	_estagio_com_reforco,
)


def test_versao():
	assert MODULE_VERSION == "2.16.0"


def _contador(respostas):
	"""Executor que devolve `respostas` em ordem e conta as chamadas."""
	estado = {"n": 0}

	def executar():
		i = estado["n"]
		estado["n"] += 1
		return respostas[min(i, len(respostas) - 1)]

	return executar, estado


def test_estagio_normal_roda_uma_vez_so(monkeypatch):
	monkeypatch.setattr(design_review_agent, "get_last_tokens", lambda: 10)
	executar, estado = _contador(["analise substantiva de riscos"])
	saida, tokens = _estagio_com_reforco("Challenger", executar)
	assert saida == "analise substantiva de riscos"
	assert estado["n"] == 1
	assert tokens == 10


def test_secao_vazia_e_repetida(monkeypatch):
	monkeypatch.setattr(design_review_agent, "get_last_tokens", lambda: 10)
	executar, estado = _contador(["", "riscos identificados na segunda tentativa"])
	saida, _ = _estagio_com_reforco("Challenger", executar)
	assert estado["n"] == 2
	assert "segunda tentativa" in saida


def test_so_espaco_em_branco_conta_como_vazio(monkeypatch):
	monkeypatch.setattr(design_review_agent, "get_last_tokens", lambda: 5)
	executar, estado = _contador(["   " + chr(10) + chr(9), "conteudo real"])
	saida, _ = _estagio_com_reforco("Guardian", executar)
	assert estado["n"] == 2
	assert saida == "conteudo real"


def test_tokens_das_duas_tentativas_sao_somados(monkeypatch):
	"""Cobrar so a ultima tentativa esconderia o custo real do reforco."""
	monkeypatch.setattr(design_review_agent, "get_last_tokens", lambda: 40)
	executar, _ = _contador(["", "conteudo"])
	_, tokens = _estagio_com_reforco("Advocate", executar)
	assert tokens == 80


def test_vazio_duas_vezes_declara_a_lacuna(monkeypatch):
	"""Fingir que a secao existe e pior que admitir a falta: quem le a revisao
	nao pode confundir 'sem achados' com 'nao analisado'."""
	monkeypatch.setattr(design_review_agent, "get_last_tokens", lambda: 1)
	executar, estado = _contador(["", ""])
	saida, _ = _estagio_com_reforco("Challenger", executar)
	assert estado["n"] == 2
	assert "[SECAO INDISPONIVEL]" in saida
	assert "NAO COBERTA" in saida
	assert "Challenger" in saida


def test_nunca_repete_mais_de_uma_vez(monkeypatch):
	"""O estagio mais caro da revisao nao pode virar laco."""
	monkeypatch.setattr(design_review_agent, "get_last_tokens", lambda: 1)
	executar, estado = _contador(["", "", ""])
	_estagio_com_reforco("Challenger", executar)
	assert estado["n"] == 2


def test_os_tres_estagios_passam_pelo_reforco():
	"""A costura: nao adianta o reforco existir se um estagio nao usa."""
	src = inspect.getsource(design_review_agent.run)
	assert src.count("_estagio_com_reforco(") == 3
	for nome in ('"Challenger"', '"Constraint Guardian"', '"User Advocate"'):
		assert nome in src
