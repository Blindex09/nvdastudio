import configparser
import os
import zipfile
from dataclasses import dataclass, field

from .injection_guard import sanitize_untrusted_block
from .logger import get_logger

MODULE_VERSION = "1.5.0"
_logger = get_logger("addon_loader")

_MAX_CODE_CHARS  = 8000    # limite por arquivo para nao saturar o contexto
_MAX_DOC_CHARS   = 2000    # limite para documentacao
_MAX_TOTAL_CHARS = 60_000  # limite total do codigo devolvido ao Claude (~15K tokens)


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

	def to_context_text(self) -> str:
		"""
		Chamado pelo modo conversacional para enriquecer a query com o codigo atual.

		O addon carregado pode ter sido escrito por outra pessoa (.nvda-addon de
		terceiros, nao necessariamente o pedido desta sessao) -- manifest, codigo
		e documentacao entram como DADO externo (sanitize_untrusted_block), nunca
		como instrucao, mesmo que um comentario ou docstring tente parecer uma.
		"""
		parts = [
			f"=== ADDON EXISTENTE: {self.addon_name} v{self.version} ===",
			f"Descricao: {self.summary}",
			f"Origem: {self.source_path}",
			"",
			sanitize_untrusted_block(
				self.manifest_raw[:1500], f"manifest.ini de {self.addon_name}",
			),
			"",
		]
		budget = _MAX_TOTAL_CHARS - sum(len(p) for p in parts)
		for path, code in self.python_files.items():
			if budget <= 0:
				parts.append(f"--- {path} --- [omitido: budget esgotado]")
				continue
			if len(code) > budget:
				code = code[:budget] + "\n[... omitido por limite de contexto ...]"
				budget = 0
			else:
				budget -= len(code)
			parts.append(sanitize_untrusted_block(f"--- {path} ---\n{code}", path))
		if self.doc_content:
			parts.append(sanitize_untrusted_block(
				self.doc_content[:_MAX_DOC_CHARS], f"documentacao de {self.addon_name}",
			))
			parts.append("")
		if self.dependencies:
			parts.append(f"Dependencias bundladas: {', '.join(self.dependencies)}")
		return "\n".join(parts)






def load_addon_from_nvda_addon(nvda_addon_path: str) -> AddonContext:
	"""
	Carrega addon a partir de um arquivo .nvda-addon (ZIP).
	nao executa codigo — apenas descomprime em memoria e le texto.
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
