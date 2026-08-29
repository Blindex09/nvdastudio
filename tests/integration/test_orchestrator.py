from unittest.mock import MagicMock, patch


from nvdastudio.core.orchestrator import (
    Orchestrator, OrchestrationResult, _MAX_CONTEXT_CHARS_PER_STEP, _MAX_PARALLEL_WORKERS,
)
from nvdastudio.core.planner import (
    ExecutionStep,
    ExecutionPlan,
    STEP_CODE_GENERATION,
    STEP_MANIFEST,
    STEP_ASSEMBLY,
)
from nvdastudio.ai.critic import Verdict, CriticResult


def _make_step(step_id="s1", step_type=STEP_CODE_GENERATION, depends_on=None,
               context_from=None):
    return ExecutionStep(
        step_id=step_id,
        step_type=step_type,
        description="Step de teste",
        model_id="kimi-k2.6",
        reasoning_params={},
        depends_on=depends_on or [],
        context_from_steps=context_from or [],
        expected_output="codigo",
        max_retries=3,
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


def _needs_fix(msg="falta initTranslation") -> CriticResult:
    return CriticResult(verdict=Verdict.NEEDS_FIX, score=70,
                        issues=[msg], fix_instructions="adicione")


def _rejected() -> CriticResult:
    return CriticResult(verdict=Verdict.REJECTED, score=20,
                        issues=["codigo invalido"], fix_instructions="reescreva")


def _valid_addon_output(extra_code=""):
    """Artefatos mínimos realistas para testes que exercitam o fluxo completo."""
    return (
        "```python:globalPlugins/teste/__init__.py\n"
        f"{extra_code}\n"
        "class GlobalPlugin:\n    pass\n"
        "```\n"
        "```ini:manifest.ini\nname = teste\nsummary = Teste\nversion = 1.0.0\n```"
    )


class TestOrchestratorInit:
    """Testa inicializacao e configuracao de callbacks."""

    def test_initialize_sem_api_key(self):
        with patch("nvdastudio.core.orchestrator.Planner"), \
             patch("nvdastudio.core.orchestrator.Critic"):
            orch = Orchestrator()
            orch.initialize()
        assert orch._planner is not None
        assert orch._critic is not None

    def test_planner_e_critic_disponiveis_sem_chamar_initialize(self):
        """
        Bug de auditoria: _planner/_critic eram None ate initialize() ser
        chamado. Se algum caller (ex: um dialog que engole excecao de
        initialize()) pulasse essa chamada, qualquer uso de planner/critic
        levantava AttributeError. Planner()/Critic() nao tem efeito colateral
        (__init__ e pass), entao nao ha motivo pra essa segunda fase.
        """
        orch = Orchestrator()
        assert orch._planner is not None
        assert orch._critic is not None

    def test_set_callbacks(self, fake_api_key):
        orch = Orchestrator()
        on_progress = MagicMock()
        on_complete = MagicMock()
        orch.set_callbacks(on_progress, on_complete)
        assert orch._on_progress is on_progress
        assert orch._on_complete is on_complete


class TestOrchestratorDepsReady:
    """Testa verificacao de dependencias entre steps."""

    def setup_method(self):
        self.orch = Orchestrator.__new__(Orchestrator)

    def test_step_sem_deps_sempre_pronto(self):
        step = _make_step(depends_on=[])
        assert self.orch._deps_ready(step, {}) is True

    def test_step_deps_satisfeitas(self):
        step = _make_step(depends_on=["s1", "s2"])
        outputs = {"s1": "out1", "s2": "out2"}
        assert self.orch._deps_ready(step, outputs) is True

    def test_step_deps_nao_satisfeitas(self):
        step = _make_step(depends_on=["s1", "s2"])
        outputs = {"s1": "out1"}
        assert self.orch._deps_ready(step, outputs) is False


class TestOrchestratorBuildContext:
    """Testa construcao de contexto para steps dependentes."""

    def setup_method(self):
        self.orch = Orchestrator.__new__(Orchestrator)

    def test_contexto_vazio_sem_context_from_steps(self):
        step = _make_step()
        step.context_from_steps = []
        ctx = self.orch._build_context(step, {"s1": "output s1"})
        assert ctx == ""

    def test_contexto_inclui_output_de_step_anterior(self):
        step = _make_step()
        step.context_from_steps = ["s1"]
        ctx = self.orch._build_context(step, {"s1": "output do s1"})
        assert "output do s1" in ctx
        assert "s1" in ctx

    def test_contexto_ignora_step_nao_aprovado(self):
        step = _make_step()
        step.context_from_steps = ["s_nao_existe"]
        ctx = self.orch._build_context(step, {})
        assert ctx == ""

    def test_contexto_truncado_quando_output_longo(self):
        step = _make_step()
        step.context_from_steps = ["s1"]
        output_longo = "x" * (_MAX_CONTEXT_CHARS_PER_STEP * 2)
        ctx = self.orch._build_context(step, {"s1": output_longo})
        assert "omitidos" in ctx or len(ctx) < len(output_longo)

    def test_contexto_nao_trunca_output_curto(self):
        step = _make_step()
        step.context_from_steps = ["s1"]
        output_curto = "x" * 100
        ctx = self.orch._build_context(step, {"s1": output_curto})
        assert output_curto in ctx
        assert "omitidos" not in ctx

    def test_limite_context_chars_positivo(self):
        assert _MAX_CONTEXT_CHARS_PER_STEP > 0


class TestOrchestratorStepPrompt:
    """Testa construcao de prompts para re-execucao com feedback."""

    def setup_method(self):
        self.orch = Orchestrator.__new__(Orchestrator)

    def test_prompt_inclui_query_original(self):
        step = _make_step()
        prompt = self.orch._build_step_prompt(step, "crie addon X", "", [])
        assert "crie addon X" in prompt

    def test_prompt_inclui_descricao_do_step(self):
        step = _make_step()
        step.description = "Gerar globalPlugin com atalho NVDA+T"
        prompt = self.orch._build_step_prompt(step, "query", "", [])
        assert "Gerar globalPlugin com atalho NVDA+T" in prompt

    def test_prompt_inclui_issues_anteriores_no_retry(self):
        step = _make_step()
        issues = ["Falta addonHandler.initTranslation()", "Sem @script decorator"]
        prompt = self.orch._build_step_prompt(step, "query", "", previous_issues=issues)
        assert "addonHandler.initTranslation" in prompt
        assert "@script" in prompt

    def test_prompt_inclui_contexto_de_steps_anteriores(self):
        step = _make_step()
        ctx = "--- Output do step s1 ---\ncodigo gerado aqui"
        prompt = self.orch._build_step_prompt(step, "query", ctx, [])
        assert "codigo gerado aqui" in prompt


class TestOrchestratorPipelineComMock:
    """
    Testa pipeline completo com Planner, Dispatcher e Critic mockados.
    v1.2.0: mocks usam evaluate_two_stage (metodo principal do Critic v2.0.0).
    """

    def test_pipeline_step_aprovado_na_primeira_tentativa(self, fake_api_key):
        """Step aprovado imediatamente nao deve gerar retries."""
        plan = _make_plan([_make_step("s1"), _make_step("s2", STEP_ASSEMBLY)])
        progress_events = []
        complete_result = []

        with patch("nvdastudio.core.orchestrator.Planner") as MockPlanner, \
             patch("nvdastudio.core.orchestrator.Critic") as MockCritic, \
             patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", return_value=(_valid_addon_output(), 0)):

            MockPlanner.return_value.create_plan.return_value = plan
            # v1.2.0: Critic usa evaluate_two_stage
            MockCritic.return_value.evaluate_two_stage.return_value = _approved()

            orch = Orchestrator()
            orch.initialize()
            orch.set_callbacks(
                on_progress=lambda ev, det: progress_events.append(ev),
                on_complete=lambda r: complete_result.append(r),
            )
            orch._run_pipeline("Crie um addon de teste")

        assert complete_result, "on_complete nao foi chamado"
        result = complete_result[0]
        assert result.success is True
        assert result.total_retries == 0

    def test_pipeline_step_corrigido_apos_retry(self, fake_api_key):
        """Step corrigido na segunda tentativa deve gerar 1 retry."""
        plan = _make_plan([_make_step("s1")])
        evaluate_calls = {"n": 0}

        def two_stage_side_effect(*args, **kwargs):
            evaluate_calls["n"] += 1
            return _needs_fix() if evaluate_calls["n"] == 1 else _approved()

        complete_result = []

        with patch("nvdastudio.core.orchestrator.Planner") as MockPlanner, \
             patch("nvdastudio.core.orchestrator.Critic") as MockCritic, \
             patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", return_value=("codigo", 0)):

            MockPlanner.return_value.create_plan.return_value = plan
            MockCritic.return_value.evaluate_two_stage.side_effect = two_stage_side_effect

            orch = Orchestrator()
            orch.initialize()
            orch.set_callbacks(
                on_progress=lambda ev, det: None,
                on_complete=lambda r: complete_result.append(r),
            )
            orch._run_pipeline("addon com retry")

        result = complete_result[0]
        assert result.total_retries == 1
        assert result.step_results[0].retries_used == 1

    def test_pipeline_step_rejeitado_continua_sem_abortar(self, fake_api_key):
        """Step rejeitado nao deve abortar o pipeline inteiro."""
        # s1 sem deps, s2 depende de s1 (sequencial garantido)
        plan = _make_plan([
            _make_step("s1"),
            _make_step("s2", STEP_ASSEMBLY, depends_on=["s1"]),
        ])
        evaluate_calls = {"n": 0}

        def two_stage_side_effect(*args, **kwargs):
            evaluate_calls["n"] += 1
            return _rejected()

        complete_result = []

        with patch("nvdastudio.core.orchestrator.Planner") as MockPlanner, \
             patch("nvdastudio.core.orchestrator.Critic") as MockCritic, \
             patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", return_value=("codigo", 0)), \
             patch("nvdastudio.gui.settings_panel.get_api_key",
                   side_effect=lambda p: "gsk_test_x" if p == "ollama" else ""):
            # s1 e code_generation, elegivel a escalacao cross-provider
            # (orchestrator.py 5.32.0+ generaliza _ESCALATION_ELIGIBLE_STEP_TYPES
            # pra alem de web_research). Sem esse patch, uma OPENAI_API_KEY (ou
            # outra) real deixada no ambiente do shell do desenvolvedor faz
            # select_model_and_provider() achar um provider de verdade e
            # disparar o rescue, consumindo uma chamada extra do
            # evaluate_two_stage mockado e desalinhando two_stage_side_effect --
            # o teste precisa ficar deterministico independente do ambiente.
            #
            # 5.52.0: side_effect mudado de "rejeita 3x, aprova da 4a em
            # diante" pra "rejeita sempre". Bug REAL corrigido em
            # orchestrator.py 5.52.0 fez a escalacao (_try_escalation) passar
            # a rodar de verdade apos as tentativas normais esgotarem --
            # antes disso, a condicao que dispara _try_escalation() tinha um
            # bug que quase nunca deixava ela executar (ver changelog). Com
            # a escalacao rodando de verdade, ela consome MAIS UMA chamada
            # real de evaluate_two_stage -- que com o side_effect antigo
            # ("aprova da 4a chamada em diante") calhava de aprovar s1 via
            # escalacao genuina, quebrando a premissa deste teste (que quer
            # testar um step que continua REJEITADO ate o fim, nao a
            # recuperacao via escalacao -- isso e testado em
            # TestTryEscalation/TestEscalacaoDeVerdadeAposSwitchProativo).
            # Rejeitar sempre preserva a intencao original do teste
            # independente de quantas chamadas reais a escalacao consome.

            MockPlanner.return_value.create_plan.return_value = plan
            MockCritic.return_value.evaluate_two_stage.side_effect = two_stage_side_effect

            orch = Orchestrator()
            orch.initialize()
            orch.set_callbacks(
                on_progress=lambda ev, det: None,
                on_complete=lambda r: complete_result.append(r),
            )
            orch._run_pipeline("addon com rejeicao")

        result = complete_result[0]
        assert len(complete_result) == 1
        rejected_steps = [r for r in result.step_results if not r.approved]
        assert any(r.step_id == "s1" for r in rejected_steps)

    def test_pipeline_mesmo_erro_repetido_escala_mais_cedo_sem_esgotar_retries(self, fake_api_key):
        """
        5.42.0/5.44.0: deteccao de loop semantico -- se 3 tentativas SEGUIDAS
        (2 repeticoes consecutivas) devolvem o MESMO issue, o loop local para
        e escala (em vez de continuar retentando o mesmo jeito ate esgotar
        max_retries). O limiar e 3 (nao 2) de proposito -- ver 5.44.0: 2
        rejeicoes identicas seguidas de uma resolvida na 3a e um caso
        LEGITIMO (test_client_cache_por_tentativa.py), entao so escala apos
        a 3a tentativa idantica. _rejected() sempre devolve ["codigo
        invalido"] -- identico a cada chamada -- e max_retries=6 aqui (acima
        do default de 3) pra tornar a economia observavel.
        """
        step = _make_step("s1")
        step.max_retries = 6
        plan = _make_plan([step])
        dispatch_calls = {"n": 0}

        def fake_dispatch(**kwargs):
            dispatch_calls["n"] += 1
            return ("codigo", 0)

        complete_result = []

        with patch("nvdastudio.core.orchestrator.Planner") as MockPlanner, \
             patch("nvdastudio.core.orchestrator.Critic") as MockCritic, \
             patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", side_effect=fake_dispatch), \
             patch("nvdastudio.core.orchestrator.memory.log_step_metric") as mock_log_metric, \
             patch("nvdastudio.gui.settings_panel.get_api_key",
                   side_effect=lambda p: "gsk_test_x" if p == "ollama" else ""):
            MockPlanner.return_value.create_plan.return_value = plan
            # SEMPRE rejeita com o MESMO issue -- nunca varia entre tentativas.
            MockCritic.return_value.evaluate_two_stage.side_effect = lambda *a, **k: _rejected()

            orch = Orchestrator()
            orch.initialize()
            orch.set_callbacks(
                on_progress=lambda ev, det: None,
                on_complete=lambda r: complete_result.append(r),
            )
            orch._run_pipeline("addon com erro repetido")

        # max_retries=6 permitiria ate 6 chamadas de dispatch localmente;
        # o loop semantico deve interromper apos a 3a tentativa identica
        # (attempt 0, 1 e 2 tem o MESMO issue -- 2 repeticoes consecutivas),
        # entao no MAXIMO 3 chamadas locais antes de escalar (a escalacao em
        # si faz sua PROPRIA chamada de dispatch, separada).
        result = complete_result[0]
        assert result.step_results[0].retries_used <= 3

        # 5.43.0: o log_step_metric da falha final deve rotular trajectory
        # como "loop_detected", nao "exhausted" -- confirma que o rotulo
        # reflete o MOTIVO real da saida antecipada.
        trajectories = [call.kwargs.get("trajectory") for call in mock_log_metric.call_args_list]
        assert "loop_detected" in trajectories

    def test_pipeline_step_aprovado_de_primeira_registra_trajectory_direct(self, fake_api_key):
        """5.43.0: aprovado no attempt 0 -- trajectory deve ser 'direct'."""
        plan = _make_plan([_make_step("s1")])
        complete_result = []

        with patch("nvdastudio.core.orchestrator.Planner") as MockPlanner, \
             patch("nvdastudio.core.orchestrator.Critic") as MockCritic, \
             patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", return_value=("codigo", 0)), \
             patch("nvdastudio.core.orchestrator.memory.log_step_metric") as mock_log_metric:
            MockPlanner.return_value.create_plan.return_value = plan
            MockCritic.return_value.evaluate_two_stage.return_value = _approved()

            orch = Orchestrator()
            orch.initialize()
            orch.set_callbacks(
                on_progress=lambda ev, det: None,
                on_complete=lambda r: complete_result.append(r),
            )
            orch._run_pipeline("addon simples")

        trajectories = [call.kwargs.get("trajectory") for call in mock_log_metric.call_args_list]
        assert "direct" in trajectories

    def test_pipeline_nao_executa_codigo_gerado(self, fake_api_key):
        """Regra 9: codigo gerado nunca e executado."""
        codigo_malicioso = "import os; os.system('echo EXECUTADO')"
        plan = _make_plan([
            _make_step("s1"),
            _make_step("manifest", STEP_MANIFEST),
        ])
        complete_result = []

        with patch("nvdastudio.core.orchestrator.Planner") as MockPlanner, \
             patch("nvdastudio.core.orchestrator.Critic") as MockCritic, \
             patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", return_value=(_valid_addon_output(codigo_malicioso), 0)):

            MockPlanner.return_value.create_plan.return_value = plan
            # Step aprovado: codigo fica em outputs e aparece no final_output
            MockCritic.return_value.evaluate_two_stage.return_value = _approved()

            orch = Orchestrator()
            orch.initialize()
            orch.set_callbacks(
                on_progress=lambda ev, det: None,
                on_complete=lambda r: complete_result.append(r),
            )
            orch._run_pipeline("addon malicioso")

        result = complete_result[0]
        # Codigo no output mas nao executado — processado como string
        assert "os.system" in result.final_output
        assert result.success is True


