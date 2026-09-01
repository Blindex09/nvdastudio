"""
Tempo para escrever, teto para nao caber.

`_EXTENDED_TIMEOUT_STEP_TYPES` e `_EXTENDED_TOKENS_STEP_TYPES` discordavam sobre
design_review e engineering_review: os dois estavam na lista de TIMEOUT (ganharam
tempo para responder) e fora da lista de TOKENS (sem permissao para responder
longo). A diferenca nunca foi deliberada -- os dois foram acrescentados ao
timeout quando o problema apareceu la, e ninguem olhou o outro lado da costura.

O Critic reprovou a revisao de design por isso, com estas palavras:

  "o texto termina de forma truncada em 'usuarios de...'"
  "o bloco do Challenger termina abruptamente"
  "ha um bloco vazio {} no Constraint Guardian"

Custo medido: de 116.158 a 169.740 tokens por revisao cortada no meio.

E havia um segundo lado: `resp.truncated` existia desde llm_client 1.1.0 e SO o
code_generator olhava. Todo outro sub-agente podia ser cortado, entregar um
documento pela metade ao Critic, e a causa nunca aparecia em lugar nenhum.
"""

import inspect

from nvdastudio.ai.ollama_client import (
	_EXTENDED_TIMEOUT_STEP_TYPES,
	_EXTENDED_TOKENS_STEP_TYPES,
	_MAX_TOKENS_DEFAULT,
	_MAX_TOKENS_EXTENDED,
)
from nvdastudio.sub_agents import _base

# Steps que legitimamente tenham timeout longo SEM teto de saida longo -- ou o
# contrario. Vazio hoje: existe para que uma excecao futura precise ser escrita
# e justificada, em vez de virar divergencia silenciosa de novo.
_DIVERGENCIAS_JUSTIFICADAS: dict[str, str] = {}


def test_as_duas_listas_concordam():
	divergentes = sorted(
		(_EXTENDED_TOKENS_STEP_TYPES ^ _EXTENDED_TIMEOUT_STEP_TYPES)
		- set(_DIVERGENCIAS_JUSTIFICADAS)
	)
	assert not divergentes, (
		f"{divergentes} esta em uma lista e nao na outra. Dar tempo de resposta "
		"sem dar teto de saida corta o documento no meio; dar teto sem tempo "
		"estoura o HTTP. Alinhe as duas ou justifique em "
		"_DIVERGENCIAS_JUSTIFICADAS."
	)


def test_design_review_pode_responder_longo():
	"""Tres personas num documento so -- foi o step mais cortado nos relatorios."""
	assert "design_review" in _EXTENDED_TOKENS_STEP_TYPES


def test_engineering_review_pode_responder_longo():
	"""Le TODO o codigo gerado de uma vez; a saida acompanha a entrada."""
	assert "engineering_review" in _EXTENDED_TOKENS_STEP_TYPES


def test_teto_estendido_e_maior_que_o_padrao():
	assert _MAX_TOKENS_EXTENDED > _MAX_TOKENS_DEFAULT


def test_justificativas_nao_viram_deposito():
	for tipo, motivo in _DIVERGENCIAS_JUSTIFICADAS.items():
		assert len(motivo.strip()) > 25, f"{tipo}: justificativa vaga demais"


class TestTruncamentoVisivel:
	def test_base_consulta_o_sinal_de_truncamento(self):
		"""A peca existia e estava desligada: so o code_generator olhava
		`resp.truncated`, e todos os outros sub-agentes passam por _base."""
		src = inspect.getsource(_base._run_sub_agent)
		assert "truncated" in src
		assert "TRUNCADO" in src

	def test_resultado_nao_e_alterado_pelo_aviso(self):
		"""Cortar ou remendar aqui seria inventar conteudo -- o registro e para
		que a causa apareca no log, nao para mascarar o sintoma."""
		src = inspect.getsource(_base._run_sub_agent)
		i = src.index("truncated")
		trecho = src[i:src.index("result =", i)]
		for proibido in ("result =", "resp.content =", "+="):
			assert proibido not in trecho, (
				"o bloco de truncamento nao pode reescrever o resultado"
			)
