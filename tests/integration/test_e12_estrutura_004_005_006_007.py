import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ---------------------------------------------------------------------------
# Fixtures comuns
# ---------------------------------------------------------------------------

_MANIFEST_OK = """name = AddonE12
summary = Addon para testes E12
author = Tester <test@example.com>
version = 1.0.0
minimumNVDAVersion = 2026.1.1
lastTestedNVDAVersion = 2026.1.1
"""

_INIT_COMPLETO = """\
import globalPluginHandler
import addonHandler
import ui
addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
\tdef __init__(self):
\t\tsuper().__init__()

\tdef terminate(self):
\t\tsuper().terminate()
"""

_INIT_SEM_CLASS = """\
import addonHandler
addonHandler.initTranslation()


def terminate():
\tpass

# Sem declaracao da classe principal do plugin
"""

_DOC_HTML = """\
<!DOCTYPE html>
<html lang="pt">
<head><meta charset="utf-8"><title>AddonE12</title></head>
<body><h1>AddonE12</h1><p>Guia do usuario.</p></body>
</html>
"""


# ---------------------------------------------------------------------------
# E12 — ESTRUTURA-004: nenhum .py em globalPlugins/
# ---------------------------------------------------------------------------

class TestE12Estrutura004:
	"""
	globalPlugins/ existe mas so contem arquivos nao-Python.
	O validador deve reportar ESTRUTURA-004.
	"""

	def test_sem_py_em_globalPlugins_gera_estrutura004(self, tmp_path):
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",  "filename": "manifest.ini",                              "code": _MANIFEST_OK},
			# globalPlugins/ tem apenas um readme.html — nenhum .py
			{"language": "html", "filename": "globalPlugins/AddonE12/readme.html",         "code": "<html></html>"},
			{"language": "html", "filename": "doc/en/userGuide.html",                      "code": _DOC_HTML},
		]
		addon_folder, _ = save_addon_files(blocks, str(tmp_path), "AddonE12", use_timestamp=False)

		problems = validate_addon_structure(addon_folder)
		assert any("ESTRUTURA-004" in p for p in problems), (
			f"ESTRUTURA-004 deveria ser detectado. Problemas: {problems}"
		)

	def test_estrutura004_nao_dispara_sem_py_fora_de_globalPlugins(self, tmp_path):
		"""
		__init__.py em globalPlugins/ garante que ESTRUTURA-004 NAO dispara —
		a presenca de pelo menos um .py e suficiente.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                             "code": _MANIFEST_OK},
			{"language": "python", "filename": "globalPlugins/AddonE12/__init__.py",       "code": _INIT_COMPLETO},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _DOC_HTML},
		]
		addon_folder, _ = save_addon_files(blocks, str(tmp_path), "AddonE12", use_timestamp=False)

		problems = validate_addon_structure(addon_folder)
		assert not any("ESTRUTURA-004" in p for p in problems), (
			f"ESTRUTURA-004 NAO deveria disparar com __init__.py presente. Problemas: {problems}"
		)


# ---------------------------------------------------------------------------
# E12 — ESTRUTURA-005: __init__.py sem GlobalPlugin nem AppModule
# ---------------------------------------------------------------------------

class TestE12Estrutura005:
	"""
	__init__.py existe mas nao declara class GlobalPlugin nem class AppModule.
	O validador deve reportar ESTRUTURA-005.
	"""

	def test_init_sem_globalPlugin_gera_estrutura005(self, tmp_path):
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                             "code": _MANIFEST_OK},
			{"language": "python", "filename": "globalPlugins/AddonE12/__init__.py",       "code": _INIT_SEM_CLASS},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _DOC_HTML},
		]
		addon_folder, _ = save_addon_files(blocks, str(tmp_path), "AddonE12", use_timestamp=False)

		problems = validate_addon_structure(addon_folder)
		assert any("ESTRUTURA-005" in p for p in problems), (
			f"ESTRUTURA-005 deveria ser detectado. Problemas: {problems}"
		)

	def test_init_sem_globalPlugin_nao_dispara_nvda003_004(self, tmp_path):
		"""
		_INIT_SEM_CLASS tem initTranslation e terminate — NVDA-003/004 NAO disparam.
		Apenas ESTRUTURA-005 e reportado.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                             "code": _MANIFEST_OK},
			{"language": "python", "filename": "globalPlugins/AddonE12/__init__.py",       "code": _INIT_SEM_CLASS},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _DOC_HTML},
		]
		addon_folder, _ = save_addon_files(blocks, str(tmp_path), "AddonE12", use_timestamp=False)

		problems = validate_addon_structure(addon_folder)
		assert not any("NVDA-003" in p for p in problems), (
			f"NVDA-003 nao deve disparar — initTranslation esta presente. Problemas: {problems}"
		)
		assert not any("NVDA-004" in p for p in problems), (
			f"NVDA-004 nao deve disparar — terminate() esta presente. Problemas: {problems}"
		)

	def test_init_com_globalPlugin_nao_gera_estrutura005(self, tmp_path):
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                             "code": _MANIFEST_OK},
			{"language": "python", "filename": "globalPlugins/AddonE12/__init__.py",       "code": _INIT_COMPLETO},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _DOC_HTML},
		]
		addon_folder, _ = save_addon_files(blocks, str(tmp_path), "AddonE12", use_timestamp=False)

		problems = validate_addon_structure(addon_folder)
		assert not any("ESTRUTURA-005" in p for p in problems), (
			f"ESTRUTURA-005 NAO deve disparar com class GlobalPlugin presente. Problemas: {problems}"
		)


