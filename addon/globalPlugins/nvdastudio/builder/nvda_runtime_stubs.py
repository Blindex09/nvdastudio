import os
import sys
import inspect
import tempfile
import types


# Diretorio de config REALISTA para a validacao em sandbox. Addons leem
# NVDAState.WritePaths.configDir (uma STRING) e a usam em os.path.join. O stub
# generico (_Permissive) devolvia um mock truthy NAO-string, e o os.path.join
# quebrava com TypeError -- um FALSO-POSITIVO que reprovava addon CORRETO (achado
# no E2E complexo AssistenteLeituraGemini, 2026-09-06: o gate de execucao
# rejeitava um HistoryManager que la fora funcionaria). Um caminho real e
# descartavel faz o padrao comum (ler configDir e juntar um arquivo) funcionar
# na validacao como funcionaria dentro do NVDA.
_STUB_CONFIG_DIR = os.path.join(tempfile.gettempdir(), "nvdastudio_stub_config")


class _StubWritePaths:
	"""Espelha nvda/source/NVDAState.WritePaths -- os caminhos que addons leem
	com frequencia, como STRINGS reais em vez de mock permissivo."""
	configDir = _STUB_CONFIG_DIR
	addonsDir = os.path.join(_STUB_CONFIG_DIR, "addons")
	addonStoreDir = os.path.join(_STUB_CONFIG_DIR, "addonStore")


def _stub_should_write_to_disk() -> bool:
	# A validacao NUNCA escreve em disco de verdade -- addons checam isto antes
	# de salvar; False mantem a validacao read-only (Regra 9 / blast radius).
	return False


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


def _init_translation_stub() -> None:
	"""
	Imita `addonHandler.initTranslation()` do NVDA de verdade.

	O NVDA injeta `_` (e as variantes de gettext) nos GLOBAIS DO MODULO QUE
	CHAMOU -- e por isso que todo addon correto faz `import addonHandler` +
	`addonHandler.initTranslation()` e depois usa `_("texto")` livremente.

	O stub antigo era um no-op. Consequencia medida: um addon MINIMAMENTE
	CORRETO pela propria regra NVDA-019 deste projeto --

	    import addonHandler
	    addonHandler.initTranslation()
	    class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	        scriptCategory = _("Meu Addon")

	-- falhava a verificacao de execucao com NameError. Nos relatorios E2E: 6
	steps reprovados por "Erro de execucao real", 1.757.209 tokens gastos
	recusando codigo certo. A verificacao estava errada, nao o addon.

	Injetar nos globais do CHAMADOR, e nao em builtins, preserva a semantica
	real: um modulo que usa gettext SEM inicializar continua quebrando, que e
	exatamente o defeito que a regra NVDA-003 existe para pegar.
	"""
	quadro = inspect.currentframe()
	chamador = quadro.f_back if quadro is not None else None
	if chamador is None:  # pragma: no cover - CPython sempre da o frame
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


# Pacotes do NVDA cujos submodulos podem ser resolvidos com stub permissivo.
_PACOTES_NVDA = (
	"gui", "config", "speech", "NVDAObjects", "addonHandler", "braille",
	"synthDriverHandler", "brailleDisplayDrivers", "textInfos", "documentBase",
	"appModules", "globalCommands", "eventHandler", "inputCore",
)


class _NVDASubmoduleFinder:
	"""Resolve `pacoteNVDA.qualquercoisa` com um modulo permissivo."""

	def find_module(self, fullname, path=None):  # pragma: no cover - API antiga
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
	# Alguns modulos NVDA tem submodulos referenciados via "from X import Y" --
	# stub permissivo como fallback pra qualquer coisa nao explicitamente
	# listada acima (nunca unittest.mock -- ver nota de MODULE_VERSION 1.0.0).
	sys.modules.setdefault("addonHandler.addonVersionCheck", _make_module("addonHandler.addonVersionCheck"))

	# Qualquer SUBMODULO de um pacote NVDA conhecido resolve sozinho.
	#
	# Antes, cada submodulo precisava estar listado a mao, e um que faltasse
	# derrubava a verificacao de execucao com ModuleNotFoundError. Medido na
	# rodada 7: `from gui.message import MessageDialog` reprovou o cg_core --
	# e gui/message.py e um dos arquivos que o proprio projeto injeta nos
	# prompts (_DOCS_CORE em nvda_context.py). Ou seja: ensinavamos o modelo a
	# usar uma API e reprovavamos quem usasse.
	#
	# So cobre submodulos de pacotes NVDA. Import de biblioteca de terceiros
	# continua falhando, que e o que a verificacao existe para pegar.
	if not any(isinstance(f, _NVDASubmoduleFinder) for f in sys.meta_path):
		sys.meta_path.append(_NVDASubmoduleFinder())
