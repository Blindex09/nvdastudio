class TestAddonBuilderVersaoV13:
    def test_versao_e_1_8_0(self):
        from nvdastudio.builder.addon_builder import MODULE_VERSION
        assert MODULE_VERSION == "4.24.0"


class TestValidateAddonStructureImport:
    def test_importavel(self):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        assert callable(validate_addon_structure)


class TestValidateAddonStructurePastaInexistente:
    def test_pasta_inexistente_retorna_erro(self):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        result = validate_addon_structure("/caminho/que/nao/existe_xyz")
        assert len(result) >= 1
        assert any("nao encontrada" in p.lower() or "ausente" in p.lower()
                   for p in result)

    def test_retorna_lista(self):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        result = validate_addon_structure("/caminho/inexistente")
        assert isinstance(result, list)


class TestValidateAddonStructureCompleto:
    """Addon com estrutura correta nao deve ter problemas."""

    def _addon_python_completo(self):
        return '"""Addon de teste."""\nimport addonHandler\nimport globalPluginHandler\nfrom scriptHandler import script\nimport ui\n\naddonHandler.initTranslation()\n\n\nclass GlobalPlugin(globalPluginHandler.GlobalPlugin):\n\n\t@script(gesture="kb:NVDA+shift+t", description="Teste")\n\tdef script_teste(self, gesture):\n\t\tui.message("teste")\n\n\tdef terminate(self):\n\t\tsuper().terminate()\n'

    def test_addon_completo_sem_problemas(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure

        # Cria estrutura correta
        (tmp_path / "manifest.ini").write_text(
            "name = MeuAddon\nsummary = MeuAddon\nauthor = Teste <teste@exemplo.com>\n"
            "version = 1.0.0\n"
            "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.2.0\n",
            encoding="utf-8"
        )
        gp = tmp_path / "globalPlugins" / "meuAddon"
        gp.mkdir(parents=True)
        (gp / "__init__.py").write_text(self._addon_python_completo(), encoding="utf-8")
        doc = tmp_path / "doc" / "pt_BR"
        doc.mkdir(parents=True)
        (doc / "userGuide.html").write_text("<html></html>", encoding="utf-8")

        problems = validate_addon_structure(str(tmp_path))
        assert problems == []

    def test_addon_nao_executa_python(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure

        (tmp_path / "manifest.ini").write_text(
            "name=x\nversion=1\nminimumNVDAVersion=2026.1.1\nlastTestedNVDAVersion=2026.1.1\n",
            encoding="utf-8"
        )
        gp = tmp_path / "globalPlugins" / "x"
        gp.mkdir(parents=True)
        malicioso = "import os; os.system('del /q')\n" + self._addon_python_completo()
        (gp / "__init__.py").write_text(malicioso, encoding="utf-8")
        doc = tmp_path / "doc"
        doc.mkdir()

        # Apenas analisa texto — nao executa
        problems = validate_addon_structure(str(tmp_path))
        assert isinstance(problems, list)


class TestValidateAddonStructureManifest:
    def test_sem_manifest_reporta_problema(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        (tmp_path / "globalPlugins").mkdir()
        problems = validate_addon_structure(str(tmp_path))
        assert any("manifest.ini" in p for p in problems)

    def test_manifest_sem_campo_name_reporta(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        (tmp_path / "manifest.ini").write_text(
            "version = 1.0.0\nminimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n",
            encoding="utf-8"
        )
        (tmp_path / "globalPlugins").mkdir()
        (tmp_path / "doc").mkdir()
        problems = validate_addon_structure(str(tmp_path))
        assert any("name" in p for p in problems)

    def test_manifest_sem_minimumNVDAVersion_reporta(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        (tmp_path / "manifest.ini").write_text(
            "name = x\nversion = 1.0.0\nlastTestedNVDAVersion = 2026.1.1\n",
            encoding="utf-8"
        )
        (tmp_path / "globalPlugins").mkdir()
        (tmp_path / "doc").mkdir()
        problems = validate_addon_structure(str(tmp_path))
        assert any("minimumNVDAVersion" in p for p in problems)


class TestValidateAddonStructurePython:
    def _manifest(self, tmp_path):
        (tmp_path / "manifest.ini").write_text(
            "name=x\nversion=1\nminimumNVDAVersion=2026.1.1\nlastTestedNVDAVersion=2026.1.1\n",
            encoding="utf-8"
        )

    def test_sem_globalplugins_reporta(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        self._manifest(tmp_path)
        (tmp_path / "doc").mkdir()
        problems = validate_addon_structure(str(tmp_path))
        assert any("globalPlugins" in p for p in problems)

    def test_sem_global_plugin_class_reporta(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        self._manifest(tmp_path)
        gp = tmp_path / "globalPlugins"
        gp.mkdir()
        (gp / "__init__.py").write_text(
            "import addonHandler\naddonHandler.initTranslation()\ndef terminate(): pass\n",
            encoding="utf-8"
        )
        (tmp_path / "doc").mkdir()
        problems = validate_addon_structure(str(tmp_path))
        assert any("GlobalPlugin" in p for p in problems)

    def test_sem_inittranslation_reporta_nvda003(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        self._manifest(tmp_path)
        gp = tmp_path / "globalPlugins"
        gp.mkdir()
        (gp / "__init__.py").write_text(
            "import globalPluginHandler\nclass GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): super().terminate()\n",
            encoding="utf-8"
        )
        (tmp_path / "doc").mkdir()
        problems = validate_addon_structure(str(tmp_path))
        assert any("NVDA-003" in p for p in problems)

    def test_sem_terminate_reporta_nvda004(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        self._manifest(tmp_path)
        gp = tmp_path / "globalPlugins"
        gp.mkdir()
        (gp / "__init__.py").write_text(
            "import addonHandler\nimport globalPluginHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin): pass\n",
            encoding="utf-8"
        )
        (tmp_path / "doc").mkdir()
        problems = validate_addon_structure(str(tmp_path))
        assert any("NVDA-004" in p for p in problems)

    def test_gestures_dict_nao_reporta_nvda007_deterministico(self, tmp_path):
        """
        NVDA-007 (__gestures) saiu do checklist deterministico em 4.5.0: a doc
        oficial do NVDA trata __gestures como alternativa valida (nao proibida),
        e o julgamento de contexto (uso legitimo em padrao de "camada" de
        comandos vs. uso ruim) agora e responsabilidade exclusiva do critic.py.
        """
        from nvdastudio.builder.addon_builder import validate_addon_structure
        self._manifest(tmp_path)
        gp = tmp_path / "globalPlugins"
        gp.mkdir()
        (gp / "__init__.py").write_text(
            "import addonHandler\nimport globalPluginHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    __gestures = {'kb:NVDA+t': 'script_test'}\n"
            "    def terminate(self): super().terminate()\n",
            encoding="utf-8"
        )
        (tmp_path / "doc").mkdir()
        problems = validate_addon_structure(str(tmp_path))
        assert not any("NVDA-007" in p for p in problems), problems


class TestValidateAddonStructureDoc:
    def test_sem_doc_reporta_estrutura006(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        (tmp_path / "manifest.ini").write_text(
            "name=x\nversion=1\nminimumNVDAVersion=2026.1.1\nlastTestedNVDAVersion=2026.1.1\n",
            encoding="utf-8"
        )
        gp = tmp_path / "globalPlugins"
        gp.mkdir()
        (gp / "__init__.py").write_text(
            "import addonHandler\nimport globalPluginHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): super().terminate()\n",
            encoding="utf-8"
        )
        problems = validate_addon_structure(str(tmp_path))
        assert any("doc" in p.lower() for p in problems)


class TestValidateAddonStructureRetornaTipos:
    def test_sempre_retorna_lista(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        result = validate_addon_structure(str(tmp_path))
        assert isinstance(result, list)

    def test_problemas_sao_strings(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        result = validate_addon_structure(str(tmp_path))
        for p in result:
            assert isinstance(p, str)


class TestValidateAddonStructurePoliticaBaseline:
    def test_minimum_abaixo_do_baseline_gera_politica_001(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure

        (tmp_path / "manifest.ini").write_text(
            "name = Legado\nversion = 1.0.0\n"
            "minimumNVDAVersion = 2025.3.2\nlastTestedNVDAVersion = 2026.1.1\n",
            encoding="utf-8",
        )
        gp = tmp_path / "globalPlugins" / "Legado"
        gp.mkdir(parents=True)
        (gp / "__init__.py").write_text(
            "import addonHandler\nimport globalPluginHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): super().terminate()\n",
            encoding="utf-8",
        )
        (tmp_path / "doc").mkdir()

        problems = validate_addon_structure(str(tmp_path))
        assert any("POLITICA-001" in p for p in problems), problems

    def test_last_tested_abaixo_do_baseline_gera_politica_002(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure

        (tmp_path / "manifest.ini").write_text(
            "name = Legado\nversion = 1.0.0\n"
            "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2025.3.0\n",
            encoding="utf-8",
        )
        gp = tmp_path / "globalPlugins" / "Legado"
        gp.mkdir(parents=True)
        (gp / "__init__.py").write_text(
            "import addonHandler\nimport globalPluginHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): super().terminate()\n",
            encoding="utf-8",
        )
        (tmp_path / "doc").mkdir()

        problems = validate_addon_structure(str(tmp_path))
        assert any("POLITICA-002" in p for p in problems), problems


class TestValidateAddonStructureLibExclusao:
    """Garante que lib/ (dependencias bundladas) nao gera falsos positivos."""

    def test_arquivos_em_lib_nao_geram_falsos_positivos(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure

        (tmp_path / "manifest.ini").write_text(
            "name = MeuAddon\nversion = 1.0.0\n"
            "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n",
            encoding="utf-8",
        )
        gp = tmp_path / "globalPlugins" / "MeuAddon"
        gp.mkdir(parents=True)
        (gp / "__init__.py").write_text(
            "import addonHandler\nimport globalPluginHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): super().terminate()\n",
            encoding="utf-8",
        )
        # Simula lib/ com dependencias bundladas (flask, typing_extensions...)
        lib_dir = gp / "lib"
        lib_dir.mkdir()
        (lib_dir / "typing_extensions.py").write_text(
            "# typing_extensions — sem GlobalPlugin, sem initTranslation, sem terminate\n"
            "def override(func): return func\n",
            encoding="utf-8",
        )
        (lib_dir / "flask_app.py").write_text(
            "from flask import Flask\napp = Flask(__name__)\n",
            encoding="utf-8",
        )
        (tmp_path / "doc").mkdir()

        problems = validate_addon_structure(str(tmp_path))
        lib_problems = [p for p in problems if "typing_extensions" in p or "flask_app" in p]
        assert lib_problems == [], (
            f"lib/ gerou falsos positivos: {lib_problems}"
        )
        assert not any(
            "ESTRUTURA-005" in p or "NVDA-003" in p or "NVDA-004" in p
            for p in problems
        ), f"Falsos positivos de estrutura detectados: {problems}"


class TestValidateAddonStructureCompatibility2026:
    """Testes para as novas regras de compatibilidade do NVDA 2026.1+."""

    def test_nvda_052_winbindings_legacy(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure

        (tmp_path / "manifest.ini").write_text(
            "name = MeuAddon\nversion = 1.0.0\n"
            "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n",
            encoding="utf-8",
        )
        gp = tmp_path / "globalPlugins" / "MeuAddon"
        gp.mkdir(parents=True)
        # Importa winUser legado
        (gp / "__init__.py").write_text(
            "import addonHandler\nimport globalPluginHandler\n"
            "import winUser\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): super().terminate()\n",
            encoding="utf-8",
        )
        (tmp_path / "doc").mkdir()

        problems = validate_addon_structure(str(tmp_path))
        assert any("NVDA-052" in p for p in problems), problems

    def test_nvda_053_sapi4_legacy(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure

        (tmp_path / "manifest.ini").write_text(
            "name = MeuAddon\nversion = 1.0.0\n"
            "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n",
            encoding="utf-8",
        )
        gp = tmp_path / "globalPlugins" / "MeuAddon"
        gp.mkdir(parents=True)
        # Usa string 'sapi4'
        (gp / "__init__.py").write_text(
            "import addonHandler\nimport globalPluginHandler\n"
            "driver = 'sapi4'\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): super().terminate()\n",
            encoding="utf-8",
        )
        (tmp_path / "doc").mkdir()

        problems = validate_addon_structure(str(tmp_path))
        assert any("NVDA-053" in p for p in problems), problems

    def test_nvda_054_typing_extensions_removido(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure

        (tmp_path / "manifest.ini").write_text(
            "name = MeuAddon\nversion = 1.0.0\n"
            "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n",
            encoding="utf-8",
        )
        gp = tmp_path / "globalPlugins" / "MeuAddon"
        gp.mkdir(parents=True)
        # Importa typing_extensions
        (gp / "__init__.py").write_text(
            "import addonHandler\nimport globalPluginHandler\n"
            "from typing_extensions import override\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): super().terminate()\n",
            encoding="utf-8",
        )
        (tmp_path / "doc").mkdir()

        problems = validate_addon_structure(str(tmp_path))
        assert any("NVDA-054" in p for p in problems), problems
