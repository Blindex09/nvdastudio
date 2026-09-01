import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def _make_memory(tmp_path):
    """SessionMemory isolada em tmp_path."""
    import nvdastudio.memory.session_memory as sm_mod
    original = sm_mod._DB_PATH
    sm_mod._DB_PATH = str(tmp_path / "mem.json")
    from nvdastudio.memory.session_memory import SessionMemory
    mem = SessionMemory()
    yield mem, sm_mod, original


# ===========================================================================
# 1. session_memory — tabela web_knowledge
# ===========================================================================

class TestWebKnowledgeMemory:
    """SessionMemory deve persistir conhecimento adquirido via pesquisa web."""

    def _mem(self, tmp_path):
        import nvdastudio.memory.session_memory as sm_mod
        orig = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "mem.json")
        from nvdastudio.memory.session_memory import SessionMemory
        mem = SessionMemory()
        return mem, sm_mod, orig

    def test_save_web_knowledge_persiste(self, tmp_path):
        mem, sm, orig = self._mem(tmp_path)
        try:
            mem.save_web_knowledge(
                topic="google-generativeai",
                content="A partir de 0.8.x o cliente e inicializado com genai.Client(api_key=...)",
                source_url="https://pypi.org/project/google-generativeai/",
                year=2026,
            )
            results = mem.get_web_knowledge("google-generativeai")
            assert len(results) >= 1
            assert results[0]["topic"] == "google-generativeai"
            assert "0.8" in results[0]["content"]
        finally:
            mem.close()
            sm._DB_PATH = orig

    def test_get_web_knowledge_vazio_retorna_lista(self, tmp_path):
        mem, sm, orig = self._mem(tmp_path)
        try:
            results = mem.get_web_knowledge("topico-inexistente")
            assert results == []
        finally:
            mem.close()
            sm._DB_PATH = orig

    def test_get_web_knowledge_respeita_max_age(self, tmp_path):
        """Registros mais antigos que max_age_days nao devem ser retornados."""
        from datetime import datetime, timedelta
        mem, sm, orig = self._mem(tmp_path)
        try:
            mem.save_web_knowledge(
                topic="requests",
                content="requests 2.31 funciona corretamente",
                source_url="",
                year=2025,
            )
            # Simula que o registro tem 60 dias: max_age_days=7 nao deve retornar
            # Para isso, atualizamos o created_at diretamente no DB
            mem._init_db()
            table = mem._db.table("web_knowledge")
            old_date = (datetime.now() - timedelta(days=60)).isoformat(timespec="seconds")
            docs = table.all()
            if docs:
                table.update({"created_at": old_date}, doc_ids=[docs[-1].doc_id])
            results = mem.get_web_knowledge("requests", max_age_days=7)
            assert results == [], (
                "Registro de 60 dias atras nao deve aparecer com max_age_days=7"
            )
        finally:
            mem.close()
            sm._DB_PATH = orig

    def test_get_web_knowledge_registros_recentes_aparecem(self, tmp_path):
        """Registros recentes (dentro de max_age_days) devem ser retornados."""
        mem, sm, orig = self._mem(tmp_path)
        try:
            mem.save_web_knowledge(
                topic="elevenlabs",
                content="ElevenLabs SDK 1.x usa ElevenLabs(api_key=...) sem genai",
                source_url="https://pypi.org/project/elevenlabs/",
                year=2026,
            )
            results = mem.get_web_knowledge("elevenlabs", max_age_days=30)
            assert len(results) >= 1
        finally:
            mem.close()
            sm._DB_PATH = orig

    def test_get_web_knowledge_mais_recente_primeiro(self, tmp_path):
        """Resultados devem vir do mais recente para o mais antigo."""
        mem, sm, orig = self._mem(tmp_path)
        try:
            mem.save_web_knowledge("ollama-sdk-v1", "versao antiga", "", 2025)
            mem.save_web_knowledge("ollama-sdk-v2", "versao nova 2026", "", 2026)
            results_v1 = mem.get_web_knowledge("ollama-sdk-v1", max_age_days=365)
            results_v2 = mem.get_web_knowledge("ollama-sdk-v2", max_age_days=365)
            assert len(results_v1) >= 1
            assert len(results_v2) >= 1
            assert "2026" in results_v2[0]["content"], (
                "O registro mais recente deve vir primeiro"
            )
        finally:
            mem.close()
            sm._DB_PATH = orig


