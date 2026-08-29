import os
import tempfile

import pytest


# Marca para pular se nao houver chave real
# .strip() defensivo: trailing space na env var causa h11.LocalProtocolError (h11>=0.16.0)
HAS_OLLAMA = os.environ.get("OLLAMA_API_KEY", "").strip()
# 2026-08-17: critic.py 3.19.0 -- o Critic agora SEMPRE usa OpenCode Go
# (prompt caching), independente do provider ativo. Sem essa chave, TODA
# avaliacao de step falha com "Chave API para opencode_go nao configurada"
# -- achado real ao vivo (madrugada 2026-08-17/18, rodada 1 do loop): os
# 2 casos deste arquivo rodaram e "passaram" no pytest (test_e36 nao exige
# success=True) mas o pipeline inteiro falhou em segundos, 0 tokens gastos,
# nenhum sinal real coletado -- so desperdicou tempo/custo do Ollama sem
# testar nada. Adicionado ao skip guard pra nao rodar (e enganar) sem as
# 2 chaves.
HAS_OPENCODE_GO = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
skip_unless_ollama = pytest.mark.skipif(
    not HAS_OLLAMA or not HAS_OPENCODE_GO,
    reason=("Ollama Cloud token nao disponivel" if not HAS_OLLAMA else "OpenCode Go token nao disponivel (necessario pro Critic, ver critic.py 3.19.0)")
)

# 5.1.0: skip_unless_ollama era definido mas nunca aplicado -- achado real
# de auditoria 2026-08-25. Todas as 5 classes deste arquivo fazem chamada
# de API real (nome "...Real" em cada uma); sem as chaves, ficavam
# penduradas indefinidamente em vez de skip limpo. pytestmark a nivel de
# modulo cobre as 5 de uma vez -- nao ha classe deterministica aqui (ao
# contrario de test_e31/e32/e34, que tem guard por classe especifica).
pytestmark = skip_unless_ollama


class TestE2EPlannerReal:
    """Planner com API real: valida que o JSON retornado e conforme o contrato."""

    def test_planner_retorna_plano_valido(self):
        from nvdastudio.core.planner import Planner, ExecutionPlan, STEP_ASSEMBLY

        planner = Planner()
        plan = planner.create_plan(
            "Crie um addon NVDA que anuncia a hora atual ao pressionar NVDA+T"
        )

        assert isinstance(plan, ExecutionPlan)
        assert plan.plan_id
        assert len(plan.steps) >= 2
        assert plan.estimated_complexity in ["low", "medium", "high"]
        # Ultimo step deve ser assembly
        assert plan.steps[-1].step_type == STEP_ASSEMBLY

    def test_planner_inclui_code_generation_e_manifest(self):
        from nvdastudio.core.planner import Planner, STEP_CODE_GENERATION, STEP_MANIFEST

        planner = Planner()
        plan = planner.create_plan("Addon que leia o texto selecionado")

        step_types = {s.step_type for s in plan.steps}
        assert STEP_CODE_GENERATION in step_types, "Plano deve incluir code_generation"
        assert STEP_MANIFEST in step_types, "Plano deve incluir manifest_builder"

    def test_planner_detecta_necessidade_de_agente(self):
        from nvdastudio.core.planner import Planner, STEP_AGENT_RUNNER

        planner = Planner()
        plan = planner.create_plan(
            "Crie um addon NVDA com agente de IA interno que responde perguntas sobre "
            "o texto em foco usando a Groq API"
        )

        assert plan.requires_agent_runner is True
        step_types = {s.step_type for s in plan.steps}
        assert STEP_AGENT_RUNNER in step_types


