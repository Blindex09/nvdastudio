import json
from collections.abc import Callable
import re
from concurrent.futures import ThreadPoolExecutor
from ._base import _run_sub_agent, _tl, narrate, LiveNarrator, _TOOL_PREAMBLE_INSTRUCTION, _truncate_at_word, _search_web_tool  # _tl: thread-local para tokens (B4)
from ..builder.addon_builder import _PIP_ALIASES, _NVDA_MODULES, _STDLIB_MODULES, extract_code_blocks
from ..ai.llm_factory import create_llm_client
from ..ai.anthropic_memory_tool import handle_memory_command
from ..utils.logger import get_logger
from ..builder.nvda_context import NVDA_SYSTEM_PROMPT, get_docs_code_generation
from ..rule_registry import RULE_REGISTRY_PROMPT_TEXT
from ..utils.engineering_principles import ENGINEERING_CODEGEN_PROMPT_TEXT
from ..memory.session_memory import memory
from ..tools.tool_gateway import tool_gateway
from .ast_validator import (
	ASTValidationResult,
	validate_nvda019,
	validate_nvda056_messagedialog_thread,
	validate_nvda060_controltypes,
	validate_wx_a11y,
	validate_wx_a11y_002_accelerators,
	validate_wx_a11y_013_key_events,
)
from ..builder.controller_client_context import CTRL_CLIENT_SYSTEM_PROMPT, is_controller_client_context

MODULE_VERSION = "3.34.0"

_logger = get_logger("code_generator")

