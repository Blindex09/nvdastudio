import time
from unittest.mock import patch

from nvdastudio.core.orchestrator import Orchestrator
from nvdastudio.core.planner import ExecutionStep, ExecutionPlan, STEP_CODE_GENERATION, STEP_ASSEMBLY
from nvdastudio.ai.critic import Verdict, CriticResult
from nvdastudio.memory.conversation_manager import conversation


def _make_step(step_id="s1", step_type=STEP_CODE_GENERATION, user_message=""):
    return ExecutionStep(
        step_id=step_id,
        step_type=step_type,
        description="Step de teste",
        model_id="kimi-k2.6",
        reasoning_params={},
        depends_on=[],
        context_from_steps=[],
        expected_output="codigo",
        max_retries=3,
        user_message=user_message,
    )


def _make_plan(steps, query="Crie um addon"):
    return ExecutionPlan(
        plan_id="test01",
        original_query=query,
        steps=steps,
        requires_web_research=False,
        requires_agent_runner=False,
        estimated_complexity="medium",
    )


def _approved() -> CriticResult:
    return CriticResult(verdict=Verdict.APPROVED, score=95, issues=[], fix_instructions="")


class TestPreExecMsg:
    """O usuario deve ser avisado do que vai acontecer ANTES do step rodar."""

    def test_user_message_e_anunciado_antes_do_dispatch(self, fake_api_key):
        step = _make_step(user_message="Fazendo algo especifico de teste...")
        plan = _make_plan([step, _make_step("s2", STEP_ASSEMBLY)])
        call_order = []

        def fake_dispatch(*args, **kwargs):
            call_order.append("dispatch")
            return "codigo gerado", 0

        def fake_emit_status(msg):
            call_order.append(("status", msg))

        with patch("nvdastudio.core.orchestrator.Planner") as MockPlanner, \
             patch("nvdastudio.core.orchestrator.Critic") as MockCritic, \
             patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", side_effect=fake_dispatch), \
             patch.object(conversation, "emit_status", side_effect=fake_emit_status):

            MockPlanner.return_value.create_plan.return_value = plan
            MockCritic.return_value.evaluate_two_stage.return_value = _approved()

            orch = Orchestrator()
            orch.initialize()
            orch.set_callbacks(on_progress=lambda ev, det: None, on_complete=lambda r: None)
            orch._run_pipeline("Crie um addon de teste")

        status_msgs = [c[1] for c in call_order if isinstance(c, tuple) and c[0] == "status"]
        assert any("Fazendo algo especifico de teste" in m for m in status_msgs), (
            f"user_message do step nao foi anunciado antes do dispatch. Status emitidos: {status_msgs}"
        )
        # Confirma que o anuncio veio ANTES do dispatch (pre_exec_msg, nao pos)
        first_status_idx = next(i for i, c in enumerate(call_order) if isinstance(c, tuple) and c[0] == "status")
        first_dispatch_idx = call_order.index("dispatch")
        assert first_status_idx < first_dispatch_idx


