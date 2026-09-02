from unittest.mock import MagicMock, patch


class TestClarifierVersao:
    def test_versao_e_1_3_0(self):
        from nvdastudio.ai.clarifier import MODULE_VERSION
        assert MODULE_VERSION == "1.7.0"


class TestClarifierCapDinamico:
    """Cap agora e 5 (LLM decide — ate 5 perguntas)."""

    def test_cap_e_5(self):
        """System prompt nao menciona limite fixo de 3."""
        from nvdastudio.ai.clarifier import _CLARIFIER_SYSTEM
        # Nao deve ter "Maximo 3 perguntas" hardcoded
        assert "aximo 3 perguntas" not in _CLARIFIER_SYSTEM

    def test_cap_menciona_5(self):
        from nvdastudio.ai.clarifier import _CLARIFIER_SYSTEM
        assert "5" in _CLARIFIER_SYSTEM

    def test_retorna_ate_5_perguntas(self, fake_api_key):
        """Mock retorna 5 perguntas — todas devem ser retornadas."""
        import json
        from unittest.mock import MagicMock, patch
        from nvdastudio.ai.clarifier import analyze_query

        data = {
            "needs_clarification": True,
            "user_level": "intermediario",
            "questions": ["q1", "q2", "q3", "q4", "q5"]
        }
        mock_resp = MagicMock()
        mock_resp.content = json.dumps(data)

        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as MC:
            MC.return_value = mock_resp
            result = analyze_query("addon para o notepad++")

        assert result.needs_clarification is True
        assert len(result.questions) == 5

    def test_nao_retorna_mais_de_5(self):
        """Cap de seguranca: nunca mais de 5 mesmo se LLM retornar 8."""
        import json
        from unittest.mock import MagicMock, patch
        from nvdastudio.ai.clarifier import analyze_query

        data = {
            "needs_clarification": True,
            "user_level": "avancado",
            "questions": [f"q{i}" for i in range(8)]
        }
        mock_resp = MagicMock()
        mock_resp.content = json.dumps(data)

        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as MC:
            MC.return_value = mock_resp
            result = analyze_query("addon complexo")

        assert len(result.questions) <= 5

    def test_query_clara_retorna_zero_perguntas(self):
        """Query clara: 0 perguntas independente do cap."""
        import json
        from unittest.mock import MagicMock, patch
        from nvdastudio.ai.clarifier import analyze_query

        data = {"needs_clarification": False, "user_level": "avancado", "questions": []}
        mock_resp = MagicMock()
        mock_resp.content = json.dumps(data)

        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as MC:
            MC.return_value = mock_resp
            result = analyze_query("crie addon que fala a hora com NVDA+T")

        assert result.needs_clarification is False
        assert result.questions == []

    def test_perguntas_sao_strings(self):
        import json
        from unittest.mock import MagicMock, patch
        from nvdastudio.ai.clarifier import analyze_query

        data = {"needs_clarification": True, "user_level": "iniciante",
                "questions": ["Para qual programa?", "Qual acao principal?"]}
        mock_resp = MagicMock()
        mock_resp.content = json.dumps(data)

        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as MC:
            MC.return_value = mock_resp
            result = analyze_query("addon para me ajudar")

        for q in result.questions:
            assert isinstance(q, str)


class TestClarifierSystemPromptDinamico:
    def test_system_menciona_necessidade(self):
        from nvdastudio.ai.clarifier import _CLARIFIER_SYSTEM
        assert "necessarias" in _CLARIFIER_SYSTEM.lower() or "segura" in _CLARIFIER_SYSTEM.lower()

    def test_system_menciona_ambiguidade_critica(self):
        from nvdastudio.ai.clarifier import _CLARIFIER_SYSTEM
        assert "critica" in _CLARIFIER_SYSTEM.lower() or "ambiguidade" in _CLARIFIER_SYSTEM.lower()


class TestPlannerUserClarificationStep:
    def test_constante_definida(self):
        from nvdastudio.core.planner import STEP_USER_CLARIFICATION
        assert STEP_USER_CLARIFICATION == "user_clarification"

    def test_no_model_map(self):
        from nvdastudio.core.planner import STEP_USER_CLARIFICATION, STEP_MODEL_MAP
        assert STEP_USER_CLARIFICATION in STEP_MODEL_MAP

    def test_no_reasoning_map(self):
        from nvdastudio.core.planner import STEP_USER_CLARIFICATION, STEP_REASONING_MAP
        assert STEP_USER_CLARIFICATION in STEP_REASONING_MAP

    def test_plan_system_menciona_user_clarification(self):
        from nvdastudio.core.planner import _PLAN_SYSTEM_PROMPT
        assert "user_clarification" in _PLAN_SYSTEM_PROMPT

    def test_plan_system_explica_quando_usar(self):
        from nvdastudio.core.planner import _PLAN_SYSTEM_PROMPT
        assert "ambiguidade" in _PLAN_SYSTEM_PROMPT.lower() or "critica" in _PLAN_SYSTEM_PROMPT.lower()


