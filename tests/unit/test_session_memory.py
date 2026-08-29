import os
import threading

import pytest


import nvdastudio.memory.session_memory as sm_mod
from nvdastudio.memory.session_memory import SessionMemory, SessionRecord


# --------------------------------------------------------------------------
# Fixture: banco SQLite em diretorio temporario (isolado do banco de producao)
# --------------------------------------------------------------------------

@pytest.fixture
def mem(tmp_path):
    """
    SessionMemory com banco temporario isolado.
    Sobrescreve _DB_PATH durante o teste e restaura no teardown.
    """
    db_path = str(tmp_path / "test_memory.json")
    original_dir = sm_mod._DB_DIR
    original_path = sm_mod._DB_PATH

    sm_mod._DB_DIR = str(tmp_path)
    sm_mod._DB_PATH = db_path

    instance = SessionMemory()

    yield instance

    instance.close()
    sm_mod._DB_DIR = original_dir
    sm_mod._DB_PATH = original_path


# --------------------------------------------------------------------------
# Helpers de fixture
# --------------------------------------------------------------------------

def _save(mem, query="query", addon="addon", plan="p1",
          ok=2, total=3, retries=0, success=True, summary="ok"):
    return mem.save_session(query, addon, plan, ok, total, retries, success, summary)


# --------------------------------------------------------------------------
# Testes: instancia global e inicializacao lazy
# --------------------------------------------------------------------------

class TestSessionMemoryInit:

    def test_instancia_global_existe(self):
        from nvdastudio.memory.session_memory import memory
        assert isinstance(memory, SessionMemory)

    def test_inicializacao_lazy(self):
        """Banco nao e criado ate primeiro uso."""
        instance = SessionMemory()
        assert instance._ready is False


# --------------------------------------------------------------------------
# Testes: save_session e get_recent
# --------------------------------------------------------------------------

class TestSessionMemorySave:

    def test_save_retorna_id_inteiro(self, mem):
        sid = _save(mem)
        assert isinstance(sid, int)
        assert sid > 0

    def test_save_e_get_recent_roundtrip(self, mem):
        _save(mem, query="crie addon de hora", addon="horaAddon", plan="p42",
              ok=4, total=5, retries=1, success=True, summary="4/5 ok")
        records = mem.get_recent(10)
        assert len(records) == 1
        r = records[0]
        assert r.query == "crie addon de hora"
        assert r.addon_name == "horaAddon"
        assert r.plan_id == "p42"
        assert r.steps_ok == 4
        assert r.steps_total == 5
        assert r.retries == 1
        assert r.success is True

    def test_save_multiplas_sessoes(self, mem):
        for i in range(5):
            _save(mem, query=f"query {i}")
        records = mem.get_recent(10)
        assert len(records) == 5

    def test_get_recent_limite_respeitado(self, mem):
        for i in range(10):
            _save(mem, query=f"q{i}")
        records = mem.get_recent(limit=3)
        assert len(records) == 3

    def test_get_recent_ordem_decrescente_por_id(self, mem):
        """Mais recente primeiro — util para mostrar historico ao usuario."""
        for i in range(3):
            _save(mem, query=f"q{i}")
        records = mem.get_recent(10)
        ids = [r.id for r in records]
        assert ids == sorted(ids, reverse=True)

    def test_query_truncada_a_500_chars(self, mem):
        """Queries muito longas sao truncadas para nao inflar o banco."""
        longa = "x" * 1000
        _save(mem, query=longa)
        records = mem.get_recent(1)
        assert len(records[0].query) <= 500

    def test_retorna_session_record(self, mem):
        _save(mem)
        records = mem.get_recent(1)
        assert isinstance(records[0], SessionRecord)

    def test_get_recent_vazio_sem_sessoes(self, mem):
        records = mem.get_recent(10)
        assert records == []


# --------------------------------------------------------------------------
# Testes: preferences
# --------------------------------------------------------------------------

