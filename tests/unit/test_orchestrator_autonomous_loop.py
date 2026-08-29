import time
from unittest.mock import MagicMock, patch



class TestOrchestratorAutonomousLoop:
    def _make_orchestrator(self):
        from nvdastudio.core.orchestrator import Orchestrator
        orch = Orchestrator()
        orch.initialize()
        return orch

    def test_orchestration_result_has_loop_count(self):
        from nvdastudio.core.orch_types import OrchestrationResult
        r = OrchestrationResult(
            plan_id="abc", query="q", step_results=[],
            final_output="", success=True,
            autonomous_loop_count=2,
        )
        assert r.autonomous_loop_count == 2

    def test_compute_progress_more_approved(self):
        from nvdastudio.core.orchestrator import Orchestrator
        from nvdastudio.core.orch_types import OrchestrationResult, StepResult
        orch = Orchestrator()
        prev = OrchestrationResult(
            plan_id="p", query="q", step_results=[
                StepResult("s1", "code", "out", approved=False, score=0, issues=["err"]),
            ],
            final_output="x", success=False, all_issues=["err"],
        )
        curr = OrchestrationResult(
            plan_id="p", query="q", step_results=[
                StepResult("s1", "code", "out", approved=True, score=90, issues=[]),
            ],
            final_output="x", success=False, all_issues=[],
        )
        score, reason = orch._compute_progress(prev, curr)
        assert score >= 40
        assert "aprovado" in reason

    def test_compute_progress_fewer_issues(self):
        from nvdastudio.core.orchestrator import Orchestrator
        from nvdastudio.core.orch_types import OrchestrationResult, StepResult
        orch = Orchestrator()
        prev = OrchestrationResult(
            plan_id="p", query="q", step_results=[
                StepResult("s1", "code", "out", approved=False, score=0, issues=["a", "b", "c"]),
            ],
            final_output="x", success=False, all_issues=["a", "b", "c"],
        )
        curr = OrchestrationResult(
            plan_id="p", query="q", step_results=[
                StepResult("s1", "code", "out", approved=False, score=0, issues=["a"]),
            ],
            final_output="x", success=False, all_issues=["a"],
        )
        score, reason = orch._compute_progress(prev, curr)
        assert score >= 30
        assert "issues" in reason

    def test_compute_progress_stagnation(self):
        from nvdastudio.core.orchestrator import Orchestrator
        from nvdastudio.core.orch_types import OrchestrationResult, StepResult
        orch = Orchestrator()
        prev = OrchestrationResult(
            plan_id="p", query="q", step_results=[
                StepResult("s1", "code", "out", approved=False, score=0, issues=["err"]),
            ],
            final_output="x", success=False, all_issues=["err"],
        )
        curr = OrchestrationResult(
            plan_id="p", query="q", step_results=[
                StepResult("s1", "code", "out", approved=False, score=0, issues=["err"]),
            ],
            final_output="x", success=False, all_issues=["err"],
        )
        score, reason = orch._compute_progress(prev, curr)
        assert score < 15  # _PROGRESS_SCORE_MIN
        assert "estagnacao" in reason or score == 0

    def test_compute_progress_longer_output(self):
        from nvdastudio.core.orchestrator import Orchestrator
        from nvdastudio.core.orch_types import OrchestrationResult, StepResult
        orch = Orchestrator()
        prev = OrchestrationResult(
            plan_id="p", query="q", step_results=[
                StepResult("s1", "code", "out", approved=False, score=0, issues=["err"]),
            ],
            final_output="x" * 10, success=False, all_issues=["err"],
        )
        curr = OrchestrationResult(
            plan_id="p", query="q", step_results=[
                StepResult("s1", "code", "out", approved=False, score=0, issues=["err"]),
            ],
            final_output="x" * 100, success=False, all_issues=["err"],
        )
        score, reason = orch._compute_progress(prev, curr)
        assert score >= 20
        assert "chars" in reason

    def test_run_until_success_succeeds_first_try(self):
        from nvdastudio.core.agentic_loop import AgenticLoop
        from nvdastudio.core.orch_types import OrchestrationResult
        orch = self._make_orchestrator()
        results = []

        def on_complete(result):
            results.append(result)

        orch.set_callbacks(on_progress=lambda e, d: None, on_complete=on_complete)

        def fake_execute_state(self, state, query, prev_result):
            return OrchestrationResult(
                plan_id="p", query=query, step_results=[],
                final_output="ok", success=True,
            )

        with patch.object(AgenticLoop, '_execute_state', fake_execute_state):
            orch._run_until_success("crie addon simples")

        assert len(results) == 1
        assert results[0].success is True

    def test_run_until_success_gives_up_on_stagnation(self):
        """
        Se 3 tentativas consecutivas tem exatamente os mesmos resultados
        (estagnacao), o loop desiste ANTES do hard ceiling.
        """
        from nvdastudio.core.agentic_loop import AgenticLoop
        from nvdastudio.core.orch_types import OrchestrationResult, StepResult
        orch = self._make_orchestrator()
        results = []

        def on_complete(result):
            results.append(result)

        orch.set_callbacks(on_progress=lambda e, d: None, on_complete=on_complete)

        attempt = 0

        def fake_execute_state(self, state, query, prev_result):
            nonlocal attempt
            attempt += 1
            return OrchestrationResult(
                plan_id="p", query=query, step_results=[
                    StepResult("s1", "code", "out", approved=False, score=0, issues=["same_error"]),
                ],
                final_output="same", success=False,
                all_issues=["same_error"], total_retries=2,
            )

        with patch.object(AgenticLoop, '_execute_state', fake_execute_state):
            orch._run_until_success("query que nao funciona")

        # Deve parar por estagnacao (streak_no_progress=3), nao por hard ceiling
        assert attempt <= 5  # bem abaixo do hard ceiling de 10
        assert results[0].success is False
        # autonomous_loop_count conta iteracoes da FSM (mais que execute_state calls)
        assert results[0].autonomous_loop_count > 0

    def test_run_until_success_continues_while_progressing(self):
        """
        Enquanto houver progresso real, continua tentando — mesmo que ja tenha
        falhado varias vezes.
        """
        from nvdastudio.core.agentic_loop import AgenticLoop
        from nvdastudio.core.orch_types import OrchestrationResult, StepResult
        orch = self._make_orchestrator()
        attempt = 0

        def fake_execute_state(self, state, query, prev_result):
            nonlocal attempt
            attempt += 1
            # Simula progresso gradual: +1 step aprovado a cada tentativa
            steps = []
            for i in range(attempt):
                steps.append(StepResult(
                    f"s{i}", "code", f"out{i}",
                    approved=(i < attempt - 1),  # todos aprovados exceto o ultimo
                    score=90 if i < attempt - 1 else 0,
                    issues=[] if i < attempt - 1 else ["err"],
                ))
            return OrchestrationResult(
                plan_id="p", query=query, step_results=steps,
                final_output="x" * (attempt * 100),
                success=False,
                all_issues=["err"] if attempt <= 5 else [],
                total_retries=max(0, 5 - attempt),
            )

        with patch.object(AgenticLoop, '_execute_state', fake_execute_state):
            orch._run_until_success("query dificil")

        # Com progresso detectado, deve tentar mais de 3x
        assert attempt > 3

    def test_run_async_starts_run_until_success(self):
        from nvdastudio.core.orchestrator import Orchestrator
        orch = Orchestrator()
        orch.initialize()

        with patch.object(orch, "_run_until_success") as mock_loop:
            orch.run_async("crie addon")
            time.sleep(0.2)
            mock_loop.assert_called_once_with("crie addon")


