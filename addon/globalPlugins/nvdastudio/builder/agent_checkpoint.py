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
	cost_usd: float = 0.0
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


# Economia de contexto num build longo: o conteudo de uma ferramenta (leitura
# de arquivo, saida de teste) fica preso no historico do cliente pra sempre e,
# sem estado no servidor (Gemini e o unico que tem via previous_interaction_id
# -- nunca guarda tool_result em _history, entao nunca aparece aqui), volta a
# ser reenviado por completo a cada turno seguinte. Encolher o TEXTO de
# resultados antigos -- nunca a entrada em si -- preserva a estrutura (role,
# ids) que cada provedor exige pra casar tool_call com tool_result; nenhuma
# entrada e removida, so o campo de conteudo de unidades fora da janela
# recente.
_TRIM_MARKER = "[conteúdo de ferramenta de um turno anterior omitido para economizar contexto -- use a ferramenta de novo se precisar dele]"


def _trim_text(text: str, max_chars: int) -> str:
	if not isinstance(text, str) or len(text) <= max_chars:
		return text
	return _TRIM_MARKER


def _is_tool_unit(entry: dict[str, Any]) -> bool:
	role = entry.get("role")
	if role in ("tool", "tool_result"):
		return True
	if role == "user" and isinstance(entry.get("content"), list):
		return any(isinstance(b, dict) and b.get("type") == "tool_result" for b in entry["content"])
	return False


def _shrink_unit(entry: dict[str, Any], max_chars: int) -> dict[str, Any]:
	role = entry.get("role")
	if role in ("tool", "tool_result"):
		shrunk = dict(entry)
		shrunk["content"] = _trim_text(entry.get("content", ""), max_chars)
		return shrunk
	if role == "user" and isinstance(entry.get("content"), list):
		new_content = [
			{**block, "content": _trim_text(block.get("content", ""), max_chars)}
			if isinstance(block, dict) and block.get("type") == "tool_result"
			else block
			for block in entry["content"]
		]
		return {**entry, "content": new_content}
	return entry


def trim_tool_history(
	history: list[dict[str, Any]], *, keep_recent: int = 6, max_chars: int = 800,
) -> list[dict[str, Any]]:
	"""Encolhe o texto de resultados de ferramenta antigos, preservando a
	estrutura e a posição de cada entrada. Nunca remove nem reordena nada --
	os provedores exigem casar cada tool_call com o tool_result seguinte na
	MESMA posição relativa; encolher só o campo de texto nunca quebra isso.
	Idempotente: reaplicar sobre um histórico já encolhido não faz nada.
	"""
	positions = [i for i, entry in enumerate(history) if _is_tool_unit(entry)]
	protected = set(positions[-keep_recent:]) if keep_recent > 0 else set()
	return [
		_shrink_unit(entry, max_chars) if i in positions and i not in protected else entry
		for i, entry in enumerate(history)
	]
