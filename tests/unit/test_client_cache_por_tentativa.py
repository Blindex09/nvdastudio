from unittest.mock import patch

from nvdastudio.ai.critic import CriticResult, Verdict


class TestClearClientCacheAcadaTentativa:
	def test_clear_client_cache_chamado_em_cada_retry(self, fake_api_key):
		from nvdastudio.core.orchestrator import Orchestrator
		from nvdastudio.core.planner import ExecutionStep
		import nvdastudio.core.orchestrator as orch_mod

		orch = Orchestrator()
		orch._api_key = fake_api_key
		orch.initialize()
		step = ExecutionStep(
			step_id="s1", step_type="agent_runner",
			description="gerar agent_runner", model_id="deepseek-v4-flash",
			max_retries=3,
		)

		rejeitado = CriticResult(verdict=Verdict.NEEDS_FIX, score=10,
								  issues=["sem classe AgentRunner"], fix_instructions="corrija")
		aprovado = CriticResult(verdict=Verdict.APPROVED, score=90, issues=[], fix_instructions="")

		clear_calls = {"count": 0}

		def fake_clear():
			clear_calls["count"] += 1

		with patch.object(orch_mod, "clear_client_cache", side_effect=fake_clear), \
			patch.object(orch, "_dispatch_with_heartbeat", return_value=("output", 10)), \
			patch.object(orch._critic, "evaluate_two_stage", side_effect=[rejeitado, rejeitado, aprovado]):
			result = orch._execute_step_with_critique(step, "query", "")

		assert result.approved is True
		# 1x antes do loop + 1x por tentativa (3 tentativas) = 4.
		assert clear_calls["count"] == 4, (
			f"esperado clear_client_cache() 4x (1 antes do loop + 3 tentativas), "
			f"recebido {clear_calls['count']}x -- regressao do fix de cache "
			f"por tentativa (orchestrator.py 5.32.0)"
		)

	def test_apenas_uma_chamada_nao_regride(self, fake_api_key):
		"""Confirma que o fix nao quebrou o caminho de sucesso na 1a tentativa."""
		from nvdastudio.core.orchestrator import Orchestrator
		from nvdastudio.core.planner import ExecutionStep
		import nvdastudio.core.orchestrator as orch_mod

		orch = Orchestrator()
		orch._api_key = fake_api_key
		orch.initialize()
		step = ExecutionStep(
			step_id="s1", step_type="manifest_builder",
			description="gerar manifest", model_id="deepseek-v4-flash",
			max_retries=1,
		)

		aprovado = CriticResult(verdict=Verdict.APPROVED, score=95, issues=[], fix_instructions="")

		clear_calls = {"count": 0}

		def fake_clear():
			clear_calls["count"] += 1

		with patch.object(orch_mod, "clear_client_cache", side_effect=fake_clear), \
			patch.object(orch, "_dispatch_with_heartbeat", return_value=("output", 10)), \
			patch.object(orch._critic, "evaluate_two_stage", return_value=aprovado):
			result = orch._execute_step_with_critique(step, "query", "")

		assert result.approved is True
		assert clear_calls["count"] == 2  # 1 antes do loop + 1 na unica tentativa
