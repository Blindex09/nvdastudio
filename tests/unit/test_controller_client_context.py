class TestMarcadorDeteccao:
    def test_marker_e_detectado_pelo_proprio_helper(self):
        from nvdastudio.builder.controller_client_context import (
            project_type_marker, is_controller_client_context,
        )
        m = project_type_marker()
        assert is_controller_client_context(m)

    def test_contexto_normal_nao_e_detectado(self):
        from nvdastudio.builder.controller_client_context import is_controller_client_context
        assert not is_controller_client_context("Objetivo deste step: gera o __init__.py")
        assert not is_controller_client_context("")
        assert not is_controller_client_context(None)

    def test_marker_prefixo_estavel(self):
        """O marcador deve comecar com o prefixo que outros modulos
        (orchestrator.py/code_generator.py/critic.py) checam via startswith."""
        from nvdastudio.builder.controller_client_context import project_type_marker
        assert project_type_marker().startswith("[PROJECT_TYPE: controller_client")


class TestCatalogoDeRegras:
    def test_todos_os_ids_seguem_padrao_ctrl_client(self):
        from nvdastudio.builder.controller_client_context import CTRL_CLIENT_RULE_IDS
        assert len(CTRL_CLIENT_RULE_IDS) >= 5
        for rid in CTRL_CLIENT_RULE_IDS:
            assert rid.startswith("CTRL-CLIENT-")

    def test_sem_ids_duplicados(self):
        from nvdastudio.builder.controller_client_context import CTRL_CLIENT_RULE_IDS
        assert len(CTRL_CLIENT_RULE_IDS) == len(set(CTRL_CLIENT_RULE_IDS))

    def test_testifrunning_e_regra_critica(self):
        """CTRL-CLIENT-001 (testIfRunning primeiro) deve ser Critico -- e a
        checagem mais basica, sem ela toda chamada seguinte e as cegas."""
        from nvdastudio.builder.controller_client_context import CTRL_CLIENT_RULES
        rule = next(r for r in CTRL_CLIENT_RULES if r[0] == "CTRL-CLIENT-001")
        assert rule[1] == "Critico"
        assert "testIfRunning" in rule[2]

    def test_regra_proibe_manifest_ini(self):
        """Deve existir uma regra explicita contra gerar manifest.ini/
        globalPlugins/ neste tipo de projeto."""
        from nvdastudio.builder.controller_client_context import CTRL_CLIENT_RULES
        found = [r for r in CTRL_CLIENT_RULES if "manifest.ini" in r[2] or "globalPlugins" in r[2]]
        assert found, "nenhuma regra menciona manifest.ini/globalPlugins"


class TestSystemPrompt:
    def test_prompt_nao_menciona_globalplugin_como_exigencia(self):
        """O prompt de geracao nao pode instruir a criar GlobalPlugin --
        isso e exclusivo do dominio de addon, nao de controller_client."""
        from nvdastudio.builder.controller_client_context import CTRL_CLIENT_SYSTEM_PROMPT
        assert "class GlobalPlugin" not in CTRL_CLIENT_SYSTEM_PROMPT

    def test_prompt_cita_as_4_funcoes_v1_da_api(self):
        from nvdastudio.builder.controller_client_context import CTRL_CLIENT_SYSTEM_PROMPT
        for fn in (
            "nvdaController_testIfRunning",
            "nvdaController_speakText",
            "nvdaController_cancelSpeech",
            "nvdaController_brailleMessage",
        ):
            assert fn in CTRL_CLIENT_SYSTEM_PROMPT

    def test_prompt_template_e_python_valido(self):
        """O bloco de template ```python:nvda_client.py``` embutido no
        prompt deve ser Python sintaticamente valido -- se quebrar, o LLM
        aprende um exemplo com erro de sintaxe."""
        import ast
        import re
        from nvdastudio.builder.controller_client_context import CTRL_CLIENT_SYSTEM_PROMPT
        m = re.search(
            r"```python:nvda_client\.py\n(.*?)```", CTRL_CLIENT_SYSTEM_PROMPT, re.DOTALL
        )
        assert m, "template nvda_client.py nao encontrado no prompt"
        ast.parse(m.group(1))


class TestCriticAddendum:
    def test_addendum_menciona_rejeitar_addon_disfarcado(self):
        """O addendum deve alertar o critic que um GlobalPlugin/manifest.ini
        aparecendo aqui e sinal de roteamento errado, nao codigo valido."""
        from nvdastudio.builder.controller_client_context import CTRL_CLIENT_CRITIC_ADDENDUM
        assert "REJEITAR" in CTRL_CLIENT_CRITIC_ADDENDUM

    def test_addendum_substitui_exigencia_de_manifest_do_assembly(self):
        from nvdastudio.builder.controller_client_context import CTRL_CLIENT_CRITIC_ADDENDUM
        assert "manifest.ini" in CTRL_CLIENT_CRITIC_ADDENDUM
