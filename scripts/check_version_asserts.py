import importlib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"

IMPORT_RE = re.compile(
    r"from\s+([\w.]+)\s+import\s+(\([^)]*\)|[^\n]*)",
    re.DOTALL,
)
# Captura tanto `import MODULE_VERSION` quanto `import MODULE_VERSION as ALIAS`
# -- sem isso, um alias (ex: `MODULE_VERSION as CODE_VER`) faz o assert
# correspondente escapar da checagem silenciosamente (achado real: CODE_VER
# em test_auditoria_2026.py ficou 1 versao atrasado sem o script acusar).
MODULE_VERSION_IMPORT_RE = re.compile(r"\bMODULE_VERSION\b(?:\s+as\s+(\w+))?")
ASSERT_RE = re.compile(r'assert\s+(\w+)\s*==\s*"([^"]+)"')

_ADDON_PKG_PATH = str(REPO_ROOT / "addon" / "globalPlugins")
if _ADDON_PKG_PATH not in sys.path:
    sys.path.insert(0, _ADDON_PKG_PATH)

sys.path.insert(0, str(TESTS_DIR))
from conftest import install_nvda_stubs  # noqa: E402 - precisa do sys.path acima primeiro

install_nvda_stubs()


def _resolve_module_path(dotted: str) -> str:
    """Normaliza `addon.globalPlugins.nvdastudio.x` e `nvdastudio.x` pro mesmo modulo real."""
    prefix = "addon.globalPlugins."
    if dotted.startswith(prefix):
        return dotted[len(prefix):]
    return dotted


def _actual_version(dotted: str) -> str | None:
    try:
        mod = importlib.import_module(_resolve_module_path(dotted))
        return getattr(mod, "MODULE_VERSION", None)
    except Exception as exc:  # noqa: BLE001 - reportamos qualquer falha de import ao usuario
        print(f"[AVISO] Nao foi possivel importar {dotted}: {exc}", file=sys.stderr)
        return None


def _check_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    imports: list[tuple[int, str, str]] = []
    for m in IMPORT_RE.finditer(text):
        mv_match = MODULE_VERSION_IMPORT_RE.search(m.group(2))
        if not mv_match:
            continue
        alias = mv_match.group(1) or "MODULE_VERSION"
        lineno = text.count("\n", 0, m.start()) + 1
        imports.append((lineno, m.group(1), alias))

    problems = []
    for lineno, line in enumerate(lines, start=1):
        m = ASSERT_RE.search(line)
        if not m:
            continue
        name, expected = m.group(1), m.group(2)

        candidates = [(mod, alias) for iln, mod, alias in imports if iln <= lineno and alias == name]
        if not candidates:
            continue
        module_path, _alias = candidates[-1]

        actual = _actual_version(module_path)
        if actual is None:
            continue
        if actual != expected:
            problems.append(
                f"{path.relative_to(REPO_ROOT)}:{lineno} — {module_path} "
                f"MODULE_VERSION real e '{actual}', teste espera '{expected}'"
            )
    return problems


def main() -> int:
    all_problems: list[str] = []
    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        if "lib" in path.parts:
            continue
        all_problems.extend(_check_file(path))

    if all_problems:
        print("Asserts de versao desatualizados encontrados:\n")
        for problem in all_problems:
            print(f"  - {problem}")
        print(
            f"\n{len(all_problems)} assert(s) de versao desatualizado(s). "
            "Atualize o valor esperado no teste para bater com o MODULE_VERSION atual."
        )
        return 1

    print("Todos os asserts de versao batem com o MODULE_VERSION real dos modulos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
