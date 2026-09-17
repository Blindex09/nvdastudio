from nvdastudio.utils.project_policy import (
    ABSOLUTE_MIN_NVDA,
    MODULE_VERSION,
    PROJECT_LAST_TESTED_NVDA,
    PROJECT_MIN_NVDA,
    PROJECT_SUPPORTED_RANGE,
    parse_version_tuple,
)


class TestProjectPolicyVersion:
    def test_module_version(self):
        assert MODULE_VERSION == "1.1.0"


class TestProjectPolicyConstants:
    def test_baseline_minimo(self):
        assert PROJECT_MIN_NVDA == "2026.1.1"

    def test_last_tested(self):
        assert PROJECT_LAST_TESTED_NVDA == "2026.2.0"

    def test_supported_range(self):
        assert PROJECT_SUPPORTED_RANGE == "2026.1.1+"

    def test_piso_absoluto(self):
        assert ABSOLUTE_MIN_NVDA == "2019.3.0"


class TestProjectPolicyHelpers:
    def test_parse_version_tuple_com_tres_partes(self):
        assert parse_version_tuple("2026.1.1") == (2026, 1, 1)

    def test_parse_version_tuple_com_duas_partes(self):
        assert parse_version_tuple("2026.1") == (2026, 1, 0)
