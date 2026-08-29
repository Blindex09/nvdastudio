import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MANIFEST_INI = """name = GmailSummarizer
summary = Addon que testa import relativo orfao
author = Tester <test@example.com>
version = 1.0.0
minimumNVDAVersion = 2026.1.1
lastTestedNVDAVersion = 2026.1.1
"""

# __init__.py importa gmail_service.py que existe — OK
# gmail_service.py importa gmail_oauth.py que NAO existe — ESTRUTURA-009
_INIT_PY = """import globalPluginHandler
import addonHandler
from .gmail_service import GmailService
addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super().__init__()
		self._svc = GmailService()

	def terminate(self):
		super().terminate()
"""

_GMAIL_SERVICE_PY = """from .gmail_oauth import get_credentials


class GmailService:
	def __init__(self):
		self._creds = None

	def connect(self):
		self._creds = get_credentials()
"""

# Versao corrigida de gmail_service que nao importa modulo orfao
_GMAIL_SERVICE_OK_PY = """class GmailService:
	def __init__(self):
		self._creds = None

	def connect(self):
		pass
"""

_GMAIL_OAUTH_PY = """def get_credentials():
	return None
"""

_USER_GUIDE_HTML = """<!DOCTYPE html>
<html lang="pt">
<head><meta charset="utf-8"><title>Gmail Guide</title></head>
<body><h1>GmailSummarizer</h1><p>Addon para teste E5.</p></body>
</html>
"""


def _make_blocks_com_orfao():
	"""Addon com gmail_service.py que importa gmail_oauth.py inexistente."""
	return [
		{"language": "ini",    "filename": "manifest.ini",                                    "code": _MANIFEST_INI},
		{"language": "python", "filename": "globalPlugins/GmailSummarizer/__init__.py",       "code": _INIT_PY},
		{"language": "python", "filename": "globalPlugins/GmailSummarizer/gmail_service.py", "code": _GMAIL_SERVICE_PY},
		{"language": "html",   "filename": "doc/en/userGuide.html",                           "code": _USER_GUIDE_HTML},
	]


def _make_blocks_completo():
	"""Addon com gmail_service.py + gmail_oauth.py — sem orfao."""
	return [
		{"language": "ini",    "filename": "manifest.ini",                                    "code": _MANIFEST_INI},
		{"language": "python", "filename": "globalPlugins/GmailSummarizer/__init__.py",       "code": _INIT_PY},
		{"language": "python", "filename": "globalPlugins/GmailSummarizer/gmail_service.py", "code": _GMAIL_SERVICE_PY},
		{"language": "python", "filename": "globalPlugins/GmailSummarizer/gmail_oauth.py",   "code": _GMAIL_OAUTH_PY},
		{"language": "html",   "filename": "doc/en/userGuide.html",                           "code": _USER_GUIDE_HTML},
	]


def _make_blocks_sem_orfao():
	"""Addon onde gmail_service.py nao faz import relativo orfao."""
	return [
		{"language": "ini",    "filename": "manifest.ini",                                    "code": _MANIFEST_INI},
		{"language": "python", "filename": "globalPlugins/GmailSummarizer/__init__.py",       "code": _INIT_PY},
		{"language": "python", "filename": "globalPlugins/GmailSummarizer/gmail_service.py", "code": _GMAIL_SERVICE_OK_PY},
		{"language": "html",   "filename": "doc/en/userGuide.html",                           "code": _USER_GUIDE_HTML},
	]


# ---------------------------------------------------------------------------
# E5 — Cenario: import relativo orfao
# ---------------------------------------------------------------------------

class TestE5ImportRelativoOrfao:
	"""
	Regressao do bug de producao do GmailSummarizer:
	from .gmail_oauth import sem gmail_oauth.py presente deve disparar ESTRUTURA-009.
	"""

	def test_import_orfao_dispara_estrutura009(self, tmp_path):
		"""
		`from .gmail_oauth import ...` sem gmail_oauth.py deve resultar em
		ESTRUTURA-009 no validate.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		addon_folder, _ = save_addon_files(
			_make_blocks_com_orfao(), str(tmp_path), "GmailSummarizer", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		e009 = [p for p in problems if "ESTRUTURA-009" in p]
		assert len(e009) >= 1, (
			f"Import relativo orfao deve disparar ESTRUTURA-009. Problemas: {problems}"
		)
		assert "gmail_oauth" in e009[0], (
			f"ESTRUTURA-009 deve mencionar o modulo ausente. Mensagem: {e009[0]}"
		)

	def test_addon_completo_sem_orfaos_passa_limpo(self, tmp_path):
		"""
		Quando gmail_oauth.py existe, ESTRUTURA-009 nao deve ser reportado.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		addon_folder, _ = save_addon_files(
			_make_blocks_completo(), str(tmp_path), "GmailSummarizer", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		e009 = [p for p in problems if "ESTRUTURA-009" in p]
		assert e009 == [], (
			f"Addon completo (todos os modulos presentes) nao deve ter ESTRUTURA-009. "
			f"Problemas: {problems}"
		)

	def test_estrutura009_menciona_arquivo_origem(self, tmp_path):
		"""
		A mensagem de ESTRUTURA-009 deve mencionar o arquivo que faz o import orfao.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		addon_folder, _ = save_addon_files(
			_make_blocks_com_orfao(), str(tmp_path), "GmailSummarizer", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		e009 = [p for p in problems if "ESTRUTURA-009" in p]
		assert any("gmail_service" in p for p in e009), (
			f"ESTRUTURA-009 deve mencionar o arquivo origem do import. Mensagem: {e009}"
		)

	def test_import_de_subpacote_nao_dispara_falso_positivo(self, tmp_path):
		"""
		Regressao do teste E2E real de 2026-08-04 (Ollama, addon AcoesRapidasSeguras):
		`from .apps import X` onde apps/ e um SUBPACOTE (apps/__init__.py), nao um
		arquivo apps.py solto, e um padrao Python valido e NAO deve disparar
		ESTRUTURA-009.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		init_py = """import globalPluginHandler
import addonHandler
from .apps import AppLauncher
addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super().__init__()
		self._launcher = AppLauncher()

	def terminate(self):
		super().terminate()
"""
		apps_init_py = "from .app_launcher import AppLauncher\n"
		app_launcher_py = "class AppLauncher:\n\tdef abrir(self):\n\t\tpass\n"

		blocks = [
			{"language": "ini", "filename": "manifest.ini", "code": _MANIFEST_INI},
			{"language": "python", "filename": "globalPlugins/AcoesRapidas/__init__.py", "code": init_py},
			{"language": "python", "filename": "globalPlugins/AcoesRapidas/apps/__init__.py", "code": apps_init_py},
			{"language": "python", "filename": "globalPlugins/AcoesRapidas/apps/app_launcher.py", "code": app_launcher_py},
			{"language": "html", "filename": "doc/en/userGuide.html", "code": _USER_GUIDE_HTML},
		]

		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AcoesRapidas", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		e009 = [p for p in problems if "ESTRUTURA-009" in p]
		assert e009 == [], (
			f"Subpacote apps/__init__.py deve satisfazer 'from .apps import ...'. Problemas: {e009}"
		)