# ---------------------------------------------------------------------------
# E12 — ESTRUTURA-006: pasta doc/ ausente
# ---------------------------------------------------------------------------

class TestE12Estrutura006:
	"""
	Addon correto estruturalmente mas sem pasta doc/.
	O validador deve reportar ESTRUTURA-006.
	"""

	def test_sem_doc_gera_estrutura006(self, tmp_path):
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                             "code": _MANIFEST_OK},
			{"language": "python", "filename": "globalPlugins/AddonE12/__init__.py",       "code": _INIT_COMPLETO},
			# Intencionalmente sem bloco doc/
		]
		addon_folder, _ = save_addon_files(blocks, str(tmp_path), "AddonE12", use_timestamp=False)

		problems = validate_addon_structure(addon_folder)
		assert any("ESTRUTURA-006" in p for p in problems), (
			f"ESTRUTURA-006 deveria ser detectado. Problemas: {problems}"
		)

	def test_com_doc_nao_gera_estrutura006(self, tmp_path):
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                             "code": _MANIFEST_OK},
			{"language": "python", "filename": "globalPlugins/AddonE12/__init__.py",       "code": _INIT_COMPLETO},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _DOC_HTML},
		]
		addon_folder, _ = save_addon_files(blocks, str(tmp_path), "AddonE12", use_timestamp=False)

		problems = validate_addon_structure(addon_folder)
		assert not any("ESTRUTURA-006" in p for p in problems), (
			f"ESTRUTURA-006 NAO deve disparar com doc/ presente. Problemas: {problems}"
		)


# ---------------------------------------------------------------------------
# E12 — ESTRUTURA-007: multiplas pastas de plugin com __init__.py
# ---------------------------------------------------------------------------

class TestE12Estrutura007:
	"""
	Duas pastas em globalPlugins/ cada uma com __init__.py — o NVDA carregaria
	dois GlobalPlugin simultaneamente causando conflito de atalhos.
	O validador deve reportar ESTRUTURA-007.

	Nota: save_addon_files() executa _deduplicate_blocks() internamente, que
	funde multiplos plugin dirs em um unico canonico — prevenindo ESTRUTURA-007
	no fluxo normal de geracao. Para testar o PATH DE FALHA do validador,
	cria-se a estrutura diretamente em disco (sem passar por save_addon_files).
	Isso representa acessos diretos ao addon_folder (ex: edicao manual, testes
	de regressao de fix_addon_structure).
	"""

	@staticmethod
	def _criar_addon_com_duas_pastas(tmp_path) -> str:
		"""Cria addon_folder com duas pastas de plugin diretamente em disco."""
		addon_folder = str(tmp_path / "AddonE12")
		for pasta in ("PluginA", "PluginB"):
			plugin_dir = os.path.join(addon_folder, "globalPlugins", pasta)
			os.makedirs(plugin_dir, exist_ok=True)
			with open(os.path.join(plugin_dir, "__init__.py"), "w", encoding="utf-8") as fh:
				fh.write(_INIT_COMPLETO)
		# manifest
		with open(os.path.join(addon_folder, "manifest.ini"), "w", encoding="utf-8") as fh:
			fh.write(_MANIFEST_OK)
		# doc/
		doc_dir = os.path.join(addon_folder, "doc", "en")
		os.makedirs(doc_dir, exist_ok=True)
		with open(os.path.join(doc_dir, "userGuide.html"), "w", encoding="utf-8") as fh:
			fh.write(_DOC_HTML)
		return addon_folder

	def test_multiplas_pastas_plugin_gera_estrutura007(self, tmp_path):
		from nvdastudio.builder.addon_builder import validate_addon_structure

		addon_folder = self._criar_addon_com_duas_pastas(tmp_path)
		problems = validate_addon_structure(addon_folder)
		assert any("ESTRUTURA-007" in p for p in problems), (
			f"ESTRUTURA-007 deveria ser detectado. Problemas: {problems}"
		)

	def test_estrutura007_menciona_nomes_das_pastas(self, tmp_path):
		from nvdastudio.builder.addon_builder import validate_addon_structure

		addon_folder = self._criar_addon_com_duas_pastas(tmp_path)
		problems = validate_addon_structure(addon_folder)
		msg007 = next(p for p in problems if "ESTRUTURA-007" in p)
		assert "PluginA" in msg007 or "PluginB" in msg007, (
			f"ESTRUTURA-007 deveria mencionar os nomes das pastas. Mensagem: {msg007}"
		)

	def test_pasta_unica_nao_gera_estrutura007(self, tmp_path):
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                             "code": _MANIFEST_OK},
			{"language": "python", "filename": "globalPlugins/AddonE12/__init__.py",       "code": _INIT_COMPLETO},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _DOC_HTML},
		]
		addon_folder, _ = save_addon_files(blocks, str(tmp_path), "AddonE12", use_timestamp=False)

		problems = validate_addon_structure(addon_folder)
		assert not any("ESTRUTURA-007" in p for p in problems), (
			f"ESTRUTURA-007 NAO deve disparar com uma unica pasta de plugin. Problemas: {problems}"
		)
