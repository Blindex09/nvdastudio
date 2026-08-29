# ---------------------------------------------------------------------------
# 1. DOC-A09 — doc_generator v1.6.0
# ---------------------------------------------------------------------------

class TestDocGeneratorRegrasDOC_A09:
	"""doc_generator deve ter a regra DOC-A09 no _SYSTEM."""

	def test_versao_e_1_6_0(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import MODULE_VERSION
		assert MODULE_VERSION == "1.10.0"

	def test_system_tem_doc_a09(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		assert "DOC-A09" in _SYSTEM

	def test_doc_a09_moderate(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		assert "DOC-A09 Moderate" in _SYSTEM

	def test_doc_a09_proibe_expressoes_vazias(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		parte = _SYSTEM.split("DOC-A09")[1]
		# Deve citar pelo menos um AI-ism de expressoes vazias
		assert any(termo in parte for termo in [
			"abrangente", "robusto", "crucial", "fundamental", "essencial"
		])

	def test_doc_a09_proibe_transicoes_mecanicas(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		parte = _SYSTEM.split("DOC-A09")[1]
		# Deve citar transicoes mecanicas de IA
		assert any(termo in parte for termo in [
			"Alem disso", "No entanto", "Desta forma", "Em suma", "Em conclusao"
		])

	def test_doc_a09_proibe_conclusoes_genericas(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		parte = _SYSTEM.split("DOC-A09")[1]
		# Deve citar pelo menos um exemplo de conclusao generica
		assert any(termo in parte for termo in [
			"Obrigado", "Esperamos", "Qualquer duvida", "este guia"
		])

	def test_doc_a09_exige_verbos_imperativos(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		parte = _SYSTEM.split("DOC-A09")[1]
		# Deve mencionar verbos diretos
		assert any(verbo in parte for verbo in [
			"Pressione", "Abra", "Digite", "Selecione"
		])

	def test_doc_a09_menciona_ruido_auditivo(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		parte = _SYSTEM.split("DOC-A09")[1]
		assert "ruido" in parte.lower() or "auditivo" in parte.lower() or "lido em voz" in parte.lower()

	def test_doc_a09_aparece_apos_doc_a08(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		idx_a08 = _SYSTEM.find("DOC-A08")
		idx_a09 = _SYSTEM.find("DOC-A09")
		assert idx_a08 < idx_a09, "DOC-A09 deve aparecer apos DOC-A08 no _SYSTEM"

	def test_total_regras_doc_a_pelo_menos_9(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		import re
		regras = re.findall(r"DOC-A\d+", _SYSTEM)
		ids_unicos = set(regras)
		assert len(ids_unicos) >= 9, f"Esperado >= 9 regras DOC-A, encontrado: {ids_unicos}"

	def test_doc_a09_proibe_ai_isms_linguagem(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
		parte = _SYSTEM.split("DOC-A09")[1]
		# Deve mencionar AI-isms ou escrita artificial
		assert any(termo in parte.lower() for termo in [
			"ai-ism", "artificial", "humana", "direto"
		])


# ---------------------------------------------------------------------------
# 2. Verificacao de versao e changelog
# ---------------------------------------------------------------------------

class TestDocGeneratorV6Changelog:

	def test_changelog_tem_1_6_0(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import __doc__
		assert "1.6.0" in (__doc__ or "")

	def test_changelog_menciona_avoid_ai_writing(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import __doc__
		assert "avoid-ai-writing" in (__doc__ or "").lower()

	def test_versao_e_superior_a_1_5_0(self):
		from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import MODULE_VERSION
		partes = [int(x) for x in MODULE_VERSION.split(".")]
		assert partes >= [1, 6, 0], f"Versao {MODULE_VERSION} deve ser >= 1.6.0"
