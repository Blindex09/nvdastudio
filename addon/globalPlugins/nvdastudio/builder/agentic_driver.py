"""Slice 0 (spike) do Caminho 3 -- driver do droid em modo AGENTICO.

Em vez de chamar o droid numa jaula de texto (o que factory_client.py faz hoje:
pasta vazia, --disable-builtin-skills, "so devolva texto"), este driver o solta
como AGENTE dentro de trilhos: `droid exec --auto medium` num workdir isolado,
onde o droid EDITA arquivos, RODA comandos e ITERA ate produzir o addon -- o
loop das ferramentas de ponta (Cursor/Claude Code), com o droid como motor.

Estado atual (pos-demolicao do staged, 2026-09-06, ver
docs/arquitetura-agentica-caminho3-2026-09-06.md):
  - Este e o UNICO caminho de geracao. O orchestrator (_run_pipeline_agentic) o
    consome de verdade -- planner/sub_agents/pipeline staged foram removidos.
  - Injeta o contexto NVDA completo (nvda_context.get_docs_code_generation +
    NVDA_SYSTEM_PROMPT) no system-prompt.
  - Validacao pelos gates: _run_gates roda sintaxe/estrutura + code_sandbox
    (execucao real) + gate de acessibilidade (ast_validator).

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
from ..utils.injection_guard import detect_injection
from ..utils.logger import get_logger

MODULE_VERSION = "0.6.0"
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
	tokens: int = 0  # tokens novos (input+output+cache-creation) somados nas rodadas
	stdout_tail: str = ""
	stderr_tail: str = ""
	error: str = ""
	# Slice 2 -- gate de execucao pos-loop (code_sandbox) + ciclo de correcao.
	execution_ok: bool = False
	gate_report: str = ""
	rounds: int = 1


def _build_nvda_context(request: str) -> str:
	"""Contexto NVDA real -- Slice 1. O MESMO conhecimento que o pipeline staged
	injeta no code_generation (nvda_context + rule_registry + engineering_principles),
	escopado pelos topicos do pedido, para um A/B justo: mesmo conhecimento, loop
	diferente. Import tardio: os modulos NVDA sao pesados, so puxa quando pedido.
	"""
	from .nvda_context import (
		NVDA_SYSTEM_PROMPT, get_docs_code_generation, extract_nvda_topics,
	)
	from ..rule_registry import RULE_REGISTRY_PROMPT_TEXT
	from ..utils.engineering_principles import ENGINEERING_CODEGEN_PROMPT_TEXT

	docs = get_docs_code_generation(topics=extract_nvda_topics(request))
	return "\n\n".join((
		NVDA_SYSTEM_PROMPT,
		RULE_REGISTRY_PROMPT_TEXT,
		ENGINEERING_CODEGEN_PROMPT_TEXT,
		docs,
	))


def _build_system_prompt(
	request: str = "", *, use_nvda_context: bool = True, extra_context: str = "",
) -> str:
	partes = [_NVDA_SPEC]
	if use_nvda_context:
		try:
			partes.append(_build_nvda_context(request))
		except Exception as exc:  # pragma: no cover - defesa
			# Contexto faltando degrada pro spec compacto, nunca derruba a build.
			_logger.warning(
				"[AGENTIC] contexto NVDA indisponivel, seguindo com spec compacto: %s", exc,
			)
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


def _droid_once(
	request: str,
	workdir: str | None = None,
	*,
	model_id: str = "kimi-k2.7-code",
	autonomy: str = "medium",
	timeout: int = _DEFAULT_TIMEOUT,
	use_nvda_context: bool = True,
	extra_context: str = "",
) -> AgenticBuildResult:
	"""UMA rodada do droid agentico + validacao BASICA (manifest/entry/sintaxe).

	Nunca levanta excecao de execucao: degrada para AgenticBuildResult(success=
	False, error=...) -- mesma doutrina de code_sandbox. E o tijolo que o ciclo
	de correcao (Slice 2) repete a cada rodada.
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

	# Guarda de injecao no request (doc 3, blast radius): o droid roda com
	# ferramentas de edicao + terminal, entao o texto que vira instrucao para ele
	# e uma fronteira que importa. Diferente de um bloco de DADO externo (que o
	# injection_guard envolveria como inerte), o request E a instrucao legitima do
	# usuario -- nao da pra trata-lo como dado. Por isso
	# aqui e deteccao NAO-bloqueante: se o request tras padrao de injecao conhecido
	# (ex.: conteudo colado de uma pagina/email pedindo "ignore previous
	# instructions"), registramos para visibilidade e seguimos -- o `--auto medium`
	# ja contem o estrago (sem push/sudo/producao).
	if detect_injection(request):
		_logger.warning(
			"[AGENTIC][INJECTION_GUARD] padrao de injecao detectado no request -- "
			"seguindo sob --auto %s (blast radius contido), registrado para auditoria.",
			autonomy,
		)

	sp_path = os.path.join(workdir, "system-prompt.txt")
	prompt_path = os.path.join(workdir, "prompt.txt")
	try:
		with open(sp_path, "w", encoding="utf-8") as fh:
			fh.write(_build_system_prompt(
				request, use_nvda_context=use_nvda_context, extra_context=extra_context,
			))
		with open(prompt_path, "w", encoding="utf-8") as fh:
			fh.write(request)
	except OSError as exc:
		return AgenticBuildResult(success=False, workdir=workdir, error=f"falha ao escrever prompts: {exc}")

	cmd = [
		droid, "exec",
		"-o", "json",  # envelope com usage -- captura tokens (comparacao de custo)
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
		tokens=_parse_droid_tokens(proc.stdout),
		stdout_tail=(proc.stdout or "")[-2000:],
		stderr_tail=(proc.stderr or "")[-2000:],
		error="" if success else "build agentica nao passou na validacao basica do Slice 0",
	)


