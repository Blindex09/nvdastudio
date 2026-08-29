from nvdastudio.ai.ollama_client import OllamaClient


def _make_client(model_id="kimi-k2.7-code", monkeypatch=None):
	if monkeypatch is not None:
		monkeypatch.setattr("nvdastudio.ai.ollama_client._HTTPX_AVAILABLE", True)
	return OllamaClient(api_key="k", model_id=model_id)


_SCHEMA_RESPONSE_FORMAT = {
	"type": "json_schema",
	"json_schema": {
		"name": "teste",
		"schema": {
			"type": "object",
			"properties": {"nome": {"type": "string"}},
			"required": ["nome"],
		},
	},
}


class TestGroundingNoCaminhoNaoNativo:
	"""
	2.24.0: json_schema_native=True pro Kimi (k2.6/k2.7-code) foi desmentido
	ao vivo (achado real de auditoria 2026-08-26, ver changelog de
	_MODEL_CAPABILITIES em ollama_client.py) -- testado contra os 17
	modelos reais da conta Ollama Cloud, nenhum seguiu o schema via
	format=<schema>, Kimi incluso (campos inventados, enum virou array,
	campo obrigatorio ausente). Kimi agora usa o MESMO caminho do GLM:
	format="json" + schema injetado como texto + validacao local
	pos-resposta (a rede de seguranca que native=True pulava por engano).
	"""

	def test_kimi_usa_o_mesmo_caminho_do_glm_apos_correcao(self, monkeypatch):
		client = _make_client("kimi-k2.7-code", monkeypatch)
		assert client._caps["json_schema_native"] is False

		fmt, adapted_msg, _sys = client._adapt_structured_output(
			_SCHEMA_RESPONSE_FORMAT, "pedido original do usuario", None,
		)

		assert fmt == "json"
		assert "FORMATO DE SAIDA OBRIGATORIO" in adapted_msg
		assert "pedido original do usuario" in adapted_msg
		assert "nome" in adapted_msg, (
			"prompt deveria conter o schema como texto (grounding), "
			"unica garantia real disponivel hoje via Ollama Cloud"
		)

	def test_glm_continua_com_o_comportamento_anterior_sem_regressao(self, monkeypatch):
		client = _make_client("glm-5.1", monkeypatch)
		assert client._caps["json_schema_native"] is False

		fmt, adapted_msg, _sys = client._adapt_structured_output(
			_SCHEMA_RESPONSE_FORMAT, "pedido original do usuario", None,
		)

		assert fmt == "json"
		assert "FORMATO DE SAIDA OBRIGATORIO" in adapted_msg
		assert "pedido original do usuario" in adapted_msg
