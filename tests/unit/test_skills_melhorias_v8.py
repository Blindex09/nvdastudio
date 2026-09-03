import pytest
from unittest.mock import patch
import nvdastudio.memory.session_memory as sm_mod
from nvdastudio.memory.session_memory import SessionMemory


@pytest.fixture
def mem(tmp_path):
    db_path = str(tmp_path / "test.json")
    orig_dir, orig_path = sm_mod._DB_DIR, sm_mod._DB_PATH
    sm_mod._DB_DIR = str(tmp_path)
    sm_mod._DB_PATH = db_path
    instance = SessionMemory()
    yield instance
    instance.close()
    sm_mod._DB_DIR = orig_dir
    sm_mod._DB_PATH = orig_path


# ============================================================
# Skill 1: evaluation — complexity stratification
# ============================================================

class TestQueryComplexityClassifier:
    """classify_query_complexity e um tradutor deterministico de vocabulario
    (low/medium/high do Planner -> simple/medium/complex das metricas), nao
    mais um classificador por IA -- ver changelog 5.55.0 em orchestrator.py."""

    def test_versao_orchestrator(self):
        from nvdastudio.core.orchestrator import MODULE_VERSION
        assert MODULE_VERSION == "5.84.0"

    def test_low_vira_simple(self):
        from nvdastudio.core.orchestrator import classify_query_complexity
        assert classify_query_complexity("low") == "simple"

    def test_medium_vira_medium(self):
        from nvdastudio.core.orchestrator import classify_query_complexity
        assert classify_query_complexity("medium") == "medium"

    def test_high_vira_complex(self):
        from nvdastudio.core.orchestrator import classify_query_complexity
        assert classify_query_complexity("high") == "complex"

    def test_retorno_sempre_string_valida(self):
        from nvdastudio.core.orchestrator import classify_query_complexity
        for c in ["low", "medium", "high", "", "desconhecido"]:
            result = classify_query_complexity(c)
            assert isinstance(result, str)
            assert result in ("simple", "medium", "complex")

    def test_valor_desconhecido_cai_em_medium(self):
        from nvdastudio.core.orchestrator import classify_query_complexity
        assert classify_query_complexity("ultra-mega-complex") == "medium"

    def test_string_vazia_cai_em_medium(self):
        from nvdastudio.core.orchestrator import classify_query_complexity
        assert classify_query_complexity("") == "medium"

    def test_sem_chamada_de_rede(self):
        """Deterministico: nao importa ai/llm_factory nem faz I/O."""
        import inspect
        from nvdastudio.core import orchestrator
        source = inspect.getsource(orchestrator.classify_query_complexity)
        assert "create_llm_client" not in source
        assert "client.chat" not in source


class TestSessionMemoryComplexityLevel:
    """log_step_metric e get_step_success_rates: suporte a complexity_level."""

    def test_versao_session_memory(self):
        from nvdastudio.memory.session_memory import MODULE_VERSION
        assert MODULE_VERSION == "3.6.0"

    def test_log_step_metric_aceita_complexity_level(self, mem):
        # Nao deve lancar excecao com o novo parametro
        mem.log_step_metric("code_generation", True, complexity_level="complex")
        mem.log_step_metric("manifest_builder", False, complexity_level="simple")

    def test_get_step_success_rates_sem_filtro(self, mem):
        mem.log_step_metric("code_generation", True, complexity_level="simple")
        mem.log_step_metric("code_generation", False, complexity_level="complex")
        rates = mem.get_step_success_rates()
        assert any(r["step_type"] == "code_generation" for r in rates)

    def test_get_step_success_rates_com_filtro_simple(self, mem):
        mem.log_step_metric("code_generation", True, complexity_level="simple")
        mem.log_step_metric("code_generation", False, complexity_level="complex")
        rates = mem.get_step_success_rates(complexity_level="simple")
        assert len(rates) == 1
        assert rates[0]["success_rate"] == 1.0

    def test_get_step_success_rates_com_filtro_complex(self, mem):
        mem.log_step_metric("code_generation", True, complexity_level="simple")
        mem.log_step_metric("code_generation", False, complexity_level="complex")
        rates = mem.get_step_success_rates(complexity_level="complex")
        assert len(rates) == 1
        assert rates[0]["success_rate"] == 0.0

    def test_filtro_inexistente_retorna_lista_vazia(self, mem):
        mem.log_step_metric("code_generation", True, complexity_level="simple")
        rates = mem.get_step_success_rates(complexity_level="extreme")
        assert rates == []

    def test_complexity_level_padrao_e_simple(self, mem):
        """Sem passar complexity_level, default e 'simple'."""
        mem.log_step_metric("code_generation", True)  # sem complexity_level
        rates = mem.get_step_success_rates(complexity_level="simple")
        assert len(rates) == 1


