from unittest.mock import MagicMock, patch

from nvdastudio.sub_agents.code_generator import run


def _fake_tool_call(name="ferramenta_desconhecida"):
    tc = MagicMock()
    tc.id = "call-1"
    tc.function.name = name
    tc.function.arguments = "{}"
    return tc


class TestToolRoundsEsgotados:
    def test_tool_calls_pendentes_apos_rounds_vira_erro_explicito(self):
        """Modelo insiste em tool_calls com nome desconhecido -> tool_results
        fica vazio -> loop quebra cedo -> resp.tool_calls continua truthy."""
        resp = MagicMock()
        resp.content = ""
        resp.tool_calls = [_fake_tool_call()]
        resp.tokens_used = 10

        fake_client = MagicMock()
        fake_client.chat.return_value = resp

        with patch("nvdastudio.sub_agents.code_generator.create_llm_client", return_value=fake_client):
            resultado = run("crie um addon", "kimi-k2.7-code", {})

        assert resultado.startswith("[ERRO]")
        assert "ferramenta" in resultado.lower() or "final" in resultado.lower()

    def test_conteudo_vazio_sem_tool_calls_vira_erro_explicito(self):
        """Modelo nao pede mais tools mas devolve content vazio -- nao pode
        virar 'codigo' vazio silencioso."""
        resp = MagicMock()
        resp.content = ""
        resp.tool_calls = []
        resp.tokens_used = 5

        fake_client = MagicMock()
        fake_client.chat.return_value = resp

        with patch("nvdastudio.sub_agents.code_generator.create_llm_client", return_value=fake_client):
            resultado = run("crie um addon", "kimi-k2.7-code", {})

        assert resultado.startswith("[ERRO]")

    def test_conteudo_valido_sem_tool_calls_nao_vira_erro(self):
        """Caminho feliz: sem tool_calls, conteudo nao vazio -- nao deve
        acionar nenhum dos novos caminhos de erro."""
        resp = MagicMock()
        resp.content = "```python:globalPlugins/Foo/__init__.py\nimport globalPluginHandler\n```"
        resp.tool_calls = []
        resp.tokens_used = 20
        resp.truncated = False

        fake_client = MagicMock()
        fake_client.chat.return_value = resp

        with patch("nvdastudio.sub_agents.code_generator.create_llm_client", return_value=fake_client):
            resultado = run("crie um addon", "kimi-k2.7-code", {})

        assert not resultado.startswith("[ERRO]")
        assert "globalPluginHandler" in resultado


class TestRespostaTruncadaPeloTetoDeTokens:
	"""Achado CRITICO de auditoria full-stack 2026-08-04 (rastreamento de
	geracao de addons grandes/complexos): quando a resposta e cortada pelo
	teto de tokens no meio de um arquivo, extract_code_blocks() descarta o
	bloco sem fechamento silenciosamente -- sem erro, sem retry, pipeline
	reportava sucesso com arquivo faltando/quebrado. resp.truncated agora
	vira [ERRO] explicito, entrando no retry/escalonamento normal."""

	def test_resp_truncated_vira_erro_explicito(self):
		resp = MagicMock()
		resp.content = "```python:globalPlugins/Foo/__init__.py\nimport globalPluginHandler\ndef metodo_incomp"
		resp.tool_calls = []
		resp.tokens_used = 48000
		resp.truncated = True

		fake_client = MagicMock()
		fake_client.chat.return_value = resp

		with patch("nvdastudio.sub_agents.code_generator.create_llm_client", return_value=fake_client):
			resultado = run("crie um addon grande com varias features", "kimi-k2.7-code", {})

		assert resultado.startswith("[ERRO]")
		assert "token" in resultado.lower()

	def test_resp_nao_truncated_nao_vira_erro(self):
		resp = MagicMock()
		resp.content = "```python:globalPlugins/Foo/__init__.py\nimport globalPluginHandler\n```"
		resp.tool_calls = []
		resp.tokens_used = 20
		resp.truncated = False

		fake_client = MagicMock()
		fake_client.chat.return_value = resp

		with patch("nvdastudio.sub_agents.code_generator.create_llm_client", return_value=fake_client):
			resultado = run("crie um addon", "kimi-k2.7-code", {})

		assert not resultado.startswith("[ERRO]")
