import hashlib
import json
import re
import sys
import threading
import time
from collections import OrderedDict
from typing import Any

from ..ai.llm_factory import create_llm_client
from ..ai.llm_client import LLMClientError, LLMResponse
from ..builder.nvda_context import NVDA_SYSTEM_PROMPT
from ..utils.logger import get_logger

_logger = get_logger("sub_agent_base")

_tl = threading.local()
_PROMPT_CACHE_TTL_SECONDS = 1800
_PROMPT_CACHE_MAX_ENTRIES = 64

_TOOL_PREAMBLE_INSTRUCTION = """
NARRACAO EM TEMPO REAL (estilo "tool preamble"):
Antes de comecar e entre cada uso de ferramenta, escreva uma frase curta e
natural em portugues do Brasil contando o que voce esta fazendo ou decidindo
agora -- como se estivesse pensando em voz alta pra um colega acompanhando.
Primeira pessoa, tempo presente, tom caloroso, sem jargao tecnico, sem nomes
internos de funcao/classe/step_type, sem Markdown, emojis ou aspas
decorativas. Narre so passos que voce vai realmente fazer -- nunca invente
um passo que nao vai acontecer de verdade. Essa narracao fica FORA de
qualquer bloco de codigo (```): nunca escreva a narracao dentro de um
bloco ```linguagem:arquivo```, sempre como texto solto antes/depois dele.
Depois de narrar, prossiga normalmente com a chamada de ferramenta ou com
o restante da resposta."""

_prompt_cache: OrderedDict[str, tuple[float, str, int]] = OrderedDict()
_prompt_cache_lock = threading.Lock()


def _prompt_cache_key(model_id: str, system: str, prompt: str, params: dict, namespace: str = "") -> str:
	payload = json.dumps(
		{"model": model_id, "system": system, "prompt": prompt, "params": params, "namespace": namespace},
		sort_keys=True, ensure_ascii=False, default=str,
	)
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def clear_prompt_response_cache() -> None:
	with _prompt_cache_lock:
		_prompt_cache.clear()


def get_last_tokens() -> int:
	return getattr(_tl, "last_tokens", 0)


# Fatia A da demolicao do staged (Caminho 3): os helpers de narracao
# (narrate/LiveNarrator/_truncate_at_word e amigos) mudaram para
# memory/narration.py -- compartilhados com a GUI e o orchestrator AGENTICOS.
# Re-exportados aqui para os sub_agents staged e os testes que ainda importam
# de _base ate a demolicao terminar.
from ..memory.narration import (  # noqa: E402,F401  (re-export para consumidores de _base)
	_PLURAIS_NARRACAO,
	_STATUS_JARGAO_RE,
	_expandir_plural,
	_limpar_narracao,
	_truncate_at_word,
	narrate,
	_REASONING_CHUNK_MIN_CHARS,
	_SENTENCE_END_CHARS,
	_SentenceChunkBuffer,
	LiveNarrator,
)


def _get_cached_client(model_id: str):
	cache = getattr(_tl, "client_cache", None)
	if cache is not None and cache.get("model_id") == model_id:
		return cache.get("client")
	return None


def _cache_client(model_id: str, client):
	_tl.client_cache = {"model_id": model_id, "client": client}


def clear_client_cache():
	_tl.client_cache = None


def _final_tool_schema(final_tool: dict) -> dict:
	return {
		"type": "function",
		"function": {
			"name": final_tool["name"],
			"description": final_tool["description"],
			"parameters": {
				"type": "object",
				"properties": {
					final_tool["param_name"]: {
						"type": "string",
						"description": final_tool.get("param_description", "O resultado final completo."),
					}
				},
				"required": [final_tool["param_name"]],
			},
		},
	}