class TestOrchestratorMidPipelineClarification:
    def test_versao_e_2_6_0(self):
        from nvdastudio.core.orchestrator import MODULE_VERSION
        assert MODULE_VERSION == "5.81.0"

    def test_set_callbacks_aceita_on_clarify(self):
        from nvdastudio.core.orchestrator import Orchestrator
        orch = Orchestrator()
        orch._planner = MagicMock()
        orch._critic = MagicMock()
        orch._api_key = "fake"
        called_with = []

        def mock_clarify(questions):
            called_with.extend(questions)
            return ["resposta1"]

        orch.set_callbacks(
            on_progress=lambda e, d: None,
            on_complete=lambda r: None,
            on_clarify=mock_clarify,
        )
        assert orch._on_clarify is mock_clarify

    def test_handle_clarification_step_sem_callback(self):
        """Sem callback: step aprovado com output vazio mas sem travar."""
        from nvdastudio.core.orchestrator import Orchestrator, STEP_USER_CLARIFICATION
        from nvdastudio.core.planner import ExecutionStep

        orch = Orchestrator()
        orch._on_clarify = None
        orch._on_progress = lambda e, d: None

        step = ExecutionStep(
            step_id="c1",
            step_type=STEP_USER_CLARIFICATION,
            description="Para qual app? | Qual acao?",
            model_id="kimi-k2.6",
        )
        result = orch._handle_clarification_step(step, {})
        assert result.approved is True
        assert result.step_id == "c1"

    def test_handle_clarification_step_com_callback(self):
        """Com callback: respostas injetadas no output."""
        from nvdastudio.core.orchestrator import Orchestrator, STEP_USER_CLARIFICATION
        from nvdastudio.core.planner import ExecutionStep

        orch = Orchestrator()
        orch._on_progress = lambda e, d: None
        orch._on_clarify = lambda qs: ["Notepad++", "Sim, global"]

        step = ExecutionStep(
            step_id="c1",
            step_type=STEP_USER_CLARIFICATION,
            description="Para qual app? | Deve ser global?",
            model_id="kimi-k2.6",
        )
        result = orch._handle_clarification_step(step, {})
        assert result.approved is True
        assert "Notepad++" in result.output
        assert "Sim, global" in result.output

    def test_handle_clarification_step_extrai_perguntas_por_pipe(self):
        """Perguntas separadas por | no campo description."""
        from nvdastudio.core.orchestrator import Orchestrator, STEP_USER_CLARIFICATION
        from nvdastudio.core.planner import ExecutionStep

        perguntas_recebidas = []

        def mock_clarify(qs):
            perguntas_recebidas.extend(qs)
            return ["r1", "r2", "r3"]

        orch = Orchestrator()
        orch._on_progress = lambda e, d: None
        orch._on_clarify = mock_clarify

        step = ExecutionStep(
            step_id="c1",
            step_type=STEP_USER_CLARIFICATION,
            description="Para qual app? | Qual acao? | Atalho preferido?",
            model_id="kimi-k2.6",
        )
        orch._handle_clarification_step(step, {})
        assert len(perguntas_recebidas) == 3
        assert "Para qual app?" in perguntas_recebidas

    def test_handle_clarification_step_description_vazia_aprovado(self):
        """Description vazia: step aprovado sem perguntar."""
        from nvdastudio.core.orchestrator import Orchestrator, STEP_USER_CLARIFICATION
        from nvdastudio.core.planner import ExecutionStep

        orch = Orchestrator()
        orch._on_progress = lambda e, d: None
        orch._on_clarify = lambda qs: []

        step = ExecutionStep(
            step_id="c1",
            step_type=STEP_USER_CLARIFICATION,
            description="",
            model_id="kimi-k2.6",
        )
        result = orch._handle_clarification_step(step, {})
        assert result.approved is True

    def test_handle_clarification_step_nao_executa_output(self):
        """Regra 9: nao executa nenhum codigo das respostas."""
        from nvdastudio.core.orchestrator import Orchestrator, STEP_USER_CLARIFICATION
        from nvdastudio.core.planner import ExecutionStep

        executou = [False]
        malicious_answer = "import os; os.system('del /q')"

        orch = Orchestrator()
        orch._on_progress = lambda e, d: None
        orch._on_clarify = lambda qs: [malicious_answer]

        step = ExecutionStep(
            step_id="c1",
            step_type=STEP_USER_CLARIFICATION,
            description="Qual app?",
            model_id="kimi-k2.6",
        )
        result = orch._handle_clarification_step(step, {})
        # Apenas armazenou o texto — nao executou
        assert malicious_answer in result.output
        assert executou[0] is False

    def test_clarify_nao_bloqueante_nao_chama_llm(self):
        """STEP_USER_CLARIFICATION nao passa pelo dispatch_step."""
        from nvdastudio.core.orchestrator import Orchestrator, STEP_USER_CLARIFICATION
        from nvdastudio.core.planner import ExecutionStep

        dispatch_chamado = [False]

        orch = Orchestrator()
        orch._on_progress = lambda e, d: None
        orch._on_clarify = lambda qs: ["resposta"]

        step = ExecutionStep(
            step_id="c1",
            step_type=STEP_USER_CLARIFICATION,
            description="Pergunta?",
            model_id="kimi-k2.6",
        )

        with patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens",
                   side_effect=lambda **kw: (dispatch_chamado.__setitem__(0, True), "x", 0)[1:]):
            orch._handle_clarification_step(step, {})

        assert dispatch_chamado[0] is False
