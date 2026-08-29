import os


def _make_addon(tmp_path, init_code="", extra_files=None, manifest=None):
    """
    Factory de addon para testes.
    skill: testing-patterns — sempre use factory functions, nunca dados duplicados.

    extra_files: dict {filename: code} para modulos de suporte em globalPlugins/<nome>/
    """
    gp = os.path.join(str(tmp_path), "globalPlugins", "MeuAddon")
    os.makedirs(gp)
    doc = os.path.join(str(tmp_path), "doc", "en")
    os.makedirs(doc)
    with open(os.path.join(doc, "userGuide.html"), "w") as f:
        f.write("<html><body>Guia</body></html>")

    # manifest padrao
    mf = manifest or (
        "name = MeuAddon\nsummary = MeuAddon\nauthor = Teste <teste@exemplo.com>\n"
        "version = 1.0.0\n"
        "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.2.0\n"
    )
    with open(os.path.join(str(tmp_path), "manifest.ini"), "w") as f:
        f.write(mf)

    # __init__.py
    if init_code:
        with open(os.path.join(gp, "__init__.py"), "w") as f:
            f.write(init_code)

    # modulos de suporte extras
    for fname, code in (extra_files or {}).items():
        with open(os.path.join(gp, fname), "w") as f:
            f.write(code)

    return str(tmp_path)


_INIT_CORRETO = """\
import globalPluginHandler
import addonHandler
addonHandler.initTranslation()

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
\tdef terminate(self):
\t\tsuper().terminate()
"""

_MODULO_SUPORTE = """\
# Modulo de servico — sem GlobalPlugin, sem initTranslation, sem terminate
class GmailService:
\tdef __init__(self):
\t\tpass
\tdef summarize(self):
\t\treturn []
"""

_SETTINGS_PANEL = """\
import wx
from gui.settingsDialogs import SettingsPanel

class MeuAddonSettingsPanel(SettingsPanel):
\ttitle = "Meu Addon"
\tdef makeSettings(self, sizer):
\t\tpass
\tdef onSave(self):
\t\tpass
"""


class TestModulosDeSuporteNaoGeram005_003_004:
    """
    Comportamento central: modulos de suporte nunca devem gerar
    ESTRUTURA-005, NVDA-003 e NVDA-004.

    skill: testing-patterns — describe blocks por comportamento, nao por funcao.
    skill: unit-testing-test-generate — identifica o cenario de producao real (GmailSummarizer).
    """

    def test_modulo_servico_nao_gera_estrutura_005(self, tmp_path):
        """gmail_service.py sem GlobalPlugin nao deve gerar ESTRUTURA-005."""
        from nvdastudio.builder.addon_builder import validate_addon_structure
        addon = _make_addon(
            tmp_path,
            init_code=_INIT_CORRETO,
            extra_files={"gmail_service.py": _MODULO_SUPORTE},
        )
        problems = validate_addon_structure(addon)
        ids = [p.split(":")[0] for p in problems]
        assert "ESTRUTURA-005" not in ids, (
            "ESTRUTURA-005 nao deve aparecer para modulos de suporte — "
            f"problemas: {problems}"
        )

    def test_modulo_servico_nao_gera_nvda_003(self, tmp_path):
        """gmail_service.py sem initTranslation nao deve gerar NVDA-003."""
        from nvdastudio.builder.addon_builder import validate_addon_structure
        addon = _make_addon(
            tmp_path,
            init_code=_INIT_CORRETO,
            extra_files={"gmail_service.py": _MODULO_SUPORTE},
        )
        problems = validate_addon_structure(addon)
        ids = [p.split(":")[0] for p in problems]
        assert "NVDA-003" not in ids, (
            f"NVDA-003 nao deve aparecer para modulos de suporte — problemas: {problems}"
        )

    def test_modulo_servico_nao_gera_nvda_004(self, tmp_path):
        """gmail_service.py sem terminate() nao deve gerar NVDA-004."""
        from nvdastudio.builder.addon_builder import validate_addon_structure
        addon = _make_addon(
            tmp_path,
            init_code=_INIT_CORRETO,
            extra_files={"gmail_service.py": _MODULO_SUPORTE},
        )
        problems = validate_addon_structure(addon)
        ids = [p.split(":")[0] for p in problems]
        assert "NVDA-004" not in ids, (
            f"NVDA-004 nao deve aparecer para modulos de suporte — problemas: {problems}"
        )

    def test_settings_panel_nao_gera_falsos_positivos(self, tmp_path):
        """settings_panel.py sem GlobalPlugin/initTranslation/terminate nao gera falsos positivos."""
        from nvdastudio.builder.addon_builder import validate_addon_structure
        addon = _make_addon(
            tmp_path,
            init_code=_INIT_CORRETO,
            extra_files={"settings_panel.py": _SETTINGS_PANEL},
        )
        problems = validate_addon_structure(addon)
        ids = [p.split(":")[0] for p in problems]
        for regra in ("ESTRUTURA-005", "NVDA-003", "NVDA-004"):
            assert regra not in ids, (
                f"{regra} nao deve aparecer para settings_panel.py — problemas: {problems}"
            )

    def test_addon_com_cinco_modulos_suporte_zero_falsos_positivos(self, tmp_path):
        """
        Cenario de producao: addon com __init__.py correto + 5 modulos de suporte.
        Simula GmailSummarizer com gmail_service, settings_panel, ai_runner,
        summarizer_service, config_spec.
        Nenhum deles deve gerar ESTRUTURA-005, NVDA-003, NVDA-004.
        """
        from nvdastudio.builder.addon_builder import validate_addon_structure
        extras = {
            "gmail_service.py": _MODULO_SUPORTE,
            "settings_panel.py": _SETTINGS_PANEL,
            "ai_runner.py": "class AIRunner:\n\tpass\n",
            "summarizer_service.py": "class SummarizerService:\n\tpass\n",
            "config_spec.py": "SPEC = {}\n",
        }
        addon = _make_addon(tmp_path, init_code=_INIT_CORRETO, extra_files=extras)
        problems = validate_addon_structure(addon)
        falsos = [p for p in problems if any(
            p.startswith(r) for r in ("ESTRUTURA-005", "NVDA-003", "NVDA-004")
        )]
        assert falsos == [], (
            f"Nenhum falso positivo esperado para modulos de suporte, "
            f"mas encontrou: {falsos}"
        )


