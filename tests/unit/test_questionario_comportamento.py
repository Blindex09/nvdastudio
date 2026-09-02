# ===========================================================================
# 1. Clarifier v1.3.0 — Q10.1c + Q14.5
# ===========================================================================

class TestClarifierQ10Q14:

    def test_versao_clarifier(self):
        from addon.globalPlugins.nvdastudio.ai.clarifier import MODULE_VERSION
        assert MODULE_VERSION == "1.7.0"

    def test_clarification_result_tem_forbidden(self):
        from addon.globalPlugins.nvdastudio.ai.clarifier import ClarificationResult
        r = ClarificationResult(needs_clarification=False, questions=[], forbidden=True,
                                refusal_reason="Motivo teste")
        assert r.forbidden is True
        assert r.refusal_reason == "Motivo teste"

    def test_clarification_result_forbidden_default_false(self):
        from addon.globalPlugins.nvdastudio.ai.clarifier import ClarificationResult
        r = ClarificationResult(needs_clarification=False, questions=[])
        assert r.forbidden is False
        assert r.refusal_reason == ""

    def test_clarification_result_tem_extra_features_planned(self):
        from addon.globalPlugins.nvdastudio.ai.clarifier import ClarificationResult
        r = ClarificationResult(needs_clarification=True, questions=["q1"],
                                extra_features_planned=["config de hora"])
        assert r.extra_features_planned == ["config de hora"]

    def test_extra_features_default_vazio(self):
        from addon.globalPlugins.nvdastudio.ai.clarifier import ClarificationResult
        r = ClarificationResult(needs_clarification=False, questions=[])
        assert r.extra_features_planned == []

    def test_system_menciona_forbidden(self):
        from addon.globalPlugins.nvdastudio.ai.clarifier import _CLARIFIER_SYSTEM
        assert "forbidden" in _CLARIFIER_SYSTEM

    def test_system_menciona_refusal_reason(self):
        from addon.globalPlugins.nvdastudio.ai.clarifier import _CLARIFIER_SYSTEM
        assert "refusal_reason" in _CLARIFIER_SYSTEM

    def test_system_menciona_coleta_dados(self):
        from addon.globalPlugins.nvdastudio.ai.clarifier import _CLARIFIER_SYSTEM
        assert "coleta" in _CLARIFIER_SYSTEM.lower() or "dados" in _CLARIFIER_SYSTEM.lower()

    def test_system_menciona_extra_features_planned(self):
        from addon.globalPlugins.nvdastudio.ai.clarifier import _CLARIFIER_SYSTEM
        assert "extra_features_planned" in _CLARIFIER_SYSTEM

    def test_system_menciona_confirmacao_extras(self):
        from addon.globalPlugins.nvdastudio.ai.clarifier import _CLARIFIER_SYSTEM
        assert "confirmacao" in _CLARIFIER_SYSTEM.lower() or "voce quer" in _CLARIFIER_SYSTEM.lower()

    def test_analyze_query_retorna_forbidden_quando_json_forbidden_true(self):
        from unittest.mock import MagicMock, patch
        from addon.globalPlugins.nvdastudio.ai.clarifier import analyze_query
        mock_resp = MagicMock()
        mock_resp.content = '{"needs_clarification": false, "user_level": "iniciante", "questions": [], "forbidden": true, "refusal_reason": "Addon de keylogger nao permitido.", "extra_features_planned": []}'
        with patch("addon.globalPlugins.nvdastudio.ai.clarifier.call_with_structured_output") as MockClient:
            MockClient.return_value = mock_resp
            result = analyze_query("quero um keylogger")
        assert result.forbidden is True
        assert "keylogger" in result.refusal_reason.lower() or "nao permitido" in result.refusal_reason.lower()

    def test_analyze_query_forbidden_nao_retorna_perguntas(self):
        from unittest.mock import MagicMock, patch
        from addon.globalPlugins.nvdastudio.ai.clarifier import analyze_query
        mock_resp = MagicMock()
        mock_resp.content = '{"needs_clarification": false, "user_level": "iniciante", "questions": [], "forbidden": true, "refusal_reason": "Nao permitido.", "extra_features_planned": []}'
        with patch("addon.globalPlugins.nvdastudio.ai.clarifier.call_with_structured_output") as MockClient:
            MockClient.return_value = mock_resp
            result = analyze_query("pedido perigoso")
        assert result.needs_clarification is False
        assert result.questions == []

    def test_analyze_query_retorna_extra_features(self):
        from unittest.mock import MagicMock, patch
        from addon.globalPlugins.nvdastudio.ai.clarifier import analyze_query
        mock_resp = MagicMock()
        mock_resp.content = '{"needs_clarification": true, "user_level": "iniciante", "questions": ["Voce quer config de hora?"], "forbidden": false, "refusal_reason": "", "extra_features_planned": ["config 12h/24h"]}'
        with patch("addon.globalPlugins.nvdastudio.ai.clarifier.call_with_structured_output") as MockClient:
            MockClient.return_value = mock_resp
            result = analyze_query("anuncia a hora")
        assert result.extra_features_planned == ["config 12h/24h"]

    def test_system_nao_tem_em_dash(self):
        from addon.globalPlugins.nvdastudio.ai.clarifier import _CLARIFIER_SYSTEM
        assert "\u2014" not in _CLARIFIER_SYSTEM


# ===========================================================================
# 2. doc_generator v1.4.0 — Q13.3: idioma do NVDA
# ===========================================================================

