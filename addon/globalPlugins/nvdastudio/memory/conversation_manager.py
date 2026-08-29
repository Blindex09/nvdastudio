import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from ..utils.logger import get_logger
from ..utils.user_visible_text import sanitize_user_visible_text

_logger = get_logger("conversation")
MODULE_VERSION = "2.3.0"

# Achado de auditoria 2026-08-04 (analise de log real de producao + pesquisa
# de UX acessivel): _MAX_STATUS_LENGTH cortava por CONTAGEM DE CARACTERES,
# nao por limite de frase/palavra -- e isso acontecia ANTES do texto chegar
# na UI, entao a mutilacao ficava permanente no historico navegavel (nao e
# so cosmetico, e corrupcao de dado). Confirmado em log real: "...um
# repositorio chamado GemVDA que integra Gemini c" (corta em "c", era
# "com" ou similar). LiveNarrator (sub_agents/_base.py) ja entrega frases
# completas antes de chegar aqui -- o corte so acontecia POR CIMA disso, e
# o consumidor que precisava de texto curto (studio_dialog._set_status(),
# barra de status) virou no-op ha varias versoes (evita SetLabel() disparar
# EVENT_OBJECT_NAMECHANGE e o NVDA narrar sozinho) -- ninguem mais renderiza
# esse texto num widget de largura fixa. Constante removida, truncamento
# removido: emit_status() agora entrega a frase completa pro historico.


@dataclass
class ConversationMessage:
    """Uma mensagem na conversa."""
    role: str  # "ia" ou "sistema"
    text: str
    timestamp: float


class ConversationManager:
    """
    Gerenciador de conversação agentica (Hermes-inspired).

    3 sinais emitidos, cada um roteado pela UI (nao decidido aqui):
    - STATUS: curto, so no historico (sem fala automatica)
    - TOOL PROGRESS: heartbeat periodico, so na barra de status (efemero)
    - CONTEUDO: longo, so no historico; o usuario le com as setas
    """

    def __init__(self):
        self._history: List[ConversationMessage] = []
        self._current_tool: Optional[str] = None
        self._tool_start_time: float = 0.0
        self._lock = threading.Lock()

        # Callbacks de UI
        self._on_status: Optional[Callable[[str], None]] = None
        self._on_tool_progress: Optional[Callable[[str, int], None]] = None
        self._on_content: Optional[Callable[[str], None]] = None

    def set_callbacks(
        self,
        on_status: Optional[Callable[[str], None]] = None,
        on_tool_progress: Optional[Callable[[str, int], None]] = None,
        on_content: Optional[Callable[[str], None]] = None,
    ):
        """Configura callbacks de UI."""
        self._on_status = on_status
        self._on_tool_progress = on_tool_progress
        self._on_content = on_content

    # -------------------------------------------------------------------------
    # Emissão de STATUS (curto, registrado no histórico, sem fala automática)
    # -------------------------------------------------------------------------

    def emit_status(self, message: str) -> None:
        """
        Emite um status curto. A UI registra no histórico
        (studio_dialog._handle_status), sem falar automaticamente. Exemplos:
        "Pesquisando...", "Plano aprovado", "Executando...", e as frases de
        narrate() (sub_agents/_base.py) narrando o que o agente faz agora.
        """
        text = sanitize_user_visible_text(message)
        _logger.info("[STATUS] %s", text)

        if self._on_status:
            try:
                self._on_status(text)
            except Exception as e:
                _logger.debug("[DEBUG] on_status falhou: %s", e)

    # -------------------------------------------------------------------------
    # Emissão de TOOL PROGRESS (com timer)
    # -------------------------------------------------------------------------

    def emit_tool_start(self, tool_name: str) -> None:
        """Inicia contagem de tempo para uma tool."""
        self._current_tool = tool_name
        self._tool_start_time = time.time()

        # Heartbeat: so na barra de status da UI (efemero), nao vai para o log/histórico.
        _logger.info("[TOOL] %s", tool_name)

    def emit_tool_progress(self, detail: str = "") -> None:
        """Atualiza progresso da tool atual."""
        if not self._current_tool:
            return

        elapsed = int((time.time() - self._tool_start_time) * 1000)
        text = f"{self._current_tool}"
        if detail:
            text += f": {detail}"

        if self._on_tool_progress:
            try:
                self._on_tool_progress(text, elapsed)
            except Exception as e:
                _logger.debug("[DEBUG] on_tool_progress falhou: %s", e)

    def emit_tool_end(self, success: bool = True) -> None:
        """Finaliza tool atual — apenas para o timer, sem emitir mensagem de conclusão."""
        if not self._current_tool:
            return

        elapsed = int((time.time() - self._tool_start_time) * 1000)
        _logger.info("[TOOL] %s %s (%dms)", self._current_tool, "OK" if success else "FAIL", elapsed)
        self._current_tool = None
        self._tool_start_time = 0.0

    # -------------------------------------------------------------------------
    # Emissão de CONTEUDO (longo, histórico, NAO TTS)
    # -------------------------------------------------------------------------

    def emit_content(self, message: str, role: str = "ia") -> None:
        """
        Emite conteúdo longo. Só vai para histórico, NÃO TTS.
        Exemplos: respostas completas do LLM, explicações, código.
        """
        message = sanitize_user_visible_text(message)
        if not message:
            return
        with self._lock:
            self._history.append(ConversationMessage(
                role=role, text=message, timestamp=time.time()
            ))

        _logger.info("[CONTENT] %d chars", len(message))

        if self._on_content:
            try:
                self._on_content(message)
            except Exception as e:
                _logger.debug("[DEBUG] on_content falhou: %s", e)

    # -------------------------------------------------------------------------
    # Utilitários
    # -------------------------------------------------------------------------

    def get_history(self) -> List[ConversationMessage]:
        """Retorna histórico completo."""
        with self._lock:
            return list(self._history)

    def get_recent_content(self, n: int = 5) -> List[ConversationMessage]:
        """Retorna últimas N mensagens de conteúdo."""
        with self._lock:
            return self._history[-n:]

    def clear(self) -> None:
        """Limpa histórico."""
        with self._lock:
            self._history.clear()
            self._current_tool = None


# Instância global
conversation = ConversationManager()
