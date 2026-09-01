import pytest


# ------------------------------------------------------------------
# V1 — Revisao de design em 3 estagios
#
# Nome antigo desta secao era "Understanding Lock + DISPOSICAO_FINAL",
# descrevendo estagios que a v2.0.0 aposentou. Atualizado em 2026-08-29
# junto com a remocao do codigo morto correspondente.
# ------------------------------------------------------------------

class TestRevisaoDeDesign:
    """skill: multi-agent-brainstorming — Challenger, Constraint Guardian e
    User Advocate, os 3 estagios que run() executa de verdade."""

    def test_versao_design_review_e_2_5_0(self):
        from nvdastudio.sub_agents.design_review_agent import MODULE_VERSION
        assert MODULE_VERSION == "2.14.0"

    # 2026-08-29: removidos os testes de _UNDERSTANDING_LOCK_SYSTEM,
    # _REASONING_LOCK, _DECISION_LOG_SYSTEM e {understanding_lock}. O
    # estagio 0 (Understanding Lock) e o Decision Log foram aposentados
    # na v2.0.0, quando a revisao caiu de 6 para 3 estagios; os simbolos
    # sobreviveram so como codigo morto ate 2026-08-29. Um teste que
    # passa contra codigo que nao roda da falsa sensacao de cobertura.
    def test_revisao_tem_os_tres_estagios_reais(self):
        from nvdastudio.sub_agents.design_review_agent import (
            _ADVOCATE_SYSTEM, _CHALLENGER_SYSTEM, _GUARDIAN_SYSTEM,
        )
        for prompt in (_CHALLENGER_SYSTEM, _GUARDIAN_SYSTEM, _ADVOCATE_SYSTEM):
            assert isinstance(prompt, str) and len(prompt) > 50

    def test_understanding_lock_nao_fixa_modelo(self):
        from nvdastudio.sub_agents import design_review_agent
        assert not hasattr(design_review_agent, "MODEL_LOCK")

    def test_run_faz_tres_chamadas_llm(self, fake_api_key="gsk_test_fake"):
        """run() deve fazer exatamente 3 chamadas: Challenger, Guardian, Advocate."""
        from unittest.mock import patch
        call_count = {"n": 0}

        def fake_run(*args, **kwargs):
            call_count["n"] += 1
            from nvdastudio.sub_agents._base import _tl
            _tl.last_tokens = 10
            return "output"

        with patch("nvdastudio.sub_agents.design_review_agent._run_sub_agent",
                   side_effect=fake_run):
            from nvdastudio.sub_agents.design_review_agent import run
            run("pedido", "kimi-k2.6", {})

        assert call_count["n"] == 3, (
            f"design_review deve fazer 3 chamadas LLM (Challenger+Guardian+Advocate), fez {call_count['n']}"
        )

    def test_run_output_contem_challenger_e_guardian(self, fake_api_key="gsk_test_fake"):
        """Output de run() deve conter secoes Challenger e Guardian."""
        from unittest.mock import patch
        from nvdastudio.sub_agents.design_review_agent import run

        def fake_run(*args, **kwargs):
            from nvdastudio.sub_agents._base import _tl
            _tl.last_tokens = 10
            return "analise_fake"

        with patch("nvdastudio.sub_agents.design_review_agent._run_sub_agent",
                   side_effect=fake_run):
            result = run("criar addon X", "kimi-k2.6", {})

        assert "Challenger" in result
        assert "Constraint Guardian" in result


# ------------------------------------------------------------------
# V2 — Pruning automatico de step_metrics e sessions
# ------------------------------------------------------------------

