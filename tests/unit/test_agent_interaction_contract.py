"""Replay do contrato real de stream e da entrega na GUI, sem consumir API."""
import ast
import io
import json
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nvdastudio.builder import agentic_driver as driver
from nvdastudio.builder.iteration_workspace import prepare_iteration_workspace
from nvdastudio.core.orch_types import OrchestrationResult
from nvdastudio.gui import studio_dialog as gui
from nvdastudio.gui.agent_progress import AgentProgress
from nvdastudio.ai.clarifier import ClarificationResult


def event(kind, **values):
	return json.dumps({"method": "droid.session_notification", "params": {
		"notification": {"type": kind, **values},
	}})


def test_replay_messages_are_not_prompts_or_duplicate_tokens():
	p = AgentProgress()
	assert not p.consume(event("create_message", message={"id": "u", "role": "user", "content": [
		{"type": "text", "text": "MODO ITERATIVO\nimport wx\nsegredo"},
	]}))
	text = "Vou verificar o arquivo .nvda-addon e corrigir o menu."
	for chunk in (text[:24], text[24:31], text[31:]):
		assert not p.consume(event("assistant_text_delta", messageId="a", blockIndex=1, textDelta=chunk))
	assert p.consume(event("assistant_text_complete", messageId="a", blockIndex=1)) == [text]
	assert not p.consume(event("create_message", message={"id": "a", "role": "assistant", "content": [
		{"type": "thinking", "thinking": "privado"}, {"type": "text", "text": text},
	]}))
	finished = p.consume(event("agent_turn_completed", turnId="turn-1"))
	assert "validações independentes" in finished[0]
	assert not p.consume(event("agent_turn_completed", turnId="turn-1"))
	assert not p.consume("{malformed")
	assert not p.consume("[]")


def test_tools_are_correlated_without_printing_commands_or_output():
	p = AgentProgress()
	call = event("tool_call", toolUse={"id": "t1", "name": "Edit", "input": {"file_path": "manifest.ini", "new_str": "segredo"}})
	assert p.consume(call) == ["Editando arquivo (Edit): manifest.ini"]
	assert not p.consume(call)
	assert not p.consume(event("tool_progress_update", toolUseId="t1", update={"text": "import wx\nsegredo"}))
	assert "edição" in p.consume(event("tool_result", toolUseId="t1", isError=True))[0]


def test_execute_nao_anuncia_falha_quando_unittest_terminou_ok():
	p = AgentProgress()
	p.consume(event("tool_call", toolUse={"id": "run", "name": "Execute", "input": {}}))
	message = p.consume(event(
		"tool_result", toolUseId="run", isError=True,
		content="Error: exit code 1\nRan 60 tests in 0.093s\nOK\n[Process exited with code 1]",
	))[0]
	assert "resultado OK" in message
	assert "falhou" not in message


def test_execute_explica_teste_vermelho_como_resultado_corrigivel():
	p = AgentProgress()
	p.consume(event("tool_call", toolUse={"id": "run", "name": "Execute", "input": {}}))
	message = p.consume(event(
		"tool_result", toolUseId="run", isError=True,
		content="Ran 60 tests in 0.1s\nFAILED (errors=1)",
	))[0]
	assert "testes encontraram problemas" in message
	assert "continuará a correção" in message


def test_falhas_de_edicao_iguais_nao_inundam_a_conversa():
	p = AgentProgress()
	for tool_id in ("e1", "e2"):
		p.consume(event("tool_call", toolUse={"id": tool_id, "name": "Edit", "input": {}}))
	first = p.consume(event("tool_result", toolUseId="e1", isError=True, content="Error: Failed to edit file"))
	second = p.consume(event("tool_result", toolUseId="e2", isError=True, content="Error: Failed to edit file"))
	assert len(first) == 1
	assert second == []


def test_conclusao_do_executor_e_rotulada_como_provisoria():
	p = AgentProgress()
	out = p.consume(event("create_message", message={
		"id": "final", "role": "assistant",
		"content": [{"type": "text", "text": "Análise concluída. O addon está completo."}],
	}))
	assert "avaliação da rodada" in out[0]
	assert "gates independentes" in out[0]


