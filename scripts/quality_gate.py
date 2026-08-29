import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class StageResult:
	name: str
	blocking: bool
	passed: bool
	duration_s: float
	summary: str
	details: str = field(default="", repr=False)


def _run(cmd: list[str], cwd: Path = REPO_ROOT, timeout: int = 600) -> tuple[int, str]:
	try:
		proc = subprocess.run(
			cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
		)
		return proc.returncode, (proc.stdout + proc.stderr)
	except subprocess.TimeoutExpired as exc:
		return 1, f"TIMEOUT apos {timeout}s: {exc}"
	except FileNotFoundError as exc:
		return 1, f"comando nao encontrado: {exc}"


def _stage_lint() -> StageResult:
	start = time.perf_counter()
	code, out = _run([sys.executable, "-m", "ruff", "check", "addon/", "tests/", "scripts/"])
	dur = time.perf_counter() - start
	n_errors = out.count("\n") if code != 0 else 0
	return StageResult(
		name="Lint (ruff)", blocking=True, passed=(code == 0), duration_s=dur,
		summary="limpo" if code == 0 else f"{n_errors} linha(s) de erro/aviso",
		details=out if code != 0 else "",
	)


def _stage_typecheck() -> StageResult:
	start = time.perf_counter()
	code, out = _run([
		sys.executable, "-m", "mypy", "addon/globalPlugins/nvdastudio",
		"--config-file", "mypy.ini",
	], timeout=180)
	dur = time.perf_counter() - start
	n_errors = out.count(": error:")
	return StageResult(
		name="Type-check (mypy)", blocking=False, passed=(n_errors == 0),
		duration_s=dur,
		summary=(
			"limpo" if n_errors == 0 else
			f"{n_errors} erro(s) -- INFORMACIONAL: a maioria e stub ausente "
			f"de modulo NVDA real (wx/gui/addonHandler), so existe dentro "
			f"do processo do NVDA, mypy nao resolve fora dele"
		),
		details=out if n_errors else "",
	)


def _stage_version_asserts() -> StageResult:
	start = time.perf_counter()
	code, out = _run([sys.executable, "scripts/check_version_asserts.py"])
	dur = time.perf_counter() - start
	return StageResult(
		name="Consistencia de MODULE_VERSION", blocking=True,
		passed=(code == 0), duration_s=dur,
		summary="ok" if code == 0 else "divergencia encontrada",
		details=out if code != 0 else "",
	)


def _stage_fitness_functions() -> StageResult:
	start = time.perf_counter()
	code, out = _run([
		sys.executable, "-m", "pytest",
		"tests/unit/test_architecture_fitness_functions.py", "-q",
	])
	dur = time.perf_counter() - start
	last_line = next((ln for ln in reversed(out.splitlines()) if ln.strip()), "")
	return StageResult(
		name="Architecture Fitness Functions", blocking=True,
		passed=(code == 0), duration_s=dur, summary=last_line,
		details=out if code != 0 else "",
	)


def _stage_pytest(label: str, path: str, blocking: bool = True) -> StageResult:
	start = time.perf_counter()
	code, out = _run([sys.executable, "-m", "pytest", path, "-q"], timeout=900)
	dur = time.perf_counter() - start
	last_line = next((ln for ln in reversed(out.splitlines()) if ln.strip()), "")
	return StageResult(
		name=label, blocking=blocking, passed=(code == 0),
		duration_s=dur, summary=last_line,
		details=out if code != 0 else "",
	)


_STAGES = [
	_stage_lint,
	_stage_typecheck,
	_stage_version_asserts,
	_stage_fitness_functions,
	lambda: _stage_pytest("Unit Tests", "tests/unit"),
	lambda: _stage_pytest("Integration Tests", "tests/integration"),
]


def run_quality_gate() -> tuple[bool, list[StageResult]]:
	results: list[StageResult] = []
	for stage_fn in _STAGES:
		result = stage_fn()
		results.append(result)
		# Nao para no primeiro NO-GO -- relatorio completo de TODOS os
		# estagios ajuda mais que abortar cedo (mesma logica de Failure
		# Localization: quanto mais sinal, mais rapido a causa raiz).
	go = all(r.passed for r in results if r.blocking)
	return go, results


def _print_report(go: bool, results: list[StageResult]) -> None:
	print("=" * 60)
	print("QUALITY GATE — NVDAStudio")
	print("=" * 60)
	for r in results:
		status = "PASS" if r.passed else ("NO-GO" if r.blocking else "AVISO")
		tag = "" if r.blocking else " (informacional, nao bloqueia)"
		print(f"[{status:5}] {r.name}{tag} — {r.summary} ({r.duration_s:.1f}s)")
		if not r.passed and r.details:
			preview = "\n".join(r.details.strip().splitlines()[-15:])
			print(f"        {preview}\n")
	print("=" * 60)
	print(f"VEREDITO: {'GO' if go else 'NO-GO'}")
	print("=" * 60)


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--json", action="store_true", help="imprime o relatorio como JSON")
	args = parser.parse_args()

	go, results = run_quality_gate()

	if args.json:
		print(json.dumps({
			"go": go,
			"stages": [
				{
					"name": r.name, "blocking": r.blocking, "passed": r.passed,
					"duration_s": round(r.duration_s, 2), "summary": r.summary,
				}
				for r in results
			],
		}, indent=2, ensure_ascii=False))
	else:
		_print_report(go, results)

	return 0 if go else 1


if __name__ == "__main__":
	sys.exit(main())
