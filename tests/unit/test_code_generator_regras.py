from addon.globalPlugins.nvdastudio.sub_agents.code_generator import (
    _SYSTEM, MODULE_VERSION,
)


class TestCodeGeneratorVersao:
    def test_versao_e_1_9_0(self):
        assert MODULE_VERSION == "3.32.0"


class TestCodeGeneratorRegrasNovas:
    """Todas as regras críticas devem estar no system prompt."""

    def test_nvda_006_proibe_monkey_patching(self):
        assert "NVDA-006" in _SYSTEM
        assert "monkey" in _SYSTEM.lower() or "monkey-patch" in _SYSTEM.lower()

    def test_nvda_006_sugere_extension_points(self):
        assert "extension" in _SYSTEM.lower() or "event handler" in _SYSTEM.lower()

    def test_nvda_007_proibe_gestures_dict(self):
        assert "NVDA-007" in _SYSTEM
        assert "__gestures" in _SYSTEM

    def test_nvda_007_exige_decorator_script(self):
        assert "@script" in _SYSTEM

    def test_nvda_008_exige_description_no_decorator(self):
        assert "NVDA-008" in _SYSTEM
        assert "description" in _SYSTEM.lower()

    def test_nvda_009_proibe_atalhos_conflitantes(self):
        assert "NVDA-009" in _SYSTEM
        # Deve listar ao menos um atalho proibido
        assert "NVDA+f" in _SYSTEM or "NVDA+t" in _SYSTEM or "NVDA+q" in _SYSTEM

    def test_nvda_011_exige_check_em_drivers(self):
        assert "NVDA-011" in _SYSTEM
        assert "check()" in _SYSTEM

    def test_nvda_015_exige_config_conf_spec(self):
        assert "NVDA-015" in _SYSTEM
        assert "config.conf" in _SYSTEM.lower() or "config.conf.spec" in _SYSTEM

    def test_nvda_016_exige_shouldwritetodisk(self):
        assert "NVDA-016" in _SYSTEM
        assert "shouldWriteToDisk" in _SYSTEM

    def test_regras_anteriores_preservadas(self):
        """Regras que já existiam não devem ter sido removidas."""
        assert "NVDA-001" in _SYSTEM
        assert "NVDA-002" in _SYSTEM
        assert "NVDA-003" in _SYSTEM
        assert "NVDA-004" in _SYSTEM
        assert "NVDA-010" in _SYSTEM
        assert "NVDA-012" in _SYSTEM

    def test_total_regras_no_prompt(self):
        """Pelo menos 12 regras NVDA devem estar no prompt."""
        ids = [f"NVDA-0{str(i).zfill(2)}" for i in range(1, 19)]
        presentes = [r for r in ids if r in _SYSTEM]
        assert len(presentes) >= 12, f"Apenas {len(presentes)} regras NVDA no prompt"

    def test_exemplos_concretos_presentes(self):
        """O prompt deve ter exemplos de código correto e errado."""
        assert "Proibido:" in _SYSTEM or "NUNCA" in _SYSTEM
        assert "Correto:" in _SYSTEM or "SEMPRE" in _SYSTEM
