import json
from unittest.mock import MagicMock, patch

import pytest

from nvdastudio.core.planner import (
	Planner, ExecutionPlan, ExecutionStep,
	STEP_MODEL_MAP, STEP_REASONING_MAP,
	STEP_CODE_GENERATION, STEP_MANIFEST, STEP_ACCESSIBILITY_AUDIT,
	STEP_TEST_GENERATION, STEP_WEB_RESEARCH, STEP_AGENT_TEMPLATE,
	STEP_AGENT_RUNNER, STEP_ASSEMBLY, STEP_DESIGN_REVIEW,
	STEP_DOCUMENTATION, STEP_USER_CLARIFICATION, PLANNER_MODEL, _PLAN_SYSTEM_PROMPT,
)
class TestStepModelMap:
	"""Invariante: todo step_type tem modelo mapeado no catalogo."""

	def test_todos_step_types_mapeados(self):
		step_types = [
			STEP_CODE_GENERATION, STEP_MANIFEST, STEP_ACCESSIBILITY_AUDIT,
			STEP_TEST_GENERATION, STEP_WEB_RESEARCH, STEP_AGENT_TEMPLATE,
			STEP_AGENT_RUNNER, STEP_ASSEMBLY, STEP_DESIGN_REVIEW,
		]
		for st in step_types:
			assert st in STEP_MODEL_MAP, f"Step '{st}' sem modelo mapeado"

	def test_modelos_mapeados_sao_validos(self):
		# v2.16.0 (achado de auditoria 2026-08-04, Felipe: "no alto para
		# qualquer provider... tem que usar o cascata"): _STEP_FALLBACK_MODEL
		# (fonte de STEP_MODEL_MAP) usava "kimi-k2.7-code" hardcoded pra TODO
		# step, mesmo quando o provedor configurado nao e Ollama -- corrigido
		# pro sentinela ALTO_MODEL, que resolve certo por provedor em
		# qualquer consumidor (apply_model_budget/resolve_step_model).
		from nvdastudio.ai.model_registry import ALTO_MODEL
		for step_type, model_id in STEP_MODEL_MAP.items():
			assert model_id == ALTO_MODEL, (
				f"Modelo '{model_id}' do step '{step_type}' deveria ser o sentinela 'alto', "
				f"nao um modelo concreto de um unico provedor"
			)

	def test_web_research_usa_alto(self):
		from nvdastudio.ai.model_registry import ALTO_MODEL
		assert STEP_MODEL_MAP[STEP_WEB_RESEARCH] == ALTO_MODEL

		model_id = STEP_MODEL_MAP[STEP_CODE_GENERATION]
		assert model_id == ALTO_MODEL, (
			f"Esperado sentinela 'alto' (provider-agnostic), recebido {model_id}"
		)

	def test_code_generation_usa_kimi(self):
		"""code_generation usa kimi-k2.7-code em todos os niveis."""
		from nvdastudio.core.planner import COMPLEXITY_MAP
		model_id = COMPLEXITY_MAP["high"][STEP_CODE_GENERATION]
		assert model_id == "kimi-k2.7-code"

	def test_agent_runner_usa_kimi(self):
		"""agent_runner usa kimi-k2.7-code em todos os niveis."""
		from nvdastudio.core.planner import COMPLEXITY_MAP
		model_id = COMPLEXITY_MAP["high"][STEP_AGENT_RUNNER]
		assert model_id == "kimi-k2.7-code"

	def test_agent_template_usa_alto(self):
		"""v2.16.0: agent_template usa o sentinela 'alto' (resolve por provedor)."""
		from nvdastudio.ai.model_registry import ALTO_MODEL
		model_id = STEP_MODEL_MAP[STEP_AGENT_TEMPLATE]
		assert model_id == ALTO_MODEL

	def test_design_review_mapeado(self):
		"""design_review mapeado para o sentinela 'alto' (fallback uniforme, provider-agnostic)."""
		from nvdastudio.ai.model_registry import ALTO_MODEL
		assert STEP_DESIGN_REVIEW in STEP_MODEL_MAP
		assert STEP_MODEL_MAP[STEP_DESIGN_REVIEW] == ALTO_MODEL


class TestStepReasoningMap:
	"""Invariante: reasoning_params validos para os modelos mapeados."""

	def test_web_research_sem_reasoning_params(self):
		assert STEP_REASONING_MAP[STEP_WEB_RESEARCH] == {}

	def test_assembly_sem_reasoning_params(self):
		assert STEP_REASONING_MAP[STEP_ASSEMBLY] == {}

	def test_code_generation_usa_alto(self):
		# v2.16.0: STEP_MODEL_MAP usa o sentinela 'alto', provider-agnostic --
		# o modelo concreto real e resolvido por apply_model_budget()/
		# resolve_step_model() no momento da execucao, nao aqui.
		from nvdastudio.ai.model_registry import ALTO_MODEL
		model_id = STEP_MODEL_MAP[STEP_CODE_GENERATION]
		assert model_id == ALTO_MODEL

	def test_agent_runner_usa_modelo_valido(self):
		from nvdastudio.ai.model_registry import ALTO_MODEL
		model_id = STEP_MODEL_MAP[STEP_AGENT_RUNNER]
		assert model_id == ALTO_MODEL, (
			f"agent_runner deve usar o sentinela 'alto', recebido {model_id}"
		)

	def test_design_review_tem_reasoning_effort(self):
		"""design_review usa thinking mode — deve ter reasoning_effort definido."""
		params = STEP_REASONING_MAP[STEP_DESIGN_REVIEW]
		assert "reasoning_effort" in params


class TestPlannerParsePlan:
	"""Testes de _parse_plan — logica deterministica de parsing de JSON."""

	def setup_method(self):
		self.planner = Planner.__new__(Planner)

	def test_parse_json_valido(self, valid_plan_json):
		raw = json.dumps(valid_plan_json)
		result = self.planner._parse_plan(raw)
		assert result["complexity"] == "medium"
		assert len(result["steps"]) == 4

	def test_parse_json_com_markdown_fence(self, valid_plan_json):
		raw = "```json\n" + json.dumps(valid_plan_json) + "\n```"
		result = self.planner._parse_plan(raw)
		assert "steps" in result

	def test_parse_json_invalido_retorna_plano_minimo(self):
		result = self.planner._parse_plan("nao e json {{{")
		assert "steps" in result
		assert len(result["steps"]) >= 3

	def test_parse_json_vazio_retorna_plano_minimo(self):
		result = self.planner._parse_plan("")
		assert "steps" in result


class TestPlannerBuildSteps:
	"""Testes de _build_steps — construcao de ExecutionStep com dados do JSON."""

	def setup_method(self):
		self.planner = Planner.__new__(Planner)

	def test_steps_tem_model_id_correto(self, valid_plan_json):
		# v1.5.0 (model_registry): kimi-k2.6 -> kimi-k2.7-code no tier heavy do Ollama.
		catalogo = {"kimi-k2.7-code", "kimi-k2.6", "deepseek-v4-flash"}
		steps = self.planner._build_steps(valid_plan_json["steps"])
		for step in steps:
			assert step.model_id in catalogo, f"model_id inesperado: {step.model_id}"

	def test_step_type_desconhecido_usa_fallback(self):
		raw = [{"step_id": "s1", "step_type": "tipo_inventado",
				"description": "x", "expected_output": "y",
				"depends_on": [], "context_from_steps": []}]
		steps = self.planner._build_steps(raw)
		assert steps[0].model_id == PLANNER_MODEL

	def test_steps_preservam_depends_on(self, valid_plan_json):
		steps = self.planner._build_steps(valid_plan_json["steps"])
		assembly = next(s for s in steps if s.step_type == STEP_ASSEMBLY)
		assert len(assembly.depends_on) >= 3

	def test_steps_tem_max_retries_padrao(self, valid_plan_json):
		steps = self.planner._build_steps(valid_plan_json["steps"])
		for step in steps:
			assert step.max_retries == 3

	def test_model_overrides_forca_modelo_do_step_type_correspondente(self, valid_plan_json):
		"""Cross-model escalation: model_overrides deve vencer a resolucao
		dinamica normal para o step_type presente no dict."""
		steps = self.planner._build_steps(
			valid_plan_json["steps"], model_overrides={STEP_CODE_GENERATION: "deepseek-v4-flash"}
		)
		code_step = next(s for s in steps if s.step_type == STEP_CODE_GENERATION)
		assert code_step.model_id == "deepseek-v4-flash"

	def test_model_overrides_nao_afeta_step_types_fora_do_mapa(self, valid_plan_json):
		steps_com_override = self.planner._build_steps(
			valid_plan_json["steps"], model_overrides={STEP_CODE_GENERATION: "deepseek-v4-flash"}
		)
		steps_sem_override = self.planner._build_steps(valid_plan_json["steps"])
		for com, sem in zip(steps_com_override, steps_sem_override):
			if com.step_type != STEP_CODE_GENERATION:
				assert com.model_id == sem.model_id


