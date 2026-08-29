import os
import sys
import types
from unittest.mock import MagicMock

import pytest

# --------------------------------------------------------------------------
# Configuracao de sys.path — feita UMA vez aqui para todos os testes
# --------------------------------------------------------------------------

_ADDON_PKG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "addon", "globalPlugins")
)
if _ADDON_PKG_PATH not in sys.path:
    sys.path.insert(0, _ADDON_PKG_PATH)


# --------------------------------------------------------------------------
# Stubs de modulos NVDA — instalados antes de qualquer import do projeto
# --------------------------------------------------------------------------

def _build_config_stub() -> MagicMock:
    """config.conf precisa se comportar como dict aninhado."""
    stub = MagicMock()
    stub.conf = {}
    return stub


def _build_gui_settings_stub() -> types.ModuleType:
    mod = types.ModuleType("gui.settingsDialogs")
    mod.SettingsPanel = object          # NVDAStudioSettingsPanel herda de object nos testes
    mod.NVDASettingsDialog = MagicMock()
    return mod


_NVDA_MODULE_STUBS: dict[str, object] = {
    "ui":                    MagicMock(),
    "api":                   MagicMock(),
    "config":                _build_config_stub(),
    "gui":                   MagicMock(),
    "gui.guiHelper":         MagicMock(),
    "wx":                    MagicMock(),
    "globalPluginHandler":   MagicMock(),
    "addonHandler":          MagicMock(),
    "scriptHandler":         MagicMock(),
    "logHandler":            MagicMock(),
    "speech":                MagicMock(),
    "braille":               MagicMock(),
    "tones":                 MagicMock(),
    "gui.settingsDialogs":   _build_gui_settings_stub(),
}


def install_nvda_stubs() -> None:
    """Instala stubs NVDA no sys.modules. Idempotente."""
    for name, stub in _NVDA_MODULE_STUBS.items():
        if name not in sys.modules:
            sys.modules[name] = stub  # type: ignore[assignment]


install_nvda_stubs()


# --------------------------------------------------------------------------
# Fixtures de sessao
# --------------------------------------------------------------------------

@pytest.fixture(scope="session")
def fake_api_key() -> str:
    """Chave API falsa para testes sem chamada real a API."""
    return "gsk_test_0000000000000000000000000000000000000000"


# --------------------------------------------------------------------------
# Fixtures de dados — JSONs conforme contratos dos modulos
# --------------------------------------------------------------------------

@pytest.fixture
def valid_plan_json() -> dict:
    """JSON de plano valido conforme contrato do Planner."""
    return {
        "complexity": "medium",
        "requires_web_research": False,
        "requires_agent_runner": False,
        "steps": [
            {
                "step_id": "s1",
                "step_type": "code_generation",
                "description": "Gerar codigo do addon",
                "expected_output": "codigo Python completo",
                "depends_on": [],
                "context_from_steps": [],
            },
            {
                "step_id": "s2",
                "step_type": "manifest_builder",
                "description": "Gerar manifest.ini",
                "expected_output": "manifest.ini valido",
                "depends_on": [],
                "context_from_steps": [],
            },
            {
                "step_id": "s3",
                "step_type": "accessibility_audit",
                "description": "Auditar acessibilidade do codigo gerado",
                "expected_output": "relatorio de auditoria",
                "depends_on": ["s1"],
                "context_from_steps": ["s1"],
            },
            {
                "step_id": "s4",
                "step_type": "assembly",
                "description": "Montar artefatos finais",
                "expected_output": "addon completo e organizado",
                "depends_on": ["s1", "s2", "s3"],
                "context_from_steps": ["s1", "s2", "s3"],
            },
        ],
    }


@pytest.fixture
def valid_critic_json_approved() -> str:
    return '{"verdict": "APROVADO", "score": 95, "issues": [], "fix_instructions": ""}'


@pytest.fixture
def valid_critic_json_fix() -> str:
    return (
        '{"verdict": "CORRIGIR", "score": 72, '
        '"issues": ["Falta addonHandler.initTranslation()"], '
        '"fix_instructions": "Adicione addonHandler.initTranslation() apos os imports."}'
    )


