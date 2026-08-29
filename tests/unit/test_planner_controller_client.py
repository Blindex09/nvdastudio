import json
from unittest.mock import MagicMock, patch

from nvdastudio.core.planner import (
	Planner, ExecutionPlan,
	STEP_MANIFEST, STEP_ACCESSIBILITY_AUDIT, STEP_DESIGN_REVIEW,
	_PLAN_SYSTEM_PROMPT,
)


def _mock_planner(plan_json: dict) -> Planner:
	mock_response = MagicMock()
	mock_response.content = json.dumps(plan_json)
	mock_response.reasoning = None
	patcher = patch("nvdastudio.core.planner.create_llm_client")
	MockClient = patcher.start()
	MockClient.return_value.chat.return_value = mock_response
	return Planner(), patcher


class TestProjectTypePropagacao:
	def test_default_e_addon_quando_ausente_no_json(self, valid_plan_json):
		planner, patcher = _mock_planner(valid_plan_json)
		try:
			plan = planner.create_plan("crie um addon simples")
		finally:
			patcher.stop()
		assert isinstance(plan, ExecutionPlan)
		assert plan.project_type == "addon"

	def test_controller_client_propagado_do_json(self, valid_plan_json):
		data = dict(valid_plan_json)
		data["project_type"] = "controller_client"
		planner, patcher = _mock_planner(data)
		try:
			plan = planner.create_plan("crie um programa que fala pelo NVDA de fora")
		finally:
			patcher.stop()
		assert plan.project_type == "controller_client"


class TestInjecaoCondicionalPorProjectType:
	"""_inject_manifest/_inject_accessibility_audit/_inject_design_review sao
	exclusivos de project_type=='addon' -- nao fazem sentido pra um programa
	externo sem manifest.ini/globalPlugins/."""

	def _plan_controller_client(self):
		return {
			"complexity": "high",
			"project_type": "controller_client",
			"requires_web_research": False,
			"requires_agent_runner": False,
			"steps": [
				{
					"step_id": "s1",
					"step_type": "code_generation",
					"description": "Gerar o programa cliente",
					"expected_output": "codigo Python completo",
					"depends_on": [],
					"context_from_steps": [],
				},
				{
					"step_id": "s2",
					"step_type": "assembly",
					"description": "Montar artefatos finais",
					"expected_output": "programa completo",
					"depends_on": ["s1"],
					"context_from_steps": ["s1"],
				},
			],
		}

	def test_nao_injeta_manifest_builder(self):
		planner, patcher = _mock_planner(self._plan_controller_client())
		try:
			plan = planner.create_plan("crie um programa externo que fala pelo NVDA")
		finally:
			patcher.stop()
		step_types = {s.step_type for s in plan.steps}
		assert STEP_MANIFEST not in step_types

	def test_nao_injeta_accessibility_audit(self):
		planner, patcher = _mock_planner(self._plan_controller_client())
		try:
			plan = planner.create_plan("crie um programa externo que fala pelo NVDA")
		finally:
			patcher.stop()
		step_types = {s.step_type for s in plan.steps}
		assert STEP_ACCESSIBILITY_AUDIT not in step_types

	def test_nao_injeta_design_review_mesmo_com_complexity_high(self):
		planner, patcher = _mock_planner(self._plan_controller_client())
		try:
			plan = planner.create_plan("crie um programa externo que fala pelo NVDA")
		finally:
			patcher.stop()
		step_types = {s.step_type for s in plan.steps}
		assert STEP_DESIGN_REVIEW not in step_types

	def test_addon_high_complexity_continua_injetando_design_review(self, valid_plan_json):
		"""Regressao: o guard novo nao pode quebrar o comportamento padrao
		(project_type=='addon', ja coberto por TestPlannerDesignReview em
		test_planner.py, mas confirmado aqui tambem pelo angulo do guard novo)."""
		data = dict(valid_plan_json)
		data["complexity"] = "high"
		planner, patcher = _mock_planner(data)
		try:
			plan = planner.create_plan("crie um addon complexo")
		finally:
			patcher.stop()
		step_types = {s.step_type for s in plan.steps}
		assert STEP_DESIGN_REVIEW in step_types

	def test_addon_continua_injetando_manifest_e_accessibility(self, valid_plan_json):
		planner, patcher = _mock_planner(valid_plan_json)
		try:
			plan = planner.create_plan("crie um addon simples")
		finally:
			patcher.stop()
		step_types = {s.step_type for s in plan.steps}
		assert STEP_MANIFEST in step_types
		assert STEP_ACCESSIBILITY_AUDIT in step_types


class TestPlanSchemaTemProjectType:
	def test_system_prompt_explica_project_type(self):
		assert "project_type" in _PLAN_SYSTEM_PROMPT
		assert "controller_client" in _PLAN_SYSTEM_PROMPT

	def test_system_prompt_nao_injeta_manifest_builder_pra_controller_client(self):
		"""A secao nova deve instruir explicitamente a nao incluir
		manifest_builder/accessibility_audit/agent_template quando
		controller_client."""
		idx = _PLAN_SYSTEM_PROMPT.find("controller_client")
		assert idx != -1
		trecho = _PLAN_SYSTEM_PROMPT[idx:idx + 800]
		assert "manifest_builder" in trecho
