import ast
import io
import configparser
import hashlib
import json
import os
import re
import tokenize
import shutil
import struct
import sys
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser

from .hidden_process import CREATE_NO_WINDOW
from .logger import get_logger, log_decision
from .project_policy import (
	ENTRY_POINT_DIRS,
	PROJECT_MIN_NVDA,
	PROJECT_LAST_TESTED_NVDA,
	parse_version_tuple,
)

MODULE_VERSION = "4.29.0"

# NVDA 2026.1+ is built with CPython 3.13 for 64-bit Windows.  Dependency
# wheels must target that runtime, not the Python interpreter that runs
# this server.
_NVDA_PYTHON_VERSION = "313"
_NVDA_WHEEL_PLATFORM = "win_amd64"
_NVDA_WHEEL_ABI = "cp313"


_logger = get_logger("addon_builder")

# Regex para nomes pip validos (PEP 508 basico — sem extras, URLs, paths ou versao).
# Aceita: "requests", "openai-whisper", "Pillow", "my.package", "pkg_2"
# Rejeita: "../evil", "http://...", "pkg[extra]", "pkg; sys_platform=='win32'"
_SAFE_PKG_NAME: re.Pattern = re.compile(
	r'^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$'
)


# Gestures de teclado que o NVDA 2026.3.1 ja usa em globalCommands.py (layouts desktop e
# laptop), sem o prefixo "kb:", em minusculas e com os modificadores em ordem alfabetica
# (ver _normalize_gesture). Addons nao devem redefinir esses atalhos.
# Usado por _check_reserved_gestures() / NVDA-009.
_NVDA_CORE_GESTURES: frozenset = frozenset({
	"alt+control+nvda+t", "alt+nvda+downarrow", "alt+nvda+end", "alt+nvda+home", "alt+nvda+j", "alt+nvda+k",
	"alt+nvda+l", "alt+nvda+leftarrow", "alt+nvda+m", "alt+nvda+r", "alt+nvda+rightarrow", "alt+nvda+s",
	"alt+nvda+shift+downarrow", "alt+nvda+shift+leftarrow", "alt+nvda+shift+rightarrow",
	"alt+nvda+shift+uparrow", "alt+nvda+t", "alt+nvda+tab", "alt+nvda+uparrow", "control+nvda+.",
	"control+nvda+[", "control+nvda+]", "control+nvda+a", "control+nvda+b", "control+nvda+c", "control+nvda+d",
	"control+nvda+downarrow", "control+nvda+end", "control+nvda+escape", "control+nvda+f1", "control+nvda+f2",
	"control+nvda+f3", "control+nvda+g", "control+nvda+home", "control+nvda+k", "control+nvda+leftarrow",
	"control+nvda+m", "control+nvda+o", "control+nvda+p", "control+nvda+pagedown", "control+nvda+pageup",
	"control+nvda+r", "control+nvda+rightarrow", "control+nvda+s", "control+nvda+shift+.",
	"control+nvda+shift+downarrow", "control+nvda+shift+f1", "control+nvda+shift+leftarrow",
	"control+nvda+shift+pagedown", "control+nvda+shift+pageup", "control+nvda+shift+rightarrow",
	"control+nvda+shift+uparrow", "control+nvda+space", "control+nvda+t", "control+nvda+u",
	"control+nvda+uparrow", "control+nvda+v", "control+nvda+w", "control+nvda+x", "control+nvda+z", "numpad1",
	"numpad2", "numpad3", "numpad4", "numpad5", "numpad6", "numpad7", "numpad8", "numpad9", "numpaddivide",
	"numpadmultiply", "numpadplus", "nvda+.", "nvda+1", "nvda+2", "nvda+3", "nvda+4", "nvda+5", "nvda+6",
	"nvda+7", "nvda+[", "nvda+]", "nvda+a", "nvda+b", "nvda+backspace", "nvda+c", "nvda+d", "nvda+delete",
	"nvda+downarrow", "nvda+end", "nvda+enter", "nvda+f", "nvda+f1", "nvda+f10", "nvda+f12", "nvda+f2",
	"nvda+f9", "nvda+home", "nvda+k", "nvda+l", "nvda+leftarrow", "nvda+m", "nvda+n", "nvda+numpad1",
	"nvda+numpad2", "nvda+numpad3", "nvda+numpad4", "nvda+numpad5", "nvda+numpad6", "nvda+numpad7",
	"nvda+numpad8", "nvda+numpad9", "nvda+numpaddelete", "nvda+numpaddivide", "nvda+numpadenter",
	"nvda+numpadminus", "nvda+numpadmultiply", "nvda+p", "nvda+pagedown", "nvda+pageup", "nvda+q", "nvda+r",
	"nvda+rightarrow", "nvda+s", "nvda+shift+-", "nvda+shift+.", "nvda+shift+=", "nvda+shift+[", "nvda+shift+]",
	"nvda+shift+a", "nvda+shift+b", "nvda+shift+backspace", "nvda+shift+d", "nvda+shift+delete",
	"nvda+shift+downarrow", "nvda+shift+end", "nvda+shift+f", "nvda+shift+f9", "nvda+shift+i", "nvda+shift+l",
	"nvda+shift+leftarrow", "nvda+shift+m", "nvda+shift+n", "nvda+shift+numpaddelete", "nvda+shift+numpadminus",
	"nvda+shift+o", "nvda+shift+pagedown", "nvda+shift+pageup", "nvda+shift+rightarrow", "nvda+shift+s",
	"nvda+shift+uparrow", "nvda+shift+w", "nvda+shift+z", "nvda+space", "nvda+t", "nvda+tab", "nvda+u",
	"nvda+uparrow", "nvda+x", "shift+numpad1", "shift+numpad2", "shift+numpad3", "shift+numpad7",
	"shift+numpad9", "shift+numpaddivide", "shift+numpadmultiply",
})


def _normalize_gesture(gesture: str) -> str:
	"""kb(laptop):NVDA+Shift+S -> shift+nvda+s ordenado: modificadores em ordem alfabetica."""
	g = re.sub(r"^kb(\((?:desktop|laptop)\))?:", "", gesture.lower())
	tokens = g.split("+")
	return "+".join(sorted(tokens[:-1]) + [tokens[-1]])


def _package_exists_on_pypi(pkg: str) -> bool:
	"""
	Verifica se um pacote existe no PyPI via HEAD request.

	Retorna True se o pacote existe (HTTP 200) ou se nao foi possivel verificar
	(timeout, sem rede, erro de servidor) — fail-open para nao bloquear instalaÃ§ao.
	Retorna False apenas para HTTP 404 — pacote definitivamente nao existe.

	nao executa codigo — apenas consulta API REST.
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
	except (TimeoutError, OSError) as exc:
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

	"""
	# Remove especificadores de versao simples: pkg==1.0, pkg>=2.0, pkg~=1.2
	base = re.split(r'[=<>!~@]', pkg)[0].strip()
	return bool(_SAFE_PKG_NAME.match(base))












_FUNCOES_GETTEXT = frozenset({"_", "ngettext", "pgettext", "npgettext"})


def chama_gettext(code: str) -> bool:
	"""
	O modulo CHAMA uma funcao de traducao? Via AST, nao por texto.

	Uma varredura textual acusa `_()` escrito dentro de docstring, comentario
	positivos em 3 acusacoes: todas mencoes em texto, nenhuma chamada.

	Erro de sintaxe devolve False: quem reporta isso e a validacao de sintaxe,
	e um NVDA-003 em cima de um arquivo que nem compila so confunde o
	diagnostico.
	"""
	try:
		arvore = ast.parse(code)
	except SyntaxError:
		return False
	for no in ast.walk(arvore):
		if (
			isinstance(no, ast.Call)
			and isinstance(no.func, ast.Name)
			and no.func.id in _FUNCOES_GETTEXT
		):
			return True
	return False


