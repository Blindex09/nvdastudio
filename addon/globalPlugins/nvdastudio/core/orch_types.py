from dataclasses import dataclass, field
from enum import Enum, auto


# ---------------------------------------------------------------------------
# Tipos base (existentes)
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
	step_id: str
	step_type: str
	output: str
	approved: bool
	score: int
	issues: list[str] = field(default_factory=list)
	retries_used: int = 0
	model_used: str = ""
	model_id: str = ""  # Alias para model_used (compatibilidade)
	tokens_used: int = 0
	execution_time_ms: int = 0

	def __post_init__(self) -> None:
		# 2.1.0: achado real de auditoria de integracao (2026-08-09) --
		# model_id era documentado como alias de model_used, mas NENHUMA
		# das 12+ construcoes de StepResult(...) em orchestrator.py setava
		# model_id, e o dataclass nao tinha sync nenhum (diferente de
		# ExecutionStep, que ja sincroniza depends_on/dependencies em
		# __post_init__). orchestrator.py:1630 le step_results[-1].model_id
		# SEM fallback pra reportar final_model_used ao evaluation_framework
		# -- ficava sempre "" silenciosamente, quebrando o rastreamento de
		# regressao por modelo. Mesmo padrao de sync do ExecutionStep,
		# aplicado aqui.
		if not self.model_id and self.model_used:
			self.model_id = self.model_used
		elif not self.model_used and self.model_id:
			self.model_used = self.model_id


@dataclass
class OrchestrationResult:
	plan_id: str
	query: str
	step_results: list[StepResult]
	final_output: str
	success: bool
	total_retries: int = 0
	error: str | None = None
	dependencies: list[str] = field(default_factory=list)
	assembly_output: str = ""
	all_issues: list[str] = field(default_factory=list)
	total_tokens: int = 0
	# Consumo REAL medido pelo circuit breaker, que inclui os steps
	# descartados por replanejamento -- `total_tokens` soma apenas os
	# step_results que sobreviveram. Medido em 2026-09-01 nas duas execucoes
	# que morreram por teto: medidor 1.181.971 contra relatorio 1.041.202, e
	# medidor 1.207.312 contra relatorio 707.841. A diferenca ficava
	# invisivel, e o teto de orcamento acabou calibrado na regua menor.
	total_tokens_medidor: int = 0
	tokens_by_model: dict[str, tuple[int, int]] = field(default_factory=dict)
	estimated_cost_usd: float = 0.0
	replan_count: int = 0
	# Espelha ExecutionPlan.planejamento_degradado: o plano veio do caminho
	# sem json_schema estrito. Nao e falha -- as injecoes deterministicas
	# garantem os steps essenciais -- mas explica variacao de FORMA do plano
	# entre rodadas do MESMO pedido, que sem isso parece aleatoria.
	planejamento_degradado: bool = False
	autonomous_loop_count: int = 0
	completed_message: str = ""
	# 5.50.0: propagado do plano ("addon" default, "controller_client") --
	# studio_dialog.py usa pra saber se deve exigir manifest.ini ao validar
	# o resultado final (controller_client nunca gera manifest.ini).
	project_type: str = "addon"


# ---------------------------------------------------------------------------
# v2.0.0: Pipeline Conversacional
# ---------------------------------------------------------------------------

class PipelinePhase(Enum):
	"""Fases do pipeline conversacional — o usuario ve e interage em cada uma."""
	CONVERSATION   = auto()  # Entendendo o que o usuario quer (clarificacao)
	RESEARCH       = auto()  # Pesquisando dominio, APIs, boas praticas
	PLANNING       = auto()  # Montando o plano de implementacao
	PLAN_APPROVAL  = auto()  # Mostrando o plano e aguardando aprovacao
	EXECUTING      = auto()  # Implementando (com checkpoints)
	REVIEW         = auto()  # Mostrando resultado final
	DONE           = auto()  # Pipeline concluido


class ConversationState(Enum):
	"""Estado da conversa com o usuario durante o pipeline."""
	IDLE               = auto()  # Aguardando input inicial
	CLARIFYING         = auto()  # Fazendo perguntas para entender melhor
	SHOWING_RESEARCH   = auto()  # Mostrando resultados da pesquisa
	SHOWING_PLAN       = auto()  # Mostrando plano para aprovacao
	AWAITING_APPROVAL  = auto()  # Aguardando usuario aprovar/rejeitar/modificar
	EXECUTING_STEP     = auto()  # Executando um step (explica o que esta fazendo)
	STEP_DONE          = auto()  # Step concluido (pergunta se continua)
	SHOWING_RESULT     = auto()  # Mostrando resultado final
	ERROR              = auto()  # Algo deu errado