def test_code_blocks_removed_before_visual_sanitizer():
	p = AgentProgress()
	msg = "Vou corrigir.\n```python\nimport wx\nsecret = 1\n```\nVerificado."
	out = p.consume(event("create_message", message={"id": "a", "role": "assistant", "content": [{"type": "text", "text": msg}]}))
	assert "import wx" not in out[0]
	assert "Verificado" in out[0]


@pytest.fixture
def dialog_class(monkeypatch):
	# wx não existe no runner. Executa os métodos reais da classe com base
	# object, sem alterar seus corpos e sem instanciar a janela nativa.
	node = next(n for n in ast.parse(Path(gui.__file__).read_text(encoding="utf-8")).body
		if isinstance(n, ast.ClassDef) and n.name == "NVDAStudioDialog")
	node.bases = [ast.Name(id="object", ctx=ast.Load())]
	module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
	ns = dict(vars(gui))
	monkeypatch.setattr(gui.wx, "CallAfter", lambda fn, *args: fn(*args))
	exec(compile(module, gui.__file__, "exec"), ns)
	return ns["NVDAStudioDialog"]


def test_actual_gui_progress_ignores_user_echo(dialog_class):
	d = object.__new__(dialog_class)
	d._chat_append = MagicMock()
	d._set_status = MagicMock()
	d._on_progress("EXECUTANDO", event("create_message", message={"role": "user", "content": [{"type": "text", "text": "prompt e codigo"}]}))
	d._chat_append.assert_not_called()
	d._on_progress("EXECUTANDO", event("create_message", message={"id": "a", "role": "assistant", "content": [{"type": "text", "text": "Vou verificar."}]}))
	d._chat_append.assert_called_once_with("Vou verificar.")


def test_actual_result_packages_authorized_request_once(dialog_class):
	d = object.__new__(dialog_class)
	for name in ("_enable_run_btn", "_run_pending_redirect", "_set_status", "_run_packaging_process", "_chat_append", "_update_input_label"):
		setattr(d, name, MagicMock())
	d._input = MagicMock()
	d._lbl_addon_loaded = MagicMock()
	d._current_addon_name = "old"
	d._package_after_current_build = True
	d._last_addon_folder = "stale_old_files"
	d._collect_all_blocks = lambda _: [
		{"language": "ini", "filename": "manifest.ini", "code": "name = example\nversion = 1.0\n"},
		{"language": "python", "filename": "globalPlugins/example/__init__.py", "code": "import globalPluginHandler\n"},
	]
	result = OrchestrationResult(plan_id="agentic", query="MODO ITERATIVO codigo privado", step_results=[], final_output="", success=True)
	d._display_result(result)
	out = "\n".join(str(c.args[0]) for c in d._chat_append.call_args_list)
	assert "MODO ITERATIVO" not in out
	assert out.count("Arquivos gerados") == 1
	assert "posso empacotar" not in out
	d._run_packaging_process.assert_called_once()
	assert d._last_addon_folder == ""


def test_result_contract_packages_even_if_transient_gui_flag_was_lost(dialog_class):
	"""Pedido de pacote viaja no resultado; nao depende da flag da janela."""
	d = object.__new__(dialog_class)
	for name in (
		"_enable_run_btn", "_run_pending_redirect", "_set_status",
		"_run_packaging_process", "_chat_append", "_update_input_label",
	):
		setattr(d, name, MagicMock())
	d._input = MagicMock()
	d._lbl_addon_loaded = MagicMock()
	d._current_addon_name = "X"
	d._package_after_current_build = False
	d._last_addon_folder = ""
	d._record_result_session = MagicMock()
	d._collect_all_blocks = lambda _: [
		{"language": "ini", "filename": "manifest.ini", "code": "name = X\n"},
		{"language": "python", "filename": "globalPlugins/X/__init__.py", "code": "x = 1\n"},
	]
	result = OrchestrationResult(
		plan_id="agentic", query="crie e empacote", step_results=[],
		final_output="", success=True, package_requested=True,
	)

	d._display_result(result)

	d._run_packaging_process.assert_called_once()
	d._record_result_session.assert_not_called()
	assert d._waiting_for_packaging_approval is False


