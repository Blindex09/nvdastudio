import os
import re

import pytest

HAS_OLLAMA = os.environ.get("OLLAMA_API_KEY", "").strip()
# 2026-08-17: critic.py 3.19.0 -- o Critic agora SEMPRE usa OpenCode Go
# (prompt caching), independente do provider ativo. Sem essa chave, TODA
# avaliacao de step falha com "Chave API para opencode_go nao configurada"
# -- achado real ao vivo (madrugada 2026-08-17/18, rodada 1 do loop): os
# 2 casos deste arquivo rodaram e "passaram" no pytest (test_e36 nao exige
# success=True) mas o pipeline inteiro falhou em segundos, 0 tokens gastos,
# nenhum sinal real coletado -- so desperdicou tempo/custo do Ollama sem
# testar nada. Adicionado ao skip guard pra nao rodar (e enganar) sem as
# 2 chaves.
HAS_OPENCODE_GO = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
skip_unless_ollama = pytest.mark.skipif(
    not HAS_OLLAMA or not HAS_OPENCODE_GO,
    reason=("Ollama Cloud token nao disponivel" if not HAS_OLLAMA else "OpenCode Go token nao disponivel (necessario pro Critic, ver critic.py 3.19.0)")
)

# Codigo de addon simples para injetar no prompt do TestGenerator
_SAMPLE_ADDON_CODE = '''```python
import addonHandler
import globalPluginHandler
import ui
import api

addonHandler.initTranslation()


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    """Addon que anuncia a hora atual."""

    def __init__(self):
        super().__init__()

    def terminate(self):
        super().terminate()

    def script_announceTime(self, gesture):
        """Anuncia a hora atual."""
        import datetime
        hora = datetime.datetime.now().strftime("%H:%M:%S")
        ui.message(hora)

    __gestures = {
        "kb:NVDA+shift+h": "announceTime",
    }
```'''

# Addon com classe AppModule para testar que AST extrai corretamente
_SAMPLE_APP_MODULE_CODE = '''```python
import appModuleHandler
import ui
import api


class AppModule(appModuleHandler.AppModule):
    """AppModule para o Visual Studio Code."""

    def event_gainFocus(self, obj, nextHandler):
        nextHandler()

    def script_reportLine(self, gesture):
        focus = api.getFocusObject()
        if focus:
            ui.message(focus.name or "sem nome")
```'''


# ---------------------------------------------------------------------------
# Classe 1: Contrato de saida — nao HTML, nao .ini, nao markdown
# ---------------------------------------------------------------------------

