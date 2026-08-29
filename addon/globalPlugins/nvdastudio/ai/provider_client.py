from __future__ import annotations

import json
from typing import Any, Callable

from . import reliability
from .llm_client import LLMClientError, LLMResponse
from ..utils.logger import get_logger, log_llm_call, log_llm_response

MODULE_VERSION = "2.15.0"
_logger = get_logger("provider_client")

_OPENAI_URL = "https://api.openai.com/v1/responses"
_XAI_URL = "https://api.x.ai/v1/responses"
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1/interactions"
_MAX_RETRIES = 2
_TIMEOUT = 300.0


class ProviderClientError(LLMClientError):
	"""Falha de comunicacao ou de protocolo com um provedor."""


def _httpx_module():
	try:
		import httpx
		return httpx
	except Exception as exc:
		raise ProviderClientError("A biblioteca HTTP interna do NVDAStudio nao esta disponivel.") from exc


def _schema_from(response_format: dict | None) -> dict | None:
	if not response_format or response_format.get("type") != "json_schema":
		return None
	return response_format.get("json_schema", {}).get("schema")


# Modelos Claude legados que so aceitam o schema manual antigo de thinking
# (thinking.type="enabled"+budget_tokens); os demais (Sonnet 5, Opus 4.6+,
# Fable 5) usam thinking.type="adaptive"+output_config.effort -- o schema
# antigo retorna 400 nesses (docs 2026).
_LEGACY_MANUAL_THINKING_CLAUDE = (
	"claude-opus-4-0", "claude-opus-4.0", "claude-opus-4-1",
	"claude-sonnet-4-0", "claude-sonnet-4.0", "claude-opus-4-2025",
	"claude-sonnet-4-2025", "claude-opus-4-5", "claude-sonnet-4-5",
	"claude-haiku-4-5",
)


def _supports_adaptive_thinking(model: str) -> bool:
	m = (model or "").lower().replace(".", "-")
	return "claude" in m and not any(v in m for v in _LEGACY_MANUAL_THINKING_CLAUDE)


# Interactions API do Gemini so aceita 4 niveis discretos em
# generation_config.thinking_level (docs 2026: ai.google.dev/gemini-api/docs/
# interactions/thinking) -- mapeia o reasoning_effort generico do projeto
# (low/medium/high/xhigh/max) pro nivel mais proximo.
_GEMINI_THINKING_LEVEL_MAP = {
	"none": "low", "minimal": "low", "low": "low",
	"medium": "medium",
	"high": "high", "xhigh": "high", "max": "high",
}


def _gemini_thinking_level(reasoning_effort: str) -> str:
	return _GEMINI_THINKING_LEVEL_MAP.get(reasoning_effort.lower(), "medium")


def _tool_function(tool: dict) -> dict:
	function = tool.get("function", tool)
	return {
		"name": function.get("name", ""),
		"description": function.get("description", ""),
		"parameters": function.get("parameters", {"type": "object", "properties": {}}),
	}


def _is_native_tool(tool: dict) -> bool:
	"""
	True quando o item ja e um bloco de server tool nativo do provedor
	(ex: {"type": "code_interpreter", ...}, {"type": "web_search"},
	{"type": "code_execution_20260521", "name": "code_execution"}) em vez
	de uma ferramenta de function-calling ({"type": "function", "function":
	{...}} ou {"name","description","parameters"} soltos). Server tools tem
	"type" definido pra algo diferente de "function" e nao devem passar
	pelo achatamento de _tool_function() -- isso corromperia o bloco nativo
	num function-tool vazio.
	"""
	return bool(tool.get("type")) and tool.get("type") != "function"


def _build_tools_payload(tools: list) -> list:
	"""Achata function-tools via _tool_function(); repassa server tools nativos intactos."""
	return [
		tool if _is_native_tool(tool) else {"type": "function", **_tool_function(tool)}
		for tool in tools
	]