def test_creation_passes_packaging_contract_to_orchestrator(dialog_class):
	d = object.__new__(dialog_class)
	d._package_after_current_build = True
	d._orchestrator = MagicMock()
	d._disable_run_btn_as_cancel = MagicMock()
	d._set_status = MagicMock()

	d._trigger_creation_pipeline("Criar addon completo")

	d._orchestrator.run_async.assert_called_once_with(
		"Criar addon completo", package_requested=True,
	)


def test_clarifier_architecture_reaches_orchestrator(dialog_class, monkeypatch):
	"""A decisão respondida pelo usuário precisa chegar literalmente ao Planner."""
	d = object.__new__(dialog_class)
	d._last_query = ""
	d._orchestrator = MagicMock()
	d._ask_clarification_inline = MagicMock(return_value=["Em todo o NVDA"])
	d._set_status = MagicMock()
	d._show_error = MagicMock()
	d._enable_run_btn = MagicMock()
	monkeypatch.setitem(dialog_class._clarify_and_run.__globals__, "analyze_query", lambda _query: ClarificationResult(
		needs_clarification=True,
		questions=["Você quer usar a voz em todo o NVDA ou apenas quando pedir?"],
		user_level="iniciante",
		addon_architecture="ambiguous",
	))

	d._clarify_and_run("crie um addon de voz")

	enriched = d._orchestrator.run_async.call_args.args[0]
	assert "Em todo o NVDA" in enriched
	assert "Arquitetura detectada: ambiguous" in enriched


def test_chat_router_failure_asks_beginner_friendly_question(dialog_class, monkeypatch):
	"""Falha do roteador principal não deve pedir só para tentar novamente."""
	d = object.__new__(dialog_class)
	d._loaded_addon_context = None
	d._chat_history = [{"role": "user", "text": "crie um addon"}]
	d._get_quick_chat_model = MagicMock(return_value="modelo")
	d._chat_finish = MagicMock()
	globals_ = dialog_class._process_chat_message.__globals__
	monkeypatch.setitem(globals_, "create_llm_client", MagicMock())
	monkeypatch.setattr(
		globals_["trajectory_compressor"],
		"compress",
		lambda *_args, **_kwargs: ([], SimpleNamespace(was_compressed=False)),
	)
	monkeypatch.setitem(
		globals_, "call_with_structured_output",
		MagicMock(side_effect=RuntimeError("serviço indisponível")),
	)

	d._process_chat_message("crie um addon")

	reply = d._chat_finish.call_args.args[0]
	assert "exemplo simples" in reply
	assert "tente novamente" not in reply.casefold()
	assert d._chat_history[-1]["role"] == "assistant"
	assert d._chat_history[-1]["text"] in reply


def test_iteration_copies_original_and_preserves_binary_assets(tmp_path):
	(tmp_path / "manifest.ini").write_text("name = x", encoding="utf-8")
	(tmp_path / "icon.png").write_bytes(b"\x89PNG")
	ctx = SimpleNamespace(source_path=str(tmp_path))
	copy = Path(prepare_iteration_workspace(ctx))
	assert (copy / "icon.png").read_bytes() == b"\x89PNG"
	(copy / "manifest.ini").write_text("name = changed", encoding="utf-8")
	assert (tmp_path / "manifest.ini").read_text() == "name = x"


def test_iteration_normalizes_root_readme_for_nvda(tmp_path):
	(tmp_path / "manifest.ini").write_text(
		"name = x\ndocFileName = readme.html\n", encoding="utf-8",
	)
	(tmp_path / "readme.html").write_text("<html>guia</html>", encoding="utf-8")
	ctx = SimpleNamespace(source_path=str(tmp_path))

	copy = Path(prepare_iteration_workspace(ctx))

	assert (copy / "doc" / "en" / "readme.html").read_text(encoding="utf-8") == (
		"<html>guia</html>"
	)


