"""NVDAStudio workspace folder and path confinement.

Every tool that reads or writes a file goes through here. What Claude sends
(add-on name, relative path) is untrusted input: nothing resolves outside the
workspace folder, not through `..`, not through an absolute path, not through
a symbolic link.
"""

import os
from pathlib import Path

ENV_WORKSPACE = "NVDASTUDIO_WORKSPACE"
_MAX_ADDON_NAME = 64


class WorkspaceError(Exception):
    """Request that leaves the workspace folder or points to something that does not exist."""


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
            raise WorkspaceError(f"path outside the allowed folder: {candidate}")
        return resolved

    def addon_dir(self, addon: str, *, must_exist: bool = True) -> Path:
        """Folder of an add-on, given its name (a single folder directly at the root)."""
        name = addon.strip()
        if (
            not name
            or len(name) > _MAX_ADDON_NAME
            or name in {".", ".."}
            or any(sep in name for sep in ("/", "\\", ":"))
        ):
            raise WorkspaceError(
                "invalid add-on name: use only the folder name, without a path"
            )
        path = self._inside(self.root / name, self.root)
        if path == self.root:
            raise WorkspaceError("invalid add-on name")
        if must_exist and not path.is_dir():
            raise WorkspaceError(f"add-on not found in the workspace folder: {name}")
        return path

    def file_in_addon(self, addon: str, relative: str) -> Path:
        """File inside an add-on; `relative` never escapes the add-on folder."""
        base = self.addon_dir(addon)
        rel = relative.replace("\\", "/").strip()
        if not rel or rel.startswith("/") or (len(rel) > 1 and rel[1] == ":"):
            raise WorkspaceError(f"invalid relative path: {relative!r}")
        return self._inside(base / rel, base)

    def package_path(self, package: str) -> Path:
        """A .nvda-addon package inside the workspace folder."""
        rel = package.replace("\\", "/").strip()
        if not rel.lower().endswith(".nvda-addon"):
            raise WorkspaceError("the package must end in .nvda-addon")
        candidate = Path(rel)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        path = self._inside(candidate, self.root)
        if not path.is_file():
            raise WorkspaceError(f"package not found: {package}")
        return path

    def list_addons(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            entry.name
            for entry in self.root.iterdir()
            if entry.is_dir() and (entry / "manifest.ini").is_file()
        )
