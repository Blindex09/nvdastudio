from datetime import datetime, timedelta, timezone


class TestRetryAfterFormatoSegundos:
	"""
	2026-08-26: _retry_after_seconds()/_retry_backoff() migraram de
	ollama_client.py pra ai/reliability.py (fonte unica compartilhada com
	os outros clientes LLM -- achado real de auditoria: 3 implementacoes
	quase identicas de retry/backoff). _parse_retry_after_header() e o
	equivalente direto; retry_delay() e o contrato publico que os clientes
	de fato chamam.
	"""

	def test_parseia_inteiro_simples(self):
		from nvdastudio.ai.reliability import _parse_retry_after_header
		assert _parse_retry_after_header("30") == 30.0

	def test_parseia_com_espacos(self):
		from nvdastudio.ai.reliability import _parse_retry_after_header
		assert _parse_retry_after_header("  45  ".strip()) == 45.0

	def test_zero_e_valido(self):
		from nvdastudio.ai.reliability import _parse_retry_after_header
		assert _parse_retry_after_header("0") == 0.0

	def test_nunca_retorna_negativo(self):
		"""Servidor mal-comportado devolvendo negativo -- nao deve travar
		nem propagar um sleep() negativo (erro em runtime)."""
		from nvdastudio.ai.reliability import _parse_retry_after_header
		result = _parse_retry_after_header("-5")
		assert result is not None
		assert result >= 0.0


class TestRetryAfterFormatoHttpDate:
	def test_parseia_data_futura(self):
		from nvdastudio.ai.reliability import _parse_retry_after_header
		alvo = datetime.now(timezone.utc) + timedelta(seconds=60)
		http_date = alvo.strftime("%a, %d %b %Y %H:%M:%S GMT")
		result = _parse_retry_after_header(http_date)
		assert result is not None
		# Tolerancia de alguns segundos (tempo de execucao do teste)
		assert 55 <= result <= 65

	def test_data_no_passado_retorna_zero_nao_negativo(self):
		from nvdastudio.ai.reliability import _parse_retry_after_header
		alvo = datetime.now(timezone.utc) - timedelta(seconds=60)
		http_date = alvo.strftime("%a, %d %b %Y %H:%M:%S GMT")
		assert _parse_retry_after_header(http_date) == 0.0


class TestRetryAfterAusenteOuInvalido:
	def test_header_ausente_retorna_none(self):
		from nvdastudio.ai.reliability import _parse_retry_after_header
		assert _parse_retry_after_header("") is None

	def test_valor_nao_parseavel_retorna_none(self):
		from nvdastudio.ai.reliability import _parse_retry_after_header
		assert _parse_retry_after_header("nao-e-nem-segundos-nem-data") is None

	def test_excecao_sem_response_cai_pro_backoff_exponencial(self):
		"""Excecao generica (sem .response) -- fail-open, nunca deve quebrar
		o caminho de retry existente; cai pro backoff exponencial."""
		from nvdastudio.ai.reliability import retry_delay
		result = retry_delay(Exception("erro generico"), attempt=0)
		assert 1.0 <= result <= 1.2

	def test_fallback_pro_backoff_exponencial_quando_sem_header(self):
		"""Contrato do chamador: sem header Retry-After nenhum, o backoff
		exponencial continua disponivel e funcionando."""
		from nvdastudio.ai.reliability import retry_delay
		exc = Exception("sem header nenhum")
		d0 = retry_delay(exc, attempt=0)
		d1 = retry_delay(exc, attempt=1)
		assert 1.0 <= d0 <= 1.2
		assert 2.0 <= d1 <= 2.4
