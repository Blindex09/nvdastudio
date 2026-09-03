"""Oraculo barato da entrega: reproduz, sem gastar 1 token de API, a cadeia
que entregou uma CASCA na rodada real de 2026-09-03 17:26 e que o portao de
completude (orchestrator 5.86.0) agora transforma em "nenhum addon".

A rodada real, resumida pelo relatorio
tests/e2e/relatorios/e2e_AssistenteEscrita_20260903_181718.json:

    web_research   692.032 tokens (3 retries, alucinou "HTTPX2"/"openai 3.8.0")
    cg_core        652.013 tokens (claude-sonnet-5)
    design_review  132.875 tokens
    ------------------------------------------------
    antes do cg_settings: ~1,51 mi -> o saldo entra na RESERVA DE ENTREGA ->
    cg_settings e a montagem barrados -> saiu 1 de 2 modulos declarados = casca.

A cadeia tem DOIS elos, exercitados aqui com os metodos REAIS do Orchestrator
(nenhum mock de logica -- so numeros de token injetados no medidor real):

  1. _saldo_permite_seguir(): quando o saldo entra na reserva de entrega, ele
     DESCARTA todo step que nao e 'assembly' -- inclusive um code_generation que
     ainda devia um modulo DECLARADO. E o instante em que a casca nasce.

  2. _validate_minimum_addon_artifacts(): o portao de completude REJEITA o
     pacote incompleto (modulo declarado ausente).

Juntos: pressao de orcamento -> descarta o modulo -> monta casca -> portao
rejeita -> nenhum addon. Exatamente o sintoma "manda codar e nao entrega nada".

E a direcao oposta: com o custo cortado (sem sonnet, sem vazamento de
web_research -- o que as correcoes de model_registry 1.22.0 e factory_client
1.1.0 fazem), o MESMO plano NAO entra na reserva, o cg_settings sobrevive, e o
portao aprova. Liga "cortamos custo" a "logo a entrega volta" -- o elo que uma
rodada E2E real so precisaria CONFIRMAR, nao descobrir.
"""

import pytest

from nvdastudio.core.orchestrator import Orchestrator
from nvdastudio.core.planner import (
	ExecutionPlan,
	ExecutionStep,
	STEP_ASSEMBLY,
	STEP_CODE_GENERATION,
	STEP_DESIGN_REVIEW,
	STEP_WEB_RESEARCH,
)
from nvdastudio.core.orch_types import StepResult
from nvdastudio.utils import iteration_budget as ib


# Caminhos do addon da rodada real. O __init__.py e o ponto de entrada (o portao
# de carregamento exige que ele exista); o configSpec.py e o modulo DECLARADO que
# ficou de fora quando o orcamento estourou.
_ENTRADA = "globalPlugins/AssistenteEscrita/__init__.py"
_SETTINGS = "globalPlugins/AssistenteEscrita/configSpec.py"


@pytest.fixture(autouse=True)
def _budget_isolado():
	"""Reset do singleton global ANTES e DEPOIS de cada teste. Fixture, nao
	setup_function: pytest so chama setup_function para funcoes de modulo, nunca
	para metodos de classe -- e o estado do medidor vazaria entre os metodos."""
	ib.budget.reset()
	yield
	ib.budget.reset()


def _orch() -> Orchestrator:
	"""Instancia sem tocar __init__ -- os metodos exercitados nao leem estado de
	instancia (usam o singleton global iteration_budget e constantes de modulo).
	Mesmo padrao de setup_method de tests/integration/test_orchestrator.py."""
	return Orchestrator.__new__(Orchestrator)


def _steps_do_plano() -> list[ExecutionStep]:
	return [
		ExecutionStep("dr0", STEP_DESIGN_REVIEW, "revisao", "kimi-k2.7-code"),
		ExecutionStep("research", STEP_WEB_RESEARCH, "pesquisa", "kimi-k2.7-code"),
		ExecutionStep("cg_core", STEP_CODE_GENERATION, "nucleo", "kimi-k2.7-code",
					  target_files=[_ENTRADA]),
		ExecutionStep("cg_settings", STEP_CODE_GENERATION, "config", "kimi-k2.7-code",
					  target_files=[_SETTINGS]),
		ExecutionStep("asm", STEP_ASSEMBLY, "montar", "kimi-k2.7-code"),
	]