class AddonBuilderError(Exception):
	"""Erro na geracao ou empacotamento do addon."""
	pass

# Campos que nunca devem aparecer no manifest.ini do addon gerado.
# sha256: calculado pelo empacotador, nunca declarado manualmente.
# configSpec: responsabilidade do codigo Python do addon, nao do manifest.
_FORBIDDEN_MANIFEST_FIELDS = frozenset({"sha256", "configspec"})
_MANIFEST_SCALAR_FIELDS = frozenset({
	"name", "summary", "description", "author", "version", "changelog",
	"minimumnvdaversion", "lasttestednvdaversion", "url", "docfilename",
})


def _manifest_scalar_errors(code: str) -> list[str]:
	"""Detecta valores que o ConfigObj do NVDA converteria em lista.

	Um parser simplificado aceitaria uma
	descricao com virgulas. O ConfigObj, usado de verdade pelo NVDA, transforma
	esse valor nao delimitado em ``list`` e a validacao ``string()`` rejeita o
	manifesto. Esta checagem reproduz exatamente esse limite sem exigir que a
	biblioteca interna do NVDA esteja instalada no ambiente de desenvolvimento.
	"""
	errors: list[str] = []
	for line_number, line in enumerate(code.splitlines(), start=1):
		if not line or line[0].isspace() or line.lstrip().startswith(("#", "[")):
			continue
		match = re.match(r"^(\w+)\s*=\s*(.*)$", line)
		if not match or match.group(1).casefold() not in _MANIFEST_SCALAR_FIELDS:
			continue
		value = match.group(2).strip()
		quoted = (
			len(value) >= 2
			and value[0] in {'"', "'"}
			and value[-1] == value[0]
		)
		if "," in value and not quoted:
			errors.append(
				f"MANIFEST-001: Campo '{match.group(1)}' na linha {line_number} "
				"contem virgula sem aspas e seria interpretado como lista pelo NVDA."
			)
	return errors


def _sanitize_manifest(code: str) -> str:
	"""

	ConfigObj (usado pelo NVDA para parsear manifest.ini) interpreta qualquer
	valor de campo que contenha uma quebra de linha como lista Python, causando
	VdtTypeError fatal na instalacao do addon.

	Esta funcao garante que todos os campos de texto do manifest fiquem em

	Algorithm:
	  1. Remove campos proibidos (sha256, configSpec) — determinisitco, antes do parse.
	  2. Junta campos de texto multiline em uma unica linha.

	Campos protegidos: summary, description, changelog (e qualquer campo de texto).
	Nao afeta campos de versao, url, name, docFileName.

	sanitizacao deterministica, nao semantica. Nao executa codigo.
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
		if current_key.casefold() in _TEXT_FIELDS and current_val_parts:
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


def _is_development_artifact(relative_path: str) -> bool:
	"""Retorna True para arquivos de desenvolvimento que nao integram o addon."""
	normalized = relative_path.replace("\\", "/").lstrip("/")
	parts = normalized.split("/")
	basename = parts[-1].casefold()
	development_dirs = {"tests", "test", ".pytest_cache", "__pycache__"}
	return (
		any(part.casefold() in development_dirs for part in parts[:-1])
		or basename == "conftest.py"
		or (basename.startswith("test_") and basename.endswith(".py"))
		or basename.endswith("_test.py")
		or basename in {"pytest.ini", "tox.ini", ".coverage", "coverage.xml"}
	)


# ------------------------------------------------------------------
# Helpers publicos para nome do addon
# ------------------------------------------------------------------



# ------------------------------------------------------------------
# Extracao de codigo
# ------------------------------------------------------------------








# ------------------------------------------------------------------
# Validacao de estrutura
# ------------------------------------------------------------------

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
	"globalPlugins",    # diretorio de plugins — nao e pacote pip
	"appModules",       # diretorio de app modules — nao e pacote pip
	"synthDrivers",     # diretorio de synth drivers — nao e pacote pip
	"brailleDisplayDrivers",  # diretorio de braille drivers — nao e pacote pip
	"installTasks",     # modulo raiz do addon — nao e pacote pip
	"nvdaBuiltin",      # modulo builtin do NVDA — nao e pacote pip
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


def _validate_html_block(code: str) -> bool:
	"""
	Verifica se o codigo e HTML valido com estrutura minima (fluxos 8.2 R:b).
	Usa html.parser (stdlib) para detectar erros de parse.
	Retorna True se o conteudo parece HTML valido com ao menos uma tag estrutural.
	Retorna False se invalido ou vazio de marcacao estrutural.
	Nao executa o HTML — apenas analise textual .
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






def write_addon_file(addon_folder: str, dest_rel: str, code: str) -> str | None:
	"""Grava UM arquivo dentro de addon_folder, com as protecoes do NVDAStudio.

	- impede path traversal (o destino tem de ficar dentro de addon_folder);
	- sanitiza manifest.ini (valores multilinha quebram o configobj do NVDA);
	- embrulha HTML sem estrutura minima;
	- grava .py e .ini em UTF-8 com LF.

	Retorna o caminho absoluto gravado, ou None se o destino foi bloqueado.
	"""
	# startswith() sozinho tem o furo classico (CWE-22): '...\MyAddonExtra\x.py'
	# comeca com '...\MyAddon'. Compara contra a pasta + separador.
	addon_folder_norm = os.path.normpath(addon_folder)
	dest_abs = os.path.normpath(os.path.join(addon_folder, dest_rel))
	if dest_abs != addon_folder_norm and not dest_abs.startswith(addon_folder_norm + os.sep):
		_logger.warning("[AVISO] Path traversal bloqueado: %s", dest_rel)
		return None

	os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
	# manifest com valores multiline causa VdtTypeError no NVDA
	if dest_abs.lower().endswith("manifest.ini"):
		code = _sanitize_manifest(code)
	if dest_abs.lower().endswith(".html") and not _validate_html_block(code):
		if not re.search(r'<html', code, re.IGNORECASE):
			_logger.warning("[AVISO] userGuide HTML sem estrutura minima — adicionando wrapper.")
			code = (
				'<!DOCTYPE html>\n<html lang="pt">\n'
				'<head><meta charset="utf-8"><title>User Guide</title></head>\n'
				f'<body>\n{code}\n</body>\n</html>'
			)
	open_kwargs: dict = {"encoding": "utf-8"}
	if dest_abs.lower().endswith((".py", ".ini")):
		code = code.replace("\r\n", "\n").replace("\r", "\n")
		open_kwargs["newline"] = "\n"
	with open(dest_abs, "w", **open_kwargs) as f:
		f.write(code)
	log_decision(_logger, "arquivo_salvo", dest_abs)
	return dest_abs




