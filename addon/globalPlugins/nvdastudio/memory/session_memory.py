import os
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass

try:
	from tinydb import TinyDB, Query
	_TINYDB_AVAILABLE = True
except ImportError:
	# tinydb nao bundled ainda — graceful degradation
	_TINYDB_AVAILABLE = False
	TinyDB = None   # type: ignore
	Query   = None  # type: ignore

from ..utils.logger import get_logger
from .relevance import rank_relevant

MODULE_VERSION = "3.6.0"
_logger = get_logger("session_memory")

# NVDASTUDIO_MEMORY_DIR redireciona o banco -- existe para ISOLAMENTO DE TESTE.
#
# Achado em 2026-09-01: a suite de testes escrevia no banco REAL do usuario
# (%APPDATA%/NVDAStudio/memory.json). Encontrada la uma entrada de
# web_knowledge com topic="prompt" e content="output valido" -- string de mock
# de teste, nao conhecimento pesquisado.
#
# Esse banco alimenta get_similar_sessions(), get_common_mistakes() e a busca
# proativa do code_generator: dado sintetico ali vira contexto de uma geracao
# real. Rodar teste nao pode mudar o estado do usuario, e muito menos ensinar
# coisa errada ao pipeline.
def resolver_dir_do_banco() -> str:
	"""Diretorio do banco: NVDASTUDIO_MEMORY_DIR quando definido, senao o do
	usuario. Funcao, e nao expressao solta, para poder ser testada sem
	recarregar o modulo -- recarregar troca a identidade das classes e quebra
	o `isinstance` de outros testes."""
	return os.environ.get("NVDASTUDIO_MEMORY_DIR", "").strip() or os.path.join(
		os.path.expanduser("~"), "AppData", "Roaming", "NVDAStudio"
	)


_DB_DIR  = resolver_dir_do_banco()
_DB_PATH = os.path.join(_DB_DIR, "memory.json")

# Limites de retencao para evitar crescimento ilimitado das tabelas.
# skill: memory-systems — "Consolidate memories periodically to prevent unbounded growth."
# skill: agent-memory-systems — anti-padrao "Store Everything Forever".
_MAX_STEP_METRICS: int = 2000   # max registros na tabela step_metrics
_MAX_SESSIONS:     int = 1000   # max registros na tabela sessions
_PRUNE_INTERVAL:   int = 100    # prune e acionado a cada N novas insercoes


@dataclass
class SessionRecord:
	"""Registro de uma sessao de criacao de addon."""
	id: int
	created_at: str
	query: str
	addon_name: str
	plan_id: str
	steps_ok: int
	steps_total: int
	retries: int
	success: bool
	summary: str
	prompt_version: str = ""


