import math

from .model_registry import registry, is_alto_model
from ..utils.logger import get_logger

MODULE_VERSION = "1.7.0"
_logger = get_logger("model_router")

# Pontuacao neutra pra modelo sem hint curado -- mesmo valor de fallback
# usado por C:\agentic (_documented_strengths), nem penaliza nem favorece
# um modelo novo que ainda nao foi avaliado manualmente.
_NEUTRAL_STRENGTH = 0.65

# Hints curados manualmente (quality=capacidade geral, coding=tarefas de
# geracao de codigo, tools=pesquisa/relatorio/tarefas nao-codigo, speed=
# latencia relativa). Heuristica baseada em descricao/porte/geracao do
# modelo (ver model_registry.py) -- NAO e benchmark real medido, e revisado
# conforme evidencia observada (get_model_reliability) acumular.
_DOCUMENTED_STRENGTHS: dict[tuple[str, str], dict[str, float]] = {
	("ollama", "kimi-k2.7-code"):        {"quality": .85, "coding": .92, "tools": .70, "speed": .55},
	("ollama", "kimi-k2.6"):             {"quality": .78, "coding": .84, "tools": .68, "speed": .60},
	("ollama", "deepseek-v4-flash"):     {"quality": .70, "coding": .72, "tools": .68, "speed": .88},
	("ollama", "deepseek-v4-pro"):       {"quality": .82, "coding": .80, "tools": .75, "speed": .60},
	("ollama", "glm-5.2"):               {"quality": .84, "coding": .90, "tools": .72, "speed": .55},
	("ollama", "glm-5.1"):               {"quality": .78, "coding": .84, "tools": .68, "speed": .58},
	("ollama", "minimax-m3"):            {"quality": .80, "coding": .86, "tools": .75, "speed": .60},
	("ollama", "minimax-m2.7"):          {"quality": .74, "coding": .78, "tools": .70, "speed": .62},
	("ollama", "gpt-oss:20b"):           {"quality": .68, "coding": .72, "tools": .74, "speed": .85},
	("ollama", "gpt-oss:120b"):          {"quality": .82, "coding": .84, "tools": .80, "speed": .55},
	# coding acima de kimi-k2.7-code de proposito: e o candidato "frontier"
	# (397B, maior modelo confirmado na conta) -- precisa vencer sob
	# complexity="high" (tradeoff=0, qualidade pura) mesmo pagando o
	# cost_tier "high" mais penalizado. Ajustado apos rodar os testes
	# desta mudanca varias vezes ate a margem ficar robusta (>0.02).
	("ollama", "qwen3.5:397b"):          {"quality": .96, "coding": .99, "tools": .80, "speed": .35},
	("ollama", "nemotron-3-ultra"):      {"quality": .84, "coding": .78, "tools": .78, "speed": .40},
	("ollama", "nemotron-3-super"):      {"quality": .76, "coding": .72, "tools": .72, "speed": .55},
	("ollama", "nemotron-3-nano:30b"):   {"quality": .62, "coding": .58, "tools": .60, "speed": .90},
	("ollama", "mistral-large-3:675b"):  {"quality": .84, "coding": .80, "tools": .76, "speed": .38},
	("ollama", "gemma4:31b"):            {"quality": .64, "coding": .60, "tools": .65, "speed": .82},
	("anthropic", "claude-opus-5"):      {"quality": .96, "coding": .95, "tools": .93, "speed": .42},
	("anthropic", "claude-sonnet-5"):    {"quality": .90, "coding": .93, "tools": .92, "speed": .68},
	("anthropic", "claude-haiku-4-5"):   {"quality": .72, "coding": .72, "tools": .78, "speed": .95},
	("openai", "gpt-5.6-sol"):           {"quality": .96, "coding": .98, "tools": .96, "speed": .48},
	("openai", "gpt-5.6-terra"):         {"quality": .88, "coding": .90, "tools": .90, "speed": .65},
	("openai", "gpt-5.6-luna"):          {"quality": .74, "coding": .76, "tools": .78, "speed": .92},
	("google", "gemini-2.5-pro"):        {"quality": .93, "coding": .92, "tools": .88, "speed": .48},
	("google", "gemini-3.6-flash"):      {"quality": .88, "coding": .89, "tools": .90, "speed": .90},
	("gemini", "gemini-2.5-pro"):        {"quality": .93, "coding": .92, "tools": .88, "speed": .48},
	("gemini", "gemini-3.6-flash"):      {"quality": .88, "coding": .89, "tools": .90, "speed": .90},
	("xai", "grok-build-0.1"):           {"quality": .90, "coding": .94, "tools": .88, "speed": .55},
	("xai", "grok-4.5"):                 {"quality": .90, "coding": .92, "tools": .90, "speed": .70},
	("xai", "grok-4.3"):                 {"quality": .78, "coding": .80, "tools": .78, "speed": .85},
	# Testado ao vivo (2026-08-08): segue instrucao de formato onde os
	# modelos do catalogo Ollama falhavam -- sem vies de especializacao em
	# codigo (nao e um modelo "de codigo"). "tools" alto de proposito.
	("opencode_go", "gpt-5.6-luna"):     {"quality": .74, "coding": .76, "tools": .90, "speed": .90},
}

