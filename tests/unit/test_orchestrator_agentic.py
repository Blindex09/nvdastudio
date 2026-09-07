"""Slice 3 do Caminho 3: roteamento agentico no orchestrator, atras de flag.

Sem chamada real ao droid -- run_agentic_build mockado. Verifica: a flag
(default OFF), a conversao de arquivos->blocos, a entrega via on_complete, o
fallback pro staged quando o agentico nao produz, e o desvio no _run_pipeline.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nvdastudio.core.orchestrator import (
	MODULE_VERSION, Orchestrator, _agentic_mode_enabled, _agentic_files_to_blocks,
)

assert MODULE_VERSION == "5.90.0"


class TestFlagAgentica:
	"""Slice 3.5: o agentico e o PADRAO -- opt-OUT, nao mais opt-in."""

	def test_default_agora_ligado(self, monkeypatch):
		# Sem a env var, o agentico esta LIGADO (o padrao de producao).
		monkeypatch.delenv("NVDASTUDIO_AGENTIC_MODE", raising=False)
		assert _agentic_mode_enabled() is True

	def test_desliga_so_com_valores_falsos(self, monkeypatch):
		for v in ("0", "false", "off", "no", "OFF", "No"):
			monkeypatch.setenv("NVDASTUDIO_AGENTIC_MODE", v)
			assert _agentic_mode_enabled() is False

	def test_valor_qualquer_mantem_ligado(self, monkeypatch):
		# So os valores de desligar desligam; qualquer outra coisa segue ligado.
		for v in ("1", "true", "on", "talvez", "sim"):
			monkeypatch.setenv("NVDASTUDIO_AGENTIC_MODE", v)
			assert _agentic_mode_enabled() is True


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


class TestPipelineAgentico:
	def _prep_workdir(self, tmp_path):
		(tmp_path / "manifest.ini").write_text("name = X\n", encoding="utf-8")
		p = tmp_path / "globalPlugins" / "X"
		p.mkdir(parents=True)
		(p / "__init__.py").write_text("import globalPluginHandler\n", encoding="utf-8")

	def test_entrega_quando_driver_produz(self, tmp_path):
		self._prep_workdir(tmp_path)
		recebidos = []
		o = Orchestrator()
		o._on_complete = lambda r: recebidos.append(r)
		o._suppress_complete_callback = False
		with patch("nvdastudio.builder.agentic_driver.run_agentic_build",
				return_value=_fake_build(tmp_path)):
			ok = o._run_pipeline_agentic("crie um addon")
		assert ok is True and len(recebidos) == 1
		res = recebidos[0]
		assert res.success is True
		assert res.step_results and "```python" in res.step_results[0].output

	def test_gate_reprovado_entrega_mas_success_false(self, tmp_path):
		self._prep_workdir(tmp_path)
		recebidos = []
		o = Orchestrator()
		o._on_complete = lambda r: recebidos.append(r)
		o._suppress_complete_callback = False
		build = _fake_build(tmp_path, execution_ok=False, gate_report="- Erro de EXECUCAO real", rounds=3)
		with patch("nvdastudio.builder.agentic_driver.run_agentic_build", return_value=build):
			ok = o._run_pipeline_agentic("x")
		assert ok is True  # entregou (tem arquivos), mesmo reprovado
		res = recebidos[0]
		assert res.success is False and "EXECUCAO" in (res.error or "")
		assert res.total_retries == 2  # rounds-1

	def test_fallback_quando_sem_arquivos(self, tmp_path):
		o = Orchestrator()
		o._on_complete = MagicMock()
		o._suppress_complete_callback = False
		build = _fake_build(tmp_path, files=[])
		with patch("nvdastudio.builder.agentic_driver.run_agentic_build", return_value=build):
			ok = o._run_pipeline_agentic("x")
		assert ok is False
		o._on_complete.assert_not_called()


class TestDesvioNoRunPipeline:
	def test_flag_ligada_desvia_pro_agentico(self, monkeypatch):
		monkeypatch.setenv("NVDASTUDIO_AGENTIC_MODE", "1")
		o = Orchestrator()
		with patch.object(o, "_run_pipeline_agentic", return_value=True) as m_ag, \
			patch.object(o, "_planner") as m_planner:
			o._run_pipeline("crie um addon")
		m_ag.assert_called_once_with("crie um addon")
		# desviou -> nunca criou plano staged
		m_planner.create_plan.assert_not_called()

	def test_flag_desligada_nao_chama_agentico(self, monkeypatch):
		# Opt-out explicito volta pro staged.
		monkeypatch.setenv("NVDASTUDIO_AGENTIC_MODE", "0")
		o = Orchestrator()
		# Curto-circuita o staged logo no create_plan (levanta -> except interno).
		o._planner = MagicMock()
		o._planner.create_plan.side_effect = RuntimeError("stop-staged")
		o._on_complete = MagicMock()
		with patch.object(o, "_run_pipeline_agentic") as m_ag:
			o._run_pipeline("x")
		m_ag.assert_not_called()

	def test_resume_nao_desvia_pro_agentico(self, monkeypatch):
		# Retomada (resume_plan) e conceito do staged -- nunca vai pro agentico.
		monkeypatch.setenv("NVDASTUDIO_AGENTIC_MODE", "1")
		o = Orchestrator()
		o._planner = MagicMock()
		o._planner.create_plan.side_effect = RuntimeError("stop-staged")
		o._on_complete = MagicMock()
		fake_plan = SimpleNamespace(steps=[], addon_name="X", dependencies=[], completed_message="")
		with patch.object(o, "_run_pipeline_agentic") as m_ag, \
			patch.object(o, "_aplicar_orcamento_por_complexidade"):
			o._run_pipeline("x", resume_plan=fake_plan)
		m_ag.assert_not_called()
