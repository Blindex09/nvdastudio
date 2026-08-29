import json
from unittest.mock import MagicMock, patch


from nvdastudio.ai.critic import (
    Critic, CriticResult, Verdict,
    get_critic_model, get_critic_fallback_model,
    _CRITIC_SPEC_SYSTEM, _CRITIC_QUALITY_SYSTEM, _CRITIC_SYSTEM,
)


class TestCriticModels:
    """
    3.20.0: CRITIC_MODEL/CRITIC_FALLBACK eram constantes mortas (nao
    referenciadas em lugar nenhum desde 3.19.0, quando get_critic_model()/
    get_critic_fallback_model() passaram a forcar OpenCode Go). Removidas;
    estes testes agora cobrem a fonte de verdade real.
    """

    def test_critic_model_e_kimi_via_opencode_go(self):
        assert get_critic_model() == "opencode_go::gpt-5.6-luna"

    def test_critic_fallback_e_glm_via_opencode_go(self):
        assert get_critic_fallback_model() == "opencode_go::kimi-k2.6"


class TestCriticSystemCombinado:
    """
    v2.0.0: _CRITIC_SYSTEM combina spec + quality.
    Testes verificam que os dois sistemas estao no combinado.
    """

    def test_critic_system_contem_spec_criterios(self):
        # Fonte: nvda-addon-specialist.kimi.md — codigo Python com GlobalPlugin e obrigatorio
        # Texto atualizado em critic.py v2.1.0: "contem codigo Python" (minusculo, dentro de frase)
        assert "codigo Python" in _CRITIC_SYSTEM

    def test_critic_system_contem_quality_criterios(self):
        assert "NVDA-001" in _CRITIC_SYSTEM
        assert "WX-A11Y" in _CRITIC_SYSTEM

    def test_critic_system_contem_agent_runner(self):
        assert "_fallback_chain" in _CRITIC_SYSTEM
        assert "reset_session" in _CRITIC_SYSTEM
        assert "ImportError" in _CRITIC_SYSTEM

    def test_critic_system_contem_agent_template(self):
        assert "Community Access" in _CRITIC_SYSTEM or "community access" in _CRITIC_SYSTEM.lower()
        assert "Invariantes" in _CRITIC_SYSTEM or "invariantes" in _CRITIC_SYSTEM.lower()

    def test_spec_e_quality_sao_strings_validas(self):
        assert isinstance(_CRITIC_SPEC_SYSTEM, str) and len(_CRITIC_SPEC_SYSTEM) > 0
        assert isinstance(_CRITIC_QUALITY_SYSTEM, str) and len(_CRITIC_QUALITY_SYSTEM) > 0

    def test_quality_system_tem_regras_nvda(self):
        """QualityCritic deve ter as regras NVDA-001 a NVDA-018."""
        for rule_id in ["NVDA-001", "NVDA-002", "NVDA-003", "NVDA-004", "NVDA-010", "NVDA-018"]:
            assert rule_id in _CRITIC_QUALITY_SYSTEM, f"{rule_id} ausente no QualityCritic"

    def test_quality_system_tem_regras_wx(self):
        """QualityCritic deve ter as regras WX-A11Y."""
        for rule_id in ["WX-A11Y-001", "WX-A11Y-005", "WX-A11Y-009", "WX-A11Y-012"]:
            assert rule_id in _CRITIC_QUALITY_SYSTEM, f"{rule_id} ausente no QualityCritic"


class TestCriticParseResult:
    """Testes de _parse_result — logica deterministica de parsing."""

    def setup_method(self):
        self.critic = Critic.__new__(Critic)
        self.critic._api_key = "fake"

    def test_parse_aprovado(self, valid_critic_json_approved):
        result = self.critic._parse_result(valid_critic_json_approved)
        assert result.verdict == Verdict.APPROVED
        assert result.score == 95
        assert result.issues == []

    def test_parse_corrigir(self, valid_critic_json_fix):
        result = self.critic._parse_result(valid_critic_json_fix)
        assert result.verdict == Verdict.NEEDS_FIX
        assert result.score == 72
        assert len(result.issues) == 1

    def test_parse_rejeitar(self, valid_critic_json_reject):
        result = self.critic._parse_result(valid_critic_json_reject)
        assert result.verdict == Verdict.REJECTED
        assert result.score == 30
        assert len(result.issues) == 2

    def test_parse_json_com_markdown_fence(self, valid_critic_json_approved):
        raw = "```json\n" + valid_critic_json_approved + "\n```"
        result = self.critic._parse_result(raw)
        assert result.verdict == Verdict.APPROVED

    def test_parse_json_invalido_retorna_needs_fix(self):
        result = self.critic._parse_result("nao e json {{{")
        assert result.verdict == Verdict.NEEDS_FIX
        assert result.score == 50
        assert len(result.issues) > 0

    def test_parse_verdict_desconhecido_retorna_needs_fix(self):
        raw = '{"verdict": "INDEFINIDO", "score": 70, "issues": [], "fix_instructions": ""}'
        result = self.critic._parse_result(raw)
        assert result.verdict == Verdict.NEEDS_FIX

    def test_parse_score_preservado(self):
        for score in [0, 50, 89, 90, 100]:
            raw = json.dumps({"verdict": "APROVADO", "score": score,
                              "issues": [], "fix_instructions": ""})
            result = self.critic._parse_result(raw)
            assert result.score == score