class TestApplyModelBudgetPreserveStepTypes:
	"""apply_model_budget(preserve_step_types=...) -- sem isso, o orcamento
	heavy/light reescrevia TODO model_id incondicionalmente, tornando
	qualquer override anterior (ex: model_overrides de _build_steps) um
	no-op silencioso. Achado e corrigido na auditoria de 2026-07-20."""

	def test_preserve_step_types_mantem_model_id_original(self):
		from nvdastudio.core.planner import apply_model_budget, ExecutionStep

		steps = [
			ExecutionStep("s1", STEP_CODE_GENERATION, "gerar", "deepseek-v4-flash"),
			ExecutionStep("s2", STEP_MANIFEST, "manifest", ""),
		]
		apply_model_budget(steps, "ollama", "alto", preserve_step_types={STEP_CODE_GENERATION})
		assert steps[0].model_id == "deepseek-v4-flash"
		assert steps[1].model_id != ""  # o nao-preservado recebe o orcamento normal

	def test_sem_preserve_step_types_comportamento_original_mantido(self):
		"""Sem o parametro (default None), o comportamento antigo (reescreve
		tudo) continua identico -- retrocompatibilidade dos 2 outros callers."""
		from nvdastudio.core.planner import apply_model_budget, ExecutionStep

		steps = [ExecutionStep("s1", STEP_CODE_GENERATION, "gerar", "modelo-que-nao-deveria-sobreviver")]
		apply_model_budget(steps, "ollama", "alto")
		assert steps[0].model_id != "modelo-que-nao-deveria-sobreviver"


class TestPlannerMinimalPlan:
	"""Testes do plano minimo de fallback."""

	def test_plano_minimo_tem_campos_obrigatorios(self):
		plan = Planner._minimal_plan()
		assert "complexity" in plan
		assert "steps" in plan
		assert "requires_web_research" in plan

	def test_plano_minimo_tem_assembly_ao_final(self):
		plan = Planner._minimal_plan()
		ultimo = plan["steps"][-1]
		assert ultimo["step_type"] == STEP_ASSEMBLY

	def test_plano_minimo_tem_ao_menos_3_steps(self):
		plan = Planner._minimal_plan()
		assert len(plan["steps"]) >= 3


class TestPlannerCreatePlanComMock:
	"""Testa create_plan com GroqClient mockado."""

	def test_create_plan_retorna_execution_plan(self, valid_plan_json):
		mock_response = MagicMock()
		mock_response.content = json.dumps(valid_plan_json)
		mock_response.reasoning = None

		with patch("nvdastudio.core.planner.create_llm_client") as MockClient:
			MockClient.return_value.chat.return_value = mock_response
			planner = Planner()
			plan = planner.create_plan("Crie um addon de teste")

		assert isinstance(plan, ExecutionPlan)
		assert plan.original_query == "Crie um addon de teste"
		assert plan.plan_id

	def test_create_plan_injeta_system_prompt_no_chat(self, valid_plan_json):
		mock_response = MagicMock()
		mock_response.content = json.dumps(valid_plan_json)
		mock_response.reasoning = None
		prompts_enviados = []

		def captura_chat(prompt, **kwargs):
			prompts_enviados.append(prompt)
			return mock_response

		with patch("nvdastudio.core.planner.create_llm_client") as MockClient:
			MockClient.return_value.chat.side_effect = captura_chat
			planner = Planner()
			planner.create_plan("crie addon X")

		assert any(_PLAN_SYSTEM_PROMPT[:40] in p for p in prompts_enviados)

	def test_create_plan_propaga_llm_error(
		self, valid_plan_json
	):
		from nvdastudio.ai.llm_client import LLMClientError

		with patch("nvdastudio.core.planner.create_llm_client") as MockClient:
			MockClient.return_value.chat.side_effect = LLMClientError("modelo falhou")
			planner = Planner()
			with pytest.raises(LLMClientError):
				planner.create_plan("Crie um addon")


class TestPlannerDesignReview:
	"""
	v1.1.0: _inject_design_review — Challenger + Constraint Guardian.
	Padrao: c:\\skills\\multi-agent-brainstorming\\SKILL.md
	Regra 5: injecao e deterministica (so em complexity=high).
	"""

	def setup_method(self):
		self.planner = Planner.__new__(Planner)

	def _make_step(self, step_id, step_type, depends_on=None):
		return ExecutionStep(
			step_id=step_id,
			step_type=step_type,
			description="step de teste",
			model_id="kimi-k2.6",
			reasoning_params={},
			depends_on=depends_on or [],
			context_from_steps=[],
			expected_output="output",
			max_retries=3,
		)

	def test_injecao_em_plano_complexo(self):
		"""complexity=high deve injetar design_review antes de code_generation."""
		steps = [
			self._make_step("s1", STEP_CODE_GENERATION),
			self._make_step("s2", STEP_ASSEMBLY, depends_on=["s1"]),
		]
		resultado = self.planner._inject_design_review(steps, "query complexa")
		tipos = [s.step_type for s in resultado]
		assert STEP_DESIGN_REVIEW in tipos
		# design_review deve vir antes de code_generation
		idx_dr = tipos.index(STEP_DESIGN_REVIEW)
		idx_cg = tipos.index(STEP_CODE_GENERATION)
		assert idx_dr < idx_cg

	def test_design_review_tem_step_id_dr0(self):
		steps = [self._make_step("s1", STEP_CODE_GENERATION)]
		resultado = self.planner._inject_design_review(steps, "query")
		dr_steps = [s for s in resultado if s.step_type == STEP_DESIGN_REVIEW]
		assert len(dr_steps) == 1
		assert dr_steps[0].step_id == "dr0"

	def test_code_generation_depende_de_dr0_apos_injecao(self):
		"""Apos injecao, code_generation deve ter dr0 em depends_on."""
		steps = [self._make_step("s1", STEP_CODE_GENERATION)]
		resultado = self.planner._inject_design_review(steps, "query")
		cg = next(s for s in resultado if s.step_type == STEP_CODE_GENERATION)
		assert "dr0" in cg.depends_on

	def test_code_generation_recebe_contexto_de_dr0(self):
		"""Apos injecao, code_generation deve ter dr0 em context_from_steps."""
		steps = [self._make_step("s1", STEP_CODE_GENERATION)]
		resultado = self.planner._inject_design_review(steps, "query")
		cg = next(s for s in resultado if s.step_type == STEP_CODE_GENERATION)
		assert "dr0" in cg.context_from_steps

	def test_nao_injeta_se_design_review_ja_presente(self):
		"""Guard: nao duplica design_review se ja existir no plano."""
		steps = [
			self._make_step("dr0", STEP_DESIGN_REVIEW),
			self._make_step("s1", STEP_CODE_GENERATION),
		]
		resultado = self.planner._inject_design_review(steps, "query")
		dr_steps = [s for s in resultado if s.step_type == STEP_DESIGN_REVIEW]
		assert len(dr_steps) == 1  # nao duplicou

	def test_design_review_max_retries_um(self):
		"""design_review nao precisa de retries — e input para code_generation."""
		steps = [self._make_step("s1", STEP_CODE_GENERATION)]
		resultado = self.planner._inject_design_review(steps, "query")
		dr = next(s for s in resultado if s.step_type == STEP_DESIGN_REVIEW)
		assert dr.max_retries == 1

	def test_create_plan_complexity_high_inclui_design_review(
		self
	):
		"""Plano com complexity=high deve ter design_review apos create_plan."""
		plan_json = {
			"complexity": "high",
			"requires_web_research": False,
			"requires_agent_runner": False,
			"steps": [
				{"step_id": "s1", "step_type": STEP_CODE_GENERATION,
				 "description": "x", "expected_output": "y",
				 "depends_on": [], "context_from_steps": []},
				{"step_id": "s2", "step_type": STEP_ASSEMBLY,
				 "description": "x", "expected_output": "y",
				 "depends_on": ["s1"], "context_from_steps": ["s1"]},
			],
		}
		mock_response = MagicMock()
		mock_response.content = json.dumps(plan_json)
		mock_response.reasoning = None

		with patch("nvdastudio.core.planner.create_llm_client") as MockClient:
			MockClient.return_value.chat.return_value = mock_response
			planner = Planner()
			plan = planner.create_plan("addon complexo com agente")

		tipos = [s.step_type for s in plan.steps]
		assert STEP_DESIGN_REVIEW in tipos
		assert plan.estimated_complexity == "high"

	def test_create_plan_complexity_medium_sem_design_review(
		self, valid_plan_json
	):
		"""Plano com complexity=medium NAO deve ter design_review."""
		mock_response = MagicMock()
		mock_response.content = json.dumps(valid_plan_json)
		mock_response.reasoning = None

		with patch("nvdastudio.core.planner.create_llm_client") as MockClient:
			MockClient.return_value.chat.return_value = mock_response
			planner = Planner()
			plan = planner.create_plan("addon simples")

		tipos = [s.step_type for s in plan.steps]
		assert STEP_DESIGN_REVIEW not in tipos

	def test_nao_executa_query_injetada(self):
		"""Regra 9: nenhum codigo do usuario e executado durante a injecao."""
		steps = [self._make_step("s1", STEP_CODE_GENERATION)]
		codigo_malicioso = "import os; os.system('echo PWNED')"
		resultado = self.planner._inject_design_review(steps, codigo_malicioso)
		# Funcao retorna lista de steps — nenhum codigo foi executado
		assert isinstance(resultado, list)
		assert all(isinstance(s, ExecutionStep) for s in resultado)


