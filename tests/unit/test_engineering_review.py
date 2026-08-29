"""
Revisao de ENGENHARIA -- step novo, agente novo e principios compartilhados.

Lacuna real fechada (auditoria 2026-08-29): todo o julgamento de qualidade do
pipeline era conformidade a REGRA CATALOGADA (~50 IDs NVDA/WX-A11Y/ARCH).
Engenharia e o que sobra quando o catalogo acaba -- fronteira de modulo
errada, erro engolido, recurso sem dono, complexidade sem motivo. Nenhum ID
descreve isso e nenhum agente procurava.

Os testes travam as decisoes que dao errado silenciosamente se alguem mexer:
a costura entre planner (injeta) e dispatcher (executa), a fonte unica dos
principios, e o veredito lido de forma deterministica.
"""

from nvdastudio.core.planner import (
	STEP_ASSEMBLY,
	STEP_CODE_GENERATION,
	STEP_ENGINEERING_REVIEW,
	ExecutionStep,
	Planner,
	_EFFORT_BY_COMPLEXITY,
	_STEP_FALLBACK_MODEL,
	_STEP_FALLBACK_REASONING,
)
from nvdastudio.sub_agents import engineering_reviewer
from nvdastudio.sub_agents.dispatcher import _get_builtin_handler
from nvdastudio.utils import engineering_principles

assert engineering_reviewer.MODULE_VERSION == "1.0.0"
assert engineering_principles.MODULE_VERSION == "1.0.0"


def _step(step_id: str, step_type: str, **kw) -> ExecutionStep:
	return ExecutionStep(
		step_id=step_id,
		step_type=step_type,
		description="x",
		model_id="alto",
		reasoning_params={},
		depends_on=kw.get("depends_on", []),
		context_from_steps=kw.get("context_from_steps", []),
		expected_output="x",
	)


class TestCosturaPlannerDispatcher:
	"""O planner PROMETE um step_type; o dispatcher precisa CONSUMIR o mesmo.
	Um step_type sem handler declarado falha explicitamente em producao
	(dispatch_step levanta, sem fallback pra code_generator) -- e a classe de
	bug mais cara de descobrir tarde, entao fica travada aqui."""

	def test_step_type_tem_handler_no_dispatcher(self):
		handler = _get_builtin_handler(STEP_ENGINEERING_REVIEW)
		assert handler is engineering_reviewer.run

	def test_step_type_esta_nas_tres_tabelas_do_planner(self):
		assert STEP_ENGINEERING_REVIEW in _STEP_FALLBACK_MODEL
		assert STEP_ENGINEERING_REVIEW in _STEP_FALLBACK_REASONING
		assert STEP_ENGINEERING_REVIEW in _EFFORT_BY_COMPLEXITY

	def test_step_type_tem_timeout_estendido_nos_dois_lugares(self):
		"""Terceira costura, a mais facil de esquecer: existem DUAS tabelas de
		timeout indexadas por step_type, em modulos diferentes. Este step
		recebe o codigo gerado INTEIRO como entrada (depende de todos os
		code_generation), entao cair no default de 180s faria um addon
		multi-feature estourar num step que nao falhou."""
		from nvdastudio.ai.ollama_client import _EXTENDED_TIMEOUT_STEP_TYPES
		from nvdastudio.utils.timeouts import _DEFAULT_STEP_TIMEOUT, get_step_timeout

		assert get_step_timeout(STEP_ENGINEERING_REVIEW) > _DEFAULT_STEP_TIMEOUT
		assert STEP_ENGINEERING_REVIEW in _EXTENDED_TIMEOUT_STEP_TYPES

	def test_roda_no_modelo_leve_nao_consome_o_orcamento_de_20_por_cento(self):
		"""README Regra 8: critica e auditoria usam o leve; so geracao de
		codigo justifica o topo. apply_model_budget() so eleva
		code_generation -- este teste trava que a revisao continua fora do
		orcamento caro mesmo se alguem mexer nas tabelas."""
		from unittest.mock import patch

		from nvdastudio.core.planner import apply_model_budget

		steps = [
			_step("cg1", STEP_CODE_GENERATION),
			_step("er_inj", STEP_ENGINEERING_REVIEW, depends_on=["cg1"]),
		]

		def _fake(provider, step_type, configured_model, complexity="medium", **kw):
			return "LEVE" if complexity == "low" else "ELEVADO"

		with patch("nvdastudio.ai.model_router.select_model", _fake):
			apply_model_budget(steps, "ollama", "alto", complexity="high")

		revisao = next(s for s in steps if s.step_type == STEP_ENGINEERING_REVIEW)
		assert revisao.model_id == "LEVE"


