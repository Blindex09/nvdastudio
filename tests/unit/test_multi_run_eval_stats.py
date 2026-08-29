import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from multi_run_eval import _compute_stats, _flakiness  # noqa: E402


def _run(success: bool, score: float = 80.0) -> dict:
	return {"success": success, "avg_score": score}


class TestFlakiness:
	def test_sem_transicoes_quando_sempre_passa(self):
		runs = [_run(True), _run(True), _run(True)]
		assert _flakiness(runs) == 0

	def test_sem_transicoes_quando_sempre_falha(self):
		runs = [_run(False), _run(False)]
		assert _flakiness(runs) == 0

	def test_conta_cada_mudanca_de_resultado(self):
		runs = [_run(True), _run(False), _run(True), _run(True), _run(False)]
		# True->False, False->True, True->False = 3 transicoes
		assert _flakiness(runs) == 3

	def test_uma_execucao_nunca_tem_transicao(self):
		assert _flakiness([_run(True)]) == 0

	def test_lista_vazia_nao_lanca_excecao(self):
		assert _flakiness([]) == 0


class TestComputeStats:
	def test_success_rate_calculada_corretamente(self):
		runs = [_run(True), _run(True), _run(False), _run(False)]
		stats = _compute_stats("AddonTeste", runs)
		assert stats["success_rate"] == 0.5

	def test_pass_at_k_true_com_pelo_menos_1_sucesso(self):
		runs = [_run(False), _run(False), _run(True)]
		stats = _compute_stats("AddonTeste", runs)
		assert stats["pass_at_k"] is True

	def test_pass_at_k_false_sem_nenhum_sucesso(self):
		runs = [_run(False), _run(False)]
		stats = _compute_stats("AddonTeste", runs)
		assert stats["pass_at_k"] is False

	def test_score_mean_e_stdev_calculados(self):
		runs = [_run(True, 90.0), _run(True, 70.0)]
		stats = _compute_stats("AddonTeste", runs)
		assert stats["avg_score_mean"] == 80.0
		assert stats["avg_score_stdev"] is not None

	def test_stdev_none_com_menos_de_2_scores(self):
		stats = _compute_stats("AddonTeste", [_run(True, 90.0)])
		assert stats["avg_score_stdev"] is None

	def test_lista_vazia_nao_lanca_excecao(self):
		stats = _compute_stats("AddonTeste", [])
		assert stats["n_execucoes"] == 0
		assert stats["success_rate"] == 0.0
