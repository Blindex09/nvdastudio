"""Docker for isolated execution: starts by itself and gets the image ready.

The MCP server calls `start_warmup()` as soon as it starts. In the background it:
1. finds Docker (CLI and Docker Desktop);
2. if the engine does not respond, opens Docker Desktop and waits for it to be ready;
3. pulls the official Python image, if missing.

Whoever needs Docker calls `ensure()`: it waits for the preparation to finish
and returns (ready, reason). Without Docker installed, or if it does not get
ready, the reason says exactly what was missing; none of this is treated as
success.
"""

import os
import shutil
import subprocess
import sys
import threading
import time

from .logger import get_logger

_logger = get_logger("docker_runtime")

# NVDA 2026.x runs CPython 3.13: the add-on code is tested on the same Python.
DEFAULT_IMAGE = "python:3.13-slim"
ENV_IMAGE = "NVDASTUDIO_SANDBOX_IMAGE"
ENV_WAIT = "NVDASTUDIO_DOCKER_WAIT"  # seconds waiting for the engine to come up (default 240)
_PROBE_TIMEOUT = 15
_PULL_TIMEOUT = 900
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0)

_DESKTOP_CANDIDATES = (
    os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Docker", "Docker", "Docker Desktop.exe"),
)


def image_name() -> str:
    return os.environ.get(ENV_IMAGE) or DEFAULT_IMAGE


def _docker_cli() -> str | None:
    found = shutil.which("docker")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),):
        candidate = os.path.join(base, "Docker", "Docker", "resources", "bin", "docker.exe")
        if os.path.isfile(candidate):
            return candidate
    return None


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, check=False,
        stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
    )


def _engine_ready(docker: str) -> bool:
    try:
        return _run([docker, "info", "--format", "{{.ServerVersion}}"], _PROBE_TIMEOUT).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _start_desktop() -> str:
    """Opens Docker Desktop. Returns a sentence about what was tried."""
    if sys.platform != "win32":
        return "the Docker engine is not responding and I can only open it on Windows"
    for exe in _DESKTOP_CANDIDATES:
        if os.path.isfile(exe):
            subprocess.Popen(  # noqa: S603 - fixed path of Docker Desktop itself
                [exe], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_DETACHED | _NO_WINDOW, close_fds=True,
            )
            return "opened Docker Desktop"
    return "Docker Desktop is not installed in the default path"


class DockerRuntime:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._started = False
        self._result: tuple[bool, str] = (False, "the Docker preparation has not started yet")

    def start_warmup(self) -> None:
        """Starts the preparation in the background (idempotent)."""
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._prepare, name="docker-warmup", daemon=True).start()

    def ensure(self) -> tuple[bool, str]:
        """Waits for the preparation to finish and returns (ready, reason)."""
        self.start_warmup()
        self._done.wait()
        return self._result

    def reset(self) -> None:
        """Forgets the result (used when Docker goes down after being ready)."""
        with self._lock:
            self._started = False
            self._done.clear()
            self._result = (False, "the Docker preparation has not started yet")

    def _prepare(self) -> None:
        try:
            self._result = self._prepare_blocking()
        except Exception as exc:  # the preparation must never bring the server down
            _logger.error("Docker preparation failed: %s", exc)
            self._result = (False, f"failed to prepare Docker: {exc}")
        finally:
            self._done.set()

    def _prepare_blocking(self) -> tuple[bool, str]:
        docker = _docker_cli()
        if not docker:
            return False, "Docker is not installed (`docker` CLI not found)"
        if not _engine_ready(docker):
            action = _start_desktop()
            _logger.info("Docker engine stopped: %s", action)
            if not os.path.isfile(docker) or action.startswith(("Docker Desktop is not", "the Docker engine")):
                return False, action
            limit = float(os.environ.get(ENV_WAIT, "240"))
            deadline = time.monotonic() + limit
            while time.monotonic() < deadline:
                if _engine_ready(docker):
                    break
                time.sleep(3)
            else:
                return False, f"{action}, but the engine still did not respond after {int(limit)}s"
        image = image_name()
        if _run([docker, "image", "inspect", image], _PROBE_TIMEOUT).returncode != 0:
            _logger.info("pulling the image %s", image)
            try:
                pulled = _run([docker, "pull", image], _PULL_TIMEOUT)
            except subprocess.TimeoutExpired:
                return False, f"the download of the image {image} did not finish"
            if pulled.returncode != 0:
                return False, f"could not pull the image {image}: {pulled.stderr.strip()[-200:]}"
        return True, "docker"


runtime = DockerRuntime()
