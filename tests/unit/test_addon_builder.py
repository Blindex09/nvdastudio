import os


from nvdastudio_mcp.addon_builder import (
    validate_addon_structure,
    _sanitize_manifest,
)
from tests.support import save_addon_files










def test_validador_detecta_string_configobj_convertida_em_lista(tmp_path):
    (tmp_path / "manifest.ini").write_text(
        "name = x\nsummary = X\nauthor = Tester\nversion = 1.0.0\n"
        "description = Audio, video, imagem e PDF\n"
        "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.2.0\n",
        encoding="utf-8",
    )
    problems = validate_addon_structure(str(tmp_path))
    assert any("MANIFEST-001" in problem for problem in problems)


def test_save_addon_files_descarta_teste_na_raiz(tmp_path):
    blocks = [
        {"filename": "test_ami.py", "language": "python", "code": "assert True\n"},
        {"filename": "globalPlugins/x/__init__.py", "language": "python", "code": "pass\n"},
    ]
    _, saved = save_addon_files(blocks, str(tmp_path), "x", garantir_doc=False)
    assert not any(os.path.basename(path) == "test_ami.py" for path in saved)




# -----------------------------------------------------------------------
# bundle_addon_dependencies
# -----------------------------------------------------------------------





class TestSaveAddonFilesTestsFilter:
    """Garante que blocos tests/ nunca sao salvos dentro do addon — v2.1.0."""

    def test_bloco_tests_excluido(self, tmp_path):
        """Arquivo tests/test_algo.py nao deve ser salvo na pasta do addon."""
        blocks = [
            {"filename": "globalPlugins/meu/__init__.py", "language": "python", "code": "# ok"},
            {"filename": "tests/test_meu.py", "language": "python", "code": "# teste"},
        ]
        addon_dir = str(tmp_path)
        _, saved_files = save_addon_files(blocks, addon_dir, "meuAddon")
        # Apenas 1 arquivo deve ser salvo (tests/ excluido)
        assert len(saved_files) >= 1, f"Esperado ao menos 1 arquivo, obteve {len(saved_files)}: {saved_files}"
        # O arquivo salvo deve ser o globalPlugins, nao o de testes
        assert all("test_meu.py" not in p for p in saved_files), f"test_meu.py nao devia ser salvo: {saved_files}"

    def test_bloco_tests_barra_invertida_excluido(self, tmp_path):
        """Garante que tests\\ (Windows) tambem e filtrado corretamente."""
        blocks = [
            {"filename": "globalPlugins/meu/__init__.py", "language": "python", "code": "# ok"},
            {"filename": "tests\\test_meu.py", "language": "python", "code": "# teste"},
        ]
        addon_dir = str(tmp_path)
        _, saved_files = save_addon_files(blocks, addon_dir, "meuAddon")
        assert len(saved_files) >= 1, f"Esperado ao menos 1 arquivo, obteve {len(saved_files)}: {saved_files}"
        assert all("test_meu.py" not in p for p in saved_files), f"test_meu.py nao devia ser salvo: {saved_files}"

    def test_bloco_nao_tests_salvo_normalmente(self, tmp_path):
        """Arquivo normal (globalPlugins/) ainda deve ser salvo."""
        blocks = [
            {"filename": "globalPlugins/meu/__init__.py", "language": "python", "code": "# ok"},
        ]
        addon_dir = str(tmp_path)
        _, saved_files = save_addon_files(blocks, addon_dir, "meuAddon")
        assert len(saved_files) >= 1

    def test_modulo_nvda_ignorado_sem_pip(self, tmp_path):
        """ui, speech, addonHandler etc. nao devem ser passados ao pip (v2.0.0)."""
        from nvdastudio_mcp.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch
        with patch("subprocess.run") as mock_run:
            bundle_addon_dependencies(
                str(tmp_path), ["ui", "speech", "addonHandler", "globalPluginHandler"], "meuAddon"
            )
        mock_run.assert_not_called()


