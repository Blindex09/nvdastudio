import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from croniter import croniter
    _CRONITER_AVAILABLE = True
except ImportError:
    _CRONITER_AVAILABLE = False
    croniter = None

from .logger import get_logger

MODULE_VERSION = "2.1.0"
_logger = get_logger("scheduler")

# Path para persistência
_SCHEDULER_DIR = Path(os.path.expanduser("~")) / "AppData" / "Roaming" / "NVDAStudio" / "scheduler"
_SCHEDULES_FILE = _SCHEDULER_DIR / "schedules.json"
_LOGS_DIR = _SCHEDULER_DIR / "logs"


@dataclass
class ScheduledTask:
    """Tarefa agendada."""
    id: str
    name: str
    description: str
    cron_expr: str  # Expressão cron ou "interval:N" para intervalo
    handler: str  # Nome da função handler
    enabled: bool = True
    last_run: str = ""
    next_run: str = ""
    run_count: int = 0
    success_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskExecution:
    """Registro de execução de tarefa."""
    task_id: str
    timestamp: str
    success: bool
    duration_ms: int
    output: Any = None
    error: Optional[str] = None


class Scheduler:
    """
    Scheduler de tarefas em background.

    Suporta:
      - Expressões cron (se croniter disponível)
      - Intervalos fixos (ex: "interval:1800" = 30min)
      - Execução em thread separada
      - Persistência de schedules
    """

    def __init__(self):
        self._tasks: Dict[str, ScheduledTask] = {}
        self._handlers: Dict[str, Callable] = {}
        self._execution_history: List[TaskExecution] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._handlers_lock = threading.Lock()

        # Cria diretórios
        _SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)

        # Carrega schedules persistidos
        self._load_schedules()

    def register_handler(self, name: str, handler: Callable):
        """Registra um handler de tarefa."""
        with self._handlers_lock:
            self._handlers[name] = handler
            _logger.info("[SCHEDULER] Handler registrado: %s", name)

    def schedule_task(self, task: ScheduledTask) -> bool:
        """Agenda uma tarefa."""
        with self._lock:
            # Valida handler
            with self._handlers_lock:
                if task.handler not in self._handlers:
                    _logger.error("[ERRO] Handler não encontrado: %s", task.handler)
                    return False

            # Calcula próxima execução
            task.next_run = self._calculate_next_run(task.cron_expr)

            self._tasks[task.id] = task
            self._save_schedules()

            _logger.info(
                "[SCHEDULER] Tarefa agendada: %s (cron: %s, próxima: %s)",
                task.name, task.cron_expr, task.next_run
            )
            return True

    def unschedule_task(self, task_id: str) -> bool:
        """Remove tarefa agendada."""
        with self._lock:
            if task_id not in self._tasks:
                return False

            del self._tasks[task_id]
            self._save_schedules()

            _logger.info("[SCHEDULER] Tarefa removida: %s", task_id)
            return True

    def enable_task(self, task_id: str) -> bool:
        """Ativa tarefa."""
        with self._lock:
            if task_id not in self._tasks:
                return False

            self._tasks[task_id].enabled = True
            self._save_schedules()
            return True

    def disable_task(self, task_id: str) -> bool:
        """Desativa tarefa."""
        with self._lock:
            if task_id not in self._tasks:
                return False

            self._tasks[task_id].enabled = False
            self._save_schedules()
            return True

    def start(self):
        """Inicia scheduler em background."""
        if self._running:
            _logger.warning("[AVISO] Scheduler já está rodando")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        _logger.info("[SCHEDULER] Iniciado em background")

    def stop(self):
        """Para scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        _logger.info("[SCHEDULER] Parado")

    def _run_loop(self):
        """Loop principal do scheduler."""
        while self._running:
            try:
                self._check_and_run_tasks()
            except Exception as e:
                _logger.error("[ERRO] Scheduler loop falhou: %s", e)

            # Dorme 1 minuto
            time.sleep(60)

    def _check_and_run_tasks(self):
        """Verifica e executa tarefas prontas."""
        now = datetime.now()

        with self._lock:
            for task in list(self._tasks.values()):
                if not task.enabled:
                    continue

                if not task.next_run:
                    continue

                try:
                    next_run = datetime.fromisoformat(task.next_run)
                except ValueError:
                    _logger.error("[ERRO] Invalid next_run para %s: %s", task.id, task.next_run)
                    continue

                if now >= next_run:
                    # Executa tarefa
                    self._execute_task(task)

                    # Calcula próxima execução
                    task.next_run = self._calculate_next_run(task.cron_expr)
                    task.last_run = now.isoformat()

            self._save_schedules()

    def _execute_task(self, task: ScheduledTask):
        """Executa uma tarefa."""
        start_time = time.time()

        _logger.info("[SCHEDULER] Executando: %s", task.name)

        try:
            # Pega handler
            with self._handlers_lock:
                handler = self._handlers.get(task.handler)

            if not handler:
                raise Exception(f"Handler não encontrado: {task.handler}")

            # Executa
            output = handler(task)

            duration_ms = int((time.time() - start_time) * 1000)

            # Registra execução
            execution = TaskExecution(
                task_id=task.id,
                timestamp=datetime.now().isoformat(),
                success=True,
                duration_ms=duration_ms,
                output=output,
            )

            # Atualiza stats
            task.run_count += 1
            task.success_count += 1

            _logger.info(
                "[SCHEDULER] %s completada em %dms",
                task.name, duration_ms
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)

            execution = TaskExecution(
                task_id=task.id,
                timestamp=datetime.now().isoformat(),
                success=False,
                duration_ms=duration_ms,
                error=str(e),
            )

            _logger.error(
                "[SCHEDULER] %s falhou: %s",
                task.name, e
            )

        # Salva histórico
        self._execution_history.append(execution)
        self._save_execution_log(execution)

        # Mantém histórico limitado
        if len(self._execution_history) > 1000:
            self._execution_history = self._execution_history[-1000:]

    def _calculate_next_run(self, cron_expr: str) -> str:
        """Calcula próxima execução."""
        now = datetime.now()

        # Intervalo fixo
        if cron_expr.startswith("interval:"):
            try:
                seconds = int(cron_expr.split(":")[1])
                next_run = now + timedelta(seconds=seconds)
                return next_run.isoformat()
            except (ValueError, IndexError):
                _logger.error("[ERRO] Intervalo inválido: %s", cron_expr)
                return ""

        # Expressão cron (requer croniter)
        if _CRONITER_AVAILABLE and croniter:
            try:
                cron = croniter(cron_expr, now)
                next_run = cron.get_next(datetime)
                return next_run.isoformat()
            except Exception as e:
                _logger.error("[ERRO] Cron inválido: %s (%s)", cron_expr, e)
                return ""

        _logger.warning("[AVISO] croniter não disponível — usando fallback 1 hora")
        return (now + timedelta(hours=1)).isoformat()

    def _save_schedules(self):
        """Salva schedules em arquivo."""
        try:
            data = {
                task_id: {
                    "id": task.id,
                    "name": task.name,
                    "description": task.description,
                    "cron_expr": task.cron_expr,
                    "handler": task.handler,
                    "enabled": task.enabled,
                    "last_run": task.last_run,
                    "next_run": task.next_run,
                    "run_count": task.run_count,
                    "success_count": task.success_count,
                    "created_at": task.created_at,
                    "metadata": task.metadata,
                }
                for task_id, task in self._tasks.items()
            }

            _SCHEDULES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            _logger.error("[ERRO] Falha ao salvar schedules: %s", e)

    def _load_schedules(self):
        """Carrega schedules do arquivo."""
        if not _SCHEDULES_FILE.exists():
            return

        try:
            data = json.loads(_SCHEDULES_FILE.read_text(encoding="utf-8"))

            for task_id, task_data in data.items():
                task = ScheduledTask(
                    id=task_data["id"],
                    name=task_data["name"],
                    description=task_data["description"],
                    cron_expr=task_data["cron_expr"],
                    handler=task_data["handler"],
                    enabled=task_data.get("enabled", True),
                    last_run=task_data.get("last_run", ""),
                    next_run=task_data.get("next_run", ""),
                    run_count=task_data.get("run_count", 0),
                    success_count=task_data.get("success_count", 0),
                    created_at=task_data.get("created_at", ""),
                    metadata=task_data.get("metadata", {}),
                )

                self._tasks[task_id] = task

            _logger.info("[SCHEDULER] %d schedules carregados", len(self._tasks))
        except Exception as e:
            _logger.error("[ERRO] Falha ao carregar schedules: %s", e)

    def _save_execution_log(self, execution: TaskExecution):
        """Salva log de execução."""
        try:
            log_file = _LOGS_DIR / f"{execution.task_id}.jsonl"

            with log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "task_id": execution.task_id,
                    "timestamp": execution.timestamp,
                    "success": execution.success,
                    "duration_ms": execution.duration_ms,
                    "error": execution.error,
                }) + "\n")
        except Exception as e:
            _logger.error("[ERRO] Falha ao salvar log: %s", e)

    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """Retorna tarefa por ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self) -> List[ScheduledTask]:
        """Lista todas as tarefas."""
        with self._lock:
            return list(self._tasks.values())

    def get_execution_history(self, task_id: Optional[str] = None, limit: int = 50) -> List[TaskExecution]:
        """Retorna histórico de execuções."""
        with self._lock:
            if task_id:
                filtered = [e for e in self._execution_history if e.task_id == task_id]
                return filtered[-limit:]
            return self._execution_history[-limit:]

    def get_status(self) -> Dict[str, Any]:
        """Retorna status do scheduler."""
        with self._lock:
            return {
                "running": self._running,
                "task_count": len(self._tasks),
                "enabled_count": sum(1 for t in self._tasks.values() if t.enabled),
                "total_executions": len(self._execution_history),
                "total_successes": sum(1 for e in self._execution_history if e.success),
            }


