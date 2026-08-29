from unittest.mock import MagicMock, patch


class TestTruncateAtWord:
    """Bug real reportado por Felipe: narrate() ecoava texto cortado no meio
    de uma palavra (ex: "...que abre o n") porque os call sites usavam slice
    bruto tipo user_query[:150]. _truncate_at_word() corta no ultimo espaco
    antes do limite em vez de no meio de uma palavra."""

    def test_texto_menor_que_limite_nao_e_alterado(self):
        from nvdastudio.sub_agents._base import _truncate_at_word
        assert _truncate_at_word("addon curto", 150) == "addon curto"

    def test_corta_no_ultimo_espaco_antes_do_limite(self):
        from nvdastudio.sub_agents._base import _truncate_at_word
        texto = "Gemini Chat Web que abre o navegador padrao do sistema"
        resultado = _truncate_at_word(texto, 30)
        assert resultado == "Gemini Chat Web que abre o"
        assert not texto[:30].endswith(resultado.split(" ")[-1] + " ")  # nao e o slice bruto

    def test_nunca_termina_no_meio_de_uma_palavra(self):
        from nvdastudio.sub_agents._base import _truncate_at_word
        texto = "informacoes atualizadas sobre apis e bibliotecas para o addon Gemini Chat que abre o navegador"
        resultado = _truncate_at_word(texto, 100)
        assert texto.startswith(resultado)
        proxima_pos = len(resultado)
        assert proxima_pos == len(texto) or texto[proxima_pos] == " "

    def test_sem_espaco_dentro_do_limite_retorna_slice_bruto(self):
        from nvdastudio.sub_agents._base import _truncate_at_word
        assert _truncate_at_word("umapalavraenormesemespacos", 10) == "umapalavra"


class TestNarrateGuardDeTeste:
    def test_narrate_nao_faz_nada_sob_pytest(self):
        """narrate() e silenciosa em teste -- nao gera chamada de rede nem thread solta."""
        from nvdastudio.sub_agents._base import narrate
        with patch("nvdastudio.sub_agents._base.create_llm_client") as mock_create:
            narrate("pesquisando algo")
        mock_create.assert_not_called()

    def test_narrate_vazio_nao_faz_nada(self):
        from nvdastudio.sub_agents._base import narrate
        with patch("nvdastudio.sub_agents._base.threading.Thread") as mock_thread:
            narrate("")
            narrate("   ")
        mock_thread.assert_not_called()


class TestNarrateWork:
    """Testa o corpo real de narrate() diretamente (bypassa o guard de teste)."""

    def test_narrate_work_chama_client_com_modelo_leve(self):
        from nvdastudio.sub_agents._base import _narrate_work

        mock_resp = MagicMock()
        mock_resp.content = "Pesquisando a versao mais recente do pacote."

        with patch("nvdastudio.sub_agents._base.create_llm_client") as mock_create, \
             patch("nvdastudio.sub_agents._base._narrate_light_model", return_value="deepseek-v4-flash"), \
             patch("nvdastudio.sub_agents._base.conversation") as mock_conv:
            mock_create.return_value.chat.return_value = mock_resp
            _narrate_work("pesquisando pacote google-generativeai")

        mock_create.assert_called_once_with(model_id="deepseek-v4-flash")
        mock_conv.emit_status.assert_called_once_with("Pesquisando a versao mais recente do pacote.")

    def test_narrate_work_usa_system_override_conversacional(self):
        from nvdastudio.sub_agents._base import _narrate_work, _NARRATE_SYSTEM

        mock_resp = MagicMock()
        mock_resp.content = "Verificando se o pacote existe."

        with patch("nvdastudio.sub_agents._base.create_llm_client") as mock_create, \
             patch("nvdastudio.sub_agents._base.conversation"):
            mock_create.return_value.chat.return_value = mock_resp
            _narrate_work("verificando pacote x")

        _, kwargs = mock_create.return_value.chat.call_args
        assert kwargs.get("system_override") == _NARRATE_SYSTEM

    def test_narrate_work_nao_emite_se_resposta_vazia(self):
        from nvdastudio.sub_agents._base import _narrate_work

        mock_resp = MagicMock()
        mock_resp.content = "   "

        with patch("nvdastudio.sub_agents._base.create_llm_client") as mock_create, \
             patch("nvdastudio.sub_agents._base.conversation") as mock_conv:
            mock_create.return_value.chat.return_value = mock_resp
            _narrate_work("algo")

        mock_conv.emit_status.assert_not_called()

    def test_narrate_work_engole_excecao_sem_propagar(self):
        from nvdastudio.sub_agents._base import _narrate_work

        with patch("nvdastudio.sub_agents._base.create_llm_client", side_effect=RuntimeError("falhou")):
            _narrate_work("algo")  # nao deve levantar


