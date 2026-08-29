import argparse
import json
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RELATORIOS_DIR = REPO_ROOT / "tests" / "e2e" / "relatorios"


def _load_reports() -> list[dict]:
	reports = []
	for path in sorted(RELATORIOS_DIR.glob("*.json")):
		try:
			data = json.loads(path.read_text(encoding="utf-8"))
		except (json.JSONDecodeError, OSError):
			continue
		data["_arquivo"] = path.name
		reports.append(data)
	return reports


def _parse_timestamp(raw: str) -> datetime | None:
	try:
		return datetime.fromisoformat(raw)
	except (ValueError, TypeError):
		return None


def _group_by_addon(reports: list[dict]) -> dict[str, list[dict]]:
	groups: dict[str, list[dict]] = defaultdict(list)
	for r in reports:
		groups[r.get("addon_name", "desconhecido")].append(r)
	for runs in groups.values():
		runs.sort(key=lambda r: _parse_timestamp(r.get("timestamp", "")) or datetime.min)
	return groups


def _flakiness(runs: list[dict]) -> int:
	"""Conta quantas vezes o resultado (sucesso/falha) MUDOU entre
	execucoes consecutivas -- 0 = comportamento consistente (sempre passa
	ou sempre falha), N alto = inconsistente demais pra confiar num
	resultado isolado."""
	outcomes = [bool(r.get("success", False)) for r in runs]
	return sum(1 for i in range(1, len(outcomes)) if outcomes[i] != outcomes[i - 1])


def _compute_stats(addon: str, runs: list[dict]) -> dict:
	n = len(runs)
	successes = sum(1 for r in runs if r.get("success", False))
	scores = [r.get("avg_score", 0.0) for r in runs if r.get("avg_score") is not None]

	stats = {
		"addon": addon,
		"n_execucoes": n,
		"success_rate": round(successes / n, 3) if n else 0.0,
		"pass_at_k": any(r.get("success", False) for r in runs) if n else False,
		"avg_score_mean": round(statistics.mean(scores), 1) if scores else None,
		"avg_score_stdev": round(statistics.stdev(scores), 1) if len(scores) >= 2 else None,
		"flakiness_transitions": _flakiness(runs),
	}
	return stats


def _print_report(all_stats: list[dict]) -> None:
	print("=" * 78)
	print("MULTI-RUN / STATISTICAL EVALS")
	print("=" * 78)
	for s in all_stats:
		confianca = "ALTA" if s["n_execucoes"] >= 10 else ("MEDIA" if s["n_execucoes"] >= 3 else "BAIXA (1-2 execucoes)")
		print(f"\n{s['addon']}")
		print(f"  Execucoes: {s['n_execucoes']}  (confianca estatistica: {confianca})")
		print(f"  Success Rate: {s['success_rate']*100:.1f}%")
		print(f"  Pass@{s['n_execucoes']}: {'sim' if s['pass_at_k'] else 'nao'} (pelo menos 1 sucesso)")
		if s["avg_score_mean"] is not None:
			desvio = f" (desvio: {s['avg_score_stdev']})" if s["avg_score_stdev"] is not None else ""
			print(f"  Score medio: {s['avg_score_mean']}{desvio}")
		if s["flakiness_transitions"] > 0:
			print(f"  AVISO Flakiness: {s['flakiness_transitions']} mudanca(s) de resultado entre execucoes consecutivas")
	print("\n" + "=" * 78)


def _run_live(test_path: str, n: int, confirmado: bool) -> int:
	custo_estimado = (
		f"MODO EXECUCAO: rodar '{test_path}' {n}x em sequencia. "
		f"Cada rodada gasta API real (custo real de tokens, minutos de execucao "
		f"por rodada -- ver docs/plans/2026-08-09-eval-maturity-e-proxima-etapa.md "
		f"pro custo tipico de 1 rodada deste tipo de teste)."
	)
	print(custo_estimado)
	if not confirmado:
		print(
			"\nNAO executado -- requer --confirmo explicito (gasta orcamento de "
			"API real, N vezes o custo de 1 execucao normal). Rode de novo com "
			"--confirmo se realmente quiser gastar isso agora."
		)
		return 1

	for i in range(1, n + 1):
		print(f"\n--- Execucao {i}/{n} ---")
		proc = subprocess.run([sys.executable, "-m", "pytest", test_path, "-q", "-s"])
		if proc.returncode not in (0, 1):
			print(f"[AVISO] Execucao {i} terminou com codigo inesperado {proc.returncode}")
	print(f"\n{n} execucoes concluidas. Rode 'python scripts/multi_run_eval.py' "
		  f"(sem --execute) pra ver as estatisticas agregadas dos novos relatorios.")
	return 0


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--addon", help="filtra por addon_name")
	parser.add_argument("--json", action="store_true", help="saida como JSON")
	parser.add_argument("--execute", action="store_true", help="roda um teste E2E N vezes de verdade (gasta API)")
	parser.add_argument("--test", help="caminho do teste E2E a rodar (com --execute)")
	parser.add_argument("--n", type=int, default=5, help="numero de execucoes (com --execute)")
	parser.add_argument("--confirmo", action="store_true", help="confirma o gasto de API real (com --execute)")
	args = parser.parse_args()

	if args.execute:
		if not args.test:
			print("--execute exige --test <caminho_do_teste>", file=sys.stderr)
			return 2
		return _run_live(args.test, args.n, args.confirmo)

	reports = _load_reports()
	if args.addon:
		reports = [r for r in reports if r.get("addon_name", "").lower() == args.addon.lower()]

	groups = _group_by_addon(reports)
	all_stats = [_compute_stats(addon, runs) for addon, runs in sorted(groups.items())]

	if args.json:
		print(json.dumps(all_stats, indent=2, ensure_ascii=False))
	else:
		_print_report(all_stats)
	return 0


if __name__ == "__main__":
	sys.exit(main())
