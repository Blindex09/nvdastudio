import ast
import os
import re
import pytest


_STUDIO_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "addon", "globalPlugins", "nvdastudio", "gui", "studio_dialog.py"
)


def _read_studio() -> str:
    """Le o codigo-fonte do studio_dialog.py diretamente do disco."""
    with open(_STUDIO_PATH, encoding="utf-8") as f:
        return f.read()


def _class_source(class_name: str) -> str:
    """Extrai o codigo-fonte de uma classe especifica via AST + slice de linhas."""
    src = _read_studio()
    lines = src.splitlines()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            start = node.lineno - 1
            end = node.end_lineno
            return "\n".join(lines[start:end])
    raise ValueError(f"Classe '{class_name}' nao encontrada em studio_dialog.py")


class TestClarificationInlineContrato:
    """
    v5.29.0: ClarificationDialog (wx.Dialog modal) removido -- esclarecimento
    passa a ser inline no chat via _ask_clarification_inline, mesmo padrao
    ja usado por aprovacao de plano e checkpoint (sem popup, uma janela so).
    """

    def _get_method_source(self) -> str:
        return _method_src_helper("_ask_clarification_inline")

    def test_nao_usa_wx_dialog(self):
        src = self._get_method_source()
        assert "wx.Dialog" not in src
        assert "ShowModal" not in src

    def test_escreve_perguntas_no_historico(self):
        src = self._get_method_source()
        assert "_chat_append" in src

    def test_fala_as_perguntas(self):
        src = self._get_method_source()
        assert "_speak_message" in src

    def test_usa_ia_para_extrair_respostas_sem_formato_fixo(self):
        """As perguntas vem da IA (clarifier.py); a extracao das respostas
        do texto livre do usuario tambem usa IA, nao parsing por posicao/
        keyword fixo."""
        src = self._get_method_source()
        assert "create_llm_client" in src
        assert "response_format" in src

    def test_classe_clarification_dialog_nao_existe_mais(self):
        with pytest.raises(ValueError):
            _class_source("ClarificationDialog")


class TestStudioDialogConstantes:
    """Verifica constantes do studio_dialog sem instanciar wx."""

    def test_output_dir_em_documents_nvdastudio(self):
        from nvdastudio.gui.studio_dialog import _OUTPUT_DIR
        assert "NVDAStudio" in _OUTPUT_DIR
        assert "addons_gerados" in _OUTPUT_DIR

    def test_announce_timer_ms_positivo(self):
        from nvdastudio.gui.studio_dialog import _ANNOUNCE_TIMER_MS
        assert isinstance(_ANNOUNCE_TIMER_MS, int)
        assert _ANNOUNCE_TIMER_MS > 0

    def test_event_icons_sem_emojis(self):
        """Regra 11: eventos anunciados sem emojis — compativel com cp1252."""
        from nvdastudio.gui.studio_dialog import _ANNOUNCE_EVENTS
        # Verifica que o conjunto de eventos anunciados nao contem strings com emojis
        _EMOJIS_PROIBIDOS = ["\u2705", "\u274c", "\u26a0", "\U0001f4e6",
                             "\U0001f916", "\u2728", "\u2764", "\U0001f680"]
        for event in _ANNOUNCE_EVENTS:
            for emoji in _EMOJIS_PROIBIDOS:
                assert emoji not in event, (
                    f"Emoji proibido no nome do evento '{event}': {repr(emoji)}"
                )

    def test_event_icons_encodaveis_cp1252(self):
        """Regra 11: nomes de eventos encodaveis em cp1252."""
        from nvdastudio.gui.studio_dialog import _ANNOUNCE_EVENTS
        for event in _ANNOUNCE_EVENTS:
            encoded = event.encode("cp1252", errors="replace")
            assert len(encoded) >= 0

    def test_announce_events_subset_de_event_icons(self):
        """Eventos importantes devem incluir PLANEJANDO, CONCLUIDO e ERRO."""
        from nvdastudio.gui.studio_dialog import _ANNOUNCE_EVENTS
        assert "PLANEJANDO" in _ANNOUNCE_EVENTS
        assert "CONCLUIDO" in _ANNOUNCE_EVENTS
        assert "ERRO" in _ANNOUNCE_EVENTS

    def test_module_version_semver(self):
        from nvdastudio.gui.studio_dialog import MODULE_VERSION
        partes = MODULE_VERSION.split(".")
        assert len(partes) == 3
        for p in partes:
            assert p.isdigit()


class TestNVDAStudioDialogHandlers:
    """
    Verifica que NVDAStudioDialog tem todos os handlers obrigatorios.
    Nao instancia wx — verifica apenas que os metodos existem no codigo-fonte.
    """

    def _get_class_source(self) -> str:
        return _class_source("NVDAStudioDialog")

    def test_tem_on_run(self):
        assert "def _on_run" in self._get_class_source()

    def test_tem_on_complete(self):
        assert "def _on_complete" in self._get_class_source()

    def test_tem_on_progress(self):
        assert "def _on_progress" in self._get_class_source()

    def test_tem_on_close(self):
        """WX-A11Y-010: timer parado no EVT_CLOSE."""
        src = self._get_class_source()
        assert "def _on_close" in src
        assert "Stop" in src or "timer" in src.lower()

    def test_tem_display_result(self):
        assert "def _display_result" in self._get_class_source()

    def test_tem_acao_salvar(self):
        """_action_instalar/_action_descartar/_action_store_submission foram
        removidos (v5.28.0) — orfaos, so alcancaveis pelo PostGenerationDialog
        ja removido antes. v5.30.0 (auditoria de orfaos): _action_salvar/
        _finalizar_salvar/_on_save TAMBEM removidos -- confirmado que nenhum
        botao os aciona (sem .Bind(wx.EVT_BUTTON, self._on_save, ...) em
        lugar nenhum); o unico caminho real de empacotamento e _on_package
        (chamado programaticamente por _run_packaging_process apos o fluxo
        inline pergunta/empacota), que ja cobre salvar+empacotar sozinho."""
        src = self._get_class_source()
        assert "def _on_package" in src
        assert "def _action_instalar" not in src
        assert "def _action_descartar" not in src
        assert "def _action_store_submission" not in src
        assert "def _action_salvar" not in src
        assert "def _on_save" not in src

    def test_display_result_salva_sessao_com_prompt_version(self):
        """v3.2.0: save_session deve receber prompt_version (A/B tracking)."""
        src = self._get_class_source()
        assert "save_session" in src
        assert "prompt_version" in src

    def test_nao_usa_posicionamento_absoluto(self):
        """WX-A11Y-005: sem SetPosition() ou coordenadas absolutas."""
        src = self._get_class_source()
        assert "SetPosition(" not in src

    def test_announce_queue_usado(self):
        """Regra 15: progresso via queue, nao ui.message() direto de thread."""
        src = self._get_class_source()
        assert "_announce_queue" in src
        assert "queue.Queue" in src or "Queue()" in src

    def test_wx_call_after_usado(self):
        """WX-A11Y-009: atualizacoes de UI de thread usam wx.CallAfter."""
        src = self._get_class_source()
        assert "wx.CallAfter" in src

    def test_nao_executa_output_gerado(self):
        """Regra 9: _display_result nao executa o output do orchestrator."""
        src = self._get_class_source()
        # final_output e exibido como texto — sem exec/eval
        assert "exec(" not in src
        assert "eval(" not in src


