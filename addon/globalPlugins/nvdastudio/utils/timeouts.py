import os
import threading
from typing import Optional

from .logger import get_logger

_logger = get_logger("timeouts")

# =============================================================================
# Defaults
# =============================================================================

# API Ollama Cloud
_DEFAULT_API_TIMEOUT = 180.0  # 3 minutos
_DEFAULT_API_STALE_TIMEOUT = 300.0  # 5 minutos
_DEFAULT_TTFB_TIMEOUT = 30.0  # 30 segundos

# Tools
_DEFAULT_TOOL_TIMEOUT = 60.0  # 1 minuto
_DEFAULT_TOOL_TIMEOUT_HEAVY = 180.0  # 3 minutos (ferramentas pesadas)

# Sandbox de código
_DEFAULT_SANDBOX_TIMEOUT = 10.0  # 10 segundos
_DEFAULT_SANDBOX_TIMEOUT_COMPLEX = 30.0  # 30 segundos

# Pipeline
_DEFAULT_STEP_TIMEOUT = 180.0  # 3 minutos por step
_DEFAULT_STEP_TIMEOUT_LONG = 600.0  # 10 minutos (design_review, code_generation)
_DEFAULT_PIPELINE_GRACE_PERIOD = 60.0  # 1 minuto de graça após timeout

# Retry backoff
_DEFAULT_BACKOFF_BASE = 5.0  # 5 segundos base
_DEFAULT_BACKOFF_MAX = 120.0  # 2 minutos máximo
_DEFAULT_BACKOFF_JITTER = 0.5  # 50% jitter


# =============================================================================
# Configuração por tipo de operação
# =============================================================================

_STEP_TYPE_TIMEOUT_OVERRIDE = {
    "design_review": _DEFAULT_STEP_TIMEOUT_LONG,
    "code_generation": _DEFAULT_STEP_TIMEOUT_LONG,
    "agent_runner": _DEFAULT_STEP_TIMEOUT_LONG,
    "web_research": _DEFAULT_STEP_TIMEOUT_LONG,
}

_TOOL_TIMEOUT_OVERRIDE = {
    "file_reader": _DEFAULT_TOOL_TIMEOUT,
    "ast_parser": _DEFAULT_TOOL_TIMEOUT,
    "nvda_validator": _DEFAULT_TOOL_TIMEOUT,
    "web_search": _DEFAULT_TOOL_TIMEOUT_HEAVY,
    "code_sandbox": _DEFAULT_SANDBOX_TIMEOUT,
}


# =============================================================================
# Helpers
# =============================================================================

def _coerce_timeout(raw: object) -> Optional[float]:
    """Converte valor para timeout válido."""
    try:
        # raw e deliberadamente `object` (entrada nao confiavel) -- float() aceita
        # qualquer coisa em runtime e nos protegemos com o except abaixo; o stub
        # do mypy so declara os tipos "normais", entao a checagem e explicitamente
        # ignorada aqui.
        timeout = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if timeout <= 0:
        return None
    return timeout


def get_api_timeout(model_id: str = "default") -> float:
    """
    Retorna timeout para chamada de API LLM.

    Args:
        model_id: ID do modelo (kimi-k2.6, deepseek-v4-flash, etc.)

    Returns:
        Timeout em segundos
    """
    # Environment override
    env_timeout = os.getenv("NVDASTUDIO_API_TIMEOUT")
    if env_timeout:
        coerced = _coerce_timeout(env_timeout)
        if coerced:
            return coerced

    # Overrides operacionais por identificador exato; isto nao classifica intencao.
    model_timeouts = {
        "kimi-k2.6": 240.0,
        "deepseek-v4-flash": 120.0,
    }
    configured_timeout = model_timeouts.get(model_id.strip().lower())
    if configured_timeout is not None:
        return configured_timeout

    return _DEFAULT_API_TIMEOUT


def get_api_stale_timeout(model_id: str = "default") -> float:
    """
    Retorna stale timeout (detecção de conexão morta).

    Args:
        model_id: ID do modelo

    Returns:
        Stale timeout em segundos
    """
    env_timeout = os.getenv("NVDASTUDIO_API_STALE_TIMEOUT")
    if env_timeout:
        coerced = _coerce_timeout(env_timeout)
        if coerced:
            return coerced

    return _DEFAULT_API_STALE_TIMEOUT


