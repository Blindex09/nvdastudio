from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _budget_isolado():
	"""Isola o singleton global entre testes -- reset antes e depois."""
	from nvdastudio.utils.iteration_budget import budget
	budget.reset()
	yield
	budget.reset()


class TestResetNoInicioDoPipeline:
	def test_run_async_reseta_budget_sincronamente(self, fake_api_key):
		from nvdastudio.core.orchestrator import Orchestrator
		from nvdastudio.utils.iteration_budget import budget

		budget.record_iteration("code_generation", "modelo-x", tokens_used=1000, success=True)
		assert budget.get_state().iterations_used == 1

		orch = Orchestrator()
		orch._api_key = fake_api_key
		with patch.object(orch, "_run_async_worker"):
			orch.run_async("crie addon")

		assert budget.get_state().iterations_used == 0

	def test_run_conversational_async_reseta_budget_sincronamente(self, fake_api_key):
		from nvdastudio.core.orchestrator import Orchestrator
		from nvdastudio.utils.iteration_budget import budget

		budget.record_iteration("code_generation", "modelo-x", tokens_used=1000, success=True)
		assert budget.get_state().iterations_used == 1

		orch = Orchestrator()
		orch._api_key = fake_api_key
		with patch.object(orch, "_run_conversational_pipeline"):
			orch.run_conversational_async("crie addon")

		assert budget.get_state().iterations_used == 0


class TestRecordIterationBudgetHelper:
	def test_registra_um_por_step_result(self, fake_api_key):
		from nvdastudio.core.orchestrator import Orchestrator, StepResult
		from nvdastudio.utils.iteration_budget import budget

		orch = Orchestrator()
		orch._api_key = fake_api_key
		steps = [
			StepResult("s1", "code_generation", "out", approved=True, score=90,
					   model_id="kimi-k2.7-code", tokens_used=500, execution_time_ms=1200),
			StepResult("s2", "manifest_builder", "out", approved=False, score=10,
					   model_id="glm-5.2", tokens_used=200, execution_time_ms=300),
		]

		orch._record_iteration_budget(steps)

		assert budget.get_state().iterations_used == 2
		assert budget.get_state().tokens_used == 700

	def test_excecao_no_record_nao_propaga(self, fake_api_key):
		"""Fail-open: iteration_budget nao pode derrubar o pipeline principal."""
		from nvdastudio.core.orchestrator import Orchestrator, StepResult
		import nvdastudio.core.orchestrator as orch_mod

		orch = Orchestrator()
		orch._api_key = fake_api_key
		with patch.object(orch_mod.iteration_budget, "record_iteration", side_effect=RuntimeError("boom")):
			orch._record_iteration_budget([StepResult("s1", "code_generation", "out", True, 90)])
		# Nao levantou -- chegar aqui e o teste passar.


class TestPipelinesChamamRecordEmTodosOsDesfechos:
	"""Confirma via inspecao de fonte que os 3 pontos de saida de cada
	pipeline (_run_conversational_pipeline e _run_pipeline) chamam
	_record_iteration_budget -- inclusive nos 2 caminhos de FALHA, que
	antes da correcao nunca registravam nada."""

	def test_run_conversational_pipeline_registra_nos_3_desfechos(self):
		import inspect
		from nvdastudio.core import orchestrator
		src = inspect.getsource(orchestrator.Orchestrator._run_conversational_pipeline)
		assert src.count("self._record_iteration_budget(step_results)") == 3, (
			"_run_conversational_pipeline deveria chamar _record_iteration_budget "
			"nos 3 desfechos: artefato ausente, sucesso, excecao critica"
		)

	def test_run_pipeline_registra_nos_3_desfechos(self):
		import inspect
		from nvdastudio.core import orchestrator
		src = inspect.getsource(orchestrator.Orchestrator._run_pipeline)
		assert src.count("self._record_iteration_budget(step_results)") == 3, (
			"_run_pipeline deveria chamar _record_iteration_budget "
			"nos 3 desfechos: artefato ausente, sucesso, excecao critica"
		)