def _collect_local_module_roots(addon_folder: str, addon_name: str) -> frozenset:
	"""
	Coleta os nomes (sem .py) de todos os arquivos Python presentes em QUALQUER
	subpasta de globalPlugins/ do addon gerado.

	Escaneia todos os subdirs (nao so o do addon_name) para cobrir o caso em que
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
	  pip install --target=<plugin_dir>/lib/ --no-compile --quiet

	Garante que o addon funcione sem que o usuario instale nada.
	O __init__.py gerado deve adicionar lib/ ao sys.path (igual ao NVDAStudio).

	Args:
		addon_folder: pasta raiz do addon (contem manifest.ini e globalPlugins/)
		packages: lista de nomes pip ex ["openai-whisper", "Pillow"]
		addon_name: nome do addon para localizar a pasta globalPlugins/<addon_name>/
		on_package_progress: callback opcional(pkg: str, status: str) chamado para
			cada pacote com status "iniciando", "ok" ou "falha".
		_pypi_checker: callable(pkg) -> bool opcional para injecao em testes.
			Default: _package_exists_on_pypi. Permite testes sem rede.

	Returns:
		Lista de pacotes instalados com sucesso.
	"""
	if not packages:
		return []

	# Coleta modulos locais do addon — nao devem ser instalados via pip (v2.0.0)
	local_roots = _collect_local_module_roots(addon_folder, addon_name)

	safe_packages: list[str] = []
	for pkg in packages:
		if not _is_safe_package_name(pkg):
			_logger.warning(
				"[AVISO] Nome de pacote rejeitado (invalido/inseguro): %r. "
				"Apenas nomes PEP 508 basicos sao aceitos.", pkg
			)
			if on_package_progress:
				on_package_progress(pkg, "ignored", "nome invalido ou inseguro: so nomes simples de pacote sao aceitos")
			continue
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
			if on_package_progress:
				on_package_progress(pkg, "ignored", "modulo do NVDA, da biblioteca padrao ou do proprio addon: nao precisa de pip")
			continue
		if pkg_install != pkg:
			_logger.info(
				"[BUNDLE] Nome de pacote normalizado: '%s' -> '%s' "
				"(submodule path removido).", pkg, pkg_install
			)
		safe_packages.append(pkg_install)
	if not safe_packages:
		return []

	# Verificacao PyPI antes do pip install (v3.8.0).
	# Pacote inexistente no PyPI (nome errado ou inventado) e descartado e
	# reportado ao chamador via on_package_progress.
	# _pypi_checker injetavel para testes sem rede (default: _package_exists_on_pypi).
	_checker = _pypi_checker if _pypi_checker is not None else _package_exists_on_pypi
	verified_packages: list[str] = []
	for pkg in safe_packages:
		if _checker(pkg):
			verified_packages.append(pkg)
		else:
			_logger.warning(
				"[BUNDLE] Pacote '%s' nao encontrado no PyPI — ignorado.", pkg
			)
			if on_package_progress:
				on_package_progress(pkg, "falha", f"nao encontrado no PyPI: {pkg}")
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
				cmd_nvda_runtime, capture_output=True, text=True, timeout=120,
				creationflags=CREATE_NO_WINDOW,  # pip abre console no Windows
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

	# Ultima fronteira antes da distribuicao: fluxos baseados em artifact_dir
	# nao passam por save_addon_files(), portanto o manifesto precisa ser
	# normalizado aqui tambem. O pacote nunca pode depender de qual caminho da
	# interface foi usado para chegar ao empacotador.
	manifest_path = os.path.join(addon_folder, "manifest.ini")
	if os.path.isfile(manifest_path):
		try:
			with open(manifest_path, encoding="utf-8", errors="replace") as manifest_file:
				manifest_content = manifest_file.read()
			manifest_content = _sanitize_manifest(manifest_content)
			manifest_errors = _manifest_scalar_errors(manifest_content)
			if manifest_errors:
				raise AddonBuilderError("[ERRO] " + " | ".join(manifest_errors))
			with open(manifest_path, "w", encoding="utf-8", newline="\n") as manifest_file:
				manifest_file.write(manifest_content)
		except OSError as exc:
			raise AddonBuilderError(f"[ERRO] Falha ao preparar manifest.ini: {exc}") from exc

	zip_path = output_path or (addon_folder.rstrip("/\\") + ".nvda-addon")

	with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
		ignored_dirs = {
			".git", ".factory", ".droid", ".pytest_cache", "__pycache__", "tests",
			"test",
		}
		for root, dirs, files in os.walk(addon_folder):
			dirs[:] = [directory for directory in dirs if directory not in ignored_dirs]
			for file in files:
				if file.endswith((".pyc", ".nvda-addon", ".zip")):
					continue
				full_path = os.path.join(root, file)
				# Base e addon_folder: arcname fica relativo ao conteudo da pasta,
				# sem incluir o nome da pasta no ZIP.
				# Exemplo: addon_folder/manifest.ini -> manifest.ini (raiz do ZIP)
				# Exemplo: addon_folder/globalPlugins/x/__init__.py -> globalPlugins/x/__init__.py
				arcname = os.path.relpath(full_path, addon_folder).replace("\\", "/")
				if _is_development_artifact(arcname):
					continue
				zf.write(full_path, arcname)

	_logger.info("[OK] Addon empacotado: %s", zip_path)
	return zip_path


# Simbolos removidos, descontinuados ou movidos para winBindings.* (NVDA 2026.1+), conforme
# user_docs/en/changes.md do NVDA (API Breaking Changes e Deprecations). "SM_" e prefixo.
_NVDA_WIN_LEGACY_SYMBOLS: dict[str, frozenset[str]] = {
	"winKernel": frozenset({
		"DUPLICATE_SAME_ACCESS", "GENERIC_READ", "GENERIC_WRITE", "PROCESS_QUERY_INFORMATION",
		"PROCESS_TERMINATE", "PROCESS_ALL_ACCESS", "PROCESS_VM_OPERATION", "PROCESS_VM_READ",
		"PROCESS_VM_WRITE", "PROCESS_INFORMATION", "STARTUPINFO", "STARTUPINFOW", "advapi32",
		"kernel32", "FILETIME", "SYSTEMTIME", "TIME_ZONE_INFORMATION",
	}),
	"winUser": frozenset({
		"GUITHREADINFO", "HWINEVENTHOOK", "WINEVENTPROC", "WNDCLASSEXW", "WNDPROC", "PAINTSTRUCT",
		"user32", "HardwareInput", "Input", "KeyBdInput", "MouseInput", "NMHdrStruct", "INPUT_MOUSE",
		"INPUT_KEYBOARD", "KEYEVENTF_KEYUP", "KEYEVENTF_UNICODE", "Input_I", "PUL",
	}),
	"winGDI": frozenset({"user32", "GdiplusStartupInput", "GdiplusStartupOutput"}),
	"wincon": frozenset({
		"COORD", "CONSOLE_SCREEN_BUFFER_INFO", "CONSOLE_SELECTION_INFO", "CHAR_INFO", "PHANDLER_ROUTINE",
	}),
}


def _is_legacy_win_symbol(module: str, symbol: str) -> bool:
	if module == "winUser" and symbol.startswith("SM_"):
		return True
	return symbol in _NVDA_WIN_LEGACY_SYMBOLS.get(module, frozenset())


def _plugin_dirs(addon_folder: str) -> list[str]:
	"""Pastas com codigo de ponto de entrada do addon, para as checagens por arquivo.

	globalPlugins/: cada pasta de plugin (e subpacotes). Demais pontos de entrada
	(appModules/, synthDrivers/, ...): a propria pasta (arquivos soltos) e subpacotes.
	Dependencias bundladas (lib/) e caches ficam de fora.
	"""
	found: list[str] = []
	for area in ENTRY_POINT_DIRS:
		area_dir = os.path.join(addon_folder, area)
		if not os.path.isdir(area_dir):
			continue
		for root, dirs, _files in os.walk(area_dir):
			dirs[:] = sorted(d for d in dirs if d not in ("lib", "__pycache__"))
			if root != area_dir or area != "globalPlugins":
				found.append(root)
	return found


