import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable

from ..utils.logger import get_logger
from .planner import ExecutionPlan
from ..memory.session_memory import memory
from .orch_types import OrchestrationResult, StepResult, compute_progress
from ..utils.iteration_budget import budget as iteration_budget

MODULE_VERSION = "2.7.0"
_LOGGER = get_logger("agentic_loop")

# ---------------------------------------------------------------------------
# Estado da maquina de estados
# ---------------------------------------------------------------------------

class AutonomousState(Enum):
	"""
	Estados do loop autonomo.

	Cada estado representa uma estrategia distinta de resolucao.
	A transicao entre estados e determinada por reflexao sobre o resultado.
	"""
	EXECUTE_NORMAL      = auto()  # tentativa padrao com plano original
	RETRY_SAME          = auto()  # retry com mesmo plano (correcoes menores)
	SWAP_MODEL          = auto()  # troca modelo do step que falhou
	SURGICAL_REPLAN     = auto()  # replaneja apenas sub-arvore do step quebrou
	FULL_REPLAN         = auto()  # replaneja tudo com nova estrategia
	CONSULT_MEMORY      = auto()  # consulta sessoes similares antes de replanar
	FORCED_NOVEL        = auto()  # forca abordagem completamente nova (anti-oscilacao)
	DECOMPOSE_GOAL      = auto()  # divide addon em micro-addons (last resort)
	ASK_USER_HINT       = auto()  # pede dica especifica ao usuario
	# --- v2.0.0 (2026) ---
	SELF_PLAY_ADVERSARIAL = auto()  # gera cenarios adversos para testar robustez
	MENTAL_SIMULATION     = auto()  # simula execucao antes de agir (detecta deadlock)
	TOOL_CREATION         = auto()  # gera ferramenta Python sob demanda
	ENSEMBLE_VERIFY       = auto()  # verifica step critico com multi-modelo
	DIAGNOSE_GIVE_UP      = auto()  # todas as estrategias esgotadas: diagnostico final

# ---------------------------------------------------------------------------
# Estrategias disponiveis (cada uma e um estado possivel)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Strategy:
	"""Uma estrategia de resolucao com descricao e precondicoes."""
	state: AutonomousState
	name: str
	description: str
	max_attempts: int = 3  # quantas vezes pode usar esta estrategia

# Ordem de preferencia: tenta estrategias mais simples primeiro
_AVAILABLE_STRATEGIES: tuple[Strategy, ...] = (
	Strategy(AutonomousState.EXECUTE_NORMAL,       "normal",      "Execucao padrao do pipeline", max_attempts=2),
	Strategy(AutonomousState.RETRY_SAME,           "retry",       "Reexecuta com correcoes menores no contexto", max_attempts=2),
	Strategy(AutonomousState.MENTAL_SIMULATION,    "simulate",    "Simula execucao antes de agir (detecta deadlock)", max_attempts=2),
	Strategy(AutonomousState.SWAP_MODEL,           "swap_model",  "Troca modelo do step critico que falhou", max_attempts=2),
	Strategy(AutonomousState.SURGICAL_REPLAN,        "surgical",    "Replaneja apenas a parte que quebrou", max_attempts=2),
	Strategy(AutonomousState.ENSEMBLE_VERIFY,      "ensemble",    "Verifica step critico com multi-modelo", max_attempts=2),
	Strategy(AutonomousState.FULL_REPLAN,          "full_replan", "Replaneja tudo com nova estrategia de alto nivel", max_attempts=2),
	Strategy(AutonomousState.SELF_PLAY_ADVERSARIAL, "adversarial", "Gera cenarios adversos para testar robustez", max_attempts=2),
	Strategy(AutonomousState.CONSULT_MEMORY,        "memory",      "Consulta sessoes similares para aprender com passado", max_attempts=1),
	Strategy(AutonomousState.TOOL_CREATION,          "tool_create", "Gera ferramenta Python sob demanda", max_attempts=1),
	Strategy(AutonomousState.FORCED_NOVEL,           "novel",       "Forca abordagem completamente nova (anti-oscilacao)", max_attempts=2),
	Strategy(AutonomousState.DECOMPOSE_GOAL,         "decompose",   "Divide addon em partes menores", max_attempts=1),
	Strategy(AutonomousState.ASK_USER_HINT,          "ask_user",    "Pede dica ao usuario sobre requisito critico", max_attempts=2),
)

# ---------------------------------------------------------------------------
# Reflexao: analise do resultado para decidir proximo estado
# ---------------------------------------------------------------------------

@dataclass
class ReflectionResult:
	"""Resultado da reflexao sobre uma tentativa."""
	has_progress: bool
	is_stagnated: bool
	is_oscillating: bool
	critical_step_failed: str  # step_type que falhou, ou ""
	novel_issues: list[str]    # issues que nunca apareceram antes
	repeated_issues: list[str] # issues que ja apareceram antes
	suggested_state: AutonomousState  # proximo estado recomendado
	reason: str