@pytest.mark.parametrize("valid", [True, False])
def test_actual_package_uses_final_sources_and_only_releases_valid_zip(dialog_class, tmp_path, monkeypatch, valid):
	from nvdastudio.builder.code_sandbox import CodeSandbox
	source = tmp_path / "source"
	source.mkdir()
	(source / "manifest.ini").write_text("name = example\nversion = 1.0\n", encoding="utf-8")
	plugin = source / "globalPlugins" / "example"
	plugin.mkdir(parents=True)
	(plugin / "__init__.py").write_text("latest = True\n", encoding="utf-8")
	(source / "icon.png").write_bytes(b"\x89PNG\x00\xff")
	(source / "old.nvda-addon").write_bytes(b"obsolete")
	(source / "test_ami.py").write_text("assert True\n", encoding="utf-8")
	(source / "e2e_tests").mkdir()
	(source / "e2e_tests" / "scenario.py").write_text("assert True\n", encoding="utf-8")
	out = tmp_path / "output"
	d = object.__new__(dialog_class)
	d._last_blocks = [{"filename": "unused"}]
	d._last_addon_folder = ""
	d._current_addon_name = "example"
	d._last_result = SimpleNamespace(artifact_dir=str(source), project_type="addon")
	d._instalar_dependencias_se_preciso = lambda *a: False
	d._auto_fix_structural_issues = lambda *a: ([], [])
	d._set_status = MagicMock()
	d._chat_append = MagicMock()
	d._show_error = MagicMock()
	ns = dialog_class._on_package.__globals__
	ns["get_output_dir"] = lambda: str(out)
	ns["fix_addon_structure"] = lambda *a: None
	monkeypatch.setattr(CodeSandbox, "validate_final_package", lambda *a: SimpleNamespace(success=valid, error="invalid", stderr="", stdout=""))
	d._on_package(None)
	final = out / "example.nvda-addon"
	assert final.exists() is valid
	if valid:
		with zipfile.ZipFile(final) as archive:
			assert archive.read("globalPlugins/example/__init__.py") == (plugin / "__init__.py").read_bytes()
			assert archive.read("icon.png") == b"\x89PNG\x00\xff"
			assert "old.nvda-addon" not in archive.namelist()
			assert "test_ami.py" not in archive.namelist()
			assert not any(name.startswith("e2e_tests/") for name in archive.namelist())
	assert [path.name for path in out.iterdir()] == (["example.nvda-addon"] if valid else [])
	assert (plugin / "__init__.py").read_text() == "latest = True\n"


def test_package_is_not_released_with_remaining_structural_problems(
	dialog_class, tmp_path, monkeypatch,
):
	from nvdastudio.builder.code_sandbox import CodeSandbox
	source = tmp_path / "source"
	source.mkdir()
	(source / "manifest.ini").write_text("name = example\n", encoding="utf-8")
	d = object.__new__(dialog_class)
	d._last_blocks = [{"filename": "unused"}]
	d._last_addon_folder = ""
	d._current_addon_name = "example"
	d._last_result = SimpleNamespace(artifact_dir=str(source), project_type="addon")
	d._instalar_dependencias_se_preciso = lambda *a: False
	d._auto_fix_structural_issues = lambda *a: ([], ["NVDA-003: traducao ausente"])
	d._set_status = MagicMock()
	d._chat_append = MagicMock()
	d._show_error = MagicMock()
	ns = dialog_class._on_package.__globals__
	out = tmp_path / "output"
	ns["get_output_dir"] = lambda: str(out)
	ns["fix_addon_structure"] = lambda *a: None
	monkeypatch.setattr(
		CodeSandbox, "validate_final_package",
		lambda *a: pytest.fail("quality gate do ZIP nao deve rodar apos falha estrutural"),
	)

	d._on_package(None)

	assert not (out / "example.nvda-addon").exists()
	assert "nao foi liberado" in d._chat_append.call_args.args[0]


