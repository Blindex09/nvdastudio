"""Persistência compacta do contexto factual de uma execução."""

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from ..utils.logger import get_logger

_logger = get_logger("execution_context")
_MAX_OUTPUT_CHARS = 12000


class ExecutionContextStore:
	"""Guarda resultados por step para retries e retomadas da execução."""

	def __init__(self, base_dir: str | None = None) -> None:
		self._base_dir = Path(base_dir) if base_dir else (
			Path.home() / "AppData" / "Roaming" / "NVDAStudio" / "execution_context"
		)
		self._base_dir.mkdir(parents=True, exist_ok=True)
		self._lock = threading.RLock()

	def _path(self, plan_id: str) -> Path:
		safe_id = "".join(ch for ch in plan_id if ch.isalnum() or ch in "-_")[:80] or "unknown"
		return self._base_dir / f"{safe_id}.json"

	def save_step(self, plan: Any, step: Any, result: Any) -> None:
		"""Salva plano mínimo, resultado, issues e output truncado atomically."""
		with self._lock:
			path = self._path(str(plan.plan_id))
			data = self._read(path)
			data.update({
				"plan_id": plan.plan_id,
				"query": plan.original_query,
				"addon_name": plan.addon_name,
				"project_type": plan.project_type,
			})
			steps = data.setdefault("steps", {})
			steps[step.step_id] = {
				"step_type": step.step_type,
				"description": step.description,
				"approved": bool(result.approved),
				"score": result.score,
				"issues": list(result.issues or [])[-10:],
				"output": str(result.output or "")[-_MAX_OUTPUT_CHARS:],
			}
			self._write(path, data)

	def get_context(self, plan_id: str, step_ids: list[str], max_chars: int = 16000) -> str:
		"""Recupera somente os steps pedidos, respeitando limite de contexto."""
		with self._lock:
			data = self._read(self._path(plan_id))
			steps = data.get("steps", {})
			parts: list[str] = []
			remaining = max_chars
			for step_id in step_ids:
				item = steps.get(step_id)
				if not item or remaining <= 0:
					continue
				text = (
					f"[{step_id} | {item.get('step_type', '')} | aprovado={item.get('approved', False)}]\n"
					f"Saída:\n{item.get('output', '')}\n"
					f"Issues: {'; '.join(item.get('issues', []))}"
				)
				text = text[:remaining]
				parts.append(text)
				remaining -= len(text)
			return "\n\n".join(parts)

	@staticmethod
	def _read(path: Path) -> dict[str, Any]:
		try:
			with path.open(encoding="utf-8") as fh:
				value = json.load(fh)
			return value if isinstance(value, dict) else {}
		except (OSError, json.JSONDecodeError):
			return {}

	@staticmethod
	def _write(path: Path, data: dict[str, Any]) -> None:
		fd, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
		try:
			with os.fdopen(fd, "w", encoding="utf-8") as fh:
				json.dump(data, fh, ensure_ascii=False, indent=2)
			os.replace(temp_name, path)
		except Exception:
			try:
				os.unlink(temp_name)
			except OSError:
				pass
			raise


execution_context_store = ExecutionContextStore()
