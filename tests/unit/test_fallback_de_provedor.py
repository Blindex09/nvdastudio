"""
Chave rejeitada por UM provedor nao pode matar o addon inteiro.

Medido em 2026-09-02, em duas execucoes: o step cg_service morreu com
"[ERRO] OpenCode Go API falhou: Client error '401 Unauthorized'", com
retries=0 e tokens=0 -- enquanto o Ollama estava configurado e funcionando na
mesma maquina.

O fallback de infraestrutura que ja existia troca de MODELO dentro do MESMO
provedor. Isso resolve timeout e 503, e nao resolve nada numa chave invalida,
expirada ou sem cota: o problema e a conta, nao o modelo.

A deteccao roda SO dentro do ramo que ja confirmou erro de infraestrutura. O
projeto ja se queimou com regex de infra batendo em codigo GERADO que continha
"status == 503" (fix v4.1.1) -- por isso o mesmo cuidado aqui.
"""

import inspect

from nvdastudio.core.orchestrator import (
	_ERRO_DE_AUTENTICACAO_RE,
	MODULE_VERSION,
	Orchestrator,
	_modelo_de_outro_provedor,
)


def test_versao():
	assert MODULE_VERSION == "5.76.0"


class TestDeteccaoDeAutenticacao:
	def test_reconhece_as_formas_reais(self):
		for texto in (
			"OpenCode Go API falhou: Client error '401 Unauthorized'",
			"HTTP 403 Forbidden",
			"invalid api key",
			"API key invalid",
		):
			assert _ERRO_DE_AUTENTICACAO_RE.search(texto), texto

	def test_nao_confunde_com_outras_falhas_de_infra(self):
		"""Timeout e 503 se resolvem trocando de modelo -- nao devem disparar
		troca de provedor."""
		for texto in ("timeout apos 300s", "HTTP 503 service unavailable",
					  "connection reset by peer"):
			assert not _ERRO_DE_AUTENTICACAO_RE.search(texto), texto


class TestEscolhaDeOutroProvedor:
	def test_escolhe_provedor_diferente_com_chave(self, monkeypatch):
		monkeypatch.setenv("OLLAMA_API_KEY", "chave-de-teste")
		escolhido = _modelo_de_outro_provedor("opencode_go")
		assert escolhido, "havia provedor alternativo com chave e nada foi escolhido"

	def test_nunca_devolve_o_provedor_que_falhou(self, monkeypatch):
		"""Insistir na conta rejeitada e repetir o mesmo 401."""
		monkeypatch.setenv("OLLAMA_API_KEY", "chave-de-teste")
		from nvdastudio.ai.model_registry import get_provider_step_models

		do_ollama = set(get_provider_step_models("ollama").values())
		assert _modelo_de_outro_provedor("ollama") not in do_ollama

	def test_sem_alternativa_devolve_vazio(self, monkeypatch):
		"""Sem outro provedor com chave nao ha o que tentar, e o erro segue
		como estava -- inventar um modelo so trocaria 401 por outra falha."""
		for var in ("OLLAMA_API_KEY", "OPENCODE_GO_API_KEY", "ANTHROPIC_API_KEY",
					"OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY"):
			monkeypatch.delenv(var, raising=False)
		monkeypatch.setattr(
			"nvdastudio.gui.settings_panel.get_api_key", lambda _p: "",
		)
		assert _modelo_de_outro_provedor("ollama") == ""


def test_a_troca_so_acontece_no_ramo_de_erro_de_infra():
	"""A costura que protege contra o falso positivo historico: a deteccao de
	autenticacao nao pode ser avaliada sobre codigo gerado."""
	src = inspect.getsource(Orchestrator)
	i = src.index("_ERRO_DE_AUTENTICACAO_RE.search")
	# a mesma condicao precisa exigir o prefixo [ERRO] antes
	trecho = src[max(0, i - 200):i + 60]
	assert "_IS_SUBAGENT_ERROR_RE.search(last_output)" in trecho
	assert "_modelo_de_outro_provedor(" in src
