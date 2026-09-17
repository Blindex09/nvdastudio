"""Evals pagos opcionais. Nunca rodam sem opt-in explícito e credencial."""
from __future__ import annotations

import os

import pytest

from nvdastudio.ai.llm_factory import create_llm_client


@pytest.mark.parametrize(
	("provider", "model_env", "key_env"),
	[
		("ollama", "NVDASTUDIO_EVAL_OLLAMA_MODEL", "OLLAMA_API_KEY"),
		("openai", "NVDASTUDIO_EVAL_OPENAI_MODEL", "OPENAI_API_KEY"),
		("gemini", "NVDASTUDIO_EVAL_GEMINI_MODEL", "GEMINI_API_KEY"),
		("anthropic", "NVDASTUDIO_EVAL_ANTHROPIC_MODEL", "ANTHROPIC_API_KEY"),
		("xai", "NVDASTUDIO_EVAL_XAI_MODEL", "XAI_API_KEY"),
		("opencode_go", "NVDASTUDIO_EVAL_OPENCODE_GO_MODEL", "OPENCODE_GO_API_KEY"),
		("factory", "NVDASTUDIO_EVAL_FACTORY_MODEL", ""),
	],
)
def test_provider_real_responde_ao_contrato_minimo(provider, model_env, key_env):
	if os.getenv("NVDASTUDIO_RUN_LIVE_AGENT_EVALS") != "1":
		pytest.skip("eval pago desativado")
	if not os.getenv(model_env) or (key_env and not os.getenv(key_env)):
		pytest.skip(f"{key_env}/{model_env} não configurados")
	client = create_llm_client(model_id=os.environ[model_env], provider=provider)
	response = client.chat("Responda somente OK.", system_override="Teste de contrato.")
	assert response.content.strip()
