import os
import re
import threading
from typing import Optional

from ..ai.llm_factory import create_llm_client
from ..ai.llm_client import LLMClientError
from ..utils.injection_guard import sanitize_untrusted_block
from ..utils.logger import get_logger, log_llm_call, log_llm_response
from ._base import (
	_tl,
	narrate,
	LiveNarrator,
	_TOOL_PREAMBLE_INSTRUCTION,
	_final_tool_schema,
	_FINAL_TOOL_INSTRUCTION,
	_extract_final_tool_result,
)

_logger = get_logger("web_researcher")
MODULE_VERSION = "4.13.0"

# Cache: registros com menos de N dias sao considerados frescos.
# Opt-in explicito para busca real sob pytest. Ver o comentario em run().
_ENV_BUSCA_REAL = "NVDASTUDIO_BUSCA_REAL"
_CACHE_MAX_AGE_DAYS: int = 7

# Mesma string literal de core/orchestrator.py::_build_step_prompt() -- unico
# jeito deterministico de saber, aqui dentro, que este prompt e um RETRY (nao
# a 1a tentativa). Ver 4.9.0.
_RETRY_MARKER = "Problemas da tentativa anterior que DEVEM ser corrigidos:"

_SYSTEM = """Voce e o WebResearcher do NVDAStudio.
Sua funcao e responder perguntas sobre pacotes Python, APIs e bibliotecas
relevantes para o desenvolvimento de addons NVDA, usando seu conhecimento de treinamento.

ATENCAO: sua saida NUNCA e um bloco de codigo com nome de arquivo no formato
```python:caminho/arquivo.py``` (esse formato e do step code_generation, um
step DIFERENTE deste). Sua saida e SEMPRE o texto markdown descrito em
"Formato de Resposta Obrigatorio" abaixo -- mesmo quando a consulta menciona
uma API de IA, um SDK ou uma biblioteca que sera usada para escrever codigo
depois. Voce pesquisa e relata; nao escreve o addon.

## Interpretacao da Consulta
Decomponha a consulta identificando: pacote/API alvo, versao solicitada,
restricao de compatibilidade (Python 3.x, Windows, NVDA/wxPython).
Identifique o tipo de informacao necessaria: instalacao, API publica, exemplos ou limitacoes.

## Prioridades de Informacao
1. Documentacao oficial do pacote — versao estavel mais recente do treinamento
2. API publica: metodos, construtores, parametros e tipos de retorno
3. Compatibilidade com Python 3.x e Windows
4. Dependencias e requisitos de instalacao via pip

## Validacao da Fonte
Prefira: PyPI oficial, GitHub do projeto, Read the Docs.
Indique se a informacao e de versao especifica ou comportamento geral.

## Formato de Resposta Obrigatorio
**Pacote:** [nome pip exato]
**Versao estavel:** [X.Y.Z ou "nao determinada"]
**Instalacao:** `pip install [pacote]`
**API principal:** [metodos e parametros mais relevantes]
**Exemplo minimo:** [codigo Python funcional de 3-5 linhas]
**Compatibilidade NVDA/wxPython:** [observacoes especificas ou "sem restricoes conhecidas"]
**Confianca:** [Alta / Media / Baixa — baseado na cobertura do treinamento]"""

# Lock para requisicoes de pesquisa web (rate-limit consciente do provedor ativo)
_search_lock = threading.Lock()


# Mesma string literal de core/orchestrator.py::_build_step_prompt() -- marca
# onde comeca o objetivo ESPECIFICO deste step, depois do preambulo "Tarefa
# original do usuario: <pedido completo>" que e IDENTICO pra todo step do
# MESMO pedido. Ver 4.10.0.
_OBJECTIVE_MARKER = "Seu objetivo neste step:"


