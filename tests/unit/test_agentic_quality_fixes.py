from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_sandbox_failure_evidence_nao_depende_de_stderr():
    from nvdastudio.core.orchestrator import _sandbox_failure_evidence

    result = SimpleNamespace(success=False, error="Timeout: validacao excedeu 15s", stderr="", stdout="")

    assert "Timeout" in _sandbox_failure_evidence(result)


def test_mental_simulation_detecta_ciclo_com_tres_steps():
    from nvdastudio.core.agentic_loop import StrategyExecutor

    def step(step_id, depends_on):
        return SimpleNamespace(
            step_id=step_id,
            step_type="code_generation",
            depends_on=depends_on,
            model_id="model",
        )

    plan = SimpleNamespace(
        steps=[
            step("a", ["c"]),
            step("b", ["a"]),
            step("c", ["b"]),
        ]
    )
    executor = StrategyExecutor(MagicMock())

    with patch.object(executor, "_run_sync") as run_sync:
        executor.mental_simulation("crie um addon", plan)

    query = run_sync.call_args.args[0]
    assert "CICLO:" in query
    assert "a -> c -> b -> a" in query or "b -> a -> c -> b" in query


def test_swap_model_usa_get_resilience_model_do_orchestrator():
    """
    Regressao 2.6.0: SWAP_MODEL nao deve mais ter logica propria de escolha
    de modelo (antes: alternava cegamente entre tier light/heavy). Deve
    delegar para orchestrator.get_resilience_model(step_type), a mesma
    fonte que a escalacao interna do pipeline usa -- as duas nao podem
    mais divergir sobre qual e o proximo modelo pra um step_type.
    """
    from nvdastudio.core.agentic_loop import StrategyExecutor

    orch = MagicMock()
    orch.get_resilience_model.return_value = "modelo-resiliente"
    executor = StrategyExecutor(orch)

    with patch.object(executor, "_run_sync") as run_sync:
        executor.swap_model("crie um addon", "code_generation", "modelo-atual")

    orch.get_resilience_model.assert_called_once_with("code_generation")
    assert "modelo-resiliente" in orch._previous_issues[0]
    run_sync.assert_called_once_with("crie um addon")


def test_swap_model_quando_ja_esta_no_modelo_de_resiliencia():
    """Se get_resilience_model() ja retorna o modelo atual (escalacao
    interna do pipeline ja tentou), swap_model nao deve crashar nem propor
    um modelo diferente -- so reexecuta (cross-provider rescue, dentro do
    pipeline, assume a partir dai)."""
    from nvdastudio.core.agentic_loop import StrategyExecutor

    orch = MagicMock()
    orch.get_resilience_model.return_value = "modelo-atual"
    executor = StrategyExecutor(orch)

    with patch.object(executor, "_run_sync") as run_sync:
        executor.swap_model("crie um addon", "code_generation", "modelo-atual")

    run_sync.assert_called_once_with("crie um addon")


def test_self_play_avalia_todos_os_cenarios_adversos():
    from nvdastudio.core.agentic_loop import StrategyExecutor

    executor = StrategyExecutor(MagicMock())
    with patch.object(executor, "_run_sync") as run_sync:
        executor.self_play_adversarial("crie um addon que consulta uma API")

    query = run_sync.call_args.args[0]
    assert "401" in query
    assert "timeout de 5s" in query
    assert "arquivo existe" in query
    assert "cancelar o dialogo" in query


def test_tool_creation_rejeita_codigo_invalido_e_faz_fallback():
    from nvdastudio.core.agentic_loop import StrategyExecutor

    client = MagicMock()
    client.chat.return_value.content = "def nao_terminada("
    executor = StrategyExecutor(MagicMock())
    with (
        patch("nvdastudio.ai.llm_factory.create_llm_client", return_value=client),
        patch("nvdastudio.gui.settings_panel.get_llm_provider", return_value="openai"),
        patch("nvdastudio.gui.settings_panel.get_llm_model", return_value="test-model"),
        patch("nvdastudio.ai.model_registry.resolve_provider_tier_model", return_value="test-model"),
        patch.object(executor, "_run_sync") as run_sync,
    ):
        executor.tool_creation("crie um addon", "parser de markdown")

    assert run_sync.call_args.args[0] == "crie um addon"


def test_fault_injection_executa_addon_real_em_subprocessos_isolados():
    from nvdastudio.builder.code_sandbox import CodeSandbox

    files = {
        "globalPlugins/MeuAddon/__init__.py": (
            "import builtins\n"
            "import urllib.request\n"
            "import urllib.error\n\n"
            "import globalPluginHandler\n\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def __init__(self):\n"
            "        try:\n"
            "            urllib.request.urlopen('http://example.invalid')\n"
            "        except (urllib.error.HTTPError, OSError):\n"
            "            pass\n"
            "        try:\n"
            "            builtins.open('arquivo-que-nao-existe')\n"
            "        except FileNotFoundError:\n"
            "            pass\n"
        )
    }

    result = CodeSandbox(timeout_sec=3).validate_addon_resilience(files, timeout=3)
    assert result.success is True
    assert "api_401" in result.stdout
    assert "missing_file" in result.stdout


def test_validacao_final_rejeita_zip_com_path_traversal(tmp_path):
    import zipfile

    from nvdastudio.builder.code_sandbox import CodeSandbox

    package = tmp_path / "malicioso.nvda-addon"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("../../fora-do-pacote.txt", "nao deveria ser extraido")

    result = CodeSandbox().validate_final_package(str(package))
    assert result.success is False
    assert "path traversal" in result.error
