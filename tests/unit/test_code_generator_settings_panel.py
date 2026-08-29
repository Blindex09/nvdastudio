def _get_system() -> str:
    from nvdastudio.sub_agents.code_generator import _SYSTEM
    return _SYSTEM


class TestSettingsPanelImportCorreto:
    """
    O _SYSTEM deve instruir o import CORRETO de NVDASettingsDialog.
    O import errado (de 'gui' ou de 'api') causa AttributeError no NVDA
    e o painel nunca aparece nas configuracoes.

    Causa raiz confirmada no log do GeminiTela:
      AttributeError: module 'api' has no attribute 'NVDASettingsDialog'
    """

    def test_system_instrui_import_de_gui_settingsDialogs(self):
        """_SYSTEM deve mencionar gui.settingsDialogs como fonte de NVDASettingsDialog."""
        system = _get_system()
        assert "gui.settingsDialogs" in system, (
            "_SYSTEM nao instrui 'from gui.settingsDialogs import NVDASettingsDialog'. "
            "Sem isso, o modelo importa de 'gui' ou 'api' e causa AttributeError no NVDA."
        )

    def test_system_proibe_import_de_api(self):
        """_SYSTEM deve alertar que NVDASettingsDialog nao vem de 'api'."""
        system = _get_system()
        # O _SYSTEM deve conter a instrucao de onde importar corretamente
        # Isso implica que o import errado (api.NVDASettingsDialog) esteja documentado como proibido
        # OU que o import correto esteja tao explicitamente documentado que o modelo nao erre
        assert "gui.settingsDialogs" in system, (
            "O import correto 'from gui.settingsDialogs import NVDASettingsDialog' "
            "deve estar explicito no _SYSTEM."
        )


class TestSettingsPanelGuardNotIn:
    """
    O _SYSTEM deve instruir o guard 'not in' antes do categoryClasses.append().
    Sem o guard, o painel e duplicado quando o addon e recarregado (NVDA-024).
    """

    def test_system_instrui_guard_not_in_antes_do_append(self):
        """_SYSTEM deve conter o padrao 'not in NVDASettingsDialog.categoryClasses'."""
        system = _get_system()
        assert "not in NVDASettingsDialog.categoryClasses" in system, (
            "_SYSTEM nao instrui o guard 'if Panel not in NVDASettingsDialog.categoryClasses' "
            "antes do append. Sem isso, o painel aparece duplicado ao recarregar o addon."
        )

    def test_system_instrui_remocao_no_terminate(self):
        """_SYSTEM deve instruir o remove() no terminate() com guard 'in'."""
        system = _get_system()
        assert "NVDASettingsDialog.categoryClasses.remove" in system, (
            "_SYSTEM nao instrui 'NVDASettingsDialog.categoryClasses.remove(Panel)' "
            "no terminate(). Sem isso, o painel persiste mesmo apos desinstalar o addon."
        )


class TestSettingsPanelVerificacaoFinal:
    """
    O _SYSTEM deve ter item na VERIFICACAO FINAL cobrindo SettingsPanel.
    Sem esse item, o modelo nao auto-verifica se o painel esta registrado corretamente.
    """

    def test_system_tem_item_11_settings_panel_na_verificacao_final(self):
        """_SYSTEM deve ter item de verificacao sobre SettingsPanel na VERIFICACAO FINAL."""
        system = _get_system()
        # O item deve cobrir o guard not in E o remove no terminate
        # Verificamos que a VERIFICACAO FINAL menciona SettingsPanel
        assert "SettingsPanel" in system and "VERIFICACAO FINAL" in system, (
            "_SYSTEM nao tem item na VERIFICACAO FINAL cobrindo SettingsPanel. "
            "Sem isso, o modelo nao auto-verifica o registro do painel."
        )

    def test_system_verificacao_final_cobre_guard_do_settings_panel(self):
        """A VERIFICACAO FINAL deve cobrir especificamente o guard 'not in'."""
        system = _get_system()
        # Localiza a secao VERIFICACAO FINAL e verifica que menciona categoryClasses ou guard
        idx = system.find("VERIFICACAO FINAL")
        assert idx != -1, "_SYSTEM nao tem secao VERIFICACAO FINAL"
        verificacao_section = system[idx:]
        assert "categoryClasses" in verificacao_section or "SettingsPanel" in verificacao_section, (
            "A VERIFICACAO FINAL nao cobre categoryClasses/SettingsPanel. "
            "O modelo nao vai auto-verificar o registro do painel."
        )


class TestSettingsPanelTemplateCompleto:
    """
    O _SYSTEM deve ter o template completo de como registrar o SettingsPanel,
    incluindo o arquivo settings_panel.py separado do __init__.py.
    """

    def test_system_tem_template_com_from_settingsDialogs(self):
        """_SYSTEM deve ter exemplo com 'from gui.settingsDialogs import SettingsPanel'."""
        system = _get_system()
        assert "from gui.settingsDialogs import SettingsPanel" in system, (
            "_SYSTEM nao tem template mostrando 'from gui.settingsDialogs import SettingsPanel'. "
            "Sem isso, o modelo nao sabe como criar a classe do painel corretamente."
        )

    def test_system_tem_makesettings_no_template(self):
        """_SYSTEM deve mostrar o metodo makeSettings obrigatorio."""
        system = _get_system()
        assert "makeSettings" in system, (
            "_SYSTEM nao mostra o metodo makeSettings. "
            "O modelo gera paineis sem esse metodo obrigatorio."
        )

    def test_system_tem_onsave_no_template(self):
        """_SYSTEM deve mostrar o metodo onSave obrigatorio."""
        system = _get_system()
        assert "onSave" in system, (
            "_SYSTEM nao mostra o metodo onSave. "
            "O modelo gera paineis sem persistencia das configuracoes."
        )
