from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_prompt_response_cache_evitar_chamada_repetida():
    from nvdastudio.ai.llm_client import LLMResponse
    from nvdastudio.sub_agents import _base

    _base.clear_prompt_response_cache()
    _base.clear_client_cache()
    client = MagicMock()
    client.chat.return_value = LLMResponse(content="resultado", model_used="light", tokens_used=12)
    with patch.object(_base, "sys", SimpleNamespace(modules={})), \
         patch.object(_base, "create_llm_client", return_value=client):
        first = _base._run_sub_agent("sistema", "pedido", "light", {})
        second = _base._run_sub_agent("sistema", "pedido", "light", {})
    assert first == second == "resultado"
    assert client.chat.call_count == 1
    _base.clear_prompt_response_cache()


def test_recuperacao_semantica_usa_modelo_sem_lista_de_gatilhos():
    from nvdastudio.memory.relevance import rank_relevant

    candidates = [
        ("atalhos globais e gestos do NVDA", "atalhos"),
        ("processamento de imagens e cores", "imagens"),
        ("gestos de teclado para leitor de telas", "teclado"),
    ]
    client = MagicMock()
    client.chat.return_value = MagicMock(content='{"selected_ids":[2]}')
    result = rank_relevant(
        "comandos de teclado acessiveis", candidates, limit=1, client=client
    )
    assert result == ["teclado"]
    assert client.chat.call_count == 1
    prompt = client.chat.call_args.args[0]
    assert "significado e intenção" in prompt


def test_compressor_de_trajetoria_usa_chat_do_cliente():
    from nvdastudio.builder.trajectory_compressor import CompressionConfig, TrajectoryCompressor

    compressor = TrajectoryCompressor(CompressionConfig(
        target_max_tokens=20,
        summary_target_tokens=5,
        protect_last_n_turns=1,
        protect_first_human=False,
        protect_first_gpt=False,
    ))
    client = MagicMock()
    client.chat.return_value = MagicMock(content="Resumo das decisões.")
    messages = [
        {"role": "human", "content": "pedido inicial " * 20},
        {"role": "gpt", "content": "resposta intermediaria " * 20},
        {"role": "human", "content": "ajuste solicitado " * 20},
        {"role": "gpt", "content": "resultado recente " * 20},
    ]
    compressed, metrics = compressor.compress(messages, llm_client=client)
    assert metrics.was_compressed
    assert client.chat.called
    assert any("CONTEXT SUMMARY" in item["content"] for item in compressed)