def _extract_topic(query: str) -> str:
	"""
	Chave de cache -- precisa ser ESPECIFICA da pergunta de pesquisa, nao do
	pedido de addon inteiro. Antes (ate 4.9.0), pegava so os primeiros 150
	chars do prompt bruto, que SEMPRE comecam com "Tarefa original do
	usuario: <pedido completo, longo>" (core/orchestrator.py::
	_build_step_prompt()) -- identico pra QUALQUER step do mesmo pedido de
	addon, so o objetivo especifico (que vem DEPOIS, e so aparece perto do
	char ~200-400 em pedidos complexos) distinguia uma pesquisa da outra.
	Resultado real: duas pesquisas genuinamente diferentes do mesmo addon
	colidiam na mesma chave de cache -- achado de auditoria de memoria
	(2026-08-09) apos revisar a robustez do cache corrigido em 4.8.0/4.9.0.
	Agora extrai a partir do marcador do objetivo especifico; cai pro
	comportamento antigo (primeiros 150 chars) se o marcador nao existir
	(chamada direta/teste sem passar por _build_step_prompt()).
	"""
	idx = query.find(_OBJECTIVE_MARKER)
	if idx != -1:
		return query[idx + len(_OBJECTIVE_MARKER):].strip()[:150]
	return query.strip()[:150]


_RAW_SOURCES_HEADER = "Fontes:"
_USER_SOURCES_HEADER = "Fontes consultadas:"


def _extract_sources_block(raw_web_result: str) -> str:
	"""
	Extrai deterministicamente a secao 'Fontes:' que native_web_search()/
	web_search() anexam ao resultado bruto (ver provider_client.py
	_format_with_sources() e ollama_client.py web_search()).

	Extracao por string, nao pela sintese do LLM: a sintese em
	_synthesize_web_results() e prosa livre e pode nao preservar URLs
	verbatim (parafrasear, resumir ou simplesmente nao repetir a lista) --
	quem precisa da lista exata de fontes le direto do texto bruto da busca,
	antes da sintese acontecer.
	"""
	idx = raw_web_result.find(_RAW_SOURCES_HEADER)
	if idx == -1:
		return ""
	return raw_web_result[idx + len(_RAW_SOURCES_HEADER):].strip()


def on_demand_web_search(query: str, model_id: str = "") -> str:
	"""
	Pesquisa web real via o provedor ATIVO -- nao mais um scraper proprio.

	Fluxo:
	  1. Cria o client do provedor configurado (mesmo usado pelo resto do
	     pipeline, via create_llm_client) para o model_id informado.
	  2. OllamaClient: chama web_search() (endpoint dedicado Ollama Cloud).
	     ProviderClient (openai/anthropic/gemini/xai): chama
	     native_web_search() (server tool de busca nativo do provedor).
	  3. Se falhar: retorna string vazia (caller faz fallback knowledge-only).

	Regra 9: nao executa codigo do usuario — apenas texto de busca.
	"""
	with _search_lock:
		try:
			client = create_llm_client(model_id=model_id)
		except LLMClientError as exc:
			_logger.warning("[WEB_SEARCH] nao foi possivel criar client: %s", exc)
			return ""

		narrate(f"navegando na web procurando informacao sobre {query}")
		result = ""
		try:
			if hasattr(client, "web_search"):
				_logger.info("[WEB_SEARCH] pesquisando via Ollama Cloud: '%s'", query[:60])
				result = client.web_search(query)
			elif hasattr(client, "native_web_search"):
				provider = getattr(client, "_provider", "provedor")
				_logger.info("[WEB_SEARCH] pesquisando via %s: '%s'", provider, query[:60])
				result = client.native_web_search(query)
			else:
				_logger.warning("[WEB_SEARCH] client %s nao suporta pesquisa web nativa.", type(client).__name__)
		except Exception as exc:
			_logger.warning("[WEB_SEARCH] falha na busca nativa: %s", exc)

		if not result:
			_logger.info("[WEB_SEARCH] busca nativa sem resultados para '%s' -- tentando fallback.", query[:60])
			result = _fallback_web_search(query)

		if not result:
			_logger.info("[WEB_SEARCH] sem resultados para: '%s'", query[:60])
			return ""
		# Reporta o resultado real ja obtido (pos-busca). A clausula "vou
		# organizar essa informacao agora" que existia aqui foi removida:
		# anunciava a sintese ANTES dela acontecer, o que ficou redundante
		# com a narracao ao vivo agora embutida no proprio content de
		# _synthesize_web_results() (padrao "final answer as tool call").
		narrate(f"encontrei resultados sobre {query}")
		_logger.info("[WEB_SEARCH] resultado obtido para '%s'", query[:60])
		return result


_TAVILY_URL = "https://api.tavily.com/search"
_EXA_URL = "https://api.exa.ai/search"
_FALLBACK_MAX_RESULTS = 5
_FALLBACK_TIMEOUT_SECONDS = 20.0