class TestDocGeneratorQ13:

    def test_versao_doc_generator(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import MODULE_VERSION
        assert MODULE_VERSION == "1.10.0"

    def test_system_menciona_nvda_locale(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        assert "NVDA_LOCALE" in _SYSTEM

    def test_system_menciona_idioma_principal(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        assert "idioma principal" in _SYSTEM.lower() or "locale" in _SYSTEM.lower()

    def test_system_menciona_fallback_en(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        assert "fallback" in _SYSTEM.lower() or "doc/en" in _SYSTEM

    def test_system_menciona_pt_br_fallback(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        assert "pt_BR" in _SYSTEM or "pt-BR" in _SYSTEM


# ===========================================================================
# 3. settings_panel v4.3.0 — Q8.2c: idioma das mensagens
# ===========================================================================

class TestSettingsPanelQ8:

    def test_versao_settings_panel(self):
        from addon.globalPlugins.nvdastudio.gui.settings_panel import MODULE_VERSION
        assert MODULE_VERSION == "6.9.0"

    def test_config_key_language_definido(self):
        from addon.globalPlugins.nvdastudio.gui.settings_panel import CONFIG_KEY_LANGUAGE
        assert CONFIG_KEY_LANGUAGE == "uiLanguage"

    def test_languages_definidos(self):
        from addon.globalPlugins.nvdastudio.gui.settings_panel import _LANGUAGES
        assert len(_LANGUAGES) >= 3
        codes = [c for _, c in _LANGUAGES]
        assert "pt_BR" in codes
        assert "en" in codes
        assert "es" in codes

    def test_language_codes_definidos(self):
        from addon.globalPlugins.nvdastudio.gui.settings_panel import _LANGUAGE_CODES
        assert "pt_BR" in _LANGUAGE_CODES
        assert "en" in _LANGUAGE_CODES

    def test_get_ui_language_existe(self):
        from addon.globalPlugins.nvdastudio.gui.settings_panel import get_ui_language
        assert callable(get_ui_language)

    def test_get_ui_language_fallback_pt_br(self):
        from unittest.mock import patch
        from addon.globalPlugins.nvdastudio.gui.settings_panel import get_ui_language
        with patch("addon.globalPlugins.nvdastudio.gui.settings_panel.config") as mock_cfg:
            mock_cfg.conf = {"nvdastudio": {"uiLanguage": "xx_INVALIDO"}}
            result = get_ui_language()
        assert result == "pt_BR"

    def test_get_ui_language_retorna_en(self):
        from unittest.mock import patch
        from addon.globalPlugins.nvdastudio.gui.settings_panel import get_ui_language
        with patch("addon.globalPlugins.nvdastudio.gui.settings_panel.config") as mock_cfg:
            mock_cfg.conf = {"nvdastudio": {"uiLanguage": "en"}}
            result = get_ui_language()
        assert result == "en"


# ===========================================================================
# 4. studio_dialog v5.9.0 — Q5.6: instrucoes.txt + Q13.3: locale injetado
# ===========================================================================

class TestStudioDialogQ5Q13:

    def test_versao_studio_dialog(self):
        from addon.globalPlugins.nvdastudio.gui.studio_dialog import MODULE_VERSION
        assert MODULE_VERSION == "5.49.0"

    def test_save_instrucoes_txt_existe(self):
        import addon.globalPlugins.nvdastudio.gui.studio_dialog as sd
        assert hasattr(sd, "_save_instrucoes_txt")
        assert callable(sd._save_instrucoes_txt)

    def test_save_instrucoes_txt_gera_arquivo(self):
        import tempfile
        import os
        from addon.globalPlugins.nvdastudio.gui.studio_dialog import _save_instrucoes_txt
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _save_instrucoes_txt("MeuAddon", tmpdir, "MeuAddon.nvda-addon")
            assert result != ""
            assert os.path.isfile(result)
            content = open(result, encoding="utf-8").read()
            assert "MeuAddon" in content
            assert "instalar" in content.lower() or "Instalar" in content

    def test_save_instrucoes_txt_nome_correto(self):
        import tempfile
        import os
        from addon.globalPlugins.nvdastudio.gui.studio_dialog import _save_instrucoes_txt
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _save_instrucoes_txt("TranscriborIA", tmpdir, "TranscriborIA.nvda-addon")
            assert "instrucoes_TranscriborIA" in os.path.basename(result)

    def test_save_instrucoes_txt_menciona_nvdastudio(self):
        import tempfile
        from addon.globalPlugins.nvdastudio.gui.studio_dialog import _save_instrucoes_txt
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _save_instrucoes_txt("Teste", tmpdir, "Teste.nvda-addon")
            content = open(result, encoding="utf-8").read()
            assert "NVDAStudio" in content

    def test_save_instrucoes_txt_sem_em_dash(self):
        import tempfile
        from addon.globalPlugins.nvdastudio.gui.studio_dialog import _save_instrucoes_txt
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _save_instrucoes_txt("Teste", tmpdir, "Teste.nvda-addon")
            content = open(result, encoding="utf-8").read()
            assert "\u2014" not in content  # Regra 11: cp1252, sem em-dash

    def test_get_nvda_locale_existe(self):
        import addon.globalPlugins.nvdastudio.gui.studio_dialog as sd
        assert hasattr(sd, "_get_nvda_locale")
        assert callable(sd._get_nvda_locale)

    def test_get_nvda_locale_fallback(self):
        from addon.globalPlugins.nvdastudio.gui.studio_dialog import _get_nvda_locale
        locale = _get_nvda_locale()
        assert isinstance(locale, str)
        assert len(locale) >= 2

    def test_get_nvda_locale_formato_valido(self):
        from addon.globalPlugins.nvdastudio.gui.studio_dialog import _get_nvda_locale
        locale = _get_nvda_locale()
        assert "_" in locale or len(locale) == 2 or len(locale) <= 6