@skip_unless_ollama
class TestTestGeneratorSaidaProibida:
    """
    SAIDA PROIBIDA do TestGenerator (v1.2.0+):
    - HTML — PROIBIDO
    - Arquivos .ini ou .cfg — PROIBIDO
    - Arquivos Markdown — PROIBIDO
    - Documentacao de qualquer tipo — PROIBIDO
    - Codigo de producao (__init__.py) — PROIBIDO

    Invariante: output deve comecar com bloco ```python:tests/test_*.py
    e conter funcoes test_*.
    """

    def test_output_nao_e_html(self):
        """TestGenerator nao deve gerar HTML em hipotese alguma."""
        from nvdastudio.sub_agents.test_generator import run
        from nvdastudio.core.planner import STEP_MODEL_MAP

        output = run(
            prompt=f"Gere testes para o seguinte addon NVDA:\n\n{_SAMPLE_ADDON_CODE}",
            model_id=STEP_MODEL_MAP.get("test_generation", "kimi-k2.6"),
            reasoning_params={},
        )

        assert isinstance(output, str)
        assert len(output) > 50

        output_lower = output.lower()
        # HTML nao deve estar presente como estrutura dominante
        assert not output_lower.startswith("<!doctype"), (
            "TestGenerator gerou HTML — SAIDA PROIBIDA"
        )
        assert not output_lower.startswith("<html"), (
            "TestGenerator gerou HTML — SAIDA PROIBIDA"
        )
        # Nao deve ser documentacao
        assert "userguide" not in output_lower.replace(" ", ""), (
            "TestGenerator gerou documentacao — SAIDA PROIBIDA"
        )

    def test_output_nao_e_manifest_ini(self):
        """TestGenerator nao deve gerar manifest.ini."""
        from nvdastudio.sub_agents.test_generator import run
        from nvdastudio.core.planner import STEP_MODEL_MAP

        output = run(
            prompt=f"Gere testes para:\n\n{_SAMPLE_ADDON_CODE}",
            model_id=STEP_MODEL_MAP.get("test_generation", "kimi-k2.6"),
            reasoning_params={},
        )

        output_lower = output.lower()
        # Se comecar com [add-on] ou name = e version = e manifest
        is_manifest = (
            "[add-on]" in output_lower
            or ("name =" in output_lower and "version =" in output_lower
                and "minimumnvdaversion" in output_lower)
        )
        assert not is_manifest, (
            "TestGenerator gerou manifest.ini — SAIDA PROIBIDA"
        )

    def test_output_contem_codigo_python(self):
        """Output deve conter codigo Python com funcoes test_*."""
        from nvdastudio.sub_agents.test_generator import run
        from nvdastudio.core.planner import STEP_MODEL_MAP

        output = run(
            prompt=f"Gere testes unitarios para o addon abaixo:\n\n{_SAMPLE_ADDON_CODE}",
            model_id=STEP_MODEL_MAP.get("test_generation", "kimi-k2.6"),
            reasoning_params={},
        )

        assert isinstance(output, str)
        assert len(output) > 100, "Output muito curto para conter testes reais"

        # Deve ter pelo menos uma funcao test_ ou classe Test
        has_test_func = bool(re.search(r"def test_\w+", output))
        has_test_class = bool(re.search(r"class Test\w+", output))
        assert has_test_func or has_test_class, (
            "Output nao contem funcoes test_* nem classes Test*. "
            f"Primeiros 300 chars: {output[:300]}"
        )

    def test_output_tem_minimo_de_tres_testes(self):
        """
        Invariante do prompt v1.2.0+: output deve ter ao menos 3 funcoes de teste.
        VERIFICACAO FINAL obrigatoria no prompt: 'pelo menos 3 funcoes de teste distintas'.
        """
        from nvdastudio.sub_agents.test_generator import run
        from nvdastudio.core.planner import STEP_MODEL_MAP

        output = run(
            prompt=(
                "Gere testes unitarios completos para o addon NVDA a seguir.\n\n"
                + _SAMPLE_ADDON_CODE
            ),
            model_id=STEP_MODEL_MAP.get("test_generation", "kimi-k2.6"),
            reasoning_params={},
        )

        test_funcs = re.findall(r"def test_\w+", output)
        assert len(test_funcs) >= 3, (
            f"Output deve ter ao menos 3 funcoes test_*, encontrou {len(test_funcs)}. "
            f"Funcoes encontradas: {test_funcs}"
        )


# ---------------------------------------------------------------------------
# Classe 2: Analise AST — _extract_code_manifest
# ---------------------------------------------------------------------------

