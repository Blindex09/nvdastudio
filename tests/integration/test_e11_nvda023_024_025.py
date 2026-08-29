import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ---------------------------------------------------------------------------
# Manifests e helpers
# ---------------------------------------------------------------------------

_MANIFEST = """name = AddonE11
summary = Addon para teste E11 — NVDA-023/024/025
author = Tester <test@example.com>
version = 1.0.0
minimumNVDAVersion = 2026.1.1
lastTestedNVDAVersion = 2026.1.1
"""

_INIT_BASE = """import globalPluginHandler
import addonHandler
addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	def terminate(self):
		super().terminate()
"""

_USER_GUIDE = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Guide</title></head>
<body><h1>AddonE11</h1><p>Teste NVDA-023/024/025.</p></body>
</html>
"""

# ---------------------------------------------------------------------------
# NVDA-023 — lazy type annotation (service file)
# ---------------------------------------------------------------------------

# FAIL: Credentials e importado dentro da funcao, mas usado na annotation
_SERVICE_NVDA023_FAIL = """def get_credentials() -> Credentials:
	from google.oauth2.credentials import Credentials
	return Credentials()
"""

# PASS: string literal forward reference — Python nao avalia em tempo de carga
_SERVICE_NVDA023_PASS = """def get_credentials() -> 'Credentials':
	from google.oauth2.credentials import Credentials
	return Credentials()
"""

# ---------------------------------------------------------------------------
# NVDA-024 — categoryClasses.append sem guard (settings_panel.py)
# ---------------------------------------------------------------------------

# FAIL: append sem guard if ... not in
_SETTINGS_NVDA024_FAIL = """from gui import NVDASettingsDialog


class MyPanel:
	pass


def register_panel() -> None:
	NVDASettingsDialog.categoryClasses.append(MyPanel)
"""

# PASS: append com guard correto
_SETTINGS_NVDA024_PASS = """from gui import NVDASettingsDialog


class MyPanel:
	pass


def register_panel() -> None:
	if MyPanel not in NVDASettingsDialog.categoryClasses:
		NVDASettingsDialog.categoryClasses.append(MyPanel)
"""

# ---------------------------------------------------------------------------
# NVDA-025 — config.conf com secao generica (qualquer .py)
# ---------------------------------------------------------------------------

# FAIL: usa placeholder "meuAddon" — nao coincide com name = AddonE11
_SERVICE_NVDA025_FAIL = """import config


def get_api_key() -> str:
	return config.conf['meuAddon']['apiKey']
"""

# PASS: usa o addonId correto "AddonE11" (case-insensitive match)
_SERVICE_NVDA025_PASS = """import config


def get_api_key() -> str:
	return config.conf['AddonE11']['apiKey']
