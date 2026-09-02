import os
import tempfile


# -----------------------------------------------------------------------
# Gap A — NVDA-024: dependencies[] so aceita nomes PyPI
# -----------------------------------------------------------------------

class TestCodeGeneratorNVDA024:
    """skill: llm-structured-output + nvda-addon-dev §22."""

    def test_versao_2_4_0(self):
        from nvdastudio.sub_agents.code_generator import MODULE_VERSION
        assert MODULE_VERSION == "3.34.0"

    def test_nvda_024_presente_no_system(self):
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        assert "NVDA-024" in _SYSTEM

    def test_tabela_conversao_googleapiclient(self):
        """Tabela deve mapear googleapiclient -> google-api-python-client."""
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        assert "googleapiclient" in _SYSTEM
        assert "google-api-python-client" in _SYSTEM

    def test_tabela_conversao_google_auth(self):
        """Tabela deve mapear google.auth -> google-auth."""
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        assert "google-auth" in _SYSTEM

    def test_proibidos_stdlib_webbrowser(self):
        """webbrowser deve estar explicitamente proibido."""
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        assert "webbrowser" in _SYSTEM

    def test_proibidos_nvda_modules(self):
        """nvda e nvdaHelper devem estar explicitamente proibidos."""
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        assert "nvda, nvdaHelper" in _SYSTEM or (
            "nvda" in _SYSTEM and "nvdaHelper" in _SYSTEM
        )

    def test_proibidos_submodulos(self):
        """Submódulos com ponto no meio devem estar proibidos."""
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        assert "googleapiclient.discovery" in _SYSTEM
        assert "google.auth.transport.requests" in _SYSTEM

    def test_verificacao_final_item_10(self):
        """VERIFICACAO FINAL deve ter item 10 sobre dependencies[]."""
        from nvdastudio.sub_agents.code_generator import _SYSTEM
        assert "10." in _SYSTEM
        assert "NVDA-024" in _SYSTEM


# -----------------------------------------------------------------------
# Gap B — fix_addon_structure() funde pastas com nomes DIFERENTES
# -----------------------------------------------------------------------