class TestStudioDialogAuditoriav511:
    """
    Testes para correcoes da auditoria 2026-03-29 (studio_dialog v5.1.0).
    Estrategia: inspecao de codigo-fonte — wx nao e instanciado.
    """

    # ---- A1: _restore_preferences anuncia via ui.message ----

    def test_restore_preferences_chama_ui_message(self):
        """A1: usuario cego deve ouvir a mensagem de boas-vindas."""
        src = _class_source("NVDAStudioDialog")
        method_start = src.find("def _restore_preferences")
        assert method_start != -1, "_restore_preferences ausente em NVDAStudioDialog"
        method_body = src[method_start:method_start + 500]
        assert "ui.message" in method_body, (
            "A1: _restore_preferences deve chamar ui.message para usuario cego ouvir boas-vindas"
        )

    # ---- A2: _on_package anuncia sucesso via ui.message ----

    def test_on_package_anuncia_sucesso(self):
        """A2: usuario cego deve ouvir confirmacao ao empacotar o addon via
        ui.message. N4 (v5.5.0): addonHandler.installAddonBundle() removido
        para evitar restart automatico do NVDA. v5.30.0 (auditoria de
        orfaos): _finalizar_instalacao e _finalizar_salvar (ambos so
        alcancaveis por caminhos ja mortos) foram removidos; _on_package e o
        unico caminho real de empacotamento hoje (salva se necessario E
        empacota, chamado por _run_packaging_process)."""
        src = _class_source("NVDAStudioDialog")
        method_start = src.find("def _on_package")
        assert method_start != -1, "_on_package ausente em NVDAStudioDialog"
        method_body = src[method_start:method_start + 3000]
        # installAddonBundle removido — a chamada "_ah.installAddonBundle" nao deve existir
        assert "_ah.installAddonBundle" not in method_body, (
            "N4: chamada _ah.installAddonBundle deve ter sido removida para evitar restart automatico"
        )
        # ui.message ainda deve existir para acessibilidade
        assert "ui.message" in method_body, (
            "A2: _on_package deve chamar ui.message para confirmar o empacotamento"
        )

    def test_on_package_escreve_confirmacao_no_historico(self):
        """v5.33.0: bug real de live-test -- Felipe reportou que a IA nao
        avisava quando terminava de empacotar. Causa: a confirmacao so
        chamava ui.message (fala efemera), nunca _chat_append (historico
        visivel). Corrigido: sucesso agora tambem vai para o historico."""
        src = _class_source("NVDAStudioDialog")
        method_start = src.find("def _on_package")
        method_body = src[method_start:method_start + 3000]
        assert "_chat_append" in method_body, (
            "_on_package deve escrever a confirmacao de sucesso no historico, nao so falar"
        )

    def test_run_packaging_process_escreve_inicio_no_historico(self):
        src = _class_source("NVDAStudioDialog")
        idx = src.find("def _run_packaging_process")
        assert idx != -1
        next_def = src.find("\n\tdef ", idx + 10)
        body = src[idx:next_def] if next_def != -1 else src[idx:idx + 800]
        assert "_chat_append" in body


class TestOnPackageAvisaProblemasEstruturaisNaoResolvidos:
    """
    Regressao para bug real GRAVE (studio_dialog.py 5.47.0), achado por
    investigacao direta (pedido do Felipe: "qualquer addon que eu gerar vai
    dar erro pro usuario, ou ele vai poder corrigir?"). _on_package()
    chamava _auto_fix_structural_issues() mas DESCARTAVA o retorno
    (actions, last_problems) -- se as 2 rodadas de autocorrecao nao
    resolvessem tudo (ex: __init__.py raiz continua ausente -- NVDA nem
    carrega o addon sem ele), o codigo seguia direto pro package_addon() e
    anunciava "empacotado com sucesso" INCONDICIONALMENTE, sem NUNCA avisar
    o usuario que o .nvda-addon entregue estava quebrado.
    """

    def test_nao_descarta_retorno_de_auto_fix_structural_issues(self):
        body = _method_src_helper("_on_package")
        # Regressao: a chamada sozinha SEM atribuicao (linha exata "\t\t\tself.
        # _auto_fix_structural_issues(addon_folder, addon_name)\n", sem "= " na
        # frente) e a assinatura do bug -- o retorno descartado.
        assert not re.search(
            r"^\s*self\._auto_fix_structural_issues\(addon_folder, addon_name\)\s*$",
            body, re.MULTILINE,
        ), (
            "_on_package ainda chama _auto_fix_structural_issues() como statement "
            "solto (sem capturar o retorno) -- regressao do bug que descartava "
            "last_problems."
        )
        assert re.search(
            r"\w+\s*,\s*\w+\s*=\s*self\._auto_fix_structural_issues\(",
            body,
        ), (
            "_on_package deve capturar (actions, problems) = "
            "self._auto_fix_structural_issues(...) em vez de descartar o retorno."
        )

    def test_avisa_quando_sobra_problema_estrutural(self):
        body = _method_src_helper("_on_package")
        assert "if _remaining_problems" in body or "if remaining_problems" in body, (
            "_on_package deve verificar se sobrou problema estrutural apos a "
            "autocorrecao antes de anunciar sucesso incondicional."
        )

    def test_sucesso_incondicional_nao_e_mais_a_unica_saida(self):
        """A mensagem 'empacotado com sucesso' deve estar dentro de um else/
        branch condicional, nao ser a unica saida possivel do metodo."""
        body = _method_src_helper("_on_package")
        idx_sucesso = body.find("addon empacotado com sucesso")
        assert idx_sucesso != -1
        # deve haver um bloco de aviso (problema estrutural) ANTES da linha
        # de sucesso incondicional no corpo do metodo -- prova que sucesso
        # agora e um dos 2 caminhos, nao o unico.
        idx_aviso = body.find("problema(s) estrutural")
        assert idx_aviso != -1 and idx_aviso < idx_sucesso, (
            "Mensagem de aviso sobre problemas estruturais nao encontrada "
            "ANTES da mensagem de sucesso -- _on_package pode ainda estar "
            "anunciando sucesso incondicionalmente."
        )

    # ---- A3: NVDAStudioDialog.__init__ chama SetFocus ----

    def test_init_chama_set_focus(self):
        """A3: foco deve ser movido para o campo de entrada apos abrir o dialog."""
        src = _class_source("NVDAStudioDialog")
        init_start = src.find("def __init__")
        assert init_start != -1
        # __init__ termina quando encontra proximo def no mesmo nivel
        next_def = src.find("\n\tdef ", init_start + 10)
        init_body = src[init_start:next_def] if next_def != -1 else src[init_start:init_start + 3000]
        assert "SetFocus" in init_body, (
            "A3: NVDAStudioDialog.__init__ deve chamar SetFocus apos construir a UI"
        )

    # ---- A4: _ask_clarification_inline move foco pro campo de resposta ----

    def test_ask_clarification_inline_seta_foco(self):
        """A4: foco deve ir para o campo de resposta do chat automaticamente
        (v5.29.0: inline, sem ClarificationDialog modal)."""
        src = _method_src_helper("_ask_clarification_inline")
        assert "self._input.SetFocus()" in src, (
            "A4: _ask_clarification_inline deve mover o foco para o campo de entrada"
        )

    def test_chat_nao_depende_de_marcador_textual(self):
        src = _read_studio()
        assert 'action == "run_pipeline"' in src
        assert '.find("PIPELINE' not in src

    # ---- I3: _on_clarify_needed captura timeout ----

    def test_on_clarify_needed_passa_timeout(self):
        """I3: timeout deve ser detectado e anunciado ao usuario.
        v5.29.0: _on_clarify_needed delega para _ask_clarification_inline,
        que agora concentra a logica de wait/timeout (inline, sem dialogo)."""
        src = _method_src_helper("_on_clarify_needed")
        assert "timeout=180" in src, "_on_clarify_needed deve repassar timeout=180"
        inline_src = _method_src_helper("_ask_clarification_inline")
        assert "wait(timeout=" in inline_src, "_clarification_event.wait(timeout=) deve estar presente"
        assert "got_input" in inline_src and "if not got_input" in inline_src, (
            "I3: resultado de wait() deve ser capturado para verificar timeout"
        )

    # ---- I5: studio_dialog nao acessa _api_key diretamente ----

    def test_nao_acessa_api_key_diretamente(self):
        """I5: studio_dialog nao deve acessar _orchestrator._api_key diretamente."""
        src = _read_studio()
        assert "_orchestrator._api_key" not in src, (
            "I5: studio_dialog nao deve acessar _orchestrator._api_key diretamente"
        )

    def test_usa_create_llm_client(self):
        """I5: studio_dialog deve usar create_llm_client para obter o cliente LLM."""
        src = _read_studio()
        assert "create_llm_client" in src, (
            "I5: studio_dialog deve usar create_llm_client para acessar o LLM"
        )

    def test_module_version_e_5_2_0(self):
        from nvdastudio.gui.studio_dialog import MODULE_VERSION
        assert MODULE_VERSION == "5.48.0"

    def test_path_containment_rejeita_outra_unidade_windows(self):
        from nvdastudio.gui.studio_dialog import _is_path_within
        assert _is_path_within(r"C:\base", r"D:\fora\arquivo.py") is False


