import ast
import os
import inspect

_STUDIO_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "addon", "globalPlugins", "nvdastudio", "gui", "studio_dialog.py"
)


def _read_studio() -> str:
    with open(_STUDIO_PATH, encoding="utf-8") as f:
        return f.read()


def _class_src(class_name: str) -> str:
    """Extrai codigo-fonte de uma classe via AST — mesmo padrao de test_studio_dialog.py."""
    src = _read_studio()
    lines = src.splitlines()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return "\n".join(lines[node.lineno - 1: node.end_lineno])
    raise ValueError(f"Classe '{class_name}' nao encontrada em studio_dialog.py")


def _method_src(class_name: str, method_name: str) -> str:
    """Extrai codigo-fonte de um metodo via AST."""
    src = _read_studio()
    lines = src.splitlines()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in ast.walk(node):
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    return "\n".join(lines[item.lineno - 1: item.end_lineno])
    raise ValueError(f"Metodo '{class_name}.{method_name}' nao encontrado.")


class TestStudioDialogVersao:
    def test_versao_e_5_2_0(self):
        from nvdastudio.gui.studio_dialog import MODULE_VERSION
        assert MODULE_VERSION == "5.48.0"


class TestChatQuickConfig:
    def test_chat_model_resolvido_por_provider(self):
        src = _method_src("NVDAStudioDialog", "_get_quick_chat_model")
        assert "resolve_provider_tier_model" in src

    def test_chat_usa_tier_leve(self):
        src = _method_src("NVDAStudioDialog", "_get_quick_chat_model")
        assert '"light"' in src

    def test_chat_system_prompt_definido(self):
        from nvdastudio.builder.nvda_context import NVDA_ADDON_CHAT_SYSTEM
        assert len(NVDA_ADDON_CHAT_SYSTEM) > 50

    def test_chat_system_exige_saida_estruturada(self):
        from nvdastudio.builder.nvda_context import NVDA_ADDON_CHAT_SYSTEM
        assert "objeto JSON" in NVDA_ADDON_CHAT_SYSTEM
        assert "run_pipeline" in NVDA_ADDON_CHAT_SYSTEM
        assert "PIPELINE:" not in NVDA_ADDON_CHAT_SYSTEM

    def test_chat_system_menciona_sem_markdown(self):
        from nvdastudio.builder.nvda_context import NVDA_ADDON_CHAT_SYSTEM
        assert "markdown" in NVDA_ADDON_CHAT_SYSTEM.lower()

    def test_chat_system_menciona_leitor_de_telas(self):
        from nvdastudio.builder.nvda_context import NVDA_ADDON_CHAT_SYSTEM
        content = NVDA_ADDON_CHAT_SYSTEM.lower()
        assert "leitor de telas" in content or "cego" in content or "nvda leria" in content


class TestAnnounceEventsExpanded:
    def test_aguardando_usuario_em_announce_events(self):
        from nvdastudio.gui.studio_dialog import _ANNOUNCE_EVENTS
        assert "AGUARDANDO_USUARIO" in _ANNOUNCE_EVENTS

    def test_todos_eventos_originais_presentes(self):
        from nvdastudio.gui.studio_dialog import _ANNOUNCE_EVENTS
        for ev in ("PLANEJANDO", "PLANO_CRIADO", "EXECUTANDO",
                   "CONCLUIDO", "ERRO", "MONTANDO"):
            assert ev in _ANNOUNCE_EVENTS


class TestDialogUiUnificada:
    """v5.0.0: sem notebook, tudo em um painel. Verifica via leitura de codigo-fonte."""

    def test_splitter_na_ui(self):
        src = _method_src("NVDAStudioDialog", "_build_ui")
        assert "SplitterWindow" in src or "splitter" in src.lower()

    def test_sem_notebook(self):
        src = _method_src("NVDAStudioDialog", "_build_ui")
        assert "Notebook" not in src

    def test_sem_duas_abas(self):
        src = _method_src("NVDAStudioDialog", "_build_ui")
        assert "AddPage" not in src

    def test_chat_widgets_no_left_panel(self):
        src = _method_src("NVDAStudioDialog", "_build_left_panel")
        assert "_chat_log" not in src and "_chat_input" not in src
        assert "_log" in src and "_input" in src

    def test_sem_tab_changed(self):
        src = _class_src("NVDAStudioDialog")
        assert "_on_tab_changed" not in src


