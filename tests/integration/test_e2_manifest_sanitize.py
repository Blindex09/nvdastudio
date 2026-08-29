import os
import sys
import configparser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Manifest com summary multiline (as tabs/espaços no ini sao continuacao de linha)
# e o campo proibido sha256 que o LLM as vezes gera.
_MANIFEST_MULTILINE = """name = AddonSanitize
summary = Este addon faz muitas coisas
	incluindo processamento de audio
	e integracao com APIs externas
author = Tester <test@example.com>
version = 1.0.0
minimumNVDAVersion = 2026.1.1
lastTestedNVDAVersion = 2026.1.1
sha256 = abc123fakehash
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
<head><meta charset="utf-8"><title>Sanitize Guide</title></head>
<body><h1>Guia</h1><p>Addon para teste E2.</p></body>
</html>
"""


def _make_blocks():
	return [
		{"language": "ini",    "filename": "manifest.ini",                                  "code": _MANIFEST_MULTILINE},
		{"language": "python", "filename": "globalPlugins/AddonSanitize/__init__.py",       "code": _INIT_PY},
		{"language": "html",   "filename": "doc/en/userGuide.html",                         "code": _USER_GUIDE_HTML},
	]


# ---------------------------------------------------------------------------
# E2 — Cenario: manifest multiline e campo proibido
# ---------------------------------------------------------------------------

class TestE2ManifestSanitize:
	"""
	_sanitize_manifest deve ser invocado por save_addon_files e produzir
	um manifest.ini valido mesmo quando o LLM gera multiline + campos proibidos.
	"""

	def test_manifest_salvo_e_parseable_por_configparser(self, tmp_path):
		"""
		O manifest.ini salvo deve ser parseavel pelo configparser (equivalente ao
		ConfigObj usado pelo NVDA) — sem VdtTypeError e sem valores lista.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files

		addon_folder, _ = save_addon_files(
			_make_blocks(), str(tmp_path), "AddonSanitize", use_timestamp=False,
		)

		manifest_path = os.path.join(addon_folder, "manifest.ini")
		assert os.path.isfile(manifest_path)

		with open(manifest_path, encoding="utf-8") as fh:
			content = fh.read()

		# configparser requer secao; o manifest NVDA nao tem -- usa secao fake
		# pra confirmar de verdade que o parser aceita o arquivo sem erro
		# (VdtTypeError/valor-lista sao sintomas de linha de continuacao mal
		# formada, que o parser rejeitaria).
		cp = configparser.RawConfigParser()
		cp.read_string("[manifest]\n" + content)

		# Nenhum valor deve ter indentacao de continuacao (seria multiline)
		for line in content.splitlines():
			assert not line.startswith("\t") and not (
				line.startswith("  ") and "=" not in line
			), (
				f"Linha de continuacao encontrada apos sanitizacao: {line!r}"
			)

	def test_sha256_removido_pelo_sanitizer(self, tmp_path):
		"""
		O campo proibido sha256 nao deve aparecer no manifest.ini salvo.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files

		addon_folder, _ = save_addon_files(
			_make_blocks(), str(tmp_path), "AddonSanitize", use_timestamp=False,
		)

		manifest_path = os.path.join(addon_folder, "manifest.ini")
		with open(manifest_path, encoding="utf-8") as fh:
			content = fh.read()

		assert "sha256" not in content.lower(), (
			"Campo proibido 'sha256' nao deve ser salvo no manifest.ini."
		)

	def test_summary_em_uma_linha(self, tmp_path):
		"""
		O summary multiline deve ter sido unido em uma unica linha.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files

		addon_folder, _ = save_addon_files(
			_make_blocks(), str(tmp_path), "AddonSanitize", use_timestamp=False,
		)

		manifest_path = os.path.join(addon_folder, "manifest.ini")
		with open(manifest_path, encoding="utf-8") as fh:
			lines = fh.readlines()

		summary_lines = [line for line in lines if line.strip().startswith("summary")]
		assert len(summary_lines) == 1, (
			f"summary deve ocupar exatamente 1 linha. Encontradas: {summary_lines}"
		)
		assert "summary" in summary_lines[0] and "=" in summary_lines[0]

	def test_pipeline_nao_reporta_problemas_criticos(self, tmp_path):
		"""
		Apos sanitizacao, o validate deve passar sem erros criticos de estrutura.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		addon_folder, _ = save_addon_files(
			_make_blocks(), str(tmp_path), "AddonSanitize", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		# Nao deve haver erros de estrutura ou NVDA-003/004 — apenas eventuais avisos menores
		criticos = [p for p in problems if any(
			tag in p for tag in ["ESTRUTURA-001", "ESTRUTURA-002", "ESTRUTURA-003",
			                     "ESTRUTURA-004", "ESTRUTURA-005", "NVDA-003", "NVDA-004"]
		)]
		assert criticos == [], f"Problemas criticos inesperados: {criticos}"

