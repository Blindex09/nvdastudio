from unittest.mock import MagicMock, patch


class TestOrchestratorRunPipelineResume:
	"""Orchestrator._run_pipeline(resume_plan=..., resume_completed=...)."""

	def test_sem_resume_seta_current_plan_apos_create_plan(self, fake_api_key):
		from nvdastudio.core.orchestrator import Orchestrator
		from nvdastudio.core.planner import ExecutionPlan, ExecutionStep

		orch = Orchestrator()
		orch._api_key = fake_api_key

		plan = ExecutionPlan(
			plan_id="p1", original_query="criar addon", steps=[
				ExecutionStep("s1", "manifest_builder", "gerar manifest", "kimi-k2.6"),
			],
		)
		mock_planner = MagicMock()
		mock_planner.create_plan.return_value = plan
		orch._planner = mock_planner
		orch._critic = MagicMock()
		orch._critic.evaluate_two_stage.return_value = MagicMock(
			verdict=__import__("nvdastudio.ai.critic", fromlist=["Verdict"]).Verdict.APPROVED,
			score=90, issues=[],
		)

		with patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", return_value=("out", 1)):
			orch._run_pipeline("criar addon")

		assert orch._current_plan is plan

	def test_resume_pula_step_ja_aprovado_e_executa_so_o_restante(self, fake_api_key):
		from nvdastudio.core.orchestrator import Orchestrator, StepResult
		from nvdastudio.core.planner import ExecutionPlan, ExecutionStep
		from nvdastudio.ai.critic import Verdict

		orch = Orchestrator()
		orch._api_key = fake_api_key

		plan = ExecutionPlan(
			plan_id="p1", original_query="criar addon", steps=[
				ExecutionStep("s1", "code_generation", "gerar codigo", "kimi-k2.6"),
				ExecutionStep("s2", "manifest_builder", "gerar manifest", "kimi-k2.6",
							  depends_on=["s1"]),
			],
		)
		orch._critic = MagicMock()
		orch._critic.evaluate_two_stage.return_value = MagicMock(
			verdict=Verdict.APPROVED, score=90, issues=[],
		)

		resume_completed = {
			"s1": StepResult(
				step_id="s1", step_type="code_generation",
				output="codigo ja pronto da tentativa anterior",
				approved=True, score=100,
			),
		}

		dispatch_calls = []

		def fake_dispatch(**kwargs):
			dispatch_calls.append(kwargs)
			return ("manifest gerado", 5)

		with patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", side_effect=fake_dispatch):
			orch._run_pipeline("criar addon", resume_plan=plan, resume_completed=resume_completed)

		# s1 nunca foi redespachado -- so s2 (o que faltava) rodou de verdade.
		assert len(dispatch_calls) == 1
		assert orch._last_result is not None
		step_ids_no_resultado = {r.step_id for r in orch._last_result.step_results}
		assert step_ids_no_resultado == {"s1", "s2"}
		s1_result = next(r for r in orch._last_result.step_results if r.step_id == "s1")
		assert s1_result.output == "codigo ja pronto da tentativa anterior"
		assert orch._current_plan is plan


class TestSurgicalReplanFallback:
	"""Sem plano anterior reaproveitavel, cai pra full replan (execute_normal) --
	comportamento preservado do codigo original."""

	def _make_executor(self):
		from nvdastudio.core.agentic_loop import StrategyExecutor
		orch = MagicMock()
		orch._current_plan = None
		return StrategyExecutor(orch), orch

	def test_sem_current_plan_cai_pra_execute_normal(self):
		executor, orch = self._make_executor()
		with patch.object(executor, "_run_sync", return_value=MagicMock()) as fake_run_sync:
			executor.surgical_replan("criar addon", "s1", [])
		fake_run_sync.assert_called_once()
		args, kwargs = fake_run_sync.call_args
		assert args[0] == "criar addon"
		assert "resume_plan" not in kwargs

	def test_step_id_nao_existe_no_plano_cai_pra_execute_normal(self):
		from nvdastudio.core.planner import ExecutionPlan, ExecutionStep
		executor, orch = self._make_executor()
		orch._current_plan = ExecutionPlan(
			plan_id="p1", original_query="q", steps=[
				ExecutionStep("outro_step", "manifest_builder", "", "kimi-k2.6"),
			],
		)
		with patch.object(executor, "_run_sync", return_value=MagicMock()) as fake_run_sync:
			executor.surgical_replan("criar addon", "s1_que_nao_existe", [])
		args, kwargs = fake_run_sync.call_args
		assert "resume_plan" not in kwargs


