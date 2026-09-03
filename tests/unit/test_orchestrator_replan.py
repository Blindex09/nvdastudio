import pytest
from unittest.mock import MagicMock, patch


class TestOrchestratorVersaoV2:
    def test_versao_e_2_6_0(self):
        from nvdastudio.core.orchestrator import MODULE_VERSION
        assert MODULE_VERSION == "5.86.0"

    def test_max_replans_positivo(self):
        from nvdastudio.core.orchestrator import _MAX_REPLANS
        assert _MAX_REPLANS > 0

    def test_max_replans_razoavel(self):
        from nvdastudio.core.orchestrator import _MAX_REPLANS
        assert _MAX_REPLANS <= 5  # nao pode ser infinito

    def test_critical_step_types_definido(self):
        from nvdastudio.core.orchestrator import _CRITICAL_STEP_TYPES
        assert "code_generation" in _CRITICAL_STEP_TYPES
        assert "agent_runner" in _CRITICAL_STEP_TYPES
        assert "manifest_builder" not in _CRITICAL_STEP_TYPES

    def test_escalation_model_e_kimi(self):
        """v5.9.0: _ESCALATION_MODEL era uma constante orfa (nenhuma logica
        a lia) -- removida na auditoria de 2026-07-20. O modelo de escalacao
        real e resolvido dinamicamente por _get_resilience_model() (tier
        heavy do provider atual)."""
        from nvdastudio.core.orchestrator import _get_resilience_model
        assert _get_resilience_model().startswith("kimi-k2")

    def test_escalation_reasoning_nao_vazio(self):
        from nvdastudio.core.orchestrator import _ESCALATION_REASONING
        assert "code_generation" in _ESCALATION_REASONING
        assert _ESCALATION_REASONING.get("code_generation") == {"reasoning_effort": "high"}

    def test_escalation_reasoning_usa_chave_universal_nao_especifica_do_ollama(self):
        """
        Achado real (2026-08-09): {"think": True} e vocabulario ESPECIFICO
        do Ollama (ollama_client.py mapeia pro payload nativo "think"), mas
        _ESCALATION_REASONING_BY_TYPE e usado via **reasoning_params em
        QUALQUER provider (_try_cross_provider_rescue/_try_escalation) --
        ollama_client.py, provider_client.py (openai/gemini/xai) e
        opencode_go_client.py tem TODOS reasoning_effort na assinatura real
        de chat(), nao "think". client.chat(**kwargs) absorve "think"
        silenciosamente sem erro (todos tem **kwargs), mas sem efeito algum
        -- a escalacao de code_generation pra qualquer provider que nao
        Ollama nunca elevava o raciocinio de verdade. Reproduzido ao vivo:
        gpt-5.6-sol (modelo de raciocinio da OpenAI) devolveu content vazio
        (raciocinio consumiu o orcamento de tokens sem emitir mensagem
        visivel) -- padrao de falha documentado pela OpenAI quando
        reasoning_effort nao e definido explicitamente."""
        from nvdastudio.core.orchestrator import _ESCALATION_REASONING_BY_TYPE
        cg_params = _ESCALATION_REASONING_BY_TYPE.get("code_generation", {})
        assert "think" not in cg_params
        assert cg_params.get("reasoning_effort") == "high"

    def test_replan_count_no_orchestration_result(self):
        from nvdastudio.core.orchestrator import OrchestrationResult
        r = OrchestrationResult(
            plan_id="x", query="q", step_results=[],
            final_output="", success=True
        )
        assert r.replan_count == 0

    def test_replan_count_preenchido(self):
        from nvdastudio.core.orchestrator import OrchestrationResult
        r = OrchestrationResult(
            plan_id="x", query="q", step_results=[],
            final_output="", success=True,
            replan_count=2
        )
        assert r.replan_count == 2


class TestStepArtifactScope:
    def test_code_generation_descarta_manifest_e_documentacao(self):
        from nvdastudio.core.orchestrator import _scope_output_to_step
        output = (
            "```python:globalPlugins/Teste/__init__.py\nimport ui\n```\n"
            "```ini:manifest.ini\nname = Teste Com Espaco\n```\n"
            "```html:doc/pt_BR/userGuide.html\n<html></html>\n```"
        )
        scoped = _scope_output_to_step("code_generation", output)
        assert "import ui" in scoped
        assert "manifest.ini" not in scoped
        assert "userGuide.html" not in scoped

    def test_code_generation_preserva_recurso_nvda(self):
        from nvdastudio.core.orchestrator import _scope_output_to_step
        output = "```text:speechDicts/pronuncia.dic\na\tb\t1\t0\n```"
        assert "speechDicts/pronuncia.dic" in _scope_output_to_step("code_generation", output)

    def test_manifest_builder_recebe_so_manifest(self):
        from nvdastudio.core.orchestrator import _scope_output_to_step
        output = (
            "```python:globalPlugins/Teste/__init__.py\nimport ui\n```\n"
            "```ini:manifest.ini\nname = Teste\n```"
        )
        scoped = _scope_output_to_step("manifest_builder", output)
        assert "manifest.ini" in scoped
        assert "import ui" not in scoped

    def test_web_research_nao_e_escaneado_por_extract_code_blocks(self):
        """
        5.38.0: causa raiz real (test_e36, 2026-08-09) -- web_researcher.py
        4.8.0 ja garante que run() nunca retorna ```python:arquivo.py``` (guard
        deterministico), mas _scope_output_to_step() rodava DEPOIS, no loop de
        retry, ANTES do Critic avaliar. extract_code_blocks() infere um
        filename ate pra um bloco ```python``` SEM anotacao (o trecho curto
        legitimo do campo "Exemplo minimo" que o formato de resposta do
        WebResearcher permite de proposito) -- a reconstrucao subsequente
        RECRIAVA ```python:modulo_inferido.py``` do zero, mesmo com a pesquisa
        saindo limpa do sub-agente. web_research nunca precisa de scoping
        (nunca escreve arquivo do addon), entao deve passar direto.
        """
        from nvdastudio.core.orchestrator import _scope_output_to_step
        output = (
            "**Pacote:** google-generativeai\n"
            "**Exemplo minimo:**\n"
            "```python\n"
            "genai.configure(api_key='...')\n"
            "```\n"
            "**Confianca:** Alta"
        )
        scoped = _scope_output_to_step("web_research", output)
        assert scoped == output
        assert "```python:" not in scoped

    def test_web_research_com_violacao_de_verdade_tambem_passa_intacto(self):
        """Nao e papel do scoping corrigir violacao de formato -- isso e
        responsabilidade do guard em web_researcher.py (4.8.0). Scoping so
        precisa NAO piorar/recriar o problema."""
        from nvdastudio.core.orchestrator import _scope_output_to_step
        output = "```python:module_1.py\nimport google.generativeai as genai\n```"
        assert _scope_output_to_step("web_research", output) == output