# ------------------------------------------------------------------
# Validadores determinÃ­sticos auxiliares — E14..E19
# Cada funcao recebe o caminho da pasta do addon e retorna list[str]
# de problemas no formato "CODIGO: descricao".
# Chamadas por validate_addon_structure() antes do retorno final.
# nenhuma funcao executa o codigo do addon.
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

	for pdir_path in _plugin_dirs(addon_folder):
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

	for pdir_path in _plugin_dirs(addon_folder):
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

	# Regex que captura qualquer string entre aspas contendo "kb:nvda+"
	_gesture_re = re.compile(r'["\'](kb(?:\((?:desktop|laptop)\))?:[^"\']+)["\']', re.IGNORECASE)

	for pdir_path in _plugin_dirs(addon_folder):
		for py_file in os.listdir(pdir_path):
			if not py_file.endswith(".py"):
				continue
			full_path = os.path.join(pdir_path, py_file)
			try:
				with open(full_path, encoding="utf-8", errors="replace") as fh:
					src = fh.read()
			except OSError:
				continue
			for match in _gesture_re.finditer(src):
				gesture = match.group(1).lower()
				if _normalize_gesture(gesture) in _NVDA_CORE_GESTURES:
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

	for pdir_path in _plugin_dirs(addon_folder):
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

	# Heuristica para detectar inicio de docstring multiline (nao perfeita, mas adequada)
	_docstring_re = re.compile(r'^\s*("""|\'\'\').*$')

	for pdir_path in _plugin_dirs(addon_folder):
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


