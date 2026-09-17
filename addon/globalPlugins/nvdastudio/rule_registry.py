from dataclasses import dataclass

from .builder.nvda_context import (
	ARCH_RULE_IDS,
	DTK_A11Y_RULES,
	NVDA_DETECTION_RULES,
	RULE_FALLBACK_MATRIX,
	WX_A11Y_RULES,
)

MODULE_VERSION = "2.0.0"


@dataclass(frozen=True)
class RuleContract:
	rule_id: str
	family: str
	severity: str
	description: str
	fallback_mode: str
	status: str = "active"
	alias_for: str | None = None


ARCH_DESCRIPTIONS: dict[str, tuple[str, str]] = {
	"ARCH-001": ("Serio", "Addon com API externa sem SettingsPanel para credenciais e opcoes."),
	"ARCH-002": ("Critico", "I/O pesado, rede ou processamento longo sem thread/background worker."),
	"ARCH-003": ("Serio", "AppModule vs GlobalPlugin incorreto para o escopo do addon."),
	"ARCH-004": ("Moderado", "Logica de dominio misturada no ponto de entrada sem servico separado."),
	"ARCH-005": ("Serio", "Configuracao persistente sem config.conf.spec e defaults claros."),
	"ARCH-006": ("Serio", "Extension points sem register/unregister completo ou assinatura correta."),
	"ARCH-007": ("Moderado", "Addon complexo sem subpacotes nomeados pela funcionalidade."),
	"ARCH-008": ("Serio", "Addon multifuncional sem ponto de entrada acessivel."),
	"ARCH-009": ("Serio", "Interface principal sem decisao clara entre menu e SettingsPanel."),
}

NVDA_UX_RULES: tuple[tuple[str, str, str], ...] = (
	("NVDA-UX-001", "Critico", "Mudanca visual de estado sem feedback equivalente pelo NVDA."),
	("NVDA-UX-002", "Serio", "Acao sem retorno auditivo ao usuario."),
	("NVDA-UX-003", "Serio", "Fluxo principal nao concluivel apenas com teclado e fala."),
)


def _contract(rule_id: str, family: str, severity: str, description: str) -> RuleContract:
	mode, _note = RULE_FALLBACK_MATRIX.get(rule_id, ("STRICT_ONLY", ""))
	return RuleContract(rule_id, family, severity, description, mode)


def _build_registry() -> dict[str, RuleContract]:
	registry: dict[str, RuleContract] = {}
	for family, rules in (
		("NVDA", NVDA_DETECTION_RULES),
		("WX-A11Y", WX_A11Y_RULES),
		("DTK-A11Y", DTK_A11Y_RULES),
		("NVDA-UX", NVDA_UX_RULES),
	):
		for rule_id, severity, description in rules:
			registry[rule_id] = _contract(rule_id, family, severity, description)
	for rule_id in ARCH_RULE_IDS:
		severity, description = ARCH_DESCRIPTIONS[rule_id]
		registry[rule_id] = _contract(rule_id, "ARCH", severity, description)
	registry["NVDA-041"] = RuleContract(
		"NVDA-041",
		"NVDA",
		"Deprecated",
		"Alias historico; use NVDA-034.",
		"ALIAS",
		status="deprecated_alias",
		alias_for="NVDA-034",
	)
	return dict(sorted(registry.items()))


RULE_REGISTRY: dict[str, RuleContract] = _build_registry()


def active_rules() -> list[RuleContract]:
	return [rule for rule in RULE_REGISTRY.values() if rule.status == "active"]


def format_rule_registry_prompt() -> str:
	lines = [
		"REGISTRO CENTRAL DE REGRAS NVDASTUDIO:",
		"Aplique somente regras pertinentes ao addon e corrija a causa real.",
	]
	for rule in active_rules():
		lines.append(
			f"{rule.rule_id} [{rule.family}/{rule.severity}] {rule.description} "
			f"| fallback={rule.fallback_mode}"
		)
	lines.append("NVDA-041 [DEPRECATED] alias de NVDA-034.")
	return "\n".join(lines)


RULE_REGISTRY_PROMPT_TEXT = format_rule_registry_prompt()