class TestCriticContextIncluiObjetivoDoStep:
    """
    5.44.0: achado real (test_e36, GeminiMultimodal, apos ARCH-010) --
    evaluate_two_stage() nunca recebia step.description, so `context`
    (saida de steps anteriores). Sem saber o OBJETIVO do proprio step, o
    Critic rejeitava sistematicamente subpacotes de feature (ARCH-010) por
    faltar classe GlobalPlugin -- regra correta so para o step FINAL da
    decomposicao. _critic_context() fecha esse gap.
    """

    def test_prepende_objetivo_quando_ha_description(self):
        from nvdastudio.core.orchestrator import _critic_context
        from nvdastudio.core.planner import ExecutionStep

        step = ExecutionStep(
            step_id="cg_video", step_type="code_generation",
            description="Gere o subpacote video/ (transcricao de video)",
            model_id="kimi-k2.6", reasoning_params={},
        )
        result = _critic_context(step, "contexto de steps anteriores")
        assert "Objetivo deste step: Gere o subpacote video/ (transcricao de video)" in result
        assert "contexto de steps anteriores" in result

    def test_sem_description_retorna_context_original(self):
        from nvdastudio.core.orchestrator import _critic_context
        from nvdastudio.core.planner import ExecutionStep

        step = ExecutionStep(
            step_id="s1", step_type="code_generation", description="",
            model_id="kimi-k2.6", reasoning_params={},
        )
        assert _critic_context(step, "contexto original") == "contexto original"

    def test_context_vazio_retorna_so_o_objetivo(self):
        from nvdastudio.core.orchestrator import _critic_context
        from nvdastudio.core.planner import ExecutionStep

        step = ExecutionStep(
            step_id="s1", step_type="code_generation",
            description="Gere o __init__.py raiz",
            model_id="kimi-k2.6", reasoning_params={},
        )
        assert _critic_context(step, "") == "Objetivo deste step: Gere o __init__.py raiz"


class TestNeedsReplan:
    """_needs_replan: True quando step critico nao aprovado."""

    def _make_result(self, step_type, approved):
        from nvdastudio.core.orchestrator import StepResult
        return StepResult(
            step_id="s1", step_type=step_type,
            output="x", approved=approved, score=50
        )

    def test_critico_nao_aprovado_retorna_true(self):
        from nvdastudio.core.orchestrator import Orchestrator
        orch = Orchestrator()
        result = self._make_result("code_generation", approved=False)
        assert orch._needs_replan([result]) is True

    def test_critico_aprovado_retorna_false(self):
        from nvdastudio.core.orchestrator import Orchestrator
        orch = Orchestrator()
        result = self._make_result("code_generation", approved=True)
        assert orch._needs_replan([result]) is False

    def test_nao_critico_nao_aprovado_retorna_false(self):
        from nvdastudio.core.orchestrator import Orchestrator
        orch = Orchestrator()
        result = self._make_result("accessibility_audit", approved=False)
        assert orch._needs_replan([result]) is False

    def test_manifest_builder_nao_aprovado_retorna_false(self):
        """manifest_builder e nao-bloqueante: assembly pode regenerar manifest sem replan."""
        from nvdastudio.core.orchestrator import Orchestrator
        orch = Orchestrator()
        result = self._make_result("manifest_builder", approved=False)
        assert orch._needs_replan([result]) is False

    def test_lista_mista_retorna_true_se_algum_critico_falhou(self):
        from nvdastudio.core.orchestrator import Orchestrator, StepResult
        orch = Orchestrator()
        r1 = StepResult("s1", "accessibility_audit", "x", False, 0)
        r2 = StepResult("s2", "code_generation", "y", False, 0)
        assert orch._needs_replan([r1, r2]) is True

    def test_lista_vazia_retorna_false(self):
        from nvdastudio.core.orchestrator import Orchestrator
        orch = Orchestrator()
        assert orch._needs_replan([]) is False

    def test_nao_executa_codigo(self):
        from nvdastudio.core.orchestrator import Orchestrator, StepResult
        orch = Orchestrator()
        r = StepResult("s1", "code_generation",
                       "import os; os.system('del /q')", False, 0)
        result = orch._needs_replan([r])
        assert isinstance(result, bool)


class TestDiversifyFailedModels:
    """_diversify_failed_models: cross-model escalation para o replan.

    Achado 2026-07-20: Planner.replan(model_map=...) sempre foi um no-op
    silencioso (o parametro nunca chegava a _build_steps, e mesmo chegando
    seria sobrescrito por apply_model_budget). Pesquisa web confirmou que
    "cross-model escalation" -- forcar um modelo DIFERENTE apos falha +
    escalacao ja terem esgotado o modelo padrao -- e pratica validada em
    2026 (modelos diferentes tem modos de falha complementares). Corrigido
    e agora _do_replan usa este metodo para popular o override real.
    """

    def test_step_critico_reprovado_ganha_proximo_modelo_da_cadeia(self, fake_api_key):
        from nvdastudio.core.orchestrator import Orchestrator, StepResult

        orch = Orchestrator()
        orch._api_key = fake_api_key
        failed = [StepResult(
            "s0", "code_generation", "", False, 0, ["erro"],
            model_used="kimi-k2.7-code",
        )]

        result = orch._diversify_failed_models(failed)

        # Proximo modelo na cadeia apos kimi-k2.7-code (model_registry.py
        # 1.10.0 estendeu _FALLBACK_CHAINS["ollama"] com glm-5.2/minimax-m3
        # antes de kimi-k2.6 -- glm-5.2 agora e o 2o da cadeia).
        assert result == {"code_generation": "glm-5.2"}

    def test_step_aprovado_e_ignorado(self, fake_api_key):
        from nvdastudio.core.orchestrator import Orchestrator, StepResult

        orch = Orchestrator()
        orch._api_key = fake_api_key
        failed = [StepResult(
            "s0", "code_generation", "", True, 100,
            model_used="kimi-k2.7-code",
        )]

        assert orch._diversify_failed_models(failed) is None

    def test_step_nao_critico_e_ignorado(self, fake_api_key):
        from nvdastudio.core.orchestrator import Orchestrator, StepResult

        orch = Orchestrator()
        orch._api_key = fake_api_key
        failed = [StepResult(
            "s0", "manifest_builder", "", False, 0, ["erro"],
            model_used="kimi-k2.7-code",
        )]

        assert orch._diversify_failed_models(failed) is None

    def test_sem_falhas_criticas_retorna_none(self, fake_api_key):
        from nvdastudio.core.orchestrator import Orchestrator

        orch = Orchestrator()
        orch._api_key = fake_api_key
        assert orch._diversify_failed_models([]) is None

    def test_dois_steps_criticos_diferentes_cada_um_ganha_seu_proprio_override(self, fake_api_key):
        from nvdastudio.core.orchestrator import Orchestrator, StepResult

        orch = Orchestrator()
        orch._api_key = fake_api_key
        failed = [
            StepResult("s0", "code_generation", "", False, 0, model_used="kimi-k2.7-code"),
            StepResult("s1", "agent_runner", "", False, 0, model_used="deepseek-v4-flash"),
        ]

        result = orch._diversify_failed_models(failed)

        assert result["code_generation"] == "glm-5.2"
        assert result["agent_runner"] == "kimi-k2.7-code"


