"""
Funcionalidade pedida vs funcionalidade entregue, e 3 regras novas por AST.

LACUNA FECHADA (2026-08-29): o pipeline provava que o addon importa, instancia,
sobrevive a fault injection, passa no lint e empacota -- mas nada provava que
ele FAZ o que o usuario pediu. `_check_reserved_gestures` detecta CONFLITO com
atalhos do NVDA core; a AUSENCIA do atalho pedido nao era verificada por
ninguem.

DIVISAO SEMANTICO/DETERMINISTICO (README Regra 7), o ponto mais importante
deste arquivo: quem INTERPRETA o pedido em linguagem natural e a LLM, no campo
`expected_gestures` do plano. Extrair "NVDA+H" da frase do usuario com regex
seria "simular entendimento semantico com regex", proibido pela Regra 7. O
codigo so CONFERE que o declarado existe no AST.
"""

import pytest

from nvdastudio.core.planner import _normalize_gestures
from nvdastudio.sub_agents.ast_validator import (
	MODULE_VERSION,
	extract_declared_gestures,
	normalize_gesture,
	validate_declared_gestures,
	validate_nvda056_messagedialog_thread,
	validate_nvda060_controltypes,
	validate_wx_a11y_013_key_events,
)

assert MODULE_VERSION == "1.3.0"


class TestNormalizacaoDeGesture:
	"""'NVDA+H' e 'kb:nvda+h' sao o MESMO atalho -- tratar como diferentes
	transformaria divergencia de formatacao em falha de funcionalidade."""

	@pytest.mark.parametrize(
		"bruto,esperado",
		[
			("NVDA+H", "kb:nvda+h"),
			("kb:NVDA+H", "kb:nvda+h"),
			("  kb:Control+Shift+M  ", "kb:control+shift+m"),
			("br(freedomScientific):dot1", "br(freedomscientific):dot1"),
			("", ""),
		],
	)
	def test_forma_canonica(self, bruto, esperado):
		assert normalize_gesture(bruto) == esperado

	def test_fonte_unica_compartilhada_com_o_planner(self):
		"""README Regra 5: o planner normaliza importando daqui, nunca com
		copia propria -- duas normalizacoes divergentes fariam o plano declarar
		um formato e o validador procurar outro."""
		assert _normalize_gestures(["NVDA+H", "kb:nvda+h", "Control+Shift+M"]) == [
			"kb:nvda+h",
			"kb:control+shift+m",
		]

	def test_planner_descarta_entrada_invalida_sem_levantar(self):
		"""Roda dentro do pipeline: excecao aqui derrubaria uma criacao boa."""
		assert _normalize_gestures(["", None, 42, "  "]) == []
		assert _normalize_gestures("nao e lista") == []


class TestExtracaoDoCodigo:
	"""Cobre os dois padroes validos do NVDA."""

	def test_decorator_gesture_singular(self):
		c = 'from scriptHandler import script\n@script(gesture="kb:NVDA+h")\ndef script_a(g): pass\n'
		assert extract_declared_gestures(c) == {"kb:nvda+h"}

	def test_decorator_gestures_plural(self):
		c = (
			"from scriptHandler import script\n"
			'@script(gestures=["kb:NVDA+shift+j", "kb:NVDA+shift+k"])\n'
			"def script_a(g): pass\n"
		)
		assert extract_declared_gestures(c) == {"kb:nvda+shift+j", "kb:nvda+shift+k"}

	def test_dict_de_classe_gestures(self):
		c = 'class G:\n\t__gestures = {"kb:control+shift+m": "script_b"}\n'
		assert extract_declared_gestures(c) == {"kb:control+shift+m"}

	def test_sintaxe_invalida_devolve_vazio(self):
		assert extract_declared_gestures("def (") == set()


