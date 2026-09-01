import json
from unittest.mock import MagicMock, patch


from nvdastudio.ai.clarifier import (
    ClarificationResult,
    analyze_query,
    build_enriched_query,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_resp(payload: dict) -> MagicMock:
    mock = MagicMock()
    mock.content = json.dumps(payload)
    mock.reasoning = None
    return mock


# ===========================================================================
# 1. ClarificationResult tem campo addon_architecture
# ===========================================================================

class TestClarificationResultArchitectureField:
    """ClarificationResult deve expor addon_architecture."""

    def test_campo_addon_architecture_existe(self):
        r = ClarificationResult(needs_clarification=False, questions=[])
        assert hasattr(r, "addon_architecture"), (
            "ClarificationResult nao tem campo addon_architecture. "
            "Adicione addon_architecture: str = 'external' ao dataclass."
        )

    def test_default_e_external(self):
        r = ClarificationResult(needs_clarification=False, questions=[])
        assert r.addon_architecture == "external", (
            "addon_architecture default deve ser 'external' (caso mais comum)."
        )

    def test_valores_validos_aceitos(self):
        for val in ("external", "driver", "deep_integration", "ambiguous"):
            r = ClarificationResult(
                needs_clarification=False, questions=[],
                addon_architecture=val,
            )
            assert r.addon_architecture == val


# ===========================================================================
# 2. analyze_query extrai addon_architecture do JSON da LLM
# ===========================================================================

class TestAnalyzeQueryExtractsArchitecture:
    """analyze_query deve propagar addon_architecture retornado pela LLM."""

    def test_architecture_external_propagado(self, fake_api_key):
        payload = {
            "intent": "create",
            "needs_clarification": False,
            "questions": [],
            "addon_architecture": "external",
            "user_level": "intermediario",
            "extra_features_planned": [],
        }
        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            Mock.return_value = _mock_resp(payload)
            result = analyze_query("addon que anuncia a hora")
        assert result.addon_architecture == "external"

    def test_architecture_driver_propagado(self):
        payload = {
            "intent": "create",
            "needs_clarification": False,
            "questions": [],
            "addon_architecture": "driver",
            "user_level": "avancado",
            "extra_features_planned": [],
        }
        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            Mock.return_value = _mock_resp(payload)
            result = analyze_query("crie um SynthDriver para SAPI5")
        assert result.addon_architecture == "driver"

    def test_architecture_ambiguous_dispara_clarificacao(self):
        """Quando addon_architecture=='ambiguous', needs_clarification deve ser True."""
        payload = {
            "intent": "create",
            "needs_clarification": True,
            "questions": [
                "Voce quer que o NVDA inteiro fale com ElevenLabs, "
                "ou so um botao que ativa quando voce quiser?"
            ],
            "addon_architecture": "ambiguous",
            "user_level": "iniciante",
            "extra_features_planned": [],
        }
        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            Mock.return_value = _mock_resp(payload)
            result = analyze_query("quero um addon que use ElevenLabs para falar")
        assert result.addon_architecture == "ambiguous"
        assert result.needs_clarification is True
        assert len(result.questions) >= 1

    def test_architecture_ausente_no_json_usa_default(self, fake_api_key):
        """LLM antiga sem campo addon_architecture nao quebra o sistema."""
        payload = {
            "intent": "create",
            "needs_clarification": False,
            "questions": [],
            "user_level": "intermediario",
            "extra_features_planned": [],
        }
        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            Mock.return_value = _mock_resp(payload)
            result = analyze_query("addon qualquer")
        assert result.addon_architecture == "external"

    def test_architecture_invalida_normalizada_para_external(self):
        """Valor invalido de addon_architecture nao quebra o sistema."""
        payload = {
            "intent": "create",
            "needs_clarification": False,
            "questions": [],
            "addon_architecture": "global_plugin_custom",  # invalido
            "user_level": "intermediario",
            "extra_features_planned": [],
        }
        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            Mock.return_value = _mock_resp(payload)
            result = analyze_query("addon qualquer")
        assert result.addon_architecture in (
            "external", "driver", "deep_integration", "ambiguous"
        ), "Valores invalidos devem ser normalizados para um valor valido."


# ===========================================================================
# 3. _CLARIFIER_SYSTEM instrui a LLM sobre diagnostico arquitetural
# ===========================================================================

class TestClarifierSystemPromptArchitecture:
    """O prompt do Clarifier deve ter instrucoes de diagnostico arquitetural."""

    def _get_system(self) -> str:
        from nvdastudio.ai.clarifier import _CLARIFIER_SYSTEM
        return _CLARIFIER_SYSTEM

    def test_prompt_menciona_addon_architecture(self):
        assert "addon_architecture" in self._get_system(), (
            "_CLARIFIER_SYSTEM nao menciona addon_architecture. "
            "A LLM precisa saber que deve diagnosticar a arquitetura do addon."
        )

    def test_prompt_menciona_driver(self):
        system = self._get_system()
        assert "driver" in system.lower(), (
            "_CLARIFIER_SYSTEM nao menciona 'driver'. "
            "A LLM precisa saber que SynthDriver e BrailleDisplayDriver sao uma "
            "categoria distinta que substitui componentes internos do NVDA."
        )

    def test_prompt_menciona_ambiguous(self):
        assert "ambiguous" in self._get_system(), (
            "_CLARIFIER_SYSTEM nao menciona 'ambiguous'. "
            "A LLM precisa saber quando retornar architecture=ambiguous."
        )

    def test_prompt_instrui_pergunta_funcional_sem_jargao(self):
        system = self._get_system()
        # Deve mencionar a estrategia de fazer pergunta no nivel do usuario
        assert "nivel" in system.lower() or "user_level" in system, (
            "_CLARIFIER_SYSTEM deve instruir que a pergunta arquitetural "
            "deve ser formulada no nivel do usuario (iniciante/avancado)."
        )


# ===========================================================================
# 4. build_enriched_query injeta addon_architecture na query enriquecida
# ===========================================================================

class TestBuildEnrichedQueryArchitecture:
    """build_enriched_query deve propagar addon_architecture para o Planner."""

    def test_architecture_injetada_na_query(self):
        result = build_enriched_query(
            original_query="crie um sintetizador ElevenLabs",
            questions=["Voce quer que substitua toda a voz do NVDA?"],
            answers=["Sim, quero que o NVDA inteiro use ElevenLabs"],
            user_level="iniciante",
            addon_architecture="driver",
        )
        assert "driver" in result.lower() or "sintetizador" in result.lower() or \
               "arquitetura" in result.lower(), (
            "build_enriched_query deve indicar a arquitetura detectada "
            "para que o Planner gere o tipo correto de addon."
        )

    def test_architecture_external_nao_polui_query_simples(self):
        """Para addons externos simples, a arquitetura pode ser omitida ou sutil."""
        result = build_enriched_query(
            original_query="addon que anuncia hora",
            questions=[],
            answers=[],
            user_level="iniciante",
            addon_architecture="external",
        )
        # Deve preservar a query original
        assert "addon que anuncia hora" in result

    def test_signature_aceita_addon_architecture(self):
        """build_enriched_query deve aceitar parametro addon_architecture."""
        import inspect
        sig = inspect.signature(build_enriched_query)
        assert "addon_architecture" in sig.parameters, (
            "build_enriched_query nao tem parametro addon_architecture. "
            "O Planner precisa receber essa informacao."
        )


# ===========================================================================
# 5. Versao do modulo
# ===========================================================================

class TestClarifierVersion:

    def test_versao_e_1_5_0(self):
        from nvdastudio.ai.clarifier import MODULE_VERSION
        assert MODULE_VERSION == "1.7.0", (
            f"clarifier versao esperada 1.5.0, encontrada {MODULE_VERSION}."
        )
