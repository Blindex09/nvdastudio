"""Catálogo canônico de ferramentas do agente e seus adaptadores.

Todo provider HTTP recebe exatamente estes schemas e toda execução passa pelo
mesmo :class:`ToolGateway`. Backends externos, como o Droid, usam os mesmos
nomes de risco através de :func:`canonical_permission_name`.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from typing import Callable

from ..tools.tool_gateway import ToolGateway, ToolSchema
from ..utils.injection_guard import sanitize_untrusted_block

MODULE_VERSION = "1.0.0"


@dataclass
class AgentToolContext:
	workdir: str
	list_files: Callable[[], list[str]]
	validate: Callable[[], tuple[bool, str]]
	permission_callback: Callable[[str, dict], bool] | None = None
	ask_user_callback: Callable[[list[str]], list[str]] | None = None
	client: object | None = None
	trace_callback: Callable[[str, dict], None] | None = None
	cancel_event: threading.Event | None = None


_SPECS: tuple[tuple[str, str, dict, bool], ...] = (
	("list_workspace", "Lista os arquivos atuais do addon.", {"type": "object", "properties": {}}, False),
	("read_workspace_file", "Lê um arquivo textual do addon.", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, False),
	("write_workspace_file", "Cria ou substitui atomicamente um arquivo textual do addon.", {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}, True),
	("delete_workspace_file", "Remove um arquivo do addon.", {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, True),
	("validate_addon", "Executa os gates locais de estrutura, sintaxe, importação e acessibilidade.", {"type": "object", "properties": {}}, False),
	("run_addon_tests", "Executa os testes do addon no backend de isolamento configurado.", {"type": "object", "properties": {"path": {"type": "string", "default": "."}}}, True),
	("web_search", "Pesquisa documentação atual usando o recurso nativo do provedor.", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}, True),
	("ask_user", "Faz uma pergunta quando uma decisão essencial estiver faltando.", {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}, False),
)


def get_agent_tool_schemas() -> list[dict]:
	"""Retorna uma cópia dos schemas no formato comum de function calling."""
	return [
		{"type": "function", "function": {"name": name, "description": description, "parameters": dict(parameters)}}
		for name, description, parameters, _dangerous in _SPECS
	]


def canonical_permission_name(tool_name: str) -> str:
	"""Normaliza nomes equivalentes vindos de runtimes externos."""
	aliases = {
		"Read": "read_workspace_file",
		"Edit": "write_workspace_file",
		"Create": "write_workspace_file",
		"Write": "write_workspace_file",
		"Execute": "run_addon_tests",
		"WebSearch": "web_search",
		"AskUser": "ask_user",
		"file_editor": "write_workspace_file",
		"write_file": "write_workspace_file",
		"edit_file": "write_workspace_file",
		"remove_file": "delete_workspace_file",
		"execute_code": "run_addon_tests",
		"code_executor": "run_addon_tests",
		"network_request": "web_search",
	}
	return aliases.get(tool_name, tool_name)


def _workspace_path(workdir: str, relative_path: str) -> str:
	if not isinstance(relative_path, str) or not relative_path.strip():
		raise ValueError("caminho vazio")
	if os.path.isabs(relative_path):
		raise ValueError("use um caminho relativo ao addon")
	base = os.path.realpath(workdir)
	target = os.path.realpath(os.path.join(base, relative_path))
	if os.path.commonpath((base, target)) != base:
		raise ValueError("caminho fora do workspace")
	return target


def _read_workspace_files(context: AgentToolContext) -> dict[str, str]:
	files: dict[str, str] = {}
	for relpath in context.list_files():
		path = _workspace_path(context.workdir, relpath)
		try:
			with open(path, encoding="utf-8", errors="replace") as stream:
				files[relpath] = stream.read()
		except OSError:
			continue
	return files


def _handler(context: AgentToolContext, name: str) -> Callable[..., str]:
	def execute(**arguments) -> str:
		if name == "list_workspace":
			return json.dumps({"files": context.list_files()}, ensure_ascii=False)
		if name == "read_workspace_file":
			path = _workspace_path(context.workdir, str(arguments.get("path") or ""))
			with open(path, encoding="utf-8", errors="replace") as stream:
				return json.dumps({"content": stream.read(120000)}, ensure_ascii=False)
		if name == "write_workspace_file":
			path = _workspace_path(context.workdir, str(arguments.get("path") or ""))
			content = arguments.get("content")
			if not isinstance(content, str):
				raise ValueError("content precisa ser texto")
			os.makedirs(os.path.dirname(path), exist_ok=True)
			fd, temporary = tempfile.mkstemp(prefix=".nvdastudio_", dir=os.path.dirname(path))
			try:
				with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
					stream.write(content)
				os.replace(temporary, path)
			finally:
				if os.path.exists(temporary):
					os.remove(temporary)
			return json.dumps({"written": os.path.relpath(path, context.workdir).replace("\\", "/")})
		if name == "delete_workspace_file":
			path = _workspace_path(context.workdir, str(arguments.get("path") or ""))
			if os.path.isfile(path):
				os.remove(path)
			return json.dumps({"deleted": True})
		if name == "validate_addon":
			passed, report = context.validate()
			return json.dumps({"passed": passed, "report": report}, ensure_ascii=False)
		if name == "run_addon_tests":
			from .code_sandbox import CodeSandbox
			files = _read_workspace_files(context)
			tests = [path for path in files if "/tests/" in f"/{path}" or os.path.basename(path).startswith("test_")]
			sandbox_result = CodeSandbox(timeout_sec=180).run_test_suite(files, tests, timeout=180)
			return json.dumps({
				"passed": sandbox_result.success,
				"isolated": getattr(sandbox_result, "isolated", False),
				"output": (sandbox_result.stdout + sandbox_result.stderr)[-12000:],
				"error": sandbox_result.error,
			}, ensure_ascii=False)
		if name == "web_search":
			query = str(arguments.get("query") or "").strip()
			search = getattr(context.client, "native_web_search", None) or getattr(context.client, "web_search", None)
			if not callable(search):
				return json.dumps({"error": "provedor sem pesquisa web nativa"})
			web_result = sanitize_untrusted_block(str(search(query))[:50000], "resultado de pesquisa web")
			return json.dumps({"untrusted_web_result": web_result}, ensure_ascii=False)
		if name == "ask_user":
			question = str(arguments.get("question") or "").strip()
			answers = context.ask_user_callback([question]) if context.ask_user_callback and question else []
			return json.dumps({"answer": answers[0] if answers else ""}, ensure_ascii=False)
		raise ValueError(f"ferramenta desconhecida: {name}")
	return execute


def build_agent_tool_gateway(context: AgentToolContext) -> ToolGateway:
	"""Monta um gateway por execução, evitando estado global entre sessões."""
	gateway = ToolGateway(cancel_event=context.cancel_event)
	gateway.set_callbacks(on_approval_request=context.permission_callback)
	for name, description, parameters, dangerous in _SPECS:
		gateway.register(
			name, _handler(context, name),
			ToolSchema(name, description, parameters, list(parameters.get("required", []))),
			dangerous=dangerous,
		)
	return gateway


def execute_agent_tool(gateway: ToolGateway, name: str, arguments: dict) -> str:
	"""Executa e converte qualquer falha para um resultado de ferramenta."""
	result, error = gateway.call(canonical_permission_name(name), arguments)
	if error:
		return json.dumps({"error": error}, ensure_ascii=False)
	return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
