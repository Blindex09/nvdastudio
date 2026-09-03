"""
A entrega inteira era descartada por falta de manifest aprovado -- com o
gerador deterministico de manifest pronto e a um passo de distancia.

`addon_builder._generate_minimal_manifest()` existe, e deterministica, e a
docstring dela diz literalmente "gera manifest.ini minimo quando
manifest_builder falhou". Mas ela e chamada dentro de `save_addon_files()`, no
assembly, e `_validate_minimum_addon_artifacts()` roda ANTES do assembly: a
execucao morria antes de o fallback ter chance de agir.

O proprio projeto ja declarava a intencao contraria -- manifest_builder esta em
_NON_BLOCKING_STEP_TYPES com o comentario "assembly pode regenerar manifest se
necessario". A regra e o comentario discordavam, e quem vencia era a regra.

Medido na rodada 7 (AssistenteLeituraGemini): 4 steps aprovados, 1.466.531
tokens, entrega descartada porque o step de manifest nao foi aprovado -- sendo
que o Critic tinha escrito, no primeiro achado, "o manifest.ini atende aos
campos obrigatorios, usa formato sem secao [add-on], possui versoes compativeis
com o baseline 2026.1.1 e URL HTTPS valida".
"""

from nvdastudio.builder.addon_builder import _generate_minimal_manifest
from nvdastudio.core.orchestrator import MODULE_VERSION, Orchestrator
from nvdastudio.core.orch_types import StepResult

NL = chr(10)
_CODIGO = (
	"```python:globalPlugins/A/__init__.py" + NL
	+ "import globalPluginHandler" + NL
	+ "class GlobalPlugin(globalPluginHandler.GlobalPlugin): pass" + NL
	+ "```" + NL
)


def _plano(project_type="addon", ids=("cg1",)):
	steps = [type("S", (), {"step_id": i})() for i in ids]
	return type("P", (), {
		"steps": steps,
		"project_type": project_type,
		"expected_gestures": [],
		"expected_files": [],
	})()


def _resultado(aprovado=True):
	return StepResult(
		step_id="cg1", step_type="code_generation", output=_CODIGO,
		approved=aprovado, score=95,
	)


def test_versao():
	assert MODULE_VERSION == "5.86.0"


def test_sem_manifest_aprovado_a_entrega_continua():
	"""Um addon com manifest minimo deterministico e codigo que funciona serve
	ao usuario; nenhum addon nao serve."""
	orq = Orchestrator.__new__(Orchestrator)
	erro = orq._validate_minimum_addon_artifacts(
		_plano(), [_resultado()], {"cg1": _CODIGO},
	)
	assert not erro, f"a entrega foi descartada por falta de manifest: {erro}"


def test_sem_codigo_python_continua_fatal():
	"""Manifest sem addon nao e addon -- este caso NAO pode ser afrouxado."""
	orq = Orchestrator.__new__(Orchestrator)
	so_manifest = "```ini:manifest.ini" + NL + "name = A" + NL + "```" + NL
	plano = _plano(ids=("mb1",))
	resultado = StepResult(
		step_id="mb1", step_type="manifest_builder", output=so_manifest,
		approved=True, score=95,
	)
	erro = orq._validate_minimum_addon_artifacts(plano, [resultado], {"mb1": so_manifest})
	assert erro, "entrega sem codigo Python nao pode passar"


def test_o_fallback_produz_manifest_valido():
	"""A folga so se justifica se o que o assembly gera realmente presta."""
	from nvdastudio.builder.addon_builder import validate_manifest

	conteudo = _generate_minimal_manifest("MeuAddon")
	assert "name = MeuAddon" in conteudo
    # sem campo obrigatorio faltando
	assert not validate_manifest(conteudo)


def test_fallback_respeita_a_politica_de_versao_do_projeto():
	from nvdastudio.utils.project_policy import (
		PROJECT_LAST_TESTED_NVDA,
		PROJECT_MIN_NVDA,
	)

	conteudo = _generate_minimal_manifest("X")
	assert f"minimumNVDAVersion = {PROJECT_MIN_NVDA}" in conteudo
	assert f"lastTestedNVDAVersion = {PROJECT_LAST_TESTED_NVDA}" in conteudo