def _linhas_cobertas_por_string(src: str) -> set[int]:
	"""Numeros de linha (1-based) que caem dentro de um token STRING.

	Fail-open: em erro de sintaxe devolve conjunto vazio. Um arquivo que nao
	tokeniza ja e reportado por outro degrau, melhor que por este -- nao cabe
	a esta funcao converter erro de sintaxe em falso NVDA-021.
	"""
	try:
		toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
	except (tokenize.TokenError, SyntaxError, IndentationError):
		return set()
	cobertas: set[int] = set()
	for tok in toks:
		if tok.type == tokenize.STRING:
			cobertas.update(range(tok.start[0], tok.end[0] + 1))
	return cobertas


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

	for pdir_path in _plugin_dirs(addon_folder):
		for py_file in os.listdir(pdir_path):
			if not py_file.endswith(".py"):
				continue
			full_path = os.path.join(pdir_path, py_file)
			try:
				with open(full_path, encoding="utf-8", errors="replace") as fh:
					lines = fh.readlines()
			except OSError:
				continue
			# 4.20.0 -- linhas cobertas por STRING nao sao indentacao.
			#
			# A checagem era puramente textual e acusava prosa dentro de docstring
			# que e texto dentro do docstring de CONTRATO. As 21 linhas com espaco
			# do arquivo estavam TODAS dentro de strings; a indentacao de codigo era
			# 100% TAB e o arquivo compilava. Portao reprovando codigo correto e a
			# classe de defeito mais cara deste projeto.
			#
			# Mesma consciencia de strings que normalizar_indentacao() ja usa para
			# CONVERTER -- so que aqui para ACUSAR: os dois lados do mesmo contrato
			# precisam concordar sobre o que e indentacao.
			linhas_em_string = _linhas_cobertas_por_string("".join(lines))
			for i, line in enumerate(lines):
				# Detecta linha que comeca com 4 ou mais espacos (nao TAB)
				# e nao e uma linha em branco ou comentario de nivel 0
				if line.startswith("    ") and not line.startswith("\t"):
					if (i + 1) in linhas_em_string:
						continue
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

	for pdir_path in _plugin_dirs(addon_folder):
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

	for pdir_path in _plugin_dirs(addon_folder):
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

	def _tree(source: str) -> ast.Module | None:
		try:
			return ast.parse(source)
		except SyntaxError:
			return None

	def _call_name(node: ast.Call) -> str:
		func = node.func
		if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
			return f"{func.value.id}.{func.attr}"
		if isinstance(func, ast.Attribute):
			return func.attr
		return func.id if isinstance(func, ast.Name) else ""

	# NVDA-002: apenas chamadas reais em módulo que participa da UI do NVDA.
	for rel, code in all_py:
		tree = _tree(code)
		calls = [_call_name(node) for node in ast.walk(tree) if isinstance(node, ast.Call)] if tree else []
		ui_module = "globalPluginHandler" in code or "appModuleHandler" in code
		if ui_module and "time.sleep" in calls and "threading" not in code:
			problems.append(f"NVDA-002: {rel}: time.sleep() bloqueia thread principal. Use threading.Thread + wx.CallAfter.")
		if ui_module and any(call in {"requests.get", "requests.post", "requests.put", "requests.delete"} for call in calls) and "threading" not in code:
			problems.append(f"NVDA-002: {rel}: HTTP sincrono bloqueia thread principal. Use threading.Thread.")

	# NVDA-005: Formato de versao
	version = manifest_fields.get("version", "")
	if version and not re.match(r"^\d+\.\d+(\.\d+)?$", version):
		problems.append(
			f"NVDA-005: manifest.ini: version='{version}' formato invalido. "
			f"A Add-on Store aceita major.minor ou major.minor.patch."
		)

	# NVDA-006: Monkey-patching
	for rel, code in all_py:
		tree = _tree(code)
		if tree is None or "extensionPoints" in code:
			continue
		imported_modules = {
			alias.asname or alias.name.split(".")[0]
			for node in tree.body if isinstance(node, ast.Import)
			for alias in node.names
		}
		patches = [
			node for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
			and isinstance(node.value, ast.Lambda)
		]
		for patch_node in patches:
			targets = patch_node.targets if isinstance(patch_node, ast.Assign) else [patch_node.target]
			if any(
				isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
				and target.value.id in imported_modules
				and not (target.value.id == "builtins" and target.attr == "_")
				for target in targets
			):
				problems.append(f"NVDA-006: {rel}: possivel monkey-patching. Use extension points.")
				break

	# NVDA-010: UI update sem wx.CallAfter
	for rel, code in all_py:
		tree = _tree(code)
		calls = [_call_name(node) for node in ast.walk(tree) if isinstance(node, ast.Call)] if tree else []
		if "threading.Thread" in calls:
			if "ui.message" in calls and "wx.CallAfter" not in calls:
				problems.append(f"NVDA-010: {rel}: ui.message() em thread sem wx.CallAfter().")
			if "SetLabel" in calls and "wx.CallAfter" not in calls:
				problems.append(f"NVDA-010: {rel}: .SetLabel() em thread sem wx.CallAfter().")

	# NVDA-011: Driver sem check()
	for rel, code in all_py:
		tree = _tree(code)
		for class_node in ast.walk(tree) if tree else []:
			if not isinstance(class_node, ast.ClassDef):
				continue
			bases = {
				base.id if isinstance(base, ast.Name) else base.attr
				for base in class_node.bases if isinstance(base, (ast.Name, ast.Attribute))
			}
			if bases.intersection({"SynthDriver", "BrailleDisplayDriver"}) and not any(
				isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "check"
				for item in class_node.body
			):
				problems.append(f"NVDA-011: {rel}: Driver sem metodo check().")
				break

	# NVDA-012: except: bare
	for rel, code in all_py:
		tree = _tree(code)
		if tree and any(isinstance(node, ast.ExceptHandler) and node.type is None for node in ast.walk(tree)):
			problems.append(f"NVDA-012: {rel}: except: bare. Especifique a excecao.")

	# NVDA-013: API version range
	min_nvda = manifest_fields.get("minimumNVDAVersion", "")
	if min_nvda and parse_version_tuple(min_nvda) < (2019, 3, 0):
		problems.append(f"NVDA-013: manifest.ini: minimumNVDAVersion={min_nvda} abaixo do minimo.")
	last_nvda = manifest_fields.get("lastTestedNVDAVersion", "")
	if min_nvda and last_nvda and parse_version_tuple(min_nvda) > parse_version_tuple(last_nvda):
		problems.append(
			f"NVDA-013: manifest.ini: minimumNVDAVersion={min_nvda} maior que "
			f"lastTestedNVDAVersion={last_nvda}; o minimo tem de ser menor ou igual ao ultimo testado."
		)

	# NVDA-015: config.conf.spec ausente
	#
	# TINHAM configSpec.py. A checagem era por ARQUIVO, entao um addon bem
	# arquitetado -- spec num modulo proprio, consumo espalhado em
	# settings_panel.py, client.py, qa/service.py -- levava um aviso por
	# arquivo mandando 'Crie configSpec.py', arquivo que ja existia ao lado.
	#
	# addon MULTI-ARQUIVO (14 disparos em multi-arquivo, 0 em arquivo unico)
	# -- ou seja, punia exatamente a classe de addon que o projeto ja tem
	# mais dificuldade de fazer convergir.
	#
	# A spec e do ADDON, nao do arquivo: basta existir em UM lugar. A
	# verificacao passa a olhar o conjunto antes de reportar qualquer arquivo.
	_tem_config_spec = any(
		"config.conf.spec" in code or "configSpec" in code
		or os.path.basename(rel).lower() == "configspec.py"
		for rel, code in all_py
	)
	if not _tem_config_spec:
		for rel, code in all_py:
			if "config.conf[" in code:
				problems.append(f"NVDA-015: {rel}: usa config.conf sem config.conf.spec. Crie configSpec.py.")

	# NVDA-016: shouldWriteToDisk ausente
	for rel, code in all_py:
		tree = _tree(code)
		write_calls: list[ast.Call] = []
		for call_node in ast.walk(tree) if tree else []:
			if not isinstance(call_node, ast.Call) or _call_name(call_node) != "open":
				continue
			mode_node = call_node.args[1] if len(call_node.args) > 1 else next(
				(keyword.value for keyword in call_node.keywords if keyword.arg == "mode"), None,
			)
			if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str) and any(
				flag in mode_node.value for flag in ("w", "a", "x", "+")
			):
				write_calls.append(call_node)
		# Escritas em diretório temporário/workspace de build e escritas já
		# submetidas ao callback humano não são persistência de configuração.
		guarded_or_ephemeral = any(
			marker in code for marker in (
				"shouldWriteToDisk", "tempfile", "workdir", "permission_callback",
			)
		)
		if write_calls and not guarded_or_ephemeral:
			problems.append(f"NVDA-016: {rel}: escrita em disco sem shouldWriteToDisk().")

	# NVDA-018: minimumNVDAVersion < 2019.3
	if min_nvda and parse_version_tuple(min_nvda) < (2019, 3, 0):
		problems.append(f"NVDA-018: manifest.ini: minimumNVDAVersion={min_nvda} < 2019.3.0.")

	# NVDA-020: Import re-export
	for rel, code in all_py:
		tree = _tree(code)
		if tree and any(
			isinstance(node, ast.ImportFrom) and node.module == "NVDAObjects"
			and any(alias.name == "IAccessible" for alias in node.names)
			for node in ast.walk(tree)
		):
			problems.append(f"NVDA-020: {rel}: from NVDAObjects import IAccessible. Use from NVDAObjects.IAccessible import IAccessible.")

	# NVDA-028 não é um erro de compatibilidade: Optional/Union continuam
	# suportados no Python do NVDA. Modernização de estilo pertence ao lint e
	# não pode invalidar um pacote funcional.

	# NVDA-029: CRLF
	for rel, code in all_py:
		if "\r\n" in code:
			problems.append(f"NVDA-029: {rel}: line endings CRLF. Use LF (\\n).")

	# NVDA-030: __init__ sem super().__init__(*args, **kwargs)
	for rel, code in all_py:
		tree = _tree(code)
		for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)) if tree else []:
			if cls.name not in {"GlobalPlugin", "AppModule"}:
				continue
			initializer = next((node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"), None)
			if initializer and not any(
				isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
				and node.func.attr == "__init__" and isinstance(node.func.value, ast.Call)
				and isinstance(node.func.value.func, ast.Name) and node.func.value.func.id == "super"
				for node in ast.walk(initializer)
			):
				problems.append(f"NVDA-030: {rel}: __init__ sem super().__init__(*args, **kwargs).")
				break

	# NVDA-031: SynthDriver sem cancel()
	for rel, code in all_py:
		tree = _tree(code)
		for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)) if tree else []:
			bases = {base.id if isinstance(base, ast.Name) else base.attr for base in cls.bases if isinstance(base, (ast.Name, ast.Attribute))}
			if "SynthDriver" in bases and not any(isinstance(node, ast.FunctionDef) and node.name == "cancel" for node in cls.body):
				problems.append(f"NVDA-031: {rel}: SynthDriver sem cancel().")
				break

	# NVDA-032: Extension point sem unregister
	for rel, code in all_py:
		if ".register(" in code and ("extensionPoints" in code or "filter_speechSequence" in code):
			if ".unregister(" not in code:
				problems.append(f"NVDA-032: {rel}: .register() sem .unregister() em terminate().")

	# NVDA-033: event_NVDAObject_init em GlobalPlugin
	for rel, code in all_py:
		tree = _tree(code)
		if tree and any(
			isinstance(cls, ast.ClassDef) and cls.name == "GlobalPlugin"
			and any(isinstance(node, ast.FunctionDef) and node.name == "event_NVDAObject_init" for node in cls.body)
			for cls in ast.walk(tree)
		):
			problems.append(f"NVDA-033: {rel}: event_NVDAObject_init em GlobalPlugin. So funciona em AppModule.")

	# NVDA-034: AppModule self-voicing sem sleepMode
	for rel, code in all_py:
		if "class AppModule" in code and ("self.voicing" in code.lower() or "selfVoicing" in code):
			if "sleepMode" not in code:
				problems.append(f"NVDA-034: {rel}: AppModule self-voicing sem sleepMode = True.")

	# NVDA-035: SynthDriver sem pause()
	for rel, code in all_py:
		tree = _tree(code)
		for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)) if tree else []:
			bases = {base.id if isinstance(base, ast.Name) else base.attr for base in cls.bases if isinstance(base, (ast.Name, ast.Attribute))}
			if "SynthDriver" in bases and not any(isinstance(node, ast.FunctionDef) and node.name == "pause" for node in cls.body):
				problems.append(f"NVDA-035: {rel}: SynthDriver sem pause().")
				break

	# NVDA-036: SynthDriver sem speak()
	for rel, code in all_py:
		tree = _tree(code)
		for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)) if tree else []:
			bases = {base.id if isinstance(base, ast.Name) else base.attr for base in cls.bases if isinstance(base, (ast.Name, ast.Attribute))}
			if "SynthDriver" in bases and not any(isinstance(node, ast.FunctionDef) and node.name == "speak" for node in cls.body):
				problems.append(f"NVDA-036: {rel}: SynthDriver sem speak().")
				break

	# NVDA-037: BrailleDisplayDriver sem campos obrigatorios
	for rel, code in all_py:
		tree = _tree(code)
		for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)) if tree else []:
			bases = {base.id if isinstance(base, ast.Name) else base.attr for base in cls.bases if isinstance(base, (ast.Name, ast.Attribute))}
			if "BrailleDisplayDriver" not in bases:
				continue
			missing = []
			attributes = {target.id for node in cls.body if isinstance(node, (ast.Assign, ast.AnnAssign)) for target in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(target, ast.Name)}
			methods = {node.name for node in cls.body if isinstance(node, ast.FunctionDef)}
			if "numCols" not in attributes:
				missing.append("numCols")
			if "display" not in methods:
				missing.append("display()")
			if "isThreadSafe" not in attributes:
				missing.append("isThreadSafe")
			if missing:
				problems.append(f"NVDA-037: {rel}: BrailleDisplayDriver sem: {', '.join(missing)}.")
			break

	# NVDA-038: SynthDriver sem supportedNotifications
	for rel, code in all_py:
		tree = _tree(code)
		for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)) if tree else []:
			bases = {base.id if isinstance(base, ast.Name) else base.attr for base in cls.bases if isinstance(base, (ast.Name, ast.Attribute))}
			attributes = {target.id for node in cls.body if isinstance(node, (ast.Assign, ast.AnnAssign)) for target in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(target, ast.Name)}
			if "SynthDriver" in bases and "supportedNotifications" not in attributes:
				problems.append(f"NVDA-038: {rel}: SynthDriver sem supportedNotifications.")
				break

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

	# (test_e36, GeminiMultimodal): esta checagem so procurava "wx.MessageDialog"
	# -- codigo gerado usando "wx.MessageBox" (mesma violacao de acessibilidade,
	# API wx diferente) passava batido aqui, e a unica linha de defesa virava
	# convergir.
	for rel, code in all_py:
		tree = _tree(code)
		calls = [_call_name(node) for node in ast.walk(tree) if isinstance(node, ast.Call)] if tree else []
		if "wx.MessageDialog" in calls:
			problems.append(f"NVDA-049: {rel}: wx.MessageDialog proibido. Use gui.message.MessageDialog.")
		if "wx.MessageBox" in calls:
			problems.append(f"NVDA-049: {rel}: wx.MessageBox proibido. Use gui.message.MessageDialog.")

	# NVDA-050: NVDAObject overlay herda de base
	for rel, code in all_py:
		tree = _tree(code)
		if tree and any(
			isinstance(cls, ast.ClassDef)
			and any(isinstance(base, ast.Name) and base.id == "NVDAObject" for base in cls.bases)
			for cls in ast.walk(tree)
		):
			problems.append(f"NVDA-050: {rel}: overlay class herda de NVDAObject base. Use IAccessible/UIA/Window/JABObject.")

	# NVDA-052: simbolos de winUser/winKernel/winGDI/wincon removidos, descontinuados ou movidos
	# para winBindings (user_docs/en/changes.md do NVDA: API Breaking Changes e Deprecations).
	# So acusa o simbolo, nunca o modulo inteiro: winUser.getForegroundWindow() e
	# winKernel.LCIDToLocaleName() continuam validos.
	for rel, code in all_py:
		tree = _tree(code)
		if tree is None:
			continue
		for node in ast.walk(tree):
			module = symbol = ""
			if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
				module, symbol = node.value.id, node.attr
			elif isinstance(node, ast.ImportFrom) and node.module in _NVDA_WIN_LEGACY_SYMBOLS:
				for alias in node.names:
					if _is_legacy_win_symbol(node.module, alias.name):
						problems.append(
							f"NVDA-052: {rel}: linha {node.lineno}: {node.module}.{alias.name} foi "
							f"removido, descontinuado ou movido para winBindings (changes.md do NVDA)."
						)
				continue
			if module in _NVDA_WIN_LEGACY_SYMBOLS and _is_legacy_win_symbol(module, symbol):
				problems.append(
					f"NVDA-052: {rel}: linha {getattr(node, 'lineno', 0)}: {module}.{symbol} foi removido, "
					f"descontinuado ou movido para winBindings (changes.md do NVDA)."
				)

	# NVDA-053: SAPI 4/5 32-bit voices
	for rel, code in all_py:
		tree = _tree(code)
		if tree and any(
			isinstance(node, (ast.Assign, ast.AnnAssign))
			and isinstance(node.value, ast.Constant)
			and isinstance(node.value.value, str)
			and node.value.value.lower() == "sapi4"
			for node in ast.walk(tree)
		):
			problems.append(f"NVDA-053: {rel}: uso de sapi4 legado. Use sapi4_32 para vozes de 32 bits (sem suporte a audio ducking).")

	# NVDA-054: typing_extensions removida no NVDA 2026.1
	for rel, code in all_py:
		tree = _tree(code)
		if tree and any(
			(isinstance(node, ast.Import) and any(alias.name == "typing_extensions" for alias in node.names))
			or (isinstance(node, ast.ImportFrom) and node.module == "typing_extensions")
			for node in ast.walk(tree)
		):
			problems.append(f"NVDA-054: {rel}: uso de typing_extensions. Remova e use o suporte nativo do Python 3.13 no NVDA 2026.1+.")

	return problems

