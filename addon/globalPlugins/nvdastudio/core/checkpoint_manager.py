import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..utils.logger import get_logger

_logger = get_logger("checkpoint")
MODULE_VERSION = "2.1.0"

# Config
_MAX_SNAPSHOTS = 20
_MAX_TOTAL_SIZE_MB = 100


class CheckpointAction(Enum):
    """Acao do usuario ao checkpoint."""
    CONTINUE = "continuar"
    REDO = "refazer"      # Volta a fase anterior
    PAUSE = "pausar"      # Salva estado, para aqui
    AUTO_CONTINUE = "auto"  # Timeout ou sem callback


@dataclass
class Checkpoint:
    """Snapshot do estado do projeto."""
    hash: str
    timestamp: float
    reason: str
    workdir: str
    files: Dict[str, str]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckpointResult:
    """Resultado de uma operacao de checkpoint."""
    success: bool
    checkpoint: Optional[Checkpoint] = None
    error: Optional[str] = None


@dataclass
class InteractiveCheckpoint:
    """Checkpoint com resumo humano para o usuario."""
    phase: str
    summary: str           # Resumo do que foi feito
    details: List[str]     # Itens especificos (ex: "3 APIs encontradas")
    files_affected: List[str]
    action: CheckpointAction = CheckpointAction.CONTINUE
    timestamp: float = field(default_factory=time.time)


