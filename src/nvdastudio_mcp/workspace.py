"""Pasta de trabalho do NVDAStudio e confinamento de caminhos.

Toda ferramenta que le ou grava arquivo passa por aqui. O que o Claude manda
(nome do addon, caminho relativo) e entrada nao confiavel: nada resolve para
fora da pasta de trabalho, nem por `..`, nem por caminho absoluto, nem por
link simbolico.
"""

import os
from pathlib import Path

ENV_WORKSPACE = "NVDASTUDIO_WORKSPACE"
_MAX_ADDON_NAME = 64


class WorkspaceError(Exception):
    """Pedido que sai da pasta de trabalho ou aponta para algo que nao existe."""


def default_root() -> Path:
    configured = os.environ.get(ENV_WORKSPACE, "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "NVDAStudio"


class Workspace:
    def __init__(self, root: Path | None = None) -> None:
        self.root: Path = (root or default_root()).expanduser().resolve()

    def ensure(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def _inside(self, candidate: Path, base: Path) -> Path:
        resolved = candidate.resolve()
        if resolved != base and base not in resolved.parents:
            raise WorkspaceError(f"caminho fora da pasta permitida: {candidate}")
        return resolved

    def addon_dir(self, addon: str, *, must_exist: bool = True) -> Path:
        """Pasta de um addon, dado o nome (uma unica pasta direto na raiz)."""
        name = addon.strip()
        if (
            not name
            or len(name) > _MAX_ADDON_NAME
            or name in {".", ".."}
            or any(sep in name for sep in ("/", "\\", ":"))
        ):
            raise WorkspaceError(
                "nome de addon invalido: use apenas o nome da pasta, sem caminho"
            )
        path = self._inside(self.root / name, self.root)
        if path == self.root:
            raise WorkspaceError("nome de addon invalido")
        if must_exist and not path.is_dir():
            raise WorkspaceError(f"addon nao encontrado na pasta de trabalho: {name}")
        return path

    def file_in_addon(self, addon: str, relative: str) -> Path:
        """Arquivo dentro de um addon; `relative` nunca escapa da pasta do addon."""
        base = self.addon_dir(addon)
        rel = relative.replace("\\", "/").strip()
        if not rel or rel.startswith("/") or (len(rel) > 1 and rel[1] == ":"):
            raise WorkspaceError(f"caminho relativo invalido: {relative!r}")
        return self._inside(base / rel, base)

    def package_path(self, package: str) -> Path:
        """Pacote .nvda-addon dentro da pasta de trabalho."""
        rel = package.replace("\\", "/").strip()
        if not rel.lower().endswith(".nvda-addon"):
            raise WorkspaceError("o pacote precisa terminar em .nvda-addon")
        candidate = Path(rel)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        path = self._inside(candidate, self.root)
        if not path.is_file():
            raise WorkspaceError(f"pacote nao encontrado: {package}")
        return path

    def list_addons(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            entry.name
            for entry in self.root.iterdir()
            if entry.is_dir() and (entry / "manifest.ini").is_file()
        )