class TestVerdictLogic:
    def test_score_alto_deve_ser_aprovado(self):
        for score in [90, 95, 100]:
            raw = json.dumps({"verdict": "APROVADO", "score": score,
                              "issues": [], "fix_instructions": ""})
            critic = Critic.__new__(Critic)
            result = critic._parse_result(raw)
            assert result.verdict == Verdict.APPROVED

    def test_score_baixo_deve_ser_rejeitar(self):
        raw = json.dumps({"verdict": "REJEITAR", "score": 30,
                          "issues": ["problema grave"], "fix_instructions": "reescreva"})
        critic = Critic.__new__(Critic)
        result = critic._parse_result(raw)
        assert result.verdict == Verdict.REJECTED


class TestCriticEvaluateComMock:
    """Testa evaluate() (estagio unico) com GroqClient mockado."""

    def test_evaluate_retorna_critic_result(self, fake_api_key, valid_critic_json_approved):
        mock_resp = MagicMock()
        mock_resp.content = valid_critic_json_approved
        mock_resp.reasoning = None

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.return_value = mock_resp
            critic = Critic()
            result = critic.evaluate("code_generation", "codigo qualquer")

        assert isinstance(result, CriticResult)
        assert result.verdict == Verdict.APPROVED

    def test_evaluate_content_vazio_retorna_needs_fix(
        self, fake_api_key, valid_critic_json_approved
    ):
        # v2.0.0: content vazio e tratado como json invalido -> NEEDS_FIX
        mock_resp = MagicMock()
        mock_resp.content = ""
        mock_resp.reasoning = valid_critic_json_approved

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.return_value = mock_resp
            critic = Critic()
            result = critic.evaluate("code_generation", "codigo qualquer")

        assert isinstance(result, CriticResult)
        assert result.verdict == Verdict.NEEDS_FIX

    def test_evaluate_usa_fallback_se_principal_falha(
        self, fake_api_key, valid_critic_json_approved
    ):
        from nvdastudio.ai.llm_client import LLMClientError
        mock_resp = MagicMock()
        mock_resp.content = valid_critic_json_approved
        mock_resp.reasoning = None
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise LLMClientError("kimi falhou")
            return mock_resp

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.side_effect = side_effect
            critic = Critic()
            result = critic.evaluate("manifest_builder", "conteudo qualquer")

        assert isinstance(result, CriticResult)

    def test_evaluate_passa_step_type_no_prompt(self, fake_api_key, valid_critic_json_approved):
        mock_resp = MagicMock()
        mock_resp.content = valid_critic_json_approved
        mock_resp.reasoning = None
        prompts_recebidos = []

        def capture_chat(prompt, **kwargs):
            prompts_recebidos.append(prompt)
            return mock_resp

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.side_effect = capture_chat
            critic = Critic()
            critic.evaluate("accessibility_audit", "codigo")

        assert any("accessibility_audit" in p for p in prompts_recebidos)

    def test_evaluate_nao_executa_codigo(self, fake_api_key, valid_critic_json_approved):
        mock_resp = MagicMock()
        mock_resp.content = valid_critic_json_approved
        mock_resp.reasoning = None
        codigo_malicioso = "import os; os.system('del C:\\\\*')"

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.return_value = mock_resp
            critic = Critic()
            result = critic.evaluate("code_generation", codigo_malicioso)

        assert isinstance(result, CriticResult)


