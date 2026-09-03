"""Regressao: o step que gera o ponto de entrada tem que convergir.

Medido na rodada de 2026-09-03 07:23. O `cg_core` -- que produz o
`__init__.py`, sem o qual o NVDA nao carrega nada -- foi reprovado tres vezes
e consumiu 635.658 tokens (55% da rodada) antes de estourar o orcamento. O
pipeline entregou ZERO arquivo.

As objecoes do Critic eram reais e DIFERENTES a cada tentativa:

  tentativa 1 (score 0):  wx.CallLater em vez de wx.CallAfter; imports
                          tolerantes so logam; painel nao condicionado ao
                          modo seguro ("embora essa parte fosse OPCIONAL" --
                          palavra do proprio Critic, contando como issue)
  tentativa 2 (score 82): descricao do item de menu promete dialogo que
                          _on_menu nao abre; FindWindowById nao acha
                          wx.MenuItem; menu criado em modo seguro
  tentativa 3:            orcamento estourado

Cada retry corrigia o anterior e ganhava objecoes novas. Nao converge por
desenho: um juiz de linguagem natural sempre acha o que dizer sobre codigo
real. Aumentar o numero de tentativas so troca "nao converge em 3" por "nao
converge em 5, mais caro".

A saida NAO e afrouxar o limiar: e aceitar, como ultimo recurso, o melhor
candidato que passou em TODA a verificacao mecanica -- registrando as
objecoes nao resolvidas como ressalva.
"""

import ast
import os
from unittest.mock import patch

from nvdastudio.ai.critic import CriticResult, Verdict
from nvdastudio.core.orchestrator import (
	_SCORE_MIN_ACEITACAO_POR_PORTOES,
	_STEPS_QUE_PRODUZEM_ARQUIVO,
	Orchestrator,
)
from nvdastudio.core.orch_types import StepResult
from nvdastudio.core.planner import ExecutionStep

_CODIGO_VALIDO = (
	"```python:globalPlugins/MeuAddon/__init__.py\n"
	"import globalPluginHandler\n"
	"import addonHandler\n\n"
	"addonHandler.initTranslation()\n\n"
	"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
	"\tdef terminate(self):\n"
	"\t\tsuper().terminate()\n"
	"```\n"
)


def _step() -> ExecutionStep:
	return ExecutionStep(
		step_id="cg_core", step_type="code_generation",
		description="gerar o ponto de entrada", model_id="kimi-k2.7-code",
		max_retries=3,
	)


def _reprovado(score: int) -> CriticResult:
	return CriticResult(
		verdict=Verdict.NEEDS_FIX if score >= 60 else Verdict.REJECTED,
		score=score,
		issues=[
			"terminate() nao remove o item de menu de forma confiavel: "
			"wx.FindWindowById nao localiza wx.MenuItem.",
		],
		fix_instructions="corrija",
	)


class TestAceitaPorPortoesVerdes:

	def test_candidato_bom_e_aceito_com_ressalva_em_vez_de_perder_tudo(self, fake_api_key):
		"""O caso do cg_core: score 82, limiar 90, tentativas esgotadas. A
		alternativa real nao e 'esperar um score 90' -- e entregar nada."""
		orch = Orchestrator()
		orch._api_key = fake_api_key
		orch.initialize()
		falha_escalacao = StepResult(
			step_id="cg_core", step_type="code_generation", output="",
			approved=False, score=0, issues=["escalacao tambem reprovou"],
		)

		with patch.object(orch, "_dispatch_with_heartbeat", return_value=(_CODIGO_VALIDO, 10)), \
			patch.object(orch._critic, "evaluate_two_stage", return_value=_reprovado(82)), \
			patch.object(orch, "_try_escalation", return_value=falha_escalacao), \
			patch.object(orch, "_try_cross_provider_rescue", return_value=None):
			resultado = orch._execute_step_with_critique(_step(), "query", "")

		assert resultado.approved is True, (
			"o melhor candidato passou em todos os portoes deterministicos e "
			"ainda assim o pipeline entregaria nada"
		)
		assert resultado.score == 82
		assert any("ACEITO COM RESSALVA" in i for i in resultado.issues)
		# A objecao nao resolvida continua visivel -- ressalva nao e perdao.
		assert any("FindWindowById" in i for i in resultado.issues)

	def test_output_aceito_e_o_do_melhor_candidato(self, fake_api_key):
		orch = Orchestrator()
		orch._api_key = fake_api_key
		orch.initialize()

		with patch.object(orch, "_dispatch_with_heartbeat", return_value=(_CODIGO_VALIDO, 10)), \
			patch.object(orch._critic, "evaluate_two_stage", return_value=_reprovado(75)), \
			patch.object(orch, "_try_escalation", return_value=StepResult(
				step_id="cg_core", step_type="code_generation", output="",
				approved=False, score=0, issues=[])), \
			patch.object(orch, "_try_cross_provider_rescue", return_value=None):
			resultado = orch._execute_step_with_critique(_step(), "query", "")

		assert "class GlobalPlugin" in resultado.output


