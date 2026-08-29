"""
Ponto de entrada carregavel: o portao que impede "sucesso" de addon morto.

ACHADO REAL (2026-08-29), medido nos 379 relatorios de tests/e2e/relatorios/:
9 addons foram entregues com success=True e NAO seriam carregados pelo NVDA.
Todos os casos abaixo sao reproducoes literais desses relatorios, com nome e
data, para que a regressao seja rastreavel ate a execucao que a revelou.

O NVDA carrega addon por CONVENCAO DE CAMINHO, nao por conteudo: um pacote em
globalPlugins/ so e carregado pelo seu __init__.py, e qualquer outro .py ao
lado dele e ignorado. Um addon sem ponto de entrada nao falha com erro -- ele
instala normalmente e simplesmente nao existe para o usuario cego, que nao tem
como descobrir por que nada acontece.

A deteccao ja existia (`validate_addon_structure` emite ESTRUTURA-008) e a
mensagem aparecia escrita nos relatorios -- mas rodava so no caminho de
empacotamento da GUI, nunca no veredito do pipeline. O defeito era detectado,
registrado, e ignorado.
"""

from nvdastudio.core.orchestrator import Orchestrator


def _falta(arquivos: set[str]) -> str:
	return Orchestrator._missing_loadable_entry_point(arquivos)


class TestPontosDeEntradaValidos:
	"""As formas que o NVDA realmente carrega. Nenhuma pode ser bloqueada --
	122 sucessos legitimos dos relatorios historicos dependem disso."""

	def test_pacote_global_plugin(self):
		assert _falta({"globalPlugins/MeuAddon/__init__.py"}) == ""

	def test_app_module_solto(self):
		assert _falta({"appModules/notepad.py"}) == ""

	def test_synth_driver(self):
		assert _falta({"synthDrivers/minhaVoz.py"}) == ""

	def test_braille_display_driver(self):
		assert _falta({"brailleDisplayDrivers/meuDisplay.py"}) == ""

	def test_vision_enhancement_provider(self):
		assert _falta({"visionEnhancementProviders/meuRealce.py"}) == ""

	def test_pacote_valido_com_modulos_auxiliares_ao_lado(self):
		"""Modulo auxiliar nao invalida o addon -- so a AUSENCIA do __init__.py."""
		assert _falta({
			"globalPlugins/MeuAddon/__init__.py",
			"globalPlugins/MeuAddon/servico.py",
			"globalPlugins/MeuAddon/gui/painel.py",
		}) == ""

	def test_caminho_com_barra_invertida_do_windows(self):
		"""Os blocos gerados as vezes vem com separador do Windows."""
		assert _falta({"globalPlugins\\MeuAddon\\__init__.py".replace("\\", "/")}) == ""


class TestRegressaoDosRelatoriosReais:
	"""Cada teste reproduz um addon que foi entregue como sucesso e nao
	funcionava. Nome e data conferem com o arquivo em tests/e2e/relatorios/."""

	def test_gemini_multimodal_so_module_1(self):
		"""2026-08-16 11:48 -- GeminiMultimodal, score 80.8, success=True.
		Um unico module_1.py solto no pacote: o NVDA ignora o arquivo inteiro."""
		erro = _falta({"globalPlugins/GeminiMultimodal/module_1.py"})
		assert erro != ""
		assert "globalPlugins/GeminiMultimodal" in erro
		assert "__init__.py" in erro

	def test_assistente_leitura_arquitetura_por_feature_sem_init(self):
		"""2026-08-17 10:27 -- AssistenteLeituraGemini, 16 arquivos Python,
		subpacotes qa/, summarizer/, web_search/ ... e nenhum __init__.py na
		raiz do addon. Arquitetura bonita, addon morto."""
		erro = _falta({
			"globalPlugins/AssistenteLeituraGemini/client.py",
			"globalPlugins/AssistenteLeituraGemini/qa/service.py",
			"globalPlugins/AssistenteLeituraGemini/qa/__init__.py",
			"globalPlugins/AssistenteLeituraGemini/summarizer/service.py",
		})
		assert erro != ""
		assert "globalPlugins/AssistenteLeituraGemini" in erro

	def test_init_no_subpacote_nao_conta_como_ponto_de_entrada(self):
		"""2026-08-16 03:31 -- GeminiMultimodal. Este NAO era pego por
		ESTRUTURA-008 (existe um __init__.py em algum lugar), mas o arquivo
		esta em audio/, nao na raiz do pacote -- o NVDA continua sem carregar
		nada. O portao e mais preciso que a checagem estrutural aqui."""
		erro = _falta({
			"globalPlugins/GeminiMultimodal/audio/audio_handler.py",
			"globalPlugins/GeminiMultimodal/audio/__init__.py",
		})
		assert erro != ""

	def test_arquivo_unico_em_subpacote_profundo(self):
		"""2026-08-16 00:43 -- GeminiMultimodal, tambem sem sinal estrutural
		previo: agent/gemini_client.py e o unico Python do addon."""
		assert _falta({"globalPlugins/GeminiMultimodal/agent/gemini_client.py"}) != ""