class TestCriticEscalaParaFallbackQuandoConteudoVazio:
    """
    Regressao para bug real achado ao vivo (test_e36, GeminiMultimodal,
    s5 code_generation) -- "Critic retornou vazio ou sem JSON reconhecivel"
    3x seguidas, sempre no modelo LEVE. O fallback pro modelo pesado so
    disparava em LLMClientError (excecao) -- uma chamada BEM-SUCEDIDA mas
    com content vazio/cortado nunca escalava. critic.py 3.15.0 fecha esse
    gap em _call_critic_with_system().
    """

    def test_conteudo_vazio_sem_excecao_escala_pro_fallback(
        self, fake_api_key, valid_critic_json_approved
    ):
        empty_resp = MagicMock()
        empty_resp.content = ""
        empty_resp.truncated = False
        fallback_resp = MagicMock()
        fallback_resp.content = valid_critic_json_approved
        fallback_resp.truncated = False
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            return empty_resp if call_count["n"] == 1 else fallback_resp

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.side_effect = side_effect
            critic = Critic()
            result = critic.evaluate("code_generation", "codigo qualquer")

        assert call_count["n"] == 2, (
            "conteudo vazio sem excecao deveria escalar pro modelo fallback "
            "(2a chamada), nao parar na 1a."
        )
        assert result.verdict == Verdict.APPROVED, (
            "o fallback trouxe um veredicto valido -- o resultado final deve "
            "refletir ele, nao o fallback textual generico score=50."
        )

    def test_truncado_sem_excecao_escala_pro_fallback(
        self, fake_api_key, valid_critic_json_approved
    ):
        truncated_resp = MagicMock()
        truncated_resp.content = '{"verdict": "APROVAR", "score": 9'  # cortado no meio
        truncated_resp.truncated = True
        fallback_resp = MagicMock()
        fallback_resp.content = valid_critic_json_approved
        fallback_resp.truncated = False
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            return truncated_resp if call_count["n"] == 1 else fallback_resp

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.side_effect = side_effect
            critic = Critic()
            result = critic.evaluate("code_generation", "codigo qualquer")

        assert call_count["n"] == 2
        assert result.verdict == Verdict.APPROVED

    def test_fallback_tambem_vazio_nao_apaga_resp_original_nao_vazio(
        self, fake_api_key
    ):
        """Se o principal veio truncado mas com ALGUM conteudo, e o fallback
        volta vazio, deve manter o conteudo do principal (algo e melhor que
        nada) em vez de substituir por uma string vazia."""
        truncated_resp = MagicMock()
        truncated_resp.content = '{"verdict": "APROVADO", "score": 90, "issues": []}'
        truncated_resp.truncated = True
        empty_fallback_resp = MagicMock()
        empty_fallback_resp.content = ""
        empty_fallback_resp.truncated = False
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            return truncated_resp if call_count["n"] == 1 else empty_fallback_resp

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.side_effect = side_effect
            critic = Critic()
            result = critic.evaluate("code_generation", "codigo qualquer")

        assert result.verdict == Verdict.APPROVED, (
            "conteudo truncado mas parseavel do principal deveria ser "
            "aproveitado quando o fallback nao trouxe nada melhor."
        )

    def test_conteudo_normal_nao_escala(self, fake_api_key, valid_critic_json_approved):
        """Caminho feliz: resposta completa na 1a tentativa nao deve chamar
        o fallback -- regressao contra escalar demais."""
        mock_resp = MagicMock()
        mock_resp.content = valid_critic_json_approved
        mock_resp.truncated = False

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.return_value = mock_resp
            critic = Critic()
            critic.evaluate("code_generation", "codigo qualquer")

        assert MockClient.return_value.chat.call_count == 1


class TestCriticOutputVazioGuard:
    """Output vazio rejeitado deterministicamente sem chamar LLM."""

    def test_output_vazio_retorna_rejeitar_sem_chamar_llm(self, fake_api_key):
        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            critic = Critic()
            result = critic.evaluate("code_generation", "")

        MockClient.return_value.chat.assert_not_called()
        assert result.verdict == Verdict.REJECTED
        assert result.score == 0

    def test_output_whitespace_retorna_rejeitar_sem_chamar_llm(self, fake_api_key):
        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            critic = Critic()
            result = critic.evaluate("manifest_builder", "   \n\t  ")

        MockClient.return_value.chat.assert_not_called()
        assert result.verdict == Verdict.REJECTED

    def test_output_nao_vazio_chama_llm(self, fake_api_key, valid_critic_json_approved):
        mock_resp = MagicMock()
        mock_resp.content = valid_critic_json_approved
        mock_resp.reasoning = None

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.return_value = mock_resp
            critic = Critic()
            critic.evaluate("code_generation", "import globalPluginHandler")

        MockClient.return_value.chat.assert_called_once()