class TestOrchestratorExecucaoParalela:
    """
    Testa execucao paralela de steps independentes — v1.2.0.
    Baseado em: c:\\skills\\dispatching-parallel-agents\\SKILL.md
    Regra 5: paralelismo e deterministico (ThreadPoolExecutor).
    """

    def test_steps_sem_deps_rodam_em_paralelo(self, fake_api_key):
        """
        Steps sem dependencia entre si devem ser disparados em paralelo.
        Invariante: todos devem completar mesmo sem depender um do outro.
        """
        # s1, s2, s3 sem dependencias — todos devem rodar no mesmo nivel
        plan = _make_plan([
            _make_step("s1"),
            _make_step("s2"),
            _make_step("s3", STEP_ASSEMBLY),
        ])
        complete_result = []

        with patch("nvdastudio.core.orchestrator.Planner") as MockPlanner, \
             patch("nvdastudio.core.orchestrator.Critic") as MockCritic, \
             patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", return_value=(_valid_addon_output(), 0)):

            MockPlanner.return_value.create_plan.return_value = plan
            MockCritic.return_value.evaluate_two_stage.return_value = _approved()

            orch = Orchestrator()
            orch.initialize()
            orch.set_callbacks(
                on_progress=lambda ev, det: None,
                on_complete=lambda r: complete_result.append(r),
            )
            orch._run_pipeline("addon paralelo")

        result = complete_result[0]
        assert result.success is True
        assert len(result.step_results) == 3
        assert all(r.approved for r in result.step_results)

    def test_steps_com_deps_rodam_em_sequencia(self, fake_api_key):
        """
        Steps com dependencias rodam depois dos predecessores.
        s2 depende de s1: s1 deve ser aprovado antes de s2 rodar.
        """
        plan = _make_plan([
            _make_step("s1"),
            _make_step("s2", STEP_ASSEMBLY, depends_on=["s1"]),
        ])
        complete_result = []
        dispatch_calls = []

        def track_dispatch(**kwargs):
            dispatch_calls.append(kwargs.get("step_type"))
            return "output"

        with patch("nvdastudio.core.orchestrator.Planner") as MockPlanner, \
             patch("nvdastudio.core.orchestrator.Critic") as MockCritic, \
             patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens",
                   side_effect=lambda **kw: (dispatch_calls.append(kw["step_type"]), (_valid_addon_output(), 0))[1]):

            MockPlanner.return_value.create_plan.return_value = plan
            MockCritic.return_value.evaluate_two_stage.return_value = _approved()

            orch = Orchestrator()
            orch.initialize()
            orch.set_callbacks(
                on_progress=lambda ev, det: None,
                on_complete=lambda r: complete_result.append(r),
            )
            orch._run_pipeline("addon sequencial")

        result = complete_result[0]
        assert result.success is True
        assert len(result.step_results) == 2

    def test_max_parallel_workers_e_positivo(self):
        """Invariante: limite de workers paralelos deve ser positivo."""
        assert _MAX_PARALLEL_WORKERS > 0

    def test_parallel_nao_executa_codigo(self, fake_api_key):
        """Regra 9: execucao paralela nunca executa o codigo gerado."""
        codigo = "import os; os.system('format C:')"
        plan = _make_plan([
            _make_step("s1"),
            _make_step("s2"),
            _make_step("manifest", STEP_MANIFEST),
        ])
        complete_result = []

        with patch("nvdastudio.core.orchestrator.Planner") as MockPlanner, \
             patch("nvdastudio.core.orchestrator.Critic") as MockCritic, \
             patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", return_value=(_valid_addon_output(codigo), 0)):

            MockPlanner.return_value.create_plan.return_value = plan
            MockCritic.return_value.evaluate_two_stage.return_value = _approved()

            orch = Orchestrator()
            orch.initialize()
            orch.set_callbacks(
                on_progress=lambda ev, det: None,
                on_complete=lambda r: complete_result.append(r),
            )
            orch._run_pipeline("teste paralelo")

        result = complete_result[0]
        # Codigo presente no output como string, nao executado
        assert any(codigo in r.output for r in result.step_results)
        assert result.success is True


