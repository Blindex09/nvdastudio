import os
import struct
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ---------------------------------------------------------------------------
# Helpers — PE header sintetico para .pyd 64-bit sem sufixo win_amd64
# ---------------------------------------------------------------------------

def _make_pyd_x64(path: str) -> None:
	"""Gera um .pyd sintetico com PE header x64 real (Machine=0x8664)."""
	buf = bytearray(0x100)
	buf[0:2] = b"MZ"
	struct.pack_into("<I", buf, 0x3C, 0x80)       # e_lfanew
	buf[0x80:0x84] = b"PE\x00\x00"
	struct.pack_into("<H", buf, 0x84, 0x8664)     # IMAGE_FILE_MACHINE_AMD64
	with open(path, "wb") as f:
		f.write(bytes(buf))


def _make_pyd_x86(path: str) -> None:
	"""Gera um .pyd sintetico com PE header x86 (Machine=0x014c) — 32-bit real."""
	buf = bytearray(0x100)
	buf[0:2] = b"MZ"
	struct.pack_into("<I", buf, 0x3C, 0x80)
	buf[0x80:0x84] = b"PE\x00\x00"
	struct.pack_into("<H", buf, 0x84, 0x014C)     # IMAGE_FILE_MACHINE_I386
	with open(path, "wb") as f:
		f.write(bytes(buf))


# ---------------------------------------------------------------------------
# Fixtures — blocks que simulam a saida da IA para um addon com dep binaria
# ---------------------------------------------------------------------------

_MANIFEST_INI = """name = MeuCryptoAddon
summary = Addon que usa cryptography para proteger configuracoes
author = Tester <test@example.com>
version = 1.0.0
minimumNVDAVersion = 2026.1.1
lastTestedNVDAVersion = 2026.1.1
"""

_INIT_PY = """import globalPluginHandler
import addonHandler
import ui
addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
\tdef __init__(self):
\t\tsuper().__init__()

\tdef script_hello(self, gesture):
\t\t# Translators: mensagem dita ao usuario.
\t\tui.message(_("Ola do addon crypto"))

\tdef terminate(self):
\t\tsuper().terminate()
"""


def _make_blocks():
	"""Simula a lista de blocks que sub_agents/assembler produz."""
	return [
		{"language": "ini",    "filename": "manifest.ini",                                 "code": _MANIFEST_INI},
		{"language": "python", "filename": "globalPlugins/MeuCryptoAddon/__init__.py",     "code": _INIT_PY},
	]


# ---------------------------------------------------------------------------
# E3 — Cenario: addon com dep binaria 64-bit
# ---------------------------------------------------------------------------

