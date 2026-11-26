import os

from .project_policy import (
	ABSOLUTE_MIN_NVDA,
	PROJECT_LAST_TESTED_NVDA,
	PROJECT_MIN_NVDA,
	PROJECT_SUPPORTED_RANGE,
)


# ------------------------------------------------------------------
# NVDA detection rules NVDA-001..040, NVDA-042..050
# ------------------------------------------------------------------

NVDA_DETECTION_RULES: list[tuple[str, str, str]] = [
	# (rule_id, severity, description)
	("NVDA-001", "Critical", "Missing nextHandler() in event handler"),
	("NVDA-002", "Critical", "Main thread blocked (sleep, synchronous I/O, blocking HTTP)"),
	# Fonte: addonHandler.initTranslation e languageHandler.setLanguage do NVDA 2026.3.1. O NVDA instala o `_` em
	# builtins (trans.install), entao nao ha NameError: sem initTranslation() as strings do modulo usam as
	# traducoes do NVDA e ignoram as do addon (locale/).
	("NVDA-003", "Moderate", "Module uses gettext without calling addonHandler.initTranslation(): its strings are looked up in NVDA's translations, not in the add-on's locale/ files (there is no NameError: NVDA installs _ in builtins)"),
	("NVDA-004", "Serious",  "Missing terminate() to clean up persistent resources"),
	("NVDA-005", "Serious",  "Wrong version format in the manifest, or lastTestedNVDAVersion < BACK_COMPAT_TO of the target NVDA -- the Add-on Store validates minimumNVDAVersion/lastTestedNVDAVersion against the real catalog of released versions (nvdaAPIVersions.json), not only against the numeric YYYY.N.P format"),
	("NVDA-006", "Moderate", "Monkey-patching of NVDA core modules"),
	("NVDA-007", "Moderate", "Script without the @script decorator"),
	("NVDA-008", "Moderate", "Script without a description in the decorator"),
	("NVDA-009", "Moderate", "Hardcoded gesture conflicts with the NVDA core"),
	("NVDA-010", "Serious",  "UI update from a background thread without wx.CallAfter() -- the 3 sanctioned ways back to the GUI thread are wx.CallAfter() (asynchronous), wx.CallLater(ms, func) (asynchronous with delay) and gui.guiHelper.wxCallOnMain() (synchronous, waits for the result); never touch wx controls directly from a non-GUI thread"),
	("NVDA-011", "Moderate", "Driver without a check() classmethod"),
	("NVDA-012", "Minor",    "Bare except: clause (catches everything without logging)"),
	("NVDA-013", "Serious",  "Incompatible API version range in the manifest"),
	("NVDA-014", "Minor",    "SHA256 missing for Add-on Store submission"),
	("NVDA-015", "Moderate", "Settings do not use config.conf.spec"),
	("NVDA-016", "Serious",  "Secure mode vulnerability (no shouldWriteToDisk() check)"),
	("NVDA-017", "Critical", "32-bit DLL on 64-bit NVDA (2026.1+): incompatible"),
	("NVDA-018", "Serious",  "minimumNVDAVersion below 2019.3.0 (requires Python 2)"),
	# NVDA-019..021: added in v3.2.0 (skill: nvda-addon-dev)
	("NVDA-019", "Serious",  "# Translators: comment missing immediately before a _() call"),
	("NVDA-020", "Moderate", "Import of a transitive re-export: use from NVDAObjects.IAccessible import IAccessible, not from NVDAObjects import IAccessible"),
	("NVDA-021", "Moderate", "Indentation with spaces instead of TABs (NVDA uses TABs as its coding standard)"),
	# NVDA-022: added in v3.4.0 — root cause of GmailSummarizer (settings panel never appeared)
	("NVDA-022", "Critical", "Module-level third-party import in a service file — prevents the whole add-on from loading (including the settings panel) if the dependency is not bundled in lib/"),
	# NVDA-023: added in v3.5.0 — annotation with a lazy type causes NameError when the module loads
	("NVDA-023", "Critical", "Type annotation that references a type imported lazily (inside the method) — NameError when the module loads: use a string literal '->\"Type\"' as a forward reference"),
	# NVDA-024: added in v3.6.0 — categoryClasses.append without a guard causes a duplicated panel in the Tab order
	("NVDA-024", "Serious",  "NVDASettingsDialog.categoryClasses.append() without an 'if Panel not in categoryClasses' guard — if the add-on is reloaded without a successful terminate(), the panel appears duplicated and Tab moves between two overlapping panels"),
	# NVDA-025: added in v3.7.0 — generic config.conf section causes collisions between add-ons
	("NVDA-025", "Critical", "config.conf uses a generic section (e.g. 'myAddon') instead of the unique addonId — several add-ons with the same section name overwrite each other's settings; always use the real addonId from manifest.ini"),
	# NVDA-037: added in v3.9.0 — BrailleDisplayDriver (renumbered from NVDA-044 in v3.8.0)
	("NVDA-037", "Moderate", "BrailleDisplayDriver without numCols, display() or isThreadSafe — required fields so that NVDA knows the display size and sends cells correctly"),
	# NVDA-038: added in v3.10.0 — SynthDriver without the required supportedNotifications (skill: nvda-addon-dev §25)
	# synthIndexReached and synthDoneSpeaking are REQUIRED in supportedNotifications and must be notified
	# in speak(). Without them, "say all", paragraph reading and index callbacks (braille) stop working.
	("NVDA-038", "Critical", "SynthDriver without supportedNotifications declaring synthIndexReached and synthDoneSpeaking — both are required (skill: nvda-addon-dev §25); without them 'say all', paragraph reading and braille on-index stop working"),
	# NVDA-039: added in v3.18.0 -- AppModule mapping several executables without registerExecutableWithAppModule (skill: nvda-addon-dev par.3.2)
	# registerExecutableWithAppModule() is the official mechanism for one AppModule to cover several executables.
	("NVDA-039", "Moderate", "AppModule with several identical appModules/*.py files for executables of the same suite -- use appModuleHandler.registerExecutableWithAppModule(executableName, appModuleName) to map extra executables to the same AppModule and unregisterExecutable() in terminate() (skill: nvda-addon-dev par.3.2)"),
	# NVDA-042..048: added/fixed in v3.8.0-v3.9.0
	("NVDA-042", "Moderate", "Uses _() for plural strings instead of ngettext() — produces wrong text: '1 items found'. Use ngettext(singular, plural, count).format(n=count)"),
	("NVDA-043", "Moderate", "Braille Translation Table missing or badly declared: missing .utb file in brailleTables/ or [brailleTables] section in manifest.ini with displayName, contracted, output, input"),
	("NVDA-044", "Moderate", "Symbol Dictionary missing or badly formatted: missing locale/<lang>/symbols-*.dic with a 'symbols:' section and TAB-separated entries, or [symbolDictionaries] section in manifest.ini"),
	("NVDA-045", "Minor",    "Locale Gesture Remapping missing or badly formatted: missing locale/<lang>/gestures.ini with [module.ClassName] sections and 'scriptName = gesture' bindings"),
	("NVDA-046", "Moderate", "Speech Dictionary with the wrong format — each line must have 4 TAB-separated fields: pattern, replacement, case_sensitive, type. Declare it in manifest.ini [speechDictionaries]"),
	("NVDA-047", "Serious",  "manifest.ini: url does not start with https:// — the Add-on Store rejects URLs without HTTPS"),
	("NVDA-048", "Critical", "wxPython bundled in lib/ (wx* entries) — NVDA already provides wxPython; bundling it causes a version conflict and needlessly enlarges the package"),
	# NVDA-040: added in v3.9.2 — AppModule for special hosts (UWP/wwahost)
	("NVDA-040", "Serious",  "AppModule for wwahost.exe does not inherit from nvdaBuiltin.appModules.wwahost.AppModule — inheriting only from appModuleHandler.AppModule ignores the special handling for UWP apps"),
	# NVDA-026: added in v3.11.0 — import of a private NVDA symbol (skill: nvda-addon-dev §22)
	# Symbols prefixed with _ are private and may change in any NVDA release, including patches.
	# There is no deprecation warning for private API — the add-on breaks silently after an NVDA update.
	("NVDA-026", "Moderate", "Import of a private NVDA symbol (_ prefix) — e.g. from someModule import _internalFunction. _ symbols are private and may change in any NVDA release without notice (skill: nvda-addon-dev §22); use only the documented public API"),
	# Source: NVDA Developer Guide, "App modules for hosted apps" and Example 3: apps using Edge WebView2
	# appear as a web page by default; disableBrowseModeByDefault is OPTIONAL (design).
	("NVDA-027", "Minor",    "Design decision, not a defect: in an app module for an app that uses Edge WebView2 (the module name is the app's, such as olk.py, not msedgewebview2.py), `disableBrowseModeByDefault = True` turns off automatic browse mode; the Developer Guide says the line can be removed if the add-on wants browse mode"),
	# NVDA-028: added in v3.12.0 — type hints with Optional[]/Union[] instead of X | None / X | Y (skill: nvda-addon-dev §18)
	# Python 3.13 (NVDA 2026.1+) fully supports the native union syntax. X | None and X | Y
	# replace the legacy forms that the skill explicitly forbids in new code.
	("NVDA-028", "Minor",    "Type hint using Optional/Union from typing instead of the modern X | None / X | Y syntax. NVDA 2026.1+ uses Python 3.13 — use int | None, str | None, etc."),
	# NVDA-029: added in v3.12.0 — CRLF line endings instead of LF (skill: nvda-addon-dev §18)
	# The skill is explicit: UTF-8 + LF. CRLF in Python files causes problems in the NVDA scons build
	("NVDA-029", "Minor",    "CRLF line endings (\\r\\n) in an add-on Python file — NVDA requires LF (\\n) per its coding standards (skill: nvda-addon-dev §18). CRLF causes problems in the scons build and in version control"),
	# NVDA-030: added in v3.13.0 — GlobalPlugin/AppModule __init__ without super().__init__(*args, **kwargs) (skill: nvda-addon-dev §3.1, §3.2)
	# The skill shows the pattern explicitly: super().__init__(*args, **kwargs) is required.
	# Without the call, globalPluginHandler does not complete the plugin initialization — gestures may
	# not be registered and the plugin may fail silently when NVDA starts.
	# *args, **kwargs is needed because NVDA may pass arguments to the constructor in future versions.
	("NVDA-030", "Serious",  "GlobalPlugin or AppModule with an __init__ that does not call super().__init__(*args, **kwargs) — the plugin initialization by globalPluginHandler/appModuleHandler is not completed correctly; gestures may not be registered and the plugin fails silently (skill: nvda-addon-dev §3.1, §3.2)"),
	# NVDA-031: added in v3.13.0 — SynthDriver without a cancel() method (skill: nvda-addon-dev §25)
	# cancel() is part of the skill's §25 "minimum viable driver".
	# Without cancel(), pressing Escape does not stop speech — completely broken behavior for the user.
	# NVDA calls cancel() whenever the user presses Ctrl or Escape to interrupt reading.
	("NVDA-031", "Critical", "SynthDriver without a cancel() method — required in the minimum viable driver (skill: nvda-addon-dev §25). Without cancel(), pressing Ctrl/Escape does not stop speech; the user is stuck listening to audio they cannot interrupt"),
	# NVDA-032: added in v3.14.0 — extension point registered in __init__ without unregister in terminate() (skill: nvda-addon-dev §7)
	# register() without a matching unregister() in terminate() is a guaranteed memory leak.
	# Worse: if the add-on is reloaded (NVDA+Ctrl+F3), the handler stays registered several times
	# — each NVDA event fires the handler N times (N = number of reloads).
	# NVDA gives no warning — the bug only shows up as duplicated behavior or sporadic crashes.
	("NVDA-032", "Serious",  "Extension point registered in __init__ (speech.filter_speechSequence.register, extensionPoints Action/Filter/Decider.register, etc.) without a matching unregister in terminate() — memory leak and a duplicated handler on every plugin reload (skill: nvda-addon-dev §7). Pattern: always call .unregister() in terminate() BEFORE super().terminate()"),
	# NVDA-033: added in v3.14.0 — event_NVDAObject_init in GlobalPlugin (skill: nvda-addon-dev §5)
	# event_NVDAObject_init is only called for AppModule, never for GlobalPlugin.
	# Putting it in a GlobalPlugin results in a silently ignored handler — zero errors, zero effect.
	# The developer assumes it works, but the add-on does nothing.
	("NVDA-033", "Serious",  "event_NVDAObject_init defined in GlobalPlugin — this event is only called for AppModule (skill: nvda-addon-dev §5). In GlobalPlugin it is silently ignored by NVDA. To customize NVDAObject properties globally, use chooseNVDAObjectOverlayClasses in GlobalPlugin; for one specific app, move it to an AppModule"),
	# NVDA-034: added in v3.14.0 — AppModule for a self-voicing app without sleepMode (skill: nvda-addon-dev §3.3)
	# Self-voicing apps (e.g. other screen readers) speak on their own.
	# Without sleepMode=True, NVDA announces every focus/caret event of the app over the app's own voice
	# — double narration, total confusion for the user.
	# Skill §3.3 is explicit: sleepMode = True is the only correct pattern for self-voicing apps.
	("NVDA-034", "Serious",  "AppModule for a self-voicing application (screen readers, narration apps, NVDA, JAWS, etc.) without sleepMode = True — NVDA will try to announce focus and caret events over the app's own voice, causing double narration (skill: nvda-addon-dev §3.3). Correct: class AppModule(appModuleHandler.AppModule): sleepMode = True"),
	# NVDA-035: added in v3.15.0 -- SynthDriver without a pause() method (skill: nvda-addon-dev §25)
	# pause() is in the skill's §25 "minimum viable driver", listed together with cancel().
	# Without pause(), NVDA raises AttributeError when Ctrl is pressed to pause/resume speech --
	# the synthesizer crashes and the user loses audio control without warning.
	("NVDA-035", "Serious",  "SynthDriver without a pause(self, switch: bool) method -- required in the minimum viable driver (skill: nvda-addon-dev §25). Without pause(), NVDA raises AttributeError when Ctrl is pressed to pause/resume speech; the synthesizer crashes. Correct: def pause(self, switch: bool) -> None: self._tts_pause(switch)"),
	# NVDA-036: added in v3.16.0 -- speak() as the main method of the SynthDriver (skill: nvda-addon-dev §25)
	# NVDA calls speak() for each piece of speech; without speak() the driver is completely non-functional.
	("NVDA-036", "Critical", "SynthDriver without a speak(self, speechSequence) method -- the driver's main method; without speak() the synthesizer produces no speech at all (skill: nvda-addon-dev §25). speak() must iterate over speechSequence, notify synthIndexReached for each IndexCommand and synthDoneSpeaking at the end."),
	# NVDA-049: added in v3.17.0 -- wx.MessageDialog is forbidden; use gui.message.MessageDialog (skill: nvda-addon-dev §12)
	# gui.message.MessageDialog is NVDA's modern API for modal dialogs -- it integrates correctly with the screen reader.
	# wx.MessageDialog is not announced correctly by NVDA and focus may not behave as a screen reader user expects.
	("NVDA-049", "Serious",  "wx.MessageDialog OR wx.MessageBox used instead of gui.message.MessageDialog -- neither integrates correctly with the NVDA screen reader (skill: nvda-addon-dev §12). Use MessageDialog.alert(), .confirm(), .ask() or an instance of gui.message.MessageDialog. wx.MessageDialog/wx.MessageBox are not announced correctly by NVDA and can trap focus"),
	# NVDA-050: added in v3.17.0 -- NVDAObject overlay class inherits from NVDAObject (base) instead of a specific class (skill: nvda-addon-dev §6)
	# Skill §6 is explicit: "Always inherit from the most specific class you need to match the object."
	# Inheriting from NVDAObject (base) in overlay classes used in chooseNVDAObjectOverlayClasses loses
	# the methods and properties specific to the target API (IAccessible2, UIA, Win32 Window, JAB).
	("NVDA-050", "Moderate", "NVDAObject overlay class inherits from NVDAObject (base class) instead of a more specific class -- use NVDAObjects.IAccessible.IAccessible, NVDAObjects.UIA.UIA, NVDAObjects.window.Window or NVDAObjects.JAB.JABObject according to the target object's API (skill: nvda-addon-dev §6). Inheriting from the generic base loses the methods and properties specific to the API"),
	# NVDA-051: added in v2.1.0 -- Tools menu (NVDA > Tools > Addon Name)
	# Bug found: MediaTranscriber did not register an item in the Tools menu
	# Fallback: if the add-on can have a menu, it should implement _ensure_menu_item() + _get_tools_menu()
	# with wx.CallAfter for thread safety
	("NVDA-051", "Minor",    "Usability suggestion, not an NVDA requirement: an add-on with its own interface is usually easier to find with an item in NVDA's Tools menu, besides the gesture. The NVDA Developer Guide does not require this."),
	# NVDA 2026.1+ compatibility rules
	("NVDA-052", "Moderate", "Use of a winUser/winKernel/winGDI/wincon symbol that was removed, deprecated or moved to winBindings.* (NVDA 2026.1+; user_docs/en/changes.md: API Breaking Changes and Deprecations). Only the symbols listed there; the rest of those modules remains valid."),
	("NVDA-053", "Critical", "Use of sapi5/sapi4 for 32-bit voices without ARM64EC portability or without sapi5_32/sapi4_32 support (NVDA 2026.1+)."),
	("NVDA-054", "Moderate", "Use of typing_extensions - NVDA 2026.1+ with Python 3.13 provides native support; remove the typing_extensions dependency."),
	# official sources (github.com/nvdaaddons/DevGuide, download.nvaccess.org/documentation/developerGuide.html,
	# github.com/nvaccess/AddonTemplate, Add-on Store submission guide). Unlike
	# NVDA-019..054 (born from real production bugs), these are PREVENTIVE -- practices
	# the official documentation requires but that had never caused a real bug in nvdastudio yet.
	("NVDA-055", "Serious",  "Import of a pip package shipped with NVDA itself (e.g. comtypes, wx, requests from the NVDA installation) instead of bundling the add-on's own dependency in lib/ -- packages shipped with NVDA can be updated, downgraded or removed at any time without notice; they are NOT a stable add-on API"),
	("NVDA-056", "Critical", "wx.MessageDialog instantiated, initialized or shown (ShowModal or Show) outside the GUI thread -- most MessageDialog methods are NOT thread-safe; calling from a non-GUI thread can cause a crash or unpredictable behavior, not only a freeze"),
	("NVDA-057", "Moderate", "@script without the SCRCAT_* constants for the category parameter (uses a free-form string instead), or ignores the canPropagate/bypassInputHelp/allowInSleepMode/speakOnDemand/resumeSayAllMode flags when the script should work during Input Help, sleep mode, NVDA's speak-on-demand mode, or needs to resume Say All after running"),
	("NVDA-058", "Moderate", "installTasks.py or uninstallTasks.py imports more modules than strictly necessary -- onInstall()/onUninstall() run in a restricted state (before the NVDA restart, .pendingInstall folder); unnecessary imports increase the risk of failure in that state"),
	("NVDA-059", "Serious",  "manifest.ini with an addonId/name containing characters other than letters, digits, underscore and hyphen (e.g. space, dot, unicode) -- the Add-on Store validates the name with a restricted regex; characters outside that set make the submission fail"),
	# Source: source/controlTypes/deprecatedAliases.py of NVDA 2026.3.1 -- the ROLE_*/STATE_* aliases
	# still exist "for backwards compatibility with add-ons only": they work, but are legacy.
	("NVDA-060", "Moderate", "Use of controlTypes.ROLE_*/controlTypes.STATE_* instead of controlTypes.Role.*/controlTypes.State.* -- NVDA keeps those aliases only for compatibility with old add-ons (controlTypes/deprecatedAliases.py, 'do not extend'); they work today, but are legacy and may go away in a future API change. Use the enum (1:1 mapping)"),
	("NVDA-061", "Moderate", "Character Descriptions missing or badly formatted: add-on that needs to describe individual characters (e.g. speech driver, phonetic dictionary) without locale/<lang>/characterDescriptions.dic in UTF-8 with character/description pairs separated by TAB, blank lines and '#' comments ignored (skill: nvda-addon-dev, Developer Guide section 'Character Descriptions')"),
	# the rule set had NO coverage of secure mode (login screen/UAC/secure
	# desktop), a real and current Add-on Store review requirement. Source:
	# add-on community (globalVars.appArgs.secure confirmed as the standard flag
	# checked by real add-ons in the __init__ of GlobalPlugin/AppModule
	# to disable early in secure mode) + NVDA's own source code
	# (nvaccess/nvda: secure mode disables creating/editing/deleting configuration
	# profiles, the Python console, and logging of sensitive data --
	# PRs #13056/#13059 fixed real exploits of file dialogs
	# reachable on the secure screen).
	("NVDA-062", "Critical", "Add-on with a script/dialog/config persistence that does not check globalVars.appArgs.secure -- in secure mode (login screen, UAC, secure desktop), scripts remain executable (defined at class level) even if __init__ checks the flag and returns early; any wx.Dialog that opens a file/folder, saves config, or logs sensitive data must check the flag at EVERY dangerous entry point, not only in __init__; NEVER log a password/token/API key unconditionally (NVDA itself treats logging in secure mode as a security risk)"),
	# until now it does not live inside any single file: it lives in the seam. The
	# delivered add-on had __init__.py calling proofread(text, model, api_key,
	# on_done, on_error) -- a signature it ITSELF declared in a
	# contract comment -- and openai_service.py defining
	# proofread(self, text, callback). It loaded, registered the gestures,
	# passed all nine gates, and died with a TypeError on the first key press.
	("NVDA-063", "Critical", "Cross-file call inside the add-on with a signature "
	 "that differs from the definition -- file A calls a method/function of B with an "
	 "argument that B does not accept, or without a required argument that B demands. Each file is "
	 "valid on its own and the add-on loads normally; the TypeError is only raised when the "
	 "user triggers the command, and the add-on's correct `except Exception` (which exists "
	 "so that it never takes the screen reader down) turns the defect into a "
	 "generic message. When one file DECLARES the contract that another implements, both "
	 "sides must match literally"),
	# Source: gui/message.py of NVDA (MessageDialog._executeCommand calls callback(payload)).
	("NVDA-064", "Serious", "gui.message.MessageDialog button callback that does not accept the "
	 "argument NVDA passes. NVDA calls callback(payload) with exactly one positional "
	 "argument (a Payload); `callback=lambda: ...` or a method with only `self` raises "
	 "TypeError when the button is activated and the button does nothing. Use `lambda payload: ...` or "
	 "`def method(self, payload)`"),
]