class TestPlannerUserMessage:
	"""Testa que user_message e populado pela LLM e preservado no step."""

	def test_step_tem_campo_user_message(self):
		from nvdastudio.core.planner import ExecutionStep, STEP_CODE_GENERATION
		step = ExecutionStep(
			step_id="s1", step_type=STEP_CODE_GENERATION,
			description="desc", model_id="modelo",
			user_message="Gerando o codigo do addon..."
		)
		assert step.user_message == "Gerando o codigo do addon..."

	def test_step_user_message_padrao_vazio(self):
		from nvdastudio.core.planner import ExecutionStep, STEP_CODE_GENERATION
		step = ExecutionStep(
			step_id="s1", step_type=STEP_CODE_GENERATION,
			description="desc", model_id="modelo",
		)
		assert step.user_message == ""

	def test_plan_tem_assembling_e_completed_message(self):
		from nvdastudio.core.planner import ExecutionPlan
		plan = ExecutionPlan(
			plan_id="abc", original_query="q", steps=[],
			assembling_message="Juntando tudo...",
			completed_message="Pronto! Criei o addon X.",
		)
		assert plan.assembling_message == "Juntando tudo..."
		assert plan.completed_message == "Pronto! Criei o addon X."

	def test_build_steps_popula_user_message(self):
		from unittest.mock import patch, MagicMock
		import json
		from nvdastudio.core.planner import Planner
		raw = {
			"complexity": "low", "requires_web_research": False,
			"requires_agent_runner": False,
			"assembling_message": "Montando...", "completed_message": "Pronto!",
			"steps": [
				{"step_id": "s1", "step_type": "code_generation",
				 "description": "d", "expected_output": "e",
				 "user_message": "Gerando o codigo...",
				 "depends_on": [], "context_from_steps": []}
			]
		}
		mock_resp = MagicMock()
		mock_resp.content = json.dumps(raw)
		mock_resp.reasoning = None
		with patch("nvdastudio.core.planner.create_llm_client") as MC:
			MC.return_value.chat.return_value = mock_resp
			plan = Planner().create_plan("crie addon")
		assert plan.steps[0].user_message == "Gerando o codigo..."
		assert plan.assembling_message == "Montando..."
		assert plan.completed_message == "Pronto!"

	def test_minimal_plan_tem_user_message(self):
		from nvdastudio.core.planner import Planner
		raw = Planner._minimal_plan()
		for step in raw["steps"]:
			assert "user_message" in step
			assert len(step["user_message"]) > 0


class TestPlannerDependencies:
	"""Testa campo dependencies no ExecutionPlan."""

	def test_plan_tem_campo_dependencies(self):
		from nvdastudio.core.planner import ExecutionPlan
		plan = ExecutionPlan(
			plan_id="x", original_query="q", steps=[],
			dependencies=["google-generativeai", "Pillow"]
		)
		assert plan.dependencies == ["google-generativeai", "Pillow"]

	def test_plan_dependencies_default_vazio(self):
		from nvdastudio.core.planner import ExecutionPlan
		plan = ExecutionPlan(plan_id="x", original_query="q", steps=[])
		assert plan.dependencies == []