class TestE3AddonComDepBinaria64Bit:
	"""
	Pipeline pos-geracao de um addon que depende de cryptography.
	Executa save real -> simula bundle -> validate real -> package real.
	Nenhum NVDA-017 deve ser disparado.
	"""

	def _simular_cryptography_bundlada(self, addon_folder: str) -> None:
		"""
		Cria a estrutura de arquivos que 'pip install cryptography' geraria
		dentro de lib/, incluindo o .pyd sem sufixo win_amd64 (o caso bug).
		"""
		lib = os.path.join(addon_folder, "globalPlugins", "MeuCryptoAddon", "lib")
		os.makedirs(os.path.join(lib, "cryptography", "hazmat", "bindings"),
		            exist_ok=True)
		# Arquivos Python puro — nao disparam NVDA-017
		open(os.path.join(lib, "cryptography", "__init__.py"), "w").close()
		open(os.path.join(lib, "cryptography", "hazmat", "__init__.py"), "w").close()
		open(os.path.join(lib, "cryptography", "hazmat", "bindings",
		                  "__init__.py"), "w").close()
		# O .pyd do caso bug — x64 SEM 'win_amd64' no nome
		_make_pyd_x64(os.path.join(lib, "cryptography", "hazmat",
		                           "bindings", "_rust.pyd"))

	def test_pipeline_completo_nao_dispara_nvda017(self, tmp_path):
		"""
		O cenario que reproduz o bug de producao: cryptography/_rust.pyd x64
		sem sufixo. O pipeline antigo reportava NVDA-017 aqui.
		O pipeline novo (com _detect_pyd_architecture) nao deve reportar.
		"""
		from nvdastudio.builder.addon_builder import (
			save_addon_files, validate_addon_structure, package_addon,
		)

		output_dir = str(tmp_path)
		addon_folder, _saved = save_addon_files(
			_make_blocks(), output_dir, "MeuCryptoAddon", use_timestamp=False,
		)

		# Simula o que o bundle_dependencies_into_lib faria com cryptography
		self._simular_cryptography_bundlada(addon_folder)

		# Validacao estrutural real — le PE header real do _rust.pyd
		problems = validate_addon_structure(addon_folder)
		nvda017 = [p for p in problems if "NVDA-017" in p]
		assert nvda017 == [], (
			"_rust.pyd x64 (PE header) sem sufixo 'win_amd64' nao deve disparar "
			f"NVDA-017. Bug de producao regrediu. Problemas: {problems}"
		)

		# Empacotamento real
		pkg = package_addon(addon_folder)
		assert os.path.isfile(pkg), "package_addon deve criar um .nvda-addon real"
		assert pkg.endswith(".nvda-addon")

		# Verifica que o ZIP e valido e contem o .pyd esperado
		with zipfile.ZipFile(pkg) as zf:
			nomes = zf.namelist()
		assert "manifest.ini" in nomes
		assert any(n.endswith("_rust.pyd") for n in nomes), (
			f"O .pyd bundlado deve estar no pacote final. Arquivos: {nomes[:20]}"
		)

	def test_pipeline_detecta_pyd_32bit_real(self, tmp_path):
		"""
		Regressao: se o pacote bundlado de fato tiver um .pyd 32-bit
		(cenario real: versao errada do pip baixou win32), NVDA-017 DEVE
		ser disparado. A funcao _detect_pyd_architecture nao pode ser
		permissiva demais a ponto de deixar passar 32-bit verdadeiros.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		addon_folder, _ = save_addon_files(
			_make_blocks(), str(tmp_path), "MeuCryptoAddon", use_timestamp=False,
		)
		lib = os.path.join(addon_folder, "globalPlugins", "MeuCryptoAddon", "lib")
		os.makedirs(lib, exist_ok=True)
		_make_pyd_x86(os.path.join(lib, "_legacy_32bit.pyd"))       # 32-bit REAL

		problems = validate_addon_structure(addon_folder)
		nvda017 = [p for p in problems if "NVDA-017" in p]
		assert len(nvda017) == 1, (
			f"pyd x86 real deve disparar NVDA-017. Problemas: {problems}"
		)
		assert "_legacy_32bit.pyd" in nvda017[0]

	def test_pipeline_mistura_x64_e_x86_so_reporta_x86(self, tmp_path):
		"""
		Cenario realista: lib/ com varios .pyd x64 (corretos) + 1 x86 infiltrado.
		O validador deve reportar APENAS o x86, nao criar ruido sobre os x64.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, validate_addon_structure

		addon_folder, _ = save_addon_files(
			_make_blocks(), str(tmp_path), "MeuCryptoAddon", use_timestamp=False,
		)
		self._simular_cryptography_bundlada(addon_folder)
		lib = os.path.join(addon_folder, "globalPlugins", "MeuCryptoAddon", "lib")
		_make_pyd_x64(os.path.join(lib, "_upb_message.pyd"))        # mais um x64
		_make_pyd_x86(os.path.join(lib, "_wrong_arch.pyd"))         # x86 infiltrado

		problems = validate_addon_structure(addon_folder)
		nvda017 = [p for p in problems if "NVDA-017" in p]
		assert len(nvda017) == 1, f"Deve haver exatamente 1 NVDA-017. {problems}"
		assert "_wrong_arch.pyd" in nvda017[0]
		assert "_rust.pyd" not in nvda017[0]
		assert "_upb_message.pyd" not in nvda017[0]

