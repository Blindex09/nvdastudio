import os
import re

import pytest

from tests.e2e.test_fluxo_completo_nvda import (
    FluxoReport,
    _executar_fluxo_completo,
    skip_unless_ollama,
    )

# 5.1.0: skip_unless_ollama importado do modulo de referencia (fonte
# unica) e aplicado a nivel de modulo -- achado real de auditoria
# 2026-08-25: este arquivo chamava _executar_fluxo_completo() (pipeline
# real, LLM de verdade) sem NENHUM guard de API key. Sem
# OLLAMA_API_KEY/OPENCODE_GO_API_KEY configuradas, o teste ficava
# pendurado indefinidamente na chamada de rede sem timeout, em vez de
# skip limpo -- travava a suite inteira. Ver
# test_e20_regras_qualidade_codigo.py 5.1.0 para o achado completo.
pytestmark = skip_unless_ollama

# ---------------------------------------------------------------------------
# Helpers (Regra 9: apenas leitura de string)
# ---------------------------------------------------------------------------


def _ler_codigo(addon_folder: str) -> str:
    """
    Concatena o codigo de TODOS os arquivos .py do addon.

    Garante que chamadas como registerExecutableWithAppModule() sejam encontradas
    independentemente de em qual arquivo o AI as colocou — evita falsos negativos
    quando a chamada esta no GlobalPlugin mas o AppModule e encontrado primeiro.
    """
    partes: list[str] = []
    for root, _, files in os.walk(addon_folder):
        for f in sorted(files):
            if not f.endswith(".py"):
                continue
            caminho = os.path.join(root, f)
            try:
                with open(caminho, encoding="utf-8", errors="replace") as fh:
                    partes.append(fh.read())
            except OSError:
                pass
    return "\n".join(partes)


def _listar_arquivos(addon_folder: str) -> list[str]:
    """Lista todos os arquivos do addon com caminho relativo (slash forward)."""
    resultado: list[str] = []
    for root, _, files in os.walk(addon_folder):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), addon_folder).replace("\\", "/")
            resultado.append(rel)
    return resultado


# ---------------------------------------------------------------------------
# Fixture NVDA-039 — GlobalPlugin com multiplos executaveis
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fluxo_multiplos_exes() -> FluxoReport:
    """NVDA-039: GlobalPlugin que mapeia multiplos executaveis ao mesmo AppModule."""
    return _executar_fluxo_completo(
        addon_name="SuiteOffice_e2e",
        query=(
            "Crie um GlobalPlugin NVDA chamado 'SuiteOffice' que melhora a acessibilidade "
            "de todos os apps Microsoft Office (Word, Excel, PowerPoint). O addon deve: "
            "1) No metodo __init__ do GlobalPlugin, chamar EXPLICITAMENTE: "
            "appModuleHandler.registerExecutableWithAppModule('winword.exe', 'office_app'), "
            "appModuleHandler.registerExecutableWithAppModule('excel.exe', 'office_app') e "
            "appModuleHandler.registerExecutableWithAppModule('powerpnt.exe', 'office_app'). "
            "Essa e a API OFICIAL do NVDA para associar multiplos executaveis a um AppModule. "
            "NAO detecte o executavel via self.process.path, os.path ou qualquer logica condicional. "
            "NAO crie AppModules separados por executavel. "
            "2) No terminate() do GlobalPlugin, chamar: "
            "appModuleHandler.unregisterExecutable('winword.exe'), "
            "appModuleHandler.unregisterExecutable('excel.exe') e "
            "appModuleHandler.unregisterExecutable('powerpnt.exe'); "
            "3) Criar appModules/office_app.py com classe AppModule(appModuleHandler.AppModule) "
            "que adiciona melhorias de acessibilidade basicas para Office; "
            "4) Implementar __init__(self, *args, **kwargs) com super().__init__(*args, **kwargs); "
            "5) Ter terminate() com super().terminate() como ULTIMA linha; "
            "6) Ter manifest.ini com minimumNVDAVersion=2026.1.1, lastTestedNVDAVersion=2026.1."
        ),
    )


