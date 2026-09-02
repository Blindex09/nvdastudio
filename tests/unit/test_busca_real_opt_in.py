"""
O guarda anti-rede era largo demais e invalidou seis rodadas de medicao.

`web_researcher.run()` pulava a busca real sempre que "pytest" estivesse em
sys.modules. Isso e certo para a suite unitaria -- teste nao pode depender de
rede -- mas pegava tambem os testes E2E, que existem justamente para exercitar o
pipeline de verdade e carregam chaves de API reais.

Medido na rodada 5: 43 buscas iniciadas, 3 sinteses concluidas. As outras 40
cairam no fallback por conhecimento do modelo.

Consequencia: em SEIS rodadas E2E, todo step de web_research respondeu so com o
conhecimento de treino, e foi reprovado sempre pelo mesmo motivo -- "usa o
pacote legado google-generativeai em vez do google-genai". A conclusao obvia
("a pesquisa do projeto e ruim") estava medindo o arnes de teste, nao o produto.

Agora e opt-in explicito. O padrao seguro nao muda: sem a variavel, teste nenhum
vai a rede.
"""

import os
from unittest.mock import MagicMock, patch

from nvdastudio.sub_agents import web_researcher
from nvdastudio.sub_agents.web_researcher import _ENV_BUSCA_REAL


def _busca_falsa(registro):
	"""Substituta que se PASSA pela busca real.

	`run()` trata uma funcao de outro modulo como "mock injetado pelo teste" e
	deixa passar de proposito -- e a valvula que permite testar a sintese sem
	rede. Para exercitar o GUARDA e preciso que a substituta pareca a original,
	senao o teste mede a valvula em vez do guarda.
	"""
	def _busca(*args, **kwargs):
		registro.append(1)
		return "resultado de busca"

	_busca.__module__ = web_researcher.__name__
	return _busca


def _resposta(texto="conteudo de pesquisa suficientemente longo " * 8):
	r = MagicMock()
	r.content = texto
	r.executed_tools = []
	r.tokens_used = 0
	r.truncated = False
	return r


def test_versao():
	assert web_researcher.MODULE_VERSION == "4.14.0"


def test_sem_a_variavel_nao_ha_busca_real(monkeypatch):
	"""O padrao continua sendo offline -- a suite unitaria nao pode ir a rede."""
	monkeypatch.delenv(_ENV_BUSCA_REAL, raising=False)
	chamou: list = []
	monkeypatch.setattr(web_researcher, "on_demand_web_search", _busca_falsa(chamou))
	with patch.object(web_researcher, "create_llm_client", return_value=MagicMock(
		chat=MagicMock(return_value=_resposta()),
	)):
		web_researcher.run("pesquise algo", "modelo", {}, _memory=None)
	assert not chamou, "a busca real rodou sem a variavel de opt-in"


def test_com_a_variavel_a_busca_real_acontece(monkeypatch):
	monkeypatch.setenv(_ENV_BUSCA_REAL, "1")
	chamou: list = []
	monkeypatch.setattr(web_researcher, "on_demand_web_search", _busca_falsa(chamou))
	with patch.object(web_researcher, "create_llm_client", return_value=MagicMock(
		chat=MagicMock(return_value=_resposta()),
	)):
		web_researcher.run("pesquise algo", "modelo", {}, _memory=None)
	assert chamou, "a variavel de opt-in nao habilitou a busca real"


def test_valor_diferente_de_1_nao_libera(monkeypatch):
	"""Meio-termo nao existe aqui: qualquer coisa que nao seja o opt-in
	explicito mantem o comportamento seguro."""
	for valor in ("0", "", "sim", "true", "  "):
		monkeypatch.setenv(_ENV_BUSCA_REAL, valor)
		chamou = []
		monkeypatch.setattr(web_researcher, "on_demand_web_search", _busca_falsa(chamou))
		with patch.object(web_researcher, "create_llm_client", return_value=MagicMock(
			chat=MagicMock(return_value=_resposta()),
		)):
			web_researcher.run("q", "modelo", {}, _memory=None)
		assert not chamou, f"valor {valor!r} nao deveria liberar a busca"


def test_a_suite_unitaria_roda_offline_por_padrao():
	"""Se esta variavel vazar para o ambiente do desenvolvedor, a suite comeca a
	depender de rede e fica lenta e instavel sem ninguem entender por que."""
	assert os.environ.get(_ENV_BUSCA_REAL, "").strip() != "1", (
		f"{_ENV_BUSCA_REAL}=1 esta no ambiente: a suite unitaria iria a rede"
	)
