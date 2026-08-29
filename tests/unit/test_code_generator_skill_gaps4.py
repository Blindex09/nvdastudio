def _get_system() -> str:
    from nvdastudio.sub_agents.code_generator import _SYSTEM
    return _SYSTEM


# ===========================================================================
# NVDA-039: registerExecutableWithAppModule
# ===========================================================================

class TestNVDA039RegisterExecutable:
    """
    A skill §3.2 mostra que quando um AppModule precisa funcionar com mais
    de um executavel, usa-se registerExecutableWithAppModule() no GlobalPlugin.
    Sem isso o modelo nao sabe como cobrir apps com multiplos .exe.
    Ex: um app que tem launcher.exe + app.exe — precisa registrar ambos.
    """

    def test_system_tem_regra_nvda039(self):
        system = _get_system()
        assert "NVDA-039" in system, (
            "_SYSTEM nao tem regra NVDA-039. O modelo nao sabe como mapear "
            "multiplos executaveis para um mesmo AppModule."
        )

    def test_nvda039_menciona_registerExecutableWithAppModule(self):
        system = _get_system()
        idx = system.find("NVDA-039")
        assert idx != -1
        regra = system[idx:]
        assert "registerExecutableWithAppModule" in regra, (
            "NVDA-039 deve mencionar registerExecutableWithAppModule()."
        )

    def test_nvda039_menciona_unregisterExecutable(self):
        system = _get_system()
        idx = system.find("NVDA-039")
        assert idx != -1
        regra = system[idx:]
        assert "unregisterExecutable" in regra, (
            "NVDA-039 deve mencionar unregisterExecutable() no terminate() "
            "— par obrigatorio do register (NVDA-036)."
        )


# ===========================================================================
# NVDA-040: Hosts especiais
# ===========================================================================

class TestNVDA040HostsEspeciais:
    """
    A skill §3.2 lista 3 hosts especiais com tratamento diferente:
    - wwahost.exe: herdar de nvdaBuiltin.appModules.wwahost.AppModule
    - msedgewebview2.exe: setar disableBrowseModeByDefault = True
    - javaw.exe: nomear modulo por AppModule.appName (nao pelo .exe)
    Sem isso o modelo gera AppModule incorreto para UWP, Electron e Java.
    """

    def test_system_tem_regra_nvda040(self):
        system = _get_system()
        assert "NVDA-040" in system, (
            "_SYSTEM nao tem regra NVDA-040. O modelo gera AppModule incorreto "
            "para apps UWP (wwahost), WebView2/Electron e Java."
        )

    def test_nvda040_menciona_wwahost(self):
        system = _get_system()
        idx = system.find("NVDA-040")
        assert idx != -1
        regra = system[idx:]
        assert "wwahost" in regra, (
            "NVDA-040 deve mencionar wwahost.exe e heranca de wwahost.AppModule."
        )

    def test_nvda040_menciona_webview2(self):
        system = _get_system()
        idx = system.find("NVDA-040")
        assert idx != -1
        regra = system[idx:]
        assert "WebView2" in regra or "msedgewebview2" in regra, (
            "NVDA-040 deve mencionar msedgewebview2.exe e disableBrowseModeByDefault."
        )

    def test_nvda040_menciona_javaw(self):
        system = _get_system()
        idx = system.find("NVDA-040")
        assert idx != -1
        regra = system[idx:]
        assert "javaw" in regra, (
            "NVDA-040 deve mencionar javaw.exe e o uso de AppModule.appName."
        )


# ===========================================================================
# NVDA-041: Sleep Mode
# ===========================================================================

class TestNVDA041SleepMode:
    """
    A skill §3.3 define sleepMode = True para apps autoloquentes que gerem
    sua propria acessibilidade (ex: jogos, leitores de tela alternativos).
    Com sleepMode = True, o NVDA desativa todos os seus recursos para aquela app.
    Sem isso o modelo nunca gera essa propriedade.
    """

    def test_system_tem_regra_nvda034_sleepmode(self):
        system = _get_system()
        # NVDA-041 foi renomeado para NVDA-034 (ID correto em NVDA_DETECTION_RULES)
        assert "NVDA-034" in system, (
            "_SYSTEM nao tem regra NVDA-034. O modelo nunca gera sleepMode = True "
            "para apps autoloquentes."
        )

    def test_nvda034_menciona_sleepMode(self):
        system = _get_system()
        idx = system.find("NVDA-034")
        assert idx != -1
        regra = system[idx:]
        assert "sleepMode" in regra, (
            "NVDA-034 deve mencionar sleepMode = True."
        )

    def test_nvda034_explica_quando_usar(self):
        system = _get_system()
        idx = system.find("NVDA-034")
        assert idx != -1
        regra = system[idx:idx + 400]
        assert "autoloquen" in regra.lower() or "self-voic" in regra.lower() or "propria" in regra.lower(), (
            "NVDA-034 deve explicar quando usar sleepMode — apps que gerenciam "
            "sua propria acessibilidade."
        )


# ===========================================================================
# NVDA-042: ngettext / pgettext para plural e contexto
# ===========================================================================

class TestNVDA042Ngettext:
    """
    A skill §8 mostra ngettext() para strings no plural e pgettext() para
    strings com contexto (desambiguacao). Sem isso o modelo usa _() para tudo,
    inclusive strings que deveriam variar no plural — producao de texto
    gramaticalmente errado como '1 itens encontrados'.
    """

    def test_system_tem_regra_nvda042(self):
        system = _get_system()
        assert "NVDA-042" in system, (
            "_SYSTEM nao tem regra NVDA-042. O modelo usa _() onde deveria usar "
            "ngettext() — gera '1 itens encontrados' em vez de '1 item encontrado'."
        )

    def test_nvda042_menciona_ngettext(self):
        system = _get_system()
        idx = system.find("NVDA-042")
        assert idx != -1
        regra = system[idx:]
        assert "ngettext" in regra, (
            "NVDA-042 deve mencionar ngettext() para strings no plural."
        )

    def test_nvda042_menciona_pgettext(self):
        system = _get_system()
        idx = system.find("NVDA-042")
        assert idx != -1
        regra = system[idx:]
        assert "pgettext" in regra, (
            "NVDA-042 deve mencionar pgettext() para strings com contexto."
        )

    def test_nvda042_mostra_exemplo_de_uso(self):
        system = _get_system()
        idx = system.find("NVDA-042")
        assert idx != -1
        regra = system[idx:]
        # deve ter pelo menos um exemplo de chamada
        assert "ngettext(" in regra, (
            "NVDA-042 deve mostrar um exemplo de chamada ngettext()."
        )
