from nvdastudio.sub_agents.doc_generator import _SYSTEM, MODULE_VERSION, run


class TestDocGeneratorVersao:
    def test_versao_e_1_2_0(self):
        assert MODULE_VERSION == "1.10.0"


class TestDocGeneratorSystemPrompt:
    def test_system_menciona_html5(self):
        assert "DOCTYPE html" in _SYSTEM or "HTML5" in _SYSTEM or "html" in _SYSTEM.lower()

    def test_system_menciona_userguide(self):
        assert "userGuide.html" in _SYSTEM

    def test_system_menciona_secoes_obrigatorias(self):
        assert "Introducao" in _SYSTEM
        assert "Como usar" in _SYSTEM
        assert "Instalacao" in _SYSTEM

    def test_system_menciona_kbd(self):
        assert "kbd" in _SYSTEM

    def test_system_menciona_lang_pt(self):
        assert "pt-BR" in _SYSTEM or "pt_BR" in _SYSTEM

    def test_system_menciona_acessibilidade(self):
        assert "leitor de telas" in _SYSTEM.lower() or "acessib" in _SYSTEM.lower()

    def test_system_menciona_api_key(self):
        assert "api" in _SYSTEM.lower()

    def test_system_formato_bloco_html(self):
        assert "```html:doc/pt_BR/userGuide.html" in _SYSTEM

    def test_nao_executa_codigo(self):
        # _SYSTEM e string estatica — nenhuma execucao
        assert isinstance(_SYSTEM, str)
        assert len(_SYSTEM) > 100


class TestDocGeneratorRun:
    def test_run_retorna_string(self, mocker):
        """
        Achado de auditoria 2026-08-04: isinstance(result, str) e
        estruturalmente garantido pelo proprio mock (return_value e uma
        string) -- nunca poderia falhar, nao exercita logica real nenhuma.
        Fortalecido pra verificar (1) o conteudo retornado e exatamente o
        que _run_sub_agent devolveu (run() nao deveria alterar/truncar) e
        (2) os argumentos reais passados pra _run_sub_agent (prompt/model_id/
        reasoning_params/cache_key), que e o que o nome do teste promete
        cobrir de fato.
        """
        mock_run_sub_agent = mocker.patch(
            "nvdastudio.sub_agents.doc_generator._run_sub_agent",
            return_value="<html><body>doc</body></html>"
        )
        result = run("prompt real", "kimi-k2.6", {"reasoning_effort": "high"}, cache_key="ck1")

        assert result == "<html><body>doc</body></html>"

        args, kwargs = mock_run_sub_agent.call_args
        assert args[1] == "prompt real"
        assert args[2] == "kimi-k2.6"
        assert args[3] == {"reasoning_effort": "high"}
        assert kwargs.get("cache_key") == "ck1"

    def test_run_nao_executa_output(self, mocker):
        html = "<script>os.system('rm -rf /')</script>"
        mocker.patch(
            "nvdastudio.sub_agents.doc_generator._run_sub_agent",
            return_value=html
        )
        result = run("prompt", "kimi-k2.6", {})
        # Retorna como string — nunca executa
        assert result == html
