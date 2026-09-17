from types import SimpleNamespace

from nvdastudio.ai.llm_client import LLMClientError, LLMResponse
from nvdastudio.ai import model_router
from nvdastudio.ai.model_router import (
	extract_required_capabilities,
	record_provider_outcome,
	select_routes,
)


def setup_function():
	model_router._provider_health.clear()


def teardown_function():
	model_router._provider_health.clear()


def test_provedor_manual_nunca_faz_roteamento_cruzado():
	routes = select_routes(
		"openai", "code_generation", "alto",
		request="crie um addon [TASK-COMPLEXITY: high]",
		available_providers=["openai", "gemini"],
		required_capabilities=frozenset({"tool_use"}),
	)
	assert len(routes) == 1
	assert routes[0].provider == "openai"
	assert "manualmente" in routes[0].reason


def test_capacidade_multimodal_vem_de_metadado_semantico_explicito():
	assert extract_required_capabilities(
		"addon de áudio [MODEL-CAPABILITIES: vision,audio,inventada]"
	) == frozenset({"vision", "audio"})
	assert extract_required_capabilities("crie um addon que processará áudio") == frozenset()


def test_studio_classifica_todos_os_provedores_disponiveis():
	routes = select_routes(
		"studio", "code_generation", "alto",
		request="crie um addon [TASK-COMPLEXITY: high]",
		available_providers=["openai", "gemini", "anthropic"],
		required_capabilities=frozenset({"tool_use"}),
	)
	assert routes
	assert {route.provider for route in routes}.issubset({"openai", "gemini", "anthropic"})
	assert all(route.reason and route.estimated_context_tokens for route in routes)


def test_preferencia_privacidade_impede_replicar_contexto_em_failover():
	routes = select_routes(
		"studio", "code_generation", "alto",
		request="[ROUTING-PREFERENCE: privacy]",
		available_providers=["openai", "gemini", "anthropic"],
		required_capabilities=frozenset({"tool_use"}),
	)
	assert len(routes) == 1
	assert routes[0].preference == "privacy"


def test_circuit_breaker_retira_provedor_instavel_temporariamente():
	for _ in range(2):
		record_provider_outcome("openai", False, "503")
	routes = select_routes(
		"studio", "code_generation", "alto",
		available_providers=["openai", "gemini"],
		required_capabilities=frozenset({"tool_use"}),
	)
	assert routes
	assert all(route.provider != "openai" for route in routes)


def test_studio_client_faz_failover_de_chamada(monkeypatch):
	from nvdastudio.ai import llm_factory, studio_client
	from nvdastudio.gui import settings_panel

	routes = [
		SimpleNamespace(provider="openai", model_id="a", to_dict=lambda: {}),
		SimpleNamespace(provider="gemini", model_id="b", to_dict=lambda: {}),
	]
	monkeypatch.setattr(studio_client, "select_routes", lambda *args, **kwargs: routes)
	monkeypatch.setattr(settings_panel, "get_studio_available_providers", lambda: ("openai", "gemini"))

	class _Failing:
		def chat(self, *args, **kwargs):
			raise LLMClientError("503")

	class _Working:
		def chat(self, *args, **kwargs):
			return LLMResponse("ok", "b")

	clients = iter([_Failing(), _Working()])
	monkeypatch.setattr(llm_factory, "create_llm_client", lambda **kwargs: next(clients))
	response = studio_client.StudioClient().chat("oi")
	assert response.content == "ok"
	assert response.model_used == "gemini::b"
