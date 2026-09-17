"""Slice 0 (spike) do Caminho 3 -- driver do droid em modo AGENTICO.

Em vez de chamar o droid numa jaula de texto (o que factory_client.py faz hoje:
pasta vazia, --disable-builtin-skills, "so devolva texto"), este driver o solta
como AGENTE dentro de trilhos: `droid exec --auto medium` num workdir isolado,
onde o droid EDITA arquivos, RODA comandos e ITERA ate produzir o addon -- o
loop das ferramentas de ponta (Cursor/Claude Code), com o droid como motor.

Estado atual:
  - Este e o unico caminho de geracao. O orchestrator chama run_agentic_build;
    o antigo pipeline staged foi removido.
  - Injeta o contexto NVDA completo (nvda_context.get_docs_code_generation +
    NVDA_SYSTEM_PROMPT) no system-prompt.
  - Validacao pelos gates: _run_gates roda sintaxe/estrutura + code_sandbox
    (execucao real) + gate de acessibilidade (ast_validator).

Blast radius: workdir descartavel + `--auto medium` (edita/roda/build/git local,
NUNCA push/sudo/producao). Nunca usa --skip-permissions-unsafe.
"""
import ast
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from ..ai.factory_client import FactoryClientError
from .agentic_backends import AgenticBackend, get_backend
from .agent_tools import (
	AgentToolContext, build_agent_tool_gateway, execute_agent_tool,
	get_agent_tool_schemas,
)
from .agent_checkpoint import (
	AgentCheckpointStore, checkpoint_store, export_client_history,
	restore_client_history,
)
from ..utils.injection_guard import detect_injection
from ..utils.logger import get_logger

MODULE_VERSION = "0.15.0"
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
3. Para qualquer API externa, consulte a documentacao oficial atual antes de
   escrever o endpoint, o nome do modelo ou o formato do payload. Nunca invente
   uma API a partir da memoria. Para o Gemini Interactions API, a referencia
   oficial usa `https://generativelanguage.googleapis.com/v1beta/interactions`,
   `input` como itens `{"type": "text", "text": "..."}` e
   `{"type": "audio", "data": "<base64>", "mime_type": "audio/..."}`;
   no momento, `gemini-3.8-flash` e o modelo mostrado na referencia de audio;
   ainda assim confirme o modelo vigente na documentacao antes de escolher um.
4. Explique em portugues o que vai fazer antes de usar ferramentas e informe
   descobertas relevantes durante o trabalho. Use AskUser se precisar de uma
   escolha do usuario. Nao abra comandos de terminal que aguardem input.
   Use timeouts em rede. Nao mostre codigo ou prompts internos na conversa.
   Mantenha os arquivos-fonte na raiz do diretorio de trabalho, inclusive apos
   validar. O NVDAStudio empacota e entrega o resultado depois de seus gates;
   nao crie um ZIP em substituicao aos fontes nem declare o pacote entregue.
5. Confirme que manifest.ini existe e tem os campos obrigatorios.
6. Crie testes automatizados proporcionais ao risco da mudança. Para bugs,
   inclua um teste de regressão que falharia antes da correção. Execute primeiro
   análise estática e testes locais; só use APIs reais quando as verificações
   baratas não forem suficientes. Inspecione os dois lados de cada integração.
