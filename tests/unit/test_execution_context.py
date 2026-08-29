from types import SimpleNamespace


def test_context_store_persiste_e_recupera_apenas_steps_relevantes(tmp_path):
	from nvdastudio.core.execution_context import ExecutionContextStore

	store = ExecutionContextStore(str(tmp_path))
	plan = SimpleNamespace(plan_id="p1", original_query="criar addon", addon_name="MeuAddon", project_type="addon")
	step_a = SimpleNamespace(step_id="a", step_type="code_generation", description="feature A")
	step_b = SimpleNamespace(step_id="b", step_type="documentation", description="docs")
	result_a = SimpleNamespace(approved=True, score=95, issues=[], output="ARTEFATO_A")
	result_b = SimpleNamespace(approved=False, score=20, issues=["erro de docs"], output="SAIDA_B")

	store.save_step(plan, step_a, result_a)
	store.save_step(plan, step_b, result_b)

	context = store.get_context("p1", ["b"], max_chars=1000)
	assert "SAIDA_B" in context
	assert "ARTEFATO_A" not in context
	assert "erro de docs" in context


def test_context_store_respeita_limite_de_tamanho(tmp_path):
	from nvdastudio.core.execution_context import ExecutionContextStore

	store = ExecutionContextStore(str(tmp_path))
	plan = SimpleNamespace(plan_id="p2", original_query="q", addon_name="A", project_type="addon")
	step = SimpleNamespace(step_id="a", step_type="code_generation", description="feature")
	result = SimpleNamespace(approved=True, score=100, issues=[], output="x" * 12000)
	store.save_step(plan, step, result)

	assert len(store.get_context("p2", ["a"], max_chars=300)) <= 300