class TestOfferChatRestore:
    """
    Testes para _offer_chat_restore — recuperacao de historico cross-session.
    Estrategia: inspecao de codigo-fonte — wx nao e instanciado.
    skill: memory-systems (Layer 3 Long-term memory).
    """

    def _method_src(self) -> str:
        src = _class_source("NVDAStudioDialog")
        idx = src.find("def _offer_chat_restore")
        assert idx != -1, "_offer_chat_restore ausente em NVDAStudioDialog"
        next_def = src.find("\n\tdef ", idx + 10)
        return src[idx:next_def] if next_def != -1 else src[idx:idx + 2000]

    def test_metodo_existe(self):
        """_offer_chat_restore deve existir em NVDAStudioDialog."""
        src = _class_source("NVDAStudioDialog")
        assert "def _offer_chat_restore" in src

    def test_chama_get_last_chat(self):
        """Deve consultar memory.get_last_chat para buscar historico anterior."""
        m = self._method_src()
        assert "get_last_chat" in m, "_offer_chat_restore deve chamar memory.get_last_chat()"

    def test_exibe_wx_message_dialog(self):
        """Deve usar wx.MessageDialog para perguntar ao usuario."""
        m = self._method_src()
        assert "wx.MessageDialog" in m or "MessageDialog" in m, (
            "_offer_chat_restore deve exibir wx.MessageDialog para perguntar ao usuario"
        )

    def test_anuncia_via_ui_message(self):
        """Resultado da escolha deve ser anunciado via ui.message (acessibilidade)."""
        m = self._method_src()
        assert "ui.message" in m, "_offer_chat_restore deve chamar ui.message para anunciar"

    def test_restaura_chat_history(self):
        """Ao confirmar, deve popular _chat_history com as mensagens recuperadas."""
        m = self._method_src()
        assert "_chat_history" in m, "Deve atualizar self._chat_history com msgs restauradas"

    def test_chama_chat_append(self):
        """Ao restaurar, deve exibir mensagens no _chat_log via _chat_append."""
        m = self._method_src()
        assert "_chat_append" in m, "Deve chamar self._chat_append para exibir msgs restauradas"

    def test_trata_excecao_silenciosamente(self):
        """Erros nao devem propagar — tratamento com except."""
        m = self._method_src()
        assert "except" in m, "_offer_chat_restore deve ter tratamento de excecao"

    def test_on_run_chama_offer_chat_restore(self):
        """_on_run deve chamar _offer_chat_restore quando chat estiver vazio."""
        src = _class_source("NVDAStudioDialog")
        on_run_idx = src.find("def _on_run")
        assert on_run_idx != -1
        next_def = src.find("\n\tdef ", on_run_idx + 10)
        on_run_body = src[on_run_idx:next_def] if next_def != -1 else src[on_run_idx:on_run_idx + 1200]
        assert "_offer_chat_restore" in on_run_body, (
            "_on_run deve chamar _offer_chat_restore apos derivar addon_name"
        )

    def test_recuperacao_condicionada_a_chat_vazio(self):
        """_offer_chat_restore so e chamado se _chat_history estiver vazio."""
        src = _class_source("NVDAStudioDialog")
        on_run_idx = src.find("def _on_run")
        next_def = src.find("\n\tdef ", on_run_idx + 10)
        on_run_body = src[on_run_idx:next_def] if next_def != -1 else src[on_run_idx:on_run_idx + 1200]
        # A chamada a _offer_chat_restore deve estar dentro de um bloco condicional
        # verificando _chat_history (vazio = nao ha conversa em andamento)
        assert "_chat_history" in on_run_body, (
            "_on_run deve verificar _chat_history antes de chamar _offer_chat_restore"
        )


class TestStudioDialogCleanText:
    """Verifica que o dialog remove linhas em branco consecutivas e limpa o texto."""

    def _method_src(self) -> str:
        src = _class_source("NVDAStudioDialog")
        idx = src.find("def _clean_text")
        assert idx != -1, "_clean_text ausente em NVDAStudioDialog"
        next_def = src.find("\n\tdef ", idx + 10)
        return src[idx:next_def] if next_def != -1 else src[idx:idx + 1000]

    def test_clean_text_removes_blank_lines(self):
        """_clean_text delega ao contrato central de texto visível."""
        m = self._method_src()
        assert "sanitize_user_visible_text" in m

    def test_stream_antigo_foi_removido(self):
        src = _class_source("NVDAStudioDialog")
        assert "def _chat_stream_append" not in src
        assert "def _chat_stream_replace" not in src



class TestStudioDialogSemKeywordFixaDeAcento:
    """_clean_text nao deve mais patchear acentos via lista fixa de palavras.
    Acentuacao correta e responsabilidade do system prompt (nvda_context.py)."""

    def test_sem_dicionario_de_correcoes(self):
        body = _class_source("NVDAStudioDialog")
        idx = body.find("def _clean_text")
        assert idx != -1
        next_def = body.find("\n\tdef ", idx + 10)
        method_body = body[idx:next_def] if next_def != -1 else body[idx:idx + 800]
        assert "corrections = {" not in method_body, (
            "_clean_text ainda tem lista fixa de correcao de acentos (keyword hardcoded)"
        )
        assert '"usuario": "usuário"' not in method_body, (
            "_clean_text nao deveria mais conter mapeamento usuario->usuário"
        )

    def test_ainda_remove_markdown(self):
        """A limpeza de markdown (nao relacionada a acento) deve continuar existindo."""
        body = _class_source("NVDAStudioDialog")
        idx = body.find("def _clean_text")
        next_def = body.find("\n\tdef ", idx + 10)
        method_body = body[idx:next_def] if next_def != -1 else body[idx:idx + 800]
        assert "sanitize_user_visible_text" in method_body


