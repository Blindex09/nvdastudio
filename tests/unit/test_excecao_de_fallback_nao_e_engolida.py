"""Regressao do commit 5862750 (fix(observabilidade)).

Quatro `try/except: pass` em llm_factory e opencode_go_client engoliam a
excecao do fallback sem log nenhum -- debugar uma falha ali era impossivel.
A regra do projeto (metodologia-verificacao-arquitetura.md, README "Logs
devem ... permanecer uteis para diagnostico") exige que o fallback continue
sendo fallback (nao propaga) MAS deixe rastro. Estes testes travam os dois
lados: nao propaga E loga.
"""

from unittest.mock import MagicMock, patch

import pytest


def _model_registry_quebrado():
	"""marcar_saida_estruturada_indisponivel que estoura, simulando o
	registry indisponivel no momento do fallback."""
	return patch(
		"nvdastudio.ai.model_registry.marcar_saida_estruturada_indisponivel",
		side_effect=RuntimeError("registry indisponivel"),
	)


class TestLLMFactoryChaveAusente:
	def test_falha_ao_marcar_indisponivel_nao_mascara_erro_real_e_e_logada(self):
		from nvdastudio.ai import llm_factory

		fake_logger = MagicMock()
		with (
			patch("nvdastudio.gui.settings_panel.get_api_key", return_value=""),
			_model_registry_quebrado(),
			patch.object(llm_factory, "_logger", fake_logger),
		):
			with pytest.raises(llm_factory.LLMFactoryError, match="nao configurada"):
				llm_factory.create_llm_client(model_id="opencode_go::gpt-5.6-luna")

		# O erro que o usuario ve continua sendo "chave nao configurada"
		# (o RuntimeError do fallback nao vazou), e a falha do fallback ficou
		# registrada com a excecao original.
		assert fake_logger.debug.called
		msg, *args = fake_logger.debug.call_args.args
		assert "[LLM_FACTORY]" in msg
		assert any(isinstance(a, RuntimeError) for a in args)


class TestOpenCodeGoSinalizarContaIndisponivel:
	def test_falha_no_registry_nao_propaga_e_e_logada(self):
		from nvdastudio.ai import opencode_go_client

		resp = MagicMock()
		resp.status_code = 429
		resp.text = "rate limited"

		fake_logger = MagicMock()
		with _model_registry_quebrado(), patch.object(opencode_go_client, "_logger", fake_logger):
			# Nao pode levantar: e um sinalizador secundario, o erro HTTP
			# real e tratado por quem chamou.
			opencode_go_client._sinalizar_conta_indisponivel(resp)

		assert fake_logger.debug.called
		msg, *args = fake_logger.debug.call_args.args
		assert "[OPENCODE_GO]" in msg
		assert any(isinstance(a, RuntimeError) for a in args)
