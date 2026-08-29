import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MANIFEST_INI = """name = TranscricaoAddon
summary = Addon que testa alucinacao de dependencias
author = Tester <test@example.com>
version = 1.0.0
minimumNVDAVersion = 2026.1.1
lastTestedNVDAVersion = 2026.1.1
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
<head><meta charset="utf-8"><title>Transcricao Guide</title></head>
<body><h1>TranscricaoAddon</h1><p>Addon para teste E7.</p></body>
</html>
"""


def _make_blocks():
	return [
		{"language": "ini",    "filename": "manifest.ini",                                     "code": _MANIFEST_INI},
		{"language": "python", "filename": "globalPlugins/TranscricaoAddon/__init__.py",       "code": _INIT_PY},
		{"language": "html",   "filename": "doc/en/userGuide.html",                            "code": _USER_GUIDE_HTML},
	]


# ---------------------------------------------------------------------------
# E7 — Cenario: alucinacao de dependencias
# ---------------------------------------------------------------------------

class TestE7PyPiAlucinacao:
	"""
	bundle_addon_dependencies com _pypi_checker injetavel.
	Nao faz chamadas de rede reais — testa apenas a logica de filtragem.
	"""

	def test_pacote_inexistente_nao_chama_pip(self, tmp_path):
		"""
		Pacote que retorna False do _pypi_checker nao deve ser instalado.
		bundle_addon_dependencies deve retornar lista vazia para pacotes invalidos.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, bundle_addon_dependencies

		addon_folder, _ = save_addon_files(
			_make_blocks(), str(tmp_path), "TranscricaoAddon", use_timestamp=False,
		)

		# _pypi_checker sempre retorna False — simula "pacote nao existe no PyPI"
		instalados = bundle_addon_dependencies(
			addon_folder,
			packages=["nvda-utils-fake", "transcricao-api-fake"],
			addon_name="TranscricaoAddon",
			_pypi_checker=lambda pkg: False,
		)

		assert instalados == [], (
			f"Pacotes que nao existem no PyPI nao devem ser instalados. "
			f"Instalados: {instalados}"
		)

	def test_pacote_valido_passa_pelo_checker(self, tmp_path):
		"""
		Pacote que passa pelo _pypi_checker (retorna True) deve tentar o pip.
		Aqui mockamos o subprocess.run para nao instalar nada de verdade.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, bundle_addon_dependencies
		import subprocess

		addon_folder, _ = save_addon_files(
			_make_blocks(), str(tmp_path), "TranscricaoAddon", use_timestamp=False,
		)

		mock_result = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

		with patch.object(subprocess, "run", return_value=mock_result) as mock_run:
			instalados = bundle_addon_dependencies(
				addon_folder,
				packages=["requests"],
				addon_name="TranscricaoAddon",
				_pypi_checker=lambda pkg: True,  # simula "existe no PyPI"
			)

		assert instalados == ["requests"], (
			f"Pacote valido (PyPI=True) deve ser instalado. Instalados: {instalados}"
		)
		assert mock_run.called, "subprocess.run deve ter sido chamado para o pip install"

	def test_mistura_fake_e_real(self, tmp_path):
		"""
		Apenas os pacotes validos devem passar; os falsos devem ser descartados.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, bundle_addon_dependencies
		import subprocess

		addon_folder, _ = save_addon_files(
			_make_blocks(), str(tmp_path), "TranscricaoAddon", use_timestamp=False,
		)

		mock_result = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
		pacotes_verificados = []

		def checker(pkg):
			pacotes_verificados.append(pkg)
			return pkg == "requests"  # so requests "existe"

		with patch.object(subprocess, "run", return_value=mock_result):
			instalados = bundle_addon_dependencies(
				addon_folder,
				packages=["fake-nvda-lib", "requests", "outro-fake"],
				addon_name="TranscricaoAddon",
				_pypi_checker=checker,
			)

		assert instalados == ["requests"], (
			f"Apenas 'requests' deve ser instalado. Instalados: {instalados}"
		)
		assert "fake-nvda-lib" in pacotes_verificados
		assert "outro-fake" in pacotes_verificados

	def test_nome_pip_inseguro_rejeitado_antes_do_checker(self, tmp_path):
		"""
		Nomes com path traversal ou caracteres invalidos devem ser rejeitados
		pelo _is_safe_package_name antes mesmo de chegar ao _pypi_checker.
		"""
		from nvdastudio.builder.addon_builder import save_addon_files, bundle_addon_dependencies

		addon_folder, _ = save_addon_files(
			_make_blocks(), str(tmp_path), "TranscricaoAddon", use_timestamp=False,
		)

		checker_chamado_com = []

		def checker(pkg):
			checker_chamado_com.append(pkg)
			return True

		instalados = bundle_addon_dependencies(
			addon_folder,
			packages=["../../../evil", "http://malicious.com/pkg", "requests[extra]"],
			addon_name="TranscricaoAddon",
			_pypi_checker=checker,
		)

		# Nenhum pacote inseguro deve chegar ao checker ou ao pip
		assert instalados == [], f"Nomes invalidos nao devem ser instalados: {instalados}"
		# requests[extra] deve ser rejeitado por conter '['
		assert not any("[" in p for p in checker_chamado_com), (
			f"Pacote com extras nao deve chegar ao checker. Checker recebeu: {checker_chamado_com}"
		)