class TestHeartbeatDurantePipeline:
    """Steps lentos devem emitir progresso periodico em vez de silencio."""

    def test_dispatch_lento_emite_progresso_periodico(self, fake_api_key):
        step = _make_step()
        plan = _make_plan([step, _make_step("s2", STEP_ASSEMBLY)])
        progress_calls = []

        def slow_dispatch(*args, **kwargs):
            time.sleep(0.05)
            return "codigo gerado", 0

        started_tools = []

        def fake_emit_start(tool_name):
            started_tools.append(tool_name)

        def fake_emit_progress():
            # emit_tool_progress() nao recebe mais step_type/elapsed_ms explicitos --
            # o elapsed e calculado internamente a partir do emit_tool_start() acima.
            progress_calls.append(True)

        with patch("nvdastudio.core.orchestrator.Planner") as MockPlanner, \
             patch("nvdastudio.core.orchestrator.Critic") as MockCritic, \
             patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", side_effect=slow_dispatch), \
             patch("nvdastudio.core.orchestrator._HEARTBEAT_INTERVAL_SECONDS", 0.01), \
             patch.object(conversation, "emit_tool_start", side_effect=fake_emit_start), \
             patch.object(conversation, "emit_tool_progress", side_effect=fake_emit_progress):

            MockPlanner.return_value.create_plan.return_value = plan
            MockCritic.return_value.evaluate_two_stage.return_value = _approved()

            orch = Orchestrator()
            orch.initialize()
            orch.set_callbacks(on_progress=lambda ev, det: None, on_complete=lambda r: None)
            orch._run_pipeline("Crie um addon de teste")

        assert progress_calls, "Nenhum heartbeat de progresso foi emitido durante step lento"
        assert started_tools, "emit_tool_start nao foi chamado para nenhum step"
        # s1 e s2 nao tem dependencia entre si e podem rodar em paralelo:
        # o heartbeat deve disparar para qualquer um dos dois, sem ordem fixa.
        assert started_tools[0] in (STEP_CODE_GENERATION, STEP_ASSEMBLY)

    def test_dispatch_rapido_nao_precisa_de_heartbeat_para_retornar_certo(self, fake_api_key):
        """Sanity check: _dispatch_with_heartbeat repassa o resultado real do dispatch."""
        orch = Orchestrator.__new__(Orchestrator)
        with patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens",
                   return_value=("saida real", 42)):
            output, tokens = orch._dispatch_with_heartbeat(
                step_type=STEP_CODE_GENERATION, prompt="p", model_id="kimi-k2.6",
                reasoning_params={},
            )
        assert output == "saida real"
        assert tokens == 42

    def test_heartbeat_usa_assinatura_real_de_emit_tool_progress(self, fake_api_key):
        """Regressao do bug real: orchestrator chamava
        conversation.emit_tool_progress(step_type, elapsed_ms) -- 3 args (com self) --
        mas o metodo real so aceita detail="" (calcula o elapsed sozinho via
        emit_tool_start/_tool_start_time). O bug so aparecia em producao porque o
        teste anterior mockava emit_tool_progress inteiro com side_effect, escondendo
        a incompatibilidade de assinatura real. Este teste NAO mocka conversation --
        chama o objeto de verdade para garantir que a assinatura bate."""
        step = _make_step()
        plan = _make_plan([step])

        def slow_dispatch(*args, **kwargs):
            time.sleep(0.05)
            return "codigo gerado", 0

        with patch("nvdastudio.core.orchestrator.Planner") as MockPlanner, \
             patch("nvdastudio.core.orchestrator.Critic") as MockCritic, \
             patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", side_effect=slow_dispatch), \
             patch("nvdastudio.core.orchestrator._HEARTBEAT_INTERVAL_SECONDS", 0.01):

            MockPlanner.return_value.create_plan.return_value = plan
            MockCritic.return_value.evaluate_two_stage.return_value = _approved()

            orch = Orchestrator()
            orch.initialize()
            orch.set_callbacks(on_progress=lambda ev, det: None, on_complete=lambda r: None)
            # Nao deve levantar TypeError de assinatura incompativel.
            orch._run_pipeline("Crie um addon de teste")


class TestThoughtStreaming:
    """v5.19.0 (revert): Hermes NUNCA expoe raciocinio bruto do modelo ao
    usuario final -- ele filtra/descarta blocos <think> inteiramente
    (gateway/stream_consumer.py::_filter_and_accumulate). O que aparece pro
    usuario e "commentary": frases curadas e completas que o assistente
    decide dizer (equivalente ao pre_exec_msg/heartbeat ja implementados
    aqui). Repassar resp.reasoning cru (chain-of-thought, as vezes em ingles,
    citando papeis internos como "Elite Challenger") quebra essa premissa e
    confunde um usuario cego. _run_sub_agent NAO deve chamar emit_thinking
    com o reasoning do modelo."""

    def test_run_sub_agent_nao_repassa_reasoning_bruto_para_thinking(self, fake_api_key):
        from nvdastudio.sub_agents._base import _run_sub_agent
        from nvdastudio.ai.llm_client import LLMResponse

        fake_resp = LLMResponse(
            content="codigo gerado", model_used="kimi-k2.6", tokens_used=10,
            reasoning="We need to generate manifest.ini for the addon...",
        )
        with patch("nvdastudio.sub_agents._base.create_llm_client") as mock_create:
            mock_client = mock_create.return_value
            mock_client.chat.return_value = fake_resp

            result = _run_sub_agent(
                system_addendum="voce e um agente de teste",
                prompt="gere codigo",
                model_id="kimi-k2.6",
                reasoning_params={},
            )

        assert result == "codigo gerado"
        import inspect
        assert "emit_thinking" not in inspect.getsource(_run_sub_agent)

    def test_run_sub_agent_nao_publica_stream_interno_no_chat(self, fake_api_key):
        from nvdastudio.sub_agents._base import _run_sub_agent
        from nvdastudio.ai.llm_client import LLMResponse

        fake_resp = LLMResponse(
            content="artefato interno", model_used="kimi-k2.6", tokens_used=10,
            reasoning="planejamento privado",
        )

        with patch("nvdastudio.sub_agents._base.create_llm_client") as mock_create:
            mock_create.return_value.chat.return_value = fake_resp
            result = _run_sub_agent(
                system_addendum="agente interno",
                prompt="gere o artefato",
                model_id="kimi-k2.6",
                reasoning_params={},
            )

        assert result == "artefato interno"
        import inspect
        source = inspect.getsource(_run_sub_agent)
        assert "emit_stream" not in source
