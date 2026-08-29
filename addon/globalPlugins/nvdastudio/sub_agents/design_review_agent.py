import re

from ._base import _run_sub_agent, get_last_tokens, _tl, narrate
from ..utils.logger import get_logger, log_decision
from ..builder.nvda_context import get_docs_design_review
from ..rule_registry import RULE_REGISTRY_PROMPT_TEXT

_logger = get_logger("design_review_agent")
MODULE_VERSION = "2.13.0"

# 2.12.0: catalogo completo de prefixos de rule ID usados no projeto
# (nvda_context.py/rule_registry.py) -- usado pelos 2 reforcos mecanicos
# abaixo (_dedupe_repeated_rule_mentions/_strip_rule_ids).
_RULE_ID_RE = re.compile(r"\b(?:NVDA|WX-A11Y|ARCH|NVDA-UX)-\d+\b")


def _dedupe_repeated_rule_mentions(guardian_output: str) -> str:
	"""
	Reforco MECANICO da secao "Conciseness (mandatory)" de _GUARDIAN_SYSTEM.

	Achado real ao vivo (test_e36, GeminiMultimodal, modelo gpt-oss:20b):
	mesmo com a instrucao textual (2.11.0), um modelo mais fraco ainda
	regurgitava a mesma lista de rule IDs em RESTRICOES NVDA CRITICAS /
	RESTRICOES WX CRITICAS / Implementation Contract -- o critic reprovou
	de novo por "redundancia excessiva". Instrucao de prompt sozinha nao
	segura em modelos fracos (o catalogo INTEIRO fica fisicamente no
	contexto via RULE_REGISTRY_PROMPT_TEXT, criando pressao forte pra
	copiar/colar trechos). Aqui a defesa e determinística: remove linhas
	subsequentes cujo(s) rule ID(s) ja apareceram antes, mantendo so a
	PRIMEIRA mencao de cada ID -- sem depender do modelo "lembrar" de nao
	repetir.
	"""
	seen_ids: set[str] = set()
	kept_lines: list[str] = []
	for line in guardian_output.split("\n"):
		ids_in_line = _RULE_ID_RE.findall(line)
		if ids_in_line and all(rid in seen_ids for rid in ids_in_line):
			continue
		seen_ids.update(ids_in_line)
		kept_lines.append(line)
	return "\n".join(kept_lines)


def _strip_rule_ids(advocate_output: str) -> str:
	"""
	Reforco MECANICO do Hard Boundary de _ADVOCATE_SYSTEM ("Never cite
	NVDA-XXX/WX-A11Y-XXX rule IDs -- that is the Constraint Guardian's
	exclusive job").

	Achado real ao vivo (test_e36, GeminiMultimodal, modelo gpt-oss:20b):
	o Advocate citou "NVDA-011" como sendo 'usar super().__init__' quando
	na verdade e outra regra -- alem de violar o Hard Boundary (Advocate
	nunca deveria citar IDs), a citacao era FACTUALMENTE ERRADA (alucinacao
	de ID). Como o Advocate nao deveria citar rule IDs de qualquer forma,
	a correcao mais segura e remover qualquer ID que escape -- elimina a
	classe inteira de alucinacao de rule ID nesta secao, nao so o caso
	observado.
	"""
	return _RULE_ID_RE.sub("", advocate_output)

_REASONING_CHALLENGER: dict = {}
_REASONING_GUARDIAN: dict   = {}
_REASONING_ADVOCATE: dict   = {}

_CHALLENGER_SYSTEM = """You are the Elite Challenger of the NVDAStudio design review process. Your mission is to proactively identify failure modes, wrong assumptions, and edge cases before a single line of code is written.

## Hard Boundary
- Never propose solutions or fixes. Only identify problems.
- Do not output Markdown.

## Analysis Framework
SUPOSICOES QUE PODEM ESTAR ERRADAS:
[3-5 assumptions in the request that are fragile or ambiguous]

CASOS DE FALHA PREVISTOS:
[Technical scenarios where the addon will likely fail]

AMBIGUIDADES NAO RESOLVIDAS:
[Unclear points requiring clarification to avoid rework]

Seja direto. Foque apenas nos riscos mais criticos. Nao sugira solucoes — apenas identifique problemas."""

