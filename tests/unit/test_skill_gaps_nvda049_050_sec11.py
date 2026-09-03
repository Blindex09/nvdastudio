def _get_system_prompt() -> str:
    from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
    return NVDA_SYSTEM_PROMPT


def _get_detection_rules():
    from nvdastudio.builder.nvda_context import NVDA_DETECTION_RULES
    return NVDA_DETECTION_RULES


def _get_auditor_system() -> str:
    from nvdastudio.sub_agents.accessibility_auditor import _SYSTEM
    return _SYSTEM


# ===========================================================================
# NVDA-049: wx.MessageDialog proibido (skill §12)
# ===========================================================================

class TestNVDA049WxMessageDialog:
    """
    A skill §12 mostra gui.message.MessageDialog como a API correta para
    dialogs modais no NVDA. wx.MessageDialog nao integra corretamente com
    o screen reader -- dialogs nao sao anunciados e o foco pode falhar.
    """

    def test_regra_nvda049_existe_em_detection_rules(self):
        rules = _get_detection_rules()
        ids = [r[0] for r in rules]
        assert "NVDA-049" in ids, (
            "NVDA_DETECTION_RULES nao tem NVDA-049. "
            "Uso de wx.MessageDialog nao e detectado pelo auditor."
        )

    def test_regra_nvda049_severidade_serio(self):
        rules = _get_detection_rules()
        rule = next((r for r in rules if r[0] == "NVDA-049"), None)
        assert rule is not None
        assert rule[1] == "Serio", (
            f"NVDA-049 deve ser 'Serio' (dialog nao integrado com NVDA): {rule[1]}"
        )

    def test_regra_nvda049_menciona_MessageDialog(self):
        rules = _get_detection_rules()
        rule = next((r for r in rules if r[0] == "NVDA-049"), None)
        assert rule is not None
        assert "MessageDialog" in rule[2], (
            "NVDA-049 deve mencionar MessageDialog na descricao."
        )

    def test_regra_nvda049_menciona_wx_MessageDialog_proibido(self):
        rules = _get_detection_rules()
        rule = next((r for r in rules if r[0] == "NVDA-049"), None)
        assert rule is not None
        assert "wx.MessageDialog" in rule[2], (
            "NVDA-049 deve mencionar wx.MessageDialog como proibido."
        )

    def test_system_prompt_tem_nvda049(self):
        prompt = _get_system_prompt()
        assert "NVDA-049" in prompt, (
            "NVDA_SYSTEM_PROMPT nao menciona NVDA-049. "
            "O modelo de geracao nao sabe que wx.MessageDialog e proibido."
        )

    def test_system_prompt_menciona_gui_message_MessageDialog(self):
        prompt = _get_system_prompt()
        assert "gui.message.MessageDialog" in prompt or "gui.message" in prompt, (
            "NVDA_SYSTEM_PROMPT deve mencionar gui.message.MessageDialog "
            "como alternativa correta ao wx.MessageDialog (skill §12)."
        )

    def test_auditor_tem_nvda049(self):
        auditor = _get_auditor_system()
        assert "NVDA-049" in auditor, (
            "accessibility_auditor._SYSTEM nao tem NVDA-049. "
            "O auditor nao vai detectar wx.MessageDialog no codigo gerado."
        )

    def test_auditor_menciona_wx_MessageDialog_proibido(self):
        auditor = _get_auditor_system()
        idx = auditor.find("NVDA-049")
        assert idx != -1
        regra = auditor[idx:]
        assert "wx.MessageDialog" in regra, (
            "NVDA-049 no auditor deve mencionar wx.MessageDialog como violacao."
        )

    def test_auditor_menciona_MessageDialog_correto(self):
        auditor = _get_auditor_system()
        idx = auditor.find("NVDA-049")
        assert idx != -1
        regra = auditor[idx:]
        assert "MessageDialog" in regra and "gui" in regra, (
            "NVDA-049 no auditor deve indicar gui.message.MessageDialog como correto."
        )

    def test_auditor_cobertura_inclui_049(self):
        auditor = _get_auditor_system()
        assert "NVDA-049" in auditor, (
            "Linha 'Nenhuma violacao' deve incluir NVDA-049 na cobertura."
        )

    def test_auditor_nenhuma_violacao_inclui_050(self):
        auditor = _get_auditor_system()
        assert "NVDA-050" in auditor, (
            "accessibility_auditor deve mencionar NVDA-050."
        )


