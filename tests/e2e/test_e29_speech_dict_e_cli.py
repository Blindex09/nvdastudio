import configparser
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
# Helpers (Regra 9: apenas leitura de string — nunca executa codigo gerado)
# ---------------------------------------------------------------------------


def _ler_codigo_completo(addon_folder: str) -> str:
    """
    Concatena o codigo de TODOS os arquivos .py do addon em uma unica string.

    Garante que chamadas como isCLIParamKnown.register() sejam encontradas
    independentemente de em qual arquivo o AI as colocou — evita falsos
    negativos quando o addon e dividido em multiplos modulos.
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


def _ler_arquivo(addon_folder: str, rel_path: str) -> str:
    """
    Le um arquivo especifico do addon pelo caminho relativo.

    rel_path pode usar barras forward ou backward — e normalizado internamente.
    Retorna string vazia se o arquivo nao existir.
    """
    caminho = os.path.join(addon_folder, *rel_path.replace("\\", "/").split("/"))
    if os.path.isfile(caminho):
        try:
            with open(caminho, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            pass
    return ""


def _listar_arquivos(addon_folder: str) -> list[str]:
    """
    Lista todos os arquivos do addon com caminho relativo (barras forward).

    Util para inspecionar estrutura de diretorios sem executar nada.
    """
    resultado: list[str] = []
    for root, _, files in os.walk(addon_folder):
        for f in files:
            rel = os.path.relpath(
                os.path.join(root, f), addon_folder
            ).replace("\\", "/")
            resultado.append(rel)
    return resultado


def _ler_speech_dict(addon_folder: str) -> tuple[str, str]:
    """
    Retorna (conteudo, rel_path) do primeiro arquivo .dic em speechDicts/.

    Retorna ("", "") se a pasta nao existir ou nao houver nenhum .dic.
    Regra 9: apenas leitura — o conteudo nunca e avaliado como codigo.
    """
    sd_dir = os.path.join(addon_folder, "speechDicts")
    if not os.path.isdir(sd_dir):
        return "", ""
    for f in sorted(os.listdir(sd_dir)):
        if f.endswith(".dic"):
            caminho = os.path.join(sd_dir, f)
            rel = f"speechDicts/{f}"
            try:
                with open(caminho, encoding="utf-8", errors="replace") as fh:
                    return fh.read(), rel
            except OSError:
                pass
    return "", ""


def _ler_manifest(addon_folder: str) -> configparser.ConfigParser:
    """
    Le e faz o parse do manifest.ini com configparser.

    Usa OPTIONXFORM=str para preservar maiusculas/minusculas nas chaves.
    Retorna instancia vazia se o arquivo nao existir.
    """
    cfg = configparser.ConfigParser()
    cfg.optionxform = str  # type: ignore[assignment]
    caminho = os.path.join(addon_folder, "manifest.ini")
    if os.path.isfile(caminho):
        try:
            cfg.read(caminho, encoding="utf-8")
        except (configparser.Error, OSError):
            pass
    return cfg


# ---------------------------------------------------------------------------
# Fixture NVDA-038 — addon com speechDicts
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fluxo_speech_dict() -> FluxoReport:
    """
    Gera um addon com speechDicts UMA VEZ para toda a classe TestSpeechDict.

    A query e deliberadamente explicita sobre o formato exato do arquivo .dic
    para reduzir alucinacoes e garantir que o AI gere o artefato correto.
    """
    return _executar_fluxo_completo(
        addon_name="PronunciaCorreta_e2e",
        query=(
            "Crie um GlobalPlugin NVDA chamado 'PronunciaCorreta' que melhora a pronuncia de termos tecnicos. "
            "O addon DEVE: "
            "1) Criar arquivo speechDicts/pronuncia.dic com pelo menos 3 regras de pronuncia. "
            "   Cada linha de regra tem EXATAMENTE 4 campos separados por TAB (caractere \\t): "
            "   <pattern>\\t<replacement>\\t<caseSensitive>\\t<type> "
            "   Exemplo: NVDA\\tNonVisual Desktop Access\\t1\\t2 "
            "   Exemplo: (\\d+)%\\t\\1 por cento\\t0\\t1 "
            "   Exemplo: API\\tA P I\\t0\\t2 "
            "   O campo caseSensitive e 0 (insensivel) ou 1 (sensivel). "
            "   O campo type e inteiro de 0 a 6 (0=anywhere, 1=regex, 2=whole word, etc). "
            "   Linhas em branco e linhas comecando com # sao comentarios e devem ser ignoradas. "
            "2) Declarar no manifest.ini secao [speechDictionaries] com subsecao [[pronuncia]]: "
            "   [speechDictionaries] "
            "   [[pronuncia]] "
            "   displayName = Correcoes de Pronuncia "
            "   mandatory = false "
            "3) Implementar __init__(self, *args, **kwargs) com super().__init__(*args, **kwargs); "
            "4) Implementar terminate() com super().terminate() como ULTIMA linha; "
            "5) Ter manifest.ini com minimumNVDAVersion=2026.1.1, lastTestedNVDAVersion=2026.1."
        ),
    )


# ---------------------------------------------------------------------------
# Fixture NVDA-046 / NVDA-010 — addon com CLI args + threading + wx.CallAfter
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fluxo_cli_args() -> FluxoReport:
    """
    Gera um addon com suporte a CLI arguments e thread worker UMA VEZ
    para toda a classe TestCliArgs.

    A query cobre NVDA-046 (register/unregister de CLI param) e NVDA-010
    (wx.CallAfter para UI em threads) em um unico addon dedicado.
    """
    return _executar_fluxo_completo(
        addon_name="ModoCLI_e2e",
        query=(
            "Crie um GlobalPlugin NVDA chamado 'ModoCLI' que suporta argumentos de linha de comando "
            "para ativar funcionalidades especiais ao iniciar o NVDA. "
            "O addon DEVE: "
            "1) Definir uma funcao _handle_cli(cliArgument: str) -> bool que verifica se "
            "   cliArgument == '--modo-especial' e retorna True nesse caso, False caso contrario; "
            "2) No __init__ do GlobalPlugin, registrar o handler: "
            "   addonHandler.isCLIParamKnown.register(_handle_cli) "
            "3) No terminate(), desregistrar o handler: "
            "   addonHandler.isCLIParamKnown.unregister(_handle_cli) "
            "   E chamar super().terminate() como ULTIMA linha; "
            "4) Criar uma thread worker (usando threading.Thread) que faz algum processamento periodico; "
            "5) Qualquer atualizacao de UI a partir dessa thread worker DEVE usar wx.CallAfter() — "
            "   por exemplo: wx.CallAfter(ui.message, 'resultado do processamento'); "
            "6) Ter manifest.ini com minimumNVDAVersion=2026.1.1, lastTestedNVDAVersion=2026.1."
        ),
    )


# ---------------------------------------------------------------------------
# Testes NVDA-038 — Speech Dictionaries
# ---------------------------------------------------------------------------


class TestSpeechDict:
    """
    Valida NVDA-038: Speech Dictionaries com arquivo .dic e manifest correto.

    Regra 9: nenhum codigo e executado em nenhuma validacao.
    Todas as asercoes operam sobre strings lidas do disco via helpers.
    """

    def test_nvda038_arquivo_speech_dict_existe(
        self, fluxo_speech_dict: FluxoReport
    ) -> None:
        """
        NVDA-038: O addon deve conter ao menos um arquivo .dic em speechDicts/.

        O NVDA carrega dicionarios de pronuncia de speechDicts/<nome>.dic.
        Sem esse arquivo, nenhuma correcao de pronuncia e aplicada, tornando
        o addon inutil para o seu proposito declarado.
        """
        if not fluxo_speech_dict.success:
            pytest.skip("Pipeline nao concluiu")
        arquivos = _listar_arquivos(fluxo_speech_dict.addon_folder)
        dic_files = [a for a in arquivos if a.startswith("speechDicts/") and a.endswith(".dic")]
        assert dic_files, (
            "NVDA-038: nenhum arquivo .dic encontrado em speechDicts/. "
            f"Arquivos presentes: {arquivos}. "
            "O NVDA le dicionarios de pronuncia de speechDicts/<nome>.dic — "
            "o arquivo e obrigatorio para que as correcoes sejam aplicadas."
        )

    def test_nvda038_linhas_tem_4_campos_tab(
        self, fluxo_speech_dict: FluxoReport
    ) -> None:
        """
        NVDA-038: Cada linha de regra no .dic deve ter exatamente 4 campos
        separados por TAB real (\\t).

        Formato obrigatorio: <pattern>\\t<replacement>\\t<caseSensitive>\\t<type>
        Linhas em branco e linhas comecando com # sao comentarios e sao ignoradas.
        Campos separados por espaco ou outro delimitador causam falha silenciosa
        no parser do NVDA — a regra simplesmente nao e carregada.
        """
        if not fluxo_speech_dict.success:
            pytest.skip("Pipeline nao concluiu")
        conteudo, rel_path = _ler_speech_dict(fluxo_speech_dict.addon_folder)
        if not conteudo:
            pytest.skip("Arquivo .dic nao encontrado — skip de formato")
        linhas_regra: list[str] = []
        for linha in conteudo.splitlines():
            linha_strip = linha.strip()
            if not linha_strip or linha_strip.startswith("#"):
                continue
            linhas_regra.append(linha)
        assert linhas_regra, (
            f"NVDA-038: {rel_path} existe mas nao tem nenhuma linha de regra "
            "(apos remover comentarios e linhas em branco). "
            "Adicione pelo menos 3 regras no formato: "
            "<pattern>\\t<replacement>\\t<caseSensitive>\\t<type>"
        )
        violacoes: list[str] = []
        for i, linha in enumerate(linhas_regra, start=1):
            campos = linha.split("\t")
            if len(campos) != 4:
                violacoes.append(
                    f"Regra {i}: {len(campos)} campo(s) encontrado(s) "
                    f"(esperado 4): {linha[:80]!r}"
                )
        assert not violacoes, (
            f"NVDA-038: linhas em {rel_path} nao tem 4 campos separados por TAB:\n"
            + "\n".join(violacoes)
            + "\nFormato correto: <pattern>\\t<replacement>\\t<caseSensitive>\\t<type>"
        )

    def test_nvda038_manifest_tem_secao_speechdictionaries(
        self, fluxo_speech_dict: FluxoReport
    ) -> None:
        """
        NVDA-038: O manifest.ini deve declarar a secao [speechDictionaries].

        Sem essa secao, o NVDA nao sabe que o addon fornece dicionarios de
        pronuncia e nao os registra no gerenciador de dicionarios, mesmo que
        o arquivo .dic exista em speechDicts/.
        """
        if not fluxo_speech_dict.success:
            pytest.skip("Pipeline nao concluiu")
        manifest_bruto = _ler_arquivo(fluxo_speech_dict.addon_folder, "manifest.ini")
        if not manifest_bruto:
            pytest.skip("manifest.ini nao encontrado — skip de secao")
        # Busca textual case-insensitive: configparser nao lida bem com secoes
        # aninhadas ([[subsecao]]) usadas pelo NVDA, entao verificamos via texto.
        tem_secao = bool(
            re.search(r"\[speechDictionaries\]", manifest_bruto, re.IGNORECASE)
        )
        assert tem_secao, (
            "NVDA-038: manifest.ini nao contem secao [speechDictionaries]. "
            "Declare a secao para que o NVDA registre os dicionarios do addon:\n"
            "[speechDictionaries]\n"
            "[[pronuncia]]\n"
            "displayName = Correcoes de Pronuncia\n"
            "mandatory = false"
        )

    def test_nvda038_campos_casesensitive_e_type_validos(
        self, fluxo_speech_dict: FluxoReport
    ) -> None:
        """
        NVDA-038: No arquivo .dic, o campo caseSensitive deve ser '0' ou '1'
        e o campo type deve ser um inteiro entre 0 e 6 inclusive.

        caseSensitive: 0 = insensivel a maiusculas, 1 = sensivel.
        type: 0=anywhere, 1=regex, 2=whole word, 3=none, 4=word start,
              5=word end, 6=user.
        Valores fora dessa faixa causam comportamento indefinido no parser
        do NVDA e podem impedir o carregamento do dicionario inteiro.
        """
        if not fluxo_speech_dict.success:
            pytest.skip("Pipeline nao concluiu")
        conteudo, rel_path = _ler_speech_dict(fluxo_speech_dict.addon_folder)
        if not conteudo:
            pytest.skip("Arquivo .dic nao encontrado — skip de validacao de campos")
        violacoes: list[str] = []
        for i, linha in enumerate(conteudo.splitlines(), start=1):
            linha_strip = linha.strip()
            if not linha_strip or linha_strip.startswith("#"):
                continue
            campos = linha.split("\t")
            if len(campos) != 4:
                continue  # formato invalido ja coberto por outro teste
            _pattern, _replacement, case_sensitive, tipo = campos
            # Valida caseSensitive
            if case_sensitive not in ("0", "1"):
                violacoes.append(
                    f"Linha {i}: caseSensitive={case_sensitive!r} invalido "
                    "(esperado '0' ou '1')"
                )
            # Valida type
            try:
                tipo_int = int(tipo)
                if not (0 <= tipo_int <= 6):
                    violacoes.append(
                        f"Linha {i}: type={tipo!r} fora do intervalo 0-6"
                    )
            except ValueError:
                violacoes.append(
                    f"Linha {i}: type={tipo!r} nao e inteiro"
                )
        assert not violacoes, (
            f"NVDA-038: campos invalidos em {rel_path}:\n"
            + "\n".join(violacoes)
            + "\ncaseSensitive deve ser '0' ou '1'; type deve ser inteiro 0-6."
        )


# ---------------------------------------------------------------------------
# Testes NVDA-046 / NVDA-010 — CLI Arguments + wx.CallAfter
# ---------------------------------------------------------------------------


class TestCliArgs:
    """
    Valida NVDA-046 (CLI argument handler) e NVDA-010 (wx.CallAfter em threads).

    Regra 9: nenhum codigo e executado em nenhuma validacao.
    Todas as asercoes operam sobre strings lidas do disco via helpers.
    """

    def test_nvda046_register_cli_param_known(
        self, fluxo_cli_args: FluxoReport
    ) -> None:
        """
        NVDA-046: O GlobalPlugin deve registrar um handler via
        addonHandler.isCLIParamKnown.register(handler) no __init__.

        Sem o registro, o NVDA nao chama o handler ao processar argumentos
        de linha de comando e o addon nunca detecta '--modo-especial'.
        O handler deve aceitar cliArgument: str e retornar bool.
        """
        if not fluxo_cli_args.success:
            pytest.skip("Pipeline nao concluiu")
        code = _ler_codigo_completo(fluxo_cli_args.addon_folder)
        assert "isCLIParamKnown" in code, (
            "NVDA-046: isCLIParamKnown nao encontrado no codigo. "
            "Registre o handler de CLI no __init__: "
            "addonHandler.isCLIParamKnown.register(_handle_cli)"
        )
        assert ".register(" in code, (
            "NVDA-046: .register( nao encontrado no codigo. "
            "O handler de CLI deve ser registrado no __init__ via "
            "addonHandler.isCLIParamKnown.register(handler)."
        )

    def test_nvda046_unregister_no_terminate(
        self, fluxo_cli_args: FluxoReport
    ) -> None:
        """
        NVDA-046: O handler registrado via isCLIParamKnown.register deve ser
        desregistrado no terminate() via isCLIParamKnown.unregister(handler).

        Sem o unregister, o handler persiste apos o addon ser descarregado.
        Isso causa erros quando o NVDA tenta chamar um handler de um modulo
        que ja nao esta na memoria, podendo travar a inicializacao do NVDA.
        """
        if not fluxo_cli_args.success:
            pytest.skip("Pipeline nao concluiu")
        code = _ler_codigo_completo(fluxo_cli_args.addon_folder)
        if "isCLIParamKnown" not in code:
            pytest.skip("isCLIParamKnown ausente — skip de unregister")
        assert "unregister(" in code, (
            "NVDA-046: isCLIParamKnown.unregister() nao encontrado no codigo. "
            "Desregistre o handler no terminate(): "
            "addonHandler.isCLIParamKnown.unregister(_handle_cli). "
            "Sem isso, o handler persiste apos o addon ser descarregado e pode "
            "causar erros na proxima inicializacao do NVDA."
        )
        # Verifica que unregister aparece proximo ao terminate para confirmar
        # que o cleanup esta no lugar certo (analise textual — Regra 9).
        tem_unregister_em_terminate = bool(
            re.search(
                r"def terminate\s*\(.*?\).*?unregister\s*\(",
                code,
                re.DOTALL,
            )
        )
        assert tem_unregister_em_terminate, (
            "NVDA-046: unregister() existe no codigo mas nao parece estar "
            "dentro do metodo terminate(). "
            "Mova addonHandler.isCLIParamKnown.unregister(handler) para dentro "
            "de def terminate(self) para garantir cleanup ao descarregar o addon."
        )

    def test_nvda010_wx_callafter_com_thread(
        self, fluxo_cli_args: FluxoReport
    ) -> None:
        """
        NVDA-010: Se o addon usa threading.Thread, qualquer atualizacao de UI
        deve usar wx.CallAfter() — nunca chamar wx diretamente da thread worker.

        O wx (wxPython) nao e thread-safe. Chamar ui.message(), gui.* ou qualquer
        operacao de UI de uma thread secundaria causa race conditions que podem
        travar ou crashar o NVDA sem mensagem de erro clara.
        wx.CallAfter() agenda a chamada para ser executada na thread principal do wx,
        garantindo seguranca em contexto multi-thread.
        """
        if not fluxo_cli_args.success:
            pytest.skip("Pipeline nao concluiu")
        code = _ler_codigo_completo(fluxo_cli_args.addon_folder)
        tem_thread = "threading.Thread" in code or "Thread(" in code
        if not tem_thread:
            pytest.skip("Addon nao usa threading.Thread — skip de wx.CallAfter")
        assert "wx.CallAfter" in code, (
            "NVDA-010: addon usa threading.Thread mas nao encontrou wx.CallAfter() no codigo. "
            "Toda atualizacao de UI a partir de thread worker deve usar wx.CallAfter(): "
            "wx.CallAfter(ui.message, 'mensagem') — nunca chamar ui.message() diretamente "
            "da thread, pois wx nao e thread-safe e pode travar o NVDA."
        )