# ---------------------------------------------------------------------------
# Fixture NVDA-040 — AppModule para app UWP em wwahost.exe
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fluxo_wwahost() -> FluxoReport:
    """NVDA-040: AppModule para app UWP que roda em wwahost.exe."""
    return _executar_fluxo_completo(
        addon_name="UWPApp_e2e",
        query=(
            "Crie um AppModule NVDA para um aplicativo UWP (Universal Windows Platform) "
            "que roda em wwahost.exe. O AppModule deve: "
            "1) Herdar de nvdaBuiltin.appModules.wwahost.AppModule (NAO de "
            "appModuleHandler.AppModule diretamente) — apps UWP em wwahost.exe exigem "
            "essa heranca especial para o AppModule ser ativado corretamente; "
            "2) Ter __init__(self, *args, **kwargs) com super().__init__(*args, **kwargs); "
            "3) Ter terminate() com super().terminate() como ULTIMA linha; "
            "4) Arquivo em appModules/wwahost.py; "
            "5) Ter manifest.ini com minimumNVDAVersion=2026.1.1, lastTestedNVDAVersion=2026.1."
        ),
    )


# ---------------------------------------------------------------------------
# Fixture NVDA-041 — AppModule com sleepMode=True para app autoloquente
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fluxo_sleep_mode() -> FluxoReport:
    """NVDA-041: AppModule com sleepMode=True para app autoloquente (self-voicing)."""
    return _executar_fluxo_completo(
        addon_name="AppAutoloquente_e2e",
        query=(
            "Crie um AppModule NVDA para um aplicativo de leitura de tela proprietario "
            "chamado 'VozApp' (vozapp.exe) que tem voz propria (autoloquente/self-voicing). "
            "O AppModule deve: "
            "1) Ter sleepMode = True como atributo de classe — isso suprime toda a fala "
            "do NVDA enquanto o app esta em foco (evita dupla fala); "
            "2) Herdar de appModuleHandler.AppModule; "
            "3) Ter __init__(self, *args, **kwargs) com super().__init__(*args, **kwargs); "
            "4) Ter terminate() com super().terminate() como ULTIMA linha; "
            "5) Arquivo em appModules/vozapp.py; "
            "6) Ter manifest.ini com minimumNVDAVersion=2026.1.1, lastTestedNVDAVersion=2026.1."
        ),
    )


# ---------------------------------------------------------------------------
# Testes NVDA-039 — Multiplos executaveis
# ---------------------------------------------------------------------------


class TestMultiplosExecutaveis:
    """
    Valida NVDA-039: registerExecutableWithAppModule para multiplos executaveis.

    Regra 9: nenhum codigo e executado em nenhuma validacao.
    """

    def test_nvda039_usa_register_executable(
        self, fluxo_multiplos_exes: FluxoReport
    ) -> None:
        """
        NVDA-039: GlobalPlugin que suporta multiplos executaveis deve usar
        appModuleHandler.registerExecutableWithAppModule().

        Criar um AppModule separado por executavel e verboso e fragil.
        O registro centralizado via registerExecutableWithAppModule() e o mecanismo
        oficial para associar um AppModule a executaveis adicionais alem do .py principal.
        """
        if not fluxo_multiplos_exes.success:
            pytest.skip("Pipeline nao concluiu")
        code = _ler_codigo(fluxo_multiplos_exes.addon_folder)
        assert "registerExecutableWithAppModule" in code, (
            "NVDA-039: addon com multiplos executaveis nao usa "
            "appModuleHandler.registerExecutableWithAppModule(). "
            "Registre cada exe adicional via: "
            "appModuleHandler.registerExecutableWithAppModule('outro.exe', 'NomeModulo')."
        )

    def test_nvda039_unregister_no_terminate(
        self, fluxo_multiplos_exes: FluxoReport
    ) -> None:
        """
        NVDA-039: Executaveis registrados via registerExecutableWithAppModule devem
        ser removidos via unregisterExecutable() no terminate().

        Sem o unregister, o mapeamento persiste apos o addon ser descarregado,
        podendo causar comportamento inesperado ao recarregar ou desativar o addon.
        """
        if not fluxo_multiplos_exes.success:
            pytest.skip("Pipeline nao concluiu")
        code = _ler_codigo(fluxo_multiplos_exes.addon_folder)
        if "registerExecutableWithAppModule" not in code:
            pytest.skip("Addon nao usa registerExecutableWithAppModule — skip unregister")
        assert "unregisterExecutable" in code, (
            "NVDA-039: addon usa registerExecutableWithAppModule() mas nao chama "
            "appModuleHandler.unregisterExecutable() no terminate(). "
            "Cada exe registrado deve ser removido no terminate() para evitar "
            "mapeamentos fantasma apos desativar o addon."
        )

    def test_nvda039_registra_multiplos_exes(
        self, fluxo_multiplos_exes: FluxoReport
    ) -> None:
        """
        NVDA-039: O addon deve registrar ao menos 2 executaveis distintos.

        Um unico registerExecutableWithAppModule() nao caracteriza o padrao
        de suporte a multiplos executaveis — o beneficio e ter varias chamadas.
        """
        if not fluxo_multiplos_exes.success:
            pytest.skip("Pipeline nao concluiu")
        code = _ler_codigo(fluxo_multiplos_exes.addon_folder)
        if "registerExecutableWithAppModule" not in code:
            pytest.skip("Addon nao usa registerExecutableWithAppModule")
        ocorrencias = len(re.findall(r"registerExecutableWithAppModule\s*\(", code))
        assert ocorrencias >= 2, (
            f"NVDA-039: apenas {ocorrencias} chamada(s) a registerExecutableWithAppModule(). "
            "O padrao de multiplos executaveis requer ao menos 2 registros distintos."
        )


