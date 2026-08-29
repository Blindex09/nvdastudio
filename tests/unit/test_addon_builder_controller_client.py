import os
import tempfile

from nvdastudio.builder.addon_builder import save_addon_files


class TestRequireManifestFallback:
	def _blocks_sem_manifest(self):
		return [
			{"filename": "nvda_client.py", "code": "import ctypes\n", "language": "python"},
		]

	def test_default_gera_manifest_fallback(self):
		"""Comportamento historico preservado: sem require_manifest
		explicito, blocos sem manifest.ini ganham um manifest minimo
		deterministico (ESTRUTURA-001, evita bloqueio quando manifest_builder
		falha num addon normal)."""
		with tempfile.TemporaryDirectory() as tmpdir:
			folder, saved = save_addon_files(self._blocks_sem_manifest(), tmpdir, "TesteAddon")
			nomes = [os.path.basename(p) for p in saved]
			assert "manifest.ini" in nomes

	def test_require_manifest_false_nao_gera_fallback(self):
		"""controller_client: nunca deveria ganhar um manifest.ini que o
		usuario nao pediu e que nao faz sentido pro tipo de projeto."""
		with tempfile.TemporaryDirectory() as tmpdir:
			folder, saved = save_addon_files(
				self._blocks_sem_manifest(), tmpdir, "ProgramaExterno",
				require_manifest=False,
			)
			nomes = [os.path.basename(p) for p in saved]
			assert "manifest.ini" not in nomes

	def test_require_manifest_false_com_manifest_real_preserva(self):
		"""Se o LLM legitimamente gerou um manifest.ini mesmo com
		require_manifest=False, nao deve remove-lo -- a flag so desliga o
		FALLBACK automatico, nao filtra blocos reais."""
		blocks = self._blocks_sem_manifest() + [
			{"filename": "manifest.ini", "code": "name = X\n", "language": "ini"},
		]
		with tempfile.TemporaryDirectory() as tmpdir:
			folder, saved = save_addon_files(
				blocks, tmpdir, "ProgramaExterno", require_manifest=False,
			)
			nomes = [os.path.basename(p) for p in saved]
			assert "manifest.ini" in nomes