def _plano() -> ExecutionPlan:
	"""Plano minimo fiel: dois modulos Python DECLARADOS e os steps que os
	produzem, mais um consultivo e a montagem."""
	return ExecutionPlan(
		plan_id="ea3bbd83",
		original_query="Crie um addon AssistenteEscrita...",
		steps=_steps_do_plano(),
		addon_name="AssistenteEscrita",
		project_type="addon",
		expected_files=[_ENTRADA, _SETTINGS],
	)


def _bloco_py(caminho: str) -> str:
	return f"```python:{caminho}\nclass GlobalPlugin:\n    pass\n```"


def _consumir(tokens: int) -> None:
	ib.budget.record_iteration("code_generation", "kimi-k2.7-code", tokens_used=tokens)


def _teto_do_plano() -> int:
	"""Dimensiona o teto pelo plano, exatamente como o orchestrator faz."""
	return ib.budget.apply_plan([s.step_type for s in _steps_do_plano()], "medium")


def _restam_apos_saldo(gasto_anterior: int) -> tuple[bool, list[str]]:
	"""Consome `gasto_anterior` e roda o portao de saldo real sobre
	[cg_settings, asm]. Devolve (ok, ids_restantes).

	Reseta o medidor no inicio: cada cenario e independente, mesmo quando um
	unico teste compara dois (caro vs barato) -- sem isto o consumo do primeiro
	somaria no segundo (o medidor e um singleton de processo)."""
	ib.budget.reset()
	orch = _orch()
	_teto_do_plano()
	_consumir(gasto_anterior)
	remaining = [
		ExecutionStep("cg_settings", STEP_CODE_GENERATION, "config", "kimi-k2.7-code",
					  target_files=[_SETTINGS]),
		ExecutionStep("asm", STEP_ASSEMBLY, "montar", "kimi-k2.7-code"),
	]
	ok, _motivo = orch._saldo_permite_seguir(remaining, set())
	return ok, [s.step_id for s in remaining]


def _modulo_seria_gerado(gasto_anterior: int) -> bool:
	"""O cg_settings so e gerado se o saldo permite seguir E ele nao foi
	descartado. Unifica os dois regimes de falha (reserva e teto estourado)."""
	ok, ids = _restam_apos_saldo(gasto_anterior)
	return ok and "cg_settings" in ids


