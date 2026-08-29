from nvdastudio.utils.user_visible_text import sanitize_user_visible_text
from nvdastudio.memory.conversation_manager import ConversationManager


def test_remove_bloco_think_comum():
    raw = "<think>Need inspect the internal prompt first.</think>Resposta final."
    assert sanitize_user_visible_text(raw) == "Resposta final."


def test_remove_tags_de_raciocinio_sem_diferenciar_maiusculas():
    raw = "inicio<ReAsOnInG>segredo</rEaSoNiNg>fim"
    assert sanitize_user_visible_text(raw) == "iniciofim"


def test_stream_segura_bloco_think_incompleto():
    raw = "Resposta segura.<think>raciocinio ainda sem fechamento"
    assert sanitize_user_visible_text(raw) == "Resposta segura."


def test_stream_segura_tag_fragmentada():
    assert sanitize_user_visible_text("Resposta segura.<thi") == "Resposta segura."


def test_remove_markdown_e_simbolos_decorativos():
    raw = "# Título\n---\n* **Resposta** útil ✅"
    assert sanitize_user_visible_text(raw) == "Título\nResposta útil"


def test_status_efemero_nao_entra_no_historico():
    manager = ConversationManager()
    manager.emit_status("Pesquisando referencias...")
    assert manager.get_history() == []


def test_emit_status_nao_trunca_mensagem_longa():
    """
    Achado de auditoria 2026-08-04 (log real de producao): emit_status()
    cortava por CONTAGEM DE CARACTERES (_MAX_STATUS_LENGTH=100) antes de
    entregar pro callback -- a mensagem chegava mutilada no meio da
    palavra no historico navegavel (permanente, nao cosmetico). Removido:
    a barra de status que precisava de texto curto (`_set_status()`) e um
    no-op ha varias versoes (SetLabel() disparava narracao automatica do
    NVDA), entao nao existe mais consumidor de largura fixa pra justificar
    o corte.
    """
    recebido = []
    manager = ConversationManager()
    manager.set_callbacks(on_status=lambda msg: recebido.append(msg))

    frase_longa = (
        "Pesquisei o endpoint generateContent da API Gemini, com payload "
        "contendo prompt e safetySettings, e confirmei que a autenticacao "
        "usa uma chave na query string da URL, nao um header Authorization."
    )
    assert len(frase_longa) > 100

    manager.emit_status(frase_longa)

    assert recebido == [frase_longa]