class CheckpointManager:
    """
    Gerenciador de checkpoints (Hermes-inspired v2).

    Snapshots JSON atomicos + checkpoint interativo com 3 opcoes:
      CONTINUE → segue em frente
      REDO     → restaura ultimo checkpoint e refaz
      PAUSE    → salva estado, para o pipeline
    """

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir:
            self._base_dir = Path(base_dir)
        else:
            self._base_dir = Path.home() / "AppData" / "Roaming" / "NVDAStudio" / "checkpoints"

        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_prune = 0.0
        # Callbacks de UI (setados pelo studio_dialog)
        self._on_checkpoint: Optional[Callable[[InteractiveCheckpoint], CheckpointAction]] = None
        self._on_status: Optional[Callable[[str], None]] = None

    def set_callbacks(
        self,
        on_checkpoint: Optional[Callable[[InteractiveCheckpoint], CheckpointAction]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ):
        """Configura callbacks de UI."""
        self._on_checkpoint = on_checkpoint
        self._on_status = on_status

    # -------------------------------------------------------------------------
    # Checkpoint basico (snapshots)
    # -------------------------------------------------------------------------

    def _project_hash(self, workdir: str) -> str:
        import hashlib
        return hashlib.sha256(workdir.encode()).hexdigest()[:16]

    def _project_dir(self, workdir: str) -> Path:
        return self._base_dir / self._project_hash(workdir)

    def ensure_checkpoint(self, workdir: str, reason: str = "auto") -> CheckpointResult:
        """Tira snapshot do estado atual."""
        try:
            project_dir = self._project_dir(workdir)
            project_dir.mkdir(parents=True, exist_ok=True)

            files = {}
            workdir_path = Path(workdir)

            if workdir_path.exists():
                for file_path in workdir_path.rglob("*"):
                    if file_path.is_file() and not self._should_skip(file_path):
                        rel_path = str(file_path.relative_to(workdir_path))
                        try:
                            with open(file_path, encoding="utf-8", errors="ignore") as f:
                                content = f.read()
                            if len(content) > 100_000:
                                content = content[:100_000] + "\n[...truncado...]"
                            files[rel_path] = content
                        except Exception as exc:
                            _logger.debug("[DEBUG] Falha ao ler %s pro checkpoint: %s", rel_path, exc)

            checkpoint = Checkpoint(
                hash=f"{int(time.time())}_{os.urandom(4).hex()}",
                timestamp=time.time(),
                reason=reason,
                workdir=workdir,
                files=files,
                metadata={"file_count": len(files)},
            )

            checkpoint_path = project_dir / f"{checkpoint.hash}.json"
            self._write_atomic(checkpoint_path, checkpoint)

            _logger.info("[CHECKPOINT] Criado: %s (%d arquivos, razao: %s)",
                        checkpoint.hash[:8], len(files), reason)

            self._prune_project(workdir)
            return CheckpointResult(success=True, checkpoint=checkpoint)

        except Exception as e:
            _logger.error("[ERRO] Falha ao criar checkpoint: %s", e)
            return CheckpointResult(success=False, error=str(e))

    def restore(self, workdir: str, checkpoint_hash: str, file_path: Optional[str] = None) -> CheckpointResult:
        """Restaura estado a partir de um checkpoint."""
        try:
            project_dir = self._project_dir(workdir)
            cp_path = project_dir / f"{checkpoint_hash}.json"

            if not cp_path.exists():
                return CheckpointResult(success=False, error=f"Checkpoint nao encontrado: {checkpoint_hash}")

            # Pre-rollback snapshot
            self.ensure_checkpoint(workdir, f"pre-rollback (restoring to {checkpoint_hash[:8]})")

            with open(cp_path, encoding="utf-8") as f:
                data = json.load(f)

            checkpoint = Checkpoint(**data)
            workdir_path = Path(workdir)
            workdir_path.mkdir(parents=True, exist_ok=True)

            if file_path:
                if file_path in checkpoint.files:
                    target = workdir_path / file_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with open(target, "w", encoding="utf-8") as f:
                        f.write(checkpoint.files[file_path])
                    _logger.info("[RESTORE] Arquivo restaurado: %s", file_path)
                else:
                    return CheckpointResult(success=False, error=f"Arquivo nao encontrado no checkpoint: {file_path}")
            else:
                for rel_path, content in checkpoint.files.items():
                    target = workdir_path / rel_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with open(target, "w", encoding="utf-8") as f:
                        f.write(content)
                _logger.info("[RESTORE] Checkpoint %s restaurado (%d arquivos)",
                            checkpoint_hash[:8], len(checkpoint.files))

            return CheckpointResult(success=True, checkpoint=checkpoint)

        except Exception as e:
            _logger.error("[ERRO] Falha ao restaurar checkpoint: %s", e)
            return CheckpointResult(success=False, error=str(e))

    def get_last_checkpoint(self, workdir: str) -> Optional[str]:
        """Retorna o hash do checkpoint mais recente."""
        project_dir = self._project_dir(workdir)
        if not project_dir.exists():
            return None

        checkpoints = sorted(project_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not checkpoints:
            return None

        try:
            with open(checkpoints[0], encoding="utf-8") as f:
                data = json.load(f)
            return data.get("hash")
        except Exception:
            return None

    # -------------------------------------------------------------------------
    # Checkpoint INTERATIVO (novo v2.0)
    # -------------------------------------------------------------------------

    def ask_checkpoint(
        self,
        phase: str,
        summary: str,
        details: List[str],
        files_affected: List[str],
        workdir: str,
    ) -> InteractiveCheckpoint:
        """
        Pergunta ao usuario se quer continuar, refazer, ou pausar.

        Se nao houver callback (modo automatico), retorna CONTINUE.
        Se o usuario escolher REDO, automaticamente restaura o ultimo checkpoint.
        """
        ic = InteractiveCheckpoint(
            phase=phase,
            summary=summary,
            details=details,
            files_affected=files_affected,
        )

        # Snapshot ANTES de perguntar (para poder refazer)
        self.ensure_checkpoint(workdir, f"pre-{phase}")

        if self._on_checkpoint:
            try:
                action = self._on_checkpoint(ic)
                ic.action = action
            except Exception as e:
                _logger.warning("[CHECKPOINT] Callback falhou: %s. Continuando automaticamente.", e)
                ic.action = CheckpointAction.CONTINUE
        else:
            # Sem callback: continua automaticamente
            ic.action = CheckpointAction.CONTINUE

        # Se usuario pediu REDO, restaura o ultimo checkpoint
        if ic.action == CheckpointAction.REDO:
            last_hash = self.get_last_checkpoint(workdir)
            if last_hash:
                result = self.restore(workdir, last_hash)
                if result.success and self._on_status:
                    self._on_status(f"Estado restaurado para antes da fase {phase}. Refazendo...")
            else:
                _logger.warning("[CHECKPOINT] REDO solicitado mas nenhum checkpoint anterior existe.")

        return ic

    # -------------------------------------------------------------------------
    # Utilitarios internos
    # -------------------------------------------------------------------------

    def _write_atomic(self, path: Path, checkpoint: Checkpoint):
        data = {
            "hash": checkpoint.hash,
            "timestamp": checkpoint.timestamp,
            "reason": checkpoint.reason,
            "workdir": checkpoint.workdir,
            "files": checkpoint.files,
            "metadata": checkpoint.metadata,
        }
        fd, temp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, path)
        except Exception:
            os.unlink(temp_path)
            raise

    def _should_skip(self, path: Path) -> bool:
        name = path.name
        skip_patterns = {
            ".git", ".svn", ".hg",
            "__pycache__", ".pytest_cache",
            "node_modules", "vendor",
            ".env", ".env.local", ".envrc",
            "*.pyc", "*.pyo", "*.exe", "*.dll",
            "*.mp3", "*.mp4", "*.wav", "*.zip", "*.tar.gz",
            "*.jpg", "*.png", "*.gif",
            "nvdastudio-*.nvda-addon",
        }
        for pattern in skip_patterns:
            if pattern.startswith("*"):
                if name.endswith(pattern[1:]):
                    return True
            elif pattern in str(path):
                return True
        return False

    def _prune_project(self, workdir: str):
        with self._lock:
            now = time.time()
            if now - self._last_prune < 60:
                return
            self._last_prune = now

            project_dir = self._project_dir(workdir)
            if not project_dir.exists():
                return

            checkpoints = sorted(project_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
            if len(checkpoints) <= _MAX_SNAPSHOTS:
                return

            to_remove = checkpoints[:len(checkpoints) - _MAX_SNAPSHOTS]
            for cp in to_remove:
                try:
                    cp.unlink()
                except Exception as exc:
                    _logger.debug("[DEBUG] Falha ao remover checkpoint antigo %s: %s", cp, exc)

            _logger.info("[CHECKPOINT] Pruned: removidos %d checkpoints antigos", len(to_remove))


# Instancia global
checkpoint_manager = CheckpointManager()