# Faixa deliberadamente estreita (0.45-0.85, nao 0.3-1.0): C:\agentic usa
# custo REAL em dolar por chamada com decaimento LOGARITMICO
# (1/(1+log1p(custo*100))), que comprime naturalmente diferencas de preco
# grandes. NVDAStudio so tem cost_tier (3 baldes curados, sem preco real
# por token) -- uma faixa larga fazia o custo DOMINAR a pontuacao mesmo
# com peso nominal menor que qualidade, porque os hints de qualidade/coding
# ficam proximos entre modelos do mesmo catalogo (0.6-0.98) enquanto uma
# faixa 0.3-1.0 de custo tem amplitude maior -- o modelo mais fraco e mais
# barato vencia ate contra o mais forte em complexity="medium" (achado
# real ao rodar os testes desta mudanca: gpt-5.6-luna vencia gpt-5.6-sol).
_COST_TIER_SCORE = {"low": 0.85, "medium": 0.65, "high": 0.45}

# Step types cuja tarefa real e "codigo" (usa a dimensao coding do hint)
# vs "ferramenta/relatorio" (usa tools) vs generico (usa quality). Mesma
# ideia do task_type de C:\agentic, mas reaproveitando step_type -- o
# proprio orquestrador ja sabe exatamente que tarefa e essa, diferente de
# um agente de chat generico que precisa classificar a mensagem.
_CODING_STEP_TYPES = frozenset({"code_generation", "agent_runner", "syntax_validation"})
_TOOLS_STEP_TYPES = frozenset({
	"web_research", "manifest_builder", "documentation", "design_review",
	"accessibility_audit", "agent_template", "assembly", "test_generation",
})

# Complexidade do PEDIDO INTEIRO (ja classificada pelo planner via IA, uma
# vez por plano -- nunca palavra-chave) mapeada pro dial cost_quality_tradeoff
# de C:\agentic (0=qualidade em primeiro lugar, 1=custo em primeiro lugar).
# "high" fica em 0.0 (qualidade pura, custo so entra via os pesos minimos
# residuais de velocidade/confiabilidade) de proposito: um pedido que a
# propria IA do planner ja classificou como alta complexidade nao deve ter
# a escolha de modelo comprometida por custo -- e o cenario em que vale a
# pena gastar mais pra reduzir risco de retrabalho. Ajustado apos testes
# reais desta mudanca mostrarem que 0.15 ainda deixava kimi-k2.7-code
# (cost_tier medio, hints fortes) vencer candidatos "frontier" por uma
# margem fragil demais (diferenca de pontuacao < 0.01).
_COST_QUALITY_TRADEOFF_BY_COMPLEXITY = {
	"low": 0.75, "simple": 0.75,
	"medium": 0.45,
	"high": 0.0,
}

# 1.5.0: corte binario (< 5 tentativas = 100% prior neutro, >= 5 = 100%
# taxa observada) substituido por shrinkage bayesiano suave, portado de
# C:\agentic (providers_auto.py::_routing_score()). Corte binario tem um
# problema real: a tentativa #5 pesa 0->100% de repente, e uma unica falha
# isolada por infra (503, timeout) nessa tentativa derruba o modelo
# inteiro do ranking de uma vez. Shrinkage: confianca cresce suave com
# volume de dados (~50% em _RELIABILITY_SHRINKAGE_K tentativas), nunca
# chega a 100% (o prior nunca e totalmente descartado) nem fica em 0%
# (um unico dado real ja pesa um pouco). Mesma constante K=20 de
# C:\agentic, mesmo raciocinio documentado la: "at 20 attempts confidence
# is .5; it never fully replaces the hint... but it can no longer
# dominate it forever either."
_RELIABILITY_SHRINKAGE_K = 20.0
_NEUTRAL_RELIABILITY = 0.75


