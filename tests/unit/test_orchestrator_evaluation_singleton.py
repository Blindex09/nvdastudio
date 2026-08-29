import inspect


class TestEvaluationUsaInstanciaGlobal:
	def test_orchestrator_nao_instancia_pipelineevaluator_do_zero(self):
		"""O bloco WIRING nao pode mais criar PipelineEvaluator() novo --
		isso descartava todo o historico a cada chamada. Verifica o padrao
		exato de atribuicao (nao a mera mencao em prosa/changelog, que cita
		o bug historico de proposito)."""
		from nvdastudio.core import orchestrator as orchestrator_mod

		src = inspect.getsource(orchestrator_mod)
		assert "= PipelineEvaluator()" not in src, (
			"orchestrator.py nao deve mais instanciar PipelineEvaluator() do zero -- "
			"use a instancia global `evaluation` de evaluation_framework.py"
		)

	def test_orchestrator_importa_a_instancia_global_evaluation(self):
		from nvdastudio.core import orchestrator as orchestrator_mod

		src = inspect.getsource(orchestrator_mod)
		assert "from ..utils.evaluation_framework import evaluation" in src

	def test_evaluation_singleton_acumula_entre_chamadas(self):
		"""Prova indireta do bug original: uma instancia NOVA de
		PipelineEvaluator() a cada chamada nunca acumularia historico --
		a instancia global `evaluation` (o que orchestrator.py agora usa)
		acumula normalmente entre chamadas, no mesmo processo."""
		from nvdastudio.utils.evaluation_framework import evaluation

		total_antes = len(evaluation._metrics)
		evaluation.record_pipeline_result(
			success=True, token_count=100, duration_seconds=1.0, issues=[],
		)
		evaluation.record_pipeline_result(
			success=True, token_count=200, duration_seconds=2.0, issues=[],
		)
		assert len(evaluation._metrics) == total_antes + 2, (
			"A instancia global deveria acumular historico entre chamadas -- "
			"uma PipelineEvaluator() nova a cada vez nunca acumularia nada"
		)
