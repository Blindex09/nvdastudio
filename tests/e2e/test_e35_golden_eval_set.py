import ast
import os

import pytest

from nvdastudio.builder.addon_builder import extract_code_blocks, validate_python_structure
from nvdastudio.core.planner import STEP_MODEL_MAP
from nvdastudio.sub_agents.ast_validator import validate_nvda019, validate_wx_a11y
from nvdastudio.utils.evaluation_framework import evaluation

HAS_OLLAMA = os.environ.get("OLLAMA_API_KEY", "").strip()
# 2026-08-17: critic.py 3.19.0 -- o Critic agora SEMPRE usa OpenCode Go
# (prompt caching), independente do provider ativo. Sem essa chave, TODA
# avaliacao de step falha com "Chave API para opencode_go nao configurada"
# -- achado real ao vivo (madrugada 2026-08-17/18, rodada 1 do loop): os
# 2 casos deste arquivo rodaram e "passaram" no pytest (test_e36 nao exige
# success=True) mas o pipeline inteiro falhou em segundos, 0 tokens gastos,
# nenhum sinal real coletado -- so desperdicou tempo/custo do Ollama sem
# testar nada. Adicionado ao skip guard pra nao rodar (e enganar) sem as
# 2 chaves.
HAS_OPENCODE_GO = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
skip_unless_ollama = pytest.mark.skipif(
	not HAS_OLLAMA or not HAS_OPENCODE_GO,
	reason=("Ollama Cloud token nao disponivel" if not HAS_OLLAMA else "OpenCode Go token nao disponivel (necessario pro Critic, ver critic.py 3.19.0)")
)

_MODEL_ID = STEP_MODEL_MAP.get("code_generation", "kimi-k2.7-code")

# Conjunto fixo de pedidos representativos -- cobre os tipos de addon mais
# comuns gerados pelo NVDAStudio. Deliberadamente pequeno (8 casos): um
# golden set grande demais custaria caro demais pra rodar sob demanda sem
# adicionar cobertura real de qualidade proporcional.
_GOLDEN_PROMPTS = [
	pytest.param(
		"Crie um globalPlugin NVDA simples que anuncia a hora atual ao pressionar NVDA+H.",
		id="globalplugin_simples",
	),
	pytest.param(
		"Crie um appModule NVDA para o Bloco de Notas do Windows que anuncia o numero "
		"da linha atual ao mover o cursor.",
		id="appmodule_simples",
	),
	pytest.param(
		"Crie um globalPlugin NVDA que abre um dialogo wx com um botao para copiar "
		"o texto selecionado para a area de transferencia.",
		id="globalplugin_com_dialogo_wx",
	),
	pytest.param(
		"Crie um globalPlugin NVDA que anuncia mensagens traduzidas (use gettext) "
		"quando o usuario pressiona NVDA+Shift+M.",
		id="globalplugin_com_traducao",
	),
]


def _assert_golden_properties(resultado_bruto: str, caso_id: str):
	"""Aplica as invariantes estruturais/comportamentais compartilhadas a
	todo caso do golden set.

	resultado_bruto e a resposta CRUA de code_generator.run() -- mistura
	narracao em prosa (LiveNarrator, tool-preamble) com blocos de codigo
	anotados com fence (```python:caminho/arquivo.py```). Igual ao
	orchestrator real (builder/addon_builder.py::extract_code_blocks()),
	extrai os blocos Python ANTES de validar -- ast.parse() na resposta
	crua inteira sempre falha (a narracao em prosa nao e Python valido),
	confundindo "modelo narrou antes de entregar codigo" com "modelo nao
	gerou codigo valido".
	"""
	blocks = extract_code_blocks(resultado_bruto)
	python_blocks = [b for b in blocks if b["filename"].endswith(".py")]
	assert python_blocks, (
		f"[{caso_id}] nenhum bloco ```python:arquivo.py``` extraido da resposta. "
		f"Primeiros 400 chars: {resultado_bruto[:400]!r}"
	)

	for block in python_blocks:
		codigo = block["code"]
		nome = block["filename"]

		try:
			ast.parse(codigo)
		except SyntaxError as exc:
			pytest.fail(f"[{caso_id}] {nome} tem SyntaxError: {exc}\nCodigo:\n{codigo[:800]}")

		avisos_estrutura = validate_python_structure(codigo)
		assert not avisos_estrutura, (
			f"[{caso_id}] {nome}: validate_python_structure encontrou avisos: {avisos_estrutura}"
		)

		violacoes_comportamentais = evaluation.validate_behavioral_contracts(codigo)
		assert not violacoes_comportamentais, (
			f"[{caso_id}] {nome}: contratos comportamentais violados: {violacoes_comportamentais}"
		)

		nvda019 = validate_nvda019(codigo)
		assert nvda019.ok, f"[{caso_id}] {nome}: NVDA-019 violado: {nvda019.violacoes}"

		wx_a11y = validate_wx_a11y(codigo)
		assert wx_a11y.ok, f"[{caso_id}] {nome}: WX-A11Y-001 violado: {wx_a11y.violacoes}"


@skip_unless_ollama
class TestGoldenEvalSetCodeGenerator:
	"""Conjunto de regressao de qualidade de prompt para code_generator.py.

	Diferente dos e2e existentes (1 pedido, 1 asserção especifica), este
	roda VARIOS pedidos representativos contra o MESMO conjunto de
	invariantes -- serve pra pegar regressao de qualidade geral do prompt
	entre versoes, nao um bug pontual de uma feature especifica.
	"""

	@pytest.mark.parametrize("pedido", _GOLDEN_PROMPTS)
	def test_pedido_golden_produz_codigo_estruturalmente_valido(self, pedido, request):
		from nvdastudio.sub_agents.code_generator import run

		caso_id = request.node.callspec.id
		resultado = run(prompt=pedido, model_id=_MODEL_ID, reasoning_params={})

		assert isinstance(resultado, str)
		assert len(resultado) > 50, f"[{caso_id}] resultado muito curto: {resultado[:200]!r}"

		_assert_golden_properties(resultado, caso_id)
