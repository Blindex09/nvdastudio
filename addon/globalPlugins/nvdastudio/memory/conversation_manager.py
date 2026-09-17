from typing import Callable, Optional

from ..utils.logger import get_logger
from ..utils.user_visible_text import sanitize_user_visible_text

_logger = get_logger("conversation")
MODULE_VERSION = "3.0.0"


class ConversationManager:
    """Canal mínimo para narração natural do agente na interface."""

    def __init__(self):
        self._on_status: Optional[Callable[[str], None]] = None

    def set_callbacks(
        self,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._on_status = on_status

    def emit_status(self, message: str) -> None:
        text = sanitize_user_visible_text(message)
        if not text:
            return
        _logger.info("[STATUS] %s", text)
        if self._on_status:
            try:
                self._on_status(text)
            except Exception as exc:
                _logger.debug("[DEBUG] on_status falhou: %s", exc)


conversation = ConversationManager()
