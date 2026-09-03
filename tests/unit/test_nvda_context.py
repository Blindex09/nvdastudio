from nvdastudio.builder.nvda_context import (
    NVDA_SYSTEM_PROMPT, PROMPT_VERSION, NVDA_QUICK_TIPS,
    NVDA_DETECTION_RULES, WX_A11Y_RULES, DTK_A11Y_RULES, NVDA_VERSION_TABLE,
)

_EMOJIS_PROIBIDOS = [
    "\u2705", "\u274c", "\u26a0", "\U0001f4e6",
    "\U0001f916", "\u2728", "\u2764", "\U0001f680",
]


class TestPromptVersion:
    def test_prompt_version_definido(self):
        assert PROMPT_VERSION, "PROMPT_VERSION nao pode ser vazio"

    def test_prompt_version_formato_semver(self):
        partes = PROMPT_VERSION.split(".")
        assert len(partes) == 3
        for parte in partes:
            assert parte.isdigit()


class TestNvdaSystemPromptConteudo:
    def test_prompt_nao_vazio(self):
        assert NVDA_SYSTEM_PROMPT and NVDA_SYSTEM_PROMPT.strip()

    def test_prompt_contem_nvda(self):
        assert "NVDA" in NVDA_SYSTEM_PROMPT

    def test_prompt_menciona_global_plugin(self):
        assert "GlobalPlugin" in NVDA_SYSTEM_PROMPT or "globalPlugin" in NVDA_SYSTEM_PROMPT

    def test_prompt_menciona_manifest(self):
        assert "manifest" in NVDA_SYSTEM_PROMPT.lower()

    def test_prompt_menciona_acessibilidade(self):
        prompt_lower = NVDA_SYSTEM_PROMPT.lower()
        assert "acessib" in prompt_lower or "label" in prompt_lower

    def test_prompt_menciona_wx_call_after(self):
        assert "CallAfter" in NVDA_SYSTEM_PROMPT

    def test_prompt_menciona_imports(self):
        assert "import" in NVDA_SYSTEM_PROMPT.lower()

    def test_prompt_menciona_try_except(self):
        assert "try" in NVDA_SYSTEM_PROMPT or "except" in NVDA_SYSTEM_PROMPT

    def test_prompt_menciona_addon_handler(self):
        assert "addonHandler" in NVDA_SYSTEM_PROMPT

    def test_prompt_menciona_ui_message(self):
        assert "ui.message" in NVDA_SYSTEM_PROMPT

    def test_prompt_menciona_baseline_2026_1_1(self):
        assert "2026.1.1" in NVDA_SYSTEM_PROMPT

    def test_prompt_menciona_forward_compat_2026(self):
        assert "2026.1" in NVDA_SYSTEM_PROMPT

    def test_prompt_menciona_terminate(self):
        """v2.0.0: terminate() e regra critica NVDA-004."""
        assert "terminate" in NVDA_SYSTEM_PROMPT.lower()

    def test_prompt_menciona_next_handler(self):
        """v2.0.0: nextHandler() e regra critica NVDA-001."""
        assert "nextHandler" in NVDA_SYSTEM_PROMPT

    def test_prompt_menciona_versoes_manifest(self):
        """v2.0.0: tabela de versoes minimumNVDAVersion deve estar no prompt."""
        assert "minimumNVDAVersion" in NVDA_SYSTEM_PROMPT or "minimumNvdaVersion" in NVDA_SYSTEM_PROMPT

    def test_prompt_menciona_2019_3(self):
        """O limite tecnico absoluto do ecossistema ainda deve estar documentado."""
        assert "2019.3" in NVDA_SYSTEM_PROMPT


class TestNvdaSystemPromptEncoding:
    def test_prompt_sem_emojis(self):
        for emoji in _EMOJIS_PROIBIDOS:
            assert emoji not in NVDA_SYSTEM_PROMPT

    def test_prompt_encodavel_cp1252_com_replace(self):
        encoded = NVDA_SYSTEM_PROMPT.encode("cp1252", errors="replace")
        assert len(encoded) > 0

    def test_prompt_e_string(self):
        assert isinstance(NVDA_SYSTEM_PROMPT, str)