# Scheduler global
scheduler = Scheduler()

# ========== Handlers Built-in ==========

def backup_sessions_handler(task: ScheduledTask) -> Dict[str, Any]:
    """Handler de backup de sessões."""
    from dataclasses import asdict
    from ..memory.session_memory import memory

    # Exporta sessões recentes
    recent = [asdict(session) for session in memory.get_recent(limit=100)]

    backup_file = _LOGS_DIR / f"sessions_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    backup_file.write_text(json.dumps(recent, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"backup_file": str(backup_file), "sessions_count": len(recent)}


def cleanup_cache_handler(task: ScheduledTask) -> Dict[str, Any]:
    """Handler de limpeza de cache."""
    # Implementar limpeza de cache antigo
    return {"status": "not_implemented"}


def weekly_report_handler(task: ScheduledTask) -> Dict[str, Any]:
    """Handler de relatório semanal."""
    from ..memory.session_memory import memory

    # Gera relatório de uso
    stats = memory.get_stats() if hasattr(memory, "get_stats") else {}

    return {
        "period": "weekly",
        "stats": stats,
    }


# Registra handlers built-in
scheduler.register_handler("backup_sessions", backup_sessions_handler)
scheduler.register_handler("cleanup_cache", cleanup_cache_handler)
scheduler.register_handler("weekly_report", weekly_report_handler)
