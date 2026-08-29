import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MANIFEST_COMPLETO = """name = AddonE9
summary = Addon para teste de estrutura
author = Tester <test@example.com>
version = 1.0.0
minimumNVDAVersion = 2026.1.1
lastTestedNVDAVersion = 2026.1.1
"""

# Manifest sem o campo "version" (obrigatorio)
_MANIFEST_SEM_VERSION = """name = AddonE9
summary = Addon para teste de estrutura
author = Tester <test@example.com>
minimumNVDAVersion = 2026.1.1
lastTestedNVDAVersion = 2026.1.1
"""

_INIT_PY = """import globalPluginHandler
import addonHandler
addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	def terminate(self):
		super().terminate()
"""

_USER_GUIDE_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Guide</title></head>
<body><h1>AddonE9</h1><p>Teste de estrutura basica.</p></body>
</html>
"""


# ---------------------------------------------------------------------------
# E9 — Cenario: validacao de estrutura basica
# ---------------------------------------------------------------------------

class TestE9EstruturaBasica:
	"""
	validate_addon_structure deve reportar ESTRUTURA-001/002/003 quando
	os arquivos ou campos obrigatorios estiverem ausentes.
	"""

	def test_sem_manifest_gera_estrutura001(self, tmp_path):
		"""
		Addon sem manifest.ini deve reportar ESTRUTURA-001.
		Skill §9: manifest.ini e obrigatorio e deve estar na raiz do addon.

		NOTA (achado 2026-08-03, teste corrigido): save_addon_files() ganhou
		um fallback deliberado em 2026-05-11 (addon_builder.py linha ~1108,
		"Bug 1 fallback") -- quando nenhum bloco manifest.ini e extraido da
		resposta do LLM, gera um manifest minimo deterministico ANTES de
		salvar em disco, pra um 503 do manifest_builder nao virar bloqueador
		fatal de instalacao. Isso significa que passar blocks SEM
		manifest.ini pra save_addon_files() nunca mais chega a
		validate_addon_structure() com manifest ausente -- o teste original
		(que usava save_addon_files) ficou obsoleto sem que ninguem
		percebesse, porque tests/e2e/ nunca era incluido nas rodadas de
		"suite completa" deste projeto. Corrigido pra testar
		validate_addon_structure() diretamente contra uma pasta escrita a
		mao sem manifest.ini -- o invariante real (ESTRUTURA-001 dispara
		quando falta manifest.ini) continua verdadeiro, so nao e mais
		alcancavel via save_addon_files() com blocks incompletos.
		"""
		from nvdastudio.builder.addon_builder import validate_addon_structure

		addon_folder = tmp_path / "AddonE9"
		gp_dir = addon_folder / "globalPlugins" / "AddonE9"
		gp_dir.mkdir(parents=True)
		(gp_dir / "__init__.py").write_text(_INIT_PY, encoding="utf-8")
		doc_dir = addon_folder / "doc" / "en"
		doc_dir.mkdir(parents=True)
		(doc_dir / "userGuide.html").write_text(_USER_GUIDE_HTML, encoding="utf-8")

		problems = validate_addon_structure(str(addon_folder))
		e001 = [p for p in problems if "ESTRUTURA-001" in p]
		assert len(e001) >= 1, (
			f"Pasta de addon sem manifest.ini deve gerar ESTRUTURA-001. "
			f"Problemas encontrados: {problems}"
		)

	def test_manifest_sem_campo_obrigatorio_gera_estrutura002(self, tmp_path):
		"""
		Manifest sem 'version' deve reportar ESTRUTURA-002.
		Campos obrigatorios: name, summary, version, minimumNVDAVersion.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                             "code": _MANIFEST_SEM_VERSION},
			{"language": "python", "filename": "globalPlugins/AddonE9/__init__.py",         "code": _INIT_PY},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _USER_GUIDE_HTML},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE9", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		e002 = [p for p in problems if "ESTRUTURA-002" in p]
		assert len(e002) >= 1, (
			f"Manifest sem 'version' deve gerar ESTRUTURA-002. "
			f"Problemas: {problems}"
		)
		assert any("version" in p.lower() for p in e002), (
			f"ESTRUTURA-002 deve mencionar o campo ausente 'version'. Mensagem: {e002}"
		)

	def test_sem_globalPlugins_gera_estrutura003(self, tmp_path):
		"""
		Addon sem pasta globalPlugins/ deve reportar ESTRUTURA-003.
		Skill §3: plugin code reside em globalPlugins/.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		# Sem nenhum bloco Python — apenas manifest + doc
		blocks = [
			{"language": "ini",  "filename": "manifest.ini",         "code": _MANIFEST_COMPLETO},
			{"language": "html", "filename": "doc/en/userGuide.html", "code": _USER_GUIDE_HTML},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE9", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		e003 = [p for p in problems if "ESTRUTURA-003" in p]
		assert len(e003) >= 1, (
			f"Addon sem globalPlugins/ deve gerar ESTRUTURA-003. "
			f"Problemas: {problems}"
		)

	def test_addon_correto_nao_gera_estrutura001_002_003(self, tmp_path):
		"""
		Addon estruturalmente correto nao deve gerar ESTRUTURA-001, 002 ou 003.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		blocks = [
			{"language": "ini",    "filename": "manifest.ini",                             "code": _MANIFEST_COMPLETO},
			{"language": "python", "filename": "globalPlugins/AddonE9/__init__.py",         "code": _INIT_PY},
			{"language": "html",   "filename": "doc/en/userGuide.html",                    "code": _USER_GUIDE_HTML},
		]
		addon_folder, _ = save_addon_files(
			blocks, str(tmp_path), "AddonE9", use_timestamp=False,
		)
		problems = validate_addon_structure(addon_folder)
		estrutura_criticos = [
			p for p in problems
			if "ESTRUTURA-001" in p or "ESTRUTURA-002" in p or "ESTRUTURA-003" in p
		]
		assert estrutura_criticos == [], (
			f"Addon correto nao deve ter ESTRUTURA-001/002/003. "
			f"Problemas: {problems}"
		)

