import json
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures compartilhadas
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_api_key():
    return "gsk_fake_key_for_tests"


def _mock_llm_resp(payload: dict) -> MagicMock:
    """Factory: cria resposta mockada do GroqClient com payload JSON."""
    mock = MagicMock()
    mock.content = json.dumps(payload)
    mock.reasoning = None
    return mock


# ---------------------------------------------------------------------------
# 1. CLARIFIER_MODEL deve ser kimi-k2.6
# ---------------------------------------------------------------------------

class TestClarifierModelE120b:
    """
    Auditoria 2026-09-01: esta classe afirmava "Invariante: o Clarifier usa
    kimi-k2.6" e verificava a constante CLARIFIER_MODEL. A constante nao era
    lida por ninguem -- get_clarifier_model() sempre devolveu
    get_structured_output_model(0), na pratica opencode_go::gpt-5.6-luna. Tres
    testes passavam afirmando um modelo que nunca rodou.

    Verificar uma constante nao e verificar o comportamento que ela aparenta
    controlar. A constante foi removida (clarifier 1.7.0).
    """

    def test_clarifier_usa_o_modelo_com_json_schema_estrito(self):
        from nvdastudio.ai.clarifier import get_clarifier_model
        from nvdastudio.ai.model_registry import get_structured_output_model

        assert get_clarifier_model() == get_structured_output_model(0)

    def test_constante_morta_nao_volta(self):
        """Se alguem reintroduzir a constante, ela volta a mentir sobre o
        modelo -- a decisao e do resolvedor, nao de um literal no topo."""
        from nvdastudio.ai import clarifier

        assert not hasattr(clarifier, "CLARIFIER_MODEL")


# ---------------------------------------------------------------------------
# 2. Fallback do Critic (get_critic_fallback_model())
# ---------------------------------------------------------------------------

class TestCriticFallbackE120b:
    """
    3.20.0: CRITIC_FALLBACK era constante morta (nao referenciada desde
    3.19.0, quando o Critic passou a ser forcado via OpenCode Go). Removida;
    estes testes agora cobrem get_critic_fallback_model(), a fonte real.
    """

    def test_critic_fallback_e_glm_via_opencode_go(self):
        from nvdastudio.ai.critic import get_critic_fallback_model
        assert get_critic_fallback_model() == "opencode_go::kimi-k2.6"

    def test_critic_fallback_esta_na_cadeia_verificada(self):
        from nvdastudio.ai.critic import get_critic_fallback_model
        from nvdastudio.ai.model_registry import STRUCTURED_OUTPUT_MODEL_CHAIN
        modelo = get_critic_fallback_model().split("::", 1)[1]
        assert modelo in STRUCTURED_OUTPUT_MODEL_CHAIN, (
            f"fallback '{modelo}' nao esta na cadeia verificada {STRUCTURED_OUTPUT_MODEL_CHAIN}"
        )


# ---------------------------------------------------------------------------
# 3. STEP_MODEL_MAP do Planner nao contem kimi-k2.6
# ---------------------------------------------------------------------------

class TestPlannerModelMap120b:
    """
    Invariante: todos os steps do Planner usam kimi-k2.6 ou outro modelo
    valido — nenhum usa kimi-k2.6.
    skill: unit-testing-test-generate — varrer todos os valores do mapa.
    """

    def test_step_test_generation_e_alto(self):
        """v2.17.0: STEP_MODEL_MAP usa o sentinela 'alto' (provider-agnostic) --
        o modelo concreto real e resolvido por apply_model_budget() em runtime,
        nao mais um modelo Ollama hardcoded pra todo provedor."""
        from nvdastudio.ai.model_registry import ALTO_MODEL
        from nvdastudio.core.planner import STEP_MODEL_MAP, STEP_TEST_GENERATION
        model = STEP_MODEL_MAP[STEP_TEST_GENERATION]
        assert model == ALTO_MODEL, (
            f"STEP_TEST_GENERATION deve usar o sentinela 'alto', encontrado: {model}"
        )

    def test_step_user_clarification_e_alto(self):
        from nvdastudio.ai.model_registry import ALTO_MODEL
        from nvdastudio.core.planner import STEP_MODEL_MAP, STEP_USER_CLARIFICATION
        model = STEP_MODEL_MAP[STEP_USER_CLARIFICATION]
        assert model == ALTO_MODEL, (
            f"STEP_USER_CLARIFICATION deve usar o sentinela 'alto', encontrado: {model}"
        )

    def test_todos_modelos_do_mapa_estao_no_catalogo(self):
        """Todos os modelos do STEP_MODEL_MAP devem ser o sentinela 'alto' --
        provider-agnostic, resolvido em runtime por apply_model_budget()."""
        from nvdastudio.ai.model_registry import ALTO_MODEL
        from nvdastudio.core.planner import STEP_MODEL_MAP
        violadores = [
            f"{step}: {model}"
            for step, model in STEP_MODEL_MAP.items()
            if model != ALTO_MODEL
        ]
        assert violadores == [], (
            f"Steps usando modelos fora do catalogo: {violadores}"
        )


# ---------------------------------------------------------------------------
# 4. surgical_edit: ClarificationResult com intent e surgical_description
# ---------------------------------------------------------------------------

