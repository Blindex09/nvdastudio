from nvdastudio.core.orch_types import StepResult


class TestStepResultModelIdSync:
	def test_model_id_e_populado_a_partir_de_model_used(self):
		result = StepResult(
			step_id="s1", step_type="code_generation", output="x",
			approved=True, score=90, model_used="kimi-k2.7-code",
		)
		assert result.model_id == "kimi-k2.7-code"

	def test_model_used_e_populado_a_partir_de_model_id(self):
		result = StepResult(
			step_id="s1", step_type="code_generation", output="x",
			approved=True, score=90, model_id="kimi-k2.7-code",
		)
		assert result.model_used == "kimi-k2.7-code"

	def test_sem_nenhum_dos_dois_permanece_vazio(self):
		result = StepResult(
			step_id="s1", step_type="code_generation", output="x",
			approved=True, score=90,
		)
		assert result.model_id == ""
		assert result.model_used == ""

	def test_final_model_used_do_ultimo_step_nao_fica_vazio(self):
		"""Reproduz o read site real: orchestrator.py:1630
		final_model_used=step_results[-1].model_id."""
		step_results = [
			StepResult(
				step_id="s1", step_type="manifest_builder", output="x",
				approved=True, score=100, model_used="kimi-k2.6",
			),
			StepResult(
				step_id="s2", step_type="assembly", output="x",
				approved=True, score=100, model_used="deepseek-v4-flash",
			),
		]
		final_model_used = step_results[-1].model_id if step_results else "unknown"
		assert final_model_used == "deepseek-v4-flash"