class TestCriticDoisEstagios:
    """
    Testa evaluate_two_stage() — metodo principal v2.0.0.
    Basado em c:\\skills\\subagent-driven-development\\SKILL.md:
    spec compliance primeiro, quality depois.
    """

    def _make_mock_resp(self, json_str):
        mock_resp = MagicMock()
        mock_resp.content = json_str
        mock_resp.reasoning = None
        return mock_resp

    def test_dois_estagios_output_vazio_rejeita(self, fake_api_key):
        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            critic = Critic()
            result = critic.evaluate_two_stage("code_generation", "")

        MockClient.return_value.chat.assert_not_called()
        assert result.verdict == Verdict.REJECTED
        assert result.score == 0

    def test_dois_estagios_spec_aprovado_quality_aprovado(
        self, fake_api_key, valid_critic_json_approved
    ):
        """Quando spec passa e quality passa: resultado e APROVADO."""
        mock_resp = self._make_mock_resp(valid_critic_json_approved)

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.return_value = mock_resp
            critic = Critic()
            result = critic.evaluate_two_stage("code_generation", "codigo valido")

        assert result.verdict == Verdict.APPROVED
        # Deve ter chamado a API duas vezes (spec + quality)
        assert MockClient.return_value.chat.call_count == 2

    def test_dois_estagios_spec_falha_quality_nao_roda(
        self, fake_api_key, valid_critic_json_fix
    ):
        """Se spec falha (CORRIGIR), quality nao deve ser chamado."""
        mock_resp = self._make_mock_resp(valid_critic_json_fix)

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.return_value = mock_resp
            critic = Critic()
            result = critic.evaluate_two_stage("code_generation", "codigo incompleto")

        assert result.verdict == Verdict.NEEDS_FIX
        assert result.stage == "spec"
        # Spec falhou: quality nao deve ter rodado
        assert MockClient.return_value.chat.call_count == 1

    def test_dois_estagios_spec_rejected_quality_nao_roda(
        self, fake_api_key, valid_critic_json_reject
    ):
        """Se spec rejeita, quality nao deve ser chamado."""
        mock_resp = self._make_mock_resp(valid_critic_json_reject)

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.return_value = mock_resp
            critic = Critic()
            result = critic.evaluate_two_stage("manifest_builder", "conteudo")

        assert result.verdict == Verdict.REJECTED
        assert result.stage == "spec"
        assert MockClient.return_value.chat.call_count == 1

    def test_dois_estagios_result_tem_stage_field(self, fake_api_key, valid_critic_json_approved):
        """CriticResult.stage deve indicar qual estagio gerou o veredicto."""
        mock_resp = self._make_mock_resp(valid_critic_json_approved)

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.return_value = mock_resp
            critic = Critic()
            result = critic.evaluate_two_stage("assembly", "output valido")

        assert hasattr(result, "stage")
        assert result.stage in ("spec", "quality", "single", "two_stage")

    def test_dois_estagios_nao_executa_codigo(self, fake_api_key, valid_critic_json_approved):
        """Regra 9: evaluate_two_stage analisa texto, nunca executa."""
        mock_resp = self._make_mock_resp(valid_critic_json_approved)
        codigo_malicioso = "import os; os.system('echo EXECUTADO')"

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.return_value = mock_resp
            critic = Critic()
            result = critic.evaluate_two_stage("code_generation", codigo_malicioso)

        assert isinstance(result, CriticResult)


class TestCriticRejeitarConfirmacaoIndependente:
    """
    critic.py 3.8.0: REJEITAR do estagio de quality passa por um segundo
    julgamento independente antes de virar final (skill agent-evaluation +
    padrao Self-Agg/votacao -- reduz falso REJEITAR, que dispara replan caro).
    """

    def _make_mock_resp(self, json_str):
        mock_resp = MagicMock()
        mock_resp.content = json_str
        mock_resp.reasoning = None
        return mock_resp

    def test_rejeitar_confirmado_por_segunda_passada_permanece_rejeitar(
        self, fake_api_key, valid_critic_json_approved, valid_critic_json_reject
    ):
        """Se a segunda passada TAMBEM rejeita, o veredicto final e REJEITAR."""
        responses = [
            self._make_mock_resp(valid_critic_json_approved),  # spec
            self._make_mock_resp(valid_critic_json_reject),    # quality
            self._make_mock_resp(valid_critic_json_reject),    # confirmacao
        ]

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.side_effect = responses
            critic = Critic()
            result = critic.evaluate_two_stage("code_generation", "codigo qualquer")

        assert result.verdict == Verdict.REJECTED
        assert result.stage == "two_stage_reject_confirmed"
        assert MockClient.return_value.chat.call_count == 3

    def test_rejeitar_nao_confirmado_e_rebaixado_para_corrigir(
        self, fake_api_key, valid_critic_json_approved, valid_critic_json_reject,
        valid_critic_json_fix,
    ):
        """Se a segunda passada discorda (nao rejeita), rebaixa para CORRIGIR
        em vez de manter um REJEITAR potencialmente falso."""
        responses = [
            self._make_mock_resp(valid_critic_json_approved),  # spec
            self._make_mock_resp(valid_critic_json_reject),    # quality
            self._make_mock_resp(valid_critic_json_fix),       # confirmacao discorda
        ]

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.side_effect = responses
            critic = Critic()
            result = critic.evaluate_two_stage("code_generation", "codigo qualquer")

        assert result.verdict == Verdict.NEEDS_FIX
        assert result.stage == "two_stage_reject_downgraded"
        assert MockClient.return_value.chat.call_count == 3
        assert any("nao confirmado" in issue.lower() for issue in result.issues)

    def test_rejeitar_do_spec_nao_dispara_confirmacao_extra(
        self, fake_api_key, valid_critic_json_reject
    ):
        """REJEITAR do Estagio 1 (spec) retorna cedo -- sem confirmacao extra
        (comportamento pre-existente, ja coberto por
        test_dois_estagios_spec_rejected_quality_nao_roda)."""
        mock_resp = self._make_mock_resp(valid_critic_json_reject)

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.return_value = mock_resp
            critic = Critic()
            result = critic.evaluate_two_stage("manifest_builder", "conteudo")

        assert result.verdict == Verdict.REJECTED
        assert result.stage == "spec"
        assert MockClient.return_value.chat.call_count == 1


