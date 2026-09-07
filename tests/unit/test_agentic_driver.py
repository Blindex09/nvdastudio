"""Slice 0 do Caminho 3: driver do droid em modo agentico.

Sem chamada real ao droid -- subprocess mockado. Verifica a CONSTRUCAO do
comando (o contrato com o droid: --auto, --cwd, --append-system-prompt-file) e
o parsing/validacao do resultado. A rodada real via Factory e um spike manual,
nao um teste automatizado (gasta saldo).
"""
import types
from unittest.mock import patch

from nvdastudio.builder import agentic_driver as ad
from nvdastudio.builder.agentic_driver import (
	MODULE_VERSION, run_agentic_build, AgenticBuildResult,
)

assert MODULE_VERSION == "0.5.0"


def _fake_proc(returncode=0, stdout="ok", stderr=""):
	return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class TestParseDroidTokens:
	"""Captura de tokens do envelope `droid exec -o json` (comparacao de custo)."""

	def test_soma_input_output_e_cache_creation_ignora_cache_read(self):
		import json
		env = json.dumps({"usage": {
			"input_tokens": 100, "output_tokens": 50,
			"cache_creation_input_tokens": 30, "cache_read_input_tokens": 9999,
		}})
		stdout = "log antes\n" + env + "\n"
		assert ad._parse_droid_tokens(stdout) == 180  # 100+50+30, sem os 9999

	def test_pega_a_ultima_linha_json_com_usage(self):
		import json
		stdout = "{\"nao_e_usage\": 1}\n" + json.dumps({"usage": {"input_tokens": 7}}) + "\n"
		assert ad._parse_droid_tokens(stdout) == 7

	def test_sem_json_devolve_zero(self):
		assert ad._parse_droid_tokens("apenas texto do droid\n") == 0
		assert ad._parse_droid_tokens("") == 0

	def test_comando_inclui_o_json(self, tmp_path):
		capturado = {}

		def fake_run(cmd, **kwargs):
			capturado["cmd"] = cmd
			(tmp_path / "manifest.ini").write_text("name = X\n", encoding="utf-8")
			plug = tmp_path / "globalPlugins" / "X"
			plug.mkdir(parents=True)
			(plug / "__init__.py").write_text("import globalPluginHandler\n", encoding="utf-8")
			return _fake_proc(stdout='{"usage": {"input_tokens": 12, "output_tokens": 3}}')

		with patch.object(ad, "_achar_droid", return_value="droid"), \
			patch.object(ad.subprocess, "run", side_effect=fake_run):
			r = run_agentic_build("x", workdir=str(tmp_path), use_nvda_context=False)
		assert "-o" in capturado["cmd"] and "json" in capturado["cmd"]
		assert r.tokens == 15


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