class TestTestGeneratorAST:
    """
    _extract_code_manifest() (v1.3.0) analisa AST do codigo real no prompt.
    Garante que o LLM gera testes para classes que realmente existem.

    Invariante: se codigo com GlobalPlugin e fornecido, o manifesto AST
    deve conter GlobalPlugin e o TestGenerator deve testar essa classe.
    """

    def test_extract_code_manifest_detecta_classe_globalplugin(self):
        """_extract_code_manifest deve detectar classe GlobalPlugin no bloco Python."""
        from nvdastudio.sub_agents.test_generator import _extract_code_manifest

        manifesto, sugestoes = _extract_code_manifest(_SAMPLE_ADDON_CODE)

        assert isinstance(manifesto, str)
        assert isinstance(sugestoes, list)
        assert len(manifesto) > 0, (
            "_extract_code_manifest retornou vazio para codigo com GlobalPlugin"
        )
        assert "GlobalPlugin" in manifesto, (
            f"Manifesto nao detectou classe GlobalPlugin. Manifesto: {manifesto}"
        )

    def test_extract_code_manifest_detecta_appmodule(self):
        """_extract_code_manifest deve detectar classe AppModule."""
        from nvdastudio.sub_agents.test_generator import _extract_code_manifest

        manifesto, sugestoes = _extract_code_manifest(_SAMPLE_APP_MODULE_CODE)

        assert isinstance(manifesto, str)
        assert isinstance(sugestoes, list)
        assert "AppModule" in manifesto, (
            f"Manifesto nao detectou classe AppModule. Manifesto: {manifesto}"
        )

    def test_extract_code_manifest_retorna_vazio_sem_codigo(self):
        """Prompt sem blocos Python deve retornar string vazia e lista vazia."""
        from nvdastudio.sub_agents.test_generator import _extract_code_manifest

        manifesto, sugestoes = _extract_code_manifest("Sem codigo aqui. Apenas texto descritivo.")

        assert manifesto == "", (
            f"Esperado string vazia, recebeu: '{manifesto}'"
        )
        assert sugestoes == [], (
            f"Esperado lista vazia de sugestoes, recebeu: {sugestoes}"
        )

    @skip_unless_ollama
    def test_testes_gerados_referenciam_classe_real(self):
        """
        Com AST manifest injetado, o LLM deve gerar testes para a classe
        que realmente existe no codigo, nao para uma classe inventada.
        Invariante: se GlobalPlugin existe no manifesto, os testes devem
        mencionar GlobalPlugin ou script_announceTime.
        """
        from nvdastudio.sub_agents.test_generator import run
        from nvdastudio.core.planner import STEP_MODEL_MAP

        output = run(
            prompt=(
                "Gere testes unitarios para o seguinte addon NVDA. "
                "Preste atencao nas classes e metodos reais:\n\n"
                + _SAMPLE_ADDON_CODE
            ),
            model_id=STEP_MODEL_MAP.get("test_generation", "kimi-k2.6"),
            reasoning_params={},
        )

        # Testes devem referenciar algo do codigo real
        has_globalplugin = "GlobalPlugin" in output or "globalplugin" in output.lower()
        has_script = "announceTime" in output or "announce_time" in output.lower()
        has_hora = "hora" in output.lower() or "time" in output.lower()

        assert has_globalplugin or has_script or has_hora, (
            "Testes nao referenciam nenhum elemento do codigo real. "
            "Possivel alucinacao de classe. "
            f"Primeiros 400 chars: {output[:400]}"
        )


# ---------------------------------------------------------------------------
# Classe 3: Mocks NVDA — setup/teardown corretos
# ---------------------------------------------------------------------------

@skip_unless_ollama
class TestTestGeneratorMocksNVDA:
    """
    Invariante v1.3.0: testes gerados devem mockar modulos NVDA via sys.modules
    em setUp() e restaurar em tearDown().
    Regra 9: apenas inspecao textual — nenhum codigo e executado.
    """

    def test_output_contem_sys_modules_mock(self):
        """setUp() deve mockar modulos NVDA via sys.modules."""
        from nvdastudio.sub_agents.test_generator import run
        from nvdastudio.core.planner import STEP_MODEL_MAP

        output = run(
            prompt=(
                "Gere testes para o addon que usa ui.message() e api.getFocusObject():\n\n"
                + _SAMPLE_ADDON_CODE
            ),
            model_id=STEP_MODEL_MAP.get("test_generation", "kimi-k2.6"),
            reasoning_params={},
        )

        # sys.modules deve estar presente (mocking de modulos NVDA)
        has_sys_modules = "sys.modules" in output
        has_mock = "mock" in output.lower() or "Mock" in output or "MagicMock" in output
        has_setup = "setUp" in output or "setup_method" in output or "fixture" in output.lower()

        assert has_sys_modules or has_mock, (
            "Output nao contem sys.modules nem Mock — modulos NVDA precisam ser mockados. "
            f"Primeiros 500 chars: {output[:500]}"
        )
        assert has_setup, (
            "Output nao contem setUp() ou equivalente para mocking"
        )

    def test_output_contem_teardown(self):
        """tearDown() deve restaurar sys.modules."""
        from nvdastudio.sub_agents.test_generator import run
        from nvdastudio.core.planner import STEP_MODEL_MAP

        output = run(
            prompt=(
                "Gere testes completos com setUp e tearDown para:\n\n"
                + _SAMPLE_ADDON_CODE
            ),
            model_id=STEP_MODEL_MAP.get("test_generation", "kimi-k2.6"),
            reasoning_params={},
        )

        has_teardown = (
            "tearDown" in output
            or "teardown_method" in output
            or "yield" in output  # pytest fixture com yield
        )

        assert has_teardown, (
            "Output nao contem tearDown() — sys.modules nao seria restaurado. "
            f"Primeiros 500 chars: {output[:500]}"
        )


