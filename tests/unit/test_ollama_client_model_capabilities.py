from nvdastudio.ai.ollama_client import OllamaClient, _MODEL_CAPABILITIES


class TestModelCapabilitiesGlmQwen:
	def test_glm_5_1_tem_entrada_propria_sem_json_schema_native(self):
		assert "glm-5.1" in _MODEL_CAPABILITIES
		assert _MODEL_CAPABILITIES["glm-5.1"]["json_schema_native"] is False
		assert _MODEL_CAPABILITIES["glm-5.1"]["json_object_only"] is True

	def test_qwen3_5_tem_entrada_propria(self):
		# 2.22.0: chave real e "qwen3.5:397b" (model_registry.py
		# _PROVIDER_TIER_MODELS["ollama"]["frontier"]) -- "qwen3.5" sem o
		# tag nunca batia contra o model_id de verdade usado em producao.
		assert "qwen3.5:397b" in _MODEL_CAPABILITIES

	def test_client_com_glm_nao_herda_capacidades_do_kimi(self, monkeypatch):
		monkeypatch.setattr("nvdastudio.ai.ollama_client._HTTPX_AVAILABLE", True)
		client = OllamaClient(api_key="k", model_id="glm-5.1")
		assert client._caps["json_schema_native"] is False

	def test_client_com_qwen3_5_397b_nao_herda_capacidades_do_kimi(self, monkeypatch):
		"""Achado real (auditoria de integracao 2026-08-09): o tier
		'frontier' inteiro herdava silenciosamente json_schema_native=True
		do Kimi porque a chave nao batia com o model_id real."""
		monkeypatch.setattr("nvdastudio.ai.ollama_client._HTTPX_AVAILABLE", True)
		client = OllamaClient(api_key="k", model_id="qwen3.5:397b")
		assert client._caps["json_schema_native"] is False

	def test_todos_os_modelos_do_catalogo_real_tem_entrada_propria(self):
		"""9 modelos confirmados no catalogo real da conta (model_registry.py
		1.15.0, GET https://ollama.com/api/tags) nunca tinham entrada aqui --
		cada um herdava as flags do Kimi por coincidencia do fallback."""
		esperados = [
			"glm-5.2", "minimax-m3", "gpt-oss:120b", "minimax-m2.7",
			"deepseek-v4-pro", "nemotron-3-ultra", "nemotron-3-super",
			"nemotron-3-nano:30b", "mistral-large-3:675b", "gemma4:31b",
		]
		for model_id in esperados:
			assert model_id in _MODEL_CAPABILITIES, f"{model_id} sem entrada propria"


class TestReasoningEffortSoQuandoModeloTemThinking:
	"""Achado de auditoria (antes do E2E real via Ollama Cloud, 2026-09-28):
	o payload["think"] era montado sempre que reasoning_effort chegava, sem
	checar thinking_native -- um modelo sem thinking nenhum (deepseek-v4-flash,
	"foco em velocidade") receberia think=True de qualquer jeito assim que
	qualquer chamador passasse reasoning_effort (o que passou a acontecer de
	verdade nesta mesma auditoria, ver agentic_driver.py)."""

	class _FakeResponse:
		def __init__(self, payload):
			self._payload = payload

		def raise_for_status(self):
			pass

		def json(self):
			return {"message": {"content": "ok", "tool_calls": []}}

	class _FakeClient:
		captured: list = []

		def __init__(self, *a, **kw):
			pass

		def __enter__(self):
			return self

		def __exit__(self, *a):
			return False

		def post(self, url, headers=None, json=None):
			TestReasoningEffortSoQuandoModeloTemThinking._FakeClient.captured.append(json)
			return TestReasoningEffortSoQuandoModeloTemThinking._FakeResponse(json)

	def _chat_and_capture(self, monkeypatch, model_id, reasoning_effort):
		monkeypatch.setattr("nvdastudio.ai.ollama_client._HTTPX_AVAILABLE", True)
		self._FakeClient.captured = []
		fake_module = type("m", (), {"Client": self._FakeClient})
		monkeypatch.setattr("nvdastudio.ai.ollama_client._httpx", fake_module)
		client = OllamaClient(api_key="k", model_id=model_id)
		client.chat("oi", reasoning_effort=reasoning_effort)
		return self._FakeClient.captured[0]

	def test_modelo_sem_thinking_nunca_recebe_think(self, monkeypatch):
		payload = self._chat_and_capture(monkeypatch, "deepseek-v4-flash", "medium")
		assert "think" not in payload

	def test_modelo_com_thinking_e_effort_recebe_o_nivel(self, monkeypatch):
		payload = self._chat_and_capture(monkeypatch, "gpt-oss:20b", "low")
		assert payload["think"] == "low"

	def test_modelo_com_thinking_sem_effort_recebe_booleano(self, monkeypatch):
		payload = self._chat_and_capture(monkeypatch, "kimi-k2.6", "medium")
		assert payload["think"] is True