class TestIntegracaoProvedoresIA:
    """v3.23.0: secao 4 (INTEGRACAO COM PROVEDORES DE IA/LLM) -- endpoint,
    auth e formato de request atuais (2026) para os 5 provedores do painel,
    para addons gerados nao dependerem so de conhecimento de treinamento
    (que pode estar desatualizado, ex: Chat Completions em vez de Responses
    API) nem de pesquisa web toda vez que o pedido mencionar um provedor
    conhecido."""

    def test_menciona_os_5_provedores(self):
        for nome in ("OpenAI", "xAI", "Anthropic", "Gemini", "Ollama"):
            assert nome in NVDA_SYSTEM_PROMPT, f"Provedor '{nome}' ausente na secao de integracao"

    def test_openai_usa_responses_api_nao_chat_completions(self):
        assert "/v1/responses" in NVDA_SYSTEM_PROMPT
        assert "/v1/chat/completions" not in NVDA_SYSTEM_PROMPT

    def test_gemini_usa_interactions_api_nao_generatecontent(self):
        assert "/v1/interactions" in NVDA_SYSTEM_PROMPT
        # "generateContent" aparece de proposito no texto (contraste explicito
        # "Interactions API, nao generateContent") -- o que nao pode existir
        # e o endpoint antigo em si.
        assert ":generateContent" not in NVDA_SYSTEM_PROMPT
        assert "v1beta/models" not in NVDA_SYSTEM_PROMPT

    def test_anthropic_menciona_messages_api_e_version_header(self):
        assert "/v1/messages" in NVDA_SYSTEM_PROMPT
        assert "anthropic-version" in NVDA_SYSTEM_PROMPT

    def test_ollama_menciona_endpoint_correto(self):
        assert "ollama.com/api/chat" in NVDA_SYSTEM_PROMPT

    def test_orienta_pesquisa_web_para_provedor_desconhecido(self):
        """Regra 7: decisao continua semantica (sem keyword hardcoded na
        LOGICA de decisao) -- aqui e so a instrucao textual do prompt,
        orientando o LLM planejador a preferir pesquisar quando o provedor
        nao estiver na lista coberta."""
        assert "requires_web_research=true" in NVDA_SYSTEM_PROMPT

    def test_orienta_pesquisa_mesmo_para_provedor_conhecido_em_funcionalidade_avancada(self):
        """v3.24.0: a secao so documenta o chat basico -- para streaming,
        tool calling, visao, structured output, extended thinking, cache de
        prompt etc., a orientacao e pesquisar mesmo que o provedor esteja
        entre os 5 conhecidos. Duas ocorrencias distintas do gatilho:
        provedor fora da lista (v3.23.0) e funcionalidade avancada dentro
        da lista (v3.24.0)."""
        assert NVDA_SYSTEM_PROMPT.count("requires_web_research=true") >= 2
        idx = NVDA_SYSTEM_PROMPT.find("mesmo que o")
        assert idx != -1
        trecho = NVDA_SYSTEM_PROMPT[idx:idx + 120]
        assert "provedor esteja nesta lista" in trecho

    def test_menciona_funcionalidades_nativas_nao_detalhadas(self):
        """As funcionalidades nativas alem do chat basico devem ser citadas
        por nome (para o LLM saber que elas existem e podem precisar de
        pesquisa), mesmo sem sintaxe detalhada de cada uma."""
        for termo in ("tool/function calling", "visao", "extended thinking", "cache de prompt"):
            assert termo in NVDA_SYSTEM_PROMPT, f"'{termo}' nao mencionado na secao de integracao"

    def test_secao_reforca_thread_em_background(self):
        """ARCH-002 tambem se aplica a chamadas de API de IA."""
        idx = NVDA_SYSTEM_PROMPT.find("INTEGRACAO COM PROVEDORES DE IA/LLM")
        assert idx != -1
        trecho = NVDA_SYSTEM_PROMPT[idx:idx + 600]
        assert "threading.Thread" in trecho