class TestFixAddonStructureDiferentNames:
    """skill: tool-design + nvda-addon-dev §1."""

    def test_addon_builder_versao_2_6_0(self):
        from nvdastudio.builder.addon_builder import MODULE_VERSION
        assert MODULE_VERSION == "4.22.0"

    def _make_addon(self, tmp_dir: str, dirs: dict[str, list[str]],
                    manifest_name: str | None = None) -> str:
        """
        Cria estrutura de addon em tmp_dir.
        dirs = {pasta: [lista_de_arquivos.py]}
        manifest_name: campo name= no manifest.ini (None = sem manifest)
        """
        gp = os.path.join(tmp_dir, "globalPlugins")
        os.makedirs(gp)
        for folder, files in dirs.items():
            fpath = os.path.join(gp, folder)
            os.makedirs(fpath)
            for fname in files:
                content = "class GlobalPlugin:\n\tpass\n" if fname == "__init__.py" else f"# {fname}\n"
                with open(os.path.join(fpath, fname), "w") as f:
                    f.write(content)
        if manifest_name:
            with open(os.path.join(tmp_dir, "manifest.ini"), "w") as f:
                f.write(f"name = {manifest_name}\nversion = 1.0.0\n")
        return tmp_dir

    def test_nomes_diferentes_funde_em_canonico_do_manifest(self):
        """GmailSummarizer + GmailResumo -> funde em GmailSummarizer (nome do manifest)."""
        from nvdastudio.builder.addon_builder import fix_addon_structure
        with tempfile.TemporaryDirectory() as tmp:
            self._make_addon(tmp, {
                "GmailSummarizer": ["__init__.py", "gmail_service.py"],
                "GmailResumo": ["settings_panel.py", "ai_runner.py"],
            }, manifest_name="GmailSummarizer")
            actions = fix_addon_structure(tmp)
            assert len(actions) > 0
            gp = os.path.join(tmp, "globalPlugins")
            remaining = os.listdir(gp)
            assert len(remaining) == 1
            assert remaining[0] == "GmailSummarizer"
            # Todos os .py devem estar em GmailSummarizer
            canon = os.path.join(gp, "GmailSummarizer")
            files = os.listdir(canon)
            assert "__init__.py" in files
            assert "gmail_service.py" in files
            assert "settings_panel.py" in files
            assert "ai_runner.py" in files

    def test_nomes_diferentes_sem_manifest_usa_globalPlugin(self):
        """Sem manifest: escolhe pasta que tem class GlobalPlugin."""
        from nvdastudio.builder.addon_builder import fix_addon_structure
        with tempfile.TemporaryDirectory() as tmp:
            gp = os.path.join(tmp, "globalPlugins")
            os.makedirs(gp)
            # PastaA tem GlobalPlugin, PastaB nao
            pasta_a = os.path.join(gp, "PastaA")
            pasta_b = os.path.join(gp, "PastaB")
            os.makedirs(pasta_a)
            os.makedirs(pasta_b)
            with open(os.path.join(pasta_a, "__init__.py"), "w") as f:
                f.write("class GlobalPlugin:\n\tpass\n")
            with open(os.path.join(pasta_b, "helper.py"), "w") as f:
                f.write("# helper\n")
            actions = fix_addon_structure(tmp)
            assert len(actions) > 0
            remaining = os.listdir(gp)
            assert len(remaining) == 1
            assert remaining[0] == "PastaA"
            # helper.py deve ter sido movido para PastaA
            assert "helper.py" in os.listdir(pasta_a)

    def test_pasta_unica_nao_mexe(self):
        """Uma unica pasta -> retorna [] sem modificar nada."""
        from nvdastudio.builder.addon_builder import fix_addon_structure
        with tempfile.TemporaryDirectory() as tmp:
            self._make_addon(tmp, {"MeuAddon": ["__init__.py"]})
            actions = fix_addon_structure(tmp)
            assert actions == []

    def test_nomes_iguais_duplicados_ainda_funde(self):
        """Comportamento anterior preservado: duas pastas com mesmo nome."""
        from nvdastudio.builder.addon_builder import fix_addon_structure
        with tempfile.TemporaryDirectory() as tmp:
            self._make_addon(tmp, {
                "MeuAddon": ["__init__.py"],
                "OutroAddon": ["__init__.py", "extra.py"],
            })
            actions = fix_addon_structure(tmp)
            assert len(actions) > 0
            gp = os.path.join(tmp, "globalPlugins")
            assert len(os.listdir(gp)) == 1

    def test_arquivo_duplicado_preserva_canonico(self):
        """Se arquivo ja existe no canonico, o extra e descartado (nao sobrescreve)."""
        from nvdastudio.builder.addon_builder import fix_addon_structure
        with tempfile.TemporaryDirectory() as tmp:
            gp = os.path.join(tmp, "globalPlugins")
            os.makedirs(gp)
            pasta_a = os.path.join(gp, "PastaA")
            pasta_b = os.path.join(gp, "PastaB")
            os.makedirs(pasta_a)
            os.makedirs(pasta_b)
            with open(os.path.join(pasta_a, "__init__.py"), "w") as f:
                f.write("class GlobalPlugin:\n\tpass\n# versao canonica\n")
            with open(os.path.join(pasta_b, "__init__.py"), "w") as f:
                f.write("class GlobalPlugin:\n\tpass\n# versao extra — deve ser descartada\n")
            fix_addon_structure(tmp)
            with open(os.path.join(pasta_a, "__init__.py")) as f:
                content = f.read()
            assert "canonica" in content  # preservou o canonico

    def test_sem_globalPlugins_retorna_vazio(self):
        """Sem pasta globalPlugins/ -> retorna [] silenciosamente."""
        from nvdastudio.builder.addon_builder import fix_addon_structure
        with tempfile.TemporaryDirectory() as tmp:
            actions = fix_addon_structure(tmp)
            assert actions == []


