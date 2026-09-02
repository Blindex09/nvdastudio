# ===========================================================================
# 1. Planner — STEP_SYNTAX_VALIDATION existe e esta nos mapas
# ===========================================================================

class TestPlannerSyntaxValidation:

    def test_step_type_definido(self):
        from addon.globalPlugins.nvdastudio.core.planner import STEP_SYNTAX_VALIDATION
        assert STEP_SYNTAX_VALIDATION == "syntax_validation"

    def test_step_no_model_map(self):
        from addon.globalPlugins.nvdastudio.ai.model_registry import ALTO_MODEL
        from addon.globalPlugins.nvdastudio.core.planner import STEP_SYNTAX_VALIDATION, STEP_MODEL_MAP
        assert STEP_SYNTAX_VALIDATION in STEP_MODEL_MAP
        # v2.17.0: sentinela 'alto' (provider-agnostic), nao mais um modelo
        # Ollama hardcoded -- ver changelog planner.py 2.17.0.
        assert STEP_MODEL_MAP[STEP_SYNTAX_VALIDATION] == ALTO_MODEL

    def test_step_no_reasoning_map(self):
        from addon.globalPlugins.nvdastudio.core.planner import STEP_SYNTAX_VALIDATION, STEP_REASONING_MAP
        assert STEP_SYNTAX_VALIDATION in STEP_REASONING_MAP

    def test_versao_Planner(self):
        from addon.globalPlugins.nvdastudio.core.planner import MODULE_VERSION
        assert MODULE_VERSION == "2.40.0"


# ===========================================================================
# 2. _inject_syntax_validation — logica de injecao
# ===========================================================================

class TestInjectSyntaxValidation:

    def _make_planner(self):
        from addon.globalPlugins.nvdastudio.core.planner import Planner
        return Planner.__new__(Planner)

    def _make_step(self, step_id, step_type, depends_on=None, context_from=None):
        from addon.globalPlugins.nvdastudio.core.planner import ExecutionStep, STEP_MODEL_MAP, STEP_REASONING_MAP
        stype = step_type
        return ExecutionStep(
            step_id=step_id,
            step_type=stype,
            description=f"step {step_id}",
            model_id=STEP_MODEL_MAP.get(stype, "kimi-k2.6"),
            reasoning_params=STEP_REASONING_MAP.get(stype, {}),
            depends_on=depends_on or [],
            context_from_steps=context_from or [],
        )

    def test_injeta_sv_apos_code_generation(self):
        from addon.globalPlugins.nvdastudio.core.planner import STEP_CODE_GENERATION, STEP_SYNTAX_VALIDATION
        p = self._make_planner()
        steps = [
            self._make_step("s1", STEP_CODE_GENERATION),
            self._make_step("s2", "manifest_builder"),
            self._make_step("s3", "assembly", depends_on=["s1", "s2"]),
        ]
        result = p._inject_syntax_validation(steps)
        types = [s.step_type for s in result]
        assert STEP_SYNTAX_VALIDATION in types

    def test_sv_vem_logo_apos_code_generation(self):
        from addon.globalPlugins.nvdastudio.core.planner import STEP_CODE_GENERATION, STEP_SYNTAX_VALIDATION
        p = self._make_planner()
        steps = [self._make_step("s1", STEP_CODE_GENERATION)]
        result = p._inject_syntax_validation(steps)
        idx_cg = next(i for i, s in enumerate(result) if s.step_type == STEP_CODE_GENERATION)
        idx_sv = next(i for i, s in enumerate(result) if s.step_type == STEP_SYNTAX_VALIDATION)
        assert idx_sv == idx_cg + 1

    def test_sv_depende_de_code_generation(self):
        from addon.globalPlugins.nvdastudio.core.planner import STEP_CODE_GENERATION, STEP_SYNTAX_VALIDATION
        p = self._make_planner()
        steps = [self._make_step("s1", STEP_CODE_GENERATION)]
        result = p._inject_syntax_validation(steps)
        sv = next(s for s in result if s.step_type == STEP_SYNTAX_VALIDATION)
        assert "s1" in sv.depends_on
        assert "s1" in sv.context_from_steps

    def test_dois_code_generation_dois_sv(self):
        from addon.globalPlugins.nvdastudio.core.planner import STEP_CODE_GENERATION, STEP_SYNTAX_VALIDATION
        p = self._make_planner()
        steps = [
            self._make_step("s1", STEP_CODE_GENERATION),
            self._make_step("s2", STEP_CODE_GENERATION),
        ]
        result = p._inject_syntax_validation(steps)
        sv_steps = [s for s in result if s.step_type == STEP_SYNTAX_VALIDATION]
        assert len(sv_steps) == 2

    def test_assembly_atualizado_para_depender_de_sv(self):
        from addon.globalPlugins.nvdastudio.core.planner import STEP_CODE_GENERATION, STEP_SYNTAX_VALIDATION
        p = self._make_planner()
        steps = [
            self._make_step("s1", STEP_CODE_GENERATION),
            self._make_step("s2", "assembly", depends_on=["s1"], context_from=["s1"]),
        ]
        result = p._inject_syntax_validation(steps)
        asm = next(s for s in result if s.step_type == "assembly")
        sv_id = next(s.step_id for s in result if s.step_type == STEP_SYNTAX_VALIDATION)
        assert sv_id in asm.depends_on
        assert sv_id in asm.context_from_steps

    def test_sem_code_generation_sem_sv(self):
        from addon.globalPlugins.nvdastudio.core.planner import STEP_SYNTAX_VALIDATION
        p = self._make_planner()
        steps = [
            self._make_step("s1", "manifest_builder"),
            self._make_step("s2", "assembly"),
        ]
        result = p._inject_syntax_validation(steps)
        sv_steps = [s for s in result if s.step_type == STEP_SYNTAX_VALIDATION]
        assert len(sv_steps) == 0

    def test_sv_usa_alto(self):
        from addon.globalPlugins.nvdastudio.ai.model_registry import ALTO_MODEL
        from addon.globalPlugins.nvdastudio.core.planner import STEP_CODE_GENERATION, STEP_SYNTAX_VALIDATION
        p = self._make_planner()
        steps = [self._make_step("s1", STEP_CODE_GENERATION)]
        result = p._inject_syntax_validation(steps)
        sv = next(s for s in result if s.step_type == STEP_SYNTAX_VALIDATION)
        # v2.17.0: model_id inicial da injecao e o sentinela 'alto' --
        # o modelo concreto real e resolvido depois por apply_model_budget()
        # no fluxo completo de create_plan()/replan_with_feedback().
        assert sv.model_id == ALTO_MODEL

    def test_sv_max_retries_1(self):
        from addon.globalPlugins.nvdastudio.core.planner import STEP_CODE_GENERATION, STEP_SYNTAX_VALIDATION
        p = self._make_planner()
        steps = [self._make_step("s1", STEP_CODE_GENERATION)]
        result = p._inject_syntax_validation(steps)
        sv = next(s for s in result if s.step_type == STEP_SYNTAX_VALIDATION)
        assert sv.max_retries == 1