class TestCriticPropagaStepTypeParaTetoDeTokensEstendido:
    """
    critic.py 3.9.0: bug real do teste E2E complexo (addon
    AssistenteLeituraGemini) -- o critic avaliando um code_generation
    grande usava o teto de tokens PADRAO (24k) em vez do ESTENDIDO (48k)
    que o proprio code_generation ja ganha, porque step_type nunca era
    repassado ate client.chat(). 3 tentativas seguidas retornaram "Critic
    retornou vazio ou sem JSON reconhecivel" (JSON cortado antes de fechar).
    """

    def test_evaluate_two_stage_repassa_step_type_code_generation(
        self, fake_api_key, valid_critic_json_approved
    ):
        mock_resp = MagicMock()
        mock_resp.content = valid_critic_json_approved
        mock_resp.reasoning = None
        mock_resp.truncated = False

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.return_value = mock_resp
            critic = Critic()
            critic.evaluate_two_stage("code_generation", "codigo valido")

        for call in MockClient.return_value.chat.call_args_list:
            assert call.kwargs.get("step_type") == "code_generation"

    def test_evaluate_single_stage_repassa_step_type(
        self, fake_api_key, valid_critic_json_approved
    ):
        mock_resp = MagicMock()
        mock_resp.content = valid_critic_json_approved
        mock_resp.reasoning = None
        mock_resp.truncated = False

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.return_value = mock_resp
            critic = Critic()
            critic.evaluate("agent_runner", "output do agente")

        _, kwargs = MockClient.return_value.chat.call_args
        assert kwargs.get("step_type") == "agent_runner"

    def test_resposta_truncada_nao_quebra_e_loga_aviso(
        self, fake_api_key, caplog
    ):
        """Se resp.truncated=True, o critic nao deve lancar excecao --
        so logar um aviso claro e seguir com o parse (que provavelmente
        falha de forma diagnosticavel, nao mais silenciosa)."""
        mock_resp = MagicMock()
        mock_resp.content = '{"verdict": "COR'  # JSON incompleto, simulando corte
        mock_resp.reasoning = None
        mock_resp.truncated = True

        with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
            MockClient.return_value.chat.return_value = mock_resp
            critic = Critic()
            result = critic.evaluate("code_generation", "codigo qualquer")

        assert isinstance(result, CriticResult)
        assert any("cortada pelo teto de tokens" in rec.message for rec in caplog.records)


class TestCriticParseResultRobustez:
    def setup_method(self):
        self.critic = Critic.__new__(Critic)
        self.critic._api_key = "fake"

    def test_extrai_json_de_dentro_de_thinking(self):
        raw = (
            'Deixa eu pensar...\n\n'
            '{"verdict": "APROVADO", "score": 92, "issues": [], "fix_instructions": ""}\n\n'
            'Fim do raciocinio.'
        )
        result = self.critic._parse_result(raw)
        assert result.verdict == Verdict.APPROVED
        assert result.score == 92

    def test_fix_instructions_como_string(self, valid_critic_json_fix):
        result = self.critic._parse_result(valid_critic_json_fix)
        assert isinstance(result.fix_instructions, str)

    def test_stage_default_e_single(self, valid_critic_json_approved):
        result = self.critic._parse_result(valid_critic_json_approved)
        assert result.stage == "single"

    def test_parse_dict_python_com_aspas_simples(self):
        raw = "{'verdict': 'APROVADO', 'score': 91, 'issues': [], 'fix_instructions': ''}"
        result = self.critic._parse_result(raw)
        assert result.verdict == Verdict.APPROVED
        assert result.score == 91

    def test_parse_json_com_path_windows_mal_escapado(self):
        raw = (
            r'{"verdict": "CORRIGIR", "score": 73, "issues": ["ajuste"], '
            r'"fix_instructions": "Revise C:\meuAddon\logs"}'
        )
        result = self.critic._parse_result(raw)
        assert result.verdict == Verdict.NEEDS_FIX
        assert result.score == 73
        assert "C:\\meuAddon\\logs" in result.fix_instructions

    def test_parse_json_com_quebra_de_linha_crua_em_string(self):
        raw = (
            '{"verdict": "CORRIGIR", "score": 68, "issues": ["ajuste"], '
            '"fix_instructions": "Linha 1\nLinha 2"}'
        )
        result = self.critic._parse_result(raw)
        assert result.verdict == Verdict.NEEDS_FIX
        assert result.score == 68
        assert "Linha 1" in result.fix_instructions


# --------------------------------------------------------------------------
# Testes: dimension_scores — v2.9.0
# skill: llm-evaluation (Multi-Dimensional Scoring)
# --------------------------------------------------------------------------

