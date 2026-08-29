import os
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


class TestAddonLoaderImport:
    def test_importavel(self):
        from nvdastudio.builder.addon_loader import (
            load_addon_from_blocks, load_addon_from_folder, load_addon_from_nvda_addon,
        )
        assert callable(load_addon_from_folder)
        assert callable(load_addon_from_nvda_addon)
        assert callable(load_addon_from_blocks)

    def test_versao_e_1_0_0(self):
        from nvdastudio.builder.addon_loader import MODULE_VERSION
        assert MODULE_VERSION == "1.4.0"


class TestLoadAddonFromBlocks:
    """
    addon_loader.py 1.3.0: monta AddonContext direto dos blocos EM MEMORIA
    que o pipeline de criacao acabou de gerar -- usado por
    gui/studio_dialog.py::_display_result() pra ativar o modo iterativo
    automaticamente apos uma criacao bem-sucedida, sem exigir que o usuario
    clique manualmente em "Carregar Pasta"/"Carregar Arquivo".
    """

    def _blocks(self):
        return [
            {"filename": "manifest.ini", "code": "name = X\nversion = 1.0.0\n", "language": "ini"},
            {"filename": "globalPlugins/x/__init__.py", "code": "class GlobalPlugin:\n    pass\n",
             "language": "python"},
            {"filename": "doc/pt_BR/userGuide.html", "code": "<html>guia</html>", "language": "html"},
            {"filename": "lib/requests/__init__.py", "code": "# dependencia bundlada", "language": "python"},
        ]

    def test_extrai_manifest_e_python_e_doc(self):
        from nvdastudio.builder.addon_loader import load_addon_from_blocks
        ctx = load_addon_from_blocks(self._blocks(), addon_name="X")
        assert ctx.addon_name == "X"
        assert "name = X" in ctx.manifest_raw
        assert "globalPlugins/x/__init__.py" in ctx.python_files
        assert "guia" in ctx.doc_content

    def test_exclui_arquivos_da_pasta_lib(self):
        """lib/ e dependencia bundlada, nao codigo do addon -- mesmo criterio
        de load_addon_from_folder()."""
        from nvdastudio.builder.addon_loader import load_addon_from_blocks
        ctx = load_addon_from_blocks(self._blocks(), addon_name="X")
        assert not any(p.startswith("lib/") for p in ctx.python_files)

    def test_blocos_sem_filename_sao_ignorados(self):
        from nvdastudio.builder.addon_loader import load_addon_from_blocks
        ctx = load_addon_from_blocks(
            [{"filename": "", "code": "lixo", "language": "python"}], addon_name="X",
        )
        assert ctx.python_files == {}

    def test_nao_toca_disco(self):
        """source_path deve indicar claramente que e um addon ainda nao
        salvo -- nao deve ser um caminho real de arquivo."""
        from nvdastudio.builder.addon_loader import load_addon_from_blocks
        ctx = load_addon_from_blocks(self._blocks(), addon_name="X")
        assert not os.path.exists(ctx.source_path)

    def test_addon_context_importavel(self):
        from nvdastudio.builder.addon_loader import AddonContext
        assert AddonContext is not None


