import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .logger import get_logger

MODULE_VERSION = "1.1.0"
_logger = get_logger("iteration_budget")

# Custos por 1M tokens (USD) — atualizar conforme provider
_MODEL_COSTS = {
    "kimi-k2.6": {"input": 0.50, "output": 1.50},
    "deepseek-v4-flash": {"input": 0.10, "output": 0.30},
    "default": {"input": 1.00, "output": 3.00},
}

# Limites padrão
_DEFAULT_MAX_ITERATIONS = 50
_DEFAULT_TOKEN_BUDGET = 500000
_DEFAULT_COST_BUDGET_USD = 5.00
_RATE_LIMIT_CALLS_PER_MINUTE = 60


@dataclass
class BudgetState:
    """Estado atual do budget."""
    iterations_used: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    last_iteration_time: str = ""
    rate_limit_hits: int = 0


@dataclass
class BudgetLimits:
    """Limites do budget."""
    max_iterations: int = _DEFAULT_MAX_ITERATIONS
    max_tokens: int = _DEFAULT_TOKEN_BUDGET
    max_cost_usd: float = _DEFAULT_COST_BUDGET_USD
    rate_limit_calls_per_minute: int = _RATE_LIMIT_CALLS_PER_MINUTE


@dataclass
class IterationRecord:
    """Registro de uma iteração."""
    timestamp: str
    step_type: str
    model_id: str
    tokens_used: int
    cost_usd: float
    success: bool
    latency_ms: int


class RateLimiter:
    """
    Rate limiter para chamadas de API.

    Implementa token bucket algorithm simples.
    """

    def __init__(self, calls_per_minute: int):
        self._calls_per_minute = calls_per_minute
        self._interval_seconds = 60.0 / calls_per_minute
        self._last_call_time: float = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        """
        Adquire permissão para fazer chamada.

        Returns:
            True se pode prosseguir, False se rate limited
        """
        with self._lock:
            now = time.time()
            elapsed = now - self._last_call_time

            if elapsed >= self._interval_seconds:
                self._last_call_time = now
                return True
            else:
                # Rate limited
                wait_time = self._interval_seconds - elapsed
                _logger.warning(
                    "[RATE LIMIT] Aguarde %.1fs antes da próxima chamada",
                    wait_time
                )
                return False

    def wait_if_needed(self):
        """Aguarda se necessário (blocking)."""
        while not self.acquire():
            time.sleep(0.1)


