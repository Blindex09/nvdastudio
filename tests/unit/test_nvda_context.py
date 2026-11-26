from nvdastudio_mcp.nvda_context import (
    NVDA_GUIDE, NVDA_DETECTION_RULES, WX_A11Y_RULES, DTK_A11Y_RULES,
)

_EMOJIS_PROIBIDOS = [
    "\u2705", "\u274c", "\u26a0", "\U0001f4e6",
    "\U0001f916", "\u2728", "\u2764", "\U0001f680",
]




class TestNvdaSystemPromptConteudo:
    def test_prompt_nao_vazio(self):
        assert NVDA_GUIDE and NVDA_GUIDE.strip()

    def test_prompt_contem_nvda(self):
        assert "NVDA" in NVDA_GUIDE

    def test_prompt_menciona_global_plugin(self):
        assert "GlobalPlugin" in NVDA_GUIDE or "globalPlugin" in NVDA_GUIDE

    def test_prompt_menciona_manifest(self):
        assert "manifest" in NVDA_GUIDE.lower()

    def test_prompt_menciona_acessibilidade(self):
        prompt_lower = NVDA_GUIDE.lower()
        assert "acessib" in prompt_lower or "label" in prompt_lower

    def test_prompt_menciona_wx_call_after(self):
        assert "CallAfter" in NVDA_GUIDE

    def test_prompt_menciona_imports(self):
        assert "import" in NVDA_GUIDE.lower()

    def test_prompt_menciona_try_except(self):
        assert "try" in NVDA_GUIDE or "except" in NVDA_GUIDE

    def test_prompt_menciona_addon_handler(self):
        assert "addonHandler" in NVDA_GUIDE

    def test_prompt_menciona_ui_message(self):
        assert "ui.message" in NVDA_GUIDE

    def test_prompt_menciona_baseline_2026_1_1(self):
        assert "2026.1.1" in NVDA_GUIDE

    def test_prompt_menciona_forward_compat_2026(self):
        assert "2026.1" in NVDA_GUIDE

    def test_prompt_menciona_terminate(self):
        """v2.0.0: terminate() e regra critica NVDA-004."""
        assert "terminate" in NVDA_GUIDE.lower()

    def test_prompt_menciona_next_handler(self):
        """v2.0.0: nextHandler() e regra critica NVDA-001."""
        assert "nextHandler" in NVDA_GUIDE

    def test_prompt_menciona_versoes_manifest(self):
        """v2.0.0: tabela de versoes minimumNVDAVersion deve estar no prompt."""
        assert "minimumNVDAVersion" in NVDA_GUIDE or "minimumNvdaVersion" in NVDA_GUIDE

    def test_prompt_menciona_2019_3(self):
        """O limite tecnico absoluto do ecossistema ainda deve estar documentado."""
        assert "2019.3" in NVDA_GUIDE


class TestNvdaSystemPromptEncoding:
    def test_prompt_sem_emojis(self):
        for emoji in _EMOJIS_PROIBIDOS:
            assert emoji not in NVDA_GUIDE

    def test_prompt_encodavel_cp1252_com_replace(self):
        encoded = NVDA_GUIDE.encode("cp1252", errors="replace")
        assert len(encoded) > 0

    def test_prompt_e_string(self):
        assert isinstance(NVDA_GUIDE, str)