def _parse_droid_tokens(stdout: str) -> int:
	"""Soma tokens NOVOS (input + output + criacao de cache) do envelope JSON do
	`droid exec -o json`. A leitura de cache (cache_read_input_tokens) fica de
	fora -- e fracao do preco; somar a peso cheio penalizaria o mecanismo que
	barateia. Mesma conta que ai/factory_client.py::_ler_envelope. Robusto: pega
	a ULTIMA linha que parseia como JSON com `usage` (o droid pode logar antes)."""
	import json
	total = 0
	for linha in reversed((stdout or "").splitlines()):
		linha = linha.strip()
		if not linha.startswith("{"):
			continue
		try:
			env = json.loads(linha)
		except (json.JSONDecodeError, ValueError):
			continue
		uso = env.get("usage") if isinstance(env, dict) else None
		if isinstance(uso, dict):
			total = (
				int(uso.get("input_tokens") or 0)
				+ int(uso.get("output_tokens") or 0)
				+ int(uso.get("cache_creation_input_tokens") or 0)
			)
			break
	return total


def _read_files_dict(workdir: str, files: list[str]) -> dict[str, str]:
	"""{caminho_relativo: conteudo} para o code_sandbox ler."""
	out: dict[str, str] = {}
	for f in files:
		try:
			with open(os.path.join(workdir, f), encoding="utf-8", errors="replace") as fh:
				out[f] = fh.read()
		except OSError:
			pass
	return out


def _run_accessibility_gate(files_dict: dict[str, str]) -> list[str]:
	"""Gate de ACESSIBILIDADE deterministico -- roda os validadores AST do
	ast_validator (o unico sub_agent que sobreviveu a demolicao do staged) em
	cada .py do addon. Reintroduz a checagem de acessibilidade que saiu com o
	accessibility_audit staged, mas MELHOR: deterministica (AST, nao LLM), o
	que casa com a tese do gate (o juiz nao e probabilistico).

	Cobre NVDA-019 (Translators em toda _()), acessibilidade wx (accelerators,
	eventos de teclado), controlTypes e MessageDialog em thread. Import tardio.
	"""
	violacoes: list[str] = []
	try:
		from ..sub_agents.ast_validator import (
			validate_nvda019, validate_wx_a11y, validate_wx_a11y_002_accelerators,
			validate_wx_a11y_013_key_events, validate_nvda060_controltypes,
			validate_nvda056_messagedialog_thread,
		)
	except Exception as exc:  # pragma: no cover - defesa
		_logger.warning("[AGENTIC] gate de acessibilidade indisponivel: %s", exc)
		return violacoes

	checagens = (
		validate_nvda019, validate_wx_a11y, validate_wx_a11y_002_accelerators,
		validate_wx_a11y_013_key_events, validate_nvda060_controltypes,
		validate_nvda056_messagedialog_thread,
	)
	for rel, codigo in files_dict.items():
		if not rel.endswith(".py"):
			continue
		for check in checagens:
			try:
				res = check(codigo)
			except Exception:  # pragma: no cover - fail-open por checagem
				continue
			if not res.ok:
				for v in res.violacoes:
					violacoes.append(f"{rel}: {v}")
	return violacoes[:15]  # cap: o essencial, sem inundar o prompt de correcao