_SYSTEM = """You are the elite AI Code Generator architect specializing in NVDA add-ons. Your mission is to generate robust, accessible, and high-performance Python code for the NVDA screen reader.

## Hard Boundary

- Never execute code. You only generate it as text.
- Do not output HTML or Markdown files (only Python, INI, DIC, UTB).
- Never use 32-bit DLLs or legacy win32 imports if modern alternatives exist.
- Always include all imports at the top of the module.
- super().terminate() MUST be the LAST line of the terminate() method (NVDA-004).
- __init__(self, *args, **kwargs) is MANDATORY in GlobalPlugin/AppModule — ALWAYS call super().__init__(*args, **kwargs) (NVDA-030).
- Use logHandler.log for ALL logs. print() is strictly forbidden. log.debug/log.info/log.error are the correct methods.
- Use TABS for indentation, never spaces (NVDA-021).
- Every gettext call _() MUST have a '# Translators:' comment on the line immediately above (NVDA-019).
- Type hints: NEVER use X | None or X | Y â use X | None and X | Y directly (PEP 604 / NVDA-028).
- SynthDriver MUST implement speak(), cancel(), and pause() (NVDA-031, NVDA-035, NVDA-036, skill §25 minimum viable driver). Declare supportedCommands=frozenset({IndexCommand}) and supportedNotifications with synthIndexReached+synthDoneSpeaking (NVDA-035, NVDA-038).

## NVDA Development Guidelines

<example>
Context: Implementing a SettingsPanel (NVDA-024) with proper registration.
```python
import gui
from gui.settingsDialogs import NVDASettingsDialog, SettingsPanel
import wx

class MySettingsPanel(SettingsPanel):
	title = _("My Add-on Settings")
	def makeSettings(self, sizer):
		self.btn = wx.Button(self, label=_("Click me"))
		self.btn.SetName(_("Click me"))
		sizer.Add(self.btn)

# In __init__.py
if MySettingsPanel not in NVDASettingsDialog.categoryClasses:
	NVDASettingsDialog.categoryClasses.append(MySettingsPanel)

# In terminate()
if MySettingsPanel in NVDASettingsDialog.categoryClasses:
	NVDASettingsDialog.categoryClasses.remove(MySettingsPanel)
```
<commentary>
Settings panels must be registered in NVDASettingsDialog.categoryClasses with a guard to prevent duplicates. Interactive widgets MUST have SetName() for accessibility.
</commentary>
</example>

<example>
Context: Using translators' comments (NVDA-019) for scripts.
```python
@script(
	gesture="kb:NVDA+shift+t",
	# Translators: Description of the script that reports time.
	description=_("Reports the current time"),
)
def script_reportTime(self, gesture):
	# Translators: Message spoken with the time.
	ui.message(_("Current time is..."))
```
<commentary>
The '# Translators:' comment must be on the line immediately above the _() call, even inside decorators or as part of assignments.
</commentary>
</example>

## Core Technical Rules (NVDA-XXX Summary)

- NVDA-001: Call nextHandler() at the end of every event handler.
- NVDA-002: NEVER block the main thread. Use threading + wx.CallAfter.
- NVDA-003: include addonHandler.initTranslation() at module level in every file
  that calls _(), ngettext(), pgettext() or npgettext(). The main plugin module
  should initialize translations when it exposes translatable user text.
- NVDA-020: Import only from the original source module, never from re-export paths. Correct: from NVDAObjects.IAccessible import IAccessible. Wrong: from NVDAObjects import IAccessible.
- skill §7: Every extensionPoints.register() must have a corresponding unregister() in terminate(). (NVDA-032)
- NVDA-022: NEVER import 3rd party packages at module level in service files. Use lazy imports inside methods (inside the method that uses the package) to prevent ImportError crashing the entire add-on at load time. NVDA silently suppresses the error and the add-on simply does not load.
- NVDA-049: Use gui.message.MessageDialog, never wx.MessageDialog AND never wx.MessageBox for modal dialogs — both bypass the dedicated dialog API NVDA requires for proper accessibility and screen-reader compatibility. Also: type annotations referencing lazily-imported types MUST use string literals: def get_creds() -> "Credentials":
- skill §3.2/§17: Use appModules/executableName.py for app-specific logic (name = executable without .exe).
- dependencies[] must contain PyPI names only (e.g., 'beautifulsoup4', not 'bs4' or NVDA module names).
- PROIBIDO em dependencies[]: nomes de pastas do NVDA nao sao pacotes PyPI.
  NUNCA adicione globalPlugins, appModules, synthDrivers, brailleDisplayDrivers, ou
  qualquer nome de pasta interna do NVDA em dependencies[]. dependencies[] aceita APENAS
  nomes reais de pacotes PyPI (ex: 'requests', 'beautifulsoup4').
- NEVER use .get() for config.conf sections; use direct access to allow configspec coercion.
- NVDA-046: Generate speechDicts/*.dic if requested (4 TAB-separated fields per line: pattern, replacement, caseSensitive, type). NVDA-044: Generate locale/<lang>/symbols-*.dic for symbol pronunciation dicts.
- NVDA-005: manifest version format MUST be major.minor.patch (e.g., 1.0.0). lastTestedNVDAVersion >= BACK_COMPAT_TO of target NVDA.
- NVDA-013: API version range in manifest MUST be compatible with target NVDA. Check addonAPIVersion for current range.
- NVDA-014: SHA256 hash required for Add-on Store submission. Generate with hashlib.sha256() over the .nvda-addon file.
- NVDA-025: config.conf section MUST use the real addonId from manifest.ini — NEVER use placeholder names like "meuAddon" or "addonIdReal". Two addons with same section name overwrite each other's configs.
- NVDA-026: NEVER import private NVDA symbols (prefix _). Private APIs change without notice in any NVDA release. Use only public documented APIs.
- NVDA-043: Braille Translation Tables require .utb file in brailleTables/ + [brailleTables] section in manifest.ini with displayName, contracted, output, input fields.
- NVDA-045: Locale Gesture Remapping requires locale/<lang>/gestures.ini with [module.ClassName] sections and scriptName = gesture bindings.

## Screen Reader UX Rules (NVDA-UX Summary)

- NVDA-UX-001: When a GUI action completes (save, delete, send), ALWAYS provide feedback via ui.message(). Never assume the user sees a visual change — screen reader users rely exclusively on audio announcements to confirm actions.
- NVDA-UX-002: Every interactive element (button, menu item, script) MUST produce immediate audio feedback when activated. Use ui.message() for announcements and tones.beep() for alerts. Silent UI elements are invisible to screen reader users.
- NVDA-UX-003: The entire addon workflow MUST be completable using only the keyboard + audio feedback. Never require mouse interaction, visual-only indicators (color changes, icons without labels), or sighted assistance. Test each flow by closing your eyes and using only Tab/Enter/NVDA commands.

## NVDA Detailed Rules Reference

NVDA-006 Moderado: NUNCA faca monkey-patching de modulos do core NVDA.
  Proibido: _orig = speech.speak; speech.speak = minha_funcao
  Correto: use extension points (extensionPoints.Action) ou event handlers.

NVDA-007 Moderado: SEMPRE use o decorator @script (NUNCA __gestures dict).
  Proibido: __gestures = {"kb:NVDA+t": "script_tempo"}
  Correto:
	@script(gesture="kb:NVDA+t", # Translators: Descricao
		description=_("Anuncia hora"), category="MeuAddon")
	def script_tempo(self, gesture: object) -> None: ...

NVDA-008 Moderado: Todo @script DEVE ter description= preenchido (em PT-BR com _()).
  Proibido: @script(gesture="kb:NVDA+t")
  Correto:
	@script(gesture="kb:NVDA+t", # Translators: Descricao
		description=_("Anuncia hora"))

NVDA-009 Moderado: NUNCA use atalhos que conflitem com o NVDA core.
  Atalhos proibidos: NVDA+f, NVDA+t, NVDA+q, NVDA+n, NVDA+a, NVDA+b, NVDA+d.
  Correto: use NVDA+shift+letra ou NVDA+ctrl+letra para seus atalhos.

NVDA-010 Serio: UI updates de thread worker SEMPRE via wx.CallAfter().
  Proibido de thread: ui.message("..."), self.label.SetLabel("...")
  Correto: wx.CallAfter(ui.message, "texto")

NVDA-011 Moderado: Se gerar SynthDriver ou BrailleDisplayDriver, SEMPRE implemente check().
  Exemplo: @classmethod
           def check(cls) -> bool: return _is_engine_available()

NVDA-012 Menor: NUNCA use except: bare. Sempre especifique a excecao.
  Proibido: except:
  Correto:  except Exception as exc: log.error("[ERRO] ...: %s", exc)

NVDA-015 Moderado: Configuracoes persistentes SEMPRE via config.conf.spec.
  Proibido: open(path_config, "w").write(json.dumps(settings))
  Correto:
	_CONFSPEC = {"meuAddon": {"opcao": "boolean(default=True)"}}
	config.conf.spec["meuAddon"] = _CONFSPEC["meuAddon"]
	# Ler: config.conf["meuAddon"]["opcao"]

NVDA-016 Serio: Antes de escrever em disco, verifique NVDAState.shouldWriteToDisk().
  Em secure mode (tela de bloqueio), acesso a disco e proibido.
  Correto: if NVDAState.shouldWriteToDisk(): open(path, "w").write(data)

NVDA-017 Critico: NUNCA use DLLs 32-bit nem ctypes apontando para bibliotecas 32-bit.
  Para compatibilidade com NVDA 2026.1+ (Python 3.13 64-bit), binarios 32-bit sao proibidos.
  Proibido: ctypes.CDLL("minha_dll_32bit.dll")
  Migracoes obrigatorias:
    winUser/winKernel â†’ winBindings.* (equivalentes modernos 64-bit)
    NVDAHelper.localLib â†’ usar .dll diretamente
    TabbableScrolledPanel removido — use wx.ScrolledPanel
    typing_extensions removido — Python 3.13 tem todos os tipos nativamente

Regra-DEPS Critico: dependencies[] DEVE conter APENAS nomes de pacote PyPI — NUNCA nomes de import.

  TABELA DE CONVERSAO obrigatoria (import â†’ pacote pip correto):
    googleapiclient         â†’ google-api-python-client
    google.auth             â†’ google-auth
    google.auth.transport   â†’ google-auth
    google.oauth2           â†’ google-auth
    google_auth_oauthlib    â†’ google-auth-oauthlib
    googleapiclient.discovery â†’ google-api-python-client
    google.auth.transport.requests â†’ google-auth
    PIL                     â†’ Pillow
    cv2                     â†’ opencv-python
    sklearn                 â†’ scikit-learn
    bs4                     â†’ beautifulsoup4
    yaml                    â†’ PyYAML
    dotenv                  â†’ python-dotenv

  PROIBIDO em dependencies[] — causam pip install failure:
    webbrowser, os, sys, re, json, threading, socket, urllib, http, pathlib â†’ stdlib Python
    nvda, nvdaHelper, ui, api, speech, braille, wx, addonHandler â†’ modulos NVDA
    globalPlugins, appModules, synthDrivers, brailleDisplayDrivers â†’ pastas do NVDA
    installTasks, nvdaBuiltin â†’ modulos internos
    googleapiclient.discovery â†’ submÃ³dulo, use: google-api-python-client
    google.auth.transport.requests â†’ submÃ³dulo, use: google-auth

NVDA-024 Serio: Quando o addon tiver SettingsPanel, registre-o CORRETAMENTE.
  IMPORT OBRIGATORIO — de gui.settingsDialogs, nao de 'gui' nem de 'api':
	from gui.settingsDialogs import NVDASettingsDialog
	from gui.settingsDialogs import SettingsPanel

  REGISTRO no __init__ com GUARD (sem guard = painel duplicado ao recarregar):
	if NomeAddonSettingsPanel not in NVDASettingsDialog.categoryClasses:
		NVDASettingsDialog.categoryClasses.append(NomeAddonSettingsPanel)

  REMOCAO no terminate() — OBRIGATORIO:
	if NomeAddonSettingsPanel in NVDASettingsDialog.categoryClasses:
		NVDASettingsDialog.categoryClasses.remove(NomeAddonSettingsPanel)

  TEMPLATE COMPLETO do arquivo settings_panel.py separado do __init__.py:
	```python:globalPlugins/NOME_DO_ADDON/settings_panel.py
	import wx
	import config
	from gui.settingsDialogs import SettingsPanel
	from gui import guiHelper

	class NomeAddonSettingsPanel(SettingsPanel):
		# Translators: Titulo do painel
		title = _("Nome do Addon")

		def makeSettings(self, sizer: wx.BoxSizer) -> None:
			helper = guiHelper.BoxSizerHelper(self, sizer=sizer)
			# Translators: Rotulo do campo
			self._api_key = helper.addLabeledControl(
				_("&Chave de API:"), wx.TextCtrl,
				# NVDA-015: NUNCA .get() — use acesso direto; configspec fornece o default
				value=config.conf["addonIdReal"]["apiKey"],
			)

		def onSave(self) -> None:
			config.conf["addonIdReal"]["apiKey"] = self._api_key.GetValue()
	```

  TEMPLATE OBRIGATORIO do arquivo configSpec.py:
	```python:globalPlugins/NOME_DO_ADDON/configSpec.py
	import config

	def apply_config_spec() -> None:
		_spec = {
			"apiKey": "string(default='')",
			"maxLinhas": "integer(default=5)",
			"ativo": "boolean(default=True)",
		}
		if "addonIdReal" not in config.conf.spec:
			config.conf.spec["addonIdReal"] = _spec
	```

  CHAMADA no __init__.py — OBRIGATORIA (sem isso config.conf["secao"] lanca KeyError):
	from .configSpec import apply_config_spec
	apply_config_spec()   # ANTES de qualquer acesso a config.conf["addonIdReal"]

NVDA-015 Moderado: NUNCA use .get() em config.conf — use acesso direto por chave.
  ConfigObj armazena tudo como string antes de validar.
  .get("maxLinhas", 4) retorna "4" (string), nao 4 (int) — causa TypeError em wx.SpinCtrl.
  Proibido: config.conf["meuAddon"].get("maxLinhas", 4)
  Correto: config.conf["meuAddon"]["maxLinhas"]   # configspec coage para int automaticamente

NVDA-004 Serio: super().terminate() DEVE ser a ULTIMA linha do terminate().
  Se colocar super() no inicio, ele encerra estado que o cleanup ainda precisa.
  Proibido (super no inicio — errado):
	def terminate(self):
		super().terminate()  # ERRADO — vem antes do cleanup
		NVDASettingsDialog.categoryClasses.remove(MeuPanel)
  Correto (super no final — SEMPRE a ultima linha):
	def terminate(self):
		if MeuPanel in NVDASettingsDialog.categoryClasses:
			NVDASettingsDialog.categoryClasses.remove(MeuPanel)
		super().terminate()  # SEMPRE a ultima linha (final, ultimo)

NVDA-030 Serio: __init__(self, *args, **kwargs) SEMPRE obrigatorio em GlobalPlugin/AppModule.
  NUNCA omita __init__ — mesmo sem inicializacao customizada.
  Os *args e **kwargs sao obrigatorios — sem eles, TypeError se NVDA passar argumentos.
  Proibido: def __init__(self): super().__init__()
  Correto:
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

Regra-LOG Critico: Use logHandler.log para TODOS os logs — print() e logging Python nao funcionam.
  print() vai para o vacuo no NVDA. logging.getLogger() nao e integrado ao NVDA.
  Proibido: print("debug info")
  Proibido: import logging; logging.info("msg")
  Correto:
	from logHandler import log
	log.debug("mensagem de debug")
	log.info("operacao concluida")
	log.error("falha: %s", str(exc), exc_info=True)

NVDA-033 Serio: chooseNVDAObjectOverlayClasses e event_NVDAObject_init so funcionam em AppModule.
  Se colocar esses metodos num GlobalPlugin, silenciosamente nao fazem NADA.
  Correto (AppModule):
	class AppModule(appModuleHandler.AppModule):
		def chooseNVDAObjectOverlayClasses(self, obj, clsList):
			if obj.windowClassName == "Edit":
				clsList.insert(0, MinhaClasseCustom)

Orientacao AppModule Moderado: Use AppModule (nao GlobalPlugin) quando o addon e especifico para uma aplicacao.
  GlobalPlugin â†’ afeta TODAS as aplicacoes. AppModule â†’ afeta UMA aplicacao especifica.
  AppModule DEVE ser nomeado pelo executavel da aplicacao (sem .exe):
    notepad.exe â†’ appModules/notepad.py
    chrome.exe  â†’ appModules/chrome.py

skill §11 Moderado: Use installTasks.py para acoes de instalacao e desinstalacao.
  onInstall() â†’ executado apos extracao. onUninstall() â†’ executado ao reiniciar apos remocao.
  Template:
	```python:installTasks.py
	def onInstall() -> None:
		pass  # validar licenca, copiar arquivos

	def onUninstall() -> None:
		pass  # remover dados do usuario
	```

NVDA-029 Menor: Arquivos .py DEVEM usar encoding UTF-8 e line endings LF (nao CRLF).
  Use LF nos arquivos .py, conforme o template oficial do NVDA 2026.1 (Python 3.13).
  Regra: encoding = UTF-8, line endings = LF (\n), nunca CRLF (\r\n).

NVDA-036 Critico: SynthDriver DEVE implementar speak() e declarar supportedCommands e supportedNotifications.
  speak() e o metodo principal -- sem ele o driver nao produz nenhuma fala.
  Sem supportedCommands: NVDA nao converte comandos nao suportados para speak().
  Sem supportedNotifications: callbacks de indice nao funcionam. Todos sao OBRIGATORIOS.
  Correto:
	def speak(self, speechSequence: list) -> None:
		for item in speechSequence:
			if isinstance(item, IndexCommand):
				synthDriverHandler.synthIndexReached.notify(synth=self, index=item.index)
			elif isinstance(item, str):
				self._tts_speak(item)
		synthDriverHandler.synthDoneSpeaking.notify(synth=self)
	supportedCommands = frozenset({IndexCommand})
	supportedNotifications = frozenset({
		synthDriverHandler.synthIndexReached,
		synthDriverHandler.synthDoneSpeaking,
	})

NVDA-032 Serio: Todo extensionPoints.register() no __init__ DEVE ter unregister() no terminate().
  Sem unregister(), o handler permanece ativo apos o addon ser desativado.
  Correto:
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		speech.filter_speechSequence.register(self._filtrar)

	def terminate(self) -> None:
		speech.filter_speechSequence.unregister(self._filtrar)
		super().terminate()  # SEMPRE ultima linha

NVDA-037 Moderado: BrailleDisplayDriver DEVE declarar numCols e implementar display().
  numCols = numero de celulas do display.
  display(cells) = metodo que recebe lista de ints e envia ao hardware.
  isThreadSafe = True se o driver suporta I/O em thread.

NVDA-039 Moderado: Use registerExecutableWithAppModule para mapear multiplos executaveis a um AppModule.
  Correto:
	class GlobalPlugin(globalPluginHandler.GlobalPlugin):
		def __init__(self, *args, **kwargs):
			super().__init__(*args, **kwargs)
			appModuleHandler.registerExecutableWithAppModule("launcher", "meuApp")

		def terminate(self) -> None:
			appModuleHandler.unregisterExecutable("launcher")
			super().terminate()

NVDA-040 Moderado: Hosts especiais requerem tratamento diferente no AppModule.
  wwahost.exe (apps UWP): herdar de nvdaBuiltin.appModules.wwahost.AppModule.
  msedgewebview2.exe (WebView2/Electron): setar disableBrowseModeByDefault = True.
  javaw.exe (apps Java via Java Access Bridge): nomear modulo pelo AppModule.appName, nao pelo .exe.

NVDA-034 Serio: Use sleepMode = True para apps autoloquentes que gerenciam propria acessibilidade.
  Apps autoloquentes (jogos, leitores de tela alternativos) — NVDA por cima causa dupla locucao.
  Use quando o app tem propria engine de TTS e gerencia toda sua propria acessibilidade (self-voicing).
  Correto:
	class AppModule(appModuleHandler.AppModule):
		sleepMode: bool = True   # NVDA desativado enquanto este app estiver em foco

NVDA-042 Moderado: Use ngettext() para plural e pgettext() para strings com contexto.
  ngettext() — plural de acordo com o numero:
	# Translators: Mensagem com contagem de itens
	ui.message(ngettext("{n} item encontrado", "{n} itens encontrados", count).format(n=count))
  pgettext() — desambiguacao de strings identicas em contextos diferentes:
	# Translators: Rotulo de coluna no cabecalho
	label = pgettext("column header", "Name")
  npgettext() -- plural com contexto (combina ngettext + pgettext):
	# Translators: Mensagem de status com contagem, no cabecalho de coluna
	header = npgettext("column header", "{n} item", "{n} items", count).format(n=count)



NVDA-050 Moderado: NVDAObject overlay class deve herdar da classe MAIS ESPECIFICA disponivel.
  Regra: sempre herdar de IAccessible, UIA, Window ou JABObject -- nunca de NVDAObject base.
  IAccessible: from NVDAObjects.IAccessible import IAccessible  # controles Win32/MSAA
  UIA:         from NVDAObjects.UIA import UIA                  # controles UI Automation
  Window:      from NVDAObjects.window import Window            # janelas genericas Win32
  JABObject:   from NVDAObjects.JAB import JABObject            # apps Java via JAB
  Proibido: class MinhaOverlay(NVDAObject): ...  # perde metodos e propriedades da API alvo
  Correto:
	from NVDAObjects.IAccessible import IAccessible
	class MinhaOverlay(IAccessible):
		def initOverlayClass(self) -> None:
			self.name = "nome customizado"

NVDA-051 Serio: Addon com interface de usuario DEVE registrar item no menu Ferramentas do NVDA.
  Menu: NVDA > Menu > Ferramentas > [Nome do Addon]
  Obrigatorio quando: addon tem dialogs, configuracoes ou funcoes acionaveis pelo usuario.
  Implementacao: _ensure_menu_item() + _get_tools_menu() + wx.CallAfter para thread-safety.
  Remocao: cleanup completo em terminate() com Unbind().
  Template obrigatorio:
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._menu_item = None
		self._bind_owner = None
		self._ensure_menu_item()

	def _get_tools_menu(self):
		main_frame = getattr(gui, "mainFrame", None)
		if not main_frame:
			return None
		menu = getattr(main_frame, "toolsMenu", None)
		if menu is not None:
			return menu
		sys_tray = getattr(main_frame, "sysTrayIcon", None)
		if sys_tray is not None:
			return getattr(sys_tray, "toolsMenu", None)
		return None

	def _get_bind_owner(self, tools_menu):
		main_frame = getattr(gui, "mainFrame", None)
		if main_frame and getattr(main_frame, "toolsMenu", None) is tools_menu and hasattr(main_frame, "Bind"):
			return main_frame
		sys_tray = getattr(main_frame, "sysTrayIcon", None) if main_frame else None
		if sys_tray and getattr(sys_tray, "toolsMenu", None) is tools_menu and hasattr(sys_tray, "Bind"):
			return sys_tray
		if sys_tray and hasattr(sys_tray, "Bind"):
			return sys_tray
		if main_frame and hasattr(main_frame, "Bind"):
			return main_frame
		return None

	def _ensure_menu_item(self):
		tools_menu = self._get_tools_menu()
		if tools_menu is None:
			wx.CallLater(250, self._ensure_menu_item)
			return
		self._menu_item = tools_menu.Append(
			wx.ID_ANY,
			# Translators: Item do menu Ferramentas
			_("Meu Addon\tNVDA+Shift+M"),
			# Translators: Descricao da opcao
			_("Abre dialog do addon"),
		)
		self._bind_owner = self._get_bind_owner(tools_menu)
		if self._bind_owner is not None:
			self._bind_owner.Bind(wx.EVT_MENU, self._on_menu, self._menu_item)

	def terminate(self):
		if self._menu_item is not None:
			tools_menu = self._get_tools_menu()
			if tools_menu is not None and wx.FindWindowById(self._menu_item.GetId()):
				tools_menu.Remove(self._menu_item)
			if self._bind_owner is not None:
				self._bind_owner.Unbind(wx.EVT_MENU, source=None, id=self._menu_item.GetId())
		super().terminate()

	def _on_menu(self, event):
		wx.CallAfter(self._abrir_dialog)

	def _abrir_dialog(self):
		# Suas implementacoes aqui
		pass

1. Python Code: Use ```python:path/to/file.py
2. Dictionaries: Use ```text:path/to/file.dic
3. Manifest: Use ```ini:manifest.ini (if requested)

## Implementation Contract (for next agent)

At the end of your response, specify:
1. Dependencies: List any required third-party libraries (PyPI names only).
2. Entry Points: Identify key GlobalPlugin or AppModule classes created.
3. Critical Resources: List any generated .dic or .utb files that must be bundled.

VERIFICACAO FINAL OBRIGATORIA:
1. O codigo segue o baseline oficial (NVDA 2026.1+)?
2. Todas as strings _() tem o comentario '# Translators:' logo acima? (NVDA-019)
3. Todos os widgets wx tem wx.StaticText/label= (fix primario) ou SetName() (complemento)? (WX-A11Y-001)
4. super().terminate() e a ultima linha do terminate()? (NVDA-004)
5. __init__ tem *args e **kwargs e chama super().__init__(*args, **kwargs)? (NVDA-030)
6. Indentacao usa TABS, nao espacos? (NVDA-021)
7. nextHandler() em event handlers? # Translators: antes de _()? addonHandler.initTranslation() no topo? (NVDA-001, NVDA-019, NVDA-003)
8. Nenhum atalho conflita com NVDA core? Type hints usam | None, nao Optional[]? (NVDA-009, NVDA-028)
9. wx.MessageDialog proibido — use gui.message.MessageDialog? event_NVDAObject_init apenas em AppModule? (NVDA-049, NVDA-033)
10. Sem except: bare? Sem bloqueio da thread principal (sleep, HTTP sincrono)? (NVDA-012, NVDA-002)
11. Todos os blocos de codigo Python tem anotacao de caminho: ```python:caminho/arquivo.py? (Regra-DEPS)
12. Nenhum import 3rd party em nivel de modulo em arquivos de servico? dependencies[] so tem PyPI names? (NVDA-022)
13. Extension points: cada .register() em __init__ tem .unregister() em terminate() ANTES do super()? (NVDA-032)
14. AppModule para wwahost.exe herda de nvdaBuiltin.appModules.wwahost.AppModule? (NVDA-040)
15. AppModule para msedgewebview2.exe tem disableBrowseModeByDefault = True? (NVDA-027)
16. SynthDriver tem cancel() + pause() + synthIndexReached + synthDoneSpeaking em supportedNotifications? (NVDA-031, NVDA-038)
17. Line endings sao LF (nao CRLF)? Arquivo salvo em UTF-8? minimumNVDAVersion >= 2026.1? (NVDA-029, NVDA-018)
18. configSpec.py com apply_config_spec() criado e chamado? SettingsPanel com categoryClasses guard no __init__ e remove no terminate? (NVDA-024)
19. manifest.ini url comeca com https://? Nenhum wxPython bundlado em lib/? (NVDA-047, NVDA-048)
20. NVDAObject overlay class herda de IAccessible/UIA/Window/JABObject (nao de NVDAObject base)? (NVDA-050)
Se qualquer item falhar, corrija o problema antes de entregar a resposta final.
"""

