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
	assert mr.MODULE_VERSION == "1.22.0"


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


class TestCadeiaChegaNoProvedorDegradado:
	"""
	A cadeia de saida estruturada tem 5 modelos e TODOS no OpenCode Go. Quando
	a conta fica sem saldo, os 5 falham em sequencia e a excecao sobe -- foi o
	que matou a execucao de 2026-09-02 04:22 em 5 segundos, com zero steps.

	`call_with_structured_output()` reconsulta `get_structured_output_model(idx)`
	a cada iteracao, entao basta o disjuntor disparar na PRIMEIRA falha para a
	segunda iteracao ja cair no provedor ativo.

	O que faltava era o disjuntor nao ser acionado no endpoint certo: ele estava
	ligado so em /chat/completions, e o Clarifier usa a Responses API
	(/v1/responses). Cinco tentativas falhavam sem nunca marcar o provedor.
	"""

	def test_apos_o_disjuntor_a_cadeia_muda_de_provedor(self):
		_limpar()
		try:
			primeiro = mr.get_structured_output_model(0)
			mr.marcar_saida_estruturada_indisponivel("HTTP 401: CreditsError")
			segundo = mr.get_structured_output_model(1)
			assert primeiro.startswith("opencode_go::")
			assert not segundo.startswith("opencode_go::"), (
				"a cadeia continuaria batendo na conta sem saldo ate esgotar"
			)
		finally:
			_limpar()

	def test_TODA_requisicao_do_cliente_aciona_o_disjuntor(self):
		"""Contagem EXATA contra `raise_for_status`, nao um minimo.

		A primeira versao deste teste exigia ">= 2" e passou com o defeito: eu
		tinha instrumentado as duas chamadas nao-streaming e deixado as duas de
		STREAMING de fora -- e o Clarifier usa streaming. A execucao morreu de
		novo em 1,55s, com o teste verde.

		Um minimo nao verifica cobertura; so a contagem contra o total verifica.
		"""
		import inspect

		from nvdastudio.ai import opencode_go_client as og

		linhas = inspect.getsource(og).split(chr(10))
		requisicoes = sum(1 for ln in linhas if ln.strip() == "resp.raise_for_status()")
		ganchos = sum(
			1 for ln in linhas
			if ln.strip() == "_sinalizar_conta_indisponivel(resp)"
		)
		assert requisicoes > 0, "precondicao: o cliente faz requisicoes"
		assert ganchos == requisicoes, (
			f"{requisicoes} requisicoes e so {ganchos} acionam o disjuntor -- "
			"a que ficar de fora mata a execucao sem marcar o provedor"
		)

	def test_streaming_le_o_corpo_antes_de_checar(self):
		"""Em resposta de streaming o corpo so existe apos read(); sem isso a
		mensagem de CreditsError chegaria vazia e o motivo logado seria inutil."""
		import inspect

		from nvdastudio.ai import opencode_go_client as og

		assert "resp.read()" in inspect.getsource(og)


class TestPlannerRefazNoProvedorDegradado:
	"""
	O Planner chama `create_llm_client()` DIRETO, sem passar pela cadeia de
	`llm_factory.call_with_structured_output()` -- e por isso nao reconsultava o
	modelo depois que o disjuntor disparava.

	Medido em 2026-09-02: TRES execucoes seguidas do complexo minimo morreram em
	1,5 a 5 segundos, com zero steps e zero tokens. Em isolamento o mecanismo
	funcionava (o Clarifier degradava e concluia), porque ele passa pela cadeia.
	O Planner nao passa: capturava LLMClientError, logava e relancava.

	A chamada que DISPARA o disjuntor precisa ser a primeira a se beneficiar
	dele.
	"""

	def test_refaz_uma_vez_quando_o_modelo_muda(self):
		import inspect

		from nvdastudio.core.planner import Planner

		src = inspect.getsource(Planner._call_planner_llm)
		i = src.index("except LLMClientError")
		trecho = src[i:]
		assert "get_structured_output_model(0)" in trecho, (
			"o Planner nao reconsulta o modelo depois da falha"
		)
		assert "cliente_degradado" in trecho

	def test_nao_refaz_quando_o_modelo_e_o_mesmo(self):
		"""Sem essa guarda viraria laco contra um provedor que nao vai
		responder -- e o erro original ficaria escondido atras de repeticao."""
		import inspect

		from nvdastudio.core.planner import Planner

		src = inspect.getsource(Planner._call_planner_llm)
		i = src.index("modelo_degradado = ")
		assert "if modelo_degradado == planner_model:" in src[i:i + 260]
		assert "raise" in src[i:i + 320]

	def test_a_degradacao_do_planner_e_anunciada(self):
		"""O plano degradado pode cair em `_minimal_plan()` -- um pedido
		complexo viraria addon simples. Quem le o log precisa saber."""
		import inspect

		from nvdastudio.core.planner import Planner

		src = inspect.getsource(Planner._call_planner_llm)
		assert "SEM garantia de json_schema" in src
		assert "plano cai no minimo" in src