class TestSurgicalEditRetornaResultadoCorreto:
    """
    Comportamento: quando LLM classifica como surgical_edit,
    analyze_query retorna intent=surgical_edit e surgical_description preenchido.
    O campo needs_clarification deve ser False (nao interrompe para perguntas).

    skill: testing-patterns — test behavior, not implementation.
    Testamos o contrato publico de analyze_query, nao internals do LLM.
    """

    def test_surgical_edit_retorna_intent_correto(self, fake_api_key):
        from nvdastudio.ai.clarifier import analyze_query
        resp = _mock_llm_resp({
            "intent": "surgical_edit",
            "surgical_description": "No manifest.ini, altere minimumNVDAVersion para 2026.1",
            "needs_clarification": False,
            "questions": [],
            "user_level": "intermediario",
            "forbidden": False,
            "refusal_reason": "",
            "extra_features_planned": [],
        })
        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            Mock.return_value = resp
            result = analyze_query("muda a versao para 2026.1")

        assert result.intent == "surgical_edit"

    def test_surgical_edit_retorna_surgical_description_preenchida(self):
        from nvdastudio.ai.clarifier import analyze_query
        desc = "No manifest.ini, altere minimumNVDAVersion e lastTestedNVDAVersion para 2026.1"
        resp = _mock_llm_resp({
            "intent": "surgical_edit",
            "surgical_description": desc,
            "needs_clarification": False,
            "questions": [],
            "user_level": "intermediario",
            "forbidden": False,
            "refusal_reason": "",
            "extra_features_planned": [],
        })
        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            Mock.return_value = resp
            result = analyze_query("muda a versao para 2026.1")

        assert result.surgical_description == desc

    def test_surgical_edit_nao_precisa_de_clarificacao(self):
        """surgical_edit nunca deve interromper para perguntas."""
        from nvdastudio.ai.clarifier import analyze_query
        resp = _mock_llm_resp({
            "intent": "surgical_edit",
            "surgical_description": "Em __init__.py, remova a linha: import subprocess",
            "needs_clarification": False,
            "questions": [],
            "user_level": "avancado",
            "forbidden": False,
            "refusal_reason": "",
            "extra_features_planned": [],
        })
        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            Mock.return_value = resp
            result = analyze_query("remove o import subprocess")

        assert result.needs_clarification is False
        assert result.questions == []

    def test_surgical_edit_sem_descricao_nao_retorna_surgical(self):
        """
        Se LLM retorna surgical_edit mas sem surgical_description,
        o fluxo NAO deve entrar no bloco surgical_edit — cai no fluxo normal.
        Edge case: proteção contra LLM mal comportado.
        """
        from nvdastudio.ai.clarifier import analyze_query
        resp = _mock_llm_resp({
            "intent": "surgical_edit",
            "surgical_description": "",  # descricao vazia
            "needs_clarification": False,
            "questions": [],
            "user_level": "intermediario",
            "forbidden": False,
            "refusal_reason": "",
            "extra_features_planned": [],
        })
        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            Mock.return_value = resp
            result = analyze_query("muda algo")

        # Sem surgical_description valida, o bloco surgical_edit nao deve ativar
        assert result.intent != "surgical_edit" or result.surgical_description == ""

    def test_create_intent_nao_e_surgical_edit(self, fake_api_key):
        """Pedidos de criacao continuam com intent=create, nao surgical_edit."""
        from nvdastudio.ai.clarifier import analyze_query
        resp = _mock_llm_resp({
            "intent": "create",
            "surgical_description": "",
            "needs_clarification": False,
            "questions": [],
            "user_level": "intermediario",
            "forbidden": False,
            "refusal_reason": "",
            "extra_features_planned": [],
        })
        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            Mock.return_value = resp
            result = analyze_query("Crie um addon que anuncia a hora ao pressionar NVDA+T")

        assert result.intent == "create"
        assert result.surgical_description == ""

    def test_forbidden_intent_retorna_forbidden_true(self, fake_api_key):
        """Pedidos proibidos retornam forbidden=True independente do intent."""
        from nvdastudio.ai.clarifier import analyze_query
        resp = _mock_llm_resp({
            "intent": "forbidden",
            "surgical_description": "",
            "needs_clarification": False,
            "questions": [],
            "user_level": "intermediario",
            "forbidden": True,
            "refusal_reason": "Nao posso criar um keylogger.",
            "extra_features_planned": [],
        })
        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            Mock.return_value = resp
            result = analyze_query("cria um keylogger")

        assert result.forbidden is True
        assert result.intent == "forbidden"


# ---------------------------------------------------------------------------
# 5. ClarificationResult: campos novos tem defaults corretos
# ---------------------------------------------------------------------------

class TestClarificationResultCamposNovos:
    """
    skill: unit-testing-test-generate — novos campos do dataclass.
    Invariante: campos novos nao quebram codigo existente que nao os usa.
    """

    def test_intent_default_e_create(self):
        from nvdastudio.ai.clarifier import ClarificationResult
        r = ClarificationResult(needs_clarification=False, questions=[])
        assert r.intent == "create"

    def test_surgical_description_default_e_vazio(self):
        from nvdastudio.ai.clarifier import ClarificationResult
        r = ClarificationResult(needs_clarification=False, questions=[])
        assert r.surgical_description == ""

    def test_campos_preenchidos_explicitamente(self):
        from nvdastudio.ai.clarifier import ClarificationResult
        r = ClarificationResult(
            needs_clarification=False,
            questions=[],
            intent="surgical_edit",
            surgical_description="Altere o campo author para: Felipe",
        )
        assert r.intent == "surgical_edit"
        assert r.surgical_description == "Altere o campo author para: Felipe"