# 2026-08-29: principios de engenharia destilados dos 3 documentos de
# metodologia do projeto (utils/engineering_principles.py). O catalogo de
# regras acima diz o que NAO fazer num addon NVDA; isto diz como decidir
# estrutura, tratamento de falha e complexidade quando nenhuma regra se
# aplica -- que e a maior parte das decisoes reais de codigo.
_SYSTEM += "\n\n" + RULE_REGISTRY_PROMPT_TEXT
_SYSTEM += "\n\n" + ENGINEERING_CODEGEN_PROMPT_TEXT




def run(prompt: str, model_id: str, reasoning_params: dict, cache_key: str | None = None) -> str:
	"""
	Gera codigo Python de addon NVDA com tool use.

	O modelo pode chamar validate_import(module_name) durante a geracao para
	verificar se um import e valido no ambiente NVDA antes de usar.
	Isso evita gerar codigo com imports que nao existem ou precisam de bundle.

	Regra 5: tool use e semantico - o modelo decide quando e o que verificar.
	Regra 9: validate_import nao executa codigo - apenas consulta lista estatica.
	"""
	# Definicao das ferramentas disponiveis durante a geracao
	tools = [
		{
			"type": "function",
			"function": {
				"name": "validate_import",
				"description": (
					"Verifica se um modulo Python pode ser importado em um addon NVDA "
					"sem causar ImportError em tempo de execucao.\n\n"
					"QUANDO USAR: Chame ANTES de adicionar qualquer import que nao seja "
					"stdlib Python pura (os, sys, re, threading, json, etc) ou um modulo "
					"do core NVDA (ui, api, speech, braille, config, wx, etc).\n\n"
					"RETORNOS E ACOES:\n"
					"- status='nvda': modulo e nativo do NVDA — use sem bundle, sem dependencias.\n"
					"- status='stdlib': modulo e da stdlib Python — use sem bundle, sem dependencias.\n"
					"- status='bundled': NVDAStudio ja inclui esse pacote — use sem adicionar ao dependencies[].\n"
					"- status='unknown': modulo NAO esta disponivel no NVDA. ACAO OBRIGATORIA: "
					"adicione o 'pip_name' retornado ao campo dependencies[] do plano de execucao. "
					"Sem isso, o addon vai falhar com ImportError ao ser carregado pelo NVDA.\n\n"
					"ERROS: Se module_name estiver vazio ou for invalido, a tool retorna "
					"status='error' com campo 'message' explicando o problema — corrija o nome "
					"do modulo e chame novamente."
				),
				"parameters": {
					"type": "object",
					"properties": {
						"module_name": {
							"type": "string",
							"description": (
								"Nome do modulo Python a verificar. Use o nome de import, "
								"nao o nome do pacote pip. Exemplos validos: 'google.generativeai', "
								"'whisper', 'cv2', 'requests'. "
								"Invalido: string vazia ou nome com espacos."
							)
						}
					},
					"required": ["module_name"]
				}
			}
		},
		{
			"type": "function",
			"function": {
				"name": "search_web",
				"description": (
					"Pesquisa informacoes atualizadas sobre pacotes, APIs e bibliotecas Python.\n\n"
					"QUANDO USAR: Chame quando nao tiver certeza sobre:\n"
					"- A versao atual de um pacote e como inicializar o cliente corretamente.\n"
					"- A API atual de uma biblioteca (ex: metodos, parametros, imports corretos).\n"
					"- Como usar um pacote especifico no contexto do NVDA ou Windows.\n"
					"- Se um pacote existe e e compativel com Python 3.13 no Windows x64.\n\n"
					"RETORNOS:\n"
					"- status='cached': informacao recente ja disponivel em cache — use diretamente.\n"
					"- status='searched': nova pesquisa realizada — o campo 'content' tem o resultado.\n"
					"- status='error': pesquisa indisponivel — prossiga com o conhecimento atual.\n\n"
					"QUANDO NAO USAR: Para pacotes do core NVDA (ui, api, speech, etc) ou stdlib "
					"Python (os, sys, re) — use validate_import em vez disso."
				),
				"parameters": {
					"type": "object",
					"properties": {
						"query": {
							"type": "string",
							"description": (
								"Pergunta ou topico a pesquisar. Seja especifico sobre o pacote e "
								"o que voce precisa saber. Exemplos: "
								"'google-generativeai SDK Python API client initialization', "
								"'elevenlabs python SDK voice synthesis 2026', "
								"'pydub audio playback windows python'."
							)
						}
					},
					"required": ["query"]
				}
			}
		},
		{
			"type": "function",
			"function": {
				"name": "fetch_url",
				"description": (
					"Busca o conteudo COMPLETO de uma URL especifica (nao so o resumo "
					"de search_web). Use quando search_web devolver um link relevante "
					"mas o resumo nao tiver detalhe suficiente (ex: lista completa de "
					"parametros de uma API, exemplo de codigo inteiro). So disponivel "
					"quando o provedor ativo suportar (Ollama Cloud); em outros "
					"provedores retorna indisponivel -- prossiga com search_web."
				),
				"parameters": {
					"type": "object",
					"properties": {
						"url": {
							"type": "string",
							"description": "URL completa da pagina a buscar (ex: 'https://docs.exemplo.com/api')."
						}
					},
					"required": ["url"]
				}
			}
		},
	]

	# 3.30.0: roteamento deterministico (Regra 5/9) -- quando o prompt vem
	# marcado como controller_client (orchestrator.py::_build_step_prompt(),
	# via controller_client_context.py::project_type_marker()), usa o
	# catalogo de regras/templates da Controller Client API em vez do
	# catalogo de addon NVDA inteiro (NVDA_SYSTEM_PROMPT/_SYSTEM/RULE_
	# REGISTRY_PROMPT_TEXT/_code_docs sao TODOS especificos de addon interno
	# -- nenhum se aplica a um programa externo).
	_is_ctrl_client = is_controller_client_context(prompt)
	if _is_ctrl_client:
		_code_docs = ""
		_generation_system = CTRL_CLIENT_SYSTEM_PROMPT
		full_system = CTRL_CLIENT_SYSTEM_PROMPT + "\n" + _TOOL_PREAMBLE_INSTRUCTION
	else:
		_code_docs = get_docs_code_generation()
		_generation_system = _SYSTEM
		full_system = NVDA_SYSTEM_PROMPT + "\n\n" + _SYSTEM + "\n\n" + _code_docs + "\n" + _TOOL_PREAMBLE_INSTRUCTION

	# Injeta dep_failures como contexto semantico (v3.1.3 — mensagem nuancada).
	# O LLM recebe o historico e decide semanticamente — com instrucao de verificar,
	# nao de bloquear. O pacote pode ter sido publicado ou corrigido desde a falha.
	# Zero keywords — raciocinio puro do modelo.
	try:
		_failures = memory.get_dep_failures(limit=10)
		if _failures:
			_fail_lines = "\n".join(
				f"  - {f['pkg']}: {f['reason']}" for f in _failures
			)
			full_system += (
				"\n\nHISTORICO DE DEPENDENCIAS COM FALHA ANTERIOR (aprendizado adaptativo):\n"
				"Os pacotes abaixo falharam na instalacao em geracoes anteriores.\n"
				"ANTES de incluir qualquer um em dependencies[], use a ferramenta validate_import\n"
				"para confirmar que o pacote existe e e compativel com o ambiente NVDA.\n"
				"Se validate_import confirmar existencia: pode incluir normalmente.\n"
				"Se validate_import retornar unknown e o pacote nao for essencial: evite.\n"
				+ _fail_lines
			)
			_logger.info("[CODE_GEN] %d dep_failures injetadas no contexto.", len(_failures))
	except Exception as _dep_exc:
		_logger.info("[CODE_GEN] dep_failures nao disponivel: %s", _dep_exc)

	# Injeta web_knowledge — conhecimento atualizado de pesquisas anteriores (v3.1.3).
	# O LLM recebe aprendizado acumulado sobre pacotes e APIs sem precisar re-pesquisar.
	try:
		_web_facts = memory.get_web_knowledge(prompt[:100], max_age_days=30)
		if _web_facts:
			_facts_lines = "\n".join(
				f"  [{f.get('year', '')}] {f['topic']}: {f['content'][:300]}"
				for f in _web_facts[:3]
			)
			full_system += (
				"\n\nCONHECIMENTO ATUALIZADO (aprendizado de pesquisas recentes):\n"
				"Informacoes verificadas sobre dependencias e APIs relevantes para este pedido:\n"
				+ _facts_lines
			)
			_logger.info("[CODE_GEN] %d web_knowledge injetadas no contexto.", len(_web_facts))
	except Exception as _web_exc:
		_logger.info("[CODE_GEN] web_knowledge nao disponivel: %s", _web_exc)

	# Narracao ao vivo (v3.22.0): o preambulo "pensando em como estruturar..."
	# cobre o intervalo antes do primeiro token chegar; dali em diante o
	# proprio modelo narra via _live (LiveNarrator, ligado como on_chunk),
	# instruido por _TOOL_PREAMBLE_INSTRUCTION -- texto solto fora dos fences
	# ```python:arquivo.py e descartado na extracao, entao narrar no meio do
	# content real e seguro aqui (nao e o caso em sub-agentes cuja resposta
	# crua e o entregavel direto).
	narrate(f"pensando em como estruturar o codigo para: {_truncate_at_word(prompt, 200)}")
	_live = LiveNarrator()

	try:
		client = create_llm_client(model_id=model_id)
		# A capability nativa só é reconhecida quando o cliente a declara
		# explicitamente. Code Interpreter/code execution não são presumidos
		# como edição do workspace local.
		if not _provider_supports_native_file_editing(client):
			tools.append(_file_editor_tool_definition())
		provider = getattr(client, "_provider", "")
		if provider == "openai":
			# Sandbox de execucao hospedado -- deixa o modelo testar o proprio
			# codigo antes de devolver a resposta final. Roda na infra da
			# OpenAI, nao na maquina do usuario nem do NVDAStudio (fora do
			# escopo da Regra 9, que e sobre nao executar codigo LOCALMENTE).
			tools.append({"type": "code_interpreter", "container": {"type": "auto"}})
		elif provider == "anthropic":
			# Mesma ideia via o code execution tool nativo da Anthropic.
			tools.append({"type": "code_execution_20260521", "name": "code_execution"})
			# Memory tool nativo -- Claude pode lembrar de padroes, decisoes e
			# erros de geracoes anteriores entre sessoes (arquivo real em
			# %APPDATA%/NVDAStudio/claude_memory/, handler client-side em
			# ai/anthropic_memory_tool.py). So Anthropic: e um tool proprio
			# do provedor, sem equivalente identico nos outros 4.
			tools.append({"type": "memory_20250818", "name": "memory"})
		resp = client.chat(
			prompt,
			system_override=full_system,
			tools=tools,
			on_chunk=_live.feed,
			step_type="code_generation",
			**reasoning_params,
		)

		# Processa tool calls se o modelo precisou verificar imports
		# tool_calls sao objetos Pydantic: ChatCompletionMessageToolCall
		# com .id, .function.name, .function.arguments
		max_tool_rounds = 3
		for _round in range(max_tool_rounds):
			if not resp.tool_calls:
				break
			# v3.25.0: quando o modelo pede 2+ tools no MESMO turno (parallel
			# tool calling, suportado pelos 5 provedores), executa em paralelo
			# via ThreadPoolExecutor em vez de round-trip sequencial -- as 4
			# tools (validate_import/search_web/fetch_url/memory) sao I/O-bound
			# e independentes entre si (nenhuma le o resultado de outra do
			# mesmo round). Ordem da lista final preservada (nao da conclusao).
			calls = list(resp.tool_calls)
			if len(calls) > 1:
				with ThreadPoolExecutor(max_workers=min(len(calls), 4)) as pool:
					tool_results = [r for r in pool.map(_dispatch_tool_call, calls) if r is not None]
			else:
				tool_results = [r for r in (_dispatch_tool_call(tc) for tc in calls) if r is not None]
			if not tool_results:
				break
			# Causa raiz de "esgotou N rodadas sem resposta final" (pesquisa
			# dedicada 2026-07-21, Anthropic Messages API + Google Interactions
			# API + OpenAI/xAI Responses API): na ULTIMA rodada permitida,
			# tool_choice="none" forca o modelo a responder so em texto/codigo
			# em vez de pedir mais uma tool -- e o padrao recomendado pelos 3
			# provedores nativos pra terminar um loop agentic. Ollama nao tem
			# esse parametro na API nativa (ver ai/ollama_client.py 2.14.0);
			# la a mitigacao e omitir `tools` do payload nesta mesma rodada.
			is_last_round = _round == max_tool_rounds - 1
			resp = client.chat(
				prompt,
				system_override=full_system,
				tools=tools,
				tool_choice="none" if is_last_round else None,
				tool_results=tool_results,
				on_chunk=_live.feed,
				step_type="code_generation",
				**reasoning_params,
			)

		_tl.last_tokens = resp.tokens_used  # B4: propaga tokens do caminho tool use

		# Auditoria 2026-07-20: causa raiz de "manifest e doc saem, codigo nao"
		# -- se o modelo ainda insiste em tool_calls apos esgotar
		# max_tool_rounds, resp.content pode estar vazio (o modelo nunca
		# chegou a dar a resposta final). Isso passava silenciosamente como
		# "codigo" vazio ate _verificar_codigo_gerado, sem virar [ERRO] e sem
		# acionar o retry/escalonamento normal do orchestrator.
		if resp.tool_calls:
			_logger.warning(
				"[AVISO] code_generator esgotou %d rodada(s) de tool-calling sem "
				"resposta final (modelo ainda pedia tool_calls).", max_tool_rounds,
			)
			return "[ERRO] O modelo nao produziu o codigo final apos esgotar as tentativas de uso de ferramentas."

		if not resp.content or not resp.content.strip():
			_logger.warning("[AVISO] code_generator recebeu conteudo vazio do modelo (sem tool_calls pendentes).")
			return "[ERRO] O modelo retornou uma resposta vazia para a geracao de codigo."

		# Achado CRITICO de auditoria full-stack 2026-08-04 (rastreamento de
		# geracao de addons grandes/complexos): quando a resposta e cortada
		# pelo teto de tokens no meio de um arquivo, extract_code_blocks()
		# (chamado depois, em _verificar_codigo_gerado/assembler) descarta o
		# bloco sem fechamento SILENCIOSAMENTE -- sem erro, sem retry. O
		# pipeline reportava sucesso com um arquivo faltando ou quebrado, pior
		# que uma falha visivel. resp.truncated (setado pelo client a partir
		# do motivo real de termino da API -- ver llm_client.py 1.1.0) agora
		# vira [ERRO] explicito, entrando no MESMO fluxo de retry/escalonamento
		# que qualquer outra falha de step (orchestrator escala pra modelo com
		# _MAX_TOKENS_EXTENDED ja ativo, ou replaneja).
		if resp.truncated:
			_logger.warning(
				"[AVISO] code_generator: resposta cortada pelo teto de tokens "
				"antes de terminar (modelo=%s). Arquivo(s) provavelmente "
				"incompleto(s) ou ausente(s).", model_id,
			)
			return (
				"[ERRO] O modelo cortou a resposta pelo limite de tokens antes de "
				"terminar o codigo -- um ou mais arquivos podem estar incompletos "
				"ou ausentes. Tente novamente ou divida o addon em menos features."
			)

		_arquivos = re.findall(r"```python:([^\n`]+)", resp.content)
		if _arquivos:
			narrate(f"terminei de escrever {len(_arquivos)} arquivo(s): {', '.join(_arquivos[:4])}. agora vou conferir")
		else:
			narrate("terminei de escrever o codigo, agora vou conferir se esta tudo certo")
		# Fase 2+3: verificacao estruturada em contexto isolado (sub-agent partitioning)
		return _verificar_codigo_gerado(resp.content, model_id, skip_nvda019=_is_ctrl_client)

	except Exception as exc:
		_logger.error("[ERRO] code_generator com tool use falhou: %s", exc)
		# Fallback sem tool use. 3.30.0: usa _generation_system (CTRL_CLIENT_
		# SYSTEM_PROMPT ou _SYSTEM, conforme roteamento acima) em vez de
		# _SYSTEM hardcoded -- senao o fallback ignorava o roteamento
		# controller_client e sempre gerava seguindo as regras de addon NVDA.
		codigo_fallback = _run_sub_agent(_generation_system, prompt, model_id, reasoning_params,
										 extra_docs=_code_docs)
		return _verificar_codigo_gerado(codigo_fallback, model_id, skip_nvda019=_is_ctrl_client)
	finally:
		_live.flush()


