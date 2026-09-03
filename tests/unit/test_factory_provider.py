"""Factory Droid como terceiro provedor, e a cadeia finalmente cross-provider.

Em 2026-09-03 os DOIS provedores do projeto falharam na mesma sessao: OpenCode
Go com 401 (sem saldo) e Ollama com 429 (rate limit). A
STRUCTURED_OUTPUT_MODEL_CHAIN parecia uma cadeia de cinco modelos e era cinco
modelos do MESMO provedor -- quando ele caiu, caiu tudo, e toda rodada passou a
planejar sem json_schema.

Metade destes testes trava as decisoes de ECONOMIA, que sao o requisito
declarado do projeto: nao vazar token sem necessidade, mesmo em addon grande.
Cada uma saiu de medicao no dia, nao de suposicao.
"""

import json

import pytest

from nvdastudio.ai import model_registry as mr
from nvdastudio.ai.factory_client import (
	_DEFAULT_MODEL,
	FactoryClient,
	FactoryClientError,
	_instrucao_de_schema,
)


def _cliente() -> FactoryClient:
	"""Instancia sem __init__: _achar_droid() exige o CLI instalado, e estes
	testes sao sobre parsing e economia, nao sobre a maquina do CI."""
	c = FactoryClient.__new__(FactoryClient)
	c._api_key = ""
	c._model_id = "kimi-k2.7-code"
	c._droid = "droid"
	return c


_ENVELOPE_OK = {
	"type": "result", "subtype": "success", "is_error": False,
	"duration_ms": 3370, "result": "conteudo gerado",
	"session_id": "abc-123",
	"usage": {
		"input_tokens": 100, "output_tokens": 50,
		"cache_read_input_tokens": 94644, "cache_creation_input_tokens": 200,
		"factory_credits": 82549,
	},
}


class TestLeituraDoEnvelope:

	def test_conteudo_sai_do_campo_result(self):
		r = _cliente()._ler_envelope(json.dumps(_ENVELOPE_OK), "", 0)

		assert r.content == "conteudo gerado"
		assert r.model_used == "kimi-k2.7-code"

	def test_is_error_vira_excecao_e_nao_conteudo(self):
		"""1 de 3 amostras medidas devolveu is_error. Se isso virasse conteudo,
		o Critic pontuaria uma mensagem de erro como se fosse resposta -- o
		defeito que a 5.79.0 corrigiu para os outros provedores."""
		env = dict(_ENVELOPE_OK, is_error=True, result="algo deu errado")

		with pytest.raises(FactoryClientError, match="erro na execucao"):
			_cliente()._ler_envelope(json.dumps(env), "", 0)

	def test_saida_vazia_vira_excecao(self):
		with pytest.raises(FactoryClientError, match="nao devolveu saida"):
			_cliente()._ler_envelope("", "boom", 1)

	def test_aviso_antes_do_json_nao_atrapalha(self):
		"""O droid pode imprimir aviso antes do envelope."""
		saida = "Aviso: nova versao disponivel\n" + json.dumps(_ENVELOPE_OK)

		r = _cliente()._ler_envelope(saida, "", 0)

		assert r.content == "conteudo gerado"

	def test_saida_sem_json_vira_excecao(self):
		with pytest.raises(FactoryClientError, match="nao e JSON reconhecivel"):
			_cliente()._ler_envelope("erro fatal, sem json aqui", "", 1)


class TestEconomia:
	"""O requisito declarado: o mais economico possivel, sem vazar token."""

	def test_tokens_contam_o_que_e_cobrado_cheio_e_nao_a_leitura_de_cache(self):
		"""tokens_used alimenta o medidor de orcamento, que e regua de CUSTO.
		Somar cache_read a peso cheio (94.644 aqui) penalizaria justamente o
		mecanismo que barateia a rodada, e o medidor recusaria trabalho que
		custa pouco."""
		r = _cliente()._ler_envelope(json.dumps(_ENVELOPE_OK), "", 0)

		assert r.tokens_used == 100 + 50 + 200

	def test_nada_fica_escondido_no_breakdown(self):
		"""Nao contar no medidor nao pode virar nao registrar: o custo real
		precisa estar disponivel para auditoria."""
		r = _cliente()._ler_envelope(json.dumps(_ENVELOPE_OK), "", 0)

		assert r.usage_breakdown["cache_read_input_tokens"] == 94644
		assert r.usage_breakdown["factory_credits"] == 82549
		assert r.usage_breakdown["session_id"] == "abc-123"

	def test_padrao_nunca_e_o_modelo_mais_caro(self):
		"""O padrao do proprio droid e claude-opus-5, o mais caro do catalogo:
		os 135 mil creditos por plano medidos no spike eram Opus. O padrao
		daqui e o mesmo heavy que o projeto ja usa nos outros provedores."""
		assert _DEFAULT_MODEL == "kimi-k2.7-code"
		assert "opus" not in _DEFAULT_MODEL

	def test_comando_nao_deixa_o_agente_explorar_o_projeto(self):
		"""O droid exec e agente de codigo: apontado para um repositorio, ele
		le arquivos e cobra por isso. E tambem blast radius -- o agente nao
		tem por que enxergar o projeto do usuario."""
		import inspect

		fonte = inspect.getsource(FactoryClient.chat)

		assert '"--cwd", trabalho' in fonte
		assert "mkdtemp" in fonte
		assert '"--disable-builtin-skills"' in fonte

	def test_nao_reusa_sessao(self):
		"""Medido: sessoes NOVAS ja leem o harness do cache (94.644 e 41.696
		em duas sessoes novas) -- o caching da Factory e entre sessoes. Reusar
		sessao so acumularia historico reenviado e pago, ainda por cima em
		cima do contexto que o orchestrator ja reenvia por tentativa."""
		import inspect

		fonte = inspect.getsource(FactoryClient.chat)

		assert '"-s"' not in fonte, "voltou a reusar sessao"


