from unittest.mock import MagicMock, patch


class TestExternalSearchVersao:
	def test_versao(self):
		from nvdastudio.tools.external_search import MODULE_VERSION
		assert MODULE_VERSION == "1.0.0"


class TestSearchTavily:
	def test_retorna_vazio_sem_query(self):
		from nvdastudio.tools.external_search import search_tavily
		assert search_tavily("", "tvly-fake") == []

	def test_retorna_vazio_sem_api_key(self):
		from nvdastudio.tools.external_search import search_tavily
		assert search_tavily("spotify api", "") == []

	def test_parseia_resultados_reais(self):
		from nvdastudio.tools.external_search import search_tavily

		mock_resp = MagicMock()
		mock_resp.json.return_value = {
			"results": [
				{"title": "Spotify Web API", "url": "https://developer.spotify.com/docs", "content": "Auth guide", "score": 0.9},
				{"title": "", "url": "https://example.com", "content": "sem titulo"},
			]
		}
		mock_resp.raise_for_status = MagicMock()
		mock_client = MagicMock()
		mock_client.__enter__.return_value.post.return_value = mock_resp

		with patch("nvdastudio.tools.external_search._httpx_module") as mock_httpx:
			mock_httpx.return_value.Client.return_value = mock_client
			result = search_tavily("spotify api", "tvly-fake")

		assert len(result) == 2
		assert result[0]["url"] == "https://developer.spotify.com/docs"
		assert result[0]["title"] == "Spotify Web API"
		assert result[1]["title"] == "https://example.com"  # fallback pro url quando sem titulo

	def test_falha_de_rede_retorna_vazio(self):
		from nvdastudio.tools.external_search import search_tavily

		mock_client = MagicMock()
		mock_client.__enter__.return_value.post.side_effect = RuntimeError("timeout")

		with patch("nvdastudio.tools.external_search._httpx_module") as mock_httpx:
			mock_httpx.return_value.Client.return_value = mock_client
			result = search_tavily("spotify api", "tvly-fake")

		assert result == []


class TestSearchExa:
	def test_retorna_vazio_sem_api_key(self):
		from nvdastudio.tools.external_search import search_exa
		assert search_exa("spotify api", "") == []

	def test_parseia_resultados_reais(self):
		from nvdastudio.tools.external_search import search_exa

		mock_resp = MagicMock()
		mock_resp.json.return_value = {
			"results": [
				{"title": "Spotify API", "url": "https://developer.spotify.com/docs", "summary": "resumo aqui"},
			]
		}
		mock_resp.raise_for_status = MagicMock()
		mock_client = MagicMock()
		mock_client.__enter__.return_value.post.return_value = mock_resp

		with patch("nvdastudio.tools.external_search._httpx_module") as mock_httpx:
			mock_httpx.return_value.Client.return_value = mock_client
			result = search_exa("spotify api", "exa-fake")

		assert len(result) == 1
		assert result[0]["content"] == "resumo aqui"


class TestSearchExternal:
	def test_sem_nenhuma_chave_retorna_vazio(self, monkeypatch):
		from nvdastudio.tools.external_search import search_external
		monkeypatch.delenv("TAVILY_API_KEY", raising=False)
		monkeypatch.delenv("EXA_API_KEY", raising=False)
		assert search_external("spotify api") == []

	def test_combina_e_dedupe_por_url(self, monkeypatch):
		from nvdastudio.tools import external_search

		monkeypatch.setenv("TAVILY_API_KEY", "tvly-fake")
		monkeypatch.setenv("EXA_API_KEY", "exa-fake")

		with patch.object(external_search, "search_tavily", return_value=[
			{"title": "A", "url": "https://a.com", "content": "a"},
			{"title": "Dup", "url": "https://dup.com", "content": "dup-tavily"},
		]), patch.object(external_search, "search_exa", return_value=[
			{"title": "B", "url": "https://b.com", "content": "b"},
			{"title": "Dup", "url": "https://dup.com", "content": "dup-exa"},
		]):
			result = external_search.search_external("spotify api")

		urls = [r["url"] for r in result]
		assert urls == ["https://a.com", "https://dup.com", "https://b.com"]  # dup.com so 1x, mantem a 1a (Tavily)

	def test_so_tavily_configurada(self, monkeypatch):
		from nvdastudio.tools import external_search

		monkeypatch.setenv("TAVILY_API_KEY", "tvly-fake")
		monkeypatch.delenv("EXA_API_KEY", raising=False)

		with patch.object(external_search, "search_tavily", return_value=[
			{"title": "A", "url": "https://a.com", "content": "a"},
		]) as mock_tavily, patch.object(external_search, "search_exa") as mock_exa:
			result = external_search.search_external("spotify api")

		mock_tavily.assert_called_once()
		mock_exa.assert_not_called()
		assert len(result) == 1


class TestFormatResultsForPrompt:
	def test_vazio_retorna_string_vazia(self):
		from nvdastudio.tools.external_search import format_results_for_prompt
		assert format_results_for_prompt([]) == ""

	def test_formata_resultados(self):
		from nvdastudio.tools.external_search import format_results_for_prompt
		results = [{"title": "Spotify API", "url": "https://developer.spotify.com/docs", "content": "resumo"}]
		text = format_results_for_prompt(results)
		assert "developer.spotify.com" in text
		assert "Spotify API" in text
		assert "nao invente URLs" in text
