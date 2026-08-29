from nvdastudio.builder.api_key_validator import (
    ApiKeyValidator, api_key_validator, MODULE_VERSION,
)

# Fixture sintetica com o FORMATO de uma chave Google/Gemini (AIza + 35 chars),
# usada apenas para exercitar o detector. Segue a mesma convencao dos demais
# fixtures deste arquivo ("a"*40 para OpenAI, "b"*40 para Anthropic): nao e, e
# nunca deve ser, uma chave real. Auditoria 2026-08-29: o valor anterior tinha
# entropia compativel com a de uma chave real e foi substituido por precaucao.
FAKE_GEMINI_KEY = "AIza" + "S" * 35


class TestModuleVersao:
    def test_versao_e_1_1_0(self):
        assert MODULE_VERSION == "1.1.0"


class TestDeteccaoDeKeysReais:
    """Uma key real hardcoded como string literal deve continuar sendo detectada."""

    def setup_method(self):
        self.v = ApiKeyValidator()

    def test_detecta_key_gemini_google(self):
        code = 'GEMINI_API_KEY = "' + FAKE_GEMINI_KEY + '"'
        result = self.v.audit_code(code)
        assert not result.is_clean
        assert result.violations[0].provider == "Google/Gemini"

    def test_detecta_key_openai(self):
        code = 'client = OpenAI(api_key="sk-' + "a" * 40 + '")'
        result = self.v.audit_code(code)
        assert not result.is_clean
        assert result.violations[0].provider == "OpenAI"

    def test_detecta_key_anthropic(self):
        code = 'ANTHROPIC_KEY = "sk-ant-' + "b" * 40 + '"'
        result = self.v.audit_code(code)
        assert not result.is_clean
        assert result.violations[0].provider == "Anthropic"

    def test_detecta_base64_dentro_de_string_literal(self):
        """Uma string Base64 longa QUANDO esta dentro de um literal de
        string continua sendo suspeita e deve ser detectada."""
        code = 'SECRET_TOKEN = "' + "aB3dE7fG9hJ1kL2mN4oP5qR6sT8uV0wX" * 2 + '=="'
        result = self.v.audit_code(code)
        assert not result.is_clean
        assert result.violations[0].provider == "Base64"

    def test_penalidade_e_20_por_violacao(self):
        code = 'GEMINI_API_KEY = "' + FAKE_GEMINI_KEY + '"'
        result = self.v.audit_code(code)
        assert result.score_penalty == 20

    def test_multiplas_violacoes_somam_penalidade(self):
        code = (
            'GEMINI_API_KEY = "' + FAKE_GEMINI_KEY + '"\n'
            'OPENAI_KEY = "sk-' + "c" * 40 + '"'
        )
        result = self.v.audit_code(code)
        assert len(result.violations) == 2
        assert result.score_penalty == 40


class TestFalsoPositivoCaminhoDeArquivo:
    """Regressao do bug real 2026-08-07: caminhos/identificadores longos
    FORA de literais de string nao devem disparar o padrao Base64."""

    def setup_method(self):
        self.v = ApiKeyValidator()

    def test_caminho_de_arquivo_em_comentario_nao_dispara(self):
        code = "# Ver globalPlugins/AssistenteLeituraGemini/gemini_client para detalhes"
        result = self.v.audit_code(code)
        assert result.is_clean

    def test_caminho_de_arquivo_em_docstring_nao_dispara(self):
        code = '"""Modulo em globalPlugins/AssistenteLeituraGemini/gemini_client/helpers."""'
        result = self.v.audit_code(code)
        assert result.is_clean

    def test_import_com_caminho_longo_nao_dispara(self):
        code = "from globalPlugins.AssistenteLeituraGemini.gemini_client import GeminiClient"
        result = self.v.audit_code(code)
        assert result.is_clean

    def test_nome_de_funcao_longo_fora_de_string_nao_dispara(self):
        code = "def super_long_function_name_that_exceeds_forty_characters_easily():"
        result = self.v.audit_code(code)
        assert result.is_clean

    def test_base64_sem_digito_nao_dispara_mesmo_dentro_de_string(self):
        """Regra explicita: o catch-all Base64 exige pelo menos 1 digito no
        match -- path-like text (so letras/underscore/slash) nunca dispara,
        mesmo estando dentro de um literal de string valido."""
        code = 'DOC_PATH = "globalPlugins/AssistenteLeituraGemini/gemini/helpers"'
        result = self.v.audit_code(code)
        assert result.is_clean

    def test_base64_com_digito_dispara_normalmente(self):
        """Contraste direto do teste acima: a mesma string, com 1 digito
        adicionado, volta a disparar -- prova que a exigencia de digito e o
        fator decisivo, nao algum outro efeito colateral do fix."""
        code = 'DOC_PATH = "globalPlugins/AssistenteLeituraGemini2/gemini/helpers"'
        result = self.v.audit_code(code)
        assert not result.is_clean

    def test_exemplo_real_do_bug_e2e(self):
        """Reproducao proxima do que provavelmente disparou o falso
        positivo real: um comentario com caminho relativo sem pontos."""
        code = (
            "class GeminiClient:\n"
            "\t# Wrapper em globalPlugins/AssistenteLeituraGemini/gemini_client para chamadas ao Gemini\n"
            "\tdef __init__(self, api_key):\n"
            "\t\tself._api_key = api_key\n"
        )
        result = self.v.audit_code(code)
        assert result.is_clean, f"Falso positivo reproduzido: {result.violations}"


