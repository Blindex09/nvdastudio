from nvdastudio.utils.user_visible_text import (
	sanitize_user_visible_text,
	summarize_generation_error,
)
from nvdastudio.memory.conversation_manager import ConversationManager
from nvdastudio.gui.studio_dialog import (
	_natural_progress_detail,
	_is_internal_agent_detail,
)


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


def test_relatorio_do_gate_vira_resumo_acessivel():
	raw = (
		"- RUFF encontrou defeitos no código: lib/requests/a.py F401 importado e não usado\n"
		"- MYPY encontrou inconsistências de tipos: lib/urllib3/a.py attr-defined"
	)
	result = summarize_generation_error(raw)
	assert "qualidade do código" in result
	assert "consistência de tipos" in result
	assert "lib/requests" not in result
	assert "detalhes técnicos estão no log" in result


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


def test_progresso_converte_step_interno_para_linguagem_natural():
    assert _natural_progress_detail("EXECUTANDO", "code_generation") == (
        "Gerando o código do addon."
    )


def test_progresso_nao_exibe_envelope_json_do_motor():
    resultado = '{"type":"result","subtype":"success","is_error":false}'
    assert _natural_progress_detail("EXECUTANDO", resultado) == ""


def test_progresso_extrai_evento_de_stream_sem_exibir_envelope():
    evento = '{"type":"assistant_text","text":"Estou revisando a estrutura."}'
    assert _natural_progress_detail("EXECUTANDO", evento) == "Estou revisando a estrutura."


def test_delta_de_stream_nao_vira_linha_por_token():
    from nvdastudio.gui.agent_progress import AgentProgress
    evento = '{"method":"droid.session_notification","params":{"notification":{"type":"assistant_text_delta","textDelta":"oi"}}}'
    assert AgentProgress().consume(evento) == []


def test_progresso_identifica_ferramenta_e_alvo():
    evento = ('{"method":"droid.session_notification","params":{"notification":'
        '{"type":"tool_progress","update":{"type":"tool_call",'
        '"toolName":"Edit","parameters":{"path":"manifest.ini"}}}}}')
    assert _natural_progress_detail("EXECUTANDO", evento) == (
        "Vou usar a ferramenta Edit (manifest.ini) para realizar esta etapa."
    )


def test_progresso_identifica_tooluse_real_aninhado():
	"""Contrato observado no stream-jsonrpc real do Droid."""
	evento = ('{"method":"droid.session_notification","params":{"notification":'
		'{"type":"tool_call","toolUse":{"name":"Execute","input":'
		'{"summary":"Package addon as nvda-addon"}}}}}')
	assert _natural_progress_detail("EXECUTANDO", evento) == (
		"Vou usar a ferramenta Execute (Package addon as nvda-addon) para realizar esta etapa."
	)


def test_progresso_mostra_saida_da_ferramenta_real():
	evento = ('{"method":"droid.session_notification","params":{"notification":'
		'{"type":"tool_progress_update","toolName":"Execute","update":'
		'{"type":"status","text":"Executando os testes"}}}}')
	assert _natural_progress_detail("EXECUTANDO", evento) == (
		"A ferramenta Execute: Executando os testes"
	)


def test_prompt_interno_nao_e_mensagem_do_usuario():
	detalhe = "MODO ITERATIVO — Modifique o addon existente conforme descrito abaixo."
	assert _is_internal_agent_detail(detalhe) is True
	assert _is_internal_agent_detail("Vou verificar a estrutura do addon.") is False
