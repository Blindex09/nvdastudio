from unittest.mock import MagicMock, patch

import nvdastudio.ai.ollama_client as ollama_client_mod
from nvdastudio.ai.ollama_client import OllamaClient


def _fake_httpx(response_json, status_ok=True):
	fake_response = MagicMock()
	fake_response.json.return_value = response_json
	if status_ok:
		fake_response.raise_for_status.return_value = None
	else:
		fake_response.raise_for_status.side_effect = Exception("HTTP error")

	fake_client_instance = MagicMock()
	fake_client_instance.post.return_value = fake_response
	fake_client_instance.__enter__.return_value = fake_client_instance
	fake_client_instance.__exit__.return_value = False

	fake_httpx = MagicMock()
	fake_httpx.Client.return_value = fake_client_instance
	return fake_httpx, fake_client_instance


class TestWebFetch:
	def test_web_fetch_usa_endpoint_dedicado_com_bearer(self):
		fake_httpx, fake_client_instance = _fake_httpx({
			"title": "Requests", "content": "Requests e uma biblioteca HTTP.", "links": ["https://x.com"],
		})
		client = OllamaClient(api_key="minha-chave", model_id="kimi-k2.7-code")
		with patch.object(ollama_client_mod, "_httpx", fake_httpx):
			result = client.web_fetch("https://requests.readthedocs.io")

		url_called, kwargs = fake_client_instance.post.call_args
		assert url_called[0] == "https://ollama.com/api/web_fetch"
		assert kwargs["headers"]["Authorization"] == "Bearer minha-chave"
		assert kwargs["json"] == {"url": "https://requests.readthedocs.io"}
		assert "Requests e uma biblioteca HTTP." in result
		assert "Titulo: Requests" in result

	def test_web_fetch_vazio_sem_url(self):
		client = OllamaClient(api_key="k", model_id="kimi-k2.7-code")
		assert client.web_fetch("") == ""
		assert client.web_fetch("   ") == ""

	def test_web_fetch_sem_content_retorna_vazio(self):
		fake_httpx, _ = _fake_httpx({"title": "X", "content": "", "links": []})
		client = OllamaClient(api_key="k", model_id="kimi-k2.7-code")
		with patch.object(ollama_client_mod, "_httpx", fake_httpx):
			assert client.web_fetch("https://x.com") == ""

	def test_web_fetch_engole_excecao_e_retorna_vazio(self):
		fake_httpx, fake_client_instance = _fake_httpx({}, status_ok=False)
		client = OllamaClient(api_key="k", model_id="kimi-k2.7-code")
		with patch.object(ollama_client_mod, "_httpx", fake_httpx):
			assert client.web_fetch("https://x.com") == ""

	def test_web_fetch_endpoint_e_diferente_do_web_search(self):
		assert ollama_client_mod._OLLAMA_CLOUD_WEB_FETCH_URL != ollama_client_mod._OLLAMA_CLOUD_WEB_SEARCH_URL
		assert ollama_client_mod._OLLAMA_CLOUD_WEB_FETCH_URL == "https://ollama.com/api/web_fetch"


class TestFetchUrlToolWiredNoCodeGenerator:
	def test_fetch_url_tool_declarado_no_schema(self):
		import inspect
		import nvdastudio.sub_agents.code_generator as mod
		src = inspect.getsource(mod)
		assert '"name": "fetch_url"' in src

	def test_fetch_url_tool_usa_web_fetch_quando_disponivel(self):
		from nvdastudio.sub_agents.code_generator import _fetch_url_tool

		fake_client = MagicMock(spec=["web_fetch"])
		fake_client.web_fetch.return_value = "conteudo completo da pagina"

		with patch("nvdastudio.sub_agents.code_generator.create_llm_client", return_value=fake_client):
			result = _fetch_url_tool("https://docs.exemplo.com")

		assert result["status"] == "fetched"
		assert "conteudo completo" in result["content"]

	def test_fetch_url_tool_indisponivel_para_provedor_sem_web_fetch(self):
		from nvdastudio.sub_agents.code_generator import _fetch_url_tool

		fake_client = MagicMock(spec=[])  # sem web_fetch (ex: OpenAI/Anthropic/Gemini/xAI)
		with patch("nvdastudio.sub_agents.code_generator.create_llm_client", return_value=fake_client):
			result = _fetch_url_tool("https://docs.exemplo.com")

		assert result["status"] == "unavailable"
