"""Apoio dos testes: monta uma pasta de addon a partir de blocos {filename, code}.

Vive nos testes porque o servidor grava arquivos so por `write_addon_file`.
"""

import html as html_lib
import os
import re
from datetime import datetime

from nvdastudio_mcp.addon_builder import (
	AddonBuilderError,
	_is_development_artifact,
	write_addon_file,
	_logger,
)


# Regex para detectar filenames sinteticos gerados quando o modelo omite a anotacao
_SYNTHETIC_FNAME_RE = re.compile(r'^arquivo_\d+\.(py|ini|html)$', re.IGNORECASE)


def _deduplicate_blocks(blocks: list[dict]) -> list[dict]:
	"""Elimina blocos duplicados e normaliza paths de globalPlugins/ antes de salvar."""
	gp_re = re.compile(r'^globalPlugins/([^/]+)/(.+)$', re.IGNORECASE)

	# Passo 1: descobre o nome canonico (ultimo globalPlugins/<X>/ visto)
	canonical_dir: str | None = None
	for block in blocks:
		raw = block.get("filename", "").replace("\\", "/").lstrip("/")
		m = gp_re.match(raw)
		if m:
			canonical_dir = m.group(1)

	# Passo 2: remapeia e deduplica; dict preserva "ultimo vence" por chave
	seen: dict[str, dict] = {}
	for block in blocks:
		raw = block.get("filename", "").replace("\\", "/").lstrip("/")
		m = gp_re.match(raw) if canonical_dir else None
		if m:
			inner = m.group(2)
			key = f"globalPlugins/{canonical_dir}/{inner}"
			seen[key] = {**block, "filename": key}
		else:
			key = raw if raw else f"__noname_{id(block)}"
			seen[key] = block

	result = list(seen.values())
	if len(result) < len(blocks):
		removed = len(blocks) - len(result)
		_logger.info(
			"[DEDUP] _deduplicate_blocks: %d bloco(s) duplicado(s) removido(s). "
			"Dir canonico: %s", removed, canonical_dir
		)

	# Filtra arquivos .py orfaos em globalPlugins/: apenas arquivos com nomes
	# sinteticos (arquivo_N.py) sem GlobalPlugin/AppModule sao residuos de montagem
	# que causam STRUCTURE-005 no validador.
	# Modulos de suporte legitimos (settings_panel.py, gemini_service.py, etc.)
	# sao SEMPRE preservados, independente do conteudo — foram gerados com nome
	# explicito pelo modelo e sao importados pelo __init__.py.
	# Regra: verificacao deterministica — nao depende de modelo.
	filtered: list[dict] = []
	orphan_count = 0
	for block in result:
		fname = block.get("filename", "").replace("\\", "/").lower()
		basename = os.path.basename(fname)
		is_globalPlugin_py = (
			gp_re.match(block.get("filename", "").replace("\\", "/").lstrip("/"))
			and fname.endswith(".py")
		)
		if is_globalPlugin_py and not fname.endswith("__init__.py"):
			code = block.get("code", "")
			is_synthetic = bool(_SYNTHETIC_FNAME_RE.match(basename))
			if is_synthetic and "class GlobalPlugin" not in code and "class AppModule" not in code:
				_logger.warning(
					"[ORFAO] Arquivo Python com nome sintetico sem GlobalPlugin/AppModule descartado: %s",
					block.get("filename", "")
				)
				orphan_count += 1
				continue
		filtered.append(block)

	if orphan_count:
		_logger.info("[DEDUP] %d arquivo(s) orfao(s) removido(s) de globalPlugins/.",
					 orphan_count)

	return filtered


def _generate_minimal_user_guide(addon_name: str) -> str:
	"""Guia do usuario minimo (HTML) para addons de teste sem documentacao."""
	seguro = html_lib.escape(addon_name or "Add-on")
	return (
		"<!DOCTYPE html>\n"
		'<html lang="pt-BR"><head><meta charset="UTF-8">\n'
		f"<title>{seguro}</title></head>\n"
		f"<body><h1>{seguro}</h1>\n"
		"<p>Este add-on foi criado com o NVDAStudio.</p>\n"
		"<h2>Como usar</h2>\n"
		"<p>Os comandos deste add-on aparecem em Preferencias, Gestos de "
		f"entrada, na categoria {seguro}. As opcoes, quando existirem, ficam "
		"em Preferencias, Configuracoes.</p>\n"
		"<h2>Observacao</h2>\n"
		"<p>Este guia foi gerado automaticamente porque a etapa de "
		"documentacao nao pode ser concluida. O add-on funciona "
		"normalmente.</p>\n"
		"</body></html>\n"
	)


def _generate_minimal_manifest(addon_name: str) -> str:
	"""Gera um manifest.ini minimo deterministico para addons de teste."""
	from nvdastudio_mcp.project_policy import PROJECT_MIN_NVDA, PROJECT_LAST_TESTED_NVDA
	return (
		# 4.21.0 -- a secao [add-on] foi REMOVIDA daqui.
		#
		# O manifest do NVDA usa ConfigObj sem secoes; o cabecalho [add-on]
		# tornaria o fallback invalido.
		#
		# defeito ficava escondido no caminho de excecao: a rede de seguranca
		# produzia exatamente o erro grave que o resto do projeto rejeita.
		f"name = {addon_name}\n"
		f"summary = Add-on criado com o NVDAStudio\n"
		f"author = NVDAStudio\n"
		f"version = 1.0.0\n"
		f"minimumNVDAVersion = {PROJECT_MIN_NVDA}\n"
		f"lastTestedNVDAVersion = {PROJECT_LAST_TESTED_NVDA}\n"
		f"url = https://github.com/nvdastudio\n"
	)


