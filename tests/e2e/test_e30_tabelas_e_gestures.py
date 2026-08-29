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
    """Concatena todos os .py do addon em uma unica string."""
    resultado: list[str] = []
    for root, _, files in os.walk(addon_folder):
        for f in files:
            if f.endswith(".py"):
                abs_path = os.path.join(root, f)
                with open(abs_path, encoding="utf-8", errors="replace") as fh:
                    resultado.append(fh.read())
    return "\n".join(resultado)


def _listar_arquivos(addon_folder: str) -> list[str]:
    """Lista todos os arquivos dentro do addon_folder com path relativo (forward slash)."""
    resultado: list[str] = []
    for root, _, files in os.walk(addon_folder):
        for f in files:
            abs_path = os.path.join(root, f)
            rel_path = os.path.relpath(abs_path, addon_folder).replace("\\", "/")
            resultado.append(rel_path)
    return resultado


def _ler_arquivo(addon_folder: str, rel_path: str) -> str:
    """Le um arquivo especifico do addon pelo path relativo."""
    abs_path = os.path.join(addon_folder, rel_path.replace("/", os.sep))
    if os.path.isfile(abs_path):
        with open(abs_path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    return ""


def _ler_manifest(addon_folder: str) -> configparser.RawConfigParser:
    """
    Le o manifest.ini do addon. Retorna parser vazio se nao encontrar.

    Atencao: manifest.ini pode ter secoes aninhadas como [[nome]] dentro de [secao].
    Usa configparser.RawConfigParser com OPTIONXFORM = str para preservar case.
    Para verificar presenca de [brailleTables] e campos como contracted/output/input,
    use busca em texto puro no conteudo bruto — ver _ler_manifest_raw().
    """
    parser = configparser.RawConfigParser()
    parser.optionxform = str  # type: ignore[assignment]
    path = os.path.join(addon_folder, "manifest.ini")
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as fh:
            try:
                parser.read_file(fh)
            except configparser.Error:
                pass  # manifest malformado — retorna parser parcial
    return parser


def _ler_manifest_raw(addon_folder: str) -> str:
    """Retorna o conteudo bruto do manifest.ini como string."""
    return _ler_arquivo(addon_folder, "manifest.ini")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fluxo_braille_table() -> FluxoReport:
    """
    Gera um addon NVDA com Braille Translation Table customizada UMA VEZ para todo o modulo.

    A query cobre explicitamente:
      - NVDA-043: arquivo .utb em brailleTables/
      - NVDA-043: secao [brailleTables] no manifest.ini com displayName, contracted, output, input
      - GlobalPlugin basico com __init__ e terminate()
      - manifest.ini com minimumNVDAVersion=2026.1.1
    """
    return _executar_fluxo_completo(
        addon_name="TabelaBraille_e2e",
        query=(
            "Crie um addon NVDA chamado 'TabelaBraille' que fornece uma tabela braille customizada "
            "para Português Brasileiro (grau 2 contraído). "
            "O addon DEVE: "
            "1) Criar o arquivo brailleTables/pt-br-grade2.utb com conteúdo mínimo de tabela liblouis "
            "   (pode ser placeholder com comentário explicativo se a tabela completa for muito grande); "
            "2) Declarar no manifest.ini a seção: "
            "   [brailleTables] "
            "   [[pt-br-grade2.utb]] "
            "   displayName = Português Brasileiro Grau 2 "
            "   contracted = True "
            "   output = True "
            "   input = False "
            "3) Implementar GlobalPlugin básico com __init__ e terminate(); "
            "4) Ter manifest.ini com minimumNVDAVersion=2026.1.1, lastTestedNVDAVersion=2026.1."
        ),
    )


@pytest.fixture(scope="module")
def fluxo_symbol_dict() -> FluxoReport:
    """
    Gera um addon NVDA com Symbol Dictionary de letras gregas UMA VEZ para todo o modulo.

    A query cobre explicitamente:
      - NVDA-044: arquivo locale/en/symbols-greek.dic com secao symbols: e entradas tab-separadas
      - NVDA-044: secao [symbolDictionaries] no manifest.ini com displayName e mandatory
      - GlobalPlugin basico com __init__ e terminate()
      - manifest.ini com minimumNVDAVersion=2026.1.1
    """
    return _executar_fluxo_completo(
        addon_name="SimbolosGrecos_e2e",
        query=(
            "Crie um addon NVDA chamado 'SimbolosGrecos' que adiciona pronuncia de letras gregas "
            "ao NVDA para usuários de matematica e ciencia. "
            "O addon DEVE: "
            "1) Criar arquivo locale/en/symbols-greek.dic com: "
            "   a) Secao 'symbols:' (linha com apenas 'symbols:' seguida das entradas) "
            "   b) Pelo menos 3 entradas no formato: <simbolo>\\t<pronuncia>\\t<nivel>\\t[preserve] "
            "      Exemplos: α\\talpha\\tall\\t  |  β\\tbeta\\tall\\t  |  π\\tpi\\tall\\t "
            "   c) Opcionalmente secao 'complexSymbols:' antes de 'symbols:' "
            "2) Declarar no manifest.ini: "
            "   [symbolDictionaries] "
            "   [[greek]] "
            "   displayName = Greek Symbols "
            "   mandatory = false "
            "3) Implementar GlobalPlugin básico com __init__ e terminate(); "
            "4) Ter manifest.ini com minimumNVDAVersion=2026.1.1, lastTestedNVDAVersion=2026.1."
        ),
    )


@pytest.fixture(scope="module")
def fluxo_gesture_remap() -> FluxoReport:
    """
    Gera um addon NVDA com Locale Gesture Remapping para o layout italiano UMA VEZ.

    A query cobre explicitamente:
      - NVDA-045: arquivo locale/it/gestures.ini com secoes [module.ClassName]
      - NVDA-045: bindings no formato scriptName = gesture
      - GlobalPlugin basico com __init__ e terminate()
      - manifest.ini com minimumNVDAVersion=2026.1.1
    """
    return _executar_fluxo_completo(
        addon_name="GesturesItalia_e2e",
        query=(
            "Crie um addon NVDA chamado 'GesturesItalia' que remapeia gestos de mouse para "
            "o layout de teclado italiano (laptop). "
            "O addon DEVE: "
            "1) Criar arquivo locale/it/gestures.ini (para layout italiano) com: "
            "   [globalCommands.GlobalCommands] "
            "   leftMouseClick = kb(laptop):NVDA+è "
            "   rightMouseClick = kb(laptop):NVDA+plus "
            "   Opcional: incluir um segundo grupo de remapeamento para outro modulo; "
            "2) Implementar GlobalPlugin básico com __init__ e terminate(); "
            "3) Ter manifest.ini com minimumNVDAVersion=2026.1.1, lastTestedNVDAVersion=2026.1."
        ),
    )


# ---------------------------------------------------------------------------
# Classe de testes: NVDA-043 — Braille Translation Tables
# ---------------------------------------------------------------------------


class TestBrailleTable:
    """
    Valida regras de Braille Translation Tables contra o addon gerado pela IA.

    Testes condicionais: pulam se o pipeline nao concluiu ou se os artefatos
    esperados nao foram gerados pelo modelo.

    Regra 9: nenhum codigo gerado e executado em nenhuma validacao.

    Regras cobertas:
      - NVDA-043: arquivo .utb em brailleTables/
      - NVDA-043: secao [brailleTables] no manifest.ini
      - NVDA-043: campos obrigatorios displayName, contracted, output, input
    """

    # ------------------------------------------------------------------
    # NVDA-043: arquivo .utb existe em brailleTables/
    # ------------------------------------------------------------------

    def test_nvda043_arquivo_utb_existe(
        self, fluxo_braille_table: FluxoReport
    ) -> None:
        """
        NVDA-043: O addon deve conter pelo menos um arquivo .utb em brailleTables/.

        O NVDA carrega tabelas de traducao braille exclusivamente de arquivos .utb
        na pasta brailleTables/ dentro do addon. Sem o arquivo a tabela nunca sera
        disponibilizada ao usuario, mesmo que o manifest.ini a declare corretamente.

        Ref: nvda_developer_guide_2025.html — secao Braille Translation Tables.
        """
        if not fluxo_braille_table.success:
            pytest.skip("Pipeline nao concluiu")
        arquivos = _listar_arquivos(fluxo_braille_table.addon_folder)
        utb_files = [
            a for a in arquivos
            if a.startswith("brailleTables/") and a.endswith(".utb")
        ]
        assert utb_files, (
            "NVDA-043: Nenhum arquivo .utb encontrado em brailleTables/. "
            "O NVDA carrega tabelas liblouis de brailleTables/<nome>.utb. "
            "Crie o arquivo e declare-o na secao [brailleTables] do manifest.ini. "
            f"Arquivos encontrados: {arquivos[:15]}"
        )

    # ------------------------------------------------------------------
    # NVDA-043: manifest.ini tem secao [brailleTables]
    # ------------------------------------------------------------------

    def test_nvda043_manifest_tem_secao_brailletables(
        self, fluxo_braille_table: FluxoReport
    ) -> None:
        """
        NVDA-043: O manifest.ini deve conter a secao [brailleTables].

        O NVDA descobre tabelas braille de addons pela secao [brailleTables] do
        manifest.ini. Sem ela o NVDA nao registra a tabela, mesmo que o .utb exista.

        Usa busca em texto puro porque configparser nao lida corretamente com
        secoes aninhadas do tipo [[nome]] dentro de [secao].

        Ref: nvda_developer_guide_2025.html — secao Braille Translation Tables.
        """
        if not fluxo_braille_table.success:
            pytest.skip("Pipeline nao concluiu")
        manifest_raw = _ler_manifest_raw(fluxo_braille_table.addon_folder)
        if not manifest_raw:
            pytest.skip("manifest.ini nao encontrado")
        assert "[brailleTables]" in manifest_raw, (
            "NVDA-043: manifest.ini sem secao [brailleTables]. "
            "Adicione a secao [brailleTables] com pelo menos uma subsecao [[nome.utb]] "
            "contendo displayName, contracted, output e input. "
            "Ref: nvda_developer_guide_2025.html — secao Braille Translation Tables."
        )

    # ------------------------------------------------------------------
    # NVDA-043: campos obrigatorios na subseção da tabela
    # ------------------------------------------------------------------

    def test_nvda043_campos_obrigatorios_na_table(
        self, fluxo_braille_table: FluxoReport
    ) -> None:
        """
        NVDA-043: A subsecao da tabela braille deve conter displayName, contracted,
        output e input.

        Cada entrada em [brailleTables] precisa declarar:
          - displayName: nome legivel pelo usuario exibido nas configuracoes NVDA
          - contracted: True/False — indica se e traducao contraida (grau 2)
          - output: True/False — tabela disponivel para saida braille
          - input: True/False — tabela disponivel para entrada via teclado braille

        Usa busca em texto puro para tolerar o formato de secoes aninhadas [[nome]].

        Ref: nvda_developer_guide_2025.html — secao Braille Translation Tables.
        """
        if not fluxo_braille_table.success:
            pytest.skip("Pipeline nao concluiu")
        manifest_raw = _ler_manifest_raw(fluxo_braille_table.addon_folder)
        if not manifest_raw:
            pytest.skip("manifest.ini nao encontrado")
        if "[brailleTables]" not in manifest_raw:
            pytest.skip("Secao [brailleTables] ausente — coberta por test_nvda043_manifest_tem_secao_brailletables")

        # Extrai o bloco a partir de [brailleTables] para restringir a busca
        idx_secao = manifest_raw.find("[brailleTables]")
        bloco = manifest_raw[idx_secao:]

        campos_obrigatorios = {
            "displayName": re.compile(r"displayName\s*=", re.IGNORECASE),
            "contracted": re.compile(r"contracted\s*=", re.IGNORECASE),
            "output": re.compile(r"\boutput\s*=", re.IGNORECASE),
            "input": re.compile(r"\binput\s*=", re.IGNORECASE),
        }
        for campo, pattern in campos_obrigatorios.items():
            assert pattern.search(bloco), (
                f"NVDA-043: Campo '{campo}' ausente na subsecao [brailleTables]. "
                f"Cada entrada de tabela braille deve declarar '{campo} = <valor>'. "
                "Campos obrigatorios: displayName, contracted, output, input. "
                "Ref: nvda_developer_guide_2025.html — secao Braille Translation Tables."
            )


# ---------------------------------------------------------------------------
# Classe de testes: NVDA-044 — Symbol Dictionaries
# ---------------------------------------------------------------------------


class TestSymbolDict:
    """
    Valida regras de Symbol Dictionaries contra o addon gerado pela IA.

    Testes condicionais: pulam se o pipeline nao concluiu ou se os artefatos
    esperados nao foram gerados pelo modelo.

    Regra 9: nenhum codigo gerado e executado em nenhuma validacao.

    Regras cobertas:
      - NVDA-044: arquivo locale/<lang>/symbols-*.dic existe
      - NVDA-044: arquivo tem secao 'symbols:'
      - NVDA-044: manifest.ini tem secao [symbolDictionaries]
      - NVDA-044: entradas no .dic tem formato tab-separado correto
    """

    # ------------------------------------------------------------------
    # NVDA-044: arquivo symbols-*.dic existe em locale/<lang>/
    # ------------------------------------------------------------------

    def test_nvda044_arquivo_symbol_dict_existe(
        self, fluxo_symbol_dict: FluxoReport
    ) -> None:
        """
        NVDA-044: O addon deve conter pelo menos um arquivo symbols-*.dic em locale/<lang>/.

        O NVDA carrega dicionarios de simbolos de locale/<lang>/symbols-<nome>.dic.
        Sem o arquivo a pronuncia customizada nunca e aplicada ao usuario.

        Ref: nvda_developer_guide_2025.html — secao Symbol Pronunciation.
        """
        if not fluxo_symbol_dict.success:
            pytest.skip("Pipeline nao concluiu")
        arquivos = _listar_arquivos(fluxo_symbol_dict.addon_folder)
        dic_files = [
            a for a in arquivos
            if re.match(r"locale/[^/]+/symbols-[^/]+\.dic$", a)
        ]
        assert dic_files, (
            "NVDA-044: Nenhum arquivo symbols-*.dic encontrado em locale/<lang>/. "
            "O NVDA carrega dicionarios de locale/<lang>/symbols-<nome>.dic. "
            "Crie o arquivo e declare-o na secao [symbolDictionaries] do manifest.ini. "
            f"Arquivos encontrados: {arquivos[:15]}"
        )

    # ------------------------------------------------------------------
    # NVDA-044: arquivo .dic tem linha 'symbols:'
    # ------------------------------------------------------------------

    def test_nvda044_tem_secao_symbols(
        self, fluxo_symbol_dict: FluxoReport
    ) -> None:
        """
        NVDA-044: O arquivo .dic deve conter a linha 'symbols:' como cabecalho de secao.

        O NVDA identifica as entradas de simbolos pela secao 'symbols:' no arquivo .dic.
        Sem essa linha o parser do NVDA nao reconhece nenhuma entrada do dicionario.

        Opcionalmente o arquivo pode ter 'complexSymbols:' antes de 'symbols:'.

        Ref: nvda_developer_guide_2025.html — secao Symbol Pronunciation.
        """
        if not fluxo_symbol_dict.success:
            pytest.skip("Pipeline nao concluiu")
        arquivos = _listar_arquivos(fluxo_symbol_dict.addon_folder)
        dic_files = [
            a for a in arquivos
            if re.match(r"locale/[^/]+/symbols-[^/]+\.dic$", a)
        ]
        if not dic_files:
            pytest.skip("Arquivo symbols-*.dic ausente — coberto por test_nvda044_arquivo_symbol_dict_existe")
        conteudo = _ler_arquivo(fluxo_symbol_dict.addon_folder, dic_files[0])
        # Verifica presenca da linha 'symbols:' (com ou sem espacos ao redor)
        linhas = [line.strip() for line in conteudo.splitlines()]
        assert "symbols:" in linhas, (
            "NVDA-044: Arquivo .dic sem linha 'symbols:'. "
            "O NVDA identifica o inicio das entradas de simbolo pela linha 'symbols:'. "
            "Adicione a linha exata 'symbols:' (sem espacos extras) seguida pelas entradas. "
            f"Arquivo verificado: {dic_files[0]}. "
            "Ref: nvda_developer_guide_2025.html — secao Symbol Pronunciation."
        )

    # ------------------------------------------------------------------
    # NVDA-044: manifest.ini tem secao [symbolDictionaries]
    # ------------------------------------------------------------------

    def test_nvda044_manifest_tem_secao_symboldictionaries(
        self, fluxo_symbol_dict: FluxoReport
    ) -> None:
        """
        NVDA-044: O manifest.ini deve conter a secao [symbolDictionaries].

        O NVDA descobre dicionarios de simbolos de addons pela secao [symbolDictionaries]
        do manifest.ini. Sem ela o NVDA nao registra o dicionario, mesmo que o .dic exista.

        Ref: nvda_developer_guide_2025.html — secao Symbol Pronunciation.
        """
        if not fluxo_symbol_dict.success:
            pytest.skip("Pipeline nao concluiu")
        manifest_raw = _ler_manifest_raw(fluxo_symbol_dict.addon_folder)
        if not manifest_raw:
            pytest.skip("manifest.ini nao encontrado")
        assert "[symbolDictionaries]" in manifest_raw, (
            "NVDA-044: manifest.ini sem secao [symbolDictionaries]. "
            "Adicione a secao [symbolDictionaries] com pelo menos uma subsecao [[nome]] "
            "contendo displayName e mandatory. "
            "Ref: nvda_developer_guide_2025.html — secao Symbol Pronunciation."
        )

    # ------------------------------------------------------------------
    # NVDA-044: entradas do .dic tem formato tab-separado correto
    # ------------------------------------------------------------------

    def test_nvda044_entradas_tem_formato_correto(
        self, fluxo_symbol_dict: FluxoReport
    ) -> None:
        """
        NVDA-044: As entradas no arquivo .dic devem ter pelo menos 2 campos tab-separados.

        Cada entrada de simbolo deve seguir o formato:
          <simbolo>\\t<pronuncia>\\t<nivel>\\t[preserve]

        O NVDA espera pelo menos simbolo e pronuncia separados por tabulacao.
        Entradas sem tab-separacao sao ignoradas pelo parser do NVDA.

        Ref: nvda_developer_guide_2025.html — secao Symbol Pronunciation.
        """
        if not fluxo_symbol_dict.success:
            pytest.skip("Pipeline nao concluiu")
        arquivos = _listar_arquivos(fluxo_symbol_dict.addon_folder)
        dic_files = [
            a for a in arquivos
            if re.match(r"locale/[^/]+/symbols-[^/]+\.dic$", a)
        ]
        if not dic_files:
            pytest.skip("Arquivo symbols-*.dic ausente — coberto por test_nvda044_arquivo_symbol_dict_existe")
        conteudo = _ler_arquivo(fluxo_symbol_dict.addon_folder, dic_files[0])

        # Encontra linhas apos 'symbols:' que nao sao vazias nem comentarios
        dentro_symbols = False
        entradas_com_tab: list[str] = []
        for linha in conteudo.splitlines():
            stripped = linha.strip()
            if stripped == "symbols:":
                dentro_symbols = True
                continue
            if dentro_symbols:
                if not stripped or stripped.startswith("#"):
                    continue
                # Outra secao encerra symbols:
                if stripped.endswith(":") and "\t" not in stripped:
                    break
                if "\t" in linha:
                    partes = linha.split("\t")
                    if len(partes) >= 2:
                        entradas_com_tab.append(stripped)

        assert entradas_com_tab, (
            "NVDA-044: Nenhuma entrada com formato tab-separado encontrada na secao 'symbols:'. "
            "Cada entrada deve seguir: <simbolo>\\t<pronuncia>\\t<nivel>\\t[preserve]. "
            "O NVDA exige pelo menos simbolo e pronuncia separados por tabulacao (\\t). "
            f"Arquivo verificado: {dic_files[0]}. "
            "Ref: nvda_developer_guide_2025.html — secao Symbol Pronunciation."
        )


# ---------------------------------------------------------------------------
# Classe de testes: NVDA-045 — Locale Gesture Remapping
# ---------------------------------------------------------------------------


class TestGestureRemap:
    """
    Valida regras de Locale Gesture Remapping contra o addon gerado pela IA.

    Testes condicionais: pulam se o pipeline nao concluiu ou se os artefatos
    esperados nao foram gerados pelo modelo.

    Regra 9: nenhum codigo gerado e executado em nenhuma validacao.

    Regras cobertas:
      - NVDA-045: arquivo locale/<lang>/gestures.ini existe
      - NVDA-045: gestures.ini tem pelo menos uma secao [module.ClassName]
      - NVDA-045: gestures.ini tem pelo menos um binding 'script = gesture'
    """

    # ------------------------------------------------------------------
    # NVDA-045: arquivo gestures.ini existe em locale/<lang>/
    # ------------------------------------------------------------------

    def test_nvda045_arquivo_gestures_ini_existe(
        self, fluxo_gesture_remap: FluxoReport
    ) -> None:
        """
        NVDA-045: O addon deve conter pelo menos um arquivo gestures.ini em locale/<lang>/.

        O NVDA carrega remapeamentos de gestos de locale/<lang>/gestures.ini.
        Sem o arquivo os gestos personalizados para o locale nao sao aplicados.

        Ref: nvda_developer_guide_2025.html — secao Locale-Specific Gesture Remapping.
        """
        if not fluxo_gesture_remap.success:
            pytest.skip("Pipeline nao concluiu")
        arquivos = _listar_arquivos(fluxo_gesture_remap.addon_folder)
        gestures_files = [
            a for a in arquivos
            if re.match(r"locale/[^/]+/gestures\.ini$", a)
        ]
        assert gestures_files, (
            "NVDA-045: Nenhum arquivo gestures.ini encontrado em locale/<lang>/. "
            "O NVDA carrega remapeamentos de gestos de locale/<lang>/gestures.ini. "
            "Crie o arquivo com secoes [module.ClassName] e bindings scriptName = gesture. "
            f"Arquivos encontrados: {arquivos[:15]}"
        )

    # ------------------------------------------------------------------
    # NVDA-045: gestures.ini tem pelo menos uma secao [module.ClassName]
    # ------------------------------------------------------------------

    def test_nvda045_tem_secao_de_modulo(
        self, fluxo_gesture_remap: FluxoReport
    ) -> None:
        """
        NVDA-045: O arquivo gestures.ini deve ter pelo menos uma secao [module.ClassName].

        Cada secao agrupa os bindings de um modulo/classe NVDA especifico.
        O formato e [module.ClassName] — ex: [globalCommands.GlobalCommands].

        Sem secoes validas o parser do NVDA ignora todo o arquivo.

        Ref: nvda_developer_guide_2025.html — secao Locale-Specific Gesture Remapping.
        """
        if not fluxo_gesture_remap.success:
            pytest.skip("Pipeline nao concluiu")
        arquivos = _listar_arquivos(fluxo_gesture_remap.addon_folder)
        gestures_files = [
            a for a in arquivos
            if re.match(r"locale/[^/]+/gestures\.ini$", a)
        ]
        if not gestures_files:
            pytest.skip("gestures.ini ausente — coberto por test_nvda045_arquivo_gestures_ini_existe")
        conteudo = _ler_arquivo(fluxo_gesture_remap.addon_folder, gestures_files[0])
        # Secao valida: [module.ClassName] — contem pelo menos um ponto entre colchetes
        secoes_validas = re.findall(r"^\[(\w+\.\w+(?:\.\w+)*)\]", conteudo, re.MULTILINE)
        assert secoes_validas, (
            "NVDA-045: gestures.ini sem nenhuma secao [module.ClassName]. "
            "Cada secao deve seguir o formato [module.ClassName] — ex: [globalCommands.GlobalCommands]. "
            "Sem secoes validas o NVDA ignora o arquivo de remapeamento. "
            f"Arquivo verificado: {gestures_files[0]}. "
            "Ref: nvda_developer_guide_2025.html — secao Locale-Specific Gesture Remapping."
        )

    # ------------------------------------------------------------------
    # NVDA-045: gestures.ini tem pelo menos um binding 'script = gesture'
    # ------------------------------------------------------------------

    def test_nvda045_tem_binding_de_gesto(
        self, fluxo_gesture_remap: FluxoReport
    ) -> None:
        """
        NVDA-045: O arquivo gestures.ini deve ter pelo menos um binding 'scriptName = gesture'.

        Cada linha de binding mapeia um nome de script a um gesto de entrada.
        O formato e: scriptName = kb:tecla  ou  scriptName = kb(laptop):NVDA+tecla.

        Sem bindings o arquivo e estruturalmente valido mas funcionalmente vazio.

        Ref: nvda_developer_guide_2025.html — secao Locale-Specific Gesture Remapping.
        """
        if not fluxo_gesture_remap.success:
            pytest.skip("Pipeline nao concluiu")
        arquivos = _listar_arquivos(fluxo_gesture_remap.addon_folder)
        gestures_files = [
            a for a in arquivos
            if re.match(r"locale/[^/]+/gestures\.ini$", a)
        ]
        if not gestures_files:
            pytest.skip("gestures.ini ausente — coberto por test_nvda045_arquivo_gestures_ini_existe")
        conteudo = _ler_arquivo(fluxo_gesture_remap.addon_folder, gestures_files[0])
        # Binding valido: linha com '=' fora de secao que contem 'kb' no valor
        # Ex: leftMouseClick = kb(laptop):NVDA+è
        bindings = re.findall(
            r"^\s*(\w+)\s*=\s*(kb(?:\([^)]+\))?:[^\s]+)",
            conteudo,
            re.MULTILINE,
        )
        assert bindings, (
            "NVDA-045: gestures.ini sem nenhum binding 'scriptName = kb:gesto'. "
            "Cada binding deve ter o formato: scriptName = kb:tecla "
            "ou scriptName = kb(laptop):NVDA+tecla para layouts especificos. "
            "Ex: leftMouseClick = kb(laptop):NVDA+è "
            f"Arquivo verificado: {gestures_files[0]}. "
            "Ref: nvda_developer_guide_2025.html — secao Locale-Specific Gesture Remapping."
        )

