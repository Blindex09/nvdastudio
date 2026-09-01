"""
Os tres estagios do design review recebiam o MESMO bloco de 30 mil tokens de
fonte do NVDA -- 90 mil por revisao, gastos antes de existir uma linha de
codigo do addon. Nao era contexto demais: era o mesmo contexto tres vezes.

Medido em 2026-09-01 nos relatorios E2E: uma revisao custa de 90 a 165 mil
tokens, entre 9% e 17% do teto de um addon complexo -- e nos seis pedidos
complexos medidos o pipeline sempre morreu por orcamento antes de gerar o
__init__.py.

O corte segue o que cada persona produz, nao um teto arbitrario. O caso do
advocate e o mais claro: `_strip_rule_ids` existe justamente para REMOVER da
saida dele os IDs de regra que ele nao deveria citar -- dar fonte do NVDA a
esse estagio empurra ele para o comportamento que o codigo depois apaga.
"""

import inspect

from nvdastudio.builder.nvda_context import (
	_DESIGN_REVIEW_PERSONA_DOCS,
	PROMPT_VERSION,
	get_docs_design_review,
)
from nvdastudio.sub_agents import design_review_agent


def test_versao_do_contexto():
	assert PROMPT_VERSION == "3.34.0"


def test_guardian_recebe_tudo():
	"""E o unico estagio cuja saida depende de ler a fonte: cita restricoes
	tecnicas e IDs de regra do NVDA/WX."""
	assert get_docs_design_review(persona="guardian") == get_docs_design_review()


def test_advocate_nao_recebe_fonte_do_nvda():
	assert get_docs_design_review(persona="advocate") == ""


def test_challenger_recebe_o_ciclo_de_vida_e_nao_a_api_de_gestos():
	docs = get_docs_design_review(persona="challenger")
	assert "NVDAState.py" in docs
	assert "addonHandler/__init__.py" in docs
	assert "inputCore.py" not in docs, "gestos sao materia do guardian"
	assert "scriptHandler.py" not in docs


def test_persona_desconhecida_recebe_tudo():
	"""Na duvida, contexto sobrando custa tokens; contexto faltando custa a
	revisao. Um nome errado nao pode virar revisao as cegas."""
	completo = get_docs_design_review()
	assert get_docs_design_review(persona="inventado") == completo
	assert get_docs_design_review(persona="") == completo


def test_economia_medida():
	"""O ganho e o motivo da mudanca -- se encolher, a mudanca perdeu sentido."""
	antes = 3 * len(get_docs_design_review())
	depois = sum(
		len(get_docs_design_review(persona=p))
		for p in ("challenger", "guardian", "advocate")
	)
	assert depois < antes * 0.55, (
		f"esperado corte de ~55%; medido {depois} contra {antes}"
	)


def test_cada_estagio_usa_a_sua_documentacao():
	"""A costura: nao adianta a funcao aceitar persona se run() continua
	mandando o mesmo bloco para os tres."""
	src = inspect.getsource(design_review_agent.run)
	for persona in ("challenger", "guardian", "advocate"):
		assert f'get_docs_design_review(persona="{persona}")' in src
		assert f"extra_docs=_docs_{persona}," in src
	assert "_design_docs" not in src, "sobrou o bloco unico antigo"


def test_personas_declaradas_existem_no_catalogo():
	"""Um nome de arquivo com typo vira 'este estagio nao recebe nada' em
	silencio -- que e exatamente o modo de falha que a rodada 6 mostrou custar
	caro (notas 52.0 -> 15.7 ao cortar contexto)."""
	completo = get_docs_design_review()
	for persona, arquivos in _DESIGN_REVIEW_PERSONA_DOCS.items():
		for arquivo in arquivos:
			assert arquivo in completo, (
				f"{persona} declara {arquivo}, que nao existe no conjunto completo"
			)