class TestIntroMessageSubstituiRegexQuebrado:
	"""v2.6.0: intro_message e gerado pela IA no mesmo JSON do plano, substituindo
	o regex de prefixos que quebrava quando 'addon' era seguido do nome do produto
	(ex: 'addon NVDA...'), gerando frases sem sentido como 'voce quer um addon que NVDA...'."""

	def test_plan_tem_campo_intro_message(self):
		from nvdastudio.core.planner import ExecutionPlan
		plan = ExecutionPlan(
			plan_id="x", original_query="q", steps=[],
			intro_message="Beleza! Entendi que voce quer um addon de clipboard.",
		)
		assert plan.intro_message == "Beleza! Entendi que voce quer um addon de clipboard."

	def test_plan_intro_message_default_vazio(self):
		from nvdastudio.core.planner import ExecutionPlan
		plan = ExecutionPlan(plan_id="x", original_query="q", steps=[])
		assert plan.intro_message == ""

	def test_create_plan_extrai_intro_message_do_json(self):
		from unittest.mock import patch, MagicMock
		import json
		from nvdastudio.core.planner import Planner
		raw = {
			"complexity": "low", "requires_web_research": False,
			"requires_agent_runner": False,
			"intro_message": "Combinado! Vou criar seu addon de clipboard agora.",
			"assembling_message": "Montando...", "completed_message": "Pronto!",
			"steps": [
				{"step_id": "s1", "step_type": "code_generation",
				 "description": "d", "expected_output": "e",
				 "depends_on": [], "context_from_steps": []}
			]
		}
		mock_resp = MagicMock()
		mock_resp.content = json.dumps(raw)
		mock_resp.reasoning = None
		with patch("nvdastudio.core.planner.create_llm_client") as MC:
			MC.return_value.chat.return_value = mock_resp
			plan = Planner().create_plan("crie addon")
		assert plan.intro_message == "Combinado! Vou criar seu addon de clipboard agora."

	def test_format_plan_for_user_usa_intro_message_direto_sem_regex(self):
		"""Regressao do bug real: query 'Criar addon NVDA ... com as seguintes
		caracteristicas' produzia 'voce quer um addon que NVDA...' via regex.
		Agora format_plan_for_user() so usa o que a IA escreveu, verbatim."""
		from nvdastudio.core.planner import Planner, ExecutionPlan
		plan = ExecutionPlan(
			plan_id="x",
			original_query="Criar addon NVDA do zero denominado GeminiChat com as seguintes caracteristicas",
			steps=[],
			intro_message="Beleza! Entendi que voce quer um addon de chat com o Gemini, chamado GeminiChat.",
		)
		texto = Planner().format_plan_for_user(plan)
		assert texto.startswith("Beleza! Entendi que voce quer um addon de chat com o Gemini, chamado GeminiChat.")
		assert "addon que NVDA" not in texto
		assert "que nvda" not in texto.lower()

	def test_format_plan_for_user_retorna_apresentacao_completa_da_ia(self):
		from nvdastudio.core.planner import Planner, ExecutionPlan
		presentation = (
			"Entendi que você quer um chat local com o Gemini.\n\n"
			"Primeiro vou criar a integração e depois conferir a acessibilidade.\n\n"
			"Quer que eu prossiga ou prefere ajustar alguma parte?"
		)
		plan = ExecutionPlan(
			plan_id="x", original_query="q", steps=[],
			intro_message="Esta introdução não deve substituir a mensagem completa.",
			plan_presentation=presentation,
		)
		assert Planner().format_plan_for_user(plan) == presentation

	def test_format_plan_for_user_nao_contem_molde_fixo(self):
		import inspect
		from nvdastudio.core.planner import Planner
		source = inspect.getsource(Planner.format_plan_for_user)
		assert "Vou fazer em" not in source
		assert "O que acha? Você pode aprovar" not in source
		assert "_naturalize_step_message" not in source

	def test_format_plan_for_user_usa_fallback_se_intro_message_vazio(self):
		"""Se por algum motivo a IA nao gerou intro_message (plano antigo/degradado),
		usa uma frase generica em vez de tentar reconstruir a query via regex."""
		from nvdastudio.core.planner import Planner, ExecutionPlan
		plan = ExecutionPlan(
			plan_id="x", original_query="Criar addon NVDA com tal caracteristica",
			steps=[], intro_message="",
		)
		texto = Planner().format_plan_for_user(plan)
		assert texto.strip()
		assert "addon que NVDA" not in texto

	def test_create_plan_popula_dependencies(self):
		from unittest.mock import patch, MagicMock
		import json
		from nvdastudio.core.planner import Planner
		raw = {
			"complexity": "low",
			"requires_web_research": False,
			"requires_agent_runner": False,
			"assembling_message": "montando",
			"completed_message": "pronto",
			"dependencies": ["google-generativeai"],
			"steps": [
				{"step_id": "s1", "step_type": "code_generation",
				 "description": "d", "expected_output": "e",
				 "user_message": "gerando",
				 "depends_on": [], "context_from_steps": []}
			]
		}
		mock_resp = MagicMock()
		mock_resp.content = json.dumps(raw)
		mock_resp.reasoning = None
		with patch("nvdastudio.core.planner.create_llm_client") as MC:
			MC.return_value.chat.return_value = mock_resp
			plan = Planner().create_plan("crie addon gemini")
		assert plan.dependencies == ["google-generativeai"]

	def test_minimal_plan_tem_dependencies_vazio(self):
		from nvdastudio.core.planner import Planner
		raw = Planner._minimal_plan()
		assert "dependencies" in raw
		assert raw["dependencies"] == []


# --------------------------------------------------------------------------
# Testes: Planner.replan() — v1.5.0
# --------------------------------------------------------------------------

class TestPlannerReplan:
	"""Planner.replan() gera novos steps para o restante do pipeline."""

	def test_replan_retorna_lista_de_steps(self):
		import json
		from unittest.mock import MagicMock, patch
		from nvdastudio.core.planner import Planner

		raw = {
			"complexity": "medium",
			"requires_web_research": False,
			"requires_agent_runner": False,
			"assembling_message": "Montando...",
			"completed_message": "Pronto!",
			"dependencies": [],
			"steps": [
				{"step_id": "r1", "step_type": "code_generation",
				 "description": "Nova geracao", "expected_output": "codigo",
				 "user_message": "Gerando novamente...",
				 "depends_on": [], "context_from_steps": []},
			]
		}
		mock_resp = MagicMock()
		mock_resp.content = json.dumps(raw)
		mock_resp.reasoning = None

		with patch("nvdastudio.core.planner.create_llm_client") as MC:
			MC.return_value.chat.return_value = mock_resp
			planner = Planner()
			result = planner.replan(
				original_query="crie addon",
				outputs_summary={"s0": "output parcial"},
				remaining_steps=[],
				issues=["Erro de sintaxe: linha 5"],
			)

		assert isinstance(result, list)
		assert len(result) == 1
		assert result[0].step_id == "r1"

	def test_replan_atribui_modelos_corretos(self):
		import json
		from unittest.mock import MagicMock, patch
		from nvdastudio.core.planner import Planner

		raw = {
			"complexity": "medium",
			"requires_web_research": False,
			"requires_agent_runner": False,
			"assembling_message": "...", "completed_message": "...",
			"dependencies": [],
			"steps": [
				{"step_id": "r1", "step_type": "code_generation",
				 "description": "Corrigir codigo", "expected_output": "codigo",
				 "user_message": "Corrigindo...",
				 "depends_on": [], "context_from_steps": []},
			]
		}
		mock_resp = MagicMock()
		mock_resp.content = json.dumps(raw)
		mock_resp.reasoning = None

		with patch("nvdastudio.core.planner.create_llm_client") as MC:
			MC.return_value.chat.return_value = mock_resp
			planner = Planner()
			result = planner.replan("criar addon", {}, [], ["erro"])

		# model_id atribuido deterministicamente pelo _build_steps via
		# apply_model_budget() -- 1 unico code_generation step vira 100%
		# elevado (max(1, floor(1*0.20))=1), usando select_model() (router
		# dinamico por pontuacao, model_router.py) pra decidir QUAL modelo,
		# nao mais o tier "heavy" estatico de resolve_provider_tier_model()
		# (esse so vale fora do modo Alto).
		from nvdastudio.ai.model_router import select_model
		from nvdastudio.gui.settings_panel import get_llm_provider, get_llm_model
		expected = select_model(get_llm_provider(), STEP_CODE_GENERATION, get_llm_model(), complexity="medium")
		assert result[0].model_id == expected

	def test_replan_falha_retorna_remaining_original(self):
		from unittest.mock import patch
		from nvdastudio.core.planner import Planner, ExecutionStep

		original = [ExecutionStep("s1", "assembly", "montar", "kimi-k2.6")]

		with patch("nvdastudio.core.planner.create_llm_client") as MC:
			MC.return_value.chat.side_effect = Exception("API falhou")
			planner = Planner()
			result = planner.replan("criar addon", {}, original, ["erro critico"])

		# Fallback: retorna os steps originais
		assert result == original

	def test_replan_retorna_original_se_steps_vazios(self):
		import json
		from unittest.mock import MagicMock, patch
		from nvdastudio.core.planner import Planner, ExecutionStep

		raw = {
			"complexity": "medium",
			"requires_web_research": False,
			"requires_agent_runner": False,
			"assembling_message": "...", "completed_message": "...",
			"dependencies": [],
			"steps": []  # planner retornou lista vazia
		}
		mock_resp = MagicMock()
		mock_resp.content = json.dumps(raw)
		mock_resp.reasoning = None

		original = [ExecutionStep("s1", "assembly", "montar", "kimi-k2.6")]

		with patch("nvdastudio.core.planner.create_llm_client") as MC:
			MC.return_value.chat.return_value = mock_resp
			planner = Planner()
			result = planner.replan("criar addon", {}, original, [])

		# Quando replan retorna lista vazia, preserva originais
		assert result == original

	def test_replan_nao_executa_outputs_anteriores(self):
		import json
		from unittest.mock import MagicMock, patch
		from nvdastudio.core.planner import Planner

		raw = {
			"complexity": "medium",
			"requires_web_research": False,
			"requires_agent_runner": False,
			"assembling_message": "...", "completed_message": "...",
			"dependencies": [],
			"steps": [
				{"step_id": "r1", "step_type": "code_generation",
				 "description": "d", "expected_output": "e",
				 "user_message": "m",
				 "depends_on": [], "context_from_steps": []},
			]
		}
		mock_resp = MagicMock()
		mock_resp.content = json.dumps(raw)
		mock_resp.reasoning = None

		# os.system() patchado so como sonda de teste (mock_system.assert_not_called()
		# abaixo) -- nunca invocado de verdade; a string 'del /q' e um literal de
		# teste inerte, nao um comando real executado em nenhum caminho de codigo.
		with patch("nvdastudio.core.planner.create_llm_client") as MC, \
			 patch("os.system") as mock_system:
			MC.return_value.chat.return_value = mock_resp
			planner = Planner()
			# Output anterior contem codigo malicioso — nao deve ser executado
			malicious_output = "import os; os.system('del /q')"
			planner.replan(
				"criar addon",
				outputs_summary={"s0": malicious_output},
				remaining_steps=[],
				issues=[]
			)

		# O texto malicioso deve ter sido tratado como dado inerte (so entra
		# no prompt textual mandado ao LLM), nunca executado pelo planner.
		mock_system.assert_not_called()
		prompt_enviado = MC.return_value.chat.call_args[0][0]
		assert "os.system" in prompt_enviado, (
			"o output anterior deveria aparecer verbatim (como texto) no prompt de replan"
		)