class TestDoReplan:
    """_do_replan: chama planner.replan() e retorna novos steps."""

    def test_replan_retorna_steps_do_planner(self, fake_api_key):
        from nvdastudio.core.orchestrator import Orchestrator, StepResult
        from nvdastudio.core.planner import ExecutionStep

        orch = Orchestrator()
        orch._api_key = fake_api_key

        mock_step = ExecutionStep(
            step_id="s_new", step_type="code_generation",
            description="novo step", model_id="kimi-k2.6"
        )
        mock_planner = MagicMock()
        mock_planner.replan.return_value = [mock_step]
        orch._planner = mock_planner

        remaining = [ExecutionStep("s1", "assembly", "", "kimi-k2.6")]
        failed = [StepResult("s0", "code_generation", "", False, 0, ["erro"])]

        result = orch._do_replan("criar addon", {}, remaining, failed)

        assert len(result) == 1
        assert result[0].step_id == "s_new"
        mock_planner.replan.assert_called_once()

    def test_replan_repassa_model_map_diversificado_para_o_planner(self, fake_api_key):
        """_do_replan deve chamar planner.replan(model_map=...) com o modelo
        diversificado do step critico que falhou (cross-model escalation)."""
        from nvdastudio.core.orchestrator import Orchestrator, StepResult
        from nvdastudio.core.planner import ExecutionStep

        orch = Orchestrator()
        orch._api_key = fake_api_key

        mock_planner = MagicMock()
        mock_planner.replan.return_value = [
            ExecutionStep("s_new", "code_generation", "novo", "x")
        ]
        orch._planner = mock_planner

        remaining = [ExecutionStep("s1", "assembly", "", "kimi-k2.6")]
        failed = [StepResult(
            "s0", "code_generation", "", False, 0, ["erro"],
            model_used="kimi-k2.7-code",
        )]

        orch._do_replan("criar addon", {}, remaining, failed)

        _, kwargs = mock_planner.replan.call_args
        assert kwargs["model_map"] == {"code_generation": "glm-5.2"}

    def test_replan_falha_retorna_steps_originais(self, fake_api_key):
        from nvdastudio.core.orchestrator import Orchestrator, StepResult
        from nvdastudio.core.planner import ExecutionStep

        orch = Orchestrator()
        orch._api_key = fake_api_key

        mock_planner = MagicMock()
        mock_planner.replan.side_effect = Exception("API indisponivel")
        orch._planner = mock_planner

        original = [ExecutionStep("s1", "assembly", "", "kimi-k2.6")]
        failed = [StepResult("s0", "code_generation", "", False, 0)]

        result = orch._do_replan("criar addon", {}, original, failed)

        # Fallback: retorna originais
        assert result == original

    def test_replan_nao_executa_output_anterior(self, fake_api_key):
        from nvdastudio.core.orchestrator import Orchestrator, StepResult
        from nvdastudio.core.planner import ExecutionStep

        orch = Orchestrator()
        orch._api_key = fake_api_key

        mock_planner = MagicMock()
        mock_planner.replan.return_value = []
        orch._planner = mock_planner

        remaining = [ExecutionStep("s1", "assembly", "", "kimi-k2.6")]
        failed = [StepResult("s0", "code_generation",
                             "import os; os.system('bad')", False, 0)]

        result = orch._do_replan("criar addon", {}, remaining, failed)
        # Nao executou o output — retornou lista (original pois replan retornou [])
        assert isinstance(result, list)


class TestTryEscalation:
    """_try_escalation: usa deepseek-v4-flash quando modelo original falha."""

    def test_escalation_usa_escalation_model(self, fake_api_key):
        from nvdastudio.core.orchestrator import Orchestrator, _get_resilience_model
        from nvdastudio.core.planner import ExecutionStep

        mock_resp = MagicMock()
        mock_resp.content = "codigo gerado"

        mock_crit = MagicMock()
        mock_crit.verdict.value = "APROVADO"
        from nvdastudio.ai.critic import Verdict
        mock_crit.verdict = Verdict.APPROVED
        mock_crit.score = 90
        mock_crit.issues = []

        orch = Orchestrator()
        orch._api_key = fake_api_key
        orch._critic = MagicMock()
        orch._critic.evaluate_two_stage.return_value = mock_crit

        step = ExecutionStep(
            step_id="s1", step_type="code_generation",
            description="gerar", model_id="kimi-k2.6"
        )

        modelos_usados = []

        def fake_dispatch(**kwargs):
            modelos_usados.append(kwargs.get("model_id", ""))
            return ("codigo gerado", 42)

        with patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", side_effect=fake_dispatch):
            orch._try_escalation(step, "criar addon", "", ["erro anterior"])

        # _try_escalation() chama _get_resilience_model(step.step_type, ...)
        # internamente (5.36.0) -- roteamento DINAMICO por step_type, nao o
        # fallback estatico de _get_resilience_model() sem argumentos (esse
        # so vale pra chamador antigo/desconhecido). model_router.py 1.3.0/
        # model_registry.py 1.16.0 corrigiram cost_tier com dados reais --
        # a identidade do modelo escolhido pode ter mudado, mas o
        # INVARIANTE (escalar usa o modelo de resiliencia pro step_type
        # real) continua o mesmo.
        assert _get_resilience_model(step.step_type) in modelos_usados

    def test_escalation_retorna_step_result(self, fake_api_key):
        from nvdastudio.core.orchestrator import Orchestrator, StepResult
        from nvdastudio.core.planner import ExecutionStep
        from nvdastudio.ai.critic import Verdict

        mock_crit = MagicMock()
        mock_crit.verdict = Verdict.APPROVED
        mock_crit.score = 85
        mock_crit.issues = []

        orch = Orchestrator()
        orch._api_key = fake_api_key
        orch._critic = MagicMock()
        orch._critic.evaluate_two_stage.return_value = mock_crit

        step = ExecutionStep("s1", "code_generation", "", "kimi-k2.6")

        with patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", return_value=("output", 10)):
            result = orch._try_escalation(step, "query", "", [])

        assert isinstance(result, StepResult)
        assert result.step_id == "s1"

    def test_escalation_falha_retorna_resultado_nao_aprovado(self, fake_api_key):
        from nvdastudio.core.orchestrator import Orchestrator, StepResult
        from nvdastudio.core.planner import ExecutionStep

        orch = Orchestrator()
        orch._api_key = fake_api_key
        orch._critic = MagicMock()

        step = ExecutionStep("s1", "code_generation", "", "kimi-k2.6")

        with patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", side_effect=Exception("falha")):
            result = orch._try_escalation(step, "query", "", [])

        assert isinstance(result, StepResult)
        assert not result.approved

    def test_escalation_nao_executa_output(self, fake_api_key):
        from nvdastudio.core.orchestrator import Orchestrator
        from nvdastudio.core.planner import ExecutionStep
        from nvdastudio.ai.critic import Verdict

        mock_crit = MagicMock()
        mock_crit.verdict = Verdict.APPROVED
        mock_crit.score = 80
        mock_crit.issues = []

        orch = Orchestrator()
        orch._api_key = fake_api_key
        orch._critic = MagicMock()
        orch._critic.evaluate_two_stage.return_value = mock_crit

        step = ExecutionStep("s1", "code_generation", "", "kimi-k2.6")
        malicious = "import os; os.system('del /f /q C:\\\\')"

        with patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", return_value=(malicious, 0)):
            result = orch._try_escalation(step, "query", "", [])

        # Resultado retornado mas codigo nao executado
        assert result.output == malicious