class _Assinatura:
	"""Assinatura de uma funcao/metodo do addon, no que interessa a NVDA-063."""

	__slots__ = ("nome", "arquivo", "linha", "posicionais", "kwonly",
				 "obrigatorios", "tem_varargs", "tem_kwargs")

	def __init__(self, nome, arquivo, linha, posicionais, kwonly,
				 obrigatorios, tem_varargs, tem_kwargs):
		self.nome = nome
		self.arquivo = arquivo
		self.linha = linha
		self.posicionais = posicionais
		self.kwonly = kwonly
		self.obrigatorios = obrigatorios
		self.tem_varargs = tem_varargs
		self.tem_kwargs = tem_kwargs

	@classmethod
	def de_funcao(cls, no, arquivo: str, metodo: bool) -> "_Assinatura":
		a = no.args
		posicionais = [arg.arg for arg in (a.posonlyargs + a.args)]
		if metodo and posicionais:
			# self/cls e preenchido pelo proprio Python na chamada ligada --
			# conta-lo faria toda chamada parecer faltar um argumento.
			posicionais = posicionais[1:]
		n_com_default = len(a.defaults)
		if n_com_default:
			obrigatorios = list(posicionais[: len(posicionais) - n_com_default])
		else:
			obrigatorios = list(posicionais)
		kwonly = [arg.arg for arg in a.kwonlyargs]
		# kw_defaults tem SEMPRE o mesmo tamanho de kwonlyargs (None onde
		# nao ha default) -- strict=True documenta e protege a invariante.
		for arg, padrao in zip(a.kwonlyargs, a.kw_defaults, strict=True):
			if padrao is None:
				obrigatorios.append(arg.arg)
		return cls(
			nome=no.name, arquivo=arquivo, linha=no.lineno,
			posicionais=posicionais, kwonly=kwonly, obrigatorios=obrigatorios,
			tem_varargs=a.vararg is not None, tem_kwargs=a.kwarg is not None,
		)

	@property
	def aceitos(self) -> set:
		return set(self.posicionais) | set(self.kwonly)


