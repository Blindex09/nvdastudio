from typing import Any, Callable, Protocol


class LLMClientError(Exception):
    """Erro base da camada de integracao com qualquer cliente LLM."""
    pass


class LLMResponse:
    """
    Resposta normalizada de qualquer cliente LLM.

    Invariante: content e sempre str (nunca None).
    tool_calls: lista de tool calls retornados pelo modelo (local tool use).
    tokens_used: total de tokens consumidos nesta chamada (prompt + completion).
    """
    def __init__(
        self,
        content: str,
        model_used: str,
        reasoning: str | None = None,
        executed_tools: list | None = None,
        tool_calls: list | None = None,
        usage_breakdown: dict | None = None,
        tokens_used: int = 0,
        truncated: bool = False,
    ):
        self.content = content or ""
        self.model_used = model_used
        self.reasoning = reasoning
        self.executed_tools = executed_tools or []
        self.tool_calls = tool_calls or []
        self.usage_breakdown = usage_breakdown
        self.tokens_used = tokens_used
        # True quando o provedor reporta que a resposta foi cortada pelo
        # teto de tokens (nao terminou naturalmente) -- ver changelog 1.1.0.
        self.truncated = truncated


class LLMClientProtocol(Protocol):
    """
    Contrato estrutural satisfeito por OllamaClient e ProviderClient.

    Regra 3 (llm_factory.py): create_llm_client roteia entre clientes
    concretos por provedor, mas todo chamador so precisa de .chat() -- este
    Protocol e o tipo de retorno real da factory, em vez de `object`.
    """

    def chat(
        self,
        user_message: str,
        on_chunk: Callable[[str], None] | None = None,
        system_override: str | None = None,
        tools: list | None = None,
        tool_choice: object | None = None,
        tool_results: list | None = None,
        response_format: dict | None = None,
        reasoning_effort: str | None = None,
        step_type: str = "",
        **kwargs: Any,
    ) -> LLMResponse: ...