class TestCriticDimensionScores:
    """
    v2.9.0: CriticResult.dimension_scores — score por dimensao (completeness,
    format, nvda_compliance). Permite fix_instructions cirurgico por dimensao.
    skill: llm-evaluation (Multi-Dimensional Scoring).
    """

    def setup_method(self):
        self.critic = Critic.__new__(Critic)
        self.critic._api_key = "fake"

    def test_critic_result_tem_campo_dimension_scores(self):
        """CriticResult deve ter campo dimension_scores."""
        r = CriticResult(
            verdict=Verdict.APPROVED, score=90,
            issues=[], fix_instructions=""
        )
        assert hasattr(r, "dimension_scores")

    def test_dimension_scores_default_dict_vazio(self):
        """Sem dimension_scores no payload: campo deve ser dict vazio (nao None)."""
        r = CriticResult(
            verdict=Verdict.APPROVED, score=90,
            issues=[], fix_instructions=""
        )
        assert r.dimension_scores == {}
        assert r.dimension_scores is not None

    def test_parse_result_extrai_dimension_scores(self):
        """_parse_result deve extrair dimension_scores do JSON."""
        raw = json.dumps({
            "verdict": "CORRIGIR",
            "score": 72,
            "issues": ["sem decorator"],
            "fix_instructions": "adicione @script",
            "dimension_scores": {
                "completeness": 90,
                "format": 85,
                "nvda_compliance": 40,
            },
        })
        result = self.critic._parse_result(raw)
        assert result.dimension_scores["completeness"] == 90
        assert result.dimension_scores["format"] == 85
        assert result.dimension_scores["nvda_compliance"] == 40

    def test_parse_result_sem_dimension_scores_usa_vazio(self):
        """JSON sem dimension_scores: campo deve ser dict vazio."""
        raw = json.dumps({
            "verdict": "APROVADO",
            "score": 93,
            "issues": [],
            "fix_instructions": "",
        })
        result = self.critic._parse_result(raw)
        assert result.dimension_scores == {}

    def test_dimension_scores_clampeados_0_100(self):
        """Valores fora de range [0,100] devem ser clampeados."""
        raw = json.dumps({
            "verdict": "CORRIGIR",
            "score": 70,
            "issues": [],
            "fix_instructions": "",
            "dimension_scores": {"completeness": -5, "format": 150, "nvda_compliance": 50},
        })
        result = self.critic._parse_result(raw)
        assert result.dimension_scores["completeness"] == 0
        assert result.dimension_scores["format"] == 100
        assert result.dimension_scores["nvda_compliance"] == 50

    def test_dimension_scores_chaves_desconhecidas_ignoradas(self):
        """Chaves nao reconhecidas nao quebram o parse."""
        raw = json.dumps({
            "verdict": "APROVADO",
            "score": 91,
            "issues": [],
            "fix_instructions": "",
            "dimension_scores": {"xpto_desconhecido": 77, "completeness": 88},
        })
        result = self.critic._parse_result(raw)
        assert result.dimension_scores["completeness"] == 88
        # chave desconhecida pode ser ignorada — nao nos campos esperados
        assert "xpto_desconhecido" not in result.dimension_scores

    def test_quality_system_contem_dimension_scores(self):
        """_CRITIC_QUALITY_SYSTEM deve solicitar dimension_scores no JSON."""
        assert "dimension_scores" in _CRITIC_QUALITY_SYSTEM

    def test_quality_system_contem_nvda_compliance(self):
        """dimension nvda_compliance deve estar no prompt."""
        assert "nvda_compliance" in _CRITIC_QUALITY_SYSTEM

    def test_dimension_scores_nao_afeta_verdict(self):
        """dimension_scores e campo informativo — nao altera verdict/score."""
        raw = json.dumps({
            "verdict": "APROVADO",
            "score": 95,
            "issues": [],
            "fix_instructions": "",
            "dimension_scores": {"completeness": 10, "format": 10, "nvda_compliance": 10},
        })
        result = self.critic._parse_result(raw)
        # Verdict e score vem do payload top-level, nao das dimensoes
        assert result.verdict == Verdict.APPROVED
        assert result.score == 95

    def test_build_targeted_fix_sem_dimension_retorna_fix_original(self):
        """Sem dimension_scores: _build_targeted_fix retorna fix_instructions original."""
        from nvdastudio.core.orchestrator import Orchestrator
        result = CriticResult(
            verdict=Verdict.NEEDS_FIX, score=70,
            issues=["problema X"], fix_instructions="corrija X",
        )
        fix = Orchestrator._build_targeted_fix(result)
        assert fix == "corrija X"

    def test_build_targeted_fix_com_dimension_prefixa_pior_dim(self):
        """Com dimension_scores: prefixo indica a dimensao mais fraca."""
        from nvdastudio.core.orchestrator import Orchestrator
        result = CriticResult(
            verdict=Verdict.NEEDS_FIX, score=70,
            issues=["sem decorator"],
            fix_instructions="adicione @script",
            dimension_scores={"completeness": 90, "format": 85, "nvda_compliance": 30},
        )
        fix = Orchestrator._build_targeted_fix(result)
        assert "nvda_compliance" in fix.lower() or "nvda" in fix.lower()
        assert "30" in fix
        assert "adicione @script" in fix




