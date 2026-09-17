"""Checkpoints duráveis e traces reexecutáveis do loop agêntico."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

MODULE_VERSION = "1.0.0"
_SCHEMA_VERSION = 1
_MAX_RESUME_AGE_SECONDS = 7 * 24 * 60 * 60
_SECRET_RE = re.compile(
	r"(?i)(?:sk-[a-z0-9_-]{16,}|AIza[a-z0-9_-]{20,}|"
	r"((?:api[_ -]?key|token|authorization)\s*[:=]\s*)\S+)"
)


def _redact(value: Any) -> Any:
	if isinstance(value, str):
		return _SECRET_RE.sub(lambda match: (match.group(1) or "") + "[REDACTED]", value)
	if isinstance(value, list):
		return [_redact(item) for item in value]
	if isinstance(value, dict):
		return {key: _redact(item) for key, item in value.items()}
	return value


def _state_root() -> str:
	base = os.getenv("APPDATA") or tempfile.gettempdir()
	return os.path.join(base, "NVDAStudio", "agent-runs")


def request_fingerprint(request: str, provider: str, model_id: str) -> str:
	payload = f"{provider}\0{model_id}\0{request.strip()}".encode("utf-8", errors="replace")
	return hashlib.sha256(payload).hexdigest()


@dataclass
class AgentCheckpoint:
	run_id: str
	fingerprint: str
	provider: str
	model_id: str
	request: str
	workdir: str
	status: str = "running"
	turn: int = 0
	corrections: int = 0
	tokens: int = 0
	message: str = ""
	tool_results: list[dict[str, str]] | None = None
	client_history: list[dict[str, Any]] = field(default_factory=list)
	trace: list[dict[str, Any]] = field(default_factory=list)
	updated_at: float = field(default_factory=time.time)
	schema_version: int = _SCHEMA_VERSION

	def event(self, kind: str, **data: Any) -> None:
		self.trace.append({"seq": len(self.trace) + 1, "at": time.time(), "kind": kind, **data})
		# Evita crescimento ilimitado e mantém a trajetória mais recente.
		if len(self.trace) > 1000:
			self.trace = self.trace[-1000:]


class AgentCheckpointStore:
	def __init__(self, root: str | None = None):
		self.root = root or _state_root()

	def new(self, request: str, provider: str, model_id: str, workdir: str) -> AgentCheckpoint:
		return AgentCheckpoint(
			run_id=str(uuid.uuid4()),
			fingerprint=request_fingerprint(request, provider, model_id),
			provider=provider, model_id=model_id, request=request, workdir=workdir,
			message=request,
		)

	def path(self, run_id: str) -> str:
		return os.path.join(self.root, f"{run_id}.json")

	def save(self, state: AgentCheckpoint) -> None:
		os.makedirs(self.root, exist_ok=True)
		state.updated_at = time.time()
		fd, temporary = tempfile.mkstemp(prefix=".agent-state-", suffix=".json", dir=self.root)
		try:
			with os.fdopen(fd, "w", encoding="utf-8") as stream:
				json.dump(_redact(asdict(state)), stream, ensure_ascii=False, indent=2, default=str)
			os.replace(temporary, self.path(state.run_id))
			try:
				os.chmod(self.path(state.run_id), 0o600)
			except OSError:
				pass
		finally:
			if os.path.exists(temporary):
				os.remove(temporary)

	def load(self, path: str) -> AgentCheckpoint | None:
		try:
			with open(path, encoding="utf-8") as stream:
				data = json.load(stream)
			if data.get("schema_version") != _SCHEMA_VERSION:
				return None
			return AgentCheckpoint(**data)
		except (OSError, ValueError, TypeError):
			return None

	def find_resumable(self, request: str, provider: str, model_id: str) -> AgentCheckpoint | None:
		fingerprint = request_fingerprint(request, provider, model_id)
		try:
			paths = [os.path.join(self.root, name) for name in os.listdir(self.root) if name.endswith(".json")]
		except OSError:
			return None
		for path in sorted(paths, key=lambda item: os.path.getmtime(item), reverse=True):
			state = self.load(path)
			if (
				state is not None and state.fingerprint == fingerprint
				and state.status in {"running", "paused", "failed"}
				and time.time() - state.updated_at <= _MAX_RESUME_AGE_SECONDS
				and os.path.isdir(state.workdir)
			):
				return state
		return None


checkpoint_store = AgentCheckpointStore()


def export_client_history(client: object) -> list[dict[str, Any]]:
	history = getattr(client, "_history", [])
	if not isinstance(history, list):
		return []
	# JSON round-trip também remove objetos acidentais não serializáveis.
	try:
		return json.loads(json.dumps(history, ensure_ascii=False, default=str))
	except (TypeError, ValueError):
		return []


def restore_client_history(client: object, history: list[dict[str, Any]]) -> None:
	if isinstance(getattr(client, "_history", None), list) and isinstance(history, list):
		client._history = history  # type: ignore[attr-defined]
