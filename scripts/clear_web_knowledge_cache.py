import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_ADDON_PKG_PATH = str(REPO_ROOT / "addon" / "globalPlugins")
if _ADDON_PKG_PATH not in sys.path:
	sys.path.insert(0, _ADDON_PKG_PATH)
sys.path.insert(0, str(REPO_ROOT / "tests"))

from conftest import install_nvda_stubs  # noqa: E402 - precisa do sys.path acima primeiro

install_nvda_stubs()

from nvdastudio.memory.session_memory import memory  # noqa: E402


def _has_disallowed_code_fence(content: str) -> bool:
	return bool(re.search(r"```python:", content or ""))


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"--all", action="store_true",
		help="Remove TODA a tabela web_knowledge, nao so entradas invalidas.",
	)
	args = parser.parse_args()

	memory._init_db()
	if not memory._ready or memory._db is None:
		print("[ERRO] Nao foi possivel inicializar o banco de session_memory.", file=sys.stderr)
		return 1

	table = memory._db.table("web_knowledge")
	all_docs = table.all()
	total = len(all_docs)

	if args.all:
		table.truncate()
		print(f"Removidas {total} entrada(s) (--all: tabela inteira limpa).")
		return 0

	invalid_ids = [d.doc_id for d in all_docs if _has_disallowed_code_fence(d.get("content", ""))]
	if invalid_ids:
		table.remove(doc_ids=invalid_ids)
	print(f"{len(invalid_ids)} de {total} entrada(s) invalida(s) removida(s).")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
