"""As checagens por arquivo valem para todo ponto de entrada, nao so globalPlugins/."""

from nvdastudio_mcp.addon_builder import validate_addon_structure, write_addon_file
from nvdastudio_mcp.scaffold import build_scaffold

NL = chr(10)
TAB = chr(9)

APP_MODULE_RUIM = NL.join([
    "import addonHandler",
    "import appModuleHandler",
    "from .ausente import coisa",
    "",
    "addonHandler.initTranslation()",
    "",
    "class AppModule(appModuleHandler.AppModule):",
    TAB + "def event_gainFocus(self, obj, nextHandler):",
    TAB + TAB + "pass",
    "",
])


def _addon(tmp_path, code):
    files = build_scaffold("MeuAddon", "appModule", "Teste", app_name="notepad").files
    files["appModules/notepad.py"] = code
    for rel, content in files.items():
        write_addon_file(str(tmp_path), rel, content)
    return str(tmp_path)


def test_app_module_sem_nexthandler_e_reportado(tmp_path):
    problems = validate_addon_structure(_addon(tmp_path, APP_MODULE_RUIM))
    assert any(p.startswith("NVDA-001") and "notepad.py" in p for p in problems), problems


def test_app_module_com_import_relativo_orfao_e_reportado(tmp_path):
    problems = validate_addon_structure(_addon(tmp_path, APP_MODULE_RUIM))
    assert any(p.startswith("STRUCTURE-009") and "ausente" in p for p in problems), problems


def test_app_module_correto_continua_sem_problemas(tmp_path):
    files = build_scaffold("MeuAddon", "appModule", "Teste", app_name="notepad").files
    for rel, content in files.items():
        write_addon_file(str(tmp_path), rel, content)
    assert validate_addon_structure(str(tmp_path)) == []
