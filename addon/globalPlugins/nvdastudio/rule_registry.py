from dataclasses import dataclass
from collections.abc import Iterable

from .builder.nvda_context import (
	ARCH_RULE_IDS,
	NVDA_DETECTION_RULES,
	WX_A11Y_RULES,
	DTK_A11Y_RULES,
	RULE_FALLBACK_MATRIX,
)

MODULE_VERSION = "1.3.0"
UPDATED_AT = "2026-08-17"

COMMUNITY_ACCESS_SOURCES: tuple[str, ...] = (
	"https://community-access.org/",
	"https://github.com/Community-Access/accessibility-agents",
)


@dataclass(frozen=True)
class RuleContract:
	rule_id: str
	family: str
	severity: str
	description: str
	source: str
	owner_agents: tuple[str, ...]
	required_surfaces: tuple[str, ...]
	callbacks: tuple[str, ...]
	fallback_mode: str
	fallback_note: str
	status: str = "active"
	alias_for: str | None = None


ARCH_DESCRIPTIONS: dict[str, tuple[str, str]] = {
	"ARCH-001": ("Serio", "Addon com API externa sem SettingsPanel para credenciais e opcoes."),
	"ARCH-002": ("Critico", "I/O pesado, rede ou processamento longo sem thread/background worker."),
	# ARCH-004/005: corrigido 2026-08-03 -- as descricoes aqui estavam
	# deslocadas em relacao ao topico real de cada ID (ARCH-004 aqui descrevia
	# config.conf.spec, que e o topico real de ARCH-005; o texto real de
	# ARCH-004 -- logica de API misturada no __init__.py -- estava ausente).
	# Confirmado contra AMBOS planner.py::_PLAN_SYSTEM_PROMPT e
	# ai/critic.py::_CRITIC_QUALITY_SYSTEM, que ja concordavam um com o outro
	# nesses 2 IDs (so este arquivo estava desalinhado). O texto orfao da
	# ARCH-005 antiga ("dependencia externa sem estrategia de bundle") foi
	# descartado -- bundling de dependencia ja e tratado deterministicamente
	# por builder/addon_builder.py::bundle_addon_dependencies(), nunca foi
	# uma regra de prompt em nenhum dos 3 arquivos.
	"ARCH-003": ("Serio", "AppModule vs GlobalPlugin -- orientacao incorreta para o tipo de addon (app-especifico deve usar AppModule, nao GlobalPlugin)."),
	"ARCH-004": ("Moderado", "Logica de API ou dominio misturada diretamente no __init__.py do plugin, sem arquivo de servico separado."),
	"ARCH-005": ("Serio", "Configuracao persistente sem config.conf.spec e defaults claros."),
	"ARCH-006": ("Serio", "Extension points sem padrao register/unregister completo ou assinatura incorreta (Action/Filter/Decider/Chain)."),
	"ARCH-007": ("Moderado", "Addon com 3 ou mais features/servicos substanciais organizados como arquivos soltos genericos em vez de subpacotes nomeados pela funcionalidade."),
	"ARCH-008": ("Serio", "Addon com 2+ funcionalidades distintas sem ponto de entrada acessivel definido (menu Ferramentas e/ou SettingsPanel)."),
	"ARCH-009": ("Serio", "Addon com wx.Dialog/wx.Frame como interface principal sem decisao explicita sobre item de menu Ferramentas vs SettingsPanel."),
}

# NOTA DE GOVERNANCA (2026-08-03, achado de auditoria -- RESOLVIDO em
# 2026-08-04, ver planner.py 2.19.0 e nvda_context.py 3.28.0): existia uma
# colisao real de numeracao -- planner.py::_PLAN_SYSTEM_PROMPT definia
# ARCH-003 ("multiplas funcionalidades -> ponto de entrada no menu
# Ferramentas/SettingsPanel") e ARCH-006 ("menu Ferramentas pra addon com
# dialog") com topicos DIFERENTES dos que ai/critic.py e
# builder/nvda_context.py ja usavam pros MESMOS IDs (AppModule vs
# GlobalPlugin / Extension points). Resolvido renumerando os topicos de
# planner.py pra ARCH-008/ARCH-009 (proximos IDs livres apos ARCH-007) --
# os topicos em si nao mudaram, so o numero; entradas acima ja refletem a
# numeracao final.

NVDA_UX_RULES: tuple[tuple[str, str, str], ...] = (
	("NVDA-UX-001", "Critico", "Mudanca visual de estado sem ui.message() ou feedback equivalente."),
	("NVDA-UX-002", "Serio", "Script, botao ou menu executa acao sem retorno auditivo ao usuario."),
	("NVDA-UX-003", "Serio", "Fluxo principal nao e concluivel apenas com teclado e fala do NVDA."),
)