def _dispatch_tool_call(tc) -> dict | None:
	"""
	Executa uma tool_call unica (validate_import/search_web/fetch_url/memory)
	e retorna o dict de tool_result pronto pra client.chat(tool_results=...),
	ou None se a tool falhou ou nao e reconhecida (mesmo comportamento do
	loop sequencial antigo -- so nao adiciona nada em tool_results).

	Extraido do loop de run() em v3.25.0 pra poder ser chamado tanto
	sequencialmente (1 tool_call) quanto em paralelo via ThreadPoolExecutor
	(2+ tool_calls no mesmo turno -- as 4 tools sao I/O-bound e independentes
	entre si dentro do mesmo round, nenhuma le o resultado de outra).
	"""
	# Suporta tanto objeto Pydantic quanto dict (compatibilidade)
	if hasattr(tc, "function"):
		tc_name = tc.function.name
		tc_args = tc.function.arguments
	else:
		tc_name = tc.get("function", {}).get("name", "")
		tc_args = tc.get("function", {}).get("arguments", "{}")
	tc_id = getattr(tc, "id", "") if hasattr(tc, "id") else tc.get("id", "")

	if tc_name == "validate_import":
		try:
			args = tc_args if isinstance(tc_args, dict) else json.loads(tc_args or "{}")
			module_name = args.get("module_name", "")
			# Narracao "antes" removida (v3.22.0): o proprio modelo ja
			# narra a intencao via _live (LiveNarrator) no content, antes
			# de chamar a tool -- narrate() aqui duplicava a mesma coisa.
			result = _validate_import_tool(module_name)
			_logger.info("[TOOL] validate_import(%s) -> %s", module_name, result["status"])
			return {
				"tool_call_id": tc_id,
				"tool_name": tc_name,
				"role": "tool",
				"content": json.dumps(result),
			}
		except Exception as exc:
			_logger.warning("[AVISO] tool_call validate_import falhou: %s", exc)
			return None
	elif tc_name == "search_web":
		try:
			args = tc_args if isinstance(tc_args, dict) else json.loads(tc_args or "{}")
			query = args.get("query", "")
			# Narracao "antes" removida (v3.22.0, mesmo motivo do
			# validate_import) -- so mantida a "depois", que narra um
			# resultado real que o modelo ainda nao viu (o proprio
			# modelo so saberia disso no proximo turno).
			result = _search_web_tool(query)
			narrate(f"encontrei resultados sobre {query}, status {result['status']}")
			_logger.info("[TOOL] search_web('%s') -> %s", query[:60], result["status"])
			return {
				"tool_call_id": tc_id,
				"tool_name": tc_name,
				"role": "tool",
				"content": json.dumps(result),
			}
		except Exception as exc:
			_logger.warning("[AVISO] tool_call search_web falhou: %s", exc)
			return None
	elif tc_name == "fetch_url":
		try:
			args = tc_args if isinstance(tc_args, dict) else json.loads(tc_args or "{}")
			url = args.get("url", "")
			# Narracao "antes" removida (v3.22.0), mesmo motivo do validate_import.
			result = _fetch_url_tool(url)
			_logger.info("[TOOL] fetch_url('%s') -> %s", url[:60], result["status"])
			return {
				"tool_call_id": tc_id,
				"tool_name": tc_name,
				"role": "tool",
				"content": json.dumps(result),
			}
		except Exception as exc:
			_logger.warning("[AVISO] tool_call fetch_url falhou: %s", exc)
			return None
	elif tc_name == "memory":
		try:
			args = tc_args if isinstance(tc_args, dict) else json.loads(tc_args or "{}")
			command = args.get("command", "")
			# Narracao "antes" removida (v3.22.0), mesmo motivo do validate_import.
			result = handle_memory_command(args)
			_logger.info("[TOOL] memory(%s) -> is_error=%s", command, result["is_error"])
			return {
				"tool_call_id": tc_id,
				"tool_name": tc_name,
				"role": "tool",
				"content": result["content"],
			}
		except Exception as exc:
			_logger.warning("[AVISO] tool_call memory falhou: %s", exc)
			return None
	elif tc_name == "file_editor":
		try:
			args = tc_args if isinstance(tc_args, dict) else json.loads(tc_args or "{}")
			if not tool_gateway.is_registered("file_editor"):
				tool_gateway.register_builtin_tools()
			result, error = tool_gateway.call("file_editor", args, request_approval=True)
			if error:
				content = json.dumps({"ok": False, "error": error}, ensure_ascii=False)
			else:
				content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
			_logger.info("[TOOL] file_editor(%s) -> %s", args.get("path", ""), "ok" if not error else error)
			return {
				"tool_call_id": tc_id,
				"tool_name": tc_name,
				"role": "tool",
				"content": content,
			}
		except Exception as exc:
			_logger.warning("[AVISO] tool_call file_editor falhou: %s", exc)
			return None
	return None