def _indexar_definicoes_do_addon(pdir_path: str) -> tuple[dict, dict]:
	"""Mapeia o que cada modulo do addon DEFINE.

	Devolve (classes, funcoes):
	  classes[modulo][Classe][metodo] = _Assinatura
	  funcoes[modulo][funcao]         = _Assinatura
	`modulo` e o nome do arquivo sem .py ("__init__" para o ponto de entrada).
	"""
	classes: dict = {}
	funcoes: dict = {}

	for py_file in sorted(os.listdir(pdir_path)):
		if not py_file.endswith(".py"):
			continue
		full_path = os.path.join(pdir_path, py_file)
		try:
			with open(full_path, encoding="utf-8", errors="replace") as fh:
				src = fh.read()
			tree = ast.parse(src, filename=py_file)
		except (OSError, SyntaxError):
			continue
		mod = py_file[: -len(".py")]
		classes.setdefault(mod, {})
		funcoes.setdefault(mod, {})
		for no in tree.body:
			if isinstance(no, ast.ClassDef):
				metodos: dict = {}
				for filho in no.body:
					if isinstance(filho, (ast.FunctionDef, ast.AsyncFunctionDef)):
						# @staticmethod nao tem self/cls implicito -- tratar como
						# "metodo" (que sempre descarta o 1o posicional) reprova
						# uma chamada self.metodo(x) valida em Python so porque
						# ela nao "sobra" um argumento pro parametro que na
						# corrigiu o proprio codigo, correto, pra calar um
						# falso positivo daqui.
						e_estatico = any(
							isinstance(d, ast.Name) and d.id == "staticmethod"
							for d in filho.decorator_list
						)
						metodos[filho.name] = _Assinatura.de_funcao(filho, py_file, metodo=not e_estatico)
				classes[mod][no.name] = metodos
			elif isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
				funcoes[mod][no.name] = _Assinatura.de_funcao(no, py_file, metodo=False)
	return classes, funcoes


def _conferir_chamada(chamada: ast.Call, alvo: _Assinatura, arquivo: str) -> list[str]:
	"""Compara UMA chamada com a definicao que ela realmente atinge."""
	# f(*args) ou f(**kwargs): o conteudo so existe em runtime. Calar e a
	if any(isinstance(a, ast.Starred) for a in chamada.args):
		return []
	if any(kw.arg is None for kw in chamada.keywords):
		return []

	problemas: list[str] = []
	onde = f"{alvo.arquivo}:{alvo.linha}"
	assinatura_txt = ", ".join(alvo.posicionais + alvo.kwonly) or "(nenhum)"

	if not alvo.tem_kwargs:
		for kw in chamada.keywords:
			if kw.arg not in alvo.aceitos:
				problemas.append(
					f"NVDA-063: {arquivo}: linha {chamada.lineno}: chamada a "
					f"{alvo.nome}() passa o argumento '{kw.arg}', que a definicao em "
					f"{onde} nao aceita (parametros: {assinatura_txt}). O chamador e a "
					f"definicao discordam -- alinhe os dois lados."
				)

	if not alvo.tem_varargs and len(chamada.args) > len(alvo.posicionais):
		problemas.append(
			f"NVDA-063: {arquivo}: linha {chamada.lineno}: chamada a {alvo.nome}() passa "
			f"{len(chamada.args)} argumento(s) posicional(is), e a definicao em {onde} "
			f"aceita {len(alvo.posicionais)} (parametros: {assinatura_txt})."
		)

	if not problemas:
		fornecidos = set(alvo.posicionais[: len(chamada.args)])
		fornecidos |= {kw.arg for kw in chamada.keywords}
		faltando = [nome for nome in alvo.obrigatorios if nome not in fornecidos]
		if faltando:
			problemas.append(
				f"NVDA-063: {arquivo}: linha {chamada.lineno}: chamada a {alvo.nome}() nao "
				f"passa o(s) argumento(s) obrigatorio(s) {', '.join(faltando)} exigido(s) "
				f"pela definicao em {onde} (parametros: {assinatura_txt})."
			)
	return problemas


def _check_cross_module_signatures(addon_folder: str) -> list[str]:
	"""
	E24 -- NVDA-063: chamador e definicao discordam ENTRE arquivos do addon.

	Todas as outras 62 regras olham UM arquivo por vez, e por isso nenhuma
	via o defeito que mais custou ate agora: cada arquivo perfeito sozinho,
	__init__.py chamava proofread(text, model, api_key, on_done, on_error)
	-- assinatura que ele mesmo declarava num comentario de contrato -- e
	openai_service.py definia proofread(self, text, callback). O addon
	carregava, registrava os atalhos, e morria de TypeError na primeira
	tecla, engolido pelo proprio except Exception do addon.

	So resolve chamada cujo alvo e INEQUIVOCO -- nas outras, cala:
	  A. modulo.Classe().metodo(...)  (modulo irmao via `from . import X`)
	  B. Classe().metodo(...)         (classe local ou `from .X import C`)
	  C. modulo.funcao(...)           (funcao de modulo irmao)
	  D. self.metodo(...)             (metodo definido na propria classe)

	Nunca adivinha o tipo de uma variavel: `obj = fabrica(); obj.metodo(x)`
	aponta, aponta com os dois lados na mensagem.

	le e parseia texto; nao importa nem executa nada do addon.
	"""
	problems: list[str] = []

	for pdir_path in _plugin_dirs(addon_folder):
		classes, funcoes = _indexar_definicoes_do_addon(pdir_path)
		if not classes and not funcoes:
			continue

		for py_file in sorted(os.listdir(pdir_path)):
			if not py_file.endswith(".py"):
				continue
			full_path = os.path.join(pdir_path, py_file)
			try:
				with open(full_path, encoding="utf-8", errors="replace") as fh:
					src = fh.read()
				tree = ast.parse(src, filename=py_file)
			except (OSError, SyntaxError):
				continue
			mod_atual = py_file[: -len(".py")]

			# O que os imports relativos ligam a que.
			modulos_irmaos: set = set()
			classe_por_nome: dict = {}
			for no in ast.walk(tree):
				if not isinstance(no, ast.ImportFrom) or not no.level:
					continue
				if no.module is None:
					for alias in no.names:
						if alias.name in classes:
							modulos_irmaos.add(alias.asname or alias.name)
				elif no.module in classes:
					for alias in no.names:
						if alias.name in classes.get(no.module, {}):
							classe_por_nome[alias.asname or alias.name] = (no.module, alias.name)
			for nome_classe in classes.get(mod_atual, {}):
				classe_por_nome.setdefault(nome_classe, (mod_atual, nome_classe))

			# self.metodo(...) precisa saber em que classe o codigo esta.
			classe_da_linha: dict = {}
			for no in tree.body:
				if isinstance(no, ast.ClassDef):
					fim = getattr(no, "end_lineno", no.lineno) or no.lineno
					for linha in range(no.lineno, fim + 1):
						classe_da_linha[linha] = no.name

			for no in ast.walk(tree):
				if not isinstance(no, ast.Call) or not isinstance(no.func, ast.Attribute):
					continue
				metodo = no.func.attr
				recept = no.func.value
				alvo = None

				if isinstance(recept, ast.Call):
					construtor = recept.func
					# A. modulo.Classe().metodo(...)
					if (
						isinstance(construtor, ast.Attribute)
						and isinstance(construtor.value, ast.Name)
						and construtor.value.id in modulos_irmaos
					):
						alvo = classes.get(construtor.value.id, {}).get(
							construtor.attr, {}
						).get(metodo)
					# B. Classe().metodo(...)
					elif isinstance(construtor, ast.Name) and construtor.id in classe_por_nome:
						mod_c, nome_c = classe_por_nome[construtor.id]
						alvo = classes.get(mod_c, {}).get(nome_c, {}).get(metodo)
				# C. modulo.funcao(...)
				elif isinstance(recept, ast.Name) and recept.id in modulos_irmaos:
					alvo = funcoes.get(recept.id, {}).get(metodo)
				# D. self.metodo(...)
				elif isinstance(recept, ast.Name) and recept.id == "self":
					nome_classe = classe_da_linha.get(no.lineno)
					if nome_classe:
						alvo = classes.get(mod_atual, {}).get(nome_classe, {}).get(metodo)

				if alvo is not None:
					problems.extend(_conferir_chamada(no, alvo, py_file))

	return problems


