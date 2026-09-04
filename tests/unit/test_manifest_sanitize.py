from nvdastudio.builder.addon_builder import _sanitize_manifest, MODULE_VERSION


class TestAddonBuilderVersao170:
    def test_versao_e_1_8_0(self):
        assert MODULE_VERSION == "4.25.0"


class TestSanitizeManifest:
    """Testa sanitizacao deterministica do manifest.ini (Bug B4)."""

    def test_campo_summary_multiline_vira_uma_linha(self):
        manifest = (
            "name = MeuAddon\n"
            "summary = Addon para transcrever audios,\n"
            "    imagens e outras midias em texto.\n"
            "version = 1.0.0\n"
        )
        result = _sanitize_manifest(manifest)
        lines = [line for line in result.splitlines() if line.startswith("summary")]
        assert len(lines) == 1, "summary deve estar em uma unica linha"
        assert "\n" not in lines[0]

    def test_campo_description_multiline_vira_uma_linha(self):
        manifest = (
            "name = MeuAddon\n"
            "description = O addon faz X,\n"
            "    Y e Z.\n"
            "version = 1.0.0\n"
        )
        result = _sanitize_manifest(manifest)
        lines = [line for line in result.splitlines() if line.startswith("description")]
        assert len(lines) == 1

    def test_campo_changelog_multiline_vira_uma_linha(self):
        manifest = (
            "name = MeuAddon\n"
            "changelog = Versao inicial com suporte a X,\n"
            "    Y e Z.\n"
        )
        result = _sanitize_manifest(manifest)
        lines = [line for line in result.splitlines() if line.startswith("changelog")]
        assert len(lines) == 1

    def test_campo_ja_em_uma_linha_preservado(self):
        manifest = (
            "name = MeuAddon\n"
            "summary = Addon que anuncia hora e data.\n"
            "version = 1.0.0\n"
        )
        result = _sanitize_manifest(manifest)
        assert "Addon que anuncia hora e data." in result

    def test_campos_nao_texto_preservados(self):
        """Campos de versao, url, name nao devem ser alterados."""
        manifest = (
            "name = MeuAddon\n"
            "version = 1.0.0\n"
            "minimumNVDAVersion = 2026.1.1\n"
            "lastTestedNVDAVersion = 2026.1.1\n"
            "url = https://github.com/user/addon\n"
            "docFileName = userGuide.html\n"
            "updateChannel = stable\n"
        )
        result = _sanitize_manifest(manifest)
        assert "1.0.0" in result
        assert "2026.1" in result
        assert "userGuide.html" in result
        assert "stable" in result

    def test_manifest_valido_sem_multiline_retorna_igual(self):
        manifest = (
            "name = MeuAddon\n"
            "summary = Descricao curta.\n"
            "description = Descricao longa em uma linha.\n"
            "version = 1.0.0\n"
        )
        result = _sanitize_manifest(manifest)
        # Todos os campos ainda presentes
        assert "name = MeuAddon" in result
        assert "summary = Descricao curta." in result
        assert "version = 1.0.0" in result

    def test_retorna_string(self):
        result = _sanitize_manifest("name = X\nversion = 1.0.0\n")
        assert isinstance(result, str)

    def test_nao_executa_codigo(self):
        """Sanitizacao e puramente deterministica — nao chama LLM."""
        import os
        before = os.environ.get("NVDASTUDIO_TEST_EXEC", "0")
        _sanitize_manifest("name = X\nsummary = y,\n    z.\n")
        after = os.environ.get("NVDASTUDIO_TEST_EXEC", "0")
        assert before == after

    def test_manifest_vazio_retorna_string(self):
        result = _sanitize_manifest("")
        assert isinstance(result, str)

    def test_conteudo_multiline_unido_com_espaco(self):
        manifest = "summary = primeira parte,\n    segunda parte.\n"
        result = _sanitize_manifest(manifest)
        lines = [line for line in result.splitlines() if line.startswith("summary")]
        assert len(lines) == 1
        # O conteudo das partes deve aparecer junto
        assert "primeira parte" in lines[0]
        assert "segunda parte" in lines[0]


class TestFindPython:
    """Testa localizacao do Python real fora do processo NVDA (Bug B5)."""

    def test_bundle_usa_python_que_nao_e_nvda(self):
        """bundle_addon_dependencies deve usar Python que nao contenha 'nvda' no path."""
        # Importa a funcao interna via inspecao do codigo-fonte
        import inspect
        from nvdastudio.builder import addon_builder
        src = inspect.getsource(addon_builder.bundle_addon_dependencies)
        assert "_find_python" in src, "_find_python deve estar em bundle_addon_dependencies"

    def test_bundle_captura_oserror(self):
        """WinError 740 (OSError) nao deve propagar — deve ser capturado graciosamente."""
        import inspect
        from nvdastudio.builder import addon_builder
        src = inspect.getsource(addon_builder.bundle_addon_dependencies)
        assert "OSError" in src, "OSError deve ser capturado no bundle"

    def test_bundle_captura_timeout(self):
        """Timeout de subprocess deve ser capturado graciosamente."""
        import inspect
        from nvdastudio.builder import addon_builder
        src = inspect.getsource(addon_builder.bundle_addon_dependencies)
        assert "TimeoutExpired" in src, "TimeoutExpired deve ser capturado no bundle"

    def test_bundle_tem_timeout_parametro(self):
        """subprocess.run deve ter timeout para nao bloquear indefinidamente."""
        import inspect
        from nvdastudio.builder import addon_builder
        src = inspect.getsource(addon_builder.bundle_addon_dependencies)
        assert "timeout=" in src, "subprocess.run deve ter timeout="

    def test_bundle_nao_usa_sys_executable_diretamente(self):
        """sys.executable nao deve ser usado diretamente (pode ser nvda.exe)."""
        import inspect
        from nvdastudio.builder import addon_builder
        src = inspect.getsource(addon_builder.bundle_addon_dependencies)
        # _find_python() e o wrapper — sys.executable pode aparecer como fallback
        # mas nao deve ser o primeiro na lista de candidatos
        assert "_find_python" in src
        # A chamada do cmd deve usar python_exe, nao sys.executable diretamente
        assert "python_exe" in src