class TestSessionMemoryPreferences:

    def test_set_e_get_preference(self, mem):
        mem.set_preference("addon_name", "meuAddon")
        assert mem.get_preference("addon_name") == "meuAddon"

    def test_get_preference_default_quando_ausente(self, mem):
        val = mem.get_preference("chave_inexistente", "valor_padrao")
        assert val == "valor_padrao"

    def test_get_preference_default_vazio(self, mem):
        val = mem.get_preference("nao_existe")
        assert val == ""

    def test_set_preference_sobrescreve_existente(self, mem):
        mem.set_preference("chave", "v1")
        mem.set_preference("chave", "v2")
        assert mem.get_preference("chave") == "v2"

    def test_multiplas_preferencias_independentes(self, mem):
        mem.set_preference("k1", "v1")
        mem.set_preference("k2", "v2")
        assert mem.get_preference("k1") == "v1"
        assert mem.get_preference("k2") == "v2"

    def test_set_retorna_true_em_sucesso(self, mem):
        ok = mem.set_preference("chave", "valor")
        assert ok is True


# --------------------------------------------------------------------------
# Testes: get_session_count
# --------------------------------------------------------------------------

class TestSessionMemoryCount:

    def test_count_zero_inicial(self, mem):
        assert mem.get_session_count() == 0

    def test_count_incrementa_a_cada_save(self, mem):
        for _ in range(3):
            _save(mem)
        assert mem.get_session_count() == 3

    def test_count_retorna_inteiro(self, mem):
        assert isinstance(mem.get_session_count(), int)


# --------------------------------------------------------------------------
# Testes: Regra 9 — memoria nunca executa codigo armazenado
# --------------------------------------------------------------------------

class TestSessionMemoryNuncaExecuta:
    """
    Invariante critico: codigo armazenado na memoria nunca e executado.
    Regra 9: Output do sistema nunca e executado automaticamente.
    """

    def test_save_codigo_malicioso_nao_executa(self, mem):
        """Codigo Python armazenado como query deve ser tratado como string."""
        codigo = "import os; os.system('echo EXECUTADO')"
        sid = _save(mem, query=codigo, summary=codigo)
        assert sid is not None
        records = mem.get_recent(1)
        # Armazenado como string, nao executado
        assert isinstance(records[0].query, str)
        assert records[0].query == codigo[:500]

    def test_eval_no_summary_nao_executa(self, mem):
        _save(mem, summary="eval('1+1')")
        records = mem.get_recent(1)
        assert isinstance(records[0].summary, str)

    def test_get_recent_retorna_strings_nao_objetos_executaveis(self, mem):
        _save(mem, query="exec('pass')")
        records = mem.get_recent(1)
        r = records[0]
        # Todos os campos de texto devem ser str
        assert isinstance(r.query, str)
        assert isinstance(r.addon_name, str)
        assert isinstance(r.summary, str)


# --------------------------------------------------------------------------
# Testes: thread safety basico
# --------------------------------------------------------------------------

