"""Suprime a janela de console de subprocessos no Windows.

Um subprocesso de app de console (o `droid` da Factory, o python do sandbox,
o pytest, o pip) abre uma janela de terminal no Windows. Essa janela ROUBA O
FOCO: para um usuario cego, o leitor de tela salta para o terminal e ele perde
o lugar na janela do NVDAStudio -- exatamente o que nao pode acontecer. Todo
subprocesso do pipeline roda escondido.

CREATE_NO_WINDOW so existe no Windows; nas outras plataformas o getattr
devolve 0 (no-op), entao passar creationflags=CREATE_NO_WINDOW e seguro em
qualquer OS.
"""

import os
import shutil
import subprocess
import sys

# 0 fora do Windows -- OR com 0 nao muda nada, entao o flag e portavel.
CREATE_NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def creationflags(base: int = 0) -> int:
	"""Combina flags existentes com CREATE_NO_WINDOW. Fonte unica para os
	varios subprocess.run espalhados pelo pipeline."""
	return base | CREATE_NO_WINDOW


def find_python() -> "str | None":
	"""Caminho de um python.exe REAL, ou None se so houver o nvda.exe.

	DENTRO do NVDA, sys.executable e o `nvda.exe` -- rodar ele como
	interpretador falha com WinError 740 (requer elevacao), que era exatamente
	o loop de "Erro de execucao real" na validacao de codigo. O addon_builder ja
	tratava isso para o pip; esta e a fonte unica (Regra 5), usada tambem pelo
	code_sandbox.

	Retorna None quando so ha o nvda.exe: o chamador deve PULAR a validacao por
	subprocesso (nao ha como executar), nunca tratar a ausencia de python como
	defeito do codigo gerado.
	"""
	exe = sys.executable or ""
	base = os.path.basename(exe).lower()
	if "python" in base and "nvda" not in base:
		# pytest/CI/dev: sys.executable ja e um python real.
		return exe
	for candidato in ("python.exe", "python3.exe", "python", "python3"):
		achado = shutil.which(candidato)
		if achado and "nvda" not in achado.lower():
			return achado
	return None
