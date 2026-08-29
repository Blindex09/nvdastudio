import os

import pytest

_PROVIDERS_E_ENV_VARS: dict[str, str] = {
	"ollama": "OLLAMA_API_KEY",
	"openai": "OPENAI_API_KEY",
	"gemini": "GEMINI_API_KEY",
	"anthropic": "ANTHROPIC_API_KEY",
	"xai": "XAI_API_KEY",
	"opencode_go": "OPENCODE_GO_API_KEY",
}


def _skip_unless_key(provider: str):
	env_var = _PROVIDERS_E_ENV_VARS[provider]
	has_key = bool(os.environ.get(env_var, "").strip())
	return pytest.mark.skipif(not has_key, reason=f"{env_var} nao disponivel")


def _smoke_chat(provider: str) -> None:
	"""Chamada minima real: 1 mensagem trivial, so confirma que a chave
	funciona e o parser de resposta do provider bate com o formato real."""
	from nvdastudio.ai.llm_factory import create_llm_client
	from nvdastudio.ai.model_registry import resolve_provider_tier_model

	model_id = resolve_provider_tier_model(provider, "light")
	client = create_llm_client(model_id=model_id, provider=provider)
	response = client.chat("Responda apenas: ok")

	assert response is not None
	assert response.content is not None
	assert response.content.strip() != "", (
		f"{provider}: resposta vazia -- possivel regressao de formato/parser "
		f"(mesmo padrao ja visto com modelos de raciocinio sem "
		f"reasoning_effort explicito)"
	)


class TestSmokeConectividadeOllama:
	@_skip_unless_key("ollama")
	def test_ollama_responde(self):
		_smoke_chat("ollama")


class TestSmokeConectividadeOpenAI:
	@_skip_unless_key("openai")
	def test_openai_responde(self):
		_smoke_chat("openai")


class TestSmokeConectividadeGemini:
	@_skip_unless_key("gemini")
	def test_gemini_responde(self):
		_smoke_chat("gemini")


class TestSmokeConectividadeAnthropic:
	@_skip_unless_key("anthropic")
	def test_anthropic_responde(self):
		_smoke_chat("anthropic")


class TestSmokeConectividadeXai:
	@_skip_unless_key("xai")
	def test_xai_responde(self):
		_smoke_chat("xai")


class TestSmokeConectividadeOpenCodeGo:
	@_skip_unless_key("opencode_go")
	def test_opencode_go_responde(self):
		_smoke_chat("opencode_go")
