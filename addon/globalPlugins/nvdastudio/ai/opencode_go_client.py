import json
import threading
from typing import Callable

from . import reliability
from .llm_client import LLMClientError, LLMResponse
from ..utils.logger import get_logger, log_llm_call, log_llm_response

MODULE_VERSION = "1.4.0"
_logger = get_logger("opencode_go_client")

_OPENCODE_GO_URL = "https://opencode.ai/zen/go/v1/chat/completions"
_OPENCODE_GO_RESPONSES_URL = "https://opencode.ai/zen/go/v1/responses"

_DEFAULT_MODEL = "gpt-5.6-luna"

# 1.2.0: modelos que exigem a Responses API em vez de Chat Completions --
# ver nota completa em OpenCodeGoClient.chat() abaixo.
_RESPONSES_API_MODELS = frozenset({"gpt-5.6-luna"})

_MAX_RETRIES = 2
_HTTP_TIMEOUT = 300

try:
	import httpx as _httpx  # type: ignore[import]
except Exception:
	_httpx = None  # type: ignore[assignment]


def _sinalizar_conta_indisponivel(resp) -> None:
	"""
	Avisa o registro quando a CONTA nao esta atendendo, nao o modelo.

	get_structured_output_model() forca este provedor porque so ele honra
	json_schema estrito e prompt caching. Isso cria um ponto unico de falha:
	sem saldo, tudo que precisa de JSON garantido cai junto -- Clarifier,
	Critic e o caminho estrito do Planner.

	Confirmado ao vivo em 2026-09-02: chave VALIDA (GET /models = 200) e
	/chat/completions devolvendo 401 CreditsError "Insufficient balance" nos 33
	modelos da conta. A cadeia de fallback tem 5 modelos, todos aqui dentro --
	trocar de modelo nao resolve nada.

	Sinalizado, o registro passa a devolver o provedor ATIVO do usuario, sem a
	garantia de json_schema. E degradacao real, nao equivalencia -- mas a
	alternativa e o pipeline inteiro parar.
	"""
	if resp.status_code not in (401, 402, 403, 429):
		return
	try:
		corpo = resp.text[:400]
	except Exception:  # pragma: no cover - defesa
		corpo = ""
	try:
		from .model_registry import marcar_saida_estruturada_indisponivel

		marcar_saida_estruturada_indisponivel(f"HTTP {resp.status_code}: {corpo[:160]}")
	except Exception as _exc:  # pragma: no cover - defesa
		_logger.debug("[OPENCODE_GO] falha ao marcar saida estruturada indisponivel: %s", _exc)


class OpenCodeGoClientError(LLMClientError):
	"""Falha de comunicacao ou de protocolo com o OpenCode Go."""


# 2026-08-26: _is_retryable_error()/_retry_backoff() migraram pra
# ai/reliability.py (fonte unica compartilhada com ollama_client.py e
# provider_client.py -- achado real de auditoria: as 3 tinham
# implementacoes quase identicas de retry/backoff).


def _strict_responses_schema(schema: dict) -> dict:
	"""Normaliza um schema JSON pro subconjunto estrito exigido pela
	Responses API (portado de C:\\agentic, ja validado em producao la):
	todo objeto precisa listar TODOS os campos em "required" (campos
	opcionais viram nullable via anyOf) e "additionalProperties": False em
	todo nivel, recursivamente."""
	normalized = dict(schema)
	if normalized.get("type") == "object":
		properties = normalized.get("properties") or {}
		originally_required = set(normalized.get("required") or [])
		strict_properties: dict = {}
		for name, value in properties.items():
			child = _strict_responses_schema(value) if isinstance(value, dict) else value
			if name not in originally_required:
				child = {"anyOf": [child, {"type": "null"}]}
			strict_properties[name] = child
		normalized["properties"] = strict_properties
		normalized["required"] = list(properties)
		normalized["additionalProperties"] = False
	elif normalized.get("type") == "array" and isinstance(normalized.get("items"), dict):
		normalized["items"] = _strict_responses_schema(normalized["items"])
	elif "anyOf" in normalized:
		normalized["anyOf"] = [
			_strict_responses_schema(item) if isinstance(item, dict) else item
			for item in normalized["anyOf"]
		]
	return normalized


