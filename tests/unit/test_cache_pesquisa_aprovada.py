"""
A pesquisa web era cacheada no fim do proprio `web_researcher.run()` -- ANTES
de o Critic existir na historia, porque ele so avalia depois que o agente
retorna. Uma pesquisa que o proprio pipeline julgava ERRADA virava conhecimento
persistido por 7 dias, servido a toda execucao seguinte.

Medido nos relatorios E2E: 15 reprovacoes com a MESMA queixa -- "a pesquisa usa
o pacote legado google-generativeai, mas o objetivo exige google-genai". E o
cache tambem alimenta a busca proativa do `code_generator`, entao a pesquisa
reprovada chegava direto na geracao de codigo: na rodada de 12:26,
`cg_core_service` gastou 419.747 tokens em 3 tentativas para ser reprovado por
seguir exatamente essa pesquisa.

Cachear so o que passou na verificacao nao e otimizacao: e a diferenca entre
memoria e boato.
"""

import inspect

from nvdastudio.sub_agents import web_researcher
from nvdastudio.sub_agents.web_researcher import MODULE_VERSION, salvar_se_aprovado


class _MemoriaFake:
	def __init__(self):
		self.gravados: list[tuple[str, str]] = []

	def save_web_knowledge(self, topic, content):
		self.gravados.append((topic, content))

	def get_web_knowledge(self, topic, max_age_days=7):
		return []


def test_versao():
	assert MODULE_VERSION == "4.14.0"


def test_run_nao_grava_mais_no_cache():
	"""O agente nao conhece o veredicto -- gravar aqui e gravar no escuro."""
	src = inspect.getsource(web_researcher.run)
	assert "save_web_knowledge" not in src, (
		"run() voltou a cachear antes da verificacao"
	)


def test_salvar_se_aprovado_grava():
	mem = _MemoriaFake()
	assert salvar_se_aprovado("Pesquise a API atual do Gemini", "conteudo", _memory=mem)
	assert len(mem.gravados) == 1
	assert mem.gravados[0][1] == "conteudo"


def test_topico_de_gravacao_e_o_mesmo_da_leitura():
	"""Se gravacao e leitura derivarem o topico de formas diferentes, o cache
	nunca acerta -- e a duplicacao da regra seria invisivel (Regra 5)."""
	prompt = "Pesquisar a documentacao atual do pacote google-genai"
	mem = _MemoriaFake()
	salvar_se_aprovado(prompt, "x", _memory=mem)
	assert mem.gravados[0][0] == web_researcher._extract_topic(prompt)


def test_conteudo_vazio_nao_e_gravado():
	"""Cachear vazio serviria vazio na proxima execucao."""
	mem = _MemoriaFake()
	assert not salvar_se_aprovado("q", "   ", _memory=mem)
	assert not mem.gravados


def test_falha_ao_cachear_nao_derruba_o_step():
	class MemoriaQuebrada:
		def save_web_knowledge(self, *a, **k):
			raise RuntimeError("disco cheio")

	assert salvar_se_aprovado("q", "conteudo", _memory=MemoriaQuebrada()) is False


def test_orchestrator_grava_apenas_no_ramo_aprovado():
	"""A costura: quem conhece o veredicto e o orchestrator, e a gravacao tem
	que estar do lado APROVADO do if -- do outro lado, o boato volta."""
	from nvdastudio.core.orchestrator import Orchestrator

	src = inspect.getsource(Orchestrator._execute_step_with_critique)
	assert "salvar_se_aprovado" in src
	pos_aprovado = src.index("if crit.verdict == Verdict.APPROVED:")
	pos_salvar = src.index("salvar_se_aprovado")
	assert pos_salvar > pos_aprovado, "gravacao fora do ramo de aprovacao"
	# e antes do proximo ramo (REJECTED), ou seja, dentro do bloco do aprovado
	pos_rejeitado = src.index("elif crit.verdict == Verdict.REJECTED:")
	assert pos_salvar < pos_rejeitado
