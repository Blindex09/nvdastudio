"""
Contexto NVDA proporcional ao que cada step precisa.

O GARGALO MEDIDO (2026-08-30, a partir dos relatorios E2E reais):

`get_docs_code_generation()` injetava os 26 arquivos-fonte do NVDA SEMPRE, em
toda chamada -- 362 mil chars, ~90 mil tokens. Somado ao `_SYSTEM` do gerador,
o custo FIXO por tentativa passava de 100 mil tokens.

Nos relatorios isso aparecia assim:

    cg_settings   ret=3  tok=412.126  ok=False   <- 41% do orcamento do addon
    cg_gemini     ret=3  tok=129.359  ok=True
    cg_questions  ret=0  tok=0        <- nunca rodou
    cg_history    ret=0  tok=0        <- nunca rodou
    cg_core       ret=0  tok=0        <- nunca rodou (geraria o __init__.py!)

Um step falhando 3 vezes numa questao trivial ("_() sem importar a funcao de
traducao") consumia 412 mil tokens e impedia os seguintes de rodar. O step que
geraria o `__init__.py` nunca chegou a executar -- e o addon foi recusado por
falta de ponto de entrada. O gargalo nao era o modelo nem o loop de retry: era
o pedagio de entrada, cobrado em toda tentativa.

E a decomposicao por arquivo (planner 2.33.0), correta em si, MULTIPLICAVA o
problema: cada step novo pagava o pedagio de novo.

QUEM DECIDE (Regra 7): a IA declara os topicos no plano; este modulo so MONTA o
que foi declarado. Sem declaracao, devolve tudo -- contexto faltando custa mais
caro que contexto sobrando.
"""

import pytest

from nvdastudio.builder.nvda_context import (
	NVDA_DOC_TOPICS,
	extract_nvda_topics,
	get_docs_code_generation,
	nvda_topics_marker,
)


class TestEconomiaReal:
	def test_escopo_declarado_custa_menos_da_metade(self):
		"""O ponto todo da mudanca. Sem isso, 5 steps x 3 tentativas x 103 mil
		tokens fixos = 1,5 milhao antes de qualquer trabalho util."""
		completo = len(get_docs_code_generation())
		settings = len(get_docs_code_generation(topics=["gui", "config"]))
		assert settings < completo * 0.55, (
			f"escopo gui+config custa {settings} de {completo} -- economia insuficiente"
		)

	@pytest.mark.parametrize("topico", sorted(NVDA_DOC_TOPICS))
	def test_todo_topico_isolado_e_mais_barato_que_tudo(self, topico):
		completo = len(get_docs_code_generation())
		assert len(get_docs_code_generation(topics=[topico])) < completo

	def test_todos_os_topicos_juntos_equivalem_ao_completo(self):
		"""Nenhum arquivo pode ficar orfao de grupo: se um so entra no contexto
		completo, o step que precisar dele nunca vai recebe-lo."""
		juntos = get_docs_code_generation(topics=list(NVDA_DOC_TOPICS))
		completo = get_docs_code_generation()
		assert len(juntos) == len(completo), (
			"algum arquivo-fonte nao pertence a nenhum topico nem ao core -- "
			"ficaria inalcancavel para qualquer step que o declarasse"
		)


class TestPadraoSeguro:
	"""Contexto faltando custa mais caro que contexto sobrando."""

	def test_sem_topicos_devolve_tudo(self):
		assert len(get_docs_code_generation(topics=[])) == len(get_docs_code_generation())

	def test_none_devolve_tudo(self):
		assert len(get_docs_code_generation(topics=None)) == len(get_docs_code_generation())

	def test_topico_desconhecido_nao_derruba_a_geracao(self):
		"""Nome errado vindo do modelo entrega o core, nunca uma excecao."""
		saida = get_docs_code_generation(topics=["inventado_pelo_modelo"])
		assert saida
		assert "globalPluginHandler" in saida, "o core precisa entrar sempre"

	def test_core_entra_em_todo_escopo(self):
		"""addonHandler/api/ui sao o piso: qualquer arquivo de addon precisa."""
		for topico in NVDA_DOC_TOPICS:
			saida = get_docs_code_generation(topics=[topico])
			assert "addonHandler" in saida, f"core ausente no topico {topico}"


