"""
Funcao de fitness: um addon NVDA canonicamente correto passa em TODOS os
portoes de verificacao.

MOTIVO, e e o mais importante deste arquivo. Entre as rodadas E2E 6 e 8, o step
que gera o ponto de entrada foi reprovado por QUATRO portoes diferentes, um por
rodada:

    rodada 6: "Entrega incompleta" + import de modulo inexistente
    rodada 7: "cannot import name" + `gui.message` sem stub
    rodada 8: "Falha de robustez sob fault injection"

Nenhuma dessas reprovacoes era defeito do codigo gerado -- eram defeitos da
VERIFICACAO. E cada uma custou uma rodada de 45 minutos e mais de um milhao de
tokens para ser descoberta, porque os portoes eram encontrados em serie, um de
cada vez, so quando o anterior parava de disparar.

Este teste roda os nove portoes de uma vez, offline, em segundos. Um portao que
reprove codigo correto aparece aqui -- nao na proxima rodada paga.

Auditoria de 2026-09-02: o unico que reprovava era o mypy, com `Name "_" is not
defined` em toda string traduzivel de todo addon correto pela NVDA-019.
"""

import os

import pytest

from nvdastudio.builder.addon_builder import (
	validate_python_imports,
	validate_python_syntax,
)
from nvdastudio.builder.code_sandbox import CodeSandbox
from nvdastudio.core.orchestrator import Orchestrator

NL = chr(10)
TAB = chr(9)
_PKG = "globalPlugins/MeuAddon"

# Addon minimo que exercita o que TODO addon NVDA real tem: GlobalPlugin,
# gettext inicializado, script com gesture, tratamento de erro, subpacote local,
# e terminate(). Se algum portao reprova isto, ele reprova a maioria dos addons
# corretos que o pipeline vai gerar.
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


@pytest.mark.parametrize("rel", sorted(_ARQUIVOS))
def test_portao_sintaxe(rel):
	assert not validate_python_syntax(_ARQUIVOS[rel])


def test_portao_imports_declarados():
	assert not validate_python_imports(_INIT, local_modules={"servico"})


def test_portao_ponto_de_entrada():
	assert not Orchestrator._missing_loadable_entry_point(list(_ARQUIVOS))


def test_portao_execucao_isolada():
	r = CodeSandbox().validate_addon_execution(_ARQUIVOS)
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