class TestSessionMemoryPruning:
    """skill: memory-systems + agent-memory-systems — anti-padrao Store Everything Forever."""

    def test_versao_session_memory_e_2_7_0(self):
        from nvdastudio.memory.session_memory import MODULE_VERSION
        assert MODULE_VERSION == "3.6.0"

    def test_constantes_de_pruning_existem(self):
        from nvdastudio.memory import session_memory
        assert hasattr(session_memory, "_MAX_STEP_METRICS")
        assert hasattr(session_memory, "_MAX_SESSIONS")
        assert hasattr(session_memory, "_PRUNE_INTERVAL")
        assert session_memory._MAX_STEP_METRICS > 0
        assert session_memory._MAX_SESSIONS > 0
        assert session_memory._PRUNE_INTERVAL > 0

    def test_limites_sao_razoaveis(self):
        from nvdastudio.memory import session_memory
        # Nao pode ser tao pequeno que poda cedo demais
        assert session_memory._MAX_STEP_METRICS >= 100
        assert session_memory._MAX_SESSIONS >= 100
        # Nao pode ser tao grande que nao haja limite real
        assert session_memory._MAX_STEP_METRICS <= 10000
        assert session_memory._MAX_SESSIONS <= 5000

    def test_prune_if_needed_existe(self):
        from nvdastudio.memory.session_memory import SessionMemory
        assert hasattr(SessionMemory, "_prune_if_needed")

    def test_prune_old_metrics_api_publica(self):
        from nvdastudio.memory.session_memory import SessionMemory
        assert hasattr(SessionMemory, "prune_old_metrics")
        assert callable(SessionMemory.prune_old_metrics)

    def test_prune_old_sessions_api_publica(self):
        from nvdastudio.memory.session_memory import SessionMemory
        assert hasattr(SessionMemory, "prune_old_sessions")
        assert callable(SessionMemory.prune_old_sessions)

    def test_prune_remove_registros_antigos(self, tmp_path):
        """_prune_if_needed deve remover registros antigos quando max excedido."""
        from nvdastudio.memory.session_memory import SessionMemory

        mem = SessionMemory()
        mem._db_path_override = str(tmp_path / "test_memory.json")

        # Substitui o _DB_PATH para usar diretorio temporario
        import nvdastudio.memory.session_memory as sm_mod
        orig_path = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "test_memory.json")

        try:
            mem._init_db()
            if not mem._ready or mem._db is None:
                pytest.skip("TinyDB nao disponivel")

            # Insere 10 registros
            for i in range(10):
                mem._db.table("step_metrics").insert({
                    "step_type": "code_generation",
                    "success": 1,
                    "retries": 0,
                    "tokens": i * 100,
                    "latency_ms": i * 10,
                    "complexity_level": "simple",
                    "created_at": f"2026-04-0{i%9+1}T10:00:0{i}",
                })

            before = len(mem._db.table("step_metrics").all())
            assert before == 10

            # Prune para max=5
            mem._prune_if_needed("step_metrics", 5)
            after = len(mem._db.table("step_metrics").all())

            assert after == 5, f"Esperava 5 registros apos prune, tem {after}"
        finally:
            mem.close()
            sm_mod._DB_PATH = orig_path

    def test_prune_nao_remove_quando_abaixo_limite(self, tmp_path):
        """_prune_if_needed nao deve remover nada quando abaixo do limite."""
        from nvdastudio.memory.session_memory import SessionMemory
        import nvdastudio.memory.session_memory as sm_mod

        orig_path = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "test_memory2.json")

        mem = SessionMemory()
        try:
            mem._init_db()
            if not mem._ready or mem._db is None:
                pytest.skip("TinyDB nao disponivel")

            for i in range(3):
                mem._db.table("step_metrics").insert({
                    "step_type": "manifest_builder",
                    "success": 1,
                    "retries": 0,
                    "tokens": 50,
                    "latency_ms": 100,
                    "complexity_level": "simple",
                    "created_at": f"2026-04-01T10:00:0{i}",
                })

            mem._prune_if_needed("step_metrics", 100)
            after = len(mem._db.table("step_metrics").all())
            assert after == 3, "Nao deveria remover nada — abaixo do limite"
        finally:
            mem.close()
            sm_mod._DB_PATH = orig_path

    def test_prune_old_metrics_retorna_contagem(self, tmp_path):
        """prune_old_metrics() deve retornar numero de registros removidos."""
        from nvdastudio.memory.session_memory import SessionMemory, _MAX_STEP_METRICS
        import nvdastudio.memory.session_memory as sm_mod

        orig_path = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "test_memory3.json")

        mem = SessionMemory()
        try:
            mem._init_db()
            if not mem._ready or mem._db is None:
                pytest.skip("TinyDB nao disponivel")

            # Insere _MAX_STEP_METRICS + 50 registros
            total = _MAX_STEP_METRICS + 50
            for _ in range(total):
                mem._db.table("step_metrics").insert({
                    "step_type": "code_generation",
                    "success": 1, "retries": 0, "tokens": 100,
                    "latency_ms": 50, "complexity_level": "simple",
                    "created_at": "2026-04-01T10:00:00",
                })

            removed = mem.prune_old_metrics()
            assert removed == 50, f"Esperava remover 50, removeu {removed}"
            remaining = len(mem._db.table("step_metrics").all())
            assert remaining == _MAX_STEP_METRICS
        finally:
            mem.close()
            sm_mod._DB_PATH = orig_path


# ------------------------------------------------------------------
# V3 — NVDA-022 (type hints) + NVDA-023 (gui.message.MessageDialog)
# ------------------------------------------------------------------

class TestCodeGeneratorNovosRegras:
    """skill: nvda-addon-dev — NVDA-022 type hints + NVDA-023 MessageDialog."""

    def test_versao_code_generator_e_2_3_0(self):
        from nvdastudio.sub_agents.code_generator import MODULE_VERSION
        assert MODULE_VERSION == "3.34.0"

    def test_nvda_022_presente_no_system_prompt(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        assert "NVDA-022" in _SYSTEM
        assert "type hint" in _SYSTEM.lower() or "Type hint" in _SYSTEM

    def test_nvda_022_proibe_optional(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        # Deve instruir a usar | em vez de Optional[]
        assert "Optional[" in _SYSTEM  # aparece no bloco PROIBIDO
        # E a alternativa correta
        assert "| None" in _SYSTEM or "str | None" in _SYSTEM

    def test_nvda_023_presente_no_system_prompt(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        assert "NVDA-049" in _SYSTEM
        assert "MessageDialog" in _SYSTEM
        assert "gui.message" in _SYSTEM

    def test_nvda_023_proibe_wx_messagedialog(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        # Deve marcar wx.MessageDialog como proibido
        assert "wx.MessageDialog" in _SYSTEM

    def test_verificacao_final_tem_item_8_type_hints(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        assert "8." in _SYSTEM
        assert "type hint" in _SYSTEM.lower()

    def test_verificacao_final_tem_item_9_messagedialog(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        assert "9." in _SYSTEM
        assert "MessageDialog" in _SYSTEM

    def test_verificacao_final_tem_9_itens(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        # Verifica que os itens 1-9 existem no checklist
        for i in range(1, 10):
            assert f"{i}." in _SYSTEM, f"Item {i} nao encontrado na VERIFICACAO FINAL"
