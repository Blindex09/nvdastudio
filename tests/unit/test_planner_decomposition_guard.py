import json


def test_guard_detecta_code_generation_grande_demais():
	from nvdastudio.core.planner import (
		ExecutionStep,
		STEP_CODE_GENERATION,
		oversized_code_generation_steps,
	)

	step = ExecutionStep(
		step_id="cg_grande",
		step_type=STEP_CODE_GENERATION,
		description="x" * 1801,
		model_id="test-model",
	)

	assert oversized_code_generation_steps([step]) == ["cg_grande"]


def test_planner_replaneja_subtarefa_grande(monkeypatch):
	from nvdastudio.core.planner import Planner

	first = {
		"complexity": "medium",
		"project_type": "addon",
		"addon_name": "MeuAddon",
		"steps": [{
			"step_id": "cg_grande",
			"step_type": "code_generation",
			"description": "x" * 1801,
			"expected_output": "Python",
		}],
	}
	second = {
		"complexity": "medium",
		"project_type": "addon",
		"addon_name": "MeuAddon",
		"steps": [{
			"step_id": "cg_feature_a",
			"step_type": "code_generation",
			"description": "Implementar somente a feature A",
			"expected_output": "Python",
		}],
	}
	responses = iter([json.dumps(first), json.dumps(second)])
	planner = Planner()
	monkeypatch.setattr(planner, "_call_planner_llm", lambda *args, **kwargs: next(responses))

	plan = planner.create_plan("crie um addon com duas features")

	assert plan.steps
	assert "cg_feature_a" in {step.step_id for step in plan.steps}