class Reflector:
	"""
	Analisa resultados de tentativas e decide a proxima estrategia.

	Regra: nunca sugere o mesmo estado 2x consecutivamente.
	Regra: detecta oscilacao (A->B->A) e sugere FORCED_NOVEL.
	Regra: 3 tentativas consecutivas sem progresso = DIAGNOSE_GIVE_UP.
	"""

	def __init__(self):
		self._history: list[AutonomousState] = []
		self._all_issues_ever: set[str] = set()
		self._streak_no_progress: int = 0
		self._strategy_success_memory: dict[str, dict[str, float]] = {}

	def _record_success(self, query_pattern: str, state: AutonomousState, score: float) -> None:
		"""Registra score de (query_pattern, estado) para meta-learning."""
		key = query_pattern[:50]
		if key not in self._strategy_success_memory:
			self._strategy_success_memory[key] = {}
		state_name = state.name
		prev = self._strategy_success_memory[key].get(state_name, 0.0)
		# Média móvel exponencial
		self._strategy_success_memory[key][state_name] = 0.7 * prev + 0.3 * score

	def _meta_boost(self, query_pattern: str, candidates: list[AutonomousState]) -> AutonomousState | None:
		"""
		Retorna o estado com melhor historico para queries similares.
		Se nenhum candidato tem historico, retorna None.
		"""
		key = query_pattern[:50]
		mem = self._strategy_success_memory.get(key, {})
		if not mem:
			return None
		best = None
		best_score = -1.0
		for cand in candidates:
			score = mem.get(cand.name, 0.0)
			if score > best_score:
				best_score = score
				best = cand
		return best if best_score > 0.3 else None

	def reflect(
		self,
		prev_result: OrchestrationResult | None,
		curr_result: OrchestrationResult,
		strategy_usage: dict[AutonomousState, int],
	) -> ReflectionResult:
		"""
		Reflete sobre a tentativa atual e decide o proximo estado.

		Fluxo:
		  1. Detecta progresso (compute_progress v2.0)
		  2. Classifica issues em novos vs repetidos
		  3. Detecta oscilacao de estados
		  4. Escolhe proximo estado com base em regras deterministicas
		"""
		# --- 1. Progresso ---
		score, reason = compute_progress(prev_result, curr_result) if prev_result else (100.0, "primeira tentativa")
		has_progress = score >= 15.0

		# Atualiza streak
		if has_progress:
			self._streak_no_progress = 0
		else:
			self._streak_no_progress += 1

		# --- 2. Classificacao de issues ---
		novel_issues: list[str] = []
		repeated_issues: list[str] = []
		for issue in curr_result.all_issues:
			key = issue[:60]
			if key in self._all_issues_ever:
				repeated_issues.append(issue)
			else:
				novel_issues.append(issue)
			self._all_issues_ever.add(key)

		# --- 3. Oscilacao ---
		is_oscillating = self._detect_oscillation()

		# --- 4. Step critico que falhou ---
		critical_failed = ""
		for r in reversed(curr_result.step_results):
			if not r.approved and r.step_type in ("code_generation", "agent_runner"):
				critical_failed = r.step_type
				break

		# --- 5. Sugere proximo estado ---
		suggested = self._suggest_next_state(
			has_progress=has_progress,
			is_oscillating=is_oscillating,
			critical_failed=critical_failed,
			strategy_usage=strategy_usage,
			novel_issues=novel_issues,
		)

		return ReflectionResult(
			has_progress=has_progress,
			is_stagnated=not has_progress and len(self._history) > 1,
			is_oscillating=is_oscillating,
			critical_step_failed=critical_failed,
			novel_issues=novel_issues,
			repeated_issues=repeated_issues,
			suggested_state=suggested,
			reason=reason,
		)

	def _detect_oscillation(self) -> bool:
		"""Detecta padrao A->B->A nos ultimos 3 estados."""
		if len(self._history) < 3:
			return False
		last3 = self._history[-3:]
		return last3[0] == last3[2] and last3[0] != last3[1]

	def _suggest_next_state(
		self,
		has_progress: bool,
		is_oscillating: bool,
		critical_failed: str,
		strategy_usage: dict[AutonomousState, int],
		novel_issues: list[str],
	) -> AutonomousState:
		"""
		Heuristica de transicao de estados.

		Regras (ordem de prioridade):
		  0. Se 3+ tentativas sem progresso -> DIAGNOSE_GIVE_UP (nao queima tokens)
		  1. Se oscilando -> FORCED_NOVEL
		  2. Se ha progresso -> EXECUTE_NORMAL ou RETRY_SAME (continua mesma estrategia)
		  3. Se step critico falhou e nao tentou SWAP_MODEL -> SWAP_MODEL
		  4. Se ja tentou SWAP_MODEL e ainda falha -> SURGICAL_REPLAN
		  5. Se nao ha issues novas (repeticao pura) -> CONSULT_MEMORY
		  6. Se ja usou CONSULT_MEMORY e ainda estagnado -> FULL_REPLAN
		  7. Se FULL_REPLAN esgotado -> DECOMPOSE_GOAL
		  8. Se DECOMPOSE falhou ou nao aplicavel -> ASK_USER_HINT
		  9. Se tudo esgotado -> DIAGNOSE_GIVE_UP
		"""
		# 0. Streak de estagnacao: desiste imediatamente
		if self._streak_no_progress >= 3:
			_LOGGER.info("[REFLEXAO] Streak de %d sem progresso. Desistindo.", self._streak_no_progress)
			return AutonomousState.DIAGNOSE_GIVE_UP

		# 1. Anti-oscilacao
		if is_oscillating:
			_LOGGER.info("[REFLEXAO] Oscilacao detectada. Quebrando com FORCED_NOVEL.")
			return AutonomousState.FORCED_NOVEL

		# 2. Progresso: continua com retry
		if has_progress:
			if strategy_usage.get(AutonomousState.RETRY_SAME, 0) < 2:
				return AutonomousState.RETRY_SAME
			return AutonomousState.EXECUTE_NORMAL

		# 3. Mental simulation: detecta deadlock ANTES de executar
		if strategy_usage.get(AutonomousState.MENTAL_SIMULATION, 0) < 2:
			return AutonomousState.MENTAL_SIMULATION

		# 4. Swap model para step critico
		if critical_failed and strategy_usage.get(AutonomousState.SWAP_MODEL, 0) < 2:
			return AutonomousState.SWAP_MODEL

		# 5. Ensemble verification: multi-modelo para consenso
		if critical_failed and strategy_usage.get(AutonomousState.ENSEMBLE_VERIFY, 0) < 2:
			return AutonomousState.ENSEMBLE_VERIFY

		# 6. Surgical replan
		if strategy_usage.get(AutonomousState.SURGICAL_REPLAN, 0) < 2:
			return AutonomousState.SURGICAL_REPLAN

		# 7. Self-play adversarial: gera cenarios adversos
		if strategy_usage.get(AutonomousState.SELF_PLAY_ADVERSARIAL, 0) < 2:
			return AutonomousState.SELF_PLAY_ADVERSARIAL

		# 8. Memoria se estamos repetindo erros
		if not novel_issues and strategy_usage.get(AutonomousState.CONSULT_MEMORY, 0) < 1:
			return AutonomousState.CONSULT_MEMORY

		# 9. Tool creation: gera ferramenta sob demanda
		if strategy_usage.get(AutonomousState.TOOL_CREATION, 0) < 1:
			return AutonomousState.TOOL_CREATION

		# 10. Full replan
		if strategy_usage.get(AutonomousState.FULL_REPLAN, 0) < 2:
			return AutonomousState.FULL_REPLAN

		# 11. Decompose
		if strategy_usage.get(AutonomousState.DECOMPOSE_GOAL, 0) < 1:
			return AutonomousState.DECOMPOSE_GOAL

		# 12. Perguntar ao usuario
		if strategy_usage.get(AutonomousState.ASK_USER_HINT, 0) < 2:
			return AutonomousState.ASK_USER_HINT

		# 13. Tudo esgotado
		return AutonomousState.DIAGNOSE_GIVE_UP

	def record_state(self, state: AutonomousState) -> None:
		"""Registra estado no historico para deteccao de oscilacao."""
		self._history.append(state)