class TestValidateAddonStructure:
    """Testes de validate_addon_structure() -- ESTRUTURA-009 (imports relativos)."""

    def _criar_addon(self, tmp_path, arquivos: dict) -> str:
        """Cria estrutura minima de addon em tmp_path. arquivos={relpath: conteudo}."""
        import os
        addon = str(tmp_path / "MeuAddon")
        plugin_dir = os.path.join(addon, "globalPlugins", "MeuAddon")
        os.makedirs(plugin_dir, exist_ok=True)
        # manifest.ini obrigatorio
        with open(os.path.join(addon, "manifest.ini"), "w", encoding="utf-8") as f:
            f.write(
                "name = MeuAddon\n"
                "summary = Addon de teste.\n"
                "version = 1.0.0\n"
                "minimumNVDAVersion = 2026.1.1\n"
                "lastTestedNVDAVersion = 2026.1.1\n"
            )
        # doc/ obrigatorio
        os.makedirs(os.path.join(addon, "doc"), exist_ok=True)
        for relpath, conteudo in arquivos.items():
            dest = os.path.join(plugin_dir, relpath)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(conteudo)
        return addon

    def test_estrutura_009_modulo_relativo_ausente_detectado(self, tmp_path):
        """ESTRUTURA-009: from .gmail_oauth import ... sem gmail_oauth.py detecta erro."""
        init = (
            "import globalPluginHandler\n"
            "import addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .gmail_service import GmailService\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        gmail_service = "from .gmail_oauth import get_credentials\n"
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "gmail_service.py": gmail_service,
            # gmail_oauth.py AUSENTE
        })
        problems = validate_addon_structure(addon)
        erros_009 = [p for p in problems if "ESTRUTURA-009" in p]
        assert len(erros_009) >= 1, f"Esperava ESTRUTURA-009, obteve: {problems}"
        assert "gmail_oauth" in erros_009[0]
        assert "gmail_service.py" in erros_009[0]

    def test_estrutura_009_modulo_relativo_presente_sem_erro(self, tmp_path):
        """Nenhum ESTRUTURA-009 quando o modulo importado existe."""
        init = (
            "import globalPluginHandler\n"
            "import addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .gmail_service import GmailService\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        gmail_service = "from .gmail_oauth import get_credentials\n"
        gmail_oauth = "def get_credentials(): pass\n"
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "gmail_service.py": gmail_service,
            "gmail_oauth.py": gmail_oauth,  # PRESENTE
        })
        problems = validate_addon_structure(addon)
        erros_009 = [p for p in problems if "ESTRUTURA-009" in p]
        assert erros_009 == [], f"ESTRUTURA-009 falso positivo: {erros_009}"

    def test_estrutura_009_imports_absolutos_ignorados(self, tmp_path):
        """Imports absolutos (sem ponto) nao sao checados pela regra 009."""
        init = (
            "import globalPluginHandler\n"
            "import addonHandler\n"
            "addonHandler.initTranslation()\n"
            "import requests\n"
            "import openai\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        addon = self._criar_addon(tmp_path, {"__init__.py": init})
        problems = validate_addon_structure(addon)
        erros_009 = [p for p in problems if "ESTRUTURA-009" in p]
        assert erros_009 == [], "Imports absolutos nao devem gerar ESTRUTURA-009"

    def test_estrutura_009_mensagem_contem_modulo_e_arquivo(self, tmp_path):
        """A mensagem ESTRUTURA-009 indica qual arquivo e qual modulo estao ausentes."""
        code = "from .modulo_inexistente import algo\n"
        addon = self._criar_addon(tmp_path, {
            "__init__.py": (
                "import globalPluginHandler\nimport addonHandler\n"
                "addonHandler.initTranslation()\n"
                "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
                "    def terminate(self): pass\n"
            ),
            "helper.py": code,
        })
        problems = validate_addon_structure(addon)
        erros_009 = [p for p in problems if "ESTRUTURA-009" in p]
        assert any("modulo_inexistente" in e for e in erros_009)
        assert any("helper.py" in e for e in erros_009)


class TestSanitizeManifestCamposProibidos:
    """Testes de remocao de campos proibidos em _sanitize_manifest (v2.7.0)."""

    def test_sha256_removido(self):
        manifest = (
            "name = GmailSummarizer\n"
            "version = 1.1.0\n"
            "sha256 = 4f4e5c434a434b4d4f4e5c434a434b4d\n"
            "minimumNVDAVersion = 2026.1.1\n"
        )
        result = _sanitize_manifest(manifest)
        assert "sha256" not in result, "sha256 deve ser removido do manifest"
        assert "name = GmailSummarizer" in result
        assert "version = 1.1.0" in result

    def test_configspec_removido(self):
        manifest = (
            "name = MeuAddon\n"
            "configSpec = [gmailResumo]\nemail = string(default='')\n"
            "version = 1.0.0\n"
        )
        result = _sanitize_manifest(manifest)
        assert "configSpec" not in result
        assert "configspec" not in result.lower()
        assert "name = MeuAddon" in result

    def test_sha256_case_insensitive_removido(self):
        manifest = "name = X\nSHA256 = abc123\nversion = 1.0.0\n"
        result = _sanitize_manifest(manifest)
        assert "SHA256" not in result

    def test_campos_normais_preservados_com_proibidos_presentes(self):
        manifest = (
            "name = TestAddon\n"
            "summary = Um addon.\n"
            "version = 1.0.0\n"
            "sha256 = deadbeef\n"
            "minimumNVDAVersion = 2026.1.1\n"
        )
        result = _sanitize_manifest(manifest)
        assert "name = TestAddon" in result
        assert "summary" in result
        assert "version = 1.0.0" in result
        assert "sha256" not in result

    def test_modulo_stdlib_ignorado_sem_pip(self, tmp_path):
        """os, sys, threading etc. nao devem ser passados ao pip (v2.0.0)."""
        from nvdastudio_mcp.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch
        with patch("subprocess.run") as mock_run:
            result = bundle_addon_dependencies(
                str(tmp_path), ["os", "sys", "threading", "json"], "meuAddon"
            )
        mock_run.assert_not_called()
        assert result == []

    def test_modulo_local_do_addon_ignorado_sem_pip(self, tmp_path):
        """Arquivo .py ja presente no addon nao deve ser passado ao pip (v2.0.0)."""
        from nvdastudio_mcp.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch
        # Cria estrutura do addon com um modulo local
        plugin_dir = tmp_path / "globalPlugins" / "meuAddon"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "settings_panel.py").write_text("# modulo local\n")
        (plugin_dir / "transcribe_dialog.py").write_text("# modulo local\n")

        with patch("subprocess.run") as mock_run:
            result = bundle_addon_dependencies(
                str(tmp_path), ["settings_panel", "transcribe_dialog"], "meuAddon"
            )
        mock_run.assert_not_called()
        assert result == []

    def test_pacote_externo_real_passa_para_pip(self, tmp_path):
        """Pacotes reais externos (openai, Pillow) devem chegar ao pip (v2.0.0)."""
        from nvdastudio_mcp.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch, MagicMock
        ok = MagicMock()
        ok.returncode = 0
        with patch("subprocess.run", return_value=ok) as mock_run:
            bundle_addon_dependencies(
                str(tmp_path), ["openai", "Pillow"], "meuAddon",
                _pypi_checker=lambda _pkg: True,
            )
        assert mock_run.call_count == 2

    def test_mistura_local_e_externo_so_externo_vai_ao_pip(self, tmp_path):
        """settings_panel (local) e openai (externo): so openai vai ao pip (v2.0.0)."""
        from nvdastudio_mcp.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch, MagicMock
        plugin_dir = tmp_path / "globalPlugins" / "meuAddon"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "settings_panel.py").write_text("# modulo local\n")

        ok = MagicMock()
        ok.returncode = 0
        with patch("subprocess.run", return_value=ok) as mock_run:
            bundle_addon_dependencies(
                str(tmp_path), ["settings_panel", "openai"], "meuAddon",
                _pypi_checker=lambda _pkg: True,
            )
        assert mock_run.call_count == 1
        # O argumento passado ao pip deve ser openai, nao settings_panel
        call_args = mock_run.call_args[0][0]  # cmd list
        assert "openai" in call_args
        assert "settings_panel" not in call_args