def _fallback_web_search(query: str) -> str:
	"""
	Fallback de busca web via Tavily/Exa (nesta ordem), usado quando o
	provedor de IA ativo nao tem web_search()/native_web_search() disponivel
	OU a chamada nativa falhou/voltou vazia (ex: modelo Ollama sem cobertura
	de busca nativa pra aquele request). Pedido do Felipe (2026-08-04, teste
	E2E real): "se algum modelo do ollama nao pesquisar na web, tem tavily e
	eza search que podemos usar tambem".

	Ambas as chaves sao OPCIONAIS -- sem nenhuma configurada (settings_panel.py
	6.7.0, get_api_key("tavily")/get_api_key("exa")), retorna "" silenciosamente,
	mesmo padrao de graceful degradation ja usado no resto deste modulo (o
	caller trata "" como "sem resultados", nunca quebra o pipeline).
	"""
	from ..gui.settings_panel import get_api_key

	tavily_key = get_api_key("tavily")
	if tavily_key:
		try:
			result = _tavily_search(query, tavily_key)
			if result:
				_logger.info("[WEB_SEARCH] fallback Tavily OK para '%s'", query[:60])
				return result
		except Exception as exc:
			_logger.warning("[WEB_SEARCH] fallback Tavily falhou: %s", exc)

	exa_key = get_api_key("exa")
	if exa_key:
		try:
			result = _exa_search(query, exa_key)
			if result:
				_logger.info("[WEB_SEARCH] fallback Exa OK para '%s'", query[:60])
				return result
		except Exception as exc:
			_logger.warning("[WEB_SEARCH] fallback Exa falhou: %s", exc)

	return ""


def _format_fallback_results(items: list[dict], title_key: str, url_key: str, text_key: str) -> str:
	"""Formata resultados de Tavily/Exa no mesmo shape textual (titulo/url/trecho
	por bloco) que o resto do modulo ja espera vindo da busca nativa dos provedores."""
	parts = []
	for item in items[:_FALLBACK_MAX_RESULTS]:
		title = (item.get(title_key) or "").strip()
		url = (item.get(url_key) or "").strip()
		text = (item.get(text_key) or "").strip()
		block = "\n".join(p for p in (title, url, text) if p)
		if block:
			parts.append(block)
	return "\n\n".join(parts)


def _tavily_search(query: str, api_key: str) -> str:
	"""Fonte: docs.tavily.com/documentation/api-reference/endpoint/search --
	POST https://api.tavily.com/search, Bearer auth, body {"query", "max_results"}."""
	from ..ai.provider_client import _httpx_module
	httpx = _httpx_module()
	resp = httpx.post(
		_TAVILY_URL,
		headers={"Authorization": f"Bearer {api_key}"},
		json={"query": query, "max_results": _FALLBACK_MAX_RESULTS, "search_depth": "basic"},
		timeout=_FALLBACK_TIMEOUT_SECONDS,
	)
	resp.raise_for_status()
	results = (resp.json() or {}).get("results") or []
	return _format_fallback_results(results, "title", "url", "content")


def _exa_search(query: str, api_key: str) -> str:
	"""Fonte: docs.exa.ai/reference/search -- POST https://api.exa.ai/search,
	header x-api-key, body {"query", "numResults", "contents": {"text": {...}}}."""
	from ..ai.provider_client import _httpx_module
	httpx = _httpx_module()
	resp = httpx.post(
		_EXA_URL,
		headers={"x-api-key": api_key},
		json={
			"query": query,
			"numResults": _FALLBACK_MAX_RESULTS,
			"contents": {"text": {"maxCharacters": 1500}},
		},
		timeout=_FALLBACK_TIMEOUT_SECONDS,
	)
	resp.raise_for_status()
	results = (resp.json() or {}).get("results") or []
	return _format_fallback_results(results, "title", "url", "text")


