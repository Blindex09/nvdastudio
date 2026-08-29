import ast
import os
import pytest

_SETTINGS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "addon", "globalPlugins", "nvdastudio", "gui", "settings_panel.py"
)


def _read_settings() -> str:
    with open(_SETTINGS_PATH, encoding="utf-8") as f:
        return f.read()


class TestSettingsPanelVersao:
    def test_versao_e_4_2_0(self):
        from nvdastudio.gui.settings_panel import MODULE_VERSION
        assert MODULE_VERSION == "6.9.0"


class TestConfigSpecDeclarado:
    """
    Achado de auditoria 2026-08-04: NVDAStudio impoe a regra NVDA-015
    ("nenhum addon gerado pode usar config.conf sem declarar
    config.conf.spec") nos addons que ele mesmo gera, mas nunca declarava
    um spec pra sua propria secao "nvdastudio" -- violacao real da propria
    regra.
    """

    def test_config_spec_cobre_todas_as_chaves_dinamicas(self):
        from nvdastudio.gui.settings_panel import (
            _API_KEY_CONFIG_KEYS,
            _CONFIG_SPEC,
            CONFIG_KEY_LANGUAGE,
            CONFIG_KEY_MODEL,
            CONFIG_KEY_OUTPUT_DIR,
            CONFIG_KEY_PROVIDER,
        )
        for key in (CONFIG_KEY_PROVIDER, CONFIG_KEY_MODEL, CONFIG_KEY_OUTPUT_DIR, CONFIG_KEY_LANGUAGE):
            assert key in _CONFIG_SPEC, f"Chave '{key}' sem entrada em _CONFIG_SPEC"
        for key in _API_KEY_CONFIG_KEYS.values():
            assert key in _CONFIG_SPEC, f"Chave de API '{key}' sem entrada em _CONFIG_SPEC"

    def test_config_spec_usa_sintaxe_configobj_valida(self):
        """Cada entrada deve ser uma string no formato validate/ConfigObj
        (ex: "string(default='...')"), nao um valor Python cru."""
        from nvdastudio.gui.settings_panel import _CONFIG_SPEC
        for key, spec in _CONFIG_SPEC.items():
            assert isinstance(spec, str), f"Spec de '{key}' deve ser string, recebido {type(spec)}"
            assert spec.startswith("string("), f"Spec de '{key}' nao parece sintaxe ConfigObj: {spec!r}"

    def test_registra_no_config_conf_spec_quando_disponivel(self, monkeypatch):
        """Quando config.conf tem .spec (ConfigObj real do NVDA), o modulo
        deve registrar _CONFIG_SPEC sob CONFIG_SECTION -- forca reexecucao
        real do codigo de nivel de modulo via importlib.reload(), nao uma
        replica manual da logica (evitaria testar o caminho real)."""
        import importlib
        import sys
        from unittest.mock import MagicMock

        fake_spec_dict = {}
        fake_config = MagicMock()
        fake_config.conf.spec = fake_spec_dict
        monkeypatch.setitem(sys.modules, "config", fake_config)

        module = importlib.import_module("nvdastudio.gui.settings_panel")
        try:
            importlib.reload(module)
            assert fake_spec_dict[module.CONFIG_SECTION] == module._CONFIG_SPEC
        finally:
            # Restaura o modulo real (com o config.conf stub original do
            # conftest) pra nao vazar estado pros proximos testes.
            monkeypatch.undo()
            importlib.reload(module)


