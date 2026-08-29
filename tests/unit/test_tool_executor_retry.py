from concurrent.futures import TimeoutError as FuturesTimeout
from unittest.mock import MagicMock, patch

from nvdastudio.tool_system import executor as executor_module
from nvdastudio.tool_system.executor import ToolExecutor
from nvdastudio.tool_system.registry import ToolEntry, ToolResult


def _make_tool_entry(name: str = "fake_tool") -> ToolEntry:
    return ToolEntry(
        name=name,
        toolset="test",
        schema={"name": name, "description": "fake"},
        handler=lambda **kwargs: "ok",
        enabled=True,
    )


class TestToolExecutorRetryOnTimeout:
    """Timeout/stale timeout (FuturesTimeout) e a unica falha retryable."""

    def test_recupera_apos_timeout_transiente(self):
        tool = _make_tool_entry()
        exec_ = ToolExecutor(max_retries=2)

        side_effects = [
            FuturesTimeout("Timeout apos 60s"),
            ToolResult(success=True, output="ok", latency_ms=10),
        ]

        with patch.object(executor_module.registry, "get_entry", return_value=tool), \
             patch.object(exec_, "_execute_once", side_effect=side_effects) as mock_once, \
             patch.object(executor_module.time, "sleep") as mock_sleep, \
             patch.object(executor_module, "calculate_backoff_delay", return_value=0.01) as mock_backoff:
            result = exec_.execute("fake_tool")

        assert result.success is True
        assert result.output == "ok"
        assert mock_once.call_count == 2
        mock_backoff.assert_called_once_with(1)
        mock_sleep.assert_called_once_with(0.01)

    def test_esgota_retries_e_retorna_falha(self):
        tool = _make_tool_entry()
        exec_ = ToolExecutor(max_retries=2)

        with patch.object(executor_module.registry, "get_entry", return_value=tool), \
             patch.object(exec_, "_execute_once", side_effect=FuturesTimeout("Timeout apos 60s")) as mock_once, \
             patch.object(executor_module.time, "sleep") as mock_sleep, \
             patch.object(executor_module, "calculate_backoff_delay", return_value=0.01):
            result = exec_.execute("fake_tool")

        assert result.success is False
        assert "Timeout" in result.error
        # max_retries=2 => 3 tentativas totais (1 original + 2 retries)
        assert mock_once.call_count == 3
        assert mock_sleep.call_count == 2

    def test_max_retries_zero_nao_tenta_de_novo(self):
        tool = _make_tool_entry()
        exec_ = ToolExecutor(max_retries=0)

        with patch.object(executor_module.registry, "get_entry", return_value=tool), \
             patch.object(exec_, "_execute_once", side_effect=FuturesTimeout("Timeout apos 60s")) as mock_once, \
             patch.object(executor_module.time, "sleep") as mock_sleep:
            result = exec_.execute("fake_tool")

        assert result.success is False
        assert mock_once.call_count == 1
        mock_sleep.assert_not_called()


class TestToolExecutorNaoRetryEmErroGenerico:
    """Erro de execucao (nao-timeout) nao e retryable: mesmo input falharia de novo."""

    def test_erro_generico_nao_dispara_retry(self):
        tool = _make_tool_entry()
        exec_ = ToolExecutor(max_retries=2)

        falha = ToolResult(success=False, output=None, error="ValueError: argumento invalido")

        with patch.object(executor_module.registry, "get_entry", return_value=tool), \
             patch.object(exec_, "_execute_once", return_value=falha) as mock_once, \
             patch.object(executor_module.time, "sleep") as mock_sleep:
            result = exec_.execute("fake_tool")

        assert result.success is False
        assert result.error == "ValueError: argumento invalido"
        mock_once.assert_called_once()
        mock_sleep.assert_not_called()


class TestToolExecutorRetryNaoRepeteAprovacao:
    """Approval callback e chamado uma unica vez, mesmo com retries."""

    def test_approval_callback_chamado_uma_vez_com_retry(self):
        tool = _make_tool_entry()
        approval_callback = MagicMock(return_value=True)
        exec_ = ToolExecutor(approval_callback=approval_callback, max_retries=1)

        side_effects = [
            FuturesTimeout("Timeout apos 60s"),
            ToolResult(success=True, output="ok"),
        ]

        with patch.object(executor_module.registry, "get_entry", return_value=tool), \
             patch.object(exec_, "_execute_once", side_effect=side_effects), \
             patch.object(executor_module.time, "sleep"), \
             patch.object(executor_module, "calculate_backoff_delay", return_value=0.01):
            result = exec_.execute("fake_tool", path="x")

        assert result.success is True
        approval_callback.assert_called_once_with("fake_tool", {"path": "x"})
class TestExecuteOnceNaoVazaThreadDoPoolCompartilhado:
    """v1.2.0: bug real de auditoria -- future.cancel() e no-op quando a task JA
    ESTA RODANDO (garantia do proprio concurrent.futures); a thread do handler
    travado continuava ocupando 1 dos workers do self._executor (pool
    COMPARTILHADO com execute_batch, max_workers=4) para sempre. Algumas tools
    travadas esgotavam o pool e toda chamada seguinte ficava enfileirada
    indefinidamente. Fix: cada chamada usa seu proprio pool descartavel de 1
    worker, isolando qualquer vazamento do pool compartilhado."""

    def test_handler_travado_nao_ocupa_slot_do_pool_compartilhado(self):
        """Handler que nunca retorna (simula travamento). Apos o timeout, o
        pool COMPARTILHADO (exec_._executor) deve continuar com todos os
        workers livres para atender outras chamadas."""
        import threading

        release_gate = threading.Event()
        handler_done = threading.Event()

        def handler_travado(**kwargs):
            release_gate.wait(timeout=5)
            handler_done.set()
            return "nunca deveria retornar antes do teste liberar"

        tool = ToolEntry(
            name="travado", toolset="test",
            schema={"name": "travado", "description": "fake"},
            handler=handler_travado, enabled=True,
        )
        exec_ = ToolExecutor(max_retries=0)

        with patch.object(executor_module.registry, "get_entry", return_value=tool), \
             patch.object(executor_module, "get_tool_timeout", return_value=0):
            try:
                exec_._execute_once(tool, "travado", {})
            except FuturesTimeout:
                pass  # esperado: get_tool_timeout=0 forca o timeout quase imediato

        try:
            assert exec_._executor._work_queue.qsize() == 0
            busy = sum(1 for t in exec_._executor._threads if t.is_alive())
            assert busy == 0, (
                "a thread travada vazou para o pool COMPARTILHADO -- deveria "
                "estar isolada no pool descartavel de _execute_once"
            )
        finally:
            # Garante que a thread travada TERMINE antes do teste retornar --
            # evita que ela vaze (ainda viva) para o proximo teste do arquivo
            # e interfira em mocks de time.sleep de outros testes.
            release_gate.set()
            handler_done.wait(timeout=2)