# --------------------------------------------------------------------------
# Feature 1: Complexity-based dynamic routing (v3.0)
# --------------------------------------------------------------------------

class TestComplexityMapRouting:
	"""COMPLEXITY_MAP — roteamento dinamico de modelos por complexidade."""

	def test_complexity_low_uses_kimi_all_steps(self):
		from nvdastudio.core.planner import COMPLEXITY_MAP, STEP_CODE_GENERATION, STEP_MANIFEST
		low_map = COMPLEXITY_MAP["low"]
		assert low_map[STEP_CODE_GENERATION] == "kimi-k2.7-code"
		assert low_map[STEP_MANIFEST] == "kimi-k2.7-code"

	def test_complexity_medium_uses_kimi_code(self):
		"""v2.4.0: medium code_generation rebalanceado para kimi-k2.7-code."""
		from nvdastudio.core.planner import COMPLEXITY_MAP, STEP_CODE_GENERATION
		med_map = COMPLEXITY_MAP["medium"]
		assert med_map[STEP_CODE_GENERATION] == "kimi-k2.7-code"

	def test_complexity_high_uses_kimi_code_and_flash_accessibility(self):
		"""v2.18.0: STEP_CRITIQUE removido -- codigo morto de verdade, nunca
		presente no enum step_type do schema JSON que a LLM usa pra montar
		o plano (confirmado via auditoria 2026-08-04), entao nunca era
		despachavel. STEP_ACCESSIBILITY_AUDIT assume o papel deste teste
		como exemplo de step que usa o modelo light (deepseek-v4-flash)
		em complexidade alta."""
		from nvdastudio.core.planner import COMPLEXITY_MAP, STEP_ACCESSIBILITY_AUDIT, STEP_CODE_GENERATION
		high_map = COMPLEXITY_MAP["high"]
		assert high_map[STEP_CODE_GENERATION] == "kimi-k2.7-code"
		assert high_map[STEP_ACCESSIBILITY_AUDIT] == "deepseek-v4-flash"

	def test_execution_plan_has_step_model_map(self):
		from nvdastudio.core.planner import ExecutionPlan
		plan = ExecutionPlan(
			plan_id="abc", original_query="q", steps=[],
			step_model_map={"code_generation": "kimi-k2.6"},
		)
		assert plan.step_model_map == {"code_generation": "kimi-k2.6"}

	def test_execution_plan_step_model_map_default_empty(self):
		from nvdastudio.core.planner import ExecutionPlan
		plan = ExecutionPlan(plan_id="abc", original_query="q", steps=[])
		assert plan.step_model_map == {}

	def test_create_plan_low_complexity_populates_step_model_map(self):
		import json
		from unittest.mock import MagicMock, patch
		from nvdastudio.core.planner import Planner, STEP_CODE_GENERATION

		plan_json = {
			"addon_name": "MeuAddon",
			"complexity": "low",
			"requires_web_research": False,
			"requires_agent_runner": False,
			"assembling_message": "Montando...",
			"completed_message": "Pronto!",
			"replan_message": "Revisando...",
			"dependencies": [],
			"steps": [
				{"step_id": "s1", "step_type": "code_generation",
				 "description": "d", "expected_output": "e",
				 "user_message": "m", "msg_evaluating": "e",
				 "msg_retrying": "r", "msg_escalating": "x",
				 "depends_on": [], "context_from_steps": []},
				{"step_id": "s2", "step_type": "assembly",
				 "description": "d", "expected_output": "e",
				 "user_message": "m", "msg_evaluating": "e",
				 "msg_retrying": "r", "msg_escalating": "x",
				 "depends_on": ["s1"], "context_from_steps": ["s1"]},
			],
		}
		mock_resp = MagicMock()
		mock_resp.content = json.dumps(plan_json)
		mock_resp.reasoning = None

		with patch("nvdastudio.core.planner.create_llm_client") as MC:
			MC.return_value.chat.return_value = mock_resp
			planner = Planner()
			plan = planner.create_plan("crie addon simples")

		# planner.py 2.23.0: apply_model_budget() pontua entre TODOS os
		# modelos ativos do provider (ai/model_router.py) em vez de sempre
		# escolher "deepseek-v4-flash" como o unico "light" fixo -- verifica
		# cost_tier (barato) em vez de um model_id especifico hardcoded.
		from nvdastudio.ai.model_registry import registry
		assert plan.estimated_complexity == "low"
		assert plan.step_model_map[STEP_CODE_GENERATION] == "kimi-k2.7-code"
		light = [
			step for step in plan.steps
			if (info := registry.get_model_info(step.model_id)) and info.cost_tier == "low"
		]
		assert len(light) / len(plan.steps) >= 0.70

	def test_create_plan_high_complexity_uses_flash_design_review(self):
		import json
		from unittest.mock import MagicMock, patch
		from nvdastudio.core.planner import Planner, STEP_DESIGN_REVIEW

		plan_json = {
			"addon_name": "MeuAddon",
			"complexity": "high",
			"requires_web_research": False,
			"requires_agent_runner": False,
			"assembling_message": "Montando...",
			"completed_message": "Pronto!",
			"replan_message": "Revisando...",
			"dependencies": [],
			"steps": [
				{"step_id": "s1", "step_type": "code_generation",
				 "description": "d", "expected_output": "e",
				 "user_message": "m", "msg_evaluating": "e",
				 "msg_retrying": "r", "msg_escalating": "x",
				 "depends_on": [], "context_from_steps": []},
				{"step_id": "s2", "step_type": "assembly",
				 "description": "d", "expected_output": "e",
				 "user_message": "m", "msg_evaluating": "e",
				 "msg_retrying": "r", "msg_escalating": "x",
				 "depends_on": ["s1"], "context_from_steps": ["s1"]},
			],
		}
		mock_resp = MagicMock()
		mock_resp.content = json.dumps(plan_json)
		mock_resp.reasoning = None

		with patch("nvdastudio.core.planner.create_llm_client") as MC:
			MC.return_value.chat.return_value = mock_resp
			planner = Planner()
			plan = planner.create_plan("crie addon complexo com agente ia e dialogo")

		# planner.py 2.23.0: design_review nunca e elegivel ao slot elevado
		# (so STEP_CODE_GENERATION e) -- pontuado (ai/model_router.py) entre
		# TODOS os modelos ativos do provider, nao mais fixo em
		# "deepseek-v4-flash". Verifica cost_tier barato em vez do model_id
		# especifico -- qual modelo barato exato vence depende da pontuacao
		# real, nao de uma tabela hardcoded.
		from nvdastudio.ai.model_registry import registry
		assert plan.estimated_complexity == "high"
		assert plan.step_model_map[STEP_DESIGN_REVIEW] == "deepseek-v4-flash"
		dr_steps = [s for s in plan.steps if s.step_type == STEP_DESIGN_REVIEW]
		assert len(dr_steps) == 1
		assert registry.get_model_info(dr_steps[0].model_id).cost_tier == "low"

	def test_replan_applies_model_map(self):
		import json
		from unittest.mock import MagicMock, patch
		from nvdastudio.core.planner import Planner

		raw = {
			"complexity": "low",
			"requires_web_research": False,
			"requires_agent_runner": False,
			"assembling_message": "...",
			"completed_message": "...",
			"dependencies": [],
			"steps": [
				{"step_id": "r1", "step_type": "code_generation",
				 "description": "Corrigir", "expected_output": "codigo",
				 "user_message": "m", "msg_evaluating": "e",
				 "msg_retrying": "r", "msg_escalating": "x",
				 "depends_on": [], "context_from_steps": []},
			],
		}
		mock_resp = MagicMock()
		mock_resp.content = json.dumps(raw)
		mock_resp.reasoning = None

		with patch("nvdastudio.core.planner.create_llm_client") as MC:
			MC.return_value.chat.return_value = mock_resp
			planner = Planner()
			result = planner.replan(
				"criar addon",
				{},
				[],
				["erro"],
				model_map={"code_generation": "kimi-k2.6"},
			)

		# v2.10.0: model_map agora chega de verdade a _build_steps() (via
		# model_overrides) E sobrevive a apply_model_budget() (via
		# preserve_step_types) -- antes era um no-op silencioso em 2 camadas
		# diferentes (achado e corrigido na auditoria de 2026-07-20, usado
		# para cross-model escalation no replan pos-falha).
		assert result[0].model_id == "kimi-k2.6"

	def test_step_model_map_alias_retrocompatible(self):
		"""STEP_MODEL_MAP ainda aponta para STEP_MODEL_MAP_MEDIUM."""
		from nvdastudio.core.planner import STEP_MODEL_MAP, STEP_MODEL_MAP_MEDIUM
		assert STEP_MODEL_MAP is STEP_MODEL_MAP_MEDIUM



