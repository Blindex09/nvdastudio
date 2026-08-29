import os
import re
from ._base import _run_sub_agent, narrate
from ..utils.logger import get_logger, log_decision
from ..builder.nvda_context import get_docs_agent_template

MODULE_VERSION = "1.5.0"

_logger = get_logger("agent_template_agent")

_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agent_templates")

_SYSTEM = """Voce e o AgentTemplateAgent do NVDAStudio.
Gere um template de agente completo no formato Community Access (community-access.org).

ATENCAO: o template NAO e codigo Python, docstring de modulo, nem descricao
de classe -- e um documento markdown com as secoes exatas listadas abaixo
("# Nome" / "## Descricao" / "## Responsabilidades" / etc.), destinado a ser
lido por humanos, nao executado. Mesmo que o pedido original mencione uma
API de IA especifica (ex: Gemini) que o addon vai usar, este step descreve
o AGENTE em prosa estruturada -- quem escreve o codigo Python de verdade e
o step code_generation, separado deste.

O template final e entregue como argumento de uma ferramenta (instrucao de
entrega mais abaixo) — as regras de formatacao a seguir (TEXTO PURO, sem
blocos de codigo ao redor do template inteiro) valem para o CONTEUDO DESSE
ARGUMENTO, nao para a resposta inteira: voce pode narrar livremente antes de
chamar a ferramenta, mas o template em si, dentro do argumento, segue estas
regras a risca.

TEXTO PURO — sem markdown de cabecalho extra, sem asteriscos soltos.

Estrutura OBRIGATORIA — inclua TODAS as secoes abaixo, nesta ordem:

# [Nome do Agente]
[descricao de uma linha]

## Descricao
[descricao detalhada do agente e seu proposito]

## Responsabilidades
- [responsabilidade 1]
- [responsabilidade 2]

## Regras de Comportamento
- [regra 1]
- [regra 2]

## Entradas
- [o que o agente recebe como input]

## Saidas
- [o que o agente produz como output]

## Invariantes
- [restricao que nunca pode ser violada 1]
- [restricao que nunca pode ser violada 2]

## Referencias
- [link ou recurso relevante 1]
- [link ou recurso relevante 2]

## Versao
1.0.0

## Metadados
name: [nome-do-agente-em-kebab-case]
description: [o-que-o-agente-faz-e-quando-usa-lo — inclua triggers especificos, compativel com YAML frontmatter do skill-creator]

O argumento da ferramenta de entrega deve ser o template em markdown puro,
sem blocos de codigo ao redor do template inteiro."""

# Tool de entrega do resultado final (padrao "final answer as tool call",
# _base.py v1.13.0) -- ver _FINAL_TOOL_INSTRUCTION em _base.py.
_FINAL_TOOL = {
	"name": "entregar_template_agente",
	"description": "Entrega o template final do agente, no formato Community Access.",
	"param_name": "template",
	"param_description": (
		"O template completo do agente em markdown puro, seguindo a "
		"estrutura Community Access (# Nome, ## Descricao, "
		"## Responsabilidades, ## Regras de Comportamento, ## Entradas, "
		"## Saidas, ## Invariantes, ## Referencias, ## Versao, "
		"## Metadados). Sem blocos de codigo ao redor do template inteiro."
	),
}

# Secoes obrigatorias do formato Community Access (Regra 5: verificacao deterministica)
_REQUIRED_SECTIONS: list[tuple[str, str]] = [
	("Descricao",            r"^##\s+Descri[cç][aã]o"),
	("Responsabilidades",    r"^##\s+Responsabilidades"),
	("Regras de Comportamento", r"^##\s+Regras\s+de\s+Comportamento"),
	("Entradas",             r"^##\s+Entradas"),
	("Saidas",               r"^##\s+(Sa[íi]das|Saidas)"),
	("Invariantes",          r"^##\s+Invariantes"),
	("Referencias",          r"^##\s+Refer[eê]ncias"),
	("Versao",               r"^##\s+Vers[aã]o"),
        ("Metadados",            r"^##\s+Metadados"),
]


def _validate_sections(md: str) -> list[str]:
	"""
	Verifica presenca de todas as secoes obrigatorias do formato Community Access.
	Retorna lista de secoes ausentes.
	Regra 5: verificacao deterministica de estrutura.
	"""
	missing = []
	for nome, pattern in _REQUIRED_SECTIONS:
		if not re.search(pattern, md, re.MULTILINE | re.IGNORECASE):
			missing.append(nome)
	return missing


def run(prompt: str, model_id: str, reasoning_params: dict, cache_key: str | None = None) -> str:
	examples = _load_template_examples()
	# Sem narrate() de intencao aqui: com final_tool o proprio modelo narra
	# ao vivo no content, antes de chamar a ferramenta de entrega -- narrar
	# a intencao de novo aqui seria redundante (v1.4.1).
	full_prompt = f"Exemplos de templates existentes para referencia:\n\n{examples}\n\nNova tarefa: {prompt}"
	output = _run_sub_agent(
		_SYSTEM, full_prompt, model_id, reasoning_params,
		extra_docs=get_docs_agent_template(), cache_key=cache_key,
		final_tool=_FINAL_TOOL,
	)

	# Validacao estrutural deterministica — Regra 5
	missing = _validate_sections(output)
	if missing:
		narrate(f"o template ficou faltando {len(missing)} secao(oes): {', '.join(missing[:3])}")
		aviso = (
			"<!-- AVISO DE ESTRUTURA: secoes Community Access ausentes: "
			+ ", ".join(missing)
			+ " — o Critic ira solicitar correcao -->\n\n"
		)
		log_decision(_logger, "agent_template_secoes_ausentes",
					 f"ausentes={missing}")
		return aviso + output

	narrate(f"o template ficou completo, com as {len(_REQUIRED_SECTIONS)} secoes esperadas")
	log_decision(_logger, "agent_template_estrutura_ok",
				 f"todas as {len(_REQUIRED_SECTIONS)} secoes presentes")
	return output


def _load_template_examples() -> str:
	parts = []
	if not os.path.isdir(_TEMPLATES_DIR):
		return ""
	for fname in os.listdir(_TEMPLATES_DIR):
		if fname.endswith(".md"):
			fpath = os.path.join(_TEMPLATES_DIR, fname)
			try:
				with open(fpath, encoding="utf-8") as f:
					parts.append(f"=== {fname} ===\n" + f.read()[:800])
			except OSError:
				pass
	return "\n\n".join(parts)