class TestOnSaveNaoValida:
    """
    onSave nao deve chamar _validate_api_key() — isso bloqueava a persistencia
    quando a rede falha (bug producao 2026-03-24).
    """

    def test_on_save_nao_chama_validate_api_key(self):
        """onSave nao deve chamar _validate_api_key como funcao — apenas documentar no docstring e ok."""
        src = _read_settings()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "onSave":
                # Verifica chamadas de funcao dentro do onSave (nao docstring)
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            assert child.func.id != "_validate_api_key", (
                                "onSave nao deve chamar _validate_api_key diretamente"
                            )
                        if isinstance(child.func, ast.Attribute):
                            assert child.func.attr != "_validate_api_key", (
                                "onSave nao deve chamar _validate_api_key via self"
                            )
                return
        pytest.fail("Metodo onSave nao encontrado em settings_panel.py")

    def test_on_save_sempre_salva_config(self):
        """onSave deve salvar output_dir no config.conf."""
        src = _read_settings()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "onSave":
                func_src = ast.get_source_segment(src, node) or ""
                assert "CONFIG_KEY_OUTPUT_DIR" in func_src or "output_dir" in func_src.lower(), (
                    "onSave deve salvar output_dir no config.conf"
                )
                return
        pytest.fail("Metodo onSave nao encontrado")

    def test_on_save_nao_tem_messagebox_de_confirmacao_chave(self):
        """onSave nao deve exibir dialogo de confirmacao para chave invalida."""
        src = _read_settings()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "onSave":
                func_src = ast.get_source_segment(src, node) or ""
                # Nao deve ter messagebox relacionado a chave invalida
                assert "Chave Invalida" not in func_src, (
                    "onSave nao deve ter dialogo 'Chave Invalida' — isso bloqueava o save"
                )
                return
        pytest.fail("Metodo onSave nao encontrado")

    def test_sem_api_key_no_save(self):
        """Apos migracao para provedores por chave propria, onSave nao deve referenciar api_key legado."""
        src = _read_settings()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "onSave":
                func_src = ast.get_source_segment(src, node) or ""
                assert "CONFIG_KEY_API_KEY" not in func_src, (
                    "onSave nao deve salvar CONFIG_KEY_API_KEY — provedores atuais usam chaves especificas"
                )
                return
        pytest.fail("Metodo onSave nao encontrado")

    def test_ollama_key_existe(self):
        """settings_panel deve ter apiKeyOllama como chave na tabela _API_KEY_CONFIG_KEYS."""
        from nvdastudio.gui.settings_panel import _API_KEY_CONFIG_KEYS
        assert _API_KEY_CONFIG_KEYS["ollama"] == "apiKeyOllama"

    def test_tavily_e_exa_key_existem(self):
        """6.7.0: chaves de busca web fallback (opcionais, nao aparecem no
        dropdown de provedor de IA)."""
        from nvdastudio.gui.settings_panel import (
            _API_KEY_CONFIG_KEYS, _API_KEY_ENV_VARS, _API_KEY_LABELS,
        )
        assert _API_KEY_CONFIG_KEYS["tavily"] == "apiKeyTavily"
        assert _API_KEY_CONFIG_KEYS["exa"] == "apiKeyExa"
        assert _API_KEY_ENV_VARS["tavily"] == "TAVILY_API_KEY"
        assert _API_KEY_ENV_VARS["exa"] == "EXA_API_KEY"
        assert "tavily" in _API_KEY_LABELS
        assert "exa" in _API_KEY_LABELS

    def test_tavily_e_exa_nao_aparecem_no_dropdown_de_provedor(self):
        """Tavily/Exa sao chaves de busca fallback, nao provedores de LLM --
        nao devem aparecer no dropdown "Provedor de IA"."""
        from nvdastudio.gui.settings_panel import _PROVIDER_CODES
        assert "tavily" not in _PROVIDER_CODES
        assert "exa" not in _PROVIDER_CODES

    def test_on_save_persiste_chaves_tavily_e_exa(self):
        """onSave deve salvar as chaves Tavily e Exa no config.conf,
        independente do provedor de IA selecionado no dropdown."""
        src = _read_settings()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "onSave":
                func_src = ast.get_source_segment(src, node) or ""
                assert "tavily_key_ctrl" in func_src, (
                    "onSave deve persistir self.tavily_key_ctrl"
                )
                assert "exa_key_ctrl" in func_src, (
                    "onSave deve persistir self.exa_key_ctrl"
                )
                return
        pytest.fail("Metodo onSave nao encontrado")

    def test_get_ollama_api_key_prefere_variavel_ambiente(self, monkeypatch):
        """O fallback via ambiente deve vencer o valor salvo em config.conf."""
        import nvdastudio.gui.settings_panel as settings_panel
        monkeypatch.setenv("OLLAMA_API_KEY", "env-key-test")
        settings_panel.config.conf[settings_panel.CONFIG_SECTION] = {
            "apiKeyOllama": "config-key-test"
        }

        assert settings_panel.get_api_key("ollama") == "env-key-test"

    def test_get_llm_model_vazio_ou_valor_invalido_retorna_alto(self):
        import nvdastudio.gui.settings_panel as settings_panel

        settings_panel.config.conf[settings_panel.CONFIG_SECTION] = {}
        assert settings_panel.get_llm_model() == "alto"

        settings_panel.config.conf[settings_panel.CONFIG_SECTION] = {
            settings_panel.CONFIG_KEY_MODEL: "modelo-fora-da-lista"
        }
        assert settings_panel.get_llm_model() == "alto"


class TestOpenCodeGoNaoESelecionavel:
    """6.9.0: OpenCode Go removido do dropdown "Provedor de IA" -- roda so
    nos bastidores como resgate automatico (model_router.py
    _OLLAMA_RESCUE_PROVIDERS) quando o Ollama Cloud nao tem uma capacidade
    nativa disponivel. Nao e mais um provider que o usuario escolhe/
    configura como principal, mas a chave continua configuravel (mesmo
    padrao ja usado por tavily/exa)."""

    def test_opencode_go_fora_do_dropdown_de_providers(self):
        import nvdastudio.gui.settings_panel as settings_panel
        codigos = [code for _, code in settings_panel._PROVIDERS]
        assert "opencode_go" not in codigos

    def test_opencode_go_fora_dos_modelos_por_provider(self):
        import nvdastudio.gui.settings_panel as settings_panel
        assert "opencode_go" not in settings_panel._MODELS_BY_PROVIDER
        assert "opencode_go" not in settings_panel._DEFAULT_MODELS

    def test_chave_opencode_go_continua_configuravel(self):
        """A chave precisa continuar existindo nos dicts de API key --
        o resgate de bastidores (gpt-5.6-luna) depende dela pra funcionar,
        mesmo sem aparecer no dropdown de provider."""
        import nvdastudio.gui.settings_panel as settings_panel
        assert "opencode_go" in settings_panel._API_KEY_CONFIG_KEYS
        assert "opencode_go" in settings_panel._API_KEY_LABELS
        assert "opencode_go" in settings_panel._API_KEY_ENV_VARS

    def test_makesettings_cria_campo_dedicado_de_chave(self):
        src = _read_settings()
        idx = src.find("def makeSettings")
        assert idx != -1
        trecho = src[idx:idx + 8000]
        assert "opencode_go_key_ctrl" in trecho

    def test_onsave_persiste_a_chave_dedicada(self):
        src = _read_settings()
        assert 'self.opencode_go_key_ctrl.GetValue().strip()' in src
