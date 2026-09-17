"""Regressões dos cinco reforços do runtime agêntico."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from nvdastudio.ai.model_router import extract_task_complexity
from nvdastudio.builder.agent_checkpoint import AgentCheckpointStore
from nvdastudio.builder.agent_evaluation import evaluate_agent_run
from nvdastudio.builder.agent_tools import (
	AgentToolContext, build_agent_tool_gateway, canonical_permission_name,
	get_agent_tool_schemas,
)
from nvdastudio.builder.agentic_driver import AgenticBuildResult, run_provider_agentic_build
from nvdastudio.builder.isolation import IsolationRunner


def test_complexidade_semantica_alimenta_o_roteador_ativo():
	from nvdastudio.core.orchestrator import _get_agentic_routes

	with (
		patch("nvdastudio.gui.settings_panel.get_llm_provider", return_value="factory"),
		patch("nvdastudio.gui.settings_panel.get_llm_model", return_value="alto"),
		patch("nvdastudio.ai.model_router.select_model", return_value="modelo-escolhido") as router,
	):
		route = _get_agentic_routes("pedido\n[TASK-COMPLEXITY: high]")[0]
		provider, model = route.provider, route.model_id
	assert (provider, model) == ("factory", "modelo-escolhido")
	assert router.call_args.kwargs["complexity"] == "high"
	assert router.call_args.kwargs["required_capabilities"] == frozenset({"tool_use"})


def test_complexidade_nao_e_adivinhada_por_palavra_chave():
	assert extract_task_complexity("faça um addon extremamente complexo") == "medium"
	assert extract_task_complexity("[TASK-COMPLEXITY: low]") == "low"


def test_catalogo_canonico_e_gateway_confinam_todos_os_adaptadores(tmp_path):
	names = {item["function"]["name"] for item in get_agent_tool_schemas()}
	assert names == {
		"list_workspace", "read_workspace_file", "write_workspace_file",
		"delete_workspace_file", "validate_addon", "run_addon_tests",
		"web_search", "ask_user",
	}
	context = AgentToolContext(
		workdir=str(tmp_path), list_files=lambda: [], validate=lambda: (True, "ok"),
		permission_callback=lambda *_args: True,
	)
	gateway = build_agent_tool_gateway(context)
	_result, error = gateway.call("write_workspace_file", {"path": "../escape.txt", "content": "x"})
	assert "fora do workspace" in error
	assert not (tmp_path.parent / "escape.txt").exists()
	assert canonical_permission_name("Edit") == "write_workspace_file"
	assert canonical_permission_name("Execute") == "run_addon_tests"


def test_checkpoint_redige_segredo_e_retomada_preserva_workspace(tmp_path, monkeypatch):
	store = AgentCheckpointStore(str(tmp_path / "states"))
	work = tmp_path / "work"
	work.mkdir()

	class FailingClient:
		_history = [{"role": "user", "content": "Authorization: segredo-supersecreto"}]
		def chat(self, *_args, **_kwargs):
			raise RuntimeError("queda simulada")

	monkeypatch.setattr("nvdastudio.ai.llm_factory.create_llm_client", lambda **_kwargs: FailingClient())
	failed = run_provider_agentic_build(
		"pedido token=segredo-supersecreto", provider="openai", model_id="m",
		workdir=str(work), use_nvda_context=False, state_store=store,
	)
	assert failed.success is False
	with open(failed.checkpoint_path, encoding="utf-8") as stream:
		checkpoint_text = stream.read()
	assert "segredo-supersecreto" not in checkpoint_text
	assert "[REDACTED]" in checkpoint_text

	class CompletingClient:
		_history = []
		def __init__(self):
			self.calls = 0
		def chat(self, *_args, **_kwargs):
			self.calls += 1
			if self.calls == 1:
				return SimpleNamespace(tokens_used=1, content="editando", tool_calls=[
					{"id": "m", "function": {"name": "write_workspace_file", "arguments": {"path": "manifest.ini", "content": "name=X\nsummary=X\nversion=1\nauthor=X\nminimumNVDAVersion=2025.1\nlastTestedNVDAVersion=2026.1\n"}}},
					{"id": "p", "function": {"name": "write_workspace_file", "arguments": {"path": "globalPlugins/X/__init__.py", "content": "import globalPluginHandler\nclass GlobalPlugin(globalPluginHandler.GlobalPlugin):\n\tpass\n"}}},
				])
			return SimpleNamespace(tokens_used=1, content="fim", tool_calls=[])

	monkeypatch.setattr("nvdastudio.ai.llm_factory.create_llm_client", lambda **_kwargs: CompletingClient())
	monkeypatch.setattr("nvdastudio.builder.agentic_driver._run_gates", lambda *_args: (True, ""))
	resumed = run_provider_agentic_build(
		"pedido token=segredo-supersecreto", provider="openai", model_id="m",
		use_nvda_context=False, state_store=store,
		permission_callback=lambda *_args: True,
	)
	assert resumed.success is True
	assert resumed.workdir == str(work)
	assert any(event["kind"] == "run_resumed" for event in resumed.trace)


def test_isolamento_docker_bloqueia_rede_e_escrita_no_host(tmp_path):
	runner = IsolationRunner()
	available, reason = runner.backend_available()
	if not available:
		pytest.skip(reason)
	script = tmp_path / "probe.py"
	script.write_text(
		"import socket\n"
		"try:\n socket.create_connection(('1.1.1.1', 53), .2); raise SystemExit('NETWORK_OPEN')\n"
		"except OSError: print('NETWORK_BLOCKED')\n"
		"try:\n open('/etc/nvdastudio-probe', 'w').write('x'); raise SystemExit('ROOT_WRITABLE')\n"
		"except OSError: print('ROOT_READ_ONLY')\n",
		encoding="utf-8",
	)
	result = runner.run_python(["probe.py"], workspace=str(tmp_path), timeout=10)
	assert result.isolated is True and result.returncode == 0
	assert "NETWORK_BLOCKED" in result.stdout
	assert "ROOT_READ_ONLY" in result.stdout


def test_eval_avalia_trajetoria_e_checkpoint_sem_autoavaliacao(tmp_path):
	checkpoint = tmp_path / "state.json"
	checkpoint.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
	good = AgenticBuildResult(
		True, str(tmp_path), files=["manifest.ini"], checkpoint_path=str(checkpoint),
		trace=[{"kind": "run_started"}, {"kind": "tool_result", "success": True}, {"kind": "run_finished"}],
	)
	assert evaluate_agent_run(good).passed is True
	bad = AgenticBuildResult(
		True, str(tmp_path), files=["manifest.ini"], checkpoint_path=str(checkpoint),
		trace=[{"kind": "run_started"}, {"kind": "tool_result", "success": False}, {"kind": "loop_detected"}],
	)
	evaluation = evaluate_agent_run(bad)
	assert evaluation.passed is False
	assert evaluation.trajectory == "loop_detected"
