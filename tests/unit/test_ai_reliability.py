from unittest.mock import MagicMock

import pytest


class FakeHttpError(Exception):
	def __init__(self, message, status_code=None, response=None):
		super().__init__(message)
		self.status_code = status_code
		self.response = response


class TestIsRetryable:
	def test_status_retryable(self):
		from nvdastudio.ai.reliability import is_retryable
		for status in (408, 429, 500, 502, 503, 504, 529):
			assert is_retryable(FakeHttpError("erro", status_code=status))

	def test_status_nao_retryable(self):
		from nvdastudio.ai.reliability import is_retryable
		assert not is_retryable(FakeHttpError("erro", status_code=400))
		assert not is_retryable(FakeHttpError("erro", status_code=401))

	def test_sem_status_usa_nome_da_excecao(self):
		from nvdastudio.ai.reliability import is_retryable

		class TimeoutException(Exception):
			pass

		assert is_retryable(TimeoutException("deu timeout"))
		assert not is_retryable(ValueError("erro comum"))


class TestRetryDelay:
	def test_extrai_tempo_do_texto_do_erro_gemini(self):
		"""Achado real 2026-08-04: Gemini free-tier embute o tempo no texto,
		nao em header nem campo estruturado."""
		from nvdastudio.ai.reliability import retry_delay
		response = MagicMock()
		response.text = "Rate limited. Please retry in 24.8s."
		response.headers = {}
		exc = FakeHttpError("429", status_code=429, response=response)
		assert retry_delay(exc, 0) == pytest.approx(25.3, abs=0.01)

	def test_extrai_do_header_retry_after_delta_segundos(self):
		from nvdastudio.ai.reliability import retry_delay
		response = MagicMock()
		response.text = ""
		response.headers = {"retry-after": "5"}
		exc = FakeHttpError("429", status_code=429, response=response)
		assert retry_delay(exc, 0) == 5.0

	def test_extrai_do_header_retry_after_http_date(self):
		"""RFC 7231: Retry-After tambem aceita HTTP-date, nao so delta-segundos
		(achado real 2026-08-18, ollama_client.py -- Ollama Cloud honra o header
		em 429)."""
		from datetime import datetime, timedelta, timezone
		from email.utils import format_datetime
		from nvdastudio.ai.reliability import retry_delay
		future = datetime.now(timezone.utc) + timedelta(seconds=10)
		response = MagicMock()
		response.text = ""
		response.headers = {"retry-after": format_datetime(future, usegmt=True)}
		exc = FakeHttpError("429", status_code=429, response=response)
		assert retry_delay(exc, 0) == pytest.approx(10.0, abs=1.0)

	def test_backoff_exponencial_quando_sem_dica_nenhuma(self):
		from nvdastudio.ai.reliability import retry_delay
		exc = FakeHttpError("500", status_code=500)
		d0 = retry_delay(exc, 0)
		d1 = retry_delay(exc, 1)
		assert 1.0 <= d0 <= 1.2
		assert 2.0 <= d1 <= 2.4

	def test_nunca_excede_o_teto(self):
		from nvdastudio.ai.reliability import retry_delay, _MAX_RETRY_DELAY
		exc = FakeHttpError("500", status_code=500)
		assert retry_delay(exc, 10) <= _MAX_RETRY_DELAY


class TestCallWithRetry:
	def test_sucesso_na_primeira_tentativa_nao_espera(self):
		from nvdastudio.ai.reliability import call_with_retry
		result = call_with_retry(lambda: "ok")
		assert result == "ok"

	def test_retenta_ate_suceder(self, monkeypatch):
		from nvdastudio.ai import reliability
		monkeypatch.setattr(reliability.time, "sleep", lambda _s: None)
		calls = {"n": 0}

		def flaky():
			calls["n"] += 1
			if calls["n"] < 3:
				raise FakeHttpError("500", status_code=500)
			return "ok"

		result = reliability.call_with_retry(flaky, max_attempts=5)
		assert result == "ok"
		assert calls["n"] == 3

	def test_erro_nao_retryable_propaga_na_hora(self):
		from nvdastudio.ai.reliability import call_with_retry

		def sempre_falha():
			raise FakeHttpError("400", status_code=400)

		with pytest.raises(FakeHttpError):
			call_with_retry(sempre_falha, max_attempts=5)

	def test_esgota_tentativas_e_propaga_ultimo_erro(self, monkeypatch):
		from nvdastudio.ai import reliability
		monkeypatch.setattr(reliability.time, "sleep", lambda _s: None)

		def sempre_falha():
			raise FakeHttpError("503", status_code=503)

		with pytest.raises(FakeHttpError):
			reliability.call_with_retry(sempre_falha, max_attempts=2)

	def test_deteccao_de_loop_mesma_falha_3x_seguidas(self, monkeypatch):
		from nvdastudio.ai import reliability
		monkeypatch.setattr(reliability.time, "sleep", lambda _s: None)

		def sempre_a_mesma_falha():
			raise FakeHttpError("mesmo erro sempre", status_code=500)

		with pytest.raises(reliability.LoopDetectedError) as exc_info:
			reliability.call_with_retry(sempre_a_mesma_falha, max_attempts=10)
		assert exc_info.value.attempts == reliability.LOOP_DETECTION_THRESHOLD

	def test_falhas_diferentes_nao_disparam_deteccao_de_loop(self, monkeypatch):
		from nvdastudio.ai import reliability
		monkeypatch.setattr(reliability.time, "sleep", lambda _s: None)
		messages = iter(["erro A", "erro B", "erro C"])

		def falha_variada():
			raise FakeHttpError(next(messages), status_code=500)

		with pytest.raises(FakeHttpError):
			reliability.call_with_retry(falha_variada, max_attempts=3)

	def test_on_retry_e_chamado_a_cada_tentativa_retentavel(self, monkeypatch):
		from nvdastudio.ai import reliability
		monkeypatch.setattr(reliability.time, "sleep", lambda _s: None)
		chamadas = []

		def flaky():
			if len(chamadas) < 2:
				raise FakeHttpError("500", status_code=500)
			return "ok"

		reliability.call_with_retry(
			flaky, max_attempts=5,
			on_retry=lambda attempt, delay, exc: chamadas.append(attempt),
		)
		assert chamadas == [1, 2]