def _provider_supports_native_file_editing(client) -> bool:
	"""Retorna True apenas para uma capacidade nativa declarada pelo cliente."""
	for attribute in ("supports_file_editing", "supports_file_write"):
		value = getattr(client, attribute, None)
		if callable(value):
			try:
				value = value()
			except Exception:
				value = False
		if isinstance(value, bool):
			return value

	native_tools = getattr(client, "native_tools", ())
	if isinstance(native_tools, (list, tuple, set, frozenset)):
		return bool({str(tool).lower() for tool in native_tools} & {
			"file_edit", "file_editor", "file_write", "write_file", "apply_patch",
		})
	return False


def _file_editor_tool_definition() -> dict:
	"""Schema da ferramenta de fallback para clientes sem edição nativa."""
	return {
		"type": "function",
		"function": {
			"name": "file_editor",
			"description": (
				"Edita arquivos reais do workspace do NVDA Studio. Pode criar, escrever, substituir, "
				"comparar, mover, remover e desfazer alterações. Leia antes, use expected_sha256 "
				"quando disponível e sempre confira o diff antes de mutações amplas."
			),
			"parameters": {
				"type": "object",
				"properties": {
					"action": {"type": "string", "enum": ["replace", "insert", "create", "write", "delete", "move", "diff", "undo"]},
					"path": {"type": "string"},
					"old_text": {"type": "string"},
					"new_text": {"type": "string"},
					"content": {"type": "string"},
					"destination_path": {"type": "string"},
					"replace_all": {"type": "boolean", "default": False},
					"expected_sha256": {"type": "string"},
					"operation_id": {"type": "string"},
				},
				"required": ["action"],
			},
		},
	}

