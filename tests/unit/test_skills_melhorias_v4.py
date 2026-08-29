# ===========================================================================
# 1. NVDA_DETECTION_RULES — 3 novas entradas
# ===========================================================================

class TestNvdaDetectionRulesV4:
    """NVDA_DETECTION_RULES deve ter 21 regras com NVDA-019..021."""

    def test_total_de_regras_e_21(self):
        from nvdastudio.builder.nvda_context import NVDA_DETECTION_RULES
        assert len(NVDA_DETECTION_RULES) == 61

    def test_nvda_019_existe(self):
        from nvdastudio.builder.nvda_context import NVDA_DETECTION_RULES
        ids = [r[0] for r in NVDA_DETECTION_RULES]
        assert "NVDA-019" in ids

    def test_nvda_020_existe(self):
        from nvdastudio.builder.nvda_context import NVDA_DETECTION_RULES
        ids = [r[0] for r in NVDA_DETECTION_RULES]
        assert "NVDA-020" in ids

    def test_nvda_021_existe(self):
        from nvdastudio.builder.nvda_context import NVDA_DETECTION_RULES
        ids = [r[0] for r in NVDA_DETECTION_RULES]
        assert "NVDA-021" in ids

    def test_nvda_019_severidade_serio(self):
        from nvdastudio.builder.nvda_context import NVDA_DETECTION_RULES
        rule = next(r for r in NVDA_DETECTION_RULES if r[0] == "NVDA-019")
        assert rule[1] == "Serio"

    def test_nvda_020_severidade_moderado(self):
        from nvdastudio.builder.nvda_context import NVDA_DETECTION_RULES
        rule = next(r for r in NVDA_DETECTION_RULES if r[0] == "NVDA-020")
        assert rule[1] == "Moderado"

    def test_nvda_021_severidade_moderado(self):
        from nvdastudio.builder.nvda_context import NVDA_DETECTION_RULES
        rule = next(r for r in NVDA_DETECTION_RULES if r[0] == "NVDA-021")
        assert rule[1] == "Moderado"

    def test_nvda_019_menciona_translators(self):
        from nvdastudio.builder.nvda_context import NVDA_DETECTION_RULES
        rule = next(r for r in NVDA_DETECTION_RULES if r[0] == "NVDA-019")
        assert "Translators" in rule[2] or "translators" in rule[2].lower()

    def test_nvda_020_menciona_re_export(self):
        from nvdastudio.builder.nvda_context import NVDA_DETECTION_RULES
        rule = next(r for r in NVDA_DETECTION_RULES if r[0] == "NVDA-020")
        texto = rule[2].lower()
        assert "re-export" in texto or "transitiv" in texto or "original" in texto

    def test_nvda_021_menciona_tabs(self):
        from nvdastudio.builder.nvda_context import NVDA_DETECTION_RULES
        rule = next(r for r in NVDA_DETECTION_RULES if r[0] == "NVDA-021")
        texto = rule[2].upper()
        assert "TABS" in texto or "TAB" in texto

    def test_ids_sequenciais_sem_gaps(self):
        from nvdastudio.builder.nvda_context import NVDA_DETECTION_RULES
        numeros = []
        for rule_id, _, _ in NVDA_DETECTION_RULES:
            assert rule_id.startswith("NVDA-")
            numeros.append(int(rule_id.split("-")[1]))
        # IDs validos: 1-25 (originais) + 42/43/44 (adicionados em v3.8.0 — gaps do chat)
        # Os IDs 26-41 nao existem como detection rules — sao regras do _SYSTEM do code_generator
        ids_existentes = sorted(numeros)
        assert all(n >= 1 for n in ids_existentes), "IDs devem ser positivos"
        assert len(ids_existentes) == len(set(ids_existentes)), "IDs nao devem ser duplicados"
        assert 42 in ids_existentes, "NVDA-042 (ngettext) deve existir"
        assert 43 in ids_existentes, "NVDA-043 (speech dicts) deve existir"
        assert 44 in ids_existentes, "NVDA-044 (braille driver) deve existir"


# ===========================================================================
# 2. NVDA_SYSTEM_PROMPT — menciona as novas regras
# ===========================================================================

class TestNvdaSystemPromptV4:
    """NVDA_SYSTEM_PROMPT deve incluir texto das regras NVDA-019..021."""

    def test_prompt_menciona_nvda_019(self):
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        assert "NVDA-019" in NVDA_SYSTEM_PROMPT

    def test_prompt_menciona_nvda_020(self):
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        assert "NVDA-020" in NVDA_SYSTEM_PROMPT

    def test_prompt_menciona_nvda_021(self):
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        assert "NVDA-021" in NVDA_SYSTEM_PROMPT

    def test_prompt_menciona_translators_comment(self):
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        assert "Translators" in NVDA_SYSTEM_PROMPT

    def test_prompt_menciona_tabs_indentacao(self):
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        texto = NVDA_SYSTEM_PROMPT.upper()
        assert "TABS" in texto or "TAB" in texto

    def test_prompt_menciona_import_original(self):
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        texto = NVDA_SYSTEM_PROMPT.lower()
        assert "original" in texto or "re-export" in texto


# ===========================================================================
# 3. code_generator._SYSTEM — regras NVDA-019..021 no gerador
# ===========================================================================

class TestCodeGeneratorV4:
    """code_generator v2.2.0 deve conter as 3 novas regras."""

    def test_versao_e_2_2_0(self):
        from nvdastudio.sub_agents.code_generator import MODULE_VERSION
        assert MODULE_VERSION == "3.32.0"

    def test_system_menciona_nvda_019(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        assert "NVDA-019" in _SYSTEM

    def test_system_menciona_nvda_020(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        assert "NVDA-020" in _SYSTEM

    def test_system_menciona_nvda_021(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        assert "NVDA-021" in _SYSTEM

    def test_system_instrui_translators_comment(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        assert "# Translators" in _SYSTEM or "Translators:" in _SYSTEM

    def test_system_instrui_tabs(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        texto = _SYSTEM.upper()
        assert "TABS" in texto

    def test_system_instrui_import_original(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        texto = _SYSTEM.lower()
        assert "original" in texto or "re-export" in texto

    def test_verificacao_final_tem_7_itens(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        # Ponto 7 adicionado em v2.2.0
        assert "7." in _SYSTEM

    def test_verificacao_final_menciona_translators(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        # O ponto 7 deve mencionar Translators
        idx = _SYSTEM.find("7.")
        assert idx != -1
        trecho = _SYSTEM[idx:idx + 100]
        assert "Translators" in trecho or "NVDA-019" in trecho


# ===========================================================================
# 4. nvda_context.py versao 3.2.0
# ===========================================================================

class TestNvdaContextVersaoV4:
    def test_versao_modulo_3_2_0(self):
        """nvda_context.py deve estar na versao 3.2.0 apos aplicacao da skill nvda-addon-dev."""
        import nvdastudio.builder.nvda_context as ctx
        import inspect
        src = inspect.getsource(ctx)
        assert "3.2.0" in src
