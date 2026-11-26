"""Execution of untrusted code in a Docker container, with no network.

Docker is prepared by `docker_runtime` (it starts Docker Desktop and pulls the
Python image, if missing). Without Docker available the operation fails closed, with the reason.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from .docker_runtime import _docker_cli, image_name, runtime

MODULE_VERSION = "2.0.0"


@dataclass
class IsolatedProcessResult:
	returncode: int = -1
	stdout: str = ""
	stderr: str = ""
	error: str = ""
	timed_out: bool = False
	isolated: bool = False
	backend: str = ""


class IsolationRunner:
	"""Runs Python with no network and no write access to the host outside the workspace."""

	def __init__(self, image: str | None = None):
		self.image: str = image or image_name()
		self._docker = _docker_cli()

	def backend_available(self) -> tuple[bool, str]:
		"""Ensures Docker (starts it by itself, if needed) and returns (ready, reason)."""
		ready, reason = runtime.ensure()
		if ready and self.image != image_name():
			# image chosen by hand for this runner: check only that one
			try:
				probe = subprocess.run(
					[self._docker or "docker", "image", "inspect", self.image],
					capture_output=True, text=True, timeout=8, check=False, stdin=subprocess.DEVNULL,
				)
			except (OSError, subprocess.TimeoutExpired) as exc:
				return False, f"Docker unavailable: {exc}"
			if probe.returncode != 0:
				return False, f"isolation image missing: {self.image}"
		return ready, reason

	def run_python(
		self,
		arguments: list[str],
		*,
		workspace: str,
		timeout: int,
		env: dict[str, str] | None = None,
	) -> IsolatedProcessResult:
		available, reason = self.backend_available()
		if not available:
			return IsolatedProcessResult(error=f"ISOLATION_UNAVAILABLE: {reason}")
		root = os.path.realpath(workspace)
		if not os.path.isdir(root):
			return IsolatedProcessResult(error="ISOLATION_INVALID_WORKSPACE")
		docker = self._docker
		if not docker:  # defense against a change between the probe and the execution
			return IsolatedProcessResult(error="ISOLATION_UNAVAILABLE: Docker is not installed")
		assert docker is not None

		command = [
			docker, "run", "--rm", "--network", "none",
			"--read-only", "--cap-drop", "ALL",
			"--security-opt", "no-new-privileges:true",
			"--pids-limit", "64", "--memory", "384m", "--cpus", "1",
			"--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
			"--mount", f"type=bind,source={root},target=/workspace",
			"--workdir", "/workspace",
			"--env", "APPDATA=/tmp/appdata",
			"--env", "LOCALAPPDATA=/tmp/localappdata",
			"--env", "TEMP=/tmp",
			"--env", "TMP=/tmp",
			"--env", "HOME=/tmp/home",
		]
		# Closed list: no key, proxy, HOME or user variable leaks.
		for key, value in (env or {}).items():
			if key in {"PYTHONPATH", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "NVDASTUDIO_FAULT_SCENARIO"}:
				command.extend(["--env", f"{key}={value}"])
		command.extend([self.image, "python", "-B", *arguments])
		try:
			proc = subprocess.run(
				command, capture_output=True, text=True, timeout=timeout, check=False,
				stdin=subprocess.DEVNULL,
			)
			return IsolatedProcessResult(
				returncode=proc.returncode,
				stdout=proc.stdout[:5000], stderr=proc.stderr[:5000],
				isolated=True, backend="docker",
			)
		except subprocess.TimeoutExpired as exc:
			return IsolatedProcessResult(
				stdout=(exc.stdout or "")[:5000] if isinstance(exc.stdout, str) else "",
				stderr=(exc.stderr or "")[:5000] if isinstance(exc.stderr, str) else "",
				error=f"Timeout: isolated execution exceeded {timeout}s",
				timed_out=True, isolated=True, backend="docker",
			)
		except OSError as exc:
			return IsolatedProcessResult(error=f"ISOLATION_UNAVAILABLE: {exc}")