class TestAgenticLoopRespeitaBudget:
	def _make_orchestrator(self):
		from nvdastudio.core.orchestrator import Orchestrator
		orch = Orchestrator()
		orch.initialize()
		return orch

	def test_budget_estourado_forca_diagnose_give_up_em_vez_de_proxima_estrategia(self):
		from nvdastudio.core.agentic_loop import AgenticLoop
		from nvdastudio.core.orch_types import OrchestrationResult, StepResult
		import nvdastudio.core.agentic_loop as agentic_loop_mod

		orch = self._make_orchestrator()
		results = []
		orch.set_callbacks(on_progress=lambda e, d: None, on_complete=results.append)

		attempt = 0

		def fake_execute_state(self, state, query, prev_result):
			nonlocal attempt
			attempt += 1
			return OrchestrationResult(
				plan_id="p", query=query, step_results=[
					StepResult("s1", "code_generation", "out", approved=False, score=0,
							   issues=[f"erro diferente {attempt}"]),
				],
				final_output="", success=False,
				all_issues=[f"erro diferente {attempt}"],
			)

		with patch.object(AgenticLoop, "_execute_state", fake_execute_state), \
			patch.object(agentic_loop_mod.iteration_budget, "can_continue",
						  return_value=(False, "Budget de custo excedido (teste)")):
			orch._run_until_success("query cara")

		# Orcamento ja "estourado" desde a 1a reflexao -> so 1 tentativa real
		# antes do diagnostico final (a 1a execucao sempre acontece; e a
		# TRANSICAO pra proxima estrategia que deve ser bloqueada).
		assert attempt == 1
		assert results[0].success is False

	def test_budget_ok_no_bloqueia_transicoes_normais(self):
		"""Confirma que o gate so age quando o orcamento realmente estoura --
		nao introduz regressao no fluxo normal (estagnacao continua parando
		por streak_no_progress, nao pelo budget)."""
		from nvdastudio.core.agentic_loop import AgenticLoop
		from nvdastudio.core.orch_types import OrchestrationResult, StepResult

		orch = self._make_orchestrator()
		results = []
		orch.set_callbacks(on_progress=lambda e, d: None, on_complete=results.append)

		attempt = 0

		def fake_execute_state(self, state, query, prev_result):
			nonlocal attempt
			attempt += 1
			return OrchestrationResult(
				plan_id="p", query=query, step_results=[
					StepResult("s1", "code_generation", "out", approved=False, score=0,
							   issues=["same_error"]),
				],
				final_output="same", success=False,
				all_issues=["same_error"], total_retries=2,
			)

		with patch.object(AgenticLoop, "_execute_state", fake_execute_state):
			orch._run_until_success("query que nao funciona")

		# Mesmo comportamento do teste pre-existente de estagnacao (budget
		# real, nao estourado, com poucas iteracoes de teste).
		assert attempt <= 5
		assert results[0].success is False


class TestExecuteStepWithCritiqueRespeitaBudget:
	"""5.28.0: achado real da suite e2e completa (217 casos reais, ~6h13min)
	-- can_continue() so era consultado em agentic_loop.py. O pipeline
	PRINCIPAL de criacao (_execute_step_with_critique) so registrava gasto
	e nunca perguntava can_continue() antes de mais uma chamada. Confirmado
	ao vivo: addon complexo rodou ate 278 iteracoes / $20.25 contra um teto
	de 50 iteracoes / $5.00 -- nenhum enforcement real."""

	def test_orcamento_estourado_aborta_sem_chamar_llm(self, fake_api_key):
		from nvdastudio.core.orchestrator import Orchestrator
		from nvdastudio.core.planner import ExecutionStep
		import nvdastudio.core.orchestrator as orch_mod

		orch = Orchestrator()
		orch._api_key = fake_api_key
		orch.initialize()
		step = ExecutionStep(
			step_id="s1", step_type="code_generation",
			description="gerar addon", model_id="kimi-k2.7-code",
		)

		dispatch_calls = {"count": 0}

		def fake_dispatch(*args, **kwargs):
			dispatch_calls["count"] += 1
			return "output", 100

		with patch.object(orch_mod.iteration_budget, "can_continue",
						   return_value=(False, "Budget de custo excedido (teste)")), \
			patch.object(orch, "_dispatch_with_heartbeat", side_effect=fake_dispatch):
			result = orch._execute_step_with_critique(step, "query", "")

		assert dispatch_calls["count"] == 0, (
			"Nenhuma chamada LLM deveria acontecer com orcamento ja estourado"
		)
		assert result.approved is False
		assert result.score == 0
		assert any("orcamento" in i.lower() for i in result.issues)

	def test_orcamento_ok_nao_bloqueia_execucao_normal(self, fake_api_key):
		"""Confirma que o gate so age quando o orcamento realmente estourou --
		nao introduz regressao no fluxo normal de execucao de step."""
		from nvdastudio.core.orchestrator import Orchestrator
		from nvdastudio.core.planner import ExecutionStep
		from nvdastudio.ai.critic import CriticResult, Verdict
		import nvdastudio.core.orchestrator as orch_mod

		orch = Orchestrator()
		orch._api_key = fake_api_key
		orch.initialize()
		step = ExecutionStep(
			step_id="s1", step_type="manifest_builder",
			description="gerar manifest", model_id="deepseek-v4-flash",
			max_retries=1,
		)

		with patch.object(orch_mod.iteration_budget, "can_continue", return_value=(True, "OK")), \
			patch.object(orch, "_dispatch_with_heartbeat", return_value=("output valido", 50)), \
			patch.object(orch._critic, "evaluate_two_stage",
						  return_value=CriticResult(verdict=Verdict.APPROVED, score=95,
													 issues=[], fix_instructions="")):
			result = orch._execute_step_with_critique(step, "query", "")

		assert result.approved is True
		assert result.score == 95


