from .registry import ToolRegistry, ToolEntry, ToolResult, registry, tool_error, tool_result
from .approval import ApprovalWorkflow, ApprovalRequest
# 2026-09-06: ToolExecutor removido. Era o gemeo redundante de
# tools/tool_gateway.py (o executor VIVO em producao) -- sem nenhuma
# instanciacao fora de teste (ver comentario 5.72.0 do orchestrator). O
# caminho de producao e tool_gateway.call(); este pacote segue exportando os
# builtins e o ApprovalWorkflow, que continuam vivos e compartilhados.

# Auto-registra builtins (side-effect: registry.register() chamado no import)
from .builtins.file_reader import read_file as read_file
from .builtins.ast_parser import parse_python_code as parse_python_code, check_imports as check_imports
from .builtins.nvda_validator import validate_addon_structure as validate_addon_structure
from .builtins.file_editor import edit_file as edit_file

# Helpers de acesso rapido (opcional)
file_reader_tool = registry.get_entry("file_reader")
ast_parser_tool = registry.get_entry("ast_parser")
nvda_validator_tool = registry.get_entry("nvda_validator")
file_editor_tool = registry.get_entry("file_editor")

__all__ = [
    "ToolRegistry",
    "ToolEntry",
    "ToolResult",
    "registry",
    "tool_error",
    "tool_result",
    "ApprovalWorkflow",
    "ApprovalRequest",
    "file_reader_tool",
    "ast_parser_tool",
    "nvda_validator_tool",
    "file_editor_tool",
    "edit_file",
]