# ---------------------------------------------------------------------------
# Executor de estrategias
# ---------------------------------------------------------------------------

class StrategyExecutor:
	"""
	Executa uma estrategia (estado) no pipeline.

	Cada metodo corresponde a um estado da FSM.
	Retorna (OrchestrationResult, success_bool).
	"""

	def __init__(self, orchestrator):
		"""
		Inicializa com referencia ao orchestrator.

		v2.1.0 fix: Usa interface publica (run_async, get_api_key, get_last_result)
		em vez de acessar atributos privados (_run_pipeline, _planner, etc).
		"""
		self._orch = orchestrator
		# Nao acessa _planner e _critic direto—usa interface publica

	def _run_sync(
		self,
		user_query: str,
		resume_plan=None,
		resume_completed: "dict[str, StepResult] | None" = None,
	) -> OrchestrationResult:
		self._orch._suppress_complete_callback = True
		try:
			self._orch._run_pipeline(user_query, resume_plan=resume_plan, resume_completed=resume_completed)
			return self._orch._last_result or OrchestrationResult(
				plan_id="?", query=user_query, step_results=[],
				final_output="", success=False, error="Pipeline nao retornou resultado."
			)
		finally:
			self._orch._suppress_complete_callback = False

	# --- Estado: EXECUTE_NORMAL ---
	def execute_normal(self, user_query: str) -> OrchestrationResult:
		"""
		Executa pipeline padrao de forma síncrona.
		"""
		return self._run_sync(user_query)

	# --- Estado: RETRY_SAME ---
	def retry_same(self, user_query: str, last_issues: list[str]) -> OrchestrationResult:
		"""
		Reexecuta com o MESMO plano, mas injeta issues anteriores no contexto
		como FIXMES para que o LLM aprenda sem replanejar.
		"""
		self._orch._previous_issues = last_issues
		return self._run_sync(user_query)

	# --- Estado: SWAP_MODEL ---
	def swap_model(self, user_query: str, failed_step_type: str, current_model: str) -> OrchestrationResult:
		"""
		Troca o modelo do step_type que falhou pelo modelo de resiliencia.

		2.6.0: antes alternava cegamente entre tier "light" e "heavy"
		(resolve_provider_tier_model), ignorando step_type e complexidade --
		duplicava, com pior informacao, a escalacao que o proprio orchestrator
		ja faz internamente (_try_escalation() via model_router.py). Delega
		agora para orchestrator.get_resilience_model(), a MESMA fonte usada
		pela escalacao interna do pipeline, para as duas nunca poderem
		escolher modelos diferentes para o mesmo step_type.
		"""
		new_model = self._orch.get_resilience_model(failed_step_type)
		if new_model == current_model:
			_LOGGER.info(
				"[SWAP_MODEL] %s ja esta no modelo de resiliencia (%s); "
				"escalacao interna do pipeline ja tentou. Reexecutando mesmo assim.",
				failed_step_type, current_model,
			)
		else:
			_LOGGER.info("[SWAP_MODEL] %s: %s -> %s", failed_step_type, current_model, new_model)
		self._orch._previous_issues = [
			f"Step {failed_step_type} falhou com modelo {current_model}. Tentando {new_model}..."
		]
		return self._run_sync(user_query)

	# --- Estado: SURGICAL_REPLAN ---
	def surgical_replan(
		self, user_query: str, failed_step_id: str, prev_step_results: list,
	) -> OrchestrationResult:
		"""
		Replaneja APENAS a partir do step que falhou -- reaproveita o MESMO
		plano da tentativa anterior (self._orch._current_plan) e injeta os
		steps ja aprovados direto em outputs/step_results, sem reexecuta-los.

		Achado de auditoria 2026-08-04: ate esta correcao, a funcao chamava
		`self._orch._planner.create_plan(user_query)` de novo -- uma NOVA
		chamada de LLM, plano nao-deterministico, step_ids sem garantia de
		bater com a tentativa anterior -- e depois reexecutava o pipeline
		INTEIRO do zero (`_run_sync`), identico a toda outra estrategia da
		FSM, apesar do nome/docstring prometerem preservar steps concluidos.
		Agora reusa `self._orch._current_plan` (setado por _run_pipeline() em
		orchestrator.py) e passa os steps aprovados via `resume_completed` --
		o motor de dependencias existente (_deps_ready) reexecuta so o step
		que falhou e quem depende dele (dependentes nunca tiveram output
		setado na tentativa anterior, entao ficam bloqueados ate isso rodar).
		Fallback pra full replan preservado quando nao ha plano anterior pra
		reaproveitar ou o step_id nao existe nele (ex: primeira tentativa).
		"""
		plan = self._orch._current_plan
		if plan is None or not any(s.step_id == failed_step_id for s in plan.steps):
			_LOGGER.warning(
				"[SURGICAL] Sem plano anterior reaproveitavel (step %s). Fallback para full replan.",
				failed_step_id,
			)
			return self.execute_normal(user_query)

		resume_completed = {
			r.step_id: r for r in prev_step_results
			if r.approved and r.step_id != failed_step_id
			and any(s.step_id == r.step_id for s in plan.steps)
		}
		_LOGGER.info(
			"[SURGICAL] Replanejando a partir de %s (%d step(s) preservado(s) de %d).",
			failed_step_id, len(resume_completed), len(plan.steps),
		)
		self._orch._previous_issues = [f"Step {failed_step_id} falhou. Replanejando so a partir dele."]
		return self._run_sync(user_query, resume_plan=plan, resume_completed=resume_completed)

	# --- Estado: FULL_REPLAN ---
	def full_replan(self, user_query: str, last_strategy: str) -> OrchestrationResult:
		"""
		Replaneja TUDO com nova estrategia de alto nivel.
		Injeta hint no prompt do planner para forcar abordagem diferente.
		"""
		_LOGGER.info("[FULL_REPLAN] Estrategia anterior: %s. Forcando nova abordagem.", last_strategy)
		self._orch._last_result = None
		return self._run_sync(user_query)

	# --- Estado: CONSULT_MEMORY ---
	def consult_memory(self, user_query: str) -> OrchestrationResult:
		"""
		Consulta sessoes similares e adapta a query com aprendizados.
		"""
		try:
			similar = memory.get_similar_sessions(user_query, limit=3)
			if similar:
				_LOGGER.info("[MEMORY] %d sessoes similares encontradas.", len(similar))
				enhanced_query = self._enhance_query_with_memory(user_query, similar)
				return self._run_sync(enhanced_query)
			_LOGGER.info("[MEMORY] Nenhuma sessao similar. Executando query original.")
		except Exception as exc:
			_LOGGER.warning("[MEMORY] Erro ao consultar: %s. Fallback para original.", exc)
		return self._run_sync(user_query)

	@staticmethod
	def _enhance_query_with_memory(query: str, similar_sessions: list[dict]) -> str:
		"""Adiciona contexto de aprendizados ao final da query."""
		lessons: list[str] = []
		for sess in similar_sessions:
			if not sess.get("success"):
				issues = sess.get("issues", [])
				if issues:
					lessons.append(
						f"Sessao similar falhou com: {issues[0][:80]}"
					)
		if lessons:
			return (
				f"{query}\n\n"
				f"[APRENDIZADOS DE SESSOES ANTERIORES]\n"
				f"{chr(10).join(f'- {lesson}' for lesson in lessons)}\n"
				f"Evite repetir os mesmos problemas. Use abordagem diferente."
			)
		return query

	# --- Estado: DECOMPOSE_GOAL ---
	def decompose_goal(self, user_query: str) -> OrchestrationResult:
		"""
		Divide addon em micro-addons sequenciais.
		Executa apenas a primeira parte nesta iteracao.
		"""
		_LOGGER.info("[DECOMPOSE] Dividindo goal em sub-goals.")
		decomposed_query = (
			f"{user_query}\n\n"
			f"INSTRUCAO CRITICA: Este addon e complexo. "
			f"Divida em NO MAXIMO 3 funcionalidades core. "
			f"Gere APENAS a primeira funcionalidade nesta versao. "
			f"Deixe hooks/extensao para as demais."
		)
		return self._run_sync(decomposed_query)

	# --- Estado: ASK_USER_HINT ---
	def ask_user_hint(self, user_query: str, stuck_reason: str) -> OrchestrationResult:
		"""
		Pausa e pergunta ao usuario.
		Se callback nao definido, fallback para execute_normal.
		"""
		if self._orch._on_clarify:
			questions = [
				f"Estou com dificuldade em: {stuck_reason}. "
				f"Qual aspecto do addon e mais importante para voce?"
			]
			self._orch._emit("AGUARDANDO_USUARIO",
							 f"Preciso de uma dica para continuar. {len(questions)} pergunta(s).")
			try:
				answers = self._orch._on_clarify(questions)
				enhanced = (
					f"{user_query}\n\n"
					f"[DICA DO USUARIO]\n{chr(10).join(answers)}"
				)
				return self._run_sync(enhanced)
			except Exception as exc:
				_LOGGER.warning("[ASK_USER] Callback falhou: %s. Fallback.", exc)
		else:
			_LOGGER.info("[ASK_USER] Sem callback. Fallback para execucao normal.")
		return self._run_sync(user_query)

	# --- Estado: MENTAL_SIMULATION ---
	def mental_simulation(self, user_query: str, prev_plan: ExecutionPlan | None) -> OrchestrationResult:
		"""
		v2.0 (2026): Simula execucao do plano ANTES de rodar.
		Detecta: deadlocks de dependencia, steps impossiveis, loops.
		Se simulacao passa: executa. Se falha: corrige plano antes de executar.
		"""
		_LOGGER.info("[SIMULATION] Simulando execucao do plano...")
		plan = prev_plan or self._orch._planner.create_plan(user_query)
		issues = []
		steps_by_id = {step.step_id: step for step in plan.steps}
		for step in plan.steps:
			if step.step_id in step.depends_on:
				issues.append(f"DEADLOCK: {step.step_id} depende de si mesmo")
			for dep_id in step.depends_on:
				if dep_id not in steps_by_id:
					issues.append(f"DEPENDENCIA_AUSENTE: {step.step_id} depende de {dep_id}")
			if not step.model_id:
				issues.append(f"SEM_MODELO: {step.step_type} sem modelo definido")

		# Detecta ciclos de qualquer tamanho (A -> B -> C -> A), não apenas
		# dependências diretas. Um ciclo longo deixava o pipeline sem steps
		# prontos e só era percebido tarde, como plano travado.
		visit_state: dict[str, int] = {}
		path: list[str] = []
		cycles: set[tuple[str, ...]] = set()

		def _visit(step_id: str) -> None:
			state = visit_state.get(step_id, 0)
			if state == 1:
				if step_id in path:
					cycle = tuple(path[path.index(step_id):] + [step_id])
					cycles.add(cycle)
				return
			if state == 2 or step_id not in steps_by_id:
				return
			visit_state[step_id] = 1
			path.append(step_id)
			for dependency in steps_by_id[step_id].depends_on:
				_visit(dependency)
			path.pop()
			visit_state[step_id] = 2

		for step_id in steps_by_id:
			_visit(step_id)
		for cycle in sorted(cycles):
			issues.append(f"CICLO: {' -> '.join(cycle)}")

		if issues:
			_LOGGER.warning("[SIMULATION] Falha na simulacao: %s", issues)
			fixed_query = (
				f"{user_query}\n\n"
				f"[CORRECOES PREVIAS - SIMULACAO]\n"
				f"{chr(10).join(f'- {i}' for i in issues)}\n"
				f"Corrija o plano para evitar os problemas acima."
			)
			return self._run_sync(fixed_query)
		_LOGGER.info("[SIMULATION] Simulacao OK. Executando...")
		return self._run_sync(user_query)

	# --- Estado: ENSEMBLE_VERIFY ---
	def ensemble_verify(self, user_query: str, failed_step_type: str) -> OrchestrationResult:
		"""
		v2.0 (2026): Para steps criticos, consulta 2 modelos e usa consenso.
		Reduz alucinacoes quando um unico modelo erra.
		"""
		_LOGGER.info("[ENSEMBLE] Verificando %s com multi-modelo...", failed_step_type)
		from ..gui.settings_panel import get_llm_model, get_llm_provider
		from ..ai.model_registry import resolve_provider_tier_model
		provider = get_llm_provider()
		configured = get_llm_model()
		models = [
			resolve_provider_tier_model(provider, "light", configured),
			resolve_provider_tier_model(provider, "heavy", configured),
		]
		prompt = (
			f"Tarefa: {user_query}\n\n"
			f"Voce e um verificador critico. Gere APENAS o step '{failed_step_type}'. "
			f"Seja extremamente rigoroso com sintaxe NVDA."
		)

		def _ask_model(model_id: str) -> tuple[str, str]:
			try:
				from ..ai.llm_factory import create_llm_client
				client = create_llm_client(model_id=model_id)
				resp = client.chat(prompt)
				content = resp.content or ""
				_LOGGER.info("[ENSEMBLE] %s respondeu (%d chars)", model_id, len(content))
				return model_id, content
			except Exception as exc:
				_LOGGER.warning("[ENSEMBLE] %s falhou: %s", model_id, exc)
				return model_id, ""

		# As duas respostas são independentes. Consultá-las em paralelo reduz
		# latência e transforma o ensemble em uma comparação real de modelos,
		# sem compartilhar histórico entre os candidatos.
		with ThreadPoolExecutor(max_workers=len(models)) as pool:
			candidate_pairs = list(pool.map(_ask_model, models))
		results = [content for _model_id, content in candidate_pairs if content]

		verified_content: str | None = None

		if len(results) >= 2:
			# 2026-08-26: arbitro exige JSON estrito (escolher "first"/"second"),
			# mas usava models[0] -- um dos 2 candidatos do proprio ensemble, tier
			# light do provider ativo. No Ollama (default), nenhum modelo da conta
			# segue json_schema de verdade (auditoria ao vivo, ver model_registry.py::
			# get_structured_output_model()); json.loads(resp.content or "{}") abaixo
			# ficava sujeito a receber prosa/markdown em vez de JSON puro.
			from ..ai.llm_factory import call_with_structured_output

			_LOGGER.info("[ENSEMBLE] Consultando arbitro semantico leve...")
			try:
				arb_prompt = (
					f"Avalie semanticamente qual resposta cumpre melhor a tarefa, a API do "
					f"NVDA e a seguranca. Nao use semelhanca textual como criterio.\n\n"
					f"Tarefa:\n{user_query}\n\n"
					f"Primeira resposta:\n{results[0][:2000]}\n\n"
					f"Segunda resposta:\n{results[1][:2000]}"
				)
				resp = call_with_structured_output(arb_prompt, {
					"type": "json_schema",
					"json_schema": {
						"name": "ensemble_choice",
						"strict": True,
						"schema": {
							"type": "object",
							"properties": {"choice": {"type": "string", "enum": ["first", "second"]}},
							"required": ["choice"],
							"additionalProperties": False,
						},
					},
				})
				choice = json.loads(resp.content or "{}").get("choice")
				if choice in {"first", "second"}:
					verified_content = results[0] if choice == "first" else results[1]
					_LOGGER.info("[ENSEMBLE] Arbitro escolheu: %s", choice)
			except Exception as exc:
				_LOGGER.warning("[ENSEMBLE] Arbitro falhou: %s. Fallback.", exc)
		elif len(results) == 1:
			verified_content = results[0]

		if verified_content:
			enhanced = (
				f"{user_query}\n\n"
				f"[RESULTADO VERIFICADO POR CONSENSO MULTI-MODELO PARA '{failed_step_type}']\n"
				f"{verified_content}\n"
				f"Use este resultado verificado como base para o step '{failed_step_type}'; "
				f"ajuste apenas o necessario para integrar com o restante do addon."
			)
			return self._run_sync(enhanced)
		return self._run_sync(user_query)

	# --- Estado: SELF_PLAY_ADVERSARIAL ---
	def self_play_adversarial(self, user_query: str) -> OrchestrationResult:
		"""
		v2.0 (2026): Gera cenarios adversos para testar robustez do addon.
		Ex: chave API invalida, network timeout, formato inesperado.
		"""
		_LOGGER.info("[ADVERSARIAL] Gerando cenarios adversos...")
		adversarial_hints = [
			"O addon DEVE tratar excecao se a API retornar 401 (chave invalida).",
			"O addon DEVE usar timeout de 5s em todas as requisicoes HTTP.",
			"O addon DEVE verificar se o arquivo existe antes de abrir.",
			"O addon NAO deve travar se o usuario cancelar o dialogo.",
		]
		# Todos os cenários entram na mesma rodada. A seleção por hash fazia
		# cada pedido testar apenas um risco e tornava a cobertura instável.
		hints = "\n".join(f"- {hint}" for hint in adversarial_hints)
		enhanced = (
			f"{user_query}\n\n"
			f"[CENARIOS ADVERSARIOS]\n{hints}\n"
			f"Implemente tratamento robusto e testes para todos esses cenarios."
		)
		return self._run_sync(enhanced)

	# --- Estado: TOOL_CREATION ---
	def tool_creation(self, user_query: str, missing_capability: str) -> OrchestrationResult:
		"""
		v2.0 (2026): Gera ferramenta Python temporaria para capacidade ausente.
		Ex: 'preciso de parser de Markdown', 'preciso de validador de CPF'.
		"""
		_LOGGER.info("[TOOL_CREATE] Criando ferramenta para: %s", missing_capability)
		tool_prompt = (
			f"Crie uma funcao Python utilitaria para: {missing_capability}\n\n"
			f"Requisitos:\n"
			f"- Pura Python (sem dependencias externas)\n"
			f"- Tipagem strict\n"
			f"- Docstring em portugues\n"
			f"- Tratamento de erros explicito\n"
			f"- Nome: _tool_{missing_capability[:20].replace(' ', '_')}"
		)
		try:
			import ast

			from ..ai.llm_factory import create_llm_client
			from ..gui.settings_panel import get_llm_provider, get_llm_model
			from ..ai.model_registry import resolve_provider_tier_model
			provider = get_llm_provider()
			model = get_llm_model()
			model = resolve_provider_tier_model(provider, "heavy", model)
			client = create_llm_client(model_id=model)
			resp = client.chat(tool_prompt)
			generated = resp.content.strip()
			if generated.startswith("```"):
				generated = generated.strip("`")
				if generated.startswith("python"):
					generated = generated[6:].lstrip()
			ast.parse(generated)
			enhanced = (
				f"{user_query}\n\n"
				f"[CAPACIDADE AUXILIAR VALIDADA]\n{generated}\n"
				f"Integre esta capacidade ao addon e valide importacao, execucao e testes."
			)
			return self._run_sync(enhanced)
		except Exception as exc:
			_LOGGER.warning("[TOOL_CREATE] Falha: %s. Fallback.", exc)
		return self._run_sync(user_query)

	# --- Estado: FORCED_NOVEL ---
	def forced_novel(self, user_query: str) -> OrchestrationResult:
		"""
		Forca abordagem completamente nova: complexity diferente, modelos invertidos.
		"""
		_LOGGER.info("[FORCED_NOVEL] Aplicando abordagem anti-oscilacao.")
		inverted_query = (
			f"{user_query}\n\n"
			f"INSTRUCAO CRITICA: Use a abordagem OPOSTA da tentativa anterior. "
			f"Se usou poucos arquivos, agora use MAIS arquivos com separacao de camadas. "
			f"Se usou muitos arquivos, agora use MENOS e mais simples. "
			f"Varie a arquitetura."
		)
		return self._run_sync(inverted_query)

	# --- Estado: DIAGNOSE_GIVE_UP (nao e desistencia — e diagnostico) ---
	def diagnose_give_up(self, user_query: str, history: list[AutonomousState]) -> OrchestrationResult:
		"""
		Todas as estrategias esgotadas. Gera diagnostico rico e alternativas.
		"""
		_LOGGER.info("[DIAGNOSE] Todas as estrategias esgotadas. Gerando diagnostico.")

		strategies_tried = ", ".join(s.name for s in _AVAILABLE_STRATEGIES if s.state in history)
		diagnosis = (
			f"Diagnostico do NVDAStudio:\n\n"
			f"Todas as estrategias disponiveis foram tentadas: {strategies_tried}.\n"
			f"O pedido pode estar fora do escopo atual do sistema, ou requer "
			f"conhecimento/infraestrutura nao disponivel.\n\n"
			f"Alternativas sugeridas:\n"
			f"1. Reformule com mais detalhes tecnicos (ex: 'use threading para download').\n"
			f"2. Divida em pedidos menores (ex: primeiro crie apenas o SettingsPanel).\n"
			f"3. Verifique se a API/biblioteca mencionada e compativel com NVDA.\n"
			f"4. Consulte a documentacao do NVDA para verificar limites."
		)

		return OrchestrationResult(
			plan_id="diag", query=user_query, step_results=[],
			final_output=diagnosis, success=False,
			error="Todas as estrategias autonomas esgotadas. Diagnostico gerado.",
		)