# ------------------------------------------------------------------
# WX-A11Y Rules — 14 rules (001..014)
# OFFICIAL source: github.com/Community-Access/accessibility-agents .github/agents/wxpython-specialist.agent.md
# Section "Detection Rules" — copied literally, translated into concise English.
# NOTE: IDs 005-011 were corrected in v2.1.0 (they were wrong).
#       IDs 013-014 were added in v2.1.0 (they were missing).
# ------------------------------------------------------------------

WX_A11Y_RULES: list[tuple[str, str, str]] = [
	# (rule_id, severity, description)
	# Source: wxpython-specialist.agent.md "Detection Rules" table
	("WX-A11Y-001", "Critical", "wx.StaticText missing immediately before an input/selection control, or label= missing on wx.Button (primary fix from the official source); SetName() is an acceptable complement, not a substitute"),
	("WX-A11Y-002", "Minor", "Not checked: a wx.AcceleratorTable is not an NVDA convention (NVDA's own source/gui uses it twice) and keyboard access is normally given by the dialog's buttons, labeled controls and tab order"),
	("WX-A11Y-003", "Critical", "EVT_LEFT_DOWN/EVT_LEFT_DCLICK without an equivalent keyboard event"),
	("WX-A11Y-004", "Serious",  "wx.Dialog without CreateStdDialogButtonSizer() or Escape handling"),
	("WX-A11Y-005", "Serious",  "wx.Dialog.ShowModal() without SetFocus() on a meaningful control"),
	("WX-A11Y-006", "Serious",  "wx.StaticBitmap or wx.BitmapButton without SetToolTip() or a wx.Accessible subclass"),
	("WX-A11Y-007", "Moderate", "wx.Colour as the only state indicator (no text/icon)"),
	("WX-A11Y-008", "Moderate", "wx.Timer or status bar without wx.Bell() or an accessible announcement"),
	("WX-A11Y-009", "Moderate", "Custom wx.Panel with EVT_PAINT without a wx.Accessible subclass"),
	("WX-A11Y-010", "Minor",    "Tab order not set explicitly and does not follow the sizer"),
	("WX-A11Y-011", "Serious",  "wx.ListCtrl or wx.TreeCtrl in virtual mode without a GetItemText override"),
	("WX-A11Y-012", "Moderate", "Menu item without an accelerator key (\\tCtrl+X suffix missing)"),
	# WX-A11Y-013/014: added in v2.1.0 — critical for NVDA/JAWS users
	# Source: wxpython-specialist.agent.md section "Screen Reader Key Event Pitfalls"
	("WX-A11Y-013", "Minor", "EVT_KEY_DOWN/EVT_CHAR on ListBox/ListCtrl/TreeCtrl/DataViewCtrl: NVDA's own code uses EVT_CHAR_HOOK on list controls (gui/nvdaControls.py) and EVT_LIST_KEY_DOWN only exists for wx.ListCtrl; a style note, not an NVDA requirement"),
	("WX-A11Y-014", "Serious",  "wx.ListCtrl with EVT_KEY_DOWN for Enter instead of EVT_LIST_ITEM_ACTIVATED"),
]

