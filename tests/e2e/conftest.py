"""Seleciona o provedor de IA da rodada E2E por variavel de ambiente.

`get_llm_provider()` le `config.conf`, que na maquina do usuario vem do painel
de configuracoes do NVDA. Numa rodada E2E nao ha painel, e ate 2026-09-03 isso
significava que TODA rodada testava o provedor padrao (ollama) -- os outros
nunca eram exercitados de ponta a ponta, por falta de um jeito de escolher.

Escopo deliberado: este conftest vive em tests/e2e/ e nao toca codigo de
producao. A selecao de provedor do usuario real continua sendo o painel.

Uso:
    NVDASTUDIO_E2E_PROVIDER=factory python -m pytest tests/e2e/...

Sem a variavel, nada muda -- o padrao continua sendo o que o codigo decide.
"""

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _provedor_da_rodada():
	provedor = os.environ.get("NVDASTUDIO_E2E_PROVIDER", "").strip()
	if not provedor:
		yield
		return

	from nvdastudio.gui.settings_panel import (
		CONFIG_KEY_PROVIDER,
		CONFIG_SECTION,
		_PROVIDER_CODES,
	)

	if provedor not in _PROVIDER_CODES:
		pytest.fail(
			f"NVDASTUDIO_E2E_PROVIDER={provedor!r} nao e um provedor conhecido. "
			f"Validos: {sorted(_PROVIDER_CODES)}"
		)

	import config

	anterior = dict(config.conf.get(CONFIG_SECTION, {}))
	config.conf.setdefault(CONFIG_SECTION, {})[CONFIG_KEY_PROVIDER] = provedor
	print(f"\n[E2E] provedor da rodada: {provedor}")
	try:
		yield
	finally:
		config.conf[CONFIG_SECTION] = anterior
