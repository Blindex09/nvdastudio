"""Orquestra o unico pipeline de geracao do NVDAStudio: o agente com tools."""

import json
import threading
from typing import Callable

from ..ai.model_registry import resetar_saida_estruturada
from ..builder.addon_builder import load_artifact_blocks
from ..tool_system.approval import ApprovalWorkflow
from ..utils.logger import get_logger
from .orch_types import OrchestrationResult, StepResult

MODULE_VERSION = "7.0.0"
_logger = get_logger("orchestrator")

_AGENTIC_CORRECTION_ROUNDS = 2
STEP_CODE_GENERATION = "code_generation"

ProgressCallback = Callable[[str, str], None]


def _agentic_files_to_blocks(workdir: str, files: list[str]) -> str:
	"""Serializa os artefatos reais no formato que a entrega da GUI consome."""
	return "\n\n".join(
		f"```{block['language']}:{block['filename']}\n{block['code']}\n```"
		for block in load_artifact_blocks(workdir, files)
	)


def _get_agentic_routes(request: str = ""):
	"""Monta a rota manual ou o ranking cross-provider do modo Studio."""
	try:
		from ..ai.model_router import extract_required_capabilities, select_routes
		from ..gui.settings_panel import (
			get_llm_model,
			get_llm_provider,
			get_studio_available_providers,
		)

		provider = get_llm_provider()
		configured_model = get_llm_model()
		required = frozenset({"tool_use"}) | extract_required_capabilities(request)
		return select_routes(
			provider, STEP_CODE_GENERATION, configured_model,
			request=request,
			available_providers=(
				get_studio_available_providers() if provider == "studio" else None
			),
			required_capabilities=required,
		)
	except Exception as exc:
		_logger.warning("[AGENTIC] falha ao resolver rota configurada: %s", exc)
		return []


