import json
import pytest
from unittest.mock import MagicMock, patch
from addon.globalPlugins.nvdastudio.core.planner import Planner, MODULE_VERSION


class TestPlannerVersao:
    def test_versao_e_1_7_0(self):
        assert MODULE_VERSION == "2.34.0"


class TestPlannerJsonSchema:
    """_call_planner_llm deve passar json_schema como response_format."""

    def test_usa_json_schema_no_formato(self):
        """Verifica que response_format contém type=json_schema."""
        chat_calls = []

        def mock_chat(prompt, **kwargs):
            chat_calls.append(kwargs)
            resp = MagicMock()
            resp.content = '{"complexity":"low","requires_web_research":false,"requires_agent_runner":false,"assembling_message":"ok","completed_message":"ok","dependencies":[],"steps":[]}'
            resp.reasoning = None
            return resp

        mock_client = MagicMock()
        mock_client.chat.side_effect = mock_chat

        with patch("addon.globalPlugins.nvdastudio.core.planner.create_llm_client", return_value=mock_client):
            planner = Planner()
            planner._call_planner_llm("crie um addon simples")

        assert len(chat_calls) > 0
        fmt = chat_calls[0].get("response_format", {})
        assert fmt.get("type") == "json_schema", f"Esperado json_schema, recebido: {fmt}"

    def test_json_schema_tem_campo_steps(self):
        """O schema deve definir o campo 'steps' como obrigatório."""
        chat_calls = []

        def mock_chat(prompt, **kwargs):
            chat_calls.append(kwargs)
            resp = MagicMock()
            resp.content = '{"complexity":"low","requires_web_research":false,"requires_agent_runner":false,"assembling_message":"ok","completed_message":"ok","dependencies":[],"steps":[]}'
            resp.reasoning = None
            return resp

        mock_client = MagicMock()
        mock_client.chat.side_effect = mock_chat

        with patch("addon.globalPlugins.nvdastudio.core.planner.create_llm_client", return_value=mock_client):
            planner = Planner()
            planner._call_planner_llm("addon de teste")

        fmt = chat_calls[0].get("response_format", {})
        schema = fmt.get("json_schema", {}).get("schema", {})
        required = schema.get("required", [])
        assert "steps" in required

    def test_json_schema_tem_campo_complexity(self):
        """O schema deve incluir 'complexity' como campo obrigatório."""
        chat_calls = []

        def mock_chat(prompt, **kwargs):
            chat_calls.append(kwargs)
            resp = MagicMock()
            resp.content = '{"complexity":"low","requires_web_research":false,"requires_agent_runner":false,"assembling_message":"ok","completed_message":"ok","dependencies":[],"steps":[]}'
            resp.reasoning = None
            return resp

        mock_client = MagicMock()
        mock_client.chat.side_effect = mock_chat

        with patch("addon.globalPlugins.nvdastudio.core.planner.create_llm_client", return_value=mock_client):
            planner = Planner()
            planner._call_planner_llm("addon de teste")

        fmt = chat_calls[0].get("response_format", {})
        schema = fmt.get("json_schema", {}).get("schema", {})
        required = schema.get("required", [])
        assert "complexity" in required

    def test_json_schema_exige_apresentacao_e_confirmacoes_da_ia(self):
        chat_calls = []

        def mock_chat(prompt, **kwargs):
            chat_calls.append(kwargs)
            resp = MagicMock()
            resp.content = '{}'
            resp.reasoning = None
            return resp

        mock_client = MagicMock()
        mock_client.chat.side_effect = mock_chat

        with patch("addon.globalPlugins.nvdastudio.core.planner.create_llm_client", return_value=mock_client):
            Planner()._call_planner_llm("addon de teste")

        schema = chat_calls[0]["response_format"]["json_schema"]["schema"]
        required = set(schema["required"])
        assert {
            "plan_presentation", "approval_message",
            "cancellation_message", "modification_message",
        } <= required

    def test_llm_error_propagado(self):
        """Se o cliente LLM falhar, LLMClientError deve ser propagado."""
        from nvdastudio.ai.llm_factory import LLMClientError

        mock_client = MagicMock()
        mock_client.chat.side_effect = LLMClientError("modelo falhou")

        with patch("addon.globalPlugins.nvdastudio.core.planner.create_llm_client", return_value=mock_client):
            planner = Planner()
            with pytest.raises(LLMClientError):
                planner._call_planner_llm("addon de teste")

    def test_json_schema_nome_e_execution_plan(self):
        """O schema deve ter name='execution_plan'."""
        chat_calls = []

        def mock_chat(prompt, **kwargs):
            chat_calls.append(kwargs)
            resp = MagicMock()
            resp.content = '{"complexity":"low","requires_web_research":false,"requires_agent_runner":false,"assembling_message":"ok","completed_message":"ok","dependencies":[],"steps":[]}'
            resp.reasoning = None
            return resp

        mock_client = MagicMock()
        mock_client.chat.side_effect = mock_chat

        with patch("addon.globalPlugins.nvdastudio.core.planner.create_llm_client", return_value=mock_client):
            planner = Planner()
            planner._call_planner_llm("addon de teste")

        fmt = chat_calls[0].get("response_format", {})
        name = fmt.get("json_schema", {}).get("name", "")
        assert name == "execution_plan"


