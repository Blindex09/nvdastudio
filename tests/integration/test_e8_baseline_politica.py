import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Manifest com versao legada (abaixo de 2026.1.1)
_MANIFEST_LEGADO = """name = AddonLegado
summary = Addon com versao legada abaixo do baseline
author = Tester <test@example.com>
version = 1.0.0
minimumNVDAVersion = 2019.3.0
lastTestedNVDAVersion = 2024.1.0
"""

# Manifest correto (no baseline)
_MANIFEST_BASELINE = """name = AddonBaseline
summary = Addon com versao no baseline oficial
author = Tester <test@example.com>
version = 1.0.0
minimumNVDAVersion = 2026.1.1
lastTestedNVDAVersion = 2026.2.0
"""

_INIT_PY = """import globalPluginHandler
import addonHandler
addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self):
		super().__init__()

	def terminate(self):
		super().terminate()
"""

_USER_GUIDE_HTML = """<!DOCTYPE html>
<html lang="pt">
<head><meta charset="utf-8"><title>Guide</title></head>
<body><h1>Addon</h1><p>Addon para teste E8.</p></body>
</html>
"""


def _make_blocks_legado():
	return [
		{"language": "ini",    "filename": "manifest.ini",                               "code": _MANIFEST_LEGADO},
		{"language": "python", "filename": "globalPlugins/AddonLegado/__init__.py",      "code": _INIT_PY},
		{"language": "html",   "filename": "doc/en/userGuide.html",                      "code": _USER_GUIDE_HTML},
	]


def _make_blocks_baseline():
	return [
		{"language": "ini",    "filename": "manifest.ini",                                 "code": _MANIFEST_BASELINE},
		{"language": "python", "filename": "globalPlugins/AddonBaseline/__init__.py",      "code": _INIT_PY},
		{"language": "html",   "filename": "doc/en/userGuide.html",                        "code": _USER_GUIDE_HTML},
	]


# ---------------------------------------------------------------------------
# E8 — Cenario: baseline / politica de versao
# ---------------------------------------------------------------------------

class TestE8BaselinePolitica:
	"""
	validate_addon_structure deve emitir POLITICA-001/002 para versoes
	abaixo do baseline oficial do projeto.
	"""

	def test_minimum_abaixo_do_baseline_gera_politica001(self, tmp_path):
		"""
		minimumNVDAVersion = 2019.3.0 deve disparar POLITICA-001.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		addon_folder, _ = save_addon_files(
			_make_blocks_legado(), str(tmp_path), "AddonLegado", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		p001 = [p for p in problems if "POLITICA-001" in p]
		assert len(p001) >= 1, (
			f"minimumNVDAVersion=2019.3.0 deve disparar POLITICA-001. "
			f"Problemas: {problems}"
		)
		assert "2019.3.0" in p001[0] or "baseline" in p001[0].lower()

	def test_last_tested_abaixo_do_baseline_gera_politica002(self, tmp_path):
		"""
		lastTestedNVDAVersion = 2024.1.0 deve disparar POLITICA-002.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		addon_folder, _ = save_addon_files(
			_make_blocks_legado(), str(tmp_path), "AddonLegado", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		p002 = [p for p in problems if "POLITICA-002" in p]
		assert len(p002) >= 1, (
			f"lastTestedNVDAVersion=2024.1.0 deve disparar POLITICA-002. "
			f"Problemas: {problems}"
		)

	def test_addon_com_baseline_correto_nao_dispara_politica(self, tmp_path):
		"""
		Addon com versoes no baseline oficial (2026.1.1) nao deve ter POLITICA-001
		nem POLITICA-002.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		addon_folder, _ = save_addon_files(
			_make_blocks_baseline(), str(tmp_path), "AddonBaseline", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		politica = [p for p in problems if "POLITICA-001" in p or "POLITICA-002" in p]
		assert politica == [], (
			f"Addon com baseline correto nao deve ter POLITICA. Problemas: {problems}"
		)

	def test_mensagem_politica001_menciona_baseline(self, tmp_path):
		"""
		A mensagem de POLITICA-001 deve mencionar o baseline oficial do projeto.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure
		from nvdastudio.utils.project_policy import PROJECT_MIN_NVDA

		addon_folder, _ = save_addon_files(
			_make_blocks_legado(), str(tmp_path), "AddonLegado", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		p001 = [p for p in problems if "POLITICA-001" in p]
		assert any(PROJECT_MIN_NVDA in p for p in p001), (
			f"POLITICA-001 deve mencionar o baseline {PROJECT_MIN_NVDA}. Mensagem: {p001}"
		)

