"""Avaliação determinística de resultado, trajetória, ferramentas e estado."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any

MODULE_VERSION = "1.0.0"


@dataclass(frozen=True)
class AgentEvaluation:
	passed: bool
	score: int
	outcome_ok: bool
	trajectory_ok: bool
	tool_use_ok: bool
	checkpoint_ok: bool
	issues: tuple[str, ...]
	trajectory: str

	def to_dict(self) -> dict[str, Any]:
		return asdict(self)


def evaluate_agent_run(result: object) -> AgentEvaluation:
	"""Pontua fatos observáveis sem pedir ao mesmo modelo que se autoavalie."""
	trace = getattr(result, "trace", []) or []
	issues: list[str] = []
	outcome_ok = bool(getattr(result, "success", False) and getattr(result, "files", []))
	if not outcome_ok:
		issues.append("resultado final não aprovado ou sem arquivos")

	kinds = [str(event.get("kind", "")) for event in trace if isinstance(event, dict)]
	has_start = any(kind in {"run_started", "run_resumed"} for kind in kinds)
	has_finish = "run_finished" in kinds
	loop_detected = "loop_detected" in kinds
	trajectory_ok = has_start and has_finish and not loop_detected
	if not has_start or not has_finish:
		issues.append("trajetória incompleta")
	if loop_detected:
		issues.append("loop repetitivo detectado")

	tool_events = [event for event in trace if isinstance(event, dict) and event.get("kind") == "tool_result"]
	tool_use_ok = not any(event.get("success") is False for event in tool_events)
	if not tool_use_ok:
		issues.append("uma ou mais ferramentas falharam")

	checkpoint_ok = False
	checkpoint_path = str(getattr(result, "checkpoint_path", "") or "")
	if checkpoint_path and os.path.isfile(checkpoint_path):
		try:
			with open(checkpoint_path, encoding="utf-8") as stream:
				payload = json.load(stream)
			checkpoint_ok = payload.get("status") in {"completed", "failed", "cancelled"}
		except (OSError, ValueError, TypeError):
			checkpoint_ok = False
	if not checkpoint_ok:
		issues.append("checkpoint terminal ausente ou inválido")

	score = (40 if outcome_ok else 0) + (30 if trajectory_ok else 0) + (20 if tool_use_ok else 0) + (10 if checkpoint_ok else 0)
	trajectory = "loop_detected" if loop_detected else ("completed" if has_finish else "incomplete")
	return AgentEvaluation(
		passed=outcome_ok and trajectory_ok and tool_use_ok and checkpoint_ok and score >= 80,
		score=score, outcome_ok=outcome_ok, trajectory_ok=trajectory_ok,
		tool_use_ok=tool_use_ok, checkpoint_ok=checkpoint_ok,
		issues=tuple(issues), trajectory=trajectory,
	)