DEPRECATED_ALIASES: tuple[RuleContract, ...] = (
	RuleContract(
		rule_id="NVDA-041",
		family="NVDA",
		severity="Deprecated",
		description="Alias historico para sleepMode em apps self-voicing; usar NVDA-034.",
		source="NVDAStudio legacy tests",
		owner_agents=("code_generator", "accessibility_auditor", "critic"),
		required_surfaces=("tests", "docs"),
		callbacks=("alias_resolution", "targeted_fix"),
		fallback_mode="ALIAS",
		fallback_note="Resolver para NVDA-034; nao criar regra ativa duplicada.",
		status="deprecated_alias",
		alias_for="NVDA-034",
	),
)


def _fallback(rule_id: str) -> tuple[str, str]:
	return RULE_FALLBACK_MATRIX.get(
		rule_id,
		("STRICT_ONLY", "Sem fallback: corrigir exatamente a violacao da regra."),
	)


def _contract(
	rule_id: str,
	family: str,
	severity: str,
	description: str,
	source: str,
	owner_agents: Iterable[str],
	required_surfaces: Iterable[str],
) -> RuleContract:
	mode, note = _fallback(rule_id)
	return RuleContract(
		rule_id=rule_id,
		family=family,
		severity=severity,
		description=description,
		source=source,
		owner_agents=tuple(owner_agents),
		required_surfaces=tuple(required_surfaces),
		callbacks=(
			"prompt_gate",
			"static_audit",
			"quality_critic",
			"targeted_fix",
			"checkpoint_report",
		),
		fallback_mode=mode,
		fallback_note=note,
	)


def _build_registry() -> dict[str, RuleContract]:
	registry: dict[str, RuleContract] = {}

	for rule_id, severity, description in NVDA_DETECTION_RULES:
		registry[rule_id] = _contract(
			rule_id,
			"NVDA",
			severity,
			description,
			"NVDA source, NVDA add-on developer guide, Community Access nvda-addon-specialist",
			("code_generator", "accessibility_auditor", "critic", "addon_builder"),
			("nvda_context", "code_generator", "accessibility_auditor", "critic", "tests", "docs"),
		)

	for rule_id, severity, description in WX_A11Y_RULES:
		registry[rule_id] = _contract(
			rule_id,
			"WX-A11Y",
			severity,
			description,
			"Community Access wxpython-specialist and wxPython accessibility patterns",
			("code_generator", "accessibility_auditor", "critic", "addon_builder"),
			("nvda_context", "code_generator", "accessibility_auditor", "critic", "tests", "docs"),
		)

	for rule_id, severity, description in DTK_A11Y_RULES:
		registry[rule_id] = _contract(
			rule_id,
			"DTK-A11Y",
			severity,
			description,
			"Community Access desktop-a11y-specialist -- platform accessibility API layer (UIA/MSAA), complementar a WX-A11Y",
			("code_generator", "accessibility_auditor", "critic"),
			("nvda_context", "code_generator", "accessibility_auditor", "critic", "tests", "docs"),
		)

	for rule_id in ARCH_RULE_IDS:
		severity, description = ARCH_DESCRIPTIONS[rule_id]
		registry[rule_id] = _contract(
			rule_id,
			"ARCH",
			severity,
			description,
			"NVDAStudio planner/design-review rules cross-checked with Community Access coordinator-worker model",
			("planner", "design_review_agent", "critic", "orchestrator"),
			("planner", "design_review_agent", "critic", "tests", "docs"),
		)

	for rule_id, severity, description in NVDA_UX_RULES:
		registry[rule_id] = _contract(
			rule_id,
			"NVDA-UX",
			severity,
			description,
			"NVDA screen reader testing checklist and Community Access screen-reader guidance",
			("accessibility_auditor", "critic", "doc_generator"),
			("accessibility_auditor", "critic", "tests", "docs"),
		)

	for alias in DEPRECATED_ALIASES:
		registry[alias.rule_id] = alias

	return dict(sorted(registry.items()))


RULE_REGISTRY: dict[str, RuleContract] = _build_registry()


def active_rule_ids() -> list[str]:
	return [rid for rid, rule in RULE_REGISTRY.items() if rule.status == "active"]


def active_rules() -> list[RuleContract]:
	return [RULE_REGISTRY[rid] for rid in active_rule_ids()]


def format_rule_registry_prompt() -> str:
	lines = [
		"REGISTRO CENTRAL DE REGRAS NVDASTUDIO:",
		"Use estes IDs como contrato obrigatorio. Se uma regra se aplica, reporte o ID e corrija sem inventar fallback.",
		"Callbacks de ciclo de vida: prompt_gate -> static_audit -> quality_critic -> targeted_fix -> checkpoint_report.",
	]
	for rule in active_rules():
		lines.append(
			f"{rule.rule_id} [{rule.family}/{rule.severity}] {rule.description} "
			f"| fallback={rule.fallback_mode}"
		)
	for alias in DEPRECATED_ALIASES:
		lines.append(f"{alias.rule_id} [DEPRECATED] alias de {alias.alias_for}: {alias.fallback_note}")
	return "\n".join(lines)


RULE_REGISTRY_PROMPT_TEXT = format_rule_registry_prompt()