@pytest.fixture
def valid_critic_json_reject() -> str:
    return (
        '{"verdict": "REJEITAR", "score": 30, '
        '"issues": ["Sem classe GlobalPlugin", "Sem imports"], '
        '"fix_instructions": "Reescreva o addon do zero com a estrutura correta."}'
    )


# --------------------------------------------------------------------------
# Fixtures de conteudo — refletem output real esperado dos sub-agentes
# --------------------------------------------------------------------------

@pytest.fixture
def sample_addon_code() -> str:
    """Codigo Python de addon NVDA valido — usado em testes de validacao e Critic."""
    return (
        "import globalPluginHandler\n"
        "import ui\n"
        "import addonHandler\n"
        "from scriptHandler import script\n\n"
        "addonHandler.initTranslation()\n\n"
        "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
        "    scriptCategory = 'TestAddon'\n\n"
        "    @script(gesture='kb:NVDA+shift+t', description='Teste')\n"
        "    def script_teste(self, gesture):\n"
        "        try:\n"
        "            ui.message('Teste')\n"
        "        except Exception as exc:\n"
        "            pass\n"
    )


@pytest.fixture
def sample_manifest_ini() -> str:
    """Conteudo de manifest.ini valido — todos os campos obrigatorios presentes.
    Versoes alinhadas com a politica atual do projeto (2026-03-25):
    minimumNVDAVersion = 2026.1.1 / lastTestedNVDAVersion = 2026.1.1
    """
    # NVDA lê manifest.ini via ConfigObj sem secoes — sem [add-on] no topo.
    # Baseline oficial do NVDAStudio: 2026.1+
    return (
        "name = testAddon\n"
        "summary = Addon de teste\n"
        "description = Addon gerado para testes do NVDAStudio\n"
        "author = Tester <tester@example.com>\n"
        "url = https://github.com/test/testAddon\n"
        "version = 1.0.0\n"
        "minimumNVDAVersion = 2026.1.1\n"
        "lastTestedNVDAVersion = 2026.1.1\n"
    )


@pytest.fixture
def ai_response_with_code_blocks() -> str:
    """Resposta simulada da IA com blocos de codigo anotados (python e ini)."""
    return (
        "Aqui esta o addon gerado:\n\n"
        "```python:globalPlugins/testAddon/__init__.py\n"
        "import globalPluginHandler\n"
        "import ui\n"
        "import addonHandler\n\n"
        "addonHandler.initTranslation()\n\n"
        "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
        "    scriptCategory = 'TestAddon'\n"
        "```\n\n"
        "E o manifest:\n\n"
        "```ini:manifest.ini\n"
        "name = testAddon\n"
        "summary = Addon de teste\n"
        "version = 1.0.0\n"
        "minimumNVDAVersion = 2026.1.1\n"
        "lastTestedNVDAVersion = 2026.1.1\n"
        "```\n"
    )


# --------------------------------------------------------------------------
# Fixture de cleanup: fecha o singleton global de SessionMemory apos cada teste
# Evita ResourceWarning de file handle aberto quando o GC coleta o objeto
# entre testes diferentes.
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _close_global_session_memory():
    """Fecha o singleton global de SessionMemory apos cada teste.
    Evita que file handles do TinyDB fiquem abertos entre testes,
    prevenindo ResourceWarning com -W error.
    """
    yield
    try:
        import nvdastudio.memory.session_memory as _sm_mod
        _sm_mod.memory.close()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _force_gc_after_test():
    """Forca coleta de lixo apos cada teste.
    Garante que ResourceWarning de sockets SSL/file handles nao fechados
    apareca no teste que os criou, nao em um teste posterior aleatorio.
    """
    import gc
    yield
    gc.collect()


@pytest.fixture(autouse=True)
def _clear_sub_agent_client_cache():
    """Limpa o cache de clientes LLM em thread-local dos sub-agentes apos cada teste."""
    yield
    try:
        from nvdastudio.sub_agents._base import clear_client_cache
        clear_client_cache()
    except Exception:
        pass