class TestSurgicalReplanReaproveitaPlano:
	"""Caminho feliz: plano anterior existe e contem o step que falhou --
	surgical_replan deve passar resume_plan + resume_completed pro _run_sync,
	preservando so os steps aprovados que pertencem a esse plano."""

	def _make_executor_com_plano(self):
		from nvdastudio.core.agentic_loop import StrategyExecutor
		from nvdastudio.core.planner import ExecutionPlan, ExecutionStep

		plan = ExecutionPlan(
			plan_id="p1", original_query="criar addon", steps=[
				ExecutionStep("s1", "code_generation", "", "kimi-k2.6"),
				ExecutionStep("s2", "manifest_builder", "", "kimi-k2.6", depends_on=["s1"]),
				ExecutionStep("s3", "accessibility_audit", "", "kimi-k2.6", depends_on=["s2"]),
			],
		)
		orch = MagicMock()
		orch._current_plan = plan
		return StrategyExecutor(orch), orch, plan

	def test_reusa_plano_e_filtra_apenas_aprovados_do_plano(self):
		from nvdastudio.core.orchestrator import StepResult

		executor, orch, plan = self._make_executor_com_plano()
		prev_step_results = [
			StepResult("s1", "code_generation", "codigo ok", approved=True, score=100),
			StepResult("s2", "manifest_builder", "manifest com erro", approved=False, score=20),
			StepResult("nao_pertence_ao_plano", "web_research", "lixo de outra tentativa",
					   approved=True, score=100),
		]

		with patch.object(executor, "_run_sync", return_value=MagicMock()) as fake_run_sync:
			executor.surgical_replan("criar addon", "s2", prev_step_results)

		fake_run_sync.assert_called_once()
		_, kwargs = fake_run_sync.call_args
		assert kwargs["resume_plan"] is plan
		assert set(kwargs["resume_completed"].keys()) == {"s1"}
		assert kwargs["resume_completed"]["s1"].output == "codigo ok"

	def test_step_que_falhou_nunca_entra_em_resume_completed_mesmo_se_aprovado(self):
		"""Salvaguarda: mesmo que o proprio failed_step_id apareca marcado
		approved=True por engano nos dados anteriores, nunca deve ser reusado --
		e precisamente o step que estamos replanejando."""
		from nvdastudio.core.orchestrator import StepResult

		executor, orch, plan = self._make_executor_com_plano()
		prev_step_results = [
			StepResult("s1", "code_generation", "codigo ok", approved=True, score=100),
			StepResult("s2", "manifest_builder", "inconsistente", approved=True, score=100),
		]

		with patch.object(executor, "_run_sync", return_value=MagicMock()) as fake_run_sync:
			executor.surgical_replan("criar addon", "s2", prev_step_results)

		_, kwargs = fake_run_sync.call_args
		assert "s2" not in kwargs["resume_completed"]


class TestHandlerSurgicalReplanPassaStepResultsReais:
	"""_handler_surgical_replan() nao deve mais descartar prev_result.step_results
	(passava sempre {} pra surgical_replan, tornando resume_completed sempre
	vazio na pratica, mesmo apos a correcao acima)."""

	def test_passa_step_results_de_prev_result(self):
		from nvdastudio.core.agentic_loop import _handler_surgical_replan
		from nvdastudio.core.orchestrator import StepResult
		from nvdastudio.core.orch_types import OrchestrationResult

		step_results = [
			StepResult("s1", "code_generation", "ok", approved=True, score=100),
			StepResult("s2", "manifest_builder", "falhou", approved=False, score=10),
		]
		prev_result = OrchestrationResult(
			plan_id="p1", query="criar addon", step_results=step_results,
			final_output="", success=False,
		)

		fake_executor = MagicMock()
		_handler_surgical_replan(fake_executor, "criar addon", prev_result)

		fake_executor.surgical_replan.assert_called_once_with(
			"criar addon", "s2", step_results,
		)

	def test_sem_prev_result_passa_lista_vazia_e_step_id_vazio(self):
		from nvdastudio.core.agentic_loop import _handler_surgical_replan

		fake_executor = MagicMock()
		_handler_surgical_replan(fake_executor, "criar addon", None)

		fake_executor.surgical_replan.assert_called_once_with("criar addon", "", [])
