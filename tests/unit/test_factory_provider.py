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


# Ids confirmados AO VIVO em 2026-09-03: o `droid` lista os validos quando
# recusa um invalido. Qualquer id fora desta lista e recusado pelo CLI.
_IDS_VALIDOS_NA_FACTORY = frozenset({
	"auto", "claude-fable-5", "claude-opus-5", "claude-opus-5-fast",
	"claude-sonnet-5", "claude-sonnet-4-6", "claude-haiku-4-5-20251001",
	"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5", "gpt-5.4",
	"gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.2", "gemini-3.1-pro-preview",
	"gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "inkling",
	"glm-5.3-flash", "glm-5.3", "glm-5.2", "glm-5.2-fast", "kimi-k3",
	"kimi-k2.7-code", "kimi-k2.6", "nemotron-3-ultra",
	"deepseek-v4-flash-0731", "deepseek-v4-pro", "minimax-m3", "grok-4.6",
	"grok-4.5", "minimax-m2.7",
})


class TestCalibracaoDoRoteamento:
	"""A escada de custo foi MEDIDA na Factory (creditos reportados pelo
	proprio usage.factory_credits, prompt identico nos seis modelos):

	    kimi-k2.7-code               894    1.0x   JSON ok
	    glm-5.3-flash              1.074    1.2x   JSON ok
	    gpt-5.4-mini               1.192    1.3x   JSON ok
	    claude-haiku-4-5-20251001  6.634    7.4x   JSON FALHOU
	    claude-sonnet-5           14.006   15.7x   JSON ok
	    gemini-3.7-flash          18.437   20.6x   JSON ok
	"""

	def test_factory_nao_cai_silenciosamente_no_catalogo_do_ollama(self):
		"""Sem a chave no mapa, select_model() fazia `provider = "ollama"` e
		devolvia ids do Ollama para executar na Factory. `deepseek-v4-flash`
		existe no Ollama; na Factory o id e `deepseek-v4-flash-0731`."""
		from nvdastudio.ai.model_registry import _UI_PROVIDER_TO_REGISTRY_PROVIDERS

		assert "factory" in _UI_PROVIDER_TO_REGISTRY_PROVIDERS

	def test_todo_modelo_roteado_existe_na_factory(self):
		"""A regressao que importa: id que o droid recusa derruba o step."""
		from nvdastudio.ai.model_registry import get_provider_step_models
		from nvdastudio.ai.model_router import select_model

		tiers = get_provider_step_models("factory")
		for tier, modelo in tiers.items():
			assert modelo in _IDS_VALIDOS_NA_FACTORY, f"{tier}={modelo}"

		for complexidade in ("low", "medium", "high"):
			for step in ("code_generation", "documentation", "assembly", "web_research"):
				escolhido = select_model("factory", step, "alto", complexity=complexidade)
				assert escolhido in _IDS_VALIDOS_NA_FACTORY, (
					f"{step}/{complexidade} -> {escolhido}"
				)

	def test_leve_e_pesado_sao_o_mesmo_por_medicao_e_nao_por_descuido(self):
		"""Nao ha tier mais barato na Factory: o kimi-k2.7-code, que o projeto
		ja usa como heavy, e o mais barato do catalogo. Mandar step leve para
		o Haiku custaria 7,4x A MAIS e ainda erraria o JSON."""
		from nvdastudio.ai.model_registry import get_provider_step_models

		tiers = get_provider_step_models("factory")

		assert tiers["light"] == tiers["heavy"] == "kimi-k2.7-code"

	def test_nao_ha_frontier_na_factory(self):
		"""Correcao de uma decisao minha do mesmo dia. A 1.21.0 pos
		claude-sonnet-5 como frontier justificando 15,7x com "UM step que
		precisa acertar". Nao e um step: apply_model_budget() dimensiona o slot
		elevado como PERCENTUAL do plano, e com retry virou oito chamadas.

		Medido na rodada de 2026-09-03 17:26, carga real:

		    claude-sonnet-5   8 chamadas  1.704.493 creditos  71,4%
		    kimi-k2.7-code    8 chamadas    659.444 creditos  27,6%
		    gpt-5.6-luna     24 chamadas     23.065 creditos   1,0%

		71,4% da conta num modelo que nao entregou melhor: o cg_core que ele
		gerou precisou da aceitacao por ressalva (score 87) e o addon saiu
		incompleto mesmo assim."""
		from nvdastudio.ai.model_registry import get_provider_step_models

		assert "frontier" not in get_provider_step_models("factory")

	def test_complexidade_alta_usa_o_heavy_e_nao_um_modelo_caro(self):
		from nvdastudio.ai.model_router import select_model

		for complexidade in ("low", "medium", "high"):
			escolhido = select_model(
				"factory", "code_generation", "alto", complexity=complexidade,
			)
			assert escolhido == "kimi-k2.7-code", complexidade
			assert "sonnet" not in escolhido and "opus" not in escolhido

	def test_factory_e_resgate_valido_para_o_ollama(self):
		"""O criterio ja escolhido pelo usuario para o resgate e ASSINATURA:
		'so nao faco isso com os outros, por que os outros nao tenho
		assinatura'. A Factory e assinatura, mesma categoria do OpenCode Go --
		e em 2026-09-03 o OpenCode Go ficou sem saldo e o Ollama comecou a
		devolver 429, deixando o resgate sem para onde ir."""
		from nvdastudio.ai.model_router import (
			_ALL_ROUTABLE_PROVIDERS,
			_OLLAMA_RESCUE_PROVIDERS,
		)

		assert "factory" in _OLLAMA_RESCUE_PROVIDERS
		assert "factory" in _ALL_ROUTABLE_PROVIDERS
		# Provedor pago por token continua fora: o usuario nao tem credito avulso.
		for pago in ("openai", "anthropic", "gemini", "xai"):
			assert pago not in _OLLAMA_RESCUE_PROVIDERS