class TestNvdaQuickTips:
    def test_quick_tips_nao_vazio(self):
        assert len(NVDA_QUICK_TIPS) > 0

    def test_quick_tips_sao_tuplas_de_dois_elementos(self):
        for tip in NVDA_QUICK_TIPS:
            assert isinstance(tip, tuple)
            assert len(tip) == 2

    def test_quick_tips_sem_titulo_vazio(self):
        for titulo, _ in NVDA_QUICK_TIPS:
            assert titulo.strip()

    def test_quick_tips_sem_descricao_vazia(self):
        for _, descricao in NVDA_QUICK_TIPS:
            assert descricao.strip()

    def test_quick_tips_sem_emojis(self):
        for titulo, descricao in NVDA_QUICK_TIPS:
            texto = titulo + descricao
            for emoji in _EMOJIS_PROIBIDOS:
                assert emoji not in texto

    def test_quick_tips_tem_ao_menos_5_dicas(self):
        assert len(NVDA_QUICK_TIPS) >= 5

    def test_quick_tips_titulos_sao_unicos(self):
        titulos = [t for t, _ in NVDA_QUICK_TIPS]
        assert len(titulos) == len(set(titulos))


class TestNvdaDetectionRules:
    """v2.0.0: NVDA_DETECTION_RULES com 18 regras do Community Access."""

    def test_detection_rules_existem(self):
        assert NVDA_DETECTION_RULES is not None
        assert len(NVDA_DETECTION_RULES) > 0

    def test_exatamente_62_regras(self):
        """62 apos NVDA-063 (assinatura divergente entre arquivos,
        achado da rodada AssistenteEscrita de 2026-09-03)."""
        assert len(NVDA_DETECTION_RULES) == 62

    def test_cada_regra_tem_3_elementos(self):
        for rule in NVDA_DETECTION_RULES:
            assert len(rule) == 3, f"Regra deve ter (id, severity, descricao): {rule}"

    def test_ids_sao_unicos(self):
        ids = [r[0] for r in NVDA_DETECTION_RULES]
        assert len(ids) == len(set(ids))

    def test_ids_formato_nvda(self):
        for rule_id, _, _ in NVDA_DETECTION_RULES:
            assert rule_id.startswith("NVDA-"), f"ID deve comecar com NVDA-: {rule_id}"

    def test_regra_001_next_handler(self):
        """NVDA-001: falta nextHandler — critico."""
        rule = next((r for r in NVDA_DETECTION_RULES if r[0] == "NVDA-001"), None)
        assert rule is not None
        assert "Critico" in rule[1] or "critico" in rule[1].lower()
        assert "nextHandler" in rule[2]

    def test_regra_017_dll_64bit(self):
        """NVDA-017: DLL 32-bit em NVDA 64-bit — critico para forward-compatibility."""
        rule = next((r for r in NVDA_DETECTION_RULES if r[0] == "NVDA-017"), None)
        assert rule is not None
        assert "Critico" in rule[1] or "critico" in rule[1].lower()

    def test_regra_018_versao_minima(self):
        """NVDA-018: minimumNVDAVersion abaixo de 2019.3.0."""
        rule = next((r for r in NVDA_DETECTION_RULES if r[0] == "NVDA-018"), None)
        assert rule is not None
        assert "2019.3" in rule[2]

    def test_severidades_validas(self):
        severidades = {"Critico", "Serio", "Moderado", "Menor"}
        for _, sev, _ in NVDA_DETECTION_RULES:
            assert sev in severidades, f"Severidade invalida: {sev}"

    def test_sem_emojis_nas_regras(self):
        for rule_id, sev, desc in NVDA_DETECTION_RULES:
            texto = rule_id + sev + desc
            for emoji in _EMOJIS_PROIBIDOS:
                assert emoji not in texto