def get_ttfb_timeout() -> float:
    """
    Retorna TTFB timeout (time-to-first-byte).

    Tempo máximo para receber primeiro token da resposta.

    Returns:
        TTFB timeout em segundos
    """
    env_timeout = os.getenv("NVDASTUDIO_TTFB_TIMEOUT")
    if env_timeout:
        coerced = _coerce_timeout(env_timeout)
        if coerced:
            return coerced

    return _DEFAULT_TTFB_TIMEOUT


def get_step_timeout(step_type: str) -> float:
    """
    Retorna timeout para tipo de step.

    Args:
        step_type: Tipo do step (code_generation, manifest, etc.)

    Returns:
        Timeout em segundos
    """
    # Override por tipo de step
    if step_type in _STEP_TYPE_TIMEOUT_OVERRIDE:
        return _STEP_TYPE_TIMEOUT_OVERRIDE[step_type]

    return _DEFAULT_STEP_TIMEOUT


def get_tool_timeout(tool_name: str) -> float:
    """
    Retorna timeout para tool.

    Args:
        tool_name: Nome da tool

    Returns:
        Timeout em segundos
    """
    # Override por tool
    if tool_name in _TOOL_TIMEOUT_OVERRIDE:
        return _TOOL_TIMEOUT_OVERRIDE[tool_name]

    return _DEFAULT_TOOL_TIMEOUT


def get_sandbox_timeout(is_complex: bool = False) -> float:
    """
    Retorna timeout para sandbox de código.

    Args:
        is_complex: Se código é complexo (requer mais tempo)

    Returns:
        Timeout em segundos
    """
    if is_complex:
        return _DEFAULT_SANDBOX_TIMEOUT_COMPLEX
    return _DEFAULT_SANDBOX_TIMEOUT


def get_pipeline_grace_period() -> float:
    """
    Retorna grace period após timeout global do pipeline.

    Permite que steps quase-prontos entreguem resultado.

    Returns:
        Grace period em segundos
    """
    env_grace = os.getenv("NVDASTUDIO_PIPELINE_GRACE_PERIOD")
    if env_grace:
        coerced = _coerce_timeout(env_grace)
        if coerced:
            return coerced

    return _DEFAULT_PIPELINE_GRACE_PERIOD


# =============================================================================
# Retry Backoff com Jitter
# =============================================================================

def calculate_backoff_delay(
    attempt: int,
    base_delay: float = _DEFAULT_BACKOFF_BASE,
    max_delay: float = _DEFAULT_BACKOFF_MAX,
    jitter_ratio: float = _DEFAULT_BACKOFF_JITTER,
) -> float:
    """
    Calcula delay de backoff exponencial com jitter.

    Inspirado no Hermes agent/retry_utils.py.

    Args:
        attempt: Número da tentativa (1-based)
        base_delay: Delay base em segundos
        max_delay: Delay máximo em segundos
        jitter_ratio: Fração de jitter (0.0-1.0)

    Returns:
        Delay em segundos com jitter
    """
    import random

    # Exponential backoff
    exponent = max(0, attempt - 1)
    if exponent >= 63 or base_delay <= 0:
        delay = max_delay
    else:
        delay = min(base_delay * (2 ** exponent), max_delay)

    # Jitter decorrelates concurrent retries
    jitter = random.uniform(0, jitter_ratio * delay)  # nosec B311 -- jitter de backoff, nao criptografico

    return delay + jitter


# =============================================================================
# Timeout Context Manager
# =============================================================================

class TimeoutError(Exception):
    """Exceção de timeout."""
    pass


class timeout_context:
    """
    Context manager de timeout.

    Uso:
        with timeout_context(30, "Operação X"):
            # código que pode timeout
    """

    def __init__(self, seconds: float, operation: str = "Operação"):
        self.seconds = seconds
        self.operation = operation
        self._timed_out = False

    def __enter__(self):
        self._timer = threading.Timer(self.seconds, self._timeout_handler)
        self._timer.start()
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        self._timer.cancel()
        return False  # Não suprime exceções

    def _timeout_handler(self):
        self._timed_out = True
        _logger.warning(
            "[TIMEOUT] %s excedeu %ds",
            self.operation, self.seconds
        )

    def is_timed_out(self) -> bool:
        return self._timed_out