def _validate_import_tool(module_name: str) -> dict:
	"""
	Implementacao da ferramenta validate_import.
	Nao executa codigo - apenas consulta listas estaticas (Regra 9).
	"""
	root = module_name.split(".")[0].lower()

	if root in {m.lower() for m in _NVDA_MODULES}:
		return {
			"status": "nvda",
			"module": module_name,
			"message": f"'{module_name}' e um modulo nativo do NVDA - disponivel sem bundle."
		}
	if root in {m.lower() for m in _STDLIB_MODULES}:
		return {
			"status": "stdlib",
			"module": module_name,
			"message": f"'{module_name}' e stdlib Python - disponivel sem bundle."
		}
	# Verifica aliases de pacotes comuns
	pip_name = None
	aliases_rev = {v.lower(): k for k, v in _PIP_ALIASES.items()}
	if root in aliases_rev:
		pip_name = aliases_rev[root].replace("_", "-")
	else:
		pip_name = module_name.replace("_", "-")

	return {
		"status": "unknown",
		"module": module_name,
		"pip_name": pip_name,
		"message": (
			f"'{module_name}' nao e modulo NVDA nem stdlib. "
			f"Adicione '{pip_name}' ao campo dependencies[] do plano para que seja bundlado."
		)
	}


def _fetch_url_tool(url: str) -> dict:
	"""
	Implementacao da ferramenta fetch_url -- busca o conteudo completo de
	uma URL. So disponivel quando o client do provedor ativo implementa
	web_fetch() (Ollama Cloud, endpoint dedicado /api/web_fetch); nos
	outros 4 provedores retorna status='unavailable' sem lancar excecao,
	pra o modelo prosseguir com search_web em vez de travar.

	Regra 9: nao executa codigo — apenas busca e retorna texto.
	"""
	try:
		client = create_llm_client(model_id="")
	except Exception as exc:
		return {"status": "error", "url": url, "content": f"Cliente indisponivel: {exc}"}

	if not hasattr(client, "web_fetch"):
		return {
			"status": "unavailable",
			"url": url,
			"content": "fetch_url so esta disponivel com Ollama Cloud como provedor ativo.",
		}

	try:
		content = client.web_fetch(url)
		_logger.info("[TOOL] fetch_url concluido: '%s'", url[:60])
		return {"status": "fetched", "url": url, "content": content[:2000]}
	except Exception as exc:
		_logger.warning("[TOOL] fetch_url falhou: %s", exc)
		return {"status": "error", "url": url, "content": f"Busca nao disponivel: {exc}"}


