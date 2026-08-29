import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ---------------------------------------------------------------------------
# Fixtures comuns
# ---------------------------------------------------------------------------

_MANIFEST_BASE = """\
name = AddonE13
summary = Addon para testes E13
author = Tester <test@example.com>
version = 1.0.0
minimumNVDAVersion = 2026.1.1
lastTestedNVDAVersion = 2026.1.1
"""

_MANIFEST_URL_HTTP = _MANIFEST_BASE + "url = http://github.com/test/addon\n"
_MANIFEST_URL_HTTPS = _MANIFEST_BASE + "url = https://github.com/test/addon\n"

_INIT_OK = """\
import globalPluginHandler
import addonHandler
addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
\tdef __init__(self):
\t\tsuper().__init__()

\tdef terminate(self):
\t\tsuper().terminate()
"""

_DOC_HTML = """\
<!DOCTYPE html>
<html lang="pt">
<head><meta charset="utf-8"><title>AddonE13</title></head>
<body><h1>AddonE13</h1><p>Guia do usuario.</p></body>
</html>
"""


# ---------------------------------------------------------------------------
# E13a — NVDA-047: url deve comecar com https://
# ---------------------------------------------------------------------------

class TestE13Nvda047:
	"""
	NVDA-047: url no manifest.ini deve comecar com https://.
	O Add-on Store rejeita URLs que nao usem HTTPS.
	"""

	def test_url_http_gera_nvda047(self, tmp_path):
		"""
		url = http://... deve gerar NVDA-047.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                            "code": _MANIFEST_URL_HTTP},
			{"language": "python", "filename": "globalPlugins/AddonE13/__init__.py",       "code": _INIT_OK},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _DOC_HTML},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE13", use_timestamp=False
		)

		problems = validate_addon_structure(addon_folder)
		nvda047 = [p for p in problems if "NVDA-047" in p]
		assert len(nvda047) >= 1, (
			f"NVDA-047 deveria ser detectado para url http://. Problemas: {problems}"
		)
		assert "http://github.com/test/addon" in nvda047[0], (
			f"Mensagem NVDA-047 deve citar a URL invalida. Mensagem: {nvda047[0]}"
		)

	def test_url_https_nao_gera_nvda047(self, tmp_path):
		"""
		url = https://... NAO deve gerar NVDA-047.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                            "code": _MANIFEST_URL_HTTPS},
			{"language": "python", "filename": "globalPlugins/AddonE13/__init__.py",       "code": _INIT_OK},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _DOC_HTML},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE13", use_timestamp=False
		)

		problems = validate_addon_structure(addon_folder)
		assert not any("NVDA-047" in p for p in problems), (
			f"NVDA-047 nao deveria disparar para url https://. Problemas: {problems}"
		)

	def test_sem_url_nao_gera_nvda047(self, tmp_path):
		"""
		Manifest sem campo url: NAO deve gerar NVDA-047 (url e opcional).
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                            "code": _MANIFEST_BASE},
			{"language": "python", "filename": "globalPlugins/AddonE13/__init__.py",       "code": _INIT_OK},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _DOC_HTML},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE13", use_timestamp=False
		)

		problems = validate_addon_structure(addon_folder)
		assert not any("NVDA-047" in p for p in problems), (
			f"NVDA-047 nao deveria disparar quando url esta ausente. Problemas: {problems}"
		)


# ---------------------------------------------------------------------------
# E13b — NVDA-048: wxPython NUNCA deve ser bundlado
# ---------------------------------------------------------------------------

class TestE13Nvda048:
	"""
	NVDA-048: qualquer entrada wx* em lib/ indica que wxPython foi bundlado
	indevidamente. O NVDA ja fornece wxPython — bundlar causa conflito.
	"""

	def test_wx_dir_em_lib_gera_nvda048(self, tmp_path):
		"""
		Presenca de lib/wx/ deve gerar NVDA-048.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                            "code": _MANIFEST_BASE},
			{"language": "python", "filename": "globalPlugins/AddonE13/__init__.py",       "code": _INIT_OK},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _DOC_HTML},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE13", use_timestamp=False
		)

		# Simula bundling de wxPython: cria lib/wx/ no disco
		wx_dir = os.path.join(addon_folder, "lib", "wx")
		os.makedirs(wx_dir, exist_ok=True)
		# Arquivo minimo para que o diretorio nao seja vazio
		with open(os.path.join(wx_dir, "__init__.py"), "w") as fh:
			fh.write("# wx stub bundlado por engano\n")

		problems = validate_addon_structure(addon_folder)
		assert any("NVDA-048" in p for p in problems), (
			f"NVDA-048 deveria ser detectado para lib/wx/. Problemas: {problems}"
		)

	def test_wxpython_dir_em_lib_gera_nvda048(self, tmp_path):
		"""
		Presenca de lib/wxPython/ (nome completo do pacote) deve gerar NVDA-048.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                            "code": _MANIFEST_BASE},
			{"language": "python", "filename": "globalPlugins/AddonE13/__init__.py",       "code": _INIT_OK},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _DOC_HTML},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE13", use_timestamp=False
		)

		# Simula bundling: lib/wxPython/
		wx_dir = os.path.join(addon_folder, "lib", "wxPython")
		os.makedirs(wx_dir, exist_ok=True)
		with open(os.path.join(wx_dir, "__init__.py"), "w") as fh:
			fh.write("# wxPython stub bundlado por engano\n")

		problems = validate_addon_structure(addon_folder)
		assert any("NVDA-048" in p for p in problems), (
			f"NVDA-048 deveria ser detectado para lib/wxPython/. Problemas: {problems}"
		)

	def test_lib_sem_wx_nao_gera_nvda048(self, tmp_path):
		"""
		lib/ com dependencias legitimas (nao-wx) NAO deve gerar NVDA-048.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                            "code": _MANIFEST_BASE},
			{"language": "python", "filename": "globalPlugins/AddonE13/__init__.py",       "code": _INIT_OK},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _DOC_HTML},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE13", use_timestamp=False
		)

		# Cria lib/ com uma dependencia legitima (ex: requests)
		lib_dir = os.path.join(addon_folder, "lib")
		os.makedirs(lib_dir, exist_ok=True)
		requests_dir = os.path.join(lib_dir, "requests")
		os.makedirs(requests_dir, exist_ok=True)
		with open(os.path.join(requests_dir, "__init__.py"), "w") as fh:
			fh.write("# requests stub\n")

		problems = validate_addon_structure(addon_folder)
		assert not any("NVDA-048" in p for p in problems), (
			f"NVDA-048 nao deveria disparar sem wx em lib/. Problemas: {problems}"
		)

	def test_sem_lib_nao_gera_nvda048(self, tmp_path):
		"""
		Addon sem pasta lib/ (sem dependencias bundladas) NAO deve gerar NVDA-048.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                            "code": _MANIFEST_BASE},
			{"language": "python", "filename": "globalPlugins/AddonE13/__init__.py",       "code": _INIT_OK},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _DOC_HTML},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE13", use_timestamp=False
		)

		# Confirma que lib/ nao existe (nenhuma dependencia bundlada)
		assert not os.path.isdir(os.path.join(addon_folder, "lib")), (
			"lib/ nao deveria existir neste addon minimo"
		)

		problems = validate_addon_structure(addon_folder)
		assert not any("NVDA-048" in p for p in problems), (
			f"NVDA-048 nao deveria disparar sem lib/. Problemas: {problems}"
		)