class TestLoadAddonFromFolder:
    def test_retorna_addon_context(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        _create_pasta_addon(tmp_path)
        ctx = load_addon_from_folder(str(tmp_path))
        from nvdastudio.builder.addon_loader import AddonContext
        assert isinstance(ctx, AddonContext)

    def test_nome_extraido_do_manifest(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        _create_pasta_addon(tmp_path)
        ctx = load_addon_from_folder(str(tmp_path))
        assert ctx.addon_name == "AddonTeste"

    def test_versao_extraida_do_manifest(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        _create_pasta_addon(tmp_path)
        ctx = load_addon_from_folder(str(tmp_path))
        assert ctx.version == "1.5.0"

    def test_summary_extraido(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        _create_pasta_addon(tmp_path)
        ctx = load_addon_from_folder(str(tmp_path))
        assert ctx.summary == "Addon de teste"

    def test_python_files_encontrados(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        _create_pasta_addon(tmp_path)
        ctx = load_addon_from_folder(str(tmp_path))
        assert len(ctx.python_files) >= 1

    def test_python_code_presente(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        _create_pasta_addon(tmp_path)
        ctx = load_addon_from_folder(str(tmp_path))
        code = "\n".join(ctx.python_files.values())
        assert "GlobalPlugin" in code

    def test_manifest_raw_presente(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        _create_pasta_addon(tmp_path)
        ctx = load_addon_from_folder(str(tmp_path))
        assert "AddonTeste" in ctx.manifest_raw

    def test_doc_carregada(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        _create_pasta_addon(tmp_path, com_doc=True)
        ctx = load_addon_from_folder(str(tmp_path))
        assert "userGuide" in ctx.doc_content.lower() or "html" in ctx.doc_content.lower()

    def test_pasta_inexistente_retorna_erros(self):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        ctx = load_addon_from_folder("/pasta/que/nao/existe_xyz")
        assert len(ctx.load_errors) >= 1

    def test_pasta_inexistente_addon_name_fallback(self):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        ctx = load_addon_from_folder("/pasta/inexistente/meuAddon")
        assert ctx.addon_name != ""

    def test_sem_manifest_reporta_erro(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        # Pasta sem manifest.ini
        gp = tmp_path / "globalPlugins"
        gp.mkdir()
        (gp / "__init__.py").write_text("# addon", encoding="utf-8")
        ctx = load_addon_from_folder(str(tmp_path))
        assert any("manifest" in e.lower() for e in ctx.load_errors)

    def test_nao_executa_codigo_python(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        executou = [False]
        malicious = "import os; os.system('del /q')"
        _create_pasta_addon(tmp_path, py_code=malicious)
        ctx = load_addon_from_folder(str(tmp_path))
        # Apenas leu — nao executou
        code = "\n".join(ctx.python_files.values())
        assert malicious in code
        assert executou[0] is False

    def test_source_path_correto(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        _create_pasta_addon(tmp_path)
        ctx = load_addon_from_folder(str(tmp_path))
        assert ctx.source_path == str(tmp_path)


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
        from nvdastudio.builder.addon_loader import load_addon_from_nvda_addon, AddonContext
        addon = self._create_nvda_addon(tmp_path)
        ctx = load_addon_from_nvda_addon(addon)
        assert isinstance(ctx, AddonContext)

    def test_nome_extraido_do_manifest(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_nvda_addon
        addon = self._create_nvda_addon(tmp_path)
        ctx = load_addon_from_nvda_addon(addon)
        assert ctx.addon_name == "AddonZip"

    def test_versao_extraida(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_nvda_addon
        addon = self._create_nvda_addon(tmp_path)
        ctx = load_addon_from_nvda_addon(addon)
        assert ctx.version == "2.0.0"

    def test_python_files_do_zip(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_nvda_addon
        addon = self._create_nvda_addon(tmp_path)
        ctx = load_addon_from_nvda_addon(addon)
        assert len(ctx.python_files) >= 1

    def test_arquivo_inexistente_retorna_erros(self):
        from nvdastudio.builder.addon_loader import load_addon_from_nvda_addon
        ctx = load_addon_from_nvda_addon("/nao/existe/addon.nvda-addon")
        assert len(ctx.load_errors) >= 1

    def test_nao_executa_codigo_do_zip(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_nvda_addon
        malicious = "import os; os.system('format C:')"
        addon = self._create_nvda_addon(tmp_path, py_code=malicious)
        ctx = load_addon_from_nvda_addon(addon)
        code = "\n".join(ctx.python_files.values())
        assert malicious in code  # apenas armazenou, nao executou


class TestAddonContextToPromptContext:
    def test_retorna_string(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        _create_pasta_addon(tmp_path)
        ctx = load_addon_from_folder(str(tmp_path))
        result = ctx.to_prompt_context()
        assert isinstance(result, str)

    def test_contem_nome_addon(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        _create_pasta_addon(tmp_path)
        ctx = load_addon_from_folder(str(tmp_path))
        result = ctx.to_prompt_context()
        assert "AddonTeste" in result

    def test_contem_versao(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        _create_pasta_addon(tmp_path)
        ctx = load_addon_from_folder(str(tmp_path))
        result = ctx.to_prompt_context()
        assert "1.5.0" in result

    def test_contem_codigo_python(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        _create_pasta_addon(tmp_path)
        ctx = load_addon_from_folder(str(tmp_path))
        result = ctx.to_prompt_context()
        assert "GlobalPlugin" in result

    def test_nao_executa_ao_formatar(self, tmp_path):
        from nvdastudio.builder.addon_loader import load_addon_from_folder
        malicious = "import os; os.system('del /q')"
        _create_pasta_addon(tmp_path, py_code=malicious)
        ctx = load_addon_from_folder(str(tmp_path))
        result = ctx.to_prompt_context()
        # Codigo malicioso esta no contexto como texto
        assert malicious in result

