import threading
import time
from dataclasses import asdict, dataclass

from .model_registry import ALTO_MODEL, is_alto_model, registry
from .route_advisor import RouteCandidate, rank_candidates
from ..utils.logger import get_logger

MODULE_VERSION = "3.1.0"
_logger = get_logger("model_router")

STUDIO_PROVIDER = "studio"
STUDIO_ROUTABLE_PROVIDERS = (
	"factory", "openai", "anthropic", "gemini", "xai", "ollama", "opencode_go",
)
_MAX_STUDIO_ROUTES = 3
_CIRCUIT_FAILURE_THRESHOLD = 2
_CIRCUIT_COOLDOWN_SECONDS = 300.0

_ROUTABLE_MODEL_CAPABILITIES = frozenset({"vision", "audio", "video"})
_VALID_COMPLEXITIES = ("low", "medium", "high")
_VALID_PREFERENCES = ("balanced", "quality", "cost", "speed", "privacy")

# Etapas cuja tarefa real é código: só decide se o modelo "frontier" entra no
# fallback por tier quando o catálogo do provedor não responde.
_CODING_STEP_TYPES = frozenset({"code_generation", "agent_runner", "syntax_validation"})

# Prior neutro e encolhimento bayesiano da taxa observada: a confiança cresce
# suave com o volume de dados (~50% em _RELIABILITY_SHRINKAGE_K tentativas),
# nunca chega a 100% e uma única falha de infraestrutura não derruba o modelo.
_RELIABILITY_SHRINKAGE_K = 20.0
_NEUTRAL_RELIABILITY = 0.75


@dataclass(frozen=True)
class RoutingHints:
	"""Decisão semântica da IA sobre a tarefa, entregue como dado tipado.

	Nunca viaja embutida no texto do pedido: o texto é do usuário, e qualquer
	marcador digitado ali passaria por decisão da IA.
	"""

	complexity: str = "medium"
	preference: str = "balanced"
	capabilities: frozenset[str] = frozenset()
	task_summary: str = ""

	@classmethod
	def declared(
		cls,
		complexity: object = "medium",
		preference: object = "balanced",
		capabilities: object = (),
		task_summary: str = "",
	) -> "RoutingHints":
		"""Valida o que a IA declarou contra o schema; valor inválido vira o padrão."""
		level = str(complexity or "").lower()
		pref = str(preference or "").lower()
		caps = {str(c).lower() for c in (capabilities or ())}  # type: ignore[attr-defined]
		return cls(
			complexity=level if level in _VALID_COMPLEXITIES else "medium",
			preference=pref if pref in _VALID_PREFERENCES else "balanced",
			capabilities=frozenset(caps & _ROUTABLE_MODEL_CAPABILITIES),
			task_summary=task_summary or "",
		)


@dataclass(frozen=True)
class RouteDecision:
	"""Decisão auditável de provedor/modelo produzida pelo gateway Studio."""

	provider: str
	model_id: str
	score: float
	reason: str
	complexity: str
	preference: str
	required_capabilities: tuple[str, ...]
	estimated_context_tokens: int

	def to_dict(self) -> dict:
		return asdict(self)


@dataclass
class _ProviderHealth:
	consecutive_failures: int = 0
	retry_after: float = 0.0
	last_error: str = ""


_provider_health: dict[str, _ProviderHealth] = {}
_provider_health_lock = threading.Lock()


