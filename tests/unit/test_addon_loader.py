import zipfile


def _create_pasta_addon(tmp_path, manifest="", py_code="", com_doc=True):
    """Helper: cria estrutura de pasta de addon para testes."""
    if not manifest:
        manifest = (
            "name = AddonTeste\nsummary = Addon de teste\n"
            "version = 1.5.0\nminimumNVDAVersion = 2026.1.1\n"
            "lastTestedNVDAVersion = 2026.1.1\nauthor = Felipe\n"
        )
    if not py_code:
        py_code = (
            "import addonHandler\nimport globalPluginHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): super().terminate()\n"
        )
    (tmp_path / "manifest.ini").write_text(manifest, encoding="utf-8")
    gp = tmp_path / "globalPlugins" / "addonTeste"
    gp.mkdir(parents=True)
    (gp / "__init__.py").write_text(py_code, encoding="utf-8")
    if com_doc:
        doc = tmp_path / "doc" / "pt_BR"
        doc.mkdir(parents=True)
        (doc / "userGuide.html").write_text("<html><body>Guia do usuario</body></html>",
                                           encoding="utf-8")
    return tmp_path








class TestLoadAddonFromNvdaAddon:
    def _create_nvda_addon(self, tmp_path, manifest="", py_code=""):
        if not manifest:
            manifest = (
                "name = AddonZip\nsummary = Addon do ZIP\n"
                "version = 2.0.0\nminimumNVDAVersion = 2026.1.1\n"
                "lastTestedNVDAVersion = 2026.1.1\n"
            )
        if not py_code:
            py_code = "import globalPluginHandler\nclass GlobalPlugin: pass\n"
        addon_path = str(tmp_path / "meu.nvda-addon")
        with zipfile.ZipFile(addon_path, "w") as zf:
            zf.writestr("manifest.ini", manifest.encode("utf-8"))
            zf.writestr("globalPlugins/addonZip/__init__.py", py_code.encode("utf-8"))
            zf.writestr("doc/pt_BR/userGuide.html", b"<html>Guia</html>")
        return addon_path

    def test_retorna_addon_context(self, tmp_path):
        from nvdastudio_mcp.addon_loader import load_addon_from_nvda_addon, AddonContext
        addon = self._create_nvda_addon(tmp_path)
        ctx = load_addon_from_nvda_addon(addon)
        assert isinstance(ctx, AddonContext)

    def test_nome_extraido_do_manifest(self, tmp_path):
        from nvdastudio_mcp.addon_loader import load_addon_from_nvda_addon
        addon = self._create_nvda_addon(tmp_path)
        ctx = load_addon_from_nvda_addon(addon)
        assert ctx.addon_name == "AddonZip"

    def test_versao_extraida(self, tmp_path):
        from nvdastudio_mcp.addon_loader import load_addon_from_nvda_addon
        addon = self._create_nvda_addon(tmp_path)
        ctx = load_addon_from_nvda_addon(addon)
        assert ctx.version == "2.0.0"

    def test_python_files_do_zip(self, tmp_path):
        from nvdastudio_mcp.addon_loader import load_addon_from_nvda_addon
        addon = self._create_nvda_addon(tmp_path)
        ctx = load_addon_from_nvda_addon(addon)
        assert len(ctx.python_files) >= 1

    def test_arquivo_inexistente_retorna_erros(self):
        from nvdastudio_mcp.addon_loader import load_addon_from_nvda_addon
        ctx = load_addon_from_nvda_addon("/nao/existe/addon.nvda-addon")
        assert len(ctx.load_errors) >= 1

    def test_nao_executa_codigo_do_zip(self, tmp_path):
        from nvdastudio_mcp.addon_loader import load_addon_from_nvda_addon
        malicious = "import os; os.system('format C:')"
        addon = self._create_nvda_addon(tmp_path, py_code=malicious)
        ctx = load_addon_from_nvda_addon(addon)
        code = "\n".join(ctx.python_files.values())
        assert malicious in code  # apenas armazenou, nao executou




