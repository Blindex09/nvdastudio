from nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM as _CRITIC_SPEC_SYSTEM


class TestCriticCobreArch008E009:
	def test_arch_008_presente_na_rubrica(self):
		assert "ARCH-008" in _CRITIC_SPEC_SYSTEM

	def test_arch_009_presente_na_rubrica(self):
		assert "ARCH-009" in _CRITIC_SPEC_SYSTEM

	def test_header_de_regras_arquiteturais_atualizado(self):
		"""O header dizia 'ARCH-001..007' -- se ainda disser isso, a
		auditoria original (que achou o gap) fica sem sinal visivel de que
		foi corrigida."""
		assert "ARCH-001..007" not in _CRITIC_SPEC_SYSTEM
		assert "ARCH-001..009" in _CRITIC_SPEC_SYSTEM

	def test_arch_008_e_arch_009_sao_contextuais_nao_estritas(self):
		"""nvda_context.py classifica ambas como CONTEXTUAL_CHOICE -- a
		rubrica do critic nao pode exigir uma opcao especifica (menu vs
		settings), so que NENHUMA exista."""
		idx_008 = _CRITIC_SPEC_SYSTEM.find("ARCH-008")
		trecho_008 = _CRITIC_SPEC_SYSTEM[idx_008:idx_008 + 700]
		assert "CONTEXTUAL" in trecho_008 or "nao penalize" in trecho_008.lower()

		idx_009 = _CRITIC_SPEC_SYSTEM.find("ARCH-009")
		trecho_009 = _CRITIC_SPEC_SYSTEM[idx_009:idx_009 + 700]
		assert "CONTEXTUAL" in trecho_009 or "nao penalize" in trecho_009.lower()
