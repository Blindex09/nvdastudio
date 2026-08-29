from nvdastudio.sub_agents.accessibility_auditor import _SYSTEM, _FINAL_TOOL


class TestPontuacaoDecorativaRemovida:
	def test_system_prompt_nao_pede_mais_pontuacao(self):
		assert "PONTUACAO" not in _SYSTEM

	def test_tool_description_nao_menciona_mais_pontuacao(self):
		assert "PONTUACAO" not in _FINAL_TOOL["param_description"]

	def test_formato_de_relatorio_ainda_exigido(self):
		"""So o campo decorativo saiu -- o formato REGRA/SEVERIDADE/LOCAL/
		PROBLEMA/CORRECAO continua exigido."""
		assert "REGRA" in _SYSTEM
		assert "SEVERIDADE" in _SYSTEM
		assert "CORRECAO" in _SYSTEM