def estimate_context_tokens(request: str) -> int:
	"""Estimativa conservadora incluindo o contexto técnico fixo do NVDA."""
	return max(4_000, len(request or "") // 4 + 12_000)


def record_provider_outcome(provider: str, success: bool, error: str = "") -> None:
	"""Atualiza o disjuntor de sessão usado somente pelo roteamento Studio."""
	if provider == STUDIO_PROVIDER:
		return
	with _provider_health_lock:
		health = _provider_health.setdefault(provider, _ProviderHealth())
		if success:
			health.consecutive_failures = 0
			health.retry_after = 0.0
			health.last_error = ""
			return
		health.consecutive_failures += 1
		health.last_error = (error or "falha sem detalhe")[:500]
		if health.consecutive_failures >= _CIRCUIT_FAILURE_THRESHOLD:
			health.retry_after = time.monotonic() + _CIRCUIT_COOLDOWN_SECONDS
			_logger.warning(
				"[DISJUNTOR] %s desligado por %.0fs apos %d falhas seguidas; ultimo erro: %s",
				provider, _CIRCUIT_COOLDOWN_SECONDS, health.consecutive_failures, health.last_error,
			)


def _provider_is_healthy(provider: str) -> bool:
	with _provider_health_lock:
		health = _provider_health.get(provider)
		return health is None or health.retry_after <= time.monotonic()


def _observed_reliability(provider: str, model_id: str, step_type: str) -> dict:
	try:
		from ..memory.session_memory import memory
		return memory.get_model_reliability(provider, model_id, step_type)
	except Exception as exc:
		_logger.debug("[DEBUG] get_model_reliability indisponivel: %s", exc)
		return {"attempts": 0, "success_rate": 0.0}


def _reliability_score(provider: str, model_id: str, step_type: str) -> float:
	data = _observed_reliability(provider, model_id, step_type)
	attempts = data["attempts"]
	if attempts <= 0:
		return _NEUTRAL_RELIABILITY
	confidence = attempts / (attempts + _RELIABILITY_SHRINKAGE_K)
	return (1.0 - confidence) * _NEUTRAL_RELIABILITY + confidence * data["success_rate"]


def _normalized_capabilities(provider: str, model_id: str) -> set[str]:
	"""Normaliza aliases históricos do catálogo sem inventar capacidades."""
	if provider == "factory" and model_id == "auto":
		return {"tool_use", "coding_agentic"}
	info = registry.get_model_info(model_id)
	if info is None:
		return set()
	caps = set(info.capabilities)
	if "tools" in caps:
		caps.add("tool_use")
	return caps


def _candidate(provider: str, model_id: str, step_type: str) -> RouteCandidate:
	"""Reúne os fatos do catálogo e da memória; nenhum julgamento embutido."""
	from .model_pricing import get_model_price
	info = registry.get_model_info(model_id)
	price = get_model_price(provider, model_id)
	observed = _observed_reliability(provider, model_id, step_type)
	attempts = int(observed.get("attempts", 0) or 0)
	return RouteCandidate(
		provider=provider,
		model_id=model_id,
		cost_tier=info.cost_tier if info else "medium",
		usd_per_million_input=price.input_per_million if price else None,
		usd_per_million_output=price.output_per_million if price else None,
		context_window=info.context_window if info else 0,
		capabilities=tuple(sorted(_normalized_capabilities(provider, model_id))),
		observed_attempts=attempts,
		observed_success_rate=float(observed["success_rate"]) if attempts > 0 else None,
	)


def _fits_context(model_id: str, context_tokens: int) -> bool:
	info = registry.get_model_info(model_id)
	return not (info and info.context_window and context_tokens > info.context_window)


def _eligible_models(
	provider: str,
	step_type: str,
	complexity: str,
	configured_model: str,
	required: frozenset[str],
	context_tokens: int = 0,
) -> list[str]:
	"""Modelos do provedor que satisfazem fatos objetivos (capacidade, contexto).

	Sem catálogo ativo para o provedor (ex.: Factory, que roteia sozinha), o
	candidato é o modelo do tier configurado.
	"""
	from .model_registry import (
		_UI_PROVIDER_TO_REGISTRY_PROVIDERS,
		get_provider_step_models,
		resolve_provider_tier_model,
	)
	if provider not in _UI_PROVIDER_TO_REGISTRY_PROVIDERS:
		provider = "ollama"
	try:
		infos = registry.get_active_models_for_ui_provider(provider)
	except Exception as exc:
		_logger.warning("[AVISO] model_router: catalogo indisponivel (%s), caindo pro tier fixo.", exc)
		infos = []
	if not infos:
		tier = "frontier" if complexity == "high" and step_type in _CODING_STEP_TYPES else "heavy"
		return [resolve_provider_tier_model(provider, tier, configured_model)]

	ids = [m.model_id for m in infos]
	if required:
		capable = [i for i in ids if required.issubset(_normalized_capabilities(provider, i))]
		if capable:
			ids = capable
		else:
			_logger.warning(
				"[AVISO] model_router: nenhum modelo de %s tem %s -- "
				"considerando sem esse filtro (pode nao suportar a chamada de verdade).",
				provider, sorted(required),
			)
	if context_tokens:
		ids = [i for i in ids if _fits_context(i, context_tokens)]
	# O modelo "frontier" é reservado a tarefas de alta complexidade: teto de
	# gasto imposto pelo harness, não opinião sobre qualidade.
	frontier_id = get_provider_step_models(provider).get("frontier")
	if frontier_id and complexity != "high":
		ids = [i for i in ids if i != frontier_id] or ids
	return ids


def select_model(
	provider: str,
	step_type: str,
	configured_model: str,
	complexity: str = "medium",
	required_capabilities: frozenset[str] | None = None,
	task_summary: str = "",
) -> str:
	"""Escolhe o model_id de UM provedor para o modo "Alto".

	Modelo concreto escolhido pelo usuário sempre vence. Entre os modelos
	elegíveis do provedor a decisão é da IA (route_advisor); com um só
	candidato, ou sem resposta da IA, vale a ordem de contingência do harness.
	Nunca retorna vazio nem levanta exceção.
	"""
	return select_model_with_reason(
		provider, step_type, configured_model, complexity,
		required_capabilities, task_summary,
	)[0]


def select_model_with_reason(
	provider: str,
	step_type: str,
	configured_model: str,
	complexity: str = "medium",
	required_capabilities: frozenset[str] | None = None,
	task_summary: str = "",
) -> tuple[str, str]:
	"""Como select_model(), mas também devolve o motivo da escolha.

	Achado ao vivo (2026-09-29): select_routes() descartava esse motivo no
	caminho de provedor fixo ("Alto" fora do Studio) -- o log da rota sempre
	mostrava o mesmo texto genérico ("Provedor escolhido manualmente..."),
	mesmo quando a IA de fato comparou vários modelos do MESMO provedor e
	justificou a escolha (confirmado ao vivo: rodadas idênticas escolheram
	kimi-k2.7-code numa vez e minimax-m2.7 na outra -- prova de que o
	ranking real acontece, só não era mostrado).
	"""
	if not is_alto_model(configured_model):
		return configured_model, "modelo especifico escolhido pelo usuario"
	ids = _eligible_models(
		provider, step_type, complexity, configured_model,
		required_capabilities or frozenset(),
	)
	if len(ids) == 1:
		return ids[0], "unico modelo elegivel do provedor para esta tarefa"
	result = rank_candidates(
		[_candidate(provider, i, step_type) for i in ids],
		step_type=step_type, complexity=complexity, preference="balanced",
		task_summary=task_summary,
		reliability={f"{provider}::{i}": _reliability_score(provider, i, step_type) for i in ids},
	)
	model_id = result.order[0].split("::", 1)[1]
	return model_id, result.reason


def select_routes(
	provider: str,
	step_type: str,
	configured_model: str,
	*,
	request: str = "",
	hints: RoutingHints | None = None,
	available_providers: tuple[str, ...] | list[str] | None = None,
	required_capabilities: frozenset[str] | None = None,
) -> list[RouteDecision]:
	"""Seleciona uma rota manual ou um ranking cross-provider para Studio.

	Fora de ``Studio + Alto`` nunca há troca silenciosa de provedor. No Studio,
	só entram provedores que o chamador confirmou como configurados e saudáveis,
	e candidatos que satisfazem capacidade e contexto; quem ordena é a IA.
	"""
	hints = hints or RoutingHints()
	complexity, preference = hints.complexity, hints.preference
	required = frozenset(required_capabilities or ()) | hints.capabilities
	context_tokens = estimate_context_tokens(request)

	if provider != STUDIO_PROVIDER or not is_alto_model(configured_model):
		model_id, model_reason = select_model_with_reason(
			provider, step_type, configured_model, complexity=complexity,
			required_capabilities=required, task_summary=hints.task_summary,
		)
		return [RouteDecision(
			provider=provider, model_id=model_id, score=1.0,
			# "manualmente" e o marcador literal que orchestrator.py:_run_agent
			# usa para decidir a narracao ("Studio selecionou..." vs "Usando...");
			# preservar a palavra mantem esse contrato -- so o texto ao redor
			# ganhou o motivo real da escolha do modelo dentro do provedor.
			reason=f"Provedor {provider} escolhido manualmente; {model_reason}.",
			complexity=complexity, preference=preference,
			required_capabilities=tuple(sorted(required)),
			estimated_context_tokens=context_tokens,
		)]

	available = set(available_providers or ())
	pool: list[RouteCandidate] = []
	for candidate_provider in STUDIO_ROUTABLE_PROVIDERS:
		if candidate_provider not in available or not _provider_is_healthy(candidate_provider):
			continue
		for model_id in _eligible_models(
			candidate_provider, step_type, complexity, ALTO_MODEL, required, context_tokens,
		):
			if required and not required.issubset(_normalized_capabilities(candidate_provider, model_id)):
				continue
			pool.append(_candidate(candidate_provider, model_id, step_type))
	if not pool:
		return []

	advice = rank_candidates(
		pool, step_type=step_type, complexity=complexity, preference=preference,
		task_summary=hints.task_summary,
		reliability={c.key: _reliability_score(c.provider, c.model_id, step_type) for c in pool},
	)
	by_key = {c.key: c for c in pool}
	# Privacidade significa minimização de compartilhamento: uma única empresa
	# recebe o pedido, sem failover que replique contexto entre serviços.
	limit = 1 if preference == "privacy" else _MAX_STUDIO_ROUTES
	reason = (
		f"{advice.reason}; complexidade {complexity}; preferência {preference}; "
		f"capacidades {', '.join(sorted(required)) or 'gerais'}; "
		f"contexto estimado {context_tokens} tokens; "
		f"decisão {'da IA' if advice.source == 'ia' else 'de contingência'}"
	)
	routes: list[RouteDecision] = []
	seen_providers: set[str] = set()
	for position, key in enumerate(advice.order):
		candidate = by_key[key]
		if candidate.provider in seen_providers:
			continue
		seen_providers.add(candidate.provider)
		routes.append(RouteDecision(
			provider=candidate.provider, model_id=candidate.model_id,
			score=round(1.0 - position / len(advice.order), 3), reason=reason,
			complexity=complexity, preference=preference,
			required_capabilities=tuple(sorted(required)),
			estimated_context_tokens=context_tokens,
		))
		if len(routes) >= limit:
			break
	return routes