class TestElo1_SaldoNaReservaDescartaModuloDeclarado:
	"""O saldo na reserva descarta o cg_settings -- um modulo DECLARADO que nao
	e 'assembly'. E o instante em que a casca nasce."""

	def test_cg_settings_e_descartado_quando_o_saldo_entra_na_reserva(self):
		teto = _teto_do_plano()
		# Consome ate DENTRO da reserva de entrega (abaixo do teto, mas dentro
		# dos ultimos _RESERVA_DE_ENTREGA): quem nao entrega nao pode mais rodar,
		# quem entrega ainda pode. Relativo ao teto real -- nao a um numero fixo.
		ok, ids = _restam_apos_saldo(teto - ib._RESERVA_DE_ENTREGA // 2)

		# Segue para a entrega, mas o cg_settings foi jogado fora no caminho.
		assert ok is True
		assert "cg_settings" not in ids, "o modulo declarado foi descartado -- nasce a casca"
		assert "asm" in ids, "a montagem sobrevive (e a unica 'entrega')"

	def test_folga_confortavel_nao_descarta_ninguem(self):
		"""Contraprova: fora da reserva, nada e descartado -- o descarte e do
		saldo apertado, nao um comportamento sempre-ligado."""
		teto = _teto_do_plano()
		ok, ids = _restam_apos_saldo(teto - ib._RESERVA_DE_ENTREGA - 200_000)

		assert ok is True
		assert ids == ["cg_settings", "asm"]


class TestElo2_PortaoRejeitaAEntregaIncompleta:
	"""Com o cg_settings de fora, o pacote tem 1 de 2 modulos. O portao de
	completude recusa -- e isso vira 'nenhum addon' para o usuario."""

	def test_casca_um_de_dois_modulos_e_rejeitada(self):
		plano = _plano()
		# Cenario real: cg_core aprovado (entregou __init__.py), cg_settings NAO.
		step_results = [
			StepResult("cg_core", STEP_CODE_GENERATION, _bloco_py(_ENTRADA),
					   approved=True, score=87),
			StepResult("cg_settings", STEP_CODE_GENERATION, "",
					   approved=False, score=0),
		]
		outputs = {"cg_core": _bloco_py(_ENTRADA)}

		erro = Orchestrator._validate_minimum_addon_artifacts(plano, step_results, outputs)

		assert erro, "a casca precisa ser recusada, nao entregue como pronta"
		assert "configSpec.py" in erro, "o portao tem que nomear o modulo que faltou"

	def test_addon_completo_passa(self):
		"""Contraprova essencial: entrega boa NAO pode ser recusada (falso
		positivo aqui e o pior desfecho -- recusa o que funciona)."""
		plano = _plano()
		step_results = [
			StepResult("cg_core", STEP_CODE_GENERATION, _bloco_py(_ENTRADA),
					   approved=True, score=90),
			StepResult("cg_settings", STEP_CODE_GENERATION, _bloco_py(_SETTINGS),
					   approved=True, score=90),
		]
		outputs = {"cg_core": _bloco_py(_ENTRADA), "cg_settings": _bloco_py(_SETTINGS)}

		erro = Orchestrator._validate_minimum_addon_artifacts(plano, step_results, outputs)

		assert erro == "", f"entrega completa foi recusada por engano: {erro!r}"


class TestCadeiaCompleta_CustoDecideEntrega:
	"""A prova que liga 'cortar custo' a 'a entrega volta': o MESMO plano e o
	MESMO teto, so mudando quanto os steps anteriores gastam, decidem entre
	casca e addon completo."""

	def test_caro_derruba_o_modulo_barato_o_preserva(self):
		teto = _teto_do_plano()

		# CARO (rodada real): consultivos + web_research vazado + sonnet no
		# nucleo empurram o saldo para DENTRO da reserva antes do cg_settings.
		caro = teto - 30_000  # dentro dos ultimos _RESERVA_DE_ENTREGA
		assert _modulo_seria_gerado(caro) is False, (
			"no caminho caro o cg_settings nao chega a ser gerado -> casca -> "
			"portao rejeita -> nenhum addon"
		)

		# BARATO (pos-correcao): sem vazamento de web_research (falha rapido) e
		# sem sonnet (nucleo no kimi). Os steps anteriores cabem com folga e o
		# modulo sobrevive para ser gerado e entregue.
		barato = teto - ib._RESERVA_DE_ENTREGA - 300_000
		assert _modulo_seria_gerado(barato) is True, (
			"cortar custo mantem o cg_settings vivo -> addon completo -> portao aprova"
		)


class TestElo1b_DescarteCondenadoParaEmVezDeMontarCasca:
	"""5.87.0: descartar um code_generation que ainda deve um modulo DECLARADO
	condena o portao de completude -- o pacote montado sem ele ja nasce
	reprovado. Parar honesto e economico (nao paga a montagem condenada); so os
	consultivos PUROS seguem sendo descartados para dar lugar a entrega."""

	def _entrar_na_reserva(self) -> None:
		teto = _teto_do_plano()
		_consumir(teto - ib._RESERVA_DE_ENTREGA // 2)

	def _cg_pendente_e_montagem(self) -> list:
		return [
			ExecutionStep("cg_settings", STEP_CODE_GENERATION, "config", "kimi-k2.7-code",
						  target_files=[_SETTINGS]),
			ExecutionStep("asm", STEP_ASSEMBLY, "montar", "kimi-k2.7-code"),
		]

	def test_descartar_modulo_declarado_para_em_vez_de_montar_casca(self):
		self._entrar_na_reserva()
		remaining = self._cg_pendente_e_montagem()
		failed: set = set()

		ok, _ = _orch()._saldo_permite_seguir(remaining, failed, _plano(), {})

		assert ok is False, "condenar a entrega tem que PARAR, nao montar uma casca"
		# Nada foi descartado nem a montagem condenada avancou -- a FASE 6 roda o
		# portao e nomeia o modulo que faltou, sem pagar os ~82k da montagem.
		assert "cg_settings" in [s.step_id for s in remaining]
		assert "cg_settings" not in failed

	def test_consultivo_puro_ainda_e_descartado(self):
		"""Nao-regressao: um step que NAO produz arquivo continua sendo
		descartado para dar lugar a entrega (comportamento da 5.60.0)."""
		self._entrar_na_reserva()
		remaining = [
			ExecutionStep("dr0", STEP_DESIGN_REVIEW, "revisao", "kimi-k2.7-code"),
			ExecutionStep("asm", STEP_ASSEMBLY, "montar", "kimi-k2.7-code"),
		]
		failed: set = set()

		ok, _ = _orch()._saldo_permite_seguir(remaining, failed, _plano(), {})

		assert ok is True
		assert [s.step_id for s in remaining] == ["asm"]
		assert failed == {"dr0"}

	def test_modulo_ja_produzido_nao_condena(self):
		"""Sem falso positivo -- o pior desfecho seria recusar entrega boa: se os
		modulos declarados JA estao em outputs, descartar um step redundante
		nao condena nada."""
		self._entrar_na_reserva()
		remaining = self._cg_pendente_e_montagem()
		outputs = {"cg_core": _bloco_py(_ENTRADA), "outro": _bloco_py(_SETTINGS)}
		failed: set = set()

		ok, _ = _orch()._saldo_permite_seguir(remaining, failed, _plano(), outputs)

		assert ok is True, "os dois modulos declarados ja existem -- nada a condenar"
		assert "cg_settings" not in [s.step_id for s in remaining]

	def test_modulo_em_caminho_divergente_nao_condena(self):
		"""Falso positivo por caminho -- o pior desfecho: o modulo foi entregue
		com o NOME certo mas em outro caminho (colocacao, que o addon_builder
		resolve). O portao de completude aprovaria; condenar aqui recusaria uma
		entrega boa. So o NOME importa, igual ao portao."""
		self._entrar_na_reserva()
		remaining = self._cg_pendente_e_montagem()
		outputs = {
			"cg_core": _bloco_py(_ENTRADA),
			"outro": _bloco_py("configSpec.py"),  # nome certo, caminho bare
		}
		failed: set = set()

		ok, _ = _orch()._saldo_permite_seguir(remaining, failed, _plano(), outputs)

		assert ok is True, "configSpec.py existe (nome bate) -- nada a condenar"
		assert "cg_settings" not in [s.step_id for s in remaining]

	def test_sem_plano_mantem_o_comportamento_antigo(self):
		"""Chamador antigo/teste sem plano: nada condena -- descarta e segue,
		exatamente como antes da 5.87.0."""
		self._entrar_na_reserva()
		remaining = self._cg_pendente_e_montagem()
		failed: set = set()

		ok, _ = _orch()._saldo_permite_seguir(remaining, failed)  # sem plan/outputs

		assert ok is True
		assert [s.step_id for s in remaining] == ["asm"]


def test_ambos_os_pipelines_setam_current_plan():
	"""Fitness function: _current_plan alimenta _project_type,
	_arquivos_de_outros_steps, a complexidade do replan, a propagacao de
	planejamento_degradado e _descarte_condena_entrega. Um pipeline que esquece
	de seta-lo degrada tudo isso para o default silencioso -- inclusive tratando
	um controller_client como "addon". Os DOIS pipelines precisam seta-lo."""
	import inspect
	from nvdastudio.core import orchestrator as _mod

	for metodo in ("_run_pipeline", "_run_conversational_pipeline"):
		fonte = inspect.getsource(getattr(_mod.Orchestrator, metodo))
		assert "self._current_plan = plan" in fonte, (
			f"{metodo} nao seta self._current_plan -- metodos plan-aware degradam la"
		)
