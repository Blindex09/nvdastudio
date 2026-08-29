"""
Revisor de ENGENHARIA do codigo gerado.

Lacuna real que este agente fecha (auditoria 2026-08-29): todo o julgamento
de qualidade do NVDAStudio era conformidade a REGRA -- as ~50 regras
NVDA-xxx/WX-A11Y/ARCH do rule_registry, fiscalizadas por accessibility_auditor,
critic e design_review_agent. Isso cobre o que e catalogavel, mas engenharia
e justamente o que sobra quando o catalogo acaba: fronteira de modulo errada,
abstracao prematura, erro engolido, estado compartilhado sem dono, codigo
impossivel de testar. Nenhum ID de regra descreve esses defeitos, e nenhum
agente do pipeline os procurava.

DIVISAO DE TRABALHO (evita a duplicacao que a Regra 5 do README proibe):
  - accessibility_auditor -> regras WX-A11Y, interface acessivel.
  - design_review_agent   -> riscos ANTES de codificar, restricoes NVDA/WX.
  - critic                -> conformidade com o spec + rubrica de regras.
  - code_sandbox          -> defeito MECANICO (ruff/mypy/import/pytest).
  - este agente           -> julgamento de ENGENHARIA sobre codigo que ja
                             passou nos degraus baratos acima.

Roda com o modelo LEVE de proposito (README Regra 8: critica e auditoria
usam o leve; so geracao de codigo justifica o topo). Nao gasta do orcamento
de 20% do modelo topo.
"""

from ._base import _run_sub_agent, _tl, get_last_tokens, narrate
from ..builder.nvda_context import get_docs_design_review
from ..utils.engineering_principles import ENGINEERING_REVIEW_PROMPT_TEXT
from ..utils.logger import get_logger, log_decision

MODULE_VERSION = "1.0.0"
_logger = get_logger("engineering_reviewer")

_REASONING: dict = {}

_SYSTEM = """You are the Engineering Reviewer for NVDAStudio. You judge the ENGINEERING of Python code that has already been generated for an NVDA add-on.

## Hard Boundary

- Never rewrite the add-on. You produce a review, never a full implementation.
- Never cite NVDA-XXX, WX-A11Y-XXX or ARCH-XXX rule IDs. Rule conformance is
  audited by other agents (accessibility_auditor and critic) and repeating it
  here is duplicated work, not review. Describe the ENGINEERING defect in plain
  terms instead, even when it overlaps a rule.
- Never report style, formatting, line length or indentation. TABs are this
  project's official style and lint already runs separately.
- Never invent defects to fill a section. An empty section is a valid, useful
  result -- say "nada relevante" and move on.
- Do not output Markdown (no **, no #, no bullet markers). Plain prose only.

## What counts as a finding

A finding must name a CONCRETE consequence: what breaks, when, and for whom.
"Poderia ser mais limpo" is not a finding. "Se a API demorar, a thread de
fala do NVDA trava e o usuario perde o retorno de voz" is a finding.

Prefer FEWER, SHARPER findings. Three real defects beat twelve observations.
If the code is genuinely sound, say so plainly -- approving good code is as
much a part of review as rejecting bad code.

## Review Framework

DEFEITOS DE ENGENHARIA:
[Real defects in structure, error handling, state or lifecycle. For each: what
 is wrong, and the concrete failure it causes. Maximum 4. Empty if none.]

COMPLEXIDADE DESNECESSARIA:
[Abstractions, indirection, configuration or generality the add-on does not
 need. Name what would be deleted and what would replace it. Maximum 2.]

TESTABILIDADE:
[Anything that makes the behaviour impossible to test without the real NVDA
 process, a real network or a real clock -- and the smallest change that would
 make it testable. Maximum 2.]

RISCO DE EVOLUCAO:
[What will break the next time this add-on is changed or the NVDA baseline
 moves. Maximum 2.]

VEREDITO_ENGENHARIA: SOLIDO | AJUSTES_RECOMENDADOS | REESTRUTURAR
[Exactly one of the three, then one sentence justifying it. Use REESTRUTURAR
 only when a defect above makes the add-on unsafe or unmaintainable as written
 -- not for accumulated small suggestions.]"""

# Principios de engenharia destilados dos 3 documentos de metodologia do
# projeto (docs/metodologia-verificacao-arquitetura.md e os dois
# conceitos-ia-*.md). Fonte unica de verdade compartilhada com planner,
# critic e code_generator -- ver utils/engineering_principles.py.
_SYSTEM += "\n\n" + ENGINEERING_REVIEW_PROMPT_TEXT


def run(prompt: str, model_id: str, reasoning_params: dict, cache_key: str | None = None) -> str:
	"""
	Revisa a engenharia do codigo gerado e retorna o documento de revisao.

	Recebe como `prompt` o codigo dos steps de code_generation (montado pelo
	orchestrator via context_from_steps) e devolve prosa estruturada pelo
	Review Framework do _SYSTEM.

	Nao bloqueia o pipeline sozinho: o veredito entra no contexto do assembly
	e na avaliacao do critic. A decisao de CONTEUDO (o que e um defeito) e da
	LLM; a de ROTEAMENTO (quando este step roda) e deterministica, no
	planner -- README Regra 8, nunca inverter isso.
	"""
	_logger.info("[ENG-REVIEW] Revisando engenharia do codigo gerado.")
	narrate("revisando a engenharia do codigo gerado")

	output = _run_sub_agent(
		_SYSTEM,
		f"Codigo gerado para revisar:\n\n{prompt}",
		model_id,
		reasoning_params or _REASONING,
		extra_docs=get_docs_design_review(),
		cache_key=cache_key,
		step_type="engineering_review",
		final_tool={
			"name": "entregar_revisao_engenharia",
			"description": "Entrega a revisao de engenharia do codigo gerado: defeitos de "
				"estrutura, complexidade desnecessaria, testabilidade, risco de evolucao "
				"e o veredito final de engenharia.",
			"param_name": "revisao",
			"param_description": "A revisao completa seguindo o Review Framework "
				"(DEFEITOS DE ENGENHARIA, COMPLEXIDADE DESNECESSARIA, TESTABILIDADE, "
				"RISCO DE EVOLUCAO, VEREDITO_ENGENHARIA), em prosa, sem Markdown.",
		},
	)

	_tl.last_tokens = get_last_tokens()
	log_decision(
		_logger, "engineering_review_concluido",
		f"chars={len(output)} veredito={_extract_verdict(output)}",
	)
	return output


def _extract_verdict(review: str) -> str:
	"""
	Extrai o veredito declarado na revisao, para log e para o orchestrator.

	Deterministico de proposito: o roteamento nunca depende de a LLM
	"decidir" o proximo passo -- so le o campo que ela preencheu. Devolve
	"INDEFINIDO" quando o modelo nao emitiu um veredito reconhecivel, sem
	nunca adivinhar um valor mais favoravel.
	"""
	for line in review.split("\n"):
		if "VEREDITO_ENGENHARIA" not in line:
			continue
		resto = line.split("VEREDITO_ENGENHARIA", 1)[1].lstrip(": ").strip().upper()
		for veredito in ("AJUSTES_RECOMENDADOS", "REESTRUTURAR", "SOLIDO"):
			if resto.startswith(veredito):
				return veredito
	return "INDEFINIDO"
