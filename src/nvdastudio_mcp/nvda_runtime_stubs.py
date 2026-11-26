import os
import sys
import inspect
import tempfile
import types


# REALISTIC config directory for validation in the sandbox. Add-ons read
# NVDAState.WritePaths.configDir (a STRING) and use it in os.path.join. The
# generic stub (_Permissive) returned a truthy NON-string mock, and os.path.join
# rejected a HistoryManager that would work out there). A real, disposable
# path makes the common pattern (read configDir and join a file) work
# in validation as it would inside NVDA.
_STUB_CONFIG_DIR = os.path.join(tempfile.gettempdir(), "nvdastudio_stub_config")


class _StubWritePaths:
	"""Mirrors nvda/source/NVDAState.WritePaths -- the paths that add-ons read
	often, as real STRINGS instead of a permissive mock."""
	configDir = _STUB_CONFIG_DIR
	addonsDir = os.path.join(_STUB_CONFIG_DIR, "addons")
	addonStoreDir = os.path.join(_STUB_CONFIG_DIR, "addonStore")


def _stub_should_write_to_disk() -> bool:
	# Validation NEVER really writes to disk -- add-ons check this before
	# saving; False keeps validation read-only.
	return False


class _Permissive:
	"""Accepts any call/attribute/use as a context manager or decorator
	without raising -- covers most of the NVDA API that the generated
	code only CALLS (does not subclass)."""

	def __call__(self, *args, **kwargs):
		# Used both as a plain function (ui.message(...)) and as a
		# decorator FACTORY (@script(description=...)) -- in the latter
		# case, the only positional argument is usually the decorated function;
		# it returns it unmodified so as not to break subsequent calls
		# such as self.script_myCommand(...).
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
	"""Real base for `class X(globalPluginHandler.GlobalPlugin)` -- it must
	be a real class (not an instance), a MagicMock does not work as a base."""
	def __init__(self, *args, **kwargs):
		super().__init__()

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


def _init_translation_stub() -> None:
	"""
	Imitates the real NVDA `addonHandler.initTranslation()`.

	NVDA injects `_` (and the gettext variants) into the GLOBALS OF THE MODULE THAT
	CALLED IT -- which is why every correct add-on does `import addonHandler` +
	`addonHandler.initTranslation()` and then uses `_("text")` freely.

	The old stub was a no-op. Measured consequence: a MINIMALLY
	CORRECT add-on by this project's own NVDA-019 rule --

	    import addonHandler
	    addonHandler.initTranslation()
	    class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	        scriptCategory = _("Meu Addon")

	rejecting correct code. The check was wrong, not the add-on.

	Injecting into the CALLER's globals, and not into builtins, preserves the real
	semantics: a module that uses gettext WITHOUT initializing keeps breaking, which is
	exactly the defect the NVDA-003 rule exists to catch.
	"""
	quadro = inspect.currentframe()
	chamador = quadro.f_back if quadro is not None else None
	if chamador is None:  # pragma: no cover - CPython always gives the frame
		return
	globais = chamador.f_globals
	globais.setdefault("_", lambda texto: texto)
	globais.setdefault("ngettext", lambda s, p, n: s if n == 1 else p)
	globais.setdefault("pgettext", lambda _ctx, texto: texto)
	globais.setdefault("npgettext", lambda _ctx, s, p, n: s if n == 1 else p)


def _make_module(name: str, **attrs) -> types.ModuleType:
	mod = types.ModuleType(name)
	for k, v in attrs.items():
		setattr(mod, k, v)
	mod.__getattr__ = lambda _n: _Permissive()  # type: ignore[method-assign]
	return mod


# NVDA packages whose submodules can be resolved with a permissive stub.
_PACOTES_NVDA = (
	"gui", "config", "speech", "NVDAObjects", "addonHandler", "braille",
	"synthDriverHandler", "brailleDisplayDrivers", "textInfos", "documentBase",
	"appModules", "globalCommands", "eventHandler", "inputCore",
)


class _NVDASubmoduleFinder:
	"""Resolves `nvdaPackage.anything` with a permissive module."""

	def find_module(self, fullname, path=None):  # pragma: no cover - old API
		return None

	def find_spec(self, fullname, path=None, target=None):
		topo = fullname.split(".")[0]
		if "." not in fullname or topo not in _PACOTES_NVDA:
			return None
		import importlib.machinery

		return importlib.machinery.ModuleSpec(fullname, _CarregadorPermissivo())


class _CarregadorPermissivo:
	def create_module(self, spec):
		return _make_module(spec.name)

	def exec_module(self, module):
		return None


def install() -> None:
	"""Registers the stubs in sys.modules -- idempotent, call before
	importing any generated add-on code."""
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
		"addonHandler": _make_module("addonHandler", initTranslation=_init_translation_stub),
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
		"NVDAState": _make_module(
			"NVDAState",
			WritePaths=_StubWritePaths,
			shouldWriteToDisk=_stub_should_write_to_disk,
		),
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
	# Some NVDA modules have submodules referenced via "from X import Y" --
	# permissive stub as a fallback for anything not explicitly
	# listed above (never unittest.mock -- see the MODULE_VERSION 1.0.0 note).
	sys.modules.setdefault("addonHandler.addonVersionCheck", _make_module("addonHandler.addonVersionCheck"))

	# Any SUBMODULE of a known NVDA package resolves by itself.
	#
	# Before, each submodule had to be listed by hand, and one that was missing
	# (gui/message.py is one of the files the project itself injects into
	# add-ons) made us reject whoever used an API.
	#
	# It only covers submodules of NVDA packages. Importing a third-party
	# library keeps failing, which is what the check exists to catch.
	if not any(isinstance(f, _NVDASubmoduleFinder) for f in sys.meta_path):
		sys.meta_path.append(_NVDASubmoduleFinder())