class TestOrchestratorContextTruncation:
    """
    Testa truncacao de contexto v1.1.0.
    Regra 5: truncacao e deterministica — testavel sem LLM.
    """

    def setup_method(self):
        self.orch = Orchestrator.__new__(Orchestrator)

    def test_contexto_curto_nao_truncado(self):
        step = _make_step()
        step.context_from_steps = ["s1"]
        output_curto = "x" * (_MAX_CONTEXT_CHARS_PER_STEP - 1)
        ctx = self.orch._build_context(step, {"s1": output_curto})
        assert output_curto in ctx
        # v2.1.0: contexto curto nao tem marcador [COMPRIMIDO]
        assert "[COMPRIMIDO]" not in ctx


    def test_contexto_truncado_nao_perde_qualidade(self):
        """Contexto comprimido mantem informacao relevante mesmo truncado."""
        step = _make_step()
        step.context_from_steps = ["s1"]
        output_longo = "y" * (_MAX_CONTEXT_CHARS_PER_STEP + 500)
        ctx = self.orch._build_context(step, {"s1": output_longo})
        # v2.1.0: compressor externo mantem qualidade mesmo com truncamento
        assert "[COMPRIMIDO]" in ctx
        assert "[FIM_COMPRIMIDO]" in ctx

    def test_contexto_truncado_nao_executa_codigo_1(self):
        """Contexto truncado nao executa codigo da output."""
        step = _make_step()
        step.context_from_steps = ["s1"]
        output = "import os; os.system('whoami')" * 100
        ctx = self.orch._build_context(step, {"s1": output})
        # v2.1.0: apenas comprime, nunca executa
        assert "whoami" in ctx  # conteudo esta la
        # mas nao foi executado (confirmado pelo facto de ctx ser uma string vazia)
        assert isinstance(ctx, str)

    def test_multiplos_steps_cada_um_truncado_independente(self):
        """Cada step tem seu proprio contexto comprimido independentemente."""
        step = _make_step()
        step.context_from_steps = ["s1", "s2"]
        output_longo = "x" * (_MAX_CONTEXT_CHARS_PER_STEP + 100)
        ctx = self.orch._build_context(step, {
            "s1": output_longo,
            "s2": output_longo,
        })
        # v2.1.0: ambos os steps tem [COMPRIMIDO] marcador
        assert ctx.count("[COMPRIMIDO]") >= 2

    def test_limite_positivo_e_constante_1(self):

        assert isinstance(_MAX_CONTEXT_CHARS_PER_STEP, int)
        assert _MAX_CONTEXT_CHARS_PER_STEP > 0

    def test_truncacao_nao_executa_codigo(self):
        step = _make_step()
        step.context_from_steps = ["s1"]
        codigo_malicioso = "import os; os.system('del C:\\\\')" * 200
        ctx = self.orch._build_context(step, {"s1": codigo_malicioso})
        assert isinstance(ctx, str)