# ===========================================================================
# NVDA-049: wx.MessageBox tambem proibido, nao so wx.MessageDialog
# (nvda_context.py 3.32.0/code_generator.py 3.31.0/addon_builder.py 4.10.0/
# accessibility_auditor.py 1.17.0). Achado real ao vivo (test_e36,
# GeminiMultimodal): a checagem mecanica de addon_builder.py e o texto da
# regra so citavam wx.MessageDialog -- codigo gerado usando wx.MessageBox
# (mesma violacao de acessibilidade, API wx diferente) passava batido pela
# checagem estatica e reprovava 3x seguidas no critic sem nenhum sinal
# explicito de qual API exata corrigir.
# ===========================================================================

class TestNVDA049WxMessageBoxTambemProibido:
    def test_regra_nvda049_menciona_wx_MessageBox(self):
        rules = _get_detection_rules()
        rule = next((r for r in rules if r[0] == "NVDA-049"), None)
        assert rule is not None
        assert "wx.MessageBox" in rule[2], (
            "NVDA-049 deve mencionar wx.MessageBox como proibido, nao so wx.MessageDialog."
        )

    def test_system_prompt_menciona_wx_MessageBox(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM as CODEGEN_SYSTEM
        assert "wx.MessageBox" in CODEGEN_SYSTEM, (
            "Prompt de code_generation deve mencionar wx.MessageBox como proibido, "
            "nao so wx.MessageDialog -- sem isso o modelo pode 'corrigir' NVDA-049 "
            "trocando pra wx.MessageBox e continuar violando a mesma regra."
        )

    def test_auditor_menciona_wx_MessageBox(self):
        auditor = _get_auditor_system()
        idx = auditor.find("NVDA-049")
        assert idx != -1
        regra = auditor[idx:idx + 300]
        assert "wx.MessageBox" in regra, (
            "NVDA-049 no auditor deve mencionar wx.MessageBox como violacao."
        )

    def test_checagem_mecanica_detecta_wx_MessageBox(self, tmp_path):
        """addon_builder._check_all_nvda_fallbacks() deve sinalizar
        wx.MessageBox(...) da mesma forma que ja sinaliza wx.MessageDialog(...)."""
        from nvdastudio.builder.addon_builder import _check_all_nvda_fallbacks

        gp_dir = tmp_path / "globalPlugins" / "TesteAddon"
        gp_dir.mkdir(parents=True)
        (gp_dir / "__init__.py").write_text(
            "import wx\n"
            "import globalPluginHandler\n\n\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "\tdef onSave(self):\n"
            "\t\twx.MessageBox('Configuracao salva', 'Aviso')\n",
            encoding="utf-8",
        )
        problems = _check_all_nvda_fallbacks(str(tmp_path), manifest_fields={})
        assert any("NVDA-049" in p and "MessageBox" in p for p in problems), (
            f"wx.MessageBox(...) nao foi detectado por _check_all_nvda_fallbacks(). "
            f"Problemas encontrados: {problems}"
        )

    def test_checagem_mecanica_nao_falsa_positiva_em_texto_normal(self, tmp_path):
        """Nao deve disparar em codigo que so MENCIONA MessageBox sem chamar
        a funcao proibida (ex: docstring, nome de variavel)."""
        from nvdastudio.builder.addon_builder import _check_all_nvda_fallbacks

        gp_dir = tmp_path / "globalPlugins" / "TesteAddon"
        gp_dir.mkdir(parents=True)
        (gp_dir / "__init__.py").write_text(
            '"""Este addon NAO usa wx.MessageBox, usa gui.message.MessageDialog."""\n'
            "import globalPluginHandler\n"
            "import gui.message\n\n\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "\tdef onSave(self):\n"
            "\t\tgui.message.MessageDialog.alert('Configuracao salva')\n",
            encoding="utf-8",
        )
        problems = _check_all_nvda_fallbacks(str(tmp_path), manifest_fields={})
        assert not any("MessageBox" in p for p in problems), (
            f"FALSO POSITIVO: docstring mencionando MessageBox foi confundida com "
            f"chamada real. Problemas: {problems}"
        )


# ===========================================================================
# NVDA-050: NVDAObject overlay class herda da classe mais especifica (skill §6)
# ===========================================================================

class TestNVDA050NVDAObjectMaisEspecifica:
    """
    A skill §6 e explicita: "Always inherit from the most specific class you need."
    Hierarquia: IAccessible > UIA > Window > JABObject > NVDAObject (base).
    Overlay classes que herdam da base NVDAObject perdem metodos e propriedades
    especificos da API alvo (IAccessible2, UI Automation, etc.).
    """

    def test_regra_nvda050_existe_em_detection_rules(self):
        rules = _get_detection_rules()
        ids = [r[0] for r in rules]
        assert "NVDA-050" in ids, (
            "NVDA_DETECTION_RULES nao tem NVDA-050. "
            "Overlay class com base NVDAObject nao e detectado."
        )

    def test_regra_nvda050_severidade_moderado(self):
        rules = _get_detection_rules()
        rule = next((r for r in rules if r[0] == "NVDA-050"), None)
        assert rule is not None
        assert rule[1] == "Moderado", (
            f"NVDA-050 deve ser 'Moderado' (NVDAObject base em overlay): {rule[1]}"
        )

    def test_regra_nvda050_menciona_IAccessible(self):
        rules = _get_detection_rules()
        rule = next((r for r in rules if r[0] == "NVDA-050"), None)
        assert rule is not None
        assert "IAccessible" in rule[2], (
            "NVDA-050 deve mencionar IAccessible como alternativa correta."
        )

    def test_regra_nvda050_menciona_UIA(self):
        rules = _get_detection_rules()
        rule = next((r for r in rules if r[0] == "NVDA-050"), None)
        assert rule is not None
        assert "UIA" in rule[2], (
            "NVDA-050 deve mencionar UIA como alternativa correta."
        )

    def test_system_prompt_tem_nvda050(self):
        prompt = _get_system_prompt()
        assert "NVDA-050" in prompt, (
            "NVDA_SYSTEM_PROMPT nao menciona NVDA-050. "
            "O modelo de geracao nao sabe que NVDAObject base e errada em overlays."
        )

    def test_system_prompt_menciona_hierarquia_NVDAObject(self):
        prompt = _get_system_prompt()
        assert "IAccessible" in prompt and "UIA" in prompt, (
            "NVDA_SYSTEM_PROMPT deve mostrar a hierarquia IAccessible/UIA "
            "para guiar a geracao de overlay classes corretas (skill §6)."
        )

    def test_auditor_tem_nvda050(self):
        auditor = _get_auditor_system()
        assert "NVDA-050" in auditor, (
            "accessibility_auditor._SYSTEM nao tem NVDA-050. "
            "O auditor nao vai detectar overlay com base NVDAObject."
        )

    def test_auditor_menciona_IAccessible_como_correto(self):
        auditor = _get_auditor_system()
        idx = auditor.find("NVDA-050")
        assert idx != -1
        regra = auditor[idx:]
        assert "IAccessible" in regra, (
            "NVDA-050 no auditor deve indicar IAccessible como alternativa correta."
        )


# ===========================================================================
# §11: installTasks.py no NVDA_SYSTEM_PROMPT
# ===========================================================================

class TestSec11InstallTasksSystemPrompt:
    """
    A skill §11 descreve installTasks.py como arquivo opcional na raiz do addon.
    onInstall() -- chamado apos extracao, antes do primeiro carregamento.
    onUninstall() -- chamado no restart apos remocao; sem input de usuario.
    Deve estar no NVDA_SYSTEM_PROMPT para que o modelo saiba gerar quando pedido.
    """

    def test_system_prompt_menciona_installTasks(self):
        prompt = _get_system_prompt()
        assert "installTasks" in prompt, (
            "NVDA_SYSTEM_PROMPT nao menciona installTasks.py. "
            "O modelo nao sabe gerar tasks de instalacao (skill §11)."
        )

    def test_system_prompt_menciona_onInstall(self):
        prompt = _get_system_prompt()
        assert "onInstall" in prompt, (
            "NVDA_SYSTEM_PROMPT deve mencionar onInstall() para o modelo "
            "saber o nome correto da funcao (skill §11)."
        )

    def test_system_prompt_menciona_onUninstall(self):
        prompt = _get_system_prompt()
        assert "onUninstall" in prompt, (
            "NVDA_SYSTEM_PROMPT deve mencionar onUninstall() (skill §11)."
        )

    def test_system_prompt_tem_template_installTasks(self):
        prompt = _get_system_prompt()
        assert "installTasks.py" in prompt, (
            "NVDA_SYSTEM_PROMPT deve ter template com anotacao de arquivo "
            "installTasks.py para o modelo gerar o arquivo correto (skill §11)."
        )


# ===========================================================================
# Contagem total de NVDA_DETECTION_RULES (sanity check)
# ===========================================================================

class TestDetectionRulesTotal:
    def test_total_regras_apos_adicao_nvda049_e_050(self):
        rules = _get_detection_rules()
        assert len(rules) == 62, (
            f"Esperado 62 regras (58 anteriores + NVDA-060..062 da auditoria de "
            f"2026-08-04 + NVDA-063, assinatura divergente entre arquivos, achada na "
            f"rodada AssistenteEscrita de 2026-09-03), encontrado {len(rules)}."
        )

    def test_nvda049_e_050_presentes(self):
        rules = _get_detection_rules()
        ids = {r[0] for r in rules}
        assert "NVDA-049" in ids, "NVDA-049 ausente de NVDA_DETECTION_RULES"
        assert "NVDA-050" in ids, "NVDA-050 ausente de NVDA_DETECTION_RULES"
