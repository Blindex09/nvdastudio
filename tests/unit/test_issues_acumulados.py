"""
Problemas acumulados entre tentativas de um mesmo step.

ACHADO NO E2E REAL (2026-08-29, segunda execucao): cada `code_generation`
gastava ~420 mil tokens em 3 tentativas e falhava nas tres, com motivo
DIFERENTE a cada vez:

    tentativa 1 -> "NVDA-003: settings_panel.py usa gettext sem initTranslation"
    tentativa 2 -> "nao foi gerado o arquivo solicitado gemini_service.py"
    tentativa 3 -> "Lint do addon gerado (ruff) apontou defeitos reais"

A causa nao era o modelo. Era `last_issues = crit.issues`, que SUBSTITUI a
lista a cada avaliacao: na tentativa 2 o prompt recebia apenas os problemas da
avaliacao 2, e os da tentativa 1 tinham sumido. O modelo corrigia o que
acabara de ouvir e reintroduzia o que ja tinha corrigido -- tres tentativas,
tres conjuntos de problemas, nenhuma convergencia.

A ARMADILHA que estes testes tambem travam: a deteccao de loop semantico
(5.42.0) compara a assinatura de `last_issues` entre tentativas consecutivas.
Fazer `last_issues` acumular teria feito a assinatura crescer sempre, nunca se
repetir, e matado a deteccao de loop em silencio -- trocando um defeito por
outro. Por isso a lista acumulada vive SEPARADA.
"""

from nvdastudio.core.orchestrator import (
	MODULE_VERSION,
	_MAX_ISSUES_ACUMULADOS,
	_acumular_issues,
)

assert MODULE_VERSION == "5.91.0"


class TestAcumulacao:
	def test_acrescenta_sem_perder_os_anteriores(self):
		"""O ponto central: a tentativa 3 tem que ver o que a 1 apontou."""
		acc: list[str] = []
		_acumular_issues(acc, ["NVDA-003: falta initTranslation"])
		_acumular_issues(acc, ["nao foi gerado gemini_service.py"])
		_acumular_issues(acc, ["ruff: F401 import nao usado"])
		assert acc == [
			"NVDA-003: falta initTranslation",
			"nao foi gerado gemini_service.py",
			"ruff: F401 import nao usado",
		]

	def test_nao_duplica_o_mesmo_problema(self):
		"""O Critic repete a mesma frase entre tentativas; listar tres vezes nao
		aumenta a chance de correcao, so gasta contexto."""
		acc: list[str] = []
		_acumular_issues(acc, ["ruff: F401"])
		_acumular_issues(acc, ["ruff: F401", "novo problema"])
		_acumular_issues(acc, ["ruff: F401"])
		assert acc.count("ruff: F401") == 1
		assert len(acc) == 2

	def test_preserva_ordem_de_descoberta(self):
		"""O problema apontado primeiro costuma ser o mais estrutural."""
		acc: list[str] = []
		_acumular_issues(acc, ["primeiro"])
		_acumular_issues(acc, ["segundo"])
		assert acc[0] == "primeiro"

	def test_ignora_vazio_e_espaco(self):
		acc: list[str] = []
		_acumular_issues(acc, ["", "   ", "real"])
		assert acc == ["real"]

	def test_lista_vazia_ou_none_nao_levanta(self):
		"""Roda dentro do laco de retry: excecao aqui derrubaria o step."""
		acc: list[str] = ["existente"]
		_acumular_issues(acc, [])
		_acumular_issues(acc, None)
		assert acc == ["existente"]

	def test_converte_para_texto(self):
		"""crit.issues nem sempre traz str puro."""
		acc: list[str] = []
		_acumular_issues(acc, [123, ("a", "b")])
		assert len(acc) == 2
		assert all(isinstance(x, str) for x in acc)


class TestTetoDoPrompt:
	"""Alto o bastante para ver tudo num step multi-arquivo, baixo o bastante
	para o prompt do retry nao virar despejo que dilui a atencao."""

	def test_respeita_o_teto(self):
		acc: list[str] = []
		_acumular_issues(acc, [f"problema {i}" for i in range(_MAX_ISSUES_ACUMULADOS + 20)])
		assert len(acc) == _MAX_ISSUES_ACUMULADOS

	def test_descarta_os_antigos_nao_os_recentes(self):
		"""Um problema apontado ha 3 tentativas e que nunca mais voltou
		provavelmente ja foi resolvido; o recente e o que ainda importa."""
		acc: list[str] = []
		_acumular_issues(acc, [f"antigo {i}" for i in range(_MAX_ISSUES_ACUMULADOS)])
		_acumular_issues(acc, ["problema mais novo"])
		assert "problema mais novo" in acc
		assert "antigo 0" not in acc
		assert len(acc) == _MAX_ISSUES_ACUMULADOS


class TestNaoQuebraADeteccaoDeLoop:
	"""A lista acumulada e SEPARADA de last_issues justamente por isto."""

	def test_orchestrator_usa_duas_listas_distintas(self):
		import inspect

		from nvdastudio.core.orchestrator import Orchestrator

		# A funcao de execucao de step precisa manter as duas.
		src = inspect.getsource(Orchestrator._execute_step_with_critique)
		assert "issues_acumulados" in src, "lista acumulada ausente"
		assert "last_issues = crit.issues" in src, (
			"last_issues precisa continuar sendo SUBSTITUIDA -- a assinatura de "
			"loop semantico depende de comparar so a avaliacao atual"
		)
		assert "previous_issues=issues_acumulados" in src, (
			"o prompt do retry precisa receber a lista ACUMULADA"
		)

	def test_assinatura_de_loop_ainda_vem_da_avaliacao_atual(self):
		import inspect

		from nvdastudio.core.orchestrator import Orchestrator

		src = inspect.getsource(Orchestrator._execute_step_with_critique)
		i_sig = src.find("_issue_signature")
		i_acc = src.find("issues_acumulados")
		assert i_sig != -1 and i_acc != -1
		assert "sorted(str(i) for i in last_issues)" in src, (
			"a assinatura precisa vir de last_issues, nunca da acumulada -- "
			"acumulada cresce sempre e nunca repetiria"
		)
