import re
from ._base import _run_sub_agent, narrate
from ..builder.nvda_context import get_docs_manifest_builder
from ..utils.project_policy import ABSOLUTE_MIN_NVDA, PROJECT_LAST_TESTED_NVDA, PROJECT_MIN_NVDA
from ..utils.addon_versioning import (
	ADDON_LIFECYCLE_PROMPT_TEXT,
	changelog_is_uninformative,
	enforce_version_bump,
	extract_previous_version,
)
from ..utils.logger import get_logger

MODULE_VERSION = "1.14.0"
_logger = get_logger("manifest_builder")

_SYSTEM = f"""You are the Elite Manifest Expert for NVDAStudio. Your mission is to generate perfectly formatted manifest.ini files that ensure 100% installation success.

## Hard Boundary
- Never include the [add-on] section header.
- Never output configSpec or SHA256 fields.
- Never include line breaks within any text field (summary, description, changelog).
- minimumNVDAVersion must NEVER be below {ABSOLUTE_MIN_NVDA}.

## NVDA Manifest Guidelines

<example>
Context: Exemplo completo de manifest.ini correto.
```ini:manifest.ini
name = MyAddon
summary = My Great Addon
description = This addon provides extensive features for NVDA users including advanced OCR and real-time transcription that works across all applications without any visual feedback.
version = 1.0.0
author = Author Name <author@example.com>
url = https://example.com
docFileName = userGuide.html
minimumNVDAVersion = {PROJECT_MIN_NVDA}
lastTestedNVDAVersion = {PROJECT_LAST_TESTED_NVDA}
changelog = Initial release with full feature set
```
<commentary>
Cada campo em UMA UNICA LINHA. Se houver quebra de linha em description, summary ou changelog, o ConfigObj parseia como lista Python, causando VdtTypeError fatal na instalacao (lista = wrong type).
</commentary>
</example>

PROIBIDO no manifest:
- Seccao [add-on] — ConfigObj nao usa secoes para campos globais
- Quebras de linha em qualquer campo de texto (causa VdtTypeError fatal)
- configSpec ou SHA256 (campos internos do NVDA, nao do addon)
- minimumNVDAVersion abaixo de {ABSOLUTE_MIN_NVDA}

## Required Fields
name, summary, description, author, url, version, minimumNVDAVersion, lastTestedNVDAVersion, docFileName, changelog.

- docFileName = userGuide.html (NVDAStudio Policy -- NVDA em si trata como opcional, default None)

## Core Baseline (NVDAStudio Policy)
- minimumNVDAVersion = {PROJECT_MIN_NVDA}
- lastTestedNVDAVersion = {PROJECT_LAST_TESTED_NVDA}

FORMATO DE SAIDA OBRIGATORIO:
Gere o conteudo do manifest dentro do bloco: ```ini:manifest.ini

## Implementation Contract (for next agent)
1. Critical Resource Check: Verify if [brailleTables], [symbolDictionaries] or [speechDictionaries] sections were required based on the addon features.

VERIFICACAO FINAL OBRIGATORIA:
1. O arquivo comeca diretamente com name = ... (SEM linha [add-on])?
2. summary, description e changelog estao em UMA UNICA LINHA cada um (sem quebras)?
3. minimumNVDAVersion e lastTestedNVDAVersion sao >= {PROJECT_MIN_NVDA}?
4. docFileName = userGuide.html esta presente?
5. O manifest NAO contem configSpec nem SHA256?
Se qualquer item falhar, corrija antes de entregar o manifest.

## Optional Sections (Add only if relevant)

[brailleTables]
[[minha-tabela.utb]]
displayName = My Braille Table
contracted = False
output = True
input = True

[symbolDictionaries]
[[meuaddon]]
displayName = My Symbols
mandatory = false

[speechDictionaries]
[[pronuncia]]
displayName = My Speech Dict
mandatory = false
"""

# 2026-08-29: o pipeline tratava toda entrega como se fosse a primeira --
# `version = 1.0.0` era o unico exemplo e nao havia nenhuma orientacao sobre
# modificar um addon que ja existe, que e metade do proposito do projeto.
# Texto e verificacao deterministica moram juntos em utils/addon_versioning.py
# de proposito, para que prompt e fiscalizacao nao divirjam.
_SYSTEM += "\n\n" + ADDON_LIFECYCLE_PROMPT_TEXT


def run(prompt: str, model_id: str, reasoning_params: dict, cache_key: str | None = None) -> str:
	# Narracao "antes" removida (v1.11.0) -- duplicava o que o proprio
	# modelo ja narra ao vivo no content, via LiveNarrator ligado abaixo
	# por live_narrate=True.
	# enable_web_search (1.13.0): confirma a versao/baseline atual do NVDA
	# contra uma fonte real quando incerto, em vez de so usar o
	# conhecimento de treinamento (pode estar desatualizado -- ver
	# achados reais desta sessao sobre catalogos de modelo desatualizados).
	result = _run_sub_agent(_SYSTEM, prompt, model_id, reasoning_params,
						  extra_docs=get_docs_manifest_builder(), cache_key=cache_key,
						  live_narrate=True, enable_web_search=True)
	# Integridade de versao e DETERMINISTICA (README Regra 7): a IA decide o
	# tipo de mudanca e o texto do changelog; o codigo garante que a versao
	# entregue e estritamente maior que a anterior. O NVDA compara versoes pra
	# decidir se um addon e atualizacao -- reentregar um addon modificado com a
	# mesma versao faz o usuario cego instalar por cima sem nenhum sinal de que
	# algo mudou. Corrige em vez de reprovar: gastar uma rodada de LLM pra
	# consertar um numero que o codigo resolve sem ambiguidade seria desperdicio.
	previous = extract_previous_version(prompt)
	result, aviso = enforce_version_bump(result, previous)
	if aviso:
		_logger.warning("[MANIFEST] %s", aviso)
	if previous and changelog_is_uninformative(result):
		# Aviso, nunca bloqueio: changelog fraco degrada a experiencia mas nao
		# quebra o addon.
		_logger.info(
			"[MANIFEST] changelog generico numa modificacao de addon existente (v%s)",
			previous,
		)

	_nome_match = re.search(r'^name\s*=\s*(.+)$', result, re.MULTILINE)
	if _nome_match:
		narrate(f"terminei o manifesto do addon {_nome_match.group(1).strip()}")
	else:
		narrate("terminei o manifesto do addon")
	return result