class TestEscalacaoDeVerdadeAposSwitchProativo:
    """
    5.52.0: BUG REAL achado ao vivo (test_e36, os 2 casos do golden eval set,
    2026-08-17) -- cg_core (o step que gera __init__.py raiz com a classe
    GlobalPlugin) esgotava os 3 retries de code_generation sem NUNCA tentar
    com reasoning_effort=high, porque o switch proativo dentro do loop de
    retry (attempt>0) ja trocava step.model_id pro resilience_model (so que
    com reasoning_params vazio) -- e a checagem final de escalacao so
    comparava model_id, entao via "mesmo modelo" e pulava _try_escalation()
    de verdade. Consequencia real: os 2 addons finais saiam sem __init__.py,
    que o NVDA nunca carrega.

    Estes testes travam que, mesmo apos o switch proativo ja ter trocado
    o modelo, um step code_generation que esgota todos os retries AINDA
    recebe uma tentativa final com reasoning_params de escalacao genuina
    (reasoning_effort=high) antes de desistir -- nao so o mesmo modelo com
    reasoning_params vazio de novo.
    """

    def test_code_generation_recebe_reasoning_effort_high_apos_esgotar_retries(self, fake_api_key):
        from nvdastudio.core.orchestrator import (
            Orchestrator, _ESCALATION_REASONING_BY_TYPE,
        )
        from nvdastudio.core.planner import ExecutionStep
        from nvdastudio.ai.critic import Verdict

        mock_crit_rejeita = MagicMock()
        mock_crit_rejeita.verdict = Verdict.REJECTED
        mock_crit_rejeita.score = 0
        mock_crit_rejeita.issues = ["erro de execucao real (import/instanciacao)"]
        mock_crit_rejeita.fix_instructions = "corrija o import"

        orch = Orchestrator()
        orch._api_key = fake_api_key
        orch._critic = MagicMock()
        # Critic rejeita SEMPRE -- inclusive na chamada extra de _try_escalation()
        # e no resgate cross-provider (se chegar la).
        orch._critic.evaluate_two_stage.return_value = mock_crit_rejeita

        step = ExecutionStep(
            step_id="cg_core", step_type="code_generation",
            description="gera __init__.py raiz com GlobalPlugin",
            model_id="qwen3.5:397b", max_retries=3,
        )

        reasoning_params_usados = []

        def fake_dispatch(**kwargs):
            reasoning_params_usados.append(kwargs.get("reasoning_params"))
            return ("codigo gerado com bug", 100)

        with patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", side_effect=fake_dispatch), \
             patch("nvdastudio.core.orchestrator.Orchestrator._try_cross_provider_rescue", return_value=None):
            resultado = orch._execute_step_with_critique(step, "criar addon complexo", "")

        assert not resultado.approved, "Critic rejeita sempre -- step nao deveria aprovar"

        esperado = _ESCALATION_REASONING_BY_TYPE.get("code_generation")
        assert esperado == {"reasoning_effort": "high"}, (
            "Pre-condicao do teste: code_generation deve ter reasoning_params "
            "de escalacao real e nao-vazio, senao este teste nao prova nada."
        )
        assert esperado in reasoning_params_usados, (
            f"O step esgotou os retries mas NUNCA foi tentado com "
            f"reasoning_params de escalacao genuina ({esperado}) -- regressao "
            f"do bug 5.52.0 (switch proativo mascarando a necessidade de "
            f"escalar de verdade). reasoning_params usados: {reasoning_params_usados}"
        )

    def test_agent_runner_mantem_comportamento_identico_ao_anterior(self, fake_api_key):
        """agent_runner nao tem reasoning_params de escalacao diferenciado
        (_ESCALATION_REASONING_BY_TYPE['agent_runner'] == {}) -- o fix nao
        deve mudar seu comportamento: continua escalando por MODELO como
        sempre fez, sem exigir reasoning_params extra que nao existe pra
        esse step_type."""
        from nvdastudio.core.orchestrator import (
            Orchestrator, _ESCALATION_REASONING_BY_TYPE,
        )
        from nvdastudio.core.planner import ExecutionStep
        from nvdastudio.ai.critic import Verdict

        assert _ESCALATION_REASONING_BY_TYPE.get("agent_runner") == {}

        mock_crit_rejeita = MagicMock()
        mock_crit_rejeita.verdict = Verdict.REJECTED
        mock_crit_rejeita.score = 0
        mock_crit_rejeita.issues = ["falhou"]
        mock_crit_rejeita.fix_instructions = "tente de novo"

        orch = Orchestrator()
        orch._api_key = fake_api_key
        orch._critic = MagicMock()
        orch._critic.evaluate_two_stage.return_value = mock_crit_rejeita

        step = ExecutionStep(
            step_id="ar1", step_type="agent_runner",
            description="roda agente", model_id="qwen3.5:397b", max_retries=2,
        )

        with patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", return_value=("output", 10)), \
             patch("nvdastudio.core.orchestrator.Orchestrator._try_cross_provider_rescue", return_value=None):
            resultado = orch._execute_step_with_critique(step, "criar addon", "")

        # Nao deve levantar excecao nem travar -- so confirma que o caminho
        # continua funcionando (comportamento identico, sem regressao).
        assert not resultado.approved


