"""
Step nao-bloqueante REPROVADO tinha o output guardado e injetado nos steps
seguintes sem nenhuma marca -- e os `issues` do Critic, que costumam CONTER a
correcao, eram descartados.

Medido na rodada E2E de 2026-09-01 12:26 (AssistenteLeituraGemini):

  web_research   REPROVADO: "o output pesquisa o pacote legado
                 google-generativeai, mas o objetivo exige o SDK atual"
  cg_core_service REPROVADO apos 3 tentativas e 419.747 tokens: "o objetivo
                 exige o uso do SDK confirmado pela pesquisa
                 (google-generativeai), mas o codigo..."

O gerador seguiu a pesquisa errada porque nada dizia que ela estava errada --
embora o pipeline ja soubesse, por escrito, uma etapa antes. Nao-bloqueante
quer dizer "nao para o pipeline"; nunca quis dizer "passa adiante como fato".
"""

import inspect

from nvdastudio.core.orchestrator import (
	MODULE_VERSION,
	Orchestrator,
	StepResult,
	_output_com_ressalva,
)


def _reprovado(motivos, saida="conteudo produzido"):
	return StepResult(
		step_id="s2", step_type="web_research", output=saida,
		approved=False, score=0, issues=list(motivos),
	)


def test_versao():
	assert MODULE_VERSION == "5.85.0"


def test_output_reprovado_e_marcado_como_nao_verificado():
	texto = _output_com_ressalva(_reprovado(["usa o pacote legado"]), "web_research")
	assert "[NAO VERIFICADO]" in texto
	assert "REPROVADO" in texto


def test_motivos_da_reprovacao_viajam_com_o_conteudo():
	"""O motivo costuma conter a correcao. Descarta-lo joga fora a unica coisa
	que o proximo step precisava saber."""
	motivo = "o objetivo exige o SDK atual google-genai, nao google-generativeai"
	texto = _output_com_ressalva(_reprovado([motivo]), "web_research")
	assert motivo in texto


def test_conteudo_original_e_preservado():
	"""Marcar nao e apagar: o conteudo ainda pode ter partes uteis, e descartar
	tudo seria trocar informacao ruim por nenhuma."""
	texto = _output_com_ressalva(_reprovado(["x"], "detalhes da API"), "web_research")
	assert "detalhes da API" in texto


def test_motivo_vence_o_conteudo_explicitamente():
	"""Sem dizer o que vale mais, o modelo fica com duas fontes conflitantes e
	nenhuma regra de desempate."""
	texto = _output_com_ressalva(_reprovado(["x"]), "web_research")
	assert "os motivos valem mais" in texto


def test_sem_motivos_devolve_o_conteudo_cru():
	"""Reprovacao sem issue nenhum nao da o que dizer -- inventar um aviso vazio
	so gastaria contexto."""
	r = StepResult(step_id="s", step_type="web_research", output="abc",
				   approved=False, score=0, issues=[])
	assert _output_com_ressalva(r, "web_research") == "abc"


def test_step_aprovado_nunca_recebe_ressalva():
	"""Duvida em cima de output aprovado enfraquece contexto bom."""
	src = inspect.getsource(Orchestrator)
	linhas = src.split(chr(10))
	# Todo ponto que grava em `outputs` sob a guarda de _NON_BLOCKING_STEP_TYPES
	# precisa da MESMA regra. Um deles sem a ressalva reabre o buraco inteiro --
	# foi assim que a primeira versao desta correcao cobriu cinco de seis.
	sem_ressalva = []
	for i, ln in enumerate(linhas):
		if '_NON_BLOCKING_STEP_TYPES:' not in ln or '.approved or' not in ln:
			continue
		trecho = chr(10).join(linhas[i:i + 8])
		if 'outputs[' not in trecho:
			continue
		if '_output_com_ressalva(' not in trecho:
			sem_ressalva.append(ln.strip())
	assert not sem_ressalva, (
		'grava output de step nao-bloqueante sem distinguir aprovado de '
		'reprovado: ' + str(sem_ressalva)
	)
	assert src.count('_output_com_ressalva(') >= 4


def test_issues_nao_string_nao_derrubam():
	"""Falha aqui viraria um pipeline morto por causa de um aviso."""
	r = StepResult(step_id="s", step_type="web_research", output="abc",
				   approved=False, score=0, issues=[None, "", "valido"])
	texto = _output_com_ressalva(r, "web_research")
	assert "valido" in texto
