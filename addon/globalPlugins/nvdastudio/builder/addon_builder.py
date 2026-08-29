import ast
import configparser
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import sys
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from html.parser import HTMLParser

from ..utils.logger import get_logger, log_decision
from ..ai.llm_factory import create_llm_client
from ..utils.project_policy import (
	PROJECT_MIN_NVDA,
	PROJECT_LAST_TESTED_NVDA,
	parse_version_tuple,
)
# session_memory: importacao opcional — registra falhas de dependencias para
# aprendizado adaptativo. Se indisponivel (ex.: TinyDB ausente), o bundle
# continua normalmente sem registrar. try/except ImportError: clausula
# permitida pelo claude.md para dependencias genuinamente opcionais.
try:
	from ..memory.session_memory import memory as _session_memory_mem
except ImportError:
	_session_memory_mem = None  # type: ignore[assignment]

MODULE_VERSION = "4.13.0"

# NVDA 2026.1+ is built with CPython 3.13 for 64-bit Windows.  Dependency
# wheels must target that runtime, not the Python interpreter used to run
# NVDAStudio's build process.
_NVDA_PYTHON_VERSION = "313"
_NVDA_WHEEL_PLATFORM = "win_amd64"
_NVDA_WHEEL_ABI = "cp313"

# Regex para detectar filenames sinteticos gerados quando o LLM omite a anotacao
_SYNTHETIC_FNAME_RE = re.compile(r'^arquivo_\d+\.(py|ini|html)$', re.IGNORECASE)

_logger = get_logger("addon_builder")

# Campos obrigatorios no manifest.ini
_MANIFEST_REQUIRED_FIELDS = ["name", "summary", "author", "version", "minimumNVDAVersion"]

# Regex para nomes pip validos (PEP 508 basico — sem extras, URLs, paths ou versao).
# Aceita: "requests", "openai-whisper", "Pillow", "my.package", "pkg_2"
# Rejeita: "../evil", "http://...", "pkg[extra]", "pkg; sys_platform=='win32'"
_SAFE_PKG_NAME: re.Pattern = re.compile(
	r'^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$'
)


# Gestures reservados pelo NVDA core — addons nao devem redefinir esses atalhos.
# Fonte: NVDA User Guide e codigo-fonte do NVDA (inputCore, globalCommands).
# Usado por _check_reserved_gestures() / NVDA-009.
_NVDA_CORE_GESTURES: frozenset = frozenset({
	"kb:nvda+n", "kb:nvda+f1", "kb:nvda+f2", "kb:nvda+q",
	"kb:nvda+shift+s", "kb:nvda+p", "kb:nvda+ctrl+p",
	"kb:nvda+v", "kb:nvda+t", "kb:nvda+b", "kb:nvda+end",
	"kb:nvda+shift+end", "kb:nvda+numpad5", "kb:nvda+numpad8",
	"kb:nvda+numpad9", "kb:nvda+numpad7", "kb:nvda+numpad4",
	"kb:nvda+numpad6", "kb:nvda+1", "kb:nvda+2", "kb:nvda+3",
	"kb:nvda+4", "kb:nvda+5", "kb:nvda+6", "kb:nvda+7",
	"kb:nvda+8", "kb:nvda+f3", "kb:nvda+f4",
})


def _package_exists_on_pypi(pkg: str) -> bool:
	"""
	Verifica se um pacote existe no PyPI via HEAD request.

	Retorna True se o pacote existe (HTTP 200) ou se nao foi possivel verificar
	(timeout, sem rede, erro de servidor) — fail-open para nao bloquear instalaÃ§ao.
	Retorna False apenas para HTTP 404 — pacote definitivamente nao existe.

	Sem keywords. A decisao semantica de evitar o pacote fica no LLM via
	contexto de dep_failures injetado pelo code_generator.
	Regra 9: nao executa codigo — apenas consulta API REST.
	"""

	url = f"https://pypi.org/pypi/{pkg}/json"
	# B310: valida o scheme explicitamente antes de abrir -- url e montada com
	# prefixo https:// fixo (pkg entra so no path), mas a checagem fecha a
	# classe de bug de qualquer jeito que um scheme file:/ftp:/etc pudesse entrar.
	parsed = urllib.parse.urlparse(url)
	if parsed.scheme not in ("http", "https"):
		_logger.warning("[PYPI] Scheme nao permitido para verificar '%s': %s", pkg, parsed.scheme)
		return True
	req = urllib.request.Request(url, method="HEAD")
	try:
		with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310 -- scheme validado acima
			return resp.status == 200
	except urllib.error.HTTPError as exc:
		if exc.code == 404:
			_logger.info("[PYPI] Pacote '%s' nao encontrado no PyPI (404).", pkg)
			return False
		# 5xx, 403, etc — PyPI pode estar instavel, fail-open
		_logger.info("[PYPI] Erro HTTP %d ao verificar '%s' — fail-open.", exc.code, pkg)
		return True
	except (socket.timeout, OSError) as exc:
		# Sem internet ou timeout — nao bloqueia o bundle
		_logger.info("[PYPI] Sem conectividade ao verificar '%s' (%s) — fail-open.", pkg, exc)
		return True
	except Exception as exc:
		_logger.info("[PYPI] Erro inesperado ao verificar '%s' (%s) — fail-open.", pkg, exc)
		return True


def _is_safe_package_name(pkg: str) -> bool:
	"""
	Valida nome de pacote pip antes de passar ao subprocess.
	Extrai apenas o nome base (sem versao) e verifica contra PEP 508 basico.
	Rejeita extras, URLs, paths e qualquer metacaractere.

	Seguranca (SEC-001): pacotes vem do output da LLM — devem ser sanitizados.
	"""
	# Remove especificadores de versao simples: pkg==1.0, pkg>=2.0, pkg~=1.2
	base = re.split(r'[=<>!~@]', pkg)[0].strip()
	return bool(_SAFE_PKG_NAME.match(base))


class AddonBuilderError(Exception):
	"""Erro na geracao ou empacotamento do addon."""
	pass

# Campos que nunca devem aparecer no manifest.ini do addon gerado.
# sha256: calculado pelo empacotador, nunca declarado manualmente.
# configSpec: responsabilidade do codigo Python do addon, nao do manifest.
_FORBIDDEN_MANIFEST_FIELDS = frozenset({"sha256", "configspec"})


def _sanitize_manifest(code: str) -> str:
	"""
	Sanitizacao deterministica do manifest.ini gerado pela LLM.

	ConfigObj (usado pelo NVDA para parsear manifest.ini) interpreta qualquer
	valor de campo que contenha uma quebra de linha como lista Python, causando
	VdtTypeError fatal na instalacao do addon.

	Esta funcao garante que todos os campos de texto do manifest fiquem em
	uma unica linha, independente do que a LLM gere.

	Algorithm:
	  1. Remove campos proibidos (sha256, configSpec) — determinisitco, antes do parse.
	  2. Junta campos de texto multiline em uma unica linha.

	Campos protegidos: summary, description, changelog (e qualquer campo de texto).
	Nao afeta campos de versao, url, name, docFileName.

	Regra 3/Regra 9: sanitizacao deterministica, nao semantica. Nao executa codigo.
	"""
	# Passo 1: remove campos proibidos linha a linha
	clean_lines = []
	for _ln in code.splitlines():
		_m = re.match(r"^(\w+)\s*=", _ln)
		if _m and _m.group(1).lower() in _FORBIDDEN_MANIFEST_FIELDS:
			_logger.warning("[MANIFEST] Campo proibido removido: %s", _m.group(1))
			continue
		clean_lines.append(_ln)
	code = "\n".join(clean_lines)

	# Passo 2: junta campos de texto multiline
	_TEXT_FIELDS = {"summary", "description", "changelog", "author"}
	lines = code.splitlines()
	result = []
	current_key = None
	current_val_parts = []

	def flush():
		if current_key is None:
			return
		if current_key in _TEXT_FIELDS and current_val_parts:
			# Une todas as partes em uma linha, separando por espaco
			joined = " ".join(p.strip() for p in current_val_parts if p.strip())
			# Remove virgulas ao final de cada parte (evita residuos de lista)
			joined = re.sub(r",\s*$", "", joined.strip())
			# Remove aspas existentes para recolocar de forma consistente
			if joined.startswith('"') and joined.endswith('"'):
				joined = joined[1:-1]
			# ConfigObj interpreta valores com virgula como lista (VdtTypeError fatal).
			# Envolve em aspas duplas sempre que houver virgula no valor.
			if "," in joined:
				joined = f'"{joined}"'
			result.append(f"{current_key} = {joined}")
		elif current_val_parts:
			result.append(f"{current_key} = {current_val_parts[0]}")
			for extra in current_val_parts[1:]:
				result.append(extra)

	for line in lines:
		m = re.match(r"^(\w+)\s*=\s*(.*)", line)
		if m:
			flush()
			current_key = m.group(1)
			current_val_parts = [m.group(2)]
		elif current_key is not None and (line.startswith(" ") or line.startswith("\t")):
			# Linha de continuacao (indentada) — parte de um valor multiline
			current_val_parts.append(line.strip())
		else:
			flush()
			current_key = None
			current_val_parts = []
			result.append(line)

	flush()
	return "\n".join(result)


# ------------------------------------------------------------------
# Helpers publicos para nome do addon
# ------------------------------------------------------------------

def name_from_manifest_blocks(blocks: list[dict]) -> str:
	"""
	Extrai o campo 'name' do bloco manifest.ini presente em blocks.

	Retorna o nome sanitizado (apenas letras, numeros e underscore) ou "" se
	nenhum manifest.ini for encontrado ou o campo name estiver ausente.

	Usado pelo studio_dialog para derivar o nombre correto do addon a partir
	do manifest gerado pela IA, em vez do inicio da query do usuario.
	"""
	for block in blocks:
		fname = (block.get("filename") or "").replace("\\", "/").lower()
		if fname == "manifest.ini" or fname.endswith("/manifest.ini"):
			code = block.get("code", "")
			for line in code.splitlines():
				m = re.match(r"^\s*name\s*=\s*(.+)$", line)
				if m:
					raw = m.group(1).strip().strip('"').strip("'")
					# Sanitiza: permite letras, numeros, underscores e hifens
					sanitized = re.sub(r"[^\w-]", "_", raw)
					sanitized = re.sub(r"_+", "_", sanitized).strip("_")
					return sanitized if sanitized else ""
	return ""


# ------------------------------------------------------------------
# Extracao de codigo
# ------------------------------------------------------------------

def _infer_python_filename(code: str, canonical_dir: str | None, fallback_counter: int = 0) -> str | None:
	"""
	Tenta inferir o filename correto de um bloco Python sem anotacao.

	Regras (em ordem de prioridade):
	  1. Contem 'class GlobalPlugin'  -> __init__.py
	  2. Contem classe *SettingsPanel* ou *Settings* -> settings_panel.py
	  3. Contem classe *Service/Manager/etc.* -> snake_case.py
	  4. Contem classe *Dialog/Panel/Frame/Window* -> snake_case.py
	  5. Contem qualquer classe -> snake_case.py
	  6. Codigo sem classe -> module_N.py (preserva, nao descarta)
	  7. Vazio ou apenas comentarios -> None (descarta silenciosamente)

	Retorna caminho relativo (string) ou None.
	v4.1.1: regras 4-6 adicionadas para evitar descarte de codigo valido.
	"""
	if re.search(r'\bclass GlobalPlugin\b', code):
		if canonical_dir:
			return f"globalPlugins/{canonical_dir}/__init__.py"
		return "__init__.py"

	m = re.search(r'\bclass \w*Settings(?:Panel)?\w*\s*\(', code)
	if m:
		if canonical_dir:
			return f"globalPlugins/{canonical_dir}/settings_panel.py"
		return "settings_panel.py"

	_DOMAIN_SUFFIXES = (
		"Service", "Manager", "Worker", "Handler", "Client",
		"Provider", "Connector", "Validator", "Resolver",
		"Factory", "Controller", "Builder", "Runner",
	)
	_sfx_pat = "|".join(_DOMAIN_SUFFIXES)
	m = re.search(rf'\bclass (\w+)({_sfx_pat})\b', code)
	if m:
		raw = m.group(1) + m.group(2)
		snake = re.sub(r'(?<!^)(?=[A-Z])', '_', raw).lower()
		fname = f"{snake}.py"
		if canonical_dir:
			return f"globalPlugins/{canonical_dir}/{fname}"
		return fname

	m = re.search(r'\bclass (\w+)(Dialog|Panel|Frame|Window)\b', code)
	if m:
		raw = m.group(1) + m.group(2)
		snake = re.sub(r'(?<!^)(?=[A-Z])', '_', raw).lower()
		fname = f"{snake}.py"
		if canonical_dir:
			return f"globalPlugins/{canonical_dir}/{fname}"
		return fname

	m = re.search(r'\bclass (\w+)\s*\(', code)
	if m:
		raw = m.group(1)
		snake = re.sub(r'(?<!^)(?=[A-Z])', '_', raw).lower()
		fname = f"{snake}.py"
		if canonical_dir:
			return f"globalPlugins/{canonical_dir}/{fname}"
		return fname

	stripped = code.strip()
	if stripped and not stripped.startswith("#") and not stripped.startswith('"""'):
		n = fallback_counter if fallback_counter > 0 else 1
		fname = f"module_{n}.py"
		if canonical_dir:
			return f"globalPlugins/{canonical_dir}/{fname}"
		return fname

	return None

def _preprocess_markdown_headers(text: str) -> str:
	"""Converte headers markdown ## path/to/file.py em anotacoes de fence.

	LLMs frequentemente geram codigo multi-arquivo usando headers markdown
	(## globalPlugins/Nome/__init__.py) como separador de filename em vez da
	anotacao padrao (```python:globalPlugins/Nome/__init__.py). Sem este
	preprocessamento, extract_code_blocks() nao reconhece o filename e
	descarta os blocos como "nao foi possivel inferir filename".

	Transformacao por fence:
	## globalPlugins/Nome/__init__.py
	```python
	...
	```
	->
	```python:globalPlugins/Nome/__init__.py
	...
	```

	Regras:
	- So converte se o header contem '/' ou termina com extensao conhecida (.py, .ini, .html)
	- Nao modifica fences que ja tem anotacao de filename
	- Case-insensitive para extensoes
	"""
	_FILENAME_EXT_RE = re.compile(
		r'\.(?:py|ini|html|dic|utb|ctb|utb|css|js|json|yaml|yml|md|txt|cfg|toml|xml|svg)$',
		re.IGNORECASE,
	)
	_PATH_SEP_RE = re.compile(r'[/\\]')
	lines = text.split('\n')
	result: list[str] = []
	i = 0
	while i < len(lines):
		line = lines[i]
		stripped = line.strip()
		m = re.match(r'^#{1,3}\s+(.+)$', stripped)
		if m:
			header_path = m.group(1).strip()
			has_path_sep = bool(_PATH_SEP_RE.search(header_path))
			has_known_ext = bool(_FILENAME_EXT_RE.search(header_path))
			is_manifest = header_path.lower().endswith('manifest.ini')
			if has_path_sep or has_known_ext or is_manifest:
				next_idx = i + 1
				while next_idx < len(lines) and lines[next_idx].strip() == '':
					next_idx += 1
				if next_idx < len(lines):
					fence_m = re.match(r'^```(\w+)(?::([^\n]+))?$', lines[next_idx].strip())
					if fence_m and not fence_m.group(2):
						lang_tag = fence_m.group(1)
						lines[next_idx] = f'```{lang_tag}:{header_path}'
						_logger.debug(
							"[PREPROC] Header ## %s -> anotacao ```%s:%s",
							header_path, lang_tag, header_path,
						)
						i += 1
						continue
		result.append(lines[i])
		i += 1
	return '\n'.join(result)