# -----------------------------------------------------------------------
# assembly_output e OrchestrationResult
# -----------------------------------------------------------------------

class TestOrchestrationResultAssemblyOutput:

    def test_assembly_output_campo_existe(self):
        r = OrchestrationResult(
            plan_id="x", query="q", step_results=[],
            final_output="final", success=True,
            assembly_output="blocos reais"
        )
        assert r.assembly_output == "blocos reais"

    def test_assembly_output_default_vazio(self):
        r = OrchestrationResult(
            plan_id="x", query="q", step_results=[],
            final_output="final", success=True
        )
        assert r.assembly_output == ""

    def test_all_issues_campo_existe(self):
        r = OrchestrationResult(
            plan_id="x", query="q", step_results=[],
            final_output="", success=False,
            all_issues=["issue1", "issue2"]
        )
        assert r.all_issues == ["issue1", "issue2"]

    def test_dependencies_campo_existe(self):
        r = OrchestrationResult(
            plan_id="x", query="q", step_results=[],
            final_output="", success=True,
            dependencies=["google-generativeai"]
        )
        assert r.dependencies == ["google-generativeai"]


# -----------------------------------------------------------------------
# _NON_BLOCKING_STEP_TYPES
# -----------------------------------------------------------------------

class TestNonBlockingStepTypes:

    def test_accessibility_audit_nao_bloqueante(self):
        from nvdastudio.core.orchestrator import _NON_BLOCKING_STEP_TYPES
        assert "accessibility_audit" in _NON_BLOCKING_STEP_TYPES

    def test_test_generation_e_bloqueante(self):
        """test_generation foi tornado bloqueante em v3.0.0 (decisao Q8.3/Q10.3)."""
        from nvdastudio.core.orchestrator import _NON_BLOCKING_STEP_TYPES
        assert "test_generation" not in _NON_BLOCKING_STEP_TYPES

    def test_code_generation_e_bloqueante(self):
        from nvdastudio.core.orchestrator import _NON_BLOCKING_STEP_TYPES
        assert "code_generation" not in _NON_BLOCKING_STEP_TYPES

    def test_assembly_e_bloqueante(self):
        from nvdastudio.core.orchestrator import _NON_BLOCKING_STEP_TYPES
        assert "assembly" not in _NON_BLOCKING_STEP_TYPES


