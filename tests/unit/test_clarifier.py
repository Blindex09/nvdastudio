import json
from unittest.mock import MagicMock, patch



from nvdastudio.ai.clarifier import (
    analyze_query, build_enriched_query,
    ClarificationResult, get_clarifier_model,
)

class TestClarifierModel:
    """Invariante: o Clarifier roda no modelo com json_schema estrito garantido.

    Auditoria 2026-09-01: existia aqui um teste afirmando "Invariante: modelo do
    Clarifier e kimi-k2.6", verificando a constante CLARIFIER_MODEL. A constante
    nao era lida por ninguem -- get_clarifier_model() sempre devolveu
    get_structured_output_model(0), na pratica opencode_go::gpt-5.6-luna. O
    teste passava, a mensagem de falha dizia que o modelo do Clarifier era
    kimi-k2.6, e o Clarifier rodava em outro modelo. Falsa confianca: verificar
    uma constante nao e verificar o comportamento que ela aparenta controlar.

    A constante foi removida (clarifier 1.7.0). O teste abaixo checa quem
    decide de fato.
    """

    def test_modelo_do_clarifier_e_o_resolvido_nao_uma_constante(self):
        from nvdastudio.ai.model_registry import get_structured_output_model

        assert get_clarifier_model() == get_structured_output_model(0)

    def test_get_clarifier_model_sempre_opencode_go(self):
        """
        1.6.0: achado real de auditoria 2026-08-26 -- analyze_query() exige
        JSON estrito, mas seguia o tier light do provider ATIVO (Ollama no
        default), sem json_schema real. Agora sempre forca OpenCode Go via
        model_registry.py::get_structured_output_model().
        """
        assert get_clarifier_model() == "opencode_go::gpt-5.6-luna"

    def test_get_clarifier_model_ignora_provider_ativo_do_usuario(self, monkeypatch):
        monkeypatch.setattr("nvdastudio.gui.settings_panel.get_llm_provider", lambda: "gemini")
        monkeypatch.setattr("nvdastudio.gui.settings_panel.get_llm_model", lambda: "gemini-3.1-pro-preview")
        assert get_clarifier_model() == "opencode_go::gpt-5.6-luna"


class TestAnalyzeQueryComMock:
    """Testa analyze_query com GroqClient mockado."""

    def test_query_clara_retorna_needs_false(self, fake_api_key):
        mock_resp = MagicMock()
        mock_resp.content = json.dumps({"needs_clarification": False, "questions": []})
        mock_resp.reasoning = None

        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            Mock.return_value = mock_resp
            result = analyze_query("Crie um globalPlugin que anuncia a hora ao pressionar NVDA+T")

        assert result.needs_clarification is False
        assert result.questions == []

    def test_query_ambigua_retorna_needs_true(self, fake_api_key):
        mock_resp = MagicMock()
        mock_resp.content = json.dumps({
            "needs_clarification": True,
            "questions": ["O que especificamente ele deve fazer no Notepad++?"],
        })
        mock_resp.reasoning = None

        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            Mock.return_value = mock_resp
            result = analyze_query("Crie um addon para Notepad++")

        assert result.needs_clarification is True
        assert len(result.questions) == 1

    def test_no_maximo_3_perguntas(self):
        """Mesmo que a LLM retorne 5 perguntas, so 3 sao aceitas."""
        mock_resp = MagicMock()
        mock_resp.content = json.dumps({
            "needs_clarification": True,
            "questions": ["p1", "p2", "p3", "p4", "p5"],
        })
        mock_resp.reasoning = None

        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            Mock.return_value = mock_resp
            result = analyze_query("addon vago")

        # v1.2.0: cap aumentado para 5 (LLM decide quantas precisa)
        assert len(result.questions) <= 5

    def test_query_vazia_retorna_false_sem_chamar_api(self):
        """Query vazia e tratada deterministicamente — sem custo de API."""
        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            result = analyze_query("")
        Mock.assert_not_called()
        assert result.needs_clarification is False

    def test_query_whitespace_retorna_false_sem_chamar_api(self):
        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            result = analyze_query("   \n\t  ")
        Mock.assert_not_called()
        assert result.needs_clarification is False

    def test_erro_na_api_retorna_false_graceful(self):
        """Falha na API nao bloqueia o usuario — sistema assume query clara."""
        from nvdastudio.ai.llm_client import LLMClientError

        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            Mock.side_effect = LLMClientError("timeout")
            result = analyze_query("addon qualquer")

        assert result.needs_clarification is False

    def test_json_invalido_retorna_false_graceful(self):
        """Resposta invalida da API nao bloqueia o usuario."""
        mock_resp = MagicMock()
        mock_resp.content = "isso nao e json {{{invalido"
        mock_resp.reasoning = None

        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            Mock.return_value = mock_resp
            result = analyze_query("addon qualquer")

        assert result.needs_clarification is False

    def test_retorna_clarification_result(self):
        """Tipo de retorno e sempre ClarificationResult."""
        mock_resp = MagicMock()
        mock_resp.content = json.dumps({"needs_clarification": False, "questions": []})
        mock_resp.reasoning = None

        with patch("nvdastudio.ai.clarifier.call_with_structured_output") as Mock:
            Mock.return_value = mock_resp
            result = analyze_query("addon X")

        assert isinstance(result, ClarificationResult)


class TestBuildEnrichedQuery:
    """Testa combinacao deterministica de query + respostas."""

    def test_combina_query_com_respostas(self):
        result = build_enriched_query(
            original_query="Crie um addon para Notepad++",
            questions=["O que ele deve fazer?", "Precisa de atalho?"],
            answers=["Anunciar numero de linhas", "Sim, NVDA+L"],
        )
        assert "Crie um addon para Notepad++" in result
        assert "Anunciar numero de linhas" in result
        assert "NVDA+L" in result

    def test_sem_perguntas_preserva_query_original(self):
        # v1.1.0: nivel e injetado mesmo sem perguntas (para o Planner adaptar)
        original = "query original sem perguntas"
        result = build_enriched_query(original, [], [])
        assert original in result

    def test_sem_respostas_preserva_query_original(self):
        original = "query sem respostas"
        result = build_enriched_query(original, ["p1", "p2"], [])
        assert original in result

    def test_respostas_vazias_nao_incluidas(self):
        result = build_enriched_query(
            "query",
            questions=["pergunta 1", "pergunta 2"],
            answers=["resposta 1", ""],  # segunda resposta vazia
        )
        assert "resposta 1" in result
        # Resposta vazia nao deve inflar o prompt
        lines_with_content = [line for line in result.split("\n") if line.strip()]
        assert not any("pergunta 2" in line and ": " in line and not line.split(": ", 1)[1].strip()
                       for line in lines_with_content)

    def test_resultado_e_string_nao_vazia(self):
        result = build_enriched_query("query", ["p"], ["r"])
        assert isinstance(result, str)
        assert len(result) > 0

    def test_query_preservada_no_inicio(self):
        """A query original deve ser a primeira parte do resultado."""
        original = "minha query original"
        result = build_enriched_query(original, ["p"], ["r"])
        assert result.startswith(original)


class TestClarificationResult:
    """Invariante: campos padrao do dataclass."""

    def test_campos_padrao(self):
        r = ClarificationResult(needs_clarification=False, questions=[])
        assert r.enriched_query == ""

    def test_campos_preenchidos(self):
        r = ClarificationResult(
            needs_clarification=True,
            questions=["q1", "q2"],
            enriched_query="query enriquecida com respostas",
        )
        assert r.needs_clarification is True
        assert len(r.questions) == 2
        assert "enriquecida" in r.enriched_query
