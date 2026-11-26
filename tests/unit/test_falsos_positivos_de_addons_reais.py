"""Falsos positivos achados ao validar os addons instalados no NVDA (cada um e um caso real).

Cada teste monta a menor pasta de addon que reproduz o caso e confere que a regra nao acusa
codigo correto. Os fatos do NVDA usados como criterio vem do codigo-fonte 2026.3.1.
"""

import os

from nvdastudio_mcp.addon_builder import (
    _manifest_scalar_errors,
    _sanitize_manifest,
    validate_addon_structure,
    write_addon_file,
)
from nvdastudio_mcp.rule_registry import DEFECT_CODES, POLICY_CODES, rule_kind
from nvdastudio_mcp.scaffold import build_scaffold

NL = chr(10)
TAB = chr(9)
Q3 = chr(34) * 3

PLUGIN = NL.join([
    "import globalPluginHandler",
    "",
    "",
    "class GlobalPlugin(globalPluginHandler.GlobalPlugin):",
    TAB + "def terminate(self):",
    TAB + TAB + "super().terminate()",
    "",
])


def _addon(tmp_path, extra=None, manifest=None, remove=()):
    files = build_scaffold("Meu").files
    files["globalPlugins/Meu/__init__.py"] = PLUGIN
    if manifest is not None:
        files["manifest.ini"] = manifest
    files.update(extra or {})
    for rel in remove:
        files.pop(rel, None)
    for rel, content in files.items():
        write_addon_file(str(tmp_path), rel, content)
    return str(tmp_path)


def _codes(tmp_path, **kwargs):
    return [p.split(":")[0] for p in validate_addon_structure(_addon(tmp_path, **kwargs))]


# --- manifest -------------------------------------------------------------

OFFICIAL_MANIFEST = NL.join([
    "name = meu",
    'summary = "Meu addon"',
    "description = " + Q3 + "Linha um, com virgula." + NL + "Linha dois." + Q3,
    'author = "A B <a@b.c>"',
    'url = "https://github.com/a/b"',
    "version = 1.0",
    "changelog = " + Q3 + "- um, dois" + NL + "- tres" + Q3,
    "docFileName = readme.html",
    "minimumNVDAVersion = 2026.1.1",
    "lastTestedNVDAVersion = 2026.3.1",
    "",
])


def test_manifest_no_formato_do_template_oficial_nao_e_acusado():
    """AbsoluteWindows e powerbox: description/changelog entre aspas triplas, com virgulas."""
    assert _manifest_scalar_errors(OFFICIAL_MANIFEST) == []


def test_sanitizador_nao_corrompe_aspas_triplas():
    """Antes virava quatro aspas: description = " + Q3 + '"Linha um...'."""
    assert _sanitize_manifest(OFFICIAL_MANIFEST).replace(chr(13), "") == OFFICIAL_MANIFEST.rstrip(NL)


def test_valor_sem_aspas_com_virgula_continua_sendo_acusado_e_corrigido():
    manifest = "name = x" + NL + "summary = a, b" + NL
    assert _manifest_scalar_errors(manifest)
    assert "summary = " + chr(34) + "a, b" + chr(34) in _sanitize_manifest(manifest)


def test_url_do_manifest_entre_aspas_nao_dispara_nvda047(tmp_path):
    assert "NVDA-047" not in _codes(tmp_path, manifest=OFFICIAL_MANIFEST)


def test_manifest_oficial_nao_gera_manifest_001_no_validador(tmp_path):
    assert "MANIFEST-001" not in _codes(tmp_path, manifest=OFFICIAL_MANIFEST)


# --- estrutura ------------------------------------------------------------

def test_ponto_de_entrada_fino_que_importa_a_classe(tmp_path):
    extra = {
        "globalPlugins/Meu/__init__.py": "from .core import GlobalPlugin" + NL,
        "globalPlugins/Meu/core.py": PLUGIN,
    }
    assert "STRUCTURE-005" not in _codes(tmp_path, extra=extra)


