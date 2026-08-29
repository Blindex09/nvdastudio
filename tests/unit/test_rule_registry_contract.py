from addon.globalPlugins.nvdastudio.builder.nvda_context import (
	ARCH_RULE_IDS,
	NVDA_DETECTION_RULES,
	WX_A11Y_RULES,
	DTK_A11Y_RULES,
)
from addon.globalPlugins.nvdastudio.rule_registry import (
	COMMUNITY_ACCESS_SOURCES,
	DEPRECATED_ALIASES,
	RULE_REGISTRY,
	RULE_REGISTRY_PROMPT_TEXT,
	active_rule_ids,
)


def test_rule_registry_cobre_todas_as_regras_ativas():
	expected = {rule_id for rule_id, _severity, _desc in NVDA_DETECTION_RULES}
	expected.update(rule_id for rule_id, _severity, _desc in WX_A11Y_RULES)
	expected.update(rule_id for rule_id, _severity, _desc in DTK_A11Y_RULES)
	expected.update(ARCH_RULE_IDS)
	expected.update({"NVDA-UX-001", "NVDA-UX-002", "NVDA-UX-003"})

	assert set(active_rule_ids()) == expected
	assert "NVDA-041" not in active_rule_ids()


def test_nvda041_e_alias_historico_para_nvda034():
	alias = RULE_REGISTRY["NVDA-041"]

	assert alias.status == "deprecated_alias"
	assert alias.alias_for == "NVDA-034"
	assert DEPRECATED_ALIASES[0].rule_id == "NVDA-041"


def test_todas_as_regras_ativas_tem_fonte_agentes_e_callbacks():
	for rule_id in active_rule_ids():
		rule = RULE_REGISTRY[rule_id]
		assert rule.source
		assert rule.owner_agents
		assert rule.required_surfaces
		assert rule.callbacks == (
			"prompt_gate",
			"static_audit",
			"quality_critic",
			"targeted_fix",
			"checkpoint_report",
		)
		assert rule.fallback_mode in {
			"STRICT_ONLY",
			"IMPLEMENTATION_ALTERNATIVES",
			"CONTEXTUAL_CHOICE",
		}


def test_prompt_unico_e_injetado_nos_agentes_principais():
	from addon.globalPlugins.nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
	from addon.globalPlugins.nvdastudio.sub_agents.accessibility_auditor import _SYSTEM as auditor_system
	from addon.globalPlugins.nvdastudio.sub_agents.code_generator import _SYSTEM as generator_system

	for prompt in (_CRITIC_QUALITY_SYSTEM, auditor_system, generator_system):
		assert "REGISTRO CENTRAL DE REGRAS NVDASTUDIO" in prompt
		assert RULE_REGISTRY_PROMPT_TEXT in prompt
		for rule_id in active_rule_ids():
			assert rule_id in prompt


def test_fontes_community_access_estao_registradas():
	assert "https://community-access.org/" in COMMUNITY_ACCESS_SOURCES
	assert "https://github.com/Community-Access/accessibility-agents" in COMMUNITY_ACCESS_SOURCES