class TestMarcadorNoPrompt:
	"""Mesmo canal do project_type_marker: o sub-agente nao recebe o objeto do
	step, so o prompt."""

	def test_ida_e_volta(self):
		prompt = nvda_topics_marker(["gui", "config"]) + "Tarefa: painel de config"
		assert extract_nvda_topics(prompt) == ["gui", "config"]

	def test_normaliza_caixa_e_espaco(self):
		assert extract_nvda_topics(nvda_topics_marker(["  GUI  ", "Config"])) == ["gui", "config"]

	def test_lista_vazia_nao_gera_marcador(self):
		"""Sem marcador o gerador injeta tudo -- o comportamento anterior."""
		assert nvda_topics_marker([]) == ""
		assert nvda_topics_marker(None) == ""

	def test_prompt_sem_marcador(self):
		assert extract_nvda_topics("Tarefa normal, sem marcador nenhum") == []

	def test_marcador_malformado_nao_levanta(self):
		"""Falha aqui trocaria 'prompt grande' por 'step morto'."""
		assert extract_nvda_topics("[NVDA-TOPICS:gui") == []
		assert extract_nvda_topics("") == []


class TestCosturaComOStep:
	def test_execution_step_tem_o_campo(self):
		from nvdastudio.core.planner import ExecutionStep

		step = ExecutionStep("s1", "code_generation", "x", "alto")
		assert step.nvda_topics == []

	def test_orchestrator_injeta_o_marcador_no_prompt(self):
		import inspect

		from nvdastudio.core.orchestrator import Orchestrator

		src = inspect.getsource(Orchestrator._build_step_prompt)
		assert "nvda_topics_marker" in src

	def test_code_generator_consome_o_marcador(self):
		import inspect

		from nvdastudio.sub_agents import code_generator

		src = inspect.getsource(code_generator)
		assert "extract_nvda_topics(prompt)" in src, (
			"o gerador precisa ler os topicos do prompt -- sem isso o marcador "
			"e injetado e ignorado, e o custo fixo volta"
		)


class TestReducaoNoRetryFoiRevertida:
	"""
	HIPOTESE TESTADA EM E2E REAL E DERRUBADA (2026-09-01).

	A ideia: "na tentativa 2 o modelo ja tem o codigo e a lista de problemas
	acumulados; falta corrigir um import, nao reaprender a API do NVDA". Enviar
	so o core no retry cortava 75% dos docs e 56% do custo do step.

	O mecanismo funcionou como projetado -- custo por tentativa caiu de ~103 mil
	para ~67 mil tokens. E o RESULTADO piorou muito:

	    AssistenteLeituraGemini   nota 52.0 -> 15.7
	    GeminiMultimodal         nota 32.7 ->  9.1

	O modelo PRECISA do contexto para fazer a correcao que o Critic pediu; sem a
	fonte do NVDA ele corrige no escuro. Economia de tokens que reduz a taxa de
	acerto nao e economia -- e so falhar mais barato.

	Estes testes existem para que a ideia nao volte sem medicao nova. O escopo
	por TOPICO continua valendo: ali o contexto e menor por ser IRRELEVANTE ao
	arquivo, nao por ser sonegado ao modelo.
	"""

	def test_retry_recebe_o_mesmo_contexto_da_primeira_tentativa(self):
		import inspect

		from nvdastudio.core.orchestrator import Orchestrator

		src = inspect.getsource(Orchestrator._build_step_prompt)
		assert "retry_core_apenas" not in src, (
			"a reducao de contexto no retry voltou -- ela foi medida em E2E real "
			"e DERRUBOU a nota de 52.0 para 15.7. Nao reintroduzir sem medir."
		)

	def test_topicos_declarados_continuam_valendo(self):
		"""O que foi revertido foi a reducao no RETRY, nao o escopo por topico."""
		import inspect

		from nvdastudio.core.orchestrator import Orchestrator

		src = inspect.getsource(Orchestrator._build_step_prompt)
		assert "nvda_topics_marker" in src