def _task_quality(strengths: dict[str, float], step_type: str) -> float:
	if step_type in _CODING_STEP_TYPES:
		return strengths["coding"]
	if step_type in _TOOLS_STEP_TYPES:
		return strengths["tools"]
	return strengths["quality"]


# Tamanho representativo de UMA chamada, usado so pra estimar custo real
# ($/token) de forma comparavel entre modelos -- nao precisa ser exato (a
# mesma dupla de tokens se aplica a todos os candidatos, entao so a ORDEM
# relativa de custo importa pro ranking, nao o valor absoluto em dolar).
_REPRESENTATIVE_INPUT_TOKENS = 4000
_REPRESENTATIVE_OUTPUT_TOKENS = 3000


def _cost_score(provider: str, model_id: str) -> float:
	"""
	1.3.0: quando ha preco real $/token CATALOGADO (model_pricing.py,
	motivado por comparacao direta com C:\\agentic e pedido do Felipe --
	"traz custo real em $/token igual o agentic"), estima o custo de uma
	chamada representativa e aplica o MESMO decaimento logaritmico de
	C:\\agentic: 1.0/(1+log1p(custo*100)), na faixa CHEIA [0, 1] -- sem
	reescalar pra uma faixa estreita. Achado ao vivo (regressao pega pelos
	proprios testes desta mudanca): a primeira versao reescalava pra
	[0.45, 0.85] (a faixa do _COST_TIER_SCORE antigo), o que comprimia
	demais a diferenca real entre modelo caro/barato -- apply_model_budget()
	dependia dessa diferenciacao pra manter a maioria dos steps num modelo
	leve, e com o custo quase empatado TODOS os steps convergiam pro modelo
	de maior qualidade, inclusive o slot que deveria ficar barato. Os pesos
	de _routing_score() (cost_weight/quality_weight) sao IDENTICOS aos de
	C:\\agentic -- usar a faixa cheia deles, nao uma reescala propria, e o
	que faz a formula continuar calibrada.

	Sem preco catalogado (Ollama/OpenCode Go -- sempre, ver PRICING_GAPS em
	model_pricing.py; ou qualquer modelo nao pesquisado), cai pro cost_tier
	curado (comportamento anterior, inalterado) -- mantem a diferenciacao de
	"restricao de recurso" (tamanho/velocidade) que ja existia pra
	providers sem preco real por token.
	"""
	from .model_pricing import get_model_price
	price = get_model_price(provider, model_id)
	if price is not None:
		real_cost = (
			_REPRESENTATIVE_INPUT_TOKENS * price.input_per_million
			+ _REPRESENTATIVE_OUTPUT_TOKENS * price.output_per_million
		) / 1_000_000
		return 1.0 / (1.0 + math.log1p(real_cost * 100))
	info = registry.get_model_info(model_id)
	tier = info.cost_tier if info else "medium"
	return _COST_TIER_SCORE.get(tier, 0.6)


def _reliability_score(provider: str, model_id: str, step_type: str) -> float:
	try:
		from ..memory.session_memory import memory
		data = memory.get_model_reliability(provider, model_id, step_type)
	except Exception as exc:
		_logger.debug("[DEBUG] get_model_reliability indisponivel: %s", exc)
		return _NEUTRAL_RELIABILITY
	attempts = data["attempts"]
	if attempts <= 0:
		return _NEUTRAL_RELIABILITY
	confidence = attempts / (attempts + _RELIABILITY_SHRINKAGE_K)
	return (1.0 - confidence) * _NEUTRAL_RELIABILITY + confidence * data["success_rate"]


def _routing_score(provider: str, model_id: str, step_type: str, complexity: str) -> float:
	strengths = _DOCUMENTED_STRENGTHS.get((provider, model_id), {
		"quality": _NEUTRAL_STRENGTH, "coding": _NEUTRAL_STRENGTH,
		"tools": _NEUTRAL_STRENGTH, "speed": _NEUTRAL_STRENGTH,
	})
	quality = _task_quality(strengths, step_type)
	cost = _cost_score(provider, model_id)
	speed = strengths["speed"]
	reliability = _reliability_score(provider, model_id, step_type)

	tradeoff = _COST_QUALITY_TRADEOFF_BY_COMPLEXITY.get(complexity, 0.45)
	cost_weight = .05 + .40 * tradeoff
	quality_weight = .80 - .40 * tradeoff
	return (
		quality_weight * quality
		+ cost_weight * cost
		+ .10 * speed
		+ .05 * reliability
	)


