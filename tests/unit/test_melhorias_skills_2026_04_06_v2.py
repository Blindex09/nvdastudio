# ------------------------------------------------------------------
# Item 1 — _build_context structured compression
# ------------------------------------------------------------------

class TestContextCompression:
    """skills: context-compression + context-degradation."""

    def test_orchestrator_versao_3_3_0(self):
        from nvdastudio.core.orchestrator import MODULE_VERSION
        assert MODULE_VERSION == "5.73.0"

    def test_build_context_output_curto_nao_usa_resumo(self):
        """Outputs curtos passam integralmente sem marcador RESUMO."""
        from nvdastudio.core.orchestrator import Orchestrator, _MAX_CONTEXT_CHARS_PER_STEP
        from tests.integration.test_orchestrator import _make_step
        orch = Orchestrator.__new__(Orchestrator)
        step = _make_step()
        step.context_from_steps = ["s1"]
        curto = "x" * (_MAX_CONTEXT_CHARS_PER_STEP - 1)
        ctx = orch._build_context(step, {"s1": curto})
        assert "RESUMO ESTRUTURADO" not in ctx
        assert curto in ctx

    def test_build_context_output_longo_usa_resumo(self):
        """Outputs longos produzem resumo estruturado com secoes."""
        from nvdastudio.core.orchestrator import Orchestrator, _MAX_CONTEXT_CHARS_PER_STEP
        from tests.integration.test_orchestrator import _make_step
        orch = Orchestrator.__new__(Orchestrator)
        step = _make_step()
        step.context_from_steps = ["s1"]
        longo = "a" * (_MAX_CONTEXT_CHARS_PER_STEP + 1000)
        ctx = orch._build_context(step, {"s1": longo})
        assert "COMPRIMIDO" in ctx
        assert "[DECISAO_PRINCIPAL]" in ctx

    def test_build_context_preserva_inicio_lost_in_middle(self):
        """Lost-in-middle: inicio deve sempre aparecer no contexto."""
        from nvdastudio.core.orchestrator import Orchestrator, _MAX_CONTEXT_CHARS_PER_STEP
        from tests.integration.test_orchestrator import _make_step
        orch = Orchestrator.__new__(Orchestrator)
        step = _make_step()
        step.context_from_steps = ["s1"]
        raw = "CABECALHO_CRITICO_" + "m" * _MAX_CONTEXT_CHARS_PER_STEP
        ctx = orch._build_context(step, {"s1": raw})
        assert "CABECALHO_CRITICO_" in ctx

    def test_build_context_preserva_final_artefatos(self):
        """Final do output (artefatos/pontos criticos) deve ser preservado."""
        from nvdastudio.core.orchestrator import Orchestrator, _MAX_CONTEXT_CHARS_PER_STEP
        from tests.integration.test_orchestrator import _make_step
        orch = Orchestrator.__new__(Orchestrator)
        step = _make_step()
        step.context_from_steps = ["s1"]
        raw = "m" * (_MAX_CONTEXT_CHARS_PER_STEP + 500) + "\nerro: RODAPE_ARTEFATO."
        ctx = orch._build_context(step, {"s1": raw})
        assert "RODAPE_ARTEFATO" in ctx

    def test_build_context_step_sem_output_nao_inclui(self):
        """Step nao presente em outputs nao gera contexto."""
        from nvdastudio.core.orchestrator import Orchestrator
        from tests.integration.test_orchestrator import _make_step
        orch = Orchestrator.__new__(Orchestrator)
        step = _make_step()
        step.context_from_steps = ["inexistente"]
        ctx = orch._build_context(step, {})
        assert ctx == ""


class TestContextAgregadoTemTeto:
    """Achado de auditoria full-stack 2026-08-04 (rastreamento de addons
    grandes/complexos, "addons de qualquer magnitude"): cada dependencia
    individual ja respeitava _MAX_CONTEXT_CHARS_PER_STEP, mas nao havia
    teto AGREGADO -- um step com muitas dependencias podia concatenar
    contexto sem limite antes de virar prompt pro LLM."""

    def test_muitas_dependencias_pequenas_sao_comprimidas_no_agregado(self):
        from nvdastudio.core.orchestrator import (
            Orchestrator, _MAX_CONTEXT_CHARS_PER_STEP, _MAX_TOTAL_CONTEXT_CHARS,
        )
        from tests.integration.test_orchestrator import _make_step

        orch = Orchestrator.__new__(Orchestrator)
        # 10 dependencias, cada uma dentro do teto individual (nao aciona
        # a compressao por-step), mas cuja SOMA estoura o teto agregado.
        n_deps = 10
        tamanho_por_dep = _MAX_CONTEXT_CHARS_PER_STEP - 100
        assert n_deps * tamanho_por_dep > _MAX_TOTAL_CONTEXT_CHARS, (
            "fixture precisa realmente estourar o teto agregado"
        )
        step = _make_step()
        step.context_from_steps = [f"s{i}" for i in range(n_deps)]
        outputs = {f"s{i}": f"conteudo{i} " + ("x" * tamanho_por_dep) for i in range(n_deps)}

        ctx = orch._build_context(step, outputs)

        assert len(ctx) <= _MAX_TOTAL_CONTEXT_CHARS * 1.1, (
            "contexto agregado deveria ser comprimido de volta pra perto do teto"
        )

    def test_poucas_dependencias_nao_aciona_compressao_agregada(self):
        from nvdastudio.core.orchestrator import Orchestrator, _MAX_CONTEXT_CHARS_PER_STEP
        from tests.integration.test_orchestrator import _make_step

        orch = Orchestrator.__new__(Orchestrator)
        step = _make_step()
        step.context_from_steps = ["s1"]
        curto = "conteudo pequeno " * 10
        assert len(curto) < _MAX_CONTEXT_CHARS_PER_STEP
        ctx = orch._build_context(step, {"s1": curto})
        assert curto in ctx


