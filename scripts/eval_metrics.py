import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RELATORIOS_DIR = REPO_ROOT / "tests" / "e2e" / "relatorios"


def _load_reports(relatorios_dir: Path) -> list[dict]:
    reports = []
    for path in sorted(relatorios_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[AVISO] Ignorando {path.name}: {exc}", file=sys.stderr)
            continue
        data["_arquivo"] = path.name
        reports.append(data)
    return reports


def _parse_timestamp(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _filter_reports(reports: list[dict], addon: str | None, since: str | None) -> list[dict]:
    filtered = reports
    if addon:
        filtered = [r for r in filtered if r.get("addon_name", "").lower() == addon.lower()]
    if since:
        since_dt = datetime.fromisoformat(since)
        filtered = [
            r for r in filtered
            if (ts := _parse_timestamp(r.get("timestamp", ""))) is not None and ts >= since_dt
        ]
    return filtered


def _estrutural_ok(report: dict) -> bool:
    """Os 2 arquivos absolutamente obrigatorios de qualquer addon NVDA."""
    return bool(report.get("has_init_py")) and bool(report.get("has_manifest"))


def _summarize(reports: list[dict]) -> dict:
    total = len(reports)
    if total == 0:
        return {"total_execucoes": 0}

    sucesso_bool = [r.get("success", False) for r in reports]
    sucesso_estrutural = [_estrutural_ok(r) for r in reports]
    scores = [r.get("avg_score", 0.0) for r in reports if r.get("avg_score") is not None]
    tokens = [r.get("total_tokens", 0) for r in reports]
    retries = [r.get("total_retries", 0) for r in reports]
    replans = [r.get("replan_count", 0) for r in reports]

    por_addon: dict[str, list[dict]] = {}
    for r in reports:
        por_addon.setdefault(r.get("addon_name", "?"), []).append(r)

    resumo_por_addon = {
        nome: {
            "execucoes": len(runs),
            "success_rate": round(sum(_estrutural_ok(r) for r in runs) / len(runs) * 100, 1),
            "avg_score": round(statistics.mean(r.get("avg_score", 0.0) for r in runs), 1),
        }
        for nome, runs in sorted(por_addon.items())
    }

    return {
        "total_execucoes": total,
        "taxa_sucesso_estrutural_pct": round(sum(sucesso_estrutural) / total * 100, 1),
        "taxa_sucesso_pipeline_completo_pct": round(sum(sucesso_bool) / total * 100, 1),
        "avg_score_medio": round(statistics.mean(scores), 1) if scores else 0.0,
        "avg_score_desvio_padrao": round(statistics.pstdev(scores), 1) if len(scores) > 1 else 0.0,
        "total_retries_medio": round(statistics.mean(retries), 1) if retries else 0.0,
        "replans_medio": round(statistics.mean(replans), 2) if replans else 0.0,
        "total_tokens_somados": sum(tokens),
        "por_addon": resumo_por_addon,
    }


def _print_human(summary: dict, reports: list[dict]) -> None:
    if summary["total_execucoes"] == 0:
        print("Nenhum relatorio E2E encontrado (filtro sem resultados ou pasta vazia).")
        return

    sep = "=" * 72
    print(sep)
    print("METRICAS DO GOLDEN EVAL SET -- tests/e2e/relatorios/")
    print(sep)
    print(f"  Execucoes analisadas:          {summary['total_execucoes']}")
    print(f"  Sucesso estrutural (init+manifest): {summary['taxa_sucesso_estrutural_pct']}%")
    print(f"  Sucesso do pipeline completo:  {summary['taxa_sucesso_pipeline_completo_pct']}%")
    print(f"  Score medio:                   {summary['avg_score_medio']} "
          f"(desvio padrao {summary['avg_score_desvio_padrao']})")
    print(f"  Retries medios por execucao:    {summary['total_retries_medio']}")
    print(f"  Replans medios por execucao:    {summary['replans_medio']}")
    print(f"  Tokens totais consumidos:      {summary['total_tokens_somados']:,}")

    print("\n--- POR ADDON ---")
    for nome, dados in summary["por_addon"].items():
        print(f"  {nome:30s} execucoes={dados['execucoes']:3d}  "
              f"sucesso_estrutural={dados['success_rate']:5.1f}%  "
              f"score_medio={dados['avg_score']:5.1f}")

    print("\n--- ULTIMAS 10 EXECUCOES (mais recente por ultimo) ---")
    ordenadas = sorted(reports, key=lambda r: r.get("timestamp", ""))
    for r in ordenadas[-10:]:
        status = "OK " if _estrutural_ok(r) else "FAL"
        print(f"  [{status}] {r.get('timestamp', '?')[:19]}  {r.get('addon_name', '?'):25s} "
              f"score={r.get('avg_score', 0):5.1f}  retries={r.get('total_retries', 0)}  "
              f"replans={r.get('replan_count', 0)}")
    print(sep)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--addon", help="Filtra por nome do addon (case-insensitive).")
    parser.add_argument("--since", help="Filtra execucoes a partir desta data (YYYY-MM-DD).")
    parser.add_argument("--json", action="store_true", help="Imprime o agregado como JSON.")
    args = parser.parse_args()

    if not RELATORIOS_DIR.is_dir():
        print(f"[ERRO] Pasta nao encontrada: {RELATORIOS_DIR}", file=sys.stderr)
        return 1

    reports = _load_reports(RELATORIOS_DIR)
    reports = _filter_reports(reports, args.addon, args.since)
    summary = _summarize(reports)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        _print_human(summary, reports)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