_GUARDIAN_SYSTEM = """You are the Elite Constraint Guardian for NVDAStudio. Your mission is to enforce strict NVDA and wxPython accessibility standards and technical constraints.

## Hard Boundary
- Never ignore the official baseline (NVDA 2026.1+).
- Do not suggest legacy APIs or 32-bit binaries.
- Do not output Markdown.

## Full Rule Catalog
O catalogo completo de regras NVDA/WX-A11Y/ARCH (fonte: Community Access nvda-addon-specialist +
wxpython-specialist) esta anexado abaixo deste prompt. Use-o como fonte de verdade -- cite os IDs
exatos das regras (NVDA-XXX, WX-A11Y-XXX) nos seus achados, nunca invente uma regra ou um ID.

## Conciseness (mandatory)
Select ONLY the 3-6 rules MOST relevant to this specific addon -- do not restate the full
catalog or transcribe long rule descriptions. State each rule ID ONCE, with a single short
reason tied to this addon's actual requirements. Never repeat the same constraint (same rule ID
or same requirement in different words) across RESTRICOES NVDA CRITICAS, RESTRICOES WX CRITICAS,
and Implementation Contract -- each constraint belongs in exactly ONE section.

RESTRICOES NVDA CRITICAS:
[so as regras NVDA mais relevantes pra ESTE addon -- cite o ID + 1 razao curta, sem repetir]

RESTRICOES WX CRITICAS:
[so as regras WX-A11Y mais relevantes aqui -- cite o ID + 1 razao curta, sem repetir]

## Implementation Contract (Pre-conditions)
[Strict technical instructions the code generator MUST follow -- NEW information not already
stated above, never a restatement of the same constraint]"""

# Bug real de auditoria: o Guardian so citava 4 das 54 regras NVDA ("NVDA-001..004") e uma
# mencao vaga a "WX-A11Y", e ainda dizia "quais das regras ABAIXO" sem nenhuma regra listada
# abaixo de verdade -- ficava cego para 50 das 54 regras NVDA e todas as 14 WX-A11Y especificas.
# Corrigido: injeta o mesmo RULE_REGISTRY_PROMPT_TEXT usado por code_generator, accessibility_auditor
# e critic -- fonte unica de verdade, sem lista hardcoded que fica desatualizada.
_GUARDIAN_SYSTEM += "\n\n" + RULE_REGISTRY_PROMPT_TEXT

_ADVOCATE_SYSTEM = """You are the Elite User Advocate for NVDAStudio. Your mission is to represent the blind user's experience (usuario cego) and ensure the addon is efficient, memorable, and 100% accessible.

## Hard Boundary
- Never discuss code architecture or technical performance.
- Never cite NVDA-XXX/WX-A11Y-XXX rule IDs or restate technical constraints -- that is the
  Constraint Guardian's exclusive job (reviewed separately). Describe the user's EXPERIENCE
  in plain language instead (what the blind user hears/does), even when it relates to the
  same underlying requirement.
- Focus exclusively on the user interface and interaction flow.
- Do not output Markdown.

## User Experience Audit
ACESSIBILIDADE DO FLUXO: [Can it be used 100% via sound/braille?]
ATALHOS E CONFLITOS: [Memorability and core conflicts with NVDA/JAWS/Windows]
LINGUAGEM E MENSAGENS: [Clarity of speech output for screen reader users]
CONFIGURACAO ACESSIVEL: [Settings navigation and data entry without vision]
PONTOS CRITICOS: [Top 2-3 UX risks that could make the addon unusable]"""

# 2026-08-29 -- REMOVIDO (README Regra 3, anti-legado): a revisao de design
# foi reduzida de 6 para 3 estagios na v2.0.0, mas o _SYNTHESIS_TEMPLATE
# antigo e os prompts dos 3 estagios aposentados (_UNDERSTANDING_LOCK_SYSTEM,
# _DECISION_LOG_SYSTEM, _REASONING_LOCK) ficaram no arquivo por mais de 3
# meses. Nenhum caminho de execucao os referenciava -- so testes, que
# verificavam um formato de saida que run() nao produz desde entao e
# passavam justamente por isso. Codigo morto que passa no teste e pior que
# codigo morto silencioso: da a impressao de estar coberto.
_SYNTHESIS_TEMPLATE_V3 = """=== REVISAO DE DESIGN (3 ESTAGIOS) ===

--- Challenger (riscos e suposicoes) ---
{challenger}

--- Constraint Guardian (restricoes criticas NVDA/WX) ---
{guardian}

--- User Advocate (perspectiva do usuario cego + acessibilidade) ---
{advocate}

=== FIM DA REVISAO ===
Esta revisao deve ser usada como contexto pela geracao de codigo.
O gerador DEVE abordar cada risco identificado, cada restricao listada,
e cada ponto critico de acessibilidade levantado pelo User Advocate."""