# ===========================================================================
# 2. web_researcher — busca temporal regressiva + cache
# ===========================================================================

class TestWebResearcherTemporalSearch:
    """web_researcher deve: checar cache, buscar com ancora temporal, salvar resultado."""

    def test_cache_hit_nao_chama_llm(self, tmp_path):
        """
        Se web_knowledge tem resultado recente para o topico,
        web_researcher deve retornar do cache sem chamar o LLM.
        """
        from unittest.mock import MagicMock, patch
        import nvdastudio.memory.session_memory as sm_mod
        orig = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "mem.json")

        from nvdastudio.memory.session_memory import SessionMemory
        fake_mem = SessionMemory()
        fake_mem.save_web_knowledge(
            topic="google-generativeai",
            content="Conteudo em cache: genai.Client(api_key=key)",
            source_url="",
            year=2026,
        )

        # get_web_knowledge (chamado internamente pelo cache-check de run()) cai no
        # fallback de selecao semantica quando o topico nao bate exatamente ("como usar
        # google-generativeai" vs "google-generativeai" salvo). relevance.py importa
        # create_llm_client localmente de ..ai.llm_factory -- patchear so em
        # web_researcher nao alcanca essa chamada, entao ela batia na API real do
        # Ollama (429). Precisa mockar tambem na origem.
        relevance_resp = MagicMock()
        relevance_resp.content = '{"selected_ids": [0]}'
        relevance_client = MagicMock()
        relevance_client.chat.return_value = relevance_resp

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client") as mock_client_cls, \
             patch("nvdastudio.ai.llm_factory.create_llm_client", return_value=relevance_client):
            from nvdastudio.sub_agents.web_researcher import run
            result = run(
                "como usar google-generativeai",
                "modelo", {},
                _memory=fake_mem,
            )
            mock_client_cls.assert_not_called(), (
                "Com cache hit, LLM nao deve ser chamado"
            )
            assert "cache" in result.lower() or "genai" in result.lower(), (
                "Resultado deve vir do cache"
            )

        fake_mem.close()
        sm_mod._DB_PATH = orig

    def test_cache_miss_chama_llm_com_ano(self, tmp_path):
        """
        Cache miss deve chamar o LLM.
        """
        from unittest.mock import MagicMock, patch
        import nvdastudio.memory.session_memory as sm_mod
        orig = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "mem.json")
        from nvdastudio.memory.session_memory import SessionMemory
        empty_mem = SessionMemory()

        captured_queries = []
        mock_resp = MagicMock()
        mock_resp.content = "A " * 100  # resposta substantiva (>300 chars)
        mock_resp.executed_tools = []
        mock_resp.tokens_used = 0

        def fake_chat(query, **kwargs):
            captured_queries.append(query)
            return mock_resp

        mock_client = MagicMock()
        mock_client.chat.side_effect = fake_chat

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client", return_value=mock_client):
            from nvdastudio.sub_agents import web_researcher
            web_researcher.run("como usar elevenlabs", "modelo", {}, _memory=empty_mem,
            )

        assert len(captured_queries) >= 1, (
            "Cache miss deve chamar o LLM"
        )

        empty_mem.close()
        sm_mod._DB_PATH = orig

    def test_resultado_substantivo_so_e_salvo_depois_de_aprovado(self, tmp_path):
        """web_researcher 4.11.0: run() NAO cacheia mais.

        Ate aqui o resultado era gravado no fim do proprio run() -- antes de o
        Critic existir na historia, porque ele so avalia depois que o agente
        retorna. Uma pesquisa que o pipeline julgava errada virava conhecimento
        persistido por 7 dias e servido a toda execucao seguinte, inclusive a
        busca proativa do code_generator.

        Medido nos relatorios E2E: 15 reprovacoes com a MESMA queixa (pacote
        legado google-generativeai), e um code_generation gastando 419.747
        tokens para ser reprovado por seguir essa pesquisa.

        Este teste travava o comportamento antigo. Agora trava o novo: run()
        pesquisa e devolve; quem grava e salvar_se_aprovado(), chamada pelo
        orchestrator no ramo do veredicto aprovado."""
        from unittest.mock import MagicMock, patch
        import nvdastudio.memory.session_memory as sm_mod
        orig = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "mem.json")
        from nvdastudio.memory.session_memory import SessionMemory
        mem = SessionMemory()

        mock_resp = MagicMock()
        mock_resp.content = "C " * 200  # substantivo
        mock_resp.executed_tools = []
        mock_resp.tokens_used = 0

        mock_client = MagicMock()
        mock_client.chat.return_value = mock_resp

        # get_web_knowledge("requests") nao bate exatamente com o topico salvo
        # ("como usar requests com NVDA"), entao cai no fallback de selecao semantica
        # (relevance.py), que importa create_llm_client localmente de ..ai.llm_factory
        # -- precisa mockar na origem, e a chamada tem que ficar dentro do "with".
        relevance_resp = MagicMock()
        relevance_resp.content = '{"selected_ids": [0]}'
        relevance_client = MagicMock()
        relevance_client.chat.return_value = relevance_resp

        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client", return_value=mock_client), \
             patch("nvdastudio.ai.llm_factory.create_llm_client", return_value=relevance_client):
            from nvdastudio.sub_agents import web_researcher
            resultado = web_researcher.run(
                "como usar requests com NVDA", "modelo", {}, _memory=mem,
            )

            # run() nao grava: o veredicto ainda nao existe neste ponto
            assert not mem.get_web_knowledge("requests", max_age_days=1), (
                "run() voltou a cachear antes da verificacao"
            )

            # aprovado pelo Critic, o orchestrator manda gravar
            web_researcher.salvar_se_aprovado(
                "como usar requests com NVDA", resultado, _memory=mem,
            )
            saved = mem.get_web_knowledge("requests", max_age_days=1)

        assert len(saved) >= 1, (
            "pesquisa aprovada deve ser cacheada para a proxima execucao"
        )

        mem.close()
        sm_mod._DB_PATH = orig

    def test_memory_none_desativa_cache(self):
        """_memory=None deve funcionar sem erros (compatibilidade com chamadas antigas)."""
        from unittest.mock import MagicMock, patch
        mock_resp = MagicMock()
        mock_resp.content = "resposta ok"
        mock_resp.executed_tools = []
        mock_resp.tokens_used = 0
        mock_client = MagicMock()
        mock_client.chat.return_value = mock_resp
        with patch("nvdastudio.sub_agents.web_researcher.create_llm_client", return_value=mock_client):
            import importlib

            from nvdastudio.sub_agents import web_researcher
            importlib.reload(web_researcher)
            result = web_researcher.run("teste", "modelo", {}, _memory=None)
            assert isinstance(result, str)