# ------------------------------------------------------------------
# Item 2 — avoid-ai-writing 43 termos no doc_generator
# ------------------------------------------------------------------

class TestAvoidAiWriting43:
    """skill: avoid-ai-writing — tabela de 43 substituicoes."""

    def test_doc_generator_versao_1_7_0(self):
        from nvdastudio.sub_agents.doc_generator import MODULE_VERSION
        assert MODULE_VERSION == "1.10.0"

    def test_termos_especificos_presentes_no_system(self):
        """Os 43 termos devem estar listados no _SYSTEM do doc_generator."""
        from nvdastudio.sub_agents.doc_generator import _SYSTEM
        # Amostra dos 43 termos da skill avoid-ai-writing
        termos_criticos = [
            "leverage", "utilize", "robust", "cutting-edge",
            "seamless", "streamline", "holistic", "synergy",
            "paradigm", "innovative", "revolutionary", "game-changing",
            "transformative", "comprehensive", "supercharge",
            "elevate", "empower", "foster", "harness",
            "spearhead", "embark", "delve", "dive deep",
            "unpack", "navigate", "crafting", "tailored",
            "bespoke", "state-of-the-art", "best-in-class",
        ]
        ausentes = [t for t in termos_criticos if t not in _SYSTEM]
        assert not ausentes, f"Termos ausentes do _SYSTEM: {ausentes}"

    def test_substituicoes_presentes_no_system(self):
        """Alternativas corretas devem estar listadas."""
        from nvdastudio.sub_agents.doc_generator import _SYSTEM
        # Verifica que as setas de substituicao estao presentes
        assert "leverage" in _SYSTEM and "use" in _SYSTEM
        assert "robust" in _SYSTEM and "reliable" in _SYSTEM
        assert "seamless" in _SYSTEM and "smooth" in _SYSTEM

    def test_tabela_nao_substitui_regras_anteriores(self):
        """A tabela dos 43 termos nao pode remover as categorias gerais de DOC-A09."""
        from nvdastudio.sub_agents.doc_generator import _SYSTEM
        # Categorias gerais do DOC-A09 devem continuar presentes
        assert "importante" in _SYSTEM   # intensificadores vazios
        assert "fundamental" in _SYSTEM
        assert "Alem disso" in _SYSTEM   # transicoes mecanicas
        assert "Portanto" in _SYSTEM


# ------------------------------------------------------------------
# Item 4 — screen-reader-testing no critic e accessibility_auditor
# ------------------------------------------------------------------

class TestScreenReaderTestingCritic:
    """skill: screen-reader-testing — NVDA-UX-002 e NVDA-UX-003."""

    def test_critic_versao_3_2_0(self):
        from nvdastudio.ai.critic import MODULE_VERSION
        assert MODULE_VERSION == "3.21.0"

    def test_nvda_ux_002_presente(self):
        """NVDA-UX-002: scripts sem feedback auditivo."""
        from nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        assert "NVDA-UX-002" in _CRITIC_QUALITY_SYSTEM
        assert "feedback auditivo" in _CRITIC_QUALITY_SYSTEM.lower() or \
               "feedback" in _CRITIC_QUALITY_SYSTEM

    def test_nvda_ux_003_presente(self):
        """NVDA-UX-003: fluxo completo sem visao."""
        from nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        assert "NVDA-UX-003" in _CRITIC_QUALITY_SYSTEM

    def test_nvda_ux_003_cita_screen_reader_testing(self):
        """UX-003 deve referenciar a skill screen-reader-testing."""
        from nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        assert "screen-reader-testing" in _CRITIC_QUALITY_SYSTEM

    def test_nvda_ux_002_menciona_ui_message(self):
        """UX-002 deve dar exemplo com ui.message()."""
        from nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        assert "ui.message" in _CRITIC_QUALITY_SYSTEM