class Orchestrator:
	"""Coordena execucao, interrupcao, redirecionamento e entrega do agente."""

	def __init__(self):
		self._on_progress: ProgressCallback | None = None
		self._on_complete: Callable[[OrchestrationResult], None] | None = None
		self._running = False
		self._cancel_requested = False
		self._agentic_cancel = threading.Event()
		self._steer_lock = threading.Lock()
		self._pending_steer = ""
		self._last_result: OrchestrationResult | None = None
		self._agentic_workdir: str | None = None
		self._package_requested = False
		self._suppress_complete_callback = False
		self._approval_workflow = ApprovalWorkflow()

	def initialize(self) -> None:
		_logger.info("[OK] Orchestrator v%s inicializado.", MODULE_VERSION)

	def set_callbacks(
		self,
		on_progress: ProgressCallback,
		on_complete: Callable[[OrchestrationResult], None],
	) -> None:
		self._on_progress = on_progress
		self._on_complete = on_complete

	def cancel_pipeline(self) -> None:
		_logger.info("[CANCEL] Solicitacao de cancelamento recebida.")
		self._cancel_requested = True
		self._agentic_cancel.set()

	def steer_pipeline(self, text: str) -> None:
		if not text or not text.strip():
			return
		with self._steer_lock:
			self._pending_steer = (self._pending_steer + "\n" + text.strip()).strip()
		_logger.info("[STEER] ajuste do usuario enfileirado para a sessao ativa.")

	def _drain_steer(self) -> str:
		with self._steer_lock:
			text, self._pending_steer = self._pending_steer, ""
		return text

	def run_async(
		self,
		user_query: str,
		*,
		workdir: str | None = None,
		package_requested: bool = False,
	) -> None:
		if self._running:
			_logger.warning("[AVISO] Orchestrator ja esta rodando.")
			return
		self._agentic_workdir = workdir
		self._package_requested = package_requested
		self._cancel_requested = False
		self._agentic_cancel.clear()
		self._drain_steer()
		self._running = True
		resetar_saida_estruturada()
		threading.Thread(
			target=self._run_async_worker,
			args=(user_query,),
			daemon=True,
		).start()

	def _run_async_worker(self, user_query: str) -> None:
		try:
			self._run_until_complete(user_query)
		finally:
			self._running = False

	def _run_until_complete(self, user_query: str) -> OrchestrationResult:
		self._last_result = None
		self._suppress_complete_callback = True
		try:
			self._run_agent(user_query)
			result = self._last_result
			if result is None:
				result = self._failure_result(user_query, "O agente nao conseguiu gerar o addon.")
		finally:
			self._suppress_complete_callback = False
		self._last_result = result
		if self._on_complete:
			self._on_complete(result)
		return result

	def _emit(self, event: str, detail: str = "") -> None:
		_logger.info("[PROGRESS] %s: %s", event, detail)
		if self._on_progress:
			self._on_progress(event, detail)

	@staticmethod
	def _failure_result(query: str, error: str) -> OrchestrationResult:
		return OrchestrationResult(
			plan_id="agentic",
			query=query,
			step_results=[],
			final_output="",
			success=False,
			error=error,
		)

	def _finish(self, result: OrchestrationResult) -> None:
		self._last_result = result
		if self._on_complete and not self._suppress_complete_callback:
			self._on_complete(result)

	def _run_agent(self, user_query: str) -> None:
		from ..builder.agent_evaluation import evaluate_agent_run
		from ..builder.agentic_driver import run_agentic_build, run_provider_agentic_build

		self._emit("PLANEJANDO")
		self._emit("EXECUTANDO", STEP_CODE_GENERATION)
		routes = _get_agentic_routes(user_query)
		if not routes:
			self._finish(self._failure_result(
				user_query,
				"O Studio não encontrou um provedor configurado e compatível.",
			))
			return

		from ..ai.model_router import record_provider_outcome
		build = None
		provider = model = ""
		route_trace: list[dict] = []
		total_tokens = 0
		active_workdir = self._agentic_workdir
		attempt_request = user_query
		for index, route in enumerate(routes):
			provider, model = route.provider, route.model_id
			route_event = route.to_dict()
			route_event["attempt"] = index + 1
			route_trace.append(route_event)
			_logger.info("[ROUTING] %s", json.dumps(route_event, ensure_ascii=False))
			automatic = "manualmente" not in route.reason
			self._emit(
				"ROTEANDO",
				(
					f"Studio selecionou {provider}, modelo {model}: {route.reason}."
					if automatic else f"Usando {provider}, modelo {model}."
				),
			)
			common = dict(
				model_id=model,
				correction_rounds=_AGENTIC_CORRECTION_ROUNDS,
				use_nvda_context=True,
				progress_callback=lambda line: self._emit("EXECUTANDO", line),
				cancel_event=self._agentic_cancel,
				steer_provider=self._drain_steer,
				permission_callback=self._agent_permission_callback,
				ask_user_callback=self._agent_ask_user,
				workdir=active_workdir,
			)
			try:
				if provider == "factory":
					build = run_agentic_build(attempt_request, **common)
				else:
					build = run_provider_agentic_build(
						attempt_request, provider=provider, **common,
					)
			except Exception as exc:
				_logger.exception("[AGENTIC] rota %s falhou", provider)
				record_provider_outcome(provider, False, str(exc))
				route_event["success"] = False
				route_event["error"] = str(exc)[:500]
				if index + 1 < len(routes):
					self._emit("ROTEANDO", "O provedor falhou; o Studio tentará a próxima rota compatível.")
					continue
				self._finish(self._failure_result(user_query, str(exc)))
				return

			total_tokens += int(getattr(build, "tokens", 0))
			route_event["success"] = bool(build.success and build.execution_ok)
			route_event["error"] = str(getattr(build, "error", ""))[:500]
			record_provider_outcome(
				provider, bool(build.files), str(getattr(build, "error", "")),
			)
			_logger.info(
				"[ROUTING_OUTCOME] %s",
				json.dumps(route_event, ensure_ascii=False),
			)
			if getattr(build, "cancelled", False) or (build.success and build.execution_ok):
				break
			if index + 1 < len(routes):
				active_workdir = build.workdir
				report = getattr(build, "gate_report", "") or getattr(build, "error", "")
				attempt_request = (
					user_query
					+ "\n\nUma rota anterior deixou arquivos neste workspace. Preserve o que "
					"estiver correto, examine o estado atual e corrija estes problemas:\n"
					+ str(report)[:6000]
				)
				self._emit(
					"ROTEANDO",
					"A primeira rota não concluiu a validação; o Studio preservará os arquivos e tentará outra.",
				)

		if build is None:
			self._finish(self._failure_result(user_query, "Nenhuma rota do Studio pôde ser executada."))
			return
		build.tokens = total_tokens

		try:
			from ..ai.model_router import extract_task_complexity
			from ..memory.session_memory import memory

			evaluation = evaluate_agent_run(build)
			build.evaluation = evaluation.to_dict()
			memory.log_step_metric(
				"agent_runner",
				bool(build.success),
				retries=max(0, int(getattr(build, "rounds", 1)) - 1),
				tokens=int(getattr(build, "tokens", 0)),
				complexity_level=extract_task_complexity(user_query),
				model_id=model,
				provider=provider,
				trajectory=evaluation.trajectory,
			)
			_logger.info(
				"[AGENT-EVAL] score=%d passed=%s issues=%s",
				evaluation.score,
				evaluation.passed,
				", ".join(evaluation.issues) or "nenhum",
			)
		except Exception as exc:
			_logger.warning("[AGENT-EVAL] avaliacao indisponivel: %s", exc)

		if getattr(build, "cancelled", False):
			self._emit("CANCELADO")
			self._finish(self._failure_result(user_query, "Geracao interrompida pelo usuario."))
			return

		self._agentic_workdir = None
		if not build.files:
			error = (
				getattr(build, "error", "")
				or getattr(build, "stderr_tail", "")
				or "O agente nao produziu arquivos."
			)
			self._finish(self._failure_result(user_query, error))
			return

		blocks = _agentic_files_to_blocks(build.workdir, build.files)
		approved = bool(build.success and build.execution_ok)
		step = StepResult(
			step_id="agentic",
			step_type=STEP_CODE_GENERATION,
			output=blocks,
			approved=approved,
			score=100 if approved else 0,
			issues=[build.gate_report] if build.gate_report else [],
			model_used=f"{provider}::{model}",
		)
		result = OrchestrationResult(
			plan_id="agentic",
			query=user_query,
			step_results=[step],
			final_output=blocks,
			artifact_dir=build.workdir,
			artifact_files=list(build.files),
			package_requested=self._package_requested,
			success=approved,
			error=None if approved else (
				getattr(build, "gate_report", "")
				or getattr(build, "error", "")
				or "gate final reprovado"
			),
			completed_message="Arquivos do addon validados." if approved else "",
			total_retries=max(int(getattr(build, "rounds", 1)) - 1, 0),
			total_tokens=int(getattr(build, "tokens", 0)),
			routing_decisions=route_trace,
			selected_provider=provider,
			selected_model=model,
		)
		self._emit("MONTANDO")
		self._emit("CONCLUIDO")
		self._finish(result)

	def _agent_permission_callback(self, tool_name: str, arguments: dict) -> bool:
		from ..builder.agent_tools import canonical_permission_name
		from ..gui.studio_dialog import get_current_dialog

		tool_name = canonical_permission_name(tool_name)
		risk, reason, _ = self._approval_workflow.analyze_risk(tool_name, arguments)
		if risk == "critical":
			return False
		dialog = get_current_dialog()
		return bool(dialog and dialog.approve_tool(tool_name, arguments, reason=reason))

	@staticmethod
	def _agent_ask_user(questions: list[str]) -> list[str]:
		from ..gui.studio_dialog import get_current_dialog

		dialog = get_current_dialog()
		return dialog._ask_clarification_inline(questions) if dialog else []
