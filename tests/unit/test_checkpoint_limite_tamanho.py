"""
Limite de ESPACO dos checkpoints, nao so de quantidade.

ACHADO POR AUDITORIA DE MECANISMOS ORFAOS (2026-08-30): `_MAX_TOTAL_SIZE_MB =
100` estava declarado em checkpoint_manager.py e NUNCA era lido. A poda aplicava
so `_MAX_SNAPSHOTS = 20` -- contagem, nao espaco.

Contar arquivos nao protege o disco: 20 checkpoints de um addon multi-arquivo
com contexto grande passam facilmente dos 100 MB, e o usuario cego nao tem como
perceber o disco enchendo. Limite declarado e nao aplicado e pior que limite
nenhum -- da a impressao de que o problema esta tratado.

Mesma classe dos outros 6 defeitos desta sessao: o mecanismo existia e ninguem
o consumia.

NOTA DE CUSTO DO TESTE: a primeira versao destes casos escrevia arquivos de 30
a 150 MB para estourar o teto real de 100 MB -- e derrubou o pytest com
MemoryError. Teste que precisa de 150 MB de disco para provar uma regra de
aritmetica esta medindo a coisa certa do jeito errado. Aqui o TETO e reduzido
via monkeypatch e os arquivos ficam na casa dos KB: mesma logica exercitada,
custo desprezivel.
"""

import os
import time

import pytest

from nvdastudio.core import checkpoint_manager as cm_mod
from nvdastudio.core.checkpoint_manager import _MAX_SNAPSHOTS, CheckpointManager

_TETO_MB_DE_TESTE = 1  # 1 MB, contra os 100 MB de producao


@pytest.fixture(autouse=True)
def _teto_pequeno(monkeypatch):
	monkeypatch.setattr(cm_mod, "_MAX_TOTAL_SIZE_MB", _TETO_MB_DE_TESTE)


def _escreve(pasta, nome: str, tamanho_kb: int, idade_s: float = 0.0) -> None:
	arq = pasta / nome
	arq.write_bytes(b"x" * (tamanho_kb * 1024))
	if idade_s:
		antigo = time.time() - idade_s
		os.utime(arq, (antigo, antigo))


def _manager_em(tmp_path):
	m = CheckpointManager()
	pasta = tmp_path / "proj"
	pasta.mkdir()
	m._project_dir = lambda workdir: pasta  # type: ignore[method-assign]
	m._last_prune = 0.0
	return m, pasta


class TestPodaPorTamanho:
	def test_poda_por_espaco_mesmo_dentro_do_limite_de_quantidade(self, tmp_path):
		"""5 checkpoints (bem abaixo de 20) somando mais que o teto precisam ser
		podados -- era exatamente o caso que passava batido."""
		m, pasta = _manager_em(tmp_path)
		for i in range(5):
			_escreve(pasta, f"cp{i}.json", tamanho_kb=400, idade_s=100 - i)
		assert len(list(pasta.glob("*.json"))) == 5

		m._prune_project(str(tmp_path))

		restantes = list(pasta.glob("*.json"))
		total_mb = sum(p.stat().st_size for p in restantes) / (1024 * 1024)
		assert len(restantes) < 5, "nada foi podado apesar de estourar o teto de espaco"
		assert total_mb <= _TETO_MB_DE_TESTE * 1.05

	def test_remove_os_mais_antigos_primeiro(self, tmp_path):
		m, pasta = _manager_em(tmp_path)
		for i in range(4):
			_escreve(pasta, f"cp{i}.json", tamanho_kb=400, idade_s=1000 - i * 100)

		m._prune_project(str(tmp_path))

		nomes = {p.name for p in pasta.glob("*.json")}
		assert "cp3.json" in nomes, "o mais recente nunca pode ser o primeiro a sair"
		assert "cp0.json" not in nomes, "o mais antigo deveria ter saido"

	def test_nunca_remove_o_ultimo_checkpoint(self, tmp_path):
		"""Um checkpoint sozinho acima do teto ainda e a UNICA chance de
		retomada que o usuario tem -- apagar seria trocar disco por trabalho
		perdido."""
		m, pasta = _manager_em(tmp_path)
		_escreve(pasta, "unico.json", tamanho_kb=3000)

		m._prune_project(str(tmp_path))

		assert (pasta / "unico.json").exists()

	def test_poda_por_quantidade_continua_valendo(self, tmp_path):
		"""O criterio antigo nao foi substituido -- os dois agem juntos."""
		m, pasta = _manager_em(tmp_path)
		for i in range(_MAX_SNAPSHOTS + 5):
			_escreve(pasta, f"cp{i:03d}.json", tamanho_kb=1, idade_s=1000 - i)

		m._prune_project(str(tmp_path))

		assert len(list(pasta.glob("*.json"))) == _MAX_SNAPSHOTS

	def test_poucos_e_pequenos_nao_sao_tocados(self, tmp_path):
		"""Falso positivo aqui apagaria retomada valida do usuario."""
		m, pasta = _manager_em(tmp_path)
		for i in range(3):
			_escreve(pasta, f"cp{i}.json", tamanho_kb=10, idade_s=10 - i)

		m._prune_project(str(tmp_path))

		assert len(list(pasta.glob("*.json"))) == 3

	def test_pasta_inexistente_nao_levanta(self, tmp_path):
		"""Roda em background durante o pipeline: excecao aqui seria ruido."""
		m = CheckpointManager()
		m._project_dir = lambda workdir: tmp_path / "nao_existe"  # type: ignore[method-assign]
		m._last_prune = 0.0
		m._prune_project(str(tmp_path))
