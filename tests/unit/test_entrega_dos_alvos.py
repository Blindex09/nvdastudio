"""
`target_files` era declarado pelo planner, injetado no prompt do step ("produza
EXATAMENTE estes arquivos") e nunca CONFERIDO. Quem reclamava de entrega parcial
era o Critic, em prosa, depois de uma avaliacao de dois estagios.

Medido nos relatorios E2E: 17 code_generation reprovados com "Nenhum codigo
Python foi produzido", 1,6 milhao de tokens -- mais os reprovados por entrega
parcial. Sao exatamente os casos que uma comparacao de nomes resolve antes de
qualquer chamada de modelo.

Mesmo padrao dos outros defeitos desta sessao: o dado certo existe, e ninguem
compara com a realidade.
"""

import inspect

from nvdastudio.core.orchestrator import MODULE_VERSION, Orchestrator, _alvos_nao_entregues
from nvdastudio.core.planner import STEP_CODE_GENERATION, STEP_DOCUMENTATION, ExecutionStep


def _step(alvos, tipo=STEP_CODE_GENERATION):
	return ExecutionStep("cg", tipo, "x", "alto", target_files=list(alvos))


def test_versao():
	assert MODULE_VERSION == "5.69.0"


def test_nada_entregue_lista_todos():
	alvos = ["globalPlugins/A/painel.py", "globalPlugins/A/api.py"]
	assert _alvos_nao_entregues(_step(alvos), {}) == alvos


def test_entrega_parcial_lista_so_o_que_falta():
	faltando = _alvos_nao_entregues(
		_step(["globalPlugins/A/painel.py", "globalPlugins/A/api.py"]),
		{"globalPlugins/A/painel.py": "codigo"},
	)
	assert faltando == ["globalPlugins/A/api.py"]


def test_entrega_completa_nao_reclama():
	assert not _alvos_nao_entregues(
		_step(["globalPlugins/A/painel.py"]),
		{"globalPlugins/A/painel.py": "codigo"},
	)


def test_caminho_diferente_nao_e_falso_positivo():
	"""Caminho errado e problema de COLOCACAO, que addon_builder ja resolve.
	Bloquear o step por isso rejeitaria codigo que existe e esta correto."""
	assert not _alvos_nao_entregues(
		_step(["globalPlugins/A/painel.py"]), {"painel.py": "codigo"},
	)


def test_separador_do_windows_nao_e_falso_positivo():
	assert not _alvos_nao_entregues(
		_step(["globalPlugins/A/painel.py"]),
		{"globalPlugins" + chr(92) + "A" + chr(92) + "painel.py": "codigo"},
	)


def test_step_sem_alvos_nao_e_cobrado():
	"""Todo plano anterior a 2.33.0 cai aqui -- exigir entrega sem ter pedido
	nada especifico so quebraria o que funcionava."""
	assert not _alvos_nao_entregues(_step([]), {})


def test_step_que_nao_escreve_codigo_nao_e_cobrado():
	assert not _alvos_nao_entregues(
		_step(["doc.md"], tipo=STEP_DOCUMENTATION), {},
	)


def test_verificacao_roda_antes_do_sandbox_e_do_critic():
	"""O ganho todo esta em falhar barato: a comparacao de nomes tem que vir
	antes da execucao isolada e antes da avaliacao de dois estagios."""
	src = inspect.getsource(Orchestrator._execute_step_with_critique)
	pos_check = src.index("_alvos_nao_entregues(")
	pos_sandbox = src.index("validate_addon_execution(")
	pos_critic = src.index("evaluate_two_stage(")
	assert pos_check < pos_sandbox < pos_critic


def test_instrucao_diz_o_formato_esperado():
	"""Um issue que so diz "faltou arquivo" faz o modelo repetir o erro; dizer o
	formato do bloco e o caminho faz ele entregar."""
	src = inspect.getsource(Orchestrator._execute_step_with_critique)
	trecho = src[src.index("Entrega incompleta"):][:600]
	assert "```python:" in trecho
	assert "COMPLETO" in trecho
