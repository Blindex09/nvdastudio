import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MANIFEST_INI = """name = AddonGestures
summary = Addon que testa deteccao de __gestures
author = Tester <test@example.com>
version = 1.0.0
minimumNVDAVersion = 2026.1.1
lastTestedNVDAVersion = 2026.1.1
"""

_INIT_PY_COM_GESTURES = """import globalPluginHandler
import addonHandler
import ui
addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super().__init__()

	def script_ola(self, gesture):
		# Translators: mensagem dita ao usuario.
		ui.message(_("Ola"))

	def terminate(self):
		super().terminate()

	__gestures = {
		"kb:nvda+shift+o": "ola",
	}
"""

_INIT_PY_CORRETO = """import globalPluginHandler
import addonHandler
import ui
import scriptHandler
addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super().__init__()

	@scriptHandler.script(
		# Translators: descricao do script para Input Help.
		description=_("Diz ola"),
		gesture="kb:nvda+shift+o",
	)
	def script_ola(self, gesture):
		# Translators: mensagem dita ao usuario.
		ui.message(_("Ola"))

	def terminate(self):
		super().terminate()
"""

_USER_GUIDE_HTML = """<!DOCTYPE html>
<html lang="pt">
<head><meta charset="utf-8"><title>Gestures Guide</title></head>
<body><h1>AddonGestures</h1><p>Addon para teste E4.</p></body>
</html>
"""


def _make_blocks_com_gestures():
	return [
		{"language": "ini",    "filename": "manifest.ini",                                "code": _MANIFEST_INI},
		{"language": "python", "filename": "globalPlugins/AddonGestures/__init__.py",    "code": _INIT_PY_COM_GESTURES},
		{"language": "html",   "filename": "doc/en/userGuide.html",                      "code": _USER_GUIDE_HTML},
	]


def _make_blocks_correto():
	return [
		{"language": "ini",    "filename": "manifest.ini",                                "code": _MANIFEST_INI},
		{"language": "python", "filename": "globalPlugins/AddonGestures/__init__.py",    "code": _INIT_PY_CORRETO},
		{"language": "html",   "filename": "doc/en/userGuide.html",                      "code": _USER_GUIDE_HTML},
	]


# ---------------------------------------------------------------------------
# E4 — Cenario: __gestures detectado / @script correto passa limpo
# ---------------------------------------------------------------------------

class TestE4Nvda007Gestures:
	"""
	validate_addon_structure (checklist deterministico) NAO deve mais
	disparar NVDA-007 por __gestures — julgamento contextual e do critic.py.
	"""

	def test_gestures_nao_dispara_nvda007_deterministico(self, tmp_path):
		"""
		Addon com __gestures dict NAO deve ter NVDA-007 no checklist
		deterministico (removido em 4.5.0 — ver critic.py para o julgamento contextual).
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		addon_folder, _ = save_addon_files(
			_make_blocks_com_gestures(), str(tmp_path), "AddonGestures", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		nvda007 = [p for p in problems if "NVDA-007" in p]
		assert nvda007 == [], (
			f"NVDA-007 nao deve mais vir do checklist deterministico. Problemas: {problems}"
		)

	def test_addon_com_script_decorator_passa_limpo(self, tmp_path):
		"""
		Addon correto (sem __gestures, com @script decorator) nao deve
		disparar NVDA-007.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		addon_folder, _ = save_addon_files(
			_make_blocks_correto(), str(tmp_path / "correto"), "AddonGestures", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		nvda007 = [p for p in problems if "NVDA-007" in p]
		assert nvda007 == [], (
			f"Addon com @script nao deve disparar NVDA-007. Problemas: {problems}"
		)