class IterationBudget:
    """
    Gerenciador de budget de iterações.

    Thread-safe via lock interno.
    """

    def __init__(self, limits: Optional[BudgetLimits] = None):
        self._limits = limits or BudgetLimits()
        self._state = BudgetState()
        self._iterations: List[IterationRecord] = []
        self._lock = threading.Lock()
        self._rate_limiter = RateLimiter(self._limits.rate_limit_calls_per_minute)
        self._paused = False
        self._stopped = False

    def reset(self):
        """Reseta budget para nova sessão."""
        with self._lock:
            self._state = BudgetState()
            self._iterations.clear()
            self._paused = False
            self._stopped = False
            _logger.info("[BUDGET] Resetado para nova sessão")

    def record_iteration(
        self,
        step_type: str,
        model_id: str = "",
        tokens_used: int = 0,
        success: bool = True,
        latency_ms: int = 0,
        **kwargs,  # Aceita argumentos extras (model_used, etc.)
    ):
        """Registra uma iteração."""
        with self._lock:
            # Fallback para model_used se model_id não fornecido
            if not model_id and "model_used" in kwargs:
                model_id = kwargs["model_used"]

            # Calcula custo
            cost_config = _MODEL_COSTS.get(model_id or "default", _MODEL_COSTS["default"])
            # Assume 50% input / 50% output como estimativa
            cost_usd = (tokens_used * 0.5 * cost_config["input"] + tokens_used * 0.5 * cost_config["output"]) / 1_000_000

            record = IterationRecord(
                timestamp=datetime.now().isoformat(),
                step_type=step_type,
                model_id=model_id or "unknown",
                tokens_used=tokens_used,
                cost_usd=cost_usd,
                success=success,
                latency_ms=latency_ms,
            )

            self._iterations.append(record)
            self._state.iterations_used += 1
            self._state.tokens_used += tokens_used
            self._state.cost_usd += cost_usd
            self._state.last_iteration_time = record.timestamp

            # Verifica limites
            self._check_limits()

    def _check_limits(self):
        """Verifica se algum limite foi excedido."""
        exceeded = []

        if self._state.iterations_used >= self._limits.max_iterations:
            exceeded.append(f"iterações ({self._state.iterations_used}/{self._limits.max_iterations})")
            self._stopped = True

        if self._state.tokens_used >= self._limits.max_tokens:
            exceeded.append(f"tokens ({self._state.tokens_used}/{self._limits.max_tokens})")
            self._stopped = True

        if self._state.cost_usd >= self._limits.max_cost_usd:
            exceeded.append(f"custo (${self._state.cost_usd:.2f}/${self._limits.max_cost_usd:.2f})")
            self._stopped = True

        if exceeded:
            _logger.warning(
                "[BUDGET] Limites excedidos: %s. Pipeline será parado.",
                ", ".join(exceeded)
            )

    def can_continue(self) -> tuple[bool, str]:
        """
        Verifica se pode continuar.

        Returns:
            (can_continue, reason)
        """
        with self._lock:
            if self._stopped:
                return False, "Budget excedido — pipeline parado"

            if self._paused:
                return False, "Budget pausado pelo usuário"

            if self._state.iterations_used >= self._limits.max_iterations:
                return False, f"Max iterações atingido ({self._state.iterations_used})"

            if self._state.tokens_used >= self._limits.max_tokens:
                return False, f"Budget de tokens excedido ({self._state.tokens_used})"

            if self._state.cost_usd >= self._limits.max_cost_usd:
                return False, f"Budget de custo excedido (${self._state.cost_usd:.2f})"

            return True, "OK"

    def check_rate_limit(self) -> bool:
        """
        Verifica rate limit.

        Returns:
            True se pode fazer chamada, False se rate limited
        """
        return self._rate_limiter.acquire()

    def wait_for_rate_limit(self):
        """Aguarda rate limit (blocking)."""
        self._rate_limiter.wait_if_needed()

    def pause(self):
        """Pausa budget."""
        with self._lock:
            self._paused = True
            _logger.info("[BUDGET] Pausado")

    def resume(self):
        """Retoma budget."""
        with self._lock:
            self._paused = False
            _logger.info("[BUDGET] Retomado")

    def stop(self):
        """Para budget permanentemente (até reset)."""
        with self._lock:
            self._stopped = True
            _logger.info("[BUDGET] Parado permanentemente")

    def get_state(self) -> BudgetState:
        """Retorna estado atual."""
        with self._lock:
            return BudgetState(
                iterations_used=self._state.iterations_used,
                tokens_used=self._state.tokens_used,
                cost_usd=self._state.cost_usd,
                start_time=self._state.start_time,
                last_iteration_time=self._state.last_iteration_time,
                rate_limit_hits=self._state.rate_limit_hits,
            )

    def get_limits(self) -> BudgetLimits:
        """Retorna limites."""
        return self._limits

    def get_remaining(self) -> Dict[str, Any]:
        """Retorna recursos restantes."""
        with self._lock:
            return {
                "iterations": max(0, self._limits.max_iterations - self._state.iterations_used),
                "tokens": max(0, self._limits.max_tokens - self._state.tokens_used),
                "cost_usd": max(0.0, self._limits.max_cost_usd - self._state.cost_usd),
                "percentage": {
                    "iterations": (self._state.iterations_used / self._limits.max_iterations) * 100,
                    "tokens": (self._state.tokens_used / self._limits.max_tokens) * 100,
                    "cost": (self._state.cost_usd / self._limits.max_cost_usd) * 100,
                }
            }

    def get_iteration_history(self, limit: int = 50) -> List[IterationRecord]:
        """Retorna histórico de iterações."""
        with self._lock:
            return self._iterations[-limit:]

    def get_summary(self) -> str:
        """Retorna resumo do budget."""
        remaining = self.get_remaining()
        return (
            f"Budget: {self._state.iterations_used}/{self._limits.max_iterations} iterações, "
            f"{self._state.tokens_used}/{self._limits.max_tokens} tokens, "
            f"${self._state.cost_usd:.2f}/${self._limits.max_cost_usd:.2f} — "
            f"Restante: {remaining['iterations']:.0f} iters, {remaining['tokens']:.0f} tokens, "
            f"${remaining['cost_usd']:.2f}"
        )


# Budget global para uso compartilhado
budget = IterationBudget()
