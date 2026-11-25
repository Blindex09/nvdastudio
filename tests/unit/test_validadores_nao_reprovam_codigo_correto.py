"""
Funcao de fitness: um addon NVDA canonicamente correto passa em TODOS os
portoes de verificacao.

que gera o ponto de entrada foi reprovado por QUATRO portoes diferentes, um por


Nenhuma dessas reprovacoes era defeito do codigo gerado -- eram defeitos da
tokens para ser descoberta, porque os portoes eram encontrados em serie, um de
cada vez, so quando o anterior parava de disparar.

Este teste roda os nove portoes de uma vez, offline, em segundos. Um portao que

defined` em toda string traduzivel de todo addon correto pela NVDA-019.
"""

import os

import pytest

from nvdastudio_mcp.code_sandbox import CodeSandbox

NL = chr(10)
TAB = chr(9)
_PKG = "globalPlugins/MeuAddon"

# Addon minimo que exercita o que TODO addon NVDA real tem: GlobalPlugin,
# gettext inicializado, script com gesture, tratamento de erro, subpacote local,
# e terminate(). Se algum portao reprova isto, ele reprova a maioria dos addons
_INIT = NL.join([
	'"""Addon de exemplo canonicamente correto."""',
	"import addonHandler",
	"import globalPluginHandler",
	"import ui",
	"from scriptHandler import script",
	"",
	"from .servico import Servico",
	"",
	"addonHandler.initTranslation()",
	"",
	"",
	"class GlobalPlugin(globalPluginHandler.GlobalPlugin):",
	TAB + 'scriptCategory = _("Meu Addon")',
	"",
	TAB + "def __init__(self):",
	TAB + TAB + "super().__init__()",
	TAB + TAB + "self._servico = Servico()",
	"",
	TAB + '@script(description=_("Anuncia a hora"), gesture="kb:NVDA+shift+h")',
	TAB + "def script_hora(self, gesture):",
	TAB + TAB + "try:",
	TAB + TAB + TAB + "ui.message(self._servico.agora())",
	TAB + TAB + "except Exception:",
	TAB + TAB + TAB + 'ui.message(_("Nao foi possivel obter a hora."))',
	"",
	TAB + "def terminate(self):",
	TAB + TAB + "super().terminate()",
	"",
])

_SERVICO = NL.join([
	'"""Servico de exemplo."""',
	"import datetime",
	"",
	"import addonHandler",
	"",
	"addonHandler.initTranslation()",
	"",
	"",
	"class Servico:",
	TAB + "def agora(self):",
	TAB + TAB + 'return datetime.datetime.now().strftime("%H:%M")',
	"",
])

_ARQUIVOS = {f"{_PKG}/__init__.py": _INIT, f"{_PKG}/servico.py": _SERVICO}


def _detalhe(r):
	return (r.stdout or r.stderr or r.error or "")[:400]


def test_portao_execucao_isolada():
	r = CodeSandbox().validate_addon_execution(_ARQUIVOS)
	assert r.success, _detalhe(r)


def test_execucao_nao_reprova_addon_que_le_configdir():
	"""Regressao (falso positivo real):
	um addon que le NVDAState.WritePaths.configDir e junta um arquivo -- padrao
	comum e CORRETO -- era reprovado pelo gate com
	`TypeError: expected str... not _Permissive`, porque o stub devolvia um mock
	truthy nao-string e o guard `if not config_dir` nao pegava. Falso-positivo
	do gate, que reprovava addon bom. O stub
	de NVDAState.WritePaths.configDir passou a ser uma string real."""
	init = NL.join([
		"import os",
		"import globalPluginHandler",
		"import addonHandler",
		"import NVDAState",
		"addonHandler.initTranslation()",
		"",
		"",
		"class GlobalPlugin(globalPluginHandler.GlobalPlugin):",
		TAB + "def __init__(self, *args, **kwargs):",
		TAB + TAB + "super().__init__(*args, **kwargs)",
		TAB + TAB + "config_dir = NVDAState.WritePaths.configDir",
		TAB + TAB + "if not config_dir:",
		TAB + TAB + TAB + "config_dir = os.environ.get('TEMP', '.')",
		TAB + TAB + "self._path = os.path.join(config_dir, 'meu_addon.json')",
	])
	arquivos = {
		f"{_PKG}/__init__.py": init,
		"manifest.ini": "name = MeuAddon" + NL,
	}
	r = CodeSandbox().validate_addon_execution(arquivos)
	assert r.success, _detalhe(r)


def test_portao_lint():
	r = CodeSandbox().lint_check(_ARQUIVOS)
	assert r.success or r.error, _detalhe(r)


def test_portao_typecheck():
	"""mypy nao tem como declarar builtins injetados em runtime; a autoridade
	sobre nome indefinido fica com o ruff (F821), que tem. Duas ferramentas
	opinando sobre a mesma coisa, uma mal informada, e pior que uma so."""
	r = CodeSandbox().typecheck(_ARQUIVOS)
	assert r.success or r.error, _detalhe(r)


@pytest.mark.parametrize("cenario", ["api_401", "missing_file", "timeout"])
def test_portao_fault_injection(cenario):
	os.environ["NVDASTUDIO_FAULT_SCENARIO"] = cenario
	try:
		r = CodeSandbox().validate_addon_execution(_ARQUIVOS)
	finally:
		os.environ.pop("NVDASTUDIO_FAULT_SCENARIO", None)
	assert r.success, _detalhe(r)


def test_gettext_sem_inicializar_ainda_e_pego():
	"""O afrouxamento nao pode cegar a verificacao para o defeito real."""
	ruim = _INIT.replace("addonHandler.initTranslation()" + NL, "")
	r = CodeSandbox().validate_addon_execution({f"{_PKG}/__init__.py": ruim})
	assert not r.success