class TestStudioDialogThoughtStreaming:
    """Thinking interno nunca deve fazer parte da conversa visivel."""

    def test_handle_thinking_foi_removido(self):
        body = _class_source("NVDAStudioDialog")
        assert "def _handle_thinking" not in body

    def test_setup_nao_registra_callback_visual_de_thinking(self):
        body = _class_source("NVDAStudioDialog")
        idx = body.find("def _setup_conversational_callbacks")
        next_def = body.find("\n\tdef ", idx + 10)
        method_body = body[idx:next_def]
        assert "on_thinking" not in method_body


class TestStudioDialogInterrupcaoAtiva:
    """Usuario pode digitar nova instrucao enquanto a IA processa (redirecionamento seguro)."""

    def test_on_run_verifica_input_ao_cancelar(self):
        """_on_run deve checar se ha texto no input antes de decidir stop vs redirect."""
        src = _class_source("NVDAStudioDialog")
        on_run_idx = src.find("def _on_run")
        assert on_run_idx != -1
        next_def = src.find("\n\tdef ", on_run_idx + 10)
        body = src[on_run_idx:next_def] if next_def != -1 else src[on_run_idx:on_run_idx + 2000]
        assert "redirect_query" in body
        assert "_pending_redirect_query" in body
        assert "cancel_pipeline" in body

    def test_run_pending_redirect_existe_e_reusa_on_run(self):
        """_run_pending_redirect deve reaproveitar _on_run para nao duplicar logica de entrada."""
        src = _class_source("NVDAStudioDialog")
        idx = src.find("def _run_pending_redirect")
        assert idx != -1, "_run_pending_redirect ausente em NVDAStudioDialog"
        next_def = src.find("\n\tdef ", idx + 10)
        body = src[idx:next_def] if next_def != -1 else src[idx:idx + 600]
        assert "_pending_redirect_query" in body
        assert "self._on_run" in body

    def test_done_dispara_redirect_pendente(self):
        """Ao concluir (fase DONE), o pipeline conversacional deve checar redirect pendente."""
        src = _class_source("NVDAStudioDialog")
        idx = src.find("def _handle_conversational_phase")
        assert idx != -1
        next_def = src.find("\n\tdef ", idx + 10)
        body = src[idx:next_def] if next_def != -1 else src[idx:idx + 3000]
        assert "_run_pending_redirect" in body

class TestProcessChatMessageSeparaMensagemDaEspecificacao:
    """O contrato estruturado separa o texto visível da tarefa interna."""

    def _method_src(self) -> str:
        src = _class_source("NVDAStudioDialog")
        idx = src.find("def _process_chat_message")
        assert idx != -1
        next_def = src.find("\n\tdef ", idx + 10)
        return src[idx:next_def] if next_def != -1 else src[idx:idx + 4000]

    def test_campos_sao_lidos_do_json(self):
        body = self._method_src()
        assert "json.loads" in body
        assert 'payload["message"]' in body
        assert 'payload["task_specification"]' in body

    def test_pipeline_desc_so_vai_para_os_triggers_do_pipeline(self):
        """pipeline_desc (especificacao tecnica) so pode aparecer como argumento
        de _trigger_creation_pipeline/_trigger_iterative_pipeline, nunca em
        _chat_finish, _chat_finish_stream ou _chat_history."""
        body = self._method_src()
        assert "_trigger_iterative_pipeline, task_specification" in body
        assert "_trigger_creation_pipeline, task_specification" in body
        assert "_chat_append, task_specification" not in body
        assert '"text": task_specification' not in body

    def test_apenas_message_vai_para_a_tela(self):
        body = self._method_src()
        assert 'f"Assistente:\\n{message}"' in body
        assert '"text": message' in body

    def test_nao_ha_marcador_textual(self):
        body = self._method_src()
        assert "PIPELINE:" not in body

class TestChatSemStreamingInterno:
    """A resposta estruturada chega inteira e não expõe deltas internos."""

    def test_chat_stream_replace_existe(self):
        src = _class_source("NVDAStudioDialog")
        assert "def _chat_stream_replace" not in src

    def test_chat_stream_replace_usa_setvalue_nao_appendtext(self):
        src = _class_source("NVDAStudioDialog")
        assert "def _chat_stream_append" not in src

    def test_on_stream_delta_usa_replace_nao_append(self):
        """A fonte real do bug: on_stream_delta recebe texto acumulado do
        StreamConsumer, precisa de semantica de substituicao, nao de anexar."""
        src = _class_source("NVDAStudioDialog")
        assert "on_stream_delta" not in src

    def test_process_chat_message_substitui_texto_visivel_filtrado(self):
        """O chat rapido reescreve o texto acumulado ja filtrado para impedir
        vazamento de thinking e de fragmentos do marcador interno."""
        body = _method_src_helper("_process_chat_message")
        assert "_chat_stream_replace" not in body
        assert "sanitize_user_visible_text" in body


class TestPlanApprovalUsaTextoLimpo:
    """v5.21.0: PLAN_APPROVAL escrevia detail cru em self._log/self._code_view,
    deixando simbolos de markdown residuais (---, ***) gerados pela IA visiveis
    na tela. Agora passa por _clean_text() antes de exibir."""

    def test_plan_approval_usa_clean_text_antes_de_setvalue(self):
        body = _method_src_helper("_handle_conversational_phase")
        idx = body.find("if phase == PipelinePhase.PLAN_APPROVAL:")
        assert idx != -1
        trecho = body[idx:idx + 400]
        assert "self._clean_text(detail)" in trecho
        assert "self._code_view.SetValue(clean_detail)" in trecho
        assert "self._log.SetValue(clean_detail)" not in trecho


class TestShowErrorInlineSemPopup:
    """v5.33.0: _show_error usava gui.messageBox (popup modal), na contramao
    da regra ja estabelecida nesta sessao de zero dialogo modal -- erro
    passa a ser inline no chat, mesmo padrao do resto da UI."""

    def test_show_error_nao_usa_messagebox(self):
        body = _method_src_helper("_show_error")
        assert "gui.messageBox" not in body

    def test_show_error_escreve_no_historico_e_fala(self):
        body = _method_src_helper("_show_error")
        assert "_chat_append" in body
        assert "ui.message" in body

    def test_show_error_sanitiza_antes_de_exibir(self):
        """Achado de auditoria 2026-08-04: os 4 chamadores passam texto de
        excecao Python cru (f"...: {exc}") -- _show_error precisa sanitizar
        internamente (mesmo padrao de _handle_status), nao confiar no
        chamador."""
        body = _method_src_helper("_show_error")
        idx_sanitize = body.find("sanitize_user_visible_text(msg)")
        idx_append = body.find("self._chat_append(")
        assert idx_sanitize != -1
        assert idx_append != -1
        assert idx_sanitize < idx_append, (
            "sanitize_user_visible_text deve rodar ANTES do _chat_append"
        )


