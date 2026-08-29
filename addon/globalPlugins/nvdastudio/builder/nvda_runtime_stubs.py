import sys
import types


class _Permissive:
	"""Aceita qualquer chamada/atributo/uso como context manager ou decorator
	sem lancar excecao -- cobre a maior parte da API do NVDA que o codigo
	gerado so CHAMA (nao subclassa)."""

	def __call__(self, *args, **kwargs):
		# Usado tanto como funcao comum (ui.message(...)) quanto como
		# FABRICA de decorator (@script(description=...)) -- nesse ultimo
		# caso, o unico argumento posicional costuma ser a funcao decorada;
		# devolve ela sem modificar pra nao quebrar chamadas subsequentes
		# tipo self.script_meuComando(...).
		if len(args) == 1 and callable(args[0]) and not kwargs:
			return args[0]
		return _Permissive()

	def __getattr__(self, _name):
		return _Permissive()

	def __getitem__(self, _key):
		return _Permissive()

	def __setitem__(self, _key, _value):
		pass

	def __enter__(self):
		return self

	def __exit__(self, *_exc):
		return False

	def __iter__(self):
		return iter([])

	def __bool__(self):
		return True

	def __repr__(self):
		return "<stub>"


class GlobalPlugin:
	"""Base real pra `class X(globalPluginHandler.GlobalPlugin)` -- precisa
	ser classe de verdade (nao instancia), MagicMock nao serve de base."""
	def __init__(self, *args, **kwargs):
		pass

	def terminate(self):
		pass

	def __getattr__(self, _name):
		return _Permissive()


class AppModule(GlobalPlugin):
	pass


class SynthDriver:
	def __init__(self, *args, **kwargs):
		pass

	def __getattr__(self, _name):
		return _Permissive()


class SettingsPanel:
	def __init__(self, *args, **kwargs):
		pass

	def __getattr__(self, _name):
		return _Permissive()

	def makeSettings(self, *args, **kwargs):
		pass


class _WxDialog:
	def __init__(self, *args, **kwargs):
		pass

	def __getattr__(self, _name):
		return _Permissive()


def _make_module(name: str, **attrs) -> types.ModuleType:
	mod = types.ModuleType(name)
	for k, v in attrs.items():
		setattr(mod, k, v)
	mod.__getattr__ = lambda _n: _Permissive()  # type: ignore[attr-defined]
	return mod


def install() -> None:
	"""Registra os stubs em sys.modules -- idempotente, chamar antes de
	importar qualquer codigo de addon gerado."""
	stubs: dict[str, types.ModuleType] = {
		"wx": _make_module("wx", Dialog=_WxDialog, Panel=_WxDialog, Frame=_WxDialog),
		"gui": _make_module("gui", SettingsPanel=SettingsPanel, mainFrame=_Permissive()),
		"gui.guiHelper": _make_module("gui.guiHelper"),
		"gui.settingsDialogs": _make_module(
			"gui.settingsDialogs", SettingsPanel=SettingsPanel, NVDASettingsDialog=_Permissive(),
		),
		"globalPluginHandler": _make_module("globalPluginHandler", GlobalPlugin=GlobalPlugin),
		"appModuleHandler": _make_module("appModuleHandler", AppModule=AppModule),
		"synthDriverHandler": _make_module(
			"synthDriverHandler", SynthDriver=SynthDriver, VoiceInfo=_Permissive(),
		),
		"brailleDisplayDriver": _make_module("brailleDisplayDriver", BrailleDisplayDriver=SynthDriver),
		"addonHandler": _make_module("addonHandler", initTranslation=_Permissive()),
		"scriptHandler": _make_module("scriptHandler", script=_Permissive()),
		"logHandler": _make_module("logHandler", log=_Permissive()),
		"config": _make_module("config", conf=_Permissive()),
		"ui": _make_module("ui"),
		"api": _make_module("api"),
		"tones": _make_module("tones"),
		"speech": _make_module("speech"),
		"speech.priorities": _make_module("speech.priorities"),
		"braille": _make_module("braille"),
		"brailleInput": _make_module("brailleInput"),
		"controlTypes": _make_module("controlTypes"),
		"textInfos": _make_module("textInfos"),
		"NVDAState": _make_module("NVDAState"),
		"globalVars": _make_module("globalVars"),
		"core": _make_module("core"),
		"queueHandler": _make_module("queueHandler"),
		"eventHandler": _make_module("eventHandler"),
		"treeInterceptorHandler": _make_module("treeInterceptorHandler"),
		"NVDAObjects": _make_module("NVDAObjects"),
		"winUser": _make_module("winUser"),
		"winAPI": _make_module("winAPI"),
	}
	for name, mod in stubs.items():
		if name not in sys.modules:
			sys.modules[name] = mod
	# Alguns modulos NVDA tem submodulos referenciados via "from X import Y" --
	# stub permissivo como fallback pra qualquer coisa nao explicitamente
	# listada acima (nunca unittest.mock -- ver nota de MODULE_VERSION 1.0.0).
	sys.modules.setdefault("addonHandler.addonVersionCheck", _make_module("addonHandler.addonVersionCheck"))
