"""Opens a .nvda-addon in the running NVDA, using NVDA's own installer entry point.

Windows registers `nvda_slave.exe addons_installAddonPackage "%1"` as the "open" verb of
.nvda-addon files. `os.startfile` goes through that association and reported success even
when no dialog showed up, so this module calls the slave directly and then checks a fact:
did a NEW visible window of the NVDA process appear (the install confirmation dialog)?
Nothing here reads the dialog text, which is localised.
"""

import csv
import io
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

ASSOCIATION_KEY = r"NVDA.Addon.1\shell\open\command"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class NvdaInstallError(Exception):
    """NVDA cannot receive the package (not Windows, not installed, not running)."""


def slave_from_command(command: str) -> str | None:
    """Path of nvda_slave.exe from the registered open command, quoted or not."""
    command = command.strip()
    if command.startswith('"'):
        end = command.find('"', 1)
        return command[1:end] if end > 1 else None
    head = command.lower().find(".exe")
    return command[: head + 4] if head > 0 else None


def find_slave() -> Path | None:
    candidates: list[str] = []
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ASSOCIATION_KEY) as key:
                registered = slave_from_command(str(winreg.QueryValue(key, None)))
                if registered:
                    candidates.append(registered)
        except OSError:
            pass
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        if base:
            candidates.append(os.path.join(base, "NVDA", "nvda_slave.exe"))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return Path(candidate)
    return None


def nvda_process_ids() -> list[int]:
    """PIDs of the running nvda.exe (empty when NVDA is not running)."""
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq nvda.exe", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
    )
    pids: list[int] = []
    for row in csv.reader(io.StringIO(result.stdout)):
        if len(row) > 1 and row[0].lower() == "nvda.exe" and row[1].isdigit():
            pids.append(int(row[1]))
    return pids


def visible_window_titles(pids: list[int]) -> list[str]:
    """Titles of the visible top-level windows owned by any of `pids`."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    titles: list[str] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def collect(hwnd: int, _param: int) -> bool:
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids:
                length = user32.GetWindowTextLengthW(hwnd)
                if length:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buffer, length + 1)
                    titles.append(buffer.value)
        return True

    user32.EnumWindows(callback_type(collect), 0)
    return titles


def open_in_nvda(
    package: Path,
    *,
    wait_seconds: float = 10.0,
    poll_seconds: float = 0.5,
    platform: str = sys.platform,
    find_slave_fn: Callable[[], Path | None] = find_slave,
    pids_fn: Callable[[], list[int]] = nvda_process_ids,
    windows_fn: Callable[[list[int]], list[str]] = visible_window_titles,
    run_fn: Callable[[list[str]], int] | None = None,
) -> dict[str, object]:
    """Hand the package to the running NVDA and report what actually happened."""
    if platform != "win32":
        raise NvdaInstallError("opening a package in NVDA only works on Windows")
    slave = find_slave_fn()
    if slave is None:
        raise NvdaInstallError("NVDA is not installed here: nvda_slave.exe was not found")
    pids = pids_fn()
    if not pids:
        raise NvdaInstallError("NVDA is not running: start NVDA and call this tool again")

    before = set(windows_fn(pids))
    command = [str(slave), "addons_installAddonPackage", str(package)]
    if run_fn is None:
        exit_code = subprocess.run(
            command, capture_output=True, check=False, timeout=60,
            stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
        ).returncode
    else:
        exit_code = run_fn(command)

    deadline = time.monotonic() + wait_seconds
    new_windows: list[str] = []
    while True:
        new_windows = [title for title in windows_fn(pids_fn() or pids) if title not in before]
        if new_windows or time.monotonic() >= deadline:
            break
        time.sleep(poll_seconds)

    detected = bool(new_windows)
    return {
        "package": str(package),
        "slave_exit_code": exit_code,
        "dialog_detected": detected,
        "new_nvda_windows": new_windows,
        "next_step": (
            "NVDA is showing its install confirmation dialog: the person confirms or cancels it, "
            "and restarts NVDA after installing."
            if detected
            else "NVDA did not open any new window within the wait time. Ask the person whether the "
                 "install dialog appeared; do not assume it did."
        ),
    }