# ---------------------------------------------------------------------------
# Fase 2: verificacao estruturada via tool_use (llm-structured-output skill)
# Fase 3: correcao cirurgica se violacoes encontradas
#
# skill: llm-structured-output
#   - Ferramenta unica com schema JSON flat (3-5 campos) — alta acuracia
#   - Cada campo tem description explicita usada pelo modelo como instrucao
#   - tool_choice forcado — modelo NAO pode omitir campos
#   - Retry loop: se resposta invalida, retorna codigo original (fail-open)
#
# skill: context-window-management (sub-agent partitioning)
#   - Nova instancia de LLMClient = historico limpo, zero contexto da Fase 1
#   - System prompt < 200 tokens vs 34K do pipeline de geracao
#   - Codigo gerado e o UNICO input — sem NVDA_SYSTEM_PROMPT, _code_docs, dep_failures
# ---------------------------------------------------------------------------


# Validadores AST da Fase 2, em tabela em vez de chamadas soltas.
#
# 3.34.0: eram 3 validadores com bloco proprio de chamada, agregacao, log e
# montagem de mensagem -- adicionar mais 3 significaria 6 repeticoes do mesmo
# fluxo, a duplicacao que a Regra 5 do README proibe. Com a tabela, um
# validador novo e uma linha.
#
# Cada entrada: (rule_id, descricao para o prompt de correcao, funcao).
# A funcao recebe o codigo Python ja extraido dos blocos e devolve
# ASTValidationResult. Todas fazem fail-open em SyntaxError -- sintaxe e
# reportada por um degrau anterior, mais barato e mais preciso.
_AST_VALIDATORS: tuple[tuple[str, str, Callable[[str], ASTValidationResult]], ...] = (
	(
		"NVDA-019",
		"# Translators: ausente antes de _()",
		validate_nvda019,
	),
	(
		"WX-A11Y-001",
		"rotulo acessivel ausente em widget wx interativo -- wx.StaticText/label= "
		"preferidos, SetName() como complemento",
		validate_wx_a11y,
	),
	(
		"WX-A11Y-002",
		"SetAcceleratorTable() ausente para wx.Panel/wx.Frame",
		validate_wx_a11y_002_accelerators,
	),
	(
		"NVDA-060",
		"controlTypes.ROLE_*/STATE_* -- API REMOVIDA no NVDA 2022.1, levanta "
		"AttributeError em runtime; use os enums controlTypes.Role.*/State.*",
		validate_nvda060_controltypes,
	),
	(
		"WX-A11Y-013",
		"EVT_KEY_DOWN/EVT_CHAR em ListBox/ListCtrl/TreeCtrl/DataViewCtrl -- falha "
		"SILENCIOSA com NVDA/JAWS, que interceptam a navegacao por setas nesses "
		"controles; use EVT_LIST_KEY_DOWN/EVT_TREE_KEY_DOWN",
		validate_wx_a11y_013_key_events,
	),
	(
		"NVDA-056",
		"wx.MessageDialog criado em thread de background sem wx.CallAfter -- UI do "
		"wx fora da thread GUI costuma travar o processo do NVDA inteiro",
		validate_nvda056_messagedialog_thread,
	),
)

