"""
Forcar UM provedor para saida estruturada criava ponto unico de falha.

`get_structured_output_model()` devolve OpenCode Go porque so ele honra
json_schema estrito e prompt caching (auditoria ao vivo 2026-08-26) -- o Ollama
Cloud nao oferece nenhuma das duas garantias, em nenhum modelo da conta. A
decisao esta certa e continua valendo.

O problema era o que acontece quando esse provedor NAO atende: Clarifier, Critic
e o caminho estrito do Planner caem todos juntos, e a execucao inteira morre.

Confirmado ao vivo em 2026-09-02, testando a chave isoladamente:

    GET  /zen/go/v1/models            -> HTTP 200, 33 modelos (chave VALIDA)
    POST /zen/go/v1/chat/completions  -> HTTP 401 CreditsError
                                         "Insufficient balance"

Testados 6 modelos, incluindo o default do projeto: todos com o mesmo erro. A
cadeia de fallback tem 5 modelos e TODOS no mesmo provedor -- trocar de modelo
nao resolve uma conta sem saldo.

A degradacao e REAL, nao equivalencia: sem json_schema estrito a qualidade do
JSON cai, e os consumidores passam a depender dos caminhos tolerantes que ja
existem. E melhor que a alternativa, que e parar.
"""

import inspect

from nvdastudio.ai import model_registry as mr


def test_versao():
	assert mr.MODULE_VERSION == "1.19.0"


def _limpar():
	mr.resetar_saida_estruturada()


def test_por_padrao_usa_o_provedor_com_garantia():
	_limpar()
	assert mr.get_structured_output_model(0).startswith("opencode_go::")


def test_marcado_indisponivel_cai_no_provedor_ativo():
	_limpar()
	mr.marcar_saida_estruturada_indisponivel("HTTP 401: CreditsError")
	try:
		escolhido = mr.get_structured_output_model(0)
		assert not escolhido.startswith("opencode_go::"), (
			"continuou insistindo no provedor que nao esta atendendo"
		)
		assert escolhido, "degradou para nada -- o pipeline ficaria sem modelo"
	finally:
		_limpar()


def test_reset_volta_ao_preferido():
	"""O limite do provedor e por JANELA DE TEMPO (5h / semana / mes): a
	indisponibilidade e temporaria e nao pode virar permanente."""
	_limpar()
	mr.marcar_saida_estruturada_indisponivel("teste")
	assert not mr.get_structured_output_model(0).startswith("opencode_go::")
	mr.resetar_saida_estruturada()
	assert mr.get_structured_output_model(0).startswith("opencode_go::")


def test_cada_execucao_reseta():
	"""A costura: sem o reset por execucao, uma falha de horas atras deixaria
	todas as execucoes seguintes degradadas."""
	from nvdastudio.core.orchestrator import Orchestrator

	src = inspect.getsource(Orchestrator)
	assert src.count("resetar_saida_estruturada()") >= 1


def test_o_cliente_sinaliza_a_falha_de_conta():
	"""Sem alguem acionar o disjuntor, ele nunca dispara -- o erro que esta
	sessao encontrou dez vezes."""
	from nvdastudio.ai import opencode_go_client as og

	src = inspect.getsource(og)
	assert "marcar_saida_estruturada_indisponivel" in src
	assert "_sinalizar_conta_indisponivel(resp)" in src


def test_apenas_erros_de_conta_disparam():
	"""503 e timeout se resolvem retentando -- degradar por eles jogaria fora a
	garantia de JSON sem motivo."""
	from nvdastudio.ai import opencode_go_client as og

	src = inspect.getsource(og._sinalizar_conta_indisponivel)
	assert "(401, 402, 403, 429)" in src
