from unittest.mock import MagicMock, patch

import nvdastudio.sub_agents._base as base_mod
from nvdastudio.sub_agents._base import _run_sub_agent, _final_tool_schema, _extract_final_tool_result

_FINAL_TOOL = {
	"name": "entregar_relatorio",
	"description": "Entrega o relatorio final de auditoria.",
	"param_name": "relatorio",
	"param_description": "O relatorio completo.",
}


def _make_tool_call(args):
	tc = MagicMock()
	tc.function.name = _FINAL_TOOL["name"]
	tc.function.arguments = args
	return tc


class TestFinalToolSchema:
	def test_schema_tem_um_parametro_string_obrigatorio(self):
		schema = _final_tool_schema(_FINAL_TOOL)
		fn = schema["function"]
		assert fn["name"] == "entregar_relatorio"
		props = fn["parameters"]["properties"]
		assert "relatorio" in props
		assert props["relatorio"]["type"] == "string"
		assert fn["parameters"]["required"] == ["relatorio"]


class TestExtractFinalToolResult:
	def test_extrai_do_argumento_dict(self):
		resp = MagicMock()
		resp.tool_calls = [_make_tool_call({"relatorio": "texto limpo"})]
		assert _extract_final_tool_result(resp, _FINAL_TOOL) == "texto limpo"

	def test_extrai_do_argumento_string_json(self):
		resp = MagicMock()
		resp.tool_calls = [_make_tool_call('{"relatorio": "texto limpo"}')]
		assert _extract_final_tool_result(resp, _FINAL_TOOL) == "texto limpo"

	def test_fallback_para_content_se_nao_chamou_tool(self):
		resp = MagicMock()
		resp.tool_calls = None
		resp.content = "resposta direta sem tool call"
		assert _extract_final_tool_result(resp, _FINAL_TOOL) == "resposta direta sem tool call"

	def test_fallback_para_content_se_json_invalido(self):
		resp = MagicMock()
		resp.tool_calls = [_make_tool_call("nao e json valido")]
		resp.content = "conteudo original"
		assert _extract_final_tool_result(resp, _FINAL_TOOL) == "conteudo original"

	def test_fallback_para_content_se_campo_ausente(self):
		resp = MagicMock()
		resp.tool_calls = [_make_tool_call({"outro_campo": "x"})]
		resp.content = "conteudo original"
		assert _extract_final_tool_result(resp, _FINAL_TOOL) == "conteudo original"


class TestExtractFencedJsonFieldSemToolCallReal:
	"""
	Regressao para bug real achado ao vivo (test_e37, design_review_agent,
	gpt-oss:20b) -- quando o modelo NAO chama a tool de entrega de verdade
	mas escreve um bloco ```json {...}``` textual imitando o formato, esse
	bloco costuma REPETIR o que ja foi dito em prosa antes. O fallback antigo
	(content bruto inteiro) duplicava tudo. _base.py 1.19.0 extrai so o campo
	esperado desse JSON textual quando possivel, descartando a prosa duplicada.
	"""

	def test_extrai_campo_do_bloco_json_textual_descartando_prosa(self):
		resp = MagicMock()
		resp.tool_calls = None
		resp.content = (
			"Estou analisando o pedido...\n"
			"RESTRICOES NVDA CRITICAS:\nNVDA-022: importacoes lazy.\n\n"
			'```json\n{"relatorio": "RESTRICOES NVDA CRITICAS:\\nNVDA-022: importacoes lazy."}\n```'
		)
		result = _extract_final_tool_result(resp, _FINAL_TOOL)
		assert result == "RESTRICOES NVDA CRITICAS:\nNVDA-022: importacoes lazy."
		# a prosa solta ("Estou analisando...") NAO deve sobreviver no resultado
		assert "Estou analisando" not in result

	def test_bloco_json_sem_fence_de_linguagem_tambem_funciona(self):
		resp = MagicMock()
		resp.tool_calls = None
		resp.content = 'prosa qualquer\n```\n{"relatorio": "conteudo limpo"}\n```'
		assert _extract_final_tool_result(resp, _FINAL_TOOL) == "conteudo limpo"

	def test_bloco_json_invalido_cai_para_content_bruto(self):
		resp = MagicMock()
		resp.tool_calls = None
		resp.content = 'prosa\n```json\n{nao e json valido}\n```'
		assert _extract_final_tool_result(resp, _FINAL_TOOL) == resp.content

	def test_bloco_json_sem_o_campo_esperado_cai_para_content_bruto(self):
		resp = MagicMock()
		resp.tool_calls = None
		resp.content = 'prosa\n```json\n{"outro_campo": "x"}\n```'
		assert _extract_final_tool_result(resp, _FINAL_TOOL) == resp.content

	def test_sem_nenhum_bloco_json_cai_para_content_bruto_como_antes(self):
		resp = MagicMock()
		resp.tool_calls = None
		resp.content = "resposta direta sem qualquer bloco json"
		assert _extract_final_tool_result(resp, _FINAL_TOOL) == resp.content


class TestRunSubAgentComFinalTool:
	def _mock_client(self, tool_calls=None, content=""):
		client = MagicMock()
		resp = MagicMock()
		resp.content = content
		resp.tool_calls = tool_calls
		resp.tokens_used = 10
		client.chat.return_value = resp
		return client

	def test_liga_live_narrate_automaticamente(self):
		client = self._mock_client(tool_calls=[_make_tool_call({"relatorio": "ok"})])
		with patch.object(base_mod, "create_llm_client", return_value=client):
			_run_sub_agent("system", "prompt", "modelo-x", {}, final_tool=_FINAL_TOOL)

		system_sent = client.chat.call_args.kwargs["system_override"]
		assert "NARRACAO EM TEMPO REAL" in system_sent
		assert "entregar_relatorio" in system_sent

	def test_passa_a_tool_pro_client(self):
		client = self._mock_client(tool_calls=[_make_tool_call({"relatorio": "ok"})])
		with patch.object(base_mod, "create_llm_client", return_value=client):
			_run_sub_agent("system", "prompt", "modelo-x", {}, final_tool=_FINAL_TOOL)

		tools_sent = client.chat.call_args.kwargs["tools"]
		assert tools_sent[0]["function"]["name"] == "entregar_relatorio"

	def test_retorno_vem_do_argumento_da_tool_nao_do_content(self):
		client = self._mock_client(
			tool_calls=[_make_tool_call({"relatorio": "relatorio limpo"})],
			content="isso aqui seria narracao solta, nao deve ser retornado",
		)
		with patch.object(base_mod, "create_llm_client", return_value=client):
			result = _run_sub_agent("system", "prompt", "modelo-x", {}, final_tool=_FINAL_TOOL)

		assert result == "relatorio limpo"

	def test_sem_final_tool_comportamento_antigo_preservado(self):
		client = self._mock_client(content="resposta direta")
		with patch.object(base_mod, "create_llm_client", return_value=client):
			result = _run_sub_agent("system", "prompt", "modelo-x", {})

		assert result == "resposta direta"
		assert "tools" not in client.chat.call_args.kwargs