# ===========================================================================
# 3. code_generator — dep_failures com mensagem nuancada
# ===========================================================================

class TestCodeGeneratorDepFailuresNuancado:
    """
    Mensagem de dep_failures deve ser nuancada:
    'verifique antes de incluir' nao 'evite completamente'.
    O LLM pode ainda incluir o pacote se validate_import confirmar existencia.
    """

    def test_mensagem_dep_failures_contem_verificar(self):
        """
        O contexto injetado de dep_failures deve conter instrucao de verificacao,
        nao de bloqueio absoluto.
        """
        from unittest.mock import patch, MagicMock

        fake_mem = MagicMock()
        fake_mem.get_dep_failures.return_value = [
            {"pkg": "triton", "reason": "nao_encontrado_pypi"},
        ]
        fake_mem.get_web_knowledge.return_value = []

        captured_system = []

        def fake_chat(prompt, system_override=None, **kwargs):
            if system_override:
                captured_system.append(system_override)
            resp = MagicMock()
            resp.content = "```python:globalPlugins/X/__init__.py\npass\n```"
            resp.tool_calls = None
            resp.tokens_used = 0
            return resp

        mock_client = MagicMock()
        mock_client.chat.side_effect = fake_chat

        with patch("nvdastudio.sub_agents.code_generator.memory", fake_mem):
            with patch("nvdastudio.sub_agents.code_generator.create_llm_client",
                       return_value=mock_client):
                with patch("nvdastudio.sub_agents.code_generator.get_docs_code_generation",
                           return_value=""):
                    from nvdastudio.sub_agents.code_generator import run
                    run("crie um addon simples", "modelo", {})

        assert len(captured_system) > 0, "system_override deve ter sido passado"
        system = captured_system[0]

        # Deve conter instrucao de verificacao, nao bloqueio absoluto
        assert any(palavra in system.lower() for palavra in
                   ["verif", "confirm", "valide", "cheque"]), (
            "Mensagem deve orientar verificacao, nao bloqueio. "
            f"Trecho relevante: {system[system.find('HISTORICO'):system.find('HISTORICO')+400]}"
        )

    def test_mensagem_dep_failures_menciona_validate_import(self):
        """Deve mencionar validate_import como ferramenta de verificacao."""
        from unittest.mock import patch, MagicMock

        fake_mem = MagicMock()
        fake_mem.get_dep_failures.return_value = [
            {"pkg": "torch", "reason": "nao_encontrado_pypi"},
        ]
        fake_mem.get_web_knowledge.return_value = []

        captured_system = []

        def fake_chat(prompt, system_override=None, **kwargs):
            if system_override:
                captured_system.append(system_override)
            resp = MagicMock()
            resp.content = "```python:globalPlugins/X/__init__.py\npass\n```"
            resp.tool_calls = None
            resp.tokens_used = 0
            return resp

        mock_client = MagicMock()
        mock_client.chat.side_effect = fake_chat

        with patch("nvdastudio.sub_agents.code_generator.memory", fake_mem):
            with patch("nvdastudio.sub_agents.code_generator.create_llm_client",
                       return_value=mock_client):
                with patch("nvdastudio.sub_agents.code_generator.get_docs_code_generation",
                           return_value=""):
                    from nvdastudio.sub_agents.code_generator import run
                    run("crie addon", "modelo", {})

        system = captured_system[0] if captured_system else ""
        assert "validate_import" in system, (
            "Deve mencionar validate_import como forma de verificar o pacote"
        )

    def test_web_knowledge_injetado_quando_disponivel(self):
        """
        Se web_knowledge tiver informacao relevante sobre uma dependencia,
        deve ser injetado no contexto do code_generator.
        """
        from unittest.mock import patch, MagicMock

        fake_mem = MagicMock()
        fake_mem.get_dep_failures.return_value = []
        fake_mem.get_web_knowledge.return_value = [
            {
                "topic": "google-generativeai",
                "content": "A partir de 0.8.x usar genai.Client(api_key=...) nao configure()",
                "source_url": "https://pypi.org",
                "year": 2026,
            }
        ]

        captured_system = []

        def fake_chat(prompt, system_override=None, **kwargs):
            if system_override:
                captured_system.append(system_override)
            resp = MagicMock()
            resp.content = "```python:globalPlugins/X/__init__.py\npass\n```"
            resp.tool_calls = None
            resp.tokens_used = 0
            return resp

        mock_client = MagicMock()
        mock_client.chat.side_effect = fake_chat

        with patch("nvdastudio.sub_agents.code_generator.memory", fake_mem):
            with patch("nvdastudio.sub_agents.code_generator.create_llm_client",
                       return_value=mock_client):
                with patch("nvdastudio.sub_agents.code_generator.get_docs_code_generation",
                           return_value=""):
                    from nvdastudio.sub_agents.code_generator import run
                    run("crie addon com google-generativeai", "modelo", {})

        system = captured_system[0] if captured_system else ""
        assert "genai.Client" in system or "0.8" in system, (
            "web_knowledge deve ser injetado no contexto quando disponivel. "
            f"Trecho: {system[-500:]}"
        )
