"""Logging of the MCP server.

In an MCP server over stdio, stdout belongs to the protocol: any line written
there corrupts the conversation with the client. So logging always goes to
stderr and, if the person sets NVDASTUDIO_LOG_DIR, also to a daily file in
that folder.
"""

import logging
import os
import re
import sys
from datetime import datetime

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"sk-ant-[A-Za-z0-9_-]{20,}",
        r"sk-[A-Za-z0-9_-]{20,}",
        r"AIza[A-Za-z0-9_-]{20,}",
        r"(?i)bearer\s+[A-Za-z0-9._-]{20,}",
        r"gsk_[A-Za-z0-9]{20,}",
        r"ghp_[A-Za-z0-9]{20,}",
    )
)


def redact_secrets(text: str) -> str:
    """Replaces with a marker whatever looks like an API key or token."""
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))


_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"


def get_logger(name: str) -> logging.Logger:
    """Returns the `nvdastudio.<name>` logger, writing to stderr (and an optional file)."""
    logger = logging.getLogger(f"nvdastudio.{name}")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    formatter = _RedactingFormatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.INFO)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)

    log_dir = os.environ.get("NVDASTUDIO_LOG_DIR", "")
    if log_dir:
        try:
            os.makedirs(log_dir, exist_ok=True)
            name_file = f"nvdastudio_{datetime.now().strftime('%Y-%m-%d')}.log"
            file_handler = logging.FileHandler(
                os.path.join(log_dir, name_file), encoding="utf-8", errors="replace"
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError:
            logger.warning("NVDASTUDIO_LOG_DIR inaccessible: %s", log_dir)
    return logger


def log_decision(logger: logging.Logger, decision: str, context: str = "") -> None:
    """Logs a relevant decision of the server."""
    logger.info("[DECISION] %s context=%s", decision, context)