class TestCriticManifestUrlGuard:
	"""Regressao do plano aa1600dd: manifest com 'url = ' vazio aprovado score 100.

	O Critic LLM nao detectou. Agora ha guard deterministico antes do estagio 1.
	"""

	def test_url_vazio_dispara_needs_fix(self):
		manifest_invalido = (
			"name = MeuAddon\n"
			"summary = teste\n"
			"description = descricao\n"
			"author = Autor\n"
			"url = \n"
			"version = 1.0.0\n"
			"minimumNVDAVersion = 2026.1.0\n"
			"lastTestedNVDAVersion = 2026.1.0\n"
		)
		critic = Critic()
		result = critic.evaluate_two_stage("manifest_builder", manifest_invalido)
		assert result.verdict == Verdict.NEEDS_FIX, (
			f"url vazio deve disparar CORRIGIR (recebido: {result.verdict})"
		)
		assert any("url" in issue.lower() for issue in result.issues), (
			f"issue deve mencionar 'url'. Issues: {result.issues}"
		)
		# Nao deve ter chamado LLM (guard deterministico)
		assert result.stage == "spec"

	def test_url_sem_https_dispara_needs_fix(self):
		manifest_invalido = (
			"name = MeuAddon\n"
			"version = 1.0.0\n"
			"url = http://example.com\n"
			"minimumNVDAVersion = 2026.1.0\n"
		)
		critic = Critic()
		result = critic.evaluate_two_stage("manifest_builder", manifest_invalido)
		assert result.verdict == Verdict.NEEDS_FIX
		assert any("https" in issue.lower() for issue in result.issues)

	def test_url_https_valido_passa_pelo_guard(self):
		"""Url valido nao dispara o guard — segue pro estagio LLM normal."""
		from unittest.mock import patch
		manifest_valido = (
			"name = MeuAddon\n"
			"version = 1.0.0\n"
			"url = https://github.com/me/addon\n"
			"minimumNVDAVersion = 2026.1.0\n"
		)
		# Mocka o LLM para o teste nao depender de rede.
		# Se chegar ate aqui, e porque o guard NAO bloqueou.
		fake_resp = json.dumps({
			"verdict": "APROVADO", "score": 95, "issues": [], "fix_instructions": ""
		})
		critic = Critic()
		with patch.object(critic, "_call_critic_with_system", return_value=fake_resp):
			result = critic.evaluate_two_stage("manifest_builder", manifest_valido)
		# O guard nao deve ter bloqueado — LLM foi chamado e retornou APROVADO
		assert result.verdict == Verdict.APPROVED

	def test_helper_isolado_aceita_aspas(self):
		"""url envolto em aspas tambem deve ser detectado."""
		assert Critic._check_manifest_url_invalid('url = ""') is not None
		assert Critic._check_manifest_url_invalid("url = ''") is not None
		assert Critic._check_manifest_url_invalid('url = "https://x.io"') is None

	def test_helper_isolado_ignora_comentarios(self):
		"""Linhas com # ou ; sao comentarios — devem ser ignoradas."""
		# Aqui nao ha linha 'url =' real — o guard nao opina.
		assert Critic._check_manifest_url_invalid("# url = vazio") is None
		assert Critic._check_manifest_url_invalid("; url = ") is None


class TestCriticWebResearchBlocoPythonGuard:
	"""
	critic.py 3.10.0: guard deterministico -- web_research que devolve um
	bloco ```python:arquivo.py``` (formato exclusivo de code_generation)
	e rejeitado direto, sem chamar o LLM. Achado real reproduzido 3x em 3
	rodadas do teste E2E complexo real (addon AssistenteLeituraGemini,
	deepseek-v4-flash devolvendo "Hello World" de addon NVDA em vez de
	texto de pesquisa).
	"""

	def test_bloco_python_dispara_needs_fix_sem_chamar_llm(self, fake_api_key):
		saida_errada = (
			"```python:__init__.py\n"
			"import globalPluginHandler\n"
			"import ui\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"    def script_helloWorld(self, gesture):\n"
			"        ui.message(\"Ola, mundo!\")\n"
			"```"
		)
		with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
			critic = Critic()
			result = critic.evaluate_two_stage("web_research", saida_errada)

		MockClient.return_value.chat.assert_not_called()
		assert result.verdict == Verdict.NEEDS_FIX
		assert result.stage == "spec"
		assert any("bloco de codigo" in issue.lower() for issue in result.issues)

	def test_texto_de_pesquisa_normal_nao_dispara_o_guard(
		self, fake_api_key, valid_critic_json_approved
	):
		"""Uma resposta legitima (markdown, com um pequeno exemplo de
		codigo inline como parte do formato) nao deve disparar o guard --
		so o marcador exato ```python:arquivo.py (formato de entrega de
		arquivo, exclusivo de code_generation) deve disparar."""
		saida_legitima = (
			"**Pacote:** requests\n"
			"**Versao estavel:** 2.31.0\n"
			"**Instalacao:** `pip install requests`\n"
			"**Exemplo minimo:**\n"
			"```python\n"
			"import requests\n"
			"requests.get('https://exemplo.com')\n"
			"```\n"
			"**Confianca:** Alta"
		)
		mock_resp = MagicMock()
		mock_resp.content = valid_critic_json_approved
		mock_resp.reasoning = None
		mock_resp.truncated = False

		with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
			MockClient.return_value.chat.return_value = mock_resp
			critic = Critic()
			critic.evaluate_two_stage("web_research", saida_legitima)

		MockClient.return_value.chat.assert_called()

	def test_bloco_python_em_outro_step_type_nao_dispara(
		self, fake_api_key, valid_critic_json_approved
	):
		"""O guard e especifico de web_research -- code_generation
		legitimamente devolve ```python:arquivo.py o tempo todo."""
		saida = "```python:globalPlugins/Addon/__init__.py\nimport ui\n```"
		mock_resp = MagicMock()
		mock_resp.content = valid_critic_json_approved
		mock_resp.reasoning = None
		mock_resp.truncated = False

		with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
			MockClient.return_value.chat.return_value = mock_resp
			critic = Critic()
			critic.evaluate_two_stage("code_generation", saida)

		MockClient.return_value.chat.assert_called()


