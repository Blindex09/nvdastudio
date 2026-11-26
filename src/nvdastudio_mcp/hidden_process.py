"""Suppresses the console window of subprocesses on Windows.

A console-app subprocess (the sandbox python, pytest, pip) opens a terminal
window on Windows. That window STEALS FOCUS: for a screen reader user, the
screen reader jumps to the terminal and they lose their place in the
NVDAStudio window -- exactly what must not happen.

CREATE_NO_WINDOW only exists on Windows; on other platforms getattr returns
0 (no-op), so passing creationflags=CREATE_NO_WINDOW is safe on any OS.
"""

import os
import shutil
import subprocess
import sys

# 0 outside Windows -- OR with 0 changes nothing, so the flag is portable.
CREATE_NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)




def find_python() -> "str | None":
	"""Path of a REAL python.exe, or None if there is only nvda.exe.

	INSIDE NVDA, sys.executable is `nvda.exe` -- running it as an
	interpreter fails with WinError 740 (requires elevation), which was exactly
	the "real execution error" loop in code validation. addon_builder already
	handled this for pip; this is the single source, also used by
	code_sandbox.

	Returns None when there is only nvda.exe: the caller must SKIP validation by
	subprocess (there is no way to execute), and never treat the absence of
	python as a defect of the generated code.
	"""
	exe = sys.executable or ""
	base = os.path.basename(exe).lower()
	if "python" in base and "nvda" not in base:
		# pytest/CI/dev: sys.executable is already a real python.
		return exe
	for candidato in ("python.exe", "python3.exe", "python", "python3"):
		achado = shutil.which(candidato)
		if achado and "nvda" not in achado.lower():
			return achado
	return None
