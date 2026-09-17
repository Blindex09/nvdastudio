from unittest.mock import MagicMock, patch

import pytest


class TestCallWithStructuredOutputFallback:
	"""
	5.3.0: pedido explicito do Felipe 2026-08-26 -- "nunca pode ficar sem
	prompt caching nem sem structured output -- se algum modelo que tem
	essas capacidades nao tiver disponivel, deve ir rapidamente para
	outro". call_with_structured_output() tenta STRUCTURED_OUTPUT_MODEL_CHAIN
	em ordem, avancando no primeiro erro de API.
	"""

	def test_primeiro_modelo_ok_nao_tenta_os_outros(self):
		from nvdastudio.ai import llm_factory

		mock_resp = MagicMock()
		mock_resp.content = "{}"
		mock_client = MagicMock()
		mock_client.chat.return_value = mock_resp

		with patch.object(llm_factory, "create_llm_client", return_value=mock_client) as mock_create:
			result = llm_factory.call_with_structured_output("pergunta", {"type": "json_object"})

		assert result is mock_resp
		mock_create.assert_called_once_with(model_id="opencode_go::gpt-5.6-luna")

	def test_primeiro_modelo_falha_avanca_para_o_segundo(self):
		from nvdastudio.ai import llm_factory
		from nvdastudio.ai.llm_client import LLMClientError

		client_ok = MagicMock()
		client_ok.chat.return_value = MagicMock(content="{}")
		client_falho = MagicMock()
		client_falho.chat.side_effect = LLMClientError("500: fora do ar")

		def fake_create(model_id):
			return client_falho if model_id == "opencode_go::gpt-5.6-luna" else client_ok

		with patch.object(llm_factory, "create_llm_client", side_effect=fake_create):
			result = llm_factory.call_with_structured_output("pergunta", {"type": "json_object"})

		assert result is client_ok.chat.return_value

	def test_cadeia_inteira_falha_levanta_excecao_com_ultimo_erro(self):
		from nvdastudio.ai import llm_factory
		from nvdastudio.ai.llm_client import LLMClientError

		client_falho = MagicMock()
		client_falho.chat.side_effect = LLMClientError("indisponivel")

		with patch.object(llm_factory, "create_llm_client", return_value=client_falho):
			with pytest.raises(llm_factory.LLMFactoryError, match="Toda a cadeia"):
				llm_factory.call_with_structured_output("pergunta", {"type": "json_object"})

	def test_nao_tenta_modelo_ja_falho_novamente(self):
		"""Cada modelo da cadeia e tentado no maximo 1 vez -- sem retry no mesmo."""
		from nvdastudio.ai import llm_factory
		from nvdastudio.ai.llm_client import LLMClientError
		from nvdastudio.ai.model_registry import STRUCTURED_OUTPUT_MODEL_CHAIN

		client_falho = MagicMock()
		client_falho.chat.side_effect = LLMClientError("indisponivel")

		with patch.object(llm_factory, "create_llm_client", return_value=client_falho) as mock_create:
			with pytest.raises(llm_factory.LLMFactoryError):
				llm_factory.call_with_structured_output("pergunta", {"type": "json_object"})

		assert mock_create.call_count == len(STRUCTURED_OUTPUT_MODEL_CHAIN) + 1

	def test_studio_e_usado_como_ultimo_fallback_configurado(self):
		from nvdastudio.ai import llm_factory
		from nvdastudio.ai.llm_client import LLMClientError, LLMResponse
		from nvdastudio.gui import settings_panel

		failed = MagicMock()
		failed.chat.side_effect = LLMClientError("indisponivel")
		studio = MagicMock()
		studio.chat.return_value = LLMResponse("{}", "studio::modelo")

		def create(model_id):
			return studio if model_id == "studio::alto" else failed

		with (
			patch.object(settings_panel, "get_llm_provider", return_value="studio"),
			patch.object(settings_panel, "get_llm_model", return_value="alto"),
			patch.object(llm_factory, "create_llm_client", side_effect=create),
		):
			result = llm_factory.call_with_structured_output(
				"pergunta", {"type": "json_object"},
			)
		assert result.content == "{}"
		studio.chat.assert_called_once()
