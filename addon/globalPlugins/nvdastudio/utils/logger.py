import glob
import logging
import os
import re
import time
from datetime import datetime

# logHandler disponivel apenas no ambiente NVDA
try:
	from logHandler import log as _nvda_log  # type: ignore[import]
except ImportError:
	_nvda_log = None  # type: ignore[assignment]

MODULE_VERSION = "1.2.0"

_LOG_RETENTION_DAYS = 30

_SECRET_PATTERNS: tuple[re.Pattern, ...] = tuple(
	re.compile(p) for p in (
		r"sk-ant-[A-Za-z0-9_-]{20,}",
		r"sk-[A-Za-z0-9_-]{20,}",
		r"AIza[A-Za-z0-9_-]{20,}",
		r"(?i)bearer\s+[A-Za-z0-9._-]{20,}",
		r"gsk_[A-Za-z0-9]{20,}",
		r"tvly-[A-Za-z0-9_-]{20,}",
	)
)


def _redact_secrets(text: str) -> str:
	"""Substitui trechos com formato de chave/token de API por um marcador.

	Deteccao por FORMATO (prefixo conhecido de provedor, comprimento
	minimo), nao por lista de palavras de dominio -- Regra 5 do README.
	"""
	if not text:
		return text
	redacted = text
	for pattern in _SECRET_PATTERNS:
		redacted = pattern.sub("[REDACTED]", redacted)
	return redacted

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_MODULE_DIR, "..", "..", "..", ".."))
_PROJECT_LOG_DIR = os.path.join(_PROJECT_ROOT, "logs")
_NVDA_LOG_DIR = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "nvda", "nvdastudio_logs")

# _PROJECT_ROOT so e valido quando o modulo roda a partir do checkout de dev
# (addon/globalPlugins/nvdastudio/utils/). No addon instalado dentro do NVDA
# (addons/nvdastudio/globalPlugins/nvdastudio/utils/, um nivel mais raso, sem
# a pasta "addon/"), o mesmo calculo de 4 niveis acima aponta para
# %APPDATA%/nvda/addons/ e cria um "logs/" ali -- que o NVDA tenta carregar
# como addon no boot e falha (sem manifest.ini). Deteccao: so a raiz do
# checkout de dev tem manifest.ini E build.py diretamente nela.
_IS_DEV_CHECKOUT = os.path.isfile(os.path.join(_PROJECT_ROOT, "manifest.ini")) and os.path.isfile(
	os.path.join(_PROJECT_ROOT, "build.py")
)


def _prune_old_logs(log_dir: str, retention_days: int = _LOG_RETENTION_DAYS) -> None:
	"""Remove arquivos `nvdastudio_*.log` com mais de `retention_days` dias.

	Fail-open: qualquer erro de I/O (permissao, arquivo em uso) e ignorado --
	podar log antigo nunca deve derrubar a inicializacao do logger.
	"""
	cutoff = time.time() - (retention_days * 86400)
	try:
		for path in glob.glob(os.path.join(log_dir, "nvdastudio_*.log")):
			try:
				if os.path.getmtime(path) < cutoff:
					os.remove(path)
			except OSError:
				continue
	except OSError:
		pass


def _ensure_log_dir():
	if _IS_DEV_CHECKOUT:
		os.makedirs(_PROJECT_LOG_DIR, exist_ok=True)
		_prune_old_logs(_PROJECT_LOG_DIR)
	os.makedirs(_NVDA_LOG_DIR, exist_ok=True)
	_prune_old_logs(_NVDA_LOG_DIR)


def _add_file_handler(logger: logging.Logger, log_dir: str, formatter: logging.Formatter) -> None:
	log_file = os.path.join(
		log_dir,
		f"nvdastudio_{datetime.now().strftime('%Y-%m-%d')}.log"
	)
	file_handler = logging.FileHandler(log_file, encoding="cp1252", errors="replace")
	file_handler.setLevel(logging.DEBUG)
	file_handler.setFormatter(formatter)
	logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
	"""
	Retorna logger configurado para o modulo informado.
	Grava em arquivo diario e no log do NVDA (via logHandler).
	"""
	_ensure_log_dir()

	logger = logging.getLogger(f"nvdastudio.{name}")
	if logger.handlers:
		return logger

	logger.setLevel(logging.DEBUG)

	formatter = logging.Formatter(
		fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
		datefmt="%Y-%m-%d %H:%M:%S"
	)
	if _IS_DEV_CHECKOUT:
		_add_file_handler(logger, _PROJECT_LOG_DIR, formatter)
	_add_file_handler(logger, _NVDA_LOG_DIR, formatter)

	# Integra com o log do NVDA se disponivel
	if _nvda_log is not None:
		nvda_handler = logging.Handler()
		nvda_handler.setLevel(logging.INFO)

		def emit(record: logging.LogRecord, _nvda=_nvda_log) -> None:
			msg = record.getMessage()
			if record.levelno >= logging.ERROR:
				_nvda.error(msg)
			elif record.levelno >= logging.WARNING:
				_nvda.warning(msg)
			else:
				_nvda.info(msg)

		nvda_handler.emit = emit  # type: ignore[method-assign]
		logger.addHandler(nvda_handler)

	return logger


def log_llm_call(logger: logging.Logger, prompt_version: str, input_text: str):
	"""Registra input enviado a LLM. Obrigatorio por spec."""
	safe = _redact_secrets(input_text[:500]).encode("cp1252", errors="replace").decode("cp1252")
	logger.debug(
		"[LLM-INPUT] prompt_version=%s chars=%d preview=%s",
		prompt_version, len(input_text), safe
	)


def log_llm_response(logger: logging.Logger, prompt_version: str, output_text: str):
	"""Registra output recebido da LLM. Obrigatorio por spec."""
	safe = _redact_secrets(output_text[:500]).encode("cp1252", errors="replace").decode("cp1252")
	logger.debug(
		"[LLM-OUTPUT] prompt_version=%s chars=%d preview=%s",
		prompt_version, len(output_text), safe
	)


def log_decision(logger: logging.Logger, decision: str, context: str = ""):
	"""Registra decisao relevante do sistema."""
	logger.info("[DECISION] %s context=%s", decision, context)