class OpenCodeGoClient:
	"""Cliente sincrono para o OpenCode Go. Thread-safe via lock interno."""

	def __init__(self, api_key: str, model_id: str = _DEFAULT_MODEL):
		if _httpx is None:
			raise OpenCodeGoClientError("A biblioteca HTTP interna do NVDAStudio nao esta disponivel.")
		if not api_key or not api_key.strip():
			raise OpenCodeGoClientError("Chave API do OpenCode Go nao configurada.")
		self._api_key = api_key.strip()
		self._model_id = model_id
		self._history: list[dict] = []
		self._lock = threading.Lock()
		_logger.info("[OK] OpenCodeGoClient inicializado. model=%s", model_id)

	@property
	def current_model_id(self) -> str:
		return self._model_id

	@property
	def history(self) -> list[dict]:
		with self._lock:
			return list(self._history)

	def switch_model(self, model_id: str) -> None:
		self._model_id = model_id

	def reset_history(self) -> None:
		with self._lock:
			self._history.clear()

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
			raise OpenCodeGoClientError("Mensagem vazia nao permitida.")
		log_llm_call(_logger, f"opencode_go_v{MODULE_VERSION}", user_message)

		with self._lock:
			messages: list = []
			messages.extend(self._history)
			if system_override:
				messages.insert(0, {"role": "system", "content": system_override})
			if tool_results:
				for tr in tool_results:
					messages.append({
						"role": "tool",
						"tool_call_id": tr.get("tool_call_id", ""),
						"content": tr["content"],
					})
			else:
				messages.append({"role": "user", "content": user_message})

		# 1.2.0: gpt-5.6-luna (unico modelo OpenAI-family do catalogo do
		# OpenCode Go) precisa da Responses API (/v1/responses), nao da Chat
		# Completions (/v1/chat/completions, usada por todo o resto do
		# catalogo) -- achado real de auditoria 2026-08-26, comparando com
		# C:\agentic (mesmo gateway, provider ja implementado corretamente la
		# desde 25/08/2026). Confirmado ao vivo: gpt-5.6-luna via
		# /chat/completions retornava 500 (presumido "fora do ar" antes desta
		# auditoria -- na verdade era so o endpoint errado pro modelo); via
		# /responses, 200 limpo, com json_schema estrito seguido a risca E
		# prompt caching real (cache hit confirmado ao reenviar o mesmo
		# prefixo, cached_tokens=2212/2215 tokens).
		if self._model_id in _RESPONSES_API_MODELS:
			return self._call_responses_api(
				messages, user_message, response_format, tools, tool_choice, tool_results, on_chunk,
			)

		payload: dict = {"model": self._model_id, "messages": messages}
		if tools and tool_choice != "none":
			payload["tools"] = tools
			if tool_choice is not None and tool_choice != "none":
				payload["tool_choice"] = tool_choice
		# 1.1.0: response_format era aceito como parametro mas nunca entrava
		# no payload -- achado real de auditoria 2026-08-26. O endpoint e
		# compativel com OpenAI (confirmado ao vivo: json_schema estrito
		# funciona de verdade em kimi-k2.6 via OpenCode Go, diferente do
		# Ollama Cloud direto, que ignora completamente -- ver ollama_client.py
		# 2.25.0). Critic (critic.py) chama com response_format=json_object
		# esperando que isso va pra API; sem esta linha, nunca ia.
		if response_format is not None:
			payload["response_format"] = response_format

		if on_chunk:
			return self._stream(payload, user_message, on_chunk, tool_results)
		return self._non_stream(payload, user_message, tool_results)

	def _non_stream(self, payload: dict, user_message: str, tool_results: list | None) -> LLMResponse:
		headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

		def do_request():
			with _httpx.Client(timeout=_HTTP_TIMEOUT) as client:
				resp = client.post(_OPENCODE_GO_URL, headers=headers, json=payload)
				_sinalizar_conta_indisponivel(resp)
				resp.raise_for_status()
				result = resp.json()
				if result.get("error"):
					raise OpenCodeGoClientError(f"[ERRO] OpenCode Go API: {result['error']}")
				return result

		try:
			data = reliability.call_with_retry(
				do_request, max_attempts=_MAX_RETRIES + 1,
				on_retry=lambda attempt, delay, exc: _logger.warning(
					"[AVISO] OpenCodeGoClient: erro retentavel na tentativa %d/%d. "
					"Retentando em %.1fs... erro=%s",
					attempt, _MAX_RETRIES + 1, delay, exc,
				),
			)
		except OpenCodeGoClientError:
			raise
		except Exception as exc:
			raise OpenCodeGoClientError(f"[ERRO] OpenCode Go API falhou: {exc}") from exc

		choice = (data.get("choices") or [{}])[0]
		message = choice.get("message", {})
		content = message.get("content") or ""
		tool_calls = message.get("tool_calls") or []
		usage = data.get("usage") or {}
		tokens_used = usage.get("total_tokens", 0)
		truncated = choice.get("finish_reason") == "length"

		self._append_history(user_message, content, tool_calls, tool_results)
		log_llm_response(_logger, f"opencode_go_v{MODULE_VERSION}", content)
		return LLMResponse(
			content=content, model_used=self._model_id, tool_calls=tool_calls,
			tokens_used=tokens_used, usage_breakdown=dict(usage), truncated=truncated,
		)

	def _stream(
		self, payload: dict, user_message: str,
		on_chunk: Callable[[str], None], tool_results: list | None,
	) -> LLMResponse:
		payload = dict(payload)
		payload["stream"] = True
		headers = {
			"Authorization": f"Bearer {self._api_key}",
			"Content-Type": "application/json",
			"Accept": "text/event-stream",
		}
		text_parts: list = []
		tool_calls_by_index: dict[int, dict] = {}

		def do_stream():
			text_parts.clear()
			tool_calls_by_index.clear()
			tokens = 0
			trunc = False
			with _httpx.Client(timeout=_HTTP_TIMEOUT) as client:
				with client.stream("POST", _OPENCODE_GO_URL, headers=headers, json=payload) as resp:
					if resp.status_code in (401, 402, 403, 429):
						try:
							resp.read()
						except Exception as _exc:  # pragma: no cover - defesa
							_logger.debug("[OPENCODE_GO] falha ao drenar corpo do erro %s: %s", resp.status_code, _exc)
					_sinalizar_conta_indisponivel(resp)
					resp.raise_for_status()
					for line in resp.iter_lines():
						if not line or not line.startswith("data:"):
							continue
						raw = line[len("data:"):].strip()
						if raw == "[DONE]":
							break
						try:
							chunk = json.loads(raw)
						except json.JSONDecodeError:
							continue
						if chunk.get("error"):
							raise OpenCodeGoClientError(f"[ERRO] OpenCode Go stream: {chunk['error']}")
						choice = (chunk.get("choices") or [{}])[0]
						delta = choice.get("delta", {})
						text = delta.get("content") or ""
						if text:
							text_parts.append(text)
							on_chunk(text)
						# tool_calls chegam fragmentados por indice no streaming
						# padrao OpenAI -- acumula por index ate fechar o turno.
						for tc_delta in delta.get("tool_calls") or []:
							idx = tc_delta.get("index", 0)
							entry = tool_calls_by_index.setdefault(idx, {
								"id": "", "type": "function",
								"function": {"name": "", "arguments": ""},
							})
							if tc_delta.get("id"):
								entry["id"] = tc_delta["id"]
							fn_delta = tc_delta.get("function") or {}
							if fn_delta.get("name"):
								entry["function"]["name"] += fn_delta["name"]
							if fn_delta.get("arguments"):
								entry["function"]["arguments"] += fn_delta["arguments"]
						if choice.get("finish_reason") == "length":
							trunc = True
						usage = chunk.get("usage")
						if usage:
							tokens = usage.get("total_tokens", 0)
			return tokens, trunc

		try:
			tokens_used, truncated = reliability.call_with_retry(
				do_stream, max_attempts=_MAX_RETRIES + 1,
				on_retry=lambda attempt, delay, exc: _logger.warning(
					"[AVISO] OpenCodeGoClient stream: erro retentavel na tentativa %d/%d. "
					"Retentando em %.1fs... erro=%s",
					attempt, _MAX_RETRIES + 1, delay, exc,
				),
			)
		except OpenCodeGoClientError:
			raise
		except Exception as exc:
			raise OpenCodeGoClientError(f"[ERRO] OpenCode Go stream falhou: {exc}") from exc

		content = "".join(text_parts)
		tool_calls = [tool_calls_by_index[i] for i in sorted(tool_calls_by_index)]
		self._append_history(user_message, content, tool_calls, tool_results)
		return LLMResponse(
			content=content, model_used=self._model_id, tool_calls=tool_calls,
			tokens_used=tokens_used, truncated=truncated,
		)

	def _call_responses_api(
		self,
		messages: list,
		user_message: str,
		response_format: dict | None,
		tools: list | None,
		tool_choice: object | None,
		tool_results: list | None,
		on_chunk: Callable[[str], None] | None,
	) -> LLMResponse:
		"""
		Chamada via Responses API (/v1/responses) -- formato exigido por
		gpt-5.6-luna, distinto do Chat Completions usado por todo o resto
		do catalogo. Ver nota completa em chat() acima.

		`messages` (mesma lista role/content ja montada por chat(), com
		system/historico/usuario) e usada como "input" -- a Responses API
		aceita tanto uma string quanto uma lista de mensagens role/content
		nesse campo.
		"""
		payload: dict = {"model": self._model_id, "input": messages, "store": True}
		if tools and tool_choice != "none":
			payload["tools"] = [
				tool if tool.get("type") and tool.get("type") != "function" else {
					"type": "function",
					"name": (tool.get("function") or tool).get("name", ""),
					"description": (tool.get("function") or tool).get("description", ""),
					"parameters": (tool.get("function") or tool).get(
						"parameters", {"type": "object", "properties": {}},
					),
				}
				for tool in tools
			]
			if tool_choice is not None and tool_choice != "none":
				payload["tool_choice"] = tool_choice
		if response_format is not None and response_format.get("type") == "json_schema":
			schema_block = response_format.get("json_schema", {})
			payload["text"] = {
				"format": {
					"type": "json_schema",
					"name": schema_block.get("name", "structured_response"),
					"schema": _strict_responses_schema(schema_block.get("schema", {})),
					"strict": True,
				},
			}

		headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

		def do_request():
			if on_chunk:
				return self._stream_responses(payload, headers, on_chunk)
			with _httpx.Client(timeout=_HTTP_TIMEOUT) as client:
				resp = client.post(_OPENCODE_GO_RESPONSES_URL, headers=headers, json=payload)
				_sinalizar_conta_indisponivel(resp)
				resp.raise_for_status()
				result = resp.json()
				if result.get("error"):
					raise OpenCodeGoClientError(f"[ERRO] OpenCode Go Responses API: {result['error']}")
				return result

		try:
			data = reliability.call_with_retry(
				do_request, max_attempts=_MAX_RETRIES + 1,
				on_retry=lambda attempt, delay, exc: _logger.warning(
					"[AVISO] OpenCodeGoClient (Responses API): erro retentavel na "
					"tentativa %d/%d. Retentando em %.1fs... erro=%s",
					attempt, _MAX_RETRIES + 1, delay, exc,
				),
			)
		except OpenCodeGoClientError:
			raise
		except Exception as exc:
			raise OpenCodeGoClientError(f"[ERRO] OpenCode Go Responses API falhou: {exc}") from exc

		content = data.get("output_text") or ""
		tool_calls: list = []
		for item in data.get("output") or []:
			if item.get("type") == "function_call":
				arguments = item.get("arguments") or {}
				if isinstance(arguments, str):
					try:
						arguments = json.loads(arguments)
					except json.JSONDecodeError:
						pass
				tool_calls.append({
					"id": item.get("call_id") or item.get("id") or "call",
					"type": "function",
					"function": {"name": item.get("name", ""), "arguments": arguments},
				})
			elif item.get("type") == "message":
				for part in item.get("content") or []:
					if part.get("type") in {"output_text", "text"}:
						content += part.get("text", "")

		usage = data.get("usage") or {}
		input_details = usage.get("input_tokens_details") or {}
		tokens_used = usage.get("total_tokens", 0)
		truncated = data.get("status") == "incomplete"

		self._append_history(user_message, content, tool_calls, tool_results)
		log_llm_response(_logger, f"opencode_go_v{MODULE_VERSION}", content)
		return LLMResponse(
			content=content, model_used=self._model_id, tool_calls=tool_calls,
			tokens_used=tokens_used,
			usage_breakdown={
				"input_tokens": usage.get("input_tokens", 0),
				"output_tokens": usage.get("output_tokens", 0),
				"cached_tokens": input_details.get("cached_tokens", 0),
			},
			truncated=truncated,
		)

	def _stream_responses(self, payload: dict, headers: dict, on_chunk: Callable[[str], None]) -> dict:
		"""Streaming da Responses API via Server-Sent Events."""
		payload = dict(payload)
		data: dict = {}
		streamed_text = ""
		with _httpx.Client(timeout=_HTTP_TIMEOUT) as client:
			with client.stream(
				"POST", _OPENCODE_GO_RESPONSES_URL, headers=headers,
				json={**payload, "stream": True},
			) as resp:
				if resp.status_code in (401, 402, 403, 429):
					try:
						resp.read()
					except Exception as _exc:  # pragma: no cover - defesa
						_logger.debug("[OPENCODE_GO] falha ao drenar corpo do erro %s: %s", resp.status_code, _exc)
				_sinalizar_conta_indisponivel(resp)
				resp.raise_for_status()
				for line in resp.iter_lines():
					if not line or not line.startswith("data:"):
						continue
					raw = line[len("data:"):].strip()
					if not raw or raw == "[DONE]":
						continue
					try:
						event = json.loads(raw)
					except json.JSONDecodeError:
						continue
					event_type = event.get("type", "")
					if event_type == "response.output_text.delta":
						delta = event.get("delta", "")
						streamed_text += delta
						on_chunk(delta)
					elif event_type in {"response.completed", "response.failed"}:
						data = event.get("response") or data
		if streamed_text and not data.get("output_text"):
			data["output_text"] = streamed_text
		return data

	def _append_history(
		self, user_message: str, content: str, tool_calls: list, tool_results: list | None,
	) -> None:
		with self._lock:
			if not tool_results:
				self._history.append({"role": "user", "content": user_message})
			assistant_entry: dict = {"role": "assistant", "content": content}
			if tool_calls:
				assistant_entry["tool_calls"] = tool_calls
			self._history.append(assistant_entry)
