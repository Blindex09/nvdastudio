import math

from nvdastudio.core.planner import (
	apply_model_budget, ExecutionStep, STEP_CODE_GENERATION, STEP_MANIFEST,
)


def _make_steps(n_code_gen: int, n_other: int) -> list[ExecutionStep]:
	steps = [
		ExecutionStep(f"cg{i}", STEP_CODE_GENERATION, "gerar", "alto")
		for i in range(n_code_gen)
	]
	steps += [
		ExecutionStep(f"o{i}", STEP_MANIFEST, "manifest", "alto")
		for i in range(n_other)
	]
	return steps


class TestBudgetPorComplexidade:
	def test_complexity_high_usa_tier_frontier(self):
		steps = _make_steps(n_code_gen=10, n_other=0)
		apply_model_budget(steps, "ollama", "alto", complexity="high")
		frontier_count = sum(s.model_id == "qwen3.5:397b" for s in steps)
		assert frontier_count == math.floor(10 * 0.35)

	def test_complexity_medium_usa_tier_heavy_percentual_original(self):
		"""Retrocompatibilidade: complexity default (medium) mantem os
		mesmos 20% do tier heavy -- a IDENTIDADE do modelo heavy pode variar
		conforme o router pontua (model_router.py 1.3.0/model_registry.py
		1.16.0 corrigiram cost_tier de varios modelos Ollama com dados reais
		de ollama.com -- kimi-k2.7-code nao e mais garantido vencer), mas o
		PERCENTUAL (20%) continua igual."""
		from nvdastudio.ai.model_router import select_model
		steps = _make_steps(n_code_gen=10, n_other=0)
		apply_model_budget(steps, "ollama", "alto", complexity="medium")
		heavy_model = select_model("ollama", STEP_CODE_GENERATION, "alto", complexity="medium")
		heavy_count = sum(s.model_id == heavy_model for s in steps)
		assert heavy_count == math.floor(10 * 0.20)

	def test_complexity_ausente_usa_default_medium(self):
		"""apply_model_budget() sem complexity= (comportamento anterior a
		2.22.0) continua identico -- default e 'medium'. IDENTIDADE do
		modelo pode variar (ver comentario acima), PERCENTUAL nao."""
		from nvdastudio.ai.model_router import select_model
		steps = _make_steps(n_code_gen=10, n_other=0)
		apply_model_budget(steps, "ollama", "alto")
		heavy_model = select_model("ollama", STEP_CODE_GENERATION, "alto", complexity="medium")
		heavy_count = sum(s.model_id == heavy_model for s in steps)
		assert heavy_count == math.floor(10 * 0.20)

	def test_complexity_low_todos_os_code_generation_ficam_no_mesmo_modelo_barato(self):
		"""complexity="low" e um caso especial: o slot "elevado" tambem e
		pontuado com complexity="low" (mesma formula usada pros steps
		nao-elevados, que SEMPRE sao pontuados como complexity="low" de
		proposito -- ver comentario em apply_model_budget()). Os dois
		colapsam na MESMA escolha, entao todo code_generation cai no mesmo
		modelo -- comportamento correto, nao uma regressao: pedido simples
		nao deveria ter um slot "premium" diferente do resto."""
		steps = _make_steps(n_code_gen=10, n_other=0)
		apply_model_budget(steps, "ollama", "alto", complexity="low")
		model_ids = {s.model_id for s in steps}
		assert len(model_ids) == 1

	def test_complexity_baixa_favorece_custo_sobre_qualidade_no_slot_elevado(self):
		"""Comparando alto vs baixo: o modelo escolhido pro slot elevado em
		complexity="low" deve ter cost_tier melhor (mais barato) ou igual ao
		escolhido em complexity="high" -- baixa complexidade nunca deve
		escolher um modelo mais caro que alta complexidade pro mesmo papel."""
		from nvdastudio.ai.model_registry import registry
		from nvdastudio.ai.model_router import _COST_TIER_SCORE
		steps_low = _make_steps(n_code_gen=10, n_other=0)
		apply_model_budget(steps_low, "ollama", "alto", complexity="low")
		steps_high = _make_steps(n_code_gen=10, n_other=0)
		apply_model_budget(steps_high, "ollama", "alto", complexity="high")

		low_cost = _COST_TIER_SCORE[registry.get_model_info(steps_low[0].model_id).cost_tier]
		high_cost = _COST_TIER_SCORE[registry.get_model_info(steps_high[0].model_id).cost_tier]
		assert low_cost >= high_cost

	def test_provider_sem_tier_frontier_cai_pra_heavy(self):
		"""xAI nao tem tier 'frontier' registrado -- high deve cair pra
		heavy em vez de KeyError ou virar 'light' silenciosamente."""
		steps = _make_steps(n_code_gen=5, n_other=0)
		apply_model_budget(steps, "xai", "alto", complexity="high")
		elevated_count = sum(s.model_id == "grok-build-0.1" for s in steps)
		assert elevated_count == math.floor(5 * 0.35)