def _run_gates(workdir: str, files: list[str]) -> tuple[bool, str]:
	"""Gate DETERMINISTICO pos-loop -> (passou, relatorio_de_falha).

	1. Estrutural: manifest + ponto de entrada + sintaxe (_validar_basico).
	2. Execucao real: code_sandbox.validate_addon_execution importa e instancia
	   a classe principal num subprocesso com stubs NVDA -- pega NameError,
	   assinatura de construtor errada, import que nao resolve (horizon: "se nao
	   executou, nao esta verificado"). Import tardio (code_sandbox e pesado).
	3. Acessibilidade: _run_accessibility_gate roda os validadores AST (NVDA-019,
	   wx a11y, controlTypes) -- reintroduz a checagem que saiu com o staged.

	O gate e do NVDAStudio (determinismo fora do modelo), nunca do droid -- e a
	tese central dos 7 projetos auditados: o executor nao e o juiz.
	"""
	has_manifest, has_entry, syntax_ok = _validar_basico(workdir, files)
	problemas: list[str] = []
	if not has_manifest:
		problemas.append("- Falta o manifest.ini na raiz do addon.")
	if not has_entry:
		problemas.append(
			"- Falta o ponto de entrada (globalPlugins/<Nome>/__init__.py "
			"ou appModules/<nome>.py)."
		)
	if not syntax_ok:
		problemas.append("- Ha erro de SINTAXE em algum arquivo .py.")
	if has_entry and syntax_ok:
		try:
			from .code_sandbox import CodeSandbox

			res = CodeSandbox(timeout_sec=15).validate_addon_execution(
				_read_files_dict(workdir, files),
			)
			if not res.success:
				detalhe = (res.error or res.stderr or "").strip().replace("\n", " ")
				problemas.append(
					f"- Erro de EXECUCAO real ao importar/instanciar o addon: {detalhe[:400]}"
				)
		except Exception as exc:  # pragma: no cover - defesa
			# Gate indisponivel nao derruba a build -- degrada (fica sem o gate
			# de execucao, mas o estrutural/sintaxe ja rodou).
			_logger.warning("[AGENTIC] gate de execucao indisponivel: %s", exc)
		# Gate de acessibilidade (so vale a pena com sintaxe valida).
		a11y = _run_accessibility_gate(_read_files_dict(workdir, files))
		if a11y:
			problemas.append(
				"- Problemas de ACESSIBILIDADE (corrija todos):\n  " + "\n  ".join(a11y)
			)
	return (not problemas), "\n".join(problemas)


def run_agentic_build(
	request: str,
	workdir: str | None = None,
	*,
	model_id: str = "kimi-k2.7-code",
	autonomy: str = "medium",
	timeout: int = _DEFAULT_TIMEOUT,
	use_nvda_context: bool = True,
	extra_context: str = "",
	correction_rounds: int = 0,
) -> AgenticBuildResult:
	"""Ponto de entrada publico do driver agentico.

	Roda a build e, se `correction_rounds` > 0, fecha o ciclo 'editar -> rodar ->
	corrigir' do Slice 2: apos cada build, roda os gates DETERMINISTICOS
	(code_sandbox + estrutura) e, se reprovarem, reinjeta os problemas no droid
	na MESMA pasta (que ja tem os arquivos) para ele corrigir -- ate passar ou
	esgotar as rodadas. `correction_rounds=0` (padrao) mantem o comportamento dos
	Slices 0/1 (build unica + validacao basica).
	"""
	# Resolve o workdir UMA vez -- todas as rodadas de correcao compartilham a
	# mesma pasta (o droid corrige os arquivos que ja existem la).
	if workdir is None:
		workdir = tempfile.mkdtemp(prefix="nvdastudio_agentic_")

	result = _droid_once(
		request, workdir, model_id=model_id, autonomy=autonomy, timeout=timeout,
		use_nvda_context=use_nvda_context, extra_context=extra_context,
	)
	tokens_acumulados = result.tokens  # soma o custo de TODAS as rodadas
	if correction_rounds <= 0 or not result.files:
		return result

	for rodada in range(1, correction_rounds + 1):
		passou, relatorio = _run_gates(result.workdir, result.files)
		result.execution_ok = passou
		result.gate_report = relatorio
		result.rounds = rodada
		result.tokens = tokens_acumulados
		if passou:
			result.success = result.success and passou
			return result
		_logger.info(
			"[AGENTIC] gate reprovou (rodada %d/%d), reinjetando no droid.",
			rodada, correction_rounds,
		)
		correcao = (
			"O addon que voce gerou no diretorio de trabalho atual NAO passou na "
			"verificacao. Problemas encontrados:\n" + relatorio +
			"\n\nCorrija os arquivos EXISTENTES (nao recomece do zero) ate que o "
			"addon importe e instancie sem erro. Rode os arquivos para confirmar."
		)
		result = _droid_once(
			correcao, result.workdir, model_id=model_id, autonomy=autonomy,
			timeout=timeout, use_nvda_context=use_nvda_context, extra_context=extra_context,
		)
		tokens_acumulados += result.tokens
		result.rounds = rodada + 1

	# Gate final apos a ultima rodada de correcao.
	passou, relatorio = _run_gates(result.workdir, result.files)
	result.execution_ok = passou
	result.gate_report = relatorio
	result.tokens = tokens_acumulados
	result.success = result.success and passou
	return result