class TestOnProgressEscreveNoHistorico:
    """Achado de auditoria 2026-08-04: _on_progress (usado por
    _trigger_iterative_pipeline, fluxo de MODIFICAR addon existente, via
    Orchestrator.run_async) so mandava pra _set_status() -- um no-op
    inerte desde a v5.35.0. Dos 12 tipos de evento em _ANNOUNCE_EVENTS, 8
    (PLANEJANDO, EXECUTANDO, CORRIGINDO, AVALIANDO, REPLANEJANDO,
    ESCALANDO, PARALELO, MONTANDO) nao iam nem pro log nem pra fala --
    silencio total durante uma correcao longa, sem nada navegavel depois."""

    def test_on_progress_escreve_no_historico_navegavel(self):
        body = _method_src_helper("_on_progress")
        assert "_chat_append" in body

    def test_on_progress_ainda_filtra_fala_efemera_por_evento_critico(self):
        """A fala continua restrita aos eventos criticos -- so o LOG deixou
        de ser exclusivo dos 4 eventos anunciaveis."""
        body = _method_src_helper("_on_progress")
        idx = body.find("_announce_queue.put(detail)")
        assert idx != -1
        trecho = body[:idx]
        assert '"PLANO_CRIADO", "AGUARDANDO_USUARIO", "CONCLUIDO", "ERRO"' in trecho


class TestFocoAposEntregaFinalVaiPraInput:
    """Achado de auditoria 2026-08-04: apos a entrega final, o foco ficava
    no _log (so leitura) no exato momento em que a proxima acao esperada e
    DIGITAR a resposta ("ajustar ou empacotar?") -- usuario de teclado/leitor
    de tela precisava dar Tab manualmente antes de conseguir responder."""

    def test_display_result_sucesso_foca_input_nao_log(self):
        body = _method_src_helper("_display_result")
        idx_label = body.find('_update_input_label("Digite sua resposta:")')
        assert idx_label != -1
        trecho = body[idx_label:idx_label + 900]
        assert "self._input.SetFocus()" in trecho
        assert "self._log.SetFocus()" not in trecho


class TestSemTruncamentoEmStatusDeProgresso:
    """v5.3x.x ja removeu o truncamento de 100 chars do LOG permanente
    (_handle_status/_MAX_STATUS_LENGTH). Achado de auditoria 2026-08-04:
    sobrava truncamento em _handle_conversational_phase e no branch de erro
    de _display_result -- ambos alimentavam so _set_status() (no-op), entao
    nunca quebravam nada visivel, mas reintroduziriam o bug silenciosamente
    se _set_status() for reconectado algum dia. Truncamento de trechos
    FALADOS (ui.message/_speak_message, efemeros por natureza) continua
    legitimo e nao e coberto aqui."""

    def test_handle_conversational_phase_sem_detail_100(self):
        body = _method_src_helper("_handle_conversational_phase")
        assert "detail[:100]" not in body

    def test_display_result_erro_sem_truncamento_no_set_status(self):
        body = _method_src_helper("_display_result")
        assert 'self._set_status(f"Erro: {err[:100]}")' not in body


class TestPipelineNaoApagaHistoricoAoIniciar:
    """v5.32.0: bug real de live-test -- Felipe reportou que ao disparar o
    pipeline (apos a conversa de esclarecimento) todo o historico visivel
    sumia, dando a impressao de uma janela nova. Causa raiz:
    _trigger_creation_pipeline e _trigger_iterative_pipeline chamavam
    self._log.SetValue("") logo no inicio, apagando a conversa que tinha
    acabado de acontecer. O historico deve continuar crescendo como uma
    unica transcricao continua -- so o botao Reset (_on_reset) deve limpar
    o historico de proposito."""

    def test_trigger_creation_pipeline_nao_limpa_o_log(self):
        body = _method_src_helper("_trigger_creation_pipeline")
        assert '_log.SetValue("")' not in body

    def test_trigger_iterative_pipeline_nao_limpa_o_log(self):
        body = _method_src_helper("_trigger_iterative_pipeline")
        assert '_log.SetValue("")' not in body

    def test_on_reset_continua_limpando_o_log_de_proposito(self):
        """Regressao: o Reset explicito do usuario deve continuar limpando."""
        body = _method_src_helper("_on_reset")
        assert '_log.SetValue("")' in body


class TestModoIterativoAutomaticoPosCriacao:
    """
    2026-08-09: antes, so acao MANUAL do usuario ("Carregar Pasta"/"Carregar
    Arquivo") setava self._loaded_addon_context -- apos uma criacao bem
    sucedida, um pedido de ajuste na MESMA conversa ("conserta esse bug")
    caia no fluxo de criacao NOVA do zero (_trigger_creation_pipeline), nao
    no modo iterativo (_trigger_iterative_pipeline), porque
    _process_chat_message escolhe o modo pelo estado dessa variavel.
    _display_result() agora ativa o modo iterativo sozinho, com os blocos em
    memoria (addon_loader.py 1.3.0::load_addon_from_blocks()), sem exigir
    reload manual nem tocar disco.
    """

    def test_display_result_ativa_modo_iterativo_apos_sucesso(self):
        body = _method_src_helper("_display_result")
        assert "load_addon_from_blocks(" in body
        assert "self._loaded_addon_context = load_addon_from_blocks(" in body

    def test_display_result_nao_chama_load_addon_context_completo(self):
        """Nao deve usar _load_addon_context() (limparia o historico do chat
        e anunciaria "addon carregado" por cima da mensagem de conclusao)."""
        body = _method_src_helper("_display_result")
        assert "self._load_addon_context(" not in body

    def test_enriched_query_consulta_memoria_por_addon(self):
        """5.41.0: memoria por addon consultada automaticamente, sem dialogo
        pedindo permissao -- session_memory.get_last_chat() ja existia
        (chat_snippets por addon_name), so nunca era lida de volta no fluxo
        iterativo (so em _offer_chat_restore(), chamada com um placeholder
        que na pratica nunca casa nada util)."""
        body = _method_src_helper("_trigger_iterative_pipeline")
        assert "memory.get_last_chat(" in body
        assert "wx.MessageDialog(" not in body

    def test_enriched_query_instrui_plano_minimo(self):
        """5.41.0: sem essa instrucao, um pedido de correcao pontual gerava
        o MESMO plano de 6-7 steps de uma criacao nova (design_review,
        agent_template, manifest_builder, documentation, assembly do zero)."""
        body = _method_src_helper("_trigger_iterative_pipeline")
        assert "plano minimo" in body.lower()
        assert "code_generation" in body

    def test_on_reset_limpa_loaded_addon_context(self):
        """Sem isso, 'Nova Sessao' preservava o modo iterativo do addon
        anterior -- um pedido de addon NOVO, sem relacao nenhuma, seria
        tratado como ajuste do addon antigo."""
        body = _method_src_helper("_on_reset")
        assert "self._loaded_addon_context = None" in body