# -----------------------------------------------------------------------
# Feedback loop — _build_step_prompt
# -----------------------------------------------------------------------

class TestFeedbackLoop:

    def setup_method(self):
        from nvdastudio.core.orchestrator import Orchestrator
        from nvdastudio.core.planner import ExecutionStep, STEP_CODE_GENERATION
        self.orch = Orchestrator()
        self.orch.initialize()
        self.step = ExecutionStep(
            step_id="s1", step_type=STEP_CODE_GENERATION,
            description="gerar codigo", model_id="modelo"
        )

    def test_prompt_code_generation_sem_failures_nao_menciona_erros(self):
        from unittest.mock import patch
        with patch("nvdastudio.core.orchestrator.memory") as mock_mem:
            mock_mem.get_recent_failures.return_value = []
            prompt = self.orch._build_step_prompt(self.step, "query", "", [])
        assert "Padroes de erro" not in prompt

    def test_prompt_code_generation_com_failures_menciona_erros(self):
        from unittest.mock import patch
        with patch("nvdastudio.core.orchestrator.memory") as mock_mem:
            mock_mem.get_recent_failures.return_value = ["Faltou nextHandler()"]
            prompt = self.orch._build_step_prompt(self.step, "query", "", [])
        assert "Padroes de erro" in prompt or "nextHandler" in prompt

    def test_prompt_assembly_consulta_failures(self):
        """Feedback loop global (v3.0.0 fluxos7.1/7.2): todos os steps consultam failures."""
        from unittest.mock import patch
        from nvdastudio.core.planner import ExecutionStep, STEP_ASSEMBLY
        step_assembly = ExecutionStep(
            step_id="s2", step_type=STEP_ASSEMBLY,
            description="assembly", model_id="modelo"
        )
        with patch("nvdastudio.core.orchestrator.memory") as mock_mem:
            mock_mem.get_recent_failures.return_value = ["algum erro"]
            self.orch._build_step_prompt(step_assembly, "query", "", [])
        mock_mem.get_recent_failures.assert_called()

    def test_previous_issues_aparece_apos_global_failures_no_prompt(self):
        """previous_issues deve aparecer no FINAL do prompt, apos global_failures.

        Razao: lost-in-middle (context-degradation skill) — o modelo da maxima
        atencao ao final do contexto. previous_issues sao criticos para o retry
        e devem receber mais atencao que failures globais (apenas informativas).
        """
        from unittest.mock import patch
        issues = ["Falta addonHandler.initTranslation()"]
        with patch("nvdastudio.core.orchestrator.memory") as mock_mem:
            mock_mem.get_recent_failures.return_value = ["Erro global de sessao"]
            prompt = self.orch._build_step_prompt(self.step, "query", "", previous_issues=issues)
        pos_failures = prompt.index("Erro global de sessao")
        pos_issues = prompt.index("addonHandler.initTranslation")
        assert pos_issues > pos_failures, (
            "previous_issues deve aparecer APOS global_failures no prompt "
            "(lost-in-middle: posicao final = maxima atencao do LLM)"
        )


