import json
import threading
from typing import Callable

from . import reliability
from .llm_client import LLMClientError, LLMResponse
from ..utils.logger import get_logger, log_llm_call, log_llm_response, log_decision
from .model_registry import registry as model_registry

MODULE_VERSION = "2.27.0"
_logger = get_logger("ollama_client")

_OLLAMA_CLOUD_URL = "https://ollama.com/api/chat"
_OLLAMA_CLOUD_WEB_SEARCH_URL = "https://ollama.com/api/web_search"
_OLLAMA_CLOUD_WEB_FETCH_URL = "https://ollama.com/api/web_fetch"
_MAX_TOKENS_DEFAULT = 24_000

# Achado de auditoria 2026-08-04 (analise de log de producao real + pesquisa
# dedicada de arquitetura de agentes 2026): code_generation/agent_runner
# geram UM addon inteiro (varios arquivos) numa unica chamada -- o teto fixo
# de 24k tokens de saida truncava a geracao no meio de um metodo em addons
# com varios arquivos substanciais (confirmado em log real: SpecCritic
# rejeitou "codigo Python incompleto, cortado no meio da definicao do
# metodo"). Mesmo raciocinio ja aplicado ao timeout estendido abaixo --
# esses 2 step_types sao consistentemente os mais pesados do pipeline.
# "assembly" adicionado 2026-08-07: consolida o output de TODOS os steps
# aprovados (contexto grande pra addons complexos) -- achado real do
# golden eval set (test_e36): critic avaliando assembly cortava a resposta
# pelo teto padrao ("Critic: resposta cortada pelo teto de tokens
# (step_type=assembly)") antes de terminar o veredito JSON, 2x seguidas.
# 48_000 -> 64_000 em 2.20.0 (2026-08-08): mesmo com o teto de 48k ja em
# producao, uma segunda rodada real do test_e36 no MESMO addon complexo
# ainda cortou resposta do critic 4x num unico run (3x code_generation,
# 1x assembly) -- evidencia real de que 48k nao cobre o caso extremo.
_MAX_TOKENS_EXTENDED = 64_000
_EXTENDED_TOKENS_STEP_TYPES = frozenset({"code_generation", "agent_runner", "assembly"})

_DEFAULT_MODEL = "kimi-k2.7-code"
_MAX_RETRIES = 2

# Timeout HTTP base (segundos). Fonte: logs de producao + tiers Ollama Cloud.
# v2.1.0 (2026-06-09): Usar timeouts.py centralizado (Hermes-inspired)
_OLLAMA_CLOUD_TIMEOUT = 300

# Timeout estendido para steps pesados
_OLLAMA_CLOUD_TIMEOUT_EXTENDED = 660

# Steps que usam o timeout estendido. "assembly" adicionado 2026-08-07
# junto com _EXTENDED_TOKENS_STEP_TYPES (mesmo achado real, mesmo motivo:
# contexto grande de consolidacao pra addons complexos).
_EXTENDED_TIMEOUT_STEP_TYPES = frozenset({
	"code_generation", "design_review", "agent_runner", "assembly",
	# engineering_review recebe o codigo gerado INTEIRO como entrada
	# (depende de todos os code_generation) -- mesmo perfil de contexto
	# longo que design_review, mesmo teto de timeout HTTP.
	"engineering_review",
})

# Temperature por tipo de operacao. Fonte: docs.ollama.com/blog/structured-outputs
# recomenda temperature=0 para outputs deterministicos. Usamos 0 para passos de
# precisao (planning, criticas, validacoes) e 0.3 para passos criativos (codigo,
# documentacao, pesquisa). A API /api/chat aceita temperature em options.
_TEMPERATURE_PRECISE = 0.0
_TEMPERATURE_CREATIVE = 0.3

try:
	import httpx as _httpx  # type: ignore[import]
	_HTTPX_AVAILABLE = True
except Exception:
	_httpx = None  # type: ignore[assignment]
	_HTTPX_AVAILABLE = False