# NVDA-019 e convencao do gettext do PROPRIO NVDA -- nao se aplica a um
# programa controller_client (externo, sem addonHandler.initTranslation()).
_SKIP_EM_CONTROLLER_CLIENT: frozenset[str] = frozenset(["NVDA-019"])


def _verificar_codigo_gerado(
	codigo: str,
	model_id: str,
	skip_nvda019: bool = False,
) -> str:
	"""
	Fase 2 e 3 do pipeline de geracao: verifica e corrige violacoes no codigo gerado.

	Fase 2 — validacao AST deterministica (ast_validator):
	  - Zero chamadas de rede. Zero falsos negativos por atencao diluida do modelo.
	  - Verifica NVDA-019 (# Translators:), WX-A11Y-001 (wx.StaticText/label=,
		SetName() como complemento) e WX-A11Y-002 (SetAcceleratorTable para
		Panel/Frame) via ast.parse().
	  - Resultado identico independente do tamanho ou complexidade do addon.
	  - Fail-open: SyntaxError no codigo gerado retorna codigo sem bloqueio.

	Fase 3 — correcao LLM cirurgica (so se Fase 2 encontra violacoes):
	  - Contexto isolado: nova instancia LLMClient sem historico da Fase 1.
	  - Lista de violacoes explicitas como input — modelo corrige apenas os pontos listados.
	  - Fail-open: qualquer excecao retorna codigo original sem alteracao.

	Retorna: codigo original (sem violacoes) ou codigo corrigido pela Fase 3.

	BUGFIX (achado por tests/e2e/test_e35_golden_eval_set.py, 2026-08-03):
	`codigo` aqui e resp.content CRU -- narracao em prosa (LiveNarrator)
	misturada com blocos ```python:caminho/arquivo.py```, nunca Python
	valido por si so. Antes desta versao, ast.parse(codigo) recebia esse
	texto misto direto, sempre estourava SyntaxError e caia no fail-open
	de validate_nvda019/validate_wx_a11y -- ou seja, a Fase 2 SEMPRE
	aprovava, silenciosamente, independente do codigo real conter
	violacoes ou nao. Suspeita ja registrada no changelog 97.20.0
	("provavelmente ja fail-opena silenciosamente na pratica") e nunca
	confirmada/corrigida ate o golden eval set reproduzir com uma API
	real. Corrigido: extrai os blocos ```python:...``` via
	extract_code_blocks() (addon_builder.py, mesma extracao usada pelo
	orchestrator pro artefato final) ANTES de validar -- a validacao roda
	sobre CODIGO de verdade, `codigo` (com fences e narracao) continua
	sendo o que entra/sai desta funcao pra Fase 3 e pro caller.
	"""
	if not codigo or not codigo.strip():
		return codigo

	# Fase 2: validacao deterministica — sem rede, sem LLM.
	# Extrai so os blocos Python anotados (mesmo padrao do orchestrator)
	# antes de rodar ast.parse() -- validar o texto misto (narracao +
	# fences) sempre fail-abria silenciosamente (ver bugfix acima).
	python_blocks = [b["code"] for b in extract_code_blocks(codigo) if b["filename"].endswith(".py")]
	codigo_para_validar = "\n".join(python_blocks) if python_blocks else codigo

	# Roda todos os validadores da tabela, preservando a ordem declarada -- a
	# ordem e o que o modelo le no prompt de correcao da Fase 3.
	resultados: list[tuple[str, str, ASTValidationResult]] = []
	for rule_id, descricao, validador in _AST_VALIDATORS:
		if skip_nvda019 and rule_id in _SKIP_EM_CONTROLLER_CLIENT:
			continue
		resultados.append((rule_id, descricao, validador(codigo_para_validar)))

	total_violacoes = sum(len(r.violacoes) for _, _, r in resultados)

	_logger.info(
		"[CODE_GEN] Fase 2 AST: %s violacoes=%d",
		" ".join(f"{rid}={'ok' if r.ok else 'FALHOU'}" for rid, _, r in resultados),
		total_violacoes,
	)

	if total_violacoes == 0:
		_logger.info("[CODE_GEN] Fase 2: sem violacoes — codigo aprovado.")
		return codigo

	# Fase 3: correcao cirurgica — contexto isolado, lista de violacoes explicita
	try:
		linhas_violacoes: list[str] = []
		for rule_id, descricao, r in resultados:
			if not r.violacoes:
				continue
			linhas_violacoes.append(f"{rule_id} ({descricao}):")
			linhas_violacoes.extend(f"  - {v}" for v in r.violacoes)

		_logger.info(
			"[CODE_GEN] Fase 3: correcao cirurgica de %d violacoes.",
			total_violacoes,
		)

		client_v = create_llm_client(model_id=model_id)
		correcao_prompt = (
			"O codigo abaixo tem as seguintes violacoes:\n\n"
			+ "\n".join(linhas_violacoes)
			+ "\n\nCorrija APENAS esses pontos e devolva o codigo completo com todos os "
			"blocos de arquivo originais (```python:caminho/...) intactos:\n\n"
			+ codigo
		)

		resp_c = client_v.chat(
			user_message=correcao_prompt,
			system_override=(
				"Voce e um editor de codigo Python para addons NVDA. "
				"Corrija exatamente as violacoes listadas e devolva o codigo completo. "
				"Mantenha todos os blocos com seus caminhos anotados (```python:path/...)."
			),
			step_type="code_generation",
		)

		if resp_c.truncated:
			# Achado 2026-08-04: aplicar uma correcao cortada pelo teto de tokens
			# SUBSTITUIRIA codigo original intacto por uma versao quebrada -- pior
			# que nao corrigir nada. Mesmo fallback do caminho "resposta invalida".
			_logger.warning("[CODE_GEN] Fase 3: correcao cortada pelo teto de tokens — retornando codigo original.")
			return codigo

		if resp_c.content and len(resp_c.content) > 200:
			_logger.info(
				"[CODE_GEN] Fase 3: correcao aplicada (%d chars).", len(resp_c.content)
			)
			return resp_c.content

		_logger.info("[CODE_GEN] Fase 3: resposta invalida — retornando codigo original.")
		return codigo

	except Exception as exc:
		_logger.info(
			"[CODE_GEN] Fase 3 indisponivel: %s — retornando codigo original.", exc
		)
		return codigo
