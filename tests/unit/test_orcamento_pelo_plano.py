"""
O teto de tokens era uma constante por complexidade. Uma constante nao consegue
servir ao mesmo tempo um plano de 7 steps e um de 27.

Medido na rodada E2E de 2026-09-01: o plano real do addon complexo tinha 27
steps, dos quais 8 de code_generation. Somando o custo MEDIDO de uma unica
passada de cada tipo (mediana dos aprovados sem retentativa nos 391
relatorios), o piso do plano dava ~755 mil tokens -- contra um teto de 1
milhao. O orcamento so caberia se absolutamente nenhum step precisasse de uma
segunda tentativa. A execucao morreu com 18 steps sem executar: por aritmetica,
nao por desperdicio.

A constante vira PISO. O teto passa a ser dimensionado pelo plano aprovado, com
um teto absoluto que preserva o papel de disjuntor -- um plano gigante nao pode
virar cheque em branco.
"""

import inspect

import pytest

from nvdastudio.core.orchestrator import Orchestrator
from nvdastudio.utils.iteration_budget import (
	_TETO_ABSOLUTO,
	_TOKEN_BUDGET_BY_COMPLEXITY,
	MODULE_VERSION,
	IterationBudget,
)

_PLANO_COMPLEXO_REAL = (
	["user_clarification", "design_review", "manifest_builder", "web_research",
	 "agent_template"]
	+ ["code_generation"] * 8
	+ ["accessibility_audit", "documentation", "assembly", "syntax_validation"]
	+ ["code_generation"] * 3
	+ ["manifest_builder", "documentation", "assembly", "test_generation",
	   "accessibility_audit", "web_research", "agent_runner"]
)


def test_versao():
	assert MODULE_VERSION == "1.6.0"


def test_plano_complexo_real_cabe_no_teto():
	"""O caso que motivou a mudanca: 27 steps, 8 de code_generation."""
	teto = IterationBudget().apply_plan(_PLANO_COMPLEXO_REAL, "high")
	assert teto > _TOKEN_BUDGET_BY_COMPLEXITY["high"], (
		"um plano deste tamanho nao cabia no teto constante"
	)
	assert teto <= _TETO_ABSOLUTO


@pytest.mark.parametrize("complexidade", ["low", "medium", "high"])
def test_plano_pequeno_mantem_o_teto_de_antes(complexidade):
	"""Planos pequenos nao podem PERDER folga: a mudanca e para o caso grande."""
	pequeno = ["code_generation", "manifest_builder", "assembly"]
	teto = IterationBudget().apply_plan(pequeno, complexidade)
	assert teto == _TOKEN_BUDGET_BY_COMPLEXITY[complexidade]


def test_teto_absoluto_preserva_o_disjuntor():
	"""Nos relatorios, execucao que passou de ~1,5 milhao nunca entregou nada --
	a de 4,6 milhoes com 41 retentativas e o caso extremo. Um plano gigante nao
	pode virar cheque em branco."""
	teto = IterationBudget().apply_plan(["code_generation"] * 500, "high")
	assert teto == _TETO_ABSOLUTO


def test_code_generation_pesa_mais_que_os_outros():
	"""E o unico tipo que retenta com frequencia -- e o que dimensiona o plano."""
	b = IterationBudget()
	so_codigo = b.apply_plan(["code_generation"] * 12, "high")
	so_doc = b.apply_plan(["documentation"] * 12, "high")
	assert so_codigo > so_doc


def test_plano_vazio_cai_no_piso_por_complexidade():
	assert IterationBudget().apply_plan([], "high") == _TOKEN_BUDGET_BY_COMPLEXITY["high"]


def test_complexidade_desconhecida_cai_em_medium():
	"""Na duvida, o comportamento seguro e o mais restritivo -- nunca o teto alto."""
	assert IterationBudget().apply_plan([], "?????") == _TOKEN_BUDGET_BY_COMPLEXITY["medium"]


def test_tipo_de_step_desconhecido_nao_derruba_a_conta():
	"""Um step_type novo nao pode zerar o orcamento nem levantar excecao."""
	teto = IterationBudget().apply_plan(["tipo_que_nao_existe"] * 40, "medium")
	assert teto > _TOKEN_BUDGET_BY_COMPLEXITY["medium"]


def test_orchestrator_passa_os_steps_do_plano():
	"""A costura: dimensionar pelo plano so funciona se quem chama passar o
	plano. Passar so a complexidade traria de volta a constante."""
	src = inspect.getsource(Orchestrator._aplicar_orcamento_por_complexidade)
	assert "apply_plan(" in src
	assert "getattr(plan, \"steps\"" in src
	assert "apply_complexity(" not in src


class TestFolgaDeReplanejamento:
	"""
	O teto era estimado somando os steps DECLARADOS no plano. Replanejamento
	substitui os steps que falharam, e o que eles ja gastaram some da conta
	final -- mas nao do consumo real.

	Medido em 2026-09-01, comparando o medidor do circuit breaker com o
	`total_tokens` do relatorio, nas duas execucoes que morreram por teto:

	  AssistenteLeituraGemini   medidor 1.181.971   relatorio 1.041.202  (1,14x)
	  GeminiMultimodal          medidor 1.207.312   relatorio   707.841  (1,71x)

	Estimar o teto ignorando esse gasto foi o que fez as duas pararem com o
	plano ainda pela metade -- de novo por aritmetica, so que num degrau acima.
	"""

	def test_plano_com_codigo_recebe_folga_de_uma_rodada(self):
		b = IterationBudget()
		com_codigo = ["code_generation"] * 12 + ["documentation"] * 12
		sem_codigo = ["documentation"] * 24
		# a folga e proporcional ao custo dos steps que disparam replanejamento
		assert b.apply_plan(com_codigo, "high") > b.apply_plan(sem_codigo, "high")

	def test_folga_e_uma_passada_a_mais_nos_steps_criticos(self):
		"""Mecanismo, nao numero magico: replanejamento e disparado por
		code_generation/agent_runner reprovado, entao a folga e o custo de
		refazer exatamente esses."""
		b = IterationBudget()
		from nvdastudio.utils.iteration_budget import (
			_CUSTO_MEDIDO_POR_STEP,
			_TENTATIVAS_ESPERADAS,
		)

		from nvdastudio.utils.iteration_budget import _MARGEM_MEDIDOR

		# Plano pequeno de proposito: com muitos steps o teto ABSOLUTO entra e
		# mascara a formula que este teste verifica.
		plano = ["code_generation"] * 6
		custo_un = _CUSTO_MEDIDO_POR_STEP["code_generation"]
		base = 6 * custo_un * _TENTATIVAS_ESPERADAS["code_generation"] + 6 * custo_un
		# A margem do medidor (1.6.0) entra por cima da estimativa: os custos por
		# step vem do relatorio, e quem CORTA a execucao e o medidor.
		assert b.apply_plan(plano, "high") == int(base * _MARGEM_MEDIDOR)

	def test_o_plano_real_que_morreu_agora_cabe(self):
		"""GeminiMultimodal, 2026-09-01: teto de 1.093.400 e medidor em
		1.207.312 com 16 etapas sem executar."""
		b = IterationBudget()
		assert b.apply_plan(_PLANO_COMPLEXO_REAL, "high") > 1_207_312

	def test_teto_absoluto_continua_cortando_loop(self):
		b = IterationBudget()
		assert b.apply_plan(["code_generation"] * 500, "high") == _TETO_ABSOLUTO
