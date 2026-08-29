import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .logger import get_logger

_logger = get_logger("tasks")
MODULE_VERSION = "1.0.0"

VALID_STATUSES = {"pending", "in_progress", "completed", "failed", "cancelled"}

STATUS_MARKERS = {
    "pending": "[ ]",
    "in_progress": "[>]",
    "completed": "[x]",
    "failed": "[!]",
    "cancelled": "[~]",
}


@dataclass
class TaskItem:
    """Uma tarefa no pipeline."""
    task_id: str
    content: str
    status: str = "pending"
    step_type: str = ""      # Tipo do step (code_generation, etc.)
    elapsed_ms: int = 0      # Tempo decorrido
    retries: int = 0
    issues: List[str] = field(default_factory=list)


class TaskTracker:
    """
    Rastreador de tarefas do pipeline (Hermes-inspired TodoStore).

    - Lista ordenada de tarefas (ordem = prioridade)
    - Apenas UMA tarefa in_progress por vez
    - Injeta lista ativa no system prompt apos compressao
    - Resumo humano do progresso para o usuario
    """

    def __init__(self):
        self._items: List[TaskItem] = []
        self._lock = threading.Lock()

    def add(self, task_id: str, content: str, step_type: str = "") -> TaskItem:
        """Adiciona nova tarefa ao final da lista."""
        with self._lock:
            # Evita duplicatas de ID
            for item in self._items:
                if item.task_id == task_id:
                    return item

            task = TaskItem(
                task_id=task_id,
                content=content,
                status="pending",
                step_type=step_type,
            )
            self._items.append(task)
            _logger.debug("[TASK] Adicionada: %s — %s", task_id, content[:60])
            return task

    def start(self, task_id: str) -> Optional[TaskItem]:
        """Marca uma tarefa como in_progress."""
        with self._lock:
            # Primeiro, finaliza qualquer tarefa in_progress atual
            for item in self._items:
                if item.status == "in_progress":
                    item.status = "completed"

            # Marca a nova
            for item in self._items:
                if item.task_id == task_id:
                    item.status = "in_progress"
                    _logger.info("[TASK] Iniciada: %s", task_id)
                    return item
            return None

    def complete(self, task_id: str, success: bool = True) -> Optional[TaskItem]:
        """Marca uma tarefa como completed ou failed."""
        with self._lock:
            for item in self._items:
                if item.task_id == task_id:
                    item.status = "completed" if success else "failed"
                    _logger.info("[TASK] %s: %s", "Concluida" if success else "Falhou", task_id)
                    return item
            return None

    def cancel(self, task_id: str) -> Optional[TaskItem]:
        """Cancela uma tarefa."""
        with self._lock:
            for item in self._items:
                if item.task_id == task_id:
                    item.status = "cancelled"
                    _logger.info("[TASK] Cancelada: %s", task_id)
                    return item
            return None

    def update_issues(self, task_id: str, issues: List[str]):
        """Adiciona problemas a uma tarefa."""
        with self._lock:
            for item in self._items:
                if item.task_id == task_id:
                    item.issues.extend(issues)
                    item.retries += 1
                    break

    def get_active(self) -> List[TaskItem]:
        """Retorna tarefas pendentes ou em progresso."""
        with self._lock:
            return [item for item in self._items if item.status in ("pending", "in_progress")]

    def get_completed(self) -> List[TaskItem]:
        """Retorna tarefas concluidas."""
        with self._lock:
            return [item for item in self._items if item.status == "completed"]

    def get_summary(self) -> Dict[str, int]:
        """Contagem por status."""
        with self._lock:
            return {
                "total": len(self._items),
                "pending": sum(1 for i in self._items if i.status == "pending"),
                "in_progress": sum(1 for i in self._items if i.status == "in_progress"),
                "completed": sum(1 for i in self._items if i.status == "completed"),
                "failed": sum(1 for i in self._items if i.status == "failed"),
                "cancelled": sum(1 for i in self._items if i.status == "cancelled"),
            }

    def format_for_user(self) -> str:
        """Formata lista de tarefas para exibicao ao usuario."""
        with self._lock:
            if not self._items:
                return "Nenhuma tarefa."

            lines = ["\n[Progresso do Pipeline]"]
            for item in self._items:
                marker = STATUS_MARKERS.get(item.status, "[?]")
                lines.append(f"  {marker} {item.task_id}: {item.content[:50]}")

            summary = self.get_summary()
            lines.append(f"\nTotal: {summary['total']} | Concluidas: {summary['completed']} | Falhas: {summary['failed']}")
            return "\n".join(lines)

    def format_for_injection(self) -> Optional[str]:
        """
        Formata tarefas ativas para injecao no system prompt.
        Chamado apos compressao de contexto.
        """
        with self._lock:
            active = [i for i in self._items if i.status in ("pending", "in_progress")]
            if not active:
                return None

            lines = ["[Lista de tarefas ativas preservada apos compressao]"]
            for item in active:
                marker = STATUS_MARKERS.get(item.status, "[?]")
                lines.append(f"- {marker} {item.task_id}: {item.content[:60]} ({item.status})")

            return "\n".join(lines)

    def format_progress_message(self) -> str:
        """Mensagem curta de progresso para TTS."""
        with self._lock:
            summary = self.get_summary()
            total = summary["total"]
            done = summary["completed"]
            failed = summary["failed"]
            current = next((i for i in self._items if i.status == "in_progress"), None)
            failed_suffix = f" ({failed} falharam)" if failed else ""

            if current:
                return f"Etapa {done+1} de {total}: {current.content[:40]}...{failed_suffix}"
            elif done >= total:
                return f"Concluido: {done}/{total} etapas.{failed_suffix}"
            else:
                return f"Progresso: {done}/{total} concluidas.{failed_suffix}"

    def clear(self):
        """Limpa todas as tarefas."""
        with self._lock:
            self._items.clear()
            _logger.info("[TASK] Todas as tarefas limpas.")

    def to_dict(self) -> List[Dict[str, Any]]:
        """Serializa para dicionario."""
        with self._lock:
            return [
                {
                    "id": item.task_id,
                    "content": item.content,
                    "status": item.status,
                    "step_type": item.step_type,
                    "retries": item.retries,
                }
                for item in self._items
            ]

    def from_dict(self, data: List[Dict[str, Any]]):
        """Carrega de dicionario."""
        with self._lock:
            self._items = []
            for d in data:
                self._items.append(TaskItem(
                    task_id=d.get("id", ""),
                    content=d.get("content", ""),
                    status=d.get("status", "pending"),
                    step_type=d.get("step_type", ""),
                    retries=d.get("retries", 0),
                ))


# Instancia global
task_tracker = TaskTracker()