class TestValidateAddonStructureNVDA022:
    """Testes de validate_addon_structure() -- NVDA-022 (imports 3rd party nivel modulo)."""

    def _criar_addon(self, tmp_path, arquivos: dict) -> str:
        import os
        addon = str(tmp_path / "MeuAddon")
        plugin_dir = os.path.join(addon, "globalPlugins", "MeuAddon")
        os.makedirs(plugin_dir, exist_ok=True)
        with open(os.path.join(addon, "manifest.ini"), "w", encoding="utf-8") as f:
            f.write(
                "name = MeuAddon\nsummary = Teste.\nversion = 1.0.0\n"
                "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n"
            )
        os.makedirs(os.path.join(addon, "doc"), exist_ok=True)
        for relpath, conteudo in arquivos.items():
            dest = os.path.join(plugin_dir, relpath)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(conteudo)
        return addon

    def test_nvda022_import_nivel_modulo_detectado(self, tmp_path):
        """NVDA-022: from googleapiclient.discovery import build no topo detecta erro."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .gmail_service import GmailService\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        service = "from googleapiclient.discovery import build\n\nclass GmailService: pass\n"
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "gmail_service.py": service,
        })
        problems = validate_addon_structure(addon)
        erros_022 = [p for p in problems if "NVDA-022" in p]
        assert len(erros_022) >= 1, f"Esperava NVDA-022, obteve: {problems}"
        assert "googleapiclient" in erros_022[0]
        assert "gmail_service.py" in erros_022[0]

    def test_nvda022_lazy_import_dentro_metodo_sem_erro(self, tmp_path):
        """Imports 3rd party dentro de metodos (lazy) nao devem gerar NVDA-022."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .gmail_service import GmailService\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        service = (
            "import threading\n"
            "\nclass GmailService:\n"
            "    def _build(self):\n"
            "        from googleapiclient.discovery import build  # lazy\n"
            "        return build('gmail', 'v1')\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "gmail_service.py": service,
        })
        problems = validate_addon_structure(addon)
        erros_022 = [p for p in problems if "NVDA-022" in p]
        assert erros_022 == [], f"NVDA-022 falso positivo com lazy import: {erros_022}"

    def test_nvda022_stdlib_ignorado(self, tmp_path):
        """threading, os, sys, typing em nivel de modulo nao geram NVDA-022."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        service = (
            "import threading\nimport os\nimport sys\n"
            "from typing import List\n\nclass MeuService: pass\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "meu_service.py": service,
        })
        problems = validate_addon_structure(addon)
        erros_022 = [p for p in problems if "NVDA-022" in p]
        assert erros_022 == [], f"stdlib nao deve gerar NVDA-022: {erros_022}"

    def test_nvda022_init_py_excluido_da_verificacao(self, tmp_path):
        """__init__.py nao e verificado pela regra NVDA-022 (importa servicos legalmente)."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .gmail_service import GmailService\n"
            "import requests  # no __init__.py (excluido da NVDA-022)\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        service = "class GmailService: pass\n"
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "gmail_service.py": service,
        })
        problems = validate_addon_structure(addon)
        erros_022 = [p for p in problems if "NVDA-022" in p]
        assert erros_022 == [], "__init__.py nao deve gerar NVDA-022"

    def test_nvda022_mensagem_sugere_lazy_import(self, tmp_path):
        """A mensagem NVDA-022 explica como corrigir com lazy import."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        service = "import openai\nclass Sumarizador: pass\n"
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "sumarizador.py": service,
        })
        problems = validate_addon_structure(addon)
        erros_022 = [p for p in problems if "NVDA-022" in p]
        assert len(erros_022) >= 1
        msg = erros_022[0]
        assert "openai" in msg
        assert "sumarizador.py" in msg

    def test_nvda022_nvda_module_camelcase_nao_e_falso_positivo(self, tmp_path):
        """NVDA-022 nao deve disparar para addonHandler, globalPluginHandler (camelCase NVDA)."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        # ai_runner.py com import addonHandler em nivel de modulo — modulo NVDA nativo
        runner = (
            "import addonHandler\n"
            "import globalPluginHandler\n"
            "import scriptHandler\n"
            "class AIRunner: pass\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "ai_runner.py": runner,
        })
        problems = validate_addon_structure(addon)
        erros_022 = [p for p in problems if "NVDA-022" in p]
        assert erros_022 == [], (
            "Modulos NVDA camelCase (addonHandler, etc.) nao devem gerar NVDA-022: "
            + str(erros_022)
        )

    def test_nvda022_nvdahelper_nao_e_falso_positivo(self, tmp_path):
        """NVDA-022: nvdaHelper (extensao C interna do NVDA) nao deve gerar aviso."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        service = (
            "import nvdaHelper\n"
            "from nvdaHelper import nvdaState\n"
            "class NvdaService: pass\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "nvda_service.py": service,
        })
        problems = validate_addon_structure(addon)
        erros_022 = [p for p in problems if "NVDA-022" in p]
        assert erros_022 == [], (
            "nvdaHelper e modulo NVDA interno, nao deve gerar NVDA-022: "
            + str(erros_022)
        )

    def test_nvda022_webbrowser_stdlib_nao_e_falso_positivo(self, tmp_path):
        """NVDA-022: webbrowser (stdlib) em nivel de modulo nao gera aviso."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        service = (
            "import webbrowser\n"
            "import email\n"
            "import html\n"
            "import platform\n"
            "class BrowserService: pass\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "browser_service.py": service,
        })
        problems = validate_addon_structure(addon)
        erros_022 = [p for p in problems if "NVDA-022" in p]
        assert erros_022 == [], (
            "Modulos stdlib (webbrowser, email, html, platform) nao devem gerar NVDA-022: "
            + str(erros_022)
        )


