"""
Layout declarado, coerencia entre arquivos e convergencia do orcamento.

Os tres fecham a mesma classe de problema, achada nos relatorios reais: o
pipeline gerava PECAS boas e nao garantia um TODO coerente, nem parava quando
deixava de convergir.

  1. LAYOUT   -- os nomes de arquivo nasciam da improvisacao do modelo. Bloco
                 sem anotacao de caminho caia no fallback module_N.py de
                 addon_builder._infer_python_filename(), justamente o unico
                 nome que o NVDA nunca carrega dentro de um pacote.
  2. COERENCIA-- cada arquivo era validado isolado; ninguem perguntava se os
                 imports entre eles fecham.
  3. ORCAMENTO-- o circuit breaker existia e era consultado, mas o medidor so
                 era alimentado no FIM do pipeline. Durante a execucao
                 tokens_used ficava em zero: ha relatorio com 41 retries e
                 4,6 MILHOES de tokens contra um teto de 500 mil.
"""

import pytest

from nvdastudio.core.planner import (
	MODULE_VERSION as PLANNER_VERSION,
	_normalize_expected_files,
	format_expected_files_for_prompt,
)
from nvdastudio.sub_agents.ast_validator import validate_internal_imports

assert PLANNER_VERSION == "2.40.0"


class TestLayoutDeclarado:
	def test_normaliza_forma_sem_mudar_intencao(self):
		saida = _normalize_expected_files(
			["globalPlugins\\X\\__init__.py", "/manifest.ini", "", None, 42, "manifest.ini"],
			"X",
		)
		assert saida == ["globalPlugins/X/__init__.py", "manifest.ini"]

	def test_preserva_ordem_declarada(self):
		saida = _normalize_expected_files(
			["manifest.ini", "globalPlugins/X/__init__.py", "globalPlugins/X/a.py"], "X",
		)
		assert saida == ["manifest.ini", "globalPlugins/X/__init__.py", "globalPlugins/X/a.py"]

	@pytest.mark.parametrize(
		"declarado",
		[
			["globalPlugins/X/__init__.py"],
			["appModules/notepad.py"],
			["synthDrivers/voz.py"],
			["brailleDisplayDrivers/display.py"],
		],
	)
	def test_layout_com_ponto_de_entrada_passa_intacto(self, declarado):
		assert _normalize_expected_files(list(declarado), "X") == declarado

	def test_reparo_usa_o_pacote_ja_declarado(self):
		"""REGRESSAO de um defeito desta implementacao: a primeira versao
		acrescentava globalPlugins/<addon_name>/__init__.py mesmo quando a IA
		ja tinha declarado OUTRO pacote -- criaria DOIS pacotes, com o ponto de
		entrada vazio ao lado dos arquivos reais. Pior que o problema original."""
		saida = _normalize_expected_files(
			["globalPlugins/Alpha/servico.py", "globalPlugins/Alpha/qa/s.py"], "NomeDiferente",
		)
		assert saida[0] == "globalPlugins/Alpha/__init__.py"
		assert not any("NomeDiferente" in c for c in saida)

	def test_reparo_cai_no_addon_name_sem_pacote_declarado(self):
		saida = _normalize_expected_files(["manifest.ini"], "Alfa")
		assert "globalPlugins/Alfa/__init__.py" in saida

	def test_reparo_com_addon_name_vazio_nao_levanta(self):
		"""Roda dentro do pipeline: excecao aqui derrubaria o planejamento."""
		saida = _normalize_expected_files([], "")
		assert saida == ["globalPlugins/MeuAddon/__init__.py"]

	def test_controller_client_nao_recebe_reparo(self):
		"""Programa EXTERNO: nao tem globalPlugins/ nem addonHandler. Aplicar a
		regra do NVDA aqui inventaria um arquivo que nao faz sentido."""
		assert _normalize_expected_files(["prog.py"], "P", "controller_client") == ["prog.py"]

	def test_prompt_vazio_quando_nao_ha_layout(self):
		"""Sem declaracao o gerador segue como antes -- nunca inventar esqueleto."""
		assert format_expected_files_for_prompt([]) == ""

	def test_prompt_lista_os_caminhos_e_proibe_renomear(self):
		texto = format_expected_files_for_prompt(["globalPlugins/X/__init__.py", "manifest.ini"])
		assert "globalPlugins/X/__init__.py" in texto
		assert "manifest.ini" in texto
		assert "invente" in texto.lower() or "renomeie" in texto.lower()

	def test_fonte_unica_dos_diretorios_de_entrada(self):
		"""README Regra 5: se planner e orchestrator divergirem nessa lista, o
		planner declara um layout que o portao final recusa."""
		from nvdastudio.core.orchestrator import Orchestrator
		from nvdastudio.core.planner import NVDA_ENTRY_POINT_DIRS

		assert set(NVDA_ENTRY_POINT_DIRS) == set(Orchestrator._ENTRY_POINT_DIRS)