def test_addon_so_de_dados_nao_precisa_de_ponto_de_entrada(tmp_path):
    """Acapela TTS Voices: so bin/ e data/, sem codigo."""
    files = {
        "manifest.ini": build_scaffold("Meu").files["manifest.ini"],
        "data/Brazilian/voz.dat": "x",
        "bin/Selector.conf": "x",
    }
    for rel, content in files.items():
        write_addon_file(str(tmp_path), rel, content)
    assert "STRUCTURE-003" not in [p.split(":")[0] for p in validate_addon_structure(str(tmp_path))]


def test_addon_sem_nada_alem_do_manifest_continua_sendo_acusado(tmp_path):
    write_addon_file(str(tmp_path), "manifest.ini", build_scaffold("Meu").files["manifest.ini"])
    assert "STRUCTURE-003" in [p.split(":")[0] for p in validate_addon_structure(str(tmp_path))]


def test_import_relativo_dentro_de_string_ou_funcao_nao_e_acusado(tmp_path):
    code = NL.join([
        "EXEMPLO = " + Q3 + "from .nao_existe import algo" + Q3,
        "",
        "def tardio():",
        TAB + "from .tambem_nao_existe import coisa",
        TAB + "return coisa",
        "",
    ])
    assert "STRUCTURE-009" not in _codes(tmp_path, extra={"globalPlugins/Meu/servico.py": code})


def test_import_relativo_de_modulo_ausente_na_carga_continua_sendo_acusado(tmp_path):
    extra = {
        "globalPlugins/Meu/__init__.py": PLUGIN + "from . import servico" + NL,
        "globalPlugins/Meu/servico.py": "from .ausente import x" + NL,
    }
    assert "STRUCTURE-009" in _codes(tmp_path, extra=extra)


def test_modulo_com_import_quebrado_que_ninguem_importa_nao_impede_o_carregamento(tmp_path):
    """addon antigo nvdastudio: uma copia do fonte do NVDA dentro da pasta, nunca importada."""
    extra = {"globalPlugins/Meu/copia/__init__.py": "from .nao_copiado import x" + NL}
    assert "STRUCTURE-009" not in _codes(tmp_path, extra=extra)


# --- gettext --------------------------------------------------------------

def test_modulo_com_gettext_sem_initTranslation_e_so_conselho(tmp_path):
    """simpleChatGPT/ui.py: o NVDA instala o _ em builtins, entao nao ha NameError."""
    code = NL.join(["def titulo():", TAB + "# Translators: titulo", TAB + 'return _("ChatGPT")', ""])
    codes = _codes(tmp_path, extra={"globalPlugins/Meu/ui.py": code})
    assert "NVDA-003" in codes and rule_kind("NVDA-003") == "advisory"


def test_comentario_com_a_palavra_initTranslation_nao_conta_como_chamada(tmp_path):
    code = NL.join(["# lembrar de chamar initTranslation", "def t():", TAB + "# Translators: x", TAB + 'return _("x")', ""])
    assert "NVDA-003" in _codes(tmp_path, extra={"globalPlugins/Meu/ui.py": code})


# --- assinaturas, config, imports ----------------------------------------

def test_property_que_devolve_classe_nao_dispara_nvda063(tmp_path):
    """instantTranslate: self.translatorClass(...) chama a classe devolvida pela property."""
    code = NL.join([
        "import globalPluginHandler",
        "",
        "",
        "class GlobalPlugin(globalPluginHandler.GlobalPlugin):",
        TAB + "@property",
        TAB + "def translatorClass(self):",
        TAB + TAB + "return dict",
        "",
        TAB + "def usar(self):",
        TAB + TAB + "return self.translatorClass(a=1)",
        "",
        TAB + "def terminate(self):",
        TAB + TAB + "super().terminate()",
        "",
    ])
    assert "NVDA-063" not in _codes(tmp_path, extra={"globalPlugins/Meu/__init__.py": code})