class TestInjecaoNoPlano:
	def test_injeta_depois_do_codigo_e_antes_do_assembly(self):
		steps = [
			_step("cg1", STEP_CODE_GENERATION),
			_step("asm", STEP_ASSEMBLY, depends_on=["cg1"]),
		]
		result = Planner()._inject_engineering_review(steps, "medium")
		tipos = [s.step_type for s in result]
		assert tipos.index(STEP_ENGINEERING_REVIEW) > tipos.index(STEP_CODE_GENERATION)
		assert tipos.index(STEP_ENGINEERING_REVIEW) < tipos.index(STEP_ASSEMBLY)

	def test_depende_de_todos_os_code_generation(self):
		"""Deliberadamente diferente de _inject_syntax_validation (1 sv_ POR
		step): defeito de engenharia tipico -- duas features gravando a mesma
		config, camada duplicada entre modulos -- so aparece olhando o
		conjunto."""
		steps = [
			_step("cg1", STEP_CODE_GENERATION),
			_step("cg2", STEP_CODE_GENERATION),
			_step("asm", STEP_ASSEMBLY),
		]
		er = next(
			s for s in Planner()._inject_engineering_review(steps, "high")
			if s.step_type == STEP_ENGINEERING_REVIEW
		)
		assert er.depends_on == ["cg1", "cg2"]
		assert er.context_from_steps == ["cg1", "cg2"]

	def test_assembly_passa_a_depender_da_revisao(self):
		"""Sem isso, um plano que ja trouxesse assembly proprio empacotaria o
		addon ANTES da revisao rodar -- mesmo bug real ja corrigido uma vez em
		_inject_accessibility_audit (E2E 2026-08-04)."""
		steps = [_step("cg1", STEP_CODE_GENERATION), _step("asm", STEP_ASSEMBLY)]
		result = Planner()._inject_engineering_review(steps, "medium")
		asm = next(s for s in result if s.step_type == STEP_ASSEMBLY)
		assert "er_inj" in asm.depends_on
		assert "er_inj" in asm.context_from_steps

	def test_sem_code_generation_nao_injeta(self):
		steps = [_step("asm", STEP_ASSEMBLY)]
		result = Planner()._inject_engineering_review(steps, "medium")
		assert all(s.step_type != STEP_ENGINEERING_REVIEW for s in result)

	def test_nao_duplica_se_ja_existe(self):
		steps = [
			_step("cg1", STEP_CODE_GENERATION),
			_step("er0", STEP_ENGINEERING_REVIEW),
			_step("asm", STEP_ASSEMBLY),
		]
		result = Planner()._inject_engineering_review(steps, "medium")
		assert sum(s.step_type == STEP_ENGINEERING_REVIEW for s in result) == 1

	def test_sem_assembly_entra_no_fim(self):
		steps = [_step("cg1", STEP_CODE_GENERATION)]
		result = Planner()._inject_engineering_review(steps, "medium")
		assert result[-1].step_type == STEP_ENGINEERING_REVIEW