class TestCoerenciaEntreArquivos:
	def test_addon_coerente_passa(self):
		arquivos = {
			"globalPlugins/A/__init__.py": "from .qa.service import QaService\n",
			"globalPlugins/A/qa/__init__.py": "",
			"globalPlugins/A/qa/service.py": "class QaService: pass\n",
		}
		assert validate_internal_imports(arquivos).ok is True

	def test_modulo_que_ninguem_gerou(self):
		"""O bug real dos addons Gemini: o arquivo que amarra as features
		importa de um modulo que nenhum step chegou a gerar."""
		arquivos = {
			"globalPlugins/A/__init__.py": "from .summarizer.service import Sum\n",
			"globalPlugins/A/qa/service.py": "class QaService: pass\n",
		}
		r = validate_internal_imports(arquivos)
		assert r.ok is False
		assert "summarizer" in r.violacoes[0]

	def test_nome_que_o_modulo_nao_define(self):
		arquivos = {
			"globalPlugins/A/__init__.py": "from .x import NaoExiste\n",
			"globalPlugins/A/x.py": "class Existe: pass\n",
		}
		r = validate_internal_imports(arquivos)
		assert r.ok is False
		assert "NaoExiste" in r.violacoes[0]

	def test_import_star_nunca_e_reportado(self):
		"""O conteudo de `import *` e dinamico -- julgar aqui daria falso
		positivo, inclusive no __init__.py que o auto-fix do addon_builder
		gera com `from .module_1 import *`."""
		arquivos = {
			"globalPlugins/A/__init__.py": "from .module_1 import *\n",
			"globalPlugins/A/module_1.py": "class GlobalPlugin: pass\n",
		}
		assert validate_internal_imports(arquivos).ok is True

	def test_importar_submodulo_do_pacote_passa(self):
		arquivos = {
			"globalPlugins/A/__init__.py": "from .qa import service\n",
			"globalPlugins/A/qa/__init__.py": "",
			"globalPlugins/A/qa/service.py": "class S: pass\n",
		}
		assert validate_internal_imports(arquivos).ok is True

	def test_alvo_com_syntax_error_nao_vira_nome_ausente(self):
		"""REGRESSAO de um defeito desta implementacao: modulo com SyntaxError
		entrava com conjunto vazio de nomes, entao TODO import dele virava
		'nome ausente' -- diagnostico errado para um erro que outro degrau, mais
		barato, ja reporta certo."""
		arquivos = {
			"globalPlugins/A/__init__.py": "from .x import Y\n",
			"globalPlugins/A/x.py": "def (",
		}
		assert validate_internal_imports(arquivos).ok is True

	def test_import_absoluto_nao_e_julgado(self):
		"""Pode vir do stdlib, de lib/ bundlado ou dos modulos do NVDA --
		validate_python_imports() no addon_builder ja cuida desse lado."""
		arquivos = {
			"globalPlugins/A/__init__.py": "import globalPluginHandler\nfrom wx import Dialog\n",
			"globalPlugins/A/x.py": "x = 1\n",
		}
		assert validate_internal_imports(arquivos).ok is True

	def test_sem_arquivos_faz_fail_open(self):
		assert validate_internal_imports({}).ok is True


