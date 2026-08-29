import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MANIFEST_INI = """name = GmailAddon
summary = Addon que testa NVDA-022
author = Tester <test@example.com>
version = 1.0.0
minimumNVDAVersion = 2026.1.1
lastTestedNVDAVersion = 2026.1.1
"""

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

# Import 3rd-party em nivel de modulo — NVDA-022
_GMAIL_SERVICE_COM_NVDA022 = """import google.auth
import google.auth.transport.requests


class GmailService:
	def __init__(self):
		self._creds = None

	def connect(self):
		request = google.auth.transport.requests.Request()
		self._creds = google.auth.default(request=request)
"""

# Import lazy dentro do metodo — correto
_GMAIL_SERVICE_LAZY = """class GmailService:
	def __init__(self):
		self._creds = None

	def connect(self):
		import google.auth
		import google.auth.transport.requests
		request = google.auth.transport.requests.Request()
		self._creds = google.auth.default(request=request)
"""

_USER_GUIDE_HTML = """<!DOCTYPE html>
<html lang="pt">
<head><meta charset="utf-8"><title>Gmail Guide</title></head>
<body><h1>GmailAddon</h1><p>Addon para teste E6.</p></body>
</html>
"""


def _make_blocks_com_nvda022():
	return [
		{"language": "ini",    "filename": "manifest.ini",                               "code": _MANIFEST_INI},
		{"language": "python", "filename": "globalPlugins/GmailAddon/__init__.py",       "code": _INIT_PY},
		{"language": "python", "filename": "globalPlugins/GmailAddon/gmail_service.py", "code": _GMAIL_SERVICE_COM_NVDA022},
		{"language": "html",   "filename": "doc/en/userGuide.html",                      "code": _USER_GUIDE_HTML},
	]


def _make_blocks_lazy():
	return [
		{"language": "ini",    "filename": "manifest.ini",                               "code": _MANIFEST_INI},
		{"language": "python", "filename": "globalPlugins/GmailAddon/__init__.py",       "code": _INIT_PY},
		{"language": "python", "filename": "globalPlugins/GmailAddon/gmail_service.py", "code": _GMAIL_SERVICE_LAZY},
		{"language": "html",   "filename": "doc/en/userGuide.html",                      "code": _USER_GUIDE_HTML},
	]


# ---------------------------------------------------------------------------
# E6 — Cenario: NVDA-022 import 3rd-party em nivel de modulo
# ---------------------------------------------------------------------------

class TestE6Nvda022ImportNivelModulo:
	"""
	Regressao do root cause do GmailSummarizer.
	"""

	def test_import_nivel_modulo_dispara_nvda022(self, tmp_path):
		"""
		`import google.auth` no topo de gmail_service.py (nivel de modulo)
		deve disparar NVDA-022.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		addon_folder, _ = save_addon_files(
			_make_blocks_com_nvda022(), str(tmp_path), "GmailAddon", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		nvda022 = [p for p in problems if "NVDA-022" in p]
		assert len(nvda022) >= 1, (
			f"Import 3rd-party em nivel de modulo deve disparar NVDA-022. "
			f"Problemas: {problems}"
		)

	def test_nvda022_menciona_nome_do_import(self, tmp_path):
		"""
		A mensagem de NVDA-022 deve mencionar o import problemático.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		addon_folder, _ = save_addon_files(
			_make_blocks_com_nvda022(), str(tmp_path), "GmailAddon", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		nvda022 = [p for p in problems if "NVDA-022" in p]
		assert any("google" in p for p in nvda022), (
			f"NVDA-022 deve mencionar o modulo google. Mensagem: {nvda022}"
		)

	def test_import_lazy_nao_dispara_nvda022(self, tmp_path):
		"""
		Import dentro do metodo (lazy) nao deve disparar NVDA-022.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		addon_folder, _ = save_addon_files(
			_make_blocks_lazy(), str(tmp_path / "lazy"), "GmailAddon", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		nvda022 = [p for p in problems if "NVDA-022" in p]
		assert nvda022 == [], (
			f"Import lazy (dentro de metodo) nao deve disparar NVDA-022. "
			f"Problemas: {problems}"
		)