def select_model(
	provider: str, step_type: str, configured_model: str,
	complexity: str = "medium",
	required_capabilities: frozenset[str] | None = None,
) -> str:
	"""
	Escolhe o melhor model_id pra este (provider, step_type, complexity),
	pontuando TODOS os modelos ativos do provider -- nunca uma tabela fixa
	de 1 valor por tier. Modelo escolhido pelo usuario (diferente de alto)
	sempre vence, sem pontuacao (mesma regra de resolve_provider_tier_model).

	required_capabilities: 2026-08-26, padrao portado de C:\\agentic
	(features/providers/providers_auto.py::_ordered_models() -- roteador
	generaliza isso pra QUALQUER capacidade exigida pela chamada real, nao
	so structured output). Filtra candidatos por ModelInfo.capabilities
	(fatos reais por modelo, ver model_registry.py) ANTES de pontuar --
	nunca decide por cost_tier/heuristica, so pelo que o modelo
	comprovadamente tem. Sem isso, o roteador podia escolher um modelo sem
	suporte real a uma capacidade exigida pela chamada (achado real: 4
	modelos servidos via Ollama Cloud estavam marcados com "json_schema" na
	lista quando a API nao honra isso de verdade -- corrigido nesta mesma
	auditoria, ver changelog dos ModelInfo em _MODEL_REGISTRY).

	Fallback gracioso: sem candidatos elegiveis (registry vazio/erro, ou
	NENHUM candidato satisfaz required_capabilities), cai pra
	resolve_provider_tier_model() (tabela heavy/light/frontier antiga) --
	nunca retorna vazio nem levanta excecao.
	"""
	if not is_alto_model(configured_model):
		return configured_model

	from .model_registry import _UI_PROVIDER_TO_REGISTRY_PROVIDERS, resolve_provider_tier_model, get_provider_step_models
	if provider not in _UI_PROVIDER_TO_REGISTRY_PROVIDERS:
		provider = "ollama"

	try:
		candidates = registry.get_active_models_for_ui_provider(provider)
	except Exception as exc:
		_logger.warning("[AVISO] model_router: catalogo indisponivel (%s), caindo pro tier fixo.", exc)
		candidates = []

	if not candidates:
		tier = "frontier" if complexity == "high" and step_type in _CODING_STEP_TYPES else "heavy"
		return resolve_provider_tier_model(provider, tier, configured_model)

	if required_capabilities:
		capable = [
			m for m in candidates
			if required_capabilities.issubset(set(m.capabilities))
		]
		if capable:
			candidates = capable
		else:
			_logger.warning(
				"[AVISO] model_router: nenhum modelo de %s tem %s -- "
				"pontuando sem esse filtro (pode nao suportar a chamada de verdade).",
				provider, sorted(required_capabilities),
			)

	# 1.4.0: achado real de auditoria 2026-08-26 -- o modelo "frontier" de um
	# provider (ex: qwen3.5:397b no Ollama) e o mais capaz por design, mas
	# _COST_TIER_SCORE so tem 3 baldes (low/medium/high): providers sem
	# preco real por token (Ollama Cloud e assinatura/cota, ver
	# model_pricing.py) caem TODOS nesse fallback grosseiro, e mais de um
	# modelo pode legitimamente colidir no mesmo balde (qwen3.5:397b e
	# deepseek-v4-flash sao AMBOS cost_tier="medium", cada um confirmado
	# por pesquisa dedicada contra ollama.com -- nenhuma das duas
	# classificacoes esta errada). Com o custo empatado, o termo de
	# qualidade (deliberadamente mais alto pro frontier) sempre vencia --
	# inclusive em complexity="low", onde apply_model_budget() conta com
	# o frontier SOMENTE aparecer quando complexity="high" pede
	# explicitamente. Fix: fora de complexity="high", o frontier do
	# provider fica de fora da competicao -- ele e reservado, nao um
	# candidato comum que por acaso pontua alto.
	frontier_id = get_provider_step_models(provider).get("frontier")
	if frontier_id and complexity != "high":
		non_frontier = [m for m in candidates if m.model_id != frontier_id]
		if non_frontier:
			candidates = non_frontier

	best = max(candidates, key=lambda m: _routing_score(provider, m.model_id, step_type, complexity))
	return best.model_id


# Todos os provedores nativos que o NVDAStudio sabe rotear -- usado so pela
# escalacao cross-provider (select_model_and_provider), nunca pra escolha
# inicial (essa continua dentro do provider ativo, ver select_model acima).
_ALL_ROUTABLE_PROVIDERS = ("ollama", "openai", "gemini", "anthropic", "xai", "opencode_go", "factory")

