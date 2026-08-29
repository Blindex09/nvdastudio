from nvdastudio.core.orchestrator import Orchestrator, _critic_context
from nvdastudio.core.orch_types import StepResult
from nvdastudio.core.planner import ExecutionPlan, ExecutionStep
from nvdastudio.builder.controller_client_context import is_controller_client_context


def _step(step_id="s1", step_type="code_generation", description="Gerar o programa"):
	return ExecutionStep(
		step_id=step_id, step_type=step_type, description=description,
		model_id="kimi-k2.6",
	)


def _plan(project_type="addon", steps=None):
	return ExecutionPlan(
		plan_id="p1", original_query="q", steps=steps or [], project_type=project_type,
	)


class TestProjectTypeHelper:
	def test_default_addon_quando_sem_plano(self):
		orch = Orchestrator()
		assert orch._project_type() == "addon"

	def test_le_do_plano_atual(self):
		orch = Orchestrator()
		orch._current_plan = _plan(project_type="controller_client")
		assert orch._project_type() == "controller_client"

	def test_nao_quebra_com_orchestrator_new_sem_init(self):
		"""Regressao: achada ao rodar a suite completa apos o fix 5.50.0 --
		varios testes existentes (tests/integration/test_orchestrator.py)
		instanciam via Orchestrator.__new__(Orchestrator) pra pular o
		__init__ pesado, entao _current_plan nunca chega a ser setado como
		atributo (nem None) -- self._current_plan direto estourava
		AttributeError em vez de cair no fallback "addon". Corrigido com
		getattr(self, "_current_plan", None)."""
		orch = Orchestrator.__new__(Orchestrator)
		assert "_current_plan" not in orch.__dict__, "precondicao do teste: __new__() nao deve ter setado o atributo"
		assert orch._project_type() == "addon"


class TestBuildStepPromptMarcador:
	def test_marca_prompt_quando_controller_client(self):
		orch = Orchestrator()
		orch._current_plan = _plan(project_type="controller_client")
		prompt = orch._build_step_prompt(_step(), "pedido original", "", [])
		assert is_controller_client_context(prompt)

	def test_nao_marca_prompt_para_addon(self):
		orch = Orchestrator()
		orch._current_plan = _plan(project_type="addon")
		prompt = orch._build_step_prompt(_step(), "pedido original", "", [])
		assert not is_controller_client_context(prompt)

	def test_marcador_vem_antes_da_tarefa_original(self):
		"""Primazia de atencao (lost-in-middle) -- o marcador tem que ser
		literalmente o inicio do prompt, nao so estar presente em algum lugar."""
		orch = Orchestrator()
		orch._current_plan = _plan(project_type="controller_client")
		prompt = orch._build_step_prompt(_step(), "pedido original", "", [])
		idx_marcador = prompt.find("[PROJECT_TYPE: controller_client")
		idx_tarefa = prompt.find("Tarefa original do usuario")
		assert idx_marcador == 0
		assert idx_marcador < idx_tarefa


class TestCriticContextProjectType:
	def test_default_project_type_addon_sem_marcador(self):
		ctx = _critic_context(_step(), "contexto")
		assert not is_controller_client_context(ctx)

	def test_controller_client_prepende_marcador(self):
		ctx = _critic_context(_step(), "contexto", project_type="controller_client")
		assert is_controller_client_context(ctx)

	def test_controller_client_preserva_objetivo_do_step(self):
		"""O marcador nao pode substituir o 'Objetivo deste step' -- so
		vem ANTES dele (mesmo racional do fix 5.44.0 de _critic_context)."""
		ctx = _critic_context(_step(description="Gerar wrapper ctypes"), "contexto", project_type="controller_client")
		assert "Objetivo deste step: Gerar wrapper ctypes" in ctx
		assert "contexto" in ctx

	def test_controller_client_sem_context_nem_description(self):
		step_sem_desc = ExecutionStep(step_id="s1", step_type="code_generation", description="", model_id="m")
		ctx = _critic_context(step_sem_desc, "", project_type="controller_client")
		assert is_controller_client_context(ctx)


class TestValidateMinimumArtifactsControllerClient:
	def _outputs_com_python_sem_manifest(self):
		return {
			"s1": "```python:nvda_client.py\nimport ctypes\n```",
		}

	def test_controller_client_nao_exige_manifest(self):
		plan = _plan(project_type="controller_client", steps=[_step()])
		results = [StepResult(step_id="s1", step_type="code_generation", output="", approved=True, score=100)]
		outputs = self._outputs_com_python_sem_manifest()
		erro = Orchestrator._validate_minimum_addon_artifacts(plan, results, outputs)
		assert erro == ""

	def test_addon_continua_exigindo_manifest(self):
		"""Regressao: o guard novo nao pode afrouxar a exigencia pra addons."""
		plan = _plan(project_type="addon", steps=[_step()])
		results = [StepResult(step_id="s1", step_type="code_generation", output="", approved=True, score=100)]
		outputs = self._outputs_com_python_sem_manifest()
		erro = Orchestrator._validate_minimum_addon_artifacts(plan, results, outputs)
		assert "manifest.ini" in erro

	def test_controller_client_ainda_exige_algum_python(self):
		plan = _plan(project_type="controller_client", steps=[_step()])
		results = [StepResult(step_id="s1", step_type="code_generation", output="", approved=True, score=100)]
		erro = Orchestrator._validate_minimum_addon_artifacts(plan, results, {"s1": "so texto, sem bloco de codigo"})
		assert "Python" in erro