class TestNarrateSystemPromptConversacional:
    def test_system_prompt_pede_frase_curta_sem_jargao(self):
        from nvdastudio.sub_agents._base import _NARRATE_SYSTEM
        assert "jargao" in _NARRATE_SYSTEM.lower() or "jargão" in _NARRATE_SYSTEM.lower()
        assert "markdown" in _NARRATE_SYSTEM.lower()


class TestNarrateWiredNosSubAgentes:
    """Confirma que narrate() e chamado nos pontos certos, sem instanciar wx/rede."""

    def test_code_generator_importa_narrate(self):
        import inspect
        import nvdastudio.sub_agents.code_generator as mod
        src = inspect.getsource(mod)
        assert "from ._base import" in src and "narrate" in src

    def test_code_generator_narra_validate_import_e_search_web(self):
        import inspect
        import nvdastudio.sub_agents.code_generator as mod
        src = inspect.getsource(mod)
        assert "narrate(" in src
        assert src.count("narrate(") >= 4

    def test_web_researcher_narra_busca(self):
        import inspect
        import nvdastudio.sub_agents.web_researcher as mod
        src = inspect.getsource(mod)
        assert "narrate(" in src


class TestNarrateEstendidoParaTodosOsSubAgentes:
    """Felipe: 'quero estender para que tudo fique igual' -- narrate() nos
    demais sub-agentes que chamam LLM (accessibility_auditor,
    agent_runner_agent, agent_template_agent, assembler, doc_generator,
    manifest_builder, test_generator, design_review_agent). ast_validator,
    syntax_validator e dispatcher ficam de fora de proposito: sao
    deterministicos, zero chamada de rede/LLM, narrar ali so adicionaria
    latencia sem nada real para narrar."""

    _AGENTES_COM_NARRATE = [
        "accessibility_auditor",
        "agent_runner_agent",
        "agent_template_agent",
        "assembler",
        "doc_generator",
        "manifest_builder",
        "test_generator",
        "design_review_agent",
    ]

    def test_todos_os_agentes_llm_importam_e_chamam_narrate(self):
        import importlib
        import inspect
        for nome in self._AGENTES_COM_NARRATE:
            mod = importlib.import_module(f"nvdastudio.sub_agents.{nome}")
            src = inspect.getsource(mod)
            assert "narrate" in src, f"{nome} nao importa narrate"
            assert "narrate(" in src, f"{nome} nao chama narrate()"

    def test_agentes_deterministicos_nao_precisam_de_narrate(self):
        """Documenta a decisao de nao instrumentar os 3 agentes sem LLM."""
        import importlib
        import inspect
        for nome in ("ast_validator", "syntax_validator", "dispatcher"):
            mod = importlib.import_module(f"nvdastudio.sub_agents.{nome}")
            src = inspect.getsource(mod)
            assert "create_llm_client" not in src, (
                f"{nome} deveria ser deterministico (sem chamada LLM direta)"
            )


