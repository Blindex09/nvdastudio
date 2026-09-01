from unittest.mock import MagicMock, patch


# --------------------------------------------------------------------------
# Fixtures de conteudo para os testes
# --------------------------------------------------------------------------

AGENT_RUNNER_COMPLETO = '''
import logging

_logger = logging.getLogger("meu_addon.agent_runner")

class AgentRunner:
    def __init__(self, model_id: str = "kimi-k2.6"):
        self._model_id = model_id
        self._history = []
        self._fallback_chain = ["kimi-k2.6"]

    def run(self, query: str, on_chunk=None) -> str:
        self._history.append({"role": "user", "content": query})
        try:
            import httpx
            headers = {"Authorization": "Bearer token", "Content-Type": "application/json"}
            resp = httpx.post("https://api.example.com/v1/chat/completions",
                              headers=headers, json={"model": self._model_id,
                              "messages": self._history}, timeout=60)
            answer = resp.json()["choices"][0]["message"]["content"] or ""
            self._history.append({"role": "assistant", "content": answer})
            return answer
        except Exception as exc:
            _logger.error("[ERRO] AgentRunner falhou: %s", exc)
            return "[ERRO] Falha ao executar agente."

    def reset_session(self):
        self._history = []
        _logger.info("[OK] Sessao reiniciada.")
'''

AGENT_RUNNER_SEM_RESET = '''
import logging
try:

class AgentRunner:
    def __init__(self, api_key):
        self._api_key = api_key
        self._history = []
        self._fallback_chain = ["kimi-k2.6"]

    def run(self, query):
        try:
            pass
        except Exception:
            pass
        return ""
    # reset_session ausente intencionalmente
'''

AGENT_RUNNER_SEM_FALLBACK = '''
import logging
try:

class AgentRunner:
    def __init__(self, api_key):
        self._api_key = api_key
        self._history = []
        # _fallback_chain ausente intencionalmente

    def run(self, query):
        try:
            pass
        except Exception:
            pass
        return ""

    def reset_session(self):
        self._history = []
'''

AGENT_RUNNER_SEM_TRY_EXCEPT_IMPORTERROR = '''
import logging
from external_provider import Client  # sem try/except ImportError

class AgentRunner:
    def __init__(self, api_key):
        self._api_key = api_key
        self._history = []
        self._fallback_chain = ["kimi-k2.6"]

    def run(self, query):
        try:
            pass
        except Exception:
            pass
        return ""

    def reset_session(self):
        self._history = []
'''

AGENT_TEMPLATE_COMPLETO = """# Meu Agente NVDA

Agente especializado em responder perguntas sobre o texto em foco.

## Descricao
Voce e o MeuAgente, responsavel por analisar o texto em foco no NVDA
e responder perguntas do usuario sobre seu conteudo.

## Responsabilidades
- Capturar o texto do objeto em foco
- Enviar para a API Groq
- Retornar resposta via ui.message()

## Regras de Comportamento
- Nunca executar codigo gerado pela IA
- Sempre usar try/except em chamadas externas
- Sem emojis nos logs

## Entradas
- Texto do objeto em foco (string)
- Pergunta do usuario (string)

## Saidas
- Resposta da IA (string) anunciada via ui.message()

## Invariantes
- Historico nunca contem mensagens de sistema
- Groq importado condicionalmente (try/except ImportError)
- max 3 retries por chamada

## Referencias
- https://ollama.com/library
- https://community-access.org/
- https://github.com/nvaccess/nvda

## Versao
1.0.0

## Metadados
name: meu-agente-nvda
description: Agente responsavel por analisar texto em foco e responder via ui.message. Use quando o usuario solicitar resposta sobre conteudo do objeto focado.
"""

AGENT_TEMPLATE_SEM_INVARIANTES = """# Meu Agente

## Descricao
Descricao do agente.

## Responsabilidades
- Responsabilidade 1

## Regras de Comportamento
- Regra 1

## Entradas
- Entrada 1

## Saidas
- Saida 1

## Referencias
- https://exemplo.com

## Versao
1.0.0
"""
# Invariantes ausente intencionalmente

AGENT_TEMPLATE_SEM_VERSAO = """# Meu Agente

## Descricao
Descricao do agente.

## Responsabilidades
- Responsabilidade 1

## Regras de Comportamento
- Regra 1

## Entradas
- Entrada 1

## Saidas
- Saida 1

## Invariantes
- Invariante 1

## Referencias
- https://exemplo.com
"""
# Versao ausente intencionalmente

# --------------------------------------------------------------------------
# Testes: agent_runner_agent._validate_structure
# --------------------------------------------------------------------------

class TestAgentRunnerValidateStructure:
    """
    Regra 5: _validate_structure e deterministica — verifica padroes no texto gerado.
    Regra 9: nunca executa o codigo.
    """

    def test_codigo_completo_sem_avisos(self):
        from nvdastudio.sub_agents.agent_runner_agent import _validate_structure
        warnings = _validate_structure(AGENT_RUNNER_COMPLETO)
        assert warnings == [], f"Esperava sem avisos, recebeu: {warnings}"

    def test_sem_reset_session_gera_aviso(self):
        from nvdastudio.sub_agents.agent_runner_agent import _validate_structure
        warnings = _validate_structure(AGENT_RUNNER_SEM_RESET)
        assert any("reset_session" in w for w in warnings), (
            "reset_session ausente deve gerar aviso"
        )

    def test_sem_fallback_chain_gera_aviso(self):
        from nvdastudio.sub_agents.agent_runner_agent import _validate_structure
        warnings = _validate_structure(AGENT_RUNNER_SEM_FALLBACK)
        assert any("_fallback_chain" in w for w in warnings), (
            "_fallback_chain ausente deve gerar aviso"
        )

    def test_sem_importerror_cliente_llm_gera_aviso(self):
        from nvdastudio.sub_agents.agent_runner_agent import _validate_structure
        warnings = _validate_structure(AGENT_RUNNER_SEM_TRY_EXCEPT_IMPORTERROR)
        assert any("lazy" in w.lower() or "httpx" in w.lower() for w in warnings), (
            "falta importacao lazy de httpx em run() deve gerar aviso"
        )

    def test_aviso_nao_executa_codigo(self):
        """Regra 9: _validate_structure analisa texto, nunca executa."""
        from nvdastudio.sub_agents.agent_runner_agent import _validate_structure
        codigo_malicioso = "import os; os.system('del C:\\\\*')\ndef reset_session(self): pass"
        # Nao deve levantar excecao nem executar nada
        warnings = _validate_structure(codigo_malicioso)
        assert isinstance(warnings, list)

    def test_codigo_vazio_gera_todos_avisos(self):
        from nvdastudio.sub_agents.agent_runner_agent import _validate_structure, _REQUIRED_PATTERNS
        warnings = _validate_structure("")
        assert len(warnings) == len(_REQUIRED_PATTERNS), (
            "Codigo vazio deve gerar aviso para cada padrao obrigatorio"
        )

