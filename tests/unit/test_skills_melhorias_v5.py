# ---------------------------------------------------------------------------
# 1. DOC-A07 e DOC-A08 — doc_generator v1.5.0
# ---------------------------------------------------------------------------

class TestDocGeneratorRegrasDOC_A07_A08:
	"""doc_generator deve ter as regras DOC-A07 e DOC-A08 no _SYSTEM."""

	def test_versao_e_1_5_0(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import MODULE_VERSION
		assert MODULE_VERSION == "1.10.0"

	def test_system_tem_doc_a07(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		assert "DOC-A07" in _SYSTEM

	def test_doc_a07_menciona_main(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		parte = _SYSTEM.split("DOC-A07")[1]
		assert "<main>" in parte or "main" in parte.lower()

	def test_doc_a07_menciona_landmark(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		parte = _SYSTEM.split("DOC-A07")[1]
		# Deve mencionar landmark ou navegação por tecla D/Q
		assert "landmark" in parte.lower() or "tecla" in parte.lower() or "D para" in parte

	def test_doc_a07_serious(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		# A severity deve ser Serious
		assert "DOC-A07 Serious" in _SYSTEM

	def test_system_tem_doc_a08(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		assert "DOC-A08" in _SYSTEM

	def test_doc_a08_menciona_ol(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		parte = _SYSTEM.split("DOC-A08")[1]
		assert "<ol>" in parte or "<ol" in parte

	def test_doc_a08_menciona_instalacao(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		parte = _SYSTEM.split("DOC-A08")[1]
		assert "nstala" in parte or "passo" in parte.lower() or "step" in parte.lower()

	def test_doc_a08_moderate(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		assert "DOC-A08 Moderate" in _SYSTEM

	def test_doc_a08_menciona_nvda_anuncia_lista(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		parte = _SYSTEM.split("DOC-A08")[1]
		assert "lista" in parte.lower() or "list" in parte.lower()

	def test_doc_a07_aparece_apos_doc_a06(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		idx_a06 = _SYSTEM.find("DOC-A06")
		idx_a07 = _SYSTEM.find("DOC-A07")
		assert idx_a06 < idx_a07, "DOC-A07 deve aparecer apos DOC-A06 no _SYSTEM"

	def test_doc_a08_aparece_apos_doc_a07(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		idx_a07 = _SYSTEM.find("DOC-A07")
		idx_a08 = _SYSTEM.find("DOC-A08")
		assert idx_a07 < idx_a08, "DOC-A08 deve aparecer apos DOC-A07 no _SYSTEM"

	def test_total_regras_doc_a_pelo_menos_8(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		import re
		regras = re.findall(r"DOC-A\d+", _SYSTEM)
		ids_unicos = set(regras)
		assert len(ids_unicos) >= 8, f"Esperado >= 8 regras DOC-A, encontrado: {ids_unicos}"


# ---------------------------------------------------------------------------
# 2. Verificacao de versao no changelog do doc_generator
# ---------------------------------------------------------------------------

class TestDocGeneratorVersionChangelog:

	def test_changelog_tem_1_5_0(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import __doc__
		assert "1.5.0" in (__doc__ or "")

	def test_changelog_menciona_wcag_web_semantics(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import __doc__
		assert "wcag-web-semantics" in (__doc__ or "").lower() or "wcag" in (__doc__ or "").lower()
