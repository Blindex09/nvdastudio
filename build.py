import os
import re
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.join(ROOT, "addon")
MANIFEST_PATH = os.path.join(ROOT, "manifest.ini")
DIST_DIR = os.path.join(ROOT, "dist")

# Arquivos/pastas a excluir do pacote
# Achado de auditoria de arquitetura (2026-08-04): .ruff_cache/.mypy_cache/
# .pytest_cache/.hypothesis nunca estavam aqui -- um .ruff_cache/ ja existia
# de verdade dentro de addon/globalPlugins/nvdastudio/ (nested, nao so na
# raiz do projeto) e seria zipado pro .nvda-addon final num build real.
EXCLUDE_DIRS = {
    "__pycache__", "bin", "tests", "_tests", "pydantic", "hermes_bridge",
    "api_server", "click", "colorama",
    ".ruff_cache", ".mypy_cache", ".pytest_cache", ".hypothesis", ".git",
}
EXCLUDE_EXTENSIONS = {".pyc", ".pyo", ".exe", ".txt"}
EXCLUDE_FILES = {"AI_MODULE_SPEC.md", "cli.py"}

# Padrões de diretório a excluir (verificado via endswith)
EXCLUDE_DIR_PATTERNS = (".dist-info", ".egg-info")
LEGACY_DIST_INFO_PREFIXES = (
    "pydantic-",
    "anyio-4.13.0",
    "certifi-2026.2.25",
    "idna-3.11",
    "typing_extensions-4.15.0",
)

# Skills folder AGORA É ESSENCIAL (SKILL.md + skill_registry.json)
# NAO excluir skills/ — ela contem metadados das skills nativas
EXCLUDE_TOP_DIRS = set()  # Vazio — skills/ é essencial agora


def read_version() -> str:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        content = f.read()
    m = re.search(r"^\s*version\s*=\s*(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else "1.0.0"


def should_include(path: str, name: str) -> bool:
    _, ext = os.path.splitext(name)
    if ext in EXCLUDE_EXTENSIONS:
        return False
    if name in EXCLUDE_FILES:
        return False
    # Verifica se está em pasta de topo excluída
    rel_path = os.path.relpath(path, ROOT)
    top_dir = rel_path.split(os.sep)[0] if os.sep in rel_path else rel_path
    if top_dir in EXCLUDE_TOP_DIRS:
        return False
    return True


def build() -> str:
    version = read_version()
    output_name = f"nvdastudio-{version}.nvda-addon"
    output_path = os.path.join(DIST_DIR, output_name)

    os.makedirs(DIST_DIR, exist_ok=True)

    doc_dir = os.path.join(ROOT, "doc")

    file_count = 0
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # manifest.ini na raiz do zip
        zf.write(MANIFEST_PATH, "manifest.ini")
        file_count += 1
        print("  + manifest.ini")

        # doc/ — documentacao do usuario (readme.html por idioma)
        if os.path.isdir(doc_dir):
            for dirpath, dirnames, filenames in os.walk(doc_dir):
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
                for filename in filenames:
                    if not should_include(dirpath, filename):
                        continue
                    abs_path = os.path.join(dirpath, filename)
                    rel_path = os.path.relpath(abs_path, ROOT)
                    arc_name = rel_path.replace("\\", "/")
                    zf.write(abs_path, arc_name)
                    file_count += 1
                    print(f"  + {arc_name}")

        # Todos os arquivos de addon/
        for dirpath, dirnames, filenames in os.walk(ADDON_DIR):
            # Filtra pastas excluidas in-place (evita descida em __pycache__, bin, dist-info, egg-info)
            dirnames[:] = [
                d for d in dirnames
                if d not in EXCLUDE_DIRS
                and not any(d.endswith(pat) for pat in EXCLUDE_DIR_PATTERNS)
            ]

            for filename in filenames:
                if not should_include(dirpath, filename):
                    continue

                abs_path = os.path.join(dirpath, filename)
                # Caminho relativo a partir de addon/
                rel_path = os.path.relpath(abs_path, ADDON_DIR)
                # Normaliza separadores para '/' dentro do zip
                arc_name = rel_path.replace("\\", "/")

                zf.write(abs_path, arc_name)
                file_count += 1
                print(f"  + {arc_name}")

        # Licencas das dependencias vendorizadas. Os metadados dist-info nao
        # sao necessarios em runtime, mas os avisos de licenca devem acompanhar
        # o software redistribuido.
        lib_dir = os.path.join(ADDON_DIR, "globalPlugins", "nvdastudio", "lib")
        if os.path.isdir(lib_dir):
            for dirpath, _, filenames in os.walk(lib_dir):
                normalized = dirpath.replace("\\", "/").lower()
                if ".dist-info" not in normalized:
                    continue
                dist_info_dir = next(
                    (part for part in dirpath.replace("\\", "/").split("/") if part.endswith(".dist-info")),
                    "",
                )
                if dist_info_dir.startswith(LEGACY_DIST_INFO_PREFIXES):
                    continue
                for filename in filenames:
                    upper_name = filename.upper()
                    if "LICENSE" not in upper_name and "COPYING" not in upper_name and upper_name != "AUTHORS":
                        continue
                    abs_path = os.path.join(dirpath, filename)
                    rel_path = os.path.relpath(abs_path, lib_dir).replace("\\", "/")
                    arc_name = f"globalPlugins/nvdastudio/licenses/{rel_path}"
                    zf.write(abs_path, arc_name)
                    file_count += 1
                    print(f"  + {arc_name}")

    size_kb = os.path.getsize(output_path) / 1024
    print("\nBuild concluido!")
    print(f"  Arquivo : dist/{output_name}")
    print(f"  Arquivos: {file_count}")
    print(f"  Tamanho : {size_kb:.1f} KB")
    return output_path


if __name__ == "__main__":
    print("Construindo NVDAStudio...\n")
    try:
        path = build()
        print(f"\nPara instalar: copie '{os.path.basename(path)}' e abra com o NVDA.")
    except Exception as exc:
        print(f"\nERRO no build: {exc}")
        raise SystemExit(1)
