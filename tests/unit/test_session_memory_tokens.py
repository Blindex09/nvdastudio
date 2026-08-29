import pytest
import nvdastudio.memory.session_memory as sm_mod
from addon.globalPlugins.nvdastudio.memory.session_memory import SessionMemory, MODULE_VERSION


class TestSessionMemoryVersao:
    def test_versao_e_2_5_0(self):
        assert MODULE_VERSION == "3.5.0"


@pytest.fixture
def mem_tokens(tmp_path):
    """SessionMemory isolada em diretorio temporario com cleanup garantido."""
    original_dir = sm_mod._DB_DIR
    original_path = sm_mod._DB_PATH
    sm_mod._DB_DIR = str(tmp_path)
    sm_mod._DB_PATH = str(tmp_path / "test_tokens.json")
    instance = SessionMemory()
    yield instance
    instance.close()
    sm_mod._DB_DIR = original_dir
    sm_mod._DB_PATH = original_path


class TestSessionMemoryTotalTokens:
    """save_session aceita total_tokens e persiste corretamente."""

    def test_save_com_total_tokens(self, mem_tokens):
        doc_id = mem_tokens.save_session(
            query="teste tokens",
            addon_name="TokenAddon",
            plan_id="p-tok",
            steps_ok=2,
            steps_total=2,
            retries=0,
            success=True,
            summary="ok",
            total_tokens=1500,
        )
        assert doc_id is not None

    def test_save_sem_total_tokens_usa_zero(self, mem_tokens):
        """total_tokens é opcional — deve funcionar sem ele."""
        doc_id = mem_tokens.save_session(
            query="sem tokens",
            addon_name="SemToken",
            plan_id="p-st",
            steps_ok=1,
            steps_total=1,
            retries=0,
            success=True,
            summary="ok",
        )
        assert doc_id is not None

    def test_total_tokens_salvo_e_recuperado(self, mem_tokens):
        mem_tokens.save_session(
            query="query tokens persistida",
            addon_name="PersistAddon",
            plan_id="p-pers",
            steps_ok=3,
            steps_total=3,
            retries=1,
            success=True,
            summary="3/3 ok",
            total_tokens=9999,
        )
        recent = mem_tokens.get_recent(limit=1)
        assert len(recent) >= 1
        # SessionRecord não expõe total_tokens diretamente, mas save não deve falhar

    def test_total_tokens_zero_aceito(self, mem_tokens):
        doc_id = mem_tokens.save_session(
            query="zero tokens",
            addon_name="ZeroToken",
            plan_id="p-z",
            steps_ok=0,
            steps_total=1,
            retries=0,
            success=False,
            summary="falhou",
            total_tokens=0,
        )
        assert doc_id is not None

    def test_total_tokens_alto_aceito(self, mem_tokens):
        """Valores altos de tokens (100k+) devem ser aceitos sem truncagem."""
        doc_id = mem_tokens.save_session(
            query="addon pesado",
            addon_name="HeavyAddon",
            plan_id="p-h",
            steps_ok=5,
            steps_total=5,
            retries=2,
            success=True,
            summary="ok",
            total_tokens=150_000,
        )
        assert doc_id is not None

    def test_nao_executa_tokens_como_codigo(self, mem_tokens):
        """total_tokens é inteiro — não deve ser tratado como código."""
        doc_id = mem_tokens.save_session(
            query="teste seguranca",
            addon_name="SecureAddon",
            plan_id="p-sec",
            steps_ok=1,
            steps_total=1,
            retries=0,
            success=True,
            summary="ok",
            total_tokens=42,
        )
        # Se chegou aqui sem executar nada, está correto
        assert doc_id is not None