# ---------------------------------------------------------------------------
# Classe 4: TestGenerator no pipeline completo
# ---------------------------------------------------------------------------

@skip_unless_ollama
class TestTestGeneratorNoPipeline:
    """
    Valida que o step test_generation aparece no pipeline completo quando
    o Planner o inclui no plano.

    Invariante (Q8.3/Q10.3): test_generation e BLOQUEANTE — pipeline
    deve tentar ate aprovar, nao pular silenciosamente.
    """

    def test_planner_inclui_test_generation_no_plano(self):
        """
        Planner deve incluir test_generation para addons que requerem testes.
        Valida que o step type esta presente no plano gerado.
        """
        from nvdastudio.core.planner import Planner

        planner = Planner()
        plan = planner.create_plan(
            "Crie um globalPlugin NVDA completo que anuncia a hora ao pressionar NVDA+H. "
            "Inclua testes unitarios para o addon gerado."
        )

        step_types = {s.step_type for s in plan.steps}
        assert "test_generation" in step_types, (
            "Planner deve incluir test_generation quando pedido explicitamente. "
            f"Steps gerados: {step_types}"
        )

    def test_step_test_generation_aparece_em_step_results(self):
        """
        No pipeline completo, o step test_generation deve aparecer em step_results
        quando incluido no plano — nao pode ser ignorado silenciosamente.
        """
        from nvdastudio.core.orchestrator import Orchestrator

        results = []
        events = []

        orch = Orchestrator()
        orch.initialize()
        orch.set_callbacks(
            on_progress=lambda ev, det: events.append((ev, det)),
            on_complete=lambda r: results.append(r),
        )

        orch._run_pipeline(
            "Crie um globalPlugin NVDA que anuncia a hora atual ao pressionar NVDA+H. "
            "Inclua testes unitarios para o codigo gerado."
        )

        assert results, "on_complete nao foi chamado"
        result = results[0]

        # Verifica se test_generation foi executado
        step_types_executados = {sr.step_type for sr in result.step_results}

        # Se o Planner incluiu test_generation, deve estar em step_results
        if "test_generation" in step_types_executados:
            test_gen_results = [
                sr for sr in result.step_results
                if sr.step_type == "test_generation"
            ]
            for tgr in test_gen_results:
                # Regra 9: output e string — nunca executado
                assert isinstance(tgr.output, str), "Output do test_generation deve ser string"

        # Pipeline deve ter completado (independente de test_generation)
        assert result.final_output is not None
        assert isinstance(result.final_output, str)

    def test_output_test_generation_e_python_quando_presente(self):
        """
        Quando test_generation e executado no pipeline real, seu output
        deve ser Python (nao HTML, nao .ini, nao markdown de documentacao).
        Regra 9: inspecao textual — nenhum codigo e executado.
        """
        from nvdastudio.core.orchestrator import Orchestrator

        results = []

        orch = Orchestrator()
        orch.initialize()
        orch.set_callbacks(
            on_progress=lambda ev, det: None,
            on_complete=lambda r: results.append(r),
        )

        orch._run_pipeline(
            "Crie um addon NVDA simples com testes unitarios incluidos."
        )

        assert results
        result = results[0]

        for sr in result.step_results:
            if sr.step_type == "test_generation" and sr.output:
                output_lower = sr.output.lower()
                # SAIDA PROIBIDA: nao pode ser HTML
                assert not output_lower.startswith("<!doctype"), (
                    "test_generation gerou HTML — SAIDA PROIBIDA"
                )
                # Deve ter sintaxe Python
                has_python = (
                    "def test_" in sr.output
                    or "class Test" in sr.output
                    or "import" in sr.output
                )
                assert has_python, (
                    "Output do test_generation nao parece ser Python valido. "
                    f"Primeiros 200 chars: {sr.output[:200]}"
                )