# -----------------------------------------------------------------------
# Gap C — planner: addon_name canonico
# -----------------------------------------------------------------------

class TestPlannerAddonNameCanonical:
    """skills: software-architecture + llm-structured-output."""

    def test_planner_versao_2_2_0(self):
        from nvdastudio.core.planner import MODULE_VERSION
        assert MODULE_VERSION == "2.44.0"

    def test_addon_name_no_dataclass(self):
        """ExecutionPlan deve ter campo addon_name."""
        from nvdastudio.core.planner import ExecutionPlan
        import dataclasses
        fields = {f.name for f in dataclasses.fields(ExecutionPlan)}
        assert "addon_name" in fields

    def test_addon_name_default_vazio(self):
        """addon_name tem default vazio (nao obrigatorio no construtor)."""
        from nvdastudio.core.planner import ExecutionPlan
        plan = ExecutionPlan(plan_id="t1", original_query="teste", steps=[])
        assert plan.addon_name == ""

    def test_addon_name_no_schema(self):
        """_PLAN_SCHEMA deve incluir addon_name como campo required."""
        import inspect
        import nvdastudio.core.planner as planner_mod
        src = inspect.getsource(planner_mod)
        schema_start = src.find("_PLAN_SCHEMA =")
        assert schema_start != -1
        schema_src = src[schema_start:schema_start + 5000]
        assert '"addon_name"' in schema_src

    def test_addon_name_required_no_schema(self):
        """addon_name deve estar na lista required do schema raiz (nao do sub-schema de steps)."""
        import inspect
        import nvdastudio.core.planner as planner_mod
        src = inspect.getsource(planner_mod)
        schema_start = src.find("_PLAN_SCHEMA =")
        assert schema_start != -1, "_PLAN_SCHEMA nao encontrado no planner"
        schema_src = src[schema_start:]

        # 2026-08-29: a versao anterior fatiava os primeiros 9000 chars e pegava o
        # ULTIMO '"required"' dessa janela. Frageis os dois: qualquer campo novo com
        # descricao longa empurra o required da RAIZ para fora da janela, e o teste
        # passa a inspecionar o required dos STEPS -- foi o que aconteceu ao adicionar
        # `expected_gestures`. O teste falhava sem que nada estivesse errado no schema.
        #
        # Agora identifica o nivel pelo que ele e de verdade: o required da raiz e o
        # MENOS indentado do bloco (os aninhados, como o dos steps, tem mais tabs).
        candidatos = [
            linha for linha in schema_src.split("\n") if '"required"' in linha
        ]
        assert candidatos, "nenhuma lista required encontrada no schema"
        raiz = min(candidatos, key=lambda ln: len(ln) - len(ln.lstrip("\t")))

        # A lista pode continuar na(s) linha(s) seguinte(s); junta ate fechar o ].
        idx = schema_src.index(raiz)
        bloco = schema_src[idx:idx + 600]
        assert "addon_name" in bloco.split("]")[0]

    def test_addon_name_regra_no_prompt(self):
        """_PLAN_SYSTEM_PROMPT deve ter regra explicita sobre addon_name."""
        from nvdastudio.core.planner import _PLAN_SYSTEM_PROMPT
        assert "addon_name" in _PLAN_SYSTEM_PROMPT
        assert "CamelCase" in _PLAN_SYSTEM_PROMPT

    def test_addon_name_description_menciona_proibicao(self):
        """description do addon_name deve mencionar nomes diferentes em steps."""
        import inspect
        import nvdastudio.core.planner as planner_mod
        src = inspect.getsource(planner_mod)
        schema_start = src.find("_PLAN_SCHEMA =")
        schema_src = src[schema_start:schema_start + 5000]
        idx = schema_src.find('"addon_name"')
        trecho = schema_src[idx:idx + 400]
        # Deve mencionar que nomes diferentes causam conflito
        assert "NUNCA" in trecho or "nunca" in trecho or "steps" in trecho.lower()