# ---------------------------------------------------------------------------
# StateGraph — Grafo declarativo de transicoes de estados (LangGraph-inspired)
# ---------------------------------------------------------------------------

@dataclass
class StateNode:
	"""No do grafo de estados. Encapsula handler e metadados do estado."""
	state: AutonomousState
	handler: Callable  # (executor, user_query, prev_result) -> OrchestrationResult
	description: str = ""
	# Arestas condicionais: list de (condicao, estado_destino)
	# usadas para bifurcacao explicita baseada no contexto do resultado.
	edges: list[tuple[Callable, AutonomousState]] = field(default_factory=list)


class StateGraph:
	"""
	Grafo de estados leve para o AgenticLoop.

	Inspiracao: LangGraph (2024). Permite definir:
	  - Nos: cada estado da FSM com seu handler associado
	  - Arestas condicionais: bifurcacao baseada em condicao do resultado
	  - Dispatch declarativo: sem if/elif; rotas por dicionario de nos

	Vantagens sobre if/elif sequencial:
	  - O grafo e inspecionavel (nodes, edges) para debugging
	  - Adicionar um estado = adicionar um no, sem tocar no loop
	  - Arestas condicionais permitem bifurcacoes mais ricas sem aninhamento

	Uso:
	  graph.add_node(StateNode(state=S, handler=fn, description="..."))
	  graph.add_edge(from_state=S, condition=cond_fn, to_state=T)
	  result = graph.dispatch(state, executor, user_query, prev_result)
	"""

	def __init__(self):
		self._nodes: dict[AutonomousState, StateNode] = {}

	def add_node(self, node: StateNode) -> "StateGraph":
		"""Adiciona um no ao grafo. Retorna self para encadeamento fluente."""
		self._nodes[node.state] = node
		return self

	def add_edge(
		self,
		from_state: AutonomousState,
		condition: Callable[[Any], bool],
		to_state: AutonomousState,
	) -> "StateGraph":
		"""Adiciona aresta condicional: se condition(prev_result) -> vai para to_state."""
		if from_state in self._nodes:
			self._nodes[from_state].edges.append((condition, to_state))
		return self

	def dispatch(
		self,
		state: AutonomousState,
		executor: "StrategyExecutor",
		user_query: str,
		prev_result: "OrchestrationResult | None",
	) -> "OrchestrationResult":
		"""
		Executa o handler do no correspondente ao estado.
		Se o estado nao estiver no grafo, faz fallback para EXECUTE_NORMAL.
		"""
		node = self._nodes.get(state)
		if node is None:
			_LOGGER.warning("[StateGraph] Estado %s nao registrado. Fallback para EXECUTE_NORMAL.", state.name)
			return executor.execute_normal(user_query)
		_LOGGER.debug("[StateGraph] Dispatching estado %s: %s", state.name, node.description)
		return node.handler(executor, user_query, prev_result)

	def nodes(self) -> list[AutonomousState]:
		"""Lista todos os estados registrados no grafo."""
		return list(self._nodes.keys())

	def edges(self) -> list[tuple[AutonomousState, AutonomousState]]:
		"""Lista todas as arestas condicionais como tuplas (from, to)."""
		result = []
		for state, node in self._nodes.items():
			for _, to_state in node.edges:
				result.append((state, to_state))
		return result