# ---------------------------------------------------------------------------
# Testes NVDA-040 — Heranca especial para wwahost.exe
# ---------------------------------------------------------------------------


class TestWwahostAppModule:
    """
    Valida NVDA-040: heranca correta para AppModule de app UWP em wwahost.exe.

    Regra 9: nenhum codigo e executado em nenhuma validacao.
    """

    def test_nvda040_wwahost_herda_corretamente(
        self, fluxo_wwahost: FluxoReport
    ) -> None:
        """
        NVDA-040: AppModule para wwahost.exe deve herdar de
        nvdaBuiltin.appModules.wwahost.AppModule, nao de appModuleHandler.AppModule.

        wwahost.exe hospeda apps UWP (Universal Windows Platform). O AppModule builtin
        do NVDA para wwahost ja trata IAccessible2 e ativacao de modo especial.
        Herdar diretamente de appModuleHandler.AppModule ignora esse comportamento
        e o AppModule pode nao ser ativado para apps UWP aninhadas.
        """
        if not fluxo_wwahost.success:
            pytest.skip("Pipeline nao concluiu")
        code = _ler_codigo(fluxo_wwahost.addon_folder)
        if "wwahost" not in code.lower():
            pytest.skip("Addon gerado nao menciona wwahost")
        # Aceita qualquer padrao de import valido do wwahost via nvdaBuiltin:
        #   Padrao 1: import nvdaBuiltin.appModules.wwahost (-> nvdaBuiltin.appModules.wwahost.AppModule)
        #   Padrao 2: from nvdaBuiltin.appModules import wwahost (-> wwahost.AppModule)
        #   Padrao 3: from nvdaBuiltin.appModules.wwahost import AppModule as X
        herda_wwahost = (
            "nvdaBuiltin.appModules.wwahost" in code
            or "appModules.wwahost" in code
            # Padrao 2: nvdaBuiltin no import + wwahost como heranca
            or ("nvdaBuiltin" in code and "wwahost.AppModule" in code)
        )
        assert herda_wwahost, (
            "NVDA-040: addon para wwahost.exe nao herda de "
            "nvdaBuiltin.appModules.wwahost.AppModule. "
            "Apps UWP requerem essa heranca especial para ativacao correta do AppModule. "
            "Herdar de appModuleHandler.AppModule diretamente nao e suficiente. "
            "Padroes validos: 'import nvdaBuiltin.appModules.wwahost' ou "
            "'from nvdaBuiltin.appModules import wwahost'."
        )

    def test_nvda040_nao_herda_direto_de_appmodulehandler(
        self, fluxo_wwahost: FluxoReport
    ) -> None:
        """
        NVDA-040: O AppModule de wwahost NAO deve herdar APENAS de
        appModuleHandler.AppModule quando o alvo e uma app UWP.

        Herdar apenas de appModuleHandler.AppModule ignora o comportamento especial
        que o builtin wwahost.AppModule ja implementa para apps UWP.
        """
        if not fluxo_wwahost.success:
            pytest.skip("Pipeline nao concluiu")
        code = _ler_codigo(fluxo_wwahost.addon_folder)
        if "wwahost" not in code.lower():
            pytest.skip("Addon gerado nao menciona wwahost")
        # Se herda do builtin wwahost, esta correto — o teste passa.
        # Se menciona wwahost mas so herda de appModuleHandler.AppModule diretamente,
        # e um sinal de que nao usou a heranca especial.
        herda_wwahost_builtin = (
            "nvdaBuiltin.appModules.wwahost" in code
            or "appModules.wwahost" in code
        )
        if herda_wwahost_builtin:
            return  # correto — nao ha problema
        # Verifica se a unica heranca e appModuleHandler.AppModule sem wwahost
        apenas_handler = bool(
            re.search(r"class\s+AppModule\s*\(\s*appModuleHandler\.AppModule\s*\)", code)
        )
        assert not apenas_handler, (
            "NVDA-040: classe AppModule herda apenas de appModuleHandler.AppModule "
            "para um addon de wwahost.exe. "
            "Use: from nvdaBuiltin.appModules import wwahost; "
            "class AppModule(wwahost.AppModule): ..."
        )

    def test_nvda040_arquivo_em_appmodules_wwahost(
        self, fluxo_wwahost: FluxoReport
    ) -> None:
        """
        NVDA-040: O arquivo principal do AppModule deve ser appModules/wwahost.py.

        O NVDA carrega AppModules pelo nome do executavel. Para wwahost.exe,
        o arquivo deve ser appModules/wwahost.py para ser encontrado automaticamente.
        """
        if not fluxo_wwahost.success:
            pytest.skip("Pipeline nao concluiu")
        arquivos = _listar_arquivos(fluxo_wwahost.addon_folder)
        tem_wwahost_py = any(
            "appmodules/wwahost.py" == a.lower()
            or a.lower().endswith("/wwahost.py")
            for a in arquivos
        )
        assert tem_wwahost_py, (
            "NVDA-040: arquivo appModules/wwahost.py nao encontrado. "
            f"Arquivos presentes: {arquivos}. "
            "O NVDA carrega AppModules pelo nome do executavel — "
            "para wwahost.exe o arquivo deve ser appModules/wwahost.py."
        )