class TestVerificacaoDaFuncionalidade:
	_CODIGO = (
		"from scriptHandler import script\n"
		"class GlobalPlugin:\n"
		'\t@script(gesture="kb:NVDA+H", description="hora")\n'
		"\tdef script_hora(self, gesture): pass\n"
	)

	def test_atalho_pedido_e_entregue(self):
		assert validate_declared_gestures(self._CODIGO, ["kb:nvda+h"]).ok is True

	def test_atalho_pedido_e_ausente(self):
		r = validate_declared_gestures(self._CODIGO, ["kb:nvda+z"])
		assert r.ok is False
		assert "kb:nvda+z" in r.violacoes[0]

	def test_diferenca_de_formatacao_nao_reprova(self):
		"""REGRESSAO: o plano pode declarar 'NVDA+H' e o codigo escrever
		'kb:NVDA+h' -- mesmo atalho."""
		assert validate_declared_gestures(self._CODIGO, ["NVDA+H"]).ok is True

	def test_atalho_extra_no_codigo_nao_reprova(self):
		"""Um addon pode expor atalhos auxiliares que o usuario nao enumerou.
		O que nunca pode faltar e o que foi pedido."""
		c = self._CODIGO + '\t@script(gesture="kb:NVDA+j")\n\tdef script_x(self, g): pass\n'
		assert validate_declared_gestures(c, ["kb:nvda+h"]).ok is True

	def test_lista_vazia_nao_verifica_nada(self):
		"""Addon sem atalho (so menu, AppModule por evento, driver)."""
		assert validate_declared_gestures("x = 1", []).ok is True

	def test_sintaxe_invalida_faz_fail_open(self):
		"""REGRESSAO de um bug real desta implementacao: sem o fail-open
		explicito, codigo com SyntaxError caia no caminho de 'nenhum gesture
		declarado' e era reprovado por FUNCIONALIDADE FALTANDO -- diagnostico
		errado para um erro que outro degrau, mais barato, ja reporta certo."""
		assert validate_declared_gestures("def (", ["kb:nvda+h"]).ok is True


class TestNVDA060ControlTypes:
	"""API REMOVIDA no NVDA 2022.1 -- nao e depreciacao. O addon levanta
	AttributeError em runtime e a funcionalidade nao acontece, sem mensagem."""

	def test_role_por_atributo(self):
		r = validate_nvda060_controltypes("import controlTypes\nx = controlTypes.ROLE_BUTTON\n")
		assert r.ok is False
		assert "2022.1" in r.violacoes[0]

	def test_state_por_import(self):
		assert validate_nvda060_controltypes("from controlTypes import STATE_CHECKED\n").ok is False

	def test_api_moderna_passa(self):
		assert validate_nvda060_controltypes("import controlTypes\nx = controlTypes.Role.BUTTON\n").ok is True

	def test_atributo_parecido_de_outro_modulo_nao_reprova(self):
		"""Precisao: so `controlTypes.ROLE_*` conta, nao qualquer ROLE_."""
		assert validate_nvda060_controltypes("import meu\nx = meu.ROLE_ADMIN\n").ok is True

	def test_fail_open(self):
		assert validate_nvda060_controltypes("def (").ok is True


class TestWXA11Y013EventosDeTecla:
	"""Falha SILENCIOSA: o dev testa sem leitor de tela e funciona; o usuario
	cego usa e nao funciona."""

	def test_listctrl_com_evt_key_down(self):
		c = (
			"import wx\nclass D:\n\tdef f(self):\n"
			"\t\tself.lista = wx.ListCtrl(self)\n"
			"\t\tself.lista.Bind(wx.EVT_KEY_DOWN, self.h)\n"
		)
		r = validate_wx_a11y_013_key_events(c)
		assert r.ok is False
		assert "EVT_LIST_KEY_DOWN" in r.violacoes[0]

	def test_treectrl_sugere_evento_de_arvore(self):
		c = (
			"import wx\nclass D:\n\tdef f(self):\n"
			"\t\tself.arv = wx.TreeCtrl(self)\n"
			"\t\tself.arv.Bind(wx.EVT_CHAR, self.h)\n"
		)
		r = validate_wx_a11y_013_key_events(c)
		assert r.ok is False
		assert "EVT_TREE_KEY_DOWN" in r.violacoes[0]

	def test_evento_correto_passa(self):
		c = (
			"import wx\nclass D:\n\tdef f(self):\n"
			"\t\tself.lista = wx.ListCtrl(self)\n"
			"\t\tself.lista.Bind(wx.EVT_LIST_KEY_DOWN, self.h)\n"
		)
		assert validate_wx_a11y_013_key_events(c).ok is True

	def test_panel_nao_e_reportado(self):
		"""Precisao: em wx.Panel/wx.Dialog o EVT_KEY_DOWN funciona normalmente.
		Reportar aqui seria falso positivo."""
		c = (
			"import wx\nclass D:\n\tdef f(self):\n"
			"\t\tself.p = wx.Panel(self)\n"
			"\t\tself.p.Bind(wx.EVT_KEY_DOWN, self.h)\n"
		)
		assert validate_wx_a11y_013_key_events(c).ok is True

	def test_fail_open(self):
		assert validate_wx_a11y_013_key_events("def (").ok is True


