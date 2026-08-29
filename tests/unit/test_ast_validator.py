# ---------------------------------------------------------------------------
# Helpers de import — import feito dentro de cada teste para falhar RED limpo
# ---------------------------------------------------------------------------

def _import_validator():
    from nvdastudio.sub_agents.ast_validator import (
        validate_nvda019,
        validate_wx_a11y,
        ASTValidationResult,
    )
    return validate_nvda019, validate_wx_a11y, ASTValidationResult


# ===========================================================================
# 1. Contrato basico do modulo
# ===========================================================================

class TestModuloExiste:
    def test_modulo_importavel(self):
        """ast_validator deve existir e ser importavel."""
        from nvdastudio.sub_agents import ast_validator  # noqa: F401

    def test_validate_nvda019_existe(self):
        from nvdastudio.sub_agents.ast_validator import validate_nvda019
        assert callable(validate_nvda019)

    def test_validate_wx_a11y_existe(self):
        from nvdastudio.sub_agents.ast_validator import validate_wx_a11y
        assert callable(validate_wx_a11y)

    def test_result_tem_ok_e_violacoes(self):
        from nvdastudio.sub_agents.ast_validator import ASTValidationResult
        r = ASTValidationResult(ok=True, violacoes=[])
        assert r.ok is True
        assert r.violacoes == []

    def test_result_ok_false_com_violacoes(self):
        from nvdastudio.sub_agents.ast_validator import ASTValidationResult
        r = ASTValidationResult(ok=False, violacoes=["linha 5"])
        assert r.ok is False
        assert len(r.violacoes) == 1

    def test_module_version_existe(self):
        from nvdastudio.sub_agents.ast_validator import MODULE_VERSION
        assert MODULE_VERSION == "1.3.0"

    def test_validate_wx_accelerator_existe(self):
        from nvdastudio.sub_agents.ast_validator import validate_wx_a11y_002_accelerators
        assert callable(validate_wx_a11y_002_accelerators)


# ===========================================================================
# 2. NVDA-019: _() com # Translators: correto
# ===========================================================================

class TestNVDA019Correto:
    """Codigo sem violacoes: validate_nvda019 deve retornar ok=True, violacoes=[]."""

    def test_codigo_sem_traducoes_e_ok(self):
        validate_nvda019, _, _ = _import_validator()
        codigo = (
            "import globalPluginHandler\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): super().terminate()\n"
        )
        r = validate_nvda019(codigo)
        assert r.ok is True
        assert r.violacoes == []

    def test_traducao_com_translators_e_ok(self):
        validate_nvda019, _, _ = _import_validator()
        codigo = (
            "import addonHandler, ui\n"
            "addonHandler.initTranslation()\n"
            "# Translators: mensagem falada quando clipboard esta vazio\n"
            'ui.message(_("Clipboard vazio"))\n'
        )
        r = validate_nvda019(codigo)
        assert r.ok is True
        assert r.violacoes == []

    def test_multiplas_traducoes_todas_com_translators(self):
        validate_nvda019, _, _ = _import_validator()
        codigo = (
            "import addonHandler, ui\n"
            "addonHandler.initTranslation()\n"
            "# Translators: primeira mensagem\n"
            'ui.message(_("Primeira"))\n'
            "# Translators: segunda mensagem\n"
            'ui.message(_("Segunda"))\n'
            "# Translators: terceira mensagem\n"
            'ui.message(_("Terceira"))\n'
        )
        r = validate_nvda019(codigo)
        assert r.ok is True
        assert r.violacoes == []

    def test_description_com_translators_e_ok(self):
        """@script(description=_()) com # Translators: deve passar."""
        validate_nvda019, _, _ = _import_validator()
        codigo = (
            "from scriptHandler import script\n"
            "class GP:\n"
            "    # Translators: descricao do script no dialogo de gestos\n"
            '    @script(description=_("Anuncia volume"))\n'
            "    def script_volume(self, gesture): pass\n"
        )
        r = validate_nvda019(codigo)
        assert r.ok is True
        assert r.violacoes == []

    def test_codigo_sintaticamente_invalido_e_ok(self):
        """Codigo que nao parseia deve retornar ok=True (fail-open — nao bloqueia)."""
        validate_nvda019, _, _ = _import_validator()
        codigo = "def foo(:\n    pass\n"  # SyntaxError proposital
        r = validate_nvda019(codigo)
        assert r.ok is True  # fail-open


