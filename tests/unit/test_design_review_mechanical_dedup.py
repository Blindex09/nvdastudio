from unittest.mock import patch

from nvdastudio.sub_agents.design_review_agent import (
	_dedupe_repeated_rule_mentions, _strip_rule_ids, run,
)


class TestDedupeRepeatedRuleMentions:
	def test_mantem_primeira_mencao_remove_repeticoes(self):
		guardian_output = (
			"RESTRICOES NVDA CRITICAS:\n"
			"NVDA-002: nunca bloqueie a thread principal.\n"
			"NVDA-010: use wx.CallAfter para voltar a GUI thread.\n"
			"\n"
			"RESTRICOES WX CRITICAS:\n"
			"NVDA-002: nunca bloqueie a thread principal.\n"
			"WX-A11Y-004: dialog precisa de tratamento de Escape.\n"
			"\n"
			"Implementation Contract:\n"
			"NVDA-002: nunca bloqueie a thread principal.\n"
			"NVDA-010: use wx.CallAfter para voltar a GUI thread.\n"
		)
		result = _dedupe_repeated_rule_mentions(guardian_output)
		assert result.count("NVDA-002") == 1
		assert result.count("NVDA-010") == 1
		assert result.count("WX-A11Y-004") == 1

	def test_preserva_linhas_sem_rule_id(self):
		guardian_output = (
			"RESTRICOES NVDA CRITICAS:\n"
			"NVDA-002: nunca bloqueie a thread principal.\n"
			"\n"
			"## Implementation Contract (Pre-conditions)\n"
			"Use threading.Thread para chamadas de rede.\n"
		)
		result = _dedupe_repeated_rule_mentions(guardian_output)
		assert "## Implementation Contract (Pre-conditions)" in result
		assert "Use threading.Thread para chamadas de rede." in result

	def test_linha_com_id_novo_e_id_repetido_e_mantida(self):
		"""Uma linha que mistura um ID ja visto com um ID NOVO deve ser
		mantida (contem informacao nova), nao descartada inteira."""
		guardian_output = (
			"NVDA-002: nunca bloqueie a thread principal.\n"
			"NVDA-002 e NVDA-010: ambas relevantes para threading e GUI.\n"
		)
		result = _dedupe_repeated_rule_mentions(guardian_output)
		assert "NVDA-002 e NVDA-010" in result

	def test_sem_rule_ids_texto_intacto(self):
		texto = "Nenhuma restricao critica identificada para este addon simples."
		assert _dedupe_repeated_rule_mentions(texto) == texto

	def test_string_vazia(self):
		assert _dedupe_repeated_rule_mentions("") == ""


class TestStripRuleIds:
	def test_remove_rule_id_citado_incorretamente(self):
		"""Achado real: Advocate citou NVDA-011 como 'usar super().__init__'
		(atribuicao errada -- essa e NVDA-030). Como o Advocate nunca deveria
		citar rule IDs, a correcao remove o ID inteiro."""
		advocate_output = (
			"ACESSIBILIDADE DO FLUXO: o usuario consegue configurar via NVDA-011 "
			"(usar super().__init__) sem problemas.\n"
		)
		result = _strip_rule_ids(advocate_output)
		assert "NVDA-011" not in result

	def test_remove_multiplos_ids(self):
		advocate_output = "Ver NVDA-002 e WX-A11Y-004 e ARCH-005 para detalhes."
		result = _strip_rule_ids(advocate_output)
		assert "NVDA-002" not in result
		assert "WX-A11Y-004" not in result
		assert "ARCH-005" not in result

	def test_texto_sem_ids_intacto(self):
		texto = "ATALHOS E CONFLITOS: NVDA+Shift+T nao conflita com atalhos padrao."
		assert _strip_rule_ids(texto) == texto


class TestRunWireiaOsDoisReforcos:
	def test_guardian_deduplicado_no_resultado_final(self, fake_api_key):
		outputs = {
			"challenger": "Suposicoes: nenhuma critica.",
			"guardian": (
				"NVDA-002: nunca bloqueie a thread principal.\n"
				"NVDA-002: nunca bloqueie a thread principal.\n"
				"NVDA-002: nunca bloqueie a thread principal.\n"
			),
			"advocate": "Fluxo acessivel via teclado.",
		}
		call_order = ["challenger", "guardian", "advocate"]

		def fake_run_sub_agent(*args, **kwargs):
			idx_key = call_order[fake_run_sub_agent.calls]
			fake_run_sub_agent.calls += 1
			return outputs[idx_key]
		fake_run_sub_agent.calls = 0

		with patch("nvdastudio.sub_agents.design_review_agent._run_sub_agent",
				   side_effect=fake_run_sub_agent):
			result = run("pedido de revisao", "kimi-k2.6", {})

		assert result.count("NVDA-002") == 1, (
			f"Guardian repetido nao foi deduplicado no resultado final de run(). "
			f"Resultado:\n{result}"
		)

	def test_advocate_sem_rule_ids_no_resultado_final(self, fake_api_key):
		outputs = {
			"challenger": "Suposicoes: nenhuma critica.",
			"guardian": "NVDA-002: nunca bloqueie a thread principal.",
			"advocate": "O usuario configura via NVDA-011 sem problemas.",
		}
		call_order = ["challenger", "guardian", "advocate"]

		def fake_run_sub_agent(*args, **kwargs):
			idx_key = call_order[fake_run_sub_agent.calls]
			fake_run_sub_agent.calls += 1
			return outputs[idx_key]
		fake_run_sub_agent.calls = 0

		with patch("nvdastudio.sub_agents.design_review_agent._run_sub_agent",
				   side_effect=fake_run_sub_agent):
			result = run("pedido de revisao", "kimi-k2.6", {})

		advocate_section = result.split("User Advocate")[-1]
		assert "NVDA-011" not in advocate_section, (
			f"Advocate citou rule ID e nao foi removido do resultado final de run(). "
			f"Secao:\n{advocate_section}"
		)
		# Guardian (secao ANTERIOR) deve continuar citando IDs normalmente --
		# o strip e exclusivo do Advocate.
		guardian_section = result.split("User Advocate")[0]
		assert "NVDA-002" in guardian_section