def extract_code_blocks(text: str) -> list[dict]:
	"""
	Extrai blocos de codigo Python, INI, HTML e arquivos de recurso NVDA do texto da IA.

	Captura blocos com e sem anotacao de filename na mesma passagem:
	```python:globalPlugins/name/__init__.py -> named (fname anotado)
	```python -> unnamed (tenta inferir via _infer_python_filename)
	```text:speechDicts/pronuncia.dic -> named (qualquer tag com filename)
	```ini:locale/it/gestures.ini -> named

	Fix ESTRUTURA-004: o antigo two-pass com early return ignorava blocos
	unnamed quando qualquer bloco named era encontrado antes.
	Fix 2.2.0: blocos sem anotacao recebem filename inferido do conteudo;
	se inferencia falhar, o bloco e descartado (nunca salvo como arquivo_N.py).
	Fix 3.7.1 (2026-04-19): aceita qualquer tag de linguagem quando filename
	esta anotado. Necessario para salvar .dic (speechDicts/, symbolDicts/),
	.utb (brailleTables/), gestures.ini (locale/) e outros recursos NVDA
	que nao sao Python/INI/HTML.
	Fix 4.1.0 (2026-05-11): preprocessa headers markdown ## path/file.py
	em anotacoes de fence. LLMs usam ## como separador de filename — sem
	este passo, blocos eram descartados como "nao foi possivel inferir filename".

	Retorna lista de dicts: {'filename': str, 'code': str, 'language': str}
	Seguranca: nao executa nenhum codigo extraido.
	"""
	text = _preprocess_markdown_headers(text)

	blocks = []
	counter: dict[str, int] = {"python": 0, "ini": 0, "html": 0}
	unamed_python: list[dict] = [] # blocos sem anotacao aguardando inferencia

	# Captura blocos com tag de linguagem conhecida (com ou sem filename).
	# Grupo 2 (fname) e opcional — None quando nao anotado.
	pattern_known = r"```(python|ini|html)(?::([^\n]+))?\n(.*?)```"
	# Captura blocos com tag DESCONHECIDA mas com filename obrigatorio.
	# Cobre: ```text:speechDicts/pronuncia.dic, ```dic:..., ```utb:..., etc.
	pattern_unknown = r"```([a-zA-Z][\w.-]*):([ \t]*[^\n]+)\n(.*?)```"

	# Processa blocos de linguagens conhecidas (python/ini/html)
	for lang, fname_raw, code in re.findall(pattern_known, text, re.DOTALL):
		code = code.strip()
		if not code:
			continue
		if fname_raw:
			fname = fname_raw.strip()
			blocks.append({"filename": fname, "code": code, "language": lang})
			_logger.debug("[EXTRACAO] arquivo=%s lang=%s chars=%d", fname, lang, len(code))
		else:
			counter[lang] += 1
			if lang == "python":
				# Adia a resolucao do nome: aguarda o post-pass que conhcece canonical_dir
				unamed_python.append({"code": code, "language": lang})
			elif lang == "ini":
				# Bloco INI sem anotacao: em addons NVDA so existe manifest.ini.
				# Usar nome canonico diretamente evita que o bloco seja salvo como
				# arquivo_N.ini em globalPlugins/ em vez da raiz.
				fname = "manifest.ini"
				blocks.append({"filename": fname, "code": code, "language": lang})
				_logger.debug("[EXTRACAO] arquivo=%s lang=%s chars=%d", fname, lang, len(code))
			else:
				# HTML sem anotacao: nome sintetico (pode haver multiplos)
				fname = f"arquivo_{counter[lang]}.html"
				blocks.append({"filename": fname, "code": code, "language": lang})
				_logger.debug("[EXTRACAO] arquivo=%s lang=%s chars=%d", fname, lang, len(code))

	# Processa blocos com tag desconhecida — salva SOMENTE se filename anotado.
	# Sem filename nao ha como saber onde salvar arquivos de formato desconhecido.
	nomes_ja_capturados = {b["filename"] for b in blocks}
	for lang, fname_raw, code in re.findall(pattern_unknown, text, re.DOTALL):
		if lang in ("python", "ini", "html"):
			continue # ja processados acima
		code = code.strip()
		if not code:
			continue
		fname = fname_raw.strip()
		if not fname or fname in nomes_ja_capturados:
			continue # sem filename ou duplicado
		blocks.append({"filename": fname, "code": code, "language": lang})
		nomes_ja_capturados.add(fname)
		_logger.debug(
			"[EXTRACAO] arquivo=%s lang=%s (recurso NVDA) chars=%d",
			fname, lang, len(code),
		)

	# Resolve blocos Python sem anotacao APOS ambos os loops (fix ESTRUTURA-004):
	# o loop pattern_unknown pode ter zero iteracoes, mas unamed_python deve sempre
	# ser processado — mover para fora garante que nunca seja ignorado.
	gp_re = re.compile(r'^globalPlugins/([^/]+)/', re.IGNORECASE)
	canonical_dir: str | None = None
	for blk in blocks:
		m = gp_re.match((blk.get("filename") or "").replace("\\", "/").lstrip("/"))
		if m:
			canonical_dir = m.group(1)
			break

	for unnamed in unamed_python:
		inferred = _infer_python_filename(unnamed["code"], canonical_dir)
		if inferred:
			unnamed["filename"] = inferred
			blocks.append(unnamed)
			_logger.info(
				"[EXTRACAO] Bloco sem anotacao: filename inferido=%s chars=%d",
				inferred, len(unnamed["code"]),
			)
		else:
			_logger.warning(
				"[EXTRACAO] Bloco Python sem anotacao descartado "
				"(nao foi possivel inferir filename). chars=%d head='%s'",
				len(unnamed["code"]), unnamed["code"][:60].replace("\n", " "),
			)

	if not blocks:
		_logger.warning("[AVISO] Nenhum bloco de codigo encontrado na resposta da IA.")

	return blocks


# ------------------------------------------------------------------
# Validacao de estrutura
# ------------------------------------------------------------------

def validate_manifest(code: str) -> list[str]:
	"""
	Valida campos obrigatorios no manifest.ini.

	Retorna lista de campos ausentes (vazia = valido).
	"""
	missing = []
	for field in _MANIFEST_REQUIRED_FIELDS:
		if not re.search(rf"^\s*{field}\s*=", code, re.MULTILINE | re.IGNORECASE):
			missing.append(field)
	return missing


def validate_python_structure(code: str) -> list[str]:
	"""
	Validacao estatica basica do codigo Python gerado.
	Nao executa o codigo — apenas analisa texto.

	Retorna lista de avisos (vazia = sem problemas encontrados).
	"""
	warnings = []
	if "import" not in code:
		warnings.append("Nenhum import encontrado no codigo.")
	if "class GlobalPlugin" not in code and "class AppModule" not in code:
		if "__init__" in code or "def script_" in code:
			warnings.append("Classe GlobalPlugin ou AppModule nao encontrada.")
	return warnings


def validate_python_syntax(code: str) -> str | None:
	"""
	Valida sintaxe Python via ast.parse. Nao executa o codigo (Regra 9).
	Returns None se ok, mensagem de erro se invalido.
	"""
	try:
		ast.parse(code)
		return None
	except SyntaxError as exc:
		return f"Erro de sintaxe na linha {exc.lineno}: {exc.msg}"


# Modulos sempre disponiveis no ambiente NVDA
_NVDA_MODULES: frozenset = frozenset({
	"globalPluginHandler", "appModuleHandler", "addonHandler",
	"ui", "api", "config", "speech", "braille", "gui", "tones",
	"nvwave", "winUser", "scriptHandler", "keyboardHandler",
	"mouseHandler", "watchdog", "globalVars", "languageHandler",
	"versionInfo", "buildVersion", "logHandler", "extensionPoints",
	"NVDAObjects", "textInfos", "controlTypes", "cursorManager",
	"reviewCursor", "baseObject", "eventHandler", "inputCore",
	"sayAllHandler", "characterProcessing", "synthDriverHandler",
	"bdDetect", "hwIo", "hwPortUtils", "winKernel", "winAPI",
	"winConsoleHandler", "UIAHandler", "IAccessibleHandler",
	"JABHandler", "oleacc", "comtypes", "ctypes", "wx", "serial",
	"speechDictHandler", "brailleInput", "vision",
	# Adicionados em v1.5.0 — estavam causando falsos positivos (B3)
	"queueHandler",   # fila de eventos/anuncios do NVDA (core nativo)
	"core",           # modulo principal do NVDA (restart, callLater, etc.)
	"NVDAState",      # estado do NVDA (shouldWriteToDisk, isRunning, etc.)
	"winBindings",    # novo nome de winUser/winKernel/etc em NVDA 2026.1
	"screenCurtain",  # Screen Curtain (refatorado em 2026.1)
	# hardware I/O (braille displays)
	"ftdi2",          # FTDI USB driver (refatorado em 2026.1)
	# Adicionados em v3.2.0 — nvdaHelper e NVDAHelper sao extensoes C internas do NVDA
	"nvdaHelper",     # extensao C interna do NVDA (nvdaHelper.dll)
	"NVDAHelper",     # alias capitalizado para o mesmo modulo
	# Adicionados em v3.6.0 — nomes de pasta do NVDA confundidos com pacotes pip (NVDA-024)
	# O LLM as vezes gera globalPlugins/appModules/synthDrivers como dependencies[]
	"globalPlugins",    # diretorio de plugins — nao e pacote pip
	"appModules",       # diretorio de app modules — nao e pacote pip
	"synthDrivers",     # diretorio de synth drivers — nao e pacote pip
	"brailleDisplayDrivers",  # diretorio de braille drivers — nao e pacote pip
	"installTasks",     # modulo raiz do addon — nao e pacote pip
	"nvdaBuiltin",      # modulo builtin do NVDA — nao e pacote pip
	# Adicionados em v4.0.0 — "nvda" simples violava NVDA-024: LLM gerava dependencies=["nvda"]
	# causando FALHA NA INSTALACAO (nao existe no PyPI). skill: lint-and-validate.
	"nvda",             # nome generico do leitor de tela — nao e pacote pip
	"pynvda",           # binding C do NVDA — nao e pacote pip externo
})

# Versao lowercase de _NVDA_MODULES para comparacao case-insensitive (v2.0.0)
_NVDA_MODULES_LOWER: frozenset = frozenset(m.lower() for m in _NVDA_MODULES)

# Modulos stdlib disponiveis em qualquer Python 3.x
_STDLIB_MODULES: frozenset = frozenset({
	"os", "sys", "re", "json", "time", "datetime", "threading",
	"queue", "logging", "pathlib", "io", "math", "random",
	"collections", "itertools", "functools", "operator",
	"subprocess", "tempfile", "shutil", "glob", "fnmatch",
	"hashlib", "base64", "urllib", "http", "socket", "ssl",
	"struct", "array", "typing", "dataclasses", "enum",
	"abc", "contextlib", "copy", "weakref", "gc", "inspect",
	"importlib", "ast", "dis", "tokenize", "traceback",
	"warnings", "unittest", "zipfile", "tarfile", "csv",
	"configparser", "argparse", "textwrap", "string", "unicodedata",
	# Adicionados em v3.2.0 — estavam faltando, causando falsos positivos no bundler
	"webbrowser", "email", "html", "xml", "platform", "locale",
	"pprint", "pickle", "sqlite3", "concurrent", "multiprocessing",
	"gettext", "codecs", "binascii", "mimetypes",
})

# Aliases pip-name -> import-root para pacotes comuns
_PIP_ALIASES: dict = {
	"openai_whisper": "whisper",
	"google_generativeai": "google",
	"pillow": "PIL",
	"opencv_python": "cv2",
	"scikit_learn": "sklearn",
}


def _resolve_pip_names(
	names: list[str],
) -> dict[str, str]:
	"""Resolve nomes para nomes pip corretos via LLM semantico (v3.5.0).

	Sem dicionario estatico: o LLM decide o nome pip correto para TODOS os
	nomes fornecidos. Retorna passthrough quando a chamada ao LLM falha.

	Toda a inteligencia de mapeamento fica no modelo — nenhum caso especial
	hardcoded aqui. O planner ja instrui o LLM a gerar nomes pip corretos;
	esta funcao e a rede de seguranca semantica para quando isso nao ocorre.

	Returns:
		dict { nome_original: nome_pip_correto }
	"""
	result: dict[str, str] = {name: name for name in names}

	if not names:
		return result

	# LLM semantico: envia todos os nomes de uma vez, recebe JSON com mapeamento
	try:
		from ..gui.settings_panel import get_llm_provider, get_llm_model
		from ..ai.model_registry import resolve_provider_tier_model
		provider = get_llm_provider()
		model = get_llm_model()
		model = resolve_provider_tier_model(provider, "light", model)
		client = create_llm_client(model_id=model)
		names_str = ", ".join(f'"{n}"' for n in names)
		prompt = (
			f"For each Python package name below, return the EXACT pip install package name "
			f"(as used in `pip install <name>`). Some names may already be correct pip names; "
			f"keep them unchanged. Others may be Python import names that differ from the pip name. "
			f"Return ONLY a JSON object: "
			f'{{"resolved": {{"original_name": "pip_package_name", ...}}}}. '
			f"No explanation, no markdown, only JSON.\n\nNames: [{names_str}]"
		)
		resp = client.chat(
			prompt,
			system_override=(
				"You are a Python packaging expert. "
				"Answer with a JSON object only. No markdown, no explanation."
			),
			response_format={"type": "json_object"},
		)
		data = json.loads(resp.content or "{}")
		resolved = data.get("resolved", {})
		for orig in names:
			pip_name = (resolved.get(orig) or "").strip()
			if pip_name and pip_name != orig:
				_logger.info("[RESOLVE] '%s' -> '%s' (LLM).", orig, pip_name)
				result[orig] = pip_name
			else:
				_logger.debug("[RESOLVE] '%s' mantido (LLM nao alterou).", orig)
	except Exception as exc:
		_logger.warning(
			"[RESOLVE] Falha na resolucao LLM (%s) — usando nomes originais: %s",
			exc, names,
		)

	return result


def _is_known_module(root: str, bundled_roots: set) -> bool:
	# Usa _NVDA_MODULES_LOWER para comparacao case-insensitive (v3.2.0).
	# A checagem NVDA-022 passa o root em lowercase; _NVDA_MODULES tem nomes
	# mixed-case (addonHandler, globalPluginHandler, etc.) — sem .lower(), o
	# check falhava e gerava NVDA-022 falso positivo para modulos NVDA nativos.
	return (
		root.lower() in _NVDA_MODULES_LOWER
		or root in _STDLIB_MODULES
		or root in getattr(sys, "stdlib_module_names", ())
		or root in bundled_roots
		or root.startswith("_")
	)


def validate_python_imports(
	code: str,
	bundled_packages: list | None = None,
	local_modules: list | set | tuple | None = None,
) -> list:
	"""
	Valida imports do codigo contra NVDA modules, stdlib e pacotes bundlados.
	Retorna lista de imports desconhecidos — possivelmente precisam ser bundlados.
	Nao executa codigo (Regra 9).
	"""
	bundled_roots: set = {
		str(module).replace("-", "_").split(".")[0].lower()
		for module in (local_modules or [])
	}
	for pkg in (bundled_packages or []):
		root = pkg.replace("-", "_").split(".")[0].lower()
		bundled_roots.add(root)
		if root in _PIP_ALIASES:
			bundled_roots.add(_PIP_ALIASES[root])

	try:
		tree = ast.parse(code)
	except SyntaxError:
		return []

	unknown: list = []
	seen: set = set()
	for node in ast.walk(tree):
		if isinstance(node, ast.Import):
			for alias in node.names:
				r = alias.name.split(".")[0]
				if r not in seen and not _is_known_module(r, bundled_roots):
					seen.add(r)
					unknown.append(alias.name)
		elif isinstance(node, ast.ImportFrom):
			# Relative imports point at files in the generated add-on.  They are
			# validated structurally after all files have been assembled and must
			# never be mistaken for missing PyPI dependencies here.
			if node.level:
				continue
			if node.module:
				r = node.module.split(".")[0]
				if r not in seen and not _is_known_module(r, bundled_roots):
					seen.add(r)
					unknown.append(node.module)
	return unknown


def _validate_html_block(code: str) -> bool:
	"""
	Verifica se o codigo e HTML valido com estrutura minima (fluxos 8.2 R:b).
	Usa html.parser (stdlib) para detectar erros de parse.
	Retorna True se o conteudo parece HTML valido com ao menos uma tag estrutural.
	Retorna False se invalido ou vazio de marcacao estrutural.
	Nao executa o HTML — apenas analise textual (Regra 9).
	"""

	class _CheckParser(HTMLParser):
		def __init__(self):
			super().__init__()
			self.has_error = False

		def handle_starttag(self, _tag, _attrs):
			pass

		def handle_endtag(self, _tag):
			pass

		def unknown_decl(self, data: str):
			pass  # declaracoes nao-HTML nao sao erros fatais

	parser = _CheckParser()
	try:
		parser.feed(code)
		parser.close()
	except Exception:
		return False

	# Exige ao menos uma tag estrutural HTML
	return bool(re.search(
		r'<(?:html|body|div|p|h[1-6]|ul|ol|table|head)\b',
		code, re.IGNORECASE
	))


# ------------------------------------------------------------------
# Persistencia
# ------------------------------------------------------------------

def _deduplicate_blocks(blocks: list[dict]) -> list[dict]:
	"""
	Elimina duplicatas e normaliza paths de globalPlugins/ antes de salvar.

	Problema (ESTRUTURA-007): Fix A coleta blocos de TODOS os steps.
	Quando code_generation gera globalPlugins/AnuncioTitulo/__init__.py e
	assembly gera globalPlugins/AnunciadorDeTitulo/__init__.py, ambos seriam
	salvos criando duas pastas de plugin — NVDA carregaria dois GlobalPlugins
	simultaneamente causando conflito de atalhos.

	Solucao:
	- Descobre o nome canonico de pasta = ULTIMO globalPlugins/<X>/ visto
	  (assembly e o ultimo step, logo prevalece sobre code_generation)
	- Remapeia TODOS os blocos globalPlugins/<qualquer>/ para globalPlugins/<canonico>/
	- Deduplica por caminho resultante (ultimo vence)
	- Blocos nao-globalPlugins (manifest.ini, doc/) tambem deduplicados por filename
	"""
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
	# sinteticos (arquivo_N.py) sem GlobalPlugin/AppModule sao residuos do assembly
	# que causam ESTRUTURA-005 no validador.
	# Modulos de suporte legitimos (settings_panel.py, gemini_service.py, etc.)
	# sao SEMPRE preservados, independente do conteudo — foram gerados com nome
	# explicito pelo LLM e sao importados pelo __init__.py.
	# Regra: verificacao deterministica — nao depende de LLM.
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


