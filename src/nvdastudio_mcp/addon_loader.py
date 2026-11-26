import configparser
import os
import zipfile
from dataclasses import dataclass, field

from .injection_guard import sanitize_untrusted_block
from .logger import get_logger

MODULE_VERSION = "1.5.0"
_logger = get_logger("addon_loader")

_MAX_CODE_CHARS  = 8000    # per-file limit so the context is not saturated
_MAX_DOC_CHARS   = 2000    # limit for documentation
_MAX_TOTAL_CHARS = 60_000  # total limit of the code returned to Claude (~15K tokens)


@dataclass
class AddonContext:
	"""Context extracted from an existing add-on for use in iterative mode."""
	addon_name: str
	version: str
	summary: str
	source_path: str                     # original folder or .nvda-addon
	python_files: dict[str, str]         # path -> content (truncated if necessary)
	manifest_raw: str                    # raw content of manifest.ini
	doc_content: str                     # userGuide.html (first one found)
	dependencies: list[str] = field(default_factory=list)
	load_errors: list[str] = field(default_factory=list)

	def to_context_text(self) -> str:
		"""
		Builds the text that enriches a query with the current code.

		The loaded add-on may have been written by someone else (a third-party
		.nvda-addon, not necessarily the request of this session) -- manifest, code
		and documentation go in as external DATA (sanitize_untrusted_block), never
		as an instruction, even if a comment or docstring tries to look like one.
		"""
		parts = [
			f"=== EXISTING ADD-ON: {self.addon_name} v{self.version} ===",
			f"Description: {self.summary}",
			f"Source: {self.source_path}",
			"",
			sanitize_untrusted_block(
				self.manifest_raw[:1500], f"manifest.ini of {self.addon_name}",
			),
			"",
		]
		budget = _MAX_TOTAL_CHARS - sum(len(p) for p in parts)
		for path, code in self.python_files.items():
			if budget <= 0:
				parts.append(f"--- {path} --- [omitted: budget exhausted]")
				continue
			if len(code) > budget:
				code = code[:budget] + "\n[... omitted due to context limit ...]"
				budget = 0
			else:
				budget -= len(code)
			parts.append(sanitize_untrusted_block(f"--- {path} ---\n{code}", path))
		if self.doc_content:
			parts.append(sanitize_untrusted_block(
				self.doc_content[:_MAX_DOC_CHARS], f"documentation of {self.addon_name}",
			))
			parts.append("")
		if self.dependencies:
			parts.append(f"Bundled dependencies: {', '.join(self.dependencies)}")
		return "\n".join(parts)






def load_addon_from_nvda_addon(nvda_addon_path: str) -> AddonContext:
	"""
	Loads an add-on from a .nvda-addon file (ZIP).
	Does not execute code — it only decompresses in memory and reads text.
	"""
	if not os.path.isfile(nvda_addon_path):
		return AddonContext(
			addon_name="unknown", version="0.0.0", summary="",
			source_path=nvda_addon_path, python_files={}, manifest_raw="",
			doc_content="",
			load_errors=[f"File not found: {nvda_addon_path}"]
		)

	errors: list[str] = []
	manifest_raw  = ""
	manifest_data: dict[str, str] = {}
	python_files: dict[str, str] = {}
	doc_content   = ""

	try:
		with zipfile.ZipFile(nvda_addon_path, "r") as zf:
			names = zf.namelist()

			# manifest.ini
			if "manifest.ini" in names:
				manifest_raw = zf.read("manifest.ini").decode("utf-8", errors="replace")
				cfg = configparser.ConfigParser()
				cfg.read_string("[addon]\n" + manifest_raw)
				manifest_data = dict(cfg["addon"]) if "addon" in cfg else {}
			else:
				errors.append("manifest.ini missing from the .nvda-addon.")

			# Python files — excludes lib/ (bundled dependencies)
			for name in sorted(names):
				if name.endswith(".py") and "globalPlugins" in name:
					# Skips files inside any lib/ folder
					parts_path = name.replace("\\", "/").split("/")
					if "lib" in parts_path:
						continue
					raw = zf.read(name).decode("utf-8", errors="replace")
					if len(raw) > _MAX_CODE_CHARS:
						raw = raw[:_MAX_CODE_CHARS] + f"\n[... {len(raw)-_MAX_CODE_CHARS} chars omitted ...]"
					python_files[name] = raw

			# Documentation
			for name in names:
				if name.lower().endswith(".html") and "doc" in name:
					doc_content = zf.read(name).decode("utf-8", errors="replace")[:_MAX_DOC_CHARS]
					break

	except zipfile.BadZipFile as exc:
		errors.append(f"Corrupted .nvda-addon file: {exc}")
	except Exception as exc:
		errors.append(f"Error reading .nvda-addon: {exc}")

	addon_name = manifest_data.get("name", os.path.splitext(os.path.basename(nvda_addon_path))[0])
	version    = manifest_data.get("version", "0.0.0")
	summary    = manifest_data.get("summary", "")

	_logger.info("[OK] addon_loader: loaded '%s' v%s from the .nvda-addon (%d Python files)",
				 addon_name, version, len(python_files))

	return AddonContext(
		addon_name=addon_name, version=version, summary=summary,
		source_path=nvda_addon_path, python_files=python_files,
		manifest_raw=manifest_raw, doc_content=doc_content,
		load_errors=errors,
	)
