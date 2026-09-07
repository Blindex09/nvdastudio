import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..utils.logger import get_logger
from ..utils.timeouts import get_tool_timeout, calculate_backoff_delay

_logger = get_logger("tool_gateway")
MODULE_VERSION = "3.4.0"

# Limites
_MAX_CALLS_PER_MINUTE = 10
# 2026-08-30: `_MAX_TOOL_TIMEOUT = 120` ficava aqui declarado e NUNCA era
# lido -- o comentario do passo 6 prometia "executa com timeout e retry" e
# `_execute_with_retry()` chamava o handler direto, sem timeout nenhum. Uma
# tool travada pendurava o pipeline indefinidamente: para o usuario cego,
# nada acontece, nada e dito, e ele nao tem como saber se deve esperar.
#
# A constante foi REMOVIDA em vez de ligada: `utils/timeouts.py` ja e a fonte
# de verdade (get_tool_timeout, com override por tool), e o executor irmao
# em tool_system/executor.py ja a consome. Manter um terceiro numero local
# seria repor a duplicacao que a Regra 5 proibe.
_MAX_RETRIES = 1

# Tools que precisam de approval
_DANGEROUS_TOOL_TYPES = {"file_writer", "code_sandbox", "execute_code"}


@dataclass
class ToolCall:
    """Registro de uma chamada de tool."""
    tool_name: str
    args: Dict[str, Any]
    timestamp: float
    latency_ms: int = 0
    success: bool = False
    error: Optional[str] = None


@dataclass
class ToolSchema:
    """Schema OpenAI de uma tool."""
    name: str
    description: str
    parameters: Dict[str, Any]
    required: List[str]


