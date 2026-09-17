"""
Funcao de fitness: o contrato central cobre os modulos que existem.

A Regra 1 do README declara `AI_MODULE_SPEC.md` como contrato central do
projeto. Auditoria de 2026-09-02: cinco modulos reais estavam FORA dele, e o
mais consequente era `ai/model_router.py`.

O roteador e uma costura central: se ficar fora do contrato, outro modulo pode
duplicar sua selecao e criar comportamento divergente.

Um contrato incompleto nao e questao de arrumacao: e a causa de reinventar o
que ja existe.
"""

import pathlib

_RAIZ = pathlib.Path(__file__).resolve().parents[2] / "addon" / "globalPlugins" / "nvdastudio"
_SPEC = _RAIZ / "AI_MODULE_SPEC.md"

# Modulos que a spec cobre COLETIVAMENTE, sem linha propria -- cada um com o
# motivo. `builtins/` sao as ferramentas do tool_system, descritas em conjunto
# porque compartilham contrato e ciclo de vida.
_COBERTOS_EM_CONJUNTO: dict[str, str] = {}

# Arquivos que nao sao modulo do produto.
_FORA_DO_CONTRATO = {"__init__.py"}


def _modulos_reais() -> set[str]:
	return {
		p.name for p in _RAIZ.rglob("*.py")
		if "nvda_docs_cache" not in str(p)
		and "lib" not in p.relative_to(_RAIZ).parts
		and p.name not in _FORA_DO_CONTRATO
	}


def test_todo_modulo_do_codigo_aparece_no_contrato():
	spec = _SPEC.read_text(encoding="utf-8")
	ausentes = sorted(
		nome for nome in _modulos_reais()
		if nome not in spec and nome not in _COBERTOS_EM_CONJUNTO
	)
	assert not ausentes, (
		"modulos fora do AI_MODULE_SPEC.md:\n  " + "\n  ".join(ausentes)
		+ "\n\nA Regra 1 declara o AI_MODULE_SPEC como contrato central. Modulo "
		"que nao esta nele e modulo que o proximo a mexer aqui nao vai encontrar "
		"-- e vai reescrever do zero, pior."
	)


def test_o_roteador_de_modelo_esta_documentado():
	"""Regressao nomeada: foi ESTE modulo que ficou de fora e ESTE que foi
	duplicado por causa disso."""
	spec = _SPEC.read_text(encoding="utf-8")
	assert "model_router.py" in spec
	assert "select_model" in spec, (
		"a selecao ativa precisa estar visivel no contrato"
	)
