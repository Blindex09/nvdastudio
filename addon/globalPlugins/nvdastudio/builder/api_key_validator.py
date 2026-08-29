import re
from dataclasses import dataclass, field

from ..utils.logger import get_logger

MODULE_VERSION = "1.1.0"
_logger = get_logger("api_key_validator")

# ---------------------------------------------------------------------------
# Padroes de API key por provider
# ---------------------------------------------------------------------------

_API_KEY_PATTERNS: list[tuple[str, str, str]] = [
    # (regex, provider, descricao)
    (r'AIza[0-9A-Za-z\-_]{35}', "Google/Gemini", "Google API key (39 chars apos AIza)"),
    (r'sk-[0-9a-zA-Z]{32,}', "OpenAI", "OpenAI secret key (sk-...)"),
    (r'sk-ant-[0-9a-zA-Z\-_]{32,}', "Anthropic", "Anthropic API key (sk-ant-...)"),
    (r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', "UUID", "Possivel UUID como key"),
    (r'[A-Za-z0-9+/]{40,}={0,2}', "Base64", "String Base64 longa (possivel key)"),
]

# ---------------------------------------------------------------------------
# Placeholders — strings que parecem key mas sao placeholders
# ---------------------------------------------------------------------------

_PLACEHOLDER_PATTERNS: list[str] = [
    r'YOUR_API_KEY',
    r'YOUR_KEY',
    r'SUA_CHAVE',
    r'SUA_API_KEY',
    r'COLOQUE_SUA',
    r'INSIRA_SUA',
    r'<.*>',  # <your-key-here>
    r'your[-_]api[-_]key',
    r'your[-_]key',
    r'api[-_]key[-_]here',
    r'placeholder',
    r'changeme',
    r'replace[-_]me',
]

# ---------------------------------------------------------------------------
# Variaveis de ambiente e config — uso correto
# ---------------------------------------------------------------------------

_SAFE_PATTERNS: list[str] = [
    r'os\.environ',
    r'os\.getenv',
    r'config\.conf\[',
    r'get_config',
    r'get_api_key',
    r'\.env',
    r'environ\[',
]

# G3 (2026-08-07): extrai o CONTEUDO de literais de string ('...', "...",
# '''...''' ou \"\"\"...\"\"\") de uma linha -- os padroes de _API_KEY_PATTERNS
# so fazem sentido dentro de um literal de string (uma key real e sempre
# atribuida/passada como string), nunca em codigo Python cru fora de aspas
# (identificadores, caminhos de import, nomes de arquivo em comentarios/
# docstrings). As alternativas triplas vem PRIMEIRO na alternancia -- sem
# isso, a aspa extra de \"\"\"...\"\"\" desloca o pareamento do padrao simples
# de aspa unica e o conteudo do docstring vaza como "literal" (2o bug
# encontrado testando o fix acima). Aproximacao simples (nao trata aspas
# escapadas nem strings triplas multi-linha, ja que audit_code processa
# linha a linha) — suficiente pra eliminar a classe de falso-positivo
# confirmada no teste E2E real.
_STRING_LITERAL_RE = re.compile(
    r'"""(.*?)"""|\'\'\'(.*?)\'\'\'|"([^"]*)"|\'([^\']*)\'',
)


def _extract_string_literals(line: str) -> list[str]:
    literals = []
    for g1, g2, g3, g4 in _STRING_LITERAL_RE.findall(line):
        content = g1 or g2 or g3 or g4
        if content:
            literals.append(content)
    return literals


@dataclass
class ApiKeyViolation:
    """Uma violacao de API key detectada."""
    line_number: int
    line_content: str
    provider: str
    description: str
    severity: str = "high"  # high, medium, low


@dataclass
class ApiKeyAuditResult:
    """Resultado da auditoria de API keys."""
    violations: list[ApiKeyViolation] = field(default_factory=list)
    score_penalty: int = 0
    is_clean: bool = True


class ApiKeyValidator:
    """
    Validador deterministico de API keys no codigo gerado.

    Regra 5: validacao deterministica — nao usa LLM.
    Penalidade: -20 pontos por violacao no score do Critic.
    """

    def audit_code(self, code: str) -> ApiKeyAuditResult:
        """
        Audita um bloco de codigo Python em busca de API keys hardcoded.

        Args:
            code: String com o codigo Python a ser auditado

        Returns:
            ApiKeyAuditResult com violacoes encontradas e penalidade
        """
        violations: list[ApiKeyViolation] = []
        lines = code.split("\n")

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Pula comentarios
            if stripped.startswith("#"):
                continue

            # Verifica se e uso seguro (env var, config.conf)
            if any(re.search(p, stripped, re.IGNORECASE) for p in _SAFE_PATTERNS):
                continue

            # Verifica placeholders
            if any(re.search(p, stripped, re.IGNORECASE) for p in _PLACEHOLDER_PATTERNS):
                continue

            # G3 (2026-08-07): so audita CONTEUDO DENTRO DE LITERAIS DE STRING
            # ('...' ou "..."), nao a linha de codigo inteira. Achado real no
            # teste E2E: o padrao "Base64" (r'[A-Za-z0-9+/]{40,}={0,2}') e tao
            # amplo que batia num caminho de arquivo comum sem pontos
            # (ex: "globalPlugins/AssistenteLeituraGemini/gemini_client"),
            # travando 3 tentativas seguidas de kimi-k2.7-code num addon que
            # em nenhum momento colocou uma chave real hardcoded -- so tinha
            # um comentario/docstring com um caminho relativo longo. Uma key
            # real so faz sentido como literal de string (e o valor sendo
            # atribuido/passado), nunca como codigo Python cru fora de aspas.
            line_violation_found = False
            for candidate in _extract_string_literals(stripped):
                if line_violation_found:
                    break
                for pattern, provider, description in _API_KEY_PATTERNS:
                    match = re.search(pattern, candidate)
                    if match:
                        matched_text = match.group(0)
                        if any(re.search(p, matched_text, re.IGNORECASE) for p in _PLACEHOLDER_PATTERNS):
                            continue
                        # G3: o catch-all "Base64" e um ultimo recurso pra
                        # provedores sem regex dedicado -- sem exigir digito,
                        # bate em qualquer caminho de arquivo/identificador
                        # longo dentro de um docstring/string legitima (ex:
                        # "globalPlugins/AssistenteLeituraGemini/gemini_client",
                        # zero digitos). Chaves/tokens reais sao dados
                        # aleatorios de alta entropia -- na pratica sempre tem
                        # pelo menos 1 digito. Path-like text raramente tem.
                        if provider == "Base64" and not any(c.isdigit() for c in matched_text):
                            continue

                        violations.append(ApiKeyViolation(
                            line_number=i,
                            line_content=stripped[:120],
                            provider=provider,
                            description=description,
                            severity="high",
                        ))
                        line_violation_found = True
                        break  # uma violacao por linha

        penalty = len(violations) * 20
        is_clean = len(violations) == 0

        if violations:
            _logger.warning(
                "[API_KEY] %d violacao(oes) encontrada(s). Penalidade: -%d pontos.",
                len(violations), penalty,
            )
            for v in violations:
                _logger.warning(
                    "  Linha %d: %s (%s)",
                    v.line_number, v.provider, v.line_content[:80],
                )

        return ApiKeyAuditResult(
            violations=violations,
            score_penalty=penalty,
            is_clean=is_clean,
        )

    def audit_blocks(self, blocks: list[dict]) -> ApiKeyAuditResult:
        """
        Audita multiplos blocos de codigo (de extract_code_blocks).

        Args:
            blocks: Lista de blocos {"language": "python", "code": "...", "filename": "..."}

        Returns:
            ApiKeyAuditResult consolidado de todos os blocos
        """
        all_violations: list[ApiKeyViolation] = []
        total_penalty = 0

        for block in blocks:
            if block.get("language") != "python":
                continue
            code = block.get("code", "")
            filename = block.get("filename", "desconhecido")

            result = self.audit_code(code)
            if result.violations:
                _logger.warning(
                    "[API_KEY] Arquivo %s: %d violacao(oes)",
                    filename, len(result.violations),
                )
                all_violations.extend(result.violations)
                total_penalty += result.score_penalty

        return ApiKeyAuditResult(
            violations=all_violations,
            score_penalty=total_penalty,
            is_clean=len(all_violations) == 0,
        )

    def get_fix_instructions(self, violations: list[ApiKeyViolation]) -> str:
        """
        Gera instrucoes de correcao para as violacoes encontradas.

        Returns:
            String com instrucoes claras para o subagente corrigir
        """
        if not violations:
            return ""

        providers = set(v.provider for v in violations)
        lines = [
            "[API_KEY] Chaves de API hardcoded detectadas. CORRIGIR:",
            "",
            "Regras:",
            "- NUNCA coloque chaves de API diretamente no codigo",
            "- Use config.conf['addonIdReal']['apiKey'] para armazenar",
            "- Ou use os.environ.get('NOME_DA_VARIAVEL')",
            "- Crie um SettingsPanel para o usuario configurar a chave",
            "",
            f"Provedores afetados: {', '.join(providers)}",
            "",
            "Exemplo CORRETO:",
            "  api_key = config.conf['meuAddon']['geminiKey']",
            "  client = genai.Client(api_key=api_key)",
            "",
            "Exemplo ERRADO:",
            "  GEMINI_API_KEY = 'AIza...'  # NUNCA faca isso",
        ]
        return "\n".join(lines)


# Instancia global
api_key_validator = ApiKeyValidator()