class TestValidateAddonStructureNVDA023:
    """Testes de validate_addon_structure() -- NVDA-023 (type annotation com tipo lazy)."""

    def _criar_addon(self, tmp_path, arquivos: dict) -> str:
        import os
        addon = str(tmp_path / "MeuAddon")
        plugin_dir = os.path.join(addon, "globalPlugins", "MeuAddon")
        os.makedirs(plugin_dir, exist_ok=True)
        with open(os.path.join(addon, "manifest.ini"), "w", encoding="utf-8") as f:
            f.write(
                "name = MeuAddon\nsummary = Teste.\nversion = 1.0.0\n"
                "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n"
            )
        os.makedirs(os.path.join(addon, "doc"), exist_ok=True)
        for relpath, conteudo in arquivos.items():
            dest = os.path.join(plugin_dir, relpath)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(conteudo)
        return addon

    def test_nvda023_bare_annotation_de_tipo_lazy_detectado(self, tmp_path):
        """NVDA-023: -> Credentials com Credentials apenas em import lazy gera erro."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .oauth import get_credentials\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        oauth = (
            "import os\n"
            "from typing import Optional\n"
            "\n"
            "def get_credentials() -> Credentials:\n"  # bare annotation — tipo nao importado a nivel de modulo
            "    from google.oauth2.credentials import Credentials  # lazy\n"
            "    return Credentials()\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "oauth.py": oauth,
        })
        problems = validate_addon_structure(addon)
        erros_023 = [p for p in problems if "NVDA-023" in p]
        assert len(erros_023) >= 1, f"Esperava NVDA-023, obteve: {problems}"
        assert "Credentials" in erros_023[0]
        assert "oauth.py" in erros_023[0]

    def test_nvda023_string_literal_annotation_sem_erro(self, tmp_path):
        """String literal -> 'Credentials' (forward reference) nao deve gerar NVDA-023."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .oauth import get_credentials\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        oauth = (
            "import os\n"
            "\n"
            "def get_credentials() -> 'Credentials':\n"  # string literal — correto (NVDA-023)
            "    from google.oauth2.credentials import Credentials  # lazy\n"
            "    return Credentials()\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "oauth.py": oauth,
        })
        problems = validate_addon_structure(addon)
        erros_023 = [p for p in problems if "NVDA-023" in p]
        assert erros_023 == [], f"String literal nao deve gerar NVDA-023: {erros_023}"

    def test_nvda023_tipo_importado_a_nivel_de_modulo_sem_erro(self, tmp_path):
        """Quando o tipo e importado a nivel de modulo, annotation direta e valida."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .service import transcrever\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        service = (
            "from typing import Optional\n"
            "\n"
            "def transcrever(texto: Optional[str]) -> str:\n"  # Optional importado no modulo
            "    return texto or ''\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "service.py": service,
        })
        problems = validate_addon_structure(addon)
        erros_023 = [p for p in problems if "NVDA-023" in p]
        assert erros_023 == [], f"Tipo no modulo nao deve gerar NVDA-023: {erros_023}"

    def test_nvda023_sem_annotation_de_retorno_sem_erro(self, tmp_path):
        """Funcao sem annotation de retorno nao deve gerar NVDA-023."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "from .oauth import get_credentials\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        oauth = (
            "import os\n"
            "\n"
            "def get_credentials():\n"  # sem annotation — igualmente valido
            "    from google.oauth2.credentials import Credentials  # lazy\n"
            "    return Credentials()\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": init,
            "oauth.py": oauth,
        })
        problems = validate_addon_structure(addon)
        erros_023 = [p for p in problems if "NVDA-023" in p]
        assert erros_023 == [], f"Sem annotation nao deve gerar NVDA-023: {erros_023}"