class TestPlannerNarracaoAoVivoViaToolCall:
    """create_plan()/_call_planner_llm() com on_narration_chunk (v2.13.0):
    troca json_schema por uma tool call obrigatoria ("entregar_plano") --
    o modelo narra livre no content ANTES de chamar a tool (visivel ao
    vivo via on_narration_chunk == on_chunk), e o plano vem do argumento
    dela. Sem on_narration_chunk, o caminho antigo (json_schema, mudo)
    continua exatamente como era -- risco minimizado no modulo mais
    central do pipeline."""

    _PLAN_DICT = {
        "complexity": "low", "requires_web_research": False,
        "requires_agent_runner": False, "assembling_message": "ok",
        "completed_message": "ok", "dependencies": [], "steps": [],
    }
    _PLAN_JSON = json.dumps(_PLAN_DICT)

    def _mock_client_json_schema(self):
        mock_client = MagicMock()
        resp = MagicMock()
        resp.content = self._PLAN_JSON
        resp.tool_calls = None
        mock_client.chat.return_value = resp
        return mock_client

    def _mock_client_tool_call(self):
        mock_client = MagicMock()
        resp = MagicMock()
        resp.content = "narrando o plano..."
        tc = MagicMock()
        tc.function.name = "entregar_plano"
        tc.function.arguments = dict(self._PLAN_DICT)
        resp.tool_calls = [tc]
        mock_client.chat.return_value = resp
        return mock_client

    def test_sem_callback_usa_json_schema_como_antes(self):
        mock_client = self._mock_client_json_schema()
        with patch("addon.globalPlugins.nvdastudio.core.planner.create_llm_client", return_value=mock_client):
            raw = Planner()._call_planner_llm("addon de teste")
        _, kwargs = mock_client.chat.call_args
        assert kwargs.get("response_format", {}).get("type") == "json_schema"
        assert "tools" not in kwargs
        assert raw == self._PLAN_JSON

    def test_com_callback_usa_tool_call_em_vez_de_json_schema(self):
        callback = MagicMock()
        mock_client = self._mock_client_tool_call()
        with patch("addon.globalPlugins.nvdastudio.core.planner.create_llm_client", return_value=mock_client):
            Planner()._call_planner_llm("addon de teste", on_narration_chunk=callback)
        _, kwargs = mock_client.chat.call_args
        assert "response_format" not in kwargs
        assert kwargs.get("tools")[0]["function"]["name"] == "entregar_plano"
        assert kwargs.get("on_chunk") is callback

    def test_tool_call_devolve_plano_como_json_string_identico_ao_schema(self):
        """_parse_plan()/_build_steps() nao devem precisar saber qual
        caminho gerou o plano -- o retorno tem que ser um JSON string
        parseavel igual ao caminho json_schema."""
        mock_client = self._mock_client_tool_call()
        with patch("addon.globalPlugins.nvdastudio.core.planner.create_llm_client", return_value=mock_client):
            raw = Planner()._call_planner_llm("addon de teste", on_narration_chunk=MagicMock())
        assert json.loads(raw) == self._PLAN_DICT

    def test_fallback_pro_content_se_modelo_nao_chamar_a_tool(self):
        mock_client = MagicMock()
        resp = MagicMock()
        resp.content = self._PLAN_JSON
        resp.tool_calls = None
        mock_client.chat.return_value = resp
        with patch("addon.globalPlugins.nvdastudio.core.planner.create_llm_client", return_value=mock_client):
            raw = Planner()._call_planner_llm("addon de teste", on_narration_chunk=MagicMock())
        assert raw == self._PLAN_JSON

    def test_create_plan_repassa_on_narration_chunk_ate_o_client(self):
        callback = MagicMock()
        mock_client = self._mock_client_tool_call()
        with patch("addon.globalPlugins.nvdastudio.core.planner.create_llm_client", return_value=mock_client), \
             patch("addon.globalPlugins.nvdastudio.gui.settings_panel.get_llm_provider", return_value="openai"), \
             patch("addon.globalPlugins.nvdastudio.gui.settings_panel.get_llm_model", return_value="gpt-5"):
            Planner().create_plan("crie um addon simples", on_narration_chunk=callback)
        _, kwargs = mock_client.chat.call_args
        assert kwargs.get("on_chunk") is callback

    def test_tool_schema_reusa_o_mesmo_schema_do_json_schema(self):
        mock_client = self._mock_client_tool_call()
        with patch("addon.globalPlugins.nvdastudio.core.planner.create_llm_client", return_value=mock_client):
            Planner()._call_planner_llm("addon de teste", on_narration_chunk=MagicMock())
        _, kwargs = mock_client.chat.call_args
        params = kwargs["tools"][0]["function"]["parameters"]
        assert params["type"] == "object"
        assert "steps" in params["properties"]
        assert "addon_name" in params["properties"]
