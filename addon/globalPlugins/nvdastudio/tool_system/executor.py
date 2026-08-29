import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Callable, Dict, Optional

from .registry import ToolEntry, ToolResult, registry
from ..utils.logger import get_logger
from ..utils.timeouts import calculate_backoff_delay, get_tool_timeout

_logger = get_logger("tool_system.executor")
MODULE_VERSION = "1.2.0"

# Retries cobrem apenas timeout/stale timeout (falha transiente). Um erro de
# execucao da tool (bug, argumento invalido) nao e retryable: o mesmo input
# vai falhar de novo, entao _execute_once ja retorna o ToolResult direto.
_DEFAULT_MAX_RETRIES = 2


class ToolExecutor:
    """
    Executor de tools com seguranca.

    Features:
      - Timeout por tool
      - Output truncation
      - Thread-safe execution
      - Error handling
      - Retry com jittered backoff em timeout (Hermes-inspired)
    """

    def __init__(self, approval_callback: Optional[Callable[[str, Dict[str, Any]], bool]] = None, max_retries: int = _DEFAULT_MAX_RETRIES):
        self._approval_callback = approval_callback
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._lock = threading.Lock()
        self._max_retries = max_retries

    def execute(self, tool_name: str, **kwargs) -> ToolResult:
        """
        Executa uma tool com timeout configuravel, stale detection e retry.

        Hermes-inspired:
          - Timeout por tool (get_tool_timeout)
          - Stale timeout detection
          - Retry com jittered backoff quando o timeout e transiente

        Args:
            tool_name: Nome da tool
            **kwargs: Argumentos para a tool

        Returns:
            ToolResult com sucesso, output, erro, latency_ms
        """
        tool = registry.get_entry(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                output=None,
                error=f"Tool '{tool_name}' nao encontrada",
            )

        if not tool.enabled:
            return ToolResult(
                success=False,
                output=None,
                error=f"Tool '{tool_name}' esta desativada",
            )

        # Approval workflow -- usa ApprovalWorkflow Hermes-style. Uma unica vez
        # por chamada: retries nao repetem o prompt de aprovacao ao usuario.
        if self._approval_callback:
            # O approval_callback agora recebe (tool_name, args) e retorna bool
            approved = self._approval_callback(tool_name, kwargs)
            if not approved:
                return ToolResult(
                    success=False,
                    output=None,
                    error="Tool nao aprovada pelo usuario",
                )

        attempt = 0
        while True:
            attempt += 1
            try:
                result = self._execute_once(tool, tool_name, kwargs)
                if attempt > 1:
                    _logger.info(
                        "[TOOL] %s recuperada na tentativa %d/%d",
                        tool_name, attempt, self._max_retries + 1
                    )
                return result
            except FuturesTimeout as e:
                if attempt > self._max_retries:
                    _logger.error(
                        "[ERRO] Tool %s: timeout apos %d tentativas: %s",
                        tool_name, attempt, e
                    )
                    return ToolResult(
                        success=False,
                        output=None,
                        error=str(e),
                    )

                wait_time = calculate_backoff_delay(attempt)
                _logger.warning(
                    "[TOOL] %s: timeout na tentativa %d/%d (%s). Retry em %.1fs.",
                    tool_name, attempt, self._max_retries + 1, e, wait_time
                )
                time.sleep(wait_time)

    def _execute_once(self, tool: ToolEntry, tool_name: str, kwargs: Dict[str, Any]) -> ToolResult:
        """
        Executa uma unica tentativa da tool, sem retry.

        Timeout e stale timeout propagam como FuturesTimeout para o chamador
        decidir se tenta de novo. Qualquer outra excecao vira ToolResult direto
        (nao e transiente, retry nao ajudaria).
        """
        start_time = time.time()

        # Timeout por tool (Hermes-inspired)
        timeout_seconds = get_tool_timeout(tool_name)
        stale_timeout = timeout_seconds * 1.5  # Stale = 150% do timeout normal

        _logger.debug(
            "[TOOL] %s: timeout=%ds, stale=%ds",
            tool_name, timeout_seconds, stale_timeout
        )

        # Bug real: future.cancel() nao cancela nada quando a task JA ESTA
        # RODANDO (garantia do proprio concurrent.futures) -- so retorna False
        # silenciosamente. A thread do handler travado continuava rodando para
        # sempre, ocupando 1 dos workers do self._executor (pool COMPARTILHADO
        # com execute_batch, max_workers=4); algumas tools travadas esgotavam
        # o pool e toda chamada seguinte ficava enfileirada indefinidamente.
        # Fix: cada chamada usa seu proprio pool descartavel de 1 worker: se a
        # task travar, o "vazamento" fica isolado nesse pool descartavel (e
        # coletado quando a thread eventualmente termina), nunca consumindo um
        # slot do pool compartilhado usado por chamadas futuras.
        _call_pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = _call_pool.submit(tool.handler, **kwargs)

            # Poll com stale detection (Hermes chat_completion_helpers.py style)
            _poll_count = 0
            _elapsed = 0.0

            while future.running():
                try:
                    future.result(timeout=0.3)  # Poll a cada 300ms
                except FuturesTimeout:
                    pass  # Ainda rodando

                _elapsed = time.time() - start_time
                _poll_count += 1

                # Touch activity a cada ~30s
                if _poll_count % 100 == 0:
                    _logger.debug(
                        "[TOOL] %s ainda rodando (%ds elapsed)",
                        tool_name, int(_elapsed)
                    )

                # Stale detection: se passou muito tempo sem output
                if _elapsed > stale_timeout:
                    _logger.warning(
                        "[TOOL] %s: stale timeout (%ds > %ds). Cancelando.",
                        tool_name, int(_elapsed), stale_timeout
                    )
                    future.cancel()
                    raise FuturesTimeout(
                        f"Stale timeout apos {int(_elapsed)}s"
                    )

                # Normal timeout
                if _elapsed > timeout_seconds:
                    _logger.warning(
                        "[TOOL] %s: timeout (%ds > %ds). Cancelando.",
                        tool_name, int(_elapsed), timeout_seconds
                    )
                    future.cancel()
                    raise FuturesTimeout(
                        f"Timeout apos {int(_elapsed)}s"
                    )

            # Resultado final
            output = future.result()

            latency_ms = int((time.time() - start_time) * 1000)

            # Trunca output se necessario
            truncated = False
            max_chars = tool.max_result_size_chars or 10000
            if isinstance(output, str) and len(output) > max_chars:
                output = output[:max_chars] + f"\n\n[... truncado: {len(output) - max_chars} chars ...]"
                truncated = True

            _logger.info(
                "[TOOL] %s completada em %dms (timeout: %ds)",
                tool_name, latency_ms, timeout_seconds
            )

            return ToolResult(
                success=True,
                output=output,
                latency_ms=latency_ms,
                truncated=truncated,
            )

        except FuturesTimeout:
            raise

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            _logger.error(
                "[ERRO] Tool %s falhou: %s (latency: %dms)",
                tool_name, e, latency_ms
            )
            return ToolResult(
                success=False,
                output=None,
                error=str(e),
                latency_ms=latency_ms,
            )

        finally:
            # wait=False: nunca bloqueia esperando a thread do handler travado
            # terminar -- so libera a referencia ao pool descartavel. Se a task
            # ja terminou (caminho de sucesso), isso e imediato de qualquer forma.
            _call_pool.shutdown(wait=False)

    def execute_batch(self, tool_calls: list) -> Dict[str, ToolResult]:
        """
        Executa multiplas tools em paralelo.

        Args:
            tool_calls: Lista de (tool_name, kwargs) tuples

        Returns:
            Dict de tool_name -> ToolResult
        """
        results = {}
        futures = {}

        for tool_name, kwargs in tool_calls:
            future = self._executor.submit(self.execute, tool_name, **kwargs)
            futures[future] = tool_name

        for future in futures:
            tool_name = futures[future]
            try:
                results[tool_name] = future.result(timeout=120)
            except Exception as e:
                results[tool_name] = ToolResult(
                    success=False,
                    output=None,
                    error=str(e),
                )

        return results

    def shutdown(self):
        """Desliga o executor."""
        self._executor.shutdown(wait=True)
