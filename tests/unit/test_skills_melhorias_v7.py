class TestCriticArquiteturaRules:
    """ARCH-001..006 devem estar no _CRITIC_QUALITY_SYSTEM (v3.0.0)."""

    def test_versao_Critic(self):
        from nvdastudio.ai.critic import MODULE_VERSION
        assert MODULE_VERSION == "3.21.0"

    def test_arch001_no_quality_system(self):
        """ARCH-001: addon com API externa sem SettingsPanel deve ser penalizado."""
        from nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        assert "ARCH-001" in _CRITIC_QUALITY_SYSTEM

    def test_arch001_menciona_settings_panel(self):
        """ARCH-001 deve mencionar SettingsPanel como solucao esperada."""
        from nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        assert "SettingsPanel" in _CRITIC_QUALITY_SYSTEM

    def test_arch002_no_quality_system(self):
        """ARCH-002: I/O bloqueante sem threading deve ser penalizado."""
        from nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        assert "ARCH-002" in _CRITIC_QUALITY_SYSTEM

    def test_arch002_menciona_threading(self):
        """ARCH-002 deve mencionar threading como solucao esperada."""
        from nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        assert "threading" in _CRITIC_QUALITY_SYSTEM

    def test_arch004_no_quality_system(self):
        """ARCH-004: logica de API no __init__.py deve ser penalizada."""
        from nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        assert "ARCH-004" in _CRITIC_QUALITY_SYSTEM

    def test_arch005_no_quality_system(self):
        """ARCH-005: config sem config.conf deve ser penalizada."""
        from nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        assert "ARCH-005" in _CRITIC_QUALITY_SYSTEM

    def test_arch_penalizacao_pontos(self):
        """Falha ARCH-001/002 deve penalizar 15 pts; ARCH-004/005 deve penalizar 10 pts."""
        from nvdastudio.ai.critic import _CRITIC_QUALITY_SYSTEM
        assert "-15" in _CRITIC_QUALITY_SYSTEM
        assert "-10" in _CRITIC_QUALITY_SYSTEM

    def test_critic_system_contem_arch_rules(self):
        """_CRITIC_SYSTEM (export de compatibilidade) tambem deve ter ARCH-001."""
        from nvdastudio.ai.critic import _CRITIC_SYSTEM
        assert "ARCH-001" in _CRITIC_SYSTEM


class TestPlannerArquiteturaRules:
    """ARCH-001, 002, 004, 005, 008, 009 devem estar no _PLAN_SYSTEM_PROMPT
    (ARCH-008/009 sao os topicos de menu/dialog, renumerados de 003/006 em
    2026-08-04 pra resolver colisao com critic.py/nvda_context.py)."""

    def test_versao_Planner(self):
        from nvdastudio.core.planner import MODULE_VERSION
        assert MODULE_VERSION == "2.33.0"

    def test_arch001_no_Planner(self):
        """ARCH-001 deve estar no prompt do Planner como regra de inferencia."""
        from nvdastudio.core.planner import _PLAN_SYSTEM_PROMPT
        assert "ARCH-001" in _PLAN_SYSTEM_PROMPT

    def test_arch002_no_Planner(self):
        """ARCH-002: Planner deve saber quando usar background thread."""
        from nvdastudio.core.planner import _PLAN_SYSTEM_PROMPT
        assert "ARCH-002" in _PLAN_SYSTEM_PROMPT

    def test_arch008_no_Planner(self):
        """ARCH-008 (renumerado de ARCH-003 em 2026-08-04, colisao com
        critic.py/nvda_context.py): multiplas funcoes -> menu Ferramentas."""
        from nvdastudio.core.planner import _PLAN_SYSTEM_PROMPT
        assert "ARCH-008" in _PLAN_SYSTEM_PROMPT

    def test_arch004_no_Planner(self):
        """ARCH-004: separacao de camadas no Planner."""
        from nvdastudio.core.planner import _PLAN_SYSTEM_PROMPT
        assert "ARCH-004" in _PLAN_SYSTEM_PROMPT

    def test_arch005_no_Planner(self):
        """ARCH-005: config.conf no Planner."""
        from nvdastudio.core.planner import _PLAN_SYSTEM_PROMPT
        assert "ARCH-005" in _PLAN_SYSTEM_PROMPT

    def test_arch009_no_Planner(self):
        """ARCH-009 (renumerado de ARCH-006 em 2026-08-04, colisao com
        critic.py/nvda_context.py): menu para qualquer addon com dialog."""
        from nvdastudio.core.planner import _PLAN_SYSTEM_PROMPT
        assert "ARCH-009" in _PLAN_SYSTEM_PROMPT

    def test_planner_menciona_settings_panel_no_arch001(self):
        """Planner ARCH-001 deve mencionar settings_panel.py como arquivo a gerar."""
        from nvdastudio.core.planner import _PLAN_SYSTEM_PROMPT
        assert "settings_panel.py" in _PLAN_SYSTEM_PROMPT

    def test_planner_menciona_service_layer(self):
        """ARCH-004 deve mencionar service layer como padrao de separacao."""
        from nvdastudio.core.planner import _PLAN_SYSTEM_PROMPT
        # Deve mencionar arquivo separado
        assert "servico" in _PLAN_SYSTEM_PROMPT.lower() or "service" in _PLAN_SYSTEM_PROMPT.lower()


class TestNvdaContextArquiteturaPatterns:
    """nvda_context.py 3.3.0 deve ter padroes de codigo arquiteturais."""

    def test_prompt_version(self):
        """PROMPT_VERSION deve ser 3.26.0."""
        from nvdastudio.builder.nvda_context import PROMPT_VERSION
        assert PROMPT_VERSION == "3.27.0"

    def test_sistema_prompt_tem_arch_separacao(self):
        """NVDA_SYSTEM_PROMPT deve ter o padrao de separacao de camadas (ARCH-004)."""
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        assert "ARCH-004" in NVDA_SYSTEM_PROMPT or "SEPARACAO DE CAMADAS" in NVDA_SYSTEM_PROMPT

    def test_sistema_prompt_tem_service_layer_template(self):
        """NVDA_SYSTEM_PROMPT deve ter template de classe de servico."""
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        assert "TranscricaoService" in NVDA_SYSTEM_PROMPT or "servico" in NVDA_SYSTEM_PROMPT.lower()

    def test_sistema_prompt_tem_background_thread_template(self):
        """NVDA_SYSTEM_PROMPT deve ter template de background thread com wx.CallAfter."""
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        assert "wx.CallAfter" in NVDA_SYSTEM_PROMPT
        assert "threading.Thread" in NVDA_SYSTEM_PROMPT

    def test_sistema_prompt_tem_settings_panel_template(self):
        """NVDA_SYSTEM_PROMPT deve ter template de SettingsPanel para API Key."""
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        assert "MeuAddonSettingsPanel" in NVDA_SYSTEM_PROMPT
        assert "apiKey" in NVDA_SYSTEM_PROMPT or "api_key" in NVDA_SYSTEM_PROMPT

    def test_sistema_prompt_menciona_arch_rules(self):
        """NVDA_SYSTEM_PROMPT deve mencionar ARCH-001..006."""
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        assert "ARCH-001" in NVDA_SYSTEM_PROMPT