class ToolGateway:
    """
    Gateway centralizado de tools (Hermes-inspired).

    Porteiro inteligente que controla todas as ferramentas:
    - Registro com schema e handler
    - Rate limiting
    - Approval para operacoes perigosas
    - Retry automatico
    - Metricas de latencia
    """

    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}      # name -> {handler, schema, check_fn}
        self._call_history: List[ToolCall] = []          # Historico de chamadas
        self._rate_tracker: Dict[str, List[float]] = {}  # tool -> timestamps
        self._lock = threading.Lock()
        # 3.4.0: pool COMPARTILHADO removido. `future.cancel()` e no-op quando a
        # task ja esta rodando (garantia do concurrent.futures), entao uma tool
        # travada ocupava para sempre um dos 4 workers deste pool -- 4 tools
        # presas esgotavam o pool e TODA chamada seguinte ficava enfileirada
        # indefinidamente (o pipeline pendura em silencio, pior falha para o
        # usuario cego). Cada chamada agora usa seu proprio pool descartavel de
        # 1 worker em _execute_with_retry: o vazamento fica isolado nesse pool e
        # nunca prende uma chamada futura. Mesma protecao que o ToolExecutor
        # (removido em 2026-09-06) garantia; agora vive no executor que roda.

        # Callbacks de UI
        self._on_tool_start: Optional[Callable[[str], None]] = None
        self._on_tool_end: Optional[Callable[[str, bool], None]] = None
        self._on_approval_request: Optional[Callable[[str, Dict[str, Any]], bool]] = None

    def set_callbacks(
        self,
        on_tool_start: Optional[Callable[[str], None]] = None,
        on_tool_end: Optional[Callable[[str, bool], None]] = None,
        on_approval_request: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
    ):
        """Configura callbacks de UI."""
        self._on_tool_start = on_tool_start
        self._on_tool_end = on_tool_end
        self._on_approval_request = on_approval_request

    # -------------------------------------------------------------------------
    # Registro de tools
    # -------------------------------------------------------------------------

    def register(
        self,
        name: str,
        handler: Callable[..., Any],
        schema: ToolSchema,
        check_fn: Optional[Callable[[], bool]] = None,
        dangerous: bool = False,
    ) -> None:
        """
        Registra uma tool no gateway.

        Args:
            name: Nome unico da tool
            handler: Funcao que executa a tool
            schema: Schema OpenAI para function calling
            check_fn: Funcao que retorna True se a tool esta disponivel
            dangerous: True se a tool precisa de approval
        """
        with self._lock:
            self._tools[name] = {
                "handler": handler,
                "schema": schema,
                "check_fn": check_fn or (lambda: True),
                "dangerous": dangerous or (name in _DANGEROUS_TOOL_TYPES),
            }
            self._rate_tracker[name] = []
        _logger.info("[GATEWAY] Tool registrada: %s (dangerous=%s)", name, dangerous)

    def unregister(self, name: str) -> None:
        """Remove uma tool do gateway."""
        with self._lock:
            self._tools.pop(name, None)
            self._rate_tracker.pop(name, None)

    def is_registered(self, name: str) -> bool:
        """Verifica se uma tool esta registrada."""
        with self._lock:
            return name in self._tools

    def is_available(self, name: str) -> bool:
        """Verifica se uma tool esta registrada E disponivel."""
        with self._lock:
            if name not in self._tools:
                return False
            try:
                return self._tools[name]["check_fn"]()
            except Exception:
                return False

    def list_tools(self) -> List[str]:
        """Lista nomes de todas as tools registradas."""
        with self._lock:
            return list(self._tools.keys())

    def list_available(self) -> List[str]:
        """Lista nomes das tools disponiveis (check_fn retorna True)."""
        available = []
        with self._lock:
            for name, info in self._tools.items():
                try:
                    if info["check_fn"]():
                        available.append(name)
                except Exception as exc:
                    _logger.debug("[DEBUG] check_fn de tool falhou: %s", exc)
        return available

    def get_schema(self, name: str) -> Optional[ToolSchema]:
        """Retorna schema de uma tool."""
        with self._lock:
            info = self._tools.get(name)
            return info["schema"] if info else None

    def get_all_schemas(self) -> List[ToolSchema]:
        """Retorna schemas de todas as tools disponiveis."""
        schemas = []
        with self._lock:
            for info in self._tools.values():
                try:
                    if info["check_fn"]():
                        schemas.append(info["schema"])
                except Exception:
                    _logger.debug("[TOOL_GATEWAY] check_fn falhou ao listar schemas", exc_info=True)
        return schemas

    # -------------------------------------------------------------------------
    # Execucao com controle
    # -------------------------------------------------------------------------

    def call(self, name: str, args: Dict[str, Any], request_approval: bool = True) -> Tuple[Any, Optional[str]]:
        """
        Executa uma tool com controle completo.

        Args:
            name: Nome da tool
            args: Argumentos para a tool
            request_approval: Se True, pergunta ao usuario para tools perigosas

        Returns:
            (resultado, erro) — erro e None se sucesso
        """
        # 1. Verifica registro
        with self._lock:
            if name not in self._tools:
                return None, f"Tool '{name}' nao registrada."

            tool_info = self._tools[name]

        # 2. Verifica disponibilidade
        try:
            if not tool_info["check_fn"]():
                return None, f"Tool '{name}' nao disponivel no momento."
        except Exception as e:
            return None, f"Erro ao verificar disponibilidade de '{name}': {e}"

        # 3. Rate limiting
        if not self._check_rate_limit(name):
            return None, f"Rate limit excedido para '{name}'. Tente novamente em um minuto."

        # 4. Approval para operacoes perigosas
        if request_approval and tool_info["dangerous"]:
            approved = self._request_approval(name, args)
            if not approved:
                return None, f"Tool '{name}' recusada pelo usuario."

        # 5. Notifica inicio
        if self._on_tool_start:
            try:
                self._on_tool_start(name)
            except Exception as exc:
                _logger.debug("[DEBUG] callback on_tool_start falhou: %s", exc)

        # 6. Executa o handler local com timeout e retry.
        start_time = time.time()
        result, error = self._execute_with_retry(tool_info["handler"], args, name)
        elapsed_ms = int((time.time() - start_time) * 1000)

        # 8. Registra chamada
        self._record_call(name, args, start_time, elapsed_ms, error is None, error)

        # 9. Notifica fim
        if self._on_tool_end:
            try:
                self._on_tool_end(name, error is None)
            except Exception as exc:
                _logger.debug("[DEBUG] callback on_tool_end falhou: %s", exc)

        if error:
            _logger.warning("[GATEWAY] Tool %s falhou: %s (%dms)", name, error, elapsed_ms)
        else:
            _logger.info("[GATEWAY] Tool %s OK (%dms)", name, elapsed_ms)

        return result, error

    def _record_call(self, name: str, args: Dict[str, Any], start_time: float, elapsed_ms: int, success: bool, error: Optional[str]) -> None:
        """Registra chamada no historico."""
        call = ToolCall(
            tool_name=name,
            args=args,
            timestamp=start_time,
            latency_ms=elapsed_ms,
            success=success,
            error=error,
        )
        with self._lock:
            self._call_history.append(call)
            self._rate_tracker[name].append(time.time())

        if self._on_tool_end:
            try:
                self._on_tool_end(name, success)
            except Exception as exc:
                _logger.debug("[DEBUG] callback on_tool_end (fallback) falhou: %s", exc)

    def _check_rate_limit(self, name: str) -> bool:
        """Verifica se a tool nao excedeu o rate limit."""
        with self._lock:
            now = time.time()
            calls = self._rate_tracker.get(name, [])
            # Mantem apenas chamadas do ultimo minuto
            recent = [t for t in calls if now - t < 60]
            self._rate_tracker[name] = recent
            return len(recent) < _MAX_CALLS_PER_MINUTE

    def _request_approval(self, name: str, args: Dict[str, Any]) -> bool:
        """Pede aprovacao ao usuario para operacoes perigosas.

        Fail-closed (achado de auditoria 2026-08-04): sem callback
        registrado, ou se o callback lancar excecao, NEGA por padrao --
        nunca executa uma tool marcada `dangerous` as cegas. Consistente com
        a doutrina ja estabelecida em tool_system/approval.py ("silencio =
        BLOQUEIO"), e com a Regra 3 do docstring deste modulo.
        """
        if self._on_approval_request:
            try:
                return bool(self._on_approval_request(name, args))
            except Exception as exc:
                _logger.warning(
                    "[GATEWAY] on_approval_request para '%s' levantou excecao "
                    "(%s) -- negando por seguranca (fail-closed).", name, exc,
                )
                return False
        _logger.warning(
            "[GATEWAY] Nenhum on_approval_request registrado para '%s' "
            "(tool perigosa) -- negando por seguranca (fail-closed).", name,
        )
        return False

    def _execute_with_retry(
        self, handler: Callable[..., Any], args: Dict[str, Any],
        tool_name: str = "",
    ) -> Tuple[Any, Optional[str]]:
        """
        Executa handler com TIMEOUT e retry automatico.

        O timeout vem de `utils/timeouts.get_tool_timeout()` -- mesma fonte que
        o executor de tool_system/ ja usava. Antes de 2026-08-30 esta funcao
        chamava `handler(**args)` direto: uma tool travada pendurava o pipeline
        para sempre, sem sinal nenhum para o usuario.

        O handler roda em thread separada porque nao ha como interromper uma
        chamada sincrona em Python de fora dela. Em timeout a thread continua
        viva ate terminar sozinha (o pool e daemon), mas o PIPELINE segue --
        que e o ponto: nao deixar o usuario esperando indefinidamente.
        """
        timeout_s = get_tool_timeout(tool_name) if tool_name else get_tool_timeout("")
        last_error = None
        for attempt in range(_MAX_RETRIES + 1):
            # 3.4.0: pool descartavel de 1 worker por tentativa. Se o handler
            # travar, `future.cancel()` nao o interrompe (a task ja roda) -- mas
            # a thread vazada fica isolada NESTE pool, jamais consumindo um slot
            # compartilhado de uma chamada futura. Ver comentario em __init__.
            call_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gateway_tool")
            try:
                future = call_pool.submit(handler, **args)
                result = future.result(timeout=timeout_s)
                return result, None
            except FuturesTimeout:
                future.cancel()
                last_error = f"timeout apos {timeout_s:.0f}s"
                _logger.warning(
                    "[GATEWAY] Tool %s excedeu %.0fs (tentativa %d).",
                    tool_name or "?", timeout_s, attempt + 1,
                )
                if attempt >= _MAX_RETRIES:
                    break
                time.sleep(calculate_backoff_delay(attempt + 1))
            except Exception as e:
                last_error = str(e)
                if attempt < _MAX_RETRIES:
                    _logger.debug("[GATEWAY] Retry %d apos erro: %s", attempt + 1, last_error)
                    time.sleep(calculate_backoff_delay(attempt + 1))
                else:
                    break
            finally:
                # Nao esperar a thread travada (wait=False) -- pendurar aqui
                # reintroduziria exatamente a falha que este fix elimina. O pool
                # descartavel e coletado quando a thread eventualmente termina.
                call_pool.shutdown(wait=False)
        return None, last_error

    # -------------------------------------------------------------------------
    # Registro de tools nativas do NVDAStudio
    # -------------------------------------------------------------------------

    def register_builtin_tools(self) -> None:
        """Regrega tools nativas do NVDAStudio no gateway."""
        try:
            from ..tool_system.builtins.file_reader import read_file as file_reader_tool
            from ..tool_system.builtins.ast_parser import parse_python_code as ast_parser_tool
            from ..tool_system.builtins.nvda_validator import validate_addon_structure as nvda_validator_tool
            from ..tool_system.builtins.file_editor import edit_file as file_editor_tool

            self.register(
                "file_reader",
                file_reader_tool,
                ToolSchema(
                    name="file_reader",
                    description="Le conteudo de arquivos de texto.",
                    parameters={"type": "object", "properties": {"path": {"type": "string"}}},
                    required=["path"],
                ),
                check_fn=lambda: True,
                dangerous=False,
            )

            self.register(
                "ast_parser",
                ast_parser_tool,
                ToolSchema(
                    name="ast_parser",
                    description="Analisa sintaxe Python via AST.",
                    parameters={"type": "object", "properties": {"code": {"type": "string"}}},
                    required=["code"],
                ),
                check_fn=lambda: True,
                dangerous=False,
            )

            self.register(
                "nvda_validator",
                nvda_validator_tool,
                ToolSchema(
                    name="nvda_validator",
                    description="Valida compatibilidade de addons NVDA.",
                    parameters={"type": "object", "properties": {"addon_path": {"type": "string"}}},
                    required=["addon_path"],
                ),
                check_fn=lambda: True,
                dangerous=False,
            )

            self.register(
                "file_editor",
                file_editor_tool,
                ToolSchema(
                    name="file_editor",
                    description="Cria, edita, compara, move, remove e desfaz alterações em arquivos do workspace.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["replace", "insert", "create", "write", "delete", "move", "diff", "undo"]},
                            "path": {"type": "string"},
                            "old_text": {"type": "string"},
                            "new_text": {"type": "string"},
                            "content": {"type": "string"},
                            "destination_path": {"type": "string"},
                            "replace_all": {"type": "boolean", "default": False},
                            "expected_sha256": {"type": "string"},
                            "operation_id": {"type": "string"},
                        },
                    },
                    required=["action"],
                ),
                check_fn=lambda: True,
                dangerous=True,
            )

            _logger.info("[GATEWAY] Tools nativas registradas: file_reader, ast_parser, nvda_validator, file_editor")
        except Exception as e:
            _logger.warning("[GATEWAY] Falha ao registrar tools nativas: %s", e)

    # -------------------------------------------------------------------------
    # Metricas
    # -------------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatisticas de uso."""
        with self._lock:
            total = len(self._call_history)
            if total == 0:
                return {"total_calls": 0}

            success = sum(1 for c in self._call_history if c.success)
            avg_latency = sum(c.latency_ms for c in self._call_history) / total

            by_tool: Dict[str, Dict[str, int]] = {}
            for c in self._call_history:
                if c.tool_name not in by_tool:
                    by_tool[c.tool_name] = {"calls": 0, "success": 0, "failures": 0}
                by_tool[c.tool_name]["calls"] += 1
                if c.success:
                    by_tool[c.tool_name]["success"] += 1
                else:
                    by_tool[c.tool_name]["failures"] += 1

            return {
                "total_calls": total,
                "success_rate": f"{success/total*100:.1f}%",
                "avg_latency_ms": int(avg_latency),
                "by_tool": by_tool,
            }

    def clear_history(self) -> None:
        """Limpa historico de chamadas."""
        with self._lock:
            self._call_history.clear()


# Instancia global
tool_gateway = ToolGateway()
