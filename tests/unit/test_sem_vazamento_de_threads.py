"""
Cada Orchestrator abria um pool de 4 threads que nunca era usado nem desligado.

Auditoria de 2026-09-01: `self._tool_executor = ToolExecutor(...)` era criado no
__init__ e NUNCA chamado -- nao existe uma unica referencia a
`self._tool_executor.<algo>` em todo o projeto. E o construtor do ToolExecutor
abre um `ThreadPoolExecutor(max_workers=4)`, com um `shutdown()` que ninguem
chama.

O NVDA fica horas aberto na maquina do usuario, e o dialogo do NVDAStudio pode
ser aberto varias vezes na mesma sessao. Threads paradas acumulando dentro do
leitor de tela nao e questao de arrumacao: e recurso do usuario.

O caminho VIVO de ferramentas e `tools/tool_gateway.py`, que importa as funcoes
de `tool_system/builtins/` diretamente -- `code_generator` chama
`tool_gateway.call("file_editor", ...)`. O par registry+executor era uma segunda
implementacao paralela, sem consumidor.
"""

import threading

from nvdastudio.core.orchestrator import MODULE_VERSION, Orchestrator


def test_versao():
	assert MODULE_VERSION == "5.89.0"


def test_criar_orchestrator_nao_deixa_thread_para_tras():
	antes = threading.active_count()
	orquestradores = [Orchestrator() for _ in range(3)]
	assert threading.active_count() == antes, (
		"criar Orchestrator abriu thread que ninguem vai fechar"
	)
	assert len(orquestradores) == 3


def test_executor_morto_nao_volta():
	"""Se alguem reintroduzir a instanciacao, o vazamento volta junto."""
	orq = Orchestrator()
	assert not hasattr(orq, "_tool_executor")


def test_approval_workflow_continua_vivo():
	"""A limpeza nao pode levar junto o que E usado: analyze_risk alimenta
	_tool_approval_callback, que decide se uma ferramenta pode rodar."""
	import inspect

	orq = Orchestrator()
	assert hasattr(orq, "_approval_workflow")
	src = inspect.getsource(Orchestrator)
	assert "_approval_workflow.analyze_risk(" in src