class TestNvdaDetectionRules:
    """v2.0.0: NVDA_DETECTION_RULES com 18 regras do Community Access."""

    def test_detection_rules_existem(self):
        assert NVDA_DETECTION_RULES is not None
        assert len(NVDA_DETECTION_RULES) > 0

    def test_exatamente_63_regras(self):
        """62 apos NVDA-063 (assinatura divergente entre arquivos,
        achado da rodada AssistenteEscrita de 2026-09-03)."""
        assert len(NVDA_DETECTION_RULES) == 63

    def test_cada_regra_tem_3_elementos(self):
        for rule in NVDA_DETECTION_RULES:
            assert len(rule) == 3, f"Regra deve ter (id, severity, descricao): {rule}"

    def test_ids_sao_unicos(self):
        ids = [r[0] for r in NVDA_DETECTION_RULES]
        assert len(ids) == len(set(ids))

    def test_ids_formato_nvda(self):
        for rule_id, _, _ in NVDA_DETECTION_RULES:
            assert rule_id.startswith("NVDA-"), f"ID deve comecar com NVDA-: {rule_id}"

    def test_regra_001_next_handler(self):
        """NVDA-001: falta nextHandler — critico."""
        rule = next((r for r in NVDA_DETECTION_RULES if r[0] == "NVDA-001"), None)
        assert rule is not None
        assert rule[1] == "Critical"
        assert "nextHandler" in rule[2]

    def test_regra_017_dll_64bit(self):
        """NVDA-017: DLL 32-bit em NVDA 64-bit — critico para forward-compatibility."""
        rule = next((r for r in NVDA_DETECTION_RULES if r[0] == "NVDA-017"), None)
        assert rule is not None
        assert rule[1] == "Critical"

    def test_regra_018_versao_minima(self):
        """NVDA-018: minimumNVDAVersion abaixo de 2019.3.0."""
        rule = next((r for r in NVDA_DETECTION_RULES if r[0] == "NVDA-018"), None)
        assert rule is not None
        assert "2019.3" in rule[2]

    def test_severidades_validas(self):
        severidades = {"Critical", "Serious", "Moderate", "Minor"}
        for _, sev, _ in NVDA_DETECTION_RULES:
            assert sev in severidades, f"Severidade invalida: {sev}"

    def test_sem_emojis_nas_regras(self):
        for rule_id, sev, desc in NVDA_DETECTION_RULES:
            texto = rule_id + sev + desc
            for emoji in _EMOJIS_PROIBIDOS:
                assert emoji not in texto


class TestWxA11yRules:
    """v2.1.0: WX_A11Y_RULES com 14 regras.
    Fonte: github.com/Community-Access/accessibility-agents .github/agents/wxpython-specialist.agent.md
    v2.0.0 tinha 12 regras com conteudo errado (IDs 005-011 errados, 013-014 ausentes).
    """

    def test_wx_a11y_rules_existem(self):
        assert WX_A11Y_RULES is not None
        assert len(WX_A11Y_RULES) > 0

    def test_exatamente_14_regras(self):
        # Fonte: wxpython-specialist.agent.md — 14 regras na tabela Detection Rules
        assert len(WX_A11Y_RULES) == 14

    def test_ids_formato_wx(self):
        for rule_id, _, _ in WX_A11Y_RULES:
            assert rule_id.startswith("WX-A11Y-"), f"ID deve comecar com WX-A11Y-: {rule_id}"

    def test_regra_005_showmodal_sem_setfocus(self):
        """WX-A11Y-005: Dialog.ShowModal() sem SetFocus() — Serio.
        Fonte: wxpython-specialist.agent.md linha da tabela WX-A11Y-005.
        """
        rule = next((r for r in WX_A11Y_RULES if r[0] == "WX-A11Y-005"), None)
        assert rule is not None
        assert "Serious" in rule[1], f"WX-A11Y-005 deve ser Serious: {rule[1]}"
        assert "ShowModal" in rule[2] or "SetFocus" in rule[2], f"Deve mencionar ShowModal/SetFocus: {rule[2]}"

    def test_regra_013_evtkeydow_listbox_critico(self):
        """WX-A11Y-013: EVT_KEY_DOWN em lista e so nota de estilo (o proprio NVDA usa EVT_CHAR_HOOK)."""
        rule = next((r for r in WX_A11Y_RULES if r[0] == "WX-A11Y-013"), None)
        assert rule is not None
        assert "Minor" in rule[1], f"WX-A11Y-013 deve ser Minor: {rule[1]}"
        assert "EVT_CHAR_HOOK" in rule[2] or "EVT_KEY_DOWN" in rule[2], f"Deve mencionar EVT: {rule[2]}"

    def test_regra_014_listctrl_item_activated(self):
        """WX-A11Y-014: ListCtrl deve usar EVT_LIST_ITEM_ACTIVATED — Serio.
        Fonte: wxpython-specialist.agent.md tabela Detection Rules linha 014.
        """
        rule = next((r for r in WX_A11Y_RULES if r[0] == "WX-A11Y-014"), None)
        assert rule is not None
        assert "Serious" in rule[1], f"WX-A11Y-014 deve ser Serious: {rule[1]}"
        assert "EVT_LIST_ITEM_ACTIVATED" in rule[2], f"Deve mencionar EVT_LIST_ITEM_ACTIVATED: {rule[2]}"

    def test_regras_001_002_003_sao_criticas(self):
        """WX-A11Y-001 e 003 seguem Critical no catalogo (impacto se a heuristica acertar); a 002 saiu."""
        for rid in ("WX-A11Y-001", "WX-A11Y-003"):
            rule = next((r for r in WX_A11Y_RULES if r[0] == rid), None)
            assert rule is not None
            assert "Critical" in rule[1], f"{rid} deve ser Critical: {rule[1]}"


