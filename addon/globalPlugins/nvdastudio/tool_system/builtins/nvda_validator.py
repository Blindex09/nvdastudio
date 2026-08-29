from pathlib import Path
from typing import List

from ..registry import registry, tool_result, tool_error
from ...utils.logger import get_logger

_logger = get_logger("tool_system.nvda_validator")

# Estrutura obrigatória de addon NVDA
_REQUIRED_FILES = {
    "manifest.ini",
    "globalPlugins/__init__.py",
}

_REQUIRED_DIRS = {
    "globalPlugins",
}

# Estrutura opcional comum
_OPTIONAL_FILES = {
    "appModules/__init__.py",
    "synthDrivers/__init__.py",
    "brailleDisplayDrivers/__init__.py",
    "userGuide.html",
    "readme.md",
}


def validate_addon_structure(addon_path: str) -> str:
    """
    Valida estrutura de um addon NVDA.

    Args:
        addon_path: Caminho da pasta do addon

    Returns:
        JSON string com validação, erros, avisos
    """
    try:
        addon_dir = Path(addon_path)

        if not addon_dir.exists():
            return tool_error(f"Pasta não encontrada: {addon_path}")

        if not addon_dir.is_dir():
            return tool_error(f"Não é uma pasta: {addon_path}")

        errors: List[str] = []
        warnings: List[str] = []
        info: List[str] = []

        # Verifica arquivos obrigatórios
        for required_file in _REQUIRED_FILES:
            file_path = addon_dir / required_file
            if not file_path.exists():
                errors.append(f"Arquivo obrigatório faltando: {required_file}")
            else:
                info.append(f"OK: {required_file}")

        # Verifica pastas obrigatórias
        for required_dir in _REQUIRED_DIRS:
            dir_path = addon_dir / required_dir
            if not dir_path.exists():
                errors.append(f"Pasta obrigatória faltando: {required_dir}")
            elif not (dir_path / "__init__.py").exists():
                errors.append(f"Pasta {required_dir} sem __init__.py")
            else:
                info.append(f"OK: {required_dir}/")

        # Verifica arquivos opcionais
        for optional_file in _OPTIONAL_FILES:
            file_path = addon_dir / optional_file
            if file_path.exists():
                info.append(f"Opcional: {optional_file}")

        # Valida manifest.ini
        manifest_path = addon_dir / "manifest.ini"
        if manifest_path.exists():
            manifest_errors = _validate_manifest(manifest_path)
            errors.extend(manifest_errors)

        # Valida globalPlugins/__init__.py
        init_path = addon_dir / "globalPlugins" / "__init__.py"
        if init_path.exists():
            init_errors = _validate_global_plugin(init_path)
            errors.extend(init_errors)

        success = len(errors) == 0

        return tool_result({
            "valid": success,
            "path": str(addon_dir),
            "errors": errors,
            "warnings": warnings,
            "info": info,
        }, error_count=len(errors))

    except Exception as e:
        return tool_error(str(e))


def _validate_manifest(manifest_path: Path) -> List[str]:
    """Valida arquivo manifest.ini."""
    errors = []

    try:
        content = manifest_path.read_text(encoding="utf-8")

        # Verifica campos obrigatórios
        required_fields = ["name", "version", "description", "minimumNVDAVersion"]
        for field in required_fields:
            if f"{field}=" not in content:
                errors.append(f"manifest.ini: campo obrigatório faltando '{field}'")

        # Verifica se não tem seção [add-on] proibida
        if "[add-on]" in content:
            errors.append("manifest.ini: seção [add-on] é proibida (use campos no topo)")

    except Exception as e:
        errors.append(f"manifest.ini: erro ao ler: {e}")

    return errors


def _validate_global_plugin(init_path: Path) -> List[str]:
    """Valida arquivo globalPlugins/__init__.py."""
    errors = []

    try:
        content = init_path.read_text(encoding="utf-8")

        # Verifica se tem GlobalPlugin class
        if "class GlobalPlugin" not in content:
            errors.append("globalPlugins/__init__.py: classe GlobalPlugin não encontrada")

        # Verifica se tem scriptCategory
        if "scriptCategory" not in content:
            errors.append("globalPlugins/__init__.py: scriptCategory não encontrado")

    except Exception as e:
        errors.append(f"globalPlugins/__init__.py: erro ao ler: {e}")

    return errors


# Auto-registro no ToolRegistry (Hermes-style)
registry.register(
    name="nvda_validator",
    toolset="builtins",
    schema={
        "description": "Valida estrutura de addon NVDA (manifest, globalPlugins, etc.)",
        "parameters": {
            "type": "object",
            "properties": {
                "addon_path": {
                    "type": "string",
                    "description": "Caminho da pasta do addon",
                },
            },
            "required": ["addon_path"],
        },
    },
    handler=validate_addon_structure,
    description="Valida estrutura de addon NVDA (manifest, globalPlugins, etc.)",
    emoji="✅",
    max_result_size_chars=5000,
)
