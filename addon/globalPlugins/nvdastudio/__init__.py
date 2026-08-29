import builtins
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	# addonHandler.initTranslation() injeta "_" em builtins em runtime (padrao
	# gettext do NVDA); o fallback abaixo faz o mesmo fora do NVDA real. mypy
	# nao enxerga atribuicao dinamica em builtins, entao declaramos aqui.
	def _(s: str) -> str: ...

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_LIB_BUNDLED = os.path.join(_THIS_DIR, "lib")
if os.path.isdir(_LIB_BUNDLED) and _LIB_BUNDLED not in sys.path:
	sys.path.insert(0, _LIB_BUNDLED)

import wx  # noqa: E402
import gui as nvda_gui  # noqa: E402
import globalPluginHandler  # noqa: E402
import addonHandler  # noqa: E402
from gui.settingsDialogs import NVDASettingsDialog  # noqa: E402
from scriptHandler import script  # noqa: E402

from .gui.studio_dialog import NVDAStudioDialog  # noqa: E402
from .gui.settings_panel import NVDAStudioSettingsPanel, get_llm_provider, get_api_key, FirstRunSetupDialog  # noqa: E402
from .utils.logger import get_logger  # noqa: E402

addonHandler.initTranslation()

if not hasattr(builtins, "_"):
	builtins._ = lambda s: s  # type: ignore[attr-defined]

MODULE_VERSION = "2.4.0"
_logger = get_logger("global_plugin")

_nvdastudio_dialog_instance = None

def _on_nvdastudio_dialog_close(event):
	global _nvdastudio_dialog_instance
	_nvdastudio_dialog_instance = None
	try:
		nvda_gui.mainFrame.postPopup()
	except Exception as exc:
		_logger.debug("[DEBUG] postPopup indisponivel ao fechar dialogo: %s", exc)
	event.Skip()

_TRIGGER_FILE = os.path.join(os.environ.get("APPDATA", ""), "nvda", "nvdastudio_open.trigger")
_TRIGGER_INTERVAL_MS = 500

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = "NVDAStudio"

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		if NVDAStudioSettingsPanel not in NVDASettingsDialog.categoryClasses:
			NVDASettingsDialog.categoryClasses.append(NVDAStudioSettingsPanel)
		self._trigger_timer = wx.Timer()
		self._trigger_timer.Bind(wx.EVT_TIMER, self._check_trigger)
		self._trigger_timer.Start(_TRIGGER_INTERVAL_MS)
		_logger.info("[OK] NVDAStudio inicializado. version=%s", MODULE_VERSION)

	def terminate(self, *args, **kwargs):
		self._trigger_timer.Stop()
		if NVDAStudioSettingsPanel in NVDASettingsDialog.categoryClasses:
			NVDASettingsDialog.categoryClasses.remove(NVDAStudioSettingsPanel)
		_logger.info("[OK] NVDAStudio encerrado.")
		super().terminate(*args, **kwargs)

	@script(
		gesture="kb:NVDA+shift+n",
		description=_("Abre o NVDAStudio - Criador de Addons com Inteligencia Artificial"),
		category="NVDAStudio"
	)
	def script_abrirNVDAStudio(self, gesture):
		wx.CallAfter(self._open_dialog)

	@script(
		gesture="kb:NVDA+shift+comma",
		description=_("Abre as configuracoes do NVDAStudio no NVDA Settings"),
		category="NVDAStudio"
	)
	def script_abrirConfiguracoes(self, gesture):
		wx.CallAfter(self._open_settings)

	def _open_dialog(self):
		global _nvdastudio_dialog_instance
		if _nvdastudio_dialog_instance is not None:
			try:
				if _nvdastudio_dialog_instance.IsShown():
					_nvdastudio_dialog_instance.Raise()
					_nvdastudio_dialog_instance.SetFocus()
					return
			except Exception as exc:
				_logger.debug("[DEBUG] Dialogo anterior nao respondeu (provavelmente destruido): %s", exc)
			_nvdastudio_dialog_instance = None

		provider = get_llm_provider()
		if not get_api_key(provider):
			setup = FirstRunSetupDialog(nvda_gui.mainFrame)
			nvda_gui.mainFrame.prePopup()
			result = setup.ShowModal()
			setup.Destroy()
			nvda_gui.mainFrame.postPopup()
			if result != wx.ID_OK:
				return

		nvda_gui.mainFrame.prePopup()
		_nvdastudio_dialog_instance = NVDAStudioDialog(nvda_gui.mainFrame)
		_nvdastudio_dialog_instance.Bind(wx.EVT_CLOSE, _on_nvdastudio_dialog_close)
		_nvdastudio_dialog_instance.Show()
		_logger.info("[OK] Dialog NVDAStudio aberto.")

	def _check_trigger(self, event=None):
		if os.path.isfile(_TRIGGER_FILE):
			try:
				os.remove(_TRIGGER_FILE)
			except OSError:
				pass
			_logger.info("[TRIGGER] Arquivo trigger detectado — abrindo dialogo.")
			self._open_dialog()

	def _open_settings(self):
		try:
			nvda_gui.mainFrame._popupSettingsDialog(NVDASettingsDialog, NVDAStudioSettingsPanel)
			_logger.info("[OK] NVDA Settings aberto na categoria NVDAStudio.")
		except Exception as exc:
			_logger.error("[ERRO] Falha ao abrir NVDA Settings: %s", exc)
