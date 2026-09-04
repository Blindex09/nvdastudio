"""Editor seguro de arquivos do workspace do NVDA Studio."""

import difflib
import hashlib
import os
import tempfile
import threading
import uuid
from pathlib import Path

from ..registry import registry, tool_error, tool_result
from ...utils.logger import get_logger

_logger = get_logger("tool_system.file_editor")


def _default_workspace_root() -> Path:
	"""Raiz do workspace das ferramentas de arquivo -- a pasta de saida dos
	addons gerados, NUNCA a arvore de codigo do proprio NVDAStudio.

	Ate aqui era `Path(__file__).resolve().parents[5]`, que em producao aponta
	para a pasta `addons/` do NVDA (e em dev para a raiz do repo). Como o
	`file_editor` e oferecido ao LLM de geracao (code_generator.py) e a
	aprovacao e por caminho, aquele default deixava o LLM alcancar o codigo do
	proprio NVDAStudio e TODOS os addons instalados -- e ao mesmo tempo deixava
	o addon-alvo real (em addons_gerados/) FORA do workspace. Confinar na pasta
	de saida corrige as duas pontas.
	"""
	try:
		from ...gui.settings_panel import get_output_dir
		return Path(get_output_dir()).expanduser().resolve()
	except Exception:  # pragma: no cover - defesa (config do NVDA ausente)
		return (Path.home() / "Documents" / "NVDAStudio" / "addons_gerados").resolve()


_WORKSPACE_ROOT = _default_workspace_root()
_DESCRIPTION = "Edita arquivos reais do workspace com histórico e operações atômicas."
_HISTORY_LIMIT = 32
_HISTORY: dict[str, dict] = {}
_HISTORY_LOCK = threading.Lock()


def _resolve_workspace_file(path: str) -> Path:
	"""Resolve um caminho e rejeita traversal/symlink fora do workspace."""
	if not isinstance(path, str) or not path.strip():
		raise ValueError("path deve ser um caminho não vazio")
	target = Path(path).expanduser().resolve(strict=False)
	try:
		target.relative_to(_WORKSPACE_ROOT.resolve())
	except ValueError as exc:
		raise ValueError("o arquivo precisa estar dentro do workspace do NVDA Studio") from exc
	return target


def _sha256(path: Path) -> str:
	hasher = hashlib.sha256()
	with path.open("rb") as stream:
		for chunk in iter(lambda: stream.read(1024 * 1024), b""):
			hasher.update(chunk)
	return hasher.hexdigest()


def _atomic_write(path: Path, content: bytes, mode: int = 0o644) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, delete=False, prefix=f".{path.name}.nvdastudio-") as temp:
		temp.write(content)
		temp.flush()
		os.fsync(temp.fileno())
		temp_path = Path(temp.name)
	try:
		os.chmod(temp_path, mode)
		os.replace(temp_path, path)
	finally:
		if temp_path.exists():
			temp_path.unlink()


def _remember(operation: dict) -> str:
	operation_id = uuid.uuid4().hex
	with _HISTORY_LOCK:
		_HISTORY[operation_id] = operation
		while len(_HISTORY) > _HISTORY_LIMIT:
			del _HISTORY[next(iter(_HISTORY))]
	return operation_id


def _check_hash(path: Path, expected_sha256: str) -> str:
	if not path.exists():
		if expected_sha256:
			raise ValueError("expected_sha256 foi informado, mas o arquivo não existe")
		return ""
	if not path.is_file():
		raise ValueError(f"não é um arquivo: {path}")
	current = _sha256(path)
	if expected_sha256 and expected_sha256.lower() != current:
		raise ValueError("o arquivo mudou desde a leitura; leia novamente antes de editar")
	return current


def _undo(operation_id: str) -> str:
	with _HISTORY_LOCK:
		operation = _HISTORY.pop(operation_id, None)
	if not operation:
		return tool_error("operação não encontrada ou já desfeita", operation_id=operation_id)
	original = Path(operation["path"])
	if operation["kind"] == "move":
		destination = Path(operation["destination_path"])
		if not destination.exists() or original.exists():
			return tool_error("não é seguro desfazer a movimentação no estado atual")
		original.parent.mkdir(parents=True, exist_ok=True)
		os.replace(destination, original)
	else:
		if operation["existed"]:
			_atomic_write(original, operation["content"], operation["mode"])
		elif original.exists():
			original.unlink()
	return tool_result({"undone": True, "operation_id": operation_id, "path": str(original)})


