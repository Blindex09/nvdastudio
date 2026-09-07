"""Slice 0 (spike) do Caminho 3 -- driver do droid em modo AGENTICO.

Em vez de chamar o droid numa jaula de texto (o que factory_client.py faz hoje:
pasta vazia, --disable-builtin-skills, "so devolva texto"), este driver o solta
como AGENTE dentro de trilhos: `droid exec --auto medium` num workdir isolado,
onde o droid EDITA arquivos, RODA comandos e ITERA ate produzir o addon -- o
loop das ferramentas de ponta (Cursor/Claude Code), com o droid como motor.

Escopo do Slice 0 (deliberadamente estreito, ver
docs/arquitetura-agentica-caminho3-2026-09-06.md):
  - NAO toca o pipeline staged atual (planner/orchestrator/sub_agents). E um
    modulo standalone, sem chamador de producao ainda -- registrado como orfao
    ACEITO em tests/unit/test_mecanismos_orfaos.py::_ORFAOS_ACEITOS.
  - Injecao do contexto NVDA completo (nvda_context) e o Slice 1; aqui vai so um
    spec compacto embutido, suficiente pra responder a pergunta do spike:
    "o loop agentico produz um addon plausivel?".
  - Validacao pesada pelos gates (code_sandbox etc.) e o Slice 2; aqui a
    validacao e basica (sintaxe + estrutura presente).

Blast radius: workdir descartavel + `--auto medium` (edita/roda/build/git local,
NUNCA push/sudo/producao). Nunca usa --skip-permissions-unsafe.
"""
import ast
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field

from ..ai.factory_client import _achar_droid, FactoryClientError
from ..utils.logger import get_logger

MODULE_VERSION = "0.1.0"
_logger = get_logger("agentic_driver")

# Sem isto o droid abre um console no Windows que rouba o foco do NVDA (0 fora
# do Windows -- portavel). Mesmo valor que factory_client.py usa.
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# Loop agentico ITERA (edita->roda->corrige) -- precisa de mais folga que uma
# geracao de tiro unico. 15 min por rodada de spike.
_DEFAULT_TIMEOUT = 900

_AUTONOMIAS_VALIDAS = ("low", "medium", "high")

# Spec compacto embutido (Slice 1 troca pelo nvda_context real). Alto sinal,
# baixo custo: o essencial da estrutura de um addon NVDA + a instrucao de
# AUTO-TESTE, que e o ponto do modo agentico.
_NVDA_SPEC = """Voce esta construindo um COMPLEMENTO (addon) para o leitor de tela NVDA.

Estrutura obrigatoria de um addon NVDA, na RAIZ do diretorio de trabalho atual:
- manifest.ini  (campos: name, summary, version, author, minimumNVDAVersion, lastTestedNVDAVersion)
- globalPlugins/<NomeDoPlugin>/__init__.py  para um global plugin, OU
  appModules/<nome>.py  para um app module.

Regras de codigo:
- Python 3, compativel com o ambiente do NVDA. Use apenas a stdlib e as APIs do
  proprio NVDA (globalPluginHandler, scriptHandler, ui, api, etc.). NUNCA use
  pacotes externos (win32*, requests, ...): nao existem no Python do NVDA.
- Um global plugin herda de globalPluginHandler.GlobalPlugin. Gestos sao ligados
  com @scriptHandler.script(...) ou __gestures. Fala com ui.message("...").
- Escreva codigo real e completo, sem placeholders ("TODO", "...", "seu codigo aqui").

Como trabalhar (voce e um AGENTE, use isso):
1. Crie os arquivos no diretorio de trabalho atual.
2. RODE `python -c "import ast; ast.parse(open('<arquivo>.py').read())"` em cada .py
   que criar, para confirmar que a sintaxe esta valida. Corrija e repita ate passar.
3. Confirme que manifest.ini existe e tem os campos obrigatorios.
Entregue apenas quando o addon estiver completo e a sintaxe de todos os .py validada."""


@dataclass
class AgenticBuildResult:
	"""Resultado de uma rodada agentica. Sem excecao: erro vira campo."""
	success: bool
	workdir: str
	files: list[str] = field(default_factory=list)
	has_manifest: bool = False
	has_entry_point: bool = False
	py_syntax_ok: bool = False
	returncode: int = -1
	duration_seconds: float = 0.0
	stdout_tail: str = ""
	stderr_tail: str = ""
	error: str = ""


def _build_system_prompt(extra_context: str = "") -> str:
	partes = [_NVDA_SPEC]
	if extra_context.strip():
		partes.append(extra_context.strip())
	return "\n\n".join(partes)


def _coletar_arquivos(workdir: str) -> list[str]:
	"""Caminhos relativos dos arquivos que o droid produziu, ignorando o que e
	interno do proprio droid/git."""
	ignorar = {".git", ".factory", "__pycache__", ".droid"}
	achados: list[str] = []
	for raiz, dirs, arquivos in os.walk(workdir):
		dirs[:] = [d for d in dirs if d not in ignorar]
		for nome in arquivos:
			if nome == "prompt.txt" or nome == "system-prompt.txt":
				continue
			rel = os.path.relpath(os.path.join(raiz, nome), workdir).replace("\\", "/")
			achados.append(rel)
	return sorted(achados)