class TestNVDA056MessageDialogEmThread:
	"""UI do wx fora da thread GUI costuma travar o processo do NVDA inteiro --
	o usuario cego perde fala e braille e so recupera reiniciando."""

	def test_dialog_em_thread_sem_callafter(self):
		c = (
			"import wx, threading\nclass G:\n"
			"\tdef go(self):\n\t\tthreading.Thread(target=self.trab).start()\n"
			'\tdef trab(self):\n\t\td = wx.MessageDialog(None, "x")\n\t\td.ShowModal()\n'
		)
		r = validate_nvda056_messagedialog_thread(c)
		assert r.ok is False
		assert "wx.CallAfter" in r.violacoes[0]

	def test_com_callafter_passa(self):
		c = (
			"import wx, threading\nclass G:\n"
			"\tdef go(self):\n\t\tthreading.Thread(target=self.trab).start()\n"
			"\tdef trab(self):\n\t\twx.CallAfter(self.mostra)\n"
			'\tdef mostra(self):\n\t\td = wx.MessageDialog(None, "x")\n'
		)
		assert validate_nvda056_messagedialog_thread(c).ok is True

	def test_dialog_na_thread_principal_passa(self):
		"""Precisao: o uso normal nunca pode ser reportado."""
		c = 'import wx\nclass G:\n\tdef script_x(self, g):\n\t\td = wx.MessageDialog(None, "x")\n'
		assert validate_nvda056_messagedialog_thread(c).ok is True

	def test_sem_thread_nenhuma_passa(self):
		assert validate_nvda056_messagedialog_thread('import wx\nd = wx.MessageDialog(None, "x")\n').ok is True

	def test_fail_open(self):
		assert validate_nvda056_messagedialog_thread("def (").ok is True


class TestTabelaDeValidadoresDoCodeGenerator:
	"""README Regra 5: a Fase 2 tinha 3 validadores com bloco proprio; virar 6
	seria 6 repeticoes do mesmo fluxo. A tabela e a fonte unica."""

	def test_todos_os_seis_estao_na_tabela(self):
		from nvdastudio.sub_agents.code_generator import _AST_VALIDATORS

		ids = {rid for rid, _, _ in _AST_VALIDATORS}
		assert ids == {
			"NVDA-019", "WX-A11Y-001", "WX-A11Y-002",
			"NVDA-060", "WX-A11Y-013", "NVDA-056",
		}

	def test_cada_entrada_tem_descricao_util_e_callable(self):
		from nvdastudio.sub_agents.code_generator import _AST_VALIDATORS

		for rid, descricao, fn in _AST_VALIDATORS:
			assert callable(fn), rid
			assert len(descricao) > 20, f"{rid} sem descricao acionavel para o prompt de correcao"

	def test_nvda019_e_o_unico_pulado_em_controller_client(self):
		"""gettext do NVDA nao se aplica a programa externo; as regras de wx e
		as de API removida continuam valendo."""
		from nvdastudio.sub_agents.code_generator import _SKIP_EM_CONTROLLER_CLIENT

		assert _SKIP_EM_CONTROLLER_CLIENT == frozenset({"NVDA-019"})
