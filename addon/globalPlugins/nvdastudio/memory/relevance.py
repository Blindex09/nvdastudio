import json
from typing import Any, TypeVar

from ..utils.logger import get_logger

MODULE_VERSION = "2.1.0"
_logger = get_logger("memory_relevance")

T = TypeVar("T")


def _semantic_client():
	"""Cria sob demanda o modelo leve do provedor escolhido pelo usuario."""
	from ..ai.llm_factory import create_llm_client
	from ..ai.model_registry import resolve_provider_tier_model
	from ..gui.settings_panel import get_llm_model, get_llm_provider

	provider = get_llm_provider()
	model = resolve_provider_tier_model(provider, "light", get_llm_model())
	return create_llm_client(model, provider=provider)


def rank_relevant(
	query: str,
	candidates: list[tuple[str, T]],
	limit: int,
	client: Any = None,
) -> list[T]:
	"""Escolhe contexto por significado, sem pontuacao lexical ou palavras-gatilho."""
	if not query or not candidates or limit <= 0:
		return []

	items = [
		{"id": index, "text": text[:3000]}
		for index, (text, _item) in enumerate(candidates)
		if text and text.strip()
	]
	if not items:
		return []

	prompt = (
		"Selecione somente os textos semanticamente relevantes para a necessidade "
		"informada. Avalie significado e intenção completos. Não use coincidência de "
		"palavras como critério. Responda apenas JSON no formato "
		'{"selected_ids":[0,1]}. Se nada for relevante, devolva a lista vazia. '
		f"Escolha no máximo {limit}.\n\nNecessidade:\n{query}\n\nTextos:\n"
		+ json.dumps(items, ensure_ascii=False)
	)
	try:
		semantic_client = client or _semantic_client()
		response = semantic_client.chat(
			prompt,
			system_override=(
				"Você é um recuperador semântico de contexto. Não responda à necessidade; "
				"apenas selecione identificadores de textos realmente pertinentes."
			),
			response_format={"type": "json_object"},
			step_type="memory_retrieval",
		)
		data = json.loads(response.content)
		selected = data.get("selected_ids", [])
		result: list[T] = []
		seen: set[int] = set()
		for raw_id in selected:
			if isinstance(raw_id, bool):
				continue
			try:
				item_id = int(raw_id)
			except (TypeError, ValueError):
				continue
			if item_id in seen or not 0 <= item_id < len(candidates):
				continue
			seen.add(item_id)
			result.append(candidates[item_id][1])
			if len(result) >= limit:
				break
		return result
	except Exception as exc:
		# 2.1.0: BUG REAL achado ao vivo (loop noturno de E2E real,
		# 2026-08-18) -- quando o cliente LLM da selecao semantica falha
		# (rede, 429, timeout, qualquer erro), o fallback antigo devolvia
		# lista VAZIA -- toda a memoria de sessoes passadas ficava invisivel
		# durante qualquer instabilidade do provedor ativo, justamente
		# quando o sistema mais precisaria dessa licao (ex: conta sob rate
		# limit -- exatamente o cenario que expos isso: test_session_memory.py
		# achou 0 sessoes onde deveria achar 1, porque o Ollama estava
		# indisponivel no momento). Viola o principio de graceful
		# degradation ja documentado no projeto (conceitos-ia-seguranca-
		# confiabilidade.md) -- degradar deve preservar sinal, nao apagar
		# tudo. Fallback deterministico agora: devolve os primeiros `limit`
		# candidatos na ordem recebida (sem palavra-chave, sem heuristica de
		# conteudo -- so ordem de chegada, que ja e o formato que os
		# chamadores preparam, tipicamente mais recentes primeiro). Perde a
		# curadoria semantica, mas nunca perde o sinal inteiro.
		_logger.warning(
			"[MEMORIA] Selecao semantica indisponivel (%s) -- usando fallback "
			"deterministico (primeiros %d candidatos, sem curadoria semantica).",
			exc, limit,
		)
		return [item for _, item in candidates][:limit]