class TestEmitCheckpoint:
    """
    5.41.0: CheckpointResult/on_checkpoint (orch_types.py) ja existiam com
    o contrato inteiro pronto -- studio_dialog.py ja tinha
    _on_conversational_checkpoint() implementado e conectado -- mas o
    Orchestrator nunca disparava um checkpoint de verdade. _emit_checkpoint()
    fecha isso: avisa quando a confianca cai (escalacao acionada, ou
    escalacao+resgate cross-provider ambos falharam), mas NUNCA pausa --
    decisao explicita do Felipe ja registrada em _on_conversational_
    checkpoint(), reconfirmada nesta sessao.
    """

    def test_emit_checkpoint_sem_callback_nao_quebra(self, fake_api_key):
        from nvdastudio.core.orchestrator import Orchestrator
        from nvdastudio.core.planner import ExecutionStep

        orch = Orchestrator()
        orch._api_key = fake_api_key
        step = ExecutionStep("s1", "code_generation", "", "kimi-k2.6")
        orch._emit_checkpoint(step, "teste")  # nao deve lancar excecao

    def test_emit_checkpoint_chama_on_checkpoint_com_should_continue_true(self, fake_api_key):
        from nvdastudio.core.orchestrator import Orchestrator, PipelinePhase
        from nvdastudio.core.planner import ExecutionStep

        orch = Orchestrator()
        orch._api_key = fake_api_key
        received = []
        orch._on_checkpoint = lambda cp: (received.append(cp), True)[1]

        step = ExecutionStep("s1", "code_generation", "", "kimi-k2.6")
        orch._emit_checkpoint(step, "confianca baixa")

        assert len(received) == 1
        assert received[0].step_id == "s1"
        assert received[0].step_type == "code_generation"
        assert received[0].summary == "confianca baixa"
        assert received[0].should_continue is True
        assert received[0].phase == PipelinePhase.EXECUTING

    def test_emit_checkpoint_ignora_should_continue_false(self, fake_api_key):
        """Decisao explicita: nunca pausa, independente do retorno do
        callback -- should_continue e sempre True quando emitido, e o
        pipeline nunca le o retorno do callback pra decidir parar."""
        from nvdastudio.core.orchestrator import Orchestrator
        from nvdastudio.core.planner import ExecutionStep

        orch = Orchestrator()
        orch._api_key = fake_api_key
        orch._on_checkpoint = lambda cp: False  # usuario "recusaria" continuar

        step = ExecutionStep("s1", "code_generation", "", "kimi-k2.6")
        orch._emit_checkpoint(step, "teste")  # nao deve lancar nem mudar comportamento

    def test_emit_checkpoint_com_excecao_no_callback_nao_propaga(self, fake_api_key):
        from nvdastudio.core.orchestrator import Orchestrator
        from nvdastudio.core.planner import ExecutionStep

        orch = Orchestrator()
        orch._api_key = fake_api_key
        orch._on_checkpoint = lambda cp: (_ for _ in ()).throw(RuntimeError("boom"))

        step = ExecutionStep("s1", "code_generation", "", "kimi-k2.6")
        orch._emit_checkpoint(step, "teste")  # nao deve propagar a excecao

    def test_escalacao_dispara_checkpoint(self, fake_api_key):
        """A propria escalacao (retries normais esgotados) ja e um sinal
        real de confianca baixa -- deve disparar o aviso."""
        from nvdastudio.core.orchestrator import Orchestrator
        from nvdastudio.core.planner import ExecutionStep
        from nvdastudio.ai.critic import Verdict

        mock_crit = MagicMock()
        mock_crit.verdict = Verdict.APPROVED
        mock_crit.score = 85
        mock_crit.issues = []

        orch = Orchestrator()
        orch._api_key = fake_api_key
        orch._critic = MagicMock()
        orch._critic.evaluate_two_stage.return_value = mock_crit
        received = []
        orch._on_checkpoint = lambda cp: (received.append(cp), True)[1]

        step = ExecutionStep("s1", "code_generation", "", "kimi-k2.6")
        with patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", return_value=("output", 10)):
            orch._try_escalation(step, "query", "", ["erro anterior"])

        assert len(received) >= 1
        assert "code_generation" in received[0].summary


class TestMensagensStatusRicas:
    """Status messages agora sao ricas e anunciaveis pelo NVDA."""

    def test_retry_nao_emite_mensagem_corrigindo_por_tentativa(self, fake_api_key):
        """
        Achado de auditoria 2026-08-04: este teste chamava
        _execute_step_with_critique() e capturava `eventos`, mas nunca
        verificava o conteudo -- passaria identico com qualquer
        comportamento. O nome/docstring original ("CORRIGINDO deve
        mencionar numero da tentativa") descrevia um comportamento JA
        REMOVIDO do orchestrator ha varias rodadas (ver comentario real no
        codigo: "Mensagem de retry removida -- evita poluir o historico").
        Reescrito pra travar o comportamento ATUAL e intencional: nenhum
        evento de progresso com "CORRIGINDO" ou numero de tentativa e
        emitido a cada retry (narracao verbosa por tentativa foi
        deliberadamente descontinuada nesta sessao/projeto).
        """
        from nvdastudio.core.orchestrator import Orchestrator
        from nvdastudio.core.planner import ExecutionStep
        from nvdastudio.ai.critic import Verdict

        eventos = []

        def captura_evento(event, detail):
            eventos.append((event, detail))

        orch = Orchestrator()
        orch._api_key = fake_api_key
        orch.set_callbacks(on_progress=captura_evento, on_complete=lambda r: None)

        # Critic retorna CORRIGIR na primeira tentativa, APROVADO na segunda
        mock_crit_fix = MagicMock()
        mock_crit_fix.verdict = Verdict.NEEDS_FIX
        mock_crit_fix.score = 40
        mock_crit_fix.issues = ["algo errado"]
        mock_crit_fix.fix_instructions = "corrija X"

        mock_crit_ok = MagicMock()
        mock_crit_ok.verdict = Verdict.APPROVED
        mock_crit_ok.score = 90
        mock_crit_ok.issues = []

        orch._critic = MagicMock()
        orch._critic.evaluate_two_stage.side_effect = [mock_crit_fix, mock_crit_ok]

        step = ExecutionStep("s1", "manifest_builder", "gerar manifest",
                             "kimi-k2.6", max_retries=3)

        with patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", return_value=("output", 0)):
            resultado = orch._execute_step_with_critique(step, "criar addon", "")

        assert resultado.approved, "Step deveria aprovar na 2a tentativa (mock_crit_ok)"
        mensagens_corrigindo = [
            (evt, det) for evt, det in eventos
            if "CORRIGINDO" in str(evt).upper() or "tentativa" in str(det).lower()
        ]
        assert mensagens_corrigindo == [], (
            f"Nenhum evento de status deveria mencionar 'CORRIGINDO' ou "
            f"'tentativa' por retry (removido de proposito -- evita poluir "
            f"o historico). Encontrado: {mensagens_corrigindo}"
        )


