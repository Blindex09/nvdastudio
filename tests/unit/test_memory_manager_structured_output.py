import sys
from unittest.mock import MagicMock, patch


class TestSummarizeSessionUsaCadeiaVerificada:
	"""
	2.3.0: _summarize_session() exige JSON estrito, mas seguia o tier light
	do provider ATIVO do usuario -- achado real de auditoria 2026-08-26. No
	Ollama (default), nenhum modelo da conta segue json_schema de verdade.
	Agora usa call_with_structured_output() (model_registry.py::
	STRUCTURED_OUTPUT_MODEL_CHAIN), com fallback automatico na cadeia.
	"""

	def test_summarize_session_chama_com_schema_de_memories(self):
		import nvdastudio.memory.memory_manager as mm_module

		mock_resp = MagicMock()
		mock_resp.content = '{"memories": ["fato reutilizavel"]}'

		# _summarize_session() detecta "pytest"/"unittest" em sys.modules e
		# retorna cedo (sem chamar a API) -- comportamento deliberado pra
		# testes isolados. Simula um ambiente sem esses modulos pra exercitar
		# o caminho real.
		real_modules = dict(sys.modules)
		sys.modules.pop("pytest", None)
		sys.modules.pop("unittest", None)
		try:
			manager = mm_module.MemoryManager.__new__(mm_module.MemoryManager)
			with patch("nvdastudio.ai.llm_factory.call_with_structured_output", return_value=mock_resp) as mock_call:
				result = manager._summarize_session("crie um addon", "MeuAddon", True, [])
		finally:
			sys.modules.update(real_modules)

		assert result == {"memories": ["fato reutilizavel"]}
		schema = mock_call.call_args.args[1]
		assert schema["json_schema"]["name"] == "session_memory_summary"