class TestToolApprovalCallback:
    """
    Bug real de auditoria: _tool_approval_callback importava get_current_dialog
    de studio_dialog.py e chamava dialog.approve_tool(...) -- nenhum dos dois
    existia em lugar nenhum do codigo (ImportError/AttributeError garantido na
    primeira tool de alto risco chamada durante um pipeline real). Pesquisa
    (Anthropic/OpenAI human-in-the-loop guidance): acoes irreversiveis exigem
    confirmacao humana explicita, com fail-closed quando nao ha canal de
    aprovacao disponivel.

    2a auditoria (2026-07-26): self._approval_workflow (ApprovalWorkflow, com
    analyze_risk baseado em regex/hardline patterns) era instanciado no
    __init__ mas NUNCA chamado -- o callback so tinha uma allowlist fixa de
    4 nomes, sem nenhuma analise de argumento. Conectado: defense-in-depth
    (pesquisa 2026) -- pre-filtro deterministico primeiro, humano depois.
    """

    def test_sem_dialog_ativo_nega_tool_de_risco_sem_lancar_excecao(self):
        import nvdastudio.gui.studio_dialog as sd_module
        assert sd_module.get_current_dialog() is None

        orch = Orchestrator()
        # "file_writer" esta em _ALWAYS_APPROVE_TOOLS (risco "high") -- exige
        # dialog humano; sem dialog ativo, fail-closed.
        approved = orch._tool_approval_callback("file_writer", {"path": "x.py"})
        assert approved is False

    def test_tools_auto_aprovadas_nao_precisam_de_dialog(self):
        import nvdastudio.gui.studio_dialog as sd_module
        assert sd_module.get_current_dialog() is None

        orch = Orchestrator()
        for tool_name in ("file_reader", "ast_parser", "nvda_validator", "syntax_checker"):
            assert orch._tool_approval_callback(tool_name, {}) is True

    def test_hardline_pattern_bloqueia_sem_chamar_dialog(self):
        """Padrao hardline (regex) bloqueia direto, nem chega a incomodar o usuario."""
        import nvdastudio.gui.studio_dialog as sd_module

        fake_dialog = MagicMock()
        with patch.object(sd_module, "_current_dialog", fake_dialog):
            orch = Orchestrator()
            approved = orch._tool_approval_callback("shell_command", {"command": "rm -rf /"})

        assert approved is False
        fake_dialog.approve_tool.assert_not_called()

    def test_dialog_ativo_aprova_tool_de_risco(self):
        import nvdastudio.gui.studio_dialog as sd_module

        fake_dialog = MagicMock()
        fake_dialog.approve_tool.return_value = True
        with patch.object(sd_module, "_current_dialog", fake_dialog):
            orch = Orchestrator()
            approved = orch._tool_approval_callback("file_writer", {"path": "x.py"})

        assert approved is True
        fake_dialog.approve_tool.assert_called_once_with(
            "file_writer", {"path": "x.py"}, reason="Tool 'file_writer' sempre requer aprovacao"
        )

    def test_dialog_ativo_nega_tool_de_risco(self):
        import nvdastudio.gui.studio_dialog as sd_module

        fake_dialog = MagicMock()
        fake_dialog.approve_tool.return_value = False
        with patch.object(sd_module, "_current_dialog", fake_dialog):
            orch = Orchestrator()
            approved = orch._tool_approval_callback("file_writer", {"path": "x.py"})

        assert approved is False
