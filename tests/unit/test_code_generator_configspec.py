def _get_system() -> str:
    from nvdastudio.sub_agents.code_generator import _SYSTEM
    return _SYSTEM


class TestNVDA024TemInstrucaoConfigSpec:
    """
    O NVDA-024 deve instruir a criar configSpec.py com apply_config_spec().
    Sem isso, o modelo gera o settings_panel.py mas nao registra o spec,
    config.conf["secao"] lanca KeyError, e o Tab escapa para outro addon.
    """

    def test_nvda024_menciona_configspec(self):
        """NVDA-024 deve mencionar configSpec.py."""
        system = _get_system()
        idx = system.find("NVDA-024")
        assert idx != -1
        regra = system[idx:]
        assert "configSpec" in regra or "config_spec" in regra.lower(), (
            "NVDA-024 nao menciona configSpec.py. Sem spec registrado, "
            "config.conf['secao'] lanca KeyError no makeSettings."
        )

    def test_nvda024_menciona_apply_config_spec(self):
        """NVDA-024 deve instruir a chamar apply_config_spec() no __init__.py."""
        system = _get_system()
        idx = system.find("NVDA-024")
        assert idx != -1
        regra = system[idx:]
        assert "apply_config_spec" in regra, (
            "NVDA-024 nao instrui apply_config_spec(). O modelo gera o painel "
            "mas nao registra o spec — config.conf['secao'] lanca KeyError."
        )

    def test_nvda026_template_configspec_tem_string_default(self):
        """O template de configSpec.py deve mostrar o formato correto de spec."""
        system = _get_system()
        assert "string(default=" in system or "integer(default=" in system, (
            "O _SYSTEM nao mostra o formato de spec do ConfigObj. "
            "O modelo nao sabe como definir os tipos e defaults corretos."
        )

    def test_nvda026_template_configspec_separado_do_settings_panel(self):
        """O template deve mostrar configSpec.py como arquivo separado."""
        system = _get_system()
        assert "configSpec.py" in system, (
            "O _SYSTEM nao mostra 'configSpec.py' como arquivo separado. "
            "O modelo pode colocar o spec inline no settings_panel.py em vez "
            "de criar o arquivo correto."
        )

    def test_nvda026_verificacao_final_cobre_configspec(self):
        """A VERIFICACAO FINAL deve ter item cobrindo configSpec + apply_config_spec."""
        system = _get_system()
        idx_vf = system.find("VERIFICACAO FINAL")
        assert idx_vf != -1
        vf = system[idx_vf:]
        assert "configSpec" in vf or "apply_config_spec" in vf, (
            "A VERIFICACAO FINAL nao cobre configSpec/apply_config_spec. "
            "O modelo nao vai auto-verificar se o spec esta registrado."
        )
