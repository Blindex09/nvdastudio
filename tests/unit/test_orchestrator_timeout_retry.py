import time
from unittest.mock import patch

from nvdastudio.core.orchestrator import Orchestrator, StepResult
from nvdastudio.core.planner import ExecutionStep


def _make_orchestrator(fake_api_key):
	orch = Orchestrator()
	orch._api_key = fake_api_key
	orch.initialize()
	return orch


class TestTimeoutResultOrEscalate:
	def test_step_type_nao_elegivel_nao_chama_escalacao(self, fake_api_key):
		"""manifest_builder nao esta em _ESCALATION_ELIGIBLE_STEP_TYPES --
		deve voltar direto pro StepResult score=0 antigo, sem tentar escalar."""
		orch = _make_orchestrator(fake_api_key)
		step = ExecutionStep(
			step_id="s1", step_type="manifest_builder",
			description="gerar manifest", model_id="deepseek-v4-flash",
		)
		with patch.object(orch, "_try_escalation") as mock_escalate:
			result = orch._timeout_result_or_escalate(step, "query", "", "Timeout: step excedeu 180s.")
		mock_escalate.assert_not_called()
		assert result.approved is False
		assert result.score == 0
		assert any("Timeout" in i for i in result.issues)

	def test_step_type_elegivel_tenta_escalacao(self, fake_api_key):
		"""code_generation esta em _ESCALATION_ELIGIBLE_STEP_TYPES -- deve
		tentar _try_escalation() e devolver o resultado dela, nao desistir na hora."""
		orch = _make_orchestrator(fake_api_key)
		step = ExecutionStep(
			step_id="s1", step_type="code_generation",
			description="gerar codigo", model_id="qwen3.5:397b",
		)
		escalated_result = StepResult(
			step_id="s1", step_type="code_generation",
			output="codigo resgatado", approved=True, score=90,
			retries_used=1, model_used="modelo-resiliente",
		)
		with patch.object(orch, "_try_escalation", return_value=escalated_result) as mock_escalate:
			result = orch._timeout_result_or_escalate(step, "query", "ctx", "Timeout: step excedeu 1200s.")
		mock_escalate.assert_called_once()
		call_kwargs = mock_escalate.call_args
		assert call_kwargs.args[0] is step
		assert result.approved is True
		assert result.output == "codigo resgatado"

	def test_escalacao_com_excecao_cai_para_timeout_simples(self, fake_api_key):
		"""Se a propria tentativa de escalacao falhar (ex: outra excecao de
		rede), nao deve propagar -- cai de volta pro StepResult score=0."""
		orch = _make_orchestrator(fake_api_key)
		step = ExecutionStep(
			step_id="s1", step_type="agent_runner",
			description="gerar agent_runner", model_id="deepseek-v4-flash",
		)
		with patch.object(orch, "_try_escalation", side_effect=RuntimeError("falha de rede")):
			result = orch._timeout_result_or_escalate(step, "query", "", "Timeout: step excedeu 600s.")
		assert result.approved is False
		assert result.score == 0
		assert any("Timeout" in i for i in result.issues)


class TestRunIsolatedStepNaoBloqueiaAposTimeout:
	def test_nao_espera_thread_travada_apos_timeout(self, fake_api_key):
		"""Bug real: `with ThreadPoolExecutor() as _pex:` bloqueava no
		__exit__ esperando a thread travada terminar, mesmo apos o timeout
		logico. Este teste prova que _run_isolated_step() retorna rapido
		(shutdown(wait=False)) mesmo quando a chamada de baixo nivel
		demoraria muito mais que o timeout configurado."""
		orch = _make_orchestrator(fake_api_key)
		step = ExecutionStep(
			step_id="s1", step_type="manifest_builder",  # nao-escalavel: caminho simples
			description="gerar manifest", model_id="deepseek-v4-flash",
		)

		def _slow_call(*args, **kwargs):
			time.sleep(2.0)
			return StepResult(step_id="s1", step_type="manifest_builder", output="tarde demais", approved=True, score=90)

		with patch("nvdastudio.core.orchestrator._get_step_timeout", return_value=0.2), \
			patch.object(orch, "_execute_step_with_critique", side_effect=_slow_call):
			start = time.perf_counter()
			result = orch._run_isolated_step(step, "query", "")
			elapsed = time.perf_counter() - start

		assert elapsed < 1.0, (
			f"_run_isolated_step() levou {elapsed:.2f}s para retornar apos um timeout "
			f"de 0.2s -- regressao do bug 'with ThreadPoolExecutor() as _pex:' "
			f"que bloqueava no __exit__ esperando a thread travada (orchestrator.py 5.51.0)."
		)
		assert result.approved is False
		assert result.score == 0
		assert any("Timeout" in i for i in result.issues)

	def test_escalacao_eh_tentada_apos_timeout_para_step_elegivel(self, fake_api_key):
		orch = _make_orchestrator(fake_api_key)
		step = ExecutionStep(
			step_id="s6", step_type="code_generation",
			description="gerar codigo", model_id="qwen3.5:397b",
		)

		def _slow_call(*args, **kwargs):
			time.sleep(2.0)
			return StepResult(step_id="s6", step_type="code_generation", output="tarde demais", approved=True, score=90)

		escalated_result = StepResult(
			step_id="s6", step_type="code_generation",
			output="codigo resgatado via escalacao", approved=True, score=85,
			retries_used=1, model_used="modelo-resiliente",
		)
		with patch("nvdastudio.core.orchestrator._get_step_timeout", return_value=0.2), \
			patch.object(orch, "_execute_step_with_critique", side_effect=_slow_call), \
			patch.object(orch, "_try_escalation", return_value=escalated_result) as mock_escalate:
			result = orch._run_isolated_step(step, "query", "")

		mock_escalate.assert_called_once()
		assert result.approved is True
		assert result.output == "codigo resgatado via escalacao"

	def test_resultado_normal_dentro_do_timeout_nao_e_afetado(self, fake_api_key):
		"""Confirma que o fix nao quebrou o caminho feliz (step completa
		dentro do timeout, sem nunca disparar FuturesTimeout)."""
		orch = _make_orchestrator(fake_api_key)
		step = ExecutionStep(
			step_id="s1", step_type="manifest_builder",
			description="gerar manifest", model_id="deepseek-v4-flash",
		)
		fast_result = StepResult(step_id="s1", step_type="manifest_builder", output="ok", approved=True, score=95)
		with patch.object(orch, "_execute_step_with_critique", return_value=fast_result):
			result = orch._run_isolated_step(step, "query", "")
		assert result.approved is True
		assert result.output == "ok"