# ---------------------------------------------------------------------------
# Factory: constroi e retorna o grafo de estados padrao do AgenticLoop
# ---------------------------------------------------------------------------

def _build_state_graph() -> StateGraph:
	"""
	Constroi o StateGraph com todos os nos/handlers do AgenticLoop.

	Cada handler tem assinatura:
	  (executor: StrategyExecutor, user_query: str, prev: OrchestrationResult|None)
	  -> OrchestrationResult
	"""
	graph = StateGraph()

	graph.add_node(StateNode(
		state=AutonomousState.EXECUTE_NORMAL,
		description="Execucao padrao do pipeline",
		handler=lambda ex, q, _prev: ex.execute_normal(q),
	))
	graph.add_node(StateNode(
		state=AutonomousState.RETRY_SAME,
		description="Reexecuta com issues anteriores injetados no contexto",
		handler=lambda ex, q, prev: ex.retry_same(q, prev.all_issues if prev else []),
	))
	graph.add_node(StateNode(
		state=AutonomousState.SWAP_MODEL,
		description="Troca o modelo do step critico que falhou",
		handler=_handler_swap_model,
	))
	graph.add_node(StateNode(
		state=AutonomousState.SURGICAL_REPLAN,
		description="Replaneja apenas a sub-arvore do step que quebrou",
		handler=_handler_surgical_replan,
	))
	graph.add_node(StateNode(
		state=AutonomousState.FULL_REPLAN,
		description="Replaneja tudo com nova estrategia",
		handler=lambda ex, q, _prev: ex.full_replan(q, "previous"),
	))
	graph.add_node(StateNode(
		state=AutonomousState.CONSULT_MEMORY,
		description="Consulta sessoes similares para enriquecer o contexto",
		handler=lambda ex, q, _prev: ex.consult_memory(q),
	))
	graph.add_node(StateNode(
		state=AutonomousState.FORCED_NOVEL,
		description="Forca abordagem completamente diferente (anti-oscilacao)",
		handler=lambda ex, q, _prev: ex.forced_novel(q),
	))
	graph.add_node(StateNode(
		state=AutonomousState.DECOMPOSE_GOAL,
		description="Divide o addon em micro-tarefas menores",
		handler=lambda ex, q, _prev: ex.decompose_goal(q),
	))
	graph.add_node(StateNode(
		state=AutonomousState.ASK_USER_HINT,
		description="Pausa e pede dica ao usuario",
		handler=_handler_ask_user_hint,
	))
	graph.add_node(StateNode(
		state=AutonomousState.MENTAL_SIMULATION,
		description="Simula o plano antes de executar (detecta deadlocks)",
		handler=lambda ex, q, _prev: ex.mental_simulation(q, None),
	))
	graph.add_node(StateNode(
		state=AutonomousState.ENSEMBLE_VERIFY,
		description="Verifica step critico com multi-modelo",
		handler=_handler_ensemble_verify,
	))
	graph.add_node(StateNode(
		state=AutonomousState.SELF_PLAY_ADVERSARIAL,
		description="Gera cenarios adversos para testar robustez",
		handler=lambda ex, q, _prev: ex.self_play_adversarial(q),
	))
	graph.add_node(StateNode(
		state=AutonomousState.TOOL_CREATION,
		description="Gera ferramenta Python sob demanda para capacidade ausente",
		handler=_handler_tool_creation,
	))
	graph.add_node(StateNode(
		state=AutonomousState.DIAGNOSE_GIVE_UP,
		description="Todas as estrategias esgotadas: gera diagnostico rico",
		handler=lambda ex, q, _prev: ex.diagnose_give_up(q, []),
	))

	return graph