def test_initial_chat_preserves_packaging_request(dialog_class):
	d = object.__new__(dialog_class)
	d._loaded_addon_context = None
	d._chat_history = []
	d._get_quick_chat_model = lambda: "test"
	d._chat_finish = MagicMock()
	d._trigger_creation_pipeline = MagicMock()
	ns = dialog_class._process_chat_message.__globals__
	ns["create_llm_client"] = MagicMock()
	ns["trajectory_compressor"] = SimpleNamespace(compress=lambda *a, **kw: ([], SimpleNamespace(was_compressed=False)))
	ns["call_with_structured_output"] = lambda *a, **kw: SimpleNamespace(content=json.dumps({
		"action": "run_pipeline", "message": "Vou corrigir.", "task_specification": "Corrigir o menu",
		"package_requested": True,
	}))
	d._process_chat_message("corrija esse addon e impacote")
	assert d._package_after_current_build is True
	request = d._trigger_creation_pipeline.call_args.args[0]
	assert request.startswith("Corrigir o menu")
	assert "[TASK-COMPLEXITY: medium]" in request
	assert "[ROUTING-PREFERENCE: balanced]" in request


def test_chat_schema_diz_que_limite_textual_nao_revoga_autorizacao(dialog_class):
	"""A Factory não pode transformar o limite do classificador em recusa."""
	ns = dialog_class._process_chat_message.__globals__
	schema = ns["_CHAT_RESPONSE_SCHEMA"]["json_schema"]["schema"]["properties"]
	action_help = schema["action"]["description"].casefold()
	message_help = schema["message"]["description"].casefold()
	assert "run_pipeline" in action_help
	assert "empacotar" in action_help
	assert "autoriza o encaminhamento" in action_help
	assert "autorizacao expressa" in message_help


def test_packaging_followup_with_tests_does_not_call_intent_llm(dialog_class):
	"""Regressao: "testes, execute e depois empacote" tinha roteamento claro,
	mas ainda chamava a IA e registrava duas falhas de JSON vazio no log."""
	d = object.__new__(dialog_class)
	d._package_after_current_build = False
	d._trigger_iterative_pipeline = MagicMock()
	d._run_packaging_process = MagicMock()
	d._get_quick_chat_model = MagicMock(side_effect=AssertionError("LLM nao deveria ser chamada"))

	d._process_packaging_decision("gere os testes, execute e depois empacote")

	assert d._package_after_current_build is True
	d._trigger_iterative_pipeline.assert_called_once_with(
		"gere os testes, execute e depois empacote"
	)
	d._run_packaging_process.assert_not_called()
	d._get_quick_chat_model.assert_not_called()


def test_accessible_text_preserves_filenames_and_shortcuts():
	from nvdastudio.utils.user_visible_text import sanitize_user_visible_text
	assert sanitize_user_visible_text("__init__.py NVDA+Shift+R") == "__init__.py NVDA+Shift+R"


def test_ask_user_returns_exact_question_identity():
	request = {"params": {"questions": [{"index": 7, "question": "Qual idioma?", "options": ["Português"]}]}}
	assert driver._answer_questions(request, lambda qs: ["Português"]) == {"answers": [
		{"index": 7, "question": "Qual idioma?", "answer": "Português"},
	]}
	assert driver._answer_questions(request, lambda qs: []) == {"cancelled": True, "answers": []}


class Writable(io.StringIO):
	def close(self):
		pass  # permite inspecionar as mensagens depois do fechamento do canal


def rpc_process(notifications):
	return SimpleNamespace(
		stdin=Writable(), stdout=io.StringIO("\n".join([json.dumps({"id": "request", "result": {}}), *notifications])),
		poll=lambda: None, wait=lambda **kwargs: 0, kill=MagicMock(), returncode=0,
	)