def validate_addon_structure(addon_folder: str) -> list[str]:
	"""
	Smoke test estrutural do addon gerado.

	Verifica sem executar codigo :
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
	- Chamador e definicao discordando entre arquivos (NVDA-063) via _check_cross_module_signatures()
	- Widgets wx sem acessibilidade (WX-A11Y-001/002/003) via _check_wx_accessibility()
	- Imports de simbolos privados (NVDA-026) via _check_private_symbol_imports()
	- Dialogos sem Escape/StdDialogButtonSizer (WX-A11Y-004) via _check_dialog_accessibility()

	Retorna lista de problemas (vazia = estrutura OK).
	Usado pelo servidor MCP (addon_validar, addon_gravar) para devolver os problemas ao Claude.
	analisa texto — nao importa nem executa nenhum modulo gerado.
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
			problems.extend(_manifest_scalar_errors(manifest_content))
			for line in manifest_content.splitlines():
				if "=" in line and not line.strip().startswith("#"):
					key, _, value = line.partition("=")
					manifest_fields[key.strip()] = value.strip().strip('"').strip("'")
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
		# appModules/, synthDrivers/ etc. sao pontos de entrada validos sozinhos:
		# so reclama quando NENHUMA pasta de ponto de entrada existe.
		if not any(os.path.isdir(os.path.join(addon_folder, d)) for d in ENTRY_POINT_DIRS):
			problems.append(
				"ESTRUTURA-003: Pasta globalPlugins/ ausente (e nenhuma outra pasta de "
				"ponto de entrada: appModules/, synthDrivers/, brailleDisplayDrivers/)."
			)
	else:
		py_files: list[str] = []
		for root, dirs, files in os.walk(gp_dir):
			dirs[:] = [d for d in dirs if d != "lib"]  # ignora dependencias bundladas
			for fname in files:
				if fname.endswith(".py"):
					py_files.append(os.path.join(root, fname))
		# Quando existe globalPlugins/<Addon>/__init__.py, o __init__.py na raiz
		# e apenas marcador de pacote. O formato legado diretamente na raiz so
		# vale quando nao ha um subdiretorio de plugin real.
		plugin_subdirs_com_init = [
			d for d in os.listdir(gp_dir)
			if os.path.isdir(os.path.join(gp_dir, d))
			and os.path.isfile(os.path.join(gp_dir, d, "__init__.py"))
		]

		if not py_files:
			problems.append("ESTRUTURA-004: Nenhum arquivo .py encontrado em globalPlugins/.")
		else:
			# B6: detecta multiplas pastas de plugin (cada uma com __init__.py)
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
				(_py_dir == _gp_dir_norm and not plugin_subdirs_com_init)
				or os.path.dirname(_py_dir) == _gp_dir_norm
			)
			# NVDA-003 em MODULO AUXILIAR: gettext sem inicializacao.
			#
			# A regra sempre disse "modulo que usa gettext sem chamar
			# addonHandler.initTranslation()", mas a implementacao so olhava o
			# __init__.py principal. Um settings_panel.py que chama _("Chave de
			# API") sem initTranslation() levanta NameError na hora em que o
			# usuario abre o painel -- e o addon parece simplesmente nao ter
			# configuracao.
			#
			# Nao da para deixar isso pro ruff: code_sandbox declara `_` e os
			# irmaos como builtins justamente para nao acusar F821 no addon
			# inteiro (senao todo addon correto seria reprovado). Silenciado
			# ali, o defeito tem que ser visto aqui.
			#
			_usa_gettext = chama_gettext(code)
			if (
				not _e_init_principal
				and _usa_gettext
				and "initTranslation" not in code
				and "import gettext" not in code
			):
				problems.append(
					f"NVDA-003: {fname}: usa gettext (_(), ngettext...) sem "
					f"chamar addonHandler.initTranslation(). NameError em tempo "
					f"de execucao na primeira string traduzida deste modulo."
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

	# ESTRUTURA-009: imports relativos sem modulo correspondente.
	# Para cada pasta de plugin, verifica se todos os `from .modulo import`
	# tem um .py correspondente na mesma pasta.
	# Causa raiz do bug do GmailSummarizer: gmail_service.py importava
	# gmail_oauth.py que nunca foi gerado — NVDA silenciava o erro e
	# o plugin inteiro deixava de ser carregado.
	for pdir_path in _plugin_dirs(addon_folder):
		pdir = os.path.relpath(pdir_path, addon_folder).replace(os.sep, "/")
		module_names = {
			f[:-3]
			for f in os.listdir(pdir_path)
			if f.endswith(".py")
		}
		# Subpacotes (pasta/__init__.py) tambem satisfazem `from .X import Y` --
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
						f"nao encontrado em {pdir}/. "
						f"O modulo ausente impede o carregamento do addon pelo NVDA."
					)

	# NVDA-022: imports 3rd party em nivel de modulo em arquivos de servico.
	# Import em nivel de modulo em gmail_service.py, summarizer_service.py, etc.
	# faz __init__.py crashar silenciosamente se lib/ estiver incompleta.
	# O NVDA nao loga o erro — o addon inteiro deixa de carregar, incluindo o
	# settings panel. Somente arquivos que NAO sao __init__.py sao verificados.
	for pdir_path in _plugin_dirs(addon_folder):
		pdir = os.path.relpath(pdir_path, addon_folder).replace(os.sep, "/")
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
	for _pdir_path_024 in _plugin_dirs(addon_folder):
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
	for _pdir_path_025 in _plugin_dirs(addon_folder):
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

	# E24 — NVDA-063: chamador e definicao discordam entre arquivos
	problems.extend(_check_cross_module_signatures(addon_folder))

	# E18 — NVDA-021: indentacao com espacos em vez de TABs
	problems.extend(_check_indentation_style(addon_folder))

	# E19 — WX-A11Y-001/002/003: widgets wx sem acessibilidade
	problems.extend(_check_private_symbol_imports(addon_folder))
	problems.extend(_check_dialog_accessibility(addon_folder))
	problems.extend(_check_wx_accessibility(addon_folder))

	# NVDA-047: url no manifest.ini deve comecar com https:// (Add-on Store rejeita http://)
	# Regex usa [ \t]* (sem newlines) para nao pular para a linha seguinte quando url
	# esta vazio. Bug historico: '\s*' consumia '\r\n' e capturava 'version = 1.0.0'
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


def fix_addon_structure(addon_folder: str) -> list[str]:
	"""
	Corrige ESTRUTURA-007: funde multiplas pastas de plugin em uma unica.

	skill: tool-design — "error messages must enable recovery".
	skill: nvda-addon-dev §1 — estrutura obrigatoria: UMA pasta globalPlugins/<nome>/.

	Cenarios cobertos:
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
	apenas reorganiza arquivos existentes — nao executa codigo.
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

	apenas le e processa arquivos — nao executa nenhum codigo.
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
		"URL":                 download_url,
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
		"missing_fields": [k for k in ("homepage", "URL", "sourceURL", "licenseURL") if not metadata[k]],
		"metadata":  metadata,
	}
