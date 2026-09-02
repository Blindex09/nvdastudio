"""
O projeto penalizava regras que nunca demonstrava.

Ranking das regras que mais reprovam code_generation nos 391 relatorios E2E,
por custo:

    NVDA-021    17 reprovacoes   1.817.655 tokens  (ja resolvido mecanicamente)
    NVDA-062    10 reprovacoes   2.420.712 tokens  <- SEM template no prompt
    NVDA-016     8 reprovacoes   1.693.336 tokens  (tem template)
    NVDA-003     7 reprovacoes   1.983.072 tokens  (tem template)
    WX-A11Y-004  5 reprovacoes     886.859 tokens  <- SEM template no prompt

As duas regras sem template eram exigidas apenas como uma linha de descricao no
catalogo. As que tem template -- NVDA-016 e NVDA-003 -- o modelo acerta com mais
frequencia. Cobrar uma forma sem nunca mostra-la e o defeito.

NVDA-062 e o caso mais caro e o mais sutil: scripts sao definidos a nivel de
CLASSE, entao checar `globalVars.appArgs.secure` no __init__ e sair cedo NAO
impede o script de rodar em secure mode. O template mostra a checagem em cada
ponto de entrada perigoso, antes de tocar na credencial.
"""

from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT, PROMPT_VERSION


def test_versao_do_prompt():
	assert PROMPT_VERSION == "3.35.0"


class TestSecureMode:
	def test_regra_tem_template(self):
		assert "globalVars.appArgs.secure" in NVDA_SYSTEM_PROMPT

	def test_mostra_o_erro_de_checar_so_no_init(self):
		"""O ponto que o modelo erra: script definido a nivel de classe roda
		mesmo com o __init__ retornando cedo."""
		i = NVDA_SYSTEM_PROMPT.index("NVDA-062 Critico")
		trecho = NVDA_SYSTEM_PROMPT[i:i + 2500]
		assert "Errado" in trecho and "Correto" in trecho
		assert "__init__" in trecho

	def test_cobre_o_painel_de_configuracoes(self):
		"""Reprovacao real medida: makeSettings() lia a chave de API e SO
		depois desabilitava o controle."""
		i = NVDA_SYSTEM_PROMPT.index("NVDA-062 Critico")
		trecho = NVDA_SYSTEM_PROMPT[i:i + 2500]
		assert "makeSettings" in trecho
		assert "onSave" in trecho

	def test_proibe_logar_credencial(self):
		i = NVDA_SYSTEM_PROMPT.index("NVDA-062 Critico")
		trecho = NVDA_SYSTEM_PROMPT[i:i + 2500]
		assert "NUNCA logue" in trecho


class TestFeedbackDeFalhaBloqueada:
	def test_falha_bloqueada_precisa_ser_falada(self):
		"""O usuario cego apertou salvar e nao ouviu nada -- para ele, funcionou.
		Warning no log nao e feedback."""
		assert "nao foi salva" in NVDA_SYSTEM_PROMPT
		assert "shouldWriteToDisk" in NVDA_SYSTEM_PROMPT


class TestDialogoAcessivel:
	def test_wx_a11y_004_tem_template(self):
		assert "CreateStdDialogButtonSizer" in NVDA_SYSTEM_PROMPT

	def test_explica_o_que_o_sizer_padrao_resolve(self):
		i = NVDA_SYSTEM_PROMPT.index("WX-A11Y-004 Serio")
		trecho = NVDA_SYSTEM_PROMPT[i:i + 900]
		assert "Escape" in trecho
		assert "tabulacao" in trecho or "ordem de foco" in trecho


def test_toda_regra_critica_do_catalogo_com_reprovacao_cara_tem_template():
	"""Funcao de fitness: regra que reprova caro e nao tem forma demonstrada no
	prompt volta a custar milhoes. As quatro abaixo sao as medidas."""
	for marcador in (
		"globalVars.appArgs.secure",   # NVDA-062
		"shouldWriteToDisk",           # NVDA-016
		"initTranslation",             # NVDA-003
		"CreateStdDialogButtonSizer",  # WX-A11Y-004
	):
		assert marcador in NVDA_SYSTEM_PROMPT, (
			f"{marcador} e exigido pelo Critic mas nao demonstrado no prompt"
		)
