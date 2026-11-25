"""
O projeto penalizava regras que nunca demonstrava.

por custo:

    NVDA-021    17 reprovacoes   1.817.655 tokens  (ja resolvido mecanicamente)
    NVDA-016     8 reprovacoes   1.693.336 tokens  (tem template)
    NVDA-003     7 reprovacoes   1.983.072 tokens  (tem template)

As duas regras sem template eram exigidas apenas como uma linha de descricao no
frequencia. Cobrar uma forma sem nunca mostra-la e o defeito.

NVDA-062 e o caso mais caro e o mais sutil: scripts sao definidos a nivel de
CLASSE, entao checar `globalVars.appArgs.secure` no __init__ e sair cedo NAO
impede o script de rodar em secure mode. O template mostra a checagem em cada
ponto de entrada perigoso, antes de tocar na credencial.
"""

from nvdastudio_mcp.nvda_context import NVDA_GUIDE




class TestSecureMode:
	def test_regra_tem_template(self):
		assert "globalVars.appArgs.secure" in NVDA_GUIDE

	def test_mostra_o_erro_de_checar_so_no_init(self):
		"""O ponto que o modelo erra: script definido a nivel de classe roda
		mesmo com o __init__ retornando cedo."""
		i = NVDA_GUIDE.index("NVDA-062 Critico")
		trecho = NVDA_GUIDE[i:i + 2500]
		assert "Errado" in trecho and "Correto" in trecho
		assert "__init__" in trecho

	def test_cobre_o_painel_de_configuracoes(self):
		"""Reprovacao real medida: makeSettings() lia a chave de API e SO
		depois desabilitava o controle."""
		i = NVDA_GUIDE.index("NVDA-062 Critico")
		trecho = NVDA_GUIDE[i:i + 2500]
		assert "makeSettings" in trecho
		assert "onSave" in trecho

	def test_proibe_logar_credencial(self):
		i = NVDA_GUIDE.index("NVDA-062 Critico")
		trecho = NVDA_GUIDE[i:i + 2500]
		assert "NUNCA logue" in trecho


class TestFeedbackDeFalhaBloqueada:
	def test_falha_bloqueada_precisa_ser_falada(self):
		"""O usuario de leitor de tela apertou salvar e nao ouviu nada -- para ele, funcionou.
		Warning no log nao e feedback."""
		assert "nao foi salva" in NVDA_GUIDE
		assert "shouldWriteToDisk" in NVDA_GUIDE


class TestDialogoAcessivel:
	def test_wx_a11y_004_tem_template(self):
		assert "CreateStdDialogButtonSizer" in NVDA_GUIDE

	def test_explica_o_que_o_sizer_padrao_resolve(self):
		i = NVDA_GUIDE.index("WX-A11Y-004 Serio")
		trecho = NVDA_GUIDE[i:i + 900]
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
		assert marcador in NVDA_GUIDE, (
			f"{marcador} e exigido pelo validador mas nao demonstrado no guia"
		)
