from datetime import datetime


class TestCalculateNextRunNaoLevantaNameError:
	def test_intervalo_fixo_calcula_proxima_execucao(self):
		from nvdastudio.utils.scheduler import Scheduler

		scheduler = Scheduler()
		antes = datetime.now()
		resultado = scheduler._calculate_next_run("interval:60")

		assert resultado != ""
		proxima = datetime.fromisoformat(resultado)
		assert proxima > antes

	def test_fallback_sem_croniter_calcula_proxima_execucao(self, monkeypatch):
		import nvdastudio.utils.scheduler as scheduler_module

		monkeypatch.setattr(scheduler_module, "_CRONITER_AVAILABLE", False)
		monkeypatch.setattr(scheduler_module, "croniter", None)

		scheduler = scheduler_module.Scheduler()
		antes = datetime.now()
		resultado = scheduler._calculate_next_run("0 0 * * *")

		assert resultado != ""
		proxima = datetime.fromisoformat(resultado)
		assert proxima > antes


class TestBackupSessionsHandlerNaoLevantaAttributeError:
	"""
	Bug real de auditoria: backup_sessions_handler chamava
	memory.get_recent_sessions(...), metodo que nunca existiu em SessionMemory
	(o metodo real e get_recent). AttributeError garantido na primeira vez que
	o scheduler rodasse a tarefa nativa de backup de sessoes.
	"""

	def test_backup_gera_arquivo_json_valido(self, tmp_path, monkeypatch):
		import json
		import nvdastudio.memory.session_memory as sm_module
		import nvdastudio.utils.scheduler as scheduler_module

		monkeypatch.setattr(sm_module, "_DB_PATH", str(tmp_path / "mem.json"))
		monkeypatch.setattr(scheduler_module, "_LOGS_DIR", tmp_path)

		mem = sm_module.SessionMemory()
		mem.save_session(
			query="criar addon de clipboard",
			addon_name="clipboard_addon",
			plan_id="p1",
			steps_ok=3,
			steps_total=3,
			retries=0,
			success=True,
			summary="ok",
		)

		result = scheduler_module.backup_sessions_handler(task=None)

		assert result["sessions_count"] >= 1
		backup_path = scheduler_module.Path(result["backup_file"])
		data = json.loads(backup_path.read_text(encoding="utf-8"))
		assert len(data) >= 1
		assert data[0]["query"] == "criar addon de clipboard"

		mem.close()
