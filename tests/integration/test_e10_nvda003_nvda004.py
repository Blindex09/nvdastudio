import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MANIFEST = """name = AddonE10
summary = Addon para teste E10 — NVDA-003 / NVDA-004
author = Tester <test@example.com>
version = 1.0.0
minimumNVDAVersion = 2026.1.1
lastTestedNVDAVersion = 2026.1.1
"""

# __init__.py sem addonHandler.initTranslation() (triggers NVDA-003)
_INIT_SEM_INIT_TRANSLATION = """import globalPluginHandler


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	def terminate(self):
		super().terminate()
"""

# __init__.py sem terminate() (triggers NVDA-004)
_INIT_SEM_TERMINATE = """import globalPluginHandler
import addonHandler
addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
"""

# __init__.py correto — sem nenhuma violacao
_INIT_CORRETO = """import globalPluginHandler
import addonHandler
addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	def terminate(self):
		super().terminate()
"""

# Arquivo de servico (nao __init__.py) sem initTranslation nem terminate.
# Isso e CORRETO — regras NVDA-003/004 nao se aplicam aqui.
_SERVICE_CORRETO = """class DataService:
	def fetch(self, url: str) -> dict:
		import urllib.request
		with urllib.request.urlopen(url) as resp:
			import json
			return json.loads(resp.read())
"""

_USER_GUIDE_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Guide</title></head>
<body><h1>AddonE10</h1><p>Teste NVDA-003/NVDA-004.</p></body>
</html>
"""


# ---------------------------------------------------------------------------
# E10 — Cenario: NVDA-003 e NVDA-004 fail paths
# ---------------------------------------------------------------------------

class TestE10Nvda003Nvda004:
	"""
	validate_addon_structure deve detectar ausencia de initTranslation() (NVDA-003)
	e terminate() (NVDA-004) no __init__.py, e NAO reportar isso em arquivos de
	servico — prevenindo falso positivo documentado no skill.
	"""

	def test_init_sem_initTranslation_gera_nvda003(self, tmp_path):
		"""
		__init__.py sem addonHandler.initTranslation() deve disparar NVDA-003.
		Skill §8 (i18n): todo GlobalPlugin deve chamar initTranslation no
		nivel de modulo antes de qualquer string traduzivel.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                               "code": _MANIFEST},
			{"language": "python", "filename": "globalPlugins/AddonE10/__init__.py",         "code": _INIT_SEM_INIT_TRANSLATION},
			{"language": "html",   "filename": "doc/en/userGuide.html",                     "code": _USER_GUIDE_HTML},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE10", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		n003 = [p for p in problems if "NVDA-003" in p]
		assert len(n003) >= 1, (
			f"__init__.py sem initTranslation() deve gerar NVDA-003. "
			f"Problemas: {problems}"
		)

	def test_init_sem_terminate_gera_nvda004(self, tmp_path):
		"""
		__init__.py sem terminate() deve disparar NVDA-004.
		Skill §3.1: todo GlobalPlugin deve implementar terminate() para liberar
		recursos ao recarregar/desinstalar o addon.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                               "code": _MANIFEST},
			{"language": "python", "filename": "globalPlugins/AddonE10/__init__.py",         "code": _INIT_SEM_TERMINATE},
			{"language": "html",   "filename": "doc/en/userGuide.html",                     "code": _USER_GUIDE_HTML},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE10", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		n004 = [p for p in problems if "NVDA-004" in p]
		assert len(n004) >= 1, (
			f"__init__.py sem terminate() deve gerar NVDA-004. "
			f"Problemas: {problems}"
		)

	def test_servico_sem_initTranslation_nao_gera_nvda003(self, tmp_path):
		"""
		Arquivo de servico (nao __init__.py) sem initTranslation() e terminate()
		NAO deve disparar NVDA-003 ou NVDA-004.
		Regressao: o validador explicitamente limita essas regras ao __init__.py
		para evitar falso positivo em modulos de suporte.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                               "code": _MANIFEST},
			{"language": "python", "filename": "globalPlugins/AddonE10/__init__.py",         "code": _INIT_CORRETO},
			{"language": "python", "filename": "globalPlugins/AddonE10/data_service.py",    "code": _SERVICE_CORRETO},
			{"language": "html",   "filename": "doc/en/userGuide.html",                     "code": _USER_GUIDE_HTML},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE10", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		falso_positivo = [p for p in problems if "NVDA-003" in p or "NVDA-004" in p]
		assert falso_positivo == [], (
			f"data_service.py (nao __init__.py) nao deve gerar NVDA-003/004. "
			f"Falso positivo detectado: {falso_positivo}"
		)

	def test_init_correto_nao_gera_nvda003_nvda004(self, tmp_path):
		"""
		__init__.py com initTranslation() e terminate() corretos nao deve
		gerar NVDA-003 nem NVDA-004.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                               "code": _MANIFEST},
			{"language": "python", "filename": "globalPlugins/AddonE10/__init__.py",         "code": _INIT_CORRETO},
			{"language": "html",   "filename": "doc/en/userGuide.html",                     "code": _USER_GUIDE_HTML},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE10", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		alvo = [p for p in problems if "NVDA-003" in p or "NVDA-004" in p]
		assert alvo == [], (
			f"__init__.py correto nao deve gerar NVDA-003/004. "
			f"Problemas: {problems}"
		)