class ProviderClient:
	"""Cliente sincrono, seguro para uso nas threads de trabalho do addon."""

	def __init__(self, provider: str, api_key: str, model_id: str):
		if provider not in {"openai", "gemini", "anthropic", "xai"}:
			raise ProviderClientError(f"Provedor nativo desconhecido: {provider}")
		if not api_key.strip():
			raise ProviderClientError(f"Chave API para {provider} nao configurada.")
		self._provider = provider
		self._api_key = api_key.strip()
		self._model_id = model_id
		self._history: list[dict] = []
		self._gemini_interaction_id: str | None = None

	@property
	def current_model_id(self) -> str:
		return self._model_id

	@property
	def history(self) -> list[dict]:
		return list(self._history)

	def switch_model(self, model_id: str) -> None:
		self._model_id = model_id

	def reset_history(self) -> None:
		self._history.clear()
		self._gemini_interaction_id = None

	def native_web_search(self, query: str) -> str:
		"""
		Pesquisa web executada pelo proprio provedor (server tool), nao por um
		scraper mantido pelo NVDAStudio. Chamada isolada de request unico --
		nao participa de self._history nem do turno de conversa em curso.

		Fontes (auditoria 2026-07-20, citacoes/provenance confirmadas
		2026-08-03 contra doc oficial de cada provedor):
		  - OpenAI/xAI (Responses API): tools=[{"type": "web_search"}].
		    Citacoes chegam em message.content[0].annotations, cada uma
		    {"type": "url_citation", "url", "title", "start_index", "end_index"}
		    (platform.openai.com/docs/guides/tools-web-search).
		  - Anthropic (Messages API): tools=[{"type": "web_search_20260318",
		    "name": "web_search"}] (server tool -- roda na infra da Anthropic).
		    Citacoes chegam no campo "citations" de cada bloco de texto, cada
		    uma {"type": "web_search_result_location", "url", "title",
		    "encrypted_index", "cited_text"} (platform.claude.com/docs/en/
		    agents-and-tools/tool-use/web-search-tool).
		  - Gemini (Interactions API): tools=[{"type": "google_search"}].
		    Corrigido bug real: este metodo so lia data["output_text"], campo
		    que a Interactions API nao garante para chamadas de tool -- o
		    resultado real vem em data["steps"], step type="model_output",
		    igual ao caminho principal de chat() (_chat_gemini). Citacoes
		    chegam em annotations do proprio step de texto, mesmo formato
		    url_citation da OpenAI/xAI (ai.google.dev/gemini-api/docs/
		    interactions/google-search).
		  Cada provedor devolve as fontes como uma secao "Fontes:" ao final
		  do texto (mesmo padrao ja usado por OllamaClient.web_search()) --
		  contrato de retorno (str) preservado para quem consome
		  (web_researcher.py alimenta o texto bruto num prompt de sintese).
		"""
		if not query or not query.strip():
			return ""
		try:
			if self._provider in {"openai", "xai"}:
				return self._native_web_search_openai_compatible(query)
			if self._provider == "anthropic":
				return self._native_web_search_anthropic(query)
			return self._native_web_search_gemini(query)
		except ProviderClientError as exc:
			_logger.warning("[WEB_SEARCH] %s falhou: %s", self._provider, exc)
			return ""

	@staticmethod
	def _format_with_sources(content: str, citations: list[dict]) -> str:
		"""Anexa uma secao 'Fontes:' com URL/titulo unicos, na ordem em que aparecem."""
		if not citations:
			return content
		seen: set[str] = set()
		lines = ["", "Fontes:"]
		for citation in citations:
			url = citation.get("url", "")
			if not url or url in seen:
				continue
			seen.add(url)
			title = citation.get("title") or url
			lines.append(f"- {title}: {url}")
		if len(lines) == 2:
			return content
		return content + "\n".join(lines)

	def _native_web_search_openai_compatible(self, query: str) -> str:
		url = _OPENAI_URL if self._provider == "openai" else _XAI_URL
		headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
		payload = {
			"model": self._model_id,
			"input": [{"role": "user", "content": query}],
			"tools": [{"type": "web_search"}],
		}
		data = self._request(url, headers, payload)
		content = ""
		citations: list[dict] = []
		for item in data.get("output") or []:
			if item.get("type") == "message":
				for part in item.get("content") or []:
					if part.get("type") == "output_text":
						content += part.get("text", "")
						citations.extend(
							a for a in (part.get("annotations") or []) if a.get("type") == "url_citation"
						)
		content = content or data.get("output_text") or ""
		return self._format_with_sources(content, citations)

	def _native_web_search_anthropic(self, query: str) -> str:
		headers = {
			"x-api-key": self._api_key,
			"anthropic-version": "2023-06-01",
			"Content-Type": "application/json",
		}
		payload = {
			"model": self._model_id,
			"max_tokens": 4096,
			"messages": [{"role": "user", "content": query}],
			"tools": [{"type": "web_search_20260318", "name": "web_search"}],
		}
		data = self._request(_ANTHROPIC_URL, headers, payload)
		blocks = data.get("content") or []
		content = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
		citations = [
			c for block in blocks if block.get("type") == "text"
			for c in (block.get("citations") or []) if c.get("type") == "web_search_result_location"
		]
		return self._format_with_sources(content, citations)

	def _native_web_search_gemini(self, query: str) -> str:
		# BUGS REAIS corrigidos (achados em teste E2E real ao vivo, 2026-08-04,
		# mesma causa raiz de _chat_gemini() 2.12.0 -- essa funcao nunca foi
		# corrigida junto): (1) "input" no formato antigo role/parts -- API
		# real rejeita com HTTP 400, busca web nativa do Gemini nunca
		# funcionou de verdade. (2) step.get("text", "") direto -- o texto
		# real fica em step.get("content", [])[i]["text"] (mesmo Content-type
		# usado em toda a Interactions API), entao mesmo se a chamada nao
		# desse 400, content ficaria sempre vazio.
		headers = {"x-goog-api-key": self._api_key, "Content-Type": "application/json"}
		payload = {
			"model": self._model_id,
			"input": query,
			"tools": [{"type": "google_search"}],
		}
		data = self._request(_GEMINI_URL, headers, payload)
		content_parts: list[str] = []
		citations: list[dict] = []
		for step in data.get("steps") or []:
			if step.get("type") != "model_output":
				continue
			for part in step.get("content") or []:
				if part.get("type") == "text":
					content_parts.append(part.get("text", ""))
			citations.extend(
				a for a in (step.get("annotations") or []) if a.get("type") == "url_citation"
			)
		return self._format_with_sources("".join(content_parts), citations)

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
		**kwargs,
	) -> LLMResponse:
		if not user_message or not user_message.strip():
			raise ProviderClientError("Mensagem vazia nao permitida.")
		log_llm_call(_logger, f"{self._provider}_v{MODULE_VERSION}", user_message)
		if self._provider in {"openai", "xai"}:
			response = self._chat_openai_compatible(
				user_message, system_override or "", tools, tool_choice, tool_results,
				response_format, reasoning_effort, on_chunk,
			)
		elif self._provider == "anthropic":
			response = self._chat_anthropic(
				user_message, system_override or "", tools, tool_choice, tool_results,
				response_format, reasoning_effort, on_chunk,
			)
		else:
			response = self._chat_gemini(
				user_message, system_override or "", tools, tool_choice, tool_results,
				response_format, reasoning_effort, on_chunk,
			)
		log_llm_response(_logger, f"{self._provider}_v{MODULE_VERSION}", response.content)
		return response

	def _request(self, url: str, headers: dict, payload: dict):
		"""
		2026-08-26: retry/backoff proprios substituidos por ai/reliability.py
		(fonte unica compartilhada com ollama_client.py e opencode_go_client.py
		-- achado real de auditoria: as 3 tinham implementacoes quase
		identicas de _MAX_RETRIES/backoff, cada uma reimplementada
		separadamente). raise_for_status() incondicional (em vez do check
		proativo de status_code antigo) delega toda a decisao de "e
		retentavel?" pro is_retryable() compartilhado, que ja sabe ler
		response.status_code da excecao -- comportamento identico, um
		caminho a menos pra manter sincronizado.
		"""
		httpx = _httpx_module()

		def do_request():
			with httpx.Client(timeout=_TIMEOUT) as client:
				response = client.post(url, headers=headers, json=payload)
				response.raise_for_status()
				return response.json()

		try:
			return reliability.call_with_retry(do_request, max_attempts=_MAX_RETRIES + 1)
		except Exception as exc:
			raise ProviderClientError(f"Falha no provedor {self._provider}: {exc}") from exc

	def _stream_sse(self, url: str, headers: dict, payload: dict, on_event):
		"""
		Decodifica o stream SSE (linhas "event: nome" + "data: {...}") e chama
		on_event(data) pra cada evento JSON decodificado. on_event nao retorna
		nada -- quem chama e responsavel por acumular texto/reasoning/tool_calls
		conforme o shape de evento de cada provedor (sao bem diferentes entre
		si: OpenAI/xAI usam campo "type" dentro do proprio JSON de data
		(response.*), Anthropic idem (content_block_*), Gemini (Interactions
		API) usa o NOME do evento SSE (linha "event: step.start"/"step.delta"/
		"step.stop") em vez de um campo dentro do JSON -- por isso o nome do
		evento SSE, quando presente, e injetado em data["_sse_event"] antes de
		chamar on_event, pra quem consome poder discriminar por ele quando o
		JSON em si nao carrega essa informacao.
		"""
		httpx = _httpx_module()
		try:
			with httpx.Client(timeout=_TIMEOUT) as client:
				with client.stream("POST", url, headers=headers, json=payload) as response:
					response.raise_for_status()
					last_event = ""
					for line in response.iter_lines():
						if not line:
							continue
						if line.startswith("event:"):
							last_event = line[6:].strip()
							continue
						if not line.startswith("data:"):
							continue
						raw = line[5:].strip()
						if raw == "[DONE]":
							break
						try:
							data = json.loads(raw)
						except json.JSONDecodeError:
							continue
						if last_event:
							data["_sse_event"] = last_event
						on_event(data)
		except Exception as exc:
			raise ProviderClientError(f"Streaming de {self._provider} falhou: {exc}") from exc

	def _build_responses_input(self, pending_tool_results: list | None) -> list[dict]:
		"""
		Reconstroi o array "input" da Responses API a partir de self._history.

		Cada entrada assistant com tool_calls vira 1 item function_call por
		chamada (formato flat: type/call_id/name/arguments no topo, sem
		aninhar em "function"); cada entrada role="tool_result" (persistida
		por uma chamada anterior com tool_results) vira 1 item
		function_call_output -- a Responses API exige os itens function_call
		originais presentes no historico para aceitar os function_call_output
		correspondentes nas chamadas seguintes.

		pending_tool_results: resultados desta chamada ainda NAO persistidos
		em self._history (isso acontece depois, em _chat_openai_compatible).
		"""
		items: list[dict] = []
		for entry in self._history:
			role = entry.get("role")
			if role == "assistant" and entry.get("tool_calls"):
				content = entry.get("content") or ""
				if content:
					items.append({"role": "assistant", "content": content})
				for call in entry["tool_calls"]:
					fn = call.get("function", {})
					items.append({
						"type": "function_call",
						"call_id": call.get("id", ""),
						"name": fn.get("name", ""),
						"arguments": fn.get("arguments", "{}"),
					})
			elif role == "tool_result":
				items.append({
					"type": "function_call_output",
					"call_id": entry.get("tool_call_id", ""),
					"output": entry.get("content", ""),
				})
			else:
				items.append({"role": role, "content": entry.get("content", "")})
		if pending_tool_results:
			for result in pending_tool_results:
				items.append({
					"type": "function_call_output",
					"call_id": result.get("tool_call_id", ""),
					"output": str(result.get("content", "")),
				})
		return items

	def _chat_openai_compatible(
		self, user: str, system: str, tools: list | None, tool_choice: object | None,
		tool_results: list | None, response_format: dict | None,
		reasoning_effort: str | None, on_chunk,
	) -> LLMResponse:
		input_items = self._build_responses_input(tool_results)
		if not tool_results:
			input_items.append({"role": "user", "content": user})
		payload: dict = {"model": self._model_id, "input": input_items}
		if system:
			payload["instructions"] = system
		if tools:
			payload["tools"] = _build_tools_payload(tools)
		if tool_choice is not None:
			payload["tool_choice"] = tool_choice
		schema = _schema_from(response_format)
		if schema:
			payload["text"] = {"format": {
				"type": "json_schema", "name": "structured_response",
				"schema": schema, "strict": True,
			}}
		elif response_format and response_format.get("type") == "json_object":
			payload["text"] = {"format": {"type": "json_object"}}
		if reasoning_effort:
			payload["reasoning"] = {"effort": reasoning_effort}
		url = _OPENAI_URL if self._provider == "openai" else _XAI_URL
		headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
		if on_chunk:
			# v2.6.0: streaming funciona com tools ativo -- confirmado por
			# pesquisa dedicada (doc oficial + xai-sdk) que response.output_text.delta
			# nao e suprimido pela presenca de tools. Texto (preambulo estilo
			# "tool preamble" da OpenAI) e argumentos de function_call chegam
			# entrelacados no mesmo stream, cada um no seu proprio item/index.
			payload["stream"] = True
			content_parts: list[str] = []
			pending_calls: dict[str, dict] = {}
			call_order: list[str] = []
			usage: dict = {}
			truncated_flag = {"v": False}

			def on_event(data):
				etype = data.get("type")
				if etype == "response.incomplete":
					# Achado de auditoria 2026-08-04: resposta cortada pelo teto de
					# max_output_tokens -- evento terminal alternativo a
					# response.completed. Ver LLMResponse.truncated (llm_client.py 1.1.0).
					truncated_flag["v"] = (
						(data.get("response") or {}).get("incomplete_details") or {}
					).get("reason") == "max_output_tokens"
					usage.update((data.get("response") or {}).get("usage") or {})
				elif etype == "response.output_text.delta":
					text = data.get("delta") or data.get("content") or ""
					if text:
						content_parts.append(text)
						on_chunk(text)
				elif etype == "response.output_item.added":
					item = data.get("item") or {}
					if item.get("type") == "function_call":
						item_id = item.get("id", "")
						pending_calls[item_id] = {
							"id": item.get("call_id") or item_id,
							"type": "function",
							"function": {"name": item.get("name", ""), "arguments": ""},
						}
						call_order.append(item_id)
				elif etype == "response.function_call_arguments.delta":
					item_id = data.get("item_id", "")
					if item_id in pending_calls:
						pending_calls[item_id]["function"]["arguments"] += data.get("delta") or ""
				elif etype == "response.output_item.done":
					item = data.get("item") or {}
					item_id = item.get("id", "")
					if item.get("type") == "function_call" and item_id in pending_calls and item.get("arguments"):
						pending_calls[item_id]["function"]["arguments"] = item.get("arguments")
				elif etype == "response.completed":
					usage.update((data.get("response") or {}).get("usage") or {})

			self._stream_sse(url, headers, payload, on_event)
			content = "".join(content_parts)
			tool_calls = [pending_calls[i] for i in call_order]
			truncated = truncated_flag["v"]
		else:
			data = self._request(url, headers, payload)
			output_items = data.get("output") or []
			content = ""
			tool_calls = []
			for item in output_items:
				item_type = item.get("type")
				if item_type == "message":
					for part in item.get("content") or []:
						if part.get("type") == "output_text":
							content += part.get("text", "")
				elif item_type == "function_call":
					tool_calls.append({
						"id": item.get("call_id") or item.get("id", ""),
						"type": "function",
						"function": {
							"name": item.get("name", ""),
							"arguments": item.get("arguments", "{}"),
						},
					})
			if not content:
				content = data.get("output_text") or ""
			usage = data.get("usage") or {}
			# status="incomplete" + incomplete_details.reason="max_output_tokens" =
			# resposta cortada pelo teto de tokens (Responses API, OpenAI/xAI).
			truncated = (
				data.get("status") == "incomplete"
				and (data.get("incomplete_details") or {}).get("reason") == "max_output_tokens"
			)

		if not tool_results:
			self._history.append({"role": "user", "content": user})
		else:
			# Persiste os resultados desta chamada para que turnos futuros
			# reconstruam os itens function_call_output corretos via
			# _build_responses_input (role="tool_result").
			for result in tool_results:
				self._history.append({
					"role": "tool_result",
					"tool_call_id": result.get("tool_call_id", ""),
					"content": str(result.get("content", "")),
				})
		assistant: dict[str, Any] = {"role": "assistant", "content": content}
		if tool_calls:
			assistant["tool_calls"] = tool_calls
		self._history.append(assistant)
		return LLMResponse(content, self._model_id, tool_calls=tool_calls, tokens_used=usage.get("total_tokens", 0), usage_breakdown=usage, truncated=truncated)

	def _chat_anthropic(
		self, user: str, system: str, tools: list | None, tool_choice: object | None,
		tool_results: list | None, response_format: dict | None,
		reasoning_effort: str | None, on_chunk,
	) -> LLMResponse:
		schema = _schema_from(response_format)
		if response_format and not schema:
			schema = {"type": "object"}
		messages = list(self._history)
		tool_result_message: dict | None = None
		if tool_results:
			tool_result_message = {"role": "user", "content": [
				{
					"type": "tool_result",
					"tool_use_id": result.get("tool_call_id", ""),
					"content": str(result.get("content", "")),
				} for result in tool_results
			]}
			messages.append(tool_result_message)
		else:
			messages.append({"role": "user", "content": user})
		payload: dict = {"model": self._model_id, "max_tokens": 65536, "messages": messages}
		if system:
			payload["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
		if tools:
			converted = []
			for tool in tools:
				if _is_native_tool(tool):
					converted.append(tool)
					continue
				fn = _tool_function(tool)
				converted.append({"name": fn["name"], "description": fn["description"], "input_schema": fn["parameters"]})
			if converted:
				converted[-1]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
			payload["tools"] = converted
		if tool_choice:
			# Formato Anthropic: {"type": "auto"|"any"|"none"} ou
			# {"type": "tool", "name": "..."} pra forcar uma tool especifica.
			# Aceita string simples (normaliza pro dict) alem do dict ja pronto.
			payload["tool_choice"] = {"type": tool_choice} if isinstance(tool_choice, str) else tool_choice
		if schema:
			payload["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
		if reasoning_effort and _supports_adaptive_thinking(self._model_id):
			payload["thinking"] = {"type": "adaptive"}
			payload.setdefault("output_config", {})["effort"] = reasoning_effort
		headers = {
			"x-api-key": self._api_key,
			"anthropic-version": "2023-06-01",
			"Content-Type": "application/json",
		}
		if on_chunk:
			# v2.6.0: streaming funciona com tools ativo -- confirmado pela
			# doc oficial (exemplo "Streaming request with tool use"): texto
			# (preambulo) chega em streaming normal ANTES de um bloco tool_use,
			# cada bloco com seu proprio index (content_block_start -> N deltas
			# -> content_block_stop). Args de tool_use chegam fragmentados via
			# input_json_delta (partial_json), acumulados por index ate fechar.
			payload["stream"] = True
			blocks_by_index: dict[int, dict] = {}
			raw_input_by_index: dict[int, str] = {}
			block_order: list[int] = []
			usage: dict = {}
			stop_reason = {"v": ""}

			def on_event(data):
				etype = data.get("type")
				if etype == "message_start":
					usage.update((data.get("message") or {}).get("usage") or {})
				elif etype == "message_delta":
					usage.update(data.get("usage") or {})
					delta_stop = (data.get("delta") or {}).get("stop_reason")
					if delta_stop:
						stop_reason["v"] = delta_stop
				elif etype == "content_block_start":
					index = data.get("index", 0)
					cb = data.get("content_block") or {}
					if cb.get("type") == "text":
						blocks_by_index[index] = {"type": "text", "text": ""}
					elif cb.get("type") == "tool_use":
						blocks_by_index[index] = {"type": "tool_use", "id": cb.get("id", ""), "name": cb.get("name", ""), "input": {}}
						raw_input_by_index[index] = ""
					else:
						return
					block_order.append(index)
				elif etype == "content_block_delta":
					index = data.get("index", 0)
					delta = data.get("delta") or {}
					dtype = delta.get("type")
					if dtype == "text_delta":
						text = delta.get("text", "")
						if index in blocks_by_index:
							blocks_by_index[index]["text"] += text
						if text:
							on_chunk(text)
					elif dtype == "input_json_delta" and index in raw_input_by_index:
						raw_input_by_index[index] += delta.get("partial_json", "")
				elif etype == "content_block_stop":
					index = data.get("index", 0)
					if index in raw_input_by_index and index in blocks_by_index:
						try:
							blocks_by_index[index]["input"] = json.loads(raw_input_by_index[index] or "{}")
						except json.JSONDecodeError:
							blocks_by_index[index]["input"] = {}

			self._stream_sse(_ANTHROPIC_URL, headers, payload, on_event)
			blocks = [blocks_by_index[i] for i in block_order]
			content = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
			tool_calls = [
				{"id": b.get("id", ""), "type": "function", "function": {"name": b.get("name", ""), "arguments": b.get("input", {})}}
				for b in blocks if b.get("type") == "tool_use"
			]
			if not tool_results:
				self._history.append({"role": "user", "content": user})
			elif tool_result_message is not None:
				self._history.append(tool_result_message)
			self._history.append({"role": "assistant", "content": blocks})
			tokens = int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)
			return LLMResponse(
				content, self._model_id, tool_calls=tool_calls, tokens_used=tokens,
				usage_breakdown=usage, truncated=stop_reason["v"] == "max_tokens",
			)
		data = self._request(_ANTHROPIC_URL, headers, payload)
		blocks = data.get("content") or []
		content = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
		tool_calls = []
		for block in blocks:
			if block.get("type") == "tool_use":
				tool_calls.append({
					"id": block.get("id", ""),
					"type": "function",
					"function": {"name": block.get("name", ""), "arguments": block.get("input", {})},
				})
		if not tool_results:
			self._history.append({"role": "user", "content": user})
		elif tool_result_message is not None:
			self._history.append(tool_result_message)
		self._history.append({"role": "assistant", "content": blocks})
		usage = data.get("usage") or {}
		tokens = int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)
		return LLMResponse(
			content, self._model_id, tool_calls=tool_calls, tokens_used=tokens,
			usage_breakdown=usage, truncated=data.get("stop_reason") == "max_tokens",
		)

	def _chat_gemini(
		self, user: str, system: str, tools: list | None, tool_choice: object | None,
		tool_results: list | None, response_format: dict | None,
		reasoning_effort: str | None, on_chunk,
	) -> LLMResponse:
		# BUG REAL CRITICO corrigido (achado durante teste E2E real com API ao
		# vivo, 2026-08-04): a Interactions API NAO aceita um array de turnos
		# manuais no formato antigo {"role":.., "parts":[...]} -- e inteiramente
		# stateful via previous_interaction_id, "input" deve ser SO o conteudo
		# NOVO (string simples ou array de Content-objects com campo "type").
		# Confirmado ao vivo: toda 1a chamada de QUALQUER conversa Gemini
		# falhava com HTTP 400 "Unknown parameter 'turns' at 'input'" ate esta
		# correcao -- o provedor Gemini estava 100% inoperante em producao,
		# nenhuma chamada real jamais funcionou por esse caminho. Resultado de
		# tool agora usa o Content-type real "function_result" (call_id/name/
		# result), confirmado via reproducao direta contra a API.
		if tool_results:
			new_input: object = [
				{
					"type": "function_result",
					"call_id": result.get("tool_call_id", ""),
					"name": result.get("tool_name", ""),
					"result": [{"type": "text", "text": str(result.get("content", ""))}],
				}
				for result in tool_results
			]
		else:
			new_input = user

		payload: dict = {"model": self._model_id, "input": new_input}
		# Modo stateful: usa previous_interaction_id sempre que ja existe uma
		# interaction anterior NESTE client -- inclusive em streaming, que
		# ANTES desta correcao nunca usava (comentario antigo dizia "SSE nao
		# retorna id de interaction", mas reproducao ao vivo confirmou que o
		# id chega via evento interaction.created/interaction.completed).
		if self._gemini_interaction_id:
			payload["previous_interaction_id"] = self._gemini_interaction_id
		if system:
			payload["system_instruction"] = system
		if tools:
			payload["tools"] = _build_tools_payload(tools)
		if tool_choice:
			# Interactions API (GA 2026-06): campo tool_choice no nivel raiz
			# do payload, mesma convencao ja usada aqui pra tools/system_instruction
			# (nao aninhado em generation_config). Valores: "auto"|"any"|"none"|"validated".
			payload["tool_choice"] = tool_choice
		schema = _schema_from(response_format)
		if schema:
			payload["response_format"] = [{
				"type": "text", "mime_type": "application/json", "schema": schema,
			}]
		elif response_format and response_format.get("type") == "json_object":
			payload["response_format"] = [{"type": "text", "mime_type": "application/json"}]
		if reasoning_effort:
			payload["generation_config"] = {"thinking_level": _gemini_thinking_level(reasoning_effort)}
		headers = {"x-goog-api-key": self._api_key, "Content-Type": "application/json"}
		if on_chunk:
			# v2.6.0: streaming funciona com tools ativo -- confirmado pela
			# doc oficial da Interactions API: texto e function_call fluem pelo
			# mesmo modelo de eventos step-based, texto nao e suprimido pela
			# presenca de tools. Diferente de OpenAI/Anthropic, o tipo do evento
			# (step.start/step.delta/step.stop) vem no NOME do evento SSE, nao
			# num campo dentro do JSON -- injetado em data["_sse_event"] por
			# _stream_sse(). Args de function_call chegam via delta.type=
			# "arguments_delta" (fragmento de JSON em string), acumulados por
			# index ate o step.stop correspondente.
			payload["stream"] = True
			steps_by_index: dict[int, dict] = {}
			raw_args_by_index: dict[int, str] = {}
			step_order: list[int] = []
			captured_interaction_id = {"v": ""}
			captured_status = {"v": ""}

			def on_event(data):
				sse_event = data.get("_sse_event", "")
				index = data.get("index", 0)
				if sse_event in ("interaction.created", "interaction.completed"):
					# Confirmado ao vivo (reproducao direta 2026-08-04): o id da
					# interaction chega aqui em streaming tambem, nao so no
					# non-streaming -- permite stateful mode (previous_interaction_id)
					# em QUALQUER modo de chamada, nao so quando on_chunk e None.
					interaction = data.get("interaction") or {}
					if interaction.get("id"):
						captured_interaction_id["v"] = interaction["id"]
					if interaction.get("status"):
						captured_status["v"] = interaction["status"]
				elif sse_event == "step.start":
					step = data.get("step") or {}
					step_type = step.get("type", "")
					if step_type == "function_call":
						steps_by_index[index] = {
							"type": "function_call",
							"id": step.get("id", f"gemini-{index}"),
							"name": step.get("name", ""),
							"arguments": {},
						}
						raw_args_by_index[index] = ""
						step_order.append(index)
					elif step_type == "model_output":
						steps_by_index[index] = {"type": "text", "text": ""}
						step_order.append(index)
				elif sse_event == "step.delta":
					delta = data.get("delta") or {}
					dtype = delta.get("type")
					if dtype == "text":
						text = delta.get("text", "")
						if index in steps_by_index:
							steps_by_index[index]["text"] += text
						if text:
							on_chunk(text)
					elif dtype == "arguments_delta" and index in raw_args_by_index:
						raw_args_by_index[index] += delta.get("arguments", "")
				elif sse_event == "step.stop":
					if index in raw_args_by_index and index in steps_by_index:
						try:
							steps_by_index[index]["arguments"] = json.loads(raw_args_by_index[index] or "{}")
						except json.JSONDecodeError:
							steps_by_index[index]["arguments"] = {}

			self._stream_sse(_GEMINI_URL, headers, payload, on_event)
			ordered_steps = [steps_by_index[i] for i in step_order]
			content = "".join(s.get("text", "") for s in ordered_steps if s.get("type") == "text")
			tool_calls = [
				{"id": s.get("id", ""), "type": "function", "function": {"name": s.get("name", ""), "arguments": s.get("arguments", {})}}
				for s in ordered_steps if s.get("type") == "function_call"
			]
			if captured_interaction_id["v"]:
				self._gemini_interaction_id = captured_interaction_id["v"]
			if not tool_results:
				self._history.append({"role": "user", "parts": [{"text": user}]})
			self._history.append({"role": "model", "parts": [{"text": content}]})
			# status="incomplete" agora CONFIRMADO disponivel em streaming
			# tambem (evento interaction.completed, reproducao ao vivo
			# 2026-08-04) -- achado anterior que dizia "nao confirmado" e
			# resolvido; mesma deteccao de truncamento do caminho non-streaming.
			return LLMResponse(
				content, self._model_id, tool_calls=tool_calls,
				truncated=captured_status["v"] == "incomplete",
			)
		data = self._request(_GEMINI_URL, headers, payload)
		self._gemini_interaction_id = data.get("id") or self._gemini_interaction_id
		steps = data.get("steps") or []
		tool_calls = []
		content_parts: list[str] = []
		for index, step in enumerate(steps):
			step_type = step.get("type")
			if step_type == "function_call":
				tool_calls.append({
					"id": step.get("id", f"gemini-{index}"),
					"type": "function",
					"function": {"name": step.get("name", ""), "arguments": step.get("arguments", {})},
				})
			elif step_type == "model_output":
				# BUG REAL corrigido (achado em teste E2E real ao vivo,
				# 2026-08-04): data.get("output_text") NUNCA existiu na
				# resposta real -- o texto fica em steps[i].content[], cada
				# item {"type":"text","text":...} (mesmo Content-type usado
				# no payload de input). Toda resposta non-streaming do
				# Gemini vinha com content="" ate esta correcao, mesmo com
				# status="completed" e nenhum erro.
				for part in step.get("content") or []:
					if part.get("type") == "text":
						content_parts.append(part.get("text", ""))
		content = "".join(content_parts)
		# self._history continua sendo mantido mesmo em modo stateful --
		# uso interno (property publica .history), NUNCA mais reenviado
		# pro payload (a API nao aceita reconstrucao manual de historico,
		# ver achado 2026-08-04 acima).
		if not tool_results:
			self._history.append({"role": "user", "parts": [{"text": user}]})
		self._history.append({"role": "model", "parts": [{"text": content}]})
		usage = data.get("usage") or {}
		tokens = usage.get("total_tokens") or (
			int(usage.get("total_input_tokens", 0) or 0) + int(usage.get("total_output_tokens", 0) or 0)
		)
		# status="incomplete" = a Interaction terminou mas contem resultado
		# incompleto (ex: bateu no teto de max_tokens) -- confirmado via
		# ai.google.dev/api/interactions-api (2026-08-04).
		return LLMResponse(
			content, self._model_id, tool_calls=tool_calls, tokens_used=tokens,
			usage_breakdown=usage, truncated=data.get("status") == "incomplete",
		)