# ------------------------------------------------------------------
# DTK-A11Y Rules — 12 rules (001..012)
# OFFICIAL source: github.com/Community-Access/accessibility-agents .github/agents/desktop-a11y-specialist.agent.md
# Section "Detection Rules" — copied literally, translated into concise English.
# DIFFERENT layer from WX-A11Y: while WX-A11Y covers patterns specific to
# wx widgets (label before a control, AcceleratorTable, etc.), DTK-A11Y covers
# platform API concepts (UIA/MSAA Name/Role/State/Value, focus trap
# in modals, High Contrast, dynamic change detection) that apply to
# any desktop toolkit and are the conceptual foundation that wx.Accessible
# implements underneath. There is no overlap in IDs or in fix guidance
# (the maintainer asked for NVDA Studio to stay more and more up to date).
# ------------------------------------------------------------------

DTK_A11Y_RULES: list[tuple[str, str, str]] = [
	# (rule_id, severity, description)
	# Source: desktop-a11y-specialist.agent.md "Detection Rules" table
	("DTK-A11Y-001", "Critical", "Interactive control without a Name exposed via UIA/MSAA/accessibilityLabel -- the screen reader announces nothing or only a generic type"),
	("DTK-A11Y-002", "Critical", "The control's Role/ControlType does not match its real behavior (e.g. clickable panel without a button role)"),
	("DTK-A11Y-003", "Serious",  "State change (checked/expanded/disabled/selected) not reflected in the accessibility API -- the screen reader shows an outdated state"),
	("DTK-A11Y-004", "Serious",  "Control with a value (slider/progress bar/spinner/text field) does not expose the current value via ValuePattern/accValue/accessibilityValue"),
	("DTK-A11Y-005", "Critical", "Interactive element not reachable by keyboard (not focusable, no tab stop) -- a keyboard user cannot get to it"),
	("DTK-A11Y-006", "Serious",  "Focus lost after a UI change (deleting an item, closing a dialog, collapsing a panel) -- it falls to the window root or an unexpected place instead of a logical destination"),
	("DTK-A11Y-007", "Moderate", "Control receives keyboard focus but has no visible focus indicator (outline/highlight) in the default theme AND in high contrast"),
	("DTK-A11Y-008", "Moderate", "Hardcoded colors instead of reading from the system theme (wx.SystemSettings.GetColour() in wx) -- breaks in Windows High Contrast mode"),
	("DTK-A11Y-009", "Serious",  "Content update (status bar, progress, validation error) happens silently, without a UIA event/accessibility notification"),
	("DTK-A11Y-010", "Serious",  "Dialog does not trap focus -- Tab can leave the modal dialog and reach controls of the parent window while it is open"),
	("DTK-A11Y-011", "Minor",    "Custom keyboard shortcut defined in code without documentation the user can discover (menu item, tooltip, help text)"),
	("DTK-A11Y-012", "Moderate", "Use of a deprecated or incorrect platform API (e.g. MSAA-only pattern on modern Windows instead of UIA)"),
]

# ------------------------------------------------------------------
# Fallback matrix per rule (NVDA + WX + ARCH)
# ------------------------------------------------------------------

ARCH_RULE_IDS: list[str] = [
	"ARCH-001",
	"ARCH-002",
	"ARCH-003",
	"ARCH-004",
	"ARCH-005",
	"ARCH-006",
	"ARCH-007",
	"ARCH-008",
	"ARCH-009",
]

FALLBACK_MODE_DOC: dict[str, str] = {
	"STRICT_ONLY": "No alternative: the rule must be met exactly.",
	"IMPLEMENTATION_ALTERNATIVES": "Accepted technical alternatives for meeting the same rule.",
	"CONTEXTUAL_CHOICE": "Choose according to the user's goal; if ambiguous, ask before generating.",
}

# Overrides only for rules with a real/contextual alternative.
# All other rules default to STRICT_ONLY.
_RULE_FALLBACK_OVERRIDES: dict[str, tuple[str, str]] = {
	"NVDA-005": ("IMPLEMENTATION_ALTERNATIVES", "Accepts fixing the version format and/or adjusting lastTestedNVDAVersion to BACK_COMPAT_TO."),
	"NVDA-014": ("CONTEXTUAL_CHOICE", "Optional in local development; require only when the target is the Add-on Store."),
	"NVDA-020": ("IMPLEMENTATION_ALTERNATIVES", "Use a direct import of the specific public API instead of a transitive re-export."),
	"NVDA-023": ("IMPLEMENTATION_ALTERNATIVES", "Use a string forward reference or remove the annotation when the type is a lazy import."),
	"NVDA-037": ("IMPLEMENTATION_ALTERNATIVES", "Implement the required fields (numCols/display/isThreadSafe) in the driver's own strategy."),
	"NVDA-039": ("IMPLEMENTATION_ALTERNATIVES", "Use registerExecutableWithAppModule and unregisterExecutable in terminate()."),
	"NVDA-042": ("IMPLEMENTATION_ALTERNATIVES", "Use ngettext/npgettext for plurals and pgettext to disambiguate context."),
	"NVDA-043": ("IMPLEMENTATION_ALTERNATIVES", "Comply with a valid .utb file and/or a correct declaration in [brailleTables] in the manifest."),
	"NVDA-044": ("IMPLEMENTATION_ALTERNATIVES", "Comply with a valid symbols-*.dic and/or a correct declaration in [symbolDictionaries]."),
	"NVDA-045": ("IMPLEMENTATION_ALTERNATIVES", "Comply with a valid gestures.ini per locale/module following the NVDA standard."),
	"NVDA-049": ("IMPLEMENTATION_ALTERNATIVES", "Use MessageDialog.alert/confirm/ask or an instance of gui.message.MessageDialog -- never wx.MessageDialog or wx.MessageBox."),
	"NVDA-050": ("IMPLEMENTATION_ALTERNATIVES", "Inherit from IAccessible/UIA/Window/JABObject according to the target API; never from the generic base."),
	"NVDA-060": ("IMPLEMENTATION_ALTERNATIVES", "Replace every controlTypes.ROLE_X/STATE_X reference with controlTypes.Role.X/State.X (1:1 mapping documented by NVDA)."),
	"NVDA-061": ("CONTEXTUAL_CHOICE", "Require characterDescriptions.dic only when the add-on really describes individual characters (speech driver, phonetic dictionary); not applicable to add-ons without that need."),
	"WX-A11Y-002": ("IMPLEMENTATION_ALTERNATIVES", "Apply an AcceleratorTable to the wx.Panel or wx.Frame when there is keyboard focus/interaction."),
	"WX-A11Y-004": ("IMPLEMENTATION_ALTERNATIVES", "The dialog must have CreateStdDialogButtonSizer and/or explicit Escape handling."),
	"WX-A11Y-006": ("IMPLEMENTATION_ALTERNATIVES", "An image control must have SetToolTip() and/or a wx.Accessible subclass (SetName() does not count)."),
	"WX-A11Y-008": ("IMPLEMENTATION_ALTERNATIVES", "Announce timer/status via wx.Bell and/or an equivalent accessible message."),
	"WX-A11Y-011": ("IMPLEMENTATION_ALTERNATIVES", "A virtual List/Tree must expose text via an appropriate override (e.g. GetItemText)."),
	"WX-A11Y-013": ("IMPLEMENTATION_ALTERNATIVES", "Prefer EVT_CHAR_HOOK or a semantic event instead of raw EVT_KEY_DOWN/EVT_CHAR."),
	"WX-A11Y-014": ("IMPLEMENTATION_ALTERNATIVES", "For item activation use EVT_LIST_ITEM_ACTIVATED instead of ad hoc key handling."),
	"ARCH-001": ("CONTEXTUAL_CHOICE", "For API key configuration: SettingsPanel, Tools menu, or both depending on UX and the request."),
	"ARCH-007": ("IMPLEMENTATION_ALTERNATIVES", "Promote existing loose files to subpackages named after the feature (e.g. services/spotify_client.py -> spotify/client.py)."),
	"ARCH-008": ("CONTEXTUAL_CHOICE", "Choose between the Tools menu, SettingsPanel or both; if ambiguous, ask the user."),
	"ARCH-009": ("CONTEXTUAL_CHOICE", "A dialog/frame may use the menu, settings or both depending on the intent of the request and the main flow."),
	"DTK-A11Y-004": ("IMPLEMENTATION_ALTERNATIVES", "Expose the value via ValuePattern (UIA) or accValue/accessibilityValue according to the control's target API."),
	"DTK-A11Y-008": ("IMPLEMENTATION_ALTERNATIVES", "In wx: wx.SystemSettings.GetColour() instead of a hardcoded color; equivalent in other toolkits (SystemColors/NSColor)."),
	"DTK-A11Y-011": ("IMPLEMENTATION_ALTERNATIVES", "Document the shortcut via a menu item with an accelerator, a tooltip, or help text -- any of them makes the shortcut discoverable."),
	"DTK-A11Y-012": ("CONTEXTUAL_CHOICE", "Migrate to UIA when the target platform supports it; keep MSAA only if there is an explicit requirement for compatibility with an older Windows version."),
}


def _build_rule_fallback_matrix() -> dict[str, tuple[str, str]]:
	"""Builds the complete fallback matrix for 100% of the known rules."""
	all_ids = [r[0] for r in NVDA_DETECTION_RULES] + [r[0] for r in WX_A11Y_RULES] + ARCH_RULE_IDS
	matrix: dict[str, tuple[str, str]] = {}
	for rid in all_ids:
		matrix[rid] = _RULE_FALLBACK_OVERRIDES.get(
			rid,
			("STRICT_ONLY", "No fallback: fix the rule violation exactly."),
		)
	return matrix


RULE_FALLBACK_MATRIX: dict[str, tuple[str, str]] = _build_rule_fallback_matrix()


def _format_rule_fallback_matrix() -> str:
	"""Formats the per-rule fallback matrix for the guide."""
	ordered_ids = [r[0] for r in NVDA_DETECTION_RULES] + [r[0] for r in WX_A11Y_RULES] + ARCH_RULE_IDS
	lines = [
		"PER-RULE FALLBACK MATRIX (100% COVERAGE):",
		"Valid modes:",
		f"- STRICT_ONLY: {FALLBACK_MODE_DOC['STRICT_ONLY']}",
		f"- IMPLEMENTATION_ALTERNATIVES: {FALLBACK_MODE_DOC['IMPLEMENTATION_ALTERNATIVES']}",
		f"- CONTEXTUAL_CHOICE: {FALLBACK_MODE_DOC['CONTEXTUAL_CHOICE']}",
		"",
		"Rules:",
	]
	for rid in ordered_ids:
		mode, note = RULE_FALLBACK_MATRIX[rid]
		lines.append(f"{rid}: {mode} -- {note}")
	return "\n".join(lines)


