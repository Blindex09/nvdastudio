from dataclasses import dataclass

from .nvda_context import (
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
	"ARCH-001": ("Serious", "Addon with an external API but no SettingsPanel for credentials and options."),
	"ARCH-002": ("Critical", "Heavy I/O, network or long processing without a thread/background worker."),
	"ARCH-003": ("Serious", "Wrong AppModule vs GlobalPlugin choice for the addon scope."),
	"ARCH-004": ("Moderate", "Domain logic mixed into the entry point without a separate service."),
	"ARCH-005": ("Serious", "Persistent configuration without config.conf.spec and clear defaults."),
	"ARCH-006": ("Serious", "Extension points without a complete register/unregister or the correct signature."),
	"ARCH-007": ("Moderate", "Complex addon without subpackages named after the feature."),
	"ARCH-008": ("Serious", "Multi-feature addon without an accessible entry point."),
	"ARCH-009": ("Serious", "Main interface without a clear choice between menu and SettingsPanel."),
}

NVDA_UX_RULES: tuple[tuple[str, str, str], ...] = (
	("NVDA-UX-001", "Critical", "Visual state change without equivalent feedback through NVDA."),
	("NVDA-UX-002", "Serious", "Action without audible feedback to the user."),
	("NVDA-UX-003", "Serious", "Main flow cannot be completed with only the keyboard and speech."),
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
		"Historical alias; use NVDA-034.",
		"ALIAS",
		status="deprecated_alias",
		alias_for="NVDA-034",
	)
	return dict(sorted(registry.items()))


RULE_REGISTRY: dict[str, RuleContract] = _build_registry()


def active_rules() -> list[RuleContract]:
	return [rule for rule in RULE_REGISTRY.values() if rule.status == "active"]




