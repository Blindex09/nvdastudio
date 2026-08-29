import inspect


class TestSessionRecapModuloEnxuto:
	"""1.1.0: extract_user_preferences() (no-op permanente) e
	save_session_learnings() (duplicava memory_manager.learn_from_session())
	foram removidas -- so build_session_recap() (a funcao que produz algo
	genuinamente novo) permanece."""

	def test_extract_user_preferences_nao_existe_mais(self):
		import nvdastudio.memory.session_recap as recap_mod
		assert not hasattr(recap_mod, "extract_user_preferences")

	def test_save_session_learnings_nao_existe_mais(self):
		import nvdastudio.memory.session_recap as recap_mod
		assert not hasattr(recap_mod, "save_session_learnings")

	def test_build_session_recap_ainda_existe(self):
		from nvdastudio.memory.session_recap import build_session_recap
		assert callable(build_session_recap)


class TestOrchestratorChamaLogSessionRecap:
	def test_log_session_recap_existe_no_orchestrator(self):
		from nvdastudio.core.orchestrator import Orchestrator
		assert hasattr(Orchestrator, "_log_session_recap")

	def test_run_conversational_pipeline_chama_log_session_recap(self):
		from nvdastudio.core import orchestrator
		src = inspect.getsource(orchestrator.Orchestrator._run_conversational_pipeline)
		assert "self._log_session_recap(" in src

	def test_run_pipeline_chama_log_session_recap(self):
		from nvdastudio.core import orchestrator
		src = inspect.getsource(orchestrator.Orchestrator._run_pipeline)
		assert "self._log_session_recap(" in src

	def test_log_session_recap_nao_expoe_ao_usuario(self):
		"""Mesma decisao de UX do checkpoint 5.4.0: metricas tecnicas ficam
		no log, nunca em _emit_conversation/on_complete direto pro usuario."""
		from nvdastudio.core import orchestrator
		src = inspect.getsource(orchestrator.Orchestrator._log_session_recap)
		assert "_logger.info(" in src
		assert "_emit_conversation" not in src

	def test_log_session_recap_nao_lanca_excecao_com_dados_minimos(self):
		from nvdastudio.core.orchestrator import Orchestrator
		from nvdastudio.core.orch_types import OrchestrationResult

		orch = Orchestrator.__new__(Orchestrator)
		result = OrchestrationResult(
			plan_id="p1", query="q", step_results=[],
			final_output="", success=True, total_tokens=0,
		)
		orch._log_session_recap("query de teste", result, [])