class TestSemToolUseFalhaAlto:
	"""O silencio mais caro da sessao.

	Ate a 1.0.0 o cliente recebia `tools` e ignorava. Os sub-agentes entregam
	resultado por tool call OBRIGATORIA (padrao "final answer as tool"):
	`entregar_sintese` no web_researcher, `entregar_critica_challenger` no
	design_review_agent. Sem o canal, eles deram voltas e reprovaram:

	    "a ferramenta entregar_sintese solicitada nao esta disponivel"
	    research_openai  692.032 tokens, reprovado 3x
	    dr0              132.875 tokens, reprovado

	824.907 tokens tentando chamar o que nao existe. Ignorar um parametro que
	nao se sabe honrar e pior que recusar: a recusa roteia para quem sabe.
	"""

	def test_tools_levanta_em_vez_de_ignorar(self):
		ferramentas = [{"type": "function", "function": {"name": "entregar_sintese"}}]

		with pytest.raises(FactoryClientError, match="nao aceita ferramentas"):
			_cliente().chat("pesquise algo", tools=ferramentas)

	def test_mensagem_nomeia_a_ferramenta_pedida(self):
		"""Sem o nome, quem le o log nao sabe QUAL step nao pode rodar aqui."""
		ferramentas = [{"type": "function", "function": {"name": "entregar_critica_challenger"}}]

		with pytest.raises(FactoryClientError, match="entregar_critica_challenger"):
			_cliente().chat("revise", tools=ferramentas)

	def test_sem_tools_segue_normal(self):
		"""A guarda nao pode barrar o caminho comum -- a maioria dos steps nao
		usa tool call."""
		import inspect

		fonte = inspect.getsource(FactoryClient.chat)
		i_guarda = fonte.index("if tools:")
		i_prompt = fonte.index("prompt = ")

		assert i_guarda < i_prompt, (
			"a guarda tem que vir antes de montar prompt e gastar subprocesso"
		)


class TestInstrucaoSoTexto:
	"""O `droid` e um AGENTE: sem instrucao explicita ele as vezes escreve
	arquivos e devolve so um RESUMO em vez do codigo (medido 2026-09-04: 2 de 5
	rodadas viraram agenticas, uma a 36.002 creditos). A instrucao 'so texto' no
	TOPO do prompt zerou isso (5/5 devolveram texto) e corta custo."""

	def test_prompt_do_droid_comeca_com_a_instrucao(self, monkeypatch):
		import nvdastudio.ai.factory_client as fc

		capturado = {}

		def fake_run(cmd, **kwargs):
			# o prompt vai no arquivo apontado por -f; le ANTES do rmtree do finally
			i = cmd.index("-f")
			with open(cmd[i + 1], encoding="utf-8") as fh:
				capturado["prompt"] = fh.read()

			class _R:
				returncode = 0
				stdout = json.dumps(_ENVELOPE_OK)
				stderr = ""

			return _R()

		monkeypatch.setattr(fc.subprocess, "run", fake_run)
		_cliente().chat("monte o addon final", system_override="voce e o assembler")

		prompt = capturado["prompt"]
		assert prompt.startswith(fc._INSTRUCAO_SO_TEXTO), (
			"a instrucao 'so texto' tem que vir no TOPO do prompt do droid"
		)
		assert "NAO crie" in prompt and "NAO use" in prompt
		# a instrucao nao pode engolir o pedido real do step
		assert "voce e o assembler" in prompt
		assert "monte o addon final" in prompt
