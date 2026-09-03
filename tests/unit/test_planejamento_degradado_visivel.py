"""O plano degradado tem que aparecer no relatorio, nao so no log.

Na rodada de 2026-09-03 07:23 o Planner falhou com o provedor de saida
estruturada (OpenCode Go, 401 sem saldo) e refez o plano no provedor ativo
do usuario, SEM json_schema estrito:

    [AVISO] Planner: falhou com modelo opencode_go::gpt-5.6-luna. 401
    [PLAN] Refazendo o plano em kimi-k2.7-code -- SEM garantia de json_schema

Isso acontece em TODA rodada enquanto nao houver saldo, e explica por que o
MESMO pedido produz planos de formas diferentes entre execucoes -- variacao
que, sem esse registro, parece aleatoria para quem compara dois relatorios.

O plano continua valido: as injecoes deterministicas do Planner garantem os
steps essenciais (foi o que aconteceu na rodada -- accessibility_audit,
manifest_builder, documentation, engineering_review e assembly estavam todos
la). O que faltava era DIZER que veio pelo caminho degradado.

Nota de diagnostico: a leitura inicial dessa rodada foi de que o plano tinha
encolhido de 13 para 9 steps. Estava errada -- os 9 sao os steps que
EXECUTARAM antes do orcamento acabar no cg_core; o plano estava completo. O
log desmentiu a inferencia, e este teste existe para que a informacao esteja
no relatorio da proxima vez, sem precisar do log.
"""

import os

from nvdastudio.core.orch_types import OrchestrationResult
from nvdastudio.core.planner import ExecutionPlan


class TestOPlanoCarregaAMarca:

	def test_campo_existe_e_o_padrao_e_nao_degradado(self):
		plano = ExecutionPlan(plan_id="x", original_query="q", steps=[])

		assert plano.planejamento_degradado is False, (
			"o padrao tem que ser 'nao degradado' -- marcar tudo como degradado "
			"tornaria a marca inutil"
		)

	def test_marca_e_setada_onde_a_degradacao_acontece(self):
		"""Ancora no codigo: a flag tem que ser marcada no MESMO ponto em que
		o cliente degradado e criado. Se alguem mover uma sem a outra, a marca
		mente."""
		fonte = open(
			os.path.join(os.path.dirname(__file__), "..", "..", "addon",
						 "globalPlugins", "nvdastudio", "core", "planner.py"),
			encoding="utf-8",
		).read()

		i_flag = fonte.index("self._planejamento_degradado = True")
		i_cliente = fonte.index("cliente_degradado = create_llm_client")

		assert 0 < i_cliente - i_flag < 400, (
			"a marca de degradacao se distanciou da criacao do cliente degradado"
		)

	def test_os_dois_construtores_de_plano_propagam(self):
		"""O Planner constroi ExecutionPlan em dois lugares (plano normal e
		plano de replanejamento). Um so propagando faria o replanejamento
		perder a marca silenciosamente."""
		fonte = open(
			os.path.join(os.path.dirname(__file__), "..", "..", "addon",
						 "globalPlugins", "nvdastudio", "core", "planner.py"),
			encoding="utf-8",
		).read()

		assert fonte.count("planejamento_degradado=getattr(self,") == 2


class TestOResultadoCarregaAMarca:

	def test_campo_existe_no_resultado(self):
		r = OrchestrationResult(
			plan_id="x", query="q", step_results=[], final_output="", success=True,
		)

		assert r.planejamento_degradado is False

	def test_propagacao_acontece_em_ponto_unico(self):
		"""OrchestrationResult e construido em 5+ lugares no orchestrator.
		Copiar a marca em cada um e a costura que quebra quando aparece o
		sexto -- exatamente a classe de defeito que esta sessao corrigiu. A
		propagacao tem que estar no ponto por onde TODO resultado passa."""
		fonte = open(
			os.path.join(os.path.dirname(__file__), "..", "..", "addon",
						 "globalPlugins", "nvdastudio", "core", "orchestrator.py"),
			encoding="utf-8",
		).read()

		assert fonte.count("result.planejamento_degradado = bool(") == 1
		# E esse ponto e o _run_until_success, nao um construtor qualquer.
		i_metodo = fonte.index("def _run_until_success")
		i_prop = fonte.index("result.planejamento_degradado = bool(")
		i_proximo_def = fonte.index("\tdef ", i_metodo + 10)
		assert i_metodo < i_prop < i_proximo_def


def test_relatorio_e2e_serializa_a_marca():
	"""Sem isso a informacao existe em memoria e some no JSON -- que e
	justamente onde alguem vai procurar ao comparar duas rodadas."""
	fonte = open(
		os.path.join(os.path.dirname(__file__), "..", "..", "tests", "e2e",
					 "test_criacao_completa.py"),
		encoding="utf-8",
	).read()

	assert "planejamento_degradado: bool = False" in fonte
	assert "\"planejamento_degradado\": self.planejamento_degradado," in fonte
	assert "report.planejamento_degradado = getattr(result," in fonte
