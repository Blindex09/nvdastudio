from pathlib import Path

from ..registry import registry, tool_result, tool_error
from ...utils.logger import get_logger

_logger = get_logger("tool_system.file_reader")


def _is_safe_path(base_path: Path, target_path: Path) -> bool:
    """Verifica se target_path está dentro de base_path (previne traversal)."""
    try:
        base_resolved = base_path.resolve()
        target_resolved = target_path.resolve()
        return str(target_resolved).startswith(str(base_resolved))
    except Exception:
        return False


def read_file(path: str, max_chars: int = 50000) -> str:
    """
    Lê um arquivo de forma segura.

    Args:
        path: Caminho do arquivo
        max_chars: Máximo de caracteres a retornar

    Returns:
        JSON string com conteúdo do arquivo
    """
    try:
        file_path = Path(path)

        # Verifica se arquivo existe
        if not file_path.exists():
            return tool_error(f"Arquivo não encontrado: {path}")

        if not file_path.is_file():
            return tool_error(f"Não é um arquivo: {path}")

        # Verifica segurança do path
        workspace = Path(__file__).parent.parent.parent.parent.parent
        if not _is_safe_path(workspace, file_path):
            _logger.warning("[AVISO] Leitura fora do workspace: %s", path)

        # Lê conteúdo
        content = file_path.read_text(encoding="utf-8")

        # Trunca se necessário
        truncated = False
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n[... truncado: {len(content) - max_chars} chars ...]"
            truncated = True

        _logger.info("[FILE] Lido: %s (%d chars)", path, len(content))

        return tool_result(
            {
                "path": str(file_path),
                "size": file_path.stat().st_size,
                "content": content,
                "truncated": truncated,
            }
        )

    except Exception as e:
        _logger.error("[ERRO] Leitura de arquivo falhou: %s", e)
        return tool_error(str(e))


# Auto-registro no ToolRegistry (Hermes-style)
registry.register(
    name="file_reader",
    toolset="builtins",
    schema={
        "description": "Lê arquivos de código Python, manifest, documentação",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Caminho do arquivo a ser lido",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Máximo de caracteres (default: 50000)",
                    "default": 50000,
                },
            },
            "required": ["path"],
        },
    },
    handler=read_file,
    description="Lê arquivos de código Python, manifest, documentação",
    emoji="📄",
    max_result_size_chars=50000,
)
