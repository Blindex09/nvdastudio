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
# PROMPT_VERSION entra junto: builder/nvda_context.py usa esse nome em vez de
# MODULE_VERSION, e por isso ficava fora da checagem -- os asserts dele so
# quebravam na suite completa, depois do commit. Aconteceu duas vezes.
_NOMES_DE_VERSAO = ("MODULE_VERSION", "PROMPT_VERSION")
MODULE_VERSION_IMPORT_RE = re.compile(
    r"\b(MODULE_VERSION|PROMPT_VERSION)\b(?:\s+as\s+(\w+))?"
)
# Aceita tanto `assert MODULE_VERSION == "x"` quanto
# `assert modulo.MODULE_VERSION == "x"` -- a segunda forma escapava da
# checagem, e o assert so quebrava na suite completa depois do commit.
# Aceita tanto `assert MODULE_VERSION == ...` quanto
# `assert modulo.MODULE_VERSION == ...` -- a segunda forma escapava da
# checagem, e o assert so quebrava na suite completa depois do commit.
ASSERT_RE = re.compile(
    r'assert\s+(?:\w+\.)?(\w+)\s*==\s*"([^"]+)"'
)

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
        for nome in _NOMES_DE_VERSAO:
            valor = getattr(mod, nome, None)
            if valor:
                return valor
        return None
    except Exception as exc:  # noqa: BLE001 - reportamos qualquer falha de import ao usuario
        print(f"[AVISO] Nao foi possivel importar {dotted}: {exc}", file=sys.stderr)
        return None


def _check_file(path: Path, aplicar: bool = False) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    imports: list[tuple[int, str, str]] = []
    for m in IMPORT_RE.finditer(text):
        lineno = text.count("\n", 0, m.start()) + 1
        mv_match = MODULE_VERSION_IMPORT_RE.search(m.group(2))
        if mv_match:
            alias = mv_match.group(2) or mv_match.group(1)
            imports.append((lineno, m.group(1), alias))
            continue
        # `from pacote import modulo` + `assert modulo.MODULE_VERSION == ...`:
        # o nome da versao nao aparece na linha de import, so no assert. Sem
        # isto, esses asserts escapavam da checagem e so quebravam na suite
        # completa, depois do commit.
        nomes = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", m.group(2))
        apelidos = {
            nomes[i + 1] for i, n in enumerate(nomes[:-1]) if n == "as"
        }
        for importado in nomes:
            # So nomes que PARECEM modulo. Constante em MAIUSCULAS e classe em
            # CamelCase nao sao pacote, e tentar importa-las so gera ruido de
            # aviso sem achar versao nenhuma. Apelido de `as` tambem nao e
            # caminho de modulo -- `import model_registry as mr` nao cria
            # `pacote.mr`.
            if importado == "as" or importado in apelidos or not importado.islower():
                continue
            imports.append((lineno, m.group(1) + "." + importado, importado))

    problems = []
    correcoes: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(lines, start=1):
        m = ASSERT_RE.search(line)
        if not m:
            continue
        name, expected = m.group(1), m.group(2)

        prefixo = ""
        m_dot = re.search(r"assert\s+(\w+)\.\w+\s*==", line)
        if m_dot:
            prefixo = m_dot.group(1)
        candidates = [
            (mod, alias) for iln, mod, alias in imports
            if iln <= lineno and alias == (prefixo or name)
        ]
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
            correcoes.append((lineno, expected, actual))

    if aplicar and correcoes:
        for lineno, esperado, real in correcoes:
            lines[lineno - 1] = lines[lineno - 1].replace(
                '"' + esperado + '"', '"' + real + '"',
            ).replace("'" + esperado + "'", "'" + real + "'")
        # splitlines() descarta a quebra final; recoloca-la e obrigatorio --
        # sem isso o proprio --fix introduz W292 em todo arquivo que toca.
        novo = chr(10).join(lines)
        if text.endswith(chr(10)):
            novo += chr(10)
        path.write_text(novo, encoding="utf-8")

    return problems


def main() -> int:
    # --fix atualiza os asserts em vez de so reclamar.
    #
    # Sem isso, cada bump de MODULE_VERSION virava uma rodada de sed na mao
    # sobre 20+ arquivos -- trabalhoso, e perigoso: um `sed` por VALOR (e nao
    # por linha) atinge asserts de outros modulos que por acaso estao na mesma
    # versao. Aconteceu nesta sessao, com "1.4.0" de tres modulos diferentes.
    # A informacao de qual linha corrigir ja estava aqui; so nao era usada.
    aplicar = "--fix" in sys.argv

    all_problems: list[str] = []
    for path in sorted(TESTS_DIR.rglob("test_*.py")):
        if "lib" in path.parts:
            continue
        all_problems.extend(_check_file(path, aplicar=aplicar))

    if all_problems and aplicar:
        print(f"{len(all_problems)} assert(s) de versao atualizado(s):")
        for problem in all_problems:
            print(f"  - {problem}")
        return 0

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