"""


# ---------------------------------------------------------------------------
# E11 — Cenario: deteccao AST deterministica
# ---------------------------------------------------------------------------

class TestE11Nvda023024025:
	"""
	validate_addon_structure deve detectar NVDA-023/024/025 em arquivos de
	servico e settings, e nao reportar nada quando o codigo segue as boas
	praticas da skill.
	"""

	def test_annotation_lazy_gera_nvda023(self, tmp_path):
		"""
		-> Credentials com Credentials apenas em import lazy deve gerar NVDA-023.
		Regressao direta do root cause: gmail_oauth.py crashava ao carregar
		porque Credentials so existia no escopo lazy da funcao get_credentials().
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                              "code": _MANIFEST},
			{"language": "python", "filename": "globalPlugins/AddonE11/__init__.py",        "code": _INIT_BASE},
			{"language": "python", "filename": "globalPlugins/AddonE11/oauth_service.py",  "code": _SERVICE_NVDA023_FAIL},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _USER_GUIDE},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE11", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		n023 = [p for p in problems if "NVDA-023" in p]
		assert len(n023) >= 1, (
			f"'-> Credentials' com Credentials lazy deve gerar NVDA-023. "
			f"Problemas: {problems}"
		)
		assert "get_credentials" in n023[0], (
			f"NVDA-023 deve mencionar o nome da funcao. Mensagem: {n023[0]}"
		)

	def test_annotation_string_literal_nao_gera_nvda023(self, tmp_path):
		"""
		-> 'Credentials' (string literal / forward reference) NAO deve gerar NVDA-023.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                              "code": _MANIFEST},
			{"language": "python", "filename": "globalPlugins/AddonE11/__init__.py",        "code": _INIT_BASE},
			{"language": "python", "filename": "globalPlugins/AddonE11/oauth_service.py",  "code": _SERVICE_NVDA023_PASS},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _USER_GUIDE},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE11", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		n023 = [p for p in problems if "NVDA-023" in p]
		assert n023 == [], (
			f"Forward reference '-> \"Credentials\"' nao deve gerar NVDA-023. "
			f"Problemas: {problems}"
		)

	def test_append_sem_guard_gera_nvda024(self, tmp_path):
		"""
		categoryClasses.append(Panel) sem guard deve gerar NVDA-024.
		Skill §§ NVDA Settings: painel duplicado no NVDA Settings ao recarregar.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                               "code": _MANIFEST},
			{"language": "python", "filename": "globalPlugins/AddonE11/__init__.py",         "code": _INIT_BASE},
			{"language": "python", "filename": "globalPlugins/AddonE11/settings_panel.py", "code": _SETTINGS_NVDA024_FAIL},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _USER_GUIDE},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE11", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		n024 = [p for p in problems if "NVDA-024" in p]
		assert len(n024) >= 1, (
			f"append() sem guard deve gerar NVDA-024. "
			f"Problemas: {problems}"
		)

	def test_append_com_guard_nao_gera_nvda024(self, tmp_path):
		"""
		categoryClasses.append(Panel) com guard correto NAO deve gerar NVDA-024.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                               "code": _MANIFEST},
			{"language": "python", "filename": "globalPlugins/AddonE11/__init__.py",         "code": _INIT_BASE},
			{"language": "python", "filename": "globalPlugins/AddonE11/settings_panel.py", "code": _SETTINGS_NVDA024_PASS},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _USER_GUIDE},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE11", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		n024 = [p for p in problems if "NVDA-024" in p]
		assert n024 == [], (
			f"append() com guard nao deve gerar NVDA-024. "
			f"Problemas: {problems}"
		)

	def test_config_conf_placeholder_gera_nvda025(self, tmp_path):
		"""
		config.conf['meuAddon'] (placeholder generico) deve gerar NVDA-025.
		Manifest tem name = AddonE11; 'meuAddon' e reconhecido como placeholder.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                              "code": _MANIFEST},
			{"language": "python", "filename": "globalPlugins/AddonE11/__init__.py",        "code": _INIT_BASE},
			{"language": "python", "filename": "globalPlugins/AddonE11/config_helper.py", "code": _SERVICE_NVDA025_FAIL},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _USER_GUIDE},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE11", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		n025 = [p for p in problems if "NVDA-025" in p]
		assert len(n025) >= 1, (
			f"config.conf['meuAddon'] deve gerar NVDA-025. "
			f"Problemas: {problems}"
		)

	def test_config_conf_addonId_correto_nao_gera_nvda025(self, tmp_path):
		"""
		config.conf['AddonE11'] coincide com name do manifest → NAO deve gerar NVDA-025.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                              "code": _MANIFEST},
			{"language": "python", "filename": "globalPlugins/AddonE11/__init__.py",        "code": _INIT_BASE},
			{"language": "python", "filename": "globalPlugins/AddonE11/config_helper.py", "code": _SERVICE_NVDA025_PASS},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _USER_GUIDE},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE11", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		n025 = [p for p in problems if "NVDA-025" in p]
		assert n025 == [], (
			f"config.conf['AddonE11'] nao deve gerar NVDA-025. "
			f"Problemas: {problems}"
		)