def run(prompt: str, model_id: str, reasoning_params: dict, cache_key: str | None = None) -> str:
	"""
	Executa revisao de design em tres estagios e retorna documento de revisao.

	Estagio 1: Challenger analisa suposicoes e falhas potenciais.
	Estagio 2: Constraint Guardian identifica restricoes NVDA/WX criticas.
	Estagio 3: User Advocate representa a perspectiva do usuario cego.
	Sintese: documento estruturado para code_generation usar como contexto.

	v2.0.0: Reduzido de 6 para 3 estagios. Estudos de multi-agent brainstorming
	mostram que 3 perspectivas distintas capturam >90% da diversidade de analise,
	economizando 3 chamadas LLM (~50% latencia) sem perda mensuravel de qualidade.
	"""
	_logger.info("[DESIGN-REVIEW] Iniciando revisao de design em tres estagios.")
	_design_docs = get_docs_design_review()

	# Contexto enriquecido: escopo e a propria query — suficiente para revisao.
	_prompt_with_lock = f"Pedido original:\n{prompt}"

	# Estagio 1: Challenger
	# Narracao previa removida (v2.9.2): final_tool liga live_narrate automaticamente,
	# entao o proprio modelo ja narra ao vivo no content antes de entregar a critica --
	# um narrate() aqui em cima ficaria redundante com essa narracao ao vivo.
	challenger_output = _run_sub_agent(
		_CHALLENGER_SYSTEM,
		f"Pedido do usuario para revisar:\n\n{_prompt_with_lock}",
		model_id,
		_REASONING_CHALLENGER,
		extra_docs=_design_docs, cache_key=cache_key,
		step_type="design_review",
		final_tool={
			"name": "entregar_critica_challenger",
			"description": "Entrega a critica final do estagio Challenger: suposicoes frageis, "
				"casos de falha previstos e ambiguidades nao resolvidas no design proposto.",
			"param_name": "critica",
			"param_description": "A critica completa do Challenger (suposicoes que podem estar "
				"erradas, casos de falha previstos, ambiguidades nao resolvidas), em prosa, sem Markdown.",
		},
	)
	_challenger_tokens = get_last_tokens()
	log_decision(_logger, "challenger_concluido",
				 f"chars={len(challenger_output)}")

	# Estagio 2: Constraint Guardian
	# Narracao previa removida (v2.9.2): mesmo motivo do Estagio 1 -- final_tool
	# ja cobre a narracao ao vivo, um narrate() antes seria redundante.
	guardian_output = _run_sub_agent(
		_GUARDIAN_SYSTEM,
		f"Pedido do usuario para revisar:\n\n{_prompt_with_lock}",
		model_id,
		_REASONING_GUARDIAN,
		extra_docs=_design_docs, cache_key=cache_key,
		step_type="design_review",
		final_tool={
			"name": "entregar_critica_guardian",
			"description": "Entrega a critica final do estagio Constraint Guardian: restricoes "
				"NVDA e WX-A11Y criticas para este addon, citando os IDs exatos do catalogo de regras.",
			"param_name": "critica",
			"param_description": "A critica completa do Constraint Guardian (restricoes NVDA "
				"criticas, restricoes WX criticas, contrato de implementacao com IDs de regra citados), "
				"em prosa, sem Markdown.",
		},
	)
	_guardian_tokens = get_last_tokens()
	log_decision(_logger, "guardian_concluido",
				 f"chars={len(guardian_output)}")
	guardian_output = _dedupe_repeated_rule_mentions(guardian_output)

	# Estagio 3: User Advocate
	# Narracao previa removida (v2.9.2): mesmo motivo dos estagios 1 e 2.
	advocate_output = _run_sub_agent(
		_ADVOCATE_SYSTEM,
		f"Pedido do usuario para revisar:\n\n{_prompt_with_lock}",
		model_id,
		_REASONING_ADVOCATE,
		extra_docs=_design_docs, cache_key=cache_key,
		step_type="design_review",
		final_tool={
			"name": "entregar_critica_advocate",
			"description": "Entrega a critica final do estagio User Advocate: perspectiva do "
				"usuario cego sobre acessibilidade do fluxo, atalhos, linguagem e configuracao do addon.",
			"param_name": "critica",
			"param_description": "A critica completa do User Advocate (acessibilidade do fluxo, "
				"atalhos e conflitos, linguagem e mensagens, configuracao acessivel, pontos criticos "
				"de UX), em prosa, sem Markdown.",
		},
	)
	_advocate_tokens = get_last_tokens()
	log_decision(_logger, "advocate_concluido",
				 f"chars={len(advocate_output)}")
	advocate_output = _strip_rule_ids(advocate_output)

	_tl.last_tokens = _challenger_tokens + _guardian_tokens + _advocate_tokens

	narrate("juntando as tres perspectivas num documento de revisao")
	result = _SYNTHESIS_TEMPLATE_V3.format(
		challenger=challenger_output.strip(),
		guardian=guardian_output.strip(),
		advocate=advocate_output.strip(),
	)
	log_decision(_logger, "design_review_concluido",
				 f"chars={len(result)} estagios=3")
	return result