# ===========================================================================
# 3. NVDA-019: _() sem # Translators: gera violacao
# ===========================================================================

class TestNVDA019Violacoes:
    """Codigo com violacoes: validate_nvda019 deve retornar ok=False com lista."""

    def test_traducao_sem_translators_gera_violacao(self):
        validate_nvda019, _, _ = _import_validator()
        codigo = (
            "import addonHandler, ui\n"
            "addonHandler.initTranslation()\n"
            'ui.message(_("Clipboard vazio"))  # sem # Translators:\n'
        )
        r = validate_nvda019(codigo)
        assert r.ok is False
        assert len(r.violacoes) == 1

    def test_violacao_menciona_numero_da_linha(self):
        validate_nvda019, _, _ = _import_validator()
        codigo = (
            "import addonHandler, ui\n"
            "addonHandler.initTranslation()\n"
            'ui.message(_("Sem translators"))\n'
        )
        r = validate_nvda019(codigo)
        assert not r.ok
        # Violacao deve indicar numero da linha (linha 3)
        assert "3" in r.violacoes[0]

    def test_duas_violacoes_geram_duas_entradas(self):
        validate_nvda019, _, _ = _import_validator()
        codigo = (
            "import addonHandler, ui\n"
            "addonHandler.initTranslation()\n"
            'ui.message(_("Primeira sem translators"))\n'
            'ui.message(_("Segunda sem translators"))\n'
        )
        r = validate_nvda019(codigo)
        assert not r.ok
        assert len(r.violacoes) == 2

    def test_mistura_correto_e_violacao(self):
        """Uma _() correta e uma sem # Translators: — so a violacao e reportada."""
        validate_nvda019, _, _ = _import_validator()
        codigo = (
            "import addonHandler, ui\n"
            "addonHandler.initTranslation()\n"
            "# Translators: mensagem ok\n"
            'ui.message(_("Mensagem correta"))\n'
            'ui.message(_("Mensagem sem translators"))\n'
        )
        r = validate_nvda019(codigo)
        assert not r.ok
        assert len(r.violacoes) == 1

    def test_return_traducao_sem_translators(self):
        """return _('...') sem # Translators: deve ser detectado."""
        validate_nvda019, _, _ = _import_validator()
        codigo = (
            "import addonHandler\n"
            "addonHandler.initTranslation()\n"
            "def get_msg():\n"
            '    return _("Mensagem sem translators")\n'
        )
        r = validate_nvda019(codigo)
        assert not r.ok
        assert len(r.violacoes) == 1

    def test_variavel_atribuida_sem_translators(self):
        """msg = _('...') sem # Translators: deve ser detectado."""
        validate_nvda019, _, _ = _import_validator()
        codigo = (
            "import addonHandler\n"
            "addonHandler.initTranslation()\n"
            'msg = _("Variavel sem translators")\n'
        )
        r = validate_nvda019(codigo)
        assert not r.ok

    def test_linha_anterior_e_codigo_nao_conta(self):
        """Linha anterior existir mas ser codigo (nao comentario # Translators:) e violacao."""
        validate_nvda019, _, _ = _import_validator()
        codigo = (
            "import addonHandler, ui\n"
            "addonHandler.initTranslation()\n"
            "x = 1  # linha anterior e codigo, nao # Translators:\n"
            'ui.message(_("Violacao"))\n'
        )
        r = validate_nvda019(codigo)
        assert not r.ok

    def test_translators_com_linha_em_branco_entre_e_violacao(self):
        """# Translators: seguido de linha em branco e depois _() e violacao."""
        validate_nvda019, _, _ = _import_validator()
        codigo = (
            "import addonHandler, ui\n"
            "addonHandler.initTranslation()\n"
            "# Translators: mensagem\n"
            "\n"
            'ui.message(_("Linha em branco entre translators e _()"))  # violacao\n'
        )
        r = validate_nvda019(codigo)
        assert not r.ok


# ===========================================================================
# 4. WX-A11Y: widgets com SetName() correto
# ===========================================================================