class TestSentenceChunkBufferViaLiveNarrator:
    """_SentenceChunkBuffer (base compartilhada) testada via LiveNarrator --
    ReasoningNarrator (a outra subclasse historica) foi removido: ficou sem
    nenhum consumidor em producao depois que o planejamento passou a narrar
    de verdade via tool call (LiveNarrator) em vez de reescrever o resumo
    de raciocinio via narrate()."""

    def test_feed_nao_emite_antes_de_fechar_frase(self):
        from nvdastudio.sub_agents._base import LiveNarrator
        with patch("nvdastudio.sub_agents._base.conversation") as mock_conv:
            narrator = LiveNarrator()
            narrator.feed("Pensando sobre a arquitetura")  # sem pontuacao final, curto
        mock_conv.emit_status.assert_not_called()

    def test_feed_emite_ao_fechar_frase_apos_minimo_de_caracteres(self):
        from nvdastudio.sub_agents._base import LiveNarrator
        frase = "Vou usar uma classe separada para a logica de rede, assim fica mais facil testar. "
        with patch("nvdastudio.sub_agents._base.conversation") as mock_conv:
            narrator = LiveNarrator()
            narrator.feed(frase)
        mock_conv.emit_status.assert_called_once()
        assert mock_conv.emit_status.call_args[0][0].strip() == frase.strip()

    def test_feed_acumula_deltas_pequenos_ate_fechar_frase(self):
        from nvdastudio.sub_agents._base import LiveNarrator
        deltas = [
            "Vou ", "usar ", "threading ", "separado ", "para ", "nao ",
            "travar ", "a ", "interface ", "principal ", "enquanto ",
            "o ", "plano ", "e ", "gerado ", "em ", "segundo ", "plano.",
        ]
        with patch("nvdastudio.sub_agents._base.conversation") as mock_conv:
            narrator = LiveNarrator()
            for delta in deltas:
                narrator.feed(delta)
        mock_conv.emit_status.assert_called_once()
        assert "threading" in mock_conv.emit_status.call_args[0][0]

    def test_feed_ignora_delta_vazio(self):
        from nvdastudio.sub_agents._base import LiveNarrator
        with patch("nvdastudio.sub_agents._base.conversation") as mock_conv:
            narrator = LiveNarrator()
            narrator.feed("")
            narrator.feed(None)
        mock_conv.emit_status.assert_not_called()

    def test_flush_emite_resto_pendente(self):
        from nvdastudio.sub_agents._base import LiveNarrator
        with patch("nvdastudio.sub_agents._base.conversation") as mock_conv:
            narrator = LiveNarrator()
            narrator.feed("frase incompleta sem pontuacao final e sem fechar")
            mock_conv.emit_status.assert_not_called()
            narrator.flush()
        mock_conv.emit_status.assert_called_once()

    def test_flush_com_buffer_vazio_nao_emite(self):
        from nvdastudio.sub_agents._base import LiveNarrator
        with patch("nvdastudio.sub_agents._base.conversation") as mock_conv:
            narrator = LiveNarrator()
            narrator.flush()
        mock_conv.emit_status.assert_not_called()

    def test_flush_limpa_o_buffer(self):
        from nvdastudio.sub_agents._base import LiveNarrator
        with patch("nvdastudio.sub_agents._base.conversation"):
            narrator = LiveNarrator()
            narrator.feed("algo pendente")
            narrator.flush()
            assert narrator._buffer == ""

    def test_reasoning_narrator_removido(self):
        """v1.14.0: ReasoningNarrator removido -- sem consumidor em producao."""
        from nvdastudio.sub_agents import _base
        assert not hasattr(_base, "ReasoningNarrator")