class TestInitPyContinuaVerificado:
    """
    ESTRUTURA-005, NVDA-003, NVDA-004 devem continuar sendo verificados
    no __init__.py — a correcao nao pode desativar a validacao real.
    """

    def test_init_sem_global_plugin_gera_005(self, tmp_path):
        """__init__.py sem GlobalPlugin DEVE gerar ESTRUTURA-005."""
        from nvdastudio.builder.addon_builder import validate_addon_structure
        addon = _make_addon(
            tmp_path,
            init_code="import addonHandler\naddonHandler.initTranslation()\n",
        )
        problems = validate_addon_structure(addon)
        ids = [p.split(":")[0] for p in problems]
        assert "ESTRUTURA-005" in ids, (
            f"__init__.py sem GlobalPlugin deveria gerar ESTRUTURA-005 — problemas: {problems}"
        )

    def test_init_sem_init_translation_gera_003(self, tmp_path):
        """__init__.py sem initTranslation DEVE gerar NVDA-003."""
        from nvdastudio.builder.addon_builder import validate_addon_structure
        code = (
            "import globalPluginHandler\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "\tdef terminate(self): super().terminate()\n"
        )
        addon = _make_addon(tmp_path, init_code=code)
        problems = validate_addon_structure(addon)
        ids = [p.split(":")[0] for p in problems]
        assert "NVDA-003" in ids, (
            f"__init__.py sem initTranslation deveria gerar NVDA-003 — problemas: {problems}"
        )

    def test_init_sem_terminate_gera_004(self, tmp_path):
        """__init__.py sem terminate() DEVE gerar NVDA-004."""
        from nvdastudio.builder.addon_builder import validate_addon_structure
        code = (
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "\tpass\n"
        )
        addon = _make_addon(tmp_path, init_code=code)
        problems = validate_addon_structure(addon)
        ids = [p.split(":")[0] for p in problems]
        assert "NVDA-004" in ids, (
            f"__init__.py sem terminate deveria gerar NVDA-004 — problemas: {problems}"
        )


class TestNVDA007NaoEhMaisDeterministico:
    """
    NVDA-007 (__gestures) saiu do checklist deterministico em 4.5.0: a doc
    oficial do NVDA trata __gestures como alternativa valida, e o julgamento
    de contexto (uso legitimo vs. ruim) agora e do critic.py, nao de um
    regex fixo aplicado igual a todo addon.
    """

    def test_gestures_em_modulo_suporte_nao_gera_nvda_007(self, tmp_path):
        """__gestures em modulo de suporte NAO deve mais gerar NVDA-007 deterministico."""
        from nvdastudio.builder.addon_builder import validate_addon_structure
        code_com_gestures = _MODULO_SUPORTE + "\n__gestures = {}\n"
        addon = _make_addon(
            tmp_path,
            init_code=_INIT_CORRETO,
            extra_files={"helper.py": code_com_gestures},
        )
        problems = validate_addon_structure(addon)
        ids = [p.split(":")[0] for p in problems]
        assert "NVDA-007" not in ids, (
            f"NVDA-007 nao deve mais vir do checklist deterministico — problemas: {problems}"
        )

    def test_gestures_em_init_nao_gera_nvda_007(self, tmp_path):
        """__gestures no __init__.py tambem NAO deve mais gerar NVDA-007 deterministico."""
        from nvdastudio.builder.addon_builder import validate_addon_structure
        code = _INIT_CORRETO + "\n__gestures = {'kb:NVDA+t': 'algo'}\n"
        addon = _make_addon(tmp_path, init_code=code)
        problems = validate_addon_structure(addon)
        ids = [p.split(":")[0] for p in problems]
        assert "NVDA-007" not in ids