_FINAL_TOOL_INSTRUCTION = """
ENTREGA DO RESULTADO FINAL: depois de narrar seu trabalho normalmente (ver
instrucao de narracao acima), voce DEVE chamar a ferramenta "{tool_name}"
com o resultado final completo -- nunca escreva o resultado final como
texto solto na resposta. A narracao ao vivo (o que voce pensa/decide
enquanto trabalha) e a chamada dessa ferramenta (o resultado) sao coisas
separadas: a primeira e conversa, a segunda e o entregavel de verdade."""


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_fenced_json_field(content: str, param_name: str) -> str | None:
	"""
	1.19.0: achado real ao vivo (test_e37, design_review_agent, gpt-oss:20b) --
	quando o modelo NAO chama a tool de entrega de verdade, mas tenta imitar
	o formato escrevendo um bloco ```json {"param_name": "..."}``` como texto
	solto, esse bloco quase sempre REPETE o que o modelo ja disse em prosa
	logo acima -- devolver resp.content inteiro (fallback antigo) duplicava
	tudo (confirmado ao vivo: rule IDs do Guardian apareciam 2x, uma vez na
	prosa e outra dentro do JSON textual). Aqui tentamos extrair SO o campo
	esperado desse JSON textual -- se achar, ele sozinho e o resultado real
	(o modelo so errou o MECANISMO de entrega, nao o conteudo), descartando
	a prosa duplicada que veio antes. Se nao achar/parsear, None -- quem
	chama cai pro content bruto (comportamento antigo preservado).
	"""
	match = _JSON_FENCE_RE.search(content)
	if not match:
		return None
	try:
		payload = json.loads(match.group(1))
	except json.JSONDecodeError:
		return None
	if not isinstance(payload, dict):
		return None
	value = payload.get(param_name)
	return value if isinstance(value, str) and value.strip() else None


def _extract_final_tool_result(resp: "LLMResponse", final_tool: dict) -> str:
	"""Extrai o argumento do tool call de entrega; cai para resp.content se
	o modelo nao chamou a ferramenta (fallback gracioso, nunca quebra)."""
	if not resp.tool_calls:
		fenced = _extract_fenced_json_field(resp.content, final_tool["param_name"])
		return fenced if fenced is not None else resp.content
	tc = resp.tool_calls[0]
	fn = tc.function if hasattr(tc, "function") else tc.get("function", {})
	args = fn.arguments if hasattr(fn, "arguments") else fn.get("arguments", {})
	if isinstance(args, str):
		try:
			args = json.loads(args or "{}")
		except json.JSONDecodeError:
			return resp.content
	if not isinstance(args, dict):
		return resp.content
	return args.get(final_tool["param_name"]) or resp.content


_SEARCH_WEB_TOOL_SCHEMA = {
	"type": "function",
	"function": {
		"name": "search_web",
		"description": (
			"Pesquisa informacoes atualizadas na web sobre o topico da tarefa "
			"atual -- diretrizes de acessibilidade, mudancas recentes na API "
			"do NVDA, versao/comportamento atual de uma biblioteca, etc.\n\n"
			"QUANDO USAR: Chame quando nao tiver certeza sobre algo que pode "
			"ter mudado desde o treinamento, ou que precisa de confirmacao "
			"contra uma fonte atual antes de decidir.\n\n"
			"RETORNOS:\n"
			"- status='cached': informacao recente ja disponivel em cache — use diretamente.\n"
			"- status='searched': nova pesquisa realizada — o campo 'content' tem o resultado.\n"
			"- status='error': pesquisa indisponivel — prossiga com o conhecimento atual."
		),
		"parameters": {
			"type": "object",
			"properties": {
				"query": {
					"type": "string",
					"description": "Pergunta ou topico especifico a pesquisar.",
				}
			},
			"required": ["query"],
		},
	},
}

_MAX_SEARCH_TOOL_ROUNDS = 2


