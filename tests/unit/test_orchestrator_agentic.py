"""Roteamento e entrega do unico pipeline agentico do orchestrator."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nvdastudio.core.orchestrator import (
	MODULE_VERSION, Orchestrator, _agentic_files_to_blocks,
)

assert MODULE_VERSION == "7.0.0"


def _route(provider="factory", model="auto", reason="rota de teste"):
	return SimpleNamespace(
		provider=provider,
		model_id=model,
		reason=reason,
		to_dict=lambda: {
			"provider": provider,
			"model_id": model,
			"reason": reason,
		},
	)


@pytest.fixture(autouse=True)
def _factory_por_padrao(monkeypatch):
	"""Casos legados deste arquivo exercitam o backend Droid."""
	monkeypatch.setattr(
		"nvdastudio.core.orchestrator._get_agentic_routes",
		lambda _request="": [_route()],
	)


class TestArquivosParaBlocos:
	def test_gera_fences_com_linguagem_certa(self, tmp_path):
		(tmp_path / "manifest.ini").write_text("name = X\n", encoding="utf-8")
		p = tmp_path / "globalPlugins" / "X"
		p.mkdir(parents=True)
		(p / "__init__.py").write_text("import globalPluginHandler\n", encoding="utf-8")
		blocks = _agentic_files_to_blocks(
			str(tmp_path), ["manifest.ini", "globalPlugins/X/__init__.py"],
		)
		assert "```ini:manifest.ini" in blocks
		assert "```python:globalPlugins/X/__init__.py" in blocks
		assert "import globalPluginHandler" in blocks


def _fake_build(tmp_path, **kw):
	base = dict(
		files=["manifest.ini", "globalPlugins/X/__init__.py"],
		workdir=str(tmp_path), execution_ok=True, gate_report="", rounds=1, success=True,
	)
	base.update(kw)
	return SimpleNamespace(**base)


def _prep(tmp_path):
	(tmp_path / "manifest.ini").write_text("name = X\n", encoding="utf-8")
	p = tmp_path / "globalPlugins" / "X"
	p.mkdir(parents=True)
	(p / "__init__.py").write_text("import globalPluginHandler\n", encoding="utf-8")


class TestRunPipelineAgentico:
	def test_entrega_quando_driver_produz(self, tmp_path):
		_prep(tmp_path)
		recebidos = []
		o = Orchestrator()
		o._on_complete = lambda r: recebidos.append(r)
		o._suppress_complete_callback = False
		with patch("nvdastudio.builder.agentic_driver.run_agentic_build",
				return_value=_fake_build(tmp_path)):
			o._run_agent("crie um addon")
		assert len(recebidos) == 1
		res = recebidos[0]
		assert res.success is True and "```python" in res.step_results[0].output
		assert res.artifact_files == ["manifest.ini", "globalPlugins/X/__init__.py"]

	def test_factory_alto_passa_auto_model_ao_driver(self, tmp_path):
		"""A seleção automática precisa chegar ao caminho agêntico real."""
		_prep(tmp_path)
		o = Orchestrator()
		o._on_complete = lambda _result: None
		o._suppress_complete_callback = False
		m = MagicMock(return_value=_fake_build(tmp_path))
		with (
			patch("nvdastudio.builder.agentic_driver.run_agentic_build", m),
			patch("nvdastudio.gui.settings_panel.get_llm_provider", return_value="factory"),
			patch("nvdastudio.gui.settings_panel.get_llm_model", return_value="alto"),
		):
			o._run_agent("crie um addon complexo")

		assert m.call_args.kwargs["model_id"] == "auto"
		assert o._last_result.step_results[0].model_used == "factory::auto"

	@pytest.mark.parametrize("provider", ["ollama", "openai", "gemini", "anthropic", "xai"])
	def test_demais_provedores_usam_motor_agentico_nativo(self, tmp_path, monkeypatch, provider):
		_prep(tmp_path)
		o = Orchestrator()
		o._on_complete = lambda _result: None
		o._suppress_complete_callback = False
		native = MagicMock(return_value=_fake_build(tmp_path))
		droid = MagicMock(side_effect=AssertionError("Droid nao deve executar outro provedor"))
		monkeypatch.setattr(
			"nvdastudio.core.orchestrator._get_agentic_routes",
			lambda _request="": [_route(provider, f"modelo-{provider}")],
		)
		with (
			patch("nvdastudio.builder.agentic_driver.run_provider_agentic_build", native),
			patch("nvdastudio.builder.agentic_driver.run_agentic_build", droid),
		):
			o._run_agent("crie um addon")
		assert native.call_args.kwargs["provider"] == provider
		assert native.call_args.kwargs["model_id"] == f"modelo-{provider}"
		assert o._last_result.step_results[0].model_used == f"{provider}::modelo-{provider}"

	def test_studio_faz_failover_preservando_workspace(self, tmp_path, monkeypatch):
		_prep(tmp_path)
		o = Orchestrator()
		o._on_complete = lambda _result: None
		o._suppress_complete_callback = False
		monkeypatch.setattr(
			"nvdastudio.core.orchestrator._get_agentic_routes",
			lambda _request="": [
				_route("openai", "modelo-a"),
				_route("gemini", "modelo-b"),
			],
		)
		first = _fake_build(
			tmp_path, success=False, execution_ok=False,
			gate_report="teste falhou",
		)
		second = _fake_build(tmp_path)
		native = MagicMock(side_effect=[first, second])
		with patch(
			"nvdastudio.builder.agentic_driver.run_provider_agentic_build",
			native,
		):
			o._run_agent("crie um addon")

		assert native.call_count == 2
		assert native.call_args_list[1].kwargs["workdir"] == str(tmp_path)
		assert o._last_result.success is True
		assert o._last_result.selected_provider == "gemini"
		assert len(o._last_result.routing_decisions) == 2

	def test_propaga_pedido_de_pacote_no_resultado(self, tmp_path):
		_prep(tmp_path)
		recebidos = []
		o = Orchestrator()
		o._on_complete = lambda result: recebidos.append(result)
		o._suppress_complete_callback = False
		o._package_requested = True
		with patch(
			"nvdastudio.builder.agentic_driver.run_agentic_build",
			return_value=_fake_build(tmp_path),
		):
			o._run_agent("crie, teste e empacote")
		assert recebidos[0].package_requested is True

	def test_gate_reprovado_entrega_mas_success_false(self, tmp_path):
		_prep(tmp_path)
		recebidos = []
		o = Orchestrator()
		o._on_complete = lambda r: recebidos.append(r)
		o._suppress_complete_callback = False
		build = _fake_build(tmp_path, execution_ok=False, gate_report="- Erro de EXECUCAO real", rounds=3)
		with patch("nvdastudio.builder.agentic_driver.run_agentic_build", return_value=build):
			o._run_agent("x")
		assert recebidos[0].success is False and "EXECUCAO" in (recebidos[0].error or "")
		assert recebidos[0].total_retries == 2

	def test_fallback_quando_sem_arquivos(self, tmp_path):
		o = Orchestrator()
		o._on_complete = MagicMock()
		o._suppress_complete_callback = False
		with patch("nvdastudio.builder.agentic_driver.run_agentic_build",
				return_value=_fake_build(tmp_path, files=[])):
			o._run_agent("x")
		o._on_complete.assert_called_once_with(o._last_result)
		assert o._last_result.success is False
		assert o._last_result.error


class TestDirecaoAoVivoNoOrchestrator:
	"""Interromper/redirecionar do orchestrator chegam ao driver agentico."""

	def test_cancelamento_vira_entrega_honesta(self, tmp_path):
		recebidos = []
		o = Orchestrator()
		o._on_complete = lambda r: recebidos.append(r)
		o._suppress_complete_callback = False
		build = _fake_build(tmp_path, cancelled=True, success=False)
		with patch("nvdastudio.builder.agentic_driver.run_agentic_build", return_value=build):
			o._run_agent("x")
		assert recebidos[0].success is False
		assert "interrompida" in (recebidos[0].error or "").lower()

	def test_passa_cancel_event_e_steer_provider_ao_driver(self, tmp_path):
		_prep(tmp_path)
		o = Orchestrator()
		o._on_complete = lambda r: None
		o._suppress_complete_callback = False
		m = MagicMock(return_value=_fake_build(tmp_path))
		with patch("nvdastudio.builder.agentic_driver.run_agentic_build", m):
			o._run_agent("crie um addon")
		kwargs = m.call_args.kwargs
		assert kwargs["cancel_event"] is o._agentic_cancel
		assert kwargs["steer_provider"] == o._drain_steer

	def test_cancel_pipeline_seta_o_event(self):
		o = Orchestrator()
		assert not o._agentic_cancel.is_set()
		o.cancel_pipeline()
		assert o._agentic_cancel.is_set()

	def test_steer_pipeline_enfileira_e_drena(self):
		o = Orchestrator()
		o.steer_pipeline("adicione um botao Limpar")
		o.steer_pipeline("e um atalho")
		drenado = o._drain_steer()
		assert "adicione um botao Limpar" in drenado and "e um atalho" in drenado
		# consumido: a proxima drenagem vem vazia.
		assert o._drain_steer() == ""

	def test_steer_vazio_e_ignorado(self):
		o = Orchestrator()
		o.steer_pipeline("   ")
		assert o._drain_steer() == ""


class TestPipelineUnico:
	def test_run_until_complete_usa_o_agente(self):
		o = Orchestrator()
		o._on_complete = MagicMock()

		def _fake(q):
			o._last_result = SimpleNamespace(success=True)

		with patch.object(o, "_run_agent", side_effect=_fake) as m:
			res = o._run_until_complete("crie um addon")
		m.assert_called_once_with("crie um addon")
		assert res.success is True
