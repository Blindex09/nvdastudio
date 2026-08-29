import configparser
import os
import zipfile
from dataclasses import dataclass, field

from ..utils.logger import get_logger

MODULE_VERSION = "1.4.0"
_logger = get_logger("addon_loader")

_MAX_CODE_CHARS  = 8000    # limite por arquivo para nao saturar o contexto
_MAX_DOC_CHARS   = 2000    # limite para documentacao
_MAX_TOTAL_CHARS = 60_000  # limite total do bloco de codigo no prompt (~15K tokens)


@dataclass
class AddonContext:
	"""Contexto extraido de um addon existente para uso no modo iterativo."""
	addon_name: str
	version: str
	summary: str
	source_path: str                     # pasta ou .nvda-addon original
	python_files: dict[str, str]         # caminho -> conteudo (truncado se necessario)
	manifest_raw: str                    # conteudo bruto do manifest.ini
	doc_content: str                     # userGuide.html (primeiro encontrado)
	dependencies: list[str] = field(default_factory=list)
	load_errors: list[str] = field(default_factory=list)

	def to_prompt_context(self) -> str:
		"""
		Formata o contexto do addon como bloco de texto injetavel no prompt.
		Chamado pelo modo conversacional para enriquecer a query com o codigo atual.
		Respeita _MAX_TOTAL_CHARS para nao estourar o contexto do modelo.
		"""
		parts = [
			f"=== ADDON EXISTENTE: {self.addon_name} v{self.version} ===",
			f"Descricao: {self.summary}",
			f"Origem: {self.source_path}",
			"",
			"--- manifest.ini ---",
			self.manifest_raw[:1500],
			"",
		]
		budget = _MAX_TOTAL_CHARS - sum(len(p) for p in parts)
		for path, code in self.python_files.items():
			block = f"--- {path} ---\n{code}\n"
			if budget <= 0:
				parts.append(f"--- {path} --- [omitido: budget esgotado]")
				continue
			if len(block) > budget:
				block = f"--- {path} ---\n{code[:budget]}\n[... omitido por limite de contexto ...]\n"
				parts.append(block)
				budget = 0
			else:
				parts.append(block)
				budget -= len(block)
		if self.doc_content:
			parts.append("--- Documentacao (resumo) ---")
			parts.append(self.doc_content[:_MAX_DOC_CHARS])
			parts.append("")
		if self.dependencies:
			parts.append(f"Dependencias bundladas: {', '.join(self.dependencies)}")
		return "\n".join(parts)


def load_addon_from_folder(folder_path: str) -> AddonContext:
	"""
	Carrega addon a partir de uma pasta (saida de save_addon_files).
	Regra 9: apenas le arquivos — nao importa nem executa nada.
	"""
	if not os.path.isdir(folder_path):
		return AddonContext(
			addon_name="desconhecido", version="0.0.0", summary="",
			source_path=folder_path, python_files={}, manifest_raw="",
			doc_content="",
			load_errors=[f"Pasta nao encontrada: {folder_path}"]
		)

	errors: list[str] = []

	# 1. manifest.ini
	manifest_raw = ""
	manifest_data: dict[str, str] = {}
	manifest_path = os.path.join(folder_path, "manifest.ini")
	if os.path.isfile(manifest_path):
		try:
			with open(manifest_path, encoding="utf-8", errors="replace") as fh:
				manifest_raw = fh.read()
			cfg = configparser.ConfigParser()
			cfg.read_string("[addon]\n" + manifest_raw)
			manifest_data = dict(cfg["addon"]) if "addon" in cfg else {}
		except Exception as exc:
			errors.append(f"Erro ao ler manifest.ini: {exc}")
	else:
		errors.append("manifest.ini ausente na raiz da pasta.")

	addon_name = manifest_data.get("name", os.path.basename(folder_path))
	version    = manifest_data.get("version", "0.0.0")
	summary    = manifest_data.get("summary", "")

	# 2. Arquivos Python em globalPlugins/ — exclui lib/, __pycache__ e *.pyc
	python_files: dict[str, str] = {}
	gp_dir = os.path.join(folder_path, "globalPlugins")
	if os.path.isdir(gp_dir):
		for root, dirs, files in os.walk(gp_dir):
			# Exclui pastas que nao sao codigo do addon
			dirs[:] = [d for d in dirs if d not in ("lib", "__pycache__")]
			rel_root = os.path.relpath(root, gp_dir).replace("\\", "/")
			if "/lib/" in "/" + rel_root + "/" or rel_root.startswith("lib/") or rel_root == "lib":
				continue
			for fname in sorted(files):
				# Inclui apenas .py; exclui .pyc e outros
				if not fname.endswith(".py") or fname.endswith(".pyc"):
					continue
				full = os.path.join(root, fname)
				rel  = os.path.relpath(full, folder_path).replace("\\", "/")
				try:
					with open(full, encoding="utf-8", errors="replace") as fh:
						raw = fh.read()
					if len(raw) > _MAX_CODE_CHARS:
						raw = raw[:_MAX_CODE_CHARS] + f"\n[... {len(raw)-_MAX_CODE_CHARS} chars omitidos ...]"
					python_files[rel] = raw
				except Exception as exc:
					errors.append(f"Erro ao ler {rel}: {exc}")

	# 3. Documentacao (primeiro userGuide.html encontrado)
	doc_content = ""
	doc_dir = os.path.join(folder_path, "doc")
	if os.path.isdir(doc_dir):
		for root, _dirs, files in os.walk(doc_dir):
			for fname in files:
				if fname.lower().endswith(".html"):
					try:
						with open(os.path.join(root, fname),
								  encoding="utf-8", errors="replace") as fh:
							doc_content = fh.read()[:_MAX_DOC_CHARS]
					except Exception as exc:
						_logger.debug("[DEBUG] Falha ao ler doc %s: %s", fname, exc)
					break
			if doc_content:
				break

	# 4. Dependencias bundladas (pasta lib/)
	deps: list[str] = []
	lib_dir = os.path.join(folder_path, "lib")
	if os.path.isdir(lib_dir):
		deps = [d for d in os.listdir(lib_dir)
				if os.path.isdir(os.path.join(lib_dir, d)) and not d.startswith("_")]

	_logger.info("[OK] addon_loader: carregado '%s' v%s (%d arquivos Python, %d deps)",
				 addon_name, version, len(python_files), len(deps))

	return AddonContext(
		addon_name=addon_name, version=version, summary=summary,
		source_path=folder_path, python_files=python_files,
		manifest_raw=manifest_raw, doc_content=doc_content,
		dependencies=deps, load_errors=errors,
	)