def _synthesize_web_results(query: str, web_results: str, model_id: str = "alto") -> str:
	"""
	Usa o modelo do provedor ativo para sintetizar resultados web brutos no
	formato padrao do WebResearcher.

	Fluxo:
	  1. Monta prompt com resultados brutos como contexto
	  2. Chama LLM com _SYSTEM + narracao ao vivo ("tool preamble") + tool de
	     entrega obrigatoria ("entregar_sintese") -- padrao "final answer as
	     tool call" (_base.py v1.13.0), aplicado aqui manualmente porque este
	     modulo nao usa _run_sub_agent(). O modelo narra o raciocinio da
	     sintese livremente no content (LiveNarrator emite em tempo real via
	     conversation.emit_status()) e entrega o texto final limpo como
	     argumento da tool, sem misturar narracao no resultado.
	  3. Retorna o resultado extraido da tool call (fallback gracioso pro
	     content bruto se o modelo nao chamar a tool -- ver
	     _extract_final_tool_result em _base.py)
	"""
	if not web_results.strip():
		return ""

	# Conteudo de paginas de terceiros (fora do controle do NVDAStudio) --
	# mesmo vetor de injecao indireta que memory_manager.py ja tratava pra
	# memoria persistente (utils/injection_guard.py, extraido de la nesta
	# versao). Envolve com marcadores explicitos em vez de bloquear a busca
	# inteira por uma frase suspeita -- resultados de busca real sao varios
	# KB, majoritariamente legitimos.
	safe_web_results = sanitize_untrusted_block(web_results, source_label="resultado de busca web")

	prompt = (
		f"Consulta do usuario: {query}\n\n"
		f"Resultados brutos da web:\n{safe_web_results}\n\n"
		f"Sintetize as informacoes acima no formato padrao do WebResearcher. "
		f"Se os resultados nao forem suficientes, indique 'Confianca: Baixa'."
	)

	final_tool = {
		"name": "entregar_sintese",
		"description": (
			"Entrega a sintese final dos resultados de pesquisa web, no "
			"formato padrao do WebResearcher."
		),
		"param_name": "sintese",
		"param_description": (
			"A sintese final completa, no formato padrao do WebResearcher "
			"(Pacote, Versao estavel, Instalacao, API principal, Exemplo "
			"minimo, Compatibilidade NVDA/wxPython, Confianca)."
		),
	}
	full_system = (
		_SYSTEM
		+ "\n" + _TOOL_PREAMBLE_INSTRUCTION
		+ "\n" + _FINAL_TOOL_INSTRUCTION.format(tool_name=final_tool["name"])
	)
	live = LiveNarrator()
	try:
		client = create_llm_client(model_id=model_id)
		resp = client.chat(
			prompt,
			system_override=full_system,
			tools=[_final_tool_schema(final_tool)],
			on_chunk=live.feed,
		)
		# Contabiliza o custo da sintese.
		#
		# Este caminho NAO registrava tokens -- so `_knowledge_only_call` fazia.
		# Enquanto a busca real estava desligada sob teste, o gasto aqui era zero
		# e ninguem notou; ligada (4.12.0), ele virou consumo REAL e INVISIVEL:
		# fora do relatorio e, pior, fora do medidor que decide parar o pipeline.
		#
		# Sintoma medido: web_research aparecia com tokens=0 mesmo com 3
		# retentativas, e o custo por step usado para dimensionar o orcamento
		# ficou subestimado por causa disso.
		_tl.last_tokens = getattr(_tl, "last_tokens", 0) + resp.tokens_used
		return _extract_final_tool_result(resp, final_tool) or ""
	except LLMClientError as exc:
		_logger.warning("[WEB_SEARCH] sintese falhou: %s", exc)
		return ""
	finally:
		live.flush()


def _knowledge_only_call(prompt: str, model_id: str) -> str:
	"""
	Chamada de LLM com o padrao "final answer as tool call" (mesmo usado no
	resto deste modulo) -- extraida de run() em 4.6.0 pra ser reutilizavel.

	4.7.0: parametro provider removido -- o resgate cross-provider
	(orchestrator.py::_try_cross_provider_rescue(), 5.37.0) agora roteia
	via a convencao "<provider>::<model_id>" embutida no proprio model_id
	(llm_factory.py 5.2.0), entao create_llm_client(model_id=model_id) ja
	resolve o provider certo sem precisar de um parametro separado aqui.
	"""
	final_tool = {
		"name": "entregar_conhecimento",
		"description": (
			"Entrega o resultado final da pesquisa de conhecimento "
			"(sem fonte web), no formato padrao do WebResearcher."
		),
		"param_name": "resposta",
		"param_description": (
			"O resultado final completo, no formato padrao do "
			"WebResearcher (Pacote, Versao estavel, Instalacao, API "
			"principal, Exemplo minimo, Compatibilidade NVDA/wxPython, "
			"Confianca)."
		),
	}
	full_system = (
		_SYSTEM
		+ "\n" + _TOOL_PREAMBLE_INSTRUCTION
		+ "\n" + _FINAL_TOOL_INSTRUCTION.format(tool_name=final_tool["name"])
	)
	live = LiveNarrator()
	try:
		log_llm_call(_logger, f"web_researcher_v{MODULE_VERSION}", prompt[:80])
		client = create_llm_client(model_id=model_id)
		resp = client.chat(
			prompt,
			system_override=full_system,
			tools=[_final_tool_schema(final_tool)],
			on_chunk=live.feed,
		)
		log_llm_response(_logger, f"web_researcher_v{MODULE_VERSION}", resp.content)
		# Soma, nao substitui: a sintese pode ter gasto e devolvido vazio antes
		# de cair aqui -- atribuir apagaria aquele custo do orcamento.
		_tl.last_tokens = getattr(_tl, "last_tokens", 0) + resp.tokens_used
		return _extract_final_tool_result(resp, final_tool) or ""
	finally:
		live.flush()