# 1.2.0: quando o provider ATIVO e "ollama", o resgate cross-provider fica
# restrito a este conjunto -- NUNCA os provedores pagos diretos (openai/
# gemini/anthropic/xai). Achado real ao vivo (test_e36, 2026-08-09): o
# resgate escalou pra OpenAI direto so porque a OPENAI_API_KEY estava
# presente no ambiente, mesmo sem saldo/creditos reais la -- Felipe
# esclareceu a intencao real: "ollama em alto, modelos do ollama, o que nao
# tiver nativo, entra opencode go... somente no ollama. so nao faco isso
# com os outros, por que os outros nao tenho assinatura". OpenCode Go e
# assinatura fixa (custo marginal ~0, ver ai/pricing.py), entao e o UNICO
# fallback seguro quando o Ollama e o provider principal escolhido.
# 1.7.0: Factory entra pelo MESMO criterio que ja escolheu o OpenCode Go --
# assinatura fixa, custo marginal previsivel, sem risco de gastar credito
# avulso que o usuario nao tem. Palavras dele em 2026-08-09: "so nao faco
# isso com os outros, por que os outros nao tenho assinatura". Em
# 2026-09-03 o criterio provou seu valor ao contrario: o OpenCode Go ficou
# sem saldo (401) e o Ollama comecou a devolver 429 na mesma sessao,
# deixando o resgate sem para onde ir.
_OLLAMA_RESCUE_PROVIDERS: tuple[str, ...] = ("opencode_go", "factory")


def select_model_and_provider(
	step_type: str, complexity: str, exclude_provider: str | None = None,
	active_provider: str | None = None,
) -> tuple[str, str] | None:
	"""
	1.1.0: escalacao cross-provider -- pontua candidatos de TODOS os
	provedores com chave configurada (nao so o provider ativo) e retorna
	o melhor (provider, model_id) entre eles. Usado quando um step ja
	esgotou retry + escalacao NORMAL (mesmo provider, select_model()) e
	continua falhando -- so nesse ponto, nunca na escolha inicial.

	Alinhado ao padrao de producao 2026 (pesquisa dedicada, 2026-08-09:
	Bifrost/LiteLLM/gateways de LLM): "failover fires at the provider level
	when a backend stops responding, while cascading fires at the model
	quality level when a response score falls below your threshold" --
	provider primario cuida do caso normal (select_model), fallback entre
	provedores so entra quando o primario ja falhou (aqui). Deliberadamente
	MENOS abrangente que C:\\agentic (que pontua todos os provedores desde
	o inicio de toda chamada) -- essa e a excecao sofisticada, nao o padrao
	dominante do mercado; replicar so na escalacao e o que a maioria dos
	gateways de producao faz.

	exclude_provider: provider que ja foi tentado (normal + escalacao) e
	falhou -- nao faz sentido pontuar candidatos dele de novo aqui.

	active_provider (1.2.0): o provider PRINCIPAL configurado pelo usuario
	(get_llm_provider(), ANTES de qualquer exclusao por falha). Quando
	"ollama", restringe o resgate a _OLLAMA_RESCUE_PROVIDERS (so
	opencode_go) -- nunca os provedores pagos diretos, que o usuario pode
	nao ter assinatura/credito neles. Para qualquer outro active_provider,
	comportamento inalterado (todos os _ALL_ROUTABLE_PROVIDERS elegiveis).

	Retorna None quando nenhum OUTRO provider tem chave configurada (fail-
	open -- comportamento identico a antes desta funcao existir).
	"""
	from ..gui.settings_panel import get_api_key
	from .model_registry import _UI_PROVIDER_TO_REGISTRY_PROVIDERS

	routable = _OLLAMA_RESCUE_PROVIDERS if active_provider == "ollama" else _ALL_ROUTABLE_PROVIDERS

	best_provider = ""
	best_model = ""
	best_score = -1.0
	for provider in routable:
		if provider == exclude_provider:
			continue
		if provider not in _UI_PROVIDER_TO_REGISTRY_PROVIDERS:
			continue
		if not get_api_key(provider):
			continue
		try:
			candidates = registry.get_active_models_for_ui_provider(provider)
		except Exception as exc:
			_logger.debug("[DEBUG] select_model_and_provider: %s indisponivel (%s).", provider, exc)
			continue
		for model in candidates:
			score = _routing_score(provider, model.model_id, step_type, complexity)
			if score > best_score:
				best_score = score
				best_provider = provider
				best_model = model.model_id

	if not best_provider:
		return None
	return (best_provider, best_model)