# ---------------------------------------------------------------------------
# Tabela de capacidades nativas por modelo.
# Fonte: documentacoes oficiais de Maio 2026 de cada provider.
# Ollama Cloud API repassa format=json e format=<schema> para os modelos.
# Mas cada modelo subjacente tem suporte diferente:
#
#   kimi-k2.7-code:  sucessor de kimi-k2.6 (mesma familia Kimi K2), foco em
#                    coding agentico. Mesmas capacidades nativas do k2.6 ate
#                    validacao ao vivo indicar diferenca (auditoria 2026-07-20
#                    nao encontrou evidencia de mudanca de capacidades, so de
#                    foco/qualidade do modelo).
#   kimi-k2.6:       json_schema nativo com strict:true + validacao MFJS.
#                    thinking nativo (ativado por padrao).
#   deepseek-v4-flash: json_object basico, sem thinking nativo (flash = velocidade).
#
# Nota (auditoria 2026-07-20): docs.ollama.com/api/chat indica que "think"
# agora aceita niveis ("low"/"medium"/"high"/"max"), nao so booleano. Nao
# implementado ainda -- thinking_effort continua False para os 2 modelos Kimi
# ate confirmacao ao vivo (Felipe so testa Ollama Cloud; risco de 400 se o
# nivel nao for realmente suportado pelo endpoint /api/chat do Ollama Cloud
# especificamente, mesmo que a doc geral do Ollama liste os niveis).
# ---------------------------------------------------------------------------
# 2026-08-26: json_schema_native=True pro Kimi (k2.6 e k2.7-code) foi
# DESMENTIDO ao vivo -- achado real de auditoria com chave real da conta
# Ollama Cloud do Felipe, testando os 17 modelos da conta contra
# https://ollama.com/api/chat com format=<schema estrito>. NENHUM dos 17
# seguiu o schema, Kimi k2.6 incluso: campos inventados, "plataforma"
# virou array em vez do enum de string pedido, "e_gratuito" obrigatorio
# ausente, tudo embrulhado em ```json. Teste de controle decisivo:
# format="json" (modo simples) e SEM format nenhum deram o MESMO resultado
# byte a byte pro Kimi -- format nao tem efeito observavel nenhum via essa
# API hoje. Isso confirma a nota de pesquisa 2026-08-08 alguns paragrafos
# abaixo ("Ollama Cloud NAO suporta... structured output real"), que ja
# contradizia esta tabela sem que ninguem tivesse conciliado as duas.
# Consequencia real: com native=True, _validate_json_against_schema()
# (safety net) era PULADA pro Kimi -- o unico modelo Ollama rodando SEM
# nenhuma validacao de schema, nem nativa (nao existe) nem local (pulada
# por engano). Corrigido pra False: ativa a mesma injecao de schema no
# prompt + validacao local pos-resposta que os outros modelos ja usam.
_MODEL_CAPABILITIES: dict[str, dict] = {
	"kimi-k2.7-code": {
		"json_schema_native": False,
		"json_object_only":  False,
		"thinking_native":   True,
		"thinking_effort":   False,  # ver nota acima -- nao confirmado ao vivo
		"preserved_thinking": True,
		"reasoning_content":  True,
	},
	"kimi-k2.6": {
		"json_schema_native": False,
		"json_object_only":  False,
		"thinking_native":   True,
		"thinking_effort":   False,  # Kimi nao tem low/medium/high — so on/off via thinking.type
		"preserved_thinking": True,  # Kimi K2.6 suporta thinking.keep="all" para preservar
		"reasoning_content":  True,   # reasoning_content entre turnos com tool calls
	},
	"deepseek-v4-flash": {
		"json_schema_native": False,
		"json_object_only":  True,
		"thinking_native":   False,  # Flash — sem thinking, foco em velocidade
		"thinking_effort":   False,
		"preserved_thinking": False,
		"reasoning_content":  False,
	},
	# glm-5.1/qwen3.5 sao citados como "fontes oficiais" no header deste modulo
	# mas nunca tinham entrada aqui -- model_id desconhecido caia no fallback
	# de _DEFAULT_MODEL (Kimi), herdando json_schema_native=True incorretamente
	# (docs Z.AI 2026: GLM so suporta response_format json_object, sem schema
	# nativo estrito). Qwen sem pesquisa dedicada ainda -- flags conservadoras
	# ate confirmacao ao vivo.
	"glm-5.1": {
		"json_schema_native": False,
		"json_object_only":  True,
		"thinking_native":   False,  # nao confirmado para esta versao especifica
		"thinking_effort":   False,  # reasoning_effort so confirmado a partir do GLM-5.2
		"preserved_thinking": False,
		"reasoning_content":  False,
	},
	# 2.22.0: chave era "qwen3.5" mas model_registry.py registra o model_id
	# REAL como "qwen3.5:397b" (_PROVIDER_TIER_MODELS["ollama"]["frontier"])
	# -- o lookup por model_id de verdade NUNCA batia aqui, entao o tier
	# frontier (usado em pedidos "high" complexity) sempre herdava as flags
	# do Kimi (fallback de _DEFAULT_MODEL) em vez das flags conservadoras
	# que esta entrada sempre pretendeu aplicar. Achado real: auditoria de
	# integracao 2026-08-09 apos o bug do ARCH-010/Critic no mesmo teste.
	"qwen3.5:397b": {
		"json_schema_native": False,  # nao confirmado -- conservador ate pesquisa dedicada
		"json_object_only":  True,
		"thinking_native":   False,
		"thinking_effort":   False,
		"preserved_thinking": False,
		"reasoning_content":  False,
	},
	# 2.22.0: os 9 modelos abaixo estao no catalogo real da conta (GET
	# https://ollama.com/api/tags, model_registry.py 1.15.0) e sao
	# alcancaveis por model_router.py::select_model() (pontua TODOS os
	# modelos ativos do provider), mas nunca tinham entrada aqui -- cada um
	# herdava silenciosamente as flags do Kimi (json_schema_native=True,
	# thinking_native=True) por coincidencia do fallback de _DEFAULT_MODEL,
	# a MESMA classe de bug ja documentada acima para glm-5.1/qwen3.5/
	# gpt-oss:20b. Flags conservadoras (specs nao auditadas em profundidade
	# ainda, ver model_registry.py 1.15.0) exceto onde ha evidencia
	# concreta: glm-5.2 e minimax-m3 tem "thinking" nas capabilities do
	# registry e glm-5.1 ja documenta "reasoning_effort so confirmado a
	# partir do GLM-5.2" (ou seja, 5.2 suporta); gpt-oss:120b e a mesma
	# familia (peso aberto OpenAI, Apache 2.0) que gpt-oss:20b, cujo
	# thinking_effort=True ja e CONFIRMADO via docs.ollama.com/capabilities/
	# thinking -- herda o mesmo padrao ate confirmacao ao vivo especifica
	# do 120b.
	"glm-5.2": {
		"json_schema_native": False,
		"json_object_only":  True,
		"thinking_native":   True,
		"thinking_effort":   True,
		"preserved_thinking": False,
		"reasoning_content":  False,
	},
	"minimax-m3": {
		"json_schema_native": False,
		"json_object_only":  True,
		"thinking_native":   True,
		"thinking_effort":   False,
		"preserved_thinking": False,
		"reasoning_content":  False,
	},
	"gpt-oss:120b": {
		"json_schema_native": False,
		"json_object_only":  True,
		"thinking_native":   True,
		"thinking_effort":   True,
		"preserved_thinking": False,
		"reasoning_content":  False,
	},
	"minimax-m2.7": {
		"json_schema_native": False,
		"json_object_only":  True,
		"thinking_native":   False,
		"thinking_effort":   False,
		"preserved_thinking": False,
		"reasoning_content":  False,
	},
	"deepseek-v4-pro": {
		"json_schema_native": False,
		"json_object_only":  True,
		"thinking_native":   False,
		"thinking_effort":   False,
		"preserved_thinking": False,
		"reasoning_content":  False,
	},
	"nemotron-3-ultra": {
		"json_schema_native": False,
		"json_object_only":  True,
		"thinking_native":   False,
		"thinking_effort":   False,
		"preserved_thinking": False,
		"reasoning_content":  False,
	},
	"nemotron-3-super": {
		"json_schema_native": False,
		"json_object_only":  True,
		"thinking_native":   False,
		"thinking_effort":   False,
		"preserved_thinking": False,
		"reasoning_content":  False,
	},
	"nemotron-3-nano:30b": {
		"json_schema_native": False,
		"json_object_only":  True,
		"thinking_native":   False,
		"thinking_effort":   False,
		"preserved_thinking": False,
		"reasoning_content":  False,
	},
	"mistral-large-3:675b": {
		"json_schema_native": False,
		"json_object_only":  True,
		"thinking_native":   False,
		"thinking_effort":   False,
		"preserved_thinking": False,
		"reasoning_content":  False,
	},
	"gemma4:31b": {
		"json_schema_native": False,
		"json_object_only":  True,
		"thinking_native":   False,
		"thinking_effort":   False,
		"preserved_thinking": False,
		"reasoning_content":  False,
	},
	# gpt-oss:20b: adicionado ao catalogo Ollama (model_registry.py) mas nunca
	# tinha entrada aqui -- caia no fallback de _DEFAULT_MODEL (Kimi),
	# herdando capabilities erradas por coincidencia. thinking_effort=True
	# CONFIRMADO via docs.ollama.com/capabilities/thinking (2026-08-04):
	# GPT-OSS e a excecao documentada -- "instead expects one of low, medium,
	# or high to tune the trace length" -- booleano true/false e IGNORADO
	# pelo modelo (nao so subotimo, o payload["think"]=True atual nunca
	# ativava thinking de verdade nesse modelo). json_schema_native/
	# json_object_only conservadores (mesmo padrao de glm-5.1/qwen3.5) ate
	# confirmacao ao vivo -- fora do escopo deste achado especifico.
	"gpt-oss:20b": {
		"json_schema_native": False,
		"json_object_only":  True,
		"thinking_native":   True,
		"thinking_effort":   True,
		"preserved_thinking": False,
		"reasoning_content":  False,
	},
}