def save_addon_files(
	blocks: list[dict],
	output_dir: str,
	addon_name: str,
	use_timestamp: bool = True,
	garantir_doc: bool = True,
) -> tuple[str, list[str]]:
	"""
	Salva os arquivos do addon no diretorio de saida, preservando a estrutura
	de diretorios necessaria para o NVDA.

	Estrutura esperada dentro de addon_folder:
		manifest.ini                              <- raiz
		globalPlugins/<addon_name>/__init__.py    <- plugin principal

	O bloco com filename='manifest.ini' vai para a raiz.
	Blocos com filename='globalPlugins/nomeAddon/__init__.py' preservam o path.
	Blocos sem path (apenas nome de arquivo) vao para globalPlugins/<addon_name>/.

	use_timestamp=True (padrao): pasta criada com sufixo de data/hora para evitar
	  conflitos. Ideal para historico de geracoes.
	use_timestamp=False: pasta criada com nome exato do addon (sem sufixo).
	  Ideal para instalar diretamente na pasta de addons do NVDA.

	Seguranca: path traversal prevenido via os.path.normpath + verificacao de prefixo.

	Returns:
		(addon_folder: str, saved_paths: list[str])
	"""
	if not blocks:
		raise AddonBuilderError("[ERRO] Nenhum bloco de codigo para salvar.")

	# Se nenhum bloco manifest.ini existe nos
	# blocos extraidos, gera um manifest minimo deterministico. Sem isso,
	# o addon nao instala (STRUCTURE-001). Causa raiz: modelo 503 durante
	_has_manifest = any(
		(b.get("filename") or "").replace("\\", "/").lstrip("/").lower() == "manifest.ini"
		or (b.get("filename") or "").replace("\\", "/").lstrip("/").lower().endswith("/manifest.ini")
		for b in blocks
	)
	if not _has_manifest:
		_fallback_manifest = _generate_minimal_manifest(addon_name)
		blocks.insert(0, {
			"filename": "manifest.ini",
			"code": _fallback_manifest,
			"language": "ini",
		})
		_logger.warning(
			"[MANIFEST-FALLBACK] Nenhum bloco manifest.ini encontrado. "
			"Gerado manifest minimo deterministico para %s.",
			addon_name,
		)

	# Guia do usuario: mesma rede de seguranca do manifest acima.
	#
	# O caminho de producao garante documentacao por padrao; testes de validacao
	# podem desligar somente este fallback com garantir_doc=False.
	_tem_guia = any(
		(b.get("filename") or "").replace("\\", "/").lower().endswith(".html")
		for b in blocks
	)
	if garantir_doc and not _tem_guia:
		_guia = _generate_minimal_user_guide(addon_name)
		for _idioma in ("pt_BR", "en"):
			blocks.append({
				"filename": f"doc/{_idioma}/userGuide.html",
				"code": _guia,
				"language": "html",
			})
		_logger.warning(
			"[DOC-FALLBACK] Nenhum guia do usuario nos blocos. Gerado guia "
			"minimo deterministico para %s.", addon_name,
		)

	# Exclui blocos de testes — nunca devem ir para o addon instalado (v2.1.0)
	# Testes gerados pela IA sao uteis para o desenvolvedor, nao para o usuario final.
	blocks = [
		b for b in blocks
		if not _is_development_artifact(b.get("filename") or "")
	]

	blocks = _deduplicate_blocks(blocks)

	safe_name = re.sub(r"[^\w]", "_", addon_name)
	if use_timestamp:
		timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
		addon_folder = os.path.join(output_dir, f"{safe_name}_{timestamp}")
	else:
		addon_folder = os.path.join(output_dir, safe_name)
	os.makedirs(addon_folder, exist_ok=True)

	# Pasta padrao para arquivos Python sem path explicito
	default_plugin_dir = os.path.join(addon_folder, "globalPlugins", safe_name)

	saved = []
	for block in blocks:
		raw_fname: str = block.get("filename", "")
		lang: str = block.get("language", "python")

		# Normaliza separadores e remove leading slashes
		raw_fname = raw_fname.replace("\\", "/").lstrip("/")

		if not raw_fname:
			# Sem nome: usa nome padrao baseado na linguagem
			ext = ".ini" if lang == "ini" else ".py"
			raw_fname = f"__init__{ext}"

		# Decide onde salvar:
		# manifest.ini -> raiz do addon_folder
		# Caminhos com '/' -> preservar estrutura relativa dentro de addon_folder
		# Arquivo simples sem '/' -> globalPlugins/<addon_name>/
		if raw_fname.lower() == "manifest.ini" or raw_fname.lower().endswith("manifest.ini"):
			dest_rel = "manifest.ini"
		elif "/" in raw_fname:
			dest_rel = raw_fname   # preserva caminho completo
		else:
			# Arquivo .py sem caminho: coloca em globalPlugins/<addon_name>/
			os.makedirs(default_plugin_dir, exist_ok=True)
			dest_rel = os.path.join("globalPlugins", safe_name, raw_fname)

		dest_abs = write_addon_file(addon_folder, dest_rel, block["code"])
		if dest_abs is None:
			continue
		saved.append(dest_abs)

	_logger.info("[OK] %d arquivo(s) salvos em %s", len(saved), addon_folder)
	return addon_folder, saved