class TestDesignReviewNonBlocking:
    """design_review deve estar em _NON_BLOCKING_STEP_TYPES para nao travar pipeline."""

    def test_design_review_em_non_blocking(self):
        from nvdastudio.core.orchestrator import _NON_BLOCKING_STEP_TYPES
        assert "design_review" in _NON_BLOCKING_STEP_TYPES, (
            "design_review ausente de _NON_BLOCKING_STEP_TYPES: "
            "reprovacao bloqueia code_generation e gera addon sem codigo."
        )

    def test_design_review_reprovado_nao_dispara_replan(self):
        """design_review reprovado nao deve disparar replan (nao e step critico)."""
        from nvdastudio.core.orchestrator import Orchestrator, StepResult
        orch = Orchestrator()
        result = StepResult("dr0", "design_review", "feedback", approved=False, score=85)
        assert orch._needs_replan([result]) is False

    def test_non_blocking_inclui_tipos_esperados(self):
        from nvdastudio.core.orchestrator import _NON_BLOCKING_STEP_TYPES
        # Q10.3: test_generation BLOQUEIA (decisao do usuario, mantida).
        # web_research nao bloqueia (offline nao impede o pipeline).
        # documentation passou a NAO bloquear em 2026-09-02, aprovado pelo
        # Felipe: um documentation reprovado 3x descartou o addon complexo
        # inteiro, ja gerado e aprovado. So foi seguro afrouxar porque
        # addon_builder 4.22.0 passou a injetar um guia minimo -- mesma rede
        # que ja tornava manifest_builder nao-bloqueante.
        for tipo in ("accessibility_audit", "design_review", "web_research", "documentation"):
            assert tipo in _NON_BLOCKING_STEP_TYPES, f"{tipo} ausente de _NON_BLOCKING_STEP_TYPES"
        for tipo_bloqueante in ("test_generation",):
            assert tipo_bloqueante not in _NON_BLOCKING_STEP_TYPES, (
                f"{tipo_bloqueante} deveria ser bloqueante agora")

    @pytest.mark.skip(reason="Progresso AVALIANDO desativado no orquestrador")
    def test_avaliando_tem_mensagem_concreta(self, fake_api_key):
        """AVALIANDO deve ter mensagem descritiva (nao vazia)."""
        from nvdastudio.core.orchestrator import Orchestrator
        from nvdastudio.core.planner import ExecutionStep
        from nvdastudio.ai.critic import Verdict

        eventos = []

        def captura(event, detail):
            eventos.append((event, detail))

        orch = Orchestrator()
        orch._api_key = fake_api_key
        orch.set_callbacks(on_progress=captura, on_complete=lambda r: None)

        mock_crit = MagicMock()
        mock_crit.verdict = Verdict.APPROVED
        mock_crit.score = 90
        mock_crit.issues = []

        orch._critic = MagicMock()
        orch._critic.evaluate_two_stage.return_value = mock_crit

        step = ExecutionStep("s1", "code_generation", "gerar codigo",
                             "kimi-k2.6", max_retries=3)

        with patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", return_value=("output", 0)):
            orch._execute_step_with_critique(step, "criar addon", "")

        avaliando_msgs = [(e, d) for e, d in eventos if e == "AVALIANDO"]
        assert len(avaliando_msgs) >= 1
        # Mensagem nao vazia
        assert all(d != "" for e, d in avaliando_msgs)

    @pytest.mark.skip(reason="Progresso PARALELO desativado no orquestrador")
    def test_paralelo_tem_mensagem_com_contagem(self, fake_api_key):
        """PARALELO deve informar quantos steps estao em paralelo."""
        from nvdastudio.core.orchestrator import Orchestrator
        from nvdastudio.core.planner import ExecutionStep
        from nvdastudio.ai.critic import Verdict

        eventos = []

        def captura(event, detail):
            eventos.append((event, detail))

        orch = Orchestrator()
        orch._api_key = fake_api_key
        orch.set_callbacks(on_progress=captura, on_complete=lambda r: None)

        mock_crit = MagicMock()
        mock_crit.verdict = Verdict.APPROVED
        mock_crit.score = 90
        mock_crit.issues = []

        orch._critic = MagicMock()
        orch._critic.evaluate_two_stage.return_value = mock_crit

        steps = [
            ExecutionStep("s1", "manifest_builder", "m", "kimi-k2.6",
                          max_retries=1),
            ExecutionStep("s2", "accessibility_audit", "a", "kimi-k2.6",
                          max_retries=1),
        ]

        with patch("nvdastudio.core.orchestrator.dispatch_step_with_tokens", return_value=("output", 0)):
            orch._execute_parallel(steps, "criar addon", {})

        paralelo_msgs = [d for e, d in eventos if e == "PARALELO"]
        assert len(paralelo_msgs) >= 1
        assert any("2" in msg or "paralelo" in msg.lower() for msg in paralelo_msgs)


class TestAnnounceEventsExpanded:
    """studio_dialog: novos eventos agora estao em _ANNOUNCE_EVENTS."""

    def test_corrigindo_em_announce_events(self):
        from nvdastudio.gui.studio_dialog import _ANNOUNCE_EVENTS
        assert "CORRIGINDO" in _ANNOUNCE_EVENTS

    def test_avaliando_em_announce_events(self):
        from nvdastudio.gui.studio_dialog import _ANNOUNCE_EVENTS
        assert "AVALIANDO" in _ANNOUNCE_EVENTS

    def test_replanejando_em_announce_events(self):
        from nvdastudio.gui.studio_dialog import _ANNOUNCE_EVENTS
        assert "REPLANEJANDO" in _ANNOUNCE_EVENTS

    def test_escalando_em_announce_events(self):
        from nvdastudio.gui.studio_dialog import _ANNOUNCE_EVENTS
        assert "ESCALANDO" in _ANNOUNCE_EVENTS

    def test_paralelo_em_announce_events(self):
        from nvdastudio.gui.studio_dialog import _ANNOUNCE_EVENTS
        assert "PARALELO" in _ANNOUNCE_EVENTS

    def test_eventos_originais_mantidos(self):
        from nvdastudio.gui.studio_dialog import _ANNOUNCE_EVENTS
        for evento in ("PLANEJANDO", "PLANO_CRIADO", "EXECUTANDO",
                       "MONTANDO", "CONCLUIDO", "ERRO"):
            assert evento in _ANNOUNCE_EVENTS



class TestDominioIdentificadoNaoVazaParaUsuario:
    """Contexto tecnico de pesquisa nunca deve ser exibido ao usuario."""

    def test_emissao_dominio_identificado_removida_do_codigo(self):
        """O changelog no docstring do modulo pode citar a string removida
        (documentando o fix) -- o que nao pode existir e a CHAMADA que emitia
        e falava essa mensagem ao usuario."""
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator)
        assert '_emit_conversation("ia", f"Domínio identificado' not in src
        assert '_emit_conversation("ia", f"Dominio identificado' not in src

    def test_research_summary_nao_e_emitido_via_emit_phase(self):
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator)
        assert "format_domain_context_for_user" not in src
        assert "research_summary" not in src

class TestRunConversationalAsyncSemRaceCondition:
    """v5.3.0: run_conversational_async() checava self._running mas so setava
    a flag para True DENTRO da thread (_run_conversational_pipeline). Duas
    chamadas em sequencia rapida (qualquer duplo-disparo na UI) viam
    self._running == False nas duas e ambas iniciavam pipeline -- bug real de
    live-test: fases/mensagens duplicadas no chat ("Fase: Pesquisando" 2x).
    Fix: self._running = True agora e setado SINCRONAMENTE antes da thread
    iniciar, igual ao padrao ja usado em run_async()."""

    def test_running_fica_true_sincronamente_antes_da_thread_rodar(self, fake_api_key):
        """Bloqueia a thread real com um Event para provar que self._running
        ja e True assim que run_conversational_async() retorna -- sem depender
        de qualquer timing/sleep da thread ter tido chance de rodar."""
        from nvdastudio.core.orchestrator import Orchestrator
        import threading

        gate = threading.Event()
        orch = Orchestrator.__new__(Orchestrator)
        orch._running = False

        def blocked_pipeline(user_query):
            gate.wait(timeout=2)

        with patch.object(orch, "_run_conversational_pipeline", side_effect=blocked_pipeline):
            orch.run_conversational_async("crie um addon")
            # Nenhum sleep aqui -- se a flag so fosse setada dentro da thread,
            # este assert seria uma race de verdade (poderia passar por sorte).
            assert orch._running is True, (
                "self._running deveria ser True IMEDIATAMENTE apos run_conversational_async(), "
                "sem depender da thread ja ter iniciado"
            )
        gate.set()

    def test_segunda_chamada_e_ignorada_enquanto_primeira_esta_pendente(self, fake_api_key):
        """Regressao direta do bug: chamar run_conversational_async() duas vezes
        em sequencia rapida so deve rodar o pipeline UMA vez."""
        from nvdastudio.core.orchestrator import Orchestrator
        import threading

        gate = threading.Event()
        calls = []
        orch = Orchestrator.__new__(Orchestrator)
        orch._running = False

        def blocked_pipeline(user_query):
            calls.append(user_query)
            gate.wait(timeout=2)

        with patch.object(orch, "_run_conversational_pipeline", side_effect=blocked_pipeline):
            orch.run_conversational_async("primeiro pedido")
            orch.run_conversational_async("segundo pedido (duplo-disparo)")
            assert len(calls) == 1, (
                "a segunda chamada deveria ter sido ignorada (self._running ja True), "
                f"mas o pipeline rodou {len(calls)} vezes"
            )
        gate.set()

