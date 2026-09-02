from addon.globalPlugins.nvdastudio.ai.critic import (
    _CRITIC_QUALITY_SYSTEM,
    _CRITIC_SPEC_SYSTEM,
    MODULE_VERSION,
)


class TestCriticVersao:
    def test_versao_e_2_9_0(self):
        assert MODULE_VERSION == "3.23.0"


class TestNvdaRegrasNovas:
    """NVDA-006..016 devem estar no quality system."""

    def test_nvda_006_monkey_patching_presente(self):
        assert "NVDA-006" in _CRITIC_QUALITY_SYSTEM
        assert "monkey" in _CRITIC_QUALITY_SYSTEM.lower()

    def test_nvda_007_gestures_dict_presente(self):
        assert "NVDA-007" in _CRITIC_QUALITY_SYSTEM
        assert "__gestures" in _CRITIC_QUALITY_SYSTEM or "gestures" in _CRITIC_QUALITY_SYSTEM.lower()

    def test_nvda_008_sem_description_presente(self):
        assert "NVDA-008" in _CRITIC_QUALITY_SYSTEM
        assert "description" in _CRITIC_QUALITY_SYSTEM.lower()

    def test_nvda_009_atalho_conflitante_presente(self):
        assert "NVDA-009" in _CRITIC_QUALITY_SYSTEM
        assert "conflita" in _CRITIC_QUALITY_SYSTEM.lower() or "atalho" in _CRITIC_QUALITY_SYSTEM.lower()

    def test_nvda_011_sem_check_presente(self):
        assert "NVDA-011" in _CRITIC_QUALITY_SYSTEM
        assert "check()" in _CRITIC_QUALITY_SYSTEM

    def test_nvda_012_bare_except_presente(self):
        assert "NVDA-012" in _CRITIC_QUALITY_SYSTEM
        assert "except" in _CRITIC_QUALITY_SYSTEM.lower()

    def test_nvda_015_config_spec_presente(self):
        assert "NVDA-015" in _CRITIC_QUALITY_SYSTEM
        assert "config.conf" in _CRITIC_QUALITY_SYSTEM.lower() or "config" in _CRITIC_QUALITY_SYSTEM.lower()

    def test_nvda_016_secure_mode_presente(self):
        assert "NVDA-016" in _CRITIC_QUALITY_SYSTEM
        assert "secure" in _CRITIC_QUALITY_SYSTEM.lower() or "shouldWriteToDisk" in _CRITIC_QUALITY_SYSTEM

    def test_nvda_006_tem_exemplo_errado_e_correto(self):
        """Regra 006 deve ter exemplo de monkey-patch e alternativa."""
        assert "extension" in _CRITIC_QUALITY_SYSTEM.lower() or "event" in _CRITIC_QUALITY_SYSTEM.lower()

    def test_nvda_007_tem_exemplo_decorator(self):
        """Regra 007 deve mencionar @script como alternativa correta."""
        assert "@script" in _CRITIC_QUALITY_SYSTEM


class TestWxA11yRegrasNovas:
    """WX-A11Y-006, 009, 011, 012 devem estar no quality system."""

    def test_wx_a11y_006_bitmap_sem_nome_presente(self):
        assert "WX-A11Y-006" in _CRITIC_QUALITY_SYSTEM
        assert "bitmap" in _CRITIC_QUALITY_SYSTEM.lower() or "StaticBitmap" in _CRITIC_QUALITY_SYSTEM

    def test_wx_a11y_009_custom_panel_presente(self):
        assert "WX-A11Y-009" in _CRITIC_QUALITY_SYSTEM
        assert "Accessible" in _CRITIC_QUALITY_SYSTEM or "accessible" in _CRITIC_QUALITY_SYSTEM.lower()

    def test_wx_a11y_011_virtual_list_presente(self):
        assert "WX-A11Y-011" in _CRITIC_QUALITY_SYSTEM
        assert "GetItemText" in _CRITIC_QUALITY_SYSTEM or "virtual" in _CRITIC_QUALITY_SYSTEM.lower()

    def test_wx_a11y_012_menu_acelerador_presente(self):
        assert "WX-A11Y-012" in _CRITIC_QUALITY_SYSTEM
        assert "acelerador" in _CRITIC_QUALITY_SYSTEM.lower() or "menu" in _CRITIC_QUALITY_SYSTEM.lower()

    def test_regras_013_014_ainda_presentes(self):
        """Regras anteriores não devem ter sido removidas."""
        assert "WX-A11Y-013" in _CRITIC_QUALITY_SYSTEM
        assert "WX-A11Y-014" in _CRITIC_QUALITY_SYSTEM


