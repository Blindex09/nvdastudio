"""Cliente virtual do provedor Studio com roteamento e failover auditáveis."""
from __future__ import annotations

from typing import Any, Callable

from .llm_client import LLMClientError, LLMResponse
from .model_registry import ALTO_MODEL
from .model_router import record_provider_outcome, select_routes
from ..utils.logger import get_logger

MODULE_VERSION = "1.0.0"
_logger = get_logger("studio_client")


class StudioClient:
	"""Resolve cada chamada entre os provedores já configurados pelo usuário."""

	def __init__(self, model_id: str = ALTO_MODEL):
		self._model_id = model_id
		self._last_route = ""

	@property
	def current_model_id(self) -> str:
		return self._last_route or self._model_id

	def chat(
		self,
		user_message: str,
		on_chunk: Callable[[str], None] | None = None,
		system_override: str | None = None,
		tools: list | None = None,
		tool_choice: object | None = None,
		tool_results: list | None = None,
		response_format: dict | None = None,
		reasoning_effort: str | None = None,
		step_type: str = "",
		**kwargs: Any,
	) -> LLMResponse:
		from .llm_factory import create_llm_client
		from ..gui.settings_panel import get_studio_available_providers

		required = frozenset({"tool_use"}) if tools else frozenset()
		routes = select_routes(
			"studio", step_type or "general", self._model_id,
			request=user_message,
			available_providers=get_studio_available_providers(),
			required_capabilities=required,
		)
		if not routes:
			raise LLMClientError(
				"Studio não encontrou um provedor configurado com as capacidades necessárias."
			)

		last_error: Exception | None = None
		for index, route in enumerate(routes):
			_logger.info("[STUDIO_ROUTE] %s", route.to_dict())
			try:
				client = create_llm_client(model_id=route.model_id, provider=route.provider)
				response = client.chat(
					user_message,
					on_chunk=on_chunk,
					system_override=system_override,
					tools=tools,
					tool_choice=tool_choice,
					tool_results=tool_results,
					response_format=response_format,
					reasoning_effort=reasoning_effort,
					step_type=step_type,
					**kwargs,
				)
				record_provider_outcome(route.provider, True)
				self._last_route = f"{route.provider}::{response.model_used}"
				response.model_used = self._last_route
				return response
			except Exception as exc:
				last_error = exc
				record_provider_outcome(route.provider, False, str(exc))
				_logger.warning(
					"[STUDIO_FALLBACK] rota %d/%d (%s::%s) falhou: %s",
					index + 1, len(routes), route.provider, route.model_id, exc,
				)
		raise LLMClientError(
			f"Todos os provedores selecionados pelo Studio falharam. Último erro: {last_error}"
		) from last_error
