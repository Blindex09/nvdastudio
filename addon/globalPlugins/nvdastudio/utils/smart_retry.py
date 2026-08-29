import random
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from .logger import get_logger

_logger = get_logger("smart_retry")
MODULE_VERSION = "1.1.0"

# Config
_MAX_RETRIES = 3
_BASE_DELAY = 2.0
_MAX_DELAY = 60.0
_JITTER_RATIO = 0.3
_CIRCUIT_BREAKER_THRESHOLD = 5


class FailoverReason(Enum):
    """Taxonomia de erros (Hermes-inspired)."""
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    SERVER_ERROR = "server_error"
    CONTEXT_OVERFLOW = "context_overflow"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    MODEL_NOT_FOUND = "model_not_found"
    FORMAT_ERROR = "format_error"
    UNKNOWN = "unknown"


@dataclass
class ClassifiedError:
    """Erro classificado com estrategia de recovery."""
    reason: FailoverReason
    retryable: bool
    should_compress: bool
    should_fallback: bool
    message: str


class SmartRetryController:
    """
    Controlador de retry inteligente (Hermes-inspired).

    Classifica o erro, escolhe a estrategia certa, aplica backoff.
    Thread-safe.
    """

    def __init__(self):
        self._circuit_breakers: Dict[str, int] = {}  # step_type -> strikes
        self._trip_timestamps: Dict[str, float] = {}  # step_type -> timestamp
        self._lock = threading.Lock()
        self._last_errors: Dict[str, List[ClassifiedError]] = {}  # step_type -> erros

    # -------------------------------------------------------------------------
    # Classificador de erros
    # -------------------------------------------------------------------------

    def classify(self, error_text: str) -> ClassifiedError:
        """Classifica um erro textual em categoria e estrategia."""
        text = str(error_text).lower()

        # Timeout
        if any(p in text for p in ["timeout", "timed out", "tempo esgotado", "connection"]):
            return ClassifiedError(
                reason=FailoverReason.TIMEOUT,
                retryable=True,
                should_compress=False,
                should_fallback=False,
                message="Timeout detectado. Reduzindo complexidade..."
            )

        # Rate limit
        if any(p in text for p in ["rate limit", "429", "too many", "limite"]):
            return ClassifiedError(
                reason=FailoverReason.RATE_LIMIT,
                retryable=True,
                should_compress=False,
                should_fallback=True,
                message="Rate limit atingido. Aguardando..."
            )

        # Auth
        if any(p in text for p in ["auth", "401", "403", "unauthorized", "forbidden", "api key"]):
            return ClassifiedError(
                reason=FailoverReason.AUTH,
                retryable=False,
                should_compress=False,
                should_fallback=False,
                message="Erro de autenticacao. Verifique a chave API."
            )

        # Context overflow
        if any(p in text for p in ["context", "overflow", "too large", "window", "max tokens"]):
            return ClassifiedError(
                reason=FailoverReason.CONTEXT_OVERFLOW,
                retryable=True,
                should_compress=True,
                should_fallback=False,
                message="Contexto muito grande. Comprimindo..."
            )

        # Server error
        if any(p in text for p in ["502", "503", "504", "500", "erro do servidor"]):
            return ClassifiedError(
                reason=FailoverReason.SERVER_ERROR,
                retryable=True,
                should_compress=False,
                should_fallback=True,
                message="Servidor indisponivel. Tentando alternativa..."
            )

        # Model not found
        if any(p in text for p in ["model not found", "invalid model", "modelo invalido"]):
            return ClassifiedError(
                reason=FailoverReason.MODEL_NOT_FOUND,
                retryable=True,
                should_compress=False,
                should_fallback=True,
                message="Modelo indisponivel. Usando fallback..."
            )

        # Format error
        if any(p in text for p in ["json", "format", "parse", "schema", "invalid"]):
            return ClassifiedError(
                reason=FailoverReason.FORMAT_ERROR,
                retryable=True,
                should_compress=False,
                should_fallback=False,
                message="Formato invalido. Reescrevendo prompt..."
            )

        # Unknown (retryable por default)
        return ClassifiedError(
            reason=FailoverReason.UNKNOWN,
            retryable=True,
            should_compress=False,
            should_fallback=False,
            message="Erro desconhecido. Tentando novamente..."
        )

    # -------------------------------------------------------------------------
    # Retry com estrategia inteligente
    # -------------------------------------------------------------------------

    def execute(
        self,
        fn: Callable[..., Any],
        args: Tuple,
        kwargs: Dict[str, Any],
        step_type: str,
        step_id: str,
        fallback_fn: Optional[Callable[..., Any]] = None,
        compress_fn: Optional[Callable[..., Any]] = None,
    ) -> Tuple[Any, Optional[str]]:
        """
        Executa funcao com retry inteligente.

        Args:
            fn: Funcao principal a executar
            args, kwargs: Argumentos
            step_type: Tipo do step (para circuit breaker)
            step_id: ID do step
            fallback_fn: Funcao alternativa se fallback necessario
            compress_fn: Funcao de compressao se context overflow

        Returns:
            (resultado, erro) — erro eh None se sucesso
        """
        # Verifica circuit breaker
        if self._circuit_breaker_tripped(step_type):
            return None, f"Circuit breaker aberto para '{step_type}'. Tente mais tarde."

        last_error = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                result = fn(*args, **kwargs)
                # Sucesso — limpa strikes
                self._clear_strikes(step_type)
                return result, None
            except Exception as exc:
                error_text = str(exc)
                classified = self.classify(error_text)
                last_error = classified

                _logger.warning(
                    "[SMART_RETRY] Step %s: erro '%s' na tentativa %d/%d. "
                    "Estrategia: %s",
                    step_id, classified.reason.value, attempt + 1,
                    _MAX_RETRIES + 1, classified.message
                )

                # Ultima tentativa? Falha
                if attempt >= _MAX_RETRIES:
                    break

                # Executa estrategia
                if classified.should_compress and compress_fn:
                    _logger.info("[SMART_RETRY] Comprimindo contexto...")
                    try:
                        new_kwargs = compress_fn(kwargs)
                        kwargs.update(new_kwargs)
                    except Exception as e:
                        _logger.debug("[SMART_RETRY] Compressao falhou: %s", e)

                if classified.should_fallback and fallback_fn:
                    _logger.info("[SMART_RETRY] Usando funcao fallback...")
                    try:
                        result = fallback_fn(*args, **kwargs)
                        self._clear_strikes(step_type)
                        return result, None
                    except Exception as fb_exc:
                        _logger.warning("[SMART_RETRY] Fallback falhou: %s", fb_exc)

                if not classified.retryable:
                    # Nao retryable — falha imediata
                    return None, f"Erro nao recuperavel: {classified.message}"

                # Aplica backoff
                delay = self._calculate_backoff(attempt)
                _logger.info("[SMART_RETRY] Aguardando %.1fs antes de retry...", delay)
                time.sleep(delay)

        # Todas as tentativas falharam
        self._record_strike(step_type)
        return None, f"Falhou apos {_MAX_RETRIES + 1} tentativas: {last_error.message if last_error else error_text}"

    # -------------------------------------------------------------------------
    # Circuit breaker
    # -------------------------------------------------------------------------

    def _circuit_breaker_tripped(self, step_type: str) -> bool:
        with self._lock:
            strikes = self._circuit_breakers.get(step_type, 0)
            if strikes >= _CIRCUIT_BREAKER_THRESHOLD:
                trip_time = self._trip_timestamps.get(step_type, 0.0)
                if time.time() - trip_time > 60.0:
                    _logger.info("[SMART_RETRY] Cooldown do Circuit Breaker expirou para '%s'. Estado: Half-Open.", step_type)
                    self._circuit_breakers[step_type] = 0
                    return False
                return True
            return False

    def _record_strike(self, step_type: str) -> None:
        with self._lock:
            self._circuit_breakers[step_type] = self._circuit_breakers.get(step_type, 0) + 1
            if self._circuit_breakers[step_type] == _CIRCUIT_BREAKER_THRESHOLD:
                self._trip_timestamps[step_type] = time.time()
                _logger.warning("[SMART_RETRY] Circuit Breaker TRIP para '%s'. Estado: Aberto (Cooldown 60s).", step_type)

    def _clear_strikes(self, step_type: str) -> None:
        with self._lock:
            self._circuit_breakers[step_type] = 0
            self._trip_timestamps.pop(step_type, None)

    def reset(self) -> None:
        """Reseta todos os circuit breakers (util ao mudar de modelo ou iniciar nova sessao)."""
        with self._lock:
            self._circuit_breakers.clear()
            self._trip_timestamps.clear()
            _logger.info("[SMART_RETRY] Todos os Circuit Breakers foram resetados.")

    # -------------------------------------------------------------------------
    # Backoff com jitter
    # -------------------------------------------------------------------------

    def _calculate_backoff(self, attempt: int) -> float:
        """Calcula delay exponencial com jitter (Hermes-inspired)."""
        # Exponential: base * 2^(attempt)
        delay = _BASE_DELAY * (2 ** attempt)
        # Cap
        delay = min(delay, _MAX_DELAY)
        # Jitter: adiciona aleatoriedade para evitar thundering herd
        jitter = delay * _JITTER_RATIO * random.random()  # nosec B311 -- jitter de backoff, nao criptografico
        return delay + jitter

    # -------------------------------------------------------------------------
    # Estategias especificas para NVDAStudio
    # -------------------------------------------------------------------------

    def suggest_strategy(self, error_text: str, step_type: str) -> str:
        """Sugere estrategia ao usuario baseado no erro."""
        classified = self.classify(error_text)

        strategies = {
            FailoverReason.TIMEOUT: (
                "O servidor demorou muito. Sugestoes:\n"
                "  1. Descreva o addon com menos detalhes\n"
                "  2. Divida em partes menores\n"
                "  3. Tente novamente em alguns segundos"
            ),
            FailoverReason.RATE_LIMIT: (
                "Muitas requisicoes seguidas. Aguarde 1 minuto e tente."
            ),
            FailoverReason.CONTEXT_OVERFLOW: (
                "O contexto ficou muito grande. Sugestoes:\n"
                "  1. Simplifique a descricao\n"
                "  2. Pecaa para gerar apenas o nucleo\n"
                "  3. Divida em multiplos addons"
            ),
            FailoverReason.AUTH: (
                "Problema com a chave API. Verifique em NVDAStudio > Opcoes."
            ),
            FailoverReason.MODEL_NOT_FOUND: (
                "Modelo indisponivel. Usando modelo fallback automaticamente."
            ),
            FailoverReason.FORMAT_ERROR: (
                "Resposta em formato inesperado. Tentando novamente..."
            ),
            FailoverReason.SERVER_ERROR: (
                "Servidor com instabilidade. Tentando modelo alternativo..."
            ),
            FailoverReason.UNKNOWN: (
                "Erro inesperado. Tentando novamente..."
            ),
        }

        return strategies.get(classified.reason, strategies[FailoverReason.UNKNOWN])


# Instancia global
smart_retry = SmartRetryController()