class TestLiveNarratorSuprimeConteudoDentroDeFence:
    """v1.15.0: bug real de live-test -- Felipe colou o historico mostrando
    dezenas de linhas de codigo Python/HTML/JSON aparecendo como se fossem
    narracao. extract_code_blocks() so protege o ARTEFATO FINAL salvo em
    disco -- nunca protegeu o que e exibido AO VIVO via LiveNarrator. Agora
    feed() detecta blocos ```fence``` e suprime tudo que esta dentro deles."""

    def test_texto_dentro_de_fence_nunca_emite(self):
        from nvdastudio.sub_agents._base import LiveNarrator
        with patch("nvdastudio.sub_agents._base.conversation") as mock_conv:
            narrator = LiveNarrator()
            narrator.feed("Vou escrever o codigo agora. ")
            narrator.feed("```python:globalPlugins/X/__init__.py\n")
            narrator.feed("import wx\nclass GlobalPlugin: pass\n")
            narrator.feed("```\n")
            narrator.feed("Pronto, terminei de escrever o arquivo. ")
            narrator.flush()
        emitidos = [c.args[0] for c in mock_conv.emit_status.call_args_list]
        texto_completo = " ".join(emitidos)
        assert "import wx" not in texto_completo
        assert "GlobalPlugin" not in texto_completo
        assert "Vou escrever o codigo agora." in texto_completo
        assert "Pronto, terminei de escrever o arquivo." in texto_completo

    def test_fence_fragmentado_entre_deltas_de_streaming_e_detectado(self):
        """O delimitador ``` pode chegar partido entre dois deltas de
        streaming (ex: um delta termina em "``", o proximo comeca com "`
        python:arquivo.py"). O detector precisa juntar isso corretamente."""
        from nvdastudio.sub_agents._base import LiveNarrator
        with patch("nvdastudio.sub_agents._base.conversation") as mock_conv:
            narrator = LiveNarrator()
            narrator.feed("Escrevendo agora. ``")
            narrator.feed("`python:arquivo.py\nsegredo_que_nao_pode_vazar = 1\n")
            narrator.feed("```")
            narrator.feed(" Terminei o arquivo com sucesso. ")
            narrator.flush()
        emitidos = [c.args[0] for c in mock_conv.emit_status.call_args_list]
        texto_completo = " ".join(emitidos)
        assert "segredo_que_nao_pode_vazar" not in texto_completo
        assert "Terminei o arquivo com sucesso." in texto_completo

    def test_multiplos_fences_intercalados_com_narracao(self):
        from nvdastudio.sub_agents._base import LiveNarrator
        with patch("nvdastudio.sub_agents._base.conversation") as mock_conv:
            narrator = LiveNarrator()
            narrator.feed("Primeiro o manifest. ")
            narrator.feed("```ini:manifest.ini\nname = X\n```\n")
            narrator.feed("Agora o codigo principal. ")
            narrator.feed("```python:__init__.py\nimport ui\n```\n")
            narrator.feed("Terminei os dois arquivos. ")
            narrator.flush()
        emitidos = [c.args[0] for c in mock_conv.emit_status.call_args_list]
        texto_completo = " ".join(emitidos)
        assert "name = X" not in texto_completo
        assert "import ui" not in texto_completo
        assert "Primeiro o manifest." in texto_completo
        assert "Agora o codigo principal." in texto_completo
        assert "Terminei os dois arquivos." in texto_completo

    def test_stream_que_termina_dentro_de_fence_nao_vaza_nada_no_flush(self):
        """Se o streaming acabar no meio de um bloco de codigo (ex: erro de
        rede), flush() nao deve vazar o codigo parcial pendente."""
        from nvdastudio.sub_agents._base import LiveNarrator
        with patch("nvdastudio.sub_agents._base.conversation") as mock_conv:
            narrator = LiveNarrator()
            narrator.feed("Escrevendo o arquivo. ")
            narrator.feed("```python:arquivo.py\ncodigo_parcial_pendente = 1")
            narrator.flush()
        emitidos = [c.args[0] for c in mock_conv.emit_status.call_args_list]
        texto_completo = " ".join(emitidos)
        assert "codigo_parcial_pendente" not in texto_completo