class TestResolveProviderTierModelFrontier:
	def test_ollama_frontier_resolve_qwen(self):
		from nvdastudio.ai.model_registry import resolve_provider_tier_model
		assert resolve_provider_tier_model("ollama", "frontier", "alto") == "qwen3.5:397b"

	def test_provider_sem_frontier_cai_pra_heavy_nao_light(self):
		"""Antes de 2.22.0, um tier desconhecido virava 'light' silenciosamente
		(bug que esta correcao teria reintroduzido sem o fallback explicito)."""
		from nvdastudio.ai.model_registry import resolve_provider_tier_model
		heavy = resolve_provider_tier_model("anthropic", "heavy", "alto")
		frontier_fallback = resolve_provider_tier_model("anthropic", "frontier", "alto")
		assert frontier_fallback == heavy

	def test_tier_desconhecido_nao_relacionado_ainda_cai_pra_light(self):
		"""Retrocompatibilidade: um tier arbitrario que NAO e heavy/light/
		frontier continua caindo em 'light', como sempre foi."""
		from nvdastudio.ai.model_registry import resolve_provider_tier_model
		light = resolve_provider_tier_model("ollama", "light", "alto")
		result = resolve_provider_tier_model("ollama", "algo_inexistente", "alto")
		assert result == light


class TestNovosModelosOllamaSemColisao:
	def test_kimi_k3_nao_foi_adicionado(self):
		"""kimi-k3 retorna HTTP 402 (sem saldo) na conta real -- exclusao
		deliberada, mesma regra de kimi3/claude-fable-5. Redundante com
		test_model_registry_ollama_2026_08.py, mantido aqui tambem porque
		quase reintroduzi esse mesmo erro adicionando por completude sem
		checar a exclusao anterior."""
		from nvdastudio.ai.model_registry import registry
		assert registry.get_model_info("kimi-k3") is None

	def test_qwen_gpt_oss_120b_registrados(self):
		from nvdastudio.ai.model_registry import registry
		assert registry.get_model_info("qwen3.5:397b") is not None
		assert registry.get_model_info("gpt-oss:120b") is not None

	def test_novos_provedores_no_fold_ollama(self):
		from nvdastudio.ai.model_registry import _OLLAMA_SERVED_MAKERS
		for maker in ("alibaba", "nvidia", "mistral", "google_oss"):
			assert maker in _OLLAMA_SERVED_MAKERS


class TestGetResilienceModelUsaRoteador:
	"""orchestrator.py 5.36.0: _get_resilience_model() so pontuava via o
	roteador (ai/model_router.py) na escolha INICIAL de modelo
	(apply_model_budget()) -- a escalacao continuava presa no tier "heavy"
	fixo. Achado real ao validar a rodada anterior (test_e36): um step que
	escalava no meio do retry voltava pro kimi-k2.7-code hardcoded mesmo
	quando o roteador tinha escolhido qwen3.5:397b originalmente pra ele."""

	def test_sem_step_type_mantem_comportamento_antigo(self):
		"""Retrocompatibilidade: chamador que nao passa step_type continua
		recebendo o tier heavy fixo (resolve_provider_tier_model), nao o
		roteador -- nenhuma mudanca de comportamento pra esse caso."""
		from nvdastudio.core.orchestrator import _get_resilience_model
		from nvdastudio.ai.model_registry import resolve_provider_tier_model
		assert _get_resilience_model() == resolve_provider_tier_model("ollama", "heavy", "alto")

	def test_com_step_type_usa_roteador(self):
		"""Com step_type informado, usa select_model() -- pode divergir do
		tier heavy fixo quando a pontuacao real favorece outro candidato
		(ex: complexity="high" favorece o tier frontier, nao heavy)."""
		from nvdastudio.core.orchestrator import _get_resilience_model
		from nvdastudio.ai.model_router import select_model
		from nvdastudio.core.planner import STEP_CODE_GENERATION
		result = _get_resilience_model(STEP_CODE_GENERATION, "high")
		assert result == select_model("ollama", STEP_CODE_GENERATION, "alto", complexity="high")
		assert result == "qwen3.5:397b"
