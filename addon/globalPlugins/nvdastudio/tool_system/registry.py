import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..utils.logger import get_logger

_logger = get_logger("tool_system.registry")


@dataclass
class ToolEntry:
    """Entrada de uma ferramenta no registry (Hermes ToolEntry style)."""
    name: str
    toolset: str
    schema: Dict[str, Any]  # Schema OpenAI function
    handler: Callable
    check_fn: Optional[Callable[[], bool]] = None
    requires_env: List[str] = field(default_factory=list)
    is_async: bool = False
    description: str = ""
    emoji: str = ""
    max_result_size_chars: Optional[int] = None
    dynamic_schema_overrides: Optional[Callable[[], Dict[str, Any]]] = None
    override: bool = False
    enabled: bool = True


@dataclass
class ToolResult:
    """Resultado da execucao de uma tool."""
    success: bool
    output: Any
    error: Optional[str] = None
    latency_ms: int = 0
    truncated: bool = False


class ToolRegistry:
    """
    Registry centralizado de ferramentas (Hermes-inspired).

    Thread-safe via RLock. Suporta:
    - Registro/deregistro
    - Check functions com cache TTL
    - Schemas dinamicos
    - Aliases de toolsets
    """

    def __init__(self):
        self._tools: Dict[str, ToolEntry] = {}
        self._toolset_checks: Dict[str, Callable[[], bool]] = {}
        self._toolset_aliases: Dict[str, str] = {}
        self._lock = threading.RLock()
        self._generation = 0  # Contador monotonico para memoizacao
        # Cache de check_fn (TTL ~30s)
        self._check_cache: Dict[str, tuple[bool, float]] = {}
        self._CHECK_TTL = 30.0

    def register(
        self,
        name: str,
        toolset: str,
        schema: Dict[str, Any],
        handler: Callable,
        check_fn: Optional[Callable[[], bool]] = None,
        requires_env: Optional[List[str]] = None,
        is_async: bool = False,
        description: str = "",
        emoji: str = "",
        max_result_size_chars: Optional[int] = None,
        dynamic_schema_overrides: Optional[Callable[[], Dict[str, Any]]] = None,
        override: bool = False,
    ) -> bool:
        """Registra uma ferramenta no registry."""
        with self._lock:
            # Resolve colisoes
            existing = self._tools.get(name)
            if existing:
                # Mesmo toolset: permitir (refresh de MCP)
                if existing.toolset == toolset:
                    pass
                elif override:
                    _logger.info("[TOOL] Override de %s (%s -> %s)", name, existing.toolset, toolset)
                else:
                    _logger.error("[ERRO] Colisao de tool %s (%s vs %s). Use override=True.", name, existing.toolset, toolset)
                    return False

            entry = ToolEntry(
                name=name,
                toolset=toolset,
                schema=schema,
                handler=handler,
                check_fn=check_fn,
                requires_env=requires_env or [],
                is_async=is_async,
                description=description or schema.get("description", ""),
                emoji=emoji,
                max_result_size_chars=max_result_size_chars,
                dynamic_schema_overrides=dynamic_schema_overrides,
                override=override,
            )

            self._tools[name] = entry
            self._generation += 1

            # Registra check_fn do toolset
            if check_fn and toolset not in self._toolset_checks:
                self._toolset_checks[toolset] = check_fn

            _logger.info("[TOOL] Registrada: %s (toolset=%s)", name, toolset)
            return True

    def deregister(self, name: str) -> bool:
        """Remove uma ferramenta do registry."""
        with self._lock:
            if name not in self._tools:
                return False
            entry = self._tools.pop(name)
            self._generation += 1

            # Limpa check_fn orfao
            if entry.toolset in self._toolset_checks:
                still_has_tools = any(
                    t.toolset == entry.toolset for t in self._tools.values()
                )
                if not still_has_tools:
                    del self._toolset_checks[entry.toolset]

            _logger.info("[TOOL] Removida: %s", name)
            return True

    def get_entry(self, name: str) -> Optional[ToolEntry]:
        """Retorna a ToolEntry de uma ferramenta."""
        with self._lock:
            return self._tools.get(name)

    def get_schema(self, name: str) -> Optional[Dict[str, Any]]:
        """Retorna o schema bruto de uma ferramenta."""
        entry = self.get_entry(name)
        if not entry:
            return None

        schema = dict(entry.schema)

        # Aplica overrides dinamicos
        if entry.dynamic_schema_overrides:
            try:
                overrides = entry.dynamic_schema_overrides()
                if overrides:
                    schema.update(overrides)
            except Exception as e:
                _logger.warning("[AVISO] dynamic_schema_overrides falhou para %s: %s", name, e)

        return schema

    def get_definitions(self, tool_names: Optional[List[str]] = None, quiet: bool = False) -> List[Dict[str, Any]]:
        """
        Retorna schemas no formato OpenAI das ferramentas disponiveis.
        Filtra por check_fn (só retorna ferramentas que realmente funcionam).
        """
        with self._lock:
            result = []
            names = tool_names if tool_names else list(self._tools.keys())

            for name in names:
                entry = self._tools.get(name)
                if not entry or not entry.enabled:
                    continue

                # Verifica check_fn com cache TTL
                available = self._is_available(entry)
                if not available:
                    if not quiet:
                        _logger.debug("[TOOL] %s indisponivel (check_fn falhou)", name)
                    continue

                schema = self.get_schema(name)
                if not schema:
                    continue

                # Monta definicao OpenAI
                definition = {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": entry.description or schema.get("description", ""),
                        "parameters": schema.get("parameters", schema),
                    },
                }
                result.append(definition)

            return result

    def _is_available(self, entry: ToolEntry) -> bool:
        """Verifica disponibilidade de uma ferramenta (com cache TTL)."""
        if not entry.check_fn:
            return True

        cache_key = f"{entry.name}:{entry.toolset}"
        import time
        now = time.time()

        cached = self._check_cache.get(cache_key)
        if cached:
            result, timestamp = cached
            if now - timestamp < self._CHECK_TTL:
                return result

        try:
            result = entry.check_fn()
            self._check_cache[cache_key] = (result, now)
            return result
        except Exception as e:
            _logger.warning("[AVISO] check_fn de %s falhou: %s", entry.name, e)
            self._check_cache[cache_key] = (False, now)
            return False

    def dispatch(self, name: str, args: Dict[str, Any], **kwargs) -> str:
        """
        Executa o handler de uma ferramenta pelo nome.
        Retorna JSON string (Hermes convention).
        """
        import json as json_mod

        entry = self.get_entry(name)
        if not entry:
            return json_mod.dumps({"error": f"Unknown tool: {name}"})

        try:
            if entry.is_async:
                # Converte async para sync
                import asyncio
                output = asyncio.run(entry.handler(args, **kwargs))
            else:
                output = entry.handler(args, **kwargs)

            # Garante retorno JSON
            if isinstance(output, str):
                return output
            return json_mod.dumps({"success": True, "output": output})

        except Exception as e:
            # Sanitiza erro (remove tokens estruturais que confundem LLM)
            error_msg = str(e)
            for token in ["CDATA", "```", "<", ">"]:
                error_msg = error_msg.replace(token, "")
            return json_mod.dumps({"error": f"Tool execution failed: {type(e).__name__}: {error_msg}"})

    def get_all_tool_names(self) -> List[str]:
        """Lista todos os nomes de ferramentas registradas."""
        with self._lock:
            return list(self._tools.keys())

    def is_toolset_available(self, toolset: str) -> bool:
        """Verifica se um toolset esta disponivel."""
        with self._lock:
            check = self._toolset_checks.get(toolset)
            if not check:
                return True
            try:
                return check()
            except Exception:
                return False

    def register_toolset_alias(self, alias: str, toolset: str):
        """Registra um alias para um nome canonico de toolset."""
        with self._lock:
            self._toolset_aliases[alias] = toolset

    def get_toolset_for_tool(self, name: str) -> Optional[str]:
        """Retorna o toolset ao qual a ferramenta pertence."""
        entry = self.get_entry(name)
        return entry.toolset if entry else None

    def get_max_result_size(self, name: str) -> Optional[int]:
        """Retorna o tamanho maximo de resultado configurado."""
        entry = self.get_entry(name)
        return entry.max_result_size_chars if entry else None

    def check_tool_availability(self) -> tuple[List[str], Dict[str, str]]:
        """Retorna tupla (available, unavailable_info)."""
        available = []
        unavailable = {}

        for name in self.get_all_tool_names():
            entry = self.get_entry(name)
            if not entry:
                continue

            if self._is_available(entry):
                available.append(name)
            else:
                unavailable[name] = f"check_fn failed for toolset {entry.toolset}"

        return available, unavailable


# Registry global (singleton)
registry = ToolRegistry()


def tool_error(message: str, **extra) -> str:
    """Helper para retornar erro JSON de tool."""
    import json
    result = {"error": message}
    result.update(extra)
    return json.dumps(result)


def tool_result(data: Any, **kwargs) -> str:
    """Helper para retornar resultado JSON de tool."""
    import json
    result = {"success": True, "output": data}
    result.update(kwargs)
    return json.dumps(result)
