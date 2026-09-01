from nvdastudio.sub_agents.code_generator import _SYSTEM as CODE_SYSTEM, MODULE_VERSION as CODE_VER
from nvdastudio.sub_agents.manifest_builder import _SYSTEM as MANIFEST_SYSTEM
from nvdastudio.sub_agents.doc_generator import _SYSTEM as DOC_SYSTEM
from nvdastudio.sub_agents.design_review_agent import (
    _ADVOCATE_SYSTEM, _SYNTHESIS_TEMPLATE_V3,
    MODULE_VERSION as DESIGN_VER
)

class TestCodeGenerator2026:
    def test_versao_e_1_9_0(self):
        assert CODE_VER == "3.34.0"

    def test_nvda_017_dll_32bit_proibida(self):
        assert "NVDA-017" in CODE_SYSTEM

    def test_nvda_017_menciona_ctypes(self):
        assert "ctypes" in CODE_SYSTEM.lower()

    def test_nvda_017_menciona_64bit(self):
        assert "64-bit" in CODE_SYSTEM or "64bit" in CODE_SYSTEM

    def test_nvda_018_minimumNVDAVersion(self):
        assert "NVDA-018" in CODE_SYSTEM

    def test_baseline_2025_3_3_presente(self):
        assert "2026.1" in CODE_SYSTEM

    def test_migracoes_winbindings(self):
        assert "winBindings" in CODE_SYSTEM

    def test_migracao_tabbable_scrolled_panel(self):
        assert "TabbableScrolledPanel" in CODE_SYSTEM

    def test_typing_extensions_removido(self):
        assert "typing_extensions" in CODE_SYSTEM

    def test_nao_executa_codigo(self):
        assert isinstance(CODE_SYSTEM, str)


class TestManifestBuilder2026:
    def test_campo_changelog_no_prompt(self):
        assert "changelog" in MANIFEST_SYSTEM.lower()

    def test_updatechannel_nao_esta_mais_no_prompt(self):
        """Achado de auditoria 2026-08-04: updateChannel nao existe no
        AddonManifest.configspec real do NVDA (confirmado contra
        nvaccess/nvda master) -- removido do prompt, era campo fabricado."""
        assert "updateChannel" not in MANIFEST_SYSTEM

    def test_exemplo_completo_tem_changelog(self):
        assert "changelog = " in MANIFEST_SYSTEM

    def test_exemplo_usa_baseline_oficial(self):
        assert "2026.1" in MANIFEST_SYSTEM

    def test_nao_executa_codigo(self):
        assert isinstance(MANIFEST_SYSTEM, str)


class TestDocGeneratorFallbackEn:
    def test_menciona_doc_en(self):
        assert "doc/en/userGuide.html" in DOC_SYSTEM

    def test_menciona_dois_blocos(self):
        assert "doc/pt_BR/userGuide.html" in DOC_SYSTEM
        assert "doc/en/userGuide.html" in DOC_SYSTEM

    def test_explica_fallback_locale(self):
        assert "locale" in DOC_SYSTEM.lower() or "fallback" in DOC_SYSTEM.lower()

    def test_lang_en_no_bloco_en(self):
        assert 'lang="en"' in DOC_SYSTEM or "lang=en" in DOC_SYSTEM

    def test_nao_executa_codigo(self):
        assert isinstance(DOC_SYSTEM, str)


class TestDesignReviewUserAdvocate:
    def test_versao_e_2_3_0(self):
        assert DESIGN_VER == "2.14.0"

    def test_advocate_respeita_modelo_do_step(self):
        import inspect
        from nvdastudio.sub_agents.design_review_agent import run
        assert inspect.getsource(run).count("model_id,") >= 3

    def test_advocate_system_menciona_usuario_cego(self):
        assert "ceg" in _ADVOCATE_SYSTEM.lower()

    def test_advocate_menciona_atalhos(self):
        assert "atalho" in _ADVOCATE_SYSTEM.lower()

    def test_advocate_menciona_conflitos(self):
        assert "conflitam" in _ADVOCATE_SYSTEM.lower() or "conflito" in _ADVOCATE_SYSTEM.lower()

    def test_advocate_menciona_linguagem(self):
        assert "linguagem" in _ADVOCATE_SYSTEM.lower() or "mensagem" in _ADVOCATE_SYSTEM.lower()

    def test_synthesis_tem_secao_advocate(self):
        assert "advocate" in _SYNTHESIS_TEMPLATE_V3.lower() or "user" in _SYNTHESIS_TEMPLATE_V3.lower()

    def test_synthesis_tem_tres_secoes(self):
        assert "{challenger}" in _SYNTHESIS_TEMPLATE_V3
        assert "{guardian}" in _SYNTHESIS_TEMPLATE_V3
        assert "{advocate}" in _SYNTHESIS_TEMPLATE_V3

    def test_nao_executa_codigo(self):
        assert isinstance(_ADVOCATE_SYSTEM, str)
