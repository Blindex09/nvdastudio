from unittest.mock import MagicMock

from nvdastudio.memory.relevance import rank_relevant


class TestRankRelevantFallbackDeterministico:
	def test_cliente_lanca_excecao_devolve_primeiros_candidatos_nao_vazio(self):
		"""Bug real: antes devolvia [] aqui. Agora devolve os candidatos
		disponiveis, ate o limite, em vez de perder o sinal inteiro."""
		client = MagicMock()
		client.chat.side_effect = Exception("[ERRO] Ollama Cloud API falhou: 429 Too Many Requests")

		candidates = [
			("sessao 1 sobre transcricao de audio", {"id": 1}),
			("sessao 2 sobre OCR", {"id": 2}),
			("sessao 3 sobre clipboard", {"id": 3}),
		]
		result = rank_relevant("crie um addon de transcricao", candidates, limit=2, client=client)

		assert result != [], "Fallback nao deveria devolver lista vazia quando ha candidatos disponiveis"
		assert result == [{"id": 1}, {"id": 2}]

	def test_respeita_o_limit_no_fallback(self):
		client = MagicMock()
		client.chat.side_effect = Exception("timeout")
		candidates = [(f"sessao {i}", {"id": i}) for i in range(10)]

		result = rank_relevant("qualquer pedido", candidates, limit=3, client=client)

		assert len(result) == 3
		assert result == [{"id": 0}, {"id": 1}, {"id": 2}]

	def test_json_invalido_tambem_cai_no_fallback_nao_vazio(self):
		"""Resposta do modelo que nao e JSON valido -- mesmo caminho de
		excecao, mesmo fallback preservando sinal."""
		client = MagicMock()
		resp = MagicMock()
		resp.content = "isso nao e json"
		client.chat.return_value = resp
		candidates = [("sessao unica", {"id": 42})]

		result = rank_relevant("pedido qualquer", candidates, limit=5, client=client)

		assert result == [{"id": 42}]

	def test_sucesso_normal_nao_afetado_pelo_fallback(self):
		"""Confirma que o caminho feliz (resposta valida do modelo)
		continua intacto -- o fallback so age em erro."""
		client = MagicMock()
		resp = MagicMock()
		resp.content = '{"selected_ids": [1]}'
		client.chat.return_value = resp
		candidates = [
			("sessao 0", {"id": 0}),
			("sessao 1 relevante", {"id": 1}),
			("sessao 2", {"id": 2}),
		]

		result = rank_relevant("pedido especifico", candidates, limit=5, client=client)

		assert result == [{"id": 1}]

	def test_sem_candidatos_fallback_tambem_vazio_legitimamente(self):
		"""Sem candidatos, [] e a resposta CORRETA (nao ha sinal nenhum pra
		preservar) -- nao confundir com o bug original."""
		client = MagicMock()
		client.chat.side_effect = Exception("erro")
		assert rank_relevant("pedido", [], limit=5, client=client) == []
