from unittest.mock import patch

import pytest


def _mock_reliability(attempts, success_rate):
	return {"attempts": attempts, "successes": round(attempts * success_rate),
			"success_rate": success_rate, "avg_latency_ms": 0.0}


class TestReliabilityScoreShrinkageBayesiano:
	"""
	1.6.0: padrao portado de C:\\agentic (providers_auto.py::_routing_score()
	-- "Bayesian-style shrinkage"). Substitui o corte binario anterior
	(< 5 tentativas = 100% prior, >= 5 = 100% taxa observada) por uma curva
	suave: confianca cresce com volume de dados, nunca chega a 0% nem 100%.
	"""

	def test_zero_tentativas_usa_prior_neutro_puro(self):
		from nvdastudio.ai.model_router import _reliability_score, _NEUTRAL_RELIABILITY
		with patch("nvdastudio.memory.session_memory.memory.get_model_reliability",
				   return_value=_mock_reliability(0, 0.0)):
			assert _reliability_score("ollama", "kimi-k2.7-code", "code_generation") == _NEUTRAL_RELIABILITY

	def test_poucas_tentativas_fica_perto_do_prior_mas_nao_igual(self):
		"""1 falha isolada com poucos dados nao deve derrubar o score inteiro
		pro valor observado (0.0) -- diferente do corte binario antigo, que
		com 4 tentativas ainda usava 100% prior; agora ha uma influencia
		pequena mas real ja a partir da 1a tentativa."""
		from nvdastudio.ai.model_router import _reliability_score, _NEUTRAL_RELIABILITY
		with patch("nvdastudio.memory.session_memory.memory.get_model_reliability",
				   return_value=_mock_reliability(1, 0.0)):
			score = _reliability_score("ollama", "kimi-k2.7-code", "code_generation")
		assert score < _NEUTRAL_RELIABILITY
		assert score > 0.0
		# confidence = 1/21 ~= 0.0476 -> score ~= 0.75 * (1-0.0476) ~= 0.714
		assert 0.70 <= score <= 0.72

	def test_muitas_tentativas_se_aproxima_da_taxa_observada(self):
		from nvdastudio.ai.model_router import _reliability_score, _NEUTRAL_RELIABILITY
		with patch("nvdastudio.memory.session_memory.memory.get_model_reliability",
				   return_value=_mock_reliability(1000, 0.9)):
			score = _reliability_score("ollama", "kimi-k2.7-code", "code_generation")
		confidence = 1000 / (1000 + 20.0)
		esperado = (1.0 - confidence) * _NEUTRAL_RELIABILITY + confidence * 0.9
		assert score == pytest.approx(esperado, abs=1e-9)
		# Com 1000 tentativas a confianca ja domina -- score bem perto de 0.9.
		assert score == pytest.approx(0.9, abs=0.01)

	def test_nunca_chega_a_100_por_cento_de_confianca(self):
		"""Mesmo com volume enorme de dados, o prior nunca e totalmente
		descartado -- confidence = attempts / (attempts + K) < 1 sempre."""
		from nvdastudio.ai.model_router import _reliability_score
		with patch("nvdastudio.memory.session_memory.memory.get_model_reliability",
				   return_value=_mock_reliability(1_000_000, 1.0)):
			score = _reliability_score("ollama", "kimi-k2.7-code", "code_generation")
		assert score < 1.0
		assert score > 0.999

	def test_20_tentativas_e_o_ponto_de_confianca_50_por_cento(self):
		"""K=20: com exatamente 20 tentativas, confidence=0.5 -- o score fica
		exatamente no meio do caminho entre o prior e a taxa observada."""
		from nvdastudio.ai.model_router import _reliability_score, _NEUTRAL_RELIABILITY
		with patch("nvdastudio.memory.session_memory.memory.get_model_reliability",
				   return_value=_mock_reliability(20, 0.3)):
			score = _reliability_score("ollama", "kimi-k2.7-code", "code_generation")
		esperado = 0.5 * _NEUTRAL_RELIABILITY + 0.5 * 0.3
		assert abs(score - esperado) < 1e-9

	def test_falha_ao_ler_memoria_usa_prior_neutro(self):
		from nvdastudio.ai.model_router import _reliability_score, _NEUTRAL_RELIABILITY
		with patch("nvdastudio.memory.session_memory.memory.get_model_reliability",
				   side_effect=RuntimeError("banco indisponivel")):
			assert _reliability_score("ollama", "kimi-k2.7-code", "code_generation") == _NEUTRAL_RELIABILITY