class TestWxA11yCorreto:
    """Codigo sem violacoes wx: validate_wx_a11y deve retornar ok=True."""

    def test_sem_widgets_wx_e_ok(self):
        _, validate_wx_a11y, _ = _import_validator()
        codigo = (
            "import globalPluginHandler\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin): pass\n"
        )
        r = validate_wx_a11y(codigo)
        assert r.ok is True
        assert r.violacoes == []

    def test_button_com_setname_e_ok(self):
        _, validate_wx_a11y, _ = _import_validator()
        codigo = (
            "import wx\n"
            "class MeuDialog(wx.Dialog):\n"
            "    def __init__(self, parent):\n"
            "        super().__init__(parent)\n"
            "        self.btn = wx.Button(self, label='OK')\n"
            "        self.btn.SetName('botao-ok')\n"
        )
        r = validate_wx_a11y(codigo)
        assert r.ok is True
        assert r.violacoes == []

    def test_textctrl_com_setname_e_ok(self):
        _, validate_wx_a11y, _ = _import_validator()
        codigo = (
            "import wx\n"
            "self.txt = wx.TextCtrl(self)\n"
            "self.txt.SetName('campo-texto')\n"
        )
        r = validate_wx_a11y(codigo)
        assert r.ok is True

    def test_checkbox_com_setname_e_ok(self):
        _, validate_wx_a11y, _ = _import_validator()
        codigo = (
            "import wx\n"
            "self.chk = wx.CheckBox(self, label='Ativar')\n"
            "self.chk.SetName('ativar-recurso')\n"
        )
        r = validate_wx_a11y(codigo)
        assert r.ok is True

    def test_statictext_nao_e_interativo_ok(self):
        """wx.StaticText nao e widget interativo — nao deve gerar violacao."""
        _, validate_wx_a11y, _ = _import_validator()
        codigo = (
            "import wx\n"
            "label = wx.StaticText(self, label='Nome:')\n"
        )
        r = validate_wx_a11y(codigo)
        assert r.ok is True

    def test_codigo_invalido_e_ok(self):
        """Codigo que nao parseia deve retornar ok=True (fail-open)."""
        _, validate_wx_a11y, _ = _import_validator()
        codigo = "class ::\n    pass\n"
        r = validate_wx_a11y(codigo)
        assert r.ok is True


# ===========================================================================
# 5. WX-A11Y: widgets sem SetName() geram violacao
# ===========================================================================

class TestWxA11yViolacoes:
    """Codigo com widgets sem SetName(): validate_wx_a11y deve reportar ok=False."""

    def test_button_sem_setname_gera_violacao(self):
        _, validate_wx_a11y, _ = _import_validator()
        codigo = (
            "import wx\n"
            "class MeuDialog(wx.Dialog):\n"
            "    def __init__(self, parent):\n"
            "        super().__init__(parent)\n"
            "        self.btn = wx.Button(self)\n"
            "        # sem label, sem SetName aqui\n"
            "        self.btn2 = wx.Button(self)\n"
        )
        r = validate_wx_a11y(codigo)
        assert r.ok is False
        assert len(r.violacoes) >= 1

    def test_violacao_menciona_tipo_widget(self):
        """label= satisfaz o fix primario de Button; sem label nem SetName ainda viola."""
        _, validate_wx_a11y, _ = _import_validator()
        codigo = (
            "import wx\n"
            "self.btn = wx.Button(self)\n"
        )
        r = validate_wx_a11y(codigo)
        assert not r.ok
        assert "Button" in r.violacoes[0] or "btn" in r.violacoes[0]

    def test_textctrl_sem_setname_gera_violacao(self):
        _, validate_wx_a11y, _ = _import_validator()
        codigo = (
            "import wx\n"
            "self.txt = wx.TextCtrl(self)\n"
            "self.outro = wx.StaticText(self, label='ok')\n"
        )
        r = validate_wx_a11y(codigo)
        assert not r.ok
        assert len(r.violacoes) == 1  # so TextCtrl, nao StaticText

    def test_choice_sem_setname_gera_violacao(self):
        _, validate_wx_a11y, _ = _import_validator()
        codigo = (
            "import wx\n"
            "self.cb = wx.Choice(self, choices=['A', 'B'])\n"
        )
        r = validate_wx_a11y(codigo)
        assert not r.ok

    def test_multiplos_widgets_sem_setname(self):
        """Button com label= satisfaz o fix primario (nao conta); TextCtrl e
        CheckBox (label= so vale para Button) continuam violando."""
        _, validate_wx_a11y, _ = _import_validator()
        codigo = (
            "import wx\n"
            "self.btn = wx.Button(self, label='OK')\n"
            "self.txt = wx.TextCtrl(self)\n"
            "self.chk = wx.CheckBox(self, label='Ativar')\n"
        )
        r = validate_wx_a11y(codigo)
        assert not r.ok
        assert len(r.violacoes) == 2

    def test_mistura_com_e_sem_setname(self):
        """Button com SetName OK, TextCtrl sem SetName = 1 violacao."""
        _, validate_wx_a11y, _ = _import_validator()
        codigo = (
            "import wx\n"
            "self.btn = wx.Button(self, label='OK')\n"
            "self.btn.SetName('botao-ok')\n"
            "self.txt = wx.TextCtrl(self)\n"
            "# sem SetName para txt\n"
        )
        r = validate_wx_a11y(codigo)
        assert not r.ok
        assert len(r.violacoes) == 1