class SessionMemory:
	"""
	Memoria persistente entre sessoes via TinyDB (JSON puro).
	Thread-safe via lock interno.
	Inicializacao lazy — abre arquivo apenas na primeira operacao.

	Estrutura do JSON:
	  sessions:    lista de registros de sessao (episodic memory)
	  preferences: chave/valor de preferencias do usuario (semantic memory)
	"""

	def __init__(self):
		self._lock  = threading.Lock()
		self._db: TinyDB | None = None   # type: ignore[valid-type]  # TinyDB=None quando indisponivel
		self._ready = False

	def _init_db(self):
		"""Abre o banco TinyDB. Idempotente. No-op se tinydb indisponivel."""
		if self._ready:
			return
		if not _TINYDB_AVAILABLE:
			_logger.warning(
				"[AVISO] tinydb nao disponivel. "
				"Adicione tinydb ao lib_requirements.txt e rebuilde o addon. "
				"SessionMemory em modo no-op."
			)
			self._ready = True
			return
		try:
			os.makedirs(_DB_DIR, exist_ok=True)
			self._db = TinyDB(_DB_PATH, indent=2, ensure_ascii=False, encoding="utf-8")
			self._ready = True
			_logger.info("[OK] SessionMemory v%s inicializada em %s", MODULE_VERSION, _DB_PATH)
		except Exception as exc:
			_logger.error("[ERRO] SessionMemory: falha ao abrir banco: %s", exc)

	# ------------------------------------------------------------------
	# Pruning interno (anti-padrao "Store Everything Forever")
	# ------------------------------------------------------------------

	def _prune_if_needed(self, table_name: str, max_records: int) -> None:
		"""
		Remove registros antigos se a tabela exceder max_records.
		Mantém apenas os max_records mais recentes (doc_id maior = mais recente).
		Chamado internamente por log_step_metric() e save_session() a cada
		_PRUNE_INTERVAL insercoes para evitar crescimento ilimitado.

		Nao lanca excecoes — falha silenciosa (nao pode bloquear operacao principal).
		Ja deve ser chamado dentro de self._lock.
		skill: memory-systems — "Consolidate memories periodically to prevent unbounded growth."
		skill: agent-memory-systems — anti-padrao "Store Everything Forever".
		"""
		if self._db is None:
			return
		try:
			table = self._db.table(table_name)
			all_docs = table.all()
			if len(all_docs) <= max_records:
				return
			# Ordena por doc_id crescente (mais antigos primeiro) e remove o excesso
			sorted_docs = sorted(all_docs, key=lambda d: d.doc_id)
			to_remove = len(all_docs) - max_records
			ids_to_remove = [d.doc_id for d in sorted_docs[:to_remove]]
			table.remove(doc_ids=ids_to_remove)
			_logger.info(
				"[OK] SessionMemory.prune: tabela=%s removidos=%d mantidos=%d",
				table_name, to_remove, max_records
			)
		except Exception as exc:
			_logger.warning("[AVISO] SessionMemory._prune_if_needed(%s): %s", table_name, exc)

	def prune_old_metrics(self) -> int:
		"""
		Remove registros antigos de step_metrics mantendo os _MAX_STEP_METRICS mais recentes.
		Retorna quantos registros foram removidos (0 se nao havia excesso).
		API publica para prune explicito, ex: chamada periodica ou no startup.
		"""
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return 0
			try:
				table = self._db.table("step_metrics")
				before = len(table.all())
				self._prune_if_needed("step_metrics", _MAX_STEP_METRICS)
				after = len(table.all())
				return max(0, before - after)
			except Exception as exc:
				_logger.warning("[AVISO] prune_old_metrics: %s", exc)
				return 0

	def prune_old_sessions(self) -> int:
		"""
		Remove registros antigos de sessions mantendo os _MAX_SESSIONS mais recentes.
		Retorna quantos registros foram removidos.
		"""
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return 0
			try:
				table = self._db.table("sessions")
				before = len(table.all())
				self._prune_if_needed("sessions", _MAX_SESSIONS)
				after = len(table.all())
				return max(0, before - after)
			except Exception as exc:
				_logger.warning("[AVISO] prune_old_sessions: %s", exc)
				return 0

	def close(self) -> None:
		"""
		Fecha o TinyDB e libera o arquivo no disco.
		Necessario no Windows antes de apagar diretorio temporario (file lock).
		Idempotente; proxima operacao reabre o banco.
		"""
		with self._lock:
			if self._db is not None:
				try:
					self._db.close()
				except Exception as exc:
					_logger.warning("[AVISO] SessionMemory.close: %s", exc)
				self._db = None
			self._ready = False

	# ------------------------------------------------------------------
	# API Publica
	# ------------------------------------------------------------------

	def save_session(
		self,
		query: str,
		addon_name: str,
		plan_id: str,
		steps_ok: int,
		steps_total: int,
		retries: int,
		success: bool,
		summary: str,
		prompt_version: str = "",
		step_issues: list | None = None,
		total_tokens: int = 0,
		step_type: str = "",
	) -> int | None:
		"""
		Salva resultado de uma sessao.
		step_issues: lista de problemas encontrados nos steps (para feedback loop).
		total_tokens: total de tokens consumidos em todos os steps da sessao.
		step_type: tipo do step que gerou os issues (code_generation, manifest_builder, etc.).
		Retorna o id (doc_id TinyDB) ou None em caso de erro.
		Regra 9: armazena apenas texto — nunca executa.
		"""
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return None
			try:
				table = self._db.table("sessions")
				issues_str = "; ".join((step_issues or [])[:5])[:300]
				doc_id = table.insert({
					"created_at":     datetime.now().isoformat(timespec="seconds"),
					"query":          query[:500],
					"addon_name":     addon_name[:100],
					"plan_id":        plan_id[:50],
					"steps_ok":       steps_ok,
					"steps_total":    steps_total,
					"retries":        retries,
					"success":        int(success),
					"summary":        summary[:500],
					"prompt_version": prompt_version[:20],
					"step_issues":    issues_str,
					"total_tokens":   total_tokens,
					"step_type":      step_type[:50],
				})
				_logger.info(
					"[OK] Sessao %d salva. addon=%s success=%s tokens=%d step_type=%s",
					doc_id, addon_name, success, total_tokens, step_type or "n/a"
				)
				# Prune automatico a cada _PRUNE_INTERVAL insercoes
				try:
					count = len(table.all())
					if count > 0 and count % _PRUNE_INTERVAL == 0:
						self._prune_if_needed("sessions", _MAX_SESSIONS)
				except Exception as exc:
					_logger.debug("[DEBUG] Prune automatico falhou: %s", exc)
				return doc_id
			except Exception as exc:
				_logger.error("[ERRO] SessionMemory.save_session: %s", exc)
				return None

	def get_recent(self, limit: int = 10) -> list[SessionRecord]:
		"""Retorna as sessoes mais recentes, ordenadas por doc_id decrescente."""
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return []
			try:
				table = self._db.table("sessions")
				all_docs = table.all()
				# Ordena por doc_id decrescente (mais recente primeiro)
				sorted_docs = sorted(all_docs, key=lambda d: d.doc_id, reverse=True)
				result = []
				for doc in sorted_docs[:limit]:
					result.append(SessionRecord(
						id=doc.doc_id,
						created_at=doc.get("created_at", ""),
						query=doc.get("query", ""),
						addon_name=doc.get("addon_name", ""),
						plan_id=doc.get("plan_id", ""),
						steps_ok=doc.get("steps_ok", 0),
						steps_total=doc.get("steps_total", 0),
						retries=doc.get("retries", 0),
						success=bool(doc.get("success", 0)),
						summary=doc.get("summary", ""),
						prompt_version=doc.get("prompt_version", ""),
					))
				return result
			except Exception as exc:
				_logger.error("[ERRO] SessionMemory.get_recent: %s", exc)
				return []

	def get_preference(self, key: str, default: str = "") -> str:
		"""Recupera preferencia do usuario."""
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return default
			try:
				table = self._db.table("preferences")
				Q = Query()
				row = table.search(Q.key == key)
				return row[0]["value"] if row else default
			except Exception as exc:
				_logger.error("[ERRO] SessionMemory.get_preference: %s", exc)
				return default

	def set_preference(self, key: str, value: str) -> bool:
		"""Salva preferencia do usuario (upsert por chave)."""
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return False
			try:
				table = self._db.table("preferences")
				Q = Query()
				table.upsert({"key": key, "value": value}, Q.key == key)
				return True
			except Exception as exc:
				_logger.error("[ERRO] SessionMemory.set_preference: %s", exc)
				return False

	def get_recent_failures(self, limit: int = 3, step_type: str = "") -> list:
		"""
		Retorna issues de sessoes recentes com falha (success=0).

		step_type: se informado, filtra apenas falhas do mesmo tipo de step.
		  Evita que falha de manifest_builder apareça como licao para code_generation.
		  Garante que cada sub-agente aprende so com seus proprios erros historicos.
		  (skill: memory-systems — recuperar a informacao certa, nao qualquer informacao)

		Usado pelo orchestrator para injetar no prompt de sub-agentes
		e evitar erros ja cometidos anteriormente (feedback loop).
		Regra 9: apenas leitura, nunca executa conteudo.
		"""
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return []
			try:
				table = self._db.table("sessions")
				all_docs = table.all()
				failed = [
					d for d in all_docs
					if not int(d.get("success", 1))
					and d.get("step_issues", "").strip()
					and (not step_type or d.get("step_type", "") == step_type)
				]
				# Mais recentes primeiro
				failed.sort(key=lambda d: d.doc_id, reverse=True)
				return [d["step_issues"] for d in failed[:limit]]
			except Exception as exc:
				_logger.error("[ERRO] SessionMemory.get_recent_failures: %s", exc)
				return []

	def get_session_count(self) -> int:
		"""Numero total de sessoes salvas."""
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return 0
			try:
				return len(self._db.table("sessions"))
			except Exception:
				return 0

	def get_stats_by_prompt_version(self) -> list[dict]:
		"""
		Agrega estatisticas por prompt_version para A/B de prompts.
		Retorna: [{prompt_version, sessions, steps_ok, steps_total, success_rate}]
		Baseado em c:\\skills\\llm-app-patterns\\SKILL.md (prompt versioning).
		Regra 9: apenas leitura, nunca executa conteudo armazenado.
		"""
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return []
			try:
				all_docs = self._db.table("sessions").all()
				# Agrega manualmente por prompt_version
				groups: dict[str, dict] = {}
				for doc in all_docs:
					pv = doc.get("prompt_version", "") or ""
					if pv not in groups:
						groups[pv] = {
							"prompt_version": pv,
							"sessions": 0,
							"steps_ok": 0,
							"steps_total": 0,
							"successes": 0,
						}
					g = groups[pv]
					g["sessions"]    += 1
					g["steps_ok"]    += doc.get("steps_ok", 0) or 0
					g["steps_total"] += doc.get("steps_total", 0) or 0
					g["successes"]   += int(doc.get("success", 0) or 0)

				result = []
				for g in sorted(groups.values(), key=lambda x: x["sessions"], reverse=True):
					total = g["sessions"]
					result.append({
						"prompt_version": g["prompt_version"],
						"sessions":       total,
						"steps_ok":       g["steps_ok"],
						"steps_total":    g["steps_total"],
						"success_rate":   round(g["successes"] / total, 3) if total > 0 else 0.0,
					})
				return result
			except Exception as exc:
				_logger.error("[ERRO] SessionMemory.get_stats_by_prompt_version: %s", exc)
				return []

	def log_step_metric(
		self,
		step_type: str,
		success: bool,
		retries: int = 0,
		tokens: int = 0,
		latency_ms: int = 0,
		complexity_level: str = "simple",
		model_id: str = "",
		provider: str = "",
		trajectory: str = "",
	) -> None:
		"""
		Registra metrica de um step individual apos execucao.
		Tabela 'step_metrics' — separada de 'sessions' para nao poluir o historico.

		skill: agent-orchestration-improve-agent (Phase 1: Performance Analysis).
		skill: llm-app-patterns Section 4 (LLMOps): latency_ms completa o performance baseline.
		skill: evaluation (95% Finding): complexity_level estratifica simples vs complexas.
		Permite identificar quais sub-agentes falham mais em queries complexas.

		model_id/provider (2.0.0): achado real comparando com C:\\agentic (outro
		projeto do Felipe) -- o roteador de la pontua modelos por confiabilidade
		OBSERVADA e persistida (successes/attempts por modelo). Este metodo
		registrava tudo MENOS qual modelo rodou o step -- nao dava pra saber
		"deepseek-v4-flash falha mais em web_research que kimi" sem essa coluna.
		Campos opcionais (default vazio) pra nao quebrar chamadores existentes.

		trajectory (3.3.0): rotulo compacto do CAMINHO percorrido ate o
		resultado -- "direct" (aprovado de primeira), "retried" (aprovado
		apos 1+ retry), "loop_detected" (saiu cedo porque a tentativa
		repetiu o mesmo erro da anterior, ver orchestrator.py 5.42.0) ou
		"exhausted" (esgotou max_retries sem repeticao detectada). Fecha o
		gap de "Trajectory Evals" (so tinha resultado FINAL de cada step,
		nunca o formato do CAMINHO que levou ate ele -- por que ele
		aprovou/falhou, nao so se aprovou/falhou).

		Regra 9: apenas armazena metricas, nunca executa conteudo.
		"""
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return
			try:
				self._db.table("step_metrics").insert({
					"created_at":       datetime.now().isoformat(timespec="seconds"),
					"step_type":        step_type[:50],
					"success":          int(success),
					"retries":          retries,
					"tokens":           tokens,
					"latency_ms":       latency_ms,
					"complexity_level": complexity_level[:10],
					"model_id":         model_id[:80],
					"provider":         provider[:30],
					"trajectory":       trajectory[:20],
				})
				# Prune automatico a cada _PRUNE_INTERVAL insercoes
				try:
					count = len(self._db.table("step_metrics").all())
					if count > 0 and count % _PRUNE_INTERVAL == 0:
						self._prune_if_needed("step_metrics", _MAX_STEP_METRICS)
				except Exception as exc:
					_logger.debug("[DEBUG] Prune automatico falhou: %s", exc)
			except Exception as exc:
				_logger.warning("[AVISO] log_step_metric: %s", exc)

	def get_step_success_rates(
		self, last_n: int = 50, complexity_level: str | None = None
	) -> list[dict]:
		"""
		Retorna taxa de sucesso (primeira tentativa e geral) por step_type.
		Baseado nos ultimos `last_n` registros de step_metrics.

		Retorna lista de dicts ordenada por success_rate ascendente
		(agentes com mais falhas primeiro — foco de melhoria).

		Se complexity_level for fornecido (simple/medium/complex), filtra por
		complexidade — permite ver se agentes falham mais em queries complexas.

		skill: agent-orchestration-improve-agent (Failure Mode Classification).
		skill: evaluation (95% Finding: Test sets should span complexity levels).
		"""
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return []
			try:
				all_docs = self._db.table("step_metrics").all()
				if complexity_level is not None:
					all_docs = [d for d in all_docs
								if d.get("complexity_level", "simple") == complexity_level]
				# Ultimos N registros
				sorted_docs = sorted(all_docs, key=lambda d: d.doc_id, reverse=True)[:last_n]
				groups: dict[str, dict] = {}
				for doc in sorted_docs:
					st = doc.get("step_type", "unknown")
					if st not in groups:
						groups[st] = {"step_type": st, "total": 0, "successes": 0,
									  "first_attempt": 0, "total_tokens": 0, "total_latency": 0}
					g = groups[st]
					g["total"] += 1
					g["successes"] += int(doc.get("success", 0))
					if doc.get("retries", 0) == 0 and doc.get("success", 0):
						g["first_attempt"] += 1
					g["total_tokens"] += doc.get("tokens", 0)
					g["total_latency"] += doc.get("latency_ms", 0)
				result = []
				for g in groups.values():
					total = g["total"]
					result.append({
						"step_type":           g["step_type"],
						"total":               total,
						"success_rate":        round(g["successes"] / total, 2) if total > 0 else 0.0,
						"first_attempt_rate":  round(g["first_attempt"] / total, 2) if total > 0 else 0.0,
						"avg_tokens":          round(g["total_tokens"] / total) if total > 0 else 0,
						"avg_latency_ms":      round(g["total_latency"] / total) if total > 0 else 0,
					})
				# Agentes mais problemáticos primeiro (menor success_rate)
				result.sort(key=lambda x: x["success_rate"])
				return result
			except Exception as exc:
				_logger.error("[ERRO] get_step_success_rates: %s", exc)
				return []

	def get_trajectory_breakdown(
		self, step_type: str | None = None, last_n: int = 200,
	) -> dict[str, int]:
		"""
		Conta quantos steps recentes seguiram cada CAMINHO (trajectory) --
		direct/retried/loop_detected/exhausted -- em vez de so o resultado
		final. 3.3.0. Registros antigos (sem o campo, gravados antes desta
		versao) contam como "" e sao ignorados no total, nao quebram a soma.

		skill: trajectory-evals -- "nao so O QUE aconteceu, mas COMO".
		Uso tipico: se "loop_detected" cresce muito num step_type, o
		fix_instructions do Critic pra esse tipo de step provavelmente
		precisa de ajuste (esta pedindo a mesma correcao que o modelo ja
		provou nao conseguir fazer).
		"""
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return {}
			try:
				all_docs = self._db.table("step_metrics").all()
				if step_type is not None:
					all_docs = [d for d in all_docs if d.get("step_type") == step_type]
				sorted_docs = sorted(all_docs, key=lambda d: d.doc_id, reverse=True)[:last_n]
				counts: dict[str, int] = {}
				for doc in sorted_docs:
					traj = doc.get("trajectory", "")
					if not traj:
						continue
					counts[traj] = counts.get(traj, 0) + 1
				return counts
			except Exception as exc:
				_logger.error("[ERRO] get_trajectory_breakdown: %s", exc)
				return {}

	def get_cost_breakdown(
		self, last_n: int = 500, since_days: int | None = None,
	) -> dict:
		"""
		3.4.0: converte tokens registrados em step_metrics em custo estimado
		real (USD/BRL), usando ai/pricing.py -- fecha o gap de "Cost
		Monitoring" (auditoria de terminologia 2026): tokens ja eram
		registrados por step, mas nunca convertidos em $ de verdade.

		Retorna {"total_usd", "total_brl", "by_model": {model_id: {tokens,
		usd, brl, calls}}, "by_provider": {provider: {tokens, usd, brl}}}.
		since_days filtra por created_at (ISO) quando informado -- None usa
		todos os last_n registros mais recentes, igual aos outros metodos de
		agregacao desta classe.

		Regra 9: apenas leitura/agregacao, nunca executa conteudo.
		"""
		from ..ai.pricing import estimate_cost_usd, USD_TO_BRL_RATE

		empty = {"total_usd": 0.0, "total_brl": 0.0, "by_model": {}, "by_provider": {}}
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return empty
			try:
				all_docs = self._db.table("step_metrics").all()
				if since_days is not None:
					cutoff = (datetime.now() - timedelta(days=since_days)).isoformat(
						timespec="seconds"
					)
					all_docs = [d for d in all_docs if d.get("created_at", "") >= cutoff]
				sorted_docs = sorted(all_docs, key=lambda d: d.doc_id, reverse=True)[:last_n]

				by_model: dict[str, dict] = {}
				by_provider: dict[str, dict] = {}
				total_usd = 0.0
				for doc in sorted_docs:
					model_id = doc.get("model_id", "") or "desconhecido"
					provider = doc.get("provider", "") or "desconhecido"
					tokens = doc.get("tokens", 0) or 0
					usd = estimate_cost_usd(model_id, tokens, provider)
					total_usd += usd

					m = by_model.setdefault(model_id, {"tokens": 0, "usd": 0.0, "calls": 0})
					m["tokens"] += tokens
					m["usd"] += usd
					m["calls"] += 1

					p = by_provider.setdefault(provider, {"tokens": 0, "usd": 0.0})
					p["tokens"] += tokens
					p["usd"] += usd

				for m in by_model.values():
					m["usd"] = round(m["usd"], 6)
					m["brl"] = round(m["usd"] * USD_TO_BRL_RATE, 6)
				for p in by_provider.values():
					p["usd"] = round(p["usd"], 6)
					p["brl"] = round(p["usd"] * USD_TO_BRL_RATE, 6)

				return {
					"total_usd": round(total_usd, 6),
					"total_brl": round(total_usd * USD_TO_BRL_RATE, 6),
					"by_model": by_model,
					"by_provider": by_provider,
				}
			except Exception as exc:
				_logger.error("[ERRO] get_cost_breakdown: %s", exc)
				return empty

	def get_model_reliability(
		self, provider: str, model_id: str, step_type: str | None = None, last_n: int = 100,
	) -> dict:
		"""
		2.0.0: confiabilidade OBSERVADA de um modelo especifico, baseada nos
		ultimos `last_n` registros de step_metrics (model_id/provider). Usado
		por ai/model_router.py como um dos 4 componentes de pontuacao
		(qualidade documentada, custo, velocidade, confiabilidade observada)
		-- mesmo padrao de C:\\agentic (outro projeto do Felipe), onde
		evidencia observada refina a ordenacao entre candidatos ja elegiveis,
		nunca decide sozinha se um modelo pode ser usado.

		Retorna {"attempts": int, "successes": int, "success_rate": float,
		"avg_latency_ms": float}. attempts=0 quando nao ha dados ainda --
		quem consome trata isso como "sem evidencia", nao como falha.
		"""
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return {"attempts": 0, "successes": 0, "success_rate": 0.0, "avg_latency_ms": 0.0}
			try:
				all_docs = self._db.table("step_metrics").all()
				matching = [
					d for d in all_docs
					if d.get("model_id") == model_id and d.get("provider") == provider
					and (step_type is None or d.get("step_type") == step_type)
				]
				recent = sorted(matching, key=lambda d: d.doc_id, reverse=True)[:last_n]
				attempts = len(recent)
				if attempts == 0:
					return {"attempts": 0, "successes": 0, "success_rate": 0.0, "avg_latency_ms": 0.0}
				successes = sum(int(d.get("success", 0)) for d in recent)
				avg_latency = sum(d.get("latency_ms", 0) for d in recent) / attempts
				return {
					"attempts": attempts,
					"successes": successes,
					"success_rate": round(successes / attempts, 3),
					"avg_latency_ms": round(avg_latency, 1),
				}
			except Exception as exc:
				_logger.error("[ERRO] get_model_reliability: %s", exc)
				return {"attempts": 0, "successes": 0, "success_rate": 0.0, "avg_latency_ms": 0.0}

	# ------------------------------------------------------------------
	# Chat persistence cross-session (Gap B — memory-systems Layer 3)
	# ------------------------------------------------------------------

	def save_chat_snippet(self, addon_name: str, messages: list[dict]) -> None:
		"""
		Persiste as ultimas 5 mensagens do chat na tabela 'chat_snippets'.
		Permite que proximas sessoes recuperem o contexto de conversas anteriores
		para o mesmo addon (Layer 3 long-term memory — skill: memory-systems).

		messages: lista de {'role': 'user'|'assistant', 'text': str}
		Regra 9: armazena apenas texto inerte, nunca executa conteudo.
		"""
		if not messages or not addon_name:
			return
		snippet = [
			{"role": m.get("role", "")[:20], "text": m.get("text", "")[:2000]}
			for m in messages[-5:]
		]
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return
			try:
				self._db.table("chat_snippets").insert({
					"created_at": datetime.now().isoformat(timespec="seconds"),
					"addon_name": addon_name[:100],
					"messages":   snippet,
				})
			except Exception as exc:
				_logger.warning("[AVISO] save_chat_snippet: %s", exc)

	def get_last_chat(self, addon_name: str) -> list[dict]:
		"""
		Recupera as mensagens do chat mais recente para o addon informado.
		Retorna lista de {'role', 'text'} ou [] se sem registro.

		skill: memory-systems (Layer 3: Long-term memory — cross-session context).
		"""
		if not addon_name:
			return []
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return []
			try:
				all_docs = self._db.table("chat_snippets").all()
				matching = [
					d for d in all_docs
					if d.get("addon_name", "") == addon_name
				]
				if not matching:
					return []
				# Mais recente = maior doc_id
				latest = max(matching, key=lambda d: d.doc_id)
				return latest.get("messages", [])
			except Exception as exc:
				_logger.error("[ERRO] get_last_chat: %s", exc)
				return []

	# ------------------------------------------------------------------
	# Dep failures — aprendizado adaptativo de dependencias (v2.8.0)
	# ------------------------------------------------------------------

	def log_dep_failure(self, pkg: str, reason: str, addon_name: str = "") -> None:
		"""
		Registra falha de instalacao de dependencia.

		Chamado pelo bundle_addon_dependencies quando PyPI retorna 404
		(possivel alucinacao do LLM) ou quando pip falha por razao semantica.
		O code_generator consulta esse historico e injeta como contexto
		para o LLM evitar semanticamente dependencias que ja falharam.

		Zero keywords — raciocinio semantico puro do modelo.
		Regra 9: apenas armazena texto inerte, nunca executa.
		"""
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return
			try:
				self._db.table("dep_failures").insert({
					"created_at": datetime.now().isoformat(timespec="seconds"),
					"pkg":        pkg[:100],
					"reason":     reason[:200],
					"addon_name": addon_name[:100],
				})
				_logger.info("[OK] dep_failure registrada: pkg=%s reason=%s", pkg, reason)
			except Exception as exc:
				_logger.warning("[AVISO] log_dep_failure: %s", exc)

	def get_dep_failures(self, limit: int = 10) -> list[dict]:
		"""
		Retorna lista de {pkg, reason} dos pacotes que falharam mais recentemente.

		Usado pelo code_generator para injetar contexto semantico no prompt:
		o LLM recebe a lista e decide semanticamente quais dependencias evitar.
		Mais recentes primeiro — as falhas mais proximas sao mais relevantes.
		Regra 9: apenas leitura, nunca executa conteudo armazenado.
		"""
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return []
			try:
				all_docs = self._db.table("dep_failures").all()
				sorted_docs = sorted(all_docs, key=lambda d: d.doc_id, reverse=True)
				return [
					{"pkg": d["pkg"], "reason": d.get("reason", "")}
					for d in sorted_docs[:limit]
				]
			except Exception as exc:
				_logger.error("[ERRO] get_dep_failures: %s", exc)
				return []

	# ------------------------------------------------------------------
	# Web knowledge — aprendizado via pesquisa web (v2.9.0)
	# ------------------------------------------------------------------

	_MAX_WEB_KNOWLEDGE: int = 500

	def save_web_knowledge(
		self,
		topic: str,
		content: str,
		source_url: str = "",
		year: int = 0,
	) -> None:
		"""
		Persiste conhecimento adquirido via pesquisa web — upsert por topic.

		Se ja existe um registro recente (dentro de _CACHE_MAX_AGE_DAYS) para o
		mesmo topic, ATUALIZA o registro existente em vez de inserir novo.
		Evita acumulo ilimitado de entradas duplicadas para o mesmo assunto.

		topic: chave de busca (query normalizada ou nome de pacote)
		content: texto aprendido — sinopse do resultado da pesquisa
		source_url: URL da fonte principal (opcional)
		year: ano do conteudo encontrado (0 = desconhecido)

		Zero keywords — raciocinio semantico puro do modelo.
		Regra 9: apenas armazena texto inerte, nunca executa.
		"""
		if not topic or not content:
			return
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return
			try:
				table = self._db.table("web_knowledge")
				Q = Query()
				# Verifica se ja existe registro para o mesmo topic
				existing = table.search(Q.topic == topic[:200])
				if existing:
					# Upsert: atualiza o registro mais recente
					latest = max(existing, key=lambda d: d.doc_id)
					table.update(
						{
							"content":    content[:2000],
							"source_url": source_url[:300],
							"year":       year,
							"created_at": datetime.now().isoformat(timespec="seconds"),
						},
						doc_ids=[latest.doc_id],
					)
					# Remove duplicatas mais antigas se houver mais de 1
					if len(existing) > 1:
						old_ids = [d.doc_id for d in existing if d.doc_id != latest.doc_id]
						table.remove(doc_ids=old_ids)
					_logger.info("[OK] web_knowledge atualizada (upsert): topic=%s", topic[:60])
				else:
					table.insert({
						"created_at": datetime.now().isoformat(timespec="seconds"),
						"topic":      topic[:200],
						"content":    content[:2000],
						"source_url": source_url[:300],
						"year":       year,
					})
					_logger.info("[OK] web_knowledge salva: topic=%s", topic[:60])
					# Prune automatico
					try:
						count = len(table.all())
						if count > 0 and count % _PRUNE_INTERVAL == 0:
							self._prune_if_needed("web_knowledge", self._MAX_WEB_KNOWLEDGE)
					except Exception as exc:
						_logger.debug("[DEBUG] Prune automatico falhou: %s", exc)
			except Exception as exc:
				_logger.warning("[AVISO] save_web_knowledge: %s", exc)

	def get_web_knowledge(
		self,
		topic: str,
		max_age_days: int = 30,
	) -> list[dict]:
		"""
		Retorna conhecimento salvo sobre um topico, dentro do prazo max_age_days.

		Prioriza a identidade exata do topico de cache e, se necessario,
		usa selecao semantica pelo modelo leve configurado.
		Regra 9: apenas leitura, nunca executa conteudo armazenado.
		"""
		if not topic:
			return []
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return []
			try:
				cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat(
					timespec="seconds"
				)
				all_docs = self._db.table("web_knowledge").all()
				exact = []
				candidates = []
				for doc in all_docs:
					if doc.get("created_at", "") < cutoff:
						continue
					if doc.get("topic", "").strip().casefold() == topic.strip().casefold():
						exact.append(doc)
					text = f"{doc.get('topic', '')} {doc.get('content', '')}"
					candidates.append((text, doc))
				matching = exact[:5] or rank_relevant(topic, candidates, limit=5)
				return [
					{
						"topic":      d["topic"],
						"content":    d.get("content", ""),
						"source_url": d.get("source_url", ""),
						"year":       d.get("year", 0),
					}
					for d in matching[:5]
				]
			except Exception as exc:
				_logger.error("[ERRO] get_web_knowledge: %s", exc)
				return []

	def get_similar_sessions(self, query: str, limit: int = 3) -> list[dict]:
		"""
		Retorna sessoes similares a query para aprendizado cross-session.

		Recuperacao por relevancia, sem gatilhos ou substrings fixas.
		Retorna apenas sessoes que falharam (success=False) para aprender com erros.
		"""
		if not query:
			return []
		with self._lock:
			self._init_db()
			if not self._ready or self._db is None:
				return []
			try:
				from tinydb import Query
				Session = Query()
				sessions = self._db.table("sessions")
				# Session e um TinyDB Query() -- == constroi uma condicao de busca,
				# nao uma comparacao booleana Python; "not Session.success" teria
				# semantica diferente na DSL do TinyDB.
				all_docs = sessions.search(Session.success == False)  # noqa: E712
				# BUGFIX (achado de auditoria full-stack 2026-08-04): lia
				# doc.get("issues", []) -- essa chave NUNCA e escrita por
				# save_session() (grava "step_issues", uma STRING unica
				# "; ".join(...), nao uma lista sob "issues"). Retornava []
				# sempre; CONSULT_MEMORY (agentic_loop.py) rodava sem erro,
				# logava "N sessoes similares encontradas" mas nunca injetava
				# nenhuma licao real na query retentada -- degradava pra no-op
				# silencioso. Le o campo certo e reconstroi a lista pro
				# contrato que os chamadores (_enhance_query_with_memory)
				# esperam (issues[0]).
				candidates = [
					(f"{doc.get('query', '')} {doc.get('step_issues', '')}", doc)
					for doc in all_docs
				]
				matching = rank_relevant(query, candidates, limit=limit)
				return [
					{
						"query": doc.get("query", ""),
						"issues": [i for i in doc.get("step_issues", "").split("; ") if i],
						"success": doc.get("success", False),
						"created_at": doc.get("created_at", ""),
					}
					for doc in matching[:limit]
				]
			except Exception as exc:
				_logger.error("[ERRO] get_similar_sessions: %s", exc)
				return []


# Instancia global — modulos importam esta instancia
memory = SessionMemory()