class TestValidateAddonStructureNVDA024:
    """NVDA-024: categoryClasses.append() sem guard causa painel duplicado."""

    def _criar_addon(self, tmp_path, files: dict) -> str:
        """Helper: cria estrutura minima de addon em tmp_path."""
        plugin_dir = tmp_path / "globalPlugins" / "meuAddon"
        plugin_dir.mkdir(parents=True)
        manifest = tmp_path / "manifest.ini"
        manifest.write_text(
            "[add-on]\naddonId=meuAddon\naddonSummary=Teste\naddonVersion=1.0.0\n"
            "addonAuthor=Teste\nminimumNVDAVersion=2023.1\nlastTestedNVDAVersion=2025.3\n"
        )
        for name, content in files.items():
            (plugin_dir / name).write_text(content)
        return str(tmp_path)

    def test_nvda024_append_sem_guard_detectado(self, tmp_path):
        """append() incondicional em categoryClasses deve gerar NVDA-024."""
        init = (
            "import globalPluginHandler, addonHandler, gui\n"
            "from gui.settingsDialogs import NVDASettingsDialog\n"
            "from .panel import MeuPanel\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def __init__(self, *args, **kwargs):\n"
            "        super().__init__(*args, **kwargs)\n"
            "        NVDASettingsDialog.categoryClasses.append(MeuPanel)\n"
            "    def terminate(self):\n"
            "        super().terminate()\n"
            "        if MeuPanel in NVDASettingsDialog.categoryClasses:\n"
            "            NVDASettingsDialog.categoryClasses.remove(MeuPanel)\n"
        )
        addon = self._criar_addon(tmp_path, {"__init__.py": init})
        problems = validate_addon_structure(addon)
        erros_024 = [p for p in problems if "NVDA-024" in p]
        assert len(erros_024) >= 1, f"Esperava NVDA-024 mas nao encontrou: {problems}"
        assert "MeuPanel" in erros_024[0]

    def test_nvda024_append_com_guard_sem_erro(self, tmp_path):
        """append() com guard 'if Panel not in' nao deve gerar NVDA-024."""
        init = (
            "import globalPluginHandler, addonHandler, gui\n"
            "from gui.settingsDialogs import NVDASettingsDialog\n"
            "from .panel import MeuPanel\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def __init__(self, *args, **kwargs):\n"
            "        super().__init__(*args, **kwargs)\n"
            "        if MeuPanel not in NVDASettingsDialog.categoryClasses:\n"
            "            NVDASettingsDialog.categoryClasses.append(MeuPanel)\n"
            "    def terminate(self):\n"
            "        super().terminate()\n"
            "        if MeuPanel in NVDASettingsDialog.categoryClasses:\n"
            "            NVDASettingsDialog.categoryClasses.remove(MeuPanel)\n"
        )
        addon = self._criar_addon(tmp_path, {"__init__.py": init})
        problems = validate_addon_structure(addon)
        erros_024 = [p for p in problems if "NVDA-024" in p]
        assert erros_024 == [], f"Guard correto nao deve gerar NVDA-024: {erros_024}"

    def test_nvda024_sem_settings_panel_sem_erro(self, tmp_path):
        """Addon sem settings panel nao deve gerar NVDA-024."""
        init = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        addon = self._criar_addon(tmp_path, {"__init__.py": init})
        problems = validate_addon_structure(addon)
        erros_024 = [p for p in problems if "NVDA-024" in p]
        assert erros_024 == [], f"Sem panel nao deve gerar NVDA-024: {erros_024}"