class TestVereditoDeterministico:
	"""O roteamento nunca depende de a LLM 'decidir' o proximo passo -- so le
	o campo que ela preencheu (README Regra 8: conteudo e da IA, roteamento e
	deterministico)."""

	def test_le_cada_veredito_valido(self):
		for veredito in ("SOLIDO", "AJUSTES_RECOMENDADOS", "REESTRUTURAR"):
			texto = f"bla bla\nVEREDITO_ENGENHARIA: {veredito}\nporque sim"
			assert engineering_reviewer._extract_verdict(texto) == veredito

	def test_veredito_ausente_nao_vira_aprovacao(self):
		"""Nunca adivinhar um valor mais favoravel quando o modelo nao emitiu
		veredito reconhecivel."""
		assert engineering_reviewer._extract_verdict("revisao sem veredito") == "INDEFINIDO"

	def test_ajustes_recomendados_nao_e_lido_como_solido(self):
		"""REGRESSAO de prefixo: 'AJUSTES_RECOMENDADOS' contem 'RECOMENDADOS',
		e uma checagem por substring solta poderia casar errado. A ordem de
		teste em _extract_verdict existe por isso."""
		texto = "VEREDITO_ENGENHARIA: AJUSTES_RECOMENDADOS porque falta timeout"
		assert engineering_reviewer._extract_verdict(texto) == "AJUSTES_RECOMENDADOS"


class TestFonteUnicaDosPrincipios:
	"""README Regra 5: zero duplicacao de regras de negocio. Os 4 consumidores
	importam do mesmo modulo -- se alguem colar o texto localmente num prompt,
	os dois divergem em silencio na proxima edicao."""

	def test_consumidores_usam_o_modulo_compartilhado(self):
		from nvdastudio.ai import critic
		from nvdastudio.core import planner
		from nvdastudio.sub_agents import code_generator

		assert engineering_principles.ENGINEERING_CRITIC_PROMPT_TEXT in critic._CRITIC_QUALITY_SYSTEM
		assert engineering_principles.ENGINEERING_PLANNING_PROMPT_TEXT in planner._PLAN_SYSTEM_PROMPT
		assert engineering_principles.ENGINEERING_CODEGEN_PROMPT_TEXT in code_generator._SYSTEM
		assert engineering_principles.ENGINEERING_REVIEW_PROMPT_TEXT in engineering_reviewer._SYSTEM

	def test_lentes_de_escrita_e_revisao_carregam_o_nucleo(self):
		nucleo = engineering_principles.ENGINEERING_CORE_PRINCIPLES
		assert nucleo in engineering_principles.ENGINEERING_CODEGEN_PROMPT_TEXT
		assert nucleo in engineering_principles.ENGINEERING_REVIEW_PROMPT_TEXT

	def test_documentos_de_origem_existem_no_repo(self):
		"""Rastreabilidade: se um doc for renomeado, isto acusa em vez de o
		ponteiro apodrecer em silencio."""
		import pathlib

		raiz = pathlib.Path(__file__).resolve().parents[2]
		for doc in engineering_principles.SOURCE_DOCS:
			assert (raiz / doc).is_file(), f"documento de origem sumiu: {doc}"


class TestPromptNaoDuplicaOCatalogoDeRegras:
	"""O revisor de engenharia existe para julgar o que NENHUM ID descreve.
	Se ele voltar a citar IDs, duplica accessibility_auditor e critic -- que e
	exatamente o defeito que _strip_rule_ids ja precisou corrigir no
	design_review_agent."""

	def test_system_proibe_citar_rule_ids(self):
		sistema = engineering_reviewer._SYSTEM
		assert "Never cite NVDA-XXX" in sistema

	def test_system_proibe_reportar_estilo(self):
		"""TAB e o padrao oficial do NVDA e o lint roda separado -- reportar
		estilo aqui geraria falso positivo garantido."""
		assert "Never report style" in engineering_reviewer._SYSTEM

	def test_system_permite_secao_vazia(self):
		"""Revisor que sempre acha algo vira ruido. Achado inventado para
		preencher secao e falso positivo por construcao."""
		assert "Never invent defects" in engineering_reviewer._SYSTEM