class TestCicloDeCorrecaoSlice2:
	"""Slice 2: gate determinístico pós-loop + reinjeção do erro no droid."""

	def _res(self, **kw):
		base = dict(success=True, workdir="/w", files=["manifest.ini", "globalPlugins/X/__init__.py"])
		base.update(kw)
		return AgenticBuildResult(**base)

	def test_correction_rounds_zero_nao_roda_gate(self):
		with patch.object(ad, "_droid_once", return_value=self._res()) as m_once, \
			patch.object(ad, "_run_gates") as m_gates:
			run_agentic_build("x", workdir="/w", correction_rounds=0)
		m_gates.assert_not_called()
		assert m_once.call_count == 1

	def test_gate_passa_de_primeira_nao_corrige(self):
		with patch.object(ad, "_droid_once", return_value=self._res()) as m_once, \
			patch.object(ad, "_run_gates", return_value=(True, "")):
			r = run_agentic_build("x", workdir="/w", correction_rounds=2)
		assert r.execution_ok is True and r.success is True and r.rounds == 1
		assert m_once.call_count == 1  # nao precisou reinjetar

	def test_gate_falha_depois_passa_reinjeta_o_erro(self):
		gates = [(False, "- Erro de EXECUCAO real: NameError: foo"), (True, "")]
		with patch.object(ad, "_droid_once", return_value=self._res()) as m_once, \
			patch.object(ad, "_run_gates", side_effect=gates):
			r = run_agentic_build("x", workdir="/w", correction_rounds=2)
		assert r.execution_ok is True and r.success is True
		assert m_once.call_count == 2  # build inicial + 1 correcao
		correcao = m_once.call_args_list[1][0][0]
		assert "NameError" in correcao and "Corrija os arquivos EXISTENTES" in correcao

	def test_gate_sempre_falha_esgota_rodadas_e_reprova(self):
		with patch.object(ad, "_droid_once", return_value=self._res()) as m_once, \
			patch.object(ad, "_run_gates", return_value=(False, "- Erro")):
			r = run_agentic_build("x", workdir="/w", correction_rounds=2)
		assert r.execution_ok is False and r.success is False
		assert m_once.call_count == 3  # inicial + 2 correcoes

	def test_run_gates_reporta_erro_de_execucao_real(self, tmp_path, monkeypatch):
		(tmp_path / "manifest.ini").write_text("name = X\n", encoding="utf-8")
		plug = tmp_path / "globalPlugins" / "X"
		plug.mkdir(parents=True)
		(plug / "__init__.py").write_text("import globalPluginHandler\n", encoding="utf-8")
		files = ["manifest.ini", "globalPlugins/X/__init__.py"]

		class _FakeSandbox:
			def __init__(self, *a, **k):
				pass

			def validate_addon_execution(self, d):
				return types.SimpleNamespace(success=False, error="NameError: foo", stderr="")

		monkeypatch.setattr("nvdastudio.builder.code_sandbox.CodeSandbox", _FakeSandbox)
		passou, rel = ad._run_gates(str(tmp_path), files)
		assert passou is False
		assert "EXECUCAO real" in rel and "NameError" in rel

	def test_run_gates_estrutura_faltando_reprova_sem_sandbox(self, tmp_path):
		# So um .py solto, sem manifest nem entry -> reprova na estrutura, nem
		# chega no gate de execucao.
		(tmp_path / "solto.py").write_text("x = 1\n", encoding="utf-8")
		passou, rel = ad._run_gates(str(tmp_path), ["solto.py"])
		assert passou is False
		assert "manifest.ini" in rel and "ponto de entrada" in rel


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


class TestGateDeAcessibilidade:
	"""#1 pos-demolicao: gate de acessibilidade deterministico (ast_validator)
	reintroduzido no caminho agentico -- o accessibility_audit staged saiu."""

	def test_gettext_sem_translators_vira_violacao(self):
		codigo = "import ui\nui.message(_('ola'))\n"  # _() sem '# Translators:' acima
		viol = ad._run_accessibility_gate({"globalPlugins/X/__init__.py": codigo})
		assert any("nvda" in v.lower() or "translators" in v.lower() for v in viol)

	def test_codigo_sem_gettext_nao_gera_violacao_nvda019(self):
		codigo = "import ui\nui.message('texto fixo')\n"
		viol = ad._run_accessibility_gate({"globalPlugins/X/__init__.py": codigo})
		# nao deve haver violacao de NVDA-019 (nao ha _() sem Translators)
		assert not any("nvda-019" in v.lower() or "translators" in v.lower() for v in viol)

	def test_ignora_nao_py(self):
		assert ad._run_accessibility_gate({"manifest.ini": "name = X"}) == []

	def test_gate_de_a11y_entra_no_run_gates(self, tmp_path):
		# estrutura minima valida + gettext sem Translators -> _run_gates reporta a11y
		(tmp_path / "manifest.ini").write_text("name = X\n", encoding="utf-8")
		plug = tmp_path / "globalPlugins" / "X"
		plug.mkdir(parents=True)
		(plug / "__init__.py").write_text(
			"import globalPluginHandler\nimport ui\ndef f():\n\tui.message(_('oi'))\n",
			encoding="utf-8",
		)
		# mocka o gate de execucao pra isolar o de a11y
		class _OK:
			success = True
			error = ""
			stderr = ""

		with patch("nvdastudio.builder.code_sandbox.CodeSandbox") as m:
			m.return_value.validate_addon_execution.return_value = _OK()
			passou, rel = ad._run_gates(str(tmp_path), ["manifest.ini", "globalPlugins/X/__init__.py"])
		assert passou is False and "ACESSIBILIDADE" in rel