def load_addon_from_blocks(
	blocks: list[dict], addon_name: str, version: str = "0.0.0", summary: str = "",
) -> AddonContext:
	"""
	Monta AddonContext direto dos blocos de codigo EM MEMORIA (formato de
	builder/addon_builder.py::extract_code_blocks(): {"filename", "code",
	"language"}) -- sem ler nada do disco. Usado pra ativar o modo iterativo
	logo apos uma criacao bem-sucedida, antes mesmo do usuario salvar os
	arquivos numa pasta (ver MODULE_VERSION 1.3.0).

	Regra 9: apenas monta estrutura em memoria — nao executa nada.
	"""
	python_files: dict[str, str] = {}
	manifest_raw = ""
	doc_content = ""
	for b in blocks:
		filename = (b.get("filename") or "").replace("\\", "/").lstrip("/")
		code = b.get("code") or ""
		if not filename:
			continue
		lower = filename.lower()
		if lower == "manifest.ini" or lower.endswith("/manifest.ini"):
			manifest_raw = code
		elif lower.endswith(".py") and "/lib/" not in f"/{filename}" and not lower.startswith("lib/"):
			if len(code) > _MAX_CODE_CHARS:
				code = code[:_MAX_CODE_CHARS] + f"\n[... {len(code)-_MAX_CODE_CHARS} chars omitidos ...]"
			python_files[filename] = code
		elif lower.endswith(".html") and not doc_content:
			doc_content = code[:_MAX_DOC_CHARS]

	return AddonContext(
		addon_name=addon_name, version=version, summary=summary,
		source_path="(recem-criado nesta sessao, ainda nao salvo em disco)",
		python_files=python_files, manifest_raw=manifest_raw,
		doc_content=doc_content,
	)


def load_addon_from_nvda_addon(nvda_addon_path: str) -> AddonContext:
	"""
	Carrega addon a partir de um arquivo .nvda-addon (ZIP).
	Regra 9: nao executa codigo — apenas descomprime em memoria e le texto.
	"""
	if not os.path.isfile(nvda_addon_path):
		return AddonContext(
			addon_name="desconhecido", version="0.0.0", summary="",
			source_path=nvda_addon_path, python_files={}, manifest_raw="",
			doc_content="",
			load_errors=[f"Arquivo nao encontrado: {nvda_addon_path}"]
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
				errors.append("manifest.ini ausente no .nvda-addon.")

			# Arquivos Python — exclui lib/ (dependencias bundladas)
			for name in sorted(names):
				if name.endswith(".py") and "globalPlugins" in name:
					# Pula arquivos dentro de qualquer pasta lib/
					parts_path = name.replace("\\", "/").split("/")
					if "lib" in parts_path:
						continue
					raw = zf.read(name).decode("utf-8", errors="replace")
					if len(raw) > _MAX_CODE_CHARS:
						raw = raw[:_MAX_CODE_CHARS] + f"\n[... {len(raw)-_MAX_CODE_CHARS} chars omitidos ...]"
					python_files[name] = raw

			# Documentacao
			for name in names:
				if name.lower().endswith(".html") and "doc" in name:
					doc_content = zf.read(name).decode("utf-8", errors="replace")[:_MAX_DOC_CHARS]
					break

	except zipfile.BadZipFile as exc:
		errors.append(f"Arquivo .nvda-addon corrompido: {exc}")
	except Exception as exc:
		errors.append(f"Erro ao ler .nvda-addon: {exc}")

	addon_name = manifest_data.get("name", os.path.splitext(os.path.basename(nvda_addon_path))[0])
	version    = manifest_data.get("version", "0.0.0")
	summary    = manifest_data.get("summary", "")

	_logger.info("[OK] addon_loader: carregado '%s' v%s do .nvda-addon (%d arquivos Python)",
				 addon_name, version, len(python_files))

	return AddonContext(
		addon_name=addon_name, version=version, summary=summary,
		source_path=nvda_addon_path, python_files=python_files,
		manifest_raw=manifest_raw, doc_content=doc_content,
		load_errors=errors,
	)
