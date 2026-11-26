"""Fatos sobre o NVDA 2026.3.1, extraidos do codigo-fonte oficial (nvaccess/nvda, tag release-2026.3.1).

Usados pelas regras para nao acusar addon que usa o que o proprio NVDA ja traz.
Para atualizar: releia `source/` (modulos), `pyproject.toml` (dependencias) e
`source/config/configSpec.py` (secoes) da nova versao.
"""

# Modulos de topo de source/ (importaveis por qualquer addon).
NVDA_CORE_MODULES: frozenset[str] = frozenset({
    "IAccessibleHandler", "JABHandler", "NVDAHelper", "NVDAObjects", "NVDAState", "RPCConstants",
    "UIAHandler", "XMLFormatting", "_asyncioEventLoop", "_bridge", "_magnifier", "_remoteClient",
    "_synthDrivers32", "addonAPIVersion", "addonHandler", "addonStore", "annotation", "api",
    "appModuleHandler", "appModules", "argsParsing", "aria", "audio", "audioDucking",
    "autoSettingsUtils", "baseObject", "bdDetect", "braille", "brailleDisplayDrivers",
    "brailleInput", "brailleTables", "brailleViewer", "browseMode", "buildVersion",
    "characterProcessing", "colors", "comHelper", "comInterfaces", "compoundDocuments", "config",
    "contentRecog", "controlTypes", "core", "cursorManager", "diffHandler", "displayModel",
    "documentBase", "documentNavigation", "documentationUtils", "driverHandler", "easeOfAccess",
    "editableText", "eventHandler", "exceptions", "extensionPoints", "fileUtils", "fonts", "ftdi2",
    "garbageHandler", "globalCommands", "globalPluginHandler", "globalPlugins", "globalVars",
    "gui", "hidpi", "hwIo", "hwPortUtils", "images", "inputCore", "installer", "jobObject",
    "keyCommandsDoc", "keyLabels", "keyboardHandler", "l10nUtil", "languageHandler", "locale",
    "localesData", "locationHelper", "logHandler", "louisHelper", "markdownTranslate", "mathPres",
    "mathType", "md2html", "monkeyPatches", "mouseHandler", "msoAutoShapeTypes", "nvdaBuiltin",
    "nvwave", "objbase", "objidl", "oleTypes", "oleacc", "pythonConsole", "queueHandler",
    "remotePythonConsole", "review", "screenBitmap", "screenCurtain", "screenExplorer",
    "scriptHandler", "shellapi", "shlobj", "speech", "speechDictHandler", "speechViewer",
    "speechXml", "synthDriverHandler", "synthDrivers", "synthSettingsRing", "systemUtils",
    "tableUtils", "tactile", "textInfos", "textUtils", "tones", "touchHandler", "touchTracker",
    "treeInterceptorHandler", "ui", "updateCheck", "utils", "versionInfo", "virtualBuffers",
    "vision", "visionEnhancementProviders", "vkCodes", "wasapi", "watchdog", "waves", "winAPI",
    "winBindings", "winConsoleHandler", "winGDI", "winInputHook", "winKernel", "winUser",
    "winVersion", "wincon", "windowUtils",
})

# Pacotes pip que o NVDA traz (nomes de import). O Developer Guide recomenda empacotar a propria copia, mas importar a do NVDA funciona.
NVDA_RUNTIME_PACKAGES: frozenset[str] = frozenset({
    "bleak", "comtypes", "cryptography", "serial", "wx", "configobj", "requests", "url_normalize",
    "schedule", "fast_diff_match_patch", "pycaw", "rpyc", "win32api", "win32con", "win32gui",
    "win32com", "win32process", "win32event", "win32file", "win32pipe", "win32security",
    "win32service", "win32clipboard", "pythoncom", "pywintypes", "nh3", "crowdin_api",
    "fuzzysearch", "markdown", "lxml", "mdx_truly_sane_lists", "mdx_gh_links", "l2m4m", "pymdownx",
    "pyphen", "detect_secrets", "regex",
})

# Secoes de config.conf que pertencem ao proprio NVDA (config/configSpec.py).
NVDA_CONFIG_SECTIONS: frozenset[str] = frozenset({
    "general", "speech", "audio", "braille", "vision", "magnifier", "presentation", "mouse",
    "speechViewer", "brailleViewer", "keyboard", "virtualBuffers", "touch", "documentFormatting",
    "documentNavigation", "reviewCursor", "UIA", "annotations", "terminals", "update",
    "inputComposition", "debugLog", "uwpOcr", "editableText", "development", "featureFlag",
    "addonStore", "remote", "math", "screenCurtain",
})