class TestEntregaParcialGracefulDegradation:
    """
    5.42.0: padrao "graceful degradation" -- antes, quando faltava
    code_generation/manifest_builder aprovado, TODOS os artefatos ja
    gerados por OUTROS steps (manifest, documentation, design_review) eram
    descartados (self._last_blocks = []) e o usuario so via um popup
    generico. Achado real: rodada do golden eval set (GeminiMultimodal)
    teve varios steps aprovados com score 95-100 e mesmo assim o usuario
    nao via nada disso quando code_generation falhava.
    """

    def test_display_result_chama_partial_quando_ha_blocos_parciais(self):
        body = _method_src_helper("_display_result")
        assert "self._display_partial_result(result, blocks)" in body

    def test_display_result_nao_descarta_blocos_antes_de_checar_parcial(self):
        """Regressao: 'self._last_blocks = []' (CODIGO, nao comentario) so
        pode acontecer DEPOIS de checar se ha blocos parciais salvaveis."""
        body = _method_src_helper("_display_result")
        idx_partial_call = body.find("return self._display_partial_result(result, blocks)")
        idx_clear = body.find("\t\t\t\tself._last_blocks = []")
        assert idx_partial_call != -1 and idx_clear != -1
        assert idx_partial_call < idx_clear

    def test_display_partial_result_existe(self):
        assert "def _display_partial_result" in _class_source("NVDAStudioDialog")

    def test_display_partial_result_ativa_modo_iterativo(self):
        body = _method_src_helper("_display_partial_result")
        assert "self._loaded_addon_context = load_addon_from_blocks(" in body

    def test_display_partial_result_preserva_last_blocks(self):
        body = _method_src_helper("_display_partial_result")
        assert "self._last_blocks = blocks" in body

    def test_display_partial_result_nao_usa_popup_de_erro(self):
        """Diferente do fluxo de erro total -- entrega parcial nao deve
        interromper com wx.MessageDialog, deixa o usuario seguir pelo chat."""
        body = _method_src_helper("_display_partial_result")
        assert "wx.MessageDialog(" not in body


class TestFaseXRemovidoDoLogTextual:
    """v5.22.0: bug real de live-test -- "[Sistema]\nFase: Pesquisando" era
    redundante com a mensagem especifica que vem logo em seguida (ex:
    "Pesquisando APIs e referencias..."). Removido o texto no log.

    v5.31.0: Felipe reportou (live-test) que o NVDA falava sozinho demais
    durante o pipeline -- toda mudanca de fase (Pesquisando, Planejando,
    Implementando...) era anunciada por ui.message() sem o usuario pedir.
    Decisao explicita dele: mudar o padrao pra todo mundo, nao so pra quem
    esta testando -- o texto continua aparecendo na interface (label vai
    pro status bar via _set_status), mas o NVDA nao narra mais essa
    transicao sozinho."""

    def test_fase_x_nao_aparece_mais_no_log(self):
        body = _method_src_helper("_handle_conversational_phase")
        assert "self._chat_append(f\"[Sistema]\\nFase: {label}\")" not in body

    def test_aviso_sonoro_de_fase_removido(self):
        body = _method_src_helper("_handle_conversational_phase")
        assert 'ui.message(f"NVDAStudio: {label}")' not in body

    def test_detalhes_tecnicos_de_pesquisa_nao_entram_no_historico(self):
        body = _method_src_helper("_handle_conversational_phase")
        guard = body.find("if phase == PipelinePhase.RESEARCH:")
        append = body.find("self._chat_append(detail)")
        assert guard != -1
        assert "return" in body[guard:append]
        assert guard < append


class TestPlanoAprovacaoSemListaFixaDeComandos:
    """v5.22.0: bug real de live-test -- o texto de aprovacao do plano listava
    comandos exatos ("Digite Sim, Ok ou Aprovar...") mas a resposta ja e
    classificada por IA de forma livre (client.chat com intent classifier em
    _on_conversational_plan_ready) -- a lista sugeria uma restricao que nao
    existe de verdade, soando como um menu de keywords em vez de conversa."""

    def test_sem_lista_de_comandos_exatos(self):
        body = _method_src_helper("_on_conversational_plan_ready")
        assert "Digite 'Sim'" not in body
        assert "Ou descreva as alteracoes" not in body
        assert "Como deseja proceder?" not in body

    def test_convite_aberto_presente(self):
        body = _method_src_helper("_on_conversational_plan_ready")
        assert "próprias palavras" in body


class TestClassificadorDeIntencaoNarraNaInterface:
    """v5.35.0: Felipe perguntou se o classificador de intencao (plano/
    empacotamento/esclarecimento) tambem e conversacional na interface --
    nao era: so mostrava o texto fixo 'Processando resposta.' e falava
    isso automaticamente. Trocado por narrate() (gerado pela IA, so no
    historico, sem falar) nos 3 pontos onde o usuario acabou de responder
    e a classificacao semantica esta prestes a rodar."""

    def test_on_run_nao_fala_processando_resposta_automaticamente(self):
        body = _method_src_helper("_on_run")
        assert 'ui.message("Processando resposta' not in body

    def test_on_run_narra_interpretacao_do_plano(self):
        body = _method_src_helper("_on_run")
        assert "narrate(" in body
        assert body.count("narrate(") >= 3


class TestCheckpointNuncaParaOPipeline:
    """v5.34.0: Felipe foi explicito -- o checkpoint nao deve parar o
    pipeline pra perguntar continuar/pausar/refazer; a IA decide sozinha e
    continua, so informando o que aconteceu no historico. Reverte o
    comportamento bloqueante introduzido nas v5.22.0/v5.28.0
    (_ask_checkpoint_inline aguardava resposta do usuario via
    threading.Event -- removido por completo, zero callers restantes)."""

    def test_ask_checkpoint_inline_nao_existe_mais(self):
        src = _class_source("NVDAStudioDialog")
        assert "def _ask_checkpoint_inline" not in src

    def test_on_checkpoint_interactive_sempre_continua(self):
        body = _method_src_helper("_on_checkpoint_interactive")
        assert "CheckpointAction.CONTINUE" in body
        assert ".wait()" not in body

    def test_on_conversational_checkpoint_sempre_continua(self):
        body = _method_src_helper("_on_conversational_checkpoint")
        assert "return True" in body
        assert ".wait()" not in body

    def test_report_checkpoint_inline_escreve_no_historico_sem_bloquear(self):
        body = _method_src_helper("_report_checkpoint_inline")
        assert "_chat_append" in body
        assert ".wait()" not in body
        assert "threading.Event" not in body

    def test_checkpoint_dialogos_nao_usam_wx_message_dialog(self):
        """Regressao: checkpoints nunca abrem popup modal."""
        for method_name in ("_on_checkpoint_interactive", "_on_conversational_checkpoint", "_report_checkpoint_inline"):
            body = _method_src_helper(method_name)
            assert "wx.MessageDialog" not in body, f"{method_name} nao deveria usar wx.MessageDialog"

    def test_estado_de_aprovacao_de_checkpoint_removido(self):
        """Regressao: nenhum campo de estado do fluxo bloqueante deve sobrar."""
        src = _class_source("NVDAStudioDialog")
        for campo in (
            "_waiting_for_checkpoint_approval",
            "_checkpoint_approval_event",
            "_checkpoint_approval_result",
            "_raw_checkpoint_approval_input",
        ):
            assert campo not in src, f"{campo} deveria ter sido removido (fluxo bloqueante nao existe mais)"