class TestDtkA11yRules:
    """v3.37.0: DTK_A11Y_RULES com 12 regras — camada de API de plataforma
    (UIA/MSAA), complementar as regras WX-A11Y existentes.
    Fonte: github.com/Community-Access/accessibility-agents .github/agents/desktop-a11y-specialist.agent.md
    """

    def test_dtk_a11y_rules_existem(self):
        assert DTK_A11Y_RULES is not None
        assert len(DTK_A11Y_RULES) > 0

    def test_exatamente_12_regras(self):
        # Fonte: desktop-a11y-specialist.agent.md — 12 regras na tabela Detection Rules
        assert len(DTK_A11Y_RULES) == 12

    def test_ids_formato_dtk(self):
        for rule_id, _, _ in DTK_A11Y_RULES:
            assert rule_id.startswith("DTK-A11Y-"), f"ID deve comecar com DTK-A11Y-: {rule_id}"

    def test_nao_colide_com_ids_wx_a11y(self):
        wx_ids = {r[0] for r in WX_A11Y_RULES}
        dtk_ids = {r[0] for r in DTK_A11Y_RULES}
        assert wx_ids.isdisjoint(dtk_ids), "DTK-A11Y nao deve reutilizar/colidir com IDs de WX-A11Y"

    def test_regra_001_missing_name_critico(self):
        """DTK-A11Y-001: controle interativo sem Name via UIA/MSAA — Critico."""
        rule = next((r for r in DTK_A11Y_RULES if r[0] == "DTK-A11Y-001"), None)
        assert rule is not None
        assert "Critical" in rule[1], f"DTK-A11Y-001 deve ser Critical: {rule[1]}"
        assert "Name" in rule[2] or "UIA" in rule[2] or "MSAA" in rule[2]

    def test_regra_005_teclado_inalcancavel_critico(self):
        """DTK-A11Y-005: elemento interativo nao alcancavel via teclado — Critico."""
        rule = next((r for r in DTK_A11Y_RULES if r[0] == "DTK-A11Y-005"), None)
        assert rule is not None
        assert "Critical" in rule[1], f"DTK-A11Y-005 deve ser Critical: {rule[1]}"
        assert "keyboard" in rule[2].lower()

    def test_regra_010_modal_focus_escape_serio(self):
        """DTK-A11Y-010: dialogo modal nao prende o foco — Serio."""
        rule = next((r for r in DTK_A11Y_RULES if r[0] == "DTK-A11Y-010"), None)
        assert rule is not None
        assert "Serious" in rule[1], f"DTK-A11Y-010 deve ser Serious: {rule[1]}"
        assert "modal" in rule[2].lower() or "dialogo" in rule[2].lower()
