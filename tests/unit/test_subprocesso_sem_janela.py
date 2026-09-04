"""Regressao: subprocessos do pipeline (droid da Factory, sandbox, pytest, pip)
abriam uma janela de console no Windows que ROUBAVA O FOCO do NVDA -- para um
usuario cego, o leitor salta para o terminal e ele perde o lugar. Todos tem que
rodar escondidos (creationflags=CREATE_NO_WINDOW, 0/no-op fora do Windows).
"""

import inspect
import subprocess
from unittest.mock import MagicMock, patch


def test_create_no_window_e_o_flag_do_windows_ou_zero():
	from nvdastudio.utils.hidden_process import CREATE_NO_WINDOW

	assert CREATE_NO_WINDOW == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_code_sandbox_run_hidden_injeta_o_flag():
	from nvdastudio.builder import code_sandbox
	from nvdastudio.utils.hidden_process import CREATE_NO_WINDOW

	fake = MagicMock(returncode=0, stdout="", stderr="")
	with patch("nvdastudio.builder.code_sandbox.subprocess.run", return_value=fake) as m:
		code_sandbox._run_hidden(["algum", "comando"])

	flags = m.call_args.kwargs.get("creationflags")
	assert flags is not None, "o wrapper tem que passar creationflags"
	# Inclui o flag (no Windows) ou e 0 (fora dele) -- os dois satisfazem.
	assert flags & CREATE_NO_WINDOW == CREATE_NO_WINDOW


def test_code_sandbox_run_hidden_preserva_kwargs_do_chamador():
	"""O flag nao pode atropelar env/timeout -- por isso os testes de pytest
	continuam lendo o env que passaram."""
	from nvdastudio.builder import code_sandbox

	fake = MagicMock(returncode=0, stdout="", stderr="")
	with patch("nvdastudio.builder.code_sandbox.subprocess.run", return_value=fake) as m:
		code_sandbox._run_hidden(["x"], env={"MARCA": "1"}, timeout=9)

	assert m.call_args.kwargs.get("env") == {"MARCA": "1"}
	assert m.call_args.kwargs.get("timeout") == 9


def test_factory_client_roda_o_droid_escondido():
	from nvdastudio.ai import factory_client

	src = inspect.getsource(factory_client.FactoryClient.chat)
	assert "creationflags=CREATE_NO_WINDOW" in src, (
		"o droid exec tem que rodar sem abrir janela de console"
	)


def test_pip_do_bundle_roda_escondido():
	from nvdastudio.builder import addon_builder

	src = inspect.getsource(addon_builder)
	# O pip install do bundle de dependencias -- a chamada com timeout=120.
	assert "creationflags=CREATE_NO_WINDOW" in src


def test_code_sandbox_nao_tem_subprocess_run_nu():
	"""Fitness function: o unico subprocess.run em code_sandbox e dentro do
	wrapper _run_hidden. Um subprocess.run novo direto voltaria a abrir
	terminal -- este teste obriga a passar pelo wrapper."""
	from nvdastudio.builder import code_sandbox

	src = inspect.getsource(code_sandbox)
	assert src.count("subprocess.run(") == 1, (
		"code_sandbox deve chamar subprocess.run so dentro de _run_hidden"
	)


def test_find_python_nunca_devolve_o_nvda():
	"""O nvda.exe nao e interpretador -- roda-lo como python da WinError 740."""
	from nvdastudio.utils.hidden_process import find_python

	achado = find_python()
	assert achado is None or "nvda" not in achado.lower()


class TestValidacaoDeExecucaoDegradaSemPython:
	"""Regressao do loop de 'Erro de execucao real: [WinError 740]': DENTRO do
	NVDA, sys.executable e o nvda.exe (nao roda como python, pede elevacao). A
	validacao de execucao tem que PULAR nesse caso -- ausencia de interpretador
	e infra, nao defeito do codigo. Tratar como falha jogava o step num loop de
	retry infinito (o que o usuario viu ao vivo)."""

	_ADDON = (
		"import globalPluginHandler\n"
		"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
		"\tpass\n"
	)

	def test_sem_python_real_pula_em_vez_de_reprovar(self, monkeypatch):
		from nvdastudio.builder import code_sandbox

		monkeypatch.setattr(code_sandbox, "_PYTHON", None)
		r = code_sandbox.CodeSandbox().validate_addon_execution(
			{"globalPlugins/X/__init__.py": self._ADDON}
		)
		assert r.success is True, "sem python, tem que PULAR, nao reprovar (senao loop)"
		assert "PULADO_SEM_PYTHON" in r.stdout

	def test_winerror_740_ao_lancar_pula(self, monkeypatch):
		from nvdastudio.builder import code_sandbox

		monkeypatch.setattr(code_sandbox, "_PYTHON", "python.exe")

		def _lanca_740(*a, **k):
			raise OSError(740, "A operacao solicitada requer elevacao")

		monkeypatch.setattr(code_sandbox, "_run_hidden", _lanca_740)
		r = code_sandbox.CodeSandbox().validate_addon_execution(
			{"globalPlugins/X/__init__.py": self._ADDON}
		)
		assert r.success is True, "740 ao lancar o interpretador tem que PULAR"
		assert "PULADO_SUBPROCESSO_INDISPONIVEL" in r.stdout