class TestAddonCorretoContinuaZeroProblemas:
    """
    skill: verification-before-completion — a correcao nao pode criar regressoes.
    Um addon bem estruturado com modulos de suporte deve continuar sem problemas.
    """

    def test_addon_completo_correto_zero_problemas(self, tmp_path):
        """Addon com __init__.py correto e modulos de suporte = zero problemas."""
        from nvdastudio.builder.addon_builder import validate_addon_structure
        extras = {
            "gmail_service.py": _MODULO_SUPORTE,
            "settings_panel.py": _SETTINGS_PANEL,
        }
        addon = _make_addon(tmp_path, init_code=_INIT_CORRETO, extra_files=extras)
        problems = validate_addon_structure(addon)
        # Filtra NVDA-017 (binarios .pyd) que nao e foco desse teste
        relevantes = [p for p in problems if not p.startswith("NVDA-017")]
        assert relevantes == [], f"Addon correto nao deve ter problemas — encontrou: {relevantes}"


class TestSubpacoteInitNaoDisparaFalsoPositivo:
    """
    Bug real achado pelo golden eval set do pipeline completo (test_e36,
    2026-08-07, addon AssistenteLeituraGemini): ESTRUTURA-005/NVDA-003/
    NVDA-004/NVDA-051 checavam QUALQUER __init__.py da arvore (fname ==
    "__init__.py" sozinho), nao so o principal -- um addon com subpacotes
    legitimos (busca_web/__init__.py, resumo/__init__.py, etc., cada um so
    reexportando algo) gerou 5 falsos positivos identicos, mesmo com o
    __init__.py principal 100% correto. Ver addon_builder.py 4.6.0.
    """

    def test_subpacote_com_init_de_reexport_nao_dispara_estrutura005(self, tmp_path):
        addon = _make_addon(tmp_path, init_code=_INIT_CORRETO)
        subpkg = os.path.join(addon, "globalPlugins", "MeuAddon", "busca_web")
        os.makedirs(subpkg)
        with open(os.path.join(subpkg, "__init__.py"), "w") as f:
            f.write("from .servico import BuscaWebServico\n")
        with open(os.path.join(subpkg, "servico.py"), "w") as f:
            f.write("class BuscaWebServico:\n\tdef buscar(self, q):\n\t\treturn q\n")

        from nvdastudio.builder.addon_builder import validate_addon_structure
        problems = validate_addon_structure(addon)
        relevantes = [p for p in problems if not p.startswith("NVDA-017")]
        assert relevantes == [], (
            f"__init__.py de subpacote (so reexport) nao deveria gerar "
            f"ESTRUTURA-005/NVDA-003/NVDA-004 — encontrou: {relevantes}"
        )

    def test_varios_subpacotes_com_init_nao_multiplicam_falso_positivo(self, tmp_path):
        """Reproducao proxima do caso real: 4 subpacotes, cada um com seu
        proprio __init__.py de reexport -- zero problemas, nao 4x ESTRUTURA-005."""
        addon = _make_addon(tmp_path, init_code=_INIT_CORRETO)
        gp = os.path.join(addon, "globalPlugins", "MeuAddon")
        for nome in ("busca_web", "resumo", "perguntas", "historico"):
            subpkg = os.path.join(gp, nome)
            os.makedirs(subpkg)
            with open(os.path.join(subpkg, "__init__.py"), "w") as f:
                f.write(f"# reexport do modulo {nome}\n")

        from nvdastudio.builder.addon_builder import validate_addon_structure
        problems = validate_addon_structure(addon)
        relevantes = [p for p in problems if not p.startswith("NVDA-017")]
        assert relevantes == [], (
            f"4 subpacotes com __init__.py nao deveriam gerar problema algum "
            f"— encontrou: {relevantes}"
        )

    def test_init_principal_com_bug_real_ainda_e_detectado(self, tmp_path):
        """Regressao inversa: o __init__.py PRINCIPAL sem GlobalPlugin
        continua sendo pego, mesmo com subpacotes presentes -- a correcao
        nao pode virar um jeito de nunca mais detectar o bug real."""
        addon = _make_addon(tmp_path, init_code="import addonHandler\naddonHandler.initTranslation()\n")
        gp = os.path.join(addon, "globalPlugins", "MeuAddon")
        subpkg = os.path.join(gp, "busca_web")
        os.makedirs(subpkg)
        with open(os.path.join(subpkg, "__init__.py"), "w") as f:
            f.write("from .servico import X\n")

        from nvdastudio.builder.addon_builder import validate_addon_structure
        problems = validate_addon_structure(addon)
        assert any("ESTRUTURA-005" in p for p in problems), (
            f"__init__.py principal sem GlobalPlugin deveria continuar sendo "
            f"detectado mesmo com subpacotes presentes — problemas: {problems}"
        )
