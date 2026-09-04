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

import subprocess

# 0 fora do Windows -- OR com 0 nao muda nada, entao o flag e portavel.
CREATE_NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def creationflags(base: int = 0) -> int:
	"""Combina flags existentes com CREATE_NO_WINDOW. Fonte unica para os
	varios subprocess.run espalhados pelo pipeline."""
	return base | CREATE_NO_WINDOW