class TestScreenReaderTestingAuditor:
    """skill: screen-reader-testing — NVDA-UX-002 e NVDA-UX-003 no auditor."""

    def test_auditor_versao_1_4_0(self):
        from nvdastudio.sub_agents.accessibility_auditor import MODULE_VERSION
        assert MODULE_VERSION == "1.20.0"

    def test_nvda_ux_002_no_auditor(self):
        from nvdastudio.sub_agents.accessibility_auditor import _SYSTEM
        assert "NVDA-UX-002" in _SYSTEM

    def test_nvda_ux_003_no_auditor(self):
        from nvdastudio.sub_agents.accessibility_auditor import _SYSTEM
        assert "NVDA-UX-003" in _SYSTEM

    def test_atalhos_nvda_no_auditor(self):
        """Auditor deve listar atalhos do NVDA para validacao."""
        from nvdastudio.sub_agents.accessibility_auditor import _SYSTEM
        assert "NVDA+F7" in _SYSTEM
        assert "NVDA+Space" in _SYSTEM

    def test_checklist_criterios_no_auditor(self):
        """Checklist da skill screen-reader-testing deve estar no auditor."""
        from nvdastudio.sub_agents.accessibility_auditor import _SYSTEM
        assert "screen-reader-testing" in _SYSTEM
        assert "label" in _SYSTEM.lower()


# ------------------------------------------------------------------
# Item 5 — descriptions nos campos do planner schema
# ------------------------------------------------------------------

class TestPlannerSchemaDescriptions:
    """skill: llm-structured-output — descriptions obrigatorias em todos os campos."""

    def test_planner_versao_2_1_0(self):
        from nvdastudio.core.planner import MODULE_VERSION
        assert MODULE_VERSION == "2.40.0"

    def test_campos_principais_tem_description(self):
        """Campos do schema de nivel raiz devem ter description."""
        import inspect
        import nvdastudio.core.planner as planner_mod
        src = inspect.getsource(planner_mod)
        # O schema _PLAN_SCHEMA é definido dentro de _call_planner_llm.
        # Verificamos que cada campo critico, quando aparece no bloco do schema,
        # tem "description" na mesma linha ou na seguinte.
        # Buscamos especificamente na secao do schema (pos apos "_PLAN_SCHEMA =")
        schema_start = src.find("_PLAN_SCHEMA =")
        assert schema_start != -1, "_PLAN_SCHEMA nao encontrado"
        schema_src = src[schema_start:schema_start + 9000]
        campos_com_description = [
            '"complexity"',
            '"assembling_message"',
            '"completed_message"',
            '"dependencies"',
        ]
        for campo in campos_com_description:
            idx = schema_src.find(campo)
            assert idx != -1, f"Campo {campo} nao encontrado no _PLAN_SCHEMA"
            trecho = schema_src[idx:idx + 300]
            assert '"description"' in trecho, \
                f"Campo {campo} nao tem description no _PLAN_SCHEMA"

    def test_campos_step_tem_description(self):
        """Campos de cada step devem ter description no _PLAN_SCHEMA."""
        import inspect
        import nvdastudio.core.planner as planner_mod
        src = inspect.getsource(planner_mod)
        schema_start = src.find("_PLAN_SCHEMA =")
        assert schema_start != -1
        # 2026-08-29: a versao anterior fatiava 9000 chars do schema e depois
        # 3000 a partir de "steps". Janela fixa quebra sozinha: qualquer campo
        # novo com descricao longa empurra os campos de step para fora e o
        # teste falha sem que nada esteja errado no schema (aconteceu ao
        # adicionar expected_files). Agora delimita o bloco de steps pelo que
        # ele realmente e -- do campo "steps" ate o "required" do proprio
        # sub-schema, que fecha as properties do step.
        schema_src = src[schema_start:]
        steps_start = schema_src.find('"steps"')
        assert steps_start != -1, "Campo 'steps' nao encontrado no _PLAN_SCHEMA"
        steps_src = schema_src[steps_start:]
        fim_step = steps_src.find('"required": ["step_id"')
        assert fim_step != -1, "fim do sub-schema de steps nao encontrado"
        steps_src = steps_src[:fim_step]
        campos_step = [
            '"step_id"', '"step_type"', '"expected_output"',
            '"user_message"', '"msg_evaluating"', '"depends_on"',
        ]
        for campo in campos_step:
            idx = steps_src.find(campo)
            assert idx != -1, f"Campo step {campo} nao encontrado na secao steps"
            trecho = steps_src[idx:idx + 300]
            assert '"description"' in trecho, \
                f"Campo step {campo} nao tem description no schema"

    def test_description_complexity_menciona_low_medium_high(self):
        """description do campo complexity deve explicar os 3 valores."""
        import inspect
        import nvdastudio.core.planner as planner_mod
        src = inspect.getsource(planner_mod)
        # Procura bloco de complexity
        idx = src.find('"complexity"')
        trecho = src[idx:idx+300]
        assert "low" in trecho and "medium" in trecho and "high" in trecho

    def test_description_steps_menciona_tipos_de_step(self):
        """description do campo steps deve listar step_types validos."""
        import inspect
        import nvdastudio.core.planner as planner_mod
        src = inspect.getsource(planner_mod)
        idx = src.find('"step_type"')
        trecho = src[idx:idx+400]
        assert "code_generation" in trecho
        assert "manifest_builder" in trecho
        assert "assembly" in trecho