_CODE_FENCE_PATTERN = re.compile(r"```python:[^\n]*\n.*?```", re.DOTALL)


def _has_disallowed_code_fence(text: str) -> bool:
	"""Mesmo regex de ai/critic.py (guard deterministico do step
	web_research) -- reusado aqui pra checar ANTES de devolver ao Critic."""
	return bool(re.search(r"```python:", text))


def _correct_code_fence_violation(bad_output: str, model_id: str) -> str:
	"""
	Correcao deterministica do bug 4/5 (web_research devolvendo
	```python:arquivo.py``` em vez de texto de pesquisa) -- ver MODULE_VERSION
	4.8.0. Faz UMA chamada corretiva focada (reformatar a MESMA informacao,
	nao repesquisar) antes de devolver ao pipeline. Se a correcao tambem
	falhar (ou o modelo repetir o erro), remove o bloco proibido
	deterministicamente -- o padrao ```python: nunca escapa daqui pra fora,
	entao o guard do critic.py nunca mais precisa rejeitar por esse motivo
	especifico.
	"""
	final_tool = {
		"name": "entregar_correcao",
		"description": "Entrega a resposta reformatada, sem bloco de codigo com nome de arquivo.",
		"param_name": "resposta_corrigida",
		"param_description": (
			"A MESMA informacao de pesquisa da resposta anterior, reescrita "
			"no formato padrao do WebResearcher (Pacote/Versao estavel/"
			"Instalacao/API principal/Exemplo minimo/Compatibilidade/"
			"Confianca), SEM nenhum bloco ```python:nome_de_arquivo```."
		),
	}
	correction_prompt = (
		"Sua resposta anterior usou o formato ERRADO -- um bloco de codigo "
		"com nome de arquivo (```python:arquivo.py```), que e exclusivo do "
		"step code_generation, nunca de pesquisa. Reescreva a MESMA "
		"informacao no formato correto: texto markdown com os campos "
		"Pacote/Versao estavel/Instalacao/API principal/Exemplo minimo "
		"(um trecho curto de codigo SEM nome de arquivo e permitido dentro "
		"do campo Exemplo minimo, mas NUNCA um bloco "
		"```python:nome_de_arquivo```)/Compatibilidade/Confianca. Nao "
		"pesquise de novo -- so reformate o que ja foi encontrado.\n\n"
		f"Resposta anterior (formato errado):\n{bad_output[:3000]}"
	)
	full_system = (
		_SYSTEM
		+ "\n" + _TOOL_PREAMBLE_INSTRUCTION
		+ "\n" + _FINAL_TOOL_INSTRUCTION.format(tool_name=final_tool["name"])
	)
	corrected = ""
	try:
		client = create_llm_client(model_id=model_id)
		resp = client.chat(
			correction_prompt,
			system_override=full_system,
			tools=[_final_tool_schema(final_tool)],
		)
		corrected = _extract_final_tool_result(resp, final_tool) or ""
	except LLMClientError as exc:
		_logger.warning("[WEB_SEARCH] correcao de formato falhou: %s", exc)

	if corrected and not _has_disallowed_code_fence(corrected):
		_logger.info("[WEB_SEARCH] formato corrigido deterministicamente apos violacao.")
		return corrected

	# Correcao tambem falhou (ou o modelo repetiu o erro) -- remove o bloco
	# proibido. Nunca deixa o padrao ```python: escapar pro Critic.
	stripped = _CODE_FENCE_PATTERN.sub("", bad_output).strip()
	_logger.warning(
		"[WEB_SEARCH] correcao de formato nao resolveu -- bloco de codigo "
		"proibido removido deterministicamente do resultado."
	)
	if len(stripped) < 40:
		return (
			"**Pacote:** nao determinado\n"
			"**Confianca:** Baixa — a pesquisa nao retornou informacao "
			"utilizavel neste formato."
		)
	return stripped