class TestMensagemDeErro:
	"""A mensagem vira contexto do proximo retry. Sem nomear o pacote orfao, o
	modelo tende a reescrever o addon inteiro em vez de criar um arquivo."""

	def test_nomeia_o_pacote_orfao(self):
		erro = _falta({"globalPlugins/Alpha/a.py", "globalPlugins/Beta/b.py"})
		assert "globalPlugins/Alpha" in erro
		assert "globalPlugins/Beta" in erro

	def test_explica_a_consequencia_para_o_usuario(self):
		"""Regra do projeto: o texto visivel diz o que o usuario perde, nao so
		o nome tecnico do defeito."""
		erro = _falta({"globalPlugins/X/a.py"})
		assert "não faria nada" in erro or "nao faria nada" in erro

	def test_python_fora_de_diretorio_carregavel_tem_mensagem_propria(self):
		erro = _falta({"utils/helper.py", "servicos/api.py"})
		assert erro != ""
		assert "globalPlugins/" in erro
		assert "appModules/" in erro


class TestIntegracaoComOPortaoDeArtefatos:
	"""_validate_minimum_addon_artifacts e o portao real do pipeline; o novo
	check tem que estar ligado nele, nao so existir solto."""

	def _plano(self, project_type="addon"):
		from nvdastudio.core.planner import ExecutionPlan, ExecutionStep

		step = ExecutionStep(
			step_id="cg1",
			step_type="code_generation",
			description="x",
			model_id="alto",
			reasoning_params={},
			depends_on=[],
			context_from_steps=[],
			expected_output="x",
		)
		return ExecutionPlan(
			plan_id="p1", original_query="q", steps=[step], project_type=project_type,
		)

	def _resultado(self):
		from nvdastudio.core.orch_types import StepResult

		return StepResult(
			step_id="cg1", step_type="code_generation", output="", approved=True, score=100,
		)

	def test_addon_sem_init_e_reprovado_pelo_portao_real(self):
		saida = (
			"```python:globalPlugins/MeuAddon/module_1.py\npass\n```\n"
			"```ini:manifest.ini\nname = MeuAddon\n```\n"
		)
		erro = Orchestrator._validate_minimum_addon_artifacts(
			self._plano(), [self._resultado()], {"cg1": saida},
		)
		assert erro != ""
		assert "__init__.py" in erro

	def test_addon_com_init_passa_pelo_portao_real(self):
		saida = (
			"```python:globalPlugins/MeuAddon/__init__.py\npass\n```\n"
			"```ini:manifest.ini\nname = MeuAddon\n```\n"
		)
		erro = Orchestrator._validate_minimum_addon_artifacts(
			self._plano(), [self._resultado()], {"cg1": saida},
		)
		assert erro == ""

	def test_controller_client_nao_exige_ponto_de_entrada_do_nvda(self):
		"""REGRESSAO: controller_client e um programa EXTERNO -- nao tem
		globalPlugins/ nem manifest.ini. Aplicar a regra de carregamento do
		NVDA aqui reprovaria toda criacao valida desse tipo, o mesmo bug que
		a 5.50.0 ja teve de corrigir para o manifest.ini."""
		saida = "```python:meu_programa.py\nprint('oi')\n```\n"
		erro = Orchestrator._validate_minimum_addon_artifacts(
			self._plano("controller_client"), [self._resultado()], {"cg1": saida},
		)
		assert erro == ""