# ===========================================================================
# 3. Orchestrator — NON_BLOCKING e CODE_OUTPUT
# ===========================================================================

class TestOrchestratorSyntaxValidation:

    def test_versao_orchestrator(self):
        from addon.globalPlugins.nvdastudio.core.orchestrator import MODULE_VERSION
        assert MODULE_VERSION == "5.72.0"

    def test_sv_em_non_blocking(self):
        from addon.globalPlugins.nvdastudio.core.orchestrator import _NON_BLOCKING_STEP_TYPES
        assert "syntax_validation" in _NON_BLOCKING_STEP_TYPES

    def test_sv_nao_em_critical(self):
        from addon.globalPlugins.nvdastudio.core.orchestrator import _CRITICAL_STEP_TYPES
        assert "syntax_validation" not in _CRITICAL_STEP_TYPES

    def test_sv_em_code_output(self):
        from addon.globalPlugins.nvdastudio.core.orchestrator import Orchestrator
        assert "syntax_validation" in Orchestrator._CODE_OUTPUT_STEP_TYPES

    def test_step_syntax_validation_importado(self):
        from addon.globalPlugins.nvdastudio.core.orchestrator import STEP_SYNTAX_VALIDATION
        assert STEP_SYNTAX_VALIDATION == "syntax_validation"


# ===========================================================================
# 4. Dispatcher — roteia syntax_validation para syntax_validator.run
# ===========================================================================

class TestDispatcherSyntaxValidation:

    def test_versao_dispatcher(self):
        from addon.globalPlugins.nvdastudio.sub_agents.dispatcher import MODULE_VERSION
        assert MODULE_VERSION == "2.4.0"

    def test_dispatch_syntax_validation_rota_para_validator(self):
        from unittest.mock import patch
        with patch("addon.globalPlugins.nvdastudio.sub_agents.syntax_validator.run") as mock_run:
            mock_run.return_value = "RESULTADO: PASS"
            from addon.globalPlugins.nvdastudio.sub_agents.dispatcher import dispatch_step
            result = dispatch_step(
                "syntax_validation", "codigo aqui", "kimi-k2.6", {}
            )
            mock_run.assert_called_once()
            assert result == "RESULTADO: PASS"

    def test_handler_nativo_resolve_no_namespace_real_do_pacote(self):
        from addon.globalPlugins.nvdastudio.sub_agents import dispatcher

        dispatcher._handler_cache.clear()
        handler = dispatcher._import_handler(
            "globalPlugins.nvdastudio.sub_agents.manifest_builder.run"
        )

        assert handler is not None
        assert handler.__module__.endswith("nvdastudio.sub_agents.manifest_builder")


# ===========================================================================
# 5. syntax_validator.py — modulo e logica interna
# ===========================================================================

