import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set

from ..utils.logger import get_logger

_logger = get_logger("tool_system.approval")

# =============================================================================
# PATTERNS DE SEGURANCA (Hermes-style)
# =============================================================================

# Comandos bloqueados INCONDICIONALMENTE — nenhum modo permite passar
_HARDLINE_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"format\s+",
    r"mkfs\.",
    r"dd\s+if=.*of=/dev/",
    r"shutdown",
    r"reboot",
    r"halt",
    r"poweroff",
    r":\(\)\{\s*:\|\:\&\s*\};",  # Fork bomb (escapado para NVDA)
    r"kill\s+-9\s+-1",
    r"pkill\s+-9",
]

# Comandos de risco elevado que entram no fluxo de aprovação
_DANGEROUS_PATTERNS = [
    r"rm\s+-r",
    r"rm\s+--recursive",
    r"rmdir\s+/s",
    r"del\s+/s",
    r"chmod\s+777",
    r"chmod\s+o\+w",
    r"chown\s+-R\s+root",
    r"curl\s+.*\|\s*(sh|bash|python)",
    r"wget\s+.*\|\s*(sh|bash|python)",
    r"python\s+.*\|\s*(sh|bash)",
    r"powershell\s+.*-enc",
    r"reg\s+delete",
    r"regedit\s+/s",
    r"sc\s+delete",
    r"taskkill\s+/f\s+/im",
    r"del\s+/f\s+/q\s+.*\\System",
    r"del\s+/f\s+/q\s+.*\\Windows",
]

# Tools que sempre requerem aprovacao (independentemente de argumentos)
_ALWAYS_APPROVE_TOOLS = {
    "file_writer",
    "code_executor",
    "shell_command",
    "network_request",
    "registry_editor",
    "system_modifier",
}

# Tools que nunca requerem aprovacao (somente leitura/validacao)
_NEVER_APPROVE_TOOLS = {
    "file_reader",
    "ast_parser",
    "nvda_validator",
    "syntax_checker",
    "validate_import",
    "validate_wxpython",
}


# =============================================================================
# DATACLASSES
# =============================================================================

@dataclass
class ApprovalRequest:
    """Solicitação de aprovação."""
    tool_name: str
    arguments: Dict[str, Any]
    reason: str
    risk_level: str  # "low", "medium", "high", "critical"
    pattern_keys: Optional[List[str]] = None

    def __post_init__(self):
        if self.pattern_keys is None:
            self.pattern_keys = []


@dataclass
class _ApprovalEntry:
    """Entrada interna de fila de aprovação (gateway-style)."""
    event: threading.Event
    data: Dict[str, Any]
    result: Optional[str] = None  # "once" | "session" | "always" | "deny"


# =============================================================================
# CLASSE PRINCIPAL
# =============================================================================