class TestConstruindoNaoExecutando:
    """v5.4.0: bug real de live-test -- "Executando {addon_name}..." era
    mostrado no INICIO da fase EXECUTING, antes de qualquer codigo existir.
    Usuario: "ele ta criando, entao nao faz sentido executar o addon antes
    da sua criacao." Corrigido para "Construindo {addon_name}..."."""

    def test_mensagem_diz_construindo(self):
        """v5.15.0: a mensagem fixa virou narrate() (narracao de verdade via
        IA, fundamentada no nome real do addon) -- o texto "construir"
        continua presente, so nao e mais uma string estatica solta."""
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator)
        assert 'narrate(f"comecando a construir o {plan.addon_name}")' in src

    def test_mensagem_nao_diz_mais_executando(self):
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator)
        assert 'f"Executando {plan.addon_name}..."' not in src


class TestFaseBannersSaoNarracaoDeVerdade:
    """v5.15.0: as 3 mensagens de abertura de fase (pesquisa, planejamento,
    construcao) eram strings estaticas fixas (nunca geradas pela IA) --
    Felipe reportou em live-test, colando o proprio transcript. Convertidas
    pra narrate() (fundamentadas em dado real: user_query/addon_name), igual
    o resto do pipeline ja fazia."""

    def test_pesquisa_narra_via_narrate_nao_texto_fixo(self):
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._run_conversational_pipeline)
        assert 'narrate(f"pesquisando informacoes atualizadas' in src
        assert '"Pesquisando APIs e referências para o addon..."' not in src

    def test_planejamento_narra_via_narrate_nao_texto_fixo(self):
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._run_conversational_pipeline)
        assert 'narrate(f"organizando os passos do plano' in src
        assert '"Criando o plano de desenvolvimento..."' not in src

    def test_construcao_narra_via_narrate_nao_texto_fixo(self):
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._run_conversational_pipeline)
        assert 'narrate(f"comecando a construir o {plan.addon_name}")' in src

    def test_pesquisa_e_planejamento_usam_truncate_at_word_nao_slice_bruto(self):
        """v5.16.0: bug real -- user_query[:150] cortava no meio de uma
        palavra e narrate() ecoava o fragmento quebrado pro usuario."""
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._run_conversational_pipeline)
        assert "_truncate_at_word(user_query, 150)" in src
        assert "user_query[:150]" not in src


class TestCheckpointResumoSimplificado:
    """v5.4.0: bug real de live-test -- o checkpoint apos cada step mostrava
    "Score: X/100", "Step type: code_generation", "Aprovado: nao" (sem
    acento) e "Tokens usados: X" -- tecnico demais para um usuario iniciante,
    e a IA nunca gerou esse texto (era Python literal hardcoded). Usuario:
    "tem que ser nivel mais iniciante... o tecnico deixa por de tras dos
    panos." Simplificado: so a descricao do problema (se houver), resto vai
    pro log interno (_logger.info)."""

    def test_summary_nao_expoe_score_numerico(self):
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._checkpoint_after_step)
        assert "Score:" not in src
        assert "Step type:" not in src
        assert "Tokens usados:" not in src

    def test_summary_ainda_diferencia_sucesso_de_problema(self):
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._checkpoint_after_step)
        assert "Etapa concluida" in src
        assert "Tivemos um problema" in src

    def test_metricas_tecnicas_vao_pro_log_nao_pro_usuario(self):
        """Score/aprovado/tokens continuam registrados -- so nao vao mais
        para a tela do usuario."""
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._checkpoint_after_step)
        assert "_logger.info(" in src
        assert "result.score" in src
        assert "result.tokens_used" in src

class TestCheckpointChamadoTambemNoRunPipeline:
    """
    5.45.0: achado real de auditoria de integracao -- _checkpoint_after_step()
    (PAUSE/REFAZER/CONTINUAR do usuario) so era chamado dentro de
    _run_conversational_pipeline(), nunca dentro de _run_pipeline() -- o
    metodo que agentic_loop.py::surgical_replan() usa pra retomar apos uma
    falha. Os 2 loops de _run_pipeline() (partial-ready e single-ready) sao
    estruturalmente identicos aos de _run_conversational_pipeline(), so
    faltava a chamada -- o checkpoint do usuario era silenciosamente pulado
    sempre que o FSM caisse em SURGICAL_REPLAN.
    """

    def test_run_pipeline_chama_checkpoint_no_caminho_single_ready(self):
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._run_pipeline)
        assert "self._checkpoint_after_step(" in src

    def test_run_pipeline_chama_checkpoint_no_caminho_partial_ready(self):
        """O metodo tem 2 loops de dependencia -- garante que o fix cobriu
        os dois, nao so o primeiro achado."""
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._run_pipeline)
        assert src.count("self._checkpoint_after_step(") >= 2


class TestDispatchComHeartbeatNaoAbortaPipelineInteiro:
    """v5.5.0: bug real de auditoria -- se dispatch_step_with_tokens levantasse
    QUALQUER excecao (ex: ValueError de step_type desconhecido no dispatcher),
    _dispatch_with_heartbeat() deixava propagar sem tratamento ate o try/except
    do topo de _run_conversational_pipeline, abortando o pipeline INTEIRO em vez
    de falhar so aquele step. Agora converte para "[ERRO] ..." (0 tokens),
    reconhecido por _IS_SUBAGENT_ERROR_RE, entrando no fluxo normal de
    retry/escalonamento."""

    def test_excecao_no_dispatch_vira_erro_recuperavel_nao_propaga(self, fake_api_key):
        from nvdastudio.core.orchestrator import Orchestrator

        orch = Orchestrator.__new__(Orchestrator)
        with patch(
            "nvdastudio.core.orchestrator.dispatch_step_with_tokens",
            side_effect=ValueError("step_type sem agente especializado: xyz"),
        ):
            output, tokens = orch._dispatch_with_heartbeat(
                step_type="xyz", prompt="p", model_id="kimi-k2.6", reasoning_params={},
            )
        assert output.startswith("[ERRO]")
        assert tokens == 0


class TestStepTypeSchemaTemEnum:
    """v2.7.0 (planner.py): sem enum, um step_type alucinado/typo pela IA so era
    descoberto no dispatcher (ValueError sem retry). Enum forca o JSON schema a
    restringir os valores aceitos, igual ja acontecia com complexity."""

    def test_step_type_tem_enum_com_os_12_tipos_validos(self):
        import inspect
        from nvdastudio.core import planner
        src = inspect.getsource(planner.Planner._call_planner_llm)
        idx = src.find('"step_type"')
        assert idx != -1
        trecho = src[idx:idx + 500]
        assert "\"enum\":" in trecho
        for tipo in (
            "code_generation", "manifest_builder", "documentation", "assembly",
            "accessibility_audit", "test_generation", "web_research", "design_review",
            "agent_template", "agent_runner", "syntax_validation", "user_clarification",
        ):
            assert f'"{tipo}"' in trecho, f"step_type '{tipo}' ausente do enum"

