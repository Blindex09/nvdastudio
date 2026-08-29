def _get_system() -> str:
    from nvdastudio.sub_agents.code_generator import _SYSTEM
    return _SYSTEM


# ===========================================================================
# NVDA-004: super().terminate() no FINAL do terminate()
# ===========================================================================

class TestNVDA004SuperTerminateFinal:
    """
    A skill §3.1 mostra explicitamente que super().terminate() fica NO FINAL.
    Se o modelo colocar super() no inicio, o cleanup de recursos nao ocorre
    porque super() pode encerrar o estado que o cleanup precisa.
    """

    def test_system_tem_regra_nvda004(self):
        system = _get_system()
        assert "NVDA-004" in system, (
            "_SYSTEM nao tem regra NVDA-004. O modelo coloca super().terminate() "
            "no inicio do terminate(), abortando o cleanup de recursos."
        )

    def test_nvda004_instrui_super_no_final(self):
        system = _get_system()
        # Busca o heading da regra na secao Detailed Rules (tem 'ULTIMA' logo depois)
        idx = system.find("NVDA-004 Serio")
        assert idx != -1
        regra = system[idx:idx + 600]
        assert "final" in regra.lower() or "ultimo" in regra.lower() or "last" in regra.lower(), (
            "NVDA-004 deve instruir explicitamente que super().terminate() "
            "deve ser a ULTIMA linha do terminate()."
        )

    def test_nvda004_item_na_verificacao_final(self):
        system = _get_system()
        idx_vf = system.find("VERIFICACAO FINAL")
        assert idx_vf != -1
        vf = system[idx_vf:]
        assert "NVDA-004" in vf or "super().terminate" in vf, (
            "A VERIFICACAO FINAL nao cobre super().terminate() no final."
        )


# ===========================================================================
# NVDA-030: super().__init__(*args, **kwargs) obrigatorio
# ===========================================================================

class TestNVDA030SuperInit:
    """
    A skill §3.1 mostra que __init__ SEMPRE chama super().__init__(*args, **kwargs).
    Sem isso, o GlobalPlugin nao inicializa corretamente e crasha ao carregar.
    O _SYSTEM tem o template correto mas nao tem regra explicita proibindo omitir.
    """

    def test_system_tem_regra_nvda030(self):
        system = _get_system()
        assert "NVDA-030" in system, (
            "_SYSTEM nao tem regra NVDA-030. O modelo pode omitir "
            "super().__init__(*args, **kwargs) causando crash ao carregar o addon."
        )

    def test_nvda030_menciona_args_kwargs(self):
        system = _get_system()
        # Busca o heading da regra na secao Detailed Rules (tem *args/**kwargs no conteudo)
        idx = system.find("NVDA-030 Serio")
        assert idx != -1
        regra = system[idx:idx + 500]
        assert "*args" in regra and "**kwargs" in regra, (
            "NVDA-030 deve mencionar *args e **kwargs — omiti-los "
            "causa TypeError se NVDA passar argumentos inesperados."
        )


# ===========================================================================
# Regra-LOG: logHandler.log obrigatorio — print()/logging nao funcionam
# ===========================================================================

class TestRegraLOGLogHandler:
    """
    A skill §12 e §18 sao claras: todo logging usa logHandler.log.
    - print() no NVDA vai para /dev/null — nao aparece em lugar algum.
    - logging.getLogger() (Python padrao) nao esta integrado ao sistema do NVDA.
    """

    def test_system_tem_regra_log(self):
        system = _get_system()
        assert "Regra-LOG" in system, (
            "_SYSTEM nao tem regra Regra-LOG. O modelo usa logging.getLogger() "
            "que nao funciona no NVDA — output vai para o vacuo."
        )

    def test_regra_log_instrui_loghandler(self):
        system = _get_system()
        idx = system.find("Regra-LOG")
        assert idx != -1
        regra = system[idx:idx + 600]
        assert "logHandler" in regra, (
            "Regra-LOG deve mencionar logHandler como o modulo correto."
        )

    def test_regra_log_proibe_print(self):
        system = _get_system()
        idx = system.find("Regra-LOG")
        assert idx != -1
        regra = system[idx:idx + 600]
        assert "print" in regra.lower(), (
            "Regra-LOG deve proibir print() — output desaparece no NVDA."
        )

    def test_regra_log_mostra_uso_correto_log(self):
        system = _get_system()
        idx = system.find("Regra-LOG")
        assert idx != -1
        regra = system[idx:idx + 600]
        assert "log.debug" in regra or "log.info" in regra or "log.error" in regra, (
            "Regra-LOG deve mostrar o uso correto: log.debug/info/error."
        )


# ===========================================================================
# NVDA-029: UTF-8 + LF line endings
# ===========================================================================

class TestNVDA029EncodingLF:
    """
    A skill §18 e explicita: UTF-8 encoding, LF line endings (nao CRLF).
    CRLF em arquivos .py pode causar SyntaxError no Python do NVDA (cp311)
    em contextos onde o parser e mais estrito com line endings.
    O NVDAStudio nunca instrui o modelo sobre encoding.
    """

    def test_system_tem_regra_nvda029(self):
        system = _get_system()
        assert "NVDA-029" in system, (
            "_SYSTEM nao tem regra NVDA-029. O modelo pode gerar arquivos "
            "com CRLF que causam SyntaxError no Python 3.11 do NVDA."
        )

    def test_nvda029_menciona_lf(self):
        system = _get_system()
        idx = system.find("NVDA-029")
        assert idx != -1
        regra = system[idx:idx + 400]
        assert "LF" in regra or "line ending" in regra.lower(), (
            "NVDA-029 deve mencionar LF (nao CRLF) como line ending correto."
        )

    def test_nvda029_menciona_utf8(self):
        system = _get_system()
        idx = system.find("NVDA-029")
        assert idx != -1
        regra = system[idx:idx + 400]
        assert "UTF-8" in regra or "utf-8" in regra.lower(), (
            "NVDA-029 deve mencionar UTF-8 como encoding correto."
        )