Entregue apenas quando o addon estiver completo, a sintaxe de todos os .py
validada e a verificacao final concluida. Ao terminar, escreva um resumo final
curto do que foi criado e dos testes executados."""


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
	# Direcao ao vivo: True quando o usuario INTERROMPEU o build (nao e falha).
	cancelled: bool = False
	checkpoint_path: str = ""
	trace: list[dict] = field(default_factory=list)
	evaluation: dict = field(default_factory=dict)


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
	ignorar = {".git", ".factory", "__pycache__", ".droid", ".pytest_cache"}
	achados: list[str] = []
	for raiz, dirs, arquivos in os.walk(workdir):
		dirs[:] = [d for d in dirs if d not in ignorar]
		for nome in arquivos:
			if nome in {"prompt.txt", "system-prompt.txt"} or nome.lower().endswith((".nvda-addon", ".zip")):
				# O pacote produzido pelo agente é um artefato intermediário. Ele
				# não deve virar bloco de código nem substituir o empacotamento
				# determinístico da interface para a pasta de saída final.
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


def _build_failure_detail(
	returncode: int, files: list[str], has_manifest: bool,
	has_entry: bool, syntax_ok: bool, stderr: str, stdout: str,
) -> str:
	"""Produz diagnóstico curto e útil quando o gate determinístico reprova."""
	problemas = []
	if returncode != 0:
		problemas.append(f"o agente terminou com código {returncode}")
	if not files:
		problemas.append("nenhum arquivo foi encontrado na pasta de trabalho")
	if files and not has_manifest:
		problemas.append("manifest.ini ausente")
	if files and not has_entry:
		problemas.append("ponto de entrada do addon ausente")
	if files and not syntax_ok:
		problemas.append("há erro de sintaxe Python")
	diagnostico = (stderr or "").strip()
	if diagnostico:
		linhas = [linha.strip() for linha in diagnostico.splitlines() if linha.strip()]
		if linhas:
			problemas.append(f"saída do agente: {linhas[-1][:300]}")
	return "; ".join(problemas) or "build agentica nao passou na validacao basica"


class _BuildCancelled(Exception):
	"""O usuario pediu para INTERROMPER o build em andamento (direcao ao vivo).
	Distinta de timeout/erro: nao e falha do agente, e escolha do usuario."""


class _ProviderSteer(Exception):
	"""Nova instrução recebida enquanto um provedor nativo transmitia texto."""


def _run_streaming(
	cmd: list[str], *, workdir: str, timeout: int,
	progress_callback: Callable[[str], None] | None = None,
	cancel_event: "threading.Event | None" = None,
) -> tuple[int, str, str]:
	"""Roda o processo agentico TRANSMITINDO o stdout ao vivo (linha a linha) para
	`progress_callback`, enquanto acumula stdout/stderr completos e respeita o
	timeout. Popen + threads de drenagem em vez de subprocess.run porque as
	ferramentas de ponta mostram o progresso DURANTE a geracao, nao so no fim --
	um build agentico complexo leva minutos, e o silencio total nesse tempo e a
	maior diferenca de UX pro usuario. Levanta subprocess.TimeoutExpired/OSError
	como subprocess.run faria (o chamador ja trata).

	`cancel_event` (direcao ao vivo): se o usuario sinalizar durante a execucao, o
	processo e MORTO limpo e _BuildCancelled e levantada. O droid exec e one-shot
	(nao aceita input mid-run), entao INTERROMPER e o que da pra fazer de verdade
	no meio de uma rodada; REDIRECIONAR acontece na fronteira da proxima rodada
	(run_agentic_build), com o workdir preservado.

	As duas streams sao drenadas em paralelo (senao o buffer cheio de uma trava a
	outra). Erros do callback nunca derrubam a build -- progresso e best-effort.
	"""
	proc = subprocess.Popen(
		cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
		text=True, encoding="utf-8", errors="replace",
		cwd=workdir, creationflags=CREATE_NO_WINDOW,
	)
	out_lines: list[str] = []
	err_lines: list[str] = []

	def _drain(stream, sink: list[str], emit: bool) -> None:
		if stream is None:
			return
		for line in stream:
			sink.append(line)
			if emit and progress_callback:
				texto = line.strip()
				if texto:
					try:
						progress_callback(texto[:200])
					except Exception:  # pragma: no cover - progresso e best-effort
						pass
		try:
			stream.close()
		except OSError:  # pragma: no cover - defesa
			pass

	t_out = threading.Thread(target=_drain, args=(proc.stdout, out_lines, True), daemon=True)
	t_err = threading.Thread(target=_drain, args=(proc.stderr, err_lines, False), daemon=True)
	t_out.start()
	t_err.start()

	# Espera cooperativa: fatia o wait em janelas curtas para poder atender o
	# cancelamento do usuario e ainda respeitar o deadline do timeout.
	deadline = time.time() + timeout
	cancelado = False
	while True:
		try:
			proc.wait(timeout=0.5)
			break  # processo terminou sozinho
		except subprocess.TimeoutExpired:
			if cancel_event is not None and cancel_event.is_set():
				cancelado = True
				break
			if time.time() >= deadline:
				proc.kill()
				proc.wait()
				raise subprocess.TimeoutExpired(cmd, timeout)

	if cancelado:
		proc.kill()
		proc.wait()
		raise _BuildCancelled()

	# Deixa as threads terminarem de drenar o que sobrou no buffer.
	t_out.join(timeout=5)
	t_err.join(timeout=5)
	return proc.returncode, "".join(out_lines), "".join(err_lines)


def _rpc_request(request_id: str, method: str, params: dict) -> dict[str, object]:
	"""Monta uma mensagem do protocolo Factory stream-jsonrpc."""
	return {
		"jsonrpc": "2.0",
		"factoryApiVersion": "1.0.0",
		"factoryProtocolVersion": "1.193.0",
		"type": "request",
		"id": request_id,
		"method": method,
		"params": params,
	}


def _permission_request_details(payload: dict) -> tuple[str, dict]:
	"""Extrai nome e argumentos de uma solicitação Factory de permissão."""
	params = payload.get("params")
	if not isinstance(params, dict):
		return "ferramenta desconhecida", {}
	uses = params.get("toolUses") or params.get("tool_uses") or []
	if not uses and isinstance(params.get("toolUse"), dict):
		uses = [params["toolUse"]]
	if isinstance(uses, list) and uses:
		use = uses[0] if isinstance(uses[0], dict) else {}
		details_obj = use.get("details")
		details: dict = details_obj if isinstance(details_obj, dict) else dict(use)
		name = details.get("toolName") or details.get("tool_name") or use.get("name") or details.get("type")
		arguments = details.get("input") or details.get("parameters") or details.get("arguments") or details
		return str(name or "ferramenta desconhecida"), arguments if isinstance(arguments, dict) else {}
	name = params.get("toolName") or params.get("tool_name") or params.get("name")
	arguments = params.get("input") or params.get("parameters") or params.get("arguments") or {}
	return str(name or "ferramenta desconhecida"), arguments if isinstance(arguments, dict) else {}


def _permission_outcome(payload: dict, approved: bool) -> str:
	"""Escolhe um valor realmente oferecido pelo servidor Factory."""
	params = payload.get("params")
	options = params.get("options", []) if isinstance(params, dict) else []
	if isinstance(options, list):
		values = [str(item.get("value")) for item in options if isinstance(item, dict) and item.get("value") is not None]
		if approved:
			return next((value for value in values if value.casefold() in {"proceed_once", "proceedonce"}), "cancel")
		return next((value for value in values if value.casefold() == "cancel"), "cancel")
	return "proceed_once" if approved else "cancel"


def _answer_questions(payload: dict, callback: Callable[[list[str]], list[str]] | None) -> dict:
	params = payload.get("params") or {}
	questions = params.get("questions") or []
	cancelled = {"cancelled": True, "answers": []}
	if not callback or not questions or any(not isinstance(q, dict) for q in questions):
		return cancelled
	try:
		labels = [str(q.get("question") or "") + (
			"\nOpções: " + "; ".join(map(str, q["options"])) if q.get("options") else ""
		) for q in questions]
		answers = callback(labels)
		if len(answers) != len(questions) or any(not a.strip() for a in answers):
			return cancelled
		return {"answers": [
			{"index": q["index"], "question": q["question"], "answer": a}
			for q, a in zip(questions, answers, strict=True)
		]}
	except Exception as exc:
		_logger.warning("[AGENTIC] falha ao perguntar ao usuario: %s", exc)
		return cancelled


_AGENT_TOOL_SCHEMAS = get_agent_tool_schemas()


def _native_call_parts(call: dict) -> tuple[str, dict, str]:
	function = call.get("function") if isinstance(call, dict) else {}
	function = function if isinstance(function, dict) else {}
	name = str(function.get("name") or call.get("name") or "")
	arguments = function.get("arguments", call.get("arguments", {}))
	if isinstance(arguments, str):
		try:
			arguments = json.loads(arguments)
		except json.JSONDecodeError:
			arguments = {}
	return name, arguments if isinstance(arguments, dict) else {}, str(call.get("id") or name)


def run_provider_agentic_build(
	request: str, *, provider: str, model_id: str, workdir: str | None = None,
	use_nvda_context: bool = True, correction_rounds: int = 0,
	progress_callback: Callable[[str], None] | None = None,
	cancel_event: "threading.Event | None" = None,
	steer_provider: Callable[[], str] | None = None,
	permission_callback: Callable[[str, dict], bool] | None = None,
	ask_user_callback: Callable[[list[str]], list[str]] | None = None,
	resume: bool = True,
	state_store: AgentCheckpointStore | None = None,
) -> AgenticBuildResult:
	"""Loop agêntico comum para provedores HTTP com function calling."""
	from ..ai.llm_factory import create_llm_client

	store = state_store or checkpoint_store
	state = store.find_resumable(request, provider, model_id) if resume and workdir is None else None
	was_resumed = state is not None
	workdir = workdir or (state.workdir if state else tempfile.mkdtemp(prefix="nvdastudio_agentic_"))
	os.makedirs(workdir, exist_ok=True)
	state = state or store.new(request, provider, model_id, workdir)
	tokens = state.tokens
	turns = state.turn
	starting_turn = turns
	corrections = state.corrections
	last_content = ""
	try:
		client = create_llm_client(model_id=model_id, provider=provider)
		restore_client_history(client, state.client_history)
		tool_context = AgentToolContext(
			workdir=workdir,
			list_files=lambda: _coletar_arquivos(workdir),
			validate=lambda: _run_gates(workdir, _coletar_arquivos(workdir)),
			permission_callback=permission_callback,
			ask_user_callback=ask_user_callback,
			client=client,
			cancel_event=cancel_event,
		)
		tool_gateway = build_agent_tool_gateway(tool_context)
		system = _build_system_prompt(request, use_nvda_context=use_nvda_context) + (
			"\n\nUse as ferramentas de workspace para produzir os arquivos reais. "
			"Nao devolva codigo apenas na conversa. Valide antes de concluir."
		)
		message = state.message or request
		tool_results: list[dict[str, str]] | None = state.tool_results
		max_turns = 32 + max(0, correction_rounds) * 8
		state.event("run_resumed" if was_resumed else "run_started", turn=turns)
		store.save(state)
		while turns - starting_turn < max_turns:
			if cancel_event is not None and cancel_event.is_set():
				state.status = "cancelled"
				state.event("cancelled", turn=turns)
				store.save(state)
				return AgenticBuildResult(False, workdir, cancelled=True, error="build interrompida pelo usuario", tokens=tokens, checkpoint_path=store.path(state.run_id), trace=state.trace)
			if steer_provider is not None:
				steer = (steer_provider() or "").strip()
				if steer:
					message = f"Nova instrucao do usuario, aplique-a agora:\n{steer}\n\n{message}"
			def _on_native_chunk(chunk: str) -> None:
				if cancel_event is not None and cancel_event.is_set():
					raise _BuildCancelled()
				if steer_provider is not None:
					new_instruction = (steer_provider() or "").strip()
					if new_instruction:
						raise _ProviderSteer(new_instruction)
				if progress_callback:
					progress_callback(chunk)

			try:
				state.message = message
				state.tool_results = tool_results
				state.client_history = export_client_history(client)
				state.event("model_call_started", turn=turns + 1, model=model_id)
				store.save(state)
				response = client.chat(
					message, system_override=system, tools=_AGENT_TOOL_SCHEMAS,
					tool_results=tool_results, step_type="code_generation",
					on_chunk=_on_native_chunk,
				)
			except _ProviderSteer as steer:
				message = f"Nova instrucao do usuario, aplique-a agora:\n{steer}"
				tool_results = None
				state.message = message
				state.tool_results = None
				state.event("steered", instruction=str(steer)[:1000])
				store.save(state)
				continue
			except _BuildCancelled:
				state.status = "cancelled"
				state.event("cancelled", turn=turns)
				store.save(state)
				return AgenticBuildResult(False, workdir, cancelled=True, error="build interrompida pelo usuario", tokens=tokens, checkpoint_path=store.path(state.run_id), trace=state.trace)
			turns += 1
			tokens += int(response.tokens_used or 0)
			state.turn = turns
			state.tokens = tokens
			state.client_history = export_client_history(client)
			state.event("model_call_finished", turn=turns, tool_calls=len(response.tool_calls), tokens=int(response.tokens_used or 0))
			last_content = response.content or last_content
			if not response.tool_calls:
				current_files = _coletar_arquivos(workdir)
				if progress_callback:
					progress_callback(
						"A rodada do agente terminou. O NVDAStudio está executando "
						"validações independentes."
					)
				passed_now, report_now = (
					_run_gates(workdir, current_files)
					if current_files else (False, "nenhum arquivo produzido")
				)
				if passed_now:
					if progress_callback:
						progress_callback("As validações independentes foram aprovadas.")
					break
				if corrections >= correction_rounds:
					break
				corrections += 1
				state.corrections = corrections
				if progress_callback:
					progress_callback(
						f"As validações independentes encontraram problemas. "
						f"Iniciando a correção automática {corrections} de {correction_rounds}."
					)
				message = (
					"A verificacao deterministica reprovou o addon. Corrija os arquivos "
					"existentes, valide novamente e so entao conclua. Problemas:\n" + report_now
				)
				tool_results = None
				continue
			tool_results = []
			turn_signatures: list[str] = []
			for call in response.tool_calls:
				name, arguments, call_id = _native_call_parts(call)
				signature = json.dumps([name, arguments], ensure_ascii=False, sort_keys=True, default=str)
				turn_signatures.append(signature)
				if progress_callback:
					progress_callback(f"Vou usar a ferramenta {name} para realizar esta etapa.")
				output = execute_agent_tool(tool_gateway, name, arguments)
				try:
					tool_ok = not bool(json.loads(output).get("error"))
				except (ValueError, AttributeError):
					tool_ok = False
				state.event("tool_result", tool=name, call_id=call_id, success=tool_ok)
				tool_results.append({"tool_call_id": call_id, "content": output})
			batch_signature = "\n".join(turn_signatures)
			previous_batches = [
				event.get("signature") for event in state.trace
				if event.get("kind") == "tool_batch"
			]
			state.event("tool_batch", signature=batch_signature[:8000])
			if len(previous_batches) >= 2 and previous_batches[-2:] == [batch_signature, batch_signature]:
				state.event("loop_detected", turn=turns)
				last_content = "Loop de ferramentas repetidas interrompido pelo detector determinístico."
				break
			message = "Continue o trabalho usando os resultados das ferramentas."
			state.message = message
			state.tool_results = tool_results
			state.client_history = export_client_history(client)
			store.save(state)
	except Exception as exc:
		state.status = "failed"
		state.event("failed", error=str(exc)[:2000])
		store.save(state)
		return AgenticBuildResult(False, workdir, tokens=tokens, error=f"{provider}: {exc}", checkpoint_path=store.path(state.run_id), trace=state.trace)

	files = _coletar_arquivos(workdir)
	has_manifest, has_entry, syntax_ok = _validar_basico(workdir, files)
	passed, report = _run_gates(workdir, files) if files else (False, "nenhum arquivo produzido")
	success = bool(files) and has_manifest and has_entry and syntax_ok and passed
	if progress_callback and not passed:
		progress_callback(
			"As validações independentes ainda encontraram problemas; "
			"a entrega não será marcada como concluída."
		)
	state.status = "completed" if success else "failed"
	state.event("run_finished", success=success, gate_report=report[:4000])
	state.client_history = export_client_history(client)
	store.save(state)
	return AgenticBuildResult(
		success, workdir, files=files, has_manifest=has_manifest,
		has_entry_point=has_entry, py_syntax_ok=syntax_ok, returncode=0 if success else -1,
		tokens=tokens, stdout_tail=last_content[-2000:], error="" if success else report,
		execution_ok=passed, gate_report=report, rounds=corrections + 1,
		checkpoint_path=store.path(state.run_id), trace=state.trace,
	)
def _run_jsonrpc_session(
	cmd: list[str], *, workdir: str, prompt: str, system_prompt: str, timeout: int,
	progress_callback: Callable[[str], None] | None = None,
	cancel_event: "threading.Event | None" = None,
	steer_provider: Callable[[], str] | None = None,
	permission_callback: Callable[[str, dict], bool] | None = None,
	ask_user_callback: Callable[[list[str]], list[str]] | None = None,
) -> tuple[int, str, str]:
	"""Executa uma sessão Droid multi-turn sobre JSON-RPC.

	A sessão permanece viva durante cada rodada. O callback de steer pode
	interromper o turno atual e enviar a nova instrução sem destruir o contexto
	ou reiniciar o trabalho do zero.
	"""
	proc = subprocess.Popen(
		cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
		text=True, encoding="utf-8", errors="replace", cwd=workdir,
		creationflags=CREATE_NO_WINDOW,
	)
	errors: list[str] = []
	def drain_errors():
		if proc.stderr is not None:
			for line in proc.stderr:
				errors.append(line)
	reader = threading.Thread(target=drain_errors, daemon=True)
	reader.start()
	try:
		code, output, error = _exchange_jsonrpc(
			proc, cmd=cmd, workdir=workdir, prompt=prompt, system_prompt=system_prompt,
			timeout=timeout, progress_callback=progress_callback, cancel_event=cancel_event,
			steer_provider=steer_provider, permission_callback=permission_callback,
			ask_user_callback=ask_user_callback,
		)
	finally:
		if proc.poll() is None:
			proc.kill()
		proc.wait()
		reader.join(timeout=2)
		for stream in (proc.stdin, proc.stdout, proc.stderr):
			if stream is not None:
				try:
					stream.close()
				except OSError:
					_logger.debug("[AGENTIC] canal ja fechado")
	return code, output, error or "".join(errors)[-2000:]


def _exchange_jsonrpc(
	proc, *, cmd: list[str], workdir: str, prompt: str, system_prompt: str, timeout: int,
	progress_callback: Callable[[str], None] | None = None,
	cancel_event: threading.Event | None = None,
	steer_provider: Callable[[], str] | None = None,
	permission_callback: Callable[[str, dict], bool] | None = None,
	ask_user_callback: Callable[[list[str]], list[str]] | None = None,
) -> tuple[int, str, str]:
	if proc.stdin is None or proc.stdout is None:
		proc.kill()
		return proc.returncode or -1, "", "Droid RPC sem canais de entrada/saída."

	linhas: list[str] = []
	eventos: queue.Queue[dict | str] = queue.Queue()
	stdin = proc.stdin

	def _ler_saida() -> None:
		assert proc.stdout is not None
		for linha in proc.stdout:
			texto = linha.strip()
			if not texto:
				continue
			linhas.append(texto)
			try:
				eventos.put(json.loads(texto))
			except json.JSONDecodeError:
				eventos.put(texto)

	threading.Thread(target=_ler_saida, daemon=True).start()

	def _enviar(metodo: str, params: dict) -> str:
		request_id = str(uuid.uuid4())
		pedido = _rpc_request(request_id, metodo, params)
		stdin.write(json.dumps(pedido, ensure_ascii=False) + "\n")
		stdin.flush()
		return request_id

	init_id = _enviar("droid.initialize_session", {
		"machineId": f"nvdastudio-{os.getpid()}", "cwd": workdir,
		"modelId": cmd[cmd.index("-m") + 1], "interactionMode": "auto",
		"autonomyLevel": cmd[cmd.index("--auto") + 1],
		"systemPrompt": {"type": "preset", "preset": "droid", "append": system_prompt},
		"disableBuiltinSkills": False,
	})
	init_deadline = time.time() + min(timeout, 60)
	while time.time() < init_deadline:
		if cancel_event is not None and cancel_event.is_set():
			raise _BuildCancelled()
		try:
			payload = eventos.get(timeout=0.25)
		except queue.Empty:
			if proc.poll() is not None:
				return -1, "\n".join(linhas), "Droid encerrou durante a inicialização da sessão."
			continue
		if isinstance(payload, dict) and str(payload.get("id")) == init_id:
			if payload.get("error") is not None:
				return -1, "\n".join(linhas), str(payload["error"])
			break
	else:
		proc.kill()
		proc.wait()
		return -1, "\n".join(linhas), "Tempo esgotado ao iniciar a sessão Droid."
	_enviar("droid.add_user_message", {"text": prompt})

	deadline = time.time() + timeout
	turn_interrupted = False
	steer_pending = ""
	completou = False
	while time.time() < deadline:
		if cancel_event is not None and cancel_event.is_set():
			try:
				_enviar("droid.interrupt_session", {})
			except (BrokenPipeError, OSError):
				pass
			proc.kill()
			proc.wait()
			raise _BuildCancelled()
		if not turn_interrupted and steer_provider is not None:
			try:
				steer_pending = (steer_provider() or "").strip()
			except Exception:  # pragma: no cover - ajuste é best-effort
				steer_pending = ""
			if steer_pending:
				_enviar("droid.interrupt_session", {})
				turn_interrupted = True
		try:
			payload = eventos.get(timeout=0.25)
		except queue.Empty:
			if proc.poll() is not None:
				break
			continue
		if progress_callback is not None and isinstance(payload, dict):
			try:
				progress_callback(json.dumps(payload, ensure_ascii=False))
			except Exception as exc:
				_logger.warning("[AGENTIC] callback de progresso falhou: %s", exc)
		if not isinstance(payload, dict):
			continue
		if payload.get("error"):
			return -1, "\n".join(linhas), str(payload["error"])
		if payload.get("method") in {"droid.request_permission", "droid.ask_user"}:
			if payload.get("method") == "droid.ask_user":
				resposta = _answer_questions(payload, ask_user_callback)
			else:
				tool_name, arguments = _permission_request_details(payload)
				approved = False
				if permission_callback is not None:
					try:
						params_permission = payload.get("params") or {}
						uses = params_permission.get("toolUses") or params_permission.get("tool_uses") or []
						if isinstance(uses, list) and uses:
							approved = all(permission_callback(*_permission_request_details(
								{"params": {"toolUses": [use]}}
							)) for use in uses)
						else:
							approved = bool(permission_callback(tool_name, arguments))
					except Exception:  # pragma: no cover - fail-closed
						approved = False
				resposta = {"outcome": _permission_outcome(payload, approved)}
			stdin.write(json.dumps({
				"jsonrpc": "2.0",
				"factoryApiVersion": "1.0.0",
				"factoryProtocolVersion": "1.193.0",
				"type": "response",
				"id": payload.get("id"),
				"result": resposta,
			}) + "\n")
			stdin.flush()
			continue
		params = payload.get("params")
		if not isinstance(params, dict):
			params = {}
		notificacao = params.get("notification", {})
		if not isinstance(notificacao, dict):
			notificacao = {}
		if notificacao.get("type") == "agent_turn_completed":
			if not steer_pending and steer_provider is not None:
				steer_pending = (steer_provider() or "").strip()
			if steer_pending:
				_enviar("droid.add_user_message", {"text": steer_pending})
				steer_pending = ""
				turn_interrupted = False
				continue
			if notificacao.get("reason") not in {None, "completed"}:
				return -1, "\n".join(linhas), "O turno do agente terminou sem concluir: " + str(notificacao.get("reason"))
			completou = True
			break
		if payload.get("type") == "result":
			completou = True
			break

	try:
		stdin.close()
	except OSError:
		pass
	if proc.poll() is None:
		try:
			proc.wait(timeout=5)
		except subprocess.TimeoutExpired:
			proc.kill()
			proc.wait()
	if not completou:
		return -1, "\n".join(linhas), "Sessão encerrada sem conclusão (timeout ou término inesperado)."
	return 0, "\n".join(linhas), ""


def _droid_once(
	request: str,
	workdir: str | None = None,
	*,
	model_id: str = "kimi-k2.7-code",
	autonomy: str = "medium",
	timeout: int = _DEFAULT_TIMEOUT,
	use_nvda_context: bool = True,
	extra_context: str = "",
	backend: AgenticBackend | None = None,
	progress_callback: Callable[[str], None] | None = None,
	cancel_event: "threading.Event | None" = None,
	steer_provider: Callable[[], str] | None = None,
	permission_callback: Callable[[str, dict], bool] | None = None,
	ask_user_callback: Callable[[list[str]], list[str]] | None = None,
) -> AgenticBuildResult:
	"""UMA rodada do motor agentico + validacao BASICA (manifest/entry/sintaxe).

	Nunca levanta excecao de execucao: degrada para AgenticBuildResult(success=
	False, error=...) -- mesma doutrina de code_sandbox. E o tijolo que o ciclo
	de correcao (Slice 2) repete a cada rodada. Cancelamento do usuario tambem vira
	resultado (cancelled=True), nao excecao.

	`backend` (lacuna #3): o motor agentico. None resolve o padrao (droid, ou o
	que NVDASTUDIO_AGENTIC_BACKEND pedir). Injetar um backend fake e o que prova,
	nos testes, que o loop nao depende do droid em si.
	"""
	if autonomy not in _AUTONOMIAS_VALIDAS:
		return AgenticBuildResult(
			success=False, workdir=workdir or "",
			error=f"autonomia invalida: {autonomy!r} (validas: {_AUTONOMIAS_VALIDAS})",
		)
	if backend is None:
		backend = get_backend()
	try:
		cli = backend.find()
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

	cmd = backend.build_command(
		cli, workdir=workdir, prompt_path=prompt_path,
		model_id=model_id, autonomy=autonomy,
	)
	_logger.info(
		"[AGENTIC] %s --auto %s -m %s cwd=%s", backend.name, autonomy, model_id, workdir,
	)

	t0 = time.time()
	try:
		if "--input-format" in cmd and "stream-jsonrpc" in cmd:
			with open(prompt_path, encoding="utf-8") as fh:
				prompt_text = fh.read()
			with open(sp_path, encoding="utf-8") as fh:
				system_prompt_text = fh.read()
			returncode, stdout, stderr = _run_jsonrpc_session(
				cmd, workdir=workdir, prompt=prompt_text,
				system_prompt=system_prompt_text, timeout=timeout,
				progress_callback=progress_callback, cancel_event=cancel_event,
				steer_provider=steer_provider, permission_callback=permission_callback, ask_user_callback=ask_user_callback,
			)
		else:
			returncode, stdout, stderr = _run_streaming(
				cmd, workdir=workdir, timeout=timeout, progress_callback=progress_callback,
				cancel_event=cancel_event,
			)
	except _BuildCancelled:
		return AgenticBuildResult(
			success=False, workdir=workdir, duration_seconds=time.time() - t0,
			cancelled=True, error="build interrompida pelo usuario",
		)
	except subprocess.TimeoutExpired:
		return AgenticBuildResult(
			success=False, workdir=workdir, duration_seconds=time.time() - t0,
			error=f"{backend.name} excedeu {timeout}s no modo agentico",
		)
	except OSError as exc:
		return AgenticBuildResult(
			success=False, workdir=workdir, duration_seconds=time.time() - t0,
			error=f"nao foi possivel executar o {backend.name}: {exc}",
		)

	dur = time.time() - t0
	# Remove os arquivos de prompt antes de coletar (nao contam como saida).
	for p in (sp_path, prompt_path):
		try:
			os.remove(p)
		except OSError as exc:
			_logger.debug("[AGENTIC] nao removeu %s: %s", p, exc)

	files = _coletar_arquivos(workdir)
	_logger.info("[AGENTIC] arquivos coletados (%d) em %s: %s", len(files), workdir, files[:20])
	has_manifest, has_entry, syntax_ok = _validar_basico(workdir, files)
	success = returncode == 0 and has_manifest and has_entry and syntax_ok and bool(files)

	return AgenticBuildResult(
		success=success,
		workdir=workdir,
		files=files,
		has_manifest=has_manifest,
		has_entry_point=has_entry,
		py_syntax_ok=syntax_ok,
		returncode=returncode,
		duration_seconds=dur,
		tokens=backend.parse_tokens(stdout),
		stdout_tail=(stdout or "")[-2000:],
		stderr_tail=(stderr or "")[-2000:],
		error="" if success else _build_failure_detail(
			returncode, files, has_manifest, has_entry, syntax_ok, stderr, stdout,
		),
	)


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


def _project_source_files(files_dict: dict[str, str]) -> dict[str, str]:
	"""Remove dependencias vendorizadas das analises do codigo do addon.

	As bibliotecas em ``lib/`` continuam presentes nos testes de execucao e na
	validacao estrutural/de ABI. Ruff, mypy e os validadores de acessibilidade,
	por outro lado, devem julgar apenas o codigo mantido pelo autor do addon.
	"""
	return {
		rel: content
		for rel, content in files_dict.items()
		if rel.replace("\\", "/").split("/", 1)[0].lower() != "lib"
	}


def _typecheck_source_files(files_dict: dict[str, str]) -> dict[str, str]:
	"""Seleciona codigo de producao; testes possuem gate de execucao proprio."""
	return {
		rel: content
		for rel, content in files_dict.items()
		if not rel.replace("\\", "/").startswith("tests/")
		and not os.path.basename(rel).startswith("test_")
	}


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
	3. Testes gerados: se houver tests/test_*.py, executa a suite em subprocesso
	   isolado. Teste vermelho reprova a entrega e volta para a autocorrecao.
	4. Acessibilidade: _run_accessibility_gate roda os validadores AST (NVDA-019,
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
	files_dict = _read_files_dict(workdir, files)
	project_files_dict = _project_source_files(files_dict)
	typecheck_files_dict = _typecheck_source_files(project_files_dict)
	try:
		from .addon_builder import validate_addon_structure
		estruturais = validate_addon_structure(workdir)
	except Exception as exc:  # pragma: no cover - defesa
		_logger.warning("[AGENTIC] validacao estrutural indisponivel: %s", exc)
	else:
		for problema in estruturais:
			problemas.append(f"- {problema}")
	if has_entry and syntax_ok:
		try:
			from .code_sandbox import CodeSandbox
			sandbox = CodeSandbox(timeout_sec=15)
		except Exception as exc:  # pragma: no cover - defesa
			_logger.warning("[AGENTIC] sandbox indisponível: %s", exc)
			sandbox = None

		if sandbox is not None:
			try:
				lint_result = sandbox.lint_check(project_files_dict)
			except Exception as exc:  # pragma: no cover - defesa
				_logger.warning("[AGENTIC] Ruff indisponível: %s", exc)
			else:
				if not lint_result.success:
					detail = (
						lint_result.error or lint_result.stdout or lint_result.stderr
					).strip().replace("\n", " ")
					problemas.append(f"- RUFF encontrou defeitos no código: {detail[:800]}")

			try:
				type_result = sandbox.typecheck(typecheck_files_dict)
			except Exception as exc:  # pragma: no cover - defesa
				_logger.warning("[AGENTIC] mypy indisponível: %s", exc)
			else:
				if not type_result.success:
					detail = (
						type_result.error or type_result.stdout or type_result.stderr
					).strip().replace("\n", " ")
					problemas.append(
						f"- MYPY encontrou inconsistências de tipos: {detail[:800]}"
					)

			try:
				res = sandbox.validate_addon_execution(files_dict)
			except Exception as exc:  # pragma: no cover - defesa
				_logger.warning("[AGENTIC] gate de execução indisponível: %s", exc)
			else:
				if not res.success:
					detalhe = (res.error or res.stderr or "").strip().replace("\n", " ")
					problemas.append(
						f"- Erro de EXECUCAO real ao importar/instanciar o addon: {detalhe[:400]}"
					)

			test_relpaths = [
				f for f in files
				if f.endswith(".py")
				and (
					f.replace("\\", "/").startswith("tests/")
					or os.path.basename(f).startswith("test_")
				)
			]
			if test_relpaths:
				try:
					test_result = sandbox.run_test_suite(
						files_dict, test_relpaths, timeout=30,
					)
				except Exception as exc:  # pragma: no cover - defesa
					_logger.warning("[AGENTIC] executor de testes indisponível: %s", exc)
				else:
					if not test_result.success:
						detalhe = (
							test_result.error
							or test_result.stderr
							or test_result.stdout
							or "suite terminou com falha sem detalhes"
						).strip().replace("\n", " ")
						problemas.append(
							f"- TESTES automatizados falharam: {detalhe[:800]}"
						)
		# Gate de acessibilidade (so vale a pena com sintaxe valida).
		a11y = _run_accessibility_gate(project_files_dict)
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
	backend: AgenticBackend | None = None,
	progress_callback: Callable[[str], None] | None = None,
	cancel_event: "threading.Event | None" = None,
	steer_provider: Callable[[], str] | None = None,
	permission_callback: Callable[[str, dict], bool] | None = None,
	ask_user_callback: Callable[[list[str]], list[str]] | None = None,
	resume: bool = True,
	state_store: AgentCheckpointStore | None = None,
) -> AgenticBuildResult:
	"""Ponto de entrada publico do driver agentico.

	Roda a build e, se `correction_rounds` > 0, fecha o ciclo 'editar -> rodar ->
	corrigir' do Slice 2: apos cada build, roda os gates DETERMINISTICOS
	(code_sandbox + estrutura) e, se reprovarem, reinjeta os problemas no droid
	na MESMA pasta (que ja tem os arquivos) para ele corrigir -- ate passar ou
	esgotar as rodadas. `correction_rounds=0` (padrao) mantem o comportamento dos
	Slices 0/1 (build unica + validacao basica).

	DIRECAO AO VIVO:
	- `cancel_event`: se setado durante uma rodada, o processo e morto e a build
	  para (result.cancelled=True). Tambem e checado ENTRE rodadas.
	- `steer_provider`: consultado durante a sessão RPC; se devolver texto, o
	  turno atual é interrompido e a nova instrução continua no mesmo contexto.
	"""
	store = state_store or checkpoint_store
	checkpoint = store.find_resumable(request, "factory", model_id) if resume and workdir is None else None
	# Resolve o workdir UMA vez -- todas as rodadas de correcao compartilham a
	# mesma pasta (o droid corrige os arquivos que ja existem la).
	if workdir is None:
		workdir = checkpoint.workdir if checkpoint else tempfile.mkdtemp(prefix="nvdastudio_agentic_")
	checkpoint = checkpoint or store.new(request, "factory", model_id, workdir)
	checkpoint.event("run_started" if checkpoint.turn == 0 else "run_resumed", turn=checkpoint.turn)
	store.save(checkpoint)

	# Resolve o backend UMA vez -- todas as rodadas de correcao usam o mesmo motor.
	if backend is None:
		backend = get_backend()

	initial_request = request
	if checkpoint.turn:
		initial_request = (
			"Retome a execução anterior. Inspecione e preserve os arquivos que já "
			"existem no workspace antes de continuar. Pedido original:\n" + request
		)
	result = _droid_once(
		initial_request, workdir, model_id=model_id, autonomy=autonomy, timeout=timeout,
		use_nvda_context=use_nvda_context, extra_context=extra_context, backend=backend,
		progress_callback=progress_callback, cancel_event=cancel_event,
		steer_provider=steer_provider, permission_callback=permission_callback, ask_user_callback=ask_user_callback,
	)
	checkpoint.turn += 1
	checkpoint.tokens += result.tokens
	checkpoint.event("model_round_finished", turn=checkpoint.turn, success=result.success, files=len(result.files))
	checkpoint.status = "cancelled" if result.cancelled else "running"
	store.save(checkpoint)
	tokens_acumulados = result.tokens  # soma o custo de TODAS as rodadas
	if result.cancelled or correction_rounds <= 0 or not result.files:
		checkpoint.status = "cancelled" if result.cancelled else ("completed" if result.success else "failed")
		checkpoint.event("run_finished", success=result.success)
		store.save(checkpoint)
		result.checkpoint_path = store.path(checkpoint.run_id)
		result.trace = checkpoint.trace
		return result

	for rodada in range(1, correction_rounds + 1):
		# Cancelamento pedido ENTRE rodadas: para antes de gastar outra.
		if cancel_event is not None and cancel_event.is_set():
			result.cancelled = True
			result.tokens = tokens_acumulados
			checkpoint.status = "cancelled"
			checkpoint.event("cancelled", turn=checkpoint.turn)
			store.save(checkpoint)
			result.checkpoint_path = store.path(checkpoint.run_id)
			result.trace = checkpoint.trace
			return result
		passou, relatorio = _run_gates(result.workdir, result.files)
		result.execution_ok = passou
		result.gate_report = relatorio
		result.rounds = rodada
		result.tokens = tokens_acumulados

		# Direcao ao vivo: consome o ajuste que o usuario digitou durante a rodada.
		# Drenado ANTES do early-return: um ajuste pendente FORCA uma rodada mesmo
		# com o gate verde -- senao o addon fecharia antes do pedido ser aplicado
		# (a ressalva que tornava o soft-steer nao-confiavel). Se o gate passou e
		# nao ha ajuste, ai sim termina.
		ajuste = ""
		if steer_provider is not None:
			try:
				ajuste = (steer_provider() or "").strip()
			except Exception:  # pragma: no cover - steer e best-effort
				ajuste = ""

		if passou and not ajuste:
			if progress_callback:
				progress_callback("As validações independentes foram aprovadas.")
			result.success = result.success and passou
			checkpoint.status = "completed" if result.success else "failed"
			checkpoint.event("run_finished", success=result.success, gate_report=relatorio[:4000])
			store.save(checkpoint)
			result.checkpoint_path = store.path(checkpoint.run_id)
			result.trace = checkpoint.trace
			return result

		if passou:
			# Gate verde, rodada existe SO para incorporar o pedido do usuario.
			_logger.info("[AGENTIC] gate verde, mas ha ajuste do usuario -- rodada %d.", rodada + 1)
			correcao = (
				"O addon ja passa na verificacao. O usuario pediu este AJUSTE -- "
				"incorpore mantendo o que ja funciona:\n" + ajuste +
				"\n\nEdite os arquivos EXISTENTES (nao recomece do zero) e rode "
				"para confirmar que continua importando e instanciando sem erro."
			)
		else:
			_logger.info(
				"[AGENTIC] gate reprovou (rodada %d/%d), reinjetando no motor.",
				rodada, correction_rounds,
			)
			if progress_callback:
				progress_callback(
					f"As validações independentes encontraram problemas. "
					f"Iniciando a correção automática {rodada} de {correction_rounds}."
				)
			correcao = (
				"O addon que voce gerou no diretorio de trabalho atual NAO passou na "
				"verificacao. Problemas encontrados:\n" + relatorio +
				"\n\nCorrija os arquivos EXISTENTES (nao recomece do zero) ate que o "
				"addon importe e instancie sem erro. Rode os arquivos para confirmar."
			)
			if ajuste:
				_logger.info("[AGENTIC] ajuste do usuario dobrado na rodada %d.", rodada + 1)
				correcao = (
					"AJUSTE PEDIDO PELO USUARIO (prioridade -- incorpore agora):\n"
					+ ajuste + "\n\n" + correcao
				)
		result = _droid_once(
			correcao, result.workdir, model_id=model_id, autonomy=autonomy,
			timeout=timeout, use_nvda_context=use_nvda_context, extra_context=extra_context,
			backend=backend, progress_callback=progress_callback, cancel_event=cancel_event,
			steer_provider=steer_provider, permission_callback=permission_callback, ask_user_callback=ask_user_callback,
		)
		checkpoint.turn += 1
		checkpoint.corrections = rodada
		checkpoint.tokens += result.tokens
		checkpoint.event("correction_round_finished", turn=checkpoint.turn, round=rodada, success=result.success)
		store.save(checkpoint)
		tokens_acumulados += result.tokens
		result.rounds = rodada + 1
		if result.cancelled:
			result.tokens = tokens_acumulados
			checkpoint.status = "cancelled"
			checkpoint.event("cancelled", turn=checkpoint.turn)
			store.save(checkpoint)
			result.checkpoint_path = store.path(checkpoint.run_id)
			result.trace = checkpoint.trace
			return result

	# Gate final apos a ultima rodada de correcao.
	passou, relatorio = _run_gates(result.workdir, result.files)
	result.execution_ok = passou
	result.gate_report = relatorio
	result.tokens = tokens_acumulados
	result.success = result.success and passou
	if progress_callback:
		progress_callback(
			"As validações independentes foram aprovadas."
			if passou else
			"As validações independentes ainda encontraram problemas; "
			"a entrega não será marcada como concluída."
		)
	checkpoint.status = "completed" if result.success else "failed"
	checkpoint.event("run_finished", success=result.success, gate_report=relatorio[:4000])
	store.save(checkpoint)
	result.checkpoint_path = store.path(checkpoint.run_id)
	result.trace = checkpoint.trace
	return result
