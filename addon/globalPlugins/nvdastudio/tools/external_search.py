import os

from ..utils.logger import get_logger

MODULE_VERSION = "1.0.0"
_logger = get_logger("external_search")

_TAVILY_URL = "https://api.tavily.com/search"
_EXA_URL = "https://api.exa.ai/search"
_TIMEOUT = 20.0


def _httpx_module():
	try:
		import httpx
		return httpx
	except Exception:
		return None


def search_tavily(query: str, api_key: str, max_results: int = 5) -> list[dict]:
	"""Busca via Tavily. Retorna [] em qualquer falha (rede, auth, parsing)."""
	if not query.strip() or not api_key.strip():
		return []
	httpx = _httpx_module()
	if httpx is None:
		return []
	headers = {
		"Authorization": f"Bearer {api_key.strip()}",
		"Content-Type": "application/json",
	}
	payload = {"query": query, "max_results": max_results, "search_depth": "basic"}
	try:
		with httpx.Client(timeout=_TIMEOUT) as client:
			resp = client.post(_TAVILY_URL, headers=headers, json=payload)
			resp.raise_for_status()
			data = resp.json()
	except Exception as exc:
		_logger.warning("[EXTERNAL_SEARCH] Tavily falhou: %s", exc)
		return []
	results = []
	for r in data.get("results") or []:
		url = (r.get("url") or "").strip()
		if not url:
			continue
		results.append({
			"title": (r.get("title") or "").strip() or url,
			"url": url,
			"content": (r.get("content") or "").strip()[:600],
		})
	return results


def search_exa(query: str, api_key: str, num_results: int = 5) -> list[dict]:
	"""Busca via Exa. Retorna [] em qualquer falha (rede, auth, parsing)."""
	if not query.strip() or not api_key.strip():
		return []
	httpx = _httpx_module()
	if httpx is None:
		return []
	headers = {
		"x-api-key": api_key.strip(),
		"Content-Type": "application/json",
	}
	payload = {
		"query": query,
		"numResults": num_results,
		"contents": {"summary": True},
	}
	try:
		with httpx.Client(timeout=_TIMEOUT) as client:
			resp = client.post(_EXA_URL, headers=headers, json=payload)
			resp.raise_for_status()
			data = resp.json()
	except Exception as exc:
		_logger.warning("[EXTERNAL_SEARCH] Exa falhou: %s", exc)
		return []
	results = []
	for r in data.get("results") or []:
		url = (r.get("url") or "").strip()
		if not url:
			continue
		summary = (r.get("summary") or r.get("text") or "").strip()
		results.append({
			"title": (r.get("title") or "").strip() or url,
			"url": url,
			"content": summary[:600],
		})
	return results


def search_external(query: str, max_results: int = 5) -> list[dict]:
	"""
	Busca externa combinada via Tavily + Exa, deduplicada por URL.

	Chaves lidas de TAVILY_API_KEY/EXA_API_KEY (env). Nenhuma configurada
	retorna [] -- caller decide o fallback (nao e um erro, e um modo valido
	de operacao sem busca externa configurada).
	"""
	tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
	exa_key = os.getenv("EXA_API_KEY", "").strip()
	if not tavily_key and not exa_key:
		return []

	combined: list[dict] = []
	seen_urls: set[str] = set()

	if tavily_key:
		for r in search_tavily(query, tavily_key, max_results):
			if r["url"] not in seen_urls:
				seen_urls.add(r["url"])
				combined.append(r)

	if exa_key:
		for r in search_exa(query, exa_key, max_results):
			if r["url"] not in seen_urls:
				seen_urls.add(r["url"])
				combined.append(r)

	return combined


def format_results_for_prompt(results: list[dict]) -> str:
	"""Formata resultados como contexto de grounding para injetar no prompt do LLM."""
	if not results:
		return ""
	lines = ["Resultados de pesquisa web real (use como base -- nao invente URLs alem destas):"]
	for i, r in enumerate(results, 1):
		lines.append(f"[{i}] {r['title']}")
		if r.get("content"):
			lines.append(r["content"])
		lines.append(f"URL: {r['url']}")
		lines.append("")
	return "\n".join(lines)
