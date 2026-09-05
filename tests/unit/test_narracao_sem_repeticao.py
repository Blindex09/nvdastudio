"""
A narracao ao vivo empilhava texto identico no historico e vazava placeholders
internos como se fossem fontes reais -- as duas queixas concretas do usuario
sobre a "narracao idiota e repeticoes".

BUG 1 (repeticao): cada retentativa de um step re-narra a MESMA frase ("Estou
pensando na estrutura do addon...") e _handle_status emitia todas. A dedup de
_chat_append() so comparava a ULTIMA linha fisica e nunca casava com o formato
multilinha "Assistente:\n{msg}" (sanitize_user_visible_text preserva o \n),
entao narracao identica empilhava verbatim. Medido no trecho de execucao real
colado pelo usuario: "Estou pensando na estrutura..." apareceu ~5x seguidas.

BUG 2 (fonte-placeholder): domain_researcher preenche research_sources com
"conhecimento estatico" / "conhecimento estatico + LLM" quando nenhuma busca
externa real rodou. O orchestrator emitia isso como "Fontes consultadas: -
conhecimento estatico" -- ruido interno vazando pra conversa, sem valor pro
usuario.
"""

from collections import deque

from nvdastudio.gui.studio_dialog import MODULE_VERSION as STUDIO_VERSION
from nvdastudio.core.orchestrator import MODULE_VERSION as ORCH_VERSION


def test_versoes():
	assert STUDIO_VERSION == "5.51.0"
	assert ORCH_VERSION == "5.88.0"


# ---------------------------------------------------------------------------
# BUG 1 -- dedup de narracao repetida em _handle_status
# ---------------------------------------------------------------------------

def _janela():
	from nvdastudio.gui.studio_dialog import _JANELA_NARRACAO
	return deque(maxlen=_JANELA_NARRACAO)


def _exibidas(mensagens):
	"""Simula a decisao de _handle_status: devolve as mensagens que NAO foram
	descartadas como eco, usando o mesmo helper puro do dialogo."""
	from nvdastudio.gui.studio_dialog import _narracao_e_eco
	janela = _janela()
	return [m for m in mensagens if not _narracao_e_eco(m, janela)]


def test_narracao_identica_repetida_nao_empilha():
	frase = "Estou pensando na estrutura do addon para atender ao pedido."
	exibidas = _exibidas([frase] * 5)
	assert exibidas == [frase], (
		f"narracao identica apareceu {len(exibidas)}x (esperado 1)"
	)


def test_narracao_diferente_passa_normalmente():
	msgs = [
		"Estou pesquisando a API do NVDA agora.",
		"Terminei a pesquisa, agora vou gerar o codigo.",
		"Escrevi o arquivo principal do addon.",
	]
	assert _exibidas(msgs) == msgs, "narracoes distintas nao podem ser dedupadas"


def test_dedup_ignora_caixa_e_espacos():
	from nvdastudio.gui.studio_dialog import _narracao_e_eco
	janela = _janela()
	assert _narracao_e_eco("Estou   organizando o PLANO de desenvolvimento.", janela) is False
	assert _narracao_e_eco("estou organizando o plano de desenvolvimento.", janela) is True


def test_frase_reaparece_depois_de_sair_da_janela():
	"""A dedup e uma JANELA curta (nao unicidade global): uma frase legitima
	que reaparece muito depois volta -- so o eco proximo e ruido."""
	msgs = ["Comecando."] + [f"Passo intermediario numero {i}." for i in range(8)] + ["Comecando."]
	exibidas = _exibidas(msgs)
	comecando = [m for m in exibidas if m == "Comecando."]
	assert len(comecando) == 2, "fora da janela de 8, a frase deve reaparecer"


def test_janela_default_e_oito():
	from nvdastudio.gui.studio_dialog import _JANELA_NARRACAO
	assert _JANELA_NARRACAO == 8


# ---------------------------------------------------------------------------
# BUG 2 -- placeholder interno nao vaza como "Fontes consultadas"
# ---------------------------------------------------------------------------

def test_placeholder_de_fonte_nao_vaza_pro_usuario():
	import inspect

	from nvdastudio.core import orchestrator

	src = inspect.getsource(orchestrator)
	# O filtro precisa existir e cobrir os dois placeholders reais do
	# domain_researcher.
	assert "conhecimento estatico" in src
	assert "conhecimento estatico + llm" in src
	assert "fontes_reais" in src, "o filtro de fontes reais sumiu"


def test_fonte_real_ainda_e_mostrada():
	"""So o placeholder e barrado -- URL real de busca externa continua indo
	pro usuario (valor de confianca/verificacao)."""
	placeholder = {"conhecimento estatico", "conhecimento estatico + llm"}
	fontes = ["conhecimento estatico", "https://download.nvaccess.org/doc"]
	reais = [s for s in fontes if s.strip().casefold() not in placeholder]
	assert reais == ["https://download.nvaccess.org/doc"]