class TestArch010DecomposicaoParalela:
    """
    2.25.0: ARCH-010 -- pedidos com 3+ features independentes devem virar
    MULTIPLOS steps code_generation (um por feature, mais um final que
    depende de todos e gera o __init__.py raiz), nao um so cobrindo tudo.
    Achado real: GeminiMultimodal (imagem+audio+video) virou um
    code_generation so e o proprio modelo REJEITOU a resposta (score 0,
    "nenhum codigo produzido") -- tarefa grande demais numa chamada so.
    """

    def test_arch010_presente_no_prompt(self):
        assert "ARCH-010" in _PLAN_SYSTEM_PROMPT

    def test_arch010_menciona_mesmo_gatilho_do_arch007(self):
        """ARCH-010 estende ARCH-007 (mesmo gatilho: 3+ features
        substanciais independentes) -- nao introduz um criterio novo."""
        idx = _PLAN_SYSTEM_PROMPT.find("ARCH-010")
        trecho = _PLAN_SYSTEM_PROMPT[idx:idx + 700]
        assert "ARCH-007" in trecho

    def test_arch010_instrui_depends_on_vazio_entre_features(self):
        """Steps de feature independentes precisam depends_on=[] entre si
        pra serem agendados em paralelo pelo orchestrator (ThreadPoolExecutor
        ja existente -- nada de novo precisa ser configurado pra isso)."""
        idx = _PLAN_SYSTEM_PROMPT.find("ARCH-010")
        trecho = _PLAN_SYSTEM_PROMPT[idx:idx + 900]
        assert "depends_on=[]" in trecho
        assert "PARALELO" in trecho or "paralelo" in trecho.lower()

    def test_arch010_instrui_step_final_dependendo_de_todos(self):
        idx = _PLAN_SYSTEM_PROMPT.find("ARCH-010")
        trecho = _PLAN_SYSTEM_PROMPT[idx:idx + 1400]
        assert "__init__.py raiz" in trecho

    def test_regra_de_composicao_permite_multiplos_code_generation(self):
        """A regra OBRIGATORIA antiga dizia 'o step' (singular) -- precisa
        deixar explicito que varios code_generation sao permitidos."""
        idx = _PLAN_SYSTEM_PROMPT.find("OBRIGATORIO: sempre inclua PELO MENOS UM code_generation")
        assert idx != -1


class TestArch011DecomposicaoDoStepFinal:
    """
    2.27.0: ARCH-011 -- decomposicao do PROPRIO step final "cg_core", nao so
    entre features (ARCH-010). Achado real ao vivo (test_e36, GeminiMultimodal,
    2026-08-16): mesmo o modelo mais forte escolhido pelo router (qwen3.5:397b)
    reprovou 3/3 tentativas do step final por sobrecarga -- root __init__.py +
    SettingsPanel completo + config.conf.spec + classes de erro, tudo numa
    chamada so. "Delegar" pra um modelo melhor nao resolve tarefa grande
    demais -- decompor resolve (pedido explicito do Felipe apos investigacao).
    """

    def test_arch011_presente_no_prompt(self):
        assert "ARCH-011" in _PLAN_SYSTEM_PROMPT

    def test_arch011_instrui_step_dedicado_cg_settings(self):
        idx = _PLAN_SYSTEM_PROMPT.find("ARCH-011")
        trecho = _PLAN_SYSTEM_PROMPT[idx:idx + 1200]
        assert "cg_settings" in trecho
        assert "configSpec.py" in trecho
        assert "settings_panel.py" in trecho

    def test_arch011_nao_contradiz_arch005(self):
        """ARCH-005 exige config.conf.spec 'no __init__ do GlobalPlugin' --
        ARCH-011 precisa deixar claro que apply_config_spec() CHAMADA no
        __init__.py satisfaz isso, mesmo definida em modulo separado."""
        idx = _PLAN_SYSTEM_PROMPT.find("ARCH-011")
        trecho = _PLAN_SYSTEM_PROMPT[idx:idx + 1600]
        assert "ARCH-005" in trecho
        assert "apply_config_spec" in trecho

    def test_arch011_tem_ressalva_para_addons_simples(self):
        """Mesma ressalva de ARCH-007/ARCH-010: nao decompor quando o
        SettingsPanel e trivial (overhead sem beneficio)."""
        idx = _PLAN_SYSTEM_PROMPT.find("ARCH-011")
        trecho = _PLAN_SYSTEM_PROMPT[idx:idx + 2000]
        assert "SIMPLES" in trecho or "simples" in trecho.lower()

    def test_regra_de_composicao_menciona_cg_settings(self):
        idx = _PLAN_SYSTEM_PROMPT.find("OBRIGATORIO: sempre inclua PELO MENOS UM code_generation")
        assert idx != -1
        trecho = _PLAN_SYSTEM_PROMPT[idx:idx + 600]
        assert "cg_settings" in trecho or "ARCH-011" in trecho


class TestPlanSystemPromptAcentuacaoCorreta:
    """As mensagens de step exibidas/faladas ao usuario sao geradas por IA a partir
    dos exemplos deste prompt. Exemplos sem acento ensinam o modelo a escrever sem
    acento (few-shot bias) — por isso o prompt em si precisa estar bem acentuado."""

    def test_exemplos_de_mensagem_tem_acentos_corretos(self):
        for palavra in ["código", "documentação", "análise", "português",
                        "usuário", "está", "máximo", "técnico"]:
            assert palavra in _PLAN_SYSTEM_PROMPT, (
                f"Palavra '{palavra}' esperada com acento no _PLAN_SYSTEM_PROMPT nao encontrada"
            )

    def test_sem_regressao_de_acento_nos_exemplos_de_mensagem(self):
        """Nenhum dos exemplos ('ex: ...') deve reintroduzir a versao sem acento
        das palavras mais comuns que os steps falam ao usuario."""
        bad_words = ["codigo funciona", "documentacao esta", "analise mais",
                     "em portugues,", "esta sendo verificado"]
        for bad in bad_words:
            assert bad not in _PLAN_SYSTEM_PROMPT, (
                f"Encontrado texto sem acento no prompt: '{bad}'"
            )