class TestChatHandlers:
    """Verifica que todos os handlers do chat existem e seguem as regras."""

    def test_on_chat_send_nao_existe(self):
        src = _class_src("NVDAStudioDialog")
        assert "def _on_chat_send" not in src

    def test_on_chat_clear_nao_existe(self):
        src = _class_src("NVDAStudioDialog")
        assert "def _on_chat_clear" not in src

    def test_on_load_addon_folder_existe(self):
        src = _class_src("NVDAStudioDialog")
        assert "def _on_load_addon_folder" in src

    def test_on_load_last_addon_existe(self):
        src = _class_src("NVDAStudioDialog")
        assert "def _on_load_last_addon" in src

    def test_trigger_iterative_pipeline_existe(self):
        src = _class_src("NVDAStudioDialog")
        assert "def _trigger_iterative_pipeline" in src

    def test_on_clarify_needed_existe(self):
        src = _class_src("NVDAStudioDialog")
        assert "def _on_clarify_needed" in src

    def test_load_addon_context_existe(self):
        src = _class_src("NVDAStudioDialog")
        assert "def _load_addon_context" in src

    def test_process_chat_message_nao_executa_output(self):
        """Regra 9: nao executa output da LLM diretamente."""
        src = _method_src("NVDAStudioDialog", "_process_chat_message")
        assert "exec(" not in src
        assert "eval(" not in src

    def test_trigger_pipeline_usa_run_async(self):
        """Pipeline iterativo usa orchestrator.run_async — nao executa codigo."""
        src = _method_src("NVDAStudioDialog", "_trigger_iterative_pipeline")
        assert "run_async" in src

    def test_trigger_pipeline_injeta_contexto_addon(self):
        """Pipeline iterativo inclui contexto do addon na query."""
        src = _method_src("NVDAStudioDialog", "_trigger_iterative_pipeline")
        assert "to_prompt_context" in src or "addon_ctx_text" in src

    def test_chat_history_inicializado_vazio(self):
        """_chat_history inicializa como lista vazia."""
        src = _method_src("NVDAStudioDialog", "__init__")
        assert "_chat_history" in src

    def test_acao_estruturada_dispara_pipeline(self):
        src = _method_src("NVDAStudioDialog", "_process_chat_message")
        assert 'action == "run_pipeline"' in src
        assert "json.loads" in src
        assert "PIPELINE:" not in src

    def test_on_clarify_needed_usa_esclarecimento_inline(self):
        """v5.29.0: ClarificationDialog (popup modal) removido -- esclarecimento
        agora e inline no chat via _ask_clarification_inline, mesmo padrao ja
        usado por aprovacao de plano e checkpoint."""
        src = _method_src("NVDAStudioDialog", "_on_clarify_needed")
        assert "_ask_clarification_inline" in src
        assert "ClarificationDialog" not in src

    def test_ask_clarification_inline_usa_threading_event(self):
        """Sincronizacao correta entre thread UI e thread daemon (Regra 15)."""
        src = _method_src("NVDAStudioDialog", "_ask_clarification_inline")
        assert "_clarification_event" in src and "wait" in src

    def test_chat_input_tem_hint_acessivel(self):
        """Regra 12: campo de input tem hint descritivo para usuario cego."""
        src = _method_src("NVDAStudioDialog", "_build_left_panel")
        assert "SetHint" in src or "hint" in src.lower()

    def test_processo_chat_usa_wx_call_after(self):
        """Regra 15: ui.message e chamadas UI vem de wx.CallAfter."""
        src = _method_src("NVDAStudioDialog", "_process_chat_message")
        assert "wx.CallAfter" in src or "CallAfter" in src

    def test_chat_finish_anuncia_via_ui_message(self):
        """Regra 12: resposta do chat anunciada em voz pelo NVDA."""
        src = _method_src("NVDAStudioDialog", "_chat_finish")
        assert "_speak_message" in src or "ui.message" in src


class TestOrquestradorClarificacaoCallbackRegistrado:
    def test_set_callbacks_assinatura_aceita_on_clarify(self):
        from nvdastudio.core.orchestrator import Orchestrator
        sig = inspect.signature(Orchestrator.set_callbacks)
        assert "on_clarify" in sig.parameters

    def test_on_clarify_default_none(self):
        from nvdastudio.core.orchestrator import Orchestrator
        sig = inspect.signature(Orchestrator.set_callbacks)
        assert sig.parameters["on_clarify"].default is None

    def test_handle_clarification_step_existe(self):
        from nvdastudio.core.orchestrator import Orchestrator
        assert hasattr(Orchestrator, "_handle_clarification_step")

    def test_orchestrator_importa_step_user_clarification(self):
        src_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "addon", "globalPlugins", "nvdastudio", "core", "orchestrator.py"
        )
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        assert "STEP_USER_CLARIFICATION" in src


class TestAddonLoaderIntegracao:
    """addon_loader importado corretamente no studio_dialog."""

    def test_studio_importa_addon_loader(self):
        src = _read_studio()
        assert "addon_loader" in src or "AddonContext" in src

    def test_studio_tem_loaded_addon_context(self):
        src = _method_src("NVDAStudioDialog", "__init__")
        assert "_loaded_addon_context" in src