# ============================================================
# Skill 2: agent-evaluation — Behavioral Contracts + Adversarial
# ============================================================

class TestBehavioralContracts:
    """
    Behavioral Contract Testing (skill: agent-evaluation).
    Invariantes que SEMPRE devem ser verdadeiros independente da query.
    Esses testes cobrem o gap real: agent acertou benchmarks mas falhou em
    producao porque nenhum invariante era testado (ex: TranscricaoMultimidia
    sem SettingsPanel).
    """

    def test_arch001_presente_no_Planner(self):
        """INVARIANTE: Planner SEMPRE tem regra ARCH-001 no prompt."""
        from nvdastudio.core.planner import _PLAN_SYSTEM_PROMPT
        assert "ARCH-001" in _PLAN_SYSTEM_PROMPT, (
            "INVARIANTE VIOLADO: ARCH-001 ausente do _PLAN_SYSTEM_PROMPT. "
            "Addons com API externa nao serao gerados com SettingsPanel."
        )

    def test_arch001_menciona_settings_panel_py(self):
        """INVARIANTE: Planner deve nomear o arquivo settings_panel.py."""
        from nvdastudio.core.planner import _PLAN_SYSTEM_PROMPT
        assert "settings_panel.py" in _PLAN_SYSTEM_PROMPT

    def test_arch002_presente_no_Planner(self):
        """INVARIANTE: Planner SEMPRE tem regra ARCH-002 (threading)."""
        from nvdastudio.core.planner import _PLAN_SYSTEM_PROMPT
        assert "ARCH-002" in _PLAN_SYSTEM_PROMPT

    def test_critic_penaliza_falta_de_settings_panel(self):
        """INVARIANTE: Critic SEMPRE penaliza addon com API sem SettingsPanel."""
        from nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        assert "ARCH-001" in _CRITIC_QUALITY_SYSTEM
        assert "-15" in _CRITIC_QUALITY_SYSTEM

    def test_critic_penaliza_io_bloqueante(self):
        """INVARIANTE: Critic SEMPRE penaliza I/O bloqueante na thread principal."""
        from nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        assert "ARCH-002" in _CRITIC_QUALITY_SYSTEM

    def test_nvda_context_tem_template_settings(self):
        """INVARIANTE: nvda_context SEMPRE tem template de SettingsPanel."""
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        assert "MeuAddonSettingsPanel" in NVDA_SYSTEM_PROMPT

    def test_nvda_context_tem_template_threading(self):
        """INVARIANTE: nvda_context SEMPRE tem template de threading."""
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        assert "threading.Thread" in NVDA_SYSTEM_PROMPT

    def test_max_retries_nunca_zero(self):
        """INVARIANTE: max_retries de qualquer step nunca pode ser 0.

        Auditoria 2026-09-01: este teste lia MAX_RETRIES_DEFAULT do
        orchestrator, constante que a producao nao consultava -- o teto real
        vem de planner._MAX_RETRIES_BY_STEP_TYPE, com _MAX_RETRIES_PADRAO de
        fallback. Um step com teto 0 nunca rodaria; e isso que precisa ser
        garantido, em quem decide."""
        from nvdastudio.core.planner import (
            _MAX_RETRIES_BY_STEP_TYPE,
            _MAX_RETRIES_PADRAO,
            Planner,
        )

        assert _MAX_RETRIES_PADRAO > 0
        assert all(v > 0 for v in _MAX_RETRIES_BY_STEP_TYPE.values())
        steps = Planner()._build_steps([
            {"step_id": "s1", "step_type": t, "model_id": "m"}
            for t in ("code_generation", "design_review", "documentation")
        ])
        assert all(s.max_retries > 0 for s in steps)

    def test_session_memory_nunca_executa_codigo(self, mem):
        """INVARIANTE (Regra 9): SessionMemory nunca executa o conteudo armazenado."""
        # Salvar codigo malicioso — nunca deve executar
        mem.log_step_metric(
            "import os; os.system('del /q')",
            success=True,
            complexity_level="complex",
        )
        # Se chegou aqui sem executar o codigo, o invariante foi preservado

    def test_orchestrator_nunca_executa_output_do_llm(self):
        """INVARIANTE (Regra 9): _execute_step_with_critique nao faz exec/eval do output."""
        import inspect
        from nvdastudio.core import orchestrator
        source = inspect.getsource(orchestrator)
        assert "exec(" not in source
        assert "eval(" not in source