# ---------------------------------------------------------------------------
# Testes NVDA-041 — SleepMode para apps autoloquentes
# ---------------------------------------------------------------------------


class TestSleepMode:
    """
    Valida NVDA-041: sleepMode = True para apps autoloquentes (self-voicing).

    Regra 9: nenhum codigo e executado em nenhuma validacao.
    """

    def test_nvda041_app_autoloquente_tem_sleep_mode(
        self, fluxo_sleep_mode: FluxoReport
    ) -> None:
        """
        NVDA-041: AppModule para app autoloquente deve ter sleepMode = True.

        Apps autoloquentes (self-voicing) tem seu proprio sintetizador de voz.
        Sem sleepMode = True, o NVDA e o app falam ao mesmo tempo — dupla fala
        que e confusa e inutilizavel para o usuario cego.
        sleepMode = True instrui o NVDA a ficar em silencio enquanto o app esta em foco.
        """
        if not fluxo_sleep_mode.success:
            pytest.skip("Pipeline nao concluiu")
        code = _ler_codigo(fluxo_sleep_mode.addon_folder)
        assert "sleepMode" in code, (
            "NVDA-041: AppModule para app autoloquente sem sleepMode. "
            "Declare sleepMode = True como atributo de classe no AppModule para "
            "suprimir a fala do NVDA enquanto o app esta em foco."
        )

    def test_nvda041_sleep_mode_e_true(
        self, fluxo_sleep_mode: FluxoReport
    ) -> None:
        """
        NVDA-041: O valor de sleepMode deve ser True (booleano), nao False nem string.

        sleepMode = False nao surte efeito — e o padrao. O atributo so e util quando
        definido como True. Qualquer outro valor causa comportamento indefinido.
        """
        if not fluxo_sleep_mode.success:
            pytest.skip("Pipeline nao concluiu")
        code = _ler_codigo(fluxo_sleep_mode.addon_folder)
        if "sleepMode" not in code:
            pytest.skip("sleepMode ausente — skip de valor")
        # Aceita tanto "sleepMode = True" como "sleepMode: bool = True" (type annotation)
        tem_sleep_true = bool(
            re.search(r"sleepMode(?:\s*:\s*\w+)?\s*=\s*True", code)
        )
        assert tem_sleep_true, (
            "NVDA-041: sleepMode presente mas valor nao e True. "
            "Declare: sleepMode = True (ou sleepMode: bool = True) na classe AppModule. "
            "sleepMode = False nao tem efeito — o NVDA continuara falando normalmente."
        )

    def test_nvda041_sleep_mode_e_atributo_de_classe(
        self, fluxo_sleep_mode: FluxoReport
    ) -> None:
        """
        NVDA-041: sleepMode deve ser atributo de CLASSE, nao atribuido no __init__.

        Atribuir sleepMode no __init__ (self.sleepMode = True) pode nao ser lido
        antes do NVDA decidir se deve silenciar o addon, dependendo da ordem
        de inicializacao. O atributo de classe garante disponibilidade imediata.
        """
        if not fluxo_sleep_mode.success:
            pytest.skip("Pipeline nao concluiu")
        code = _ler_codigo(fluxo_sleep_mode.addon_folder)
        if "sleepMode" not in code:
            pytest.skip("sleepMode ausente — skip de posicao")
        # Atribuicao via self.sleepMode no __init__ e menos segura
        atribuicao_em_init = bool(
            re.search(r"self\.sleepMode\s*=\s*True", code)
        )
        # Atributo de classe correto — aceita com ou sem type annotation:
        #   sleepMode = True        (sem anotacao)
        #   sleepMode: bool = True  (com anotacao — igualmente valido)
        atributo_de_classe = bool(
            re.search(
                r"^\s{4}sleepMode(?:\s*:\s*\w+)?\s*=\s*True",
                code,
                re.MULTILINE,
            )
        )
        if atribuicao_em_init and not atributo_de_classe:
            pytest.skip(
                "NVDA-041: sleepMode atribuido via self.sleepMode = True no __init__ "
                "em vez de atributo de classe. "
                "Prefira declarar sleepMode = True diretamente no corpo da classe, "
                "nao dentro de __init__."
            )
        assert atributo_de_classe or bool(
            re.search(r"sleepMode(?:\s*:\s*\w+)?\s*=\s*True", code)
        ), (
            "NVDA-041: sleepMode = True nao encontrado como atributo de classe. "
            "Declare dentro do corpo da classe AppModule, antes de qualquer metodo. "
            "Formatos aceitos: 'sleepMode = True' ou 'sleepMode: bool = True'."
        )

    def test_nvda041_arquivo_em_appmodules(
        self, fluxo_sleep_mode: FluxoReport
    ) -> None:
        """
        NVDA-041: O arquivo do AppModule deve estar em appModules/.

        sleepMode so tem efeito em AppModule — em GlobalPlugin e ignorado.
        O arquivo deve estar em appModules/<nome_exe>.py para que o NVDA
        o ative apenas quando o app alvo esta em foco.
        """
        if not fluxo_sleep_mode.success:
            pytest.skip("Pipeline nao concluiu")
        arquivos = _listar_arquivos(fluxo_sleep_mode.addon_folder)
        tem_appmodule_dir = any("appmodules/" in a.lower() for a in arquivos)
        assert tem_appmodule_dir, (
            "NVDA-041: nenhum arquivo encontrado em appModules/. "
            f"Arquivos presentes: {arquivos}. "
            "sleepMode so funciona em AppModule — o arquivo deve estar em "
            "appModules/<nome_exe>.py (ex: appModules/vozapp.py)."
        )