RULE_FALLBACK_MATRIX_TEXT: str = _format_rule_fallback_matrix()

_EXPECTED_RULE_IDS = [r[0] for r in NVDA_DETECTION_RULES] + [r[0] for r in WX_A11Y_RULES] + ARCH_RULE_IDS
_MISSING_FALLBACK_RULES = [rid for rid in _EXPECTED_RULE_IDS if rid not in RULE_FALLBACK_MATRIX]
if _MISSING_FALLBACK_RULES:
	raise RuntimeError(f"Incomplete fallback matrix: {_MISSING_FALLBACK_RULES}")

# ------------------------------------------------------------------
# ------------------------------------------------------------------

NVDA_GUIDE = f"""HUMAN-FACING TEXT OF THE ADDON (summary, description and changelog in manifest.ini, userGuide.html,
UI messages): write it in the language of the person who asked for the addon (for example correct
Brazilian Portuguese, with every accent and cedilla), not in English by default.
This does NOT apply to technical identifiers (manifest field names, variable names).

NVDA VERSION AND COMPATIBILITY:
Official project baseline: {PROJECT_SUPPORTED_RANGE}.
For new addons generated by NVDAStudio:
- minimumNVDAVersion = {PROJECT_MIN_NVDA}
- lastTestedNVDAVersion = {PROJECT_LAST_TESTED_NVDA}
ANTI-LEGACY RULE: do not generate active compatibility for versions earlier than {PROJECT_MIN_NVDA}.
WARNING: minimumNVDAVersion NEVER below {ABSOLUTE_MIN_NVDA} (before that it was Python 2). Rule NVDA-018.
CRITICAL WARNING: lastTestedNVDAVersion MUST be >= BACK_COMPAT_TO of the NVDA version where the addon will be installed.
For NVDA 2025.x, BACK_COMPAT_TO = 2025.1.0, so lastTestedNVDAVersion >= 2025.1 is mandatory.
If the addon must stay ready for NVDA 2026.1+, avoid 32-bit DLLs, compiled binaries without ABI validation, and removed APIs.
NVDA 2026.1 — BREAKING CHANGES (skill: nvda-addon-specialist §NVDA 2026.1):
  - Python 3.13 64-bit: NVDA and its extensions are 64-bit. Do not generate 32-bit .dll/.pyd files.
  - Some symbols of winUser, winKernel, winGDI and wincon were removed, deprecated or moved to winBindings.* (see NVDA's changes.md: API Breaking Changes and Deprecations); the modules themselves still exist. Use addon_validate (NVDA-052) to find the affected symbols.
  - versionInfo: copyrightYears and url moved to buildVersion — use from buildVersion import copyrightYears, url.
  - NVDAHelper.localLib changed from ctypes.CDLL to a module — use NVDAHelper.localLib.dll for the CDLL object.
  - sapi5 is now 64-bit; use sapi5_32 for 32-bit SAPI voices (no audio ducking). sapi4 was removed — use sapi4_32.
  - Screen Curtain moved from visionEnhancementProviders.screenCurtain to the screenCurtain subpackage.
  - ARM64: Windows 10 on ARM is no longer supported; ARM64EC only on Windows 11.

PROBLEM DETECTION RULES (NVDA-001..040, NVDA-042..050):
NVDA-001 Critical: Missing nextHandler() in event handler.
NVDA-002 Critical: Main thread blocked (sleep, synchronous I/O, blocking HTTP).
NVDA-003 Moderate: Module calls _(), ngettext(), pgettext() or npgettext() without
  addonHandler.initTranslation(). The Developer Guide says to call it at the top of every module with
  translatable strings; without it the module uses NVDA's translations instead of the add-on's locale/
  files (there is no NameError: NVDA installs _ in builtins). Do not require it in modules that do not
  use gettext.
NVDA-004 Serious: Missing terminate() to clean up persistent resources.
NVDA-005 Serious: Wrong version format in the manifest.
NVDA-006 Moderate: Monkey-patching of NVDA core modules.
NVDA-007 Moderate: Script without the @script decorator.
NVDA-008 Moderate: Script without a description in the decorator.
NVDA-009 Moderate: Hardcoded gesture conflicts with the NVDA core.
NVDA-010 Serious: UI update from a background thread without wx.CallAfter().
NVDA-011 Moderate: Driver without a check() classmethod.
NVDA-012 Minor: Bare except: clause.
NVDA-013 Serious: Incompatible API version range in the manifest.
NVDA-014 Minor: SHA256 missing for Add-on Store submission.
NVDA-015 Moderate: Settings do not use config.conf.spec.
NVDA-016 Serious: Secure mode vulnerability (no shouldWriteToDisk() check).
NVDA-017 Critical: 32-bit DLL on 64-bit NVDA (2026.1+).
NVDA-018 Serious: minimumNVDAVersion below {ABSOLUTE_MIN_NVDA}.
NVDA-019 Serious: # Translators: comment missing immediately before a _() call.
  ABSOLUTE RULE: EVERY line with _() MUST have '# Translators: ...' on the IMMEDIATELY preceding line.
  There are no exceptions — it applies to @script(description=_()), ui.message(), title=_(), SetName(), etc.
  For @script, the comment goes on the line BEFORE the decorator:
    # Translators: Description of the script in the input gestures dialog
    @script(gesture="kb:NVDA+shift+x", description=_("Opens the panel"))
  Avoid _() inside lambdas — extract it to a dedicated method where you can put the comment.
  Correct: # Translators: Message when the clipboard is empty
           ui.message(_("Clipboard is empty"))
  Wrong:   ui.message(_("Clipboard is empty"))  # no comment
NVDA-020 Moderate: Import of a transitive re-export (API unstable between versions).
  Correct: from NVDAObjects.IAccessible import IAccessible
  Wrong:   from NVDAObjects import IAccessible
NVDA-062 Critical: SECURE MODE at EVERY dangerous entry point.
  In secure mode (login screen, UAC, secure desktop) the addon's scripts REMAIN
  executable: they are defined at class level, so checking the flag only in
  __init__ and returning early does NOT stop the script from running. Every entry that reads a
  credential, opens a file, saves config or makes an external request needs its
  own check, BEFORE touching the sensitive data.
  Wrong (checks only in __init__ -- the script runs anyway):
    class GlobalPlugin(globalPluginHandler.GlobalPlugin):
      def __init__(self):
        super().__init__()
        if globalVars.appArgs.secure:
          return
      @script(gesture="kb:NVDA+shift+r")
      def script_summarize(self, gesture):
        key = config.conf["MyAddon"]["apiKey"]   # runs in secure mode!
  Correct (each entry point protects itself, and WARNS the user):
    import globalVars
    import ui

    def _blocked_in_secure_mode():
      if globalVars.appArgs.secure:
        # Translators: message when the feature is unavailable on the secure screen
        ui.message(_("Unavailable in NVDA secure mode."))
        return True
      return False

    @script(gesture="kb:NVDA+shift+r")
    def script_summarize(self, gesture):
      if _blocked_in_secure_mode():
        return
      key = config.conf["MyAddon"]["apiKey"]
  The SAME applies to makeSettings()/onSave() of a SettingsPanel: do NOT read the
  API key and then disable the control -- disabling afterwards does not
  undo the read. Check before reading.
  And NEVER log a password, token or API key, in any mode.

NVDA-UX-002 / NVDA-016: a blocked failure has to be SPOKEN.
  When saving is blocked by secure mode or by
  NVDAState.shouldWriteToDisk(), writing a warning to the log is not enough: the
  screen reader user pressed save and heard nothing, so for them the action worked.
  Always call ui.message() explaining that the change was not saved.

WX-A11Y-004 Serious: a dialog needs standard buttons and Escape handling.
  Wrong (no standard sizer -- Escape does not close it, and the focus order is wrong):
    sizer.Add(wx.Button(self, label=_("OK")))
  Correct:
    buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
    sizer.Add(buttons, flag=wx.EXPAND | wx.ALL, border=5)
  wx.OK/wx.CANCEL give a label translated by the system, correct tab order
  and closing with Escape without extra code.

NVDA-021 Moderate: Indentation with spaces instead of TABs. It is the NVDA and
  AddonTemplate standard: use a TAB for indentation in every .py file of the addon.
  NVDA uses TABs as its coding standard. Always generate with TABs.
NVDA-022 Critical: Module-level third-party import in a service file.
  If the dependency is not in lib/, the whole import chain fails and NVDA does
  not load the addon — the settings panel never appears, gestures do not work.
  RULE: in ANY service file (not __init__.py), imports of packages
  external to the stdlib/NVDA MUST be lazy, inside the method that uses them:
  Wrong (module level — causes a silent crash of the addon):
    from googleapiclient.discovery import build  # top of the file
  Correct (lazy — the addon loads even without the package):
    def my_method(self):
        from googleapiclient.discovery import build  # inside the method

NVDA-023 Critical: Type annotation references a lazily imported type — NameError when the module loads.
  When an import is lazy (inside a method, NVDA-022), the type is not in the module
  namespace. Using the type directly in the function signature causes an immediate NameError.
  In Python 3.x without 'from __future__ import annotations', annotations are evaluated
  eagerly when the function is defined.
  RULE: use a string literal (forward reference) for any lazily imported type:
  Wrong (NameError when loading the module — the addon does not load, the settings panel vanishes):
    def get_credentials() -> Credentials:   # Credentials is only imported lazily, inside
        from google.oauth2.credentials import Credentials  # the body — never in scope
  Correct (string literal — evaluated only when inspected):
    def get_credentials() -> "Credentials":
        from google.oauth2.credentials import Credentials
  ALTERNATIVE: remove the return annotation when the type is external:
    def get_credentials():  # no annotation — equally valid for NVDA

NVDA-024 Serious: NVDASettingsDialog.categoryClasses.append() without a guard — duplicated panel in the Tab order.
  If the addon is reloaded (e.g. NVDA+Ctrl+F3) or terminate() fails, the panel may
  be added twice. With two identical panels in the list, Tab moves between
  the controls of the two overlapping panels — it looks like the settings get mixed up
  with those of other addons.
  RULE: always use a guard before append:
  Wrong (unconditional append — duplicates the panel if the addon reloads):
    NVDASettingsDialog.categoryClasses.append(MyAddonSettingsPanel)
  Correct (guard against duplicates):
    if MyAddonSettingsPanel not in NVDASettingsDialog.categoryClasses:
        NVDASettingsDialog.categoryClasses.append(MyAddonSettingsPanel)

NVDA-025 Critical: config.conf with a generic section — collision between addons.
  TERMINOLOGY NOTE: "addonId" below is an
  INTERNAL NVDAStudio convention for the addon's unique identifier -- the real NVDA
  manifest.ini (addonHandler/__init__.py, AddonManifest) does NOT
  have a field literally called "addonId". The unique identifier is the
  name= field of manifest.ini. Wherever this file says "addonId", read "the value of the
  name= field of manifest.ini".
  Each addon MUST use a unique section in config.conf, equal to the name in manifest.ini.
  If two addons use the same section (e.g. both use "myAddon"), the settings
  of one overwrite those of the other — the user cannot use both addons at the same time.
  RULE: The config.conf section name MUST be the exact value of the name= field of manifest.ini.
  Wrong (generic placeholder — they collide if two addons are generated):
    config.conf["myAddon"]["apiKey"]   # "myAddon" is a placeholder, not the real id
  Correct (unique name from the manifest — e.g. "GmailSummarizer", "RssReader", etc.):
    config.conf["GmailSummarizer"]["apiKey"]   # same as name= in manifest.ini
  NAMING RULE: use the name in CamelCase exactly as declared in manifest.ini.
  Examples:
    manifest.ini: name=GmailSummarizer  ->  config.conf["GmailSummarizer"]
    manifest.ini: name=RssReader        ->  config.conf["RssReader"]
    manifest.ini: name=QuickTranslation ->  config.conf["QuickTranslation"]

NVDA-042 Moderate: Use ngettext() for plural strings and pgettext() for strings with context.
  Using _() for strings that vary with the plural produces grammatically wrong text: "1 items found".
  ngettext() — picks singular or plural automatically:
    # Translators: Message with an item count (singular/plural)
    ui.message(ngettext("{{n}} item found", "{{n}} items found", count).format(n=count))
  pgettext() — disambiguates identical strings in different contexts:
    label = pgettext("column header", "Name")   # translated as the column header
    label = pgettext("person name", "Name")     # translated as the form field
  npgettext() — plural with context:
    msg = npgettext("list item", "{{n}} result", "{{n}} results", count).format(n=count)
  Rule: whenever the number matters grammatically, use ngettext(). Whenever the same
  English string has different translations depending on context, use pgettext().

NVDA-043 Moderate: Braille Translation Table — .utb file in brailleTables/ + manifest.ini.
  Create brailleTables/<name>.utb with liblouis content (plain text).
  CRITICAL: manifest.ini MUST be ONE SINGLE file with the base fields AND the additional sections.
  Complete manifest.ini (base + brailleTables):
    File: manifest.ini
```ini
    name = AddonName
    summary = Short description
    description = Full description
    author = Author <email@example.com>
    url = https://github.com/user/addon
    version = 1.0.0
    minimumNVDAVersion = {PROJECT_MIN_NVDA}
    lastTestedNVDAVersion = {PROJECT_LAST_TESTED_NVDA}

    [brailleTables]
    [[pt-br-grade2.utb]]
    displayName = Brazilian Portuguese Grade 2
    contracted = True
    output = True
    input = False
    ```
  Minimal template brailleTables/pt-br-grade2.utb:
    File: brailleTables/pt-br-grade2.utb
```ini
    # Brazilian Portuguese Grade 2 Braille table
    # liblouis format — replace with real contraction rules
    include pt-br.utb
    ```

NVDA-044 Moderate: Symbol Dictionaries — locale/<lang>/symbols-<name>.dic with a symbols: section.
  File: locale/<lang>/symbols-<name>.dic (e.g. locale/en/symbols-greek.dic)
  Declare it in manifest.ini:
    [symbolDictionaries]
    [[<name>]]
    displayName = Readable Name
    mandatory = false    # true = always active; false = the user enables it in NVDA Settings
  .dic file format — the separators are real TABs (shown below as [TAB]):
    symbols:
    <symbol>[TAB]<pronunciation>[TAB]<level>[TAB]<preserve>
  level: none | some | most | all | char | unchanged
  preserve: empty | norep | char | always
  Template locale/en/symbols-greek.dic:
    File: locale/en/symbols-greek.dic
```ini
    symbols:
    alpha[TAB]alpha[TAB]all[TAB]
    beta[TAB]beta[TAB]all[TAB]
    gamma[TAB]gamma[TAB]all[TAB]
    pi[TAB]pi[TAB]all[TAB]
    ```
  Important: [TAB] stands for a real TAB character (0x09) in the generated file.
  Example manifest.ini:
    File: manifest.ini
```ini
    [symbolDictionaries]
    [[greek]]
    displayName = Greek Symbols
    mandatory = false
    ```

NVDA-045 Minor: Locale Gesture Remapping — locale/<lang>/gestures.ini for a specific layout.
  File: locale/<lang>/gestures.ini (e.g. locale/it/gestures.ini for the Italian layout)
  Overrides NVDA's default gestures for users of a specific locale.
  REQUIRED when the request asks for locale-specific gestures — create the physical file.
  Format:
    [module.ClassName]
    scriptName = gesture
  Each [section] is module.ClassName (e.g. globalCommands.GlobalCommands).
  Template locale/it/gestures.ini:
    File: locale/it/gestures.ini
```ini
    [globalCommands.GlobalCommands]
    leftMouseClick = kb(laptop):NVDA+e
    rightMouseClick = kb(laptop):NVDA+plus
    ```
  Use kb(laptop): for gestures specific to the laptop layout.

NVDA-046 Moderate: Speech Dictionaries — fix pronunciation via speechDicts/.
  REQUIRED: create the file speechDicts/<name>.dic. Without the physical file no pronunciation is fixed.
  The addon MUST include this file — a missing .dic is a fatal error.
  CRITICAL: each line has EXACTLY 4 fields separated by a real TAB (U+0009, \t).
  Do NOT use spaces as separators. NVDA rejects lines with the wrong number of fields.
  Structure: pattern\treplacement\tcase_sensitive\ttype
  Types: 0=anywhere, 1=Python regex, 2=whole word, 3=part of word, 6=wildcards.
  case_sensitive: 0=ignore case, 1=case sensitive.
  Example speechDicts/pronunciation.dic (each | represents a real TAB U+0009):
    File: speechDicts/pronunciation.dic
```ini
    NVDA	NonVisual Desktop Access	1	2
    API	A-P-I	1	2
    HTTP	H-T-T-P	0	2
    ```
  Declare it in manifest.ini:
    [speechDictionaries]
    [[pronunciation]]
    displayName = Pronunciation Fixes
    mandatory = false
  mandatory=true -> always active. mandatory=false -> the user enables it in NVDA Settings > Speech.
  NOTE: the integers 0/1/2/3/6 above are the FORMAT OF THE .dic FILE
  ("type" column, separated by TAB) -- they remain the correct and
  stable way to write the .dic file itself, they do not change. What was deprecated
  in NVDA 2026.2 is only the equivalent internal Python API (speechDictHandler.
  ENTRY_TYPE_* -> speechDictHandler.types.EntryType) for addons that
  build dictionary entries PROGRAMMATICALLY in code (rare --
  the vast majority of addons only declare the static .dic, as above). If
  the code ever needs to create entries via Python instead of the
  static .dic file, use speechDictHandler.types.EntryType, never the raw
  integers directly in Python code.

NVDA-047 Serious: manifest.ini with a url without HTTPS is rejected by the Add-on Store.
	The url field cannot be empty and MUST start with https://.
	Wrong:
		url = http://mysite.com/addon
		url =
	Correct:
		url = https://github.com/user/my-addon

NVDA-048 Critical: Never bundle wxPython in lib/.
	NVDA already provides wxPython. Bundling wx* entries in lib/ causes a version conflict,
	needlessly enlarges the package and causes unpredictable UI failures.
	Rule: dependencies[] never includes wxPython and the lib/ folder must not contain wx*.
	NOTE: "dependencies[]" is an
	INTERNAL NVDAStudio structure (the list of pip packages declared so that
	builder.py knows what to download/package into lib/) -- it is not a field of the
	real NVDA manifest.ini (addonHandler/__init__.py, AddonManifest, does not
	define "dependencies"). Do not confuse it with anything the NVDA core validates.

NVDA-040 Serious: AppModule for wwahost.exe (UWP apps) MUST inherit from nvdaBuiltin.appModules.wwahost.AppModule.
  wwahost.exe hosts UWP apps (Microsoft Store). The built-in NVDA already handles IA2 and special activation.
  Inheriting ONLY from appModuleHandler.AppModule for wwahost.exe ignores that behavior — CRITICAL BUG.
  Required file: appModules/wwahost.py
  Template:
    File: appModules/wwahost.py
```python
    import nvdaBuiltin.appModules.wwahost

    class AppModule(nvdaBuiltin.appModules.wwahost.AppModule):
        # AppModule for UWP apps hosted in wwahost.exe
        pass
    ```
  If you need to override event_gainFocus or scripts, add them to the same class.
  NEVER use: class AppModule(appModuleHandler.AppModule) — for wwahost.exe.

NVDA-026 Moderate: Import of a private NVDA symbol (_ prefix) — unstable API (skill: nvda-addon-dev §22).
  Symbols with _ in NVDA modules (e.g. _internalHelper, _cache, _privateFunc) are private.
  There is no deprecation warning — the symbol may disappear or change signature in any release.
  Wrong (breaks silently after an NVDA update):
    from someModule import _internalFunction
    from NVDAObjects.IAccessible import _specialOverride
  Correct (use only the documented public API):
    from scriptHandler import script
    from NVDAObjects.IAccessible import IAccessible
  If you need internal behavior, use extension points (§7) instead of accessing private symbols.

NVDA-027 Minor: AppModule for an app with Edge WebView2 (Developer Guide, Example 3).
  The app module takes the name of the APP (for example olk.py for the new Outlook), not msedgewebview2.py.
  WebView2 apps appear as a web page and NVDA uses browse mode in them by default.
  `disableBrowseModeByDefault: bool = True` in the AppModule class turns that off; it is optional, a
  design decision: remove the line if you want the person to navigate with the browse mode commands.

NVDA-028 Minor: Type hint using Optional/Union instead of the modern X | None or X | Y syntax (skill: nvda-addon-dev §18).
  NVDA 2026.1+ uses Python 3.13. Always use the native union syntax:
  Wrong (legacy — forbidden by the skill):
    from typing import Optional, Union
    def process(text: str, count: Optional[int] = None) -> bool: ...
    def get(value: Union[str, int]) -> None: ...
  Correct (native Python 3.10+ — required):
    def process(text: str, count: int | None = None) -> bool: ...
    def get(value: str | int) -> None: ...
  Remove all imports of Optional and Union from typing — use X | None and X | Y directly.

NVDA-029 Minor: CRLF line endings (\\r\\n) in a Python file — NVDA requires LF (\\n) (skill: nvda-addon-dev §18).
  NVDA coding standards: UTF-8 + LF. CRLF causes problems in the scons build and in git diff.
  When generating Python code, ALWAYS use Unix line breaks (\\n), never CRLF (\\r\\n).
  .py, .ini, .dic, .utb files: all must have LF.

NVDA-030 Serious: GlobalPlugin or AppModule with an __init__ that does not call super().__init__(*args, **kwargs) (skill: nvda-addon-dev §3.1, §3.2).
  Without the call, globalPluginHandler/appModuleHandler does not complete the plugin initialization —
  gestures may not be registered and the plugin fails silently when loading.
  REAL JUSTIFICATION:
  globalPluginHandler.py instantiates GlobalPlugin() WITHOUT arguments, and appModuleHandler.py
  instantiates AppModule(processID, appName) with a fixed signature -- there is NO documented
  guarantee that NVDA will pass extra arguments "in future versions". The real reason
  to require (*args, **kwargs) is simpler: it is the generic form that works
  correctly for BOTH real constructors (zero args of GlobalPlugin AND the two
  positional args of AppModule) without having to hardcode a specific signature that
  could diverge between the two types -- not a prediction of a future API change.
  Wrong:
    def __init__(self):
        super().__init__()    # does not forward processID/appName if it is an AppModule
  Correct:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
  ABSOLUTE RULE: every __init__ of a GlobalPlugin or AppModule MUST take (*args, **kwargs) and
  MUST call super().__init__(*args, **kwargs) as its first statement.

NVDA-031 Critical: SynthDriver without a cancel() method — required in the minimum viable driver (skill: nvda-addon-dev §25).
  NVDA calls cancel() when the user presses Ctrl or Escape to stop speech.
  Without cancel(), the user is stuck listening to audio they cannot interrupt.
  It is part of the "minimum viable driver" defined by the skill — it is not optional.
  Required:
    def cancel(self) -> None:
        '''Stops speech immediately.'''
        self._tts_stop()   # stop the TTS engine here
  Also required: pause(self, switch: bool) for the Ctrl toggle -- see NVDA-035.

NVDA-032 Serious: Extension point registered in __init__ without unregister in terminate() (skill: nvda-addon-dev §7).
  Every .register() in __init__ MUST have a matching .unregister() in terminate().
  Without unregister: memory leak. If the plugin is reloaded (NVDA+Ctrl+F3), the handler
  is duplicated — each NVDA event fires N times (N = reloads). No warning, no error.
  Wrong:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        speech.filter_speechSequence.register(self._filter)
    def terminate(self):
        super().terminate()   # handler still registered — memory leak
  Correct:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        speech.filter_speechSequence.register(self._filter)
    def terminate(self):
        speech.filter_speechSequence.unregister(self._filter)  # BEFORE super()
        super().terminate()
  General rule: for each .register() in __init__, one .unregister() in terminate().

NVDA-033 Serious: event_NVDAObject_init defined in GlobalPlugin — silently ignored (skill: nvda-addon-dev §5).
  event_NVDAObject_init is only called for AppModule, NEVER for GlobalPlugin.
  Putting it in a GlobalPlugin results in a handler that never runs — zero errors, zero effect.
  To customize NVDAObject properties in ANY app: use chooseNVDAObjectOverlayClasses.
  To customize in ONE specific app: move it to an AppModule.
  Wrong (GlobalPlugin — silently ignored):
    class GlobalPlugin(globalPluginHandler.GlobalPlugin):
        def event_NVDAObject_init(self, obj):  # never called here
            obj.name = "fixed"
  Correct (AppModule — works):
    class AppModule(appModuleHandler.AppModule):
        def event_NVDAObject_init(self, obj):  # called correctly
            obj.name = "fixed"

NVDA-034 Serious: AppModule for a self-voicing app without sleepMode = True (skill: nvda-addon-dev §3.3).
  Self-voicing apps (other screen readers, narrators, apps with their own TTS) speak on their
  own. Without sleepMode=True, NVDA announces focus/caret OVER the app's voice — double narration.
  Correct:
    class AppModule(appModuleHandler.AppModule):
        sleepMode = True   # turns NVDA off for this self-voicing app

NVDA-035 Serious: SynthDriver without a pause(self, switch: bool) method -- required in the minimum viable driver (skill: nvda-addon-dev §25).
  NVDA calls pause(True) to pause and pause(False) to resume speech (the user presses Ctrl).
  Without pause(), NVDA raises AttributeError when pausing -- the synthesizer crashes and must be restarted.
  It is part of the skill's minimum viable driver, listed together with cancel() -- it is not optional.
  Required:
    def pause(self, switch: bool) -> None:
        '''Pauses (True) or resumes (False) speech.'''
        self._tts_pause(switch)

NVDA-036 Critical: SynthDriver without a speak(self, speechSequence) method -- the driver's main method (skill: nvda-addon-dev §25).
  NVDA calls speak() with a list of str and SynthCommand for each piece of speech to produce.
  Without speak(), the synthesizer produces no speech at all -- completely non-functional driver.
  speak() MUST iterate over speechSequence, notify synthIndexReached for each IndexCommand and synthDoneSpeaking at the end.
  Required:
    def speak(self, speechSequence: list) -> None:
        for item in speechSequence:
            if isinstance(item, IndexCommand):
                synthDriverHandler.synthIndexReached.notify(synth=self, index=item.index)
            elif isinstance(item, str):
                self._tts_speak(item)   # your TTS call here
        synthDriverHandler.synthDoneSpeaking.notify(synth=self)


  File: brailleDisplayDrivers/<name>.py
  Required fields: name (str), description (str), numCols (int), display(cells).
  isThreadSafe=True is needed for USB/Bluetooth auto-detection.

NVDA-038 Critical: SynthDriver without the required supportedNotifications.
  synthIndexReached and synthDoneSpeaking MUST be in supportedNotifications AND must be
  notified inside speak(). Without them, 'say all', paragraph reading and braille on-index stop working.
  Required: supportedNotifications = frozenset({{synthDriverHandler.synthIndexReached,
                                                    synthDriverHandler.synthDoneSpeaking}})
  Inside speak(): notify after each IndexCommand and at the end of the sequence:
    synthDriverHandler.synthIndexReached.notify(synth=self, index=item.index)
    synthDriverHandler.synthDoneSpeaking.notify(synth=self)

NVDA-039 Moderate: AppModule for several executables without registerExecutableWithAppModule().
	When several executables of the same suite share behavior, do not duplicate
	appModules/*.py with identical code. Use NVDA's official mapping:
		appModuleHandler.registerExecutableWithAppModule("extraExecutable", "appModuleName")
	And remove it in terminate():
		appModuleHandler.unregisterExecutable("extraExecutable")
	Example:
		def __init__(self, *args, **kwargs):
				super().__init__(*args, **kwargs)
				appModuleHandler.registerExecutableWithAppModule("time", "time_app_mod")
		def terminate(self):
				appModuleHandler.unregisterExecutable("time")
				super().terminate()

  Template:
    File: brailleDisplayDrivers/NAME.py
```python
    import braille

    class BrailleDisplayDriver(braille.BrailleDisplayDriver):
        name = "myDisplay"
        description = "My Braille Display"
        numCols: int = 40        # display cells
        isThreadSafe: bool = True

        @classmethod
        def check(cls) -> bool:
            return True  # True if the hardware is available

        def __init__(self, port=None):
            super().__init__(port=port)
            # open the serial/USB/HID connection here

        def terminate(self) -> None:
            # close the connection
            super().terminate()  # ALWAYS the last line

        def display(self, cells: list[int]) -> None:
            # cells = list of ints (8-bit dot pattern per cell)
            # e.g. self._serial.write(bytes(cells))
            pass
    ```

NVDA-049 Serious: wx.MessageDialog AND wx.MessageBox are forbidden -- use gui.message.MessageDialog (skill: nvda-addon-dev §12).
  gui.message.MessageDialog is NVDA's modern API for modal dialogs -- it integrates correctly with the screen reader.
  wx.MessageDialog/wx.MessageBox are not announced correctly by NVDA; focus may not behave as a screen reader user expects.
  Thread-safe convenience methods: MessageDialog.alert(), .confirm(), .ask().
  Full modal dialog on the GUI thread:
    from gui.message import MessageDialog, DefaultButtonSet, ReturnCode
    from gui import mainFrame
    def show():
        dlg = MessageDialog(mainFrame, _("Are you sure?"), _("Confirm"), buttons=DefaultButtonSet.YES_NO)
        match dlg.ShowModal():
            case ReturnCode.YES: execute()
    wx.CallAfter(show)  # ALWAYS on the GUI thread
  Wrong: wx.MessageDialog(None, _("Ok"), _("Info"), wx.OK).ShowModal()

NVDA-050 Moderate: NVDAObject overlay class inherits from NVDAObject (base) instead of a more specific class (skill: nvda-addon-dev §6).
  Skill §6 is explicit: "Always inherit from the most specific class you need to match the object."
  Available hierarchy:
    NVDAObjects.IAccessible.IAccessible -- for MSAA/IAccessible2 objects (most Win32 apps)
    NVDAObjects.UIA.UIA                  -- for UI Automation objects (modern apps, UWP)
    NVDAObjects.window.Window            -- for generic Win32 windows
    NVDAObjects.JAB.JABObject            -- for Java Access Bridge objects
  Wrong (generic base -- loses the IAccessible2 and UIA methods):
    class MyOverlay(NVDAObject): ...
  Correct (specific class for the context):
    from NVDAObjects.IAccessible import IAccessible
    class MyOverlay(IAccessible): ...

NVDA-051 Minor: usability suggestion (the NVDA Developer Guide does not require it): an addon with its own
  interface can register an item in NVDA's Tools menu, besides the keyboard gesture.
  Menu: NVDA > Menu > Tools > [Addon Name]
  Implementation: _ensure_menu_item() + _get_tools_menu() + wx.CallAfter for thread safety.
  Removal: full cleanup in terminate() with Unbind().
  Optional example:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._menu_item = None
        self._bind_owner = None
        self._ensure_menu_item()

    def _get_tools_menu(self):
        main_frame = getattr(gui, "mainFrame", None)
        if not main_frame: return None
        menu = getattr(main_frame, "toolsMenu", None)
        if menu is not None: return menu
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
        if sys_tray and hasattr(sys_tray, "Bind"): return sys_tray
        if main_frame and hasattr(main_frame, "Bind"): return main_frame
        return None

    def _ensure_menu_item(self):
        tools_menu = self._get_tools_menu()
        if tools_menu is None:
            wx.CallLater(250, self._ensure_menu_item)
            return
        self._menu_item = tools_menu.Append(wx.ID_ANY,
            # Translators: Tools menu item
            _("My Addon\\tNVDA+Shift+M"),
            # Translators: Description of the option
            _("Opens the addon dialog"))
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
        wx.CallAfter(self._open_dialog)

Source: github.com/Community-Access/accessibility-agents .github/agents/wxpython-specialist.agent.md
WX-A11Y-001 Critical: wx.StaticText missing immediately before an input/selection control, or label= missing on wx.Button (primary fix). SetName() is a complement, not a substitute.
WX-A11Y-002 Minor (not checked): wx.Panel or wx.Frame without a wx.AcceleratorTable. NVDA itself rarely uses one; keyboard access comes from buttons, labeled controls and tab order.
WX-A11Y-003 Critical: EVT_LEFT_DOWN/EVT_LEFT_DCLICK without an equivalent keyboard event.
WX-A11Y-004 Serious: wx.Dialog without CreateStdDialogButtonSizer() or Escape handling.
WX-A11Y-005 Serious: wx.Dialog.ShowModal() without SetFocus() on a meaningful control.
WX-A11Y-006 Serious: wx.StaticBitmap or wx.BitmapButton without SetToolTip() or a wx.Accessible subclass (SetName() does not affect screen readers).
WX-A11Y-007 Moderate: wx.Colour as the only state indicator (no text/icon).
WX-A11Y-008 Moderate: wx.Timer or status bar without wx.Bell() or an accessible announcement.
WX-A11Y-009 Moderate: Custom wx.Panel with EVT_PAINT without a wx.Accessible subclass.
WX-A11Y-010 Minor: Tab order not set and does not follow the sizer.
WX-A11Y-011 Serious: wx.ListCtrl or wx.TreeCtrl in virtual mode without a GetItemText override.
WX-A11Y-012 Moderate: Menu item without an accelerator key (\tCtrl+X suffix missing).
WX-A11Y-013 Minor: EVT_KEY_DOWN/EVT_CHAR on ListBox/ListCtrl/TreeCtrl. NVDA itself uses EVT_CHAR_HOOK on list controls; EVT_LIST_KEY_DOWN exists only for wx.ListCtrl. Style note.
WX-A11Y-014 Serious: wx.ListCtrl with EVT_KEY_DOWN for Enter instead of EVT_LIST_ITEM_ACTIVATED.

Source: github.com/Community-Access/accessibility-agents .github/agents/desktop-a11y-specialist.agent.md
Platform API layer (UIA/MSAA) -- complements the WX-A11Y rules above, does not duplicate them.
DTK-A11Y-001 Critical: Interactive control without a Name exposed via UIA/MSAA -- the screen reader announces nothing.
DTK-A11Y-002 Critical: Role/ControlType does not match the control's real behavior.
DTK-A11Y-003 Serious: State change (checked/expanded/disabled/selected) not reflected in the accessibility API.
DTK-A11Y-004 Serious: Control with a value (slider/progress/spinner/field) does not expose the current value via ValuePattern/accValue.
DTK-A11Y-005 Critical: Interactive element not reachable by keyboard (no tab stop).
DTK-A11Y-006 Serious: Focus lost after a UI change (deleting an item, closing a dialog) -- it falls outside the logical destination.
DTK-A11Y-007 Moderate: Keyboard focus without a visual indicator in the default theme AND in high contrast.
DTK-A11Y-008 Moderate: Hardcoded colors instead of reading from the system theme -- breaks in High Contrast.
DTK-A11Y-009 Serious: Silent content update, without a UIA event/accessibility notification.
DTK-A11Y-010 Serious: Modal dialog does not trap focus -- Tab reaches the parent window.
DTK-A11Y-011 Minor: Custom keyboard shortcut without documentation the user can discover.
DTK-A11Y-012 Moderate: Deprecated or incorrect platform API (e.g. MSAA only instead of UIA on modern Windows).

{RULE_FALLBACK_MATRIX_TEXT}

ADDON TYPES:
globalPlugins: Work in any context. Folder: globalPlugins/addonName/__init__.py.
appModules: Specific to one .exe. Folder: appModules/exeName.py.
synthDrivers: Synthesizer drivers. Folder: synthDrivers/driverName.py.
brailleDisplayDrivers: Braille display drivers. Folder: brailleDisplayDrivers/driverName.py.

REQUIRED MANIFEST.INI:

File: manifest.ini
```ini
name = AddonName
summary = Short description
description = Full description
author = Name <email@example.com>
url = https://github.com/user/addon
docFileName = readme.html
version = 1.0.0
lastTestedNVDAVersion = {PROJECT_LAST_TESTED_NVDA}
minimumNVDAVersion = {PROJECT_MIN_NVDA}
```

INSTALL AND UNINSTALL TASKS (skill: nvda-addon-dev §11):
Optional installTasks.py file at the root of the addon package.
onInstall() -- called after extraction, before the first load. Raise to abort the installation.
onUninstall() -- called on NVDA restart after the user removes the addon. Cannot ask for input.

File: installTasks.py
```python
def onInstall() -> None:
	# Called after extraction, before the first load. Raise to abort.
	# Validate the license, copy extra files, check dependencies
	pass

def onUninstall() -> None:
	# Called on NVDA restart after removal. No user input.
	# Remove user data, clear the cache
	pass
```

STANDARD CODE TEMPLATE:

File: globalPlugins/addonName/__init__.py
```python
import wx
import gui
import globalPluginHandler
import addonHandler
from scriptHandler import script

addonHandler.initTranslation()

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = "AddonName"

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	# Translators: Description of the script that opens the main panel in the input gestures dialog
	@script(gesture="kb:NVDA+shift+x", description=_("Opens the main panel"))
	def script_openPanel(self, gesture):
		wx.CallAfter(self._open_dialog)

	def _open_dialog(self):
		dlg = MyDialog(gui.mainFrame)
		gui.mainFrame.prePopup()
		dlg.ShowModal()
		gui.mainFrame.postPopup()

	def terminate(self):
		super().terminate()

class MyDialog(wx.Dialog):
	def __init__(self, parent):
		super().__init__(parent, title="My Addon")
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.field = wx.TextCtrl(self, style=wx.TE_MULTILINE)
		self.field.SetName("Main text field")
		sizer.Add(self.field, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)
		btn_close = wx.Button(self, wx.ID_CLOSE, label="&Close")
		btn_close.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
		sizer.Add(btn_close, flag=wx.ALIGN_RIGHT | wx.ALL, border=8)
		self.SetSizer(sizer)
		self.SetSize((600, 400))
		self.Centre()
```

CRITICAL RULES (ALWAYS check in the generated code):
1. nextHandler() in every event handler (NVDA-001)
2. terminate() for cleanup (NVDA-004)
3. addonHandler.initTranslation() present (NVDA-003)
4. wx.CallAfter() to open dialogs from scripts (NVDA-010, WX-A11Y-009)
5. wx.BoxSizer for layout, never absolute positioning (WX-A11Y-005)
6. wx.StaticText before a control without a visible label, or label= on wx.Button (WX-A11Y-001)
7. & in button labels for accelerators (WX-A11Y-012)
8. try/except around external calls (never a bare except:, NVDA-012)
9. Imports always at the top of the file
10. minimumNVDAVersion >= {PROJECT_MIN_NVDA} for new NVDAStudio addons
11. CLASS NAME: globalPlugins MUST have 'class GlobalPlugin(...)'. NVDA looks up the class by the EXACT name 'GlobalPlugin'. Any other name (MyPlugin, AnnouncerPlugin, etc.) will be ignored — the addon will not load. (NVDA-001)
12. # Translators: REQUIRED before EVERY _(): every _("...") call MUST have '# Translators: description' on the immediately preceding line, NO EXCEPTIONS (NVDA-019). It applies to @script(description=_()), ui.message(_(...)), title=_(), SetName(_(...)), etc.

ESSENTIAL NVDA FUNCTIONS:
ui.message("text") makes NVDA speak immediately.
api.getFocusObject() returns the object with the current focus.
tones.beep(440, 500) emits a 440Hz beep for 500ms.
braille.handler.message() sends to the braille display.
config.conf["section"]["key"] accesses persistent settings.
core.callLater(ms, func) schedules func after a delay without blocking the UI.

SETTINGS PANEL IN NVDA SETTINGS (NVDA-015):
To register a panel in NVDA Menu > Preferences > Settings:

File: globalPlugins/myAddon/__init__.py
```python
from gui.settingsDialogs import NVDASettingsDialog
from .my_panel import MyAddonSettingsPanel

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		if MyAddonSettingsPanel not in NVDASettingsDialog.categoryClasses:
			NVDASettingsDialog.categoryClasses.append(MyAddonSettingsPanel)

	def terminate(self):
		super().terminate()
		if MyAddonSettingsPanel in NVDASettingsDialog.categoryClasses:
			NVDASettingsDialog.categoryClasses.remove(MyAddonSettingsPanel)
```

File: globalPlugins/myAddon/my_panel.py
```python
import wx
import config
from gui.settingsDialogs import SettingsPanel
from gui import guiHelper

class MyAddonSettingsPanel(SettingsPanel):
	title = "My Addon"

	def makeSettings(self, sizer):
		helper = guiHelper.BoxSizerHelper(self, sizer=sizer)
		self._api_field = helper.addLabeledControl(
			"API key:", wx.TextCtrl,
			# NVDA-025: replace "realAddonId" with the addonId from manifest.ini (e.g. "GmailSummarizer")
			value=config.conf["realAddonId"].get("apiKey", "")
		)

	def onSave(self):
		# NVDA-025: same addonId used here — must be identical to manifest.ini
		config.conf["realAddonId"]["apiKey"] = self._api_field.GetValue()
```

INTERFACE ENTRY POINT (CONTEXTUAL DECISION):
- Option A: item in the Tools menu (good for commands/the main dialog)
- Option B: panel in Settings (good for persistent preferences)
- Option C: both (when there is a main command + dedicated settings)
If the user's request does not make it clear, ASK which entry point they prefer before generating.

NVDA TOOLS MENU ITEM (when the menu is chosen):
To add an item to NVDA Menu > Tools with compatibility across APIs:

```python
import gui
import wx

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
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
			"My Addon\tNVDA+Shift+N",
			"Opens My Addon",
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
		wx.CallAfter(self._open_dialog)
```

CORRECT TIMER IN NVDA (do not use wx.CallLater directly):
```python
import core
# Schedules a call after 500ms on the core queue (thread-safe)
core.callLater(500, ui.message, "Operation complete")
```

LAYER GESTURES — OFFICIAL NVDA PATTERN:
Used when the addon has many shortcuts. The user presses a "trigger" shortcut
(e.g. NVDA+Shift+T) and then presses a simple key (e.g. T, S, A...).
Real source: the instantTranslate addon (production).

HOW IT WORKS:
1. The trigger activates layer mode (self.toggling = True)
2. getScript() intercepts all gestures while toggling=True
3. If the gesture is valid: runs the script AND then calls finish()
4. If the gesture is invalid: plays an error beep AND calls finish()
5. finish() turns layer mode off and restores the normal gestures

COMPLETE TEMPLATE:
File: globalPlugins/myAddon/__init__.py
```python
import tones
import globalPluginHandler
import addonHandler
import ui
from scriptHandler import script

addonHandler.initTranslation()

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = "MyAddon"

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.toggling = False  # flag: are we in layer mode?

	def getScript(self, gesture):
		# Intercepts gestures when layer mode is active.
		if not self.toggling:
			# Normal mode: default behavior
			return globalPluginHandler.GlobalPlugin.getScript(self, gesture)
		# Layer mode: look up the specific script
		script = globalPluginHandler.GlobalPlugin.getScript(self, gesture)
		if not script:
			# Invalid gesture: emit an error and turn the layer off
			script = self._layer_error
		# Always end the layer after running (via wrapper)
		return self._with_finish(script)

	def _with_finish(self, func):
		# Wrapper: runs func and then calls finish() even if it fails.
		def wrapper(gesture):
			try:
				func(gesture)
			finally:
				self.finish()
		return wrapper

	def finish(self):
		# Turns layer mode off and restores the normal gestures.
		self.toggling = False
		self.clearGestureBindings()
		self.bindGestures(self.__gestures)

	def _layer_error(self, gesture):
		# Invalid gesture inside the layer: low beep and exit.
		tones.beep(120, 100)

	@script(
		gesture="kb:NVDA+shift+m",
		description="Activates MyAddon layer commands. Press H to list them.",
	)
	def script_activateLayer(self, gesture):
		# Activates layer mode. A second press = error.
		if self.toggling:
			self._layer_error(gesture)
			return
		# Switch to the layer gestures
		self.bindGestures(self.__layerGestures)
		self.toggling = True
		tones.beep(100, 10)  # short beep confirms activation

	# ---- Layer scripts (simple keys) -------------------------

	@script(description="Layer action 1")
	def script_action1(self, gesture):
		ui.message("Action 1 executed")

	@script(description="Layer action 2")
	def script_action2(self, gesture):
		ui.message("Action 2 executed")

	@script(description="Lists all the layer commands")
	def script_layerHelp(self, gesture):
		ui.message(
			"Available commands: "
			"A for action 1, "
			"B for action 2, "
			"H for this help."
		)

	def terminate(self):
		super().terminate()

	# ---- Layer gesture mapping (active only while toggling) ---
	__layerGestures = {{
		"kb:a": "action1",
		"kb:b": "action2",
		"kb:h": "layerHelp",
	}}

	# ---- Normal gesture (always active) ----------------------------------
	__gestures = {{
		"kb:NVDA+shift+m": "activateLayer",
	}}
```

RULES FOR LAYER GESTURES:
- __layerGestures uses SIMPLE keys (a, b, shift+a, etc) — without NVDA+
- __gestures has ONLY the trigger (NVDA+some_key)
- finish() MUST restore with bindGestures(self.__gestures)
- tones.beep(100, 10) on the trigger — audible activation feedback
- tones.beep(120, 100) on error — lower, longer sound
- ALWAYS include script_layerHelp with kb:h listing the commands
- the getScript() override is required — without it the layer gestures
  are not intercepted correctly

MANDATORY ARCHITECTURE PATTERNS (skill: architecture-patterns, software-architecture):

1. LAYER SEPARATION (ARCH-004):
Any addon with external API calls or complex business logic MUST
split into at least 2 files inside globalPlugins/addonName/:
  __init__.py    — only GlobalPlugin, scripts, menu, lifecycle (init/terminate)
  <service>.py   — class that encapsulates the external API or domain logic

WRONG (everything in __init__.py):
File: globalPlugins/myAddon/__init__.py
```python
# 200+ lines mixing wx, requests, business logic...
```

CORRECT:
File: globalPlugins/myAddon/transcription_service.py
```python
import threading
# RULE NVDA-022: imports of third-party packages (requests, openai, googleapiclient,
# google_auth_oauthlib, etc.) NEVER at module level in service files.
# A module-level import makes __init__.py crash if lib/ is incomplete,
# and NVDA silences the error — the whole addon silently stops loading.
# ALWAYS put it inside the method that uses the package (lazy import).

class TranscriptionService:
	def __init__(self, api_key: str):
		self._api_key = api_key

	def transcribe_async(self, audio_path: str, on_done, on_error):
		# Runs in the background -- never blocks the NVDA thread.
		def _worker():
			try:
				result = self._call_api(audio_path)
				import wx
				wx.CallAfter(on_done, result)
			except Exception as exc:
				import wx
				wx.CallAfter(on_error, str(exc))
		threading.Thread(target=_worker, daemon=True).start()

	def _call_api(self, audio_path: str) -> str:
		# API logic isolated here — testable without NVDA
		import requests  # lazy — NVDA-022: do not import at module level
		resp = requests.post(
			"https://api.example.com/transcribe",
			headers={{"Authorization": f"Bearer {{self._api_key}}"}},
			files={{"audio": open(audio_path, "rb")}},
			timeout=30,
		)
		resp.raise_for_status()
		return resp.json()["text"]

	# NVDA-023: when the returned type comes from a lazy import, use a string literal.
	# Wrong: def get_credentials() -> Credentials:  # NameError — Credentials not in scope
	# Correct: def get_credentials() -> "Credentials":
	def get_credentials(self) -> "Credentials":  # noqa: F821
		from google.oauth2.credentials import Credentials  # lazy — NVDA-022
		return Credentials.from_authorized_user_file(self._token_path, self._scopes)
```

File: globalPlugins/myAddon/__init__.py
```python
import wx, gui, globalPluginHandler, addonHandler, config, ui
from scriptHandler import script
from gui.settingsDialogs import NVDASettingsDialog
from .transcription_service import TranscriptionService
from ..gui.settings_panel import MyAddonSettingsPanel

addonHandler.initTranslation()

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = "MyAddon"

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		# NVDA-015: required spec — register BEFORE any access to config.conf['realAddonId']
		config.conf.spec["realAddonId"] = {{
			"apiKey": "string(default='')",
		}}
		if MyAddonSettingsPanel not in NVDASettingsDialog.categoryClasses:
			NVDASettingsDialog.categoryClasses.append(MyAddonSettingsPanel)
		self._service: TranscriptionService | None = None

	def _get_service(self) -> TranscriptionService:
		if self._service is None:
			# NVDA-025: replace "realAddonId" with the addonId from manifest.ini
			api_key = config.conf["realAddonId"].get("apiKey", "")
			self._service = TranscriptionService(api_key)
		return self._service

	# Translators: Description of the transcription script in the input gestures dialog
	@script(gesture="kb:NVDA+shift+t", description=_("Transcribes the current audio"))
	def script_transcribe(self, gesture):
		# Translators: Message spoken when audio transcription starts
		ui.message(_("Starting transcription..."))
		self._get_service().transcribe_async(
			"path/audio.wav",
			on_done=lambda txt: ui.message(txt),
			on_error=self._on_transcription_error,  # NVDA-019: no _() in lambdas
		)

	def _on_transcription_error(self, err: str) -> None:
		# Translators: Message spoken when the transcription fails
		ui.message(_("Error: ") + err)

	def terminate(self):
		super().terminate()
		if MyAddonSettingsPanel in NVDASettingsDialog.categoryClasses:
			NVDASettingsDialog.categoryClasses.remove(MyAddonSettingsPanel)
```

2. CORRECT BACKGROUND THREAD (ARCH-002):
Every operation > 1 second MUST run in a threading.Thread with wx.CallAfter for the UI.
NEVER: requests.get() or file.read() on the main thread (it freezes all of NVDA).
```python
def _process_in_background(self, data, callback):
	def _worker():
		try:
			result = self._service.process(data)
			wx.CallAfter(callback, result)
		except Exception as exc:
			# Translators: Message spoken when the background processing fails
			wx.CallAfter(ui.message, _("Error: ") + str(exc))
	threading.Thread(target=_worker, daemon=True).start()
```

3. SETTINGS PANEL FOR API KEY (ARCH-001 + ARCH-005):
Any addon with an external API MUST generate settings_panel.py:
File: globalPlugins/myAddon/settings_panel.py
```python
import wx
import config
from gui.settingsDialogs import SettingsPanel
from gui import guiHelper

class MyAddonSettingsPanel(SettingsPanel):
	# Translators: Title of the addon's settings panel in NVDA's settings dialog
	title = _("My Addon")

	def makeSettings(self, sizer):
		helper = guiHelper.BoxSizerHelper(self, sizer=sizer)
		# Translators: Label of the API key field in the settings panel
		self._api_key = helper.addLabeledControl(
			_("&API key:"), wx.TextCtrl,
			# NVDA-025: replace "realAddonId" with the addonId from manifest.ini
			value=config.conf["realAddonId"].get("apiKey", ""),
		)
		# Translators: Accessible name of the API key field (read by screen readers)
		self._api_key.SetName(_("API key"))

	def onSave(self):
		# NVDA-025: same addonId — must be identical to manifest.ini
		config.conf["realAddonId"]["apiKey"] = self._api_key.GetValue()
```
And in GlobalPlugin.__init__, REGISTER via:
```python
if MyAddonSettingsPanel not in NVDASettingsDialog.categoryClasses:
    NVDASettingsDialog.categoryClasses.append(MyAddonSettingsPanel)
```
And in GlobalPlugin.terminate, REMOVE via:
```python
if MyAddonSettingsPanel in NVDASettingsDialog.categoryClasses:
    NVDASettingsDialog.categoryClasses.remove(MyAddonSettingsPanel)
```

5. APPMODULE — ADDON FOR A SPECIFIC APP (ARCH-003):
Use AppModule when the request mentions ONE specific application (Notepad, Firefox, Word, etc.).
File: appModules/<exe_name>.py  (e.g. notepad.py for notepad.exe)
NEVER use the name displayed to the user — use the .exe process name WITHOUT the extension.
NVDA-033: event_NVDAObject_init only works in AppModule, NEVER in GlobalPlugin.
NVDA-034: if the app is self-voicing (its own TTS), add sleepMode = True.
File: appModules/notepad.py
```python
import appModuleHandler
import addonHandler
import ui
from scriptHandler import script
from NVDAObjects import NVDAObject

addonHandler.initTranslation()

class AppModule(appModuleHandler.AppModule):
	APP_MODULE_ALLOW_SKIPINFO = True   # lets NVDA skip the default info on focus

	def event_gainFocus(self, obj: NVDAObject, nextHandler) -> None:
		# Called when focus enters any element of notepad.exe.
		# ALWAYS call nextHandler() so the event chain is not broken (NVDA-001).
		nextHandler()

	def event_NVDAObject_init(self, obj: NVDAObject) -> None:
		# Called when any NVDAObject is created inside this app.
		# ONLY in AppModule (skill: nvda-addon-dev §5) — silent in GlobalPlugin.
		# Fix properties before NVDA reads them aloud.
		if obj.role == 8 and obj.name is None:  # role: unnamed document
			obj.name = "Notepad document"

	def chooseNVDAObjectOverlayClasses(self, obj: NVDAObject, clsList: list) -> None:
		# Injects overlay classes to customize specific objects.
		# Call super() so classes already added by other modules are not removed.
		super().chooseNVDAObjectOverlayClasses(obj, clsList)
		# Example: adds editable text behavior to edit fields
		# clsList.insert(0, MyCustomClass)

	# Translators: Description of the Notepad script in the input gestures dialog
	@script(
		gesture="kb:NVDA+shift+n",
		description=_("Announces info about the current document in Notepad"),
	)
	def script_announceInfo(self, gesture: object) -> None:
		obj = self.productName  # process name
		# Translators: Message spoken when announcing document information in Notepad
		ui.message(_("Notepad active"))

	def terminate(self) -> None:
		super().terminate()
```
ARCH-003 INFERENCE: which addon type to create?
- asks for a specific app -> AppModule
  "addon for Notepad" -> appModules/notepad.py
  "addon for Firefox" -> appModules/firefox.py (or waterfox, librewolf, etc.)
  "addon for wwahost" -> NVDA-040: use nvdaBuiltin.appModules.wwahost.AppModule as the base
  "addon for an app with Edge WebView2 (olk.exe, etc.)" -> NVDA-027: the module takes the app's name; disableBrowseModeByDefault = True is optional
  "app with its own TTS / self-voicing" -> NVDA-034: include sleepMode = True
- global functionality (any app) -> GlobalPlugin
  "announce the clipboard", "global shortcut", "translation addon", etc.
- synthesizer driver -> SynthDriver
  "new synthesizer", "TTS", "speech engine", "voice driver", etc.
  File: synthDrivers/<name>.py. Requires: speak(), cancel() (NVDA-031), pause(), check().
- braille display driver -> BrailleDisplayDriver
  "braille display", "braille line", "braille driver", etc.
  File: brailleDisplayDrivers/<name>.py. Requires: required fields (NVDA-037).
- ambiguity -> ask the person before generating.
  If the type cannot be inferred, gather the necessary context.

6. EXTENSION POINTS — GLOBAL SPEECH/FOCUS CUSTOMIZATION (ARCH-006):
Use extensionPoints when you need to filter or modify speech, focus or braille GLOBALLY.
NVDA-032: EVERY .register() in __init__ MUST have .unregister() in terminate() — guaranteed memory leak.
File: globalPlugins/myAddon/__init__.py
```python
import speech
import globalPluginHandler
import addonHandler

addonHandler.initTranslation()

class GlobalPlugin(globalPluginHandler.GlobalPlugin):

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		# Registers a speech sequence filter.
		# NVDA-032: it is REQUIRED to have .unregister() in terminate().
		speech.filter_speechSequence.register(self._filter_speech)

	def _filter_speech(self, seq: list, *, user: bool) -> list:
		# Modifies the speech sequence before it reaches the synthesizer.
		# user=True: started by the user; user=False: automatic.
		# Return the list (modified or not) — never return None.
		return seq

	def terminate(self) -> None:
		# NVDA-032: unregister BEFORE super().terminate()
		speech.filter_speechSequence.unregister(self._filter_speech)
		super().terminate()
```
Event propagation order (NVDA-001, why nextHandler() matters):
  An event (e.g. gainFocus) goes through 4 stages in sequence, each of which can
  process it and pass it on via nextHandler(): GlobalPlugin -> AppModule ->
  TreeInterceptor -> NVDAObject. If any stage forgets nextHandler(),
  the following stages (including the NVDAObject itself) NEVER receive the event.
  The signature also changes per level: in GlobalPlugin/AppModule/TreeInterceptor it is
  event_<name>(self, obj, nextHandler); in NVDAObject it is just event_<name>(self)
  -- WITHOUT nextHandler, because it is the last stage of the chain.

Other useful extension points (skill: nvda-addon-dev §7):
  extensionPoints.Action  — notifies observers (no return value)
  extensionPoints.Filter  — transforms values (with a return value, like filter_speechSequence)
  extensionPoints.Decider — one handler decides, the first one that returns a bool decides
  extensionPoints.AccumulatingDecider — ALL handlers vote; decide() accumulates the votes
    (use when several addons/parts of NVDA need to weigh in on the same decision, not just one)
  extensionPoints.Chain — each handler returns an iterable (usually a generator);
    the results of all registered handlers are concatenated in sequence
    (5th type documented in the official Developer Guide,
    it was missing here -- the same register()/unregister() in terminate() rule applies)
  speech.speechCanceled   — (Action) fired when speech is canceled
  braille.pre_writeCells  — (Filter) filters cells before writing to the display

Automatic NVDAObject property pattern (lazy getters/setters):
  _get_<propName>(self)          — called automatically when accessing obj.<propName>
  _set_<propName>(self, value)   — called automatically when assigning obj.<propName> = value
  Real examples: _get_name(self), _get_role(self), _get_states(self) in overlay classes
  used with chooseNVDAObjectOverlayClasses. NEVER override name/role directly in
  __init__ — always via _get_<propName>, otherwise the value gets frozen and does not update.

TreeInterceptor (browse mode for rich content — web pages, documents):
  Base class: treeInterceptorHandler.TreeInterceptor (usually via DocumentTreeInterceptor
  or cursorManager.CursorManager, not the bare TreeInterceptor in practice).
  Main methods to override: _get_documentText(self), _get_currentNode(self) and the
  navigation event handlers (event_caret, event_gainFocus inside the TreeInterceptor).
  Only use TreeInterceptor if the addon needs to offer virtual buffer navigation over
  content the app does not expose via standard UI Automation/IAccessible (e.g. apps with custom
  rendering). For most addons (simple GlobalPlugin/AppModule) this does NOT apply.

7. ORGANIZE BY FEATURE, NOT BY LOOSE FILES (ARCH-007):
Dedicated 2026 research (vertical slice / feature-based organization): when the addon has
3 or more substantial and distinct features/services (e.g. integrates Spotify + does transcription
+ manages playlists — different domains, not methods of the same API), each one goes in its
own subpackage named after the feature inside globalPlugins/<addon_name>/, NOT in
generic loose files (helper.py, utils.py, misc.py) nor everything directly at the package root.
```text
globalPlugins/MyAddon/
  __init__.py            <- only orchestrates: imports and uses each subpackage, never implements the feature
  spotify/
    __init__.py
    client.py             <- HTTP calls to the Spotify Web API
  transcription/
    __init__.py
    service.py             <- integration with the transcription library
  playlists/
    __init__.py
    manager.py
```
For 1-2 features (the most common case), loose file(s) at the package root are still
enough (see ARCH-004) — do not create a subpackage for a single service class.

WHEN DELIVERING AN ADDON:
complete manifest.ini; complete Python code with docstrings and terminate();
verification of all the rules NVDA-001 to NVDA-040, NVDA-042..NVDA-062 and WX-A11Y-001 to WX-A11Y-014 (use addon_validate);
architectural inference ARCH-001..009 before writing the code.
"""

# Local copy of the NVDA and AddonTemplate source code (text, never imported).
NVDA_DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nvda_docs_cache")