def _validar_basico(workdir: str, files: list[str]) -> tuple[bool, bool, bool]:
	"""(has_manifest, has_entry_point, py_syntax_ok) -- validacao leve do Slice 0.
	Os gates de verdade (code_sandbox, completude) entram no Slice 2."""
	has_manifest = any(f.rsplit("/", 1)[-1] == "manifest.ini" for f in files)
	has_entry_point = any(
		f.endswith("__init__.py") and "globalPlugins/" in f for f in files
	) or any(f.startswith("appModules/") and f.endswith(".py") for f in files)
	py_syntax_ok = True
	for f in files:
		if not f.endswith(".py"):
			continue
		try:
			with open(os.path.join(workdir, f), encoding="utf-8", errors="replace") as fh:
				ast.parse(fh.read())
		except (SyntaxError, OSError):
			py_syntax_ok = False
			break
	return has_manifest, has_entry_point, py_syntax_ok


def run_agentic_build(
	request: str,
	workdir: str | None = None,
	*,
	model_id: str = "kimi-k2.7-code",
	autonomy: str = "medium",
	timeout: int = _DEFAULT_TIMEOUT,
	extra_context: str = "",
) -> AgenticBuildResult:
	"""Roda UMA build agentica do addon via droid e valida basico.

	Nunca levanta excecao de execucao: degrada para AgenticBuildResult(success=
	False, error=...) -- mesma doutrina de code_sandbox.

	request: o pedido do usuario em linguagem natural.
	workdir: diretorio de trabalho (isolado). None cria um tempdir (o chamador
	         decide quando limpar -- o spike quer inspecionar o resultado).
	autonomy: nivel --auto do droid. 'medium' = edita/roda/build local, sem
	          push/sudo/producao. 'high' e producao -- nao usar aqui.
	"""
	if autonomy not in _AUTONOMIAS_VALIDAS:
		return AgenticBuildResult(
			success=False, workdir=workdir or "",
			error=f"autonomia invalida: {autonomy!r} (validas: {_AUTONOMIAS_VALIDAS})",
		)
	try:
		droid = _achar_droid()
	except FactoryClientError as exc:
		return AgenticBuildResult(success=False, workdir=workdir or "", error=str(exc))

	if workdir is None:
		workdir = tempfile.mkdtemp(prefix="nvdastudio_agentic_")
	os.makedirs(workdir, exist_ok=True)

	sp_path = os.path.join(workdir, "system-prompt.txt")
	prompt_path = os.path.join(workdir, "prompt.txt")
	try:
		with open(sp_path, "w", encoding="utf-8") as fh:
			fh.write(_build_system_prompt(extra_context))
		with open(prompt_path, "w", encoding="utf-8") as fh:
			fh.write(request)
	except OSError as exc:
		return AgenticBuildResult(success=False, workdir=workdir, error=f"falha ao escrever prompts: {exc}")

	cmd = [
		droid, "exec",
		"--auto", autonomy,
		"--cwd", workdir,
		"-m", model_id,
		"--append-system-prompt-file", sp_path,
		"-f", prompt_path,
	]
	_logger.info("[AGENTIC] droid exec --auto %s -m %s cwd=%s", autonomy, model_id, workdir)

	t0 = time.time()
	try:
		proc = subprocess.run(
			cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
			timeout=timeout, cwd=workdir, creationflags=CREATE_NO_WINDOW,
		)
	except subprocess.TimeoutExpired:
		return AgenticBuildResult(
			success=False, workdir=workdir, duration_seconds=time.time() - t0,
			error=f"droid excedeu {timeout}s no modo agentico",
		)
	except OSError as exc:
		return AgenticBuildResult(
			success=False, workdir=workdir, duration_seconds=time.time() - t0,
			error=f"nao foi possivel executar o droid: {exc}",
		)

	dur = time.time() - t0
	# Remove os arquivos de prompt antes de coletar (nao contam como saida).
	for p in (sp_path, prompt_path):
		try:
			os.remove(p)
		except OSError as exc:
			_logger.debug("[AGENTIC] nao removeu %s: %s", p, exc)

	files = _coletar_arquivos(workdir)
	has_manifest, has_entry, syntax_ok = _validar_basico(workdir, files)
	success = proc.returncode == 0 and has_manifest and has_entry and syntax_ok and bool(files)

	return AgenticBuildResult(
		success=success,
		workdir=workdir,
		files=files,
		has_manifest=has_manifest,
		has_entry_point=has_entry,
		py_syntax_ok=syntax_ok,
		returncode=proc.returncode,
		duration_seconds=dur,
		stdout_tail=(proc.stdout or "")[-2000:],
		stderr_tail=(proc.stderr or "")[-2000:],
		error="" if success else "build agentica nao passou na validacao basica do Slice 0",
	)