class TestUsoSeguroNaoDisparaViolacao:
    def setup_method(self):
        self.v = ApiKeyValidator()

    def test_config_conf_nao_dispara(self):
        code = 'api_key = config.conf["assistenteLeituraGemini"]["geminiApiKey"]'
        result = self.v.audit_code(code)
        assert result.is_clean

    def test_os_environ_nao_dispara(self):
        code = 'api_key = os.environ.get("GEMINI_API_KEY")'
        result = self.v.audit_code(code)
        assert result.is_clean

    def test_get_api_key_helper_nao_dispara(self):
        code = "api_key = get_api_key('gemini')"
        result = self.v.audit_code(code)
        assert result.is_clean


class TestPlaceholdersNaoDisparam:
    def setup_method(self):
        self.v = ApiKeyValidator()

    def test_your_api_key_nao_dispara(self):
        code = 'GEMINI_API_KEY = "YOUR_API_KEY"'
        result = self.v.audit_code(code)
        assert result.is_clean

    def test_sua_chave_nao_dispara(self):
        code = 'chave = "SUA_CHAVE_AQUI"'
        result = self.v.audit_code(code)
        assert result.is_clean

    def test_angle_bracket_placeholder_nao_dispara(self):
        code = 'api_key = "<sua-chave-aqui>"'
        result = self.v.audit_code(code)
        assert result.is_clean


class TestComentariosIgnorados:
    def setup_method(self):
        self.v = ApiKeyValidator()

    def test_linha_de_comentario_com_key_nao_dispara(self):
        code = '# exemplo: GEMINI_API_KEY = "' + FAKE_GEMINI_KEY + '"'
        result = self.v.audit_code(code)
        assert result.is_clean


class TestAuditBlocks:
    def setup_method(self):
        self.v = ApiKeyValidator()

    def test_ignora_blocos_nao_python(self):
        blocks = [
            {"language": "ini", "filename": "manifest.ini",
             "code": 'key = "' + FAKE_GEMINI_KEY + '"'},
        ]
        result = self.v.audit_blocks(blocks)
        assert result.is_clean

    def test_audita_blocos_python_e_consolida(self):
        blocks = [
            {"language": "python", "filename": "a.py",
             "code": 'K1 = "' + FAKE_GEMINI_KEY + '"'},
            {"language": "python", "filename": "b.py",
             "code": 'K2 = "sk-' + "d" * 40 + '"'},
        ]
        result = self.v.audit_blocks(blocks)
        assert len(result.violations) == 2
        assert result.score_penalty == 40


class TestGetFixInstructions:
    def setup_method(self):
        self.v = ApiKeyValidator()

    def test_sem_violacoes_retorna_vazio(self):
        assert self.v.get_fix_instructions([]) == ""

    def test_com_violacoes_menciona_config_conf(self):
        code = 'GEMINI_API_KEY = "' + FAKE_GEMINI_KEY + '"'
        result = self.v.audit_code(code)
        fix = self.v.get_fix_instructions(result.violations)
        assert "config.conf" in fix
        assert "Google/Gemini" in fix


class TestInstanciaGlobal:
    def test_api_key_validator_e_instancia_de_apikeyvalidator(self):
        assert isinstance(api_key_validator, ApiKeyValidator)
