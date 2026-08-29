import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ===========================================================================
# 1. session_memory — tabela dep_failures
# ===========================================================================

class TestDepFailuresMemory:
    """SessionMemory deve persistir e recuperar falhas de dependencias."""

    def _make_memory(self, tmp_path):
        """Instancia SessionMemory isolada em tmp_path."""
        import nvdastudio.memory.session_memory as sm_mod
        original_path = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "test_memory.json")
        mem = sm_mod.SessionMemory()
        yield mem
        mem.close()
        sm_mod._DB_PATH = original_path

    def test_log_dep_failure_salva_registro(self, tmp_path):
        """log_dep_failure deve salvar pacote na tabela dep_failures."""
        from nvdastudio.memory.session_memory import SessionMemory
        import nvdastudio.memory.session_memory as sm_mod
        original = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "mem.json")
        mem = SessionMemory()
        try:
            mem.log_dep_failure("triton", "nao_encontrado_pypi", "GeminiAssistant")
            failures = mem.get_dep_failures(limit=10)
            nomes = [f["pkg"] for f in failures]
            assert "triton" in nomes, (
                f"triton deveria estar em dep_failures. Encontrado: {nomes}"
            )
        finally:
            mem.close()
            sm_mod._DB_PATH = original

    def test_get_dep_failures_retorna_com_razao(self, tmp_path):
        """get_dep_failures deve retornar pkg e reason de cada falha."""
        from nvdastudio.memory.session_memory import SessionMemory
        import nvdastudio.memory.session_memory as sm_mod
        original = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "mem.json")
        mem = SessionMemory()
        try:
            mem.log_dep_failure("torch", "nao_encontrado_pypi", "MeuAddon")
            failures = mem.get_dep_failures(limit=10)
            assert len(failures) >= 1
            f = next(x for x in failures if x["pkg"] == "torch")
            assert f["reason"] == "nao_encontrado_pypi"
        finally:
            mem.close()
            sm_mod._DB_PATH = original

    def test_get_dep_failures_sem_historico_retorna_lista_vazia(self, tmp_path):
        """Se nenhuma falha foi registrada, get_dep_failures retorna []."""
        from nvdastudio.memory.session_memory import SessionMemory
        import nvdastudio.memory.session_memory as sm_mod
        original = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "mem.json")
        mem = SessionMemory()
        try:
            failures = mem.get_dep_failures(limit=10)
            assert failures == [], f"Sem historico deve retornar []. Retornou: {failures}"
        finally:
            mem.close()
            sm_mod._DB_PATH = original

    def test_dep_failures_multiplos_pacotes(self, tmp_path):
        """Multiplos pacotes diferentes devem ser registrados separadamente."""
        from nvdastudio.memory.session_memory import SessionMemory
        import nvdastudio.memory.session_memory as sm_mod
        original = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "mem.json")
        mem = SessionMemory()
        try:
            mem.log_dep_failure("triton", "nao_encontrado_pypi", "Addon1")
            mem.log_dep_failure("torchvision", "nao_encontrado_pypi", "Addon2")
            mem.log_dep_failure("tensorflow", "nao_encontrado_pypi", "Addon3")
            failures = mem.get_dep_failures(limit=10)
            nomes = {f["pkg"] for f in failures}
            assert "triton" in nomes
            assert "torchvision" in nomes
            assert "tensorflow" in nomes
        finally:
            mem.close()
            sm_mod._DB_PATH = original

    def test_dep_failures_respeita_limit(self, tmp_path):
        """get_dep_failures deve respeitar o parametro limit."""
        from nvdastudio.memory.session_memory import SessionMemory
        import nvdastudio.memory.session_memory as sm_mod
        original = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "mem.json")
        mem = SessionMemory()
        try:
            for i in range(5):
                mem.log_dep_failure(f"pkg_{i}", "nao_encontrado_pypi", "Addon")
            failures = mem.get_dep_failures(limit=2)
            assert len(failures) <= 2
        finally:
            mem.close()
            sm_mod._DB_PATH = original


# ===========================================================================
# 2. addon_builder._package_exists_on_pypi — verificacao semantica
# ===========================================================================

class TestPackageExistsOnPypi:
    """_package_exists_on_pypi verifica PyPI sem keywords."""

    def test_404_retorna_false(self):
        """Pacote que retorna 404 do PyPI nao existe — retorna False."""
        from unittest.mock import patch
        from nvdastudio.builder.addon_builder import _package_exists_on_pypi
        import urllib.error as uerr
        with patch("urllib.request.urlopen",
                   side_effect=uerr.HTTPError(None, 404, "Not Found", {}, None)):
            result = _package_exists_on_pypi("triton-nao-existe-xyz")
            assert result is False, "404 deve retornar False"

    def test_200_retorna_true(self):
        """Pacote que retorna 200 existe no PyPI — retorna True."""
        from unittest.mock import patch, MagicMock
        from nvdastudio.builder.addon_builder import _package_exists_on_pypi
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _package_exists_on_pypi("requests")
            assert result is True, "200 deve retornar True"

    def test_timeout_retorna_true_fail_open(self):
        """Timeout nao deve bloquear instalacao — fail-open (True)."""
        from unittest.mock import patch
        from nvdastudio.builder.addon_builder import _package_exists_on_pypi
        with patch("urllib.request.urlopen",
                   side_effect=TimeoutError("timeout")):
            result = _package_exists_on_pypi("qualquer-pacote")
            assert result is True, "Timeout deve ser fail-open (True)"

    def test_sem_internet_retorna_true_fail_open(self):
        """Sem internet (OSError) nao deve bloquear instalacao — fail-open."""
        from unittest.mock import patch
        from nvdastudio.builder.addon_builder import _package_exists_on_pypi
        with patch("urllib.request.urlopen",
                   side_effect=OSError("Network unreachable")):
            result = _package_exists_on_pypi("qualquer-pacote")
            assert result is True, "Erro de rede deve ser fail-open (True)"

    def test_outro_erro_http_retorna_true_fail_open(self):
        """500, 503 etc nao sao 404 — PyPI pode estar down, fail-open."""
        from unittest.mock import patch
        from nvdastudio.builder.addon_builder import _package_exists_on_pypi
        import urllib.error as uerr
        with patch("urllib.request.urlopen",
                   side_effect=uerr.HTTPError(None, 503, "Service Unavailable", {}, None)):
            result = _package_exists_on_pypi("qualquer-pacote")
            assert result is True, "Erro 503 deve ser fail-open (True)"


