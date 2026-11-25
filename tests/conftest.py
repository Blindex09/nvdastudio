"""Configuracao comum dos testes do servidor MCP do NVDAStudio."""

import gc
import sys
import types
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

# Modulos do NVDA que nao existem fora do leitor de telas. Os testes que
# exercitam codigo de addon (validador, sandbox) so precisam que o import
# funcione; o comportamento real do NVDA nao e simulado aqui.
_NVDA_MODULE_STUBS: dict[str, object] = {
    name: MagicMock()
    for name in (
        "ui", "api", "config", "gui", "gui.guiHelper", "wx",
        "globalPluginHandler", "addonHandler", "scriptHandler",
        "logHandler", "speech", "braille", "tones",
    )
}
_settings_dialogs = types.ModuleType("gui.settingsDialogs")
_settings_dialogs.SettingsPanel = object  # type: ignore[attr-defined]
_settings_dialogs.NVDASettingsDialog = MagicMock()  # type: ignore[attr-defined]
_NVDA_MODULE_STUBS["gui.settingsDialogs"] = _settings_dialogs


def install_nvda_stubs() -> None:
    """Instala stubs do NVDA em sys.modules. Idempotente."""
    for name, stub in _NVDA_MODULE_STUBS.items():
        sys.modules.setdefault(name, stub)  # type: ignore[arg-type]


install_nvda_stubs()


@pytest.fixture(autouse=True)
def _gc_apos_teste() -> Iterator[None]:
    """Forca coleta de lixo para que ResourceWarning apareca no teste que a causou."""
    yield
    gc.collect()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):  # type: ignore[no-untyped-def]
    """Teste que precisa de isolamento (Docker + imagem) PULA quando ele falta.

    O sandbox falha fechado: sem Docker ou sem a imagem, nada roda. Isso e
    ausencia de ambiente, nao defeito do codigo, e o relatorio deve dizer
    "pulado" com o motivo em vez de "falhou".
    """
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed and "ISOLATION_UNAVAILABLE" in str(report.longrepr):
        report.outcome = "skipped"
        report.longrepr = (str(item.path), item.location[1], "Skipped: isolamento (Docker + imagem) indisponivel")
