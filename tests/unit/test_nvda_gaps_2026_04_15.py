import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ===========================================================================
# 1. code_generator — novas regras NVDA-043 a NVDA-046
# ===========================================================================

class TestCodeGeneratorNovasRegras:
    """Novas regras NVDA devem estar presentes no _SYSTEM do code_generator."""

    def _src(self):
        import inspect
        from nvdastudio.sub_agents import code_generator
        return inspect.getsource(code_generator)

    def test_nvda_043_braille_tables_coberto(self):
        src = self._src()
        assert "NVDA-043" in src or (
            "brailleTables" in src and "displayName" in src
        ), "NVDA-043 (Braille Translation Tables) deve estar no code_generator"

    def test_nvda_044_symbol_dicts_coberto(self):
        src = self._src()
        assert "NVDA-044" in src or (
            "symbolDictionaries" in src and "locale" in src.lower()
        ), "NVDA-044 (Symbol Dictionaries) deve estar no code_generator"

    def test_nvda_045_locale_gestures_coberto(self):
        src = self._src()
        assert "NVDA-045" in src or (
            "gestures.ini" in src
        ), "NVDA-045 (Locale Gesture Remapping) deve estar no code_generator"

    def test_nvda_046_cli_args_coberto(self):
        src = self._src()
        assert "NVDA-046" in src or (
            "isCLIParamKnown" in src
        ), "NVDA-046 (CLI Arguments) deve estar no code_generator"

    def test_nvda_object_most_specific_class(self):
        src = self._src()
        assert "most specific" in src.lower() or "mais especifica" in src.lower(), (
            "Regra de herdar da classe mais especifica de NVDAObject "
            "deve estar no code_generator"
        )

    def test_verificacao_final_cobre_novas_regras(self):
        """Checklist VERIFICACAO FINAL deve ter ao menos 18 itens."""
        src = self._src()
        # Conta itens numerados no checklist (padrão "NN. ")
        import re
        nums = re.findall(r'^\d{1,2}\.', src, re.MULTILINE)
        high = max(int(n.rstrip('.')) for n in nums) if nums else 0
        assert high >= 18, (
            f"VERIFICACAO FINAL deve ter ao menos 18 itens. Maior numero encontrado: {high}"
        )


# ===========================================================================
# 2. manifest_builder — brailleTables e symbolDictionaries
# ===========================================================================

class TestManifestBuilderNovosCampos:
    """manifest_builder deve conhecer [brailleTables] e [symbolDictionaries]."""

    def _src(self):
        import inspect
        from nvdastudio.sub_agents import manifest_builder
        return inspect.getsource(manifest_builder)

    def test_braille_tables_mencionado(self):
        src = self._src()
        assert "brailleTables" in src, (
            "manifest_builder deve mencionar secao [brailleTables]"
        )

    def test_symbol_dicts_mencionado(self):
        src = self._src()
        assert "symbolDictionaries" in src, (
            "manifest_builder deve mencionar secao [symbolDictionaries]"
        )


# ===========================================================================
# 3. web_researcher — dead code removido
# ===========================================================================

class TestWebResearcherSemCodigoMorto:
    """_build_temporal_window_queries deve ter sido removida (era dead code)."""

    def test_funcao_legada_removida(self):
        """A funcao v1.4.0 nao deve mais existir como definicao no modulo."""
        import inspect
        import re
        from nvdastudio.sub_agents import web_researcher
        src = inspect.getsource(web_researcher)
        # Verifica que nao existe DEFINICAO da funcao (def _build_temporal...)
        # O nome pode aparecer em docstring/changelog, mas nao como funcao definida
        assert not re.search(r'^\s*def _build_temporal_window_queries\b', src, re.MULTILINE), (
            "_build_temporal_window_queries foi removida como dead code em v1.6.0. "
            "run() usa exclusivamente _build_deep_search_windows."
        )


# ===========================================================================
# 6. session_memory — upsert em web_knowledge
# ===========================================================================

class TestWebKnowledgeUpsert:
    """save_web_knowledge deve atualizar entrada existente, nao duplicar."""

    def _mem(self, tmp_path):
        import nvdastudio.memory.session_memory as sm_mod
        orig = sm_mod._DB_PATH
        sm_mod._DB_PATH = str(tmp_path / "mem.json")
        from nvdastudio.memory.session_memory import SessionMemory
        return SessionMemory(), sm_mod, orig

    def test_salva_duas_vezes_nao_duplica(self, tmp_path):
        """Salvar mesmo topic duas vezes nao deve criar 2 registros distintos."""
        mem, sm, orig = self._mem(tmp_path)
        try:
            mem.save_web_knowledge("elevenlabs", "versao 1", "", 2026)
            mem.save_web_knowledge("elevenlabs", "versao 2 atualizada", "", 2026)
            results = mem.get_web_knowledge("elevenlabs", max_age_days=1)
            assert len(results) == 1, (
                f"Mesmo topic salvo duas vezes deve ter 1 registro. "
                f"Encontrou: {len(results)}"
            )
        finally:
            mem.close()
            sm._DB_PATH = orig

    def test_upsert_preserva_conteudo_mais_recente(self, tmp_path):
        """Apos upsert, o conteudo deve ser o da ultima chamada."""
        mem, sm, orig = self._mem(tmp_path)
        try:
            mem.save_web_knowledge("ollama", "versao antiga", "", 2025)
            mem.save_web_knowledge("ollama", "versao nova 2026", "", 2026)
            results = mem.get_web_knowledge("ollama", max_age_days=365)
            assert len(results) == 1
            assert "nova 2026" in results[0]["content"], (
                f"Upsert deve preservar conteudo mais recente. "
                f"Conteudo: {results[0]['content']}"
            )
        finally:
            mem.close()
            sm._DB_PATH = orig

    def test_topicos_diferentes_sao_salvos_separadamente(self, tmp_path):
        """Topics distintos devem ter registros separados."""
        mem, sm, orig = self._mem(tmp_path)
        try:
            mem.save_web_knowledge("elevenlabs", "conteudo A", "", 2026)
            mem.save_web_knowledge("google-generativeai", "conteudo B", "", 2026)
            r1 = mem.get_web_knowledge("elevenlabs", max_age_days=1)
            r2 = mem.get_web_knowledge("google-generativeai", max_age_days=1)
            assert len(r1) == 1 and len(r2) == 1, (
                f"Topics diferentes devem ter registros separados. "
                f"elevenlabs={len(r1)}, google-generativeai={len(r2)}"
            )
        finally:
            mem.close()
            sm._DB_PATH = orig