def run(
	prompt: str,
	model_id: str,
	reasoning_params: dict,
	_memory=None,
	cache_key: str | None = None,
) -> str:
	"""
	Pesquisa de conhecimento via LLM, com pesquisa web real.

	Fluxo:
	  1. Verifica cache web_knowledge — se hit recente, retorna sem chamar LLM
	  2. Chama on_demand_web_search() e sintetiza o resultado via LLM
	  3. Se a fonte falhar, chama LLM com knowledge-only como fallback
	  5. Salva resultado no cache

	_memory: instancia SessionMemory injetavel para testes.
	"""
	if _memory is None:
		try:
			from ..memory.session_memory import memory as _default_mem
			_memory = _default_mem
		except Exception:
			_memory = None

	# Zera antes de acumular: sem isto, uma chamada que nao gera custo herdaria
	# o total da anterior e o orcamento contaria o mesmo gasto duas vezes.
	_tl.last_tokens = 0
	topic = _extract_topic(prompt)

	# 1. Verifica cache -- NUNCA num retry (ver 4.9.0). _extract_topic() pega
	# os primeiros 150 chars do prompt, que sempre comecam com "Tarefa
	# original do usuario: <query completa>" (orchestrator.py::
	# _build_step_prompt()) -- IDENTICO em toda tentativa do MESMO step,
	# retry incluso. Sem essa checagem, um retry (que existe justamente pra
	# gerar uma resposta NOVA porque a anterior falhou) so reaproveitava o
	# cache da 1a tentativa -- nunca chamava o LLM de novo, faz o retry
	# inteiro virar decoracao. Achado real: log de producao mostrou 4
	# tentativas seguidas (incluindo escalacao cross-provider) todas como
	# "[CACHE] hit" pro mesmo topico.
	is_retry = _RETRY_MARKER in prompt
	if _memory is not None and not is_retry:
		try:
			cached = _memory.get_web_knowledge(topic, max_age_days=_CACHE_MAX_AGE_DAYS)
			if cached and _has_disallowed_code_fence(cached[0]["content"]):
				# 4.8.0: achado real de auditoria (test_e36, 2026-08-09) --
				# um resultado com ```python:arquivo.py``` cacheado ANTES
				# deste guard existir fazia TODA retentativa e ate a
				# escalacao cross-provider devolverem o MESMO cache hit,
				# sem nunca chamar o LLM de novo -- 4 tentativas (2 no
				# provider original + rescue via outro provider) bateram
				# no MESMO cache stale, tornando retry/rescue inuteis.
				# Cache invalido = tratado como miss, nunca reutilizado.
				_logger.warning(
					"[CACHE] entrada cacheada para '%s' viola o guard de "
					"formato -- descartando, tratando como cache miss.",
					topic[:60],
				)
			elif cached:
				_logger.info("[CACHE] hit para '%s'", topic[:60])
				return f"[CACHE] {cached[0]['content']}"
		except Exception as exc:
			_logger.info("[CACHE] erro ao consultar: %s", exc)

	# 2. Este agente tem a funcao explicita de pesquisar: tenta a fonte real sempre.
	web_result: Optional[str] = None
	_logger.info("[WEB_SEARCH] pesquisando fonte atual para '%s'", topic[:60])
	# A suite isolada nao acessa a rede, exceto quando o proprio teste injeta
	# uma funcao de busca simulada. Isso nao interpreta o texto da consulta.
	#
	# 4.12.0 -- O GUARDA ERA LARGO DEMAIS E INVALIDOU MEDICAO.
	#
	# "pytest esta importado" pegava tambem os testes E2E, que existem
	# justamente para exercitar o pipeline de verdade e carregam chaves de API
	# reais. Resultado medido na rodada 5: 43 buscas iniciadas, 3 sinteses
	# concluidas -- 40 cairam no fallback por conhecimento do modelo.
	#
	# Consequencia: em SEIS rodadas E2E, todo step de web_research respondeu
	# so com o conhecimento de treino, e foi reprovado sempre pelo mesmo
	# motivo -- "usa o pacote legado google-generativeai". A conclusao obvia
	# ("a pesquisa e ruim") estava medindo o arnes de teste, nao o produto.
	#
	# Agora e opt-in EXPLICITO: sem a variavel, teste nenhum vai a rede (o
	# padrao seguro continua); com ela, o E2E mede o que o usuario teria.
	import sys
	search_is_real = getattr(on_demand_web_search, "__module__", "") == __name__
	em_teste = "pytest" in sys.modules or "unittest" in sys.modules
	busca_liberada = os.environ.get(_ENV_BUSCA_REAL, "").strip() == "1"
	if em_teste and search_is_real and not busca_liberada:
		_logger.info(
			"[WEB_SEARCH] busca real desligada sob teste (defina %s=1 para "
			"habilitar). Caindo no conhecimento do modelo.", _ENV_BUSCA_REAL,
		)
		raw_web = ""
	else:
		raw_web = on_demand_web_search(prompt, model_id=model_id)
	if raw_web:
		synthesized = _synthesize_web_results(prompt, raw_web, model_id=model_id)
		if synthesized:
			sources = _extract_sources_block(raw_web)
			if sources:
				synthesized = f"{synthesized}\n\n{_USER_SOURCES_HEADER}{sources}"
			web_result = f"[WEB_SEARCH] {synthesized}"
			_logger.info("[WEB_SEARCH] sintese concluida para '%s'", topic[:60])

	# 3. Fallback knowledge-only (se web falhou ou nao necessario)
	if web_result is None:
		try:
			result = _knowledge_only_call(prompt, model_id)
		except LLMClientError as exc:
			_logger.warning("[AVISO] WebResearcher falhou: %s", exc)
			return f"[ERRO] WebResearcher: {exc}"
	else:
		result = web_result

	if not result.strip():
		_logger.warning("[AVISO] WebResearcher retornou resposta vazia.")
		return "[ERRO] WebResearcher: resposta vazia."

	# 3.5 Guard deterministico (4.8.0): corrige/remove ```python:arquivo.py```
	# ANTES de devolver ao pipeline -- ver _correct_code_fence_violation().
	if _has_disallowed_code_fence(result):
		_logger.warning(
			"[WEB_SEARCH] violacao de formato detectada (```python:) -- "
			"corrigindo deterministicamente antes de devolver ao Critic."
		)
		result = _correct_code_fence_violation(result, model_id)

	# 4. NAO salva aqui. Ver salvar_se_aprovado().
	#
	# Ate 2026-09-01 o resultado era cacheado NESTE ponto, antes de o Critic
	# existir na historia -- ele so avalia depois que este agente retorna. Uma
	# pesquisa que o proprio pipeline julgava errada virava "conhecimento"
	# persistido por 7 dias e servido a toda execucao seguinte.
	#
	# Medido: 15 relatorios com a MESMA reprovacao -- "a pesquisa usa o pacote
	# legado google-generativeai, mas o objetivo exige google-genai". E o cache
	# tambem alimenta o code_generator (busca proativa), entao a pesquisa
	# reprovada chegava direto na geracao de codigo.
	#
	# Cachear so o que passou na verificacao nao e otimizacao: e a diferenca
	# entre memoria e boato.
	return result


def salvar_se_aprovado(prompt: str, content: str, _memory=None) -> bool:
	"""
	Persiste a pesquisa no cache -- so quando o Critic aprovou.

	Chamado pelo orchestrator, que e quem conhece o veredicto. O topico e
	derivado do MESMO `_extract_topic()` usado na leitura, entao gravacao e
	leitura nao podem divergir (Regra 5).

	Nunca levanta: falha ao cachear nao pode derrubar um step aprovado.
	"""
	if not (content or "").strip():
		return False
	if _memory is None:
		try:
			from ..memory.session_memory import memory as _default_mem
			_memory = _default_mem
		except Exception:
			return False
	try:
		topico = _extract_topic(prompt)
		_memory.save_web_knowledge(topico, content)
		_logger.info("[CACHE] salvo (aprovado) para '%s'.", topico[:60])
		return True
	except Exception as exc:
		_logger.info("[CACHE] erro ao salvar: %s", exc)
		return False