class TestCriticSempreOpenCodeGo:
	"""
	critic.py 3.20.0: Critic roteado pra OpenCode Go (kimi-k2.6/glm-5.1),
	SEMPRE, independente do provider ativo escolhido pelo usuario -- pedido
	explicito do Felipe pra aproveitar prompt caching (confirmado ao vivo:
	Ollama Cloud nao tem, OpenCode Go tem). get_critic_model()/
	get_critic_fallback_model() nao devem mais seguir get_llm_provider()/
	get_llm_model() do usuario -- diferente de TODOS os outros sub-agentes
	(code_generation, web_research, etc.), que continuam 100% dependentes
	do provider ativo escolhido nas settings.
	"""

	def test_get_critic_model_e_opencode_go_kimi(self):
		from nvdastudio.ai.critic import get_critic_model
		assert get_critic_model() == "opencode_go::gpt-5.6-luna"

	def test_get_critic_fallback_model_e_opencode_go_glm(self):
		from nvdastudio.ai.critic import get_critic_fallback_model
		assert get_critic_fallback_model() == "opencode_go::kimi-k2.6"

	def test_fallback_e_diferente_do_primario(self):
		"""Fallback precisa ser um modelo REALMENTE diferente do primario --
		senao a escalacao de 3.15.0 (resposta vazia/cortada) vira uma
		segunda chamada identica, inutil."""
		from nvdastudio.ai.critic import get_critic_model, get_critic_fallback_model
		assert get_critic_model() != get_critic_fallback_model()

	def test_ignora_provider_ativo_do_usuario(self, fake_api_key):
		"""Mesmo com o usuario tendo escolhido explicitamente 'gemini' (ou
		qualquer outro provider) como ativo nas settings, o Critic continua
		usando OpenCode Go -- essa e a mudanca de comportamento pedida:
		SO o Critic ignora o provider ativo, nenhum outro sub-agente."""
		from nvdastudio.ai.critic import get_critic_model, get_critic_fallback_model
		with patch("nvdastudio.gui.settings_panel.get_llm_provider", return_value="gemini"), \
			 patch("nvdastudio.gui.settings_panel.get_llm_model", return_value="gemini-3.1-pro-preview"):
			assert get_critic_model() == "opencode_go::gpt-5.6-luna"
			assert get_critic_fallback_model() == "opencode_go::kimi-k2.6"

	def test_create_llm_client_recebe_model_id_tagueado_com_provider(
		self, fake_api_key, valid_critic_json_approved
	):
		"""evaluate_two_stage() deve passar o model_id no formato
		'opencode_go::<modelo>' pra create_llm_client() -- e esse prefixo
		que faz llm_factory.py forcar o provider, ignorando o provider
		ativo do usuario (mesma convencao ja usada por
		model_router.py::select_model_and_provider() pra escalacao
		cross-provider)."""
		mock_resp = MagicMock()
		mock_resp.content = valid_critic_json_approved
		mock_resp.reasoning = None
		mock_resp.truncated = False

		with patch("nvdastudio.ai.critic.create_llm_client") as MockClient:
			MockClient.return_value.chat.return_value = mock_resp
			critic = Critic()
			critic.evaluate_two_stage("code_generation", "```python:__init__.py\nimport ui\n```")

		chamado_com = [call.kwargs.get("model_id", call.args[0] if call.args else None)
					   for call in MockClient.call_args_list]
		assert any(m == "opencode_go::gpt-5.6-luna" for m in chamado_com), (
			f"create_llm_client deveria ser chamado com model_id='opencode_go::gpt-5.6-luna' "
			f"pelo menos uma vez. Chamadas reais: {chamado_com}"
		)
