def _get_system() -> str:
    from nvdastudio.sub_agents.code_generator import _SYSTEM
    return _SYSTEM


class TestNVDA024TemplateSemGet:
    """
    O template do NVDA-024 NAO deve usar .get() em config.conf.
    Se o template tem .get(), o modelo reproduz esse padrao em todos os campos,
    incluindo SpinCtrl onde .get() retorna string e causa TypeError.
    """

    def test_template_nvda026_nao_usa_get_em_config_conf(self):
        """O template de settings_panel.py no _SYSTEM nao deve ter .get() em ConfigObj."""
        system = _get_system()
        # Localiza o bloco do template NVDA-024
        idx = system.find("TEMPLATE COMPLETO do arquivo settings_panel.py")
        assert idx != -1, "_SYSTEM nao tem bloco 'TEMPLATE COMPLETO do arquivo settings_panel.py'"
        template_section = system[idx:idx + 1500]
        assert 'config.conf["addonIdReal"].get(' not in template_section, (
            "O template NVDA-024 tem .get() em config.conf — isso propaga o bug para "
            "todos os addons gerados. ConfigObj retorna strings; .get() bypassa a "
            "validacao do configspec e causa TypeError em wx.SpinCtrl."
        )

    def test_template_nvda026_usa_acesso_direto_por_chave(self):
        """O template deve usar config.conf['secao']['chave'] sem .get()."""
        system = _get_system()
        idx = system.find("TEMPLATE COMPLETO do arquivo settings_panel.py")
        assert idx != -1
        template_section = system[idx:idx + 1500]
        # O acesso correto no onSave ja existe; o makeSettings tambem deve usar
        # config.conf["addonIdReal"]["apiKey"] e nao .get()
        assert 'config.conf["addonIdReal"]["' in template_section, (
            "O template NVDA-024 deve acessar configuracoes via "
            "config.conf['addonIdReal']['chave'] sem .get(), "
            "para que ConfigObj valide e coaja o tipo correto (int, bool, etc.)."
        )


class TestNVDA015ProibeGetEmConfigObj:
    """
    O _SYSTEM deve ter regra NVDA-015 proibindo .get() em ConfigObj.
    Sem essa regra, o modelo usa .get() em todo campo, incluindo SpinCtrl,
    causando TypeError silencioso e Tab escapando do painel.
    """

    def test_system_tem_regra_nvda015(self):
        """_SYSTEM deve mencionar NVDA-015."""
        system = _get_system()
        assert "NVDA-015" in system, (
            "_SYSTEM nao tem regra NVDA-015. Sem ela, o modelo usa "
            "config.conf['secao'].get() em SpinCtrl e causa TypeError silencioso."
        )

    def test_nvda015_proibe_get_em_config_conf(self):
        """NVDA-015 deve mencionar que .get() em ConfigObj e proibido."""
        system = _get_system()
        assert "NVDA-015" in system
        # Busca pela regra especifica do .get() (pode haver outro NVDA-015 antes)
        idx = system.find("NUNCA use .get()")
        assert idx != -1, "_SYSTEM deve ter regra explicita 'NUNCA use .get()' em config.conf."
        regra = system[idx:idx + 600]
        assert ".get(" in regra, (
            "NVDA-015 deve mencionar explicitamente que .get() em config.conf e proibido."
        )

    def test_nvda015_menciona_spinctrl_ou_tipo(self):
        """NVDA-015 deve explicar o perigo de tipo errado (string vs int)."""
        system = _get_system()
        idx = system.find("NVDA-015")
        assert idx != -1
        # NVDA-015 pode estar em dois lugares (comentario no template + regra completa)
        # Busca em todo o system a partir do primeiro NVDA-015
        regra = system[idx:]
        assert "string" in regra.lower() or "int" in regra.lower() or "SpinCtrl" in regra, (
            "NVDA-015 deve explicar que ConfigObj retorna strings e .get() bypassa "
            "a coercao de tipo — causando falha em SpinCtrl, CheckBox, etc."
        )

    def test_nvda015_mostra_acesso_correto(self):
        """NVDA-015 deve mostrar o padrao correto de acesso."""
        system = _get_system()
        idx = system.find("NUNCA use .get()")
        assert idx != -1
        regra = system[idx:idx + 600]
        # O padrao correto e config.conf["secao"]["chave"] sem .get()
        assert 'config.conf[' in regra and ']["' in regra, (
            "NVDA-015 deve mostrar config.conf['secao']['chave'] como padrao correto."
        )

    def test_nvda015_item_na_verificacao_final(self):
        """A VERIFICACAO FINAL deve ter item cobrindo o proibicao de .get() em ConfigObj."""
        system = _get_system()
        idx_vf = system.find("VERIFICACAO FINAL")
        assert idx_vf != -1
        vf_section = system[idx_vf:]
        assert "NVDA-015" in vf_section or ".get(" in vf_section or "configSpec" in vf_section, (
            "A VERIFICACAO FINAL nao cobre o uso proibido de .get() em ConfigObj. "
            "Sem esse item, o modelo nao auto-verifica antes de responder."
        )
