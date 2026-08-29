import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MANIFEST_INI = """name = AddonMinimo
summary = Addon minimo para testes E1
author = Tester <test@example.com>
version = 1.0.0
minimumNVDAVersion = 2026.1.1
lastTestedNVDAVersion = 2026.2.0
"""

_INIT_PY = """import globalPluginHandler
import addonHandler
import ui
addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self, *args, **kwargs):
		# Translators: mensagem de inicializacao.
		super().__init__(*args, **kwargs)

	def terminate(self, *args, **kwargs):
		super().terminate(*args, **kwargs)
"""

_USER_GUIDE_HTML = """<!DOCTYPE html>
<html lang="pt">
<head><meta charset="utf-8"><title>AddonMinimo User Guide</title></head>
<body><h1>AddonMinimo</h1><p>Addon minimo para testes E1.</p></body>
</html>
"""


def _make_blocks():
	return [
		{"language": "ini",    "filename": "manifest.ini",                               "code": _MANIFEST_INI},
		{"language": "python", "filename": "globalPlugins/AddonMinimo/__init__.py",      "code": _INIT_PY},
		{"language": "html",   "filename": "doc/en/userGuide.html",                      "code": _USER_GUIDE_HTML},
	]


# ---------------------------------------------------------------------------
# E1 — Cenario: addon minimo sem erros
# ---------------------------------------------------------------------------

class TestE1AddonMinimo:
	"""
	Pipeline completo de um addon minimo e correto.
	Nenhum problema deve ser reportado pelo validador.
	"""

	def test_pipeline_sem_problemas(self, tmp_path):
		"""
		Happy path: save -> validate -> package sem nenhum problema.
		"""
		from nvdastudio.builder.addon_builder import (
			save_addon_files, validate_addon_structure, package_addon,
		)

		addon_folder, saved = save_addon_files(
			_make_blocks(), str(tmp_path), "AddonMinimo", use_timestamp=False,
		)

		assert os.path.isfile(os.path.join(addon_folder, "manifest.ini"))
		assert os.path.isfile(
			os.path.join(addon_folder, "globalPlugins", "AddonMinimo", "__init__.py")
		)

		problems = validate_addon_structure(addon_folder)
		assert problems == [], (
			f"Addon minimo correto nao deve ter problemas. Encontrados: {problems}"
		)

		pkg = package_addon(addon_folder)
		assert os.path.isfile(pkg)
		assert pkg.endswith(".nvda-addon")

		with zipfile.ZipFile(pkg) as zf:
			names = zf.namelist()
		assert "manifest.ini" in names
		assert any("__init__.py" in n for n in names)

	def test_validate_retorna_lista_vazia(self, tmp_path):
		"""
		validate_addon_structure deve retornar [] para addon correto.
		Garante que o tipo de retorno nao quebra chamadores que fazem `if problems`.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		addon_folder, _ = save_addon_files(
			_make_blocks(), str(tmp_path), "AddonMinimo", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		assert isinstance(problems, list)
		assert len(problems) == 0

	def test_nvda_addon_e_zip_valido(self, tmp_path):
		"""
		O .nvda-addon gerado deve ser um ZIP valido que o Python consegue abrir.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, package_addon

		addon_folder, _ = save_addon_files(
			_make_blocks(), str(tmp_path), "AddonMinimo", use_timestamp=False,
		)
		pkg = package_addon(addon_folder)
		assert zipfile.is_zipfile(pkg), f"O .nvda-addon deve ser um ZIP valido: {pkg}"
