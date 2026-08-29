import ast
from typing import List, Optional

from ..registry import registry, tool_result, tool_error
from ...utils.logger import get_logger

_logger = get_logger("tool_system.ast_parser")


def parse_python_code(code: str) -> str:
    """
    Analisa código Python via AST.

    Args:
        code: Código Python a analisar

    Returns:
        JSON string com estrutura AST, imports, classes, funções
    """
    try:
        tree = ast.parse(code)

        # Extrai informações
        imports = []
        classes = []
        functions = []
        global_vars = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(f"{module}.{alias.name}")
            elif isinstance(node, ast.ClassDef):
                classes.append({
                    "name": node.name,
                    "bases": [base.id for base in node.bases if isinstance(base, ast.Name)],
                    "methods": [n.name for n in node.body if isinstance(n, ast.FunctionDef)],
                })
            elif isinstance(node, ast.FunctionDef):
                functions.append({
                    "name": node.name,
                    "args": [arg.arg for arg in node.args.args],
                    "decorators": [d.id if isinstance(d, ast.Name) else str(d) for d in node.decorator_list],
                })
            elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                global_vars.append(node.targets[0].id)

        return tool_result(
            {
                "valid": True,
                "imports": imports,
                "classes": classes,
                "functions": functions,
                "global_vars": global_vars,
                "line_count": len(code.splitlines()),
            }
        )

    except SyntaxError as e:
        return tool_error(
            f"SyntaxError: {e.msg} (linha {e.lineno}, coluna {e.offset})",
            code=code[:100],
        )
    except Exception as e:
        return tool_error(str(e))


def check_imports(code: str, allowed_modules: Optional[List[str]] = None) -> str:
    """
    Verifica imports de código Python.

    Args:
        code: Código Python
        allowed_modules: Lista de módulos permitidos (None = todos permitidos)

    Returns:
        JSON string com imports encontrados e status
    """
    try:
        tree = ast.parse(code)

        imports = []
        forbidden = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
                    if allowed_modules and not any(alias.name.startswith(m) for m in allowed_modules):
                        forbidden.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    full_import = f"{module}.{alias.name}"
                    imports.append(full_import)
                    if allowed_modules and not any(full_import.startswith(m) for m in allowed_modules):
                        forbidden.append(full_import)

        if forbidden:
            return tool_error(
                f"Imports proibidos: {', '.join(forbidden)}",
                imports=imports,
                forbidden=forbidden,
            )

        return tool_result({
            "imports": imports,
            "allowed": allowed_modules,
        })

    except SyntaxError as e:
        return tool_error(f"SyntaxError: {e.msg}")
    except Exception as e:
        return tool_error(str(e))


# Auto-registro no ToolRegistry (Hermes-style)
registry.register(
    name="ast_parser",
    toolset="builtins",
    schema={
        "description": "Analisa estrutura AST de código Python (imports, classes, funções)",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Código Python a analisar",
                },
            },
            "required": ["code"],
        },
    },
    handler=parse_python_code,
    description="Analisa estrutura AST de código Python (imports, classes, funções)",
    emoji="🔍",
    max_result_size_chars=10000,
)

registry.register(
    name="check_imports",
    toolset="builtins",
    schema={
        "description": "Verifica imports de código Python contra lista de módulos permitidos",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Código Python",
                },
                "allowed_modules": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de módulos permitidos (None = todos)",
                },
            },
            "required": ["code"],
        },
    },
    handler=check_imports,
    description="Verifica imports de código Python contra lista de módulos permitidos",
    emoji="🔍",
    max_result_size_chars=5000,
)