def test_rpc_answers_permissions_and_questions_then_finishes(monkeypatch):
	monkeypatch.setattr(driver.uuid, "uuid4", lambda: "request")
	permission = json.dumps({"method": "droid.request_permission", "id": "permission", "params": {
		"toolUses": [{"name": "Edit", "input": {"path": "a"}}, {"name": "Execute", "input": {"command": "test"}}],
		"options": [{"value": "proceed_once"}, {"value": "cancel"}],
	}})
	ask = json.dumps({"method": "droid.ask_user", "id": "ask", "params": {"questions": [{"index": 1, "question": "Idioma?"}]}})
	p = rpc_process([permission, ask, event("agent_turn_completed", reason="completed")])
	approved = []
	code, _, _ = driver._exchange_jsonrpc(p, cmd=["droid", "-m", "model", "--auto", "medium"], workdir=".", prompt="x", system_prompt="x", timeout=2,
		permission_callback=lambda name, args: approved.append(name) or name != "Execute", ask_user_callback=lambda qs: ["pt"])
	assert code == 0
	assert approved == ["Edit", "Execute"]
	responses = [json.loads(line) for line in p.stdin.getvalue().splitlines()]
	assert next(r for r in responses if r.get("id") == "permission")["result"]["outcome"] == "cancel"
	assert next(r for r in responses if r.get("id") == "ask")["result"]["answers"][0]["answer"] == "pt"


def test_rpc_cancellation_is_not_a_generation_error(monkeypatch):
	monkeypatch.setattr(driver.uuid, "uuid4", lambda: "request")
	p = rpc_process([])
	cancel = threading.Event()
	cancel.set()
	with pytest.raises(driver._BuildCancelled):
		driver._exchange_jsonrpc(p, cmd=["droid", "-m", "model", "--auto", "medium"], workdir=".", prompt="x", system_prompt="x", timeout=2, cancel_event=cancel)


def test_rpc_steering_interrupts_and_sends_instruction_in_same_session(monkeypatch):
	monkeypatch.setattr(driver.uuid, "uuid4", lambda: "request")
	p = rpc_process([event("agent_turn_completed", reason="interrupted"), event("agent_turn_completed", reason="completed")])
	steers = iter(["Corrija o menu", "", "", ""])
	code, _, _ = driver._exchange_jsonrpc(p, cmd=["droid", "-m", "model", "--auto", "medium"], workdir=".", prompt="inicial", system_prompt="x", timeout=2, steer_provider=lambda: next(steers, ""))
	assert code == 0
	sent = [json.loads(line) for line in p.stdin.getvalue().splitlines()]
	assert [r["params"]["text"] for r in sent if r.get("method") == "droid.add_user_message"] == ["inicial", "Corrija o menu"]
	assert sum(r.get("method") == "droid.initialize_session" for r in sent) == 1
	assert sum(r.get("method") == "droid.interrupt_session" for r in sent) == 1


def test_rpc_failure_drains_stderr_and_cleans_process(monkeypatch):
	monkeypatch.setattr(driver.uuid, "uuid4", lambda: "request")
	p = rpc_process([json.dumps({"id": "msg", "error": {"message": "Falha do provedor"}})])
	p.stderr = io.StringIO("diagnostic\n" * 10000)
	monkeypatch.setattr(driver.subprocess, "Popen", lambda *a, **kw: p)
	code, _, error = driver._run_jsonrpc_session(["droid", "-m", "model", "--auto", "medium"], workdir=".", prompt="x", system_prompt="x", timeout=2)
	assert code != 0
	assert "Falha do provedor" in error
	p.kill.assert_called()
	assert p.stderr.closed


def test_agent_run_releases_running_state(monkeypatch):
	from nvdastudio.core.orchestrator import Orchestrator
	o = Orchestrator()
	o._run_until_complete = MagicMock()
	monkeypatch.setattr(threading, "Thread", lambda target, args, **kw: SimpleNamespace(start=lambda: target(*args)))
	o.run_async("primeira")
	assert not o._running
	o.run_async("segunda")
	assert o._run_until_complete.call_count == 2


def test_iteration_extracts_package_assets_and_rejects_traversal(tmp_path):
	package = tmp_path / "addon.nvda-addon"
	with zipfile.ZipFile(package, "w") as z:
		z.writestr("manifest.ini", "name = x")
		z.writestr("lib/resource.bin", b"\x00\xff")
	copy = Path(prepare_iteration_workspace(SimpleNamespace(source_path=str(package))))
	assert (copy / "lib/resource.bin").read_bytes() == b"\x00\xff"
	with zipfile.ZipFile(package, "w") as z:
		z.writestr("../escape", "bad")
	with pytest.raises(ValueError, match="fora"):
		prepare_iteration_workspace(SimpleNamespace(source_path=str(package)))