def _search_web_tool(query: str, _mem=None) -> dict:
	"""
	Implementacao compartilhada da ferramenta search_web (extraida de
	sub_agents/code_generator.py 3.28.0 pra reuso -- Regra 3, zero
	duplicacao -- quando _run_sub_agent(enable_web_search=True) tambem
	passou a oferecer essa tool a outros sub-agentes).

	Fluxo: 1) cache web_knowledge (evita chamada desnecessaria); 2) cache
	miss -- chama web_researcher.run() (que por sua vez usa
	on_demand_web_search(), com fallback Tavily/Exa desde 4.4.0).
	Imports locais (memory, web_researcher.run) evitam import circular --
	web_researcher.py ja importa DESTE modulo (_base.py) no nivel de topo.

	_mem: instancia SessionMemory injetavel para testes sem efeitos colaterais.
	Regra 9: nao executa codigo — apenas pesquisa e retorna texto.
	"""
	if _mem is None:
		from ..memory.session_memory import memory as _mem
	try:
		cached = _mem.get_web_knowledge(query[:150], max_age_days=7)
		if cached:
			_logger.info("[TOOL] search_web cache hit: '%s'", query[:60])
			return {
				"status": "cached",
				"query": query,
				"content": cached[0]["content"][:1500],
				"year": cached[0].get("year", 0),
			}
	except Exception as exc:
		_logger.info("[TOOL] search_web cache check falhou: %s", exc)

	try:
		from .web_researcher import run as _web_researcher_run
		content = _web_researcher_run(query, "", {}, _memory=_mem)
		_logger.info("[TOOL] search_web pesquisa concluida: '%s'", query[:60])
		return {"status": "searched", "query": query, "content": content[:1500]}
	except Exception as exc:
		_logger.warning("[TOOL] search_web falhou: %s", exc)
		return {"status": "error", "query": query, "content": f"Pesquisa nao disponivel: {exc}"}


def _dispatch_search_web_tool_call(tc) -> dict | None:
	"""Resolve uma unica tool_call de search_web (unica tool oferecida por
	_run_sub_agent(enable_web_search=True)) pro formato de tool_result que
	client.chat(tool_results=...) espera."""
	if hasattr(tc, "function"):
		tc_name, tc_args = tc.function.name, tc.function.arguments
	else:
		tc_name = tc.get("function", {}).get("name", "")
		tc_args = tc.get("function", {}).get("arguments", "{}")
	tc_id = getattr(tc, "id", "") if hasattr(tc, "id") else tc.get("id", "")

	if tc_name != "search_web":
		_logger.warning("[TOOL] tool_call desconhecida '%s' ignorada (so search_web disponivel).", tc_name)
		return None
	try:
		args = tc_args if isinstance(tc_args, dict) else json.loads(tc_args or "{}")
		query = args.get("query", "")
		result = _search_web_tool(query)
		narrate(f"encontrei resultados sobre {query}, status {result['status']}")
		_logger.info("[TOOL] search_web('%s') -> %s", query[:60], result["status"])
		return {
			"tool_call_id": tc_id,
			"tool_name": tc_name,
			"role": "tool",
			"content": json.dumps(result),
		}
	except Exception as exc:
		_logger.warning("[AVISO] tool_call search_web falhou: %s", exc)
		return None