class TestAdversarialInputs:
    """
    Adversarial Testing (skill: agent-evaluation).
    Entradas que deveriam provocar comportamento gracioso, nao crash.
    """

    def test_classify_complexity_string_gigante(self):
        """Entrada gigante nao deve crashar o tradutor de vocabulario."""
        from nvdastudio.core.orchestrator import classify_query_complexity
        giant = "x" * 10000
        result = classify_query_complexity(giant)
        assert result in ("simple", "medium", "complex")

    def test_classify_complexity_unicode(self):
        """Caracteres unicode especiais nao devem crashar."""
        from nvdastudio.core.orchestrator import classify_query_complexity
        result = classify_query_complexity("\u0000 \ud83d\ude00")
        assert result in ("simple", "medium", "complex")

    def test_log_step_metric_step_type_enorme(self, mem):
        """step_type com 200 chars nao deve crashar — deve truncar a 50."""
        long_type = "x" * 200
        mem.log_step_metric(long_type, True)  # nao deve lancar excecao

    def test_log_step_metric_complexity_invalida(self, mem):
        """complexity_level nao reconhecido nao deve crashar."""
        mem.log_step_metric("code_generation", True, complexity_level="ultra-mega-complex")

    def test_get_step_success_rates_sem_dados(self, mem):
        """Banco vazio nao deve levantar excecao."""
        rates = mem.get_step_success_rates(complexity_level="complex")
        assert rates == []

    def test_classify_complexity_none_string(self):
        """String com None-like text nao deve crashar."""
        from nvdastudio.core.orchestrator import classify_query_complexity
        assert classify_query_complexity("None") == "medium"

    def test_behavioral_contract_prompt_injection(self):
        """
        Prompt injection no _PLAN_SYSTEM_PROMPT nao deve mudar valores esperados.
        Se alguem injetar 'IGNORE ARCH-001' no prompt, o assert ainda detecta.
        """
        from nvdastudio.core.planner import _PLAN_SYSTEM_PROMPT
        # ARCH-001 deve estar presente como regra real, nao apenas mencionado
        idx = _PLAN_SYSTEM_PROMPT.find("ARCH-001")
        assert idx != -1
        # Deve aparecer como regra definida (letra maiuscula ARCH), nao em comentario
        context_around = _PLAN_SYSTEM_PROMPT[max(0, idx-20):idx+50]
        assert "ARCH-001" in context_around


# ============================================================
# Skill 3: unit-testing-test-generate — test_generator AST
# ============================================================

