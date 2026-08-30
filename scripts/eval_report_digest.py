"""
Agrega os relatorios de execucao E2E em sinal acionavel.

MOTIVO (2026-08-29): o projeto acumulou 379 relatorios em
`tests/e2e/relatorios/` e ninguem os lia sistematicamente. A auditoria que
originou este script foi feita a mao e achou, em uma tarde, que TODOS os 9
addons Gemini marcados success=True estavam quebrados -- defeito que estava
escrito nos relatorios havia meses. Fazer isso a mao nao escala e depende de
alguem suspeitar do lugar certo.

O que ele responde, com dado em vez de palpite:
  - a taxa de sucesso REAL, separando falha de capacidade de falha de
    infraestrutura (chave ausente, rate limit, timeout) -- misturar as duas
    e o erro de leitura mais comum nestes relatorios;
  - quais tipos de addon convergem e quais nao;
  - quais regras aparecem mais em struct_problems, que e exatamente a fila de
    prioridade para promover regra a validador deterministico;
  - quais "sucessos" entregaram addon sem ponto de entrada carregavel.

Uso:
    python scripts/eval_report_digest.py
    python scripts/eval_report_digest.py --dir tests/e2e/relatorios --top 15
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

# Diretorios que o NVDA carrega por convencao. Mantido igual a
# core/planner.py::NVDA_ENTRY_POINT_DIRS e
# core/orchestrator.py::_ENTRY_POINT_DIRS -- este script roda fora do addon
# (nao importa o pacote) para continuar funcionando num checkout sem as
# dependencias instaladas.
_ENTRY_POINT_DIRS = (
	"globalPlugins",
	"appModules",
	"synthDrivers",
	"brailleDisplayDrivers",
	"visionEnhancementProviders",
)

# Padroes de falha que NAO sao do addon nem do pipeline -- sao do ambiente.
# Contar como falha de capacidade infla o problema e esconde o real.
_INFRA = (
	(re.compile(r"429|too many requests|quota|rate limit", re.I), "rate limit / quota"),
	(re.compile(r"chave api|api key|nao configurada|not configured", re.I), "chave ausente"),
	(re.compile(r"timeout|timed out", re.I), "timeout"),
	(re.compile(r"connection|conexao|network|ssl", re.I), "rede"),
	(re.compile(r"\b(500|502|503)\b|overloaded", re.I), "erro do provedor"),
)

_RULE_ID = re.compile(r"\b(?:NVDA-UX|WX-A11Y|DTK-A11Y|ARCH|ESTRUTURA|NVDA)-\d+\b")


def _classifica_erro(erro: str) -> str:
	"""Devolve a categoria de infraestrutura, ou "" quando e falha real."""
	for padrao, rotulo in _INFRA:
		if padrao.search(erro):
			return rotulo
	return ""


def _tem_ponto_de_entrada(arquivos: list[str]) -> bool:
	"""Mesma regra de carregamento do NVDA usada pelo portao do orchestrator."""
	for caminho in arquivos:
		partes = caminho.replace("\\", "/").lstrip("/").split("/")
		if len(partes) < 2 or partes[0] not in _ENTRY_POINT_DIRS:
			continue
		if len(partes) == 2 or (len(partes) == 3 and partes[-1] == "__init__.py"):
			return True
	return False


def carregar(diretorio: pathlib.Path) -> list[dict]:
	relatorios: list[dict] = []
	for arq in sorted(diretorio.glob("*.json")):
		try:
			relatorios.append(json.loads(arq.read_text(encoding="utf-8")))
		except (OSError, json.JSONDecodeError):
			continue
	return relatorios


def digest(relatorios: list[dict], top: int) -> str:
	linhas: list[str] = []
	esc = linhas.append

	# Execucoes que de fato rodaram. Sem tokens, o pipeline morreu antes de
	# gerar qualquer coisa -- normalmente falta de chave -- e incluir isso na
	# taxa de sucesso mede o ambiente, nao o produto.
	reais = [d for d in relatorios if (d.get("total_tokens") or 0) > 0]
	sucesso = [d for d in reais if d.get("success")]

	esc("=" * 72)
	esc("DIGEST DOS RELATORIOS E2E")
	esc("=" * 72)
	esc(f"relatorios no diretorio ......... {len(relatorios)}")
	esc(f"execucoes que rodaram de verdade  {len(reais)}  (tokens > 0)")
	if reais:
		esc(f"  sucesso ....................... {len(sucesso)}  ({len(sucesso) / len(reais) * 100:.0f}%)")
		esc(f"  falha ......................... {len(reais) - len(sucesso)}")
	esc("")

	# --- por que as que nao rodaram nao rodaram
	nao_rodaram = [d for d in relatorios if (d.get("total_tokens") or 0) == 0 and not d.get("success")]
	if nao_rodaram:
		cat: collections.Counter = collections.Counter()
		for d in nao_rodaram:
			cat[_classifica_erro(d.get("error") or "") or "falhou antes de gastar token"] += 1
		esc(f"NAO CHEGARAM A RODAR ({len(nao_rodaram)})")
		for rotulo, n in cat.most_common():
			esc(f"  {n:4d}  {rotulo}")
		esc("")

	# --- convergencia por tipo de addon
	por_addon: dict[str, list[dict]] = collections.defaultdict(list)
	for d in reais:
		por_addon[str(d.get("addon_name") or "?")].append(d)
	esc("CONVERGENCIA POR ADDON  (so execucoes que rodaram, >= 2 execucoes)")
	esc(f"  {'addon':<30s} {'exec':>5s} {'ok':>4s} {'taxa':>6s} {'score':>7s} {'retries':>8s} {'tokens':>11s}")
	for nome, execs in sorted(por_addon.items(), key=lambda kv: -len(kv[1])):
		if len(execs) < 2:
			continue
		ok = sum(1 for d in execs if d.get("success"))
		score = sum(d.get("avg_score") or 0 for d in execs) / len(execs)
		ret = sum(d.get("total_retries") or 0 for d in execs) / len(execs)
		tok = sum(d.get("total_tokens") or 0 for d in execs) / len(execs)
		esc(f"  {nome[:29]:<30s} {len(execs):5d} {ok:4d} {ok / len(execs) * 100:5.0f}% {score:7.1f} {ret:8.1f} {tok:11,.0f}")
	esc("")

	# --- sucessos que nao carregariam
	quebrados = [
		d for d in sucesso
		if [x for x in (d.get("zip_names") or []) if x.endswith(".py")]
		and not _tem_ponto_de_entrada(d.get("zip_names") or [])
	]
	esc(f"SUCESSOS SEM PONTO DE ENTRADA CARREGAVEL: {len(quebrados)}")
	if quebrados:
		esc("  (o NVDA nao carregaria estes addons -- instalam e nao fazem nada)")
		for d in sorted(quebrados, key=lambda x: str(x.get("timestamp"))):
			esc(f"  {str(d.get('timestamp'))[:16]}  {str(d.get('addon_name'))[:30]}")
	esc("")

	# --- fila de prioridade para promover regra a validador
	regras: collections.Counter = collections.Counter()
	for d in relatorios:
		for problema in d.get("struct_problems") or []:
			for rid in set(_RULE_ID.findall(str(problema))):
				regras[rid] += 1
	esc(f"REGRAS MAIS VIOLADAS  (top {top}) -- fila de prioridade para virar validador")
	if not regras:
		esc("  nenhuma registrada")
	for rid, n in regras.most_common(top):
		esc(f"  {n:4d}  {rid}")
	esc("")

	# --- falhas de capacidade real
	reais_falhas: collections.Counter = collections.Counter()
	for d in reais:
		if d.get("success"):
			continue
		erro = (d.get("error") or "").strip()
		if not erro:
			continue
		infra = _classifica_erro(erro)
		reais_falhas[f"INFRA: {infra}" if infra else erro[:90]] += 1
	esc(f"MOTIVOS DE FALHA  (top {top}, so execucoes que rodaram)")
	if not reais_falhas:
		esc("  nenhuma")
	for motivo, n in reais_falhas.most_common(top):
		esc(f"  {n:4d}  {motivo}")

	return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--dir", default="tests/e2e/relatorios", help="diretorio dos relatorios")
	parser.add_argument("--top", type=int, default=12, help="quantos itens por ranking")
	args = parser.parse_args(argv)

	diretorio = pathlib.Path(args.dir)
	if not diretorio.is_dir():
		print(f"[ERRO] diretorio nao encontrado: {diretorio}", file=sys.stderr)
		return 2

	relatorios = carregar(diretorio)
	if not relatorios:
		print(f"[AVISO] nenhum relatorio legivel em {diretorio}")
		return 0

	print(digest(relatorios, args.top))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