def _run_sub_agent(
	system_addendum: str,
	prompt: str,
	model_id: str,
	reasoning_params: dict,
	on_chunk=None,
	extra_docs: str = "",
	cache_key: str | None = None,
	live_narrate: bool = False,
	final_tool: dict | None = None,
	step_type: str = "",
	enable_web_search: bool = False,
) -> str:
	"""
	Executa um sub-agente com o modelo e params especificados.

	cache_key: namespace opcional do cache local de respostas exatas.
	live_narrate: quando True, injeta a instrucao de narracao "tool preamble"
	no system prompt e (se on_chunk nao foi passado explicitamente) liga um
	LiveNarrator automaticamente -- narracao ao vivo direto do conteudo real
	do sub-agente, sem reescrita. So usar em sub-agentes cuja resposta final
	e extraida de blocos com fence (o texto solto da narracao e descartado
	na extracao).

	final_tool: {"name", "description", "param_name", "param_description"}.
	Para sub-agentes cuja resposta CRUA e o proprio entregavel (relatorio,
	template, resumo -- design_review_agent, accessibility_auditor,
	agent_template_agent, web_researcher), misturar narracao direto no
	content contaminaria o resultado. final_tool resolve isso: liga
	live_narrate automaticamente (a narracao ao vivo continua acontecendo no
	content, ANTES do tool call) e adiciona uma tool obrigatoria por
	instrucao (nao forcada via tool_choice -- Anthropic documenta tool_choice
	forcado como incompativel com alguns modos, e nem todo provedor tem esse
	parametro implementado neste projeto) que o modelo chama com o resultado
	final limpo como argumento. O retorno de _run_sub_agent() passa a vir
	desse argumento, nunca do content bruto. Fallback gracioso: se o modelo
	nao chamar a tool (nao é garantido, so fortemente instruido), o content
	bruto e usado do jeito que era antes -- nunca quebra, so perde a
	separacao limpa daquela chamada especifica.

	step_type: propagado ate client.chat() (ai/ollama_client.py). Achado de
	auditoria 2026-08-04: nenhum chamador desta funcao passava step_type,
	entao os overrides de timeout estendido (_EXTENDED_TIMEOUT_STEP_TYPES) e
	de teto de tokens (_EXTENDED_TOKENS_STEP_TYPES) do client Ollama nunca
	ativavam pra nenhum sub-agente que passa por aqui -- so os chamadores
	cujo step_type real esta nesses sets (agent_runner, design_review)
	precisam passar o valor; os demais mantem "" (comportamento inalterado).

	enable_web_search: quando True, oferece a tool search_web (schema
	_SEARCH_WEB_TOOL_SCHEMA) e roda um loop de tool-calling limitado
	(_MAX_SEARCH_TOOL_ROUNDS rodadas, tool_choice="none" forcado na ultima --
	mesmo padrao de code_generator.py 3.23.0 pra garantir que o loop sempre
	fecha com resposta final) alem da chamada unica anterior. Pedido do
	Felipe (2026-08-04, teste E2E real): "a ia vai poder fazer pesquisas na
	web quando quiser, quando ela decidir" -- code_generator.py ja tinha
	isso (search_web + validate_import + fetch_url, proprios daquele
	dominio); esta extensao da o mesmo poder de decisao (so search_web, os
	outros dois sao especificos de geracao de codigo) a QUALQUER sub-agente
	que passe por _run_sub_agent(), sem duplicar o loop em cada um.
	Desativa o cache de prompt/resposta (_prompt_cache) quando ligado -- o
	cache atual e de resposta unica, nao cobre uma conversa multi-turno.
	"""
	docs_block = ("\n\n" + extra_docs) if extra_docs else ""
	full_system = NVDA_SYSTEM_PROMPT + docs_block + "\n\n" + system_addendum
	if final_tool:
		live_narrate = True
	if live_narrate:
		full_system += "\n" + _TOOL_PREAMBLE_INSTRUCTION
	if final_tool:
		full_system += "\n" + _FINAL_TOOL_INSTRUCTION.format(tool_name=final_tool["name"])
	live_narrator = None
	if live_narrate and on_chunk is None and "pytest" not in sys.modules and "unittest" not in sys.modules:
		live_narrator = LiveNarrator()
		on_chunk = live_narrator.feed
	try:
		# Cache de resposta unica nao cobre uma conversa multi-turno de
		# tool-calling -- desativado quando enable_web_search esta ligado.
		cache_enabled = (
			"pytest" not in sys.modules and "unittest" not in sys.modules
			and not enable_web_search
		)
		response_key = _prompt_cache_key(model_id, full_system, prompt, reasoning_params, cache_key or "")
		if cache_enabled:
			with _prompt_cache_lock:
				cached = _prompt_cache.get(response_key)
				if cached and time.time() - cached[0] <= _PROMPT_CACHE_TTL_SECONDS:
					_prompt_cache.move_to_end(response_key)
					_tl.last_tokens = 0
					_logger.info("[PROMPT_CACHE] hit model=%s", model_id)
					return cached[1]
				if cached:
					del _prompt_cache[response_key]

		client = _get_cached_client(model_id)
		if client is None:
			client = create_llm_client(model_id=model_id)
			_cache_client(model_id, client)
		chat_kwargs: dict[str, Any] = {
			"system_override": full_system,
		}
		if step_type:
			chat_kwargs["step_type"] = step_type
		# Sub-agentes nao publicam tokens no chat. Um callback explicito ainda
		# pode ser usado por um consumidor interno, sem acoplar ao canal da UI.
		if on_chunk:
			chat_kwargs["on_chunk"] = on_chunk
		tools: list[dict] = []
		if enable_web_search:
			tools.append(_SEARCH_WEB_TOOL_SCHEMA)
		if final_tool:
			tools.append(_final_tool_schema(final_tool))
		if tools:
			chat_kwargs["tools"] = tools
		resp: LLMResponse = client.chat(
			prompt,
			**chat_kwargs,
			**reasoning_params,
		)

		if enable_web_search:
			for _round in range(_MAX_SEARCH_TOOL_ROUNDS):
				if not resp.tool_calls:
					break
				tool_results = [
					r for r in (_dispatch_search_web_tool_call(tc) for tc in resp.tool_calls)
					if r is not None
				]
				if not tool_results:
					break
				is_last_round = _round == _MAX_SEARCH_TOOL_ROUNDS - 1
				round_kwargs = dict(chat_kwargs)
				round_kwargs["tool_results"] = tool_results
				if is_last_round:
					round_kwargs["tool_choice"] = "none"
				resp = client.chat(prompt, **round_kwargs, **reasoning_params)

		_tl.last_tokens = resp.tokens_used

		# `resp.truncated` existia desde llm_client 1.1.0 e SO o code_generator
		# olhava. Todo outro sub-agente -- design_review, engineering_review,
		# manifest_builder, auditoria -- podia ter a resposta cortada pelo teto de
		# tokens e entregar um documento pela metade ao Critic, que entao reprovava
		# por "termina de forma truncada". A peca existia e estava desligada de quem
		# precisava dela.
		#
		# Nao mexe no resultado: cortar ou remendar aqui seria inventar conteudo.
		# Registra, para que a causa apareca no log em vez de virar "o modelo
		# escreveu mal".
		if getattr(resp, "truncated", False):
			_logger.warning(
				"[TRUNCADO] Resposta do sub-agente (step_type=%s, modelo=%s) foi "
				"cortada pelo teto de tokens de saida -- o consumidor vai receber um "
				"documento incompleto.", step_type or "?", model_id,
			)
		result = _extract_final_tool_result(resp, final_tool) if final_tool else resp.content
		if cache_enabled and result:
			with _prompt_cache_lock:
				_prompt_cache[response_key] = (time.time(), result, resp.tokens_used)
				_prompt_cache.move_to_end(response_key)
				while len(_prompt_cache) > _PROMPT_CACHE_MAX_ENTRIES:
					_prompt_cache.popitem(last=False)

		return result
	except LLMClientError as exc:
		_logger.error("[ERRO] Sub-agente %s falhou: %s", model_id, exc)
		_tl.last_tokens = 0
		return f"[ERRO] Sub-agente nao conseguiu gerar resposta: {exc}"
	except Exception as exc:
		_logger.error("[ERRO] Sub-agente %s falhou de forma inesperada: %s", model_id, exc)
		_tl.last_tokens = 0
		return f"[ERRO] Sub-agente falhou de forma inesperada: {exc}"
	finally:
		if live_narrator is not None:
			live_narrator.flush()
