import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def _make_addon(tmp_path):
    """Cria estrutura minima de addon valido para os testes."""
    gp = tmp_path / "globalPlugins" / "MeuAddon"
    gp.mkdir(parents=True)
    (gp / "__init__.py").write_text(
        "import globalPluginHandler, addonHandler\n"
        "addonHandler.initTranslation()\n"
        "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
        "    def terminate(self): super().terminate()\n",
        encoding="utf-8",
    )
    (tmp_path / "manifest.ini").write_text(
        "name = MeuAddon\nversion = 1.0.0\n"
        "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n",
        encoding="utf-8",
    )
    (tmp_path / "doc").mkdir()
    lib = gp / "lib"
    lib.mkdir()
    return lib


# ===========================================================================
# 1. win_amd64 — compativel com baseline, NAO deve gerar NVDA-017
# ===========================================================================

class TestNVDA017WinAmd64NaoEFalsoPositivo:
    """
    Binarios cp313-win_amd64 sao compatíveis com NVDA 2026.1.1+ (Python 3.13 64-bit).
    O validador NAO deve reportar NVDA-017 para esses arquivos.
    Esse era o falso positivo que aparecia com google-generativeai, cffi, etc.
    """

    def test_pyd_cp313_win_amd64_nao_gera_nvda017(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        lib = _make_addon(tmp_path)
        (lib / "_cffi_backend.cp313-win_amd64.pyd").write_bytes(b"\x00")
        problems = validate_addon_structure(str(tmp_path))
        nvda017 = [p for p in problems if "NVDA-017" in p]
        assert nvda017 == [], (
            "cp313-win_amd64.pyd e compativel com NVDA 2026.1.1+ — "
            f"nao deve gerar NVDA-017. Gerou: {nvda017}"
        )

    def test_multiplos_pyd_win_amd64_nao_geram_nvda017(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        lib = _make_addon(tmp_path)
        # Simula o que google-generativeai instala (cffi, charset_normalizer, mypyc)
        for nome in (
            "_cffi_backend.cp313-win_amd64.pyd",
            "cd.cp313-win_amd64.pyd",
            "81d243bd2c585b0f4821__mypyc.cp313-win_amd64.pyd",
        ):
            (lib / nome).write_bytes(b"\x00")
        problems = validate_addon_structure(str(tmp_path))
        nvda017 = [p for p in problems if "NVDA-017" in p]
        assert nvda017 == [], (
            f"Binarios win_amd64 nao devem gerar NVDA-017. Gerou: {nvda017}"
        )

    def test_pyd_win_amd64_sem_versao_python_nao_gera_nvda017(self, tmp_path):
        """win_amd64 sem especificacao de versao Python tambem e 64-bit — sem aviso."""
        from nvdastudio.builder.addon_builder import validate_addon_structure
        lib = _make_addon(tmp_path)
        (lib / "modulo.win_amd64.pyd").write_bytes(b"\x00")
        problems = validate_addon_structure(str(tmp_path))
        nvda017 = [p for p in problems if "NVDA-017" in p]
        assert nvda017 == [], (
            f"win_amd64.pyd sem versao Python nao deve gerar NVDA-017. Gerou: {nvda017}"
        )


# ===========================================================================
# 2. win32 — 32-bit, DEVE continuar gerando NVDA-017 critico
# ===========================================================================

class TestNVDA017Win32ContinuaCritico:
    """
    Binarios 32-bit (win32) sao incompativeis com NVDA 2026.1+ (Python 3.13 64-bit).
    O validador DEVE continuar reportando NVDA-017 para esses arquivos.
    """

    def test_pyd_win32_gera_nvda017(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        lib = _make_addon(tmp_path)
        (lib / "core.cp311-win32.pyd").write_bytes(b"\x00")
        problems = validate_addon_structure(str(tmp_path))
        nvda017 = [p for p in problems if "NVDA-017" in p]
        assert len(nvda017) == 1, (
            f"win32.pyd DEVE gerar NVDA-017. Problemas: {problems}"
        )

    def test_pyd_win32_menciona_win32_na_mensagem(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        lib = _make_addon(tmp_path)
        (lib / "engine.cp311-win32.pyd").write_bytes(b"\x00")
        problems = validate_addon_structure(str(tmp_path))
        nvda017 = [p for p in problems if "NVDA-017" in p][0]
        assert "engine.cp311-win32.pyd" in nvda017, (
            "Mensagem NVDA-017 deve mencionar o arquivo 32-bit"
        )

    def test_pyd_cp311_amd64_rejeitado_por_abi_antiga(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        lib = _make_addon(tmp_path)
        (lib / "legacy.cp311-win_amd64.pyd").write_bytes(b"\x00")
        problems = validate_addon_structure(str(tmp_path))
        nvda017 = [p for p in problems if "NVDA-017" in p]
        assert len(nvda017) == 1
        assert "CPython 3.13" in nvda017[0]


# ===========================================================================
# 3. sem marcacao — arquitetura incerta, DEVE gerar NVDA-017
# ===========================================================================

class TestNVDA017SemMarcacaoGeraAviso:
    """
    Binarios .pyd sem marcacao de arquitetura (sem win32 nem win_amd64)
    tem arquitetura incerta — devem continuar gerando NVDA-017.
    """

    def test_pyd_sem_marcacao_gera_nvda017(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        lib = _make_addon(tmp_path)
        (lib / "modulo_sem_arch.pyd").write_bytes(b"\x00")
        problems = validate_addon_structure(str(tmp_path))
        nvda017 = [p for p in problems if "NVDA-017" in p]
        assert len(nvda017) == 1, (
            f".pyd sem marcacao deve gerar NVDA-017. Problemas: {problems}"
        )

    def test_mistura_win32_e_sem_marcacao_gera_nvda017(self, tmp_path):
        """Mistura de 32-bit e sem marcacao: ambos devem gerar aviso."""
        from nvdastudio.builder.addon_builder import validate_addon_structure
        lib = _make_addon(tmp_path)
        (lib / "modulo.cp311-win32.pyd").write_bytes(b"\x00")
        (lib / "outro.pyd").write_bytes(b"\x00")
        problems = validate_addon_structure(str(tmp_path))
        nvda017 = [p for p in problems if "NVDA-017" in p]
        assert len(nvda017) == 2, (
            "ABI antiga e binario sem marcacao devem ser reportados. "
            f"Problemas: {problems}"
        )

    def test_win_amd64_com_win32_na_mistura_so_win32_conta(self, tmp_path):
        """Se ha win_amd64 E win32, apenas o win32 deve gerar NVDA-017."""
        from nvdastudio.builder.addon_builder import validate_addon_structure
        lib = _make_addon(tmp_path)
        (lib / "ok.cp313-win_amd64.pyd").write_bytes(b"\x00")
        (lib / "ruim.cp311-win32.pyd").write_bytes(b"\x00")
        problems = validate_addon_structure(str(tmp_path))
        nvda017 = [p for p in problems if "NVDA-017" in p]
        assert len(nvda017) == 1, (
            "Apenas o win32 deve gerar NVDA-017, nao o win_amd64. "
            f"Problemas: {problems}"
        )
        assert "ruim.cp311-win32.pyd" in nvda017[0]
        assert "ok.cp313-win_amd64.pyd" not in nvda017[0]