def test_config_conf_de_secao_do_proprio_nvda_nao_pede_spec(tmp_path):
    """facundia: config.conf["audio"]["outputDevice"] e do NVDA, nao do addon."""
    code = NL.join(["import config", "", "def saida():", TAB + 'return config.conf["audio"]["outputDevice"]', ""])
    assert "NVDA-015" not in _codes(tmp_path, extra={"globalPlugins/Meu/audio.py": code})


def test_config_conf_de_secao_propria_sem_spec_continua_sendo_apontado(tmp_path):
    code = NL.join(["import config", "", "def valor():", TAB + 'return config.conf["meuAddon"]["x"]', ""])
    assert "NVDA-015" in _codes(tmp_path, extra={"globalPlugins/Meu/cfg.py": code})


def test_import_de_pacote_que_o_nvda_traz_ou_o_addon_empacota_nao_e_acusado(tmp_path):
    code = NL.join(["import configobj", "import winVersion", "import dep_empacotada", "", "def f():", TAB + "pass", ""])
    extra = {"globalPlugins/Meu/servico.py": code, "globalPlugins/Meu/lib/dep_empacotada.py": "X = 1" + NL}
    assert "NVDA-022" not in _codes(tmp_path, extra=extra)


def test_import_de_terceiro_nao_empacotado_continua_sendo_apontado(tmp_path):
    code = NL.join(["import biblioteca_que_nao_existe_no_nvda", "", "def f():", TAB + "pass", ""])
    assert "NVDA-022" in _codes(tmp_path, extra={"globalPlugins/Meu/servico.py": code})


def test_binario_x86_e_aceito_quando_o_addon_ainda_suporta_o_nvda_32_bits(tmp_path):
    """VisionAssistant: minimumNVDAVersion 2025.1 e traz lib/x86 e lib/x64."""
    pe32 = b"MZ" + bytes(0x3A) + (0x40).to_bytes(4, "little") + b"PE" + bytes(2) + (0x14C).to_bytes(2, "little")
    folder = _addon(tmp_path, manifest=OFFICIAL_MANIFEST.replace("minimumNVDAVersion = 2026.1.1", "minimumNVDAVersion = 2025.1"))
    target = os.path.join(folder, "globalPlugins", "Meu", "lib", "x86")
    os.makedirs(target)
    with open(os.path.join(target, "_modulo.pyd"), "wb") as handle:
        handle.write(pe32)
    assert "NVDA-017" not in [p.split(":")[0] for p in validate_addon_structure(folder)]


def test_binario_x86_continua_sendo_defeito_quando_o_minimo_e_2026_1(tmp_path):
    pe32 = b"MZ" + bytes(0x3A) + (0x40).to_bytes(4, "little") + b"PE" + bytes(2) + (0x14C).to_bytes(2, "little")
    folder = _addon(tmp_path)
    target = os.path.join(folder, "globalPlugins", "Meu", "lib")
    os.makedirs(target)
    with open(os.path.join(target, "_modulo.pyd"), "wb") as handle:
        handle.write(pe32)
    assert "NVDA-017" in [p.split(":")[0] for p in validate_addon_structure(folder)]


# --- categorias -----------------------------------------------------------

def test_so_defeito_bloqueia_e_o_padrao_de_regra_nova_e_conselho():
    assert rule_kind("NVDA-063") == "defect" and rule_kind("STRUCTURE-009") == "defect"
    assert rule_kind("POLICY-002") == "policy" and rule_kind("NVDA-047") == "policy"
    assert rule_kind("NVDA-019") == "advisory" and rule_kind("QUALQUER-999") == "advisory"
    assert not (DEFECT_CODES & POLICY_CODES)


def test_manifest_que_nao_e_utf8_vira_problema_e_nao_derruba_o_validador(tmp_path):
    folder = _addon(tmp_path)
    with open(os.path.join(folder, "manifest.ini"), "wb") as handle:
        handle.write(b"name = Meu" + bytes([13, 10]) + b"summary = caf" + bytes([0xE9]) + bytes([13, 10]))
    assert isinstance(validate_addon_structure(folder), list)