# ===========================================================================
# 3. bundle_addon_dependencies — ignora pacote inexistente no PyPI
# ===========================================================================

class TestBundleIgnoraPacoteInexistentePypi:
    """Bundle deve ignorar pacotes que nao existem no PyPI sem tentar instalar."""

    def test_pacote_nao_existe_pypi_nao_chama_pip(self, tmp_path):
        """Se PyPI retorna 404, bundle nao deve chamar pip install."""
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch, MagicMock
        pip_calls = []
        def fake_subprocess(cmd, **kwargs):
            if "pip" in str(cmd) or "install" in str(cmd):
                pip_calls.append(cmd)
            r = MagicMock()
            r.returncode = 1
            r.stdout = ""
            r.stderr = ""
            return r
        with patch("subprocess.run", side_effect=fake_subprocess), \
             patch("nvdastudio.builder.addon_builder.create_llm_client"):
            result = bundle_addon_dependencies(
                str(tmp_path), ["triton-fantasma"],
                "MeuAddon",
                _pypi_checker=lambda pkg: False,  # simula 404 para tudo
            )
            assert pip_calls == [], (
                "pip nao deve ser chamado para pacote inexistente no PyPI"
            )
            assert result == []

    def test_pacote_existente_pypi_chama_pip(self, tmp_path):
        """Se PyPI confirma existencia, bundle deve tentar pip install."""
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch, MagicMock
        ok = MagicMock()
        ok.returncode = 0
        with patch("subprocess.run", return_value=ok) as mock_pip:
            bundle_addon_dependencies(
                str(tmp_path), ["requests"],
                "MeuAddon",
                _pypi_checker=lambda pkg: True,  # simula 200 para tudo
            )
            assert mock_pip.call_count >= 1, "pip deve ser chamado para pacote existente"

    def test_mistura_existente_e_inexistente(self, tmp_path):
        """Existente vai ao pip, inexistente e ignorado."""
        from nvdastudio.builder.addon_builder import bundle_addon_dependencies
        from unittest.mock import patch, MagicMock
        ok = MagicMock()
        ok.returncode = 0

        def fake_checker(pkg):
            return pkg == "requests"  # so requests "existe"

        with patch("subprocess.run", return_value=ok) as mock_pip:
            bundle_addon_dependencies(
                str(tmp_path), ["requests", "triton-fantasma"],
                "MeuAddon",
                _pypi_checker=fake_checker,
            )
        all_args = " ".join(
            str(a) for call in mock_pip.call_args_list for a in call[0][0]
        )
        assert "requests" in all_args, "requests deve ir ao pip"
        assert "triton-fantasma" not in all_args, "triton-fantasma nao deve ir ao pip"


# ===========================================================================
# 4. code_generator — dep_failures injetado como contexto semantico
# ===========================================================================

class TestCodeGeneratorDepFailuresContexto:
    """
    code_generator deve consultar dep_failures e injetar no system prompt
    para que o LLM evite semanticamente pacotes que ja falharam.
    """

    def test_system_menciona_deps_que_falharam(self):
        """
        Se existem dep_failures registradas, o full_system passado ao LLM
        deve mencionar esses pacotes para o modelo evitar.
        Sem keywords — o modelo interpreta semanticamente.
        """
        from unittest.mock import patch, MagicMock

        # Injeta falhas na memory mockada
        fake_mem = MagicMock()
        fake_mem.get_dep_failures.return_value = [
            {"pkg": "triton", "reason": "nao_encontrado_pypi"},
            {"pkg": "torch", "reason": "nao_encontrado_pypi"},
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

        fake_client = MagicMock()
        fake_client.chat.side_effect = fake_chat

        with patch("nvdastudio.sub_agents.code_generator.memory", fake_mem):
            with patch("nvdastudio.sub_agents.code_generator.create_llm_client",
                       return_value=fake_client):
                with patch("nvdastudio.sub_agents.code_generator.get_docs_code_generation",
                           return_value=""):
                    from nvdastudio.sub_agents.code_generator import run
                    run("crie um addon simples", "modelo", {})

        assert len(captured_system) > 0, "system_override deve ter sido passado"
        system_usado = captured_system[0]
        assert "triton" in system_usado, (
            "dep_failures devem ser injetados no contexto para o LLM evitar semanticamente"
        )
        assert "torch" in system_usado, (
            "todos os pacotes com falha devem aparecer no contexto"
        )