class TestConvergenciaDoOrcamento:
	"""O circuit breaker existia e era consultado a cada tentativa desde a
	5.28.0 -- mas lia um medidor que so era alimentado no FIM do pipeline."""

	def _orquestrador_nu(self):
		from nvdastudio.core.orchestrator import Orchestrator

		o = Orchestrator.__new__(Orchestrator)
		o._tokens_by_model = {}
		o._budget_recorded_in_flight = False
		return o

	def test_consumo_em_voo_chega_ao_orcamento(self):
		from nvdastudio.utils.iteration_budget import budget

		budget.reset()
		o = self._orquestrador_nu()
		assert budget.can_continue()[0] is True
		for _ in range(5):
			o._track_model_tokens("kimi-k2.7-code", 100_000, "code_generation")
		assert budget.can_continue()[0] is False, (
			"500 mil tokens deveriam esgotar o teto padrao -- sem isso o "
			"pipeline corre ate milhoes de tokens, como nos relatorios reais"
		)
		budget.reset()

	def test_marca_que_houve_registro_em_voo(self):
		from nvdastudio.utils.iteration_budget import budget

		budget.reset()
		o = self._orquestrador_nu()
		o._track_model_tokens("kimi-k2.7-code", 1000, "code_generation")
		assert o._budget_recorded_in_flight is True
		budget.reset()

	def test_zero_token_nao_marca_nem_conta(self):
		from nvdastudio.utils.iteration_budget import budget

		budget.reset()
		o = self._orquestrador_nu()
		o._track_model_tokens("kimi-k2.7-code", 0, "code_generation")
		assert o._budget_recorded_in_flight is False
		budget.reset()

	def test_registro_terminal_nao_conta_de_novo(self):
		"""REGRESSAO: com o medidor alimentado em voo, repetir o registro no
		fim contaria os mesmos tokens duas vezes e derrubaria o orcamento pela
		metade do gasto real."""
		from nvdastudio.core.orch_types import StepResult
		from nvdastudio.utils.iteration_budget import budget

		budget.reset()
		o = self._orquestrador_nu()
		o._track_model_tokens("kimi-k2.7-code", 10_000, "code_generation")
		antes = budget.get_state().tokens_used
		o._record_iteration_budget([
			StepResult(
				step_id="cg1", step_type="code_generation", output="", approved=True,
				score=100, tokens_used=10_000, model_used="kimi-k2.7-code",
			)
		])
		assert budget.get_state().tokens_used == antes
		budget.reset()

	def test_registro_terminal_ainda_age_sem_consumo_em_voo(self):
		"""Caminhos que morrem antes da primeira chamada de LLM continuam
		contabilizados -- senao o orcamento perderia o custo das falhas caras."""
		from nvdastudio.core.orch_types import StepResult
		from nvdastudio.utils.iteration_budget import budget

		budget.reset()
		o = self._orquestrador_nu()
		o._record_iteration_budget([
			StepResult(
				step_id="cg1", step_type="code_generation", output="", approved=False,
				score=0, tokens_used=5_000, model_used="kimi-k2.7-code",
			)
		])
		assert budget.get_state().tokens_used == 5_000
		budget.reset()


class TestDigestDosRelatorios:
	"""O instrumento que substitui auditoria manual."""

	def _importar(self):
		import importlib.util
		import pathlib

		caminho = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "eval_report_digest.py"
		spec = importlib.util.spec_from_file_location("eval_report_digest", caminho)
		assert spec and spec.loader
		mod = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(mod)
		return mod

	def test_separa_infraestrutura_de_capacidade(self):
		"""Misturar as duas e o erro de leitura mais comum nestes relatorios:
		52 execucoes falharam so por falta de chave."""
		m = self._importar()
		assert m._classifica_erro("Client error '429 Too Many Requests'") == "rate limit / quota"
		assert m._classifica_erro("Chave API para ollama nao configurada") == "chave ausente"
		assert m._classifica_erro("nenhum arquivo Python valido foi gerado") == ""

	def test_usa_a_mesma_regra_de_carregamento_do_orchestrator(self):
		m = self._importar()
		assert m._tem_ponto_de_entrada(["globalPlugins/A/__init__.py"]) is True
		assert m._tem_ponto_de_entrada(["appModules/notepad.py"]) is True
		assert m._tem_ponto_de_entrada(["globalPlugins/A/module_1.py"]) is False

	def test_diretorios_de_entrada_batem_com_o_addon(self):
		"""O script roda fora do pacote (checkout sem deps) e por isso repete a
		lista -- este teste garante que a copia nao divirja em silencio."""
		from nvdastudio.core.planner import NVDA_ENTRY_POINT_DIRS

		m = self._importar()
		assert set(m._ENTRY_POINT_DIRS) == set(NVDA_ENTRY_POINT_DIRS)

	# digest() sobre entrada vazia nao pode levantar -- roda em CI sem relatorios
	def test_digest_com_lista_vazia(self):
		m = self._importar()
		assert isinstance(m.digest([], 5), str)
