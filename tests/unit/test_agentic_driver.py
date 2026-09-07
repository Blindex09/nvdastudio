"""Slice 0 do Caminho 3: driver do droid em modo agentico.

Sem chamada real ao droid -- subprocess mockado. Verifica a CONSTRUCAO do
comando (o contrato com o droid: --auto, --cwd, --append-system-prompt-file) e
o parsing/validacao do resultado. A rodada real via Factory e um spike manual,
nao um teste automatizado (gasta saldo).
"""
import types
from unittest.mock import patch

from nvdastudio.builder import agentic_driver as ad
from nvdastudio.builder.agentic_driver import MODULE_VERSION, run_agentic_build

assert MODULE_VERSION == "0.2.0"


def _fake_proc(returncode=0, stdout="ok", stderr=""):
	return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class TestConstrucaoDoComando:
	def test_comando_usa_auto_medium_cwd_e_system_prompt(self, tmp_path):
		capturado = {}

		def fake_run(cmd, **kwargs):
			capturado["cmd"] = cmd
			capturado["cwd"] = kwargs.get("cwd")
			# Simula o droid criando um addon minimo valido
			plug = tmp_path / "globalPlugins" / "Ola"
			plug.mkdir(parents=True)
			(plug / "__init__.py").write_text("import globalPluginHandler\n", encoding="utf-8")
			(tmp_path / "manifest.ini").write_text("name = Ola\n", encoding="utf-8")
			return _fake_proc()

		with patch.object(ad, "_achar_droid", return_value="droid"), \
			patch.object(ad.subprocess, "run", side_effect=fake_run):
			r = run_agentic_build("crie um addon", workdir=str(tmp_path), use_nvda_context=False)

		cmd = capturado["cmd"]
		assert cmd[0] == "droid" and cmd[1] == "exec"
		assert "--auto" in cmd and cmd[cmd.index("--auto") + 1] == "medium"
		assert "--cwd" in cmd and cmd[cmd.index("--cwd") + 1] == str(tmp_path)
		assert "--append-system-prompt-file" in cmd
		# NUNCA a flag insegura.
		assert "--skip-permissions-unsafe" not in cmd
		assert r.success is True
		assert r.has_manifest and r.has_entry_point and r.py_syntax_ok

	def test_autonomia_invalida_falha_sem_rodar_droid(self, tmp_path):
		with patch.object(ad, "_achar_droid", return_value="droid") as m_droid, \
			patch.object(ad.subprocess, "run") as m_run:
			r = run_agentic_build("x", workdir=str(tmp_path), autonomy="ultra")
		assert r.success is False and "autonomia invalida" in r.error
		m_droid.assert_not_called()
		m_run.assert_not_called()


class TestParsingDoResultado:
	def test_returncode_zero_mas_sem_manifest_nao_e_sucesso(self, tmp_path):
		def fake_run(cmd, **kwargs):
			(tmp_path / "globalPlugins").mkdir()
			(tmp_path / "globalPlugins" / "__init__.py").write_text("x=1\n", encoding="utf-8")
			return _fake_proc(returncode=0)

		with patch.object(ad, "_achar_droid", return_value="droid"), \
			patch.object(ad.subprocess, "run", side_effect=fake_run):
			r = run_agentic_build("x", workdir=str(tmp_path), use_nvda_context=False)
		assert r.success is False  # sem manifest.ini
		assert r.has_manifest is False

	def test_sintaxe_invalida_derruba_sucesso(self, tmp_path):
		def fake_run(cmd, **kwargs):
			plug = tmp_path / "globalPlugins" / "Ola"
			plug.mkdir(parents=True)
			(plug / "__init__.py").write_text("def f(:\n", encoding="utf-8")  # sintaxe quebrada
			(tmp_path / "manifest.ini").write_text("name = Ola\n", encoding="utf-8")
			return _fake_proc(returncode=0)

		with patch.object(ad, "_achar_droid", return_value="droid"), \
			patch.object(ad.subprocess, "run", side_effect=fake_run):
			r = run_agentic_build("x", workdir=str(tmp_path), use_nvda_context=False)
		assert r.py_syntax_ok is False and r.success is False

	def test_timeout_degrada_sem_excecao(self, tmp_path):
		import subprocess as _sp

		def fake_run(cmd, **kwargs):
			raise _sp.TimeoutExpired(cmd, kwargs.get("timeout", 1))

		with patch.object(ad, "_achar_droid", return_value="droid"), \
			patch.object(ad.subprocess, "run", side_effect=fake_run):
			r = run_agentic_build("x", workdir=str(tmp_path), timeout=5, use_nvda_context=False)
		assert r.success is False and "excedeu" in r.error

	def test_droid_ausente_degrada_sem_excecao(self, tmp_path):
		from nvdastudio.ai.factory_client import FactoryClientError

		with patch.object(ad, "_achar_droid", side_effect=FactoryClientError("droid nao encontrado")):
			r = run_agentic_build("x", workdir=str(tmp_path))
		assert r.success is False and "droid nao encontrado" in r.error


class TestContextoNVDA:
	"""Slice 1: injeta o MESMO contexto NVDA do pipeline staged como system prompt."""

	def test_sem_contexto_e_so_o_spec_compacto(self):
		sp = ad._build_system_prompt("addon de relogio", use_nvda_context=False)
		assert "COMPLEMENTO" in sp  # do _NVDA_SPEC embutido
		# Sem o contexto real, e curto (so o spec compacto).
		assert len(sp) < 5000

	def test_com_contexto_injeta_conhecimento_nvda_real(self):
		compacto = ad._build_system_prompt("addon de relogio", use_nvda_context=False)
		completo = ad._build_system_prompt("addon de relogio", use_nvda_context=True)
		# O contexto real (nvda_context + regras + principios + docs) e muito maior.
		assert len(completo) > len(compacto) * 3
		assert "COMPLEMENTO" in completo  # o spec de autoria continua presente

	def test_contexto_indisponivel_degrada_pro_spec(self):
		# Se o contexto NVDA explodir, a build NAO cai -- volta pro spec compacto.
		with patch.object(ad, "_build_nvda_context", side_effect=RuntimeError("boom")):
			sp = ad._build_system_prompt("x", use_nvda_context=True)
		assert "COMPLEMENTO" in sp  # seguiu com o spec, sem levantar


class TestColetaDeArquivos:
	def test_ignora_prompts_e_internos_do_droid(self, tmp_path):
		(tmp_path / "manifest.ini").write_text("name = X\n", encoding="utf-8")
		(tmp_path / "system-prompt.txt").write_text("spec", encoding="utf-8")
		(tmp_path / ".factory").mkdir()
		(tmp_path / ".factory" / "interno.json").write_text("{}", encoding="utf-8")
		files = ad._coletar_arquivos(str(tmp_path))
		assert "manifest.ini" in files
		assert "system-prompt.txt" not in files
		assert not any(f.startswith(".factory") for f in files)
