def _get_system() -> str:
    from nvdastudio.sub_agents.code_generator import _SYSTEM
    return _SYSTEM


# ===========================================================================
# NVDA-036: Extension Points — register/unregister obrigatorio
# ===========================================================================

class TestNVDA032ExtensionPoints:
    """
    A skill §7 e clara: todo register() em __init__ DEVE ter unregister()
    correspondente no terminate(). Sem isso, o handler permanece registrado
    mesmo apos o addon ser desativado, causando memory leak e comportamento
    erratico (ex: filtro de fala continua ativo apos desinstalar o addon).
    NVDA-032 = extension point register sem unregister correspondente.
    """

    def test_system_tem_regra_nvda032(self):
        system = _get_system()
        assert "NVDA-032" in system, (
            "_SYSTEM nao tem regra NVDA-032. O modelo pode gerar "
            "extensionPoints.register() sem unregister() no terminate() — "
            "memory leak e handler ativo apos desinstalar."
        )

    def test_nvda032_menciona_unregister(self):
        system = _get_system()
        idx = system.find("NVDA-032 Serio")
        assert idx != -1
        regra = system[idx:idx + 600]
        assert "unregister" in regra, (
            "NVDA-032 deve mencionar unregister() como obrigatorio no terminate()."
        )

    def test_nvda032_menciona_register(self):
        system = _get_system()
        idx = system.find("NVDA-032 Serio")
        assert idx != -1
        regra = system[idx:idx + 600]
        assert "register" in regra, (
            "NVDA-032 deve mostrar o padrao register() no __init__."
        )

    def test_nvda032_item_na_verificacao_final(self):
        system = _get_system()
        idx_vf = system.find("VERIFICACAO FINAL")
        assert idx_vf != -1
        vf = system[idx_vf:]
        assert "NVDA-032" in vf or "unregister" in vf, (
            "A VERIFICACAO FINAL nao cobre extension points sem unregister."
        )


# ===========================================================================
# NVDA-037: BrailleDisplayDriver — template completo
# ===========================================================================

class TestNVDA037BrailleDisplayDriver:
    """
    A skill §26 define BrailleDisplayDriver com numCols, display(), isThreadSafe.
    O _SYSTEM so tem NVDA-011 (check() obrigatorio). Sem template completo,
    o modelo geraria um driver sem numCols (NVDA nao sabe o tamanho do display)
    e sem display() (metodo obrigatorio para enviar celulas ao hardware).
    """

    def test_system_tem_regra_nvda037(self):
        system = _get_system()
        assert "NVDA-037" in system, (
            "_SYSTEM nao tem regra NVDA-037. BrailleDisplayDriver gerado "
            "sem numCols e display() nao funciona no NVDA."
        )

    def test_nvda037_menciona_numCols(self):
        system = _get_system()
        idx = system.find("NVDA-037")
        assert idx != -1
        regra = system[idx:]
        assert "numCols" in regra, (
            "NVDA-037 deve mencionar numCols — sem ele o NVDA nao sabe "
            "quantas celulas o display tem."
        )

    def test_nvda037_menciona_display_method(self):
        system = _get_system()
        idx = system.find("NVDA-037")
        assert idx != -1
        regra = system[idx:]
        assert "def display" in regra or "display(self, cells" in regra or "display(cells)" in regra, (
            "NVDA-037 deve mostrar o metodo display() — e obrigatorio para "
            "enviar os padroes de celulas ao hardware."
        )

    def test_nvda037_menciona_isThreadSafe(self):
        system = _get_system()
        idx = system.find("NVDA-037")
        assert idx != -1
        regra = system[idx:]
        assert "isThreadSafe" in regra, (
            "NVDA-037 deve mencionar isThreadSafe — necessario para auto-deteccao."
        )


# ===========================================================================
# NVDA-038: Speech Dictionaries — formato speechDicts/
# ===========================================================================

class TestNVDA038SpeechDictionaries:
    """
    A skill §19 define speechDicts/ com formato de 4 campos tab-separados:
    pattern, replacement, caseSensitive, type.
    Completamente ausente do _SYSTEM. Sem isso o modelo nao sabe como
    gerar dicionarios de pronuncia para addons que precisam corrigir
    palavras mal pronunciadas pelo sintetizador.
    """

    def test_system_tem_regra_nvda038(self):
        system = _get_system()
        assert "NVDA-038" in system, (
            "_SYSTEM nao tem regra NVDA-038. O modelo nao sabe o formato "
            "de speechDicts/ para dicionarios de pronuncia."
        )

    def test_nvda038_menciona_speechDicts(self):
        system = _get_system()
        idx = system.find("NVDA-038")
        assert idx != -1
        regra = system[idx:]
        assert "speechDicts" in regra, (
            "NVDA-038 deve mencionar o diretorio speechDicts/."
        )

    def test_nvda038_menciona_formato_4_campos(self):
        system = _get_system()
        idx = system.find("NVDA-038")
        assert idx != -1
        regra = system[idx:]
        assert "caseSensitive" in regra or "replacement" in regra, (
            "NVDA-038 deve mostrar o formato dos 4 campos tab-separados: "
            "pattern, replacement, caseSensitive, type."
        )

    def test_nvda038_menciona_manifest_speechDictionaries(self):
        system = _get_system()
        idx = system.find("NVDA-038")
        assert idx != -1
        regra = system[idx:]
        assert "speechDictionar" in regra or "manifest" in regra.lower(), (
            "NVDA-038 deve mencionar a secao [speechDictionaries] do manifest.ini."
        )