class TestLearnFromSessionChamadoEmTodosOsDesfechos:
	"""Achado de auditoria full-stack 2026-08-04 (segunda rodada, subsistema
	de memoria): memory_manager.learn_from_session() so era chamado no
	caminho de SUCESSO de _run_conversational_pipeline -- falhas e execucoes
	via _run_pipeline (FSM) nunca ensinavam MEMORY.md/USER.md."""

	def test_run_conversational_pipeline_chama_nos_3_desfechos(self):
		import inspect
		from nvdastudio.core import orchestrator
		src = inspect.getsource(orchestrator.Orchestrator._run_conversational_pipeline)
		assert src.count("self._learn_from_session(") == 3, (
			"_run_conversational_pipeline deveria chamar _learn_from_session "
			"nos 3 desfechos: artefato ausente, sucesso, excecao critica"
		)

	def test_run_pipeline_chama_nos_3_desfechos(self):
		import inspect
		from nvdastudio.core import orchestrator
		src = inspect.getsource(orchestrator.Orchestrator._run_pipeline)
		assert src.count("self._learn_from_session(") == 3, (
			"_run_pipeline deveria chamar _learn_from_session "
			"nos 3 desfechos: artefato ausente, sucesso, excecao critica"
		)

	def test_learn_from_session_usa_current_plan_addon_name_nao_plan_direto(self, fake_api_key):
		"""Nao pode acessar plan.addon_name direto -- plan pode nao existir
		se a excecao aconteceu antes da criacao do plano."""
		from nvdastudio.core.orchestrator import Orchestrator
		import nvdastudio.core.orchestrator as orch_mod

		orch = Orchestrator()
		orch._api_key = fake_api_key
		orch._current_plan_addon_name = "MeuAddon"

		captured = {}

		def fake_learn(**kwargs):
			captured.update(kwargs)

		with patch.object(orch_mod.memory_manager, "learn_from_session", side_effect=fake_learn):
			orch._learn_from_session("crie um addon", True, [])

		assert captured["addon_name"] == "MeuAddon"

	def test_learn_from_session_nao_quebra_sem_current_plan_addon_name(self, fake_api_key):
		"""Objeto recem-criado via __new__ (sem passar por __init__) -- fallback
		via getattr nao pode lancar AttributeError."""
		from nvdastudio.core.orchestrator import Orchestrator
		import nvdastudio.core.orchestrator as orch_mod

		orch = Orchestrator.__new__(Orchestrator)
		captured = {}

		def fake_learn(**kwargs):
			captured.update(kwargs)

		with patch.object(orch_mod.memory_manager, "learn_from_session", side_effect=fake_learn):
			orch._learn_from_session("crie um addon", False, ["erro"])

		assert captured["addon_name"] == ""

	def test_excecao_no_learn_nao_propaga(self, fake_api_key):
		from nvdastudio.core.orchestrator import Orchestrator
		import nvdastudio.core.orchestrator as orch_mod

		orch = Orchestrator()
		orch._api_key = fake_api_key
		with patch.object(orch_mod.memory_manager, "learn_from_session", side_effect=RuntimeError("boom")):
			orch._learn_from_session("crie um addon", True, [])