class ApprovalWorkflow:
    """
    Sistema de aprovação de ferramentas (Hermes-inspired).

    Fail-closed: silencio, timeout ou falha tecnica = BLOQUEIO.
    """

    def __init__(self, auto_approve_low_risk: bool = True, mode: str = "smart"):
        self._auto_approve_low = auto_approve_low_risk
        self._mode = mode  # "smart", "off", "strict"
        self._approval_callback: Optional[Callable[[ApprovalRequest], bool]] = None

        # Estado persistente por sessao
        self._session_approved: Dict[str, Set[str]] = {}  # session_key -> set de tools
        self._permanent_approved: Set[str] = set()  # allowlist global
        self._session_yolo: Set[str] = set()

        # Fila gateway
        self._gateway_queues: Dict[str, List[_ApprovalEntry]] = {}
        self._pending: Dict[str, Dict[str, Any]] = {}

        self._lock = threading.Lock()

    def set_approval_callback(self, callback: Callable[[ApprovalRequest], bool]):
        """Define callback de aprovação (UI/dialog)."""
        self._approval_callback = callback

    # -------------------------------------------------------------------------
    # Detecção de risco
    # -------------------------------------------------------------------------

    def analyze_risk(self, tool_name: str, arguments: Dict[str, Any]) -> tuple[str, str, List[str]]:
        """
        Analisa o risco de uma tool.

        Returns:
            (risk_level, reason, pattern_keys)
        """
        pattern_keys = []

        # 1. Hardline — bloqueio incondicional
        arg_str = self._args_to_string(arguments)
        for pattern in _HARDLINE_PATTERNS:
            if re.search(pattern, arg_str, re.IGNORECASE):
                pattern_keys.append(f"hardline:{pattern[:30]}")
                return "critical", "Comando catastrofico detectado (hardline)", pattern_keys

        # 2. Sempre aprovar tools especificas
        if tool_name in _ALWAYS_APPROVE_TOOLS:
            return "high", f"Tool '{tool_name}' sempre requer aprovacao", []

        # 3. Nunca aprovar tools especificas
        if tool_name in _NEVER_APPROVE_TOOLS:
            return "low", f"Tool '{tool_name}' de baixo risco", []

        # 4. Padroes perigosos nos argumentos
        for pattern in _DANGEROUS_PATTERNS:
            if re.search(pattern, arg_str, re.IGNORECASE):
                pattern_keys.append(f"dangerous:{pattern[:30]}")
                return "high", "Padrao perigoso detectado nos argumentos", pattern_keys

        # 5. Argumentos sensiveis
        if self._has_risky_arguments(arguments):
            return "medium", "Argumentos sensiveis detectados", []

        # 6. Modo auto-approve
        if self._auto_approve_low:
            return "low", "Risco baixo (auto-aprovado)", []

        return "medium", "Politica padrao requer aprovacao", []

    def _args_to_string(self, arguments: Dict[str, Any]) -> str:
        """Converte argumentos para string para pattern matching."""
        parts = []
        for key, value in arguments.items():
            if isinstance(value, str):
                parts.append(f"{key}={value}")
            elif isinstance(value, (list, dict)):
                parts.append(f"{key}={str(value)[:200]}")
        return " ".join(parts)

    def _has_risky_arguments(self, arguments: Dict[str, Any]) -> bool:
        """Verifica se argumentos contem padroes sensiveis."""
        risky_patterns = {
            "path": ["..", ":", "~", "\\\\"],
            "command": ["rm", "del", "chmod", "sudo", "format", "mkfs"],
            "url": ["http://", "ftp://"],
            "code": ["eval(", "exec(", "__import__", "subprocess", "os.system"],
        }

        for key, value in arguments.items():
            if not isinstance(value, str):
                continue

            for pattern_key, patterns in risky_patterns.items():
                if pattern_key in key.lower():
                    for pattern in patterns:
                        if pattern in value.lower():
                            return True

        return False

    # -------------------------------------------------------------------------
    # Aprovação
    # -------------------------------------------------------------------------

    def should_approve(self, tool_name: str, arguments: Dict[str, Any], session_key: str = "default") -> tuple[bool, str]:
        """
        Decide se uma tool deve ser aprovada.

        Returns:
            (approved, reason)

        BUGFIX (achado de auditoria 2026-08-04, escrevendo os primeiros
        testes deste modulo -- nunca tinha teste dedicado apesar de ser
        safety-critical): o hardline SO era checado depois da allowlist
        permanente/de sessao. Ou seja: uma vez que uma tool (ex:
        "shell_command") fosse aprovada permanentemente, um argumento
        hardline futuro (ex: "rm -rf /") passava direto, porque
        analyze_risk() nunca chegava a rodar -- contradizendo o proprio
        docstring do modulo ("hardline e bloqueio incondicional, nenhum
        modo permite passar"). Corrigido: hardline agora e o PRIMEIRO
        gate, antes de mode/YOLO/allowlist -- nada contorna, por design.
        """
        # Hardline e SEMPRE o primeiro gate -- incondicional, nenhum modo,
        # allowlist ou YOLO pode contornar.
        risk_level, reason, _pattern_keys = self.analyze_risk(tool_name, arguments)
        if risk_level == "critical":
            return False, f"BLOQUEADO (hardline): {reason}"

        # Modo off = aprova tudo (hardline ja foi checado acima)
        if self._mode == "off":
            return True, "Modo off (auto-aprovado)"

        # YOLO mode (hardline ja foi checado acima)
        if session_key in self._session_yolo:
            return True, "YOLO mode"

        # Verifica aprovacoes persistentes
        with self._lock:
            if tool_name in self._permanent_approved:
                return True, "Permitido permanentemente (allowlist)"

            session_approved = self._session_approved.get(session_key, set())
            if tool_name in session_approved:
                return True, "Permitido para esta sessao"

        if risk_level == "low":
            return True, reason

        # Risco medio/alto — requer aprovacao
        return False, f"APPROVAL_REQUIRED: {reason}"

    def request_approval(self, tool_name: str, arguments: Dict[str, Any], session_key: str = "default") -> bool:
        """
        Solicita aprovacao do usuario.

        Returns:
            True se aprovado, False se negado
        """
        risk_level, reason, pattern_keys = self.analyze_risk(tool_name, arguments)

        # Verifica hardline
        if risk_level == "critical":
            _logger.error("[BLOCKED] %s: %s", tool_name, reason)
            return False

        # Verifica se ja esta aprovado
        approved, approval_reason = self.should_approve(tool_name, arguments, session_key)
        if approved:
            _logger.info("[APPROVAL] %s: %s", tool_name, approval_reason)
            return True

        # Cria requisicao
        request = ApprovalRequest(
            tool_name=tool_name,
            arguments=arguments,
            reason=reason,
            risk_level=risk_level,
            pattern_keys=pattern_keys,
        )

        # Sem callback = negar (fail-closed)
        if not self._approval_callback:
            _logger.warning("[BLOCKED] %s: Nenhum callback de aprovacao definido", tool_name)
            return False

        # Chama callback
        try:
            result = self._approval_callback(request)
            _logger.info("[APPROVAL] %s: %s", tool_name, "APROVADO" if result else "NEGADO")
            return result
        except Exception as e:
            _logger.error("[ERRO] Approval callback falhou: %s", e)
            return False

    def approve_once(self, tool_name: str, session_key: str = "default"):
        """Aprova uma tool para esta execucao."""
        pass  # O executor ja vai tentar de novo

    def _approve_session_locked(self, tool_name: str, session_key: str):
        """Corpo de approve_session() sem adquirir o lock -- para chamadores
        (resolve_pending()) que ja seguram self._lock. Ver 2.2.0."""
        if session_key not in self._session_approved:
            self._session_approved[session_key] = set()
        self._session_approved[session_key].add(tool_name)
        _logger.info("[APPROVAL] %s aprovada para sessao %s", tool_name, session_key)

    def approve_session(self, tool_name: str, session_key: str = "default"):
        """Aprova uma tool para toda a sessao."""
        with self._lock:
            self._approve_session_locked(tool_name, session_key)

    def _approve_always_locked(self, tool_name: str):
        """Corpo de approve_always() sem adquirir o lock -- ver 2.2.0."""
        self._permanent_approved.add(tool_name)
        _logger.info("[APPROVAL] %s aprovada permanentemente", tool_name)

    def approve_always(self, tool_name: str):
        """Aprova uma tool permanentemente."""
        with self._lock:
            self._approve_always_locked(tool_name)

    def deny(self, tool_name: str, session_key: str = "default"):
        """Nega explicitamente uma tool."""
        _logger.info("[APPROVAL] %s negada", tool_name)

    def enable_yolo(self, session_key: str = "default"):
        """Ativa YOLO mode para uma sessao (bypass exceto hardline)."""
        with self._lock:
            self._session_yolo.add(session_key)
            _logger.warning("[YOLO] Modo YOLO ativado para sessao %s", session_key)

    def disable_yolo(self, session_key: str = "default"):
        """Desativa YOLO mode."""
        with self._lock:
            self._session_yolo.discard(session_key)
            _logger.info("[YOLO] Modo YOLO desativado para sessao %s", session_key)

    # -------------------------------------------------------------------------
    # Gateway queues (para aprovacao assíncrona)
    # -------------------------------------------------------------------------

    def submit_pending(self, tool_name: str, arguments: Dict[str, Any], session_key: str = "default") -> _ApprovalEntry:
        """Submete um pedido de aprovacao para a fila do gateway."""
        entry = _ApprovalEntry(
            event=threading.Event(),
            data={
                "tool_name": tool_name,
                "arguments": arguments,
                "session_key": session_key,
                "submitted_at": time.time(),
            },
        )

        with self._lock:
            if session_key not in self._gateway_queues:
                self._gateway_queues[session_key] = []
            self._gateway_queues[session_key].append(entry)
            self._pending[session_key] = {
                "tool_name": tool_name,
                "submitted_at": time.time(),
            }

        return entry

    def resolve_pending(self, session_key: str, result: str) -> bool:
        """Resolve um pedido pendente (chamado pelo gateway/UI)."""
        with self._lock:
            queue = self._gateway_queues.get(session_key, [])
            if not queue:
                return False

            entry = queue.pop(0)
            entry.result = result
            entry.event.set()

            # Aplica aprovacao -- chama as versoes _locked (nao approve_session/
            # approve_always) porque este bloco ja esta dentro do with self._lock
            # acima; chamar as publicas re-adquiriria o mesmo Lock nao-reentrante
            # e travaria pra sempre (deadlock real corrigido em 2.2.0).
            if result in ("once", "session"):
                tool_name = entry.data["tool_name"]
                self._approve_session_locked(tool_name, session_key)
            elif result == "always":
                tool_name = entry.data["tool_name"]
                self._approve_always_locked(tool_name)

            return True

    def get_pending(self, session_key: str = "default") -> Optional[Dict[str, Any]]:
        """Retorna o pedido pendente de uma sessao."""
        with self._lock:
            return self._pending.get(session_key)

    def clear_session(self, session_key: str = "default"):
        """Limpa estado de uma sessao."""
        with self._lock:
            self._session_approved.pop(session_key, None)
            self._session_yolo.discard(session_key)
            self._gateway_queues.pop(session_key, None)
            self._pending.pop(session_key, None)
