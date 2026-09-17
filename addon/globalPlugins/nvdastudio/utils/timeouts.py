"""Timeout e backoff usados pelo gateway de ferramentas ativo."""

import random

MODULE_VERSION = "2.0.0"

_DEFAULT_TOOL_TIMEOUT = 60.0
_TOOL_TIMEOUTS = {
	"run_addon_tests": 180.0,
	"validate_addon": 180.0,
	"web_search": 180.0,
}


def get_tool_timeout(tool_name: str) -> float:
	"""Retorna o limite operacional da ferramenta canônica."""
	return _TOOL_TIMEOUTS.get(tool_name, _DEFAULT_TOOL_TIMEOUT)


def calculate_backoff_delay(
	attempt: int,
	base_delay: float = 5.0,
	max_delay: float = 120.0,
	jitter_ratio: float = 0.5,
) -> float:
	"""Backoff exponencial com jitter para falhas transitórias de ferramenta."""
	exponent = max(0, attempt - 1)
	delay = max_delay if exponent >= 63 or base_delay <= 0 else min(
		base_delay * (2 ** exponent), max_delay,
	)
	return delay + random.uniform(0, jitter_ratio * delay)  # nosec B311
