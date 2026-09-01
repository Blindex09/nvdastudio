"""
O arquivo mais importante do addon era o ultimo da fila, entao era a primeira
baixa.

MEDIDO em 2026-09-01, e o achado e categorico: nas SEIS execucoes complexas que
falharam, o step que gera `globalPlugins/<addon>/__init__.py` NUNCA chegou a ser
executado. Nenhuma vez. Nao e que ele saia errado -- ele nunca e tentado, porque
ARCH-010 o fazia depender de TODOS os code_generation de feature, e o orcamento
acaba antes. Por isso `has_init_py=False` em 100% dos relatorios de falha.

A conta que explica: 47,3% dos code_generation sao aprovados. Com o pipeline
exigindo que TODOS passem, um plano com 8 steps de codigo tem 0,25% de chance de
completar. Nenhuma melhoria incremental de qualidade resolve um AND serial dessa
profundidade -- o que da para mudar e a ORDEM, para que morrer no meio ainda
entregue um addon que o NVDA carrega.
"""

from nvdastudio.core.planner import (
	MODULE_VERSION,
	STEP_CODE_GENERATION,
	ExecutionStep,
	Planner,
	_tem_ciclo,
)


def _cg(sid, alvos=None, dep=None):
	return ExecutionStep(
		sid, STEP_CODE_GENERATION, "descricao de " + sid, "alto",
		depends_on=list(dep or []), target_files=list(alvos or []),
	)


def _plano_arch010():
	"""O formato que ARCH-010 produzia: nucleo depende de todas as features."""
	return [
		_cg("cg_img", ["globalPlugins/A/imagem/__init__.py"]),
		_cg("cg_aud", ["globalPlugins/A/audio/__init__.py"]),
		_cg("cg_core", ["globalPlugins/A/__init__.py"], ["cg_img", "cg_aud"]),
	]


def test_versao():
	assert MODULE_VERSION == "2.40.0"


class TestNucleoVemPrimeiro:
	def test_nucleo_roda_antes_das_features(self):
		r = Planner()._priorizar_ponto_de_entrada(_plano_arch010())
		assert [s.step_id for s in r][0] == "cg_core"

	def test_nucleo_nao_espera_mais_os_irmaos(self):
		r = Planner()._priorizar_ponto_de_entrada(_plano_arch010())
		nucleo = next(s for s in r if s.step_id == "cg_core")
		assert nucleo.depends_on == []

	def test_features_recebem_o_contrato_do_nucleo(self):
		"""Sem isso cada feature inventaria a propria interface e o nucleo
		importaria nomes que ninguem implementou."""
		r = Planner()._priorizar_ponto_de_entrada(_plano_arch010())
		for sid in ("cg_img", "cg_aud"):
			s = next(x for x in r if x.step_id == sid)
			assert "cg_core" in s.depends_on
			assert "cg_core" in s.context_from_steps

	def test_nucleo_e_instruido_a_importar_de_forma_tolerante(self):
		"""Ele e escrito antes dos modulos existirem: um ImportError duro
		impediria o addon INTEIRO de carregar."""
		r = Planner()._priorizar_ponto_de_entrada(_plano_arch010())
		desc = next(s for s in r if s.step_id == "cg_core").description
        # o contrato e a tolerancia sao o motivo da inversao
		assert "CONTRATO" in desc
		assert "ImportError" in desc

	def test_nenhum_step_e_perdido(self):
		plano = _plano_arch010()
		r = Planner()._priorizar_ponto_de_entrada(plano)
		assert {s.step_id for s in r} == {s.step_id for s in plano}
		assert len(r) == len(plano)

	def test_step_unico_nao_e_reordenado(self):
		"""Sem decomposicao nao ha ordem a inverter."""
		plano = [_cg("cg_unico", ["globalPlugins/A/__init__.py"])]
		assert Planner()._priorizar_ponto_de_entrada(plano) == plano

	def test_plano_sem_nucleo_identificavel_fica_como_esta(self):
		plano = [_cg("cg_a", ["globalPlugins/A/a.py"]), _cg("cg_b", ["globalPlugins/A/b.py"])]
		r = Planner()._priorizar_ponto_de_entrada(plano)
		assert [s.step_id for s in r] == ["cg_a", "cg_b"]

	def test_com_varios_pontos_de_entrada_vence_o_que_integra(self):
		"""Em appModules/, todo .py solto e carregavel por convencao -- um plano
		com dois appModules tem dois pontos de entrada legitimos. O nucleo e o
		que INTEGRA os outros, nao o primeiro da lista."""
		plano = [
			_cg("cg_util", ["appModules/util.py"]),
			_cg("cg_app", ["appModules/notepad.py"], ["cg_util"]),
		]
		r = Planner()._priorizar_ponto_de_entrada(plano)
		assert r[0].step_id == "cg_app"


class TestGuardaDeCiclo:
	"""O orchestrator NAO detecta ciclo -- ele apenas nunca marcaria os steps
	como prontos, e o pipeline travaria em silencio ate o timeout. Um ciclo
	seria pior que a ordem ruim que estamos consertando."""

	def test_ciclo_faz_reverter_tudo(self):
		plano = [
			ExecutionStep("man", "manifest_builder", "x", "alto", depends_on=["cg_img"]),
			_cg("cg_img", ["globalPlugins/A/imagem/__init__.py"]),
			_cg("cg_core", ["globalPlugins/A/__init__.py"], ["cg_img", "man"]),
		]
		antes = {s.step_id: list(s.depends_on) for s in plano}
		r = Planner()._priorizar_ponto_de_entrada(plano)
		assert {s.step_id: list(s.depends_on) for s in r} == antes

	def test_detector_de_ciclo(self):
		a = ExecutionStep("a", STEP_CODE_GENERATION, "x", "m", depends_on=["b"])
		b = ExecutionStep("b", STEP_CODE_GENERATION, "x", "m", depends_on=["a"])
		assert _tem_ciclo([a, b])

	def test_grafo_acilico_nao_dispara(self):
		a = ExecutionStep("a", STEP_CODE_GENERATION, "x", "m")
		b = ExecutionStep("b", STEP_CODE_GENERATION, "x", "m", depends_on=["a"])
		assert not _tem_ciclo([a, b])

	def test_dependencia_para_step_inexistente_nao_e_ciclo(self):
		"""Plano do modelo pode citar um id que nao existe -- isso e outro
		problema, e nao pode ser confundido com ciclo."""
		a = ExecutionStep("a", STEP_CODE_GENERATION, "x", "m", depends_on=["fantasma"])
		assert not _tem_ciclo([a])


def test_prompt_e_codigo_pedem_a_mesma_coisa():
	"""Pedir ao modelo o contrario do que o codigo faz deixaria o plano sendo
	reescrito toda vez -- e o proximo a ler o prompt acreditaria no formato
	errado."""
	from nvdastudio.core.planner import _PLAN_SYSTEM_PROMPT

	# Delimitado pela proxima regra, nunca por janela de tamanho fixo: dois
	# testes desta sessao ja quebraram por usar contagem de caracteres quando a
	# descricao cresceu.
	i = _PLAN_SYSTEM_PROMPT.index("ARCH-010")
	j = _PLAN_SYSTEM_PROMPT.find("ARCH-011", i)
	trecho = _PLAN_SYSTEM_PROMPT[i:j if j != -1 else None]
	assert "PRIMEIRO" in trecho
	assert "cg_core" in trecho
	assert "ImportError" in trecho