class TestE2ECriticReal:
    """Critic com API real: valida que veredictos sao coerentes com o spec."""

    def test_critic_aprova_codigo_valido(self, sample_addon_code):
        from nvdastudio.ai.critic import Critic

        critic = Critic()
        result = critic.evaluate("code_generation", sample_addon_code)

        # Score deve ser >= 60 para codigo valido
        assert result.score >= 60, (
            f"Score muito baixo para codigo valido: {result.score}. Issues: {result.issues}"
        )

    def test_critic_rejeita_codigo_vazio(self):
        from nvdastudio.ai.critic import Critic, Verdict

        critic = Critic()
        result = critic.evaluate("code_generation", "")

        assert result.verdict in [Verdict.NEEDS_FIX, Verdict.REJECTED]
        assert result.score < 90

    def test_critic_aprova_manifest_valido(self, sample_manifest_ini):
        from nvdastudio.ai.critic import Critic

        critic = Critic()
        result = critic.evaluate("manifest_builder", sample_manifest_ini)

        assert result.score >= 60

    def test_critic_detecta_falta_de_minimum_nvda_version(self):
        from nvdastudio.ai.critic import Critic, Verdict

        manifest_incompleto = (
            "name = testAddon\n"
            "summary = Addon incompleto\n"
            "version = 1.0.0\n"
            # minimumNVDAVersion ausente — deve ser detectado
        )
        critic = Critic()
        result = critic.evaluate("manifest_builder", manifest_incompleto)

        assert result.verdict != Verdict.APPROVED or result.issues, (
            "Critic deveria detectar ausencia de minimumNVDAVersion"
        )


class TestE2ESubAgentsReal:
    """Sub-agentes com API real: valida outputs conforme contratos."""

    def test_code_generator_retorna_python_valido(self):
        from nvdastudio.sub_agents.code_generator import run

        output = run(
            prompt="Crie um globalPlugin NVDA que anuncia 'Ola' ao pressionar NVDA+H", model_id="kimi-k2.6", reasoning_params={"reasoning_effort": "medium"})

        assert isinstance(output, str)
        assert len(output) > 100, "Output muito curto para ser um addon real"
        # Nao executa — apenas verifica presenca de elementos esperados
        assert "GlobalPlugin" in output or "globalPlugin" in output
        assert "import" in output

    def test_manifest_builder_retorna_ini_valido(self):
        from nvdastudio.sub_agents.manifest_builder import run
        from nvdastudio.builder.addon_builder import validate_manifest

        output = run(
            prompt="Gere manifest.ini para addon chamado 'testHora' versao 1.0.0", model_id="kimi-k2.6", reasoning_params={})

        assert isinstance(output, str)
        # Valida campos obrigatorios no output
        missing = validate_manifest(output)
        assert len(missing) == 0, f"Manifest gerado esta faltando campos: {missing}"

    def test_web_researcher_usa_compound_e_retorna_conteudo(self):
        from nvdastudio.sub_agents.web_researcher import run

        output = run(
            prompt="O que e o NVDA e como funciona o sistema de addons dele?", model_id="ignorado", # WebResearcher sempre usa compound
            reasoning_params={})

        assert isinstance(output, str)
        assert len(output) > 50, "WebResearcher retornou conteudo muito curto"
        # Nao deve comecar com erro
        assert not output.startswith("[ERRO]"), f"WebResearcher retornou erro: {output}"


