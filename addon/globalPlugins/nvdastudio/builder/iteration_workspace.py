"""Prepara uma cópia editável do addon, sem modificar o original instalado."""
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

MODULE_VERSION = "1.1.0"


def _ensure_documentation_layout(root: Path) -> None:
	"""Cria o fallback de documentacao que o NVDA realmente procura."""
	manifest = root / "manifest.ini"
	readme = root / "readme.html"
	if not manifest.is_file() or not readme.is_file() or (root / "doc").is_dir():
		return
	doc_name = "readme.html"
	for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
		key, separator, value = line.partition("=")
		if separator and key.strip().casefold() == "docfilename":
			doc_name = value.strip().strip('"').strip("'") or doc_name
			break
	destination = root / "doc" / "en" / Path(doc_name).name
	destination.parent.mkdir(parents=True, exist_ok=True)
	shutil.copy2(readme, destination)


def prepare_iteration_workspace(context, parent_dir: str | None = None) -> str:
	root = Path(tempfile.mkdtemp(prefix="nvdastudio_iteration_", dir=parent_dir))
	source = Path(context.source_path) if context.source_path else None
	if source is not None and source.is_dir():
		for folder, dirs, files in os.walk(source, followlinks=False):
			dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", ".factory", ".droid", ".pytest_cache", "tests"}
				and not (Path(folder) / d).is_symlink()]
			for name in files:
				original = Path(folder) / name
				if original.is_symlink() or name.endswith((".nvda-addon", ".zip", ".pyc")):
					continue
				target = root / original.relative_to(source)
				target.parent.mkdir(parents=True, exist_ok=True)
				shutil.copy2(original, target)
	elif source is not None and source.is_file() and zipfile.is_zipfile(source):
		with zipfile.ZipFile(source) as archive:
			for item in archive.infolist():
				target = (root / item.filename).resolve()
				if not target.is_relative_to(root.resolve()):
					raise ValueError("Caminho do pacote fora da pasta de trabalho")
				if item.is_dir():
					continue
				target.parent.mkdir(parents=True, exist_ok=True)
				with archive.open(item) as src, target.open("wb") as dst:
					shutil.copyfileobj(src, dst)
	else:
		contents = dict(context.python_files)
		contents["manifest.ini"] = context.manifest_raw
		if context.doc_content:
			contents["readme.html"] = context.doc_content
		for relative, content in contents.items():
			target = (root / relative).resolve()
			if not target.is_relative_to(root.resolve()):
				raise ValueError("Caminho do addon fora da pasta de trabalho")
			target.parent.mkdir(parents=True, exist_ok=True)
			target.write_text(content, encoding="utf-8")
	_ensure_documentation_layout(root)
	return str(root)