class TestSyntaxValidatorModulo:

    def test_versao(self):
        from addon.globalPlugins.nvdastudio.sub_agents.syntax_validator import MODULE_VERSION
        assert MODULE_VERSION == "2.0.0"

    def test_usa_ast_parse_local(self):
        # v2.0.0: validacao AST local, sem LLM
        import inspect
        from addon.globalPlugins.nvdastudio.sub_agents import syntax_validator
        src = inspect.getsource(syntax_validator)
        assert "ast.parse" in src

    def test_run_retorna_pass_para_codigo_valido(self):
        from addon.globalPlugins.nvdastudio.sub_agents.syntax_validator import run
        prompt = "```python:globalPlugins/A/__init__.py\nimport ui\nprint('ok')\n```"
        result = run(prompt, "kimi-k2.6", {})
        assert "PASS" in result

    def test_run_retorna_fail_para_codigo_invalido(self):
        from addon.globalPlugins.nvdastudio.sub_agents.syntax_validator import run
        prompt = "```python:globalPlugins/A/__init__.py\ndef foo(\n```"
        result = run(prompt, "kimi-k2.6", {})
        assert "FAIL" in result

    def test_extract_python_blocks_vazio(self):
        from addon.globalPlugins.nvdastudio.sub_agents.syntax_validator import _extract_python_blocks
        assert _extract_python_blocks("sem blocos") == []

    def test_extract_python_blocks_encontra_bloco(self):
        from addon.globalPlugins.nvdastudio.sub_agents.syntax_validator import _extract_python_blocks
        texto = "```python:globalPlugins/MeuAddon/__init__.py\nprint('oi')\n```"
        blocos = _extract_python_blocks(texto)
        assert len(blocos) == 1
        assert blocos[0][0] == "globalPlugins/MeuAddon/__init__.py"
        assert "print('oi')" in blocos[0][1]

    def test_extract_python_blocks_multiplos(self):
        from addon.globalPlugins.nvdastudio.sub_agents.syntax_validator import _extract_python_blocks
        texto = (
            "```python:globalPlugins/A/__init__.py\npass\n```\n"
            "```python:globalPlugins/A/mod.py\nx = 1\n```"
        )
        blocos = _extract_python_blocks(texto)
        assert len(blocos) == 2

    def test_run_multiplos_blocos_todos_validos(self):
        from addon.globalPlugins.nvdastudio.sub_agents.syntax_validator import run
        prompt = (
            "```python:globalPlugins/A/__init__.py\nimport ui\n```\n"
            "```python:globalPlugins/A/mod.py\nx = 1 + 2\n```"
        )
        result = run(prompt, "kimi-k2.6", {})
        assert "PASS" in result

    def test_run_multiplos_blocos_um_invalido(self):
        from addon.globalPlugins.nvdastudio.sub_agents.syntax_validator import run
        prompt = (
            "```python:globalPlugins/A/__init__.py\nimport ui\n```\n"
            "```python:globalPlugins/A/mod.py\ndef foo(\n```"
        )
        result = run(prompt, "kimi-k2.6", {})
        assert "FAIL" in result

    def test_run_sem_blocos_retorna_skip(self):
        from addon.globalPlugins.nvdastudio.sub_agents import syntax_validator
        result = syntax_validator.run("sem blocos python", "kimi-k2.6", {})
        assert "SKIP" in result

    def test_run_sem_rede(self):
        # v2.0.0: validacao local, sem LLM — run() nunca faz chamadas de rede
        import inspect
        from addon.globalPlugins.nvdastudio.sub_agents import syntax_validator
        src = inspect.getsource(syntax_validator)
        assert "create_llm_client" not in src, "v2.0.0 nao deve usar LLM"
        assert "ast.parse" in src

    def test_nao_executa_codigo_localmente(self):
        # Garante que syntax_validator nao usa subprocess, exec ou eval
        import inspect
        from addon.globalPlugins.nvdastudio.sub_agents import syntax_validator
        src = inspect.getsource(syntax_validator)
        assert "subprocess" not in src
        assert "exec(" not in src
        assert "eval(" not in src


# ===========================================================================
# 6. llm_client — captura executed_tools em LLMResponse
# ===========================================================================

class TestGroqClientExecutedTools:

    def test_ollama_response_tem_executed_tools(self):
        from addon.globalPlugins.nvdastudio.ai.llm_client import LLMResponse
        resp = LLMResponse(content="ok", model_used="kimi-k2.6", executed_tools=[{"type": "code_interpreter"}])
        assert len(resp.executed_tools) == 1
        assert resp.executed_tools[0]["type"] == "code_interpreter"

    def test_ollama_response_executed_tools_default_vazio(self):
        from addon.globalPlugins.nvdastudio.ai.llm_client import LLMResponse
        resp = LLMResponse(content="ok", model_used="kimi-k2.6")
        assert resp.executed_tools == []
