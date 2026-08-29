"""Retry/backoff/deteccao de loop compartilhado entre todos os clientes LLM.

Porta o padrao ja validado em C:\\agentic (features/reliability/reliability.py,
versao async) pro estilo sincrono do NVDAStudio -- achado real de auditoria
2026-08-26, comparando os dois projetos: ollama_client.py, opencode_go_client.py
e provider_client.py tinham 3 implementacoes quase identicas de
_MAX_RETRIES/_is_retryable_error/backoff, cada uma reimplementada
separadamente -- a mesma classe de duplicacao ja corrigida em
orchestrator.py/agentic_loop.py (classificador e recovery duplicados,
5.55.0/2.6.0). Fonte unica agora.
"""

import random
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, TypeVar

MODULE_VERSION = "1.1.0"

T = TypeVar("T")

# 529: "overloaded_error" da Anthropic -- nao esta na lista padrao de status
# retryable de nenhuma lib HTTP generica, mas e uma condicao real e
# retentavel documentada pela Anthropic.
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}

# Falhas identicas consecutivas antes de desistir cedo. Cortar em 2 mata
# retries que ainda tinham chance real com estado limpo; 3 e o minimo que a
# metodologia do proprio projeto (docs/conceitos-ia-para-desenvolvimento-de-
# software.md, secao de loop detection) considera um loop confirmado.
LOOP_DETECTION_THRESHOLD = 3

_MAX_RETRY_DELAY = 30.0

# Achado de teste E2E real ao vivo (2026-08-04, conta Gemini free-tier): o
# 429 do Gemini embute o tempo real de espera na MENSAGEM de erro em texto
# livre ("...Please retry in 24.8s."), sem Retry-After header nem campo
# estruturado dedicado. Anthropic/OpenAI/xAI nao embutem isso na mensagem
# (confirmado por inspecao das respostas 429/529 desses 3).
_RETRY_AFTER_TEXT_RE = re.compile(r"retry in\s+([\d.]+)\s*s", re.IGNORECASE)


class LoopDetectedError(RuntimeError):
	"""A mesma falha se repetiu LOOP_DETECTION_THRESHOLD vezes seguidas.

	Distingue "insistir na mesma abordagem quebrada" (retentar mais nao
	ajuda) de "tentar abordagens genuinamente diferentes que continuam
	falhando" (vale continuar). Guarda a excecao original em last_error.
	"""

	def __init__(self, signature: str, attempts: int, last_error: Exception):
		super().__init__(
			f"Loop detectado: a mesma falha se repetiu {attempts}x seguidas ({signature})"
		)
		self.signature = signature
		self.attempts = attempts
		self.last_error = last_error


def _failure_signature(exc: Exception) -> str:
	"""Fingerprint grosseiro de uma falha, estavel entre retries do mesmo problema."""
	return f"{type(exc).__name__}:{status_code(exc)}:{str(exc)[:200]}"


def status_code(exc: Exception) -> int | None:
	direct = getattr(exc, "status_code", None)
	if isinstance(direct, int):
		return direct
	response = getattr(exc, "response", None)
	value = getattr(response, "status_code", None)
	return value if isinstance(value, int) else None


def is_retryable(exc: Exception) -> bool:
	status = status_code(exc)
	if status is not None:
		return status in RETRYABLE_STATUS
	name = type(exc).__name__.lower()
	return any(marker in name for marker in ("timeout", "connect", "ratelimit", "temporarily"))


def _parse_retry_after_header(value: str) -> float | None:
	"""Header HTTP Retry-After padrao (RFC 7231): delta-segundos OU HTTP-date.

	Portado de ollama_client.py (achado real 2026-08-18: 429 do Ollama
	Cloud honra este header; ler com precisao evita adivinhar com backoff
	fixo insuficiente pra um rate limit que reseta por minuto/hora).
	"""
	if not value:
		return None
	# Formato 1: delta-segundos (inteiro simples, ex: "30")
	try:
		return max(0.0, float(value))
	except ValueError:
		pass
	# Formato 2: HTTP-date (ex: "Wed, 21 Oct 2026 07:28:00 GMT")
	try:
		target = parsedate_to_datetime(value)
		if target.tzinfo is None:
			target = target.replace(tzinfo=timezone.utc)
		return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())
	except Exception:
		return None


def retry_delay(exc: Exception, attempt: int) -> float:
	"""Tempo de espera antes da proxima tentativa. Ordem de preferencia:
	1. Tempo embutido no TEXTO do erro (ver _RETRY_AFTER_TEXT_RE acima).
	2. Header Retry-After padrao HTTP, quando existe.
	3. Backoff exponencial com jitter."""
	response = getattr(exc, "response", None)
	text = ""
	if response is not None:
		text = getattr(response, "text", "") or ""
	match = _RETRY_AFTER_TEXT_RE.search(text or str(exc))
	if match:
		return min(float(match.group(1)) + 0.5, _MAX_RETRY_DELAY)
	headers = getattr(response, "headers", None) if response is not None else None
	header_value = None
	if headers:
		header_value = headers.get("retry-after") or headers.get("Retry-After")
	if header_value is not None:
		header_delay = _parse_retry_after_header(str(header_value).strip())
		if header_delay is not None:
			return min(header_delay, _MAX_RETRY_DELAY)
	base = min(1.0 * (2 ** attempt), 8.0)
	return min(_MAX_RETRY_DELAY, base + random.uniform(0, min(base * 0.2, 0.5)))


def call_with_retry(
	call: Callable[[], T],
	*,
	max_attempts: int = 3,
	on_retry: Callable[[int, float, Exception], None] | None = None,
	on_loop_detected: Callable[[LoopDetectedError], None] | None = None,
) -> T:
	"""Executa call() (sem argumentos) com retry/backoff/deteccao de loop.

	Levanta LoopDetectedError se a MESMA falha se repetir
	LOOP_DETECTION_THRESHOLD vezes seguidas. Levanta a excecao original
	quando ela nao e retentavel ou as tentativas se esgotam.
	"""
	last_error: Exception | None = None
	recent_signatures: list[str] = []
	for attempt in range(1, max_attempts + 1):
		try:
			return call()
		except Exception as exc:
			last_error = exc
			recent_signatures.append(_failure_signature(exc))
			window = recent_signatures[-LOOP_DETECTION_THRESHOLD:]
			if len(window) == LOOP_DETECTION_THRESHOLD and len(set(window)) == 1:
				loop_error = LoopDetectedError(window[0], LOOP_DETECTION_THRESHOLD, exc)
				if on_loop_detected:
					on_loop_detected(loop_error)
				raise loop_error from exc
			if attempt >= max_attempts or not is_retryable(exc):
				raise
			delay = retry_delay(exc, attempt - 1)
			if on_retry:
				on_retry(attempt, delay, exc)
			time.sleep(delay)
	raise last_error or RuntimeError("call_with_retry: nenhuma tentativa executada")