class TestNaoAceitaOQueNaoDeve:
	"""A aceitacao e ultimo recurso, nao porta dos fundos."""

	def test_score_de_rejeicao_nunca_e_aceito(self, fake_api_key):
		"""Abaixo de 60 o Critic esta dizendo que o output e irrecuperavel.
		Nenhum portao deterministico compensa isso."""
		orch = Orchestrator()
		orch._api_key = fake_api_key
		orch.initialize()

		with patch.object(orch, "_dispatch_with_heartbeat", return_value=(_CODIGO_VALIDO, 10)), \
			patch.object(orch._critic, "evaluate_two_stage", return_value=_reprovado(30)), \
			patch.object(orch, "_try_escalation", return_value=StepResult(
				step_id="cg_core", step_type="code_generation", output="",
				approved=False, score=0, issues=["irrecuperavel"])), \
			patch.object(orch, "_try_cross_provider_rescue", return_value=None):
			resultado = orch._execute_step_with_critique(_step(), "query", "")

		assert resultado.approved is False

	def test_escalacao_aprovada_ganha_da_aceitacao_com_ressalva(self, fake_api_key):
		"""Se a escalacao resolveu de verdade, e o resultado dela que vale --
		aceitar com ressalva quando ha aprovacao limpa seria pior."""
		orch = Orchestrator()
		orch._api_key = fake_api_key
		orch.initialize()
		escalacao_ok = StepResult(
			step_id="cg_core", step_type="code_generation",
			output=_CODIGO_VALIDO, approved=True, score=95, issues=[],
		)

		with patch.object(orch, "_dispatch_with_heartbeat", return_value=(_CODIGO_VALIDO, 10)), \
			patch.object(orch._critic, "evaluate_two_stage", return_value=_reprovado(82)), \
			patch.object(orch, "_try_escalation", return_value=escalacao_ok), \
			patch.object(orch, "_try_cross_provider_rescue", return_value=None):
			resultado = orch._execute_step_with_critique(_step(), "query", "")

		assert resultado.approved is True
		assert resultado.score == 95
		assert not any("RESSALVA" in i for i in resultado.issues)

	def test_so_vale_para_step_que_produz_arquivo(self):
		"""Um step consultivo que nao converge nao tem nada para entregar --
		aceitar com ressalva ali so mascararia o problema."""
		assert _STEPS_QUE_PRODUZEM_ARQUIVO == {"code_generation"}
		for consultivo in ("design_review", "engineering_review", "web_research", "assembly"):
			assert consultivo not in _STEPS_QUE_PRODUZEM_ARQUIVO

	def test_piso_e_o_mesmo_do_critic(self):
		"""60 nao e numero escolhido aqui: e o limite que o proprio Critic usa
		para separar CORRIGIR de REJEITAR. Duas reguas diferentes para a mesma
		coisa e a duplicacao que a Regra 5 proibe."""
		fonte = open(
			os.path.join(os.path.dirname(__file__), "..", "..", "addon",
						 "globalPlugins", "nvdastudio", "ai", "critic.py"),
			encoding="utf-8",
		).read()

		assert _SCORE_MIN_ACEITACAO_POR_PORTOES == 60
		assert "score 60-89  -> CORRIGIR" in fonte


def test_aceitacao_so_acontece_depois_de_escalacao_e_resgate():
	"""Fitness function de ORDEM: a aceitacao com ressalva e a ultima linha
	antes de devolver fracasso. Se alguem move a chamada para antes da
	escalacao, o pipeline para de tentar consertar de verdade e passa a
	aceitar cedo -- o oposto do que este mecanismo existe para fazer."""
	caminho = os.path.join(
		os.path.dirname(__file__), "..", "..", "addon", "globalPlugins",
		"nvdastudio", "core", "orchestrator.py",
	)
	fonte = open(caminho, encoding="utf-8").read()
	arvore = ast.parse(fonte)

	metodo = next(
		no for no in ast.walk(arvore)
		if isinstance(no, ast.FunctionDef) and no.name == "_execute_step_with_critique"
	)
	nomes = [
		no.func.attr for no in ast.walk(metodo)
		if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
	]

	primeira_aceitacao = nomes.index("_aceitar_por_portoes_verdes")
	assert nomes.index("_try_escalation") < primeira_aceitacao, (
		"aceitacao com ressalva vindo ANTES da escalacao de modelo"
	)
	assert nomes.index("_try_cross_provider_rescue") < nomes[
		primeira_aceitacao + 1:
	].index("_aceitar_por_portoes_verdes") + primeira_aceitacao + 1, (
		"a aceitacao no caminho final tem que vir depois do resgate cross-provider"
	)