# Handlers extraidos com assinatura uniforme para o StateGraph

def _handler_swap_model(
	executor: "StrategyExecutor",
	user_query: str,
	prev_result: "OrchestrationResult | None",
) -> "OrchestrationResult":
	"""Determina step/modelo que falhou e delega para swap_model."""
	failed_step = ""
	current_model = ""
	if prev_result:
		for r in reversed(prev_result.step_results):
			if not r.approved:
				failed_step = r.step_type
				current_model = r.model_used
				break
	return executor.swap_model(user_query, failed_step, current_model)


def _handler_surgical_replan(
	executor: "StrategyExecutor",
	user_query: str,
	prev_result: "OrchestrationResult | None",
) -> "OrchestrationResult":
	"""Determina o step_id que falhou e delega para surgical_replan."""
	failed_step_id = ""
	prev_step_results = prev_result.step_results if prev_result else []
	for r in reversed(prev_step_results):
		if not r.approved:
			failed_step_id = r.step_id
			break
	return executor.surgical_replan(user_query, failed_step_id, prev_step_results)


def _handler_ask_user_hint(
	executor: "StrategyExecutor",
	user_query: str,
	prev_result: "OrchestrationResult | None",
) -> "OrchestrationResult":
	"""Extrai stuck_reason do resultado anterior e delega para ask_user_hint."""
	stuck_reason = "estrategias esgotadas"
	if prev_result and prev_result.all_issues:
		stuck_reason = prev_result.all_issues[0][:80]
	return executor.ask_user_hint(user_query, stuck_reason)