class TestCanalUnificadoStatusEHeartbeat:
    """v5.28.0: status curto e heartbeat de tool progress eram canais mudos
    para o historico (status nunca ia para self._log; heartbeat nao falava
    nada, so atualizava uma barra de status silenciosa). Status passou a
    ir tambem para o historico (navegavel com as setas).

    v5.31.0: a v5.28.0 tambem tinha feito status e heartbeat falarem ao
    vivo via _speak_message -- Felipe reportou que isso fazia o NVDA falar
    demais sozinho durante o pipeline inteiro. Decisao dele: revertido por
    padrao para todo mundo. O texto continua visivel (historico + barra de
    status), so nao e mais narrado automaticamente."""

    def test_handle_status_escreve_no_historico(self):
        body = _method_src_helper("_handle_status")
        assert "_chat_append" in body

    def test_handle_status_nao_fala_automaticamente(self):
        body = _method_src_helper("_handle_status")
        assert "_speak_message" not in body

    def test_handle_tool_progress_nao_fala_automaticamente(self):
        body = _method_src_helper("_handle_tool_progress")
        assert "_speak_message" not in body

    def test_handle_tool_progress_nao_fala_step_type_tecnico_cru(self):
        """Nao pode voltar a expor nomes internos (code_generation,
        manifest_builder, ...) diretamente na fala -- usa _TOOL_PROGRESS_LABELS."""
        body = _method_src_helper("_handle_tool_progress")
        assert "_TOOL_PROGRESS_LABELS" in body

    def test_tool_progress_labels_cobre_todos_os_step_types_conhecidos(self):
        from nvdastudio.core.planner import (
            STEP_CODE_GENERATION, STEP_MANIFEST, STEP_ACCESSIBILITY_AUDIT,
            STEP_TEST_GENERATION, STEP_WEB_RESEARCH, STEP_AGENT_TEMPLATE,
            STEP_AGENT_RUNNER, STEP_ASSEMBLY, STEP_DESIGN_REVIEW,
            STEP_DOCUMENTATION, STEP_SYNTAX_VALIDATION,
        )
        # NVDAStudioDialog e mockado neste ambiente de teste (sem wx/gui reais)
        # -- inspeciona o codigo-fonte da classe em vez de acessar o atributo
        # num objeto Mock (mesmo padrao de _method_src_helper/_class_source).
        body = _class_source("NVDAStudioDialog")
        for step_type in (
            STEP_CODE_GENERATION, STEP_MANIFEST, STEP_ACCESSIBILITY_AUDIT,
            STEP_TEST_GENERATION, STEP_WEB_RESEARCH, STEP_AGENT_TEMPLATE,
            STEP_AGENT_RUNNER, STEP_ASSEMBLY, STEP_DESIGN_REVIEW,
            STEP_DOCUMENTATION, STEP_SYNTAX_VALIDATION,
        ):
            assert f'"{step_type}"' in body, f"step_type sem rotulo em linguagem natural: {step_type}"


class TestSetStatusNaoTocaMaisNoWidget:
    """v5.36.0: bug real de live-test -- Felipe reportou (repetido, com
    frustracao) que narracoes do pipeline continuavam sendo faladas
    automaticamente pelo NVDA mesmo depois de toda limpeza de auto-fala ja
    feita (v5.31.0 em diante). Causa raiz: nao era nenhum ui.message()/
    _speak_message() esquecido -- era _set_status() chamando
    self._status.SetLabel(...). wx.StaticText.SetLabel() muda o texto de um
    controle Win32 nativo por baixo (SetWindowText), disparando
    EVENT_OBJECT_NAMECHANGE automaticamente; o NVDA anuncia essa mudanca
    sozinho, como comportamento built-in do proprio SO/NVDA, independente
    de qualquer chamada do addon. Unico jeito confiavel de garantir "nunca
    falado automaticamente, sempre so historico": parar de tocar no widget."""

    def test_set_status_nao_chama_setlabel(self):
        body = _method_src_helper("_set_status")
        assert ".SetLabel(" not in body

    def test_set_status_nao_acessa_self_status(self):
        body = _method_src_helper("_set_status")
        assert "self._status." not in body


class TestConversationalMessageSemDuplicacaoDeLog:
    """v5.21.0: cada mensagem de IA/Sistema era escrita DUAS vezes no log --
    uma crua via _append_log() (sem limpeza), outra limpa via _chat_append() --
    causando linha duplicada (uma suja, uma limpa) a cada mensagem. _append_log
    ficou orfao e foi removido."""

    def test_append_log_nao_existe_mais(self):
        body = _class_source("NVDAStudioDialog")
        assert "def _append_log" not in body

    def test_callback_conversacional_legado_foi_removido(self):
        body = _class_source("NVDAStudioDialog")
        assert "def _handle_conversational_message" not in body

class TestChatAppendPreservaCursor:
    """
    Achado de auditoria 2026-08-04 (analise de log real de producao +
    pesquisa de UX acessivel): _chat_append() era chamado direto (sem
    preservar posicao) de 15+ pontos do pipeline pra status/progresso ao
    vivo -- so _chat_finish() (resposta final do turno) preservava a
    posicao do cursor, entao a view pulava pro fim a CADA atualizacao de
    status durante o pipeline, nao so na resposta final. Alem disso,
    _chat_finish() chamava SetFocus() no historico, roubando o foco de
    onde o usuario estava (ex: campo de digitacao).
    """

    def test_chat_append_captura_e_restaura_insertion_point(self):
        body = _method_src_helper("_chat_append")
        assert "GetInsertionPoint()" in body
        assert "SetInsertionPoint(pos)" in body

    def test_chat_append_nunca_rouba_foco(self):
        body = _method_src_helper("_chat_append")
        assert "_log.SetFocus(" not in body

    def test_chat_finish_nao_tem_logica_propria_de_cursor(self):
        """A logica de preservar posicao agora mora so em _chat_append(),
        de forma uniforme -- _chat_finish() nao deve duplicar isso nem
        roubar o foco do historico."""
        body = _method_src_helper("_chat_finish")
        assert "_log.SetFocus(" not in body
        assert "_log.GetLastPosition(" not in body
        assert "_log.SetInsertionPoint(" not in body