class TestValidateAddonStructureNVDA025:
    """NVDA-025: config.conf com secao generica causa colisao entre addons."""

    def _criar_addon(self, tmp_path, py_files: dict, addon_id: str = "MeuAddonReal") -> str:
        """Helper: cria addon com manifest.ini contendo addonId especifico."""
        plugin_dir = tmp_path / "globalPlugins" / addon_id
        plugin_dir.mkdir(parents=True)
        manifest = tmp_path / "manifest.ini"
        manifest.write_text(
            f"[add-on]\naddonId={addon_id}\naddonSummary=Teste\naddonVersion=1.0.0\n"
            "addonAuthor=Teste\nminimumNVDAVersion=2023.1\nlastTestedNVDAVersion=2025.3\n"
        )
        for name, content in py_files.items():
            (plugin_dir / name).write_text(content)
        return str(tmp_path)

    def test_nvda025_placeholder_meuaddon_detectado(self, tmp_path):
        """config.conf['meuAddon'] deve gerar NVDA-025."""
        init = (
            "import globalPluginHandler, addonHandler, config\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): pass\n"
        )
        panel = (
            "import wx, config\n"
            "from gui.settingsDialogs import SettingsPanel\n"
            "class TestPanel(SettingsPanel):\n"
            "    title = 'Teste'\n"
            "    def makeSettings(self, sizer):\n"
            "        self._v = config.conf['meuAddon'].get('key', '')\n"
            "    def onSave(self):\n"
            "        config.conf['meuAddon']['key'] = ''\n"
        )
        addon = self._criar_addon(tmp_path, {"__init__.py": init, "panel.py": panel})
        problems = validate_addon_structure(addon)
        erros_025 = [p for p in problems if "NVDA-025" in p]
        assert len(erros_025) >= 1, f"Esperava NVDA-025 para placeholder 'meuAddon': {problems}"
        assert "meuAddon" in erros_025[0]

    def test_nvda025_placeholder_addonidreal_detectado(self, tmp_path):
        """config.conf['addonIdReal'] (nosso placeholder novo) deve gerar NVDA-025."""
        panel = (
            "import wx, config\n"
            "from gui.settingsDialogs import SettingsPanel\n"
            "class TestPanel(SettingsPanel):\n"
            "    title = 'Teste'\n"
            "    def makeSettings(self, sizer):\n"
            "        self._v = config.conf['addonIdReal'].get('key', '')\n"
            "    def onSave(self):\n"
            "        config.conf['addonIdReal']['key'] = ''\n"
        )
        addon = self._criar_addon(tmp_path, {"__init__.py": "import globalPluginHandler, addonHandler\naddonHandler.initTranslation()\nclass GlobalPlugin(globalPluginHandler.GlobalPlugin):\n    def terminate(self): pass\n", "panel.py": panel})
        problems = validate_addon_structure(addon)
        erros_025 = [p for p in problems if "NVDA-025" in p]
        assert len(erros_025) >= 1, f"Esperava NVDA-025 para placeholder 'addonIdReal': {problems}"

    def test_nvda025_secao_correta_sem_erro(self, tmp_path):
        """config.conf com o addonId correto nao deve gerar NVDA-025."""
        panel = (
            "import wx, config\n"
            "from gui.settingsDialogs import SettingsPanel\n"
            "class TestPanel(SettingsPanel):\n"
            "    title = 'Teste'\n"
            "    def makeSettings(self, sizer):\n"
            "        self._v = config.conf['MeuAddonReal'].get('key', '')\n"
            "    def onSave(self):\n"
            "        config.conf['MeuAddonReal']['key'] = ''\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": "import globalPluginHandler, addonHandler\naddonHandler.initTranslation()\nclass GlobalPlugin(globalPluginHandler.GlobalPlugin):\n    def terminate(self): pass\n",
            "panel.py": panel,
        }, addon_id="MeuAddonReal")
        problems = validate_addon_structure(addon)
        erros_025 = [p for p in problems if "NVDA-025" in p]
        assert erros_025 == [], f"addonId correto nao deve gerar NVDA-025: {erros_025}"

    def test_nvda025_secao_errada_detectada(self, tmp_path):
        """config.conf com secao diferente do addonId deve gerar NVDA-025."""
        panel = (
            "import wx, config\n"
            "from gui.settingsDialogs import SettingsPanel\n"
            "class TestPanel(SettingsPanel):\n"
            "    title = 'Teste'\n"
            "    def makeSettings(self, sizer):\n"
            "        self._v = config.conf['outroAddon'].get('key', '')\n"
            "    def onSave(self):\n"
            "        config.conf['outroAddon']['key'] = ''\n"
        )
        addon = self._criar_addon(tmp_path, {
            "__init__.py": "import globalPluginHandler, addonHandler\naddonHandler.initTranslation()\nclass GlobalPlugin(globalPluginHandler.GlobalPlugin):\n    def terminate(self): pass\n",
            "panel.py": panel,
        }, addon_id="MeuAddonReal")
        problems = validate_addon_structure(addon)
        erros_025 = [p for p in problems if "NVDA-025" in p]
        assert len(erros_025) >= 1, f"Secao 'outroAddon' != 'MeuAddonReal' deve gerar NVDA-025: {problems}"
        assert "outroAddon" in erros_025[0]
        assert "MeuAddonReal" in erros_025[0]