class TestWxA11yRules:
    """v2.1.0: WX_A11Y_RULES com 14 regras.
    Fonte: github.com/Community-Access/accessibility-agents .github/agents/wxpython-specialist.agent.md
    v2.0.0 tinha 12 regras com conteudo errado (IDs 005-011 errados, 013-014 ausentes).
    """

    def test_wx_a11y_rules_existem(self):
        assert WX_A11Y_RULES is not None
        assert len(WX_A11Y_RULES) > 0

    def test_exatamente_14_regras(self):
        # Fonte: wxpython-specialist.agent.md — 14 regras na tabela Detection Rules
        assert len(WX_A11Y_RULES) == 14

    def test_ids_formato_wx(self):
        for rule_id, _, _ in WX_A11Y_RULES:
            assert rule_id.startswith("WX-A11Y-"), f"ID deve comecar com WX-A11Y-: {rule_id}"

    def test_regra_005_showmodal_sem_setfocus(self):
        """WX-A11Y-005: Dialog.ShowModal() sem SetFocus() — Serio.
        Fonte: wxpython-specialist.agent.md linha da tabela WX-A11Y-005.
        """
        rule = next((r for r in WX_A11Y_RULES if r[0] == "WX-A11Y-005"), None)
        assert rule is not None
        assert "Serio" in rule[1], f"WX-A11Y-005 deve ser Serio: {rule[1]}"
        assert "ShowModal" in rule[2] or "SetFocus" in rule[2], f"Deve mencionar ShowModal/SetFocus: {rule[2]}"

    def test_regra_013_evtkeydow_listbox_critico(self):
        """WX-A11Y-013: EVT_KEY_DOWN em ListBox/ListCtrl falha com NVDA/JAWS — Critico.
        Fonte: wxpython-specialist.agent.md secao Screen Reader Key Event Pitfalls.
        """
        rule = next((r for r in WX_A11Y_RULES if r[0] == "WX-A11Y-013"), None)
        assert rule is not None
        assert "Critico" in rule[1], f"WX-A11Y-013 deve ser Critico: {rule[1]}"
        assert "EVT_CHAR_HOOK" in rule[2] or "EVT_KEY_DOWN" in rule[2], f"Deve mencionar EVT: {rule[2]}"

    def test_regra_014_listctrl_item_activated(self):
        """WX-A11Y-014: ListCtrl deve usar EVT_LIST_ITEM_ACTIVATED — Serio.
        Fonte: wxpython-specialist.agent.md tabela Detection Rules linha 014.
        """
        rule = next((r for r in WX_A11Y_RULES if r[0] == "WX-A11Y-014"), None)
        assert rule is not None
        assert "Serio" in rule[1], f"WX-A11Y-014 deve ser Serio: {rule[1]}"
        assert "EVT_LIST_ITEM_ACTIVATED" in rule[2], f"Deve mencionar EVT_LIST_ITEM_ACTIVATED: {rule[2]}"

    def test_regras_001_002_003_sao_criticas(self):
        """WX-A11Y-001/002/003 sao Critico.
        Fonte: wxpython-specialist.agent.md tabela Detection Rules.
        """
        for rid in ("WX-A11Y-001", "WX-A11Y-002", "WX-A11Y-003"):
            rule = next((r for r in WX_A11Y_RULES if r[0] == rid), None)
            assert rule is not None
            assert "Critico" in rule[1], f"{rid} deve ser Critico: {rule[1]}"