class TestValidacaoDeQualidadeSoRodaEmBlocoPython:
    """A validacao de imports deve rodar apenas para blocos Python."""

    def test_validate_imports_aninhado_no_if_python(self):
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._execute_step_with_critique)
        idx_if = src.find('if blk.get("language") == "python":')
        assert idx_if != -1
        idx_validate = src.find("unknown_imports = validate_python_imports(")
        assert idx_validate != -1
        assert idx_validate > idx_if
        assert "background_reviewer" not in src

        def indent_of(pos):
            line_start = src.rfind("\n", 0, pos) + 1
            line = src[line_start:pos]
            return len(line) - len(line.lstrip("\t"))

        if_indent = indent_of(idx_if)
        validate_indent = indent_of(idx_validate)
        assert validate_indent > if_indent, (
            "validate_python_imports() precisa estar DENTRO do if "
            "language==python, nao no nivel do for"
        )

class TestAgentMemorySingletonNaoMaisSombreado:
    """v5.6.0: bug real de auditoria -- o bloco de WIRING pos-sucesso do pipeline
    criava `AgentMemory()` nova (descartavel) em vez de usar o singleton `agent_mem`
    ja importado no topo do arquivo (from ..memory.agent_memory import agent_memory
    as agent_mem). Toda chamada .remember() gravava num objeto que morria logo em
    seguida -- _build_step_prompt() (que LE do singleton certo via
    get_common_mistakes/get_successful_patterns) nunca via nada gravado, entao o
    "aprendizado" nunca influenciava geracoes futuras de verdade.
    Tambem corrigido: so o caminho de SUCESSO gravava memoria -- falhas nunca
    eram registradas, entao get_common_mistakes() ("EVITE ESTES ERROS") sempre
    retornava vazio."""

    def test_wiring_nao_cria_instancia_descartavel_de_agentmemory(self):
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._run_conversational_pipeline)
        assert "= AgentMemory()" not in src, (
            "ainda cria uma instancia nova de AgentMemory() em vez de usar o singleton agent_mem"
        )
        assert "agent_mem.remember(" in src

    def test_falha_de_step_tambem_grava_em_agent_memory(self):
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator)
        assert src.count("success=False") >= 3, (
            "esperado pelo menos 3 pontos gravando falha em agent_mem.remember() "
            "(sequencial + paralelo nos dois pipelines)"
        )


class TestBuildStepPromptUsaRecallSemantico:
    """
    5.47.0: achado real de auditoria de integracao -- agent_mem.recall()
    (recuperacao ranqueada por RELEVANCIA ao contexto, via rank_relevant())
    existia desde agent_memory.py 1.0.0, totalmente testado, mas nunca era
    chamado em _build_step_prompt() -- so get_common_mistakes()/
    get_successful_patterns() (frequencia bruta, sem filtro de relevancia)
    eram usados.
    """

    def test_build_step_prompt_chama_recall(self):
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._build_step_prompt)
        assert "agent_mem.recall(" in src

    def test_recall_usa_description_do_step_como_contexto(self):
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._build_step_prompt)
        assert "agent_mem.recall(step.step_type, step.description" in src

    def test_recall_nao_duplica_entradas_ja_trazidas_por_relevancia(self):
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._build_step_prompt)
        assert "relevant_patterns" in src


class TestConclusaoExigeAddonCompleto:
    """Regressao: documentacao isolada jamais pode ser anunciada como sucesso."""

    @staticmethod
    def _plan():
        from nvdastudio.core.planner import ExecutionPlan, ExecutionStep
        return ExecutionPlan(
            plan_id="gate", original_query="crie addon", steps=[
                ExecutionStep(
                    step_id="codigo", step_type="code_generation",
                    description="gerar", model_id="light", reasoning_params={},
                    depends_on=[], context_from_steps=[], expected_output="addon",
                )
            ],
        )

    @staticmethod
    def _approved(output):
        from nvdastudio.core.orchestrator import StepResult
        return [StepResult(
            step_id="codigo", step_type="code_generation", output=output,
            approved=True, score=100,
        )]

    def test_recusa_manifesto_e_documentacao_sem_python(self):
        from nvdastudio.core.orchestrator import Orchestrator
        output = "```ini:manifest.ini\nname = incompleto\n```\ntexto de documentacao"
        error = Orchestrator._validate_minimum_addon_artifacts(
            self._plan(), self._approved(output), {"codigo": output}
        )
        assert "nenhum arquivo Python" in error

    def test_aceita_python_e_manifesto_aprovados(self):
        from nvdastudio.core.orchestrator import Orchestrator
        output = (
            "```python:globalPlugins/completo/__init__.py\nclass GlobalPlugin:\n    pass\n```\n"
            "```ini:manifest.ini\nname = completo\n```"
        )
        error = Orchestrator._validate_minimum_addon_artifacts(
            self._plan(), self._approved(output), {"codigo": output}
        )
        assert error == ""


class TestPlanejamentoNarraViaLiveNarrator:
    """v5.14.0: a fase de planejamento ("Criando o plano de desenvolvimento...")
    ficava muda de verdade -- ligava um ReasoningNarrator (v5.13.0), que
    reescreve o resumo de raciocinio via uma segunda IA, o mesmo padrao
    "robo" reclamado nos sub-agentes. Felipe: "eu quero fazer em tudo".
    Trocado por LiveNarrator (narracao real, sem reescrita) + planner.py
    2.13.0 que pede o plano via tool call ("entregar_plano") em vez de
    json_schema quando narracao e pedida -- sempre com flush() garantido
    via try/finally mesmo se a chamada falhar."""

    def test_live_narrator_importado_no_orchestrator(self):
        from nvdastudio.core import orchestrator
        assert hasattr(orchestrator, "LiveNarrator")

    def test_create_plan_recebe_on_narration_chunk_do_feed(self):
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._run_conversational_pipeline)
        idx = src.find("self._planner.create_plan(user_query")
        assert idx != -1
        assert "on_narration_chunk=_plan_narrator.feed" in src[idx - 50:idx + 100]

    def test_create_plan_narrator_flush_em_finally(self):
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._run_conversational_pipeline)
        idx_create = src.find("self._planner.create_plan(user_query")
        idx_finally = src.find("finally:", idx_create)
        idx_flush = src.find("_plan_narrator.flush()", idx_finally)
        assert -1 not in (idx_create, idx_finally, idx_flush), (
            "create_plan() precisa ter flush() do LiveNarrator garantido em finally"
        )

    def test_replan_with_feedback_recebe_on_narration_chunk_e_flush_em_finally(self):
        import inspect
        from nvdastudio.core import orchestrator
        src = inspect.getsource(orchestrator.Orchestrator._run_conversational_pipeline)
        idx = src.find("self._planner.replan_with_feedback(")
        assert idx != -1
        trecho = src[idx:idx + 400]
        assert "on_narration_chunk=_replan_narrator.feed" in trecho
        idx_finally = src.find("finally:", idx)
        idx_flush = src.find("_replan_narrator.flush()", idx_finally)
        assert -1 not in (idx_finally, idx_flush)
