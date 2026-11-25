"""Execução de código não confiável com isolamento verificável.

O backend padrão usa um contêiner local já instalado. A imagem nunca é
baixada automaticamente: sem backend disponível a operação falha fechada.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

MODULE_VERSION = "1.0.0"
DEFAULT_IMAGE = "python:3.11-slim"


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
	"""Executa Python sem rede e sem acesso de escrita ao host fora do workspace."""

	def __init__(self, image: str | None = None):
		self.image: str = image or os.getenv("NVDASTUDIO_SANDBOX_IMAGE") or DEFAULT_IMAGE
		self._docker = shutil.which("docker")

	def backend_available(self) -> tuple[bool, str]:
		docker = self._docker
		if not docker:
			return False, "Docker não está instalado"
		try:
			probe = subprocess.run(
				[docker, "image", "inspect", self.image],
				capture_output=True, text=True, timeout=8, check=False,
			)
		except (OSError, subprocess.TimeoutExpired) as exc:
			return False, f"Docker indisponível: {exc}"
		if probe.returncode != 0:
			return False, (
				f"imagem de isolamento ausente: {self.image}. "
				"Instale-a explicitamente antes de executar código gerado"
			)
		return True, "docker"

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
		if not docker:  # defesa contra alteração entre o probe e a execução
			return IsolatedProcessResult(error="ISOLATION_UNAVAILABLE: Docker não está instalado")
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
		# Lista fechada: nenhuma chave, proxy, HOME ou variável do usuário vaza.
		for key, value in (env or {}).items():
			if key in {"PYTHONPATH", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "NVDASTUDIO_FAULT_SCENARIO"}:
				command.extend(["--env", f"{key}={value}"])
		command.extend([self.image, "python", "-B", *arguments])
		try:
			proc = subprocess.run(
				command, capture_output=True, text=True, timeout=timeout, check=False,
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
				error=f"Timeout: execução isolada excedeu {timeout}s",
				timed_out=True, isolated=True, backend="docker",
			)
		except OSError as exc:
			return IsolatedProcessResult(error=f"ISOLATION_UNAVAILABLE: {exc}")