class TestDtkA11yRules:
    """v3.37.0: DTK_A11Y_RULES com 12 regras — camada de API de plataforma
    (UIA/MSAA), complementar as regras WX-A11Y existentes.
    Fonte: github.com/Community-Access/accessibility-agents .github/agents/desktop-a11y-specialist.agent.md
    """

    def test_dtk_a11y_rules_existem(self):
        assert DTK_A11Y_RULES is not None
        assert len(DTK_A11Y_RULES) > 0

    def test_exatamente_12_regras(self):
        # Fonte: desktop-a11y-specialist.agent.md — 12 regras na tabela Detection Rules
        assert len(DTK_A11Y_RULES) == 12

    def test_ids_formato_dtk(self):
        for rule_id, _, _ in DTK_A11Y_RULES:
            assert rule_id.startswith("DTK-A11Y-"), f"ID deve comecar com DTK-A11Y-: {rule_id}"

    def test_nao_colide_com_ids_wx_a11y(self):
        wx_ids = {r[0] for r in WX_A11Y_RULES}
        dtk_ids = {r[0] for r in DTK_A11Y_RULES}
        assert wx_ids.isdisjoint(dtk_ids), "DTK-A11Y nao deve reutilizar/colidir com IDs de WX-A11Y"

    def test_regra_001_missing_name_critico(self):
        """DTK-A11Y-001: controle interativo sem Name via UIA/MSAA — Critico."""
        rule = next((r for r in DTK_A11Y_RULES if r[0] == "DTK-A11Y-001"), None)
        assert rule is not None
        assert "Critico" in rule[1], f"DTK-A11Y-001 deve ser Critico: {rule[1]}"
        assert "Name" in rule[2] or "UIA" in rule[2] or "MSAA" in rule[2]

    def test_regra_005_teclado_inalcancavel_critico(self):
        """DTK-A11Y-005: elemento interativo nao alcancavel via teclado — Critico."""
        rule = next((r for r in DTK_A11Y_RULES if r[0] == "DTK-A11Y-005"), None)
        assert rule is not None
        assert "Critico" in rule[1], f"DTK-A11Y-005 deve ser Critico: {rule[1]}"
        assert "teclado" in rule[2].lower()

    def test_regra_010_modal_focus_escape_serio(self):
        """DTK-A11Y-010: dialogo modal nao prende o foco — Serio."""
        rule = next((r for r in DTK_A11Y_RULES if r[0] == "DTK-A11Y-010"), None)
        assert rule is not None
        assert "Serio" in rule[1], f"DTK-A11Y-010 deve ser Serio: {rule[1]}"
        assert "modal" in rule[2].lower() or "dialogo" in rule[2].lower()


class TestNvdaVersionTable:
    """NVDA_VERSION_TABLE com baseline oficial e faixas auxiliares do projeto."""

    def test_version_table_existe(self):
        assert NVDA_VERSION_TABLE is not None
        assert len(NVDA_VERSION_TABLE) > 0

    def test_cada_linha_tem_3_elementos(self):
        for row in NVDA_VERSION_TABLE:
            assert len(row) == 3, f"Linha deve ter (cenario, min, tested): {row}"

    def test_versao_minima_nao_abaixo_de_2019_3(self):
        """Regra NVDA-018: minimumNVDAVersion nunca abaixo de 2019.3.0."""
        for cenario, min_ver, _ in NVDA_VERSION_TABLE:
            partes = min_ver.split(".")
            ano = int(partes[0])
            assert ano >= 2019, f"Cenario '{cenario}': ano {ano} abaixo do minimo"

    def test_linha_forward_compat_aponta_para_2026(self):
        """A tabela deve preservar uma linha de forward-compatibility para NVDA 2026.1+."""
        row = next((r for r in NVDA_VERSION_TABLE if "2026.1+" in r[0]), None)
        assert row is not None
        assert "2026" in row[2], f"Linha forward-compat deve apontar para 2026.x: {row}"

    def test_baseline_oficial_e_2026_1_1(self):
        row = next((r for r in NVDA_VERSION_TABLE if "Baseline oficial" in r[0]), None)
        assert row is not None
        assert row[1] == "2026.1.1"
        assert row[2] == "2026.2.0"