class TestPlannerVersaoAtualizada:
    def test_versao_e_1_7_0(self):
        from nvdastudio.core.planner import MODULE_VERSION
        assert MODULE_VERSION == "2.31.0"

    def test_step_user_clarification_no_model_map(self):
        from nvdastudio.core.planner import STEP_USER_CLARIFICATION, STEP_MODEL_MAP
        assert STEP_USER_CLARIFICATION in STEP_MODEL_MAP

    def test_step_user_clarification_no_reasoning_map(self):
        from nvdastudio.core.planner import STEP_USER_CLARIFICATION, STEP_REASONING_MAP
        assert STEP_USER_CLARIFICATION in STEP_REASONING_MAP

    def test_plan_system_menciona_user_clarification(self):
        from nvdastudio.core.planner import _PLAN_SYSTEM_PROMPT
        assert "user_clarification" in _PLAN_SYSTEM_PROMPT


class TestConversationalPlanReadyAI:
    def _method_src(self) -> str:
        src = _class_src("NVDAStudioDialog")
        idx = src.find("def _on_conversational_plan_ready")
        assert idx != -1, "_on_conversational_plan_ready ausente"
        next_def = src.find("\n\tdef ", idx + 10)
        return src[idx:next_def] if next_def != -1 else src[idx:]

    def test_on_conversational_plan_ready_calls_llm_client(self):
        m = self._method_src()
        assert "create_llm_client" in m

    def test_on_conversational_plan_ready_has_json_response_format(self):
        m = self._method_src()
        assert "json_object" in m

    def test_on_conversational_plan_ready_no_keyword_lists(self):
        m = self._method_src()
        assert "msg_lower" not in m
        assert "except Exception" in m

    def test_confirmacoes_do_plano_vem_da_ia(self):
        m = self._method_src()
        assert "plan.approval_message" in m
        assert "plan.cancellation_message" in m
        assert "plan.modification_message" in m
        assert "Plano aprovado. Vou iniciar o desenvolvimento." not in m
        assert "Vou ajustar o plano conforme você pediu:" not in m

    def test_on_run_captures_raw_input(self):
        src = _class_src("NVDAStudioDialog")
        idx = src.find("def _on_run")
        assert idx != -1
        next_def = src.find("\n\tdef ", idx + 10)
        on_run_body = src[idx:next_def] if next_def != -1 else src[idx:]
        assert "_raw_plan_approval_input" in on_run_body



class TestChatSystemPromptComCanaisSeparados:
    """A mensagem visível e a especificação interna têm campos distintos."""

    def test_instrui_mensagem_natural_e_acao_estruturada(self):
        from nvdastudio.builder.nvda_context import NVDA_ADDON_CHAT_SYSTEM
        content = NVDA_ADDON_CHAT_SYSTEM.lower()
        assert "message" in content and "acolhedor" in content
        assert "run_pipeline" in content

    def test_instrui_sem_raciocinio_interno(self):
        from nvdastudio.builder.nvda_context import NVDA_ADDON_CHAT_SYSTEM
        content = NVDA_ADDON_CHAT_SYSTEM.lower()
        assert "raciocínio interno" in content

    def test_instrui_parte_tecnica_nunca_mostrada(self):
        from nvdastudio.builder.nvda_context import NVDA_ADDON_CHAT_SYSTEM
        content = NVDA_ADDON_CHAT_SYSTEM.lower()
        assert "canal interno" in content and "task_specification" in content


class TestChatSystemPromptModoAnaliseNaoVirarAuditoria:
    """v3.20.0 (nvda_context.py): bug real de live-test -- usuario pediu para
    revisar um addon carregado e a IA respondeu no formato interno do
    design_review_agent.py (SUPOSICOES QUE PODEM ESTAR ERRADAS, IMPLEMENTATION
    CONTRACT, checklist NVDA-001..N). O prompt so tinha instrucao de registro de
    linguagem para o modo criacao/modificacao; reforcado tambem para o modo
    analise/discussao."""

    def test_instrui_conversa_mesmo_ao_revisar_ou_analisar(self):
        from nvdastudio.builder.nvda_context import NVDA_ADDON_CHAT_SYSTEM
        content = NVDA_ADDON_CHAT_SYSTEM.lower()
        assert "revisar" in content and "conversa" in content

    def test_proibe_formato_de_auditoria_tecnica(self):
        from nvdastudio.builder.nvda_context import NVDA_ADDON_CHAT_SYSTEM
        content = NVDA_ADDON_CHAT_SYSTEM.lower()
        assert "auditoria" in content
        assert "documento interno de engenharia" in content

    def test_instrui_limitar_a_2_ou_3_pontos_mais_importantes(self):
        from nvdastudio.builder.nvda_context import NVDA_ADDON_CHAT_SYSTEM
        content = NVDA_ADDON_CHAT_SYSTEM.lower()
        assert "2 ou 3" in content or "2-3" in content
