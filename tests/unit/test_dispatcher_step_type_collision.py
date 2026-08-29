from unittest.mock import MagicMock, patch

from nvdastudio.core.planner import STEP_AGENT_RUNNER, STEP_CODE_GENERATION


class TestDispatchStepNaoInjetaStepTypeEmReasoningParams:
	def test_reasoning_params_passado_ao_handler_nao_contem_step_type(self, fake_api_key):
		from nvdastudio.sub_agents import dispatcher

		reasoning_params_recebido = {}

		def fake_handler(prompt, model_id, reasoning_params, cache_key=None):
			reasoning_params_recebido.update(reasoning_params)
			return "output"

		with patch.object(dispatcher, "_get_builtin_handler", return_value=fake_handler):
			dispatcher.dispatch_step(
				step_type=STEP_AGENT_RUNNER, prompt="p",
				model_id="kimi-k2.7-code", reasoning_params={},
			)

		assert "step_type" not in reasoning_params_recebido, (
			"dispatch_step() nao deve injetar step_type em reasoning_params -- "
			"causava TypeError real em sub-agentes que ja passam step_type "
			"explicitamente (agent_runner_agent.py, code_generator.py)."
		)

	def test_reasoning_params_original_do_chamador_preservado_intacto(self, fake_api_key):
		"""dispatch_step() nao deve mutar nem descartar chaves legitimas
		(ex: reasoning_effort) ja presentes em reasoning_params."""
		from nvdastudio.sub_agents import dispatcher

		reasoning_params_recebido = {}

		def fake_handler(prompt, model_id, reasoning_params, cache_key=None):
			reasoning_params_recebido.update(reasoning_params)
			return "output"

		with patch.object(dispatcher, "_get_builtin_handler", return_value=fake_handler):
			dispatcher.dispatch_step(
				step_type=STEP_CODE_GENERATION, prompt="p",
				model_id="kimi-k2.7-code",
				reasoning_params={"reasoning_effort": "high"},
			)

		assert reasoning_params_recebido == {"reasoning_effort": "high"}


class TestAgentRunnerNaoColideComClientChatReal:
	"""Reproduz o crash real ponta-a-ponta: dispatch_step() -> agent_runner_agent.run()
	-> _run_sub_agent() -> client.chat(**chat_kwargs, **reasoning_params). O
	TypeError de kwarg duplicado acontece na mecanica de chamada do Python --
	reproduz com MagicMock tanto quanto com o client real."""

	def test_dispatch_step_agent_runner_nao_levanta_typeerror(self, fake_api_key):
		from nvdastudio.sub_agents import dispatcher
		from nvdastudio.ai.llm_client import LLMResponse

		mock_resp = LLMResponse(content="```python:globalPlugins/X/agent_runner.py\ncode\n```",
								 model_used="kimi-k2.7-code", tokens_used=10)
		mock_client = MagicMock()
		mock_client.chat.return_value = mock_resp

		with patch("nvdastudio.sub_agents._base.create_llm_client", return_value=mock_client), \
			patch("nvdastudio.sub_agents._base._get_cached_client", return_value=None):
			# Nao deve levantar TypeError -- antes do fix, SEMPRE levantava aqui.
			result = dispatcher.dispatch_step(
				step_type=STEP_AGENT_RUNNER, prompt="gerar agent runner",
				model_id="kimi-k2.7-code", reasoning_params={},
			)

		assert isinstance(result, str)
		mock_client.chat.assert_called_once()
		call_kwargs = mock_client.chat.call_args.kwargs
		assert call_kwargs.get("step_type") == "agent_runner"