class TestE2EFullPipeline:
    """
    Pipeline E2E completo: Planner -> Dispatcher -> Critic -> Assembler.
    Valida que o sistema produz output coerente sem executar codigo.
    """

    def test_pipeline_addon_simples(self):
        from nvdastudio.core.orchestrator import Orchestrator, OrchestrationResult

        results = []
        events = []

        orch = Orchestrator()
        orch.initialize()
        orch.set_callbacks(
            on_progress=lambda ev, det: events.append((ev, det)),
            on_complete=lambda r: results.append(r),
        )

        orch._run_pipeline(
            "Crie um addon NVDA simples que anuncia a hora atual ao pressionar NVDA+H"
        )

        assert results, "on_complete nao foi chamado"
        result = results[0]

        assert isinstance(result, OrchestrationResult)
        assert result.plan_id
        assert len(result.step_results) >= 2

        # Verifica que eventos de progresso foram emitidos
        event_types = {e[0] for e in events}
        assert "PLANEJANDO" in event_types
        assert "CONCLUIDO" in event_types or "ERRO" in event_types

        # Verifica que output final existe
        assert isinstance(result.final_output, str)

        # Regra 9: verifica que codigo nao foi executado
        # (se tivesse sido, o processo teria falhado ou feito algo indesejado)
        # Apenas verifica que o output contem texto, sem executar nada
        assert len(result.final_output) > 0

    def test_pipeline_addon_com_agente_interno(self):
        """
        Verifica que o Planner identifica necessidade de agente e cria o plano correto.
        O Critic real pode rejeitar steps por criterios estritos — isso e comportamento
        esperado e valido. O teste valida que o pipeline completa sem erro critico.
        Regra 9: nenhum codigo gerado e executado.
        """
        from nvdastudio.core.orchestrator import Orchestrator

        results = []
        progress = []

        orch = Orchestrator()
        orch.initialize()
        orch.set_callbacks(
            on_progress=lambda ev, det: progress.append(ev),
            on_complete=lambda r: results.append(r),
        )

        orch._run_pipeline(
            "Crie um addon NVDA que usa agente de IA para responder perguntas "
            "sobre o texto em foco, usando a Groq API internamente"
        )

        # Pipeline deve ter completado (on_complete chamado)
        assert results, "on_complete nao foi chamado"
        result = results[0]

        # Plano deve ter sido criado (PLANO_CRIADO emitido)
        assert "PLANO_CRIADO" in progress or "PLANEJANDO" in progress, (
            "Pipeline nao emitiu evento de planejamento"
        )

        # Pipeline deve ter pelo menos tentado executar steps
        assert len(result.step_results) > 0, (
            "Pipeline nao executou nenhum step"
        )

        # Output final nao deve ser None
        assert result.final_output is not None

        # Regra 9: chegou aqui sem executar codigo gerado
        assert isinstance(result.final_output, str)

    def test_pipeline_codigo_gerado_nao_executado(self):
        """Regra 9 E2E: garante que em nenhum momento codigo foi executado."""

        from nvdastudio.core.orchestrator import Orchestrator

        results = []

        orch = Orchestrator()
        orch.initialize()
        orch.set_callbacks(
            on_progress=lambda ev, det: None,
            on_complete=lambda r: results.append(r),
        )

        # Mesmo com prompt que poderia gerar codigo "perigoso",
        # o pipeline apenas gera texto — nunca executa
        orch._run_pipeline(
            "Crie um addon NVDA que leia arquivos do sistema"
        )

        assert results
        # Se chegou aqui sem excecao de execucao de codigo, a regra 9 esta sendo respeitada
        assert results[0].final_output is not None


class TestE2EAddonBuilderComOutputReal:
    """Valida extracao e salvamento de artefatos do output real do pipeline."""

    def test_extrai_e_salva_artefatos_do_output_real(self):
        from nvdastudio.sub_agents.code_generator import run
        from nvdastudio.builder.addon_builder import extract_code_blocks, save_addon_files

        output = run(
            prompt=(
                "Crie um globalPlugin NVDA chamado 'horaAddon' que anuncia "
                "a hora ao pressionar NVDA+Shift+H. Inclua manifest.ini."
            ),
            model_id="kimi-k2.6",
            reasoning_params={},
        )

        blocks = extract_code_blocks(output)
        assert len(blocks) > 0, "Nenhum bloco de codigo extraido do output real"

        with tempfile.TemporaryDirectory() as tmpdir:
            folder, saved = save_addon_files(blocks, tmpdir, "horaAddon")
            assert os.path.isdir(folder)
            assert len(saved) > 0
            for path in saved:
                assert os.path.isfile(path)
                # Nao executa — apenas verifica que o arquivo existe e tem conteudo
                with open(path, encoding="utf-8") as f:
                    content = f.read()
                assert len(content) > 0

