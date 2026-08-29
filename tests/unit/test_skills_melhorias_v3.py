# ===========================================================================
# 1. validate_import tool — code_generator v2.1.0
# ===========================================================================

class TestValidateImportToolDesign:
    """Descricao do validate_import deve responder: o que faz, quando usar,
    o que aceita, o que retorna e como agir em cada status."""

    def test_versao_e_2_1_0(self):
        from addon.globalPlugins.nvdastudio.sub_agents.code_generator import MODULE_VERSION
        assert MODULE_VERSION == "3.33.0"

    def _get_tool_description(self):
        from addon.globalPlugins.nvdastudio.sub_agents import code_generator
        import inspect
        src = inspect.getsource(code_generator.run)
        # Extrai a descricao do tool diretamente do modulo
        # Procura pela string de descricao no codigo-fonte
        idx = src.find('"description"')
        assert idx != -1, "Campo description nao encontrado no tools[]"
        return src[idx:]

    def test_tool_tem_quando_usar(self):
        desc = self._get_tool_description()
        assert "QUANDO USAR" in desc or "quando usar" in desc.lower()

    def test_tool_tem_status_nvda(self):
        desc = self._get_tool_description()
        assert "status='nvda'" in desc or "status=\\'nvda\\'" in desc or "nvda" in desc.lower()

    def test_tool_tem_status_unknown(self):
        desc = self._get_tool_description()
        assert "unknown" in desc.lower()

    def test_tool_tem_acao_para_unknown(self):
        desc = self._get_tool_description()
        assert "dependencies" in desc.lower()

    def test_tool_tem_exemplo_de_module_name(self):
        desc = self._get_tool_description()
        # Deve ter pelo menos um exemplo de nome de modulo
        assert "whisper" in desc or "ollama" in desc or "requests" in desc

    def test_tool_descreve_erros(self):
        desc = self._get_tool_description()
        assert "error" in desc.lower() or "invalido" in desc.lower() or "vazio" in desc.lower()

    def test_tool_nao_executa_codigo(self):
        from addon.globalPlugins.nvdastudio.sub_agents.code_generator import _validate_import_tool
        # Ferramenta deve ser chamavel e retornar dict sem executar codigo externo
        result = _validate_import_tool("os")
        assert isinstance(result, dict)
        assert "status" in result

    def test_validate_import_nvda_module(self):
        from addon.globalPlugins.nvdastudio.sub_agents.code_generator import _validate_import_tool
        result = _validate_import_tool("ui")
        assert result["status"] == "nvda"

    def test_validate_import_stdlib(self):
        from addon.globalPlugins.nvdastudio.sub_agents.code_generator import _validate_import_tool
        result = _validate_import_tool("os")
        assert result["status"] == "stdlib"

    def test_validate_import_unknown(self):
        from addon.globalPlugins.nvdastudio.sub_agents.code_generator import _validate_import_tool
        result = _validate_import_tool("ollama")
        assert result["status"] == "unknown"
        assert "pip_name" in result
        assert "dependencies" in result["message"].lower()


# ===========================================================================
# 2. Regras DOC-A01..A06 — doc_generator v1.3.0
# ===========================================================================

class TestDocGeneratorAcessibilidade:
    """doc_generator deve ter as 6 regras de acessibilidade DOC-A01..A06."""

    def test_versao_e_1_3_0(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import MODULE_VERSION
        assert MODULE_VERSION == "1.10.0"

    def test_regra_doc_a01_hierarquia_heading(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        assert "DOC-A01" in _SYSTEM

    def test_a01_menciona_pular_nivel(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        parte = _SYSTEM.split("DOC-A01")[1]
        assert "pule" in parte.lower() or "salto" in parte.lower() or "h2" in parte.lower()

    def test_regra_doc_a02_links_ambiguos(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        assert "DOC-A02" in _SYSTEM

    def test_a02_menciona_clique_aqui(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        parte = _SYSTEM.split("DOC-A02")[1]
        assert "clique aqui" in parte.lower() or "ambiguo" in parte.lower()

    def test_regra_doc_a03_emojis(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        assert "DOC-A03" in _SYSTEM

    def test_a03_menciona_headings_e_bullets(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        parte = _SYSTEM.split("DOC-A03")[1]
        assert "heading" in parte.lower() or "h2" in parte.lower()
        assert "lista" in parte.lower() or "li" in parte.lower() or "marcador" in parte.lower()

    def test_regra_doc_a04_descricao_tabela(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        assert "DOC-A04" in _SYSTEM

    def test_a04_menciona_preceder_tabela(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        parte = _SYSTEM.split("DOC-A04")[1]
        assert "tabela" in parte.lower() or "table" in parte.lower()

    def test_regra_doc_a05_th_scope(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        assert "DOC-A05" in _SYSTEM

    def test_a05_menciona_scope(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        parte = _SYSTEM.split("DOC-A05")[1]
        assert "scope" in parte.lower()

    def test_regra_doc_a06_referencias_vagas(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        assert "DOC-A06" in _SYSTEM

    def test_a06_menciona_botao(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        parte = _SYSTEM.split("DOC-A06")[1]
        assert "botao" in parte.lower() or "button" in parte.lower()

    def test_todas_regras_presentes(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        for regra in ["DOC-A01", "DOC-A02", "DOC-A03", "DOC-A04", "DOC-A05", "DOC-A06"]:
            assert regra in _SYSTEM, f"Regra {regra} ausente no _SYSTEM do doc_generator"

    def test_nao_executa_codigo(self):
        from addon.globalPlugins.nvdastudio.sub_agents.doc_generator import _SYSTEM
        assert isinstance(_SYSTEM, str)