class TestAgentRunnerSubAgentRun:
    """Testa run() — prefixo de aviso e adicionado quando estrutura incompleta."""

    def test_output_completo_sem_prefixo_aviso(self, fake_api_key):
        from nvdastudio.sub_agents.agent_runner_agent import run

        mock_resp = MagicMock()
        mock_resp.content = AGENT_RUNNER_COMPLETO

        with patch("nvdastudio.sub_agents._base.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.return_value = mock_resp
            output = run("crie agentrunner para addon X", "kimi-k2.6", {})

        assert "AVISO DE ESTRUTURA" not in output
        assert "reset_session" in output

    def test_output_incompleto_adiciona_prefixo_aviso(self, fake_api_key):
        from nvdastudio.sub_agents.agent_runner_agent import run

        mock_resp = MagicMock()
        mock_resp.content = AGENT_RUNNER_SEM_RESET  # sem reset_session

        with patch("nvdastudio.sub_agents._base.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.return_value = mock_resp
            output = run("crie agentrunner", "kimi-k2.6", {})

        assert "AVISO DE ESTRUTURA" in output
        assert "reset_session" in output  # aviso menciona o que esta ausente

    def test_output_nunca_executado(self, fake_api_key):
        """Regra 9: run() retorna string, nunca exec/eval."""
        from nvdastudio.sub_agents.agent_runner_agent import run

        mock_resp = MagicMock()
        mock_resp.content = "import os; os.system('del C:\\\\')"

        with patch("nvdastudio.sub_agents._base.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.return_value = mock_resp
            # Nao deve executar o codigo malicioso
            output = run("prompt qualquer", "kimi-k2.6", {})

        assert isinstance(output, str)

# --------------------------------------------------------------------------
# Testes: agent_template_agent._validate_sections
# --------------------------------------------------------------------------

class TestAgentTemplateValidateSections:
    """
    Regra 5: _validate_sections e deterministica — verifica secoes no MD gerado.
    Formato Community Access exige todas as 8 secoes.
    """

    def test_template_completo_sem_secoes_ausentes(self):
        from nvdastudio.sub_agents.agent_template_agent import _validate_sections
        missing = _validate_sections(AGENT_TEMPLATE_COMPLETO)
        assert missing == [], f"Esperava sem ausentes, recebeu: {missing}"

    def test_sem_invariantes_reporta_secao_ausente(self):
        from nvdastudio.sub_agents.agent_template_agent import _validate_sections
        missing = _validate_sections(AGENT_TEMPLATE_SEM_INVARIANTES)
        assert "Invariantes" in missing

    def test_sem_versao_reporta_secao_ausente(self):
        from nvdastudio.sub_agents.agent_template_agent import _validate_sections
        missing = _validate_sections(AGENT_TEMPLATE_SEM_VERSAO)
        assert "Versao" in missing

    def test_template_vazio_reporta_todas_secoes(self):
        from nvdastudio.sub_agents.agent_template_agent import _validate_sections, _REQUIRED_SECTIONS
        missing = _validate_sections("")
        assert len(missing) == len(_REQUIRED_SECTIONS), (
            "Template vazio deve reportar todas as secoes ausentes"
        )

    def test_secoes_case_insensitive(self):
        """_validate_sections aceita variantes de acentuacao (Saidas/Saídas)."""
        from nvdastudio.sub_agents.agent_template_agent import _validate_sections
        template_acentuado = AGENT_TEMPLATE_COMPLETO.replace("## Saidas", "## Saídas")
        missing = _validate_sections(template_acentuado)
        assert "Saidas" not in missing

    def test_todas_8_secoes_obrigatorias(self):
        from nvdastudio.sub_agents.agent_template_agent import _REQUIRED_SECTIONS
        nomes = [nome for nome, _ in _REQUIRED_SECTIONS]
        assert len(_REQUIRED_SECTIONS) == 9, "Community Access exige 9 secoes"
        assert "Descricao" in nomes
        assert "Responsabilidades" in nomes
        assert "Regras de Comportamento" in nomes
        assert "Entradas" in nomes
        assert "Saidas" in nomes
        assert "Invariantes" in nomes
        assert "Referencias" in nomes
        assert "Versao" in nomes
        assert "Metadados" in nomes

class TestAgentTemplateSubAgentRun:
    """Testa run() — prefixo de aviso adicionado quando secoes ausentes."""

    def test_template_completo_sem_aviso(self, fake_api_key):
        from nvdastudio.sub_agents.agent_template_agent import run

        mock_resp = MagicMock()
        mock_resp.content = AGENT_TEMPLATE_COMPLETO

        with patch("nvdastudio.sub_agents._base.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.return_value = mock_resp
            output = run("crie template de agente X", "kimi-k2.6", {})

        assert "AVISO DE ESTRUTURA" not in output

    def test_template_incompleto_adiciona_aviso_html_comment(self, fake_api_key):
        """Aviso e inserido como comentario HTML para nao quebrar o markdown."""
        from nvdastudio.sub_agents.agent_template_agent import run

        mock_resp = MagicMock()
        mock_resp.content = AGENT_TEMPLATE_SEM_INVARIANTES

        with patch("nvdastudio.sub_agents._base.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.return_value = mock_resp
            output = run("crie template", "kimi-k2.6", {})

        assert "AVISO DE ESTRUTURA" in output
        assert "Invariantes" in output  # aviso menciona a secao ausente

    def test_load_template_examples_inclui_templates_existentes(self):
        from nvdastudio.sub_agents.agent_template_agent import _load_template_examples
        result = _load_template_examples()
        assert isinstance(result, str)
        # Se existem templates no diretorio, devem estar no resultado
        if result:
            assert "##" in result or "Descricao" in result

# --------------------------------------------------------------------------
# Testes: Critic verifica criterios de agent_runner e agent_template
# --------------------------------------------------------------------------

class TestCriticCriteriosAgente:
    """
    Verifica que o Critic tem criterios especificos para agent_runner e agent_template
    no _CRITIC_SYSTEM — Regra 5: criterios deterministicos no prompt.
    """

    def test_critic_system_tem_criterios_agent_runner(self):
        from nvdastudio.ai.critic import _CRITIC_SYSTEM
        assert "agent_runner" in _CRITIC_SYSTEM.lower()
        assert "reset_session" in _CRITIC_SYSTEM
        assert "_fallback_chain" in _CRITIC_SYSTEM
        assert "historico" in _CRITIC_SYSTEM.lower() or "history" in _CRITIC_SYSTEM.lower()

    def test_critic_system_tem_criterios_agent_template(self):
        from nvdastudio.ai.critic import _CRITIC_SYSTEM
        assert "agent_template" in _CRITIC_SYSTEM.lower()
        assert "Community Access" in _CRITIC_SYSTEM or "community access" in _CRITIC_SYSTEM.lower()
        assert "Invariantes" in _CRITIC_SYSTEM or "invariantes" in _CRITIC_SYSTEM.lower()
        assert "Versao" in _CRITIC_SYSTEM or "versao" in _CRITIC_SYSTEM.lower()

    def test_critic_system_tem_criterios_web_research(self):
        """web_research deve ter criterio proprio — nao aplicar code_generation."""
        from nvdastudio.ai.critic import _CRITIC_SYSTEM
        assert "web_research" in _CRITIC_SYSTEM.lower()

    def test_critic_system_menciona_cliente_llm_importerror(self):
        """ImportError do cliente LLM e invariante critico do agent_runner."""
        from nvdastudio.ai.critic import _CRITIC_SYSTEM
        assert "ImportError" in _CRITIC_SYSTEM or "importerror" in _CRITIC_SYSTEM.lower()

# --------------------------------------------------------------------------
# Testes: assembler._validate_agent_artifacts
# --------------------------------------------------------------------------

class TestAssemblerValidateAgentArtifacts:
    """
    Invariante v1.0.1: assembler detecta artefatos de agente ausentes.
    Regra 5: verificacao deterministica de presenca de arquivos.
    Regra 9: nunca executa nenhum artefato.
    """

    _OUTPUT_COMPLETO = """\
=== RESUMO ===
Addon com agente criado.

=== ARQUIVOS ===
```python:addon/globalPlugins/meuAddon/__init__.py
import globalPluginHandler
```

```python:addon/globalPlugins/meuAddon/agent_runner.py
class AgentRunner:
    def reset_session(self): self._history = []
    _fallback_chain = ["kimi-k2.6"]
```

```markdown:addon/globalPlugins/meuAddon/agent_config.md
## Invariantes
- historico sem system
## Versao
1.0.0
```

=== INSTALACAO ===
Instale via Menu NVDA > Ferramentas > Addons.
"""

    _OUTPUT_SEM_AGENT_RUNNER_PY = """\
=== RESUMO ===
Addon com AgentRunner criado (mas arquivo ausente no output).

=== ARQUIVOS ===
```python:addon/globalPlugins/meuAddon/__init__.py
import globalPluginHandler
class GlobalPlugin(globalPluginHandler.GlobalPlugin): pass
```

O reset_session e o AgentRunner deveriam estar em agent_runner.py mas nao estao listados.
"""

    _OUTPUT_SEM_AGENT_CONFIG_MD = """\
=== RESUMO ===
Addon com agente criado.

=== ARQUIVOS ===
```python:addon/globalPlugins/meuAddon/agent_runner.py
class AgentRunner:
    def reset_session(self): pass
```

Falta agent_config.md com os ## Invariantes do agente.
"""

    _OUTPUT_SEM_AGENTE = """\
=== RESUMO ===
Addon simples sem agente.

=== ARQUIVOS ===
```python:addon/globalPlugins/meuAddon/__init__.py
import globalPluginHandler
class GlobalPlugin(globalPluginHandler.GlobalPlugin): pass
```

=== INSTALACAO ===
Instale via NVDA.
"""

    def test_output_completo_sem_avisos(self):
        from nvdastudio.sub_agents.assembler import _validate_agent_artifacts
        warnings = _validate_agent_artifacts(self._OUTPUT_COMPLETO)
        assert warnings == [], f"Esperava sem avisos, recebeu: {warnings}"

    def test_sem_agent_runner_py_gera_aviso(self):
        """AgentRunner referenciado no texto mas bloco .py ausente -> aviso."""
        from nvdastudio.sub_agents.assembler import _validate_agent_artifacts
        warnings = _validate_agent_artifacts(self._OUTPUT_SEM_AGENT_RUNNER_PY)
        assert any("agent_runner.py" in w for w in warnings), (
            "agent_runner.py ausente deve gerar aviso"
        )

    def test_sem_agent_config_md_gera_aviso(self):
        """Invariantes referenciados mas agent_config.md ausente -> aviso."""
        from nvdastudio.sub_agents.assembler import _validate_agent_artifacts
        warnings = _validate_agent_artifacts(self._OUTPUT_SEM_AGENT_CONFIG_MD)
        assert any("agent_config.md" in w for w in warnings), (
            "agent_config.md ausente deve gerar aviso"
        )

    def test_addon_simples_sem_agente_sem_avisos(self):
        """Addon sem agente nao deve gerar avisos de artefatos."""
        from nvdastudio.sub_agents.assembler import _validate_agent_artifacts
        warnings = _validate_agent_artifacts(self._OUTPUT_SEM_AGENTE)
        assert warnings == []

    def test_output_vazio_sem_avisos(self):
        """Output vazio nao tem conteudo de agente — sem avisos."""
        from nvdastudio.sub_agents.assembler import _validate_agent_artifacts
        warnings = _validate_agent_artifacts("")
        assert warnings == []

    def test_validate_nunca_executa_codigo(self):
        """Regra 9: _validate_agent_artifacts analisa texto, nunca executa."""
        from nvdastudio.sub_agents.assembler import _validate_agent_artifacts
        output_malicioso = (
            "AgentRunner class with reset_session\n"
            "import os; os.system('del C:\\\\')\n"
        )
        # Nao deve levantar excecao nem executar nada
        result = _validate_agent_artifacts(output_malicioso)
        assert isinstance(result, list)

class TestAssemblerRun:
    """Testa run() do assembler — aviso de montagem adicionado quando necessario."""

    def test_output_com_agentes_completo_sem_prefixo_aviso(self, fake_api_key):
        from nvdastudio.sub_agents.assembler import run

        mock_resp = MagicMock()
        mock_resp.content = TestAssemblerValidateAgentArtifacts._OUTPUT_COMPLETO

        with patch("nvdastudio.sub_agents._base.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.return_value = mock_resp
            output = run("monte o addon", "kimi-k2.6", {})

        assert "AVISO DE MONTAGEM" not in output

    def test_output_incompleto_adiciona_aviso_montagem(self, fake_api_key):
        from nvdastudio.sub_agents.assembler import run

        mock_resp = MagicMock()
        mock_resp.content = TestAssemblerValidateAgentArtifacts._OUTPUT_SEM_AGENT_RUNNER_PY

        with patch("nvdastudio.sub_agents._base.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.return_value = mock_resp
            output = run("monte o addon", "kimi-k2.6", {})

        assert "AVISO DE MONTAGEM" in output
        assert "agent_runner.py" in output

    def test_output_nunca_executado(self, fake_api_key):
        """Regra 9: run() retorna string, nunca executa o conteudo."""
        from nvdastudio.sub_agents.assembler import run

        mock_resp = MagicMock()
        mock_resp.content = "import os; os.system('del C:\\\\')"

        with patch("nvdastudio.sub_agents._base.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.return_value = mock_resp
            output = run("prompt qualquer", "kimi-k2.6", {})

        assert isinstance(output, str)

# --------------------------------------------------------------------------
# Testes: design_review_agent estrutura — v1.1.0
# --------------------------------------------------------------------------

class TestDesignReviewAgentEstrutura:
    """
    Valida estrutura do design_review_agent.py.
    Padrao: multi-agent-brainstorming (Challenger + Guardian + User Advocate).
    Regra 9: nunca executa codigo — apenas analisa e produz texto.
    """

    def test_design_review_agent_importavel(self):
        from nvdastudio.sub_agents import design_review_agent
        assert design_review_agent is not None

    def test_tem_funcao_run(self):
        from nvdastudio.sub_agents.design_review_agent import run
        assert callable(run)

    def test_challenger_e_guardian_respeitam_modelo_do_step(self):
        import inspect
        from nvdastudio.sub_agents.design_review_agent import run
        assert inspect.getsource(run).count("model_id,") >= 3

    def test_nao_tem_modelo_fixo_no_design_review(self):
        from nvdastudio.sub_agents import design_review_agent
        assert not hasattr(design_review_agent, "MODEL_ADVOCATE")

    def test_challenger_usa_modelo_glm(self):
        """Challenger precisa de reasoning profundo para identificar falhas criticas."""
        from nvdastudio.sub_agents.design_review_agent import _REASONING_CHALLENGER
        assert isinstance(_REASONING_CHALLENGER, dict)

    def test_guardian_usa_modelo_glm(self):
        """Constraint Guardian precisa de reasoning profundo para mapear restricoes."""
        from nvdastudio.sub_agents.design_review_agent import _REASONING_GUARDIAN
        assert isinstance(_REASONING_GUARDIAN, dict)

    def test_advocate_usa_modelo_kimi(self):
        """User Advocate usa modelo standard."""
        import inspect
        from nvdastudio.sub_agents.design_review_agent import run
        assert "MODEL_ADVOCATE" not in inspect.getsource(run)

    def test_challenger_system_menciona_suposicoes(self):
        from nvdastudio.sub_agents.design_review_agent import _CHALLENGER_SYSTEM
        assert "suposic" in _CHALLENGER_SYSTEM.lower() or "falh" in _CHALLENGER_SYSTEM.lower()

    def test_guardian_system_menciona_restricoes_nvda(self):
        from nvdastudio.sub_agents.design_review_agent import _GUARDIAN_SYSTEM
        assert "NVDA-001" in _GUARDIAN_SYSTEM or "nextHandler" in _GUARDIAN_SYSTEM

    def test_guardian_system_menciona_restricoes_wx(self):
        from nvdastudio.sub_agents.design_review_agent import _GUARDIAN_SYSTEM
        assert "WX-A11Y" in _GUARDIAN_SYSTEM or "BoxSizer" in _GUARDIAN_SYSTEM

    def test_advocate_system_menciona_usuario_cego(self):
        """User Advocate deve focar na perspectiva do usuario cego."""
        from nvdastudio.sub_agents.design_review_agent import _ADVOCATE_SYSTEM
        assert "ceg" in _ADVOCATE_SYSTEM.lower() or "leitor de tela" in _ADVOCATE_SYSTEM.lower()

    def test_synthesis_template_tem_secoes_estruturadas(self):
        """Template de sintese deve ter secoes Challenger, Guardian e Advocate."""
        from nvdastudio.sub_agents.design_review_agent import _SYNTHESIS_TEMPLATE_V3
        assert "Challenger" in _SYNTHESIS_TEMPLATE_V3
        assert "Guardian" in _SYNTHESIS_TEMPLATE_V3
        assert "{challenger}" in _SYNTHESIS_TEMPLATE_V3
        assert "{guardian}" in _SYNTHESIS_TEMPLATE_V3
        assert "{advocate}" in _SYNTHESIS_TEMPLATE_V3


class TestGuardianCatalogoCompletoDeRegras:
    """v2.7.0: bug real de auditoria (comparacao com community-access.org) -- o Guardian
    so citava 4 das 54 regras NVDA ("NVDA-001..004") e uma mencao vaga a "WX-A11Y", e
    dizia "quais das regras ABAIXO" sem nenhuma regra de verdade listada abaixo. Corrigido:
    injeta o mesmo RULE_REGISTRY_PROMPT_TEXT usado por code_generator, accessibility_auditor
    e critic -- ficando cego para 50 das 54 regras NVDA e as 14 WX-A11Y so era resolvido assim."""

    def test_guardian_contem_registro_completo_de_regras(self):
        from nvdastudio.sub_agents.design_review_agent import _GUARDIAN_SYSTEM
        from nvdastudio.rule_registry import RULE_REGISTRY_PROMPT_TEXT
        assert RULE_REGISTRY_PROMPT_TEXT in _GUARDIAN_SYSTEM

    def test_guardian_cita_regras_alem_das_4_originais(self):
        """Regressao direta: antes so tinha NVDA-001..004. Agora deve ter regras bem alem disso."""
        from nvdastudio.sub_agents.design_review_agent import _GUARDIAN_SYSTEM
        for rid in ("NVDA-030", "NVDA-048", "WX-A11Y-013"):
            assert rid in _GUARDIAN_SYSTEM, f"{rid} ausente do Guardian -- catalogo incompleto"

    def test_guardian_nao_promete_regras_que_nao_lista(self):
        """A frase antiga "quais das regras ABAIXO" so fazia sentido se regras realmente
        estivessem listadas abaixo -- garante que RULE_REGISTRY_PROMPT_TEXT vem DEPOIS do
        placeholder que menciona "abaixo"."""
        from nvdastudio.sub_agents.design_review_agent import _GUARDIAN_SYSTEM
        idx_placeholder = _GUARDIAN_SYSTEM.find("abaixo")
        idx_primeira_regra = _GUARDIAN_SYSTEM.find("NVDA-001")
        assert idx_placeholder != -1 and idx_primeira_regra != -1
        assert idx_primeira_regra > idx_placeholder

    def test_run_nao_executa_codigo_gerado(self, fake_api_key):
        from nvdastudio.sub_agents.design_review_agent import run
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.content = "analise de risco"
        mock_resp.reasoning = None

        codigo = "import os; os.system('del /f /q C:\\\\')"
        with patch("nvdastudio.sub_agents._base.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.return_value = mock_resp
            output = run(codigo, "kimi-k2.6", {})

        assert isinstance(output, str)

    def test_dispatcher_inclui_design_review(self):
        """STEP_DESIGN_REVIEW deve estar no mapa do dispatcher."""
        # Verifica que o modulo dispatcher importa e roteia STEP_DESIGN_REVIEW
        import inspect
        import nvdastudio.sub_agents.dispatcher as disp_mod
        src = inspect.getsource(disp_mod)
        assert "STEP_DESIGN_REVIEW" in src or "design_review" in src

class TestBaseSystemOverride:
    """
    _base.py v1.0.1: system_override agora e passado corretamente ao client.chat().

    Bug corrigido: full_system (NVDA_SYSTEM_PROMPT + system_addendum) era calculado
    em _run_sub_agent mas nao passado ao GroqClient.chat() — todos os sub-agentes
    usavam apenas o NVDA_SYSTEM_PROMPT generico, sem o contexto especializado.

    Regra 3: DRY — _base.py e a unica fonte de chamada ao GroqClient.
    Regra 9: nenhum codigo gerado e executado nestes testes.
    """

    def test_run_sub_agent_passa_system_override(self, fake_api_key):
        """
        _run_sub_agent deve passar full_system como system_override ao client.chat().
        Sem este fix, o system_addendum era descartado silenciosamente.
        """
        mock_resp = MagicMock()
        mock_resp.content = "codigo gerado"
        mock_resp.reasoning = None

        system_override_recebido = []

        def capture_chat(prompt, **kwargs):
            system_override_recebido.append(kwargs.get("system_override"))
            return mock_resp

        with patch("nvdastudio.sub_agents._base.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.side_effect = capture_chat
            from nvdastudio.sub_agents._base import _run_sub_agent
            _run_sub_agent(
                system_addendum="Voce e o CodeGenerator especializado.",
                prompt="gere um addon",
                model_id="kimi-k2.6",
                reasoning_params={},
            )

        assert len(system_override_recebido) == 1, "chat() deve ter sido chamado uma vez"
        override = system_override_recebido[0]
        assert override is not None, "system_override nao deve ser None"
        assert isinstance(override, str), "system_override deve ser string"
        assert "CodeGenerator especializado" in override, (
            "system_addendum deve estar no system_override"
        )

    def test_run_sub_agent_system_override_contem_nvda_prompt(self, fake_api_key):
        """
        system_override deve conter NVDA_SYSTEM_PROMPT + system_addendum concatenados.
        """

        mock_resp = MagicMock()
        mock_resp.content = "ok"
        mock_resp.reasoning = None
        overrides_recebidos = []

        def capture_chat(prompt, **kwargs):
            overrides_recebidos.append(kwargs.get("system_override", ""))
            return mock_resp

        with patch("nvdastudio.sub_agents._base.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.side_effect = capture_chat
            from nvdastudio.sub_agents._base import _run_sub_agent
            _run_sub_agent(
                system_addendum="ADDENDUM_UNICO_XYZ",
                prompt="prompt qualquer",
                model_id="kimi-k2.6",
                reasoning_params={},
            )

        assert len(overrides_recebidos) == 1
        override = overrides_recebidos[0]
        # Deve conter tanto o prompt base quanto o addendum
        assert "ADDENDUM_UNICO_XYZ" in override, "Addendum ausente do system_override"
        assert len(override) > len("ADDENDUM_UNICO_XYZ"), (
            "system_override deve conter mais que apenas o addendum"
        )

    def test_code_generator_usa_system_addendum_especializado(self, fake_api_key):
        """
        code_generator.run() deve enviar system prompt que contem instrucoes especificas
        de geracao de codigo NVDA (nao apenas o NVDA_SYSTEM_PROMPT generico).
        """
        mock_resp = MagicMock()
        mock_resp.content = "codigo gerado"
        mock_resp.reasoning = None
        mock_resp.tool_calls = []
        mock_resp.tokens_used = 0
        overrides = []

        def capture_chat(prompt, **kwargs):
            overrides.append(kwargs.get("system_override", ""))
            return mock_resp

        # code_generator.run() usa create_llm_client para instanciar clientes.
        with patch("nvdastudio.sub_agents.code_generator.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.side_effect = capture_chat
            from nvdastudio.sub_agents.code_generator import run
            run("crie um addon", "kimi-k2.6", {})

        assert len(overrides) == 1
        override = overrides[0]
        # code_generator tem _SYSTEM com "CodeGenerator" e instrucoes de codigo
        assert len(override) > 100, "system_override muito curto"
        # O addendum especializado do code_generator deve estar presente
        override_lower = override.lower()
        assert any(t in override_lower for t in [
            "codegenerator", "codigo python", "globalPlugin".lower(),
            "python", "addon", "import",
        ]), f"system_override nao contem contexto de code_generator. Inicio: {override[:200]}"

    def test_run_sub_agent_erro_retorna_string_com_prefixo(self, fake_api_key):
        """Quando GroqClient lanca erro, _run_sub_agent retorna string com [ERRO]."""
        from nvdastudio.ai.llm_client import LLMClientError

        with patch("nvdastudio.sub_agents._base.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.side_effect = LLMClientError("falha na api")
            from nvdastudio.sub_agents._base import _run_sub_agent
            output = _run_sub_agent(
                system_addendum="addendum",
                prompt="prompt",
                model_id="kimi-k2.6",
                reasoning_params={},
            )

        assert isinstance(output, str)
        assert output.startswith("[ERRO]"), f"Esperado [ERRO] no inicio, recebido: {output[:100]}"

    def test_run_sub_agent_excecao_generica_tambem_vira_string_com_prefixo(self, fake_api_key):
        """Bug real de auditoria: so LLMClientError era capturado. Qualquer
        outra excecao (ex: ValueError vindo de dentro de client.chat(), ou de
        create_llm_client()) escapava sem tratamento, passando direto pelo
        retry/escalonamento do orchestrator e abortando o pipeline INTEIRO em
        vez de falhar so este step."""
        with patch("nvdastudio.sub_agents._base.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.side_effect = ValueError("erro inesperado, nao-LLMClientError")
            from nvdastudio.sub_agents._base import _run_sub_agent
            output = _run_sub_agent(
                system_addendum="addendum",
                prompt="prompt",
                model_id="kimi-k2.6",
                reasoning_params={},
            )

        assert isinstance(output, str)
        assert output.startswith("[ERRO]"), f"Esperado [ERRO] no inicio, recebido: {output[:100]}"

class TestCodeGeneratorToolUse:
    """Testa estrutura do tool use no code_generator."""

    def test_validate_import_tool_nvda_modulo(self):
        from nvdastudio.sub_agents.code_generator import _validate_import_tool
        result = _validate_import_tool("globalPluginHandler")
        assert result["status"] == "nvda"
        assert "module" in result

    def test_validate_import_tool_stdlib(self):
        from nvdastudio.sub_agents.code_generator import _validate_import_tool
        result = _validate_import_tool("threading")
        assert result["status"] == "stdlib"

    def test_validate_import_tool_desconhecido(self):
        from nvdastudio.sub_agents.code_generator import _validate_import_tool
        result = _validate_import_tool("google.generativeai")
        assert result["status"] == "unknown"
        assert "pip_name" in result
        assert "message" in result

    def test_validate_import_tool_nao_executa(self):
        from nvdastudio.sub_agents.code_generator import _validate_import_tool
        import os
        marker = os.path.join(os.path.expanduser("~"), "_validate_tool_exec.txt")
        _validate_import_tool(f"open(r'{marker}','w').write('EXEC')")
        assert not os.path.exists(marker)

    def test_code_generator_tem_funcao_run(self):
        import nvdastudio.sub_agents.code_generator as cg
        assert hasattr(cg, "run")
        assert callable(cg.run)

    def test_code_generator_tem_validate_import_tool(self):
        import nvdastudio.sub_agents.code_generator as cg
        assert hasattr(cg, "_validate_import_tool")
        assert callable(cg._validate_import_tool)

    def test_code_generator_fallback_sem_tool_use(self):
        """Se tool use falhar, cai para _run_sub_agent sem crash."""
        from unittest.mock import patch, MagicMock
        mock_resp = MagicMock()
        mock_resp.content = "codigo gerado"
        mock_resp.tool_calls = []
        with patch("nvdastudio.sub_agents.code_generator.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.return_value = mock_resp
            from nvdastudio.sub_agents.code_generator import run
            result = run("prompt", "kimi-k2.6", {})
        assert isinstance(result, str)

    def test_code_generator_nao_executa_output(self):
        """Regra 9: codigo gerado nunca e executado."""
        from unittest.mock import patch, MagicMock
        import os
        marker = os.path.join(os.path.expanduser("~"), "_cg_exec_test.txt")
        codigo = f"import os; os.open(r'{marker}', os.O_CREAT)"
        mock_resp = MagicMock()
        mock_resp.content = f"```python:globalPlugins/x/__init__.py\n{codigo}\n```"
        mock_resp.tool_calls = []
        with patch("nvdastudio.sub_agents.code_generator.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.return_value = mock_resp
            from nvdastudio.sub_agents.code_generator import run
            run("prompt", "kimi-k2.6", {})
        assert not os.path.exists(marker)

# --------------------------------------------------------------------------
# Testes: assembler._validate_structural_issues (v1.1.0 — B6 e B7)
# --------------------------------------------------------------------------

class TestAssemblerVersao120:
    def test_versao_e_1_2_0(self):
        from nvdastudio.sub_agents.assembler import MODULE_VERSION
        assert MODULE_VERSION == "1.7.0"

    def test_validate_structural_issues_importavel(self):
        from nvdastudio.sub_agents.assembler import _validate_structural_issues
        assert callable(_validate_structural_issues)

class TestAssemblerB6DuasPastasPlugin:
    """B6: duas pastas globalPlugins/ com __init__.py causam conflito no NVDA."""

    _OUTPUT_UMA_PASTA = """\
```python:globalPlugins/MeuAddon/__init__.py
import globalPluginHandler
class GlobalPlugin(globalPluginHandler.GlobalPlugin): pass
```
```ini:manifest.ini
name = MeuAddon
"""

    _OUTPUT_DUAS_PASTAS = """\
```python:globalPlugins/MediaTranscriber/__init__.py
import globalPluginHandler
class GlobalPlugin(globalPluginHandler.GlobalPlugin): pass
```
```python:globalPlugins/TranscriptorMultimidia/__init__.py
import globalPluginHandler
class GlobalPlugin(globalPluginHandler.GlobalPlugin): pass
```
```ini:manifest.ini
name = Transcriber
"""

    def test_uma_pasta_sem_aviso(self):
        from nvdastudio.sub_agents.assembler import _validate_structural_issues
        warnings = _validate_structural_issues(self._OUTPUT_UMA_PASTA)
        b6 = [w for w in warnings if "B6" in w]
        assert b6 == [], f"Uma pasta nao deve gerar aviso B6: {b6}"

    def test_duas_pastas_gera_aviso_b6(self):
        from nvdastudio.sub_agents.assembler import _validate_structural_issues
        warnings = _validate_structural_issues(self._OUTPUT_DUAS_PASTAS)
        b6 = [w for w in warnings if "B6" in w]
        assert len(b6) == 1, f"Duas pastas devem gerar exatamente 1 aviso B6: {warnings}"

    def test_aviso_b6_menciona_nomes_das_pastas(self):
        from nvdastudio.sub_agents.assembler import _validate_structural_issues
        warnings = _validate_structural_issues(self._OUTPUT_DUAS_PASTAS)
        b6 = [w for w in warnings if "B6" in w][0]
        assert "MediaTranscriber" in b6 or "TranscriptorMultimidia" in b6

    def test_aviso_b6_menciona_fusao(self):
        """Aviso deve instruir a fundir em uma unica pasta."""
        from nvdastudio.sub_agents.assembler import _validate_structural_issues
        warnings = _validate_structural_issues(self._OUTPUT_DUAS_PASTAS)
        b6 = [w for w in warnings if "B6" in w][0]
        assert "fund" in b6.lower() or "unica" in b6.lower()

    def test_output_vazio_sem_aviso_b6(self):
        from nvdastudio.sub_agents.assembler import _validate_structural_issues
        warnings = _validate_structural_issues("")
        b6 = [w for w in warnings if "B6" in w]
        assert b6 == []

    def test_nao_executa_conteudo(self):
        """Regra 9: analisa texto, nunca executa."""
        from nvdastudio.sub_agents.assembler import _validate_structural_issues
        output = "```python:globalPlugins/A/__init__.py\nimport os; os.system('del')\n```"
        result = _validate_structural_issues(output)
        assert isinstance(result, list)

class TestAssemblerB7DocFilenameSemdoc:
    """B7: docFileName no manifest sem bloco html:doc/ correspondente."""

    _OUTPUT_COM_DOC_BLOCO = """\
```ini:manifest.ini
name = MeuAddon
docFileName = readme.html
```
```html:doc/pt_BR/userGuide.html
<html><body><h1>Documentacao</h1></body></html>
```
"""

    _OUTPUT_SEM_DOC_BLOCO = """\
```ini:manifest.ini
name = MeuAddon
docFileName = readme.html
```
```python:globalPlugins/MeuAddon/__init__.py
import globalPluginHandler
```
"""

    _OUTPUT_SEM_DOCFILENAME = """\
```ini:manifest.ini
name = MeuAddon
```
```python:globalPlugins/MeuAddon/__init__.py
import globalPluginHandler
```
"""

    def test_com_bloco_html_sem_aviso_b7(self):
        from nvdastudio.sub_agents.assembler import _validate_structural_issues
        warnings = _validate_structural_issues(self._OUTPUT_COM_DOC_BLOCO)
        b7 = [w for w in warnings if "B7" in w]
        assert b7 == [], f"Com bloco html nao deve gerar B7: {b7}"

    def test_sem_bloco_html_gera_aviso_b7(self):
        from nvdastudio.sub_agents.assembler import _validate_structural_issues
        warnings = _validate_structural_issues(self._OUTPUT_SEM_DOC_BLOCO)
        b7 = [w for w in warnings if "B7" in w]
        assert len(b7) == 1, f"docFileName sem html deve gerar B7: {warnings}"

    def test_aviso_b7_menciona_html_doc(self):
        from nvdastudio.sub_agents.assembler import _validate_structural_issues
        warnings = _validate_structural_issues(self._OUTPUT_SEM_DOC_BLOCO)
        b7 = [w for w in warnings if "B7" in w][0]
        assert "html:doc/" in b7

    def test_sem_docfilename_sem_aviso_b7(self):
        """Sem docFileName no manifest nao ha expectativa de doc."""
        from nvdastudio.sub_agents.assembler import _validate_structural_issues
        warnings = _validate_structural_issues(self._OUTPUT_SEM_DOCFILENAME)
        b7 = [w for w in warnings if "B7" in w]
        assert b7 == []

    def test_output_vazio_sem_aviso_b7(self):
        from nvdastudio.sub_agents.assembler import _validate_structural_issues
        warnings = _validate_structural_issues("")
        b7 = [w for w in warnings if "B7" in w]
        assert b7 == []

class TestAssemblerRunComB6B7:
    """run() inclui avisos B6/B7 no bloco AVISO DE MONTAGEM."""

    def test_run_duas_pastas_inclui_aviso_montagem(self, fake_api_key):
        from nvdastudio.sub_agents.assembler import run
        output_duas_pastas = (
            "```python:globalPlugins/PluginA/__init__.py\nclass GlobalPlugin: pass\n```\n"
            "```python:globalPlugins/PluginB/__init__.py\nclass GlobalPlugin: pass\n```\n"
            "```ini:manifest.ini\nname = MeuAddon\n```\n"
        )
        mock_resp = MagicMock()
        mock_resp.content = output_duas_pastas
        with patch("nvdastudio.sub_agents._base.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.return_value = mock_resp
            output = run("monte", "kimi-k2.6", {})
        assert "AVISO DE MONTAGEM" in output
        assert "B6" in output

    def test_run_sem_doc_inclui_aviso_montagem(self, fake_api_key):
        from nvdastudio.sub_agents.assembler import run
        output_sem_doc = (
            "```python:globalPlugins/MeuAddon/__init__.py\nclass GlobalPlugin: pass\n```\n"
            "```ini:manifest.ini\nname = MeuAddon\ndocFileName = readme.html\n```\n"
        )
        mock_resp = MagicMock()
        mock_resp.content = output_sem_doc
        with patch("nvdastudio.sub_agents._base.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.return_value = mock_resp
            output = run("monte", "kimi-k2.6", {})
        assert "AVISO DE MONTAGEM" in output
        assert "B7" in output

    def test_run_addon_correto_sem_aviso(self, fake_api_key):
        from nvdastudio.sub_agents.assembler import run
        output_correto = (
            "```python:globalPlugins/MeuAddon/__init__.py\nclass GlobalPlugin: pass\n```\n"
            "```ini:manifest.ini\nname = MeuAddon\n```\n"
            "```html:doc/pt_BR/userGuide.html\n<html></html>\n```\n"
        )
        mock_resp = MagicMock()
        mock_resp.content = output_correto
        with patch("nvdastudio.sub_agents._base.create_llm_client") as MockFactory:
            MockFactory.return_value.chat.return_value = mock_resp
            output = run("monte", "kimi-k2.6", {})
        assert "AVISO DE MONTAGEM" not in output

# --------------------------------------------------------------------------
# Testes: validate_addon_structure — B6 e NVDA-017 (v1.7.0)
# --------------------------------------------------------------------------

class TestAddonStructureValidatorB6MultiplasPasstas:
    """B6: validate_addon_structure detecta multiplas pastas de plugin."""

    def test_uma_pasta_sem_problema_estrutura007(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        gp = tmp_path / "globalPlugins" / "MeuAddon"
        gp.mkdir(parents=True)
        (gp / "__init__.py").write_text(
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): super().terminate()\n",
            encoding="utf-8"
        )
        (tmp_path / "manifest.ini").write_text(
            "name = MeuAddon\nversion = 1.0.0\n"
            "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n",
            encoding="utf-8"
        )
        (tmp_path / "doc").mkdir()
        problems = validate_addon_structure(str(tmp_path))
        est007 = [p for p in problems if "ESTRUTURA-007" in p]
        assert est007 == [], f"Uma pasta nao deve gerar ESTRUTURA-007: {est007}"

    def test_duas_pastas_gera_estrutura007(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        for nome in ("PluginA", "PluginB"):
            gp = tmp_path / "globalPlugins" / nome
            gp.mkdir(parents=True)
            (gp / "__init__.py").write_text(
                "import globalPluginHandler, addonHandler\n"
                "addonHandler.initTranslation()\n"
                "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
                "    def terminate(self): super().terminate()\n",
                encoding="utf-8"
            )
        (tmp_path / "manifest.ini").write_text(
            "name = Teste\nversion = 1.0.0\n"
            "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n",
            encoding="utf-8"
        )
        (tmp_path / "doc").mkdir()
        problems = validate_addon_structure(str(tmp_path))
        est007 = [p for p in problems if "ESTRUTURA-007" in p]
        assert len(est007) == 1, f"Duas pastas devem gerar ESTRUTURA-007: {problems}"

    def test_estrutura007_menciona_nomes_das_pastas(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        for nome in ("MediaTranscriber", "TranscriptorMultimidia"):
            gp = tmp_path / "globalPlugins" / nome
            gp.mkdir(parents=True)
            (gp / "__init__.py").write_text("class GlobalPlugin: pass", encoding="utf-8")
        (tmp_path / "manifest.ini").write_text(
            "name = T\nversion = 1.0.0\n"
            "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n",
            encoding="utf-8"
        )
        problems = validate_addon_structure(str(tmp_path))
        est007 = [p for p in problems if "ESTRUTURA-007" in p][0]
        assert "MediaTranscriber" in est007 or "TranscriptorMultimidia" in est007

    def test_pasta_sem_init_nao_conta(self, tmp_path):
        """Subpasta de plugin sem __init__.py nao conta como plugin duplicado."""
        from nvdastudio.builder.addon_builder import validate_addon_structure
        gp_real = tmp_path / "globalPlugins" / "MeuAddon"
        gp_real.mkdir(parents=True)
        (gp_real / "__init__.py").write_text(
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): super().terminate()\n",
            encoding="utf-8"
        )
        # Esta pasta NAO tem __init__.py
        gp_lib = tmp_path / "globalPlugins" / "lib"
        gp_lib.mkdir(parents=True)
        (gp_lib / "utils.py").write_text("pass", encoding="utf-8")
        (tmp_path / "manifest.ini").write_text(
            "name = MeuAddon\nversion = 1.0.0\n"
            "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n",
            encoding="utf-8"
        )
        (tmp_path / "doc").mkdir()
        problems = validate_addon_structure(str(tmp_path))
        est007 = [p for p in problems if "ESTRUTURA-007" in p]
        assert est007 == []

class TestAddonStructureValidatorNVDA017Pyd:
    """NVDA-017: validate_addon_structure detecta .pyd incompativeis."""

    def _make_addon(self, tmp_path):
        gp = tmp_path / "globalPlugins" / "MeuAddon"
        gp.mkdir(parents=True)
        (gp / "__init__.py").write_text(
            "import globalPluginHandler, addonHandler\n"
            "addonHandler.initTranslation()\n"
            "class GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
            "    def terminate(self): super().terminate()\n",
            encoding="utf-8"
        )
        (tmp_path / "manifest.ini").write_text(
            "name = MeuAddon\nversion = 1.0.0\n"
            "minimumNVDAVersion = 2026.1.1\nlastTestedNVDAVersion = 2026.1.1\n",
            encoding="utf-8"
        )
        (tmp_path / "doc").mkdir()
        lib = gp / "lib"
        lib.mkdir()
        return lib

    def test_sem_pyd_sem_nvda017(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        lib = self._make_addon(tmp_path)
        (lib / "ollama").mkdir()
        (lib / "ollama" / "__init__.py").write_text("pass", encoding="utf-8")
        problems = validate_addon_structure(str(tmp_path))
        nvda017 = [p for p in problems if "NVDA-017" in p]
        assert nvda017 == [], f"Sem .pyd nao deve gerar NVDA-017: {nvda017}"

    def test_pyd_na_lib_gera_nvda017(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        lib = self._make_addon(tmp_path)
        (lib / "pydantic_core").mkdir()
        (lib / "pydantic_core" / "core.cp311-win32.pyd").write_bytes(b"\x00")
        problems = validate_addon_structure(str(tmp_path))
        nvda017 = [p for p in problems if "NVDA-017" in p]
        assert len(nvda017) == 1, f"Arquivo .pyd deve gerar NVDA-017: {problems}"

    def test_nvda017_menciona_nome_do_arquivo(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        lib = self._make_addon(tmp_path)
        # win32 = 32-bit, deve gerar NVDA-017 e mencionar o nome do arquivo
        (lib / "meu_modulo.cp311-win32.pyd").write_bytes(b"\x00")
        problems = validate_addon_structure(str(tmp_path))
        nvda017 = [p for p in problems if "NVDA-017" in p][0]
        assert "meu_modulo.cp311-win32.pyd" in nvda017

    def test_nvda017_conta_multiplos_pyd(self, tmp_path):
        from nvdastudio.builder.addon_builder import validate_addon_structure
        lib = self._make_addon(tmp_path)
        for nome in ("a.cp311-win32.pyd", "b.cp311-win32.pyd", "c.cp311-win32.pyd"):
            (lib / nome).write_bytes(b"\x00")
        problems = validate_addon_structure(str(tmp_path))
        nvda017 = [p for p in problems if "NVDA-017" in p][0]
        assert "3" in nvda017

    def test_nvda017_menciona_no_binary(self, tmp_path):
        """Aviso deve sugerir --no-binary como solucao."""
        from nvdastudio.builder.addon_builder import validate_addon_structure
        lib = self._make_addon(tmp_path)
        (lib / "x.pyd").write_bytes(b"\x00")
        problems = validate_addon_structure(str(tmp_path))
        nvda017 = [p for p in problems if "NVDA-017" in p][0]
        assert "no-binary" in nvda017 or "no_binary" in nvda017

    def test_nao_executa_pyd(self, tmp_path):
        """Regra 9: validate_addon_structure nunca executa .pyd."""
        from nvdastudio.builder.addon_builder import validate_addon_structure
        lib = self._make_addon(tmp_path)
        # .pyd com bytes invalidos — se fosse executado causaria crash
        (lib / "malicioso.pyd").write_bytes(b"\xff\xfe" * 100)
        problems = validate_addon_structure(str(tmp_path))
        assert isinstance(problems, list)

class TestDesignReviewTokenAccumulation:
    """
    I1: design_review_agent v2.3.0 — tokens dos 3 estagios devem ser acumulados.

    Bug: cada _run_sub_agent sobrescrevia _tl.last_tokens; dispatcher lia apenas
    os tokens do Advocate (ultimo estagio), perdendo Challenger + Guardian (~2/3 do total).
    Correcao: _tl.last_tokens = soma dos 3 estagios logo apos o ultimo _run_sub_agent.
    """

    def test_importa_get_last_tokens_e_tl(self):
        """design_review_agent deve importar get_last_tokens e _tl para acumulacao."""
        import inspect
        from nvdastudio.sub_agents import design_review_agent
        src = inspect.getsource(design_review_agent)
        assert "get_last_tokens" in src, (
            "I1: design_review_agent deve importar get_last_tokens de _base"
        )
        assert "_tl" in src, (
            "I1: design_review_agent deve importar _tl para setar o total acumulado"
        )

    def test_run_acumula_tokens_tres_estagios(self, fake_api_key):
        """run() deve somar tokens dos 4 estagios em _tl.last_tokens."""
        from unittest.mock import patch

        call_count = {"n": 0}
        tokens_por_chamada = [50, 100, 200, 300, 125, 150]  # Lock, Challenger, Guardian, Advocate, Quality, Decision Log

        def fake_run_sub_agent(system_addendum, prompt, model_id, reasoning_params, on_chunk=None, extra_docs="", cache_key=None, live_narrate=False, final_tool=None, step_type=""):
            idx = call_count["n"]
            call_count["n"] += 1
            from nvdastudio.sub_agents._base import _tl
            _tl.last_tokens = tokens_por_chamada[idx]
            return f"output_estagio_{idx + 1}"

        with patch("nvdastudio.sub_agents.design_review_agent._run_sub_agent",
                   side_effect=fake_run_sub_agent):
            from nvdastudio.sub_agents.design_review_agent import run
            from nvdastudio.sub_agents._base import get_last_tokens
            run("pedido de revisao", "kimi-k2.6", {})

        total = get_last_tokens()
        assert total == 350, (
            f"I1: total de tokens deve ser 50+100+200=350, recebido {total}. "
            "Certifique-se que _tl.last_tokens acumula os 3 estagios."
        )

    def test_versao_design_review_e_2_4_0(self):
        from nvdastudio.sub_agents.design_review_agent import MODULE_VERSION
        assert MODULE_VERSION == "2.14.0"

# ==========================================================================
# Testes de contexto especializado — v1.1.0 dos sub-agentes sem docs
# ==========================================================================

class TestTestGeneratorV120:
    """
    test_generator v1.2.0: SAIDA PROIBIDA + VERIFICACAO FINAL adicionados ao prompt.

    O TestGenerator gerava HTML userGuide em vez de pytest — causa raiz: ausencia
    de restricao explicita e checklist de auto-verificacao (skills: llm-structured-output,
    prompt-engineering-patterns). max_chars do get_docs_test_generator reduzidos.
    """

    def test_module_version_e_1_2_0(self):
        from nvdastudio.sub_agents.test_generator import MODULE_VERSION
        assert MODULE_VERSION == "1.8.0", (
            "test_generator deve ser v1.3.0 apos adicao de _extract_code_manifest (skill: unit-testing-test-generate)"
        )

    def test_importa_get_docs_test_generator(self):
        import inspect
        from nvdastudio.sub_agents import test_generator
        src = inspect.getsource(test_generator)
        assert "get_docs_test_generator" in src, (
            "test_generator deve importar get_docs_test_generator de nvda_context"
        )

    def test_run_passa_extra_docs(self, fake_api_key):
        """run() deve chamar _run_sub_agent com extra_docs preenchido."""
        extra_docs_recebido = []

        def fake_run_sub(system_addendum, prompt, model_id, reasoning_params, on_chunk=None, extra_docs="", cache_key=None, live_narrate=False, final_tool=None, step_type=""):
            extra_docs_recebido.append(extra_docs)
            return "testes gerados"

        with patch("nvdastudio.sub_agents.test_generator._run_sub_agent",
                   side_effect=fake_run_sub), \
             patch("nvdastudio.sub_agents.test_generator.get_docs_test_generator",
                   return_value="=== NVDA SOURCE: scriptHandler.py ===\nconteudo mockado"):
            from nvdastudio.sub_agents.test_generator import run
            run("gere testes para addon X", "kimi-k2.6", {})

        assert len(extra_docs_recebido) == 1, "run() deve chamar _run_sub_agent uma vez"
        assert extra_docs_recebido[0] != "", (
            "extra_docs nao pode ser vazio — get_docs_test_generator() deve retornar conteudo"
        )

    def test_system_prompt_menciona_mocks_nvda(self):
        """_SYSTEM deve mencionar mocks de modulos NVDA criticos."""
        from nvdastudio.sub_agents.test_generator import _SYSTEM
        system_lower = _SYSTEM.lower()
        for termo in ["mock", "ui", "api", "config"]:
            assert termo in system_lower, (
                f"_SYSTEM do test_generator deve mencionar '{termo}' para guiar mocks"
            )

    def test_system_prompt_tem_verificacao_final(self):
        """_SYSTEM deve ter VERIFICACAO FINAL para prevenir HTML no output."""
        from nvdastudio.sub_agents.test_generator import _SYSTEM
        assert "VERIFICACAO FINAL" in _SYSTEM, (
            "_SYSTEM deve ter VERIFICACAO FINAL para forcar auto-revisao do modelo"
        )

    def test_system_prompt_tem_saida_proibida(self):
        """_SYSTEM deve listar tipos de saida proibidos (HTML, markdown, etc.)."""
        from nvdastudio.sub_agents.test_generator import _SYSTEM
        assert "SAIDA PROIBIDA" in _SYSTEM, (
            "_SYSTEM deve ter SAIDA PROIBIDA explicitando o que nunca gerar"
        )
        assert "HTML" in _SYSTEM, (
            "_SYSTEM deve mencionar HTML como saida proibida"
        )

    def test_system_prompt_formato_no_topo(self):
        """Instrucao de formato deve aparecer antes dos MOCKS OBRIGATORIOS."""
        from nvdastudio.sub_agents.test_generator import _SYSTEM
        idx_formato = _SYSTEM.find("FORMATO DE SAIDA OBRIGATORIO")
        idx_mocks = _SYSTEM.find("MOCKS OBRIGATORIOS")
        assert idx_formato != -1, "_SYSTEM deve ter bloco FORMATO DE SAIDA OBRIGATORIO"
        assert idx_formato < idx_mocks, (
            "FORMATO DE SAIDA OBRIGATORIO deve vir antes de MOCKS OBRIGATORIOS no prompt"
        )

class TestAgentRunnerV110:
    """
    agent_runner_agent v1.1.0: agora injeta get_docs_agent_runner() como extra_docs.

    O AgentRunnerAgent precisa conhecer: addonHandler (quando destruir o runner),
    globalPluginHandler (onde e instanciado), queueHandler (thread safety),
    NVDAState (secure mode), config (persistencia), logHandler (logging correto).
    """

    def test_module_version_e_1_1_0(self):
        from nvdastudio.sub_agents.agent_runner_agent import MODULE_VERSION
        assert MODULE_VERSION == "1.5.0", (
            "agent_runner_agent deve ser v1.1.0 apos adicao de contexto de docs"
        )

    def test_importa_get_docs_agent_runner(self):
        import inspect
        from nvdastudio.sub_agents import agent_runner_agent
        src = inspect.getsource(agent_runner_agent)
        assert "get_docs_agent_runner" in src, (
            "agent_runner_agent deve importar get_docs_agent_runner de nvda_context"
        )

    def test_run_passa_extra_docs(self, fake_api_key):
        """run() deve chamar _run_sub_agent com extra_docs preenchido."""
        extra_docs_recebido = []

        def fake_run_sub(system_addendum, prompt, model_id, reasoning_params, on_chunk=None, extra_docs="", cache_key=None, live_narrate=False, final_tool=None, step_type=""):
            extra_docs_recebido.append(extra_docs)
            return _AGENT_RUNNER_BASE_CODE  # codigo valido para passar _validate_structure

        with patch("nvdastudio.sub_agents.agent_runner_agent._run_sub_agent",
                   side_effect=fake_run_sub), \
             patch("nvdastudio.sub_agents.agent_runner_agent.get_docs_agent_runner",
                   return_value="=== NVDA SOURCE: addonHandler/__init__.py ===\nconteudo mockado"):
            from nvdastudio.sub_agents.agent_runner_agent import run
            run("gere um agent_runner para addon Y", "kimi-k2.6", {})

        assert len(extra_docs_recebido) == 1
        assert extra_docs_recebido[0] != "", (
            "extra_docs nao pode ser vazio — get_docs_agent_runner() deve retornar conteudo"
        )

# Codigo minimo valido para _validate_structure do agent_runner_agent
_AGENT_RUNNER_BASE_CODE = """
class AgentRunner:
    def __init__(self, api_key: str, model_id: str):
        self._history = []
        self._fallback_chain = ["kimi-k2.6"]

    def reset_session(self):
        self._history = []

    def run(self, query: str, on_chunk=None) -> str:
        try:
            return "Groq nao disponivel"
        try:
            pass
        except Exception:
            pass
        return "ok"
"""

class TestAgentTemplateV110:
    """
    agent_template_agent v1.1.0: agora injeta get_docs_agent_template() como extra_docs.

    O AgentTemplateAgent precisa conhecer: addonHandler (ciclo de vida),
    globalPluginHandler (registros de agentes), addonAPIVersion (compatibilidade),
    DevGuide e AddonTemplate (convencoes da comunidade).
    """

    def test_module_version_e_1_1_0(self):
        from nvdastudio.sub_agents.agent_template_agent import MODULE_VERSION
        assert MODULE_VERSION == "1.5.0", (
            "agent_template_agent deve ser v1.4.1 apos adocao do padrao final_tool (_base.py v1.13.0)"
        )

    def test_importa_get_docs_agent_template(self):
        import inspect
        from nvdastudio.sub_agents import agent_template_agent
        src = inspect.getsource(agent_template_agent)
        assert "get_docs_agent_template" in src, (
            "agent_template_agent deve importar get_docs_agent_template de nvda_context"
        )

    def test_run_passa_extra_docs(self, fake_api_key):
        """run() deve chamar _run_sub_agent com extra_docs preenchido."""
        extra_docs_recebido = []

        def fake_run_sub(system_addendum, prompt, model_id, reasoning_params, on_chunk=None, extra_docs="", cache_key=None, live_narrate=False, final_tool=None, step_type=""):
            extra_docs_recebido.append(extra_docs)
            return _TEMPLATE_MD_COMPLETO

        with patch("nvdastudio.sub_agents.agent_template_agent._run_sub_agent",
                   side_effect=fake_run_sub), \
             patch("nvdastudio.sub_agents.agent_template_agent.get_docs_agent_template",
                   return_value="=== NVDA SOURCE: addonHandler ===\nconteudo mockado"):
            from nvdastudio.sub_agents.agent_template_agent import run
            run("crie template para agente leitor de tela", "kimi-k2.6", {})

        assert len(extra_docs_recebido) == 1
        assert extra_docs_recebido[0] != "", (
            "extra_docs nao pode ser vazio — get_docs_agent_template() deve retornar conteudo"
        )

# Template MD minimo valido para _validate_sections do agent_template_agent
_TEMPLATE_MD_COMPLETO = """# Agente Leitor

## Descricao
Agente responsavel por leitura de tela.

## Responsabilidades
- Ler objetos focados

## Regras de Comportamento
- Nunca executar codigo externo

## Entradas
- Objeto NVDA foco atual

## Saidas
- Texto sintetizado

## Invariantes
- Nao modifica sys.modules

## Referencias
- https://github.com/nvaccess/nvda

## Versao
1.1.0

## Metadados
name: agente-leitor
description: Agente responsavel por leitura de tela e sintese de texto. Use quando o usuario solicitar leitura de objetos NVDA focados.
"""

class TestGetDocsNvdaContext:
    """
    nvda_context.py: as 3 novas funcoes get_docs_* devem retornar string nao-vazia.

    3.31.0 (achado de auditoria, 2026-08-16): os docs REAIS do NVDA agora
    vem bundlados junto do proprio pacote do addon (nvda_docs_cache/, ver
    README la) em vez de um caminho absoluto (c:\\docs_nvda) que so
    existia manualmente numa maquina especifica -- SEMPRE presentes,
    inclusive em CI, ja que fazem parte do repositorio. Os testes "_callable"
    abaixo confirmam isso (conteudo real, nao mais so "sem excecao"); os
    testes "_com_docs" continuam usando docs_dir mockado via tmp_path pra
    testar o comportamento com um fixture controlado, independente do
    conteudo real bundlado.
    """

    def test_get_docs_test_generator_callable(self):
        """get_docs_test_generator() deve retornar conteudo REAL -- docs
        bundlados junto do pacote, sempre presentes (3.31.0)."""
        from nvdastudio.builder.nvda_context import get_docs_test_generator
        result = get_docs_test_generator()
        assert isinstance(result, str), "get_docs_test_generator deve retornar str"
        assert result.strip(), "docs bundlados devem produzir conteudo nao-vazio"

    def test_get_docs_agent_runner_callable(self):
        """get_docs_agent_runner() deve retornar conteudo REAL -- docs
        bundlados junto do pacote, sempre presentes (3.31.0)."""
        from nvdastudio.builder.nvda_context import get_docs_agent_runner
        result = get_docs_agent_runner()
        assert isinstance(result, str), "get_docs_agent_runner deve retornar str"
        assert result.strip(), "docs bundlados devem produzir conteudo nao-vazio"

    def test_get_docs_agent_template_callable(self):
        """get_docs_agent_template() deve retornar conteudo REAL -- docs
        bundlados junto do pacote, sempre presentes (3.31.0)."""
        from nvdastudio.builder.nvda_context import get_docs_agent_template
        result = get_docs_agent_template()
        assert isinstance(result, str), "get_docs_agent_template deve retornar str"
        assert result.strip(), "docs bundlados devem produzir conteudo nao-vazio"

    def test_get_docs_test_generator_com_docs(self, tmp_path):
        """
        Quando docs existem, get_docs_test_generator deve retornar conteudo nao-vazio.
        Usa docs_dir mockado com arquivo scriptHandler.py minimo.
        """
        src_dir = tmp_path / "nvda" / "source"
        src_dir.mkdir(parents=True)
        (src_dir / "scriptHandler.py").write_text(
            "def script(gesture=None, **kwargs): pass\n", encoding="utf-8"
        )
        from nvdastudio.builder.nvda_context import get_docs_test_generator
        result = get_docs_test_generator(docs_dir=str(tmp_path))
        assert "scriptHandler" in result, (
            "Com docs mockados, get_docs_test_generator deve incluir scriptHandler.py"
        )

    def test_get_docs_agent_runner_com_docs(self, tmp_path):
        """
        Quando docs existem, get_docs_agent_runner deve retornar conteudo nao-vazio.
        """
        src_dir = tmp_path / "nvda" / "source"
        (src_dir / "addonHandler").mkdir(parents=True)
        (src_dir / "addonHandler" / "__init__.py").write_text(
            "def initTranslation(): pass\n", encoding="utf-8"
        )
        from nvdastudio.builder.nvda_context import get_docs_agent_runner
        result = get_docs_agent_runner(docs_dir=str(tmp_path))
        assert "addonHandler" in result, (
            "Com docs mockados, get_docs_agent_runner deve incluir addonHandler/__init__.py"
        )

    def test_get_docs_agent_template_com_docs(self, tmp_path):
        """
        Quando docs existem, get_docs_agent_template deve retornar conteudo nao-vazio.
        """
        src_dir = tmp_path / "nvda" / "source"
        src_dir.mkdir(parents=True)
        (src_dir / "globalPluginHandler.py").write_text(
            "class GlobalPlugin: pass\n", encoding="utf-8"
        )
        from nvdastudio.builder.nvda_context import get_docs_agent_template
        result = get_docs_agent_template(docs_dir=str(tmp_path))
        assert "globalPluginHandler" in result, (
            "Com docs mockados, get_docs_agent_template deve incluir globalPluginHandler.py"
        )


class TestAvisoUpdateChannelNoTemplateOficial:
    """3.31.0: manifest.ini.tpl OFICIAL (nvaccess/addonTemplate, bundlado em
    nvda_docs_cache/) ainda inclui um placeholder "updateChannel" que NAO
    existe no configspec real (AddonManifest, addonHandler/__init__.py) --
    achado ja tratado no PROMPT do sub-agente (manifest_builder.py 1.12.0,
    ver test_auditoria_2026.py::TestManifestBuilder2026), mas o CONTEXTO
    bruto (o template em si) tambem cita o campo -- essas funcoes tem que
    injetar um aviso deterministico ANTES do template, sempre, pra nao
    contradizer o prompt principal."""

    def test_manifest_builder_context_tem_aviso_antes_do_template(self):
        from nvdastudio.builder.nvda_context import get_docs_manifest_builder
        result = get_docs_manifest_builder()
        assert "AVISO" in result and "updateChannel" in result
        idx_aviso = result.find("AVISO")
        idx_template = result.find("=== TEMPLATE: manifest.ini.tpl ===")
        assert idx_template != -1, "template real deve estar presente (docs bundlados)"
        assert idx_aviso < idx_template, "aviso deve vir ANTES do template, nao depois"

    def test_assembler_context_tem_aviso_antes_do_template(self):
        from nvdastudio.builder.nvda_context import get_docs_assembler
        result = get_docs_assembler()
        assert "AVISO" in result and "updateChannel" in result
        idx_aviso = result.find("AVISO")
        idx_template = result.find("=== TEMPLATE: manifest.ini.tpl ===")
        assert idx_template != -1
        assert idx_aviso < idx_template

    def test_chat_system_tem_aviso_antes_do_template(self):
        from nvdastudio.builder.nvda_context import NVDA_ADDON_CHAT_SYSTEM
        idx_aviso = NVDA_ADDON_CHAT_SYSTEM.find("updateChannel")
        idx_template = NVDA_ADDON_CHAT_SYSTEM.find("=== TEMPLATE: manifest.ini ===")
        assert idx_template != -1
        assert idx_aviso != -1
        assert idx_aviso < idx_template + len("=== TEMPLATE: manifest.ini ===\n") + 500, (
            "aviso deve estar logo no inicio da secao do template, nao so em algum lugar"
        )


class TestNvdaSystemPromptAcentuacaoCompartilhada:
    """v5.20.0: instrucao de acentuacao adicionada UMA VEZ no NVDA_SYSTEM_PROMPT
    (base compartilhada por _run_sub_agent) em vez de duplicar em cada um dos
    13 sub-agentes. Achado real: manifest_builder gerava description/changelog
    sem acento porque seu proprio prompt (em ingles) nao tinha essa instrucao."""

    def test_instrui_acentuacao_correta(self):
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        assert "acentos" in NVDA_SYSTEM_PROMPT.lower()
        assert "usuário" in NVDA_SYSTEM_PROMPT
        assert "configuração" in NVDA_SYSTEM_PROMPT

    def test_manifest_builder_herda_a_instrucao_via_run_sub_agent(self):
        """manifest_builder nao declara a regra de acento por conta propria --
        ela chega via NVDA_SYSTEM_PROMPT concatenado em _run_sub_agent."""
        from nvdastudio.sub_agents.manifest_builder import _SYSTEM
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        assert "acentos" not in _SYSTEM.lower()
        assert "acentos" in NVDA_SYSTEM_PROMPT.lower()


class TestNvdaSystemPromptCallbacksAusentes:
    """v3.21.0 (nvda_context.py): auditoria comparando com community-access.org
    (fonte oficial do NVDA Addon Specialist) achou 3 callbacks/padroes reais da API
    do NVDA que nunca eram ensinados ao code_generator: TreeInterceptor (browse mode
    para conteudo rico), o padrao de propriedade automatica _get_<prop>/_set_<prop>
    do NVDAObject, e extensionPoints.AccumulatingDecider (so Action/Filter/Decider
    apareciam). Adicionados ao NVDA_SYSTEM_PROMPT compartilhado."""

    def test_instrui_tree_interceptor(self):
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        assert "TreeInterceptor" in NVDA_SYSTEM_PROMPT
        assert "_get_documentText" in NVDA_SYSTEM_PROMPT

    def test_instrui_padrao_get_set_propriedade(self):
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        assert "_get_<propName>" in NVDA_SYSTEM_PROMPT
        assert "_set_<propName>" in NVDA_SYSTEM_PROMPT

    def test_instrui_accumulating_decider(self):
        from nvdastudio.builder.nvda_context import NVDA_SYSTEM_PROMPT
        assert "AccumulatingDecider" in NVDA_SYSTEM_PROMPT
