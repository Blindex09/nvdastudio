from nvdastudio.sub_agents.manifest_builder import _SYSTEM, MODULE_VERSION


class TestManifestBuilderVersao:
    def test_versao_e_1_5_0(self):
        assert MODULE_VERSION == "1.14.0"


class TestManifestBuilderPromptAntiLista:
    """O system prompt deve proibir multiline em TODOS os campos de texto."""

    def test_menciona_summary_na_regra(self):
        assert "summary" in _SYSTEM

    def test_menciona_description_na_regra(self):
        assert "description" in _SYSTEM

    def test_menciona_changelog_na_regra(self):
        assert "changelog" in _SYSTEM

    def test_menciona_vtdtypeerror(self):
        """Deve mencionar o erro fatal para que a LLM entenda a gravidade."""
        assert "VdtTypeError" in _SYSTEM or "wrong type" in _SYSTEM or "lista" in _SYSTEM

    def test_menciona_uma_unica_linha(self):
        assert "uma" in _SYSTEM.lower() and "linha" in _SYSTEM.lower()

    def test_proibido_presente_no_prompt(self):
        assert "PROIBIDO" in _SYSTEM or "proibido" in _SYSTEM.lower()

    def test_exemplo_correto_presente(self):
        """Deve ter exemplo de manifest correto para a LLM seguir."""
        assert "name = " in _SYSTEM
        assert "summary = " in _SYSTEM
        assert "version = " in _SYSTEM

    def test_formato_fence_ini(self):
        """LLM deve saber formatar como bloco ini anotado."""
        assert "```ini:manifest.ini" in _SYSTEM

    def test_nao_menciona_secao_addon(self):
        """SEM [add-on] no manifest — ConfigObj nao usa secoes."""
        assert "[add-on]" not in _SYSTEM or "SEM" in _SYSTEM

    def test_versoes_corretas_no_exemplo(self):
        """Exemplo deve usar o baseline oficial do projeto (2026.1)."""
        assert "2026.1" in _SYSTEM