# ===========================================================================
# 6. Integracao com _verificar_codigo_gerado (Fase 2 AST)
# ===========================================================================

class TestFase2AST:
    """_verificar_codigo_gerado agora usa AST, nao LLM — sem chamadas de rede."""

    def test_codigo_correto_retorna_codigo_original(self):
        """Codigo sem violacoes: _verificar_codigo_gerado retorna o mesmo codigo."""
        from nvdastudio.sub_agents.code_generator import _verificar_codigo_gerado
        codigo = (
            "import addonHandler, ui\n"
            "addonHandler.initTranslation()\n"
            "# Translators: mensagem de teste\n"
            'ui.message(_("Teste"))\n'
        )
        resultado = _verificar_codigo_gerado(codigo, model_id="x")
        assert resultado == codigo

    def test_codigo_vazio_retorna_vazio(self):
        from nvdastudio.sub_agents.code_generator import _verificar_codigo_gerado
        assert _verificar_codigo_gerado("", model_id="x") == ""

    def test_fase2_nao_faz_chamada_de_rede(self):
        """Com AST, api_key e model_id sao ignorados — nenhuma chamada ao GroqClient."""
        from unittest.mock import patch
        from nvdastudio.sub_agents.code_generator import _verificar_codigo_gerado
        codigo = (
            "import addonHandler\n"
            "addonHandler.initTranslation()\n"
            "# Translators: ok\n"
            'x = _("ok")\n'
        )
        with patch("nvdastudio.sub_agents.code_generator.create_llm_client") as mock_gc:
            resultado = _verificar_codigo_gerado(codigo, model_id="any")
        mock_gc.assert_not_called()  # AST nao usa create_llm_client
        assert resultado == codigo


# ===========================================================================
# 7. WX-A11Y-002: wx.Panel/wx.Frame sem SetAcceleratorTable
# ===========================================================================

class TestWxA11y002AcceleratorTable:
    def test_panel_com_accelerator_table_e_ok(self):
        from nvdastudio.sub_agents.ast_validator import validate_wx_a11y_002_accelerators
        codigo = (
            "import wx\n"
            "class D(wx.Dialog):\n"
            "    def __init__(self, parent):\n"
            "        super().__init__(parent)\n"
            "        self.panel = wx.Panel(self)\n"
            "        self.panel.SetAcceleratorTable(wx.AcceleratorTable([]))\n"
        )
        r = validate_wx_a11y_002_accelerators(codigo)
        assert r.ok is True
        assert r.violacoes == []

    def test_panel_sem_accelerator_table_gera_violacao(self):
        from nvdastudio.sub_agents.ast_validator import validate_wx_a11y_002_accelerators
        codigo = (
            "import wx\n"
            "class D(wx.Dialog):\n"
            "    def __init__(self, parent):\n"
            "        super().__init__(parent)\n"
            "        self.panel = wx.Panel(self)\n"
        )
        r = validate_wx_a11y_002_accelerators(codigo)
        assert r.ok is False
        assert len(r.violacoes) == 1
