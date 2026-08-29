class TestDomainResearcherVersao:
	def test_versao_e_1_4_0(self):
		from nvdastudio.tools.domain_researcher import MODULE_VERSION
		assert MODULE_VERSION == "1.4.0"


class TestAcentuacaoCorrigida:
	"""v1.1.0: _DOMAIN_KNOWLEDGE e _DOMAIN_RESEARCH_SYSTEM estavam escritos
	inteiramente sem acento (convencao de comentario que vazou para texto
	exibido ao usuario via format_domain_context_for_user). Bug real de
	live-test: usuario reportou falta de acento na pesquisa de dominio."""

	def test_domain_research_system_tem_acentos(self):
		from nvdastudio.tools.domain_researcher import _DOMAIN_RESEARCH_SYSTEM
		palavras = ["dom\u00ednio", "est\u00e1", "seguran\u00e7a", "an\u00e1lise", "n\u00e3o"]
		for palavra in palavras:
			assert palavra in _DOMAIN_RESEARCH_SYSTEM, (
				f"Palavra '{palavra}' esperada com acento em _DOMAIN_RESEARCH_SYSTEM"
			)

	def test_domain_knowledge_email_tem_acentos(self):
		from nvdastudio.tools.domain_researcher import _DOMAIN_KNOWLEDGE
		email = _DOMAIN_KNOWLEDGE["email"]
		texto = " ".join(email["apis"] + email["security"] + email["patterns"] + email["nvda_notes"])
		assert "obrigat\u00f3rio" in texto
		assert "autentica\u00e7\u00e3o" in texto

	def test_domain_knowledge_automacao_tem_acentos(self):
		from nvdastudio.tools.domain_researcher import _DOMAIN_KNOWLEDGE
		automacao = _DOMAIN_KNOWLEDGE["automacao"]
		texto = " ".join(automacao["security"] + automacao["nvda_notes"])
		assert "c\u00f3digo arbitr\u00e1rio" in texto
		assert "descri\u00e7\u00e3o" in texto

	def test_relatorio_user_facing_nao_existe(self):
		"""DomainContext pertence aos agentes, nao ao historico da conversa."""
		from nvdastudio.tools import domain_researcher
		assert not hasattr(domain_researcher, "format_domain_context_for_user")


class TestLlmResearchComBuscaExterna:
	"""1.4.0: research_sources agora vem de busca real (Tavily/Exa) via
	external_search.py, nunca mais do LLM 'lembrando' URLs do treinamento."""

	def _make_researcher(self):
		from unittest.mock import MagicMock, patch
		from nvdastudio.tools.domain_researcher import DomainResearcher

		with patch("nvdastudio.gui.settings_panel.get_llm_provider", return_value="ollama"), \
			 patch("nvdastudio.gui.settings_panel.get_llm_model", return_value="kimi-k2.6"), \
			 patch("nvdastudio.tools.domain_researcher.create_llm_client"):
			researcher = DomainResearcher()
			researcher._client = MagicMock()
			return researcher

	def test_research_sources_vem_da_busca_real_quando_configurada(self):
		import json
		from unittest.mock import MagicMock, patch

		researcher = self._make_researcher()
		mock_resp = MagicMock()
		mock_resp.content = json.dumps({
			"domain": "musica", "description": "addon Spotify",
			"apis_involved": ["Spotify Web API"], "best_practices": [],
			"security_requirements": [], "architecture_patterns": [],
			"nvda_specific_notes": [],
			"research_sources": ["https://url-inventada-pelo-llm.example"],  # deve ser IGNORADO
		})
		researcher._client.chat.return_value = mock_resp

		real_results = [{"title": "Spotify Web API", "url": "https://developer.spotify.com/docs", "content": "auth"}]
		with patch("nvdastudio.tools.domain_researcher.search_external", return_value=real_results):
			ctx = researcher._llm_research("addon que toca musica do spotify", "")

		# research_sources = URL REAL da busca, nao a que o LLM colocou no JSON
		assert ctx.research_sources == ["https://developer.spotify.com/docs"]
		assert "url-inventada-pelo-llm" not in ctx.research_sources

	def test_research_sources_vazio_sem_busca_externa_configurada(self):
		import json
		from unittest.mock import MagicMock, patch

		researcher = self._make_researcher()
		mock_resp = MagicMock()
		mock_resp.content = json.dumps({
			"domain": "musica", "description": "addon Spotify",
			"apis_involved": [], "best_practices": [], "security_requirements": [],
			"architecture_patterns": [], "nvda_specific_notes": [],
			"research_sources": ["https://palpite-do-llm.example"],
		})
		researcher._client.chat.return_value = mock_resp

		with patch("nvdastudio.tools.domain_researcher.search_external", return_value=[]):
			ctx = researcher._llm_research("addon que toca musica do spotify", "")

		# Sem busca externa real, research_sources fica vazio -- nao aceita o
		# palpite do LLM (era o bug: URLs fabricadas passavam como se fossem reais).
		assert ctx.research_sources == []

	def test_grounding_injetado_no_prompt_quando_ha_resultados(self):
		import json
		from unittest.mock import MagicMock, patch

		researcher = self._make_researcher()
		mock_resp = MagicMock()
		mock_resp.content = json.dumps({
			"domain": "musica", "description": "x", "apis_involved": [],
			"best_practices": [], "security_requirements": [],
			"architecture_patterns": [], "nvda_specific_notes": [], "research_sources": [],
		})
		researcher._client.chat.return_value = mock_resp

		real_results = [{"title": "Spotify Web API", "url": "https://developer.spotify.com/docs", "content": "auth guide"}]
		with patch("nvdastudio.tools.domain_researcher.search_external", return_value=real_results):
			researcher._llm_research("addon spotify", "")

		sent_prompt = researcher._client.chat.call_args.kwargs["user_message"]
		assert "developer.spotify.com/docs" in sent_prompt
		assert "nao invente URLs" in sent_prompt
