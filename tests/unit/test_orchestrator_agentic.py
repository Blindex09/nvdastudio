"""Roteamento agentico no orchestrator apos a demolicao do staged (2026-09-06).

O agente e o UNICO caminho: _run_pipeline, _run_conversational_pipeline e
_run_until_success delegam a _run_pipeline_agentic. Sem flag, sem fallback staged.
run_agentic_build e mockado (sem droid real).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nvdastudio.core.orchestrator import (
	MODULE_VERSION, Orchestrator, _agentic_files_to_blocks,
)

assert MODULE_VERSION == "5.92.0"


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
			ok = o._run_pipeline_agentic("crie um addon")
		assert ok is True and len(recebidos) == 1
		res = recebidos[0]
		assert res.success is True and "```python" in res.step_results[0].output

	def test_gate_reprovado_entrega_mas_success_false(self, tmp_path):
		_prep(tmp_path)
		recebidos = []
		o = Orchestrator()
		o._on_complete = lambda r: recebidos.append(r)
		o._suppress_complete_callback = False
		build = _fake_build(tmp_path, execution_ok=False, gate_report="- Erro de EXECUCAO real", rounds=3)
		with patch("nvdastudio.builder.agentic_driver.run_agentic_build", return_value=build):
			ok = o._run_pipeline_agentic("x")
		assert ok is True
		assert recebidos[0].success is False and "EXECUCAO" in (recebidos[0].error or "")
		assert recebidos[0].total_retries == 2

	def test_fallback_quando_sem_arquivos(self, tmp_path):
		o = Orchestrator()
		o._on_complete = MagicMock()
		o._suppress_complete_callback = False
		with patch("nvdastudio.builder.agentic_driver.run_agentic_build",
				return_value=_fake_build(tmp_path, files=[])):
			ok = o._run_pipeline_agentic("x")
		assert ok is False
		o._on_complete.assert_not_called()


class TestDirecaoAoVivoNoOrchestrator:
	"""Interromper/redirecionar do orchestrator chegam ao driver agentico."""

	def test_cancelamento_vira_entrega_honesta(self, tmp_path):
		recebidos = []
		o = Orchestrator()
		o._on_complete = lambda r: recebidos.append(r)
		o._suppress_complete_callback = False
		build = _fake_build(tmp_path, cancelled=True, success=False)
		with patch("nvdastudio.builder.agentic_driver.run_agentic_build", return_value=build):
			ok = o._run_pipeline_agentic("x")
		assert ok is True
		assert recebidos[0].success is False
		assert "interrompida" in (recebidos[0].error or "").lower()

	def test_passa_cancel_event_e_steer_provider_ao_driver(self, tmp_path):
		_prep(tmp_path)
		o = Orchestrator()
		o._on_complete = lambda r: None
		o._suppress_complete_callback = False
		m = MagicMock(return_value=_fake_build(tmp_path))
		with patch("nvdastudio.builder.agentic_driver.run_agentic_build", m):
			o._run_pipeline_agentic("crie um addon")
		kwargs = m.call_args.kwargs
		assert kwargs["cancel_event"] is o._agentic_cancel
		assert kwargs["steer_provider"] == o._drenar_steer

	def test_cancel_pipeline_seta_o_event(self):
		o = Orchestrator()
		assert not o._agentic_cancel.is_set()
		o.cancel_pipeline()
		assert o._agentic_cancel.is_set()

	def test_steer_pipeline_enfileira_e_drena(self):
		o = Orchestrator()
		o.steer_pipeline("adicione um botao Limpar")
		o.steer_pipeline("e um atalho")
		drenado = o._drenar_steer()
		assert "adicione um botao Limpar" in drenado and "e um atalho" in drenado
		# consumido: a proxima drenagem vem vazia.
		assert o._drenar_steer() == ""

	def test_steer_vazio_e_ignorado(self):
		o = Orchestrator()
		o.steer_pipeline("   ")
		assert o._drenar_steer() == ""


class TestPipelinesDelegamAoAgente:
	def test_run_pipeline_e_agentico(self):
		o = Orchestrator()
		with patch.object(o, "_run_pipeline_agentic", return_value=True) as m:
			o._run_pipeline("crie um addon")
		m.assert_called_once_with("crie um addon")

	def test_run_pipeline_sem_arquivos_erro_honesto(self):
		o = Orchestrator()
		o._on_complete = MagicMock()
		with patch.object(o, "_run_pipeline_agentic", return_value=False):
			o._run_pipeline("x")
		res = o._on_complete.call_args[0][0]
		assert res.success is False and "nao conseguiu" in (res.error or "")

	def test_conversational_e_agentico(self):
		o = Orchestrator()
		with patch.object(o, "_run_pipeline_agentic", return_value=True) as m:
			o._run_conversational_pipeline("modifique meu addon")
		m.assert_called_once_with("modifique meu addon")

	def test_run_until_success_usa_o_agente(self):
		o = Orchestrator()
		o._on_complete = MagicMock()

		def _fake(q):
			o._last_result = SimpleNamespace(success=True, planejamento_degradado=False)
			return True

		with patch.object(o, "_run_pipeline_agentic", side_effect=_fake) as m:
			res = o._run_until_success("crie um addon")
		m.assert_called_once_with("crie um addon")
		assert res.success is True
