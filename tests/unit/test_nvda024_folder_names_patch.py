import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ===========================================================================
# Fix A: addon_builder — _NVDA_MODULES_LOWER filtra nomes de pasta
# ===========================================================================

class TestAddonBuilderFolderNamesFiltered:
    """
    addon_builder.bundle_addon_dependencies deve filtrar silenciosamente
    nomes de pasta do NVDA em vez de tentar pip install (que falharia).
    Verifica que _NVDA_MODULES_LOWER contem as novas entradas.
    """

    def _get_modules_lower(self):
        from nvdastudio.builder.addon_builder import _NVDA_MODULES_LOWER
        return _NVDA_MODULES_LOWER

    def test_globalplugins_filtrado(self):
        m = self._get_modules_lower()
        assert "globalplugins" in m, (
            "_NVDA_MODULES_LOWER nao tem 'globalplugins'. "
            "Resultado: pip install globalplugins falha com ERROR: Could not find..."
        )

    def test_appmodules_filtrado(self):
        m = self._get_modules_lower()
        assert "appmodules" in m, (
            "_NVDA_MODULES_LOWER nao tem 'appmodules'."
        )

    def test_synthdrivers_filtrado(self):
        m = self._get_modules_lower()
        assert "synthdrivers" in m, (
            "_NVDA_MODULES_LOWER nao tem 'synthdrivers'."
        )

    def test_brailledisplaydrivers_filtrado(self):
        m = self._get_modules_lower()
        assert "brailledisplaydrivers" in m, (
            "_NVDA_MODULES_LOWER nao tem 'brailledisplaydrivers'."
        )

    def test_installtasks_filtrado(self):
        m = self._get_modules_lower()
        assert "installtasks" in m, (
            "_NVDA_MODULES_LOWER nao tem 'installtasks'."
        )

    def test_nvdabuiltin_filtrado(self):
        m = self._get_modules_lower()
        assert "nvdabuiltin" in m, (
            "_NVDA_MODULES_LOWER nao tem 'nvdabuiltin'."
        )

    def test_versao_addon_builder_e_3_6_0(self):
        from nvdastudio.builder.addon_builder import MODULE_VERSION
        assert MODULE_VERSION == "4.18.0", (
            f"addon_builder versao esperada 3.7.0, encontrada {MODULE_VERSION}."
        )


# ===========================================================================
# Fix B: code_generator — NVDA-024 lista pastas como proibidas no _SYSTEM
# ===========================================================================

class TestCodeGeneratorNVDA024FolderNames:
    """
    _SYSTEM do code_generator deve listar nomes de pasta do NVDA
    explicitamente como proibidos em dependencies[].
    """

    def _get_system(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        return _SYSTEM

    def test_globalplugins_proibido_no_system(self):
        system = self._get_system()
        assert "globalPlugins" in system and "PROIBIDO" in system, (
            "_SYSTEM nao menciona globalPlugins como proibido em dependencies[]."
        )

    def test_appmodules_proibido_no_system(self):
        system = self._get_system()
        idx = system.find("PROIBIDO em dependencies")
        assert idx != -1
        proibido = system[idx:idx + 600]
        assert "appModules" in proibido, (
            "appModules nao esta listado como proibido em NVDA-024."
        )

    def test_synthdrivers_proibido_no_system(self):
        system = self._get_system()
        idx = system.find("PROIBIDO em dependencies")
        assert idx != -1
        proibido = system[idx:idx + 600]
        assert "synthDrivers" in proibido, (
            "synthDrivers nao esta listado como proibido em NVDA-024."
        )

    def test_versao_code_generator_e_3_1_1(self):
        from nvdastudio.sub_agents.code_generator import MODULE_VERSION
        assert MODULE_VERSION == "3.34.0", (
            f"code_generator versao esperada 3.24.0, encontrada {MODULE_VERSION}."
        )