@dataclass
class DomainContext:
	"""Contexto do dominio do addon — pesquisado antes de planejar."""
	domain: str                          # ex: "email", "clima", "audio", "braille"
	description: str                     # Descricao em linguagem natural do dominio
	apis_involved: list[str]             # APIs relevantes (ex: ["Gmail API", "OAuth2"])
	best_practices: list[str]            # Boas praticas especificas do dominio
	security_requirements: list[str]     # Requisitos de seguranca (ex: ["OAuth2", "API key em env"])
	architecture_patterns: list[str]     # Padroes arquiteturais recomendados
	nvda_specific_notes: list[str]       # Notas especificas para NVDA neste dominio
	research_sources: list[str]          # Fontes consultadas (URLs ou referencias)
	raw_research: str = ""               # Texto bruto da pesquisa


@dataclass
class PlanApproval:
	"""Resultado da aprovacao do plano pelo usuario."""
	approved: bool
	modifications: str = ""              # Mudancas solicitadas pelo usuario
	user_feedback: str = ""              # Feedback geral do usuario


@dataclass
class CheckpointResult:
	"""Resultado de um checkpoint durante a execucao."""
	phase: PipelinePhase
	step_id: str
	step_type: str
	summary: str                         # Resumo do que foi feito
	should_continue: bool                # Usuario quer continuar?
	user_feedback: str = ""              # Feedback do usuario neste checkpoint


# Thresholds de progresso (tunados para nao enganar nem desistir cedo demais)
_PROGRESS_MIN_APPROVED_DELTA = 1
_PROGRESS_MIN_ISSUES_DELTA = 2
_PROGRESS_MIN_OUTPUT_LEN_DELTA = 50
_PROGRESS_SCORE_MIN = 15


def compute_progress(
	prev: OrchestrationResult | None, curr: OrchestrationResult,
) -> tuple[float, str]:
	"""
	Compara duas tentativas consecutivas e retorna (score 0-100, razao).

	Score > _PROGRESS_SCORE_MIN = progresso real detectado.
	Score = 0 = estagnacao (mesmos erros, mesmo output).
	"""
	if prev is None:
		return 100.0, "primeira tentativa"

	score = 0.0
	reasons: list[str] = []

	# 1. Steps aprovados
	prev_approved = sum(1 for r in prev.step_results if r.approved)
	curr_approved = sum(1 for r in curr.step_results if r.approved)
	# O threshold estava declarado no bloco acima e a condicao era `>` hardcoded
	# -- com o valor 1 os dois sao equivalentes, entao o comportamento sempre
	# esteve certo, mas o "botao" nao estava ligado no fio: tunar a constante
	# para 2 nao teria efeito nenhum, apesar do comentario dizer "tunados".
	# Achado na varredura de mecanismos orfaos de 2026-08-30.
	if curr_approved - prev_approved >= _PROGRESS_MIN_APPROVED_DELTA:
		score += 40.0
		reasons.append(f"+{curr_approved - prev_approved} aprovado(s)")
	elif curr_approved < prev_approved:
		score -= 20.0
		reasons.append(f"-{prev_approved - curr_approved} aprovado(s)")

	# 2. Issues (erros)
	prev_issues = len(prev.all_issues)
	curr_issues = len(curr.all_issues)
	if curr_issues < prev_issues:
		reduction = prev_issues - curr_issues
		if reduction >= _PROGRESS_MIN_ISSUES_DELTA:
			score += 30.0
			reasons.append(f"-{reduction} issues")
		else:
			score += 10.0
			reasons.append(f"-{reduction} issues (pequeno)")
	elif curr_issues > prev_issues:
		score -= 15.0
		reasons.append(f"+{curr_issues - prev_issues} issues (piorou)")

	# 3. Tamanho do output final
	prev_len = len(prev.final_output)
	curr_len = len(curr.final_output)
	if curr_len > prev_len + _PROGRESS_MIN_OUTPUT_LEN_DELTA:
		score += 20.0
		reasons.append(f"+{curr_len - prev_len} chars output")
	elif curr_len < prev_len - _PROGRESS_MIN_OUTPUT_LEN_DELTA:
		score -= 10.0
		reasons.append(f"-{prev_len - curr_len} chars output")

	# 4. Total retries
	if curr.total_retries < prev.total_retries:
		score += 10.0
		reasons.append(f"-{prev.total_retries - curr.total_retries} retries")
	elif curr.total_retries > prev.total_retries:
		score -= 5.0
		reasons.append(f"+{curr.total_retries - prev.total_retries} retries")

	# Bonus: se ainda nao atingiu score minimo mas curta distance de issues
	# (ex: issues diferentes — nao os mesmos erros copiados)
	if score < _PROGRESS_SCORE_MIN and curr_issues > 0 and prev_issues > 0:
		# Verifica se issues sao diferentes (novos erros = aprendizado)
		prev_set = set(i[:40] for i in prev.all_issues)
		curr_set = set(i[:40] for i in curr.all_issues)
		if curr_set != prev_set and len(curr_set - prev_set) > 0:
			score += 10.0
			reasons.append("novos erros (nao repeticao)")

	reason = "; ".join(reasons) if reasons else "estagnacao"
	return score, reason
