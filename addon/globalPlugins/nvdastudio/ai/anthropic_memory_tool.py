import os
from pathlib import Path

from ..utils.logger import get_logger

MODULE_VERSION = "1.1.0"
_logger = get_logger("anthropic_memory_tool")

_MEMORY_ROOT = Path(os.path.expanduser("~")) / "AppData" / "Roaming" / "NVDAStudio" / "claude_memory"
_MAX_LINES = 999_999


def _ensure_root() -> Path:
	_MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
	return _MEMORY_ROOT


def _resolve_path(virtual_path: str) -> Path | None:
	"""
	Resolve um path virtual "/memories/..." para um Path real dentro de
	_MEMORY_ROOT. Retorna None se o path nao comecar com /memories ou se
	resolver (apos normalizar ../ etc) pra fora da raiz -- protecao contra
	path traversal (CWE-22), exigida explicitamente pela doc do memory tool.
	"""
	if not virtual_path or not virtual_path.startswith("/memories"):
		return None
	rel = virtual_path[len("/memories"):].lstrip("/\\")
	root = _ensure_root()
	candidate = (root / rel).resolve() if rel else root.resolve()
	try:
		candidate.relative_to(root.resolve())
	except ValueError:
		return None
	return candidate


def _format_size(num_bytes: int) -> str:
	if num_bytes < 1024:
		return f"{num_bytes}B"
	if num_bytes < 1024 * 1024:
		return f"{num_bytes / 1024:.1f}K"
	return f"{num_bytes / (1024 * 1024):.1f}M"


def _cmd_view(input_: dict) -> tuple[str, bool]:
	path = input_.get("path", "")
	real = _resolve_path(path)
	if real is None:
		return f"The path {path} does not exist. Please provide a valid path.", True
	if real.is_dir():
		entries = []
		try:
			for child in sorted(real.rglob("*")):
				if child.is_file() and not any(part.startswith(".") or part == "node_modules" for part in child.parts):
					rel = "/memories/" + str(child.relative_to(_MEMORY_ROOT)).replace("\\", "/")
					entries.append(f"{_format_size(child.stat().st_size)}\t{rel}")
		except Exception as exc:
			_logger.debug("[DEBUG] Falha ao listar %s: %s", path, exc)
		header = f"Here're the files and directories up to 2 levels deep in {path}, excluding hidden items and node_modules:"
		lines = [header, f"{_format_size(0)}\t{path}"] + entries
		return "\n".join(lines), False
	if real.is_file():
		try:
			text = real.read_text(encoding="utf-8")
		except Exception:
			return f"The path {path} does not exist. Please provide a valid path.", True
		lines = text.split("\n")
		if len(lines) > _MAX_LINES:
			return f"File {path} exceeds maximum line limit of 999,999 lines.", True
		view_range = input_.get("view_range")
		start, end = 1, len(lines)
		if view_range and len(view_range) == 2:
			start = max(1, view_range[0])
			end = len(lines) if view_range[1] == -1 else min(len(lines), view_range[1])
		numbered = "\n".join(f"{i:>6}\t{lines[i - 1]}" for i in range(start, end + 1))
		return f"Here's the content of {path} with line numbers:\n{numbered}", False
	return f"The path {path} does not exist. Please provide a valid path.", True


def _cmd_create(input_: dict) -> tuple[str, bool]:
	path = input_.get("path", "")
	real = _resolve_path(path)
	if real is None:
		return f"The path {path} does not exist. Please provide a valid path.", True
	if real.exists():
		return f"Error: File {path} already exists", True
	real.parent.mkdir(parents=True, exist_ok=True)
	real.write_text(input_.get("file_text", ""), encoding="utf-8")
	return f"File created successfully at: {path}", False


def _cmd_str_replace(input_: dict) -> tuple[str, bool]:
	path = input_.get("path", "")
	real = _resolve_path(path)
	if real is None or not real.is_file():
		return f"Error: The path {path} does not exist. Please provide a valid path.", True
	text = real.read_text(encoding="utf-8")
	old_str = input_.get("old_str", "")
	new_str = input_.get("new_str", "")
	count = text.count(old_str)
	if count == 0:
		return f"No replacement was performed, old_str `{old_str}` did not appear verbatim in {path}.", True
	if count > 1:
		line_numbers = [i + 1 for i, line in enumerate(text.split("\n")) if old_str in line]
		return (
			f"No replacement was performed. Multiple occurrences of old_str `{old_str}` "
			f"in lines: {line_numbers}. Please ensure it is unique"
		), True
	real.write_text(text.replace(old_str, new_str, 1), encoding="utf-8")
	return "The memory file has been edited.", False


def _cmd_insert(input_: dict) -> tuple[str, bool]:
	path = input_.get("path", "")
	real = _resolve_path(path)
	if real is None or not real.is_file():
		return f"Error: The path {path} does not exist", True
	lines = real.read_text(encoding="utf-8").split("\n")
	insert_line = input_.get("insert_line", 0)
	if insert_line < 0 or insert_line > len(lines):
		return (
			f"Error: Invalid `insert_line` parameter: {insert_line}. "
			f"It should be within the range of lines of the file: [0, {len(lines)}]"
		), True
	insert_text = input_.get("insert_text", "").rstrip("\n")
	lines.insert(insert_line, insert_text)
	real.write_text("\n".join(lines), encoding="utf-8")
	return f"The file {path} has been edited.", False


def _cmd_delete(input_: dict) -> tuple[str, bool]:
	path = input_.get("path", "")
	real = _resolve_path(path)
	if real is None or not real.exists():
		return f"Error: The path {path} does not exist", True
	if real.resolve() == _MEMORY_ROOT.resolve():
		return "Error: cannot delete the /memories root directory", True
	if real.is_dir():
		import shutil
		shutil.rmtree(real)
	else:
		real.unlink()
	return f"Successfully deleted {path}", False


def _cmd_rename(input_: dict) -> tuple[str, bool]:
	old_path = input_.get("old_path", "")
	new_path = input_.get("new_path", "")
	real_old = _resolve_path(old_path)
	real_new = _resolve_path(new_path)
	if real_old is None or not real_old.exists():
		return f"Error: The path {old_path} does not exist", True
	if real_old.resolve() == _MEMORY_ROOT.resolve():
		return "Error: cannot rename the /memories root directory", True
	if real_new is None:
		return f"Error: The path {new_path} does not exist. Please provide a valid path.", True
	if real_new.exists():
		return f"Error: The destination {new_path} already exists", True
	real_new.parent.mkdir(parents=True, exist_ok=True)
	real_old.rename(real_new)
	return f"Successfully renamed {old_path} to {new_path}", False


_COMMANDS = {
	"view": _cmd_view,
	"create": _cmd_create,
	"str_replace": _cmd_str_replace,
	"insert": _cmd_insert,
	"delete": _cmd_delete,
	"rename": _cmd_rename,
}


def handle_memory_command(input_: dict) -> dict:
	"""
	Executa 1 comando do memory tool da Anthropic e retorna o tool_result.

	Retorno: {"content": str, "is_error": bool} -- content vai direto no
	campo "content" do tool_result; is_error vira o campo "is_error".
	"""
	command = input_.get("command", "")
	handler = _COMMANDS.get(command)
	if handler is None:
		return {"content": f"Error: unknown command {command}", "is_error": True}
	try:
		content, is_error = handler(input_)
		return {"content": content, "is_error": is_error}
	except Exception as exc:
		_logger.warning("[MEMORY_TOOL] comando '%s' falhou: %s", command, exc)
		return {"content": f"Error: {exc}", "is_error": True}