# ===========================================================================
# ===========================================================================

class TestNvda047UrlVazio:
	"""Bug regressao: regex consumia newline e capturava version= da linha seguinte."""

	def test_url_vazio_reportado_com_mensagem_correta(self, tmp_path):
		addon = tmp_path / "addon"
		addon.mkdir()
		# Cria globalPlugins/x/__init__.py para nao disparar ESTRUTURA-004
		gp = addon / "globalPlugins" / "x"
		gp.mkdir(parents=True)
		(gp / "__init__.py").write_text(
			"import addonHandler\naddonHandler.initTranslation()\n"
			"import globalPluginHandler\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"  def terminate(self): pass\n",
			encoding="utf-8",
		)
		manifest = (
			"name = MeuAddon\n"
			"summary = teste\n"
			"description = d\n"
			"author = A\n"
			"url = \n"
			"version = 1.0.0\n"
			"minimumNVDAVersion = 2026.1.0\n"
			"lastTestedNVDAVersion = 2026.1.0\n"
		)
		(addon / "manifest.ini").write_text(manifest, encoding="utf-8")
		problems = validate_addon_structure(str(addon))
		nvda047 = [p for p in problems if p.startswith("NVDA-047")]
		assert len(nvda047) == 1, f"Esperado 1 NVDA-047, recebido: {nvda047}"
		# Mensagem antiga reportava 'version = 1.0.0' — agora reporta url vazio
		assert "vazio" in nvda047[0].lower()
		assert "version" not in nvda047[0]

	def test_url_http_sem_s_reportado_corretamente(self, tmp_path):
		addon = tmp_path / "addon"
		addon.mkdir()
		gp = addon / "globalPlugins" / "x"
		gp.mkdir(parents=True)
		(gp / "__init__.py").write_text(
			"import addonHandler\naddonHandler.initTranslation()\n"
			"import globalPluginHandler\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"  def terminate(self): pass\n",
			encoding="utf-8",
		)
		manifest = (
			"name = MeuAddon\n"
			"summary = teste\n"
			"description = d\n"
			"author = A\n"
			"url = http://example.com\n"
			"version = 1.0.0\n"
			"minimumNVDAVersion = 2026.1.0\n"
			"lastTestedNVDAVersion = 2026.1.0\n"
		)
		(addon / "manifest.ini").write_text(manifest, encoding="utf-8")
		problems = validate_addon_structure(str(addon))
		nvda047 = [p for p in problems if p.startswith("NVDA-047")]
		assert len(nvda047) == 1
		assert "http://example.com" in nvda047[0]
		assert "https" in nvda047[0].lower()

	def test_url_https_valido_nao_reporta(self, tmp_path):
		addon = tmp_path / "addon"
		addon.mkdir()
		gp = addon / "globalPlugins" / "x"
		gp.mkdir(parents=True)
		(gp / "__init__.py").write_text(
			"import addonHandler\naddonHandler.initTranslation()\n"
			"import globalPluginHandler\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"  def terminate(self): pass\n",
			encoding="utf-8",
		)
		manifest = (
			"name = MeuAddon\n"
			"summary = teste\n"
			"description = d\n"
			"author = A\n"
			"url = https://github.com/me/addon\n"
			"version = 1.0.0\n"
			"minimumNVDAVersion = 2026.1.0\n"
			"lastTestedNVDAVersion = 2026.1.0\n"
		)
		(addon / "manifest.ini").write_text(manifest, encoding="utf-8")
		problems = validate_addon_structure(str(addon))
		nvda047 = [p for p in problems if p.startswith("NVDA-047")]
		assert nvda047 == []


class TestPathTraversalComFronteiraDeDiretorio:
    # sem exigir fronteira de separador -- uma pasta irma cujo nome comeca com o
    # mesmo prefixo (ex: testAddonExtra vs testAddon) passava no startswith().
    # Fix: compara contra addon_folder + os.sep.

    def test_bloqueia_escrita_em_pasta_irma_com_nome_prefixado(self, tmp_path):
        """addon_name='testAddon' + filename com ../ tentando escrever em
        testAddonExtra (pasta irma cujo nome comeca com testAddon).
        """
        blocks = [
            {"filename": "manifest.ini", "code": "name = testAddon\n", "language": "ini"},
            {
                "filename": "../testAddonExtra/evil.py",
                "code": "# nao deveria ser escrito fora de addon_folder\n",
                "language": "python",
            },
        ]
        folder, saved = save_addon_files(
            blocks, str(tmp_path), "testAddon", use_timestamp=False
        )
        evil_path = os.path.join(str(tmp_path), "testAddonExtra", "evil.py")
        assert not os.path.exists(evil_path)
        for p in saved:
            assert p.startswith(folder + os.sep) or p == folder