def _handler_ensemble_verify(
	executor: "StrategyExecutor",
	user_query: str,
	prev_result: "OrchestrationResult | None",
) -> "OrchestrationResult":
	"""Determina o step critico que falhou e delega para ensemble_verify."""
	failed_step = ""
	if prev_result:
		for r in reversed(prev_result.step_results):
			if not r.approved and r.step_type in ("code_generation", "agent_runner"):
				failed_step = r.step_type
				break
	return executor.ensemble_verify(user_query, failed_step)


def _handler_tool_creation(
	executor: "StrategyExecutor",
	user_query: str,
	prev_result: "OrchestrationResult | None",
) -> "OrchestrationResult":
	"""Extrai capacidade ausente do resultado anterior e delega para tool_creation."""
	missing = ""
	if prev_result and prev_result.all_issues:
		missing = prev_result.all_issues[0][:40]
	return executor.tool_creation(user_query, missing)


# ---------------------------------------------------------------------------
# Agente autonomo principal
# ---------------------------------------------------------------------------

class AgenticLoop:
	"""
	Loop autonomo completo: nunca desiste enquanto houver estrategia nao tentada.
	"""

	def __init__(self, orchestrator):
		self._orch = orchestrator
		self._executor = StrategyExecutor(orchestrator)
		self._reflector = Reflector()
		self._strategy_usage: dict[AutonomousState, int] = {}
		self._state_history: list[AutonomousState] = []
		# StateGraph: grafo declarativo de transicoes (LangGraph-inspired)
		self._graph: StateGraph = _build_state_graph()
		_LOGGER.debug("[AgenticLoop] StateGraph construido com %d nos.", len(self._graph.nodes()))

	def run(self, user_query: str) -> OrchestrationResult:
		"""
		Executa o loop autonomo ate sucesso ou esgotamento de estrategias.

		Fluxo:
		  1. Estado inicial: EXECUTE_NORMAL
		  2. Executa estrategia
		  3. Reflete sobre resultado
		  4. Se success -> retorna
		  5. Se nao success -> transiciona para proximo estado
		  6. Repete ate esgotar estrategias
		"""
		current_state = AutonomousState.EXECUTE_NORMAL
		prev_result: OrchestrationResult | None = None
		loop_count = 0

		while True:
			loop_count += 1
			self._state_history.append(current_state)
			self._strategy_usage[current_state] = self._strategy_usage.get(current_state, 0) + 1

			_LOGGER.info(
				"[AGENTIC] Loop %d | Estado: %s | Estrategias usadas: %s",
				loop_count, current_state.name,
				{str(k.name): v for k, v in self._strategy_usage.items()},
			)

			# --- Executa estrategia ---
			result = self._execute_state(current_state, user_query, prev_result)
			loop_count += 1  # count the actual execution

			# --- Verifica sucesso ---
			if result.success:
				_LOGGER.info("[AGENTIC] Sucesso no estado %s apos %d loops.", current_state.name, loop_count)
				object.__setattr__(result, 'autonomous_loop_count', loop_count)
				# Meta-learning: registra sucesso deste estado para esta query
				self._reflector._record_success(user_query, current_state, score=100.0)
				return result

			# --- Reflete para decidir proximo estado ---
			reflection = self._reflector.reflect(prev_result, result, self._strategy_usage)
			self._reflector.record_state(current_state)

			_LOGGER.info(
				"[AGENTIC] Reflexao: progresso=%s oscilacao=%s | Sugerido: %s | Razao: %s",
				reflection.has_progress, reflection.is_oscillating,
				reflection.suggested_state.name, reflection.reason,
			)

			# --- Anti-loop: se sugerido == atual e nao ha progresso, forca novo ---
			next_state = reflection.suggested_state
			if next_state == current_state and not reflection.has_progress:
				_LOGGER.info("[AGENTIC] Estado repetido sem progresso. Forcando transicao.")
				next_state = self._force_alternative(current_state)

			# --- Verifica se proximo estado esgotou tentativas ---
			strategy = self._get_strategy(next_state)
			if strategy and self._strategy_usage.get(next_state, 0) >= strategy.max_attempts:
				_LOGGER.info("[AGENTIC] Estado %s esgotou %d tentativas. Proximo.", next_state.name, strategy.max_attempts)
				next_state = self._force_alternative(next_state)

			# --- Meta-learning: boost se query similar teve sucesso com outro estado ---
			boosted = self._reflector._meta_boost(user_query, [s.state for s in _AVAILABLE_STRATEGIES if s.state != next_state])
			if boosted and boosted != next_state and not reflection.has_progress:
				_LOGGER.info("[AGENTIC] Meta-learning boost: %s teve sucesso em queries similares.", boosted.name)
				next_state = boosted

			# --- Verifica orcamento de custo/iteracoes ---
			# Achado de auditoria 2026-08-04: iteration_budget.can_continue()
			# existia e era funcional, mas nada aqui o consultava -- a FSM podia
			# encadear ~15-20 reexecucoes completas do pipeline (cada estrategia
			# ate max_attempts) sem nunca checar quanto ja foi gasto. Um budget
			# rastreado mas nunca aplicado e pior que nenhum budget: passa a
			# falsa impressao de que existe um teto. Verificado ANTES do check
			# de DIAGNOSE_GIVE_UP abaixo para que o motivo fique claro nos logs
			# e no diagnostico final (usa o mesmo caminho de saida).
			can_continue, budget_reason = iteration_budget.can_continue()
			if not can_continue and next_state != AutonomousState.DIAGNOSE_GIVE_UP:
				_LOGGER.warning(
					"[AGENTIC] Orcamento excedido (%s). Encerrando com diagnostico "
					"em vez de tentar %s.", budget_reason, next_state.name,
				)
				next_state = AutonomousState.DIAGNOSE_GIVE_UP

			# --- Verifica se TODAS estrategias esgotadas ---
			if next_state == AutonomousState.DIAGNOSE_GIVE_UP:
				_LOGGER.warning("[AGENTIC] Todas as estrategias esgotadas.")
				final = self._executor.diagnose_give_up(user_query, self._state_history)
				object.__setattr__(final, 'autonomous_loop_count', loop_count)
				return final

			# --- Delay entre tentativas ---
			if not reflection.has_progress:
				time.sleep(2)

			prev_result = result
			current_state = next_state

	def _execute_state(self, state: AutonomousState, user_query: str, prev_result: OrchestrationResult | None) -> OrchestrationResult:
		"""
		Despacha o estado atual para o handler correspondente via StateGraph.

		v2.2.0: Substituicao do grande if/elif por um grafo de estados declarativo.
		Cada estado e um no registrado em self._graph com handler e metadados.
		Permite inspecao do grafo (self._graph.nodes(), .edges()) para debugging.
		"""
		# Caso especial: DIAGNOSE_GIVE_UP precisa do historico de estados
		if state == AutonomousState.DIAGNOSE_GIVE_UP:
			return self._executor.diagnose_give_up(user_query, self._state_history)

		return self._graph.dispatch(state, self._executor, user_query, prev_result)

	@staticmethod
	def _get_strategy(state: AutonomousState) -> Strategy | None:
		for s in _AVAILABLE_STRATEGIES:
			if s.state == state:
				return s
		return None

	def _force_alternative(self, blocked_state: AutonomousState) -> AutonomousState:
		"""Forca transicao para proxima estrategia disponivel."""
		for s in _AVAILABLE_STRATEGIES:
			if s.state != blocked_state and self._strategy_usage.get(s.state, 0) < s.max_attempts:
				return s.state
		return AutonomousState.DIAGNOSE_GIVE_UP