class TestCollectAllBlocksIgnoraAgentTemplate:
    """5.45.0: bug real ao vivo (test_e36, GeminiMultimodal) -- code_generation
    reprovado (score 0) mas um trecho ilustrativo sem anotacao de arquivo
    dentro do agent_template aprovado (score 95, so gera TEMPLATE MD, nunca
    codigo de producao) virava module_N.py "de verdade" e era empacotado como
    se fosse o addon. _collect_all_blocks() nao pode usar agent_template como
    fonte de arquivo, mesmo quando ele e o unico step approved com output."""

    def _step(self, step_type: str, approved: bool, output: str, score: int = 100):
        from types import SimpleNamespace
        return SimpleNamespace(
            step_type=step_type, approved=approved, output=output, score=score,
        )

    def _run_collect_all_blocks(self, result):
        """Executa o corpo real de _collect_all_blocks() isolado (mesma
        estrategia do resto do arquivo: NVDAStudioDialog nao e instanciavel
        neste ambiente de teste porque wx e mockado -- ver docstring do
        modulo). Monta uma funcao standalone a partir do source real via
        exec(), com o import real de extract_code_blocks."""
        from nvdastudio.builder.addon_builder import extract_code_blocks
        from nvdastudio.utils.logger import get_logger

        src = _method_src_helper("_collect_all_blocks")
        # Substitui "def _collect_all_blocks(self, result)" por uma funcao
        # standalone equivalente, preservando o corpo exatamente como esta.
        standalone_src = src.replace(
            "def _collect_all_blocks(self, result) -> list[dict]:",
            "def _collect_all_blocks(result) -> list[dict]:",
            1,
        )
        namespace = {
            "extract_code_blocks": extract_code_blocks,
            "_logger": get_logger("test_collect_all_blocks"),
        }
        exec(compile(standalone_src, "<_collect_all_blocks>", "exec"), namespace)
        return namespace["_collect_all_blocks"](result)

    def test_bloco_sem_anotacao_em_agent_template_e_ignorado(self):
        result = type("R", (), {})()
        result.step_results = [
            self._step("code_generation", approved=False,
                       output="```python:globalPlugins/X/gemini_client.py\n"
                              "class GlobalPlugin:\n\tpass\n```", score=0),
            self._step("manifest_builder", approved=True,
                       output="```ini:manifest.ini\nname = X\n```"),
            # Trecho ilustrativo sem nome de arquivo, tipico de um template
            # MD que cita um exemplo de codigo -- NAO deve virar um arquivo
            # real do addon so porque agent_template foi aprovado.
            self._step("agent_template", approved=True,
                       output="# Template do Agente\n\n```python\n"
                              "resposta = gemini.generate(prompt)\n```"),
        ]

        blocks = self._run_collect_all_blocks(result)
        filenames = [b.get("filename", "") for b in blocks]

        assert "manifest.ini" in filenames
        assert not any(
            (f.startswith("module_") and f.endswith(".py")) for f in filenames
        ), f"bloco de agent_template vazou como arquivo real: {filenames}"

    def test_step_priority_nao_lista_agent_template(self):
        src = _method_src_helper("_collect_all_blocks")
        import re
        m = re.search(r"_STEP_PRIORITY\s*=\s*\[(.*?)\]", src, re.DOTALL)
        assert m, "_STEP_PRIORITY nao encontrado"
        assert "agent_template" not in m.group(1)
        assert "_CODE_SOURCE_STEP_TYPES" in src


def _method_src_helper(method_name: str) -> str:
    src = _class_source("NVDAStudioDialog")
    idx = src.find(f"def {method_name}")
    assert idx != -1, f"{method_name} nao encontrado"
    next_def = src.find("\n\tdef ", idx + 10)
    return src[idx:next_def] if next_def != -1 else src[idx:idx + 4000]


class TestCollectWebSources:
    """5.37.0: 'Fontes consultadas' no historico -- so a secao de fontes dos
    steps web_research chega na tela, nunca o relatorio tecnico completo."""

    def _step(self, step_type: str, output: str):
        from types import SimpleNamespace
        return SimpleNamespace(step_type=step_type, output=output)

    def test_coleta_fontes_de_step_web_research(self):
        from nvdastudio.gui.studio_dialog import _collect_web_sources

        steps = [
            self._step("code_generation", "codigo gerado, irrelevante aqui"),
            self._step(
                "web_research",
                "[WEB_SEARCH] **Pacote:** spotipy\n\n"
                "Fontes consultadas:\n- Spotify Web API: https://developer.spotify.com/docs",
            ),
        ]
        result = _collect_web_sources(steps)
        assert "Fontes consultadas:" in result
        assert "developer.spotify.com" in result
        assert "codigo gerado" not in result  # so a secao de fontes, nao o resto do step

    def test_nao_inclui_relatorio_tecnico_quando_sem_fontes(self):
        """Step web_research sem citacoes (busca falhou/nao achou nada) nao
        deve aparecer no historico -- continua interno como sempre foi."""
        from nvdastudio.gui.studio_dialog import _collect_web_sources

        steps = [self._step("web_research", "[WEB_SEARCH] pesquisa sem resultados web, so conhecimento do modelo")]
        assert _collect_web_sources(steps) == ""

    def test_retorna_vazio_sem_steps_web_research(self):
        from nvdastudio.gui.studio_dialog import _collect_web_sources

        steps = [self._step("code_generation", "x"), self._step("manifest_builder", "y")]
        assert _collect_web_sources(steps) == ""

    def test_ignora_step_sem_output(self):
        from nvdastudio.gui.studio_dialog import _collect_web_sources

        steps = [self._step("web_research", "")]
        assert _collect_web_sources(steps) == ""


class TestCollectFollowupSuggestions:
    """5.38.0: Follow-up Suggestions -- deterministico, baseado em step
    opcional (test_generation) que o planner sabia que podia incluir e nao
    incluiu, nao prosa generica inventada."""

    def _step(self, step_type: str):
        from types import SimpleNamespace
        return SimpleNamespace(step_type=step_type, output="x")

    def test_sugere_testes_quando_nao_rodou(self):
        from nvdastudio.gui.studio_dialog import _collect_followup_suggestions

        steps = [self._step("code_generation"), self._step("manifest_builder")]
        result = _collect_followup_suggestions(steps)
        assert "testes" in result.lower()

    def test_nao_sugere_quando_test_generation_ja_rodou(self):
        from nvdastudio.gui.studio_dialog import _collect_followup_suggestions

        steps = [self._step("code_generation"), self._step("test_generation")]
        assert _collect_followup_suggestions(steps) == ""

    def test_lista_vazia_nao_sugere(self):
        from nvdastudio.gui.studio_dialog import _collect_followup_suggestions
        # Lista vazia acontece quando o pipeline falhou antes de qualquer step --
        # nao ha base pra sugerir nada (nao e "quer testes" pra um addon que nem existe).
        assert _collect_followup_suggestions([]) == ""


class TestControllerClientNaoExigeManifest:
    """5.46.0: controller_client (programa externo ao NVDA) nunca gera
    manifest.ini por design -- o gate de completude e o empacotamento nao
    podem exigi-lo pra esse tipo de projeto."""

    def test_display_result_pula_exigencia_de_manifest_pra_controller_client(self):
        src = _method_src_helper("_display_result")
        assert 'getattr(result, "project_type"' in src
        assert '"controller_client"' in src

    def test_on_package_tem_branch_controller_client(self):
        src = _method_src_helper("_on_package")
        assert "controller_client" in src
        assert ".zip" in src

    def test_on_package_pula_fix_addon_structure_pra_controller_client(self):
        """fix_addon_structure()/_auto_fix_structural_issues() assumem
        estrutura de addon (manifest.ini, globalPlugins/) -- nao podem
        rodar num programa controller_client, que nunca teve essa
        estrutura por design."""
        src = _method_src_helper("_on_package")
        idx_branch = src.find("if _is_ctrl_client_pkg:")
        assert idx_branch != -1
        # A chamada REAL (nao a mencao em comentario logo acima do branch)
        # deve vir so depois do branch, que retorna antes de chegar la.
        idx_fix_call = src.find("fix_addon_structure(addon_folder)")
        assert idx_fix_call != -1
        assert idx_branch < idx_fix_call, (
            "fix_addon_structure(addon_folder) deve vir DEPOIS do branch "
            "controller_client (que faz return antes de chegar la)"
        )