class TestStepMessagesPadraoAcentuadas:
    """As mensagens default (fallback quando a IA nao gera user_message) sao
    strings Python literais — precisam estar acentuadas manualmente."""

    def setup_method(self):
        self.planner = Planner.__new__(Planner)

    def test_design_review_user_message_acentuado(self):
        step = self.planner._inject_design_review([
            ExecutionStep(step_id="s1", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
        ], "query")
        dr_step = step[0]
        assert "começar" in dr_step.user_message

    def test_documentation_user_message_acentuado(self):
        steps = self.planner._inject_documentation([
            ExecutionStep(step_id="s1", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
        ])
        doc_step = next(s for s in steps if s.step_type == STEP_DOCUMENTATION)
        assert "documentação" in doc_step.user_message
        assert "usuário" in doc_step.user_message

    def test_assembly_user_message_acentuado(self):
        steps = self.planner._inject_assembly([
            ExecutionStep(step_id="s1", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
        ])
        asm_step = next(s for s in steps if s.step_type == STEP_ASSEMBLY)
        assert "incluídos" in asm_step.msg_evaluating


class TestInjectManifest:
    """
    planner.py 2.21.0: _inject_manifest() novo -- bug real achado no teste
    E2E complexo real (2026-08-07, addon AssistenteLeituraGemini): um plano
    de 6 steps saiu do LLM SEM nenhum manifest_builder, e nada corrigia
    isso (diferente de documentation/assembly/accessibility_audit, que ja
    tinham rede de seguranca). Mesmo padrao de _inject_documentation."""

    def setup_method(self):
        self.planner = Planner.__new__(Planner)

    def test_injeta_quando_ausente(self):
        steps = self.planner._inject_manifest([
            ExecutionStep(step_id="s1", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
        ], "crie um addon simples")
        assert any(s.step_type == STEP_MANIFEST for s in steps)

    def test_nao_duplica_quando_ja_presente(self):
        steps_in = [
            ExecutionStep(step_id="mf_existente", step_type=STEP_MANIFEST,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
        ]
        steps = self.planner._inject_manifest(steps_in, "crie um addon simples")
        manifest_steps = [s for s in steps if s.step_type == STEP_MANIFEST]
        assert len(manifest_steps) == 1
        assert manifest_steps[0].step_id == "mf_existente"

    def test_inserido_imediatamente_antes_do_assembly(self):
        steps = self.planner._inject_manifest([
            ExecutionStep(step_id="s1", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
            ExecutionStep(step_id="asm", step_type=STEP_ASSEMBLY,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e", depends_on=["s1"], context_from_steps=["s1"]),
        ], "crie um addon simples")
        types = [s.step_type for s in steps]
        assert types.index(STEP_MANIFEST) == types.index(STEP_ASSEMBLY) - 1

    def test_assembly_ganha_dependencia_do_manifest_injetado(self):
        steps = self.planner._inject_manifest([
            ExecutionStep(step_id="s1", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
            ExecutionStep(step_id="asm", step_type=STEP_ASSEMBLY,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e", depends_on=["s1"], context_from_steps=["s1"]),
        ], "crie um addon simples")
        asm_step = next(s for s in steps if s.step_type == STEP_ASSEMBLY)
        assert "mf_inj" in asm_step.depends_on
        assert "mf_inj" in asm_step.context_from_steps

    def test_fallback_sem_assembly_adiciona_no_final(self):
        steps = self.planner._inject_manifest([
            ExecutionStep(step_id="s1", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
        ], "crie um addon simples")
        assert any(s.step_type == STEP_MANIFEST for s in steps)

    def test_description_menciona_o_pedido_original(self):
        query = "crie um addon de transcricao de audio via Gemini"
        steps = self.planner._inject_manifest([
            ExecutionStep(step_id="s1", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
        ], query)
        mf_step = next(s for s in steps if s.step_type == STEP_MANIFEST)
        assert query in mf_step.description

    def test_dependencia_de_code_generation_removida_quando_manifest_ja_no_plano(self):
        """
        planner.py 2.24.0: manifest_builder nao pode ficar bloqueado esperando
        code_generation -- se esgotar TODAS as tentativas (incluindo escalacao
        cross-provider), manifest.ini nunca seria gerado, mesmo nao precisando
        de nada do codigo.
        """
        steps = self.planner._inject_manifest([
            ExecutionStep(step_id="s1", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
            ExecutionStep(step_id="mf1", step_type=STEP_MANIFEST,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e", depends_on=["s1"], context_from_steps=["s1"]),
        ], "crie um addon simples")
        mf_step = next(s for s in steps if s.step_type == STEP_MANIFEST)
        assert "s1" not in mf_step.depends_on
        assert "s1" not in mf_step.context_from_steps

    def test_dependencia_de_step_nao_relacionado_e_preservada(self):
        steps = self.planner._inject_manifest([
            ExecutionStep(step_id="s1", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
            ExecutionStep(step_id="uc1", step_type=STEP_USER_CLARIFICATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
            ExecutionStep(step_id="mf1", step_type=STEP_MANIFEST,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e", depends_on=["uc1"], context_from_steps=["uc1"]),
        ], "crie um addon simples")
        mf_step = next(s for s in steps if s.step_type == STEP_MANIFEST)
        assert mf_step.depends_on == ["uc1"]

    def test_manifest_injetado_nao_precisa_de_sanitizacao(self):
        """manifest_step injetado por _inject_manifest ja nasce depends_on=[] --
        so o caso "ja presente no plano bruto do LLM" precisa de sanitizacao."""
        steps = self.planner._inject_manifest([
            ExecutionStep(step_id="s1", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
        ], "crie um addon simples")
        mf_step = next(s for s in steps if s.step_type == STEP_MANIFEST)
        assert mf_step.depends_on == []

    def test_syntax_validation_user_message_acentuado(self):
        steps = self.planner._inject_syntax_validation([
            ExecutionStep(step_id="s1", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
        ])
        sv_step = next(s for s in steps if s.step_type == "syntax_validation")
        assert "código" in sv_step.user_message


class TestInjectCoreStep:
    """
    planner.py 2.28.0: _inject_core_step() novo -- bug real achado no teste
    E2E complexo real (2026-08-17, addon GeminiMultimodal): o plano bruto do
    LLM tinha varios code_generation por feature mas NENHUM dependia de
    todos os outros (o papel de "cg_core" que ARCH-010 exige) -- o addon
    final saiu sem __init__.py. Mesmo padrao deterministico de
    _inject_manifest (Regra 5)."""

    def setup_method(self):
        self.planner = Planner.__new__(Planner)

    def test_nao_injeta_com_0_ou_1_code_generation(self):
        steps_0 = self.planner._inject_core_step([
            ExecutionStep(step_id="mf1", step_type=STEP_MANIFEST,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
        ], "crie um addon simples")
        assert not any(s.step_id == "cg_core_inj" for s in steps_0)

        steps_1 = self.planner._inject_core_step([
            ExecutionStep(step_id="s1", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
        ], "crie um addon simples")
        assert not any(s.step_id == "cg_core_inj" for s in steps_1)

    def test_injeta_quando_2_features_sem_step_integrador(self):
        """Reproduz o bug real: 2+ code_generation independentes, nenhum
        depende dos outros -- falta o step que integra tudo em __init__.py."""
        steps = self.planner._inject_core_step([
            ExecutionStep(step_id="cg_imagem", step_type=STEP_CODE_GENERATION,
                          description="gera globalPlugins/Addon/imagem/",
                          model_id="m", reasoning_params={}, expected_output="e"),
            ExecutionStep(step_id="cg_audio", step_type=STEP_CODE_GENERATION,
                          description="gera globalPlugins/Addon/audio/",
                          model_id="m", reasoning_params={}, expected_output="e"),
        ], "crie um assistente multimodal com imagem e audio")
        core = next((s for s in steps if s.step_id == "cg_core_inj"), None)
        assert core is not None, "Deveria injetar o step core quando nenhum outro integra tudo"
        assert set(core.depends_on) == {"cg_imagem", "cg_audio"}
        assert set(core.context_from_steps) == {"cg_imagem", "cg_audio"}

    def test_nao_duplica_quando_ja_ha_step_integrador(self):
        """cg_core ja presente no plano bruto (depende de TODOS os outros
        code_generation) -- nao deve injetar um segundo."""
        steps_in = [
            ExecutionStep(step_id="cg_imagem", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
            ExecutionStep(step_id="cg_audio", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
            ExecutionStep(step_id="cg_core", step_type=STEP_CODE_GENERATION,
                          description="integra tudo", model_id="m", reasoning_params={},
                          expected_output="e", depends_on=["cg_imagem", "cg_audio"],
                          context_from_steps=["cg_imagem", "cg_audio"]),
        ]
        steps = self.planner._inject_core_step(steps_in, "crie um addon multimodal")
        assert not any(s.step_id == "cg_core_inj" for s in steps)
        assert len([s for s in steps if s.step_type == STEP_CODE_GENERATION]) == 3

    def test_nao_injeta_quando_step_integrador_cobre_so_alguns(self):
        """Um step que depende de APENAS UM dos outros code_generation nao
        conta como integrador -- mas o teste aqui confirma o caso onde ele
        JA cobre todos (parcial nao e coberto por este helper de forma
        isolada; o proprio codigo so aceita cobertura total)."""
        steps = self.planner._inject_core_step([
            ExecutionStep(step_id="cg_imagem", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
            ExecutionStep(step_id="cg_audio", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
            ExecutionStep(step_id="cg_video", step_type=STEP_CODE_GENERATION,
                          description="so depende de imagem, nao de audio",
                          model_id="m", reasoning_params={}, expected_output="e",
                          depends_on=["cg_imagem"], context_from_steps=["cg_imagem"]),
        ], "crie um addon multimodal")
        core = next((s for s in steps if s.step_id == "cg_core_inj"), None)
        assert core is not None, (
            "cg_video so cobre cg_imagem, nao cg_audio -- nao conta como "
            "integrador completo, ainda falta injetar"
        )

    def test_description_lista_os_subpacotes_e_o_pedido_original(self):
        query = "crie um assistente multimodal com Gemini"
        steps = self.planner._inject_core_step([
            ExecutionStep(step_id="cg_imagem", step_type=STEP_CODE_GENERATION,
                          description="modulo de descricao de imagem",
                          model_id="m", reasoning_params={}, expected_output="e"),
            ExecutionStep(step_id="cg_audio", step_type=STEP_CODE_GENERATION,
                          description="modulo de transcricao de audio",
                          model_id="m", reasoning_params={}, expected_output="e"),
        ], query)
        core = next(s for s in steps if s.step_id == "cg_core_inj")
        assert query in core.description
        assert "modulo de descricao de imagem" in core.description
        assert "modulo de transcricao de audio" in core.description
        assert "GlobalPlugin" in core.description

    def test_assembly_e_documentation_ganham_dependencia_do_core_injetado(self):
        steps = self.planner._inject_core_step([
            ExecutionStep(step_id="cg_imagem", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
            ExecutionStep(step_id="cg_audio", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
            ExecutionStep(step_id="asm", step_type=STEP_ASSEMBLY,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e", depends_on=["cg_imagem", "cg_audio"],
                          context_from_steps=["cg_imagem", "cg_audio"]),
            ExecutionStep(step_id="doc1", step_type=STEP_DOCUMENTATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e", depends_on=["cg_imagem", "cg_audio"],
                          context_from_steps=["cg_imagem", "cg_audio"]),
        ], "crie um addon multimodal")
        asm_step = next(s for s in steps if s.step_type == STEP_ASSEMBLY)
        doc_step = next(s for s in steps if s.step_type == STEP_DOCUMENTATION)
        assert "cg_core_inj" in asm_step.depends_on
        assert "cg_core_inj" in doc_step.depends_on

    def test_inserido_apos_o_ultimo_code_generation_de_feature(self):
        steps = self.planner._inject_core_step([
            ExecutionStep(step_id="cg_imagem", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
            ExecutionStep(step_id="cg_audio", step_type=STEP_CODE_GENERATION,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
            ExecutionStep(step_id="asm", step_type=STEP_ASSEMBLY,
                          description="d", model_id="m", reasoning_params={},
                          expected_output="e"),
        ], "crie um addon multimodal")
        ids = [s.step_id for s in steps]
        assert ids.index("cg_core_inj") > ids.index("cg_audio")
        assert ids.index("cg_core_inj") < ids.index("asm")


class TestCreatePlanRecebeDomainCtx:
    """Explainability (2026-08-03): domain_ctx era calculado na fase PESQUISA
    do orchestrator mas nunca chegava em create_plan()/_call_planner_llm() --
    o plano era montado cego pra pesquisa que tinha acabado de rodar. Agora
    o domain_ctx grounded (arquitetura/boas praticas/seguranca reais) e
    injetado no prompt do planner."""

    def test_domain_ctx_none_nao_quebra(self, fake_api_key):
        """Comportamento antigo (sem domain_ctx) continua funcionando -- default None."""
        from nvdastudio.core.planner import Planner

        raw = {
            "addon_name": "X", "complexity": "low", "requires_web_research": False,
            "requires_agent_runner": False, "assembling_message": "...", "completed_message": "...",
            "dependencies": [], "steps": [],
        }
        mock_resp = MagicMock()
        mock_resp.content = json.dumps(raw)
        mock_resp.reasoning = None

        with patch("nvdastudio.core.planner.create_llm_client") as MC:
            MC.return_value.chat.return_value = mock_resp
            planner = Planner()
            plan = planner.create_plan("criar addon simples")

        assert plan.addon_name == "X"

    def test_domain_ctx_populado_chega_no_prompt_do_llm(self, fake_api_key):
        """O texto de grounding (arquitetura/boas praticas/seguranca reais da
        pesquisa) deve estar no prompt que o LLM do planner recebe -- nao so
        aceito e descartado."""
        from nvdastudio.core.planner import Planner
        from nvdastudio.core.orch_types import DomainContext

        domain_ctx = DomainContext(
            domain="musica",
            description="addon que integra com Spotify",
            apis_involved=["Spotify Web API"],
            best_practices=["usar OAuth2 com refresh token"],
            security_requirements=["nunca hardcode client_secret"],
            architecture_patterns=["separar cliente da API em modulo proprio"],
            nvda_specific_notes=[],
            research_sources=["https://developer.spotify.com/docs"],
        )

        raw = {
            "addon_name": "SpotifyAddon", "complexity": "medium", "requires_web_research": False,
            "requires_agent_runner": False, "assembling_message": "...", "completed_message": "...",
            "dependencies": [], "steps": [],
        }
        mock_resp = MagicMock()
        mock_resp.content = json.dumps(raw)
        mock_resp.reasoning = None

        with patch("nvdastudio.core.planner.create_llm_client") as MC:
            MC.return_value.chat.return_value = mock_resp
            planner = Planner()
            planner.create_plan("criar addon que integra com spotify", domain_ctx=domain_ctx)

        sent_prompt = MC.return_value.chat.call_args[0][0]
        assert "separar cliente da API em modulo proprio" in sent_prompt
        assert "nunca hardcode client_secret" in sent_prompt
        assert "usar OAuth2 com refresh token" in sent_prompt