class TestSchemaVaiNoPrompt:
	"""O droid exec nao tem response_format; o -o json descreve o ENVELOPE."""

	def test_sem_response_format_nao_adiciona_nada(self):
		assert _instrucao_de_schema(None) == ""
		assert _instrucao_de_schema({}) == ""

	def test_schema_entra_com_as_descricoes(self):
		"""Medido: com o schema COMPACTO (sem as descricoes) o modelo devolveu
		dependencies com stdlib e caixa divergente no nome; com o schema
		completo, nenhum dos dois defeitos apareceu. As descricoes sao
		requisito, nao enfeite."""
		rf = {
			"type": "json_schema",
			"json_schema": {"name": "plano", "schema": {
				"type": "object",
				"properties": {"addon_name": {
					"type": "string",
					"description": "CamelCase, sem acentos",
				}},
			}},
		}

		txt = _instrucao_de_schema(rf)

		assert "APENAS um objeto JSON valido" in txt
		assert "CamelCase, sem acentos" in txt
		assert "description" in txt


class TestCadeiaCrossProvider:

	def setup_method(self):
		mr.resetar_saida_estruturada()

	def teardown_method(self):
		mr.resetar_saida_estruturada()

	def test_cadeia_tem_mais_de_um_provedor(self):
		"""O defeito original: cinco entradas, um provedor so."""
		provedores = {e.split("::", 1)[0] for e in mr.STRUCTURED_OUTPUT_MODEL_CHAIN}

		assert len(provedores) >= 2, (
			f"a cadeia voltou a ter um provedor so: {provedores}"
		)
		assert "factory" in provedores

	def test_toda_entrada_declara_o_provedor(self):
		for entrada in mr.STRUCTURED_OUTPUT_MODEL_CHAIN:
			assert "::" in entrada, f"entrada sem provedor: {entrada}"

	def test_queda_de_um_provedor_vai_para_o_proximo_nao_para_a_degradacao(self):
		"""O caso real de 2026-09-02: 401 sem saldo. Antes, isso derrubava a
		garantia inteira; agora sobra a Factory."""
		mr.marcar_saida_estruturada_indisponivel("HTTP 401", provider="opencode_go")

		escolhido = mr.get_structured_output_model(0)

		assert escolhido.startswith("factory::"), escolhido

	def test_so_degrada_quando_nenhum_provedor_da_cadeia_responde(self):
		mr.marcar_saida_estruturada_indisponivel("401", provider="opencode_go")
		mr.marcar_saida_estruturada_indisponivel("erro", provider="factory")

		escolhido = mr.get_structured_output_model(0)

		assert not escolhido.startswith("opencode_go::")
		assert not escolhido.startswith("factory::")
		assert escolhido, "degradou para nada -- o pipeline ficaria sem modelo"

	def test_reset_devolve_a_cadeia_inteira(self):
		"""O limite dos provedores e por janela de tempo: indisponibilidade e
		temporaria e nao pode virar permanente."""
		mr.marcar_saida_estruturada_indisponivel("401", provider="opencode_go")
		assert not mr.get_structured_output_model(0).startswith("opencode_go::")

		mr.resetar_saida_estruturada()

		assert mr.get_structured_output_model(0).startswith("opencode_go::")

	def test_default_do_marcador_continua_sendo_opencode_go(self):
		"""Compatibilidade com o unico chamador historico, que marcava sem
		dizer o provedor."""
		mr.marcar_saida_estruturada_indisponivel("sem provider explicito")

		assert mr.get_structured_output_model(0).startswith("factory::")


def test_factory_e_selecionavel_como_provedor():
	"""Sem entrar no dropdown e no mapa de chaves, o provedor existe no codigo
	e nao existe para o usuario."""
	from nvdastudio.gui import settings_panel as sp

	assert "factory" in sp._PROVIDER_CODES
	assert "factory" in sp._API_KEY_CONFIG_KEYS
	assert "factory" in sp._API_KEY_ENV_VARS
	assert sp._API_KEY_ENV_VARS["factory"] == "FACTORY_API_KEY"
