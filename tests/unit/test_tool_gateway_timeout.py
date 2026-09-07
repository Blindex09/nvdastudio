"""
Timeout por tool no gateway -- prometido em comentario, ausente no codigo.

ACHADO NA VARREDURA DE MECANISMOS ORFAOS (2026-08-30). O tool_gateway tinha:

    _MAX_TOOL_TIMEOUT = 120  # segundos          <- declarado, NUNCA lido
    # 6. Executa o handler local com timeout e retry.   <- comentario promete
    result, error = self._execute_with_retry(...)
    ...
    result = handler(**args)                     <- chamada direta, sem timeout

A constante irma `_MAX_RETRIES` era usada 19 vezes; esta, zero. Assinatura
classica de condicao esquecida.

CONSEQUENCIA REAL: uma tool travada -- leitura de arquivo em disco lento,
validacao de addon gigante -- penduraria o pipeline INDEFINIDAMENTE. Para o
usuario cego e o pior tipo de falha: nada acontece, nada e dito, e ele nao tem
como saber se deve esperar ou desistir. Viola o principio nº3 que o proprio
projeto ensina ao gerador ("toda operacao externa tem limite de tempo
explicito").

A PROVA de que era defeito e nao decisao: existiam DOIS executores de tool no
projeto, e o outro (tool_system/executor.py) sempre fez certo -- ThreadPool com
timeout, stale detection e backoff, consumindo `utils/timeouts`. Esse executor
gemeo foi removido em 2026-09-06 (morto em producao) e sua protecao de pool
descartavel foi portada para o gateway (3.4.0) -- ver TestPoolDescartavelNaoVaza.

A constante local foi REMOVIDA em vez de ligada: `utils/timeouts` ja e a fonte
de verdade, e manter um terceiro numero seria repor a duplicacao (Regra 5).
"""

import threading
import time

import pytest

from nvdastudio.tools import tool_gateway as gw_mod
from nvdastudio.tools.tool_gateway import MODULE_VERSION, ToolGateway

assert MODULE_VERSION == "3.4.0"


@pytest.fixture
def gateway_rapido(monkeypatch):
	"""Teto de 1s para o teste nao levar 60s (o padrao real)."""
	monkeypatch.setattr(gw_mod, "get_tool_timeout", lambda nome: 1.0)
	return ToolGateway()


class TestTimeoutPorTool:
	def test_tool_travada_devolve_erro_em_vez_de_pendurar(self, gateway_rapido):
		"""O ponto central: antes disso, o pipeline esperava para sempre."""
		def travada():
			time.sleep(30)

		inicio = time.time()
		resultado, erro = gateway_rapido._execute_with_retry(travada, {}, "travada")
		decorrido = time.time() - inicio

		assert resultado is None
		assert erro is not None and "timeout" in erro.lower()
		assert decorrido < 10, "o timeout precisa interromper, nao esperar a tool"

	def test_tool_rapida_passa_intacta(self, gateway_rapido):
		"""Falso positivo aqui quebraria toda tool legitima."""
		resultado, erro = gateway_rapido._execute_with_retry(lambda: "ok", {}, "rapida")
		assert resultado == "ok"
		assert erro is None

	def test_argumentos_chegam_ao_handler(self, gateway_rapido):
		"""A execucao passou a ser por pool -- os kwargs nao podem se perder."""
		resultado, erro = gateway_rapido._execute_with_retry(
			lambda a, b: a + b, {"a": 2, "b": 3}, "soma",
		)
		assert resultado == 5
		assert erro is None

	def test_excecao_da_tool_continua_virando_erro(self, gateway_rapido):
		"""Comportamento anterior preservado: erro real nao vira timeout."""
		def explode():
			raise ValueError("falha real da tool")

		resultado, erro = gateway_rapido._execute_with_retry(explode, {}, "explode")
		assert resultado is None
		assert "falha real da tool" in str(erro)
		assert "timeout" not in str(erro).lower()

	def test_mensagem_de_erro_diz_o_tempo(self, gateway_rapido):
		"""Sem o numero, o usuario nao sabe se a tool e lenta ou se travou."""
		resultado, erro = gateway_rapido._execute_with_retry(
			lambda: time.sleep(30), {}, "lenta",
		)
		assert "1s" in str(erro)


class TestPoolDescartavelNaoVaza:
	"""Regressao 3.4.0: uma tool travada nunca pode prender uma chamada futura.

	Antes, o gateway usava um pool COMPARTILHADO de max_workers=4 e
	`future.cancel()` (no-op quando a task ja roda). 4 tools travadas ocupavam
	os 4 workers para sempre e TODA chamada seguinte enfileirava sem fim -- o
	pipeline pendurava em silencio, o pior tipo de falha para o usuario cego.
	Esta cobertura vivia so contra o ToolExecutor (removido em 2026-09-06); o
	executor VIVO -- o gateway -- nao a tinha. Ver auditoria-confirmacao-2026-09-06.
	"""

	def test_tools_travadas_nao_esgotam_o_gateway(self, monkeypatch):
		monkeypatch.setattr(gw_mod, "get_tool_timeout", lambda nome: 0.3)
		# Backoff instantaneo: o retry por timeout nao deve inflar o teste.
		monkeypatch.setattr(gw_mod, "calculate_backoff_delay", lambda tentativa: 0.0)
		gw = ToolGateway()

		liberar = threading.Event()

		def travada():
			liberar.wait(timeout=10)

		# 5 tools travadas -- estritamente MAIS que os 4 workers do pool antigo.
		# Com o bug, a 5a ja enfileiraria; aqui cada uma isola seu proprio pool.
		for _ in range(5):
			resultado, erro = gw._execute_with_retry(travada, {}, "travada")
			assert resultado is None
			assert erro is not None and "timeout" in erro.lower()

		# O ponto: depois de 5 travamentos, uma tool rapida responde NA HORA.
		# Com o pool compartilhado esgotado, ela ficaria presa atras das
		# travadas ate `liberar.set()` -- e este assert falharia por tempo.
		inicio = time.time()
		resultado, erro = gw._execute_with_retry(lambda: "ok", {}, "rapida")
		decorrido = time.time() - inicio

		liberar.set()  # solta as threads travadas antes de encerrar o teste

		assert resultado == "ok" and erro is None
		assert decorrido < 2.0, (
			"a tool rapida ficou presa atras das travadas -- o pool esgotou, "
			"o vazamento de thread voltou"
		)


class TestFonteUnicaDoTimeout:
	def test_constante_local_foi_removida(self):
		"""Um terceiro numero local reporia a duplicacao que a Regra 5 proibe --
		`utils/timeouts` e a fonte de verdade, e o executor irmao ja a usa."""
		assert not hasattr(gw_mod, "_MAX_TOOL_TIMEOUT"), (
			"_MAX_TOOL_TIMEOUT voltou: use get_tool_timeout() de utils/timeouts"
		)

	def test_gateway_consome_o_modulo_central(self):
		import inspect

		src = inspect.getsource(gw_mod)
		assert "from ..utils.timeouts import get_tool_timeout" in src
		# 2026-09-06: antes havia aqui um test_os_dois_executores_usam_a_mesma_fonte
		# que importava tool_system/executor.py e exigia que os DOIS executores
		# usassem get_tool_timeout. O executor gemeo foi removido (morto em
		# producao); resta um so executor -- o gateway -- e a assercao acima ja
		# garante que ele consome a fonte unica de timeout.
