"""
O custo da pesquisa web era invisivel -- para o relatorio e para o disjuntor.

`_synthesize_web_results()` chama o LLM e NAO registrava tokens; so o caminho de
fallback (`_knowledge_only_call`) registrava. Enquanto a busca real estava
desligada sob teste, o gasto aqui era zero e ninguem notou. Ligada
(web_researcher 4.12.0), virou consumo REAL e INVISIVEL: fora do relatorio e,
pior, fora do medidor que decide parar o pipeline.

Sintoma medido: web_research aparecia com `tokens=0` mesmo com 3 retentativas,
nos relatorios das rodadas 7 e 8 e do complexo minimo. E o custo por step usado
para dimensionar o orcamento (iteration_budget) ficou subestimado por causa
disso -- um erro alimentando o outro.
"""

from unittest.mock import MagicMock, patch

from nvdastudio.sub_agents import web_researcher
from nvdastudio.sub_agents._base import _tl


def _resposta(texto, tokens):
	r = MagicMock()
	r.content = texto
	r.tool_calls = []
	r.executed_tools = []
	r.tokens_used = tokens
	r.truncated = False
	return r


class _MemoriaVazia:
	"""Memoria que nunca tem cache.

	`_memory=None` NAO desliga o cache: run() cai na memoria global, e na suite
	completa ela ja tem entradas de web_knowledge deixadas por outros testes --
	o cache acerta, run() retorna cedo e nenhum token e gasto. Foi assim que
	estes testes passaram isolados e falharam na suite.
	"""

	def get_web_knowledge(self, *args, **kwargs):
		return []

	def save_web_knowledge(self, *args, **kwargs):
		return None


def _busca_falsa(retorno="resultado bruto da busca"):
	def _busca(*args, **kwargs):
		return retorno

	_busca.__module__ = web_researcher.__name__
	return _busca


def test_versao():
	assert web_researcher.MODULE_VERSION == "4.15.0"


def test_sintese_registra_o_proprio_custo(monkeypatch):
	monkeypatch.setenv(web_researcher._ENV_BUSCA_REAL, "1")
	monkeypatch.setattr(web_researcher, "on_demand_web_search", _busca_falsa())
	cliente = MagicMock(chat=MagicMock(return_value=_resposta("sintese " * 40, 4321)))
	with patch.object(web_researcher, "create_llm_client", return_value=cliente):
		web_researcher.run("pesquise algo", "modelo", {}, _memory=_MemoriaVazia())
	assert _tl.last_tokens >= 4321, (
		f"custo da sintese nao contabilizado: {_tl.last_tokens}"
	)


def test_contador_zera_entre_chamadas(monkeypatch):
	"""Sem zerar, uma chamada sem custo herdaria o total da anterior e o
	orcamento contaria o mesmo gasto duas vezes."""
	monkeypatch.delenv(web_researcher._ENV_BUSCA_REAL, raising=False)
	cliente = MagicMock(chat=MagicMock(return_value=_resposta("conteudo " * 40, 100)))
	with patch.object(web_researcher, "create_llm_client", return_value=cliente):
		web_researcher.run("q1", "modelo", {}, _memory=_MemoriaVazia())
		primeiro = _tl.last_tokens
		web_researcher.run("q2", "modelo", {}, _memory=_MemoriaVazia())
	assert _tl.last_tokens == primeiro, "o contador acumulou entre execucoes"


def test_fallback_tambem_registra(monkeypatch):
	monkeypatch.delenv(web_researcher._ENV_BUSCA_REAL, raising=False)
	cliente = MagicMock(chat=MagicMock(return_value=_resposta("conteudo " * 40, 777)))
	with patch.object(web_researcher, "create_llm_client", return_value=cliente):
		web_researcher.run("q", "modelo", {}, _memory=_MemoriaVazia())
	assert _tl.last_tokens >= 777