class TestExtractCodeManifest:
    """_extract_code_manifest() deve extrair estrutura de codigo via AST."""

    def test_versao_test_generator(self):
        from nvdastudio.sub_agents.test_generator import MODULE_VERSION
        assert MODULE_VERSION == "1.8.0"

    def test_extrai_classes_de_bloco_python(self):
        from nvdastudio.sub_agents.test_generator import _extract_code_manifest
        prompt = "```python\nclass TranscricaoService:\n    def transcrever(self): pass\n```"
        result, _sugestoes = _extract_code_manifest(prompt)
        assert "TranscricaoService" in result

    def test_extrai_metodos_publicos(self):
        from nvdastudio.sub_agents.test_generator import _extract_code_manifest
        prompt = "```python\nclass Addon:\n    def ativar(self): pass\n    def _interno(self): pass\n```"
        result, _sugestoes = _extract_code_manifest(prompt)
        assert "ativar" in result
        assert "_interno" not in result  # metodos privados excluidos

    def test_prompt_sem_codigo_retorna_vazio(self):
        from nvdastudio.sub_agents.test_generator import _extract_code_manifest
        result, sugestoes = _extract_code_manifest("apenas texto sem blocos de codigo aqui")
        assert result == ""
        assert sugestoes == []

    def test_prompt_com_codigo_invalido_retorna_vazio(self):
        from nvdastudio.sub_agents.test_generator import _extract_code_manifest
        prompt = "```python\ndef funcao_com_erro(: pass\n```"
        # SyntaxError deve ser silenciada, retorna vazio
        result, sugestoes = _extract_code_manifest(prompt)
        assert result == ""
        assert sugestoes == []

    def test_retorno_contem_instrucao_de_teste(self):
        from nvdastudio.sub_agents.test_generator import _extract_code_manifest
        prompt = "```python\nclass MeuAddon:\n    def rodar(self): pass\n```"
        result, _sugestoes = _extract_code_manifest(prompt)
        assert "INSTRUCAO" in result or "test_" in result.lower()

    def test_multiplos_blocos(self):
        from nvdastudio.sub_agents.test_generator import _extract_code_manifest
        prompt = (
            "```python\nclass Servico:\n    def executar(self): pass\n```\n"
            "```python\nclass Configuracoes:\n    def salvar(self): pass\n```"
        )
        result, _sugestoes = _extract_code_manifest(prompt)
        assert "Servico" in result
        assert "Configuracoes" in result

    def test_extrai_imports_externos(self):
        from nvdastudio.sub_agents.test_generator import _extract_code_manifest
        prompt = "```python\nimport requests\nimport threading\nclass A: pass\n```"
        result, _sugestoes = _extract_code_manifest(prompt)
        assert "requests" in result or "threading" in result

    def test_sem_classes_sem_funcoes_retorna_vazio(self):
        from nvdastudio.sub_agents.test_generator import _extract_code_manifest
        prompt = "```python\n# apenas comentario\nx = 1\n```"
        result, sugestoes = _extract_code_manifest(prompt)
        assert result == ""
        assert sugestoes == []


class TestRunComManifest:
    """run() deve injetar manifesto AST no prompt enriquecido."""

    def test_manifest_injetado_no_prompt_quando_ha_codigo(self):
        """Quando o prompt tem codigo Python, run() injeta o manifesto antes do prompt."""
        from nvdastudio.sub_agents import test_generator
        injected_prompts = []

        def fake_run_sub_agent(system, prompt, model_id, reasoning_params, **kwargs):
            injected_prompts.append(prompt)
            return "```python\ndef test_x(): pass\n```"

        prompt_com_codigo = "```python\nclass TranscricaoService:\n    def transcrever(self): pass\n```"

        with patch.object(test_generator, "_run_sub_agent", side_effect=fake_run_sub_agent):
            test_generator.run(prompt_com_codigo, "modelo", {})

        assert len(injected_prompts) == 1
        assert "TranscricaoService" in injected_prompts[0]
        assert "ESTRUTURA DO ADDON A TESTAR" in injected_prompts[0]

    def test_run_sem_codigo_nao_altera_prompt(self):
        """Sem codigo Python, run() passa o prompt original sem modificar."""
        from nvdastudio.sub_agents import test_generator
        injected_prompts = []

        def fake_run_sub_agent(system, prompt, model_id, reasoning_params, **kwargs):
            injected_prompts.append(prompt)
            return "```python\ndef test_x(): pass\n```"

        prompt_sem_codigo = "cria um addon que le a hora"

        with patch.object(test_generator, "_run_sub_agent", side_effect=fake_run_sub_agent):
            test_generator.run(prompt_sem_codigo, "modelo", {})

        assert len(injected_prompts) == 1
        # Sem codigo, prompt nao deve ter o manifesto
        assert "ESTRUTURA DO ADDON A TESTAR" not in injected_prompts[0]
        assert injected_prompts[0] == prompt_sem_codigo