class OllamaClientError(LLMClientError):
	"""Erro da camada de integracao com Ollama Cloud API."""
	pass


# 2026-08-26: _is_retryable_error()/_retry_backoff()/_retry_after_seconds()
# migraram pra ai/reliability.py (fonte unica compartilhada com
# provider_client.py e opencode_go_client.py -- achado real de auditoria:
# as 3 tinham implementacoes quase identicas). O parser de Retry-After
# (delta-segundos + HTTP-date, achado real 2026-08-18) foi preservado
# integralmente em reliability.py::_parse_retry_after_header().


def _clean_response(text: str) -> str:
	"""Preserva integralmente a resposta do modelo.

	Texto de interface e limpo somente em ``sanitize_user_visible_text``. Fazer
	essa limpeza aqui corromperia JSON, codigo, ``*args``, ``**kwargs`` e flags de
	linha de comando antes que os validadores ou o gerador pudessem usa-los.
	"""
	return (text or "").strip()


class OllamaClient:
	"""
	Cliente Ollama Cloud API para o NVDAStudio.

	Usa o endpoint https://ollama.com/api/chat com autenticacao Bearer
	via chave de API do Ollama Cloud.

	Obter chave: https://ollama.com/settings/keys
	Ou cole manualmente em NVDA > Preferencias > Configuracoes > NVDAStudio.

	Suporta:
	- chat() com system_override, on_chunk (streaming via JSON lines), tools, tool_results
	- Historico de conversa multi-turn
	- Tool use no formato OpenAI (suportado pelo Ollama)
	- response_format adaptado por modelo: json_schema nativo (Kimi) ou schema injetado (GLM)
	- reasoning_effort mapeado para think apenas quando modelo suporta

	Notas sobre a API:
	- A API nativa /api/chat usa "options": {"num_predict": N} para limite de tokens.
	- O campo "max_completion_tokens" so existe na API OpenAI-compatible /v1/chat/completions.
	- O campo "prompt_cache_key" nao e suportado pelo Ollama Cloud (e especifico da Moonshot).
	- O cache de prefixo no Ollama e automatico via KV cache por modelo.

	Invariante: content sempre str (nunca None) no LLMResponse retornado.
	"""

	def __init__(self, api_key: str, model_id: str = _DEFAULT_MODEL):
		if not _HTTPX_AVAILABLE or _httpx is None:
			raise OllamaClientError(
				"[ERRO] httpx nao disponivel. "
				"Certifique-se que httpx esta em addon/globalPlugins/nvdastudio/lib/"
			)
		self._api_key = api_key.strip()
		self._model_id = model_id
		self._history: list = []
		self._lock = threading.Lock()
		self._caps = _MODEL_CAPABILITIES.get(model_id, _MODEL_CAPABILITIES[_DEFAULT_MODEL])

		# G1 (2026-05-15): Validacao de modelo via registry.
		# Detecta modelos deprecated/retired na inicializacao.
		ok, msg = model_registry.validate_model(model_id)
		if not ok:
			_logger.warning("[OllamaClient] %s", msg)
		elif msg:
			_logger.warning("[OllamaClient] %s", msg)

		_logger.info(
			"[OK] OllamaClient v%s inicializado. model=%s caps=%s",
			MODULE_VERSION, model_id,
			"json_schema" if self._caps["json_schema_native"] else "json_object",
		)

	# ------------------------------------------------------------------
	# API Publica
	# ------------------------------------------------------------------

	@property
	def current_model_id(self) -> str:
		return self._model_id

	def switch_model(self, model_id: str):
		self._model_id = model_id
		self._caps = _MODEL_CAPABILITIES.get(model_id, _MODEL_CAPABILITIES[_DEFAULT_MODEL])
		log_decision(_logger, "ollama_modelo_trocado", model_id)

	def reset_history(self):
		with self._lock:
			self._history.clear()
		log_decision(_logger, "ollama_historico_resetado")

	def web_search(self, query: str, max_results: int = 5) -> str:
		"""
		Pesquisa web nativa do Ollama Cloud (endpoint dedicado, nao o /api/chat).

		Fonte (auditoria 2026-07-20): docs.ollama.com/capabilities/web-search --
		POST https://ollama.com/api/web_search com a mesma chave Bearer usada
		pelo /api/chat. Substitui o scraper DuckDuckGo (ddgs) que o NVDAStudio
		mantinha por conta propria -- a pesquisa passa a ser responsabilidade
		do provedor, nao do addon.
		"""
		if not query or not query.strip():
			return ""
		headers = {
			"Authorization": f"Bearer {self._api_key}",
			"Content-Type": "application/json",
		}
		payload = {"query": query, "max_results": max_results}
		try:
			with _httpx.Client(timeout=_OLLAMA_CLOUD_TIMEOUT) as client:
				resp = client.post(_OLLAMA_CLOUD_WEB_SEARCH_URL, headers=headers, json=payload)
				resp.raise_for_status()
				data = resp.json()
		except Exception as exc:
			_logger.warning("[WEB_SEARCH] Ollama web_search falhou: %s", exc)
			return ""

		results = data.get("results") or []
		if not results:
			return ""
		lines: list[str] = [f"Resultados da web para: {query}\n"]
		for i, r in enumerate(results, 1):
			title = (r.get("title") or "").strip()
			content = (r.get("content") or "").strip()
			url = (r.get("url") or "").strip()
			if title or content:
				lines.append(f"[{i}] {title}")
				if content:
					lines.append(content[:600])
				if url:
					lines.append(f"Fonte: {url}")
				lines.append("")
		return "\n".join(lines)

	def web_fetch(self, url: str) -> str:
		"""
		Busca o conteudo COMPLETO de uma URL especifica (endpoint dedicado
		Ollama Cloud, irmao do web_search). Usado quando o snippet do
		web_search nao e suficiente e o agente precisa seguir um link ate
		a pagina inteira (ex: doc completa de uma API/pacote).

		Fonte (auditoria 2026-07-20): docs.ollama.com/capabilities/web-search --
		POST https://ollama.com/api/web_fetch, mesma chave Bearer, corpo
		{"url": ...}, resposta {"title", "content", "links"}.
		"""
		if not url or not url.strip():
			return ""
		headers = {
			"Authorization": f"Bearer {self._api_key}",
			"Content-Type": "application/json",
		}
		try:
			with _httpx.Client(timeout=_OLLAMA_CLOUD_TIMEOUT) as client:
				resp = client.post(_OLLAMA_CLOUD_WEB_FETCH_URL, headers=headers, json={"url": url})
				resp.raise_for_status()
				data = resp.json()
		except Exception as exc:
			_logger.warning("[WEB_FETCH] Ollama web_fetch falhou: %s", exc)
			return ""

		title = (data.get("title") or "").strip()
		content = (data.get("content") or "").strip()
		if not content:
			return ""
		lines = [f"Conteudo de: {url}"]
		if title:
			lines.append(f"Titulo: {title}")
		lines.append("")
		lines.append(content[:4000])
		return "\n".join(lines)

	# ------------------------------------------------------------------
	# Adaptacao de structured output por modelo
	# ------------------------------------------------------------------

	def _adapt_structured_output(
		self, response_format: dict, user_message: str, system_override: str | None,
	) -> tuple[object, str, str | None]:
		"""
		Adapta response_format conforme capacidades do modelo alvo.

		Retorna (format_value, adapted_user_message, adapted_system_override).

		Kimi k2.6 (json_schema nativo):
		  payload.format = schema completo — validacao MFJS do lado do servidor.

		GLM 5.1 (apenas json_object):
		  payload.format = "json" — schema e injetado na mensagem do usuario.
		  Validacao local pos-resposta no chat().

		Quando response_format e None ou json_object simples: sem adaptacao.
		"""
		rf_type = response_format.get("type", "")
		if rf_type != "json_schema":
			if rf_type == "json_object":
				return ("json", user_message, system_override)
			return (None, user_message, system_override)

		schema_obj = response_format.get("json_schema", {}).get("schema")
		if schema_obj is None:
			return ("json", user_message, system_override)

		if self._caps["json_schema_native"]:
			# Kimi: schema nativo -- payload.format faz a validacao server-side
			# (MFJS), mas docs.ollama.com/capabilities/structured-outputs
			# recomenda TAMBEM aterrar o schema como texto no prompt mesmo
			# com format nativo ligado (achado de auditoria 2026-08-04,
			# pesquisa dedicada contra a doc oficial atual -- so o caminho
			# GLM abaixo fazia isso, o nativo enviava so via `format`, sem
			# nenhum reforco textual). Grounding leve (nao repete a
			# instrucao completa de proibicao de texto extra do caminho
			# GLM, que existe ali porque o modelo NAO tem validacao nativa
			# -- aqui o servidor ja garante a forma, o texto so ajuda o
			# modelo a "entender" o schema antes de gerar).
			schema_text = json.dumps(schema_obj, indent=2, ensure_ascii=False)
			grounding = f"\n\n--- SCHEMA JSON ESPERADO (referencia) ---\n{schema_text}\n"
			return (schema_obj, user_message + grounding, system_override)

		# GLM: injeta schema na mensagem + usa format=json basico
		schema_text = json.dumps(schema_obj, indent=2, ensure_ascii=False)
		schema_instruction = (
			"\n\n--- FORMATO DE SAIDA OBRIGATORIO ---\n"
			"Retorne APENAS um JSON valido seguindo EXATAMENTE esta estrutura. "
			"Nao inclua texto, markdown, explicacoes ou comentarios fora do JSON.\n"
			f"ESTRUTURA:\n{schema_text}\n"
		)
		adapted_msg = user_message + schema_instruction
		return ("json", adapted_msg, system_override)

	@staticmethod
	def _validate_json_against_schema(content: str, schema_obj: dict) -> list[str]:
		"""
		Validacao local pos-resposta: verifica campos required, tipos e enums.

		Usado como safety net para GLM que nao tem json_schema strict.
		Retorna lista de violacoes (vazia = OK).
		"""
		violations: list[str] = []
		try:
			data = json.loads(content)
		except json.JSONDecodeError as exc:
			return [f"JSON invalido: {exc}"]
		if not isinstance(data, dict):
			return ["Resposta nao e um objeto JSON"]
		if not isinstance(schema_obj, dict):
			return []
		for field in schema_obj.get("required", []):
			if field not in data:
				violations.append(f"Campo obrigatorio ausente: {field}")
		props = schema_obj.get("properties", {})
		for field, value in data.items():
			if field in props:
				prop = props[field]
				expected_type = prop.get("type", "")
				if expected_type == "array" and not isinstance(value, list):
					violations.append(f"Campo '{field}' deveria ser array, recebeu {type(value).__name__}")
				elif expected_type == "integer" and isinstance(value, float) and value == int(value):
					pass
				elif expected_type == "integer" and not isinstance(value, int):
					violations.append(f"Campo '{field}' deveria ser integer, recebeu {type(value).__name__}")
				elif expected_type == "boolean" and not isinstance(value, bool):
					violations.append(f"Campo '{field}' deveria ser boolean, recebeu {type(value).__name__}")
				elif expected_type == "string" and not isinstance(value, str):
					violations.append(f"Campo '{field}' deveria ser string, recebeu {type(value).__name__}")
				allowed_enum = prop.get("enum")
				if allowed_enum and value not in allowed_enum:
					violations.append(f"Campo '{field}' valor invalido '{value}'. Permitidos: {allowed_enum}")
		return violations

	@property
	def history(self) -> list:
		with self._lock:
			return list(self._history)

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
			raise OllamaClientError("[ERRO] Mensagem vazia nao permitida.")

		log_llm_call(_logger, f"ollama_v{MODULE_VERSION}", user_message)

		# Adapta structured output conforme capacidades do modelo
		adapted_msg = user_message
		adapted_system = system_override
		format_value: object | None = None
		schema_for_validation: dict | None = None
		if response_format:
			format_value, adapted_msg, adapted_system = self._adapt_structured_output(
				response_format, user_message, system_override
			)
			if response_format.get("type") == "json_schema":
				schema_for_validation = response_format.get("json_schema", {}).get("schema")

		with self._lock:
			messages: list = []
			messages.extend(self._history)

			if tool_results:
				for tr in tool_results:
					messages.append({
						"role": "tool",
						"tool_name": tr.get("tool_name") or tr.get("tool_call_id", ""),
						"content": tr["content"],
					})
			else:
				messages.append({"role": "user", "content": adapted_msg})

		payload: dict = {
			"model": self._model_id,
			"messages": messages,
			"stream": False,
			"options": {
				"num_predict": (
					_MAX_TOKENS_EXTENDED if step_type in _EXTENDED_TOKENS_STEP_TYPES
					else _MAX_TOKENS_DEFAULT
				),
				# RISCO: Kimi K2.6 nativo aceita APENAS temperature=1.0 (thinking) ou 0.6
				# (nao-thinking); outros valores causam 400 na API Moonshot direta.
				# Via Ollama Cloud, nao e claro se options.temperature e passado adiante
				# ou normalizado internamente pelo Ollama. Se Ollama ignora temperature
				# para cloud models (como esperado), nao ha impacto. Se repassa, causa 400.
				# Evidencia: sem relatos de erro de temperatura em producao ate 2026-05-14.
				# Decisao: manter comportamento atual; rever se 400 por temperature aparecer.
				# 2.21.0: web_research removido da lista "criativa" -- achado
				# real de multiplas rodadas do golden eval set (test_e36):
				# o step devolvia repetidamente um bloco ```python:arquivo.py```
				# em vez de texto de pesquisa, com DOIS modelos diferentes
				# (deepseek-v4-flash e kimi-k2.7-code, apos escalonamento).
				# Pesquisa web (2026-08-08, docs.ollama.com/capabilities/
				# structured-outputs, ja citado no comentario acima): Ollama
				# Cloud NAO suporta tool_choice forcado nem structured output
				# real -- a unica alavanca documentada pra reduzir drift de
				# formato e temperature=0. web_research e uma tarefa de
				# extracao/relato factual, nao geracao criativa -- a
				# classificacao original ("pesquisa" na lista criativa) nao
				# se sustenta pra esse sintoma especifico.
				"temperature": _TEMPERATURE_CREATIVE if step_type in (
					"code_generation", "agent_runner",
					"documentation", "design_review", "user_clarification",
					"test_generation", "agent_template"
				) else _TEMPERATURE_PRECISE,
			},
		}
		if adapted_system:
			messages.insert(0, {"role": "system", "content": adapted_system})
		# tool_choice="none": API nativa /api/chat nao tem esse parametro (ver
		# changelog 2.14.0) -- a mitigacao e simplesmente nao oferecer `tools`
		# nesta rodada, forcando o modelo a responder so em texto.
		if tools and tool_choice != "none":
			payload["tools"] = tools
		if format_value is not None:
			payload["format"] = format_value

		# thinking: parametro think aceita booleano OU nivel string
		# ("low"/"medium"/"high"/"max") conforme docs.ollama.com/capabilities/
		# thinking. Kimi e GLM (thinking_effort=False aqui) so tem on/off via
		# True -- nao documentados como aceitando nivel, mantido conservador.
		# GPT-OSS (thinking_effort=True, confirmado via doc oficial 2026-08-04)
		# e o oposto: booleano e IGNORADO pelo modelo, so aceita a string do
		# nivel -- reasoning_effort ja chega aqui como "low"/"medium"/"high"
		# (mesmo vocabulario usado em toda a orquestracao, ver planner.py
		# _EFFORT_BY_COMPLEXITY), entao repassa direto sem transformar.
		if reasoning_effort:
			payload["think"] = reasoning_effort if self._caps.get("thinking_effort") else True

		if on_chunk:
			# v2.12.0: streaming funciona com tools ativo -- confirmado
			# por pesquisa dedicada (docs.ollama.com/blog/streaming-tool):
			# message.content narra normalmente antes de um chunk com
			# message.tool_calls preenchido. Ressalva documentada (best-effort,
			# nao garantido por todos os modelos -- issue ollama/ollama#12557
			# em aberto): alguns modelos as vezes emitem SO o tool_calls, sem
			# nenhum content antes -- nesse caso simplesmente nao ha nada pra
			# narrar naquele passo, sem erro.
			return self._stream(payload, user_message, on_chunk, system_override, step_type, tool_results)

		headers = {
			"Authorization": f"Bearer {self._api_key}",
			"Content-Type": "application/json",
			"Accept": "application/json",
		}

		_http_timeout = (
			_OLLAMA_CLOUD_TIMEOUT_EXTENDED
			if step_type in _EXTENDED_TIMEOUT_STEP_TYPES
			else _OLLAMA_CLOUD_TIMEOUT
		)
		def do_request():
			with _httpx.Client(timeout=_http_timeout) as client:
				resp = client.post(_OLLAMA_CLOUD_URL, headers=headers, json=payload)
				resp.raise_for_status()
				result = resp.json()
				if result.get("error"):
					raise OllamaClientError(f"[ERRO] Ollama Cloud API: {result['error']}")
				return result

		try:
			data = reliability.call_with_retry(
				do_request, max_attempts=_MAX_RETRIES + 1,
				on_retry=lambda attempt, delay, exc: _logger.warning(
					"[AVISO] OllamaClient: erro retentavel na tentativa %d/%d. "
					"Retentando em %.1fs... erro=%s",
					attempt, _MAX_RETRIES + 1, delay, exc,
				),
			)
		except OllamaClientError:
			raise
		except Exception as exc:
			raise OllamaClientError(f"[ERRO] Ollama Cloud API falhou: {exc}") from exc

		message = data.get("message", {})
		content = _clean_response(message.get("content") or "")
		oai_tool_calls = message.get("tool_calls") or []
		thinking = message.get("thinking")

		# Validacao local pos-resposta para modelos sem json_schema nativo.
		# Quando schema foi injetado na mensagem (GLM), verifica se
		# a resposta realmente segue a estrutura. Se nao, adiciona aviso no log
		# mas NAO rejeita — o Critic ja faz a validacao semantica no pipeline.
		if schema_for_validation and not self._caps["json_schema_native"]:
			violations = self._validate_json_against_schema(content, schema_for_validation)
			if violations:
				_logger.warning(
					"[AVISO] Validacao schema local: %d violacao(oes) para modelo %s: %s",
					len(violations), self._model_id, violations[:3],
				)

		total_duration = data.get("total_duration", 0)
		prompt_eval_count = data.get("prompt_eval_count", 0)
		eval_count = data.get("eval_count", 0)
		tokens_used = prompt_eval_count + eval_count
		# done_reason="length" = a API cortou a resposta pelo teto de tokens
		# (num_predict/context), nao terminou naturalmente ("stop"). Ver
		# LLMResponse.truncated (llm_client.py 1.1.0) e code_generator.py
		# 3.28.0 pro consumo real disso.
		truncated = data.get("done_reason") == "length"

		with self._lock:
			if not tool_results:
				self._history.append({"role": "user", "content": user_message})
			assistant_entry: dict = {"role": "assistant", "content": content}
			if oai_tool_calls:
				assistant_entry["tool_calls"] = oai_tool_calls
			if thinking and self._caps["thinking_native"]:
				assistant_entry["thinking"] = thinking
			self._history.append(assistant_entry)

		log_llm_response(_logger, f"ollama_v{MODULE_VERSION}", content)

		return LLMResponse(
			content=content,
			model_used=self._model_id,
			reasoning=thinking or "",
			tool_calls=oai_tool_calls,
			tokens_used=tokens_used,
			usage_breakdown={
				"total_duration": total_duration,
				"prompt_eval_count": prompt_eval_count,
				"eval_count": eval_count,
			},
			truncated=truncated,
		)

	# ------------------------------------------------------------------
	# Streaming via JSON lines
	# ------------------------------------------------------------------

	def _stream(
		self,
		payload: dict,
		user_message: str,
		on_chunk: Callable[[str], None] | None,
		system_override: str | None = None,
		step_type: str = "",
		tool_results: list | None = None,
	) -> LLMResponse:
		payload = dict(payload)
		payload["stream"] = True

		headers = {
			"Authorization": f"Bearer {self._api_key}",
			"Content-Type": "application/json",
			"Accept": "application/x-ndjson",
		}

		text_parts: list = []
		thinking_parts: list = []
		tool_calls: list = []
		tokens_used = 0
		truncated = False

		_http_timeout = (
			_OLLAMA_CLOUD_TIMEOUT_EXTENDED
			if step_type in _EXTENDED_TIMEOUT_STEP_TYPES
			else _OLLAMA_CLOUD_TIMEOUT
		)
		def do_stream():
			text_parts.clear()
			thinking_parts.clear()
			tool_calls.clear()
			tokens = 0
			trunc = False
			with _httpx.Client(timeout=_http_timeout) as client:
				with client.stream("POST", _OLLAMA_CLOUD_URL, headers=headers, json=payload) as resp:
					resp.raise_for_status()
					for line in resp.iter_lines():
						if not line:
							continue
						try:
							chunk = json.loads(line)
						except json.JSONDecodeError:
							continue
						if chunk.get("error"):
							raise OllamaClientError(f"[ERRO] Ollama Cloud stream: {chunk['error']}")
						msg = chunk.get("message", {})
						# Captura thinking antes do content (Ollama: message.thinking)
						# Fonte: docs.ollama.com/capabilities/thinking — thinking chunks
						# chegam antes dos content chunks no streaming.
						thinking_text = msg.get("thinking") or ""
						if thinking_text:
							thinking_parts.append(thinking_text)
						text = msg.get("content") or ""
						if text:
							text_parts.append(text)
							if on_chunk:
								on_chunk(text)
						# tool_calls chegam consolidados num unico chunk (nao
						# fragmentados) -- fonte: ollama.com/blog/streaming-tool.
						# Best-effort: alguns modelos mandam so isso, sem
						# content nenhum antes (issue ollama/ollama#12557).
						chunk_tool_calls = msg.get("tool_calls") or []
						if chunk_tool_calls:
							tool_calls.extend(chunk_tool_calls)
						if chunk.get("done"):
							prompt_eval_count = chunk.get("prompt_eval_count", 0)
							eval_count = chunk.get("eval_count", 0)
							tokens = prompt_eval_count + eval_count
							trunc = chunk.get("done_reason") == "length"
			return tokens, trunc

		try:
			tokens_used, truncated = reliability.call_with_retry(
				do_stream, max_attempts=_MAX_RETRIES + 1,
				on_retry=lambda attempt, delay, exc: _logger.warning(
					"[AVISO] OllamaClient stream: erro retentavel na tentativa %d/%d. "
					"Retentando em %.1fs... erro=%s",
					attempt, _MAX_RETRIES + 1, delay, exc,
				),
			)
		except OllamaClientError:
			raise
		except Exception as exc:
			raise OllamaClientError(f"[ERRO] Ollama Cloud stream falhou: {exc}") from exc

		content = _clean_response("".join(text_parts))
		thinking_content = "".join(thinking_parts)

		with self._lock:
			if not tool_results:
				self._history.append({"role": "user", "content": user_message})
			assistant_entry: dict = {"role": "assistant", "content": content}
			if tool_calls:
				assistant_entry["tool_calls"] = tool_calls
			if thinking_content and self._caps["thinking_native"]:
				assistant_entry["thinking"] = thinking_content
			self._history.append(assistant_entry)

		return LLMResponse(
			content=content,
			model_used=self._model_id,
			reasoning=thinking_content,
			tool_calls=tool_calls,
			tokens_used=tokens_used,
			truncated=truncated,
		)