class TestSessionMemoryThreadSafety:

    def test_save_concorrente_nao_corrompe_banco(self, mem):
        """Writes concorrentes nao devem corromper o banco (lock interno)."""
        errors = []

        def save_n(n):
            try:
                for i in range(5):
                    _save(mem, query=f"thread {n} item {i}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=save_n, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Erros em writes concorrentes: {errors}"
        count = mem.get_session_count()
        assert count == 20  # 4 threads * 5 saves


# --------------------------------------------------------------------------
# Testes: prompt_version — v1.1.0
# --------------------------------------------------------------------------

class TestSessionMemoryPromptVersion:
    """
    v1.1.0: prompt_version permite A/B de versoes de prompt.
    Baseado em c:\\skills\\llm-app-patterns\\SKILL.md (prompt versioning).
    """

    def test_save_com_prompt_version(self, mem):
        sid = mem.save_session(
            "query", "addon", "p1", 3, 4, 0, True, "ok",
            prompt_version="2.0.0"
        )
        assert sid is not None
        records = mem.get_recent(1)
        assert records[0].prompt_version == "2.0.0"

    def test_save_sem_prompt_version_usa_vazio(self, mem):
        mem.save_session("query", "addon", "p1", 3, 4, 0, True, "ok")
        records = mem.get_recent(1)
        assert records[0].prompt_version == ""

    def test_prompt_version_truncada_a_20_chars(self, mem):
        """Versoes muito longas sao truncadas para nao inflar o banco."""
        mem.save_session(
            "q", "a", "p", 1, 1, 0, True, "ok",
            prompt_version="versao-muito-longa-demais-xyz"
        )
        records = mem.get_recent(1)
        assert len(records[0].prompt_version) <= 20

    def test_session_record_tem_campo_prompt_version(self, mem):
        _save(mem)
        records = mem.get_recent(1)
        assert hasattr(records[0], "prompt_version")

    def test_multiplas_versoes_salvas(self, mem):
        for ver in ["1.0.0", "2.0.0", "2.0.0"]:
            mem.save_session("q", "a", "p", 2, 3, 0, True, "ok", prompt_version=ver)
        records = mem.get_recent(10)
        versoes = [r.prompt_version for r in records]
        assert "1.0.0" in versoes
        assert versoes.count("2.0.0") == 2


class TestSessionMemoryStatsPromptVersion:
    """
    v1.1.0: get_stats_by_prompt_version() — comparacao de eficacia.
    Regra 9: apenas leitura de texto armazenado, nunca executa.
    """

    def test_stats_vazio_sem_sessoes(self, mem):
        stats = mem.get_stats_by_prompt_version()
        assert stats == []

    def test_stats_agrupa_por_versao(self, mem):
        mem.save_session("q", "a", "p1", 3, 4, 0, True, "ok", prompt_version="1.0.0")
        mem.save_session("q", "a", "p2", 4, 4, 0, True, "ok", prompt_version="2.0.0")
        mem.save_session("q", "a", "p3", 2, 4, 1, False, "fail", prompt_version="2.0.0")
        stats = mem.get_stats_by_prompt_version()
        assert len(stats) == 2

    def test_stats_calcula_success_rate(self, mem):
        mem.save_session("q", "a", "p1", 4, 4, 0, True, "ok", prompt_version="v1")
        mem.save_session("q", "a", "p2", 1, 4, 2, False, "fail", prompt_version="v1")
        stats = mem.get_stats_by_prompt_version()
        v1 = next(s for s in stats if s["prompt_version"] == "v1")
        assert v1["sessions"] == 2
        assert v1["success_rate"] == 0.5

    def test_stats_retorna_dicts_com_campos_esperados(self, mem):
        mem.save_session("q", "a", "p", 2, 3, 0, True, "ok", prompt_version="v1")
        stats = mem.get_stats_by_prompt_version()
        assert len(stats) == 1
        s = stats[0]
        assert "prompt_version" in s
        assert "sessions" in s
        assert "steps_ok" in s
        assert "steps_total" in s
        assert "success_rate" in s

    def test_stats_nunca_executa_conteudo(self, mem):
        """Regra 9: stats apenas agrega numeros, nunca executa texto armazenado."""
        mem.save_session(
            "import os; os.system('echo hack')", "a", "p",
            1, 1, 0, True, "eval('1+1')", prompt_version="v1"
        )
        stats = mem.get_stats_by_prompt_version()
        assert isinstance(stats, list)
        assert stats[0]["sessions"] == 1

    def test_stats_success_rate_100_percent(self, mem):
        for _ in range(3):
            mem.save_session("q", "a", "p", 4, 4, 0, True, "ok", prompt_version="perfeito")
        stats = mem.get_stats_by_prompt_version()
        s = next(st for st in stats if st["prompt_version"] == "perfeito")
        assert s["success_rate"] == 1.0

    def test_stats_success_rate_zero_percent(self, mem):
        for _ in range(2):
            mem.save_session("q", "a", "p", 0, 4, 3, False, "fail", prompt_version="ruim")
        stats = mem.get_stats_by_prompt_version()
        s = next(st for st in stats if st["prompt_version"] == "ruim")
        assert s["success_rate"] == 0.0


class TestSessionMemoryStepIssues:
    """Testa campo step_issues e get_recent_failures (feedback loop)."""

    def test_save_com_step_issues(self):
        from nvdastudio.memory.session_memory import SessionMemory
        mem = SessionMemory()
        try:
            doc_id = mem.save_session(
                query="teste", addon_name="Addon", plan_id="p1",
                steps_ok=1, steps_total=2, retries=1, success=False,
                summary="falhou", step_issues=["Faltou nextHandler()", "sem terminate()"]
            )
            assert doc_id is not None
        finally:
            mem.close()

    def test_get_recent_failures_retorna_lista(self):
        from nvdastudio.memory.session_memory import SessionMemory
        mem = SessionMemory()
        try:
            result = mem.get_recent_failures()
            assert isinstance(result, list)
        finally:
            mem.close()

    def test_get_recent_failures_retorna_apenas_falhas_com_issues(self):
        from nvdastudio.memory.session_memory import SessionMemory
        mem = SessionMemory()
        try:
            # Salva falha com issue
            mem.save_session(
                query="falhou", addon_name="A", plan_id="p1",
                steps_ok=0, steps_total=1, retries=2, success=False,
                summary="err", step_issues=["erro real aqui"]
            )
            # Salva sucesso — nao deve aparecer em failures
            mem.save_session(
                query="ok", addon_name="B", plan_id="p2",
                steps_ok=1, steps_total=1, retries=0, success=True,
                summary="ok"
            )
            failures = mem.get_recent_failures(limit=5)
            for f in failures:
                assert isinstance(f, str)
                assert len(f) > 0
        finally:
            mem.close()

    def test_get_recent_failures_limite_respeitado(self):
        from nvdastudio.memory.session_memory import SessionMemory
        mem = SessionMemory()
        try:
            for i in range(5):
                mem.save_session(
                    query=f"q{i}", addon_name="A", plan_id=f"p{i}",
                    steps_ok=0, steps_total=1, retries=1, success=False,
                    summary="fail", step_issues=[f"issue {i}"]
                )
            result = mem.get_recent_failures(limit=2)
            assert len(result) <= 2
        finally:
            mem.close()

    def test_get_recent_failures_nao_executa_conteudo(self):
        """Regra 9: get_recent_failures nunca executa o conteudo armazenado."""
        from nvdastudio.memory.session_memory import SessionMemory
        marker = os.path.join(os.path.expanduser("~"), "_nvdastudio_fail_exec.txt")
        mem = SessionMemory()
        try:
            mem.save_session(
                query="q", addon_name="A", plan_id="p",
                steps_ok=0, steps_total=1, retries=1, success=False,
                summary="fail",
                step_issues=[f"open(r'{marker}','w').write('EXEC')"]
            )
            mem.get_recent_failures()
            assert not os.path.exists(marker)
        finally:
            mem.close()


# --------------------------------------------------------------------------
# Testes: log_step_metric + get_step_success_rates — v2.4.0
# skill: agent-orchestration-improve-agent (Performance Analysis)
# --------------------------------------------------------------------------

class TestStepMetrics:
    """
    Skill: agent-orchestration-improve-agent (Phase 1: Performance Analysis).
    Testa tabela step_metrics — permite identificar quais sub-agentes falham mais.
    Regra 9: apenas armazena metricas numericas, nunca executa conteudo.
    """

    def test_log_step_metric_nao_levanta(self, mem):
        """log_step_metric nunca levanta excecao — falha e silenciosa."""
        mem.log_step_metric("code_generation", success=True, retries=0, tokens=800)

    def test_log_step_metric_aceita_falha(self, mem):
        mem.log_step_metric("manifest_builder", success=False, retries=2, tokens=500)
        rates = mem.get_step_success_rates()
        assert any(r["step_type"] == "manifest_builder" for r in rates)

    def test_get_step_success_rates_vazio_sem_metricas(self, mem):
        rates = mem.get_step_success_rates()
        assert rates == []

    def test_get_step_success_rates_retorna_lista_de_dicts(self, mem):
        mem.log_step_metric("code_generation", success=True)
        rates = mem.get_step_success_rates()
        assert isinstance(rates, list)
        assert isinstance(rates[0], dict)

    def test_get_step_success_rates_campos_esperados(self, mem):
        mem.log_step_metric("test_generation", success=True, retries=1, tokens=300, latency_ms=1500)
        rates = mem.get_step_success_rates()
        r = rates[0]
        assert "step_type" in r
        assert "total" in r
        assert "success_rate" in r
        assert "first_attempt_rate" in r
        assert "avg_tokens" in r
        assert "avg_latency_ms" in r

    def test_success_rate_calculo_correto(self, mem):
        """3 sucesso + 1 falha = success_rate 0.75."""
        for _ in range(3):
            mem.log_step_metric("code_generation", success=True, retries=0)
        mem.log_step_metric("code_generation", success=False, retries=3)
        rates = mem.get_step_success_rates()
        cg = next(r for r in rates if r["step_type"] == "code_generation")
        assert cg["total"] == 4
        assert cg["success_rate"] == 0.75

    def test_first_attempt_rate_apenas_sem_retries(self, mem):
        """first_attempt_rate conta apenas sucesso com retries=0."""
        mem.log_step_metric("manifest_builder", success=True, retries=0)
        mem.log_step_metric("manifest_builder", success=True, retries=1)
        rates = mem.get_step_success_rates()
        mb = next(r for r in rates if r["step_type"] == "manifest_builder")
        assert mb["first_attempt_rate"] == 0.5  # 1 de 2 na primeira tentativa

    def test_avg_tokens_calculado(self, mem):
        mem.log_step_metric("code_generation", success=True, tokens=1000)
        mem.log_step_metric("code_generation", success=True, tokens=2000)
        rates = mem.get_step_success_rates()
        cg = next(r for r in rates if r["step_type"] == "code_generation")
        assert cg["avg_tokens"] == 1500

    def test_multiplos_step_types_isolados(self, mem):
        mem.log_step_metric("code_generation", success=True)
        mem.log_step_metric("manifest_builder", success=False)
        mem.log_step_metric("test_generation", success=True)
        rates = mem.get_step_success_rates()
        types = {r["step_type"] for r in rates}
        assert "code_generation" in types
        assert "manifest_builder" in types
        assert "test_generation" in types

    def test_ordenados_por_success_rate_ascendente(self, mem):
        """Agentes com mais falhas devem aparecer primeiro (foco de melhoria)."""
        # code_generation: 0% sucesso
        mem.log_step_metric("code_generation", success=False)
        # manifest_builder: 100% sucesso
        mem.log_step_metric("manifest_builder", success=True)
        rates = mem.get_step_success_rates()
        assert rates[0]["step_type"] == "code_generation"
        assert rates[-1]["step_type"] == "manifest_builder"

    def test_last_n_limita_registros_considerados(self, mem):
        """last_n=2 considera apenas os 2 registros mais recentes."""
        # Salva 3 sucessos antigos
        for _ in range(3):
            mem.log_step_metric("code_generation", success=True)
        # Salva 2 falhas recentes
        for _ in range(2):
            mem.log_step_metric("code_generation", success=False)
        rates = mem.get_step_success_rates(last_n=2)
        cg = next(r for r in rates if r["step_type"] == "code_generation")
        # Com last_n=2 so ve as 2 falhas recentes
        assert cg["success_rate"] == 0.0
        assert cg["total"] == 2

    def test_regra9_log_step_metric_nao_executa(self, mem):
        """Regra 9: metricas sao dados numericos — step_type truncado, nunca exec."""
        marker = os.path.join(os.path.expanduser("~"), "_nvda_metrics_exec.txt")
        # step_type potencialmente malicioso deve ser truncado, nunca executado
        mem.log_step_metric(
            f"eval(open('{marker}','w').write('x'))",
            success=True
        )
        assert not os.path.exists(marker)

    def test_log_step_metric_registra_latency_ms(self, mem):
        """latency_ms e gravado e refletido em avg_latency_ms."""
        mem.log_step_metric("code_generation", success=True, tokens=500, latency_ms=1200)
        mem.log_step_metric("code_generation", success=True, tokens=500, latency_ms=800)
        rates = mem.get_step_success_rates()
        cg = next(r for r in rates if r["step_type"] == "code_generation")
        assert cg["avg_latency_ms"] == 1000

    def test_log_step_metric_latency_ms_zero_padrao(self, mem):
        """latency_ms omitido deve resultar em avg_latency_ms=0."""
        mem.log_step_metric("manifest_builder", success=True)
        rates = mem.get_step_success_rates()
        mb = next(r for r in rates if r["step_type"] == "manifest_builder")
        assert mb["avg_latency_ms"] == 0


class TestTrajectoryBreakdown:
    """
    3.3.0: trajectory (log_step_metric) + get_trajectory_breakdown() --
    fecha o gap de "Trajectory Evals": nao so O RESULTADO de um step, mas
    COMO ele chegou la (direct/retried/loop_detected/exhausted).
    """

    def test_log_step_metric_aceita_trajectory_sem_levantar(self, mem):
        mem.log_step_metric("code_generation", success=True, trajectory="direct")

    def test_get_trajectory_breakdown_vazio_sem_metricas(self, mem):
        assert mem.get_trajectory_breakdown() == {}

    def test_get_trajectory_breakdown_conta_por_rotulo(self, mem):
        mem.log_step_metric("code_generation", success=True, trajectory="direct")
        mem.log_step_metric("code_generation", success=True, trajectory="retried")
        mem.log_step_metric("code_generation", success=False, trajectory="loop_detected")
        mem.log_step_metric("code_generation", success=False, trajectory="exhausted")
        mem.log_step_metric("code_generation", success=True, trajectory="direct")
        counts = mem.get_trajectory_breakdown()
        assert counts == {"direct": 2, "retried": 1, "loop_detected": 1, "exhausted": 1}

    def test_get_trajectory_breakdown_filtra_por_step_type(self, mem):
        mem.log_step_metric("code_generation", success=True, trajectory="direct")
        mem.log_step_metric("web_research", success=True, trajectory="retried")
        counts = mem.get_trajectory_breakdown(step_type="web_research")
        assert counts == {"retried": 1}

    def test_get_trajectory_breakdown_ignora_registros_antigos_sem_o_campo(self, mem):
        """Registros gravados antes da 3.3.0 nao tem 'trajectory' -- devem
        ser ignorados, nao contar como uma categoria vazia."""
        mem.log_step_metric("code_generation", success=True)  # trajectory="" (default)
        mem.log_step_metric("code_generation", success=True, trajectory="direct")
        counts = mem.get_trajectory_breakdown()
        assert counts == {"direct": 1}

    def test_get_trajectory_breakdown_respeita_last_n(self, mem):
        for _ in range(3):
            mem.log_step_metric("code_generation", success=True, trajectory="direct")
        for _ in range(2):
            mem.log_step_metric("code_generation", success=False, trajectory="exhausted")
        counts = mem.get_trajectory_breakdown(last_n=2)
        assert counts == {"exhausted": 2}


# --------------------------------------------------------------------------
# Testes: save_chat_snippet + get_last_chat — v2.5.0
# skill: memory-systems (Layer 3 Long-term memory)
# --------------------------------------------------------------------------

class TestChatSnippets:
    """Persistencia de historico de chat cross-session via tabela 'chat_snippets'."""

    def test_save_e_recupera_chat(self, mem):
        msgs = [
            {"role": "user", "text": "Crie um addon de hora"},
            {"role": "assistant", "text": "Addon criado com sucesso."},
        ]
        mem.save_chat_snippet("horaAddon", msgs)
        result = mem.get_last_chat("horaAddon")
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[0]["text"] == "Crie um addon de hora"

    def test_get_last_chat_addon_inexistente_retorna_lista_vazia(self, mem):
        result = mem.get_last_chat("inexistente")
        assert result == []

    def test_save_chat_vazio_nao_grava(self, mem):
        """Lista vazia nao deve criar registro — get retorna vazio."""
        mem.save_chat_snippet("addon", [])
        result = mem.get_last_chat("addon")
        assert result == []

    def test_save_chat_addon_name_vazio_nao_grava(self, mem):
        msgs = [{"role": "user", "text": "teste"}]
        mem.save_chat_snippet("", msgs)
        result = mem.get_last_chat("")
        assert result == []

    def test_save_chat_trunca_a_5_mensagens(self, mem):
        """Apenas as ultimas 5 mensagens sao gravadas."""
        msgs = [{"role": "user", "text": f"msg{i}"} for i in range(10)]
        mem.save_chat_snippet("addon", msgs)
        result = mem.get_last_chat("addon")
        assert len(result) == 5
        # As ultimas 5 mensagens: msg5..msg9
        assert result[0]["text"] == "msg5"
        assert result[-1]["text"] == "msg9"

    def test_get_last_chat_retorna_mais_recente(self, mem):
        """Multiplos saves para o mesmo addon — get retorna o mais recente."""
        msgs1 = [{"role": "user", "text": "primeira sessao"}]
        msgs2 = [{"role": "user", "text": "segunda sessao"}]
        mem.save_chat_snippet("addon", msgs1)
        mem.save_chat_snippet("addon", msgs2)
        result = mem.get_last_chat("addon")
        assert result[0]["text"] == "segunda sessao"

    def test_chats_diferentes_addons_isolados(self, mem):
        mem.save_chat_snippet("addonA", [{"role": "user", "text": "addon A"}])
        mem.save_chat_snippet("addonB", [{"role": "user", "text": "addon B"}])
        assert mem.get_last_chat("addonA")[0]["text"] == "addon A"
        assert mem.get_last_chat("addonB")[0]["text"] == "addon B"

    def test_regra9_texto_nao_executado(self, mem):
        """Regra 9: texto do chat nao e executado, apenas armazenado."""
        marker = os.path.join(os.path.expanduser("~"), "_nvda_chat_exec.txt")
        payload = f"eval(open('{marker}','w').write('x'))"
        msgs = [{"role": "user", "text": payload}]
        mem.save_chat_snippet("addon", msgs)
        result = mem.get_last_chat("addon")
        assert not os.path.exists(marker)
        # Texto foi armazenado inerte
        assert result[0]["text"] == payload[:2000]


class TestGetSimilarSessionsLeOCampoQueSaveSessionEscreve:
    """Achado de auditoria full-stack 2026-08-04: get_similar_sessions() lia
    doc.get("issues", []) -- chave que save_session() NUNCA escreve (grava
    "step_issues", uma STRING unica). Retornava [] sempre; CONSULT_MEMORY
    (agentic_loop.py) rodava sem erro mas nunca injetava licao real na
    query retentada -- no-op silencioso."""

    def test_sessao_com_falha_e_encontrada_com_issues_reconstruidas(self, mem):
        mem.save_session(
            query="crie um addon de transcricao de audio",
            addon_name="Transcritor", plan_id="p1",
            steps_ok=2, steps_total=4, retries=1, success=False,
            summary="falhou na geracao de codigo",
            step_issues=["NVDA-019: falta comentario Translators", "erro de sintaxe"],
        )

        result = mem.get_similar_sessions("crie um addon de transcricao de audio")

        assert len(result) == 1
        assert not result[0]["success"]
        assert result[0]["issues"] == [
            "NVDA-019: falta comentario Translators", "erro de sintaxe",
        ]

    def test_sem_sessao_similar_retorna_vazio(self, mem):
        assert mem.get_similar_sessions("pedido sem nenhuma sessao anterior") == []

    def test_sessao_bem_sucedida_nao_e_retornada(self, mem):
        """So sessoes que FALHARAM (success=False) servem de licao -- o
        proprio metodo filtra por Session.success == False."""
        mem.save_session(
            query="crie um addon de OCR", addon_name="OCRAddon", plan_id="p2",
            steps_ok=4, steps_total=4, retries=0, success=True,
            summary="sucesso", step_issues=[],
        )
        assert mem.get_similar_sessions("crie um addon de OCR") == []
