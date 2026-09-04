"""Regressao: uma chave AUSENTE de provedor auxiliar interrompia a geracao com
um dialogo de erro. Com a Factory selecionada (sem chave, via login do droid), o
Critic/Planner ainda pedem OpenCode Go para saida estruturada -- e sem a chave
do OpenCode Go, create_llm_client estourava e o pipeline parava.

Correcao: chave ausente do OpenCode Go MARCA o provedor indisponivel (a mesma
degradacao do disjuntor de 401/429), entao quem reconsulta
get_structured_output_model cai na proxima perna da cadeia (Factory) em vez de
interromper.
"""

import pytest


class TestChaveAusenteDegradaEmVezDeInterromper:
	def test_opencode_go_sem_chave_marca_e_cadeia_cai_na_factory(self):
		from nvdastudio.ai import model_registry as mr
		from nvdastudio.ai.llm_factory import LLMFactoryError, create_llm_client

		# A fixture autouse do conftest ja reseta, mas deixa explicito o ponto
		# de partida: sem nada marcado, a cadeia comeca no OpenCode Go.
		mr.resetar_saida_estruturada()
		assert mr.get_structured_output_model(0).startswith("opencode_go::")

		# Sem chave configurada (ambiente de teste): levanta -- mas ANTES marca
		# o provedor indisponivel, para o reconsulto do chamador nao repetir.
		with pytest.raises(LLMFactoryError):
			create_llm_client(model_id="opencode_go::gpt-5.6-luna")

		# O ponto todo: a proxima consulta NAO devolve mais OpenCode Go -- cai
		# na Factory, que nao precisa de chave. E o que faz o Critic/Planner
		# seguirem em vez de interromper.
		degradado = mr.get_structured_output_model(0)
		assert not degradado.startswith("opencode_go::"), (
			"chave ausente tem que degradar a cadeia, nao deixar o pipeline parar"
		)
		assert degradado.startswith("factory::")

	def test_call_with_structured_output_atravessa_a_cadeia_sem_chave(self):
		"""O helper compartilhado (clarifier/agentic_loop/studio_dialog/memory)
		ja itera a cadeia inteira: os 5 do OpenCode Go falham rapido sem chave e
		ele chega na Factory. Este teste amarra que a fonte segue assim."""
		import inspect

		from nvdastudio.ai import llm_factory

		src = inspect.getsource(llm_factory.call_with_structured_output)
		assert "for idx in range(len(STRUCTURED_OUTPUT_MODEL_CHAIN))" in src
		assert "continue" in src, "um erro de um modelo tem que avancar pro proximo"
