"""
Teto de tokens proporcional a complexidade, e parada limpa ao estourar.

REGRESSAO REAL QUE ESTES TESTES TRAVAM (E2E ao vivo, 2026-08-29):

Ligar o medidor do orcamento em voo (orchestrator 5.59.0) fez o freio
funcionar -- e expos que o TETO estava errado. Havia um unico valor fixo de
500 mil tokens, calibrado (sem ninguem notar) para addon simples, porque
enquanto o medidor nao era alimentado o numero nao tinha efeito nenhum.

Medicao dos 379 relatorios:
    addon simples que deu certo ..... mediana 204 mil / maximo 621 mil
    addon COMPLEXO que deu certo .... mediana 821 mil / maximo 4,6 milhoes

NENHUM addon complexo jamais teve sucesso dentro de 500 mil. Com o freio
funcionando, o teto antigo transformou "caro e as vezes funciona" em "para
cedo e NUNCA funciona": dois pedidos complexos reais morreram aos ~800 mil
tokens com 1 de 11 e 1 de 14 steps aprovados.

E havia uma segunda metade faltando. Ao estourar, o laco seguia chamando cada
step restante so para ele devolver score=0 -- a nota media do relatorio caiu
para 7.1 e 8.9, numeros que parecem colapso de qualidade quando na verdade um
step tinha sido aprovado com 98 e o resto nunca rodou. Relatorio que mente
sobre a causa manda investigar o lugar errado.
"""

import pytest

from nvdastudio.core.orchestrator import MODULE_VERSION as ORCH_VERSION, Orchestrator
from nvdastudio.utils.iteration_budget import (
	_DEFAULT_TOKEN_BUDGET,
	_TOKEN_BUDGET_BY_COMPLEXITY,
	MODULE_VERSION as BUDGET_VERSION,
	budget,
)

assert BUDGET_VERSION == "1.8.0"
assert ORCH_VERSION == "5.82.0"


@pytest.fixture(autouse=True)
def _orcamento_limpo():
	budget.reset()
	yield
	budget.reset()


class TestTetoPorComplexidade:
	@pytest.mark.parametrize(
		"complexidade,esperado",
		[("low", 300_000), ("medium", 700_000), ("high", 1_000_000)],
	)
	def test_cada_complexidade_tem_seu_teto(self, complexidade, esperado):
		assert budget.apply_complexity(complexidade) == esperado

	def test_teto_alto_cobre_a_mediana_real_do_addon_complexo(self):
		"""821 mil e a mediana medida dos addons complexos que DERAM CERTO. Um
		teto abaixo disso mata mais da metade das execucoes que funcionariam."""
		assert _TOKEN_BUDGET_BY_COMPLEXITY["high"] > 821_000

	def test_teto_simples_cobre_o_maximo_real_do_addon_simples(self):
		"""621 mil foi o maximo medido num addon simples bem-sucedido -- mas o
		teto 'low' e menor de proposito: addon simples que passa disso esta em
		loop, nao trabalhando. O teto 'medium' e que precisa cobrir."""
		assert _TOKEN_BUDGET_BY_COMPLEXITY["medium"] > 621_000

	@pytest.mark.parametrize("entrada", ["", "  ", "DESCONHECIDA", None])
	def test_complexidade_invalida_cai_no_medio_nunca_no_alto(self, entrada):
		"""Na duvida, o comportamento seguro e o mais restritivo -- cair no teto
		alto por engano daria cheque em branco para uma execucao em loop."""
		assert budget.apply_complexity(entrada) == _TOKEN_BUDGET_BY_COMPLEXITY["medium"]

	def test_maiusculas_e_espacos_nao_quebram(self):
		assert budget.apply_complexity("  HIGH  ") == _TOKEN_BUDGET_BY_COMPLEXITY["high"]

	def test_reset_devolve_o_teto_padrao(self):
		"""REGRESSAO: o budget e singleton de PROCESSO. Sem restaurar no reset,
		uma sessao com complexity=high deixaria o teto alto valendo para a
		proxima query, sem relacao nenhuma."""
		budget.apply_complexity("high")
		assert budget._limits.max_tokens == 1_000_000
		budget.reset()
		assert budget._limits.max_tokens == _DEFAULT_TOKEN_BUDGET

	def test_teto_alto_de_fato_deixa_passar_do_teto_antigo(self):
		"""O ponto todo da correcao: 800 mil tokens matavam a execucao antes."""
		budget.apply_complexity("high")
		for _ in range(8):
			budget.record_iteration(step_type="code_generation", tokens_used=100_000)
		assert budget.can_continue()[0] is True, (
			"800 mil tokens ainda param um addon complexo -- foi exatamente "
			"assim que os 2 pedidos reais morreram em 2026-08-29"
		)


class TestAplicacaoPeloOrchestrator:
	def _plano(self, complexidade):
		from nvdastudio.core.planner import ExecutionPlan

		return ExecutionPlan(
			plan_id="p1", original_query="q", steps=[], estimated_complexity=complexidade,
		)

	def test_orchestrator_aplica_o_teto_do_plano(self):
		o = Orchestrator.__new__(Orchestrator)
		o._aplicar_orcamento_por_complexidade(self._plano("high"))
		assert budget._limits.max_tokens == 1_000_000

	def test_plano_sem_complexidade_nao_levanta(self):
		"""Roda dentro do pipeline: excecao aqui derrubaria um plano valido."""
		o = Orchestrator.__new__(Orchestrator)
		o._aplicar_orcamento_por_complexidade(object())
		assert budget._limits.max_tokens in _TOKEN_BUDGET_BY_COMPLEXITY.values()


class TestDegradacaoGraciosa:
	"""Parar limpo e dizer a causa, em vez de cascatear zeros."""

	def test_mensagem_diz_orcamento_quando_foi_orcamento(self):
		o = Orchestrator.__new__(Orchestrator)
		o._parou_por_orcamento = ("Budget de tokens excedido (1800000)", 7)
		msg = o._mensagem_de_falha(
			"A criação não foi concluída porque nenhum arquivo Python válido..."
		)
		assert "limite de recursos" in msg
		assert "7 etapa" in msg
		assert "nenhum arquivo Python" not in msg

	def test_mensagem_original_preservada_quando_nao_foi_orcamento(self):
		"""A causa real tem precedencia sobre o sintoma -- mas so quando existe."""
		o = Orchestrator.__new__(Orchestrator)
		o._parou_por_orcamento = None
		original = "A criação não foi concluída porque nenhum arquivo Python válido..."
		assert o._mensagem_de_falha(original) == original

	def test_sem_o_atributo_nao_levanta(self):
		"""Instancias criadas via __new__ (padrao usado por varios testes do
		projeto para pular o __init__ pesado) nao tem o atributo."""
		o = Orchestrator.__new__(Orchestrator)
		assert o._mensagem_de_falha("erro original") == "erro original"