class TestEnsembleVerifyUsaResultadoVerificado:
    """Bug corrigido: ensemble_verify calculava consenso/arbitragem mas
    descartava o resultado, sempre reexecutando com a query original.
    Agora o resultado escolhido (convergente ou arbitrado) e injetado
    como hint na query, igual as demais estrategias da FSM."""

    def _make_executor(self):
        from nvdastudio.core.agentic_loop import StrategyExecutor
        return StrategyExecutor(MagicMock())

    def test_modelos_convergentes_usa_resultado_verificado(self):
        executor = self._make_executor()
        resposta_igual = "codigo do manifest gerado igualzinho pelos dois modelos"

        mock_client = MagicMock()
        mock_client.chat.side_effect = [
            MagicMock(content=resposta_igual),
            MagicMock(content=resposta_igual),
            MagicMock(content='{"choice":"first"}'),
        ]

        captured = {}

        def fake_run_sync(query):
            captured["query"] = query
            return MagicMock()

        with patch("nvdastudio.ai.llm_factory.create_llm_client", return_value=mock_client), \
             patch.object(executor, "_run_sync", side_effect=fake_run_sync):
            executor.ensemble_verify("crie o addon X", "manifest_builder")

        assert "RESULTADO VERIFICADO" in captured["query"]
        assert resposta_igual in captured["query"]

    def test_modelos_divergentes_arbitro_escolhe_a_usa_resultado_de_a(self):
        executor = self._make_executor()

        resultado_a = "versao A do manifest, bem diferente"
        resultado_b = "versao B completamente distinta da A"

        chat_calls = {"n": 0}

        def fake_chat(*args, **kwargs):
            chat_calls["n"] += 1
            if chat_calls["n"] == 1:
                return MagicMock(content=resultado_a)
            if chat_calls["n"] == 2:
                return MagicMock(content=resultado_b)
            return MagicMock(content='{"choice":"first"}')

        mock_client = MagicMock()
        mock_client.chat.side_effect = fake_chat

        captured = {}

        def fake_run_sync(query):
            captured["query"] = query
            return MagicMock()

        with patch("nvdastudio.ai.llm_factory.create_llm_client", return_value=mock_client), \
             patch.object(executor, "_run_sync", side_effect=fake_run_sync):
            executor.ensemble_verify("crie o addon X", "manifest_builder")

        assert resultado_a in captured["query"], "Arbitro escolheu A -- resultado de A deveria ir para a query"
        assert resultado_b not in captured["query"]

    def test_modelos_divergentes_arbitro_escolhe_b_usa_resultado_de_b(self):
        executor = self._make_executor()

        resultado_a = "versao A do manifest, bem diferente"
        resultado_b = "versao B completamente distinta da A"

        chat_calls = {"n": 0}

        def fake_chat(*args, **kwargs):
            chat_calls["n"] += 1
            if chat_calls["n"] == 1:
                return MagicMock(content=resultado_a)
            if chat_calls["n"] == 2:
                return MagicMock(content=resultado_b)
            return MagicMock(content='{"choice":"second"}')

        mock_client = MagicMock()
        mock_client.chat.side_effect = fake_chat

        captured = {}

        def fake_run_sync(query):
            captured["query"] = query
            return MagicMock()

        with patch("nvdastudio.ai.llm_factory.create_llm_client", return_value=mock_client), \
             patch.object(executor, "_run_sync", side_effect=fake_run_sync):
            executor.ensemble_verify("crie o addon X", "manifest_builder")

        assert resultado_b in captured["query"], "Arbitro escolheu B -- resultado de B deveria ir para a query"
        assert resultado_a not in captured["query"]

    def test_arbitro_falha_usa_query_original_sem_injecao(self):
        executor = self._make_executor()

        resultado_a = "versao A do manifest, bem diferente"
        resultado_b = "versao B completamente distinta da A"

        chat_calls = {"n": 0}

        def fake_chat(*args, **kwargs):
            chat_calls["n"] += 1
            if chat_calls["n"] == 1:
                return MagicMock(content=resultado_a)
            if chat_calls["n"] == 2:
                return MagicMock(content=resultado_b)
            raise RuntimeError("arbitro indisponivel")

        mock_client = MagicMock()
        mock_client.chat.side_effect = fake_chat

        captured = {}

        def fake_run_sync(query):
            captured["query"] = query
            return MagicMock()

        with patch("nvdastudio.ai.llm_factory.create_llm_client", return_value=mock_client), \
             patch.object(executor, "_run_sync", side_effect=fake_run_sync):
            executor.ensemble_verify("crie o addon X", "manifest_builder")

        assert captured["query"] == "crie o addon X"
        assert "RESULTADO VERIFICADO" not in captured["query"]