class TestCriticSystemCombinado:
    def test_total_nvda_rules_no_quality(self):
        """Quality system deve conter pelo menos NVDA-001 a NVDA-018."""
        ids_esperados = [f"NVDA-0{str(i).zfill(2)}" for i in range(1, 10)]
        ids_esperados += [f"NVDA-0{i}" for i in range(10, 19)]
        presentes = [rid for rid in ids_esperados if rid in _CRITIC_QUALITY_SYSTEM]
        # Pelo menos 14 dos 18 IDs devem estar no quality system
        assert len(presentes) >= 14, f"Apenas {len(presentes)} de 18 NVDA rules presentes"

    def test_total_wx_rules_no_quality(self):
        """Quality system deve conter pelo menos WX-A11Y-001 a WX-A11Y-014."""
        ids = [f"WX-A11Y-0{str(i).zfill(2)}" for i in range(1, 15)]
        presentes = [rid for rid in ids if rid in _CRITIC_QUALITY_SYSTEM]
        assert len(presentes) >= 9, f"Apenas {len(presentes)} de 14 WX-A11Y rules presentes"


class TestCriticEspecDesignReviewDocumentation:
    """I4: _CRITIC_SPEC_SYSTEM deve ter criterios objetivos para design_review e documentation."""

    def test_spec_system_contem_design_review(self):
        assert "design_review:" in _CRITIC_SPEC_SYSTEM, (
            "I4: _CRITIC_SPEC_SYSTEM deve ter bloco 'design_review:' com criterios objetivos"
        )

    def test_spec_system_design_review_tem_tres_secoes(self):
        """Criterio de design_review exige Challenger, Guardian e User Advocate."""
        assert "Challenger" in _CRITIC_SPEC_SYSTEM
        assert "Guardian" in _CRITIC_SPEC_SYSTEM
        assert "User Advocate" in _CRITIC_SPEC_SYSTEM

    def test_spec_system_contem_documentation(self):
        assert "documentation:" in _CRITIC_SPEC_SYSTEM, (
            "I4: _CRITIC_SPEC_SYSTEM deve ter bloco 'documentation:' com criterios objetivos"
        )

    def test_spec_system_documentation_menciona_html(self):
        """Criterio de documentation deve exigir estrutura HTML."""
        assert "html" in _CRITIC_SPEC_SYSTEM.lower() or "HTML" in _CRITIC_SPEC_SYSTEM

    def test_design_review_tem_aprovado_corrigir_rejeitar(self):
        """Criterios de design_review devem cobrir todos os 3 veredictos."""
        dr_start = _CRITIC_SPEC_SYSTEM.find("design_review:")
        doc_start = _CRITIC_SPEC_SYSTEM.find("documentation:")
        # Bloco entre design_review: e documentation:
        dr_block = _CRITIC_SPEC_SYSTEM[dr_start:doc_start]
        for verdict in ["APROVADO", "CORRIGIR", "REJEITAR"]:
            assert verdict in dr_block, f"design_review block deve ter criterio {verdict}"

    def test_documentation_tem_aprovado_corrigir_rejeitar(self):
        doc_start = _CRITIC_SPEC_SYSTEM.find("documentation:")
        score_start = _CRITIC_SPEC_SYSTEM.find("Score:", doc_start)
        doc_block = _CRITIC_SPEC_SYSTEM[doc_start:score_start]
        for verdict in ["APROVADO", "CORRIGIR", "REJEITAR"]:
            assert verdict in doc_block, f"documentation block deve ter criterio {verdict}"