def _generate_minimal_manifest(addon_name: str) -> str:
	"""Gera manifest.ini minimo quando manifest_builder falhou.

	Causa raiz (Bug 1, 2026-05-11): modelo retornou 503 repetidas
	vezes, step manifest_builder REJEITADO (score=0), nenhum manifest.ini
	gerado -> ESTRUTURA-001 (bloqueador fatal). O addon nao instala sem manifest.

	Este fallback deterministico garante que o addon sempre tenha manifest.ini
	com campos obrigatorios, mesmo quando o LLM falha completamente.
	Regra 5: geracao deterministica — nao usa LLM.
	Regra 9: nao executa codigo — apenas gera texto INI.
	"""
	from ..utils.project_policy import PROJECT_MIN_NVDA, PROJECT_LAST_TESTED_NVDA
	return (
		f"[add-on]\n"
		f"name = {addon_name}\n"
		f"summary = Add-on gerado pelo NVDAStudio\n"
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
	require_manifest: bool = True,
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

	# Bug 1 fallback (2026-05-11): se nenhum bloco manifest.ini existe nos
	# blocos extraidos, gera um manifest minimo deterministico. Sem isso,
	# o addon nao instala (ESTRUTURA-001). Causa raiz: modelo 503 durante
	# manifest_builder => nenhum manifest.ini => bloqueador fatal.
	# 5.50.0 (require_manifest=False): projetos controller_client NUNCA tem
	# manifest.ini por design (nao sao addons) -- gerar um fake aqui
	# corromperia a saida com um arquivo que nao deveria existir.
	_has_manifest = any(
		(b.get("filename") or "").replace("\\", "/").lstrip("/").lower() == "manifest.ini"
		or (b.get("filename") or "").replace("\\", "/").lstrip("/").lower().endswith("/manifest.ini")
		for b in blocks
	)
	if not _has_manifest and require_manifest:
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

	# Exclui blocos de testes — nunca devem ir para o addon instalado (v2.1.0)
	# Testes gerados pela IA sao uteis para o desenvolvedor, nao para o usuario final.
	blocks = [
		b for b in blocks
		if not (b.get("filename") or "").replace("\\", "/").lstrip("/").startswith("tests/")
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

		# Previne path traversal: destino deve ficar dentro de addon_folder.
		# Bug real: startswith() sozinho tem furo classico (CWE-22) -- ex:
		# '...\\MyAddonExtra\\x.py'.startswith('...\\MyAddon') e True. Compara
		# contra addon_folder + separador para exigir fronteira de diretorio real.
		addon_folder_norm = os.path.normpath(addon_folder)
		dest_abs = os.path.normpath(os.path.join(addon_folder, dest_rel))
		if dest_abs != addon_folder_norm and not dest_abs.startswith(addon_folder_norm + os.sep):
			_logger.warning("[AVISO] Path traversal bloqueado: %s", raw_fname)
			continue

		os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
		code = block["code"]
		# Bug producao 2026-03-24: manifest com valores multiline causam VdtTypeError
		if dest_abs.lower().endswith("manifest.ini"):
			code = _sanitize_manifest(code)
		# fluxos 8.2 R:b: valida HTML antes de salvar; adiciona wrapper se invalido
		if dest_abs.lower().endswith(".html") and not _validate_html_block(code):
			if not re.search(r'<html', code, re.IGNORECASE):
				_logger.warning(
					"[AVISO] userGuide HTML sem estrutura minima — adicionando wrapper."
				)
				code = (
					'<!DOCTYPE html>\n<html lang="pt">\n'
					'<head><meta charset="utf-8"><title>User Guide</title></head>\n'
					f'<body>\n{code}\n</body>\n</html>'
				)
		# skill: nvda-addon-dev (Secao 18 — UTF-8 + LF line endings em todos os .py).
		# No Windows, open() produz CRLF por padrao. newline="\n" forca LF para
		# compatibilidade com o padrao de codificacao do NVDA e do repositorio.
		# Normaliza tambem qualquer \r\n ja presente no codigo gerado pela LLM.
		_open_kwargs: dict = {"encoding": "utf-8"}
		if dest_abs.lower().endswith(".py"):
			code = code.replace("\r\n", "\n").replace("\r", "\n")
			_open_kwargs["newline"] = "\n"
		if dest_abs.lower().endswith(".ini"):
			code = code.replace("\r\n", "\n").replace("\r", "\n")
			_open_kwargs["newline"] = "\n"
		with open(dest_abs, "w", **_open_kwargs) as f:
			f.write(code)
		saved.append(dest_abs)
		log_decision(_logger, "arquivo_salvo", dest_abs)

	_logger.info("[OK] %d arquivo(s) salvos em %s", len(saved), addon_folder)
	_auto_fix_missing_init_from_module_fallback(addon_folder)
	return addon_folder, saved


def _auto_fix_missing_init_from_module_fallback(addon_folder: str) -> None:
	"""
	5.51.0: correcao DETERMINISTICA (sem chamada de LLM) pra ESTRUTURA-008 no
	caso mais comum -- achado real ao vivo (test_e36, AssistenteLeituraGemini,
	2026-08-17): o step de code_generation que deveria gerar o __init__.py
	raiz emitiu um bloco SEM anotacao de filename e sem `class GlobalPlugin`
	reconhecivel, entao _infer_python_filename() (unico lugar que ja sabe
	quando isso acontece) caiu no fallback "module_N.py" -- e o addon final
	saiu sem __init__.py, que o NVDA nunca carrega.

	A propria mensagem de ESTRUTURA-008 ja sugere a correcao exata ("crie
	__init__.py com from .module_1 import *"), mas nada aplicava isso de
	verdade -- ou dependia do round-trip de _auto_fix_structural_issues()
	(LLM, nao-deterministico, so existe no fluxo real da UI via
	_on_package(), NUNCA no caminho de teste E2E que usa save_addon_files()
	direto). Aqui, quando uma pasta globalPlugins/<addon>/ (nivel raiz, nao
	subpacotes) tem exatamente UM module_N.py, nenhum __init__.py, e NENHUM
	.py nela contem `class GlobalPlugin`, cria __init__.py com
	`from .module_N import *` deterministicamente -- sem custo de LLM, sem
	ambiguidade (so age quando ha exatamente 1 candidato claro).
	"""
	gp_dir = os.path.join(addon_folder, "globalPlugins")
	if not os.path.isdir(gp_dir):
		return
	for sub in os.listdir(gp_dir):
		sub_path = os.path.join(gp_dir, sub)
		if not os.path.isdir(sub_path):
			continue
		init_path = os.path.join(sub_path, "__init__.py")
		if os.path.isfile(init_path):
			continue
		top_level_py = [
			f for f in os.listdir(sub_path)
			if f.endswith(".py") and os.path.isfile(os.path.join(sub_path, f))
		]
		if not top_level_py:
			continue
		has_global_plugin = False
		for fname in top_level_py:
			try:
				with open(os.path.join(sub_path, fname), encoding="utf-8", errors="replace") as fh:
					if re.search(r'\bclass GlobalPlugin\b', fh.read()):
						has_global_plugin = True
						break
			except OSError:
				continue
		if has_global_plugin:
			continue
		module_candidates = [f for f in top_level_py if re.fullmatch(r"module_\d+\.py", f)]
		if len(module_candidates) != 1:
			continue
		module_name = module_candidates[0][:-len(".py")]
		with open(init_path, "w", encoding="utf-8", newline="\n") as fh:
			fh.write(f"from .{module_name} import *  # noqa: F401,F403\n")
		_logger.warning(
			"[AUTO_FIX] ESTRUTURA-008: %s sem __init__.py -- criado com "
			"'from .%s import *' (correcao deterministica).",
			sub, module_name,
		)


def _collect_local_module_roots(addon_folder: str, addon_name: str) -> frozenset:
	"""
	Coleta os nomes (sem .py) de todos os arquivos Python presentes em QUALQUER
	subpasta de globalPlugins/ do addon gerado.

	Escaneia todos os subdirs (nao so o do addon_name) para cobrir o caso em que
	a LLM gera blocos com nomes de pasta inconsistentes (GeminiTranscriber,
	GeminiTranscriptor, TranscricaoGemini). Sem isso, modulos locais em pastas
	alternativas passavam pelo filtro e chegavam ao pip com falha.
	"""
	roots: set = set()
	gp = os.path.join(addon_folder, "globalPlugins")
	if not os.path.isdir(gp):
		return frozenset()
	for subdir in os.listdir(gp):
		subdir_path = os.path.join(gp, subdir)
		if not os.path.isdir(subdir_path):
			continue
		for fname in os.listdir(subdir_path):
			if fname.endswith(".py"):
				stem = fname[:-3]
				roots.add(stem)
				roots.add(stem.lower())
				roots.add(stem.replace("-", "_").lower())
	return frozenset(roots)


def bundle_addon_dependencies(
	addon_folder: str,
	packages: list[str],
	addon_name: str,
	on_package_progress=None,
	_pypi_checker=None,
) -> list[str]:
	"""
	Bundla pacotes pip em lib/ dentro do addon gerado.
	Mesmo mecanismo do build.py do NVDAStudio:
	  pip install --target=<plugin_dir>/lib/ --no-compile --quiet

	Garante que o addon funcione sem que o usuario instale nada.
	O __init__.py gerado deve adicionar lib/ ao sys.path (igual ao NVDAStudio).

	Args:
		addon_folder: pasta raiz do addon (contem manifest.ini e globalPlugins/)
		packages: lista de nomes pip ex ["openai-whisper", "Pillow"]
		addon_name: nome do addon para localizar a pasta globalPlugins/<addon_name>/
		on_package_progress: callback opcional(pkg: str, status: str) chamado para
			cada pacote com status "iniciando", "ok" ou "falha".
		api_key: credencial LLM opcional. Quando fornecida, nomes de pacote que
			parecem import roots desconhecidos sao resolvidos semanticamente
			via LLM antes do pip install. (v3.4.0)
		_pypi_checker: callable(pkg) -> bool opcional para injecao em testes.
			Default: _package_exists_on_pypi. Permite testes sem rede.

	Returns:
		Lista de pacotes instalados com sucesso.
	"""
	if not packages:
		return []

	# Coleta modulos locais do addon — nao devem ser instalados via pip (v2.0.0)
	local_roots = _collect_local_module_roots(addon_folder, addon_name)

	# Valida nomes de pacote (SEC-001): output da LLM nao e confiavel
	safe_packages: list[str] = []
	for pkg in packages:
		if not _is_safe_package_name(pkg):
			_logger.warning(
				"[AVISO] Nome de pacote rejeitado (invalido/inseguro): %r. "
				"Apenas nomes PEP 508 basicos sao aceitos.", pkg
			)
			continue
		# Normaliza path de submodulo: LLM as vezes gera "google_auth_oauthlib.flow"
		# em vez do nome pip correto "google-auth-oauthlib". Extrai apenas o root
		# antes do primeiro ponto para filtro E para o pip install. (v3.2.0)
		pkg_install = pkg.split(".")[0] if "." in pkg else pkg
		# Filtra modulos do NVDA, stdlib e arquivos locais do addon (v2.0.0)
		pkg_root = pkg_install.replace("-", "_").lower()
		if pkg_root in _NVDA_MODULES_LOWER or pkg_root in _STDLIB_MODULES or pkg_root in local_roots:
			_logger.info(
				"[BUNDLE] Ignorado '%s': e modulo NVDA/stdlib/local do addon, "
				"nao precisa de pip install.", pkg
			)
			continue
		if pkg_install != pkg:
			_logger.info(
				"[BUNDLE] Nome de pacote normalizado: '%s' -> '%s' "
				"(submodule path removido).", pkg, pkg_install
			)
		safe_packages.append(pkg_install)
	if not safe_packages:
		return []

	# Resolve import roots para nomes pip corretos (v3.4.0):
	# - Camada 1: _IMPORT_TO_PIP (casos conhecidos, sem latencia)
	# - Camada 2: passthrough para nomes que ja parecem pip (hifen/simples)
	# - Camada 3: LLM semantico para import roots desconhecidos (se api_key fornecida)
	pip_name_map = _resolve_pip_names(safe_packages)
	safe_packages = [pip_name_map[p] for p in safe_packages]

	# Verificacao PyPI antes do pip install (v3.8.0).
	# Elimina alucinacoes do LLM sem keywords — pacote inexistente no PyPI
	# e descartado silenciosamente e registrado em session_memory.dep_failures.
	# O code_generator consulta dep_failures e injeta como contexto semantico
	# para o LLM evitar repetir o erro em geracoes futuras.
	# _pypi_checker injetavel para testes sem rede (default: _package_exists_on_pypi).
	_checker = _pypi_checker if _pypi_checker is not None else _package_exists_on_pypi
	verified_packages: list[str] = []
	for pkg in safe_packages:
		if _checker(pkg):
			verified_packages.append(pkg)
		else:
			_logger.warning(
				"[BUNDLE] Pacote '%s' nao encontrado no PyPI — ignorado. "
				"Possivel alucinacao do LLM. Registrando em dep_failures.", pkg
			)
			if on_package_progress:
				on_package_progress(pkg, "falha", f"nao encontrado no PyPI: {pkg}")
			try:
				if _session_memory_mem is not None:
					_session_memory_mem.log_dep_failure(pkg, "nao_encontrado_pypi", addon_name)
			except Exception as _mem_exc:
				_logger.info("[BUNDLE] dep_failure nao registrada: %s", _mem_exc)
	safe_packages = verified_packages
	if not safe_packages:
		return []

	# Localiza a pasta do plugin dentro de globalPlugins/
	# Tenta primeiro pelo nome sanitizado, depois varre o que existir
	safe_name = re.sub(r"[^\w]", "_", addon_name)
	plugin_dir = os.path.join(addon_folder, "globalPlugins", safe_name)
	if not os.path.isdir(plugin_dir):
		# Varre globalPlugins/ e pega o primeiro subdiretorio
		gp = os.path.join(addon_folder, "globalPlugins")
		if os.path.isdir(gp):
			subdirs = [d for d in os.listdir(gp)
					   if os.path.isdir(os.path.join(gp, d))]
			if subdirs:
				plugin_dir = os.path.join(gp, subdirs[0])

	lib_dir = os.path.join(plugin_dir, "lib")
	os.makedirs(lib_dir, exist_ok=True)

	# Localiza o Python real do sistema — dentro do NVDA, sys.executable aponta
	# para nvda.exe (nao tem pip) e pode causar WinError 740 (requer elevacao).
	# Estrategia: tenta pythonw.exe / python.exe no PATH antes de sys.executable.
	def _find_python() -> str:
		for candidate in ("pythonw.exe", "python.exe", "python3.exe"):
			found = shutil.which(candidate)
			if found and "nvda" not in found.lower():
				return found
		# Fallback: sys.executable (pode falhar dentro do NVDA)
		return sys.executable

	python_exe = _find_python()
	_logger.info("[BUNDLE] Usando Python: %s", python_exe)

	installed = []
	for pkg in safe_packages:
		_logger.info("[BUNDLE] Instalando %s em lib/...", pkg)
		if on_package_progress:
			on_package_progress(pkg, "iniciando")
		# O Python que executa o builder pode ser diferente do runtime embarcado
		# no NVDA.  Fixamos explicitamente CPython 3.13 + Windows x64; usar o
		# ambiente do builder como fallback poderia instalar .pyd cp311 e gerar
		# um add-on que empacota normalmente, mas falha ao ser importado pelo NVDA.
		cmd_nvda_runtime = [
			python_exe, "-m", "pip", "install", pkg,
			"--target", lib_dir, "--no-compile", "--quiet",
			"--platform", _NVDA_WHEEL_PLATFORM,
			"--python-version", _NVDA_PYTHON_VERSION,
			"--implementation", "cp",
			"--abi", _NVDA_WHEEL_ABI,
			"--only-binary", ":all:",
		]
		try:
			result = subprocess.run(
				cmd_nvda_runtime, capture_output=True, text=True, timeout=120
			)
			if result.returncode == 0:
				installed.append(pkg)
				log_decision(_logger, "bundle_ok", f"pkg={pkg} lib={lib_dir}")
				if on_package_progress:
					on_package_progress(pkg, "ok")
			else:
				_logger.warning(
					"[AVISO] Falha ao bundlar %s para CPython 3.13 win_amd64: %s",
					pkg, result.stderr[:300],
				)
				if on_package_progress:
					on_package_progress(pkg, "falha", result.stderr[:300])
		except OSError as exc:
			# WinError 740 (requer elevacao) ou executavel nao encontrado
			_logger.warning("[AVISO] bundle pip falhou com OSError para %s: %s. "
							"Pacote precisara ser instalado manualmente.", pkg, exc)
			if on_package_progress:
				on_package_progress(pkg, "falha", str(exc)[:200])
		except subprocess.TimeoutExpired:
			_logger.warning("[AVISO] Timeout ao bundlar %s. "
							"Pacote precisara ser instalado manualmente.", pkg)
			if on_package_progress:
				on_package_progress(pkg, "falha", "timeout (120s)")

	_logger.info("[OK] %d/%d pacotes bundlados em %s", len(installed), len(packages), lib_dir)
	return installed


def package_addon(addon_folder: str, output_path: str | None = None) -> str:
	"""
	Empacota a pasta do addon em um arquivo .nvda-addon (zip renomeado).

	Estrutura correta dentro do ZIP (exigida pelo NVDA):
		manifest.ini
		globalPlugins/
		  nomeAddon/
			__init__.py

	O arcname e calculado relativo a addon_folder (nao ao seu pai),
	garantindo que os arquivos fiquem na raiz do ZIP sem prefixo de pasta.

	Args:
		addon_folder: Caminho da pasta com os arquivos do addon.
		output_path: Caminho de saida. Se None, salva ao lado da pasta.

	Returns:
		Caminho do arquivo .nvda-addon gerado.
	"""
	if not os.path.isdir(addon_folder):
		raise AddonBuilderError(f"[ERRO] Pasta nao encontrada: {addon_folder}")

	zip_path = output_path or (addon_folder.rstrip("/\\") + ".nvda-addon")

	with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
		for root, _, files in os.walk(addon_folder):
			for file in files:
				full_path = os.path.join(root, file)
				# Base e addon_folder: arcname fica relativo ao conteudo da pasta,
				# sem incluir o nome da pasta no ZIP.
				# Exemplo: addon_folder/manifest.ini -> manifest.ini (raiz do ZIP)
				# Exemplo: addon_folder/globalPlugins/x/__init__.py -> globalPlugins/x/__init__.py
				arcname = os.path.relpath(full_path, addon_folder).replace("\\", "/")
				zf.write(full_path, arcname)

	_logger.info("[OK] Addon empacotado: %s", zip_path)
	return zip_path


# -----------------------------------------------------------------------
# Export: Relatorio Markdown + ZIP completo para distribuicao
# -----------------------------------------------------------------------

def generate_quality_report(
	addon_name: str,
	plan_id: str,
	step_results: list,
	total_tokens: int = 0,
) -> str:
	"""
	Gera relatorio de qualidade em Markdown com sumario dos steps,
	issues encontrados e metricas da sessao.

	addon_name: nome do addon gerado
	plan_id: ID do plano de execucao
	step_results: lista de StepResult (ou dicts com step_id, step_type, approved, score, issues)
	total_tokens: total de tokens consumidos (contador da sessao)

	Retorna: string Markdown pronta para salvar em arquivo.
	Regra 9: apenas leitura de metadados — nunca executa codigo gerado.
	"""

	lines = [
		f"# Relatorio de Qualidade — {addon_name}",
		"",
		f"**Plano:** {plan_id}  ",
		f"**Gerado em:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
	]
	if total_tokens > 0:
		lines.append(f"**Tokens consumidos:** {total_tokens:,}  ")
	lines.append("")

	ok = sum(1 for r in step_results if (r.approved if hasattr(r, "approved") else r.get("approved", False)))
	total = len(step_results)
	lines += [
		"## Resumo",
		"",
		f"- Steps aprovados: {ok}/{total}",
		f"- Status geral: {'OK' if ok == total else 'PARCIAL' if ok > 0 else 'FALHA'}",
		"",
		"## Detalhes por Step",
		"",
	]

	for r in step_results:
		if hasattr(r, "step_id"):
			step_id   = r.step_id
			step_type = r.step_type
			approved  = r.approved
			score     = r.score
			issues    = r.issues
		else:
			step_id   = r.get("step_id", "?")
			step_type = r.get("step_type", "?")
			approved  = r.get("approved", False)
			score     = r.get("score", 0)
			issues    = r.get("issues", [])

		status = "APROVADO" if approved else "REPROVADO"
		lines += [
			f"### {step_type} [{step_id}] — {status} (score {score})",
			"",
		]
		if issues:
			lines.append("**Issues encontrados:**")
			lines.append("")
			for issue in issues:
				lines.append(f"- {issue}")
			lines.append("")
		else:
			lines.append("Nenhum issue encontrado.")
			lines.append("")

	lines += [
		"---",
		"",
		"*Gerado pelo NVDAStudio — NVDAStudio e um criador autonomo de addons NVDA com IA.*",
	]

	return "\n".join(lines)


def export_addon_zip(
	addon_folder: str,
	addon_name: str,
	report_md: str = "",
	out_dir: str | None = None,
) -> str:
	"""
	Empacota o addon gerado em ZIP de distribuicao com estrutura completa:
	  - manifest.ini (raiz)
	  - globalPlugins/ (ou appModules/)
	  - lib/ (dependencias bundladas, se existir)
	  - QUALITY_REPORT.md (relatorio de qualidade, se fornecido)

	Diferente de package_addon() que gera .nvda-addon (para instalar),
	este gera um .zip legivel para inspecao e distribuicao de codigo fonte.

	out_dir: diretorio de saida do ZIP. Se None, usa o diretorio pai de addon_folder.

	Retorna o caminho do ZIP gerado.
	Regra 9: apenas empacota arquivos existentes — nao executa codigo.
	"""
	if not os.path.isdir(addon_folder):
		raise AddonBuilderError(f"[ERRO] Pasta nao encontrada: {addon_folder}")

	safe_name = addon_name.replace(" ", "_")
	_zip_dir = out_dir if out_dir else os.path.dirname(addon_folder)
	zip_path = os.path.join(_zip_dir, f"{safe_name}_source.zip")

	with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
		# Arquivos do addon
		for root, _, files in os.walk(addon_folder):
			for file in files:
				full_path = os.path.join(root, file)
				arcname = os.path.join(safe_name, os.path.relpath(full_path, addon_folder))
				arcname = arcname.replace("\\", "/")
				zf.write(full_path, arcname)

		# Relatorio de qualidade (opcional)
		if report_md:
			zf.writestr(f"{safe_name}/QUALITY_REPORT.md", report_md.encode("utf-8"))

	_logger.info("[OK] ZIP de distribuicao gerado: %s", zip_path)
	return zip_path


# ------------------------------------------------------------------
# Validadores determinÃ­sticos auxiliares — E14..E19
# Cada funcao recebe o caminho da pasta do addon e retorna list[str]
# de problemas no formato "CODIGO: descricao".
# Chamadas por validate_addon_structure() antes do retorno final.
# Regra 9: nenhuma funcao executa o codigo do addon.
# ------------------------------------------------------------------


def _check_event_handlers(addon_folder: str) -> list[str]:
	"""
	E14 — NVDA-001: funcoes event_* com parametro nextHandler que nunca chamam nextHandler().

	Logica AST:
	- Para cada .py em globalPlugins/ (exceto lib/)
	- Encontra funcoes cujo nome comeca com "event_" E tem "nextHandler" nos parametros
	- Se o corpo da funcao nao contem uma chamada a nextHandler() -> reporta NVDA-001
	- Excecao: funcoes que so chamam super().event_*() sem nextHandler() ainda sao reportadas
	  porque o super() nao propaga o nextHandler para a cadeia de handlers.
	"""
	problems: list[str] = []
	gp_dir = os.path.join(addon_folder, "globalPlugins")
	if not os.path.isdir(gp_dir):
		return problems

	for pdir in os.listdir(gp_dir):
		pdir_path = os.path.join(gp_dir, pdir)
		if not os.path.isdir(pdir_path):
			continue
		for py_file in os.listdir(pdir_path):
			if not py_file.endswith(".py"):
				continue
			full_path = os.path.join(pdir_path, py_file)
			try:
				with open(full_path, encoding="utf-8", errors="replace") as fh:
					src = fh.read()
			except OSError:
				continue
			# Filtragem rapida antes de parsear AST
			if "event_" not in src or "nextHandler" not in src:
				continue
			try:
				tree = ast.parse(src, filename=py_file)
			except SyntaxError:
				continue
			for node in ast.walk(tree):
				if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
					continue
				if not node.name.startswith("event_"):
					continue
				# Verifica se nextHandler esta nos parametros da funcao
				param_names = [a.arg for a in node.args.args]
				if "nextHandler" not in param_names:
					continue
				# Verifica se nextHandler() e chamado em algum lugar do corpo
				_called = False
				for _child in ast.walk(node):
					if isinstance(_child, ast.Call):
						func = _child.func
						# nextHandler() — chamada direta
						if isinstance(func, ast.Name) and func.id == "nextHandler":
							_called = True
							break
				if not _called:
					problems.append(
						f"NVDA-001: {py_file}: linha {node.lineno}: "
						f"funcao '{node.name}' tem parametro nextHandler mas nunca chama "
						f"nextHandler() — outros handlers na cadeia nao serao notificados. "
						f"Adicione nextHandler() no final da funcao."
					)
	return problems


def _check_script_descriptions(addon_folder: str) -> list[str]:
	"""
	E15 — NVDA-008: funcoes decoradas com @script sem kwarg 'description'.

	Logica AST:
	- Para cada .py em globalPlugins/ (exceto lib/)
	- Encontra funcoes com decorator @script
	- Verifica se o decorator tem o kwarg 'description'
	- Se nao tiver -> reporta NVDA-008
	  Scripts sem description ficam invisiveis no dialogo de gestos de entrada do NVDA.
	"""
	problems: list[str] = []
	gp_dir = os.path.join(addon_folder, "globalPlugins")
	if not os.path.isdir(gp_dir):
		return problems

	for pdir in os.listdir(gp_dir):
		pdir_path = os.path.join(gp_dir, pdir)
		if not os.path.isdir(pdir_path):
			continue
		for py_file in os.listdir(pdir_path):
			if not py_file.endswith(".py"):
				continue
			full_path = os.path.join(pdir_path, py_file)
			try:
				with open(full_path, encoding="utf-8", errors="replace") as fh:
					src = fh.read()
			except OSError:
				continue
			if "@script" not in src:
				continue
			try:
				tree = ast.parse(src, filename=py_file)
			except SyntaxError:
				continue
			for node in ast.walk(tree):
				if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
					continue
				for deco in node.decorator_list:
					# @script(description=...) — decorator com argumentos
					if isinstance(deco, ast.Call):
						deco_name = ""
						if isinstance(deco.func, ast.Name):
							deco_name = deco.func.id
						elif isinstance(deco.func, ast.Attribute):
							deco_name = deco.func.attr
						if deco_name != "script":
							continue
						# Verifica se ha kwarg 'description'
						kwarg_names = [kw.arg for kw in deco.keywords]
						if "description" not in kwarg_names:
							problems.append(
								f"NVDA-008: {py_file}: linha {node.lineno}: "
								f"@script na funcao '{node.name}' sem kwarg 'description' — "
								f"o script ficara invivel no dialogo 'Gestos de Entrada' do NVDA. "
								f"Adicione: @script(gesture='...', description=_('Descricao'))."
							)
					# @script sem parenteses — tambem invalido (nao ha como ter description)
					elif isinstance(deco, ast.Name) and deco.id == "script":
						problems.append(
							f"NVDA-008: {py_file}: linha {node.lineno}: "
							f"@script sem argumentos na funcao '{node.name}' — "
							f"use @script(gesture='...', description=_('Descricao'))."
						)
	return problems


def _check_reserved_gestures(addon_folder: str) -> list[str]:
	"""
	E16 — NVDA-009: uso de gestures reservados pelo NVDA core.

	Logica regex/texto:
	- Para cada .py em globalPlugins/ (exceto lib/)
	- Busca strings que correspondam a gestures de _NVDA_CORE_GESTURES
	- Se encontrar -> reporta NVDA-009 com o gesture especifico
	  Redefinir gestures do core pode quebrar comandos globais do NVDA para o usuario.
	"""
	problems: list[str] = []
	gp_dir = os.path.join(addon_folder, "globalPlugins")
	if not os.path.isdir(gp_dir):
		return problems

	# Regex que captura qualquer string entre aspas contendo "kb:nvda+"
	_gesture_re = re.compile(r'["\']([^"\']*kb:nvda\+[^"\']*)["\']', re.IGNORECASE)

	for pdir in os.listdir(gp_dir):
		pdir_path = os.path.join(gp_dir, pdir)
		if not os.path.isdir(pdir_path):
			continue
		for py_file in os.listdir(pdir_path):
			if not py_file.endswith(".py"):
				continue
			full_path = os.path.join(pdir_path, py_file)
			try:
				with open(full_path, encoding="utf-8", errors="replace") as fh:
					src = fh.read()
			except OSError:
				continue
			if "nvda+" not in src.lower():
				continue
			for match in _gesture_re.finditer(src):
				gesture = match.group(1).lower()
				if gesture in _NVDA_CORE_GESTURES:
					# Calcula numero de linha da ocorrencia
					lineno = src[: match.start()].count("\n") + 1
					problems.append(
						f"NVDA-009: {py_file}: linha {lineno}: "
						f"gesture '{gesture}' e reservado pelo NVDA core — "
						f"redefinir esse atalho quebra comandos globais do NVDA. "
						f"Escolha um gesture diferente para este script."
					)
	return problems



def _check_dialog_accessibility(addon_folder: str) -> list[str]:
	"""E21 — WX-A11Y-004: Dialogos wx sem StdDialogButtonSizer ou tecla Escape.

	wx.Dialog sem StdDialogButtonSizer e sem handler de tecla Escape
	deixa usuarios de teclado presos no dialogo sem poder fecha-lo.
	Verifica via heuristica de texto (presenca de padroes).
	"""
	problems: list[str] = []
	gp_dir = os.path.join(addon_folder, "globalPlugins")
	if not os.path.isdir(gp_dir):
		return problems

	for pdir in os.listdir(gp_dir):
		pdir_path = os.path.join(gp_dir, pdir)
		if not os.path.isdir(pdir_path):
			continue
		for py_file in os.listdir(pdir_path):
			if not py_file.endswith(".py"):
				continue
			full_path = os.path.join(pdir_path, py_file)
			try:
				with open(full_path, encoding="utf-8", errors="replace") as fh:
					src = fh.read()
			except OSError:
				continue
			has_dialog = bool(re.search(
				r"class\s+\w+Dialog|wx\.Dialog\(",
				src, re.IGNORECASE,
			))
			if not has_dialog:
				continue
			has_sizer = "StdDialogButtonSizer" in src or "CreateButtonSizer" in src
			has_escape = bool(re.search(
				r"WXK_ESCAPE|wx\.ID_CANCEL|EVT_CHAR_HOOK.*ESCAPE|"
				r"EVT_KEY_DOWN.*ESCAPE|\.Bind\(.*EVT_CLOSE",
				src, re.IGNORECASE,
			))
			if not has_sizer and not has_escape:
				problems.append(
					f"WX-A11Y-004: {py_file}: "
					f"Dialogo wx sem StdDialogButtonSizer nem handler "
					f"de tecla Escape — usuarios de teclado podem ficar "
					f"presos sem conseguir fechar. Adicione "
					f"StdDialogButtonSizer ou Bind(EVT_CHAR_HOOK) para Escape."
				)
	return problems

def _check_translatable_strings(addon_folder: str) -> list[str]:
	"""
	E17 — NVDA-019: chamadas a _() sem comentario '# Translators:' na linha anterior.

	Logica texto linha a linha:
	- Para cada .py em globalPlugins/ (exceto lib/)
	- Se uma linha contem _(" mas a linha ANTERIOR nao e um comentario '# Translators:'
	  (ou '# translators:' — case-insensitive)
	  -> reporta NVDA-019 com arquivo e numero da linha
	- Ignora linhas que sao comentarios ou estao em strings de documentacao (heuristica simples).
	  O comentario Translators: e obrigatorio para o Poedit extrair a string para traducao.
	"""
	problems: list[str] = []
	gp_dir = os.path.join(addon_folder, "globalPlugins")
	if not os.path.isdir(gp_dir):
		return problems

	# Heuristica para detectar inicio de docstring multiline (nao perfeita, mas adequada)
	_docstring_re = re.compile(r'^\s*("""|\'\'\').*$')

	for pdir in os.listdir(gp_dir):
		pdir_path = os.path.join(gp_dir, pdir)
		if not os.path.isdir(pdir_path):
			continue
		for py_file in os.listdir(pdir_path):
			if not py_file.endswith(".py"):
				continue
			full_path = os.path.join(pdir_path, py_file)
			try:
				with open(full_path, encoding="utf-8", errors="replace") as fh:
					lines = fh.readlines()
			except OSError:
				continue
			in_docstring = False
			for i, line in enumerate(lines):
				stripped = line.strip()
				# Alternancia de docstring (heuristica basica)
				if '"""' in stripped or "'''" in stripped:
					# Conta ocorrencias: numero impar significa que entramos/saimos
					triple_dq = stripped.count('"""')
					triple_sq = stripped.count("'''")
					if (triple_dq % 2 == 1) or (triple_sq % 2 == 1):
						in_docstring = not in_docstring
				if in_docstring:
					continue
				# Ignora linhas de comentario
				if stripped.startswith("#"):
					continue
				# Detecta _(" ou _(' na linha
				if '_("' not in line and "_('" not in line:
					continue
				# Verifica se a linha anterior e um comentario Translators:
				prev_line = lines[i - 1].strip() if i > 0 else ""
				if not (prev_line.startswith("#") and "translators:" in prev_line.lower()):
					problems.append(
						f"NVDA-019: {py_file}: linha {i + 1}: "
						f"chamada a _() sem '# Translators: ...' na linha anterior — "
						f"o Poedit nao extraira essa string para traducao. "
						f"Adicione '# Translators: Descricao breve' acima da linha."
					)
	return problems


def _check_indentation_style(addon_folder: str) -> list[str]:
	"""
	E18 — NVDA-021: uso de espacos em vez de TABs para indentacao.

	Logica texto:
	- Para cada .py em globalPlugins/ (exceto lib/)
	- Se uma linha comeca com 4 espacos em vez de TAB -> reporta NVDA-021
	- Apenas a primeira ocorrencia por arquivo e suficiente para alertar o desenvolvedor.
	  O NVDA e o padrÃ£o NVDA core usam TABs — misturar espacos e TABs causa IndentationError.
	"""
	problems: list[str] = []
	gp_dir = os.path.join(addon_folder, "globalPlugins")
	if not os.path.isdir(gp_dir):
		return problems

	for pdir in os.listdir(gp_dir):
		pdir_path = os.path.join(gp_dir, pdir)
		if not os.path.isdir(pdir_path):
			continue
		for py_file in os.listdir(pdir_path):
			if not py_file.endswith(".py"):
				continue
			full_path = os.path.join(pdir_path, py_file)
			try:
				with open(full_path, encoding="utf-8", errors="replace") as fh:
					lines = fh.readlines()
			except OSError:
				continue
			for i, line in enumerate(lines):
				# Detecta linha que comeca com 4 ou mais espacos (nao TAB)
				# e nao e uma linha em branco ou comentario de nivel 0
				if line.startswith("    ") and not line.startswith("\t"):
					problems.append(
						f"NVDA-021: {py_file}: linha {i + 1}: "
						f"indentacao com espacos detectada — o NVDA e o core NVDA usam TABs. "
						f"Substitua os espacos por TABs para evitar IndentationError em Python "
						f"com modo strict de mistura de indentacao."
					)
					# Apenas primeira ocorrencia por arquivo
					break
	return problems



def _check_private_symbol_imports(addon_folder: str) -> list[str]:
	"""E20 — NVDA-026: imports de simbolos privados (_prefix) do NVDA.

	Simbolos com prefixo _ sao privados e podem mudar sem aviso
	entre versoes do NVDA. Importa-los quebra o addon em updates.

	Usa AST para detectar `from modulo import _simbolo` em qualquer
	arquivo .py do addon. Ignora imports relativos (`.modulo`),
	modulos do proprio addon e stdlib — foco apenas em modulos NVDA.
	"""
	problems: list[str] = []
	gp_dir = os.path.join(addon_folder, "globalPlugins")
	if not os.path.isdir(gp_dir):
		return problems

	# Nomes de modulo que indicam origem NVDA (case-insensitive)
	_NVDA_MODULE_INDICATORS = frozenset({
		"scriptHandler", "globalCommands", "inputCore",
		"speech", "braille", "NVDAObjects", "appModuleHandler",
		"globalPluginHandler", "synthDriverHandler", "bdDetect",
		"gui", "config", "api", "ui", "winUser", "winKernel",
		"winGDI", "eventHandler", "logHandler", "addonHandler",
		"tones", "nvwave", "keyboardHandler", "mouseHandler",
		"textInfos", "controlTypes", "cursorManager",
		"reviewCursor", "vision", "comtypes",
	})

	for pdir in os.listdir(gp_dir):
		pdir_path = os.path.join(gp_dir, pdir)
		if not os.path.isdir(pdir_path):
			continue
		for py_file in os.listdir(pdir_path):
			if not py_file.endswith(".py"):
				continue
			full_path = os.path.join(pdir_path, py_file)
			try:
				with open(full_path, encoding="utf-8", errors="replace") as fh:
					src = fh.read()
			except OSError:
				continue
			try:
				tree = ast.parse(src)
			except SyntaxError:
				continue
			for node in ast.walk(tree):
				if isinstance(node, ast.ImportFrom):
					if node.level is not None and node.level > 0:
						continue  # relative import, safe
					mod = (node.module or "").split(".")[0]
					if mod.lower() not in _NVDA_MODULE_INDICATORS:
						continue
					for alias in node.names:
						if alias.name.startswith("_"):
							problems.append(
								f"NVDA-026: {py_file} linha {node.lineno}: "
								f"'{alias.name}' importado de modulo NVDA '{mod}' "
								f"— simbolo privado (prefixo _) — quebra com "
								f"atualizacoes do NVDA. Use a API publica."
							)
	return problems

def _check_wx_accessibility(addon_folder: str) -> list[str]:
	"""
	E19 — WX-A11Y-001/002/003: widgets wx sem atributos de acessibilidade.

	Logica regex/texto (nao AST completo — analise heuristica por presenca de padroes):

	WX-A11Y-001: arquivo usa wx.Button( mas nao tem label= nem .SetName( em
	  nenhum lugar -> widgets sem nome acessivel sao inutilizaveis por
	  leitores de tela. 4.11.0: label= adicionado como sinal aceito (achado
	  real, fonte citada wxpython-specialist.agent.md exige label= no Button
	  como fix primario -- SetName() mantido como complemento, nao mais o
	  unico sinal aceito).

	WX-A11Y-002: arquivo usa wx.Panel( ou wx.Frame( mas nao tem AcceleratorTable
	  -> paineis/frames sem tabela de atalhos nao permitem navegacao por teclado.

	WX-A11Y-003: arquivo usa EVT_LEFT_DOWN mas nao tem EVT_CHAR_HOOK nem EVT_KEY_DOWN
	  -> eventos apenas de mouse sem equivalente de teclado sao inacessiveis.

	Cada regra gera no maximo um problema por arquivo para evitar spam no relatorio.
	"""
	problems: list[str] = []
	gp_dir = os.path.join(addon_folder, "globalPlugins")
	if not os.path.isdir(gp_dir):
		return problems

	for pdir in os.listdir(gp_dir):
		pdir_path = os.path.join(gp_dir, pdir)
		if not os.path.isdir(pdir_path):
			continue
		for py_file in os.listdir(pdir_path):
			if not py_file.endswith(".py"):
				continue
			full_path = os.path.join(pdir_path, py_file)
			try:
				with open(full_path, encoding="utf-8", errors="replace") as fh:
					src = fh.read()
			except OSError:
				continue

			# WX-A11Y-001: wx.Button sem label= nem .SetName(
			if "wx.Button(" in src and "label=" not in src and ".SetName(" not in src:
				problems.append(
					f"WX-A11Y-001: {py_file}: "
					f"wx.Button() detectado sem label= nem .SetName() — "
					f"botoes sem nome acessivel sao anunciados apenas como 'Botao' "
					f"por leitores de tela. Fix primario (fonte oficial): "
					f"wx.Button(parent, label=_('Nome legivel'))."
				)

			# WX-A11Y-002: wx.Panel ou wx.Frame sem AcceleratorTable
			has_panel_or_frame = "wx.Panel(" in src or "wx.Frame(" in src
			if has_panel_or_frame and "AcceleratorTable" not in src:
				problems.append(
					f"WX-A11Y-002: {py_file}: "
					f"wx.Panel() ou wx.Frame() sem AcceleratorTable — "
					f"usuarios de teclado nao conseguem ativar acoes pelo teclado. "
					f"Adicione wx.AcceleratorTable com as teclas de atalho do painel."
				)

			# WX-A11Y-003: EVT_LEFT_DOWN sem equivalente de teclado
			if (
				"EVT_LEFT_DOWN" in src
				and "EVT_CHAR_HOOK" not in src
				and "EVT_KEY_DOWN" not in src
			):
				problems.append(
					f"WX-A11Y-003: {py_file}: "
					f"Bind(EVT_LEFT_DOWN) sem equivalente de teclado (EVT_CHAR_HOOK ou EVT_KEY_DOWN) — "
					f"acao acessivel apenas por mouse. Adicione Bind(EVT_CHAR_HOOK, ...) "
					f"ou Bind(EVT_KEY_DOWN, ...) para suporte a teclado."
				)
	return problems



def _check_all_nvda_fallbacks(addon_folder: str, manifest_fields: dict) -> list[str]:
	"""Fallback validation for ALL 33 NVDA rules without structural fallback."""
	problems: list[str] = []
	gp_dir = os.path.join(addon_folder, "globalPlugins")
	if not os.path.isdir(gp_dir):
		return problems

	all_py: list[tuple[str, str]] = []
	for plugin_area in ["globalPlugins", "appModules", "synthDrivers", "brailleDisplayDrivers"]:
		area_dir = os.path.join(addon_folder, plugin_area)
		if not os.path.isdir(area_dir):
			continue
		for root, dirs, files in os.walk(area_dir):
			dirs[:] = [d for d in dirs if d != "lib"]
			for fname in files:
				if fname.endswith(".py"):
					full = os.path.join(root, fname)
					try:
						with open(full, encoding="utf-8", errors="replace") as fh:
							code = fh.read()
						all_py.append((os.path.relpath(full, addon_folder), code))
					except OSError:
						continue

	# NVDA-002: Bloqueio thread principal
	for rel, code in all_py:
		if "time.sleep(" in code and "threading" not in code:
			problems.append(f"NVDA-002: {rel}: time.sleep() bloqueia thread principal. Use threading.Thread + wx.CallAfter.")
		if re.search(r"requests\.(get|post|put|delete)\(", code) and "threading" not in code:
			problems.append(f"NVDA-002: {rel}: HTTP sincrono bloqueia thread principal. Use threading.Thread.")

	# NVDA-005: Formato de versao
	version = manifest_fields.get("version", "")
	if version and not re.match(r"^\d+\.\d+\.\d+$", version):
		problems.append(f"NVDA-005: manifest.ini: version='{version}' formato invalido. Use major.minor.patch.")

	# NVDA-006: Monkey-patching
	for rel, code in all_py:
		if re.search(r"^\s*\w+\.\w+\s*=\s*(lambda|def)", code, re.MULTILINE):
			if "extensionPoints" not in code:
				problems.append(f"NVDA-006: {rel}: possivel monkey-patching. Use extension points.")

	# NVDA-010: UI update sem wx.CallAfter
	for rel, code in all_py:
		if "threading.Thread" in code:
			if "ui.message(" in code and "wx.CallAfter" not in code:
				problems.append(f"NVDA-010: {rel}: ui.message() em thread sem wx.CallAfter().")
			if ".SetLabel(" in code and "wx.CallAfter" not in code:
				problems.append(f"NVDA-010: {rel}: .SetLabel() em thread sem wx.CallAfter().")

	# NVDA-011: Driver sem check()
	for rel, code in all_py:
		if "SynthDriver" in code or "BrailleDisplayDriver" in code:
			if "def check(" not in code:
				problems.append(f"NVDA-011: {rel}: Driver sem metodo check().")

	# NVDA-012: except: bare
	for rel, code in all_py:
		if re.search(r"except\s*:", code):
			problems.append(f"NVDA-012: {rel}: except: bare. Especifique a excecao.")

	# NVDA-013: API version range
	min_nvda = manifest_fields.get("minimumNVDAVersion", "")
	if min_nvda and parse_version_tuple(min_nvda) < (2019, 3, 0):
		problems.append(f"NVDA-013: manifest.ini: minimumNVDAVersion={min_nvda} abaixo do minimo.")

	# NVDA-015: config.conf.spec ausente
	for rel, code in all_py:
		if "config.conf[" in code and "config.conf.spec" not in code and "configSpec" not in code:
			problems.append(f"NVDA-015: {rel}: usa config.conf sem config.conf.spec. Crie configSpec.py.")

	# NVDA-016: shouldWriteToDisk ausente
	for rel, code in all_py:
		if re.search(r"open\(.*['\"]w['\"]", code) and "shouldWriteToDisk" not in code:
			problems.append(f"NVDA-016: {rel}: escrita em disco sem shouldWriteToDisk().")

	# NVDA-018: minimumNVDAVersion < 2019.3
	if min_nvda and parse_version_tuple(min_nvda) < (2019, 3, 0):
		problems.append(f"NVDA-018: manifest.ini: minimumNVDAVersion={min_nvda} < 2019.3.0.")

	# NVDA-020: Import re-export
	for rel, code in all_py:
		if "from NVDAObjects import" in code and "IAccessible" in code:
			problems.append(f"NVDA-020: {rel}: from NVDAObjects import IAccessible. Use from NVDAObjects.IAccessible import IAccessible.")

	# NVDA-027: WebView2 sem disableBrowseMode
	for rel, code in all_py:
		if "msedgewebview2" in rel.lower():
			if "class AppModule" in code and "disableBrowseModeByDefault" not in code:
				problems.append(f"NVDA-027: {rel}: AppModule msedgewebview2 sem disableBrowseModeByDefault.")

	# NVDA-028: Type hints legados
	for rel, code in all_py:
		if "from typing import Optional" in code or "from typing import Union" in code:
			problems.append(f"NVDA-028: {rel}: usa Optional/Union. Use X | None e X | Y nativos.")

	# NVDA-029: CRLF
	for rel, code in all_py:
		if "\r\n" in code:
			problems.append(f"NVDA-029: {rel}: line endings CRLF. Use LF (\\n).")

	# NVDA-030: __init__ sem super().__init__(*args, **kwargs)
	for rel, code in all_py:
		if "class GlobalPlugin" in code or "class AppModule" in code:
			if "def __init__" in code and "super().__init__(*args, **kwargs)" not in code:
				problems.append(f"NVDA-030: {rel}: __init__ sem super().__init__(*args, **kwargs).")

	# NVDA-031: SynthDriver sem cancel()
	for rel, code in all_py:
		if "SynthDriver" in code and "synthDriverHandler" in code:
			if "def cancel(" not in code:
				problems.append(f"NVDA-031: {rel}: SynthDriver sem cancel().")

	# NVDA-032: Extension point sem unregister
	for rel, code in all_py:
		if ".register(" in code and ("extensionPoints" in code or "filter_speechSequence" in code):
			if ".unregister(" not in code:
				problems.append(f"NVDA-032: {rel}: .register() sem .unregister() em terminate().")

	# NVDA-033: event_NVDAObject_init em GlobalPlugin
	for rel, code in all_py:
		if "class GlobalPlugin" in code and "event_NVDAObject_init" in code:
			problems.append(f"NVDA-033: {rel}: event_NVDAObject_init em GlobalPlugin. So funciona em AppModule.")

	# NVDA-034: AppModule self-voicing sem sleepMode
	for rel, code in all_py:
		if "class AppModule" in code and ("self.voicing" in code.lower() or "selfVoicing" in code):
			if "sleepMode" not in code:
				problems.append(f"NVDA-034: {rel}: AppModule self-voicing sem sleepMode = True.")

	# NVDA-035: SynthDriver sem pause()
	for rel, code in all_py:
		if "SynthDriver" in code and "synthDriverHandler" in code:
			if "def pause(" not in code:
				problems.append(f"NVDA-035: {rel}: SynthDriver sem pause().")

	# NVDA-036: SynthDriver sem speak()
	for rel, code in all_py:
		if "SynthDriver" in code and "synthDriverHandler" in code:
			if "def speak(" not in code:
				problems.append(f"NVDA-036: {rel}: SynthDriver sem speak().")

	# NVDA-037: BrailleDisplayDriver sem campos obrigatorios
	for rel, code in all_py:
		if "BrailleDisplayDriver" in code:
			missing = []
			if "numCols" not in code:
				missing.append("numCols")
			if "def display(" not in code:
				missing.append("display()")
			if "isThreadSafe" not in code:
				missing.append("isThreadSafe")
			if missing:
				problems.append(f"NVDA-037: {rel}: BrailleDisplayDriver sem: {', '.join(missing)}.")

	# NVDA-038: SynthDriver sem supportedNotifications
	for rel, code in all_py:
		if "SynthDriver" in code:
			if "supportedNotifications" not in code:
				problems.append(f"NVDA-038: {rel}: SynthDriver sem supportedNotifications.")

	# NVDA-039: AppModules duplicados
	app_modules_dir = os.path.join(addon_folder, "appModules")
	if os.path.isdir(app_modules_dir):
		app_py_files = [f for f in os.listdir(app_modules_dir) if f.endswith(".py")]
		if len(app_py_files) > 1:
			codes = {}
			for f in app_py_files:
				try:
					with open(os.path.join(app_modules_dir, f), encoding="utf-8", errors="replace") as fh:
						codes[f] = fh.read()
				except OSError:
					continue
			seen: dict[str, str] = {}
			for f, c in codes.items():
				body = re.sub(r"#.*", "", c)
				body = re.sub(r"\s+", " ", body).strip()
				if body in seen:
					problems.append(f"NVDA-039: appModules/: {f} e {seen[body]} identicos. Use registerExecutableWithAppModule().")
				else:
					seen[body] = f

	# NVDA-040: wwahost sem heranca correta
	for rel, code in all_py:
		if "wwahost" in rel.lower():
			if "class AppModule" in code and "nvdaBuiltin.appModules.wwahost" not in code:
				problems.append(f"NVDA-040: {rel}: AppModule wwahost sem herdar de nvdaBuiltin.appModules.wwahost.AppModule.")

	# NVDA-042: _() em vez de ngettext()
	for rel, code in all_py:
		if re.search(r"_\(['\"].*\{.*n.*\}.*['\"]\)", code) and "ngettext" not in code:
			problems.append(f"NVDA-042: {rel}: _() para string com contagem. Use ngettext().")

	# NVDA-043: brailleTables sem [brailleTables] no manifest
	manifest_path = os.path.join(addon_folder, "manifest.ini")
	if os.path.isfile(manifest_path):
		try:
			with open(manifest_path, encoding="utf-8", errors="replace") as fh:
				mraw = fh.read()
			if os.path.isdir(os.path.join(addon_folder, "brailleTables")) and "[brailleTables]" not in mraw:
				problems.append("NVDA-043: brailleTables/ existe mas manifest.ini sem [brailleTables].")
		except OSError:
			pass

	# NVDA-044: symbols-*.dic sem [symbolDictionaries]
	if os.path.isfile(manifest_path):
		try:
			with open(manifest_path, encoding="utf-8", errors="replace") as fh:
				mraw = fh.read()
			has_sym = False
			loc_dir = os.path.join(addon_folder, "locale")
			if os.path.isdir(loc_dir):
				for _root, _dirs, files in os.walk(loc_dir):
					if any(f.startswith("symbols-") and f.endswith(".dic") for f in files):
						has_sym = True
						break
			if has_sym and "[symbolDictionaries]" not in mraw:
				problems.append("NVDA-044: symbols-*.dic existe mas manifest.ini sem [symbolDictionaries].")
		except OSError:
			pass

	# NVDA-045: gestures.ini sem [gestureRemaps]
	if os.path.isfile(manifest_path):
		try:
			with open(manifest_path, encoding="utf-8", errors="replace") as fh:
				mraw = fh.read()
			has_ges = False
			loc_dir = os.path.join(addon_folder, "locale")
			if os.path.isdir(loc_dir):
				for _root, _dirs, files in os.walk(loc_dir):
					if "gestures.ini" in files:
						has_ges = True
						break
			if has_ges and "[gestureRemaps]" not in mraw:
				problems.append("NVDA-045: gestures.ini existe mas manifest.ini sem [gestureRemaps].")
		except OSError:
			pass

	# NVDA-046: speechDicts sem [speechDictionaries]
	if os.path.isfile(manifest_path):
		try:
			with open(manifest_path, encoding="utf-8", errors="replace") as fh:
				mraw = fh.read()
			if os.path.isdir(os.path.join(addon_folder, "speechDicts")) and "[speechDictionaries]" not in mraw:
				problems.append("NVDA-046: speechDicts/ existe mas manifest.ini sem [speechDictionaries].")
		except OSError:
			pass

	# NVDA-049: wx.MessageDialog/wx.MessageBox proibidos. Achado real ao vivo
	# (test_e36, GeminiMultimodal): esta checagem so procurava "wx.MessageDialog"
	# -- codigo gerado usando "wx.MessageBox" (mesma violacao de acessibilidade,
	# API wx diferente) passava batido aqui, e a unica linha de defesa virava
	# o critic (LLM), que reprovava mas sem um sinal mecanico claro pro retry
	# convergir.
	for rel, code in all_py:
		if "wx.MessageDialog" in code:
			problems.append(f"NVDA-049: {rel}: wx.MessageDialog proibido. Use gui.message.MessageDialog.")
		if re.search(r"\bwx\.MessageBox\s*\(", code):
			problems.append(f"NVDA-049: {rel}: wx.MessageBox proibido. Use gui.message.MessageDialog.")

	# NVDA-050: NVDAObject overlay herda de base
	for rel, code in all_py:
		if "chooseNVDAObjectOverlayClasses" in code or "initOverlayClass" in code:
			if re.search(r"class\s+\w+\(NVDAObject\)", code):
				problems.append(f"NVDA-050: {rel}: overlay class herda de NVDAObject base. Use IAccessible/UIA/Window/JABObject.")

	# NVDA-052: Uso de APIs legadas winUser/winKernel/winGDI/shellapi/ftdi2
	for rel, code in all_py:
		if re.search(r"\bimport\s+(winUser|winKernel|winGDI|shellapi)\b", code) or re.search(r"\bfrom\s+(winUser|winKernel|winGDI|shellapi)\s+import\b", code):
			problems.append(f"NVDA-052: {rel}: uso de import legado de winUser/winKernel/winGDI/shellapi. Migre para winBindings.")
		elif re.search(r"\bimport\s+ftdi2\b", code) or re.search(r"\bfrom\s+ftdi2\s+import\b", code):
			problems.append(f"NVDA-052: {rel}: uso de import legado de ftdi2. Migre para o subpacote ftdi2 com snake_case.")

	# NVDA-053: SAPI 4/5 32-bit voices
	for rel, code in all_py:
		if '"sapi4"' in code or "'sapi4'" in code:
			problems.append(f"NVDA-053: {rel}: uso de sapi4 legado. Use sapi4_32 para vozes de 32 bits (sem suporte a audio ducking).")

	# NVDA-054: typing_extensions removida no NVDA 2026.1
	for rel, code in all_py:
		if "import typing_extensions" in code or "from typing_extensions import" in code:
			problems.append(f"NVDA-054: {rel}: uso de typing_extensions. Remova e use o suporte nativo do Python 3.13 no NVDA 2026.1+.")

	return problems

def validate_addon_structure(addon_folder: str) -> list[str]:
	"""
	Smoke test estrutural do addon gerado.

	Verifica sem executar codigo (Regra 9):
	- manifest.ini na raiz com campos obrigatorios
	- globalPlugins/ com arquivo Python
	- Classe GlobalPlugin presente
	- addonHandler.initTranslation() presente (NVDA-003)
	- terminate() presente (NVDA-004)
	- Pasta doc/ presente (userGuide.html)
	- event_* com nextHandler ignorado (NVDA-001) via _check_event_handlers()
	- @script sem description (NVDA-008) via _check_script_descriptions()
	- Gestures reservados do NVDA core (NVDA-009) via _check_reserved_gestures()
	- _() sem # Translators: comment (NVDA-019) via _check_translatable_strings()
	- Indentacao com espacos em vez de TABs (NVDA-021) via _check_indentation_style()
	- Widgets wx sem acessibilidade (WX-A11Y-001/002/003) via _check_wx_accessibility()
	- Imports de simbolos privados (NVDA-026) via _check_private_symbol_imports()
	- Dialogos sem Escape/StdDialogButtonSizer (WX-A11Y-004) via _check_dialog_accessibility()

	Retorna lista de problemas (vazia = estrutura OK).
	Usado pelo studio_dialog para anunciar problemas ao usuario cego imediatamente apos salvar.
	Regra 9: analisa texto — nao importa nem executa nenhum modulo gerado.
	"""
	problems: list[str] = []

	if not os.path.isdir(addon_folder):
		return [f"ESTRUTURA-000: Pasta do addon nao encontrada: {addon_folder}"]

	manifest_fields: dict[str, str] = {}

	# 1. manifest.ini na raiz
	manifest_path = os.path.join(addon_folder, "manifest.ini")
	if not os.path.isfile(manifest_path):
		problems.append("ESTRUTURA-001: manifest.ini ausente na raiz do addon.")
	else:
		try:
			with open(manifest_path, encoding="utf-8", errors="replace") as fh:
				manifest_content = fh.read()
			for line in manifest_content.splitlines():
				if "=" in line and not line.strip().startswith("#"):
					key, _, value = line.partition("=")
					manifest_fields[key.strip()] = value.strip()
			for campo in ["name", "author", "version", "minimumNVDAVersion", "lastTestedNVDAVersion"]:
				if campo not in manifest_content:
					problems.append(
						f"ESTRUTURA-002: Campo '{campo}' ausente no manifest.ini."
					)
			min_nvda = manifest_fields.get("minimumNVDAVersion", "")
			last_tested = manifest_fields.get("lastTestedNVDAVersion", "")
			if min_nvda and parse_version_tuple(min_nvda) < parse_version_tuple(PROJECT_MIN_NVDA):
				problems.append(
					f"POLITICA-001: minimumNVDAVersion = {min_nvda} abaixo do baseline "
					f"oficial do projeto ({PROJECT_MIN_NVDA}). Remova compatibilidade legado."
				)
			if last_tested and parse_version_tuple(last_tested) < parse_version_tuple(PROJECT_LAST_TESTED_NVDA):
				problems.append(
					f"POLITICA-002: lastTestedNVDAVersion = {last_tested} abaixo do baseline "
					f"oficial do projeto ({PROJECT_LAST_TESTED_NVDA}). Atualize o manifest."
				)
		except Exception as exc:
			problems.append(f"ESTRUTURA-002: Erro ao ler manifest.ini: {exc}")

	# 2. globalPlugins/ existe e tem Python
	gp_dir = os.path.join(addon_folder, "globalPlugins")
	if not os.path.isdir(gp_dir):
		problems.append("ESTRUTURA-003: Pasta globalPlugins/ ausente.")
	else:
		py_files: list[str] = []
		for root, dirs, files in os.walk(gp_dir):
			dirs[:] = [d for d in dirs if d != "lib"]  # ignora dependencias bundladas
			for fname in files:
				if fname.endswith(".py"):
					py_files.append(os.path.join(root, fname))

		if not py_files:
			problems.append("ESTRUTURA-004: Nenhum arquivo .py encontrado em globalPlugins/.")
		else:
			# B6: detecta multiplas pastas de plugin (cada uma com __init__.py)
			plugin_subdirs_com_init = [
				d for d in os.listdir(gp_dir)
				if os.path.isdir(os.path.join(gp_dir, d))
				and os.path.isfile(os.path.join(gp_dir, d, "__init__.py"))
			]
			if len(plugin_subdirs_com_init) > 1:
				nomes = ", ".join(plugin_subdirs_com_init)
				problems.append(
					f"ESTRUTURA-007: Multiplas pastas de plugin com __init__.py: {nomes}. "
					f"O NVDA carregaria dois GlobalPlugin simultaneamente — conflito de atalhos. "
					f"Funda o codigo em uma unica pasta globalPlugins/NomeUnico/."
				)


		# ESTRUTURA-008: Pasta de plugin sem __init__.py — NVDA nunca carrega.
		# Detecta subpastas de globalPlugins/ que tem .py mas nao tem __init__.py.
		# Root cause: MediaTranscriber gerou module_1.py sem __init__.py —
		# o addon foi instalado mas nunca carregou (sem menu, sem atalhos).
		for _sub in os.listdir(gp_dir):
			_sub_path = os.path.join(gp_dir, _sub)
			if not os.path.isdir(_sub_path):
				continue
			_has_init = os.path.isfile(os.path.join(_sub_path, "__init__.py"))
			_has_other_py = any(
				f.endswith(".py") and f != "__init__.py"
				for f in os.listdir(_sub_path)
			)
			if _has_other_py and not _has_init:
				problems.append(
					f"ESTRUTURA-008: Pasta globalPlugins/{_sub}/ tem arquivos .py "
					f"mas nao tem __init__.py. O NVDA so carrega __init__.py como "
					f"GlobalPlugin — module_1.py, servicos e outros modulos sao "
					f"ignorados. Renomeie o arquivo principal para __init__.py ou "
					f"crie __init__.py com from .module_1 import *."
				)

		for py_path in py_files:
			fname = os.path.basename(py_path)
			try:
				with open(py_path, encoding="utf-8", errors="replace") as fh:
					code = fh.read()
			except Exception as exc:
				_logger.debug("[DEBUG] Ignorando arquivo problematico: %s", exc)
				continue

			# ESTRUTURA-005, NVDA-003, NVDA-004: obrigatorios APENAS no __init__.py
			# PRINCIPAL do addon (globalPlugins/<AddonName>/__init__.py), nao em
			# QUALQUER __init__.py da arvore. Modulos de suporte (gmail_service.py,
			# settings_panel.py, ai_runner.py, summarizer_service.py, etc.) nao sao
			# GlobalPlugins — nunca terao GlobalPlugin, initTranslation nem
			# terminate. Checar nesses arquivos gera falsos positivos que
			# confundem o usuario sem indicar nenhum problema real.
			#
			# Bug real achado no teste E2E complexo real (2026-08-07, addon
			# AssistenteLeituraGemini): `fname == "__init__.py"` sozinho bate em
			# QUALQUER __init__.py da arvore (via os.walk em py_files acima),
			# nao so o principal -- um addon com subpacotes legitimos
			# (busca_web/__init__.py, resumo/__init__.py, perguntas/__init__.py,
			# historico/__init__.py) gerou 5 falsos positivos identicos de
			# ESTRUTURA-005/NVDA-003/NVDA-004 (1 por __init__.py de subpacote),
			# mesmo com o __init__.py principal 100% correto (GlobalPlugin,
			# initTranslation, terminate, tudo presente). Mesma classe de causa
			# raiz do bug ja corrigido pra ESTRUTURA-009 (subpacotes nao eram
			# reconhecidos la tambem). Fix: so aplica essas 3 regras quando o
			# __init__.py esta em globalPlugins/ diretamente (fixture de teste
			# simplificada, sem subpasta do addon -- ainda coberto por
			# retrocompatibilidade) OU um nivel DIRETO abaixo (o normal:
			# globalPlugins/<AddonName>/__init__.py). NUNCA 2+ niveis abaixo
			# (globalPlugins/<AddonName>/<subpacote>/__init__.py), que e
			# exatamente o padrao que causava o falso positivo.
			_py_dir = os.path.normpath(os.path.dirname(py_path))
			_gp_dir_norm = os.path.normpath(gp_dir)
			_e_init_principal = fname == "__init__.py" and (
				_py_dir == _gp_dir_norm
				or os.path.dirname(_py_dir) == _gp_dir_norm
			)
			if _e_init_principal:
				if "class GlobalPlugin" not in code and "class AppModule" not in code:
					problems.append(
						f"ESTRUTURA-005: {fname}: classe GlobalPlugin ou AppModule ausente."
					)
				if "initTranslation" not in code:
					problems.append(
						f"NVDA-003: {fname}: addonHandler.initTranslation() ausente."
					)
				if "def terminate" not in code:
					problems.append(
						f"NVDA-004: {fname}: metodo terminate() ausente."
					)

			# NVDA-051: Se tem UI (dialogs), deve ter menu Ferramentas.
			# Mesma restricao ao __init__.py PRINCIPAL (nao qualquer __init__.py
			# da arvore) que ESTRUTURA-005/NVDA-003/NVDA-004 acima.
			if _e_init_principal and ("wx.Dialog" in code or "wx.Frame" in code):
				if "_ensure_menu_item" not in code:
					problems.append(
						f"NVDA-051: {fname}: addon com interface de usuario sem "
						f"item no menu Ferramentas (NVDA > Menu > Ferramentas). "
						f"Implementar _ensure_menu_item() + _get_tools_menu()."
					)

		# ESTRUTURA-009: imports relativos sem modulo correspondente.
		# Para cada pasta de plugin, verifica se todos os `from .modulo import`
		# tem um .py correspondente na mesma pasta.
		# Causa raiz do bug do GmailSummarizer: gmail_service.py importava
		# gmail_oauth.py que nunca foi gerado — NVDA silenciava o erro e
		# o plugin inteiro deixava de ser carregado.
		for pdir in os.listdir(gp_dir):
			pdir_path = os.path.join(gp_dir, pdir)
			if not os.path.isdir(pdir_path):
				continue
			module_names = {
				f[:-3]
				for f in os.listdir(pdir_path)
				if f.endswith(".py")
			}
			# Subpacotes (pasta/__init__.py) tambem satisfazem `from .X import Y` --
			# achado no teste real E2E de 2026-08-04: LLM gerou apps/, system_info/
			# e url/ como subpacotes legitimos, e o check antigo (so .py solto)
			# gerava 3 falsos positivos de ESTRUTURA-009 num addon estruturalmente correto.
			module_names |= {
				d
				for d in os.listdir(pdir_path)
				if os.path.isdir(os.path.join(pdir_path, d))
				and os.path.isfile(os.path.join(pdir_path, d, "__init__.py"))
			}
			for py_file in os.listdir(pdir_path):
				if not py_file.endswith(".py"):
					continue
				try:
					with open(
						os.path.join(pdir_path, py_file),
						encoding="utf-8", errors="replace",
					) as _fh:
						_src = _fh.read()
				except Exception as exc:
					_logger.debug("[DEBUG] Ignorando arquivo problematico: %s", exc)
					continue
				for _rim in re.finditer(
					r"^from \.(\w+) import", _src, re.MULTILINE
				):
					mod = _rim.group(1)
					if mod not in module_names:
						problems.append(
							f"ESTRUTURA-009: {py_file}: "
							f"'from .{mod} import ...' mas {mod}.py "
							f"nao encontrado em globalPlugins/{pdir}/. "
							f"O modulo ausente impede o carregamento do addon pelo NVDA."
						)

		# NVDA-022: imports 3rd party em nivel de modulo em arquivos de servico.
		# Import em nivel de modulo em gmail_service.py, summarizer_service.py, etc.
		# faz __init__.py crashar silenciosamente se lib/ estiver incompleta.
		# O NVDA nao loga o erro — o addon inteiro deixa de carregar, incluindo o
		# settings panel. Somente arquivos que NAO sao __init__.py sao verificados.
		for pdir in os.listdir(gp_dir):
			pdir_path = os.path.join(gp_dir, pdir)
			if not os.path.isdir(pdir_path):
				continue
			local_module_names: set[str] = {
				f[:-3].lower()
				for f in os.listdir(pdir_path)
				if f.endswith(".py")
			}
			for py_file in os.listdir(pdir_path):
				if not py_file.endswith(".py") or py_file == "__init__.py":
					continue
				try:
					with open(
						os.path.join(pdir_path, py_file),
						encoding="utf-8", errors="replace",
					) as _fh2:
						_src2 = _fh2.read()
				except Exception as exc:
					_logger.debug("[DEBUG] Ignorando arquivo problematico: %s", exc)
					continue
				try:
					_tree = ast.parse(_src2)
				except SyntaxError:
					continue
				# Verifica apenas imports em nivel de modulo (filhos diretos do Module).
				for _node in _tree.body:
					if isinstance(_node, ast.Import):
						for _alias in _node.names:
							_root = _alias.name.split(".")[0].lower()
							if not _is_known_module(_root, set()) and _root not in local_module_names:
								problems.append(
									f"NVDA-022: {py_file}: "
									f"import '{_alias.name}' em nivel de modulo \u2014 "
									f"se nao bundlado em lib/, impede carregamento do addon "
									f"inteiro (settings panel nunca aparece). "
									f"Mova para dentro do metodo: 'import {_alias.name}' "
									f"dentro de def meu_metodo(self)."
								)
					elif isinstance(_node, ast.ImportFrom):
						# Ignora imports relativos (from .modulo import ...)
						if _node.module and _node.level == 0:
							_root = _node.module.split(".")[0].lower()
							if not _is_known_module(_root, set()) and _root not in local_module_names:
								problems.append(
									f"NVDA-022: {py_file}: "
									f"import '{_node.module}' em nivel de modulo \u2014 "
									f"se nao bundlado em lib/, impede carregamento do addon "
									f"inteiro (settings panel nunca aparece). "
									f"Mova para dentro do metodo: "
									f"'from {_node.module} import ...' "
									f"dentro de def meu_metodo(self)."
								)

				# NVDA-023: type annotation que referencia tipo importado de forma lazy.
				# Em Python 3.x sem 'from __future__ import annotations', annotations sao
				# avaliadas eagerly. Se o tipo so existe no escopo lazy (dentro de metodo),
				# Python levanta NameError ao definir a funcao, impedindo o carregamento do modulo.
				# Root cause confirmado: gmail_oauth.py, def get_credentials() -> Credentials:
				_module_level_names_023: set[str] = set()
				for _n in _tree.body:
					if isinstance(_n, ast.Import):
						for _a in _n.names:
							_module_level_names_023.add(_a.asname or _a.name.split(".")[0])
					elif isinstance(_n, ast.ImportFrom):
						for _a in _n.names:
							_module_level_names_023.add(_a.asname or _a.name)
					elif isinstance(_n, (
						ast.FunctionDef,
						ast.AsyncFunctionDef,
						ast.ClassDef,
					)):
						_module_level_names_023.add(_n.name)
					elif isinstance(_n, ast.Assign):
						for _t in _n.targets:
							if isinstance(_t, ast.Name):
								_module_level_names_023.add(_t.id)
				# Coleta nomes importados de forma lazy (dentro de corpos de funcao).
				# _out recebido por parametro (nao por closure) -- este loop roda por
				# arquivo/pasta, e uma closure sobre _lazy_imported_023 seria
				# revalidada a cada iteracao, arriscando capturar a instancia errada
				# de set() num refactor futuro que adie a chamada.
				def _collect_lazy(_parent: ast.AST, _out: set[str]) -> None:
					for _child in ast.walk(_parent):
						if isinstance(_child, (
							ast.FunctionDef,
							ast.AsyncFunctionDef,
						)):
							for _st in _child.body:
								if isinstance(_st, ast.Import):
									for _al in _st.names:
										_out.add(_al.asname or _al.name.split(".")[0])
								elif isinstance(_st, ast.ImportFrom) and _st.level == 0:
									for _al in _st.names:
										_out.add(_al.asname or _al.name)
				_lazy_imported_023: set[str] = set()
				_collect_lazy(_tree, _lazy_imported_023)
				# Verifica annotations de funcoes que referenciam nomes lazy como bare Name
				for _fn in ast.walk(_tree):
					if not isinstance(_fn, (
						ast.FunctionDef,
						ast.AsyncFunctionDef,
					)):
						continue
					_anns_to_check = [_fn.returns] + [
						_a.annotation
						for _a in (
							_fn.args.args
							+ _fn.args.posonlyargs
							+ _fn.args.kwonlyargs
						)
					]
					for _ann in _anns_to_check:
						if (
							isinstance(_ann, ast.Name)
							and _ann.id in _lazy_imported_023
							and _ann.id not in _module_level_names_023
						):
							problems.append(
								f"NVDA-023: {py_file}: funcao '{_fn.name}' usa "
								f"'{_ann.id}' como type annotation mas esse tipo so "
								f"existe em import lazy (dentro de metodo) \u2014 "
								f"NameError ao carregar o modulo, addon nao carrega. "
								f"Corrija: -> \"{_ann.id}\" (string literal / forward reference)."
							)



		# NVDA-024: categoryClasses.append() sem guard — verifica TODOS os .py (incluindo __init__.py)
		# append() incondicional causa painel duplicado no NVDA Settings ao recarregar addon.
		for _pdir_024 in os.listdir(gp_dir):
			_pdir_path_024 = os.path.join(gp_dir, _pdir_024)
			if not os.path.isdir(_pdir_path_024):
				continue
			for _pyf_024 in os.listdir(_pdir_path_024):
				if not _pyf_024.endswith(".py"):
					continue
				try:
					with open(
						os.path.join(_pdir_path_024, _pyf_024),
						encoding="utf-8", errors="replace",
					) as _fh_024:
						_src_024 = _fh_024.read()
				except OSError:
					continue
				try:
					_tree_024 = ast.parse(_src_024, filename=_pyf_024)
				except SyntaxError:
					continue
				for _node_024 in ast.walk(_tree_024):
					if not isinstance(_node_024, ast.Expr):
						continue
					call = _node_024.value
					if not isinstance(call, ast.Call):
						continue
					func = call.func
					if not (
						isinstance(func, ast.Attribute)
						and func.attr == "append"
						and isinstance(func.value, ast.Attribute)
						and func.value.attr == "categoryClasses"
						and isinstance(func.value.value, ast.Name)
						and func.value.value.id == "NVDASettingsDialog"
					):
						continue
					# Ha um append em NVDASettingsDialog.categoryClasses.
					# Verifica se existe um if com 'not in' guard englobando o append.
					_append_line = _node_024.lineno
					_guarded = False
					for _if_node in ast.walk(_tree_024):
						if not isinstance(_if_node, ast.If):
							continue
						for _stmt in _if_node.body:
							if _stmt.lineno == _append_line:
								_test = _if_node.test
								if (
									isinstance(_test, ast.Compare)
									and any(isinstance(op, ast.NotIn) for op in _test.ops)
								):
									_guarded = True
								break
						if _guarded:
							break
					if not _guarded:
						_panel_name = ""
						if call.args and isinstance(call.args[0], ast.Name):
							_panel_name = call.args[0].id
						problems.append(
							f"NVDA-024: {_pyf_024}: linha {_append_line}: "
							f"NVDASettingsDialog.categoryClasses.append({_panel_name}) "
							f"sem guard 'if {_panel_name} not in NVDASettingsDialog.categoryClasses' "
							f"— painel duplicado no Tab se o addon for recarregado sem terminate() bem-sucedido."
						)

		# NVDA-025: config.conf com secao generica — colisao entre addons
		# Detecta config.conf["X"] onde X eh um placeholder conhecido ou nao corresponde
		# ao addonId declarado no manifest.ini.
		# Extrai addonId do manifest (robusto a manifests sem secao header).
		_manifest_path_025 = os.path.join(addon_folder, "manifest.ini")
		_addon_id_025: str | None = None
		if os.path.isfile(_manifest_path_025):
			try:
				_cp_025 = configparser.ConfigParser()
				_cp_025.read(_manifest_path_025, encoding="utf-8")
				if _cp_025.has_option("add-on", "addonid"):
					_addon_id_025 = _cp_025.get("add-on", "addonid").strip()
				elif _cp_025.has_option("DEFAULT", "addonid"):
					_addon_id_025 = _cp_025.get("DEFAULT", "addonid").strip()
			except Exception:
				# Fallback: parse manual com regex para manifests sem secao header
				try:
					_raw_025 = open(_manifest_path_025, encoding="utf-8").read()
					_m_025 = re.search(r"(?i)addonId\s*=\s*(\S+)", _raw_025)
					if _m_025:
						_addon_id_025 = _m_025.group(1).strip()
				except OSError:
					pass
		_KNOWN_PLACEHOLDERS_025 = {"meuAddon", "addonIdReal", "myAddon", "myaddon"}
		# Itera todos os .py de todas as pastas de plugin (includes __init__.py)
		for _pdir_025 in os.listdir(gp_dir):
			_pdir_path_025 = os.path.join(gp_dir, _pdir_025)
			if not os.path.isdir(_pdir_path_025):
				continue
			for _pyf_025 in os.listdir(_pdir_path_025):
				if not _pyf_025.endswith(".py"):
					continue
				_full_025 = os.path.join(_pdir_path_025, _pyf_025)
				try:
					with open(_full_025, encoding="utf-8", errors="replace") as _fh_025:
						_src_025 = _fh_025.read()
				except OSError:
					continue
				if "config.conf" not in _src_025:
					continue
				try:
					_tree_025 = ast.parse(_src_025, filename=_pyf_025)
				except SyntaxError:
					continue
				for _node_025 in ast.walk(_tree_025):
					# Detecta config.conf["secao"] ou config.conf["secao"]["chave"]
					# AST: Subscript(value=Attribute(value=Name("config"), attr="conf"), slice=Constant("secao"))
					if not isinstance(_node_025, ast.Subscript):
						continue
					_val_025 = _node_025.value
					if not (
						isinstance(_val_025, ast.Attribute)
						and _val_025.attr == "conf"
						and isinstance(_val_025.value, ast.Name)
						and _val_025.value.id == "config"
					):
						continue
					_slice_025 = _node_025.slice
					_section_025: str | None = None
					if isinstance(_slice_025, ast.Constant) and isinstance(_slice_025.value, str):
						_section_025 = _slice_025.value
					if _section_025 is None:
						continue
					# Placeholder generico conhecido
					if _section_025 in _KNOWN_PLACEHOLDERS_025:
						problems.append(
							f"NVDA-025: {_pyf_025}: linha {_node_025.lineno}: "
							f"config.conf[\"{_section_025}\"] usa placeholder generico \u2014 "
							f"substitua pelo addonId real do manifest.ini para evitar colisao "
							f"com outros addons gerados pelo NVDAStudio."
						)
					# Secao que difere do addonId real
					elif (
						_addon_id_025 is not None
						and _section_025.lower() != _addon_id_025.lower()
						and _section_025 not in {"nvdastudio"}
					):
						problems.append(
							f"NVDA-025: {_pyf_025}: linha {_node_025.lineno}: "
							f"config.conf[\"{_section_025}\"] difere do addonId "
							f"\"{_addon_id_025}\" do manifest.ini \u2014 "
							f"use config.conf[\"{_addon_id_025}\"] para evitar colisao entre addons."
						)

	# 3. doc/ existe
	doc_dir = os.path.join(addon_folder, "doc")
	if not os.path.isdir(doc_dir):
		problems.append(
			"ESTRUTURA-006: Pasta doc/ ausente — userGuide.html nao gerado."
		)

	# 4. Arquivos .pyd (binarios compilados) em lib/ — discriminacao por arquitetura.
	# Regra NVDA-017 (skill nvda-addon-dev §22): o problema sao binarios 32-bit
	# incompativeis com NVDA 2026.1+ (Python 3.13 64-bit), nao binarios 64-bit.
	#
	# v4.0.0 (skill tool-design + lint-and-validate): inspecao PE real via struct.
	# Antes: heuristica de nome (win_amd64 no fname) — FALSO POSITIVO confirmado para
	# binarios com nome fixo (_rust.pyd, _upb._message.pyd) que sao 64-bit reais.
	# Apos: le os magic bytes do cabecalho PE (offset 0x3C + 4 bytes para IMAGE_FILE_HEADER).
	# MACHINE_AMD64 (0x8664) â†’ OK; MACHINE_I386 (0x14C) â†’ CRITICO; outros â†’ AVISO.
	#
	# Fallback: se leitura falhar (arquivo vazio, nao-PE, permissao), reporta como AVISO.
	_MACHINE_AMD64 = 0x8664   # x64 — compativel com NVDA 2026.1+ (Python 3.13 64-bit)
	_MACHINE_I386  = 0x014C   # x86 — CRITICO: incompativel com NVDA 2026.1+

	def _pyd_machine(path: str) -> int | None:
		"""Le o campo Machine do IMAGE_FILE_HEADER de um PE. Retorna None se falhar."""
		try:
			with open(path, "rb") as _pf:
				# Cabecalho DOS: magic MZ (0x5A4D), offset 0x3C aponta para PE signature
				_dos = _pf.read(0x40)
				if len(_dos) < 0x40 or _dos[:2] != b"MZ":
					return None
				_pe_offset = struct.unpack_from("<I", _dos, 0x3C)[0]
				_pf.seek(_pe_offset)
				_pe_sig = _pf.read(4)
				if _pe_sig != b"PE\x00\x00":
					return None
				# IMAGE_FILE_HEADER: Machine (2 bytes) imediatamente apos a assinatura PE
				_machine_bytes = _pf.read(2)
				if len(_machine_bytes) < 2:
					return None
				return struct.unpack_from("<H", _machine_bytes)[0]
		except OSError:
			return None

	pyd_criticos:  list[str] = []  # win32 confirmado via PE
	pyd_abi_criticos: list[str] = []  # extensao compilada para CPython diferente de 3.13
	pyd_avisos:    list[str] = []  # leitura PE falhou ou arquitetura desconhecida
	for root, _dirs, files in os.walk(addon_folder):
		for fname in files:
			if not fname.lower().endswith(".pyd"):
				continue
			_fpath = os.path.join(root, fname)
			_rel = os.path.relpath(_fpath, addon_folder)
			_abi_match = re.search(r"\.cp(\d{2,3})(?:-|\.)", fname, re.IGNORECASE)
			if _abi_match and _abi_match.group(1) != _NVDA_PYTHON_VERSION:
				pyd_abi_criticos.append(_rel)
				continue
			_machine = _pyd_machine(_fpath)
			if _machine == _MACHINE_AMD64:
				# 64-bit real — OK para baseline 2026.1+ (Python 3.13 64-bit)
				continue
			if _machine == _MACHINE_I386:
				pyd_criticos.append(_rel)
			else:
				# None = leitura falhou (arquivo vazio, nao-PE, permissao), ou arquitetura exotica.
				# Fallback: se o nome contem win_amd64, trata como 64-bit OK (heuristica segura).
				if "win_amd64" in fname.lower():
					continue
				pyd_avisos.append(_rel)
	if pyd_criticos:
		exemplos = ", ".join(pyd_criticos[:3])
		problems.append(
			f"NVDA-017: {len(pyd_criticos)} arquivo(s) .pyd 32-bit (x86) confirmado(s) "
			f"via inspecao PE: {exemplos}. "
			f"Incompativel com NVDA 2026.1+ (Python 3.13 64-bit). "
			f"Instale com --no-binary ou use wheel win_amd64."
		)
	if pyd_abi_criticos:
		exemplos = ", ".join(pyd_abi_criticos[:3])
		problems.append(
			f"NVDA-017: {len(pyd_abi_criticos)} arquivo(s) .pyd compilado(s) para uma "
			f"ABI Python diferente de CPython 3.13: {exemplos}. "
			f"Incompativel com NVDA 2026.1+. Use wheels cp313-win_amd64 ou abi3-win_amd64."
		)
	if pyd_avisos:
		exemplos = ", ".join(pyd_avisos[:3])
		problems.append(
			f"NVDA-017: {len(pyd_avisos)} arquivo(s) .pyd com arquitetura nao identificada "
			f"(cabecalho PE nao lido): {exemplos}. "
			f"Verifique se sao binarios 64-bit compativeis com Python 3.13 x64. "
			f"Se nao, reinstale com --no-binary para obter wheel win_amd64."
		)

	# E14 — NVDA-001: event_* com nextHandler ignorado
	problems.extend(_check_event_handlers(addon_folder))

	# E15 — NVDA-008: @script sem description
	problems.extend(_check_script_descriptions(addon_folder))

	# E16 — NVDA-009: gestures reservados do NVDA core
	problems.extend(_check_reserved_gestures(addon_folder))

	# E17 — NVDA-019: _() sem # Translators: comment
	problems.extend(_check_translatable_strings(addon_folder))

	# E18 — NVDA-021: indentacao com espacos em vez de TABs
	problems.extend(_check_indentation_style(addon_folder))

	# E19 — WX-A11Y-001/002/003: widgets wx sem acessibilidade
	problems.extend(_check_private_symbol_imports(addon_folder))
	problems.extend(_check_dialog_accessibility(addon_folder))
	problems.extend(_check_wx_accessibility(addon_folder))

	# NVDA-047: url no manifest.ini deve comecar com https:// (Add-on Store rejeita http://)
	# Regex usa [ \t]* (sem newlines) para nao pular para a linha seguinte quando url
	# esta vazio. Bug historico: '\s*' consumia '\r\n' e capturava 'version = 1.0.0'
	# da linha seguinte como se fosse valor de url. Plano aa1600dd (2026-05-10).
	_manifest_047 = os.path.join(addon_folder, "manifest.ini")
	if os.path.isfile(_manifest_047):
		try:
			_raw_047 = open(_manifest_047, encoding="utf-8", errors="replace").read()
			_m_047 = re.search(r"(?im)^url[ \t]*=[ \t]*(.*)$", _raw_047)
			if _m_047:
				_url_047 = _m_047.group(1).strip()
				if not _url_047:
					problems.append(
						"NVDA-047: manifest.ini: campo 'url' esta vazio. "
						"O Add-on Store do NVDA rejeita URLs vazias. "
						"Defina url = https://... com um endereco valido."
					)
				elif not _url_047.lower().startswith("https://"):
					problems.append(
						f"NVDA-047: manifest.ini: url '{_url_047}' nao comeca com https://. "
						f"O Add-on Store do NVDA rejeita URLs sem HTTPS. "
						f"Corrija para: url = https://..."
					)
		except OSError:
			pass

	# NVDA-048: wxPython NUNCA deve ser bundlado — NVDA ja fornece wxPython
	# Detecta qualquer entrada wx* em lib/ (diretorio ou arquivo)
	_lib_dir_048 = os.path.join(addon_folder, "lib")
	if os.path.isdir(_lib_dir_048):
		for _entry_048 in os.listdir(_lib_dir_048):
			if _entry_048.lower().startswith("wx"):
				problems.append(
					f"NVDA-048: lib/{_entry_048}: wxPython bundlado indevidamente. "
					f"O NVDA ja inclui wxPython — bundlar causa conflito de versao "
					f"e falhas imprevisÃ­veis. Remova lib/{_entry_048} do addon."
				)
				break

	# E20 — ALL 33 NVDA fallbacks (NVDA-002, 005, 006, 010-016, 018, 020, 027-046, 049-050)
	problems.extend(_check_all_nvda_fallbacks(addon_folder, manifest_fields))

	if problems:
		_logger.warning("[AVISO] validate_addon_structure: %d problemas: %s",
						len(problems), problems[:3])
	else:
		_logger.info("[OK] validate_addon_structure: estrutura correta.")

	return problems


# Codigos estruturais que impedem o addon de carregar no NVDA.
# Sao bloqueadores reais: sem eles, instalar gera um .nvda-addon inutil que
# falha em silencio (NVDA pula o addon sem mensagem ao usuario). Plano aa1600dd
# (2026-05-10) ensinou que empacotar com ESTRUTURA-004 = lixo entregue ao usuario.
_BLOCKING_STRUCTURAL_CODES = (
	"ESTRUTURA-000",  # pasta do addon nao encontrada
	"ESTRUTURA-001",  # manifest.ini ausente
	"ESTRUTURA-003",  # pasta globalPlugins/ ausente
	"ESTRUTURA-004",  # nenhum .py em globalPlugins/
	"ESTRUTURA-005",  # GlobalPlugin/AppModule ausente em __init__.py
	"ESTRUTURA-007",  # multiplas pastas de plugin (carrega dois GlobalPlugin)
)


def get_blocking_structural_issues(problems: list[str]) -> list[str]:
	"""Filtra apenas problemas que impedem o NVDA de carregar o addon.

	Recebe a lista retornada por validate_addon_structure() e devolve apenas
	os codigos bloqueadores listados em _BLOCKING_STRUCTURAL_CODES.

	Qualquer item na lista de retorno justifica abortar o empacotamento em
	vez de gerar um .nvda-addon que falha em silencio. Avisos nao bloqueadores
	(NVDA-003, NVDA-047, POLITICA-001, ESTRUTURA-006 etc.) continuam sendo
	exibidos como warnings normais.
	"""
	return [p for p in problems if p.startswith(_BLOCKING_STRUCTURAL_CODES)]


def fix_addon_structure(addon_folder: str) -> list[str]:
	"""
	Corrige ESTRUTURA-007: funde multiplas pastas de plugin em uma unica.

	skill: tool-design — "error messages must enable recovery".
	skill: nvda-addon-dev §1 — estrutura obrigatoria: UMA pasta globalPlugins/<nome>/.

	Cenarios cobertos:
	A) Pastas com mesmo nome (duplicatas do assembler) — caso original.
	B) Pastas com nomes DIFERENTES gerados por steps diferentes (ex: GmailSummarizer
	   gerado pelo code_generator e GmailResumo gerado pelo manifest_builder).
	   Antes: so detectava mas nao fundia. Agora: funde usando o canonico do manifest.

	Logica de escolha do nome canonico (prioridade):
	1. Nome declarado no manifest.ini do addon (campo name=) — source of truth
	2. Pasta que tem class GlobalPlugin no __init__.py
	3. Primeira pasta em ordem alfabetica (fallback)

	Etapas:
	1. Lista TODOS os subdiretorios de globalPlugins/ (com ou sem __init__.py)
	2. Se <= 1: retorna [] (nada a corrigir)
	3. Escolhe nome canonico pela prioridade acima
	4. Move todos os arquivos .py de pastas extras para o canonico
	5. Remove as pastas extras

	Retorna lista de acoes aplicadas (vazia = nenhuma correcao necessaria).
	Regra 9: apenas reorganiza arquivos existentes — nao executa codigo.
	"""
	actions: list[str] = []
	gp_dir = os.path.join(addon_folder, "globalPlugins")
	if not os.path.isdir(gp_dir):
		return actions

	# Lista TODOS os subdirs de globalPlugins/ — inclui pastas sem __init__.py
	all_plugin_dirs = sorted([
		d for d in os.listdir(gp_dir)
		if os.path.isdir(os.path.join(gp_dir, d))
	])
	if len(all_plugin_dirs) <= 1:
		return actions

	# Prioridade 1: nome do campo name= no manifest.ini
	canonical: str | None = None
	manifest_path = os.path.join(addon_folder, "manifest.ini")
	if os.path.isfile(manifest_path):
		try:
			with open(manifest_path, encoding="utf-8", errors="replace") as fh:
				for line in fh:
					m = re.match(r"^\s*name\s*=\s*(.+)$", line)
					if m:
						manifest_name = m.group(1).strip().strip('"').strip("'")
						# Procura pasta que case (case-insensitive) com o nome do manifest
						for d in all_plugin_dirs:
							if d.lower() == manifest_name.lower():
								canonical = d
								break
						if not canonical:
							# Nenhuma pasta tem nome exato — cria com nome do manifest
							canonical = manifest_name
						break
		except Exception as exc:
			_logger.warning("[FIX-007] falha ao ler manifest.ini: %s", exc)

	# Prioridade 2: pasta que tem class GlobalPlugin no __init__.py
	if not canonical:
		for d in all_plugin_dirs:
			init_path = os.path.join(gp_dir, d, "__init__.py")
			if os.path.isfile(init_path):
				try:
					with open(init_path, encoding="utf-8", errors="replace") as fh:
						if "class GlobalPlugin" in fh.read():
							canonical = d
							break
				except Exception as exc:
					_logger.debug("[DEBUG] Ignorando arquivo problematico: %s", exc)
					continue

	# Prioridade 3: primeira em ordem alfabetica
	if not canonical:
		canonical = all_plugin_dirs[0]

	canonical_path = os.path.join(gp_dir, canonical)
	os.makedirs(canonical_path, exist_ok=True)

	actions.append(
		f"ESTRUTURA-007: {len(all_plugin_dirs)} pastas detectadas "
		f"({', '.join(all_plugin_dirs)}). Canonico: {canonical}."
	)
	log_decision(_logger, "fix_addon_structure",
				 f"canonico={canonical} extras={[d for d in all_plugin_dirs if d != canonical]}")

	for extra in all_plugin_dirs:
		if extra == canonical:
			continue
		extra_path = os.path.join(gp_dir, extra)
		for fname in os.listdir(extra_path):
			if not fname.endswith(".py"):
				continue
			src = os.path.join(extra_path, fname)
			dst = os.path.join(canonical_path, fname)
			if os.path.exists(dst):
				# Ja existe — preserva o do canonico (tem GlobalPlugin), descarta o extra
				actions.append(f"  SKIP {fname} (ja existe em {canonical})")
				_logger.info("[FIX-007] skip %s (ja existe em %s)", fname, canonical)
			else:
				shutil.move(src, dst)
				actions.append(f"  MOVER {extra}/{fname} -> {canonical}/{fname}")
				_logger.info("[FIX-007] movido %s/%s -> %s/%s",
							 extra, fname, canonical, fname)
		try:
			shutil.rmtree(extra_path)
			actions.append(f"  REMOVIDO {extra}/")
			_logger.info("[FIX-007] pasta removida: %s", extra_path)
		except Exception as exc:
			_logger.warning("[FIX-007] falha ao remover %s: %s", extra_path, exc)

	_logger.info("[OK] fix_addon_structure: %d acoes aplicadas.", len(actions))
	return actions


def generate_store_submission(
	nvda_addon_path: str,
	source_url: str = "",
	download_url: str = "",
	channel: str = "stable",
	license_name: str = "GPL v2",
) -> dict:
	"""
	Gera SHA256 do .nvda-addon e JSON de metadados completo para submissao
	ao NVDA Add-on Store (nvaccess/addon-datastore).

	Fluxo:
	1. Le o manifest.ini do .nvda-addon (ZIP) para extrair metadados
	2. Calcula SHA256 do arquivo .nvda-addon
	3. Monta o JSON conforme esquema oficial do addon-datastore

	Campos obrigatorios do Add-on Store (fonte: jsonMetadata.md):
	  addonId, channel, addonVersionNumber {major,minor,patch},
	  displayName, publisher, description,
	  minNVDAVersion {major,minor,patch}, lastTestedVersion {major,minor,patch},
	  URL (download), sha256, sourceURL, license

	Regra 9: apenas le e processa arquivos — nao executa nenhum codigo.
	Retorna: dict com campo 'json_path' (arquivo salvo), 'sha256', 'metadata'.
	Levanta AddonBuilderError se o arquivo nao existir ou manifest invalido.
	"""
	if not os.path.isfile(nvda_addon_path):
		raise AddonBuilderError(
			f"[ERRO] generate_store_submission: arquivo nao encontrado: {nvda_addon_path}"
		)

	# 1. Calcula SHA256 do .nvda-addon
	sha256_hash = hashlib.sha256()
	with open(nvda_addon_path, "rb") as fh:
		for chunk in iter(lambda: fh.read(65536), b""):
			sha256_hash.update(chunk)
	sha256 = sha256_hash.hexdigest()
	_logger.info("[OK] SHA256 calculado: %s", sha256[:16] + "...")

	# 2. Le manifest.ini de dentro do ZIP
	manifest_data: dict[str, str] = {}
	try:
		with zipfile.ZipFile(nvda_addon_path, "r") as zf:
			# O manifest.ini esta sempre na raiz do ZIP
			manifest_content = zf.read("manifest.ini").decode("utf-8", errors="replace")
			for line in manifest_content.splitlines():
				if "=" in line and not line.strip().startswith("#"):
					key, _, value = line.partition("=")
					manifest_data[key.strip()] = value.strip()
	except KeyError:
		raise AddonBuilderError(
			"[ERRO] generate_store_submission: manifest.ini nao encontrado no .nvda-addon"
		)
	except Exception as exc:
		raise AddonBuilderError(
			f"[ERRO] generate_store_submission: falha ao ler manifest.ini: {exc}"
		)

	# 3. Extrai e valida campos obrigatorios do manifest
	addon_name    = manifest_data.get("name", "")
	addon_summary = manifest_data.get("summary", addon_name)
	addon_desc    = manifest_data.get("description", addon_summary)
	addon_version = manifest_data.get("version", "0.0.0")
	addon_author  = manifest_data.get("author", "")
	addon_url     = manifest_data.get("url", source_url)
	min_nvda      = manifest_data.get("minimumNVDAVersion", PROJECT_MIN_NVDA)
	last_tested   = manifest_data.get("lastTestedNVDAVersion", PROJECT_LAST_TESTED_NVDA)

	if not addon_name:
		raise AddonBuilderError(
			"[ERRO] generate_store_submission: campo 'name' ausente no manifest.ini"
		)

	def _parse_version(ver_str: str) -> dict:
		"""Converte '2026.1' em {major:2025, minor:3, patch:3}."""
		parts = str(ver_str).replace("-", ".").split(".")
		try:
			major = int(parts[0]) if len(parts) > 0 else 0
			minor = int(parts[1]) if len(parts) > 1 else 0
			patch = int(parts[2]) if len(parts) > 2 else 0
		except (ValueError, IndexError):
			major, minor, patch = 0, 0, 0
		return {"major": major, "minor": minor, "patch": patch}

	version_obj   = _parse_version(addon_version)
	min_nvda_obj  = _parse_version(min_nvda)
	last_nvda_obj = _parse_version(last_tested)

	# addonId: camelCase sem espacos (convencao do store)
	addon_id = re.sub(r"[^a-zA-Z0-9]", "", addon_name)
	if not addon_id:
		addon_id = "meuAddon"

	# publisher: extrai nome antes do <email> se presente
	publisher = addon_author.split("<")[0].strip() or addon_author

	# 4. Monta metadados conforme esquema oficial addon-datastore
	metadata = {
		"addonId":             addon_id,
		"channel":             channel,
		"addonVersionNumber":  version_obj,
		"displayName":         addon_summary,
		"publisher":           publisher,
		"description":         addon_desc,
		"homepage":            addon_url or source_url,
		"minNVDAVersion":      min_nvda_obj,
		"lastTestedVersion":   last_nvda_obj,
		"URL":                 download_url or f"https://github.com/{addon_id}/releases/download/v{addon_version}/{addon_id}.nvda-addon",
		"sha256":              sha256,
		"sourceURL":           source_url or addon_url or "",
		"license":             license_name,
		"licenseURL":          "",
	}

	# 5. Salva JSON ao lado do .nvda-addon
	json_path = nvda_addon_path.replace(".nvda-addon", "_store_submission.json")
	try:
		with open(json_path, "w", encoding="utf-8") as json_fh:
			json.dump(metadata, json_fh, indent=2, ensure_ascii=False)
		_logger.info("[OK] Store submission JSON salvo: %s", json_path)
	except Exception as exc:
		raise AddonBuilderError(
			f"[ERRO] generate_store_submission: falha ao salvar JSON: {exc}"
		)

	log_decision(_logger, "store_submission_gerado",
				 f"addon={addon_id} version={addon_version} sha256={sha256[:16]}")

	return {
		"json_path": json_path,
		"sha256":    sha256,
		"metadata":  metadata,
	}
