def _get_system() -> str:
    from nvdastudio.sub_agents.code_generator import _SYSTEM
    return _SYSTEM


# ===========================================================================
# NVDA-033: event_NVDAObject_init e chooseNVDAObjectOverlayClasses
#           so funcionam em AppModule — nao em GlobalPlugin
# ===========================================================================

class TestNVDA033HooksApenasAppModule:
    """
    A skill §3.2 avisa: event_NVDAObject_init e chooseNVDAObjectOverlayClasses
    so funcionam em AppModule. Se o modelo gerar esses hooks num GlobalPlugin,
    silenciosamente nao fazem nada — o addon parece correto mas nao funciona.
    """

    def test_system_tem_regra_nvda033(self):
        system = _get_system()
        assert "NVDA-033" in system, (
            "_SYSTEM nao tem regra NVDA-033. O modelo pode gerar "
            "chooseNVDAObjectOverlayClasses/event_NVDAObject_init num GlobalPlugin "
            "onde silenciosamente nao funcionam."
        )

    def test_nvda033_menciona_appmodule(self):
        system = _get_system()
        idx = system.find("NVDA-033 Serio")
        assert idx != -1
        regra = system[idx:idx + 500]
        assert "AppModule" in regra, (
            "NVDA-033 deve mencionar AppModule como o unico lugar "
            "onde esses hooks funcionam."
        )

    def test_nvda033_menciona_chooseNVDAObjectOverlayClasses(self):
        system = _get_system()
        idx = system.find("NVDA-033 Serio")
        assert idx != -1
        regra = system[idx:idx + 500]
        assert "chooseNVDAObjectOverlayClasses" in regra, (
            "NVDA-033 deve mencionar chooseNVDAObjectOverlayClasses."
        )


# ===========================================================================
# Orientacao AppModule: AppModule vs GlobalPlugin — quando usar cada
# ===========================================================================

class TestOrientacaoAppModuleVsGlobalPlugin:
    """
    A skill §3.2 define AppModule para addons de uma aplicacao especifica.
    O _SYSTEM so tem template de GlobalPlugin. O modelo nao sabe quando
    gerar AppModule (nomeado pelo .exe, class AppModule(AppModule)).
    """

    def test_system_tem_orientacao_appmodule(self):
        system = _get_system()
        assert "Orientacao AppModule" in system, (
            "_SYSTEM nao tem orientacao de AppModule vs GlobalPlugin. O modelo nunca gera AppModule — "
            "tudo vira GlobalPlugin, inclusive addons especificos para uma app."
        )

    def test_orientacao_appmodule_menciona_exe(self):
        system = _get_system()
        idx = system.find("Orientacao AppModule")
        assert idx != -1
        regra = system[idx:idx + 600]
        assert ".exe" in regra or "executavel" in regra.lower() or "appModules" in regra, (
            "Orientacao AppModule deve explicar que AppModule e nomeado pelo .exe da aplicacao "
            "e fica em appModules/."
        )

    def test_orientacao_appmodule_distingue_quando_usar_cada_tipo(self):
        system = _get_system()
        idx = system.find("Orientacao AppModule")
        assert idx != -1
        regra = system[idx:idx + 600]
        assert "GlobalPlugin" in regra, (
            "Orientacao AppModule deve contrastar AppModule com GlobalPlugin para o modelo "
            "saber quando usar cada um."
        )


# ===========================================================================
# skill §11: installTasks.py — onInstall/onUninstall
# ===========================================================================

class TestSkill11InstallTasks:
    """
    A skill §11 define installTasks.py com onInstall() e onUninstall().
    O NVDAStudio nunca gera esse arquivo. Para addons que precisam
    copiar arquivos extras, validar licenca ou limpar dados ao desinstalar.
    """

    def test_system_tem_regra_skill11(self):
        system = _get_system()
        assert "skill §11" in system, (
            "_SYSTEM nao tem referencia a skill §11. O modelo nunca gera installTasks.py "
            "com onInstall/onUninstall."
        )

    def test_skill11_menciona_oninstall(self):
        system = _get_system()
        idx = system.find("skill §11")
        assert idx != -1
        regra = system[idx:idx + 500]
        assert "onInstall" in regra, (
            "skill §11 deve mencionar onInstall()."
        )

    def test_skill11_menciona_onuninstall(self):
        system = _get_system()
        idx = system.find("skill §11")
        assert idx != -1
        regra = system[idx:idx + 500]
        assert "onUninstall" in regra, (
            "skill §11 deve mencionar onUninstall()."
        )

    def test_skill11_menciona_installtasks_py(self):
        system = _get_system()
        idx = system.find("skill §11")
        assert idx != -1
        regra = system[idx:idx + 500]
        assert "installTasks" in regra, (
            "skill §11 deve mencionar o arquivo installTasks.py."
        )


# ===========================================================================
# NVDA-036: SynthDriver — supportedCommands e supportedNotifications obrigatorios
# ===========================================================================

class TestNVDA036SynthDriverObrigatorios:
    """
    A skill §25 e explicita: SynthDriver DEVE ter speak(), supportedCommands e
    supportedNotifications. Sem eles:
    - sem speak(): driver nao produz nenhuma fala
    - sem supportedCommands: NVDA nao converte commands para speak()
    - sem supportedNotifications: 'ler tudo' e callbacks de indice falham
    """

    def test_system_tem_regra_nvda036(self):
        system = _get_system()
        assert "NVDA-036" in system, (
            "_SYSTEM nao tem regra NVDA-036. SynthDriver gerado sem "
            "supportedCommands/supportedNotifications quebra 'ler tudo' e "
            "callbacks de indice silenciosamente."
        )

    def test_nvda036_menciona_supportedCommands(self):
        system = _get_system()
        idx = system.find("NVDA-036")
        assert idx != -1
        regra = system[idx:idx + 600]
        assert "supportedCommands" in regra, (
            "NVDA-036 deve mencionar supportedCommands como obrigatorio."
        )

    def test_nvda036_menciona_supportedNotifications(self):
        system = _get_system()
        idx = system.find("NVDA-036")
        assert idx != -1
        regra = system[idx:idx + 600]
        assert "supportedNotifications" in regra, (
            "NVDA-036 deve mencionar supportedNotifications como obrigatorio."
        )

    def test_nvda036_menciona_synthIndexReached_e_synthDoneSpeaking(self):
        system = _get_system()
        idx = system.find("NVDA-036")
        assert idx != -1
        regra = system[idx:]  # busca do NVDA-036 ate o fim
        assert "synthIndexReached" in regra or "synthDoneSpeaking" in regra, (
            "NVDA-036 deve mencionar synthIndexReached e synthDoneSpeaking "
            "como as duas notificacoes obrigatorias."
        )

    def test_nvda036_menciona_speak(self):
        system = _get_system()
        idx = system.find("NVDA-036 Critico")
        assert idx != -1, "_SYSTEM deve ter regra 'NVDA-036 Critico' na secao Detailed Rules."
        regra = system[idx:idx + 800]
        assert "speak" in regra, (
            "NVDA-036 deve mencionar speak() como metodo principal do SynthDriver "
            "(skill: nvda-addon-dev §25). Sem speak() o driver nao produz nenhuma fala."
        )
