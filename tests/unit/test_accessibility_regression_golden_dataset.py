from dataclasses import dataclass

from nvdastudio.sub_agents.ast_validator import (
	validate_nvda019,
	validate_wx_a11y,
	validate_wx_a11y_002_accelerators,
)
from nvdastudio.builder.code_sandbox import CodeSandbox


@dataclass
class GoldenCase:
	"""Um caso do dataset: nome, codigo de addon completo, e o que se
	espera encontrar (ou nao encontrar) em cada checagem."""
	nome: str
	codigo: str
	espera_nvda019_ok: bool = True
	espera_wx_a11y_ok: bool = True
	espera_wx_a11y_002_ok: bool = True
	espera_bindgesture_aviso: bool = False


_GOLDEN_DATASET: list[GoldenCase] = [
	GoldenCase(
		nome="addon_minimo_conforme",
		codigo=(
			"import addonHandler\n"
			"import globalPluginHandler\n"
			"import ui\n\n"
			"addonHandler.initTranslation()\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef __init__(self, *args, **kwargs):\n"
			"\t\tsuper().__init__(*args, **kwargs)\n"
			"\t\t# Translators: mensagem de boas-vindas\n"
			"\t\tui.message(_(\"Addon carregado\"))\n"
		),
	),
	GoldenCase(
		nome="traducao_sem_comentario_translators",
		codigo=(
			"import addonHandler\n"
			"import globalPluginHandler\n"
			"import ui\n\n"
			"addonHandler.initTranslation()\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef __init__(self, *args, **kwargs):\n"
			"\t\tsuper().__init__(*args, **kwargs)\n"
			"\t\tui.message(_(\"Addon carregado\"))\n"
		),
		espera_nvda019_ok=False,
	),
	GoldenCase(
		nome="dialog_com_settings_panel_conforme",
		codigo=(
			"import wx\n"
			"import gui\n\n"
			"class MeuDialogo(wx.Dialog):\n"
			"\tdef __init__(self, parent):\n"
			"\t\tsuper().__init__(parent, title=\"Config\")\n"
			"\t\tself.txt = wx.TextCtrl(self)\n"
			"\t\tself.txt.SetName(\"Campo de configuracao\")\n"
			"\t\ttable = wx.AcceleratorTable([])\n"
			"\t\tself.SetAcceleratorTable(table)\n"
		),
	),
	GoldenCase(
		nome="textctrl_sem_setname",
		codigo=(
			"import wx\n\n"
			"class MeuDialogo(wx.Dialog):\n"
			"\tdef __init__(self, parent):\n"
			"\t\tsuper().__init__(parent, title=\"Config\")\n"
			"\t\tself.txt = wx.TextCtrl(self)\n"
		),
		espera_wx_a11y_ok=False,
	),
	GoldenCase(
		nome="panel_instanciado_sem_accelerator_table",
		codigo=(
			"import wx\n\n"
			"class MeuDialogo(wx.Dialog):\n"
			"\tdef __init__(self, parent):\n"
			"\t\tsuper().__init__(parent)\n"
			"\t\tself.painel = wx.Panel(self)\n"
			"\t\tself.btn = wx.Button(self.painel, label=\"OK\")\n"
			"\t\tself.btn.SetName(\"Botao OK\")\n"
		),
		espera_wx_a11y_002_ok=False,
	),
]


class TestGoldenDatasetAcessibilidade:
	"""Roda o dataset inteiro -- cada caso e um sub-teste parametrizado."""

	def test_dataset_nao_esta_vazio(self):
		assert len(_GOLDEN_DATASET) >= 5, (
			"golden dataset de acessibilidade deveria crescer com falhas "
			"reais, nao ficar estatico -- ver secao 14 de "
			"conceitos-ia-para-desenvolvimento-de-software.md"
		)

	def test_nomes_unicos(self):
		nomes = [c.nome for c in _GOLDEN_DATASET]
		assert len(nomes) == len(set(nomes)), "casos do dataset devem ter nomes unicos"

	def test_nvda019_bate_expectativa_em_todos_os_casos(self):
		for caso in _GOLDEN_DATASET:
			resultado = validate_nvda019(caso.codigo)
			assert resultado.ok == caso.espera_nvda019_ok, (
				f"caso '{caso.nome}': NVDA-019 esperado ok={caso.espera_nvda019_ok}, "
				f"recebido ok={resultado.ok} violacoes={resultado.violacoes}"
			)

	def test_wx_a11y_bate_expectativa_em_todos_os_casos(self):
		for caso in _GOLDEN_DATASET:
			resultado = validate_wx_a11y(caso.codigo)
			assert resultado.ok == caso.espera_wx_a11y_ok, (
				f"caso '{caso.nome}': WX-A11Y esperado ok={caso.espera_wx_a11y_ok}, "
				f"recebido ok={resultado.ok} violacoes={resultado.violacoes}"
			)

	def test_wx_a11y_002_bate_expectativa_em_todos_os_casos(self):
		for caso in _GOLDEN_DATASET:
			resultado = validate_wx_a11y_002_accelerators(caso.codigo)
			assert resultado.ok == caso.espera_wx_a11y_002_ok, (
				f"caso '{caso.nome}': WX-A11Y-002 esperado ok={caso.espera_wx_a11y_002_ok}, "
				f"recebido ok={resultado.ok} violacoes={resultado.violacoes}"
			)


class TestGoldenDatasetBindGestureDinamico:
	"""
	Caso do dataset com bindGesture() dinamico sem unbind -- item #5
	(Keyboard/Focus Management, code_sandbox.py 1.3.0) exercitado junto,
	nao isolado, porque um addon real combina classe principal + bind
	dinamico no mesmo arquivo.
	"""

	def test_bindgesture_dinamico_sem_unbind_e_detectado_no_addon_completo(self):
		codigo = (
			"import globalPluginHandler\n\n"
			"class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
			"\tdef atualizarAtalho(self, gesture):\n"
			"\t\tself.bindGesture(gesture, \"minhaAcao\")\n"
		)
		resultado = CodeSandbox().validate_addon_execution(
			{"globalPlugins/MeuAddon/__init__.py": codigo}
		)
		assert resultado.success is True
		assert "AVISO_BINDGESTURE_SEM_UNBIND" in resultado.stdout