def edit_file(path: str = "", old_text: str = "", new_text: str = "", replace_all: bool = False, expected_sha256: str = "", action: str = "replace", content: str = "", destination_path: str = "", operation_id: str = "") -> str:
	"""Executa replace, insert, create, write, delete, move, diff ou undo."""
	try:
		if action == "undo":
			return _undo(operation_id)
		file_path = _resolve_workspace_file(path)
		if action == "move":
			destination = _resolve_workspace_file(destination_path)
			if not file_path.is_file():
				return tool_error("arquivo de origem não encontrado")
			if destination.exists():
				return tool_error("o destino já existe")
			_check_hash(file_path, expected_sha256)
			os.replace(file_path, destination)
			operation = _remember({"kind": "move", "path": str(file_path), "destination_path": str(destination)})
			return tool_result({"action": action, "path": str(destination), "operation_id": operation})

		if action == "create" and file_path.exists():
			return tool_error("arquivo já existe; use action=write para sobrescrever")
		if action in {"create", "write"}:
			if not isinstance(content, str):
				return tool_error("content deve ser texto")
			_check_hash(file_path, expected_sha256)
			existed = file_path.exists()
			before = file_path.read_bytes() if existed else b""
			mode = file_path.stat().st_mode if existed else 0o644
			_atomic_write(file_path, content.encode("utf-8"), mode)
			operation = _remember({"kind": action, "path": str(file_path), "content": before, "existed": existed, "mode": mode})
			return tool_result({"action": action, "path": str(file_path), "sha256": _sha256(file_path), "operation_id": operation})

		if not file_path.is_file():
			return tool_error(f"arquivo não encontrado: {path}")
		current_hash = _check_hash(file_path, expected_sha256)
		before = file_path.read_bytes()
		mode = file_path.stat().st_mode
		with file_path.open("r", encoding="utf-8", newline="") as stream:
			current = stream.read()
		if action == "delete":
			file_path.unlink()
			operation = _remember({"kind": action, "path": str(file_path), "content": before, "existed": True, "mode": mode})
			return tool_result({"action": action, "path": str(file_path), "operation_id": operation})
		if action == "diff":
			proposed = content if content else current.replace(old_text, new_text, -1 if replace_all else 1)
			diff = "".join(difflib.unified_diff(current.splitlines(True), proposed.splitlines(True), fromfile=str(file_path), tofile=str(file_path)))
			return tool_result({"action": action, "path": str(file_path), "diff": diff, "sha256": current_hash})
		if not old_text:
			return tool_error("old_text deve ser não vazio")
		occurrences = current.count(old_text)
		if occurrences == 0:
			return tool_error("old_text não foi encontrado", current_sha256=current_hash)
		if occurrences > 1 and not replace_all:
			return tool_error(f"old_text aparece {occurrences} vezes; torne o trecho específico")
		replacement = old_text + new_text if action == "insert" else new_text
		updated = current.replace(old_text, replacement, -1 if replace_all else 1)
		_atomic_write(file_path, updated.encode("utf-8"), mode)
		operation = _remember({"kind": action, "path": str(file_path), "content": before, "existed": True, "mode": mode})
		return tool_result({"action": action, "path": str(file_path), "replacements": occurrences if replace_all else 1, "sha256": _sha256(file_path), "operation_id": operation})
	except Exception as exc:
		_logger.error("[ERRO] Editor de arquivo falhou: %s", exc)
		return tool_error(str(exc))


_SCHEMA = {
	"description": _DESCRIPTION,
	"parameters": {
		"type": "object",
		"properties": {
			"action": {"type": "string", "enum": ["replace", "insert", "create", "write", "delete", "move", "diff", "undo"]},
			"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"},
			"content": {"type": "string"}, "destination_path": {"type": "string"},
			"replace_all": {"type": "boolean", "default": False}, "expected_sha256": {"type": "string"}, "operation_id": {"type": "string"},
		},
		"required": ["action"],
	},
}

registry.register(name="file_editor", toolset="builtins", schema=_SCHEMA, handler=edit_file, description=_DESCRIPTION, emoji="✏️", max_result_size_chars=12000)
