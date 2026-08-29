import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..utils.logger import get_logger

_logger = get_logger("trajectory_compressor")
MODULE_VERSION = "1.0.0"

# Proxy: 1 token ≈ 4 caracteres em português/código
_CHARS_PER_TOKEN = 4


@dataclass
class CompressionConfig:
    """Configuração de compressão."""
    target_max_tokens: int = 4000  # Menor que hermes (15250) — contexto NVDA é menor
    summary_target_tokens: int = 500
    protect_last_n_turns: int = 4
    protect_first_system: bool = True
    protect_first_human: bool = True
    protect_first_gpt: bool = True
    protect_first_tool: bool = True
    # Modelo para sumarização (None = usa modelo default do OllamaClient)
    summary_model: Optional[str] = None


@dataclass
class CompressionMetrics:
    """Métricas de compressão."""
    original_tokens: int = 0
    compressed_tokens: int = 0
    tokens_saved: int = 0
    turns_removed: int = 0
    was_compressed: bool = False
    still_over_limit: bool = False
    summary_length: int = 0


class TrajectoryCompressor:
    """
    Compressor de trajetória (Hermes-inspired, simplificado).

    Preserva cabeça e cauda, resume o meio via LLM.
    """

    def __init__(self, config: Optional[CompressionConfig] = None):
        self.config = config or CompressionConfig()
        self._lock = threading.Lock()

    def _estimate_tokens(self, text: str) -> int:
        """Estima tokens via proxy de caracteres."""
        return max(1, len(text) // _CHARS_PER_TOKEN)

    def _count_message_tokens(self, msg: Dict[str, Any]) -> int:
        """Conta tokens de uma mensagem."""
        content = msg.get("content", "")
        if isinstance(content, str):
            return self._estimate_tokens(content)
        return self._estimate_tokens(str(content))

    def _count_total_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Conta tokens totais da trajetória."""
        return sum(self._count_message_tokens(m) for m in messages)

    def _find_protected_indices(self, messages: List[Dict[str, Any]]) -> Tuple[set, set]:
        """
        Encontra índices protegidos (cabeça e cauda).

        Returns:
            (head_protected, tail_protected)
        """
        head = set()
        tail = set()

        # Cabeça: primeira ocorrência de cada role
        seen_roles = set()
        for i, msg in enumerate(messages):
            role = msg.get("role", "")
            if role not in seen_roles:
                if role == "system" and self.config.protect_first_system:
                    head.add(i)
                    seen_roles.add(role)
                elif role == "human" and self.config.protect_first_human:
                    head.add(i)
                    seen_roles.add(role)
                elif role == "gpt" and self.config.protect_first_gpt:
                    head.add(i)
                    seen_roles.add(role)
                elif role == "tool" and self.config.protect_first_tool:
                    head.add(i)
                    seen_roles.add(role)

        # Cauda: últimos N turnos
        n = min(self.config.protect_last_n_turns, len(messages))
        for i in range(len(messages) - n, len(messages)):
            tail.add(i)

        return head, tail

    def _extract_content_for_summary(
        self,
        messages: List[Dict[str, Any]],
        start_idx: int,
        end_idx: int,
    ) -> str:
        """Extrai conteúdo dos turnos a serem comprimidos."""
        parts = []
        for i in range(start_idx, end_idx):
            msg = messages[i]
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if isinstance(content, str):
                # Trunca se muito longo
                if len(content) > 1500:
                    content = content[:1500] + " [...]"
                parts.append(f"[{role}]: {content}")
            else:
                parts.append(f"[{role}]: {str(content)[:1500]}")

        return "\n\n".join(parts)

    def _generate_summary(self, content: str, llm_client) -> str:
        """
        Gera resumo via LLM.

        Args:
            content: Texto a ser resumido
            llm_client: Instância de OllamaClient ou similar

        Returns:
            Resumo com prefixo [CONTEXT SUMMARY]:
        """
        prompt = (
            "Resuma a seguinte sequência de ações de um assistente de programação. "
            "Inclua: ações realizadas, decisões importantes, erros encontrados e como foram resolvidos, "
            "informações-chave e nomes de arquivos/variáveis relevantes. "
            "Seja factual e conciso. Máximo 500 tokens.\n\n"
            f"{content[:8000]}\n\n"
            "[CONTEXT SUMMARY]:"
        )

        try:
            if llm_client:
                response = llm_client.chat(prompt)
                summary = (response.content or "").strip()
            else:
                # Fallback: truncamento simples
                summary = content[:2000] + " [... comprimido ...]"

            # Garante prefixo
            if not summary.startswith("[CONTEXT SUMMARY]"):
                summary = f"[CONTEXT SUMMARY]: {summary}"

            return summary

        except Exception as e:
            _logger.error("[ERRO] Falha na sumarização: %s", e)
            return (
                "[CONTEXT SUMMARY]: [Geração de resumo falhou — turnos anteriores continham "
                "chamadas de ferramenta e respostas que foram comprimidos para economizar contexto.]"
            )

    def compress(
        self,
        messages: List[Dict[str, Any]],
        llm_client=None,
    ) -> Tuple[List[Dict[str, Any]], CompressionMetrics]:
        """
        Comprime trajetória se exceder target de tokens.

        Args:
            messages: Lista de mensagens (dict com role, content)
            llm_client: Cliente LLM para sumarização (opcional)

        Returns:
            (messages_compressed, metrics)
        """
        with self._lock:
            # 1. Conta tokens
            original_tokens = self._count_total_tokens(messages)
            original_turns = len(messages)

            metrics = CompressionMetrics(
                original_tokens=original_tokens,
            )

            # 2. Se está abaixo do target, não comprime
            if original_tokens <= self.config.target_max_tokens:
                metrics.was_compressed = False
                metrics.compressed_tokens = original_tokens
                return list(messages), metrics

            _logger.info(
                "[COMPRESS] Trajetória com %d tokens (target: %d). Comprimindo...",
                original_tokens, self.config.target_max_tokens,
            )

            # 3. Encontra regiões protegidas
            head, tail = self._find_protected_indices(messages)

            # Calcula região compressível
            all_protected = head | tail
            compressible = [i for i in range(len(messages)) if i not in all_protected]

            if not compressible:
                # Nada para comprimir, mas ainda está acima do target
                metrics.was_compressed = False
                metrics.still_over_limit = True
                metrics.compressed_tokens = original_tokens
                _logger.warning("[COMPRESS] Nada para comprimir, mas acima do target")
                return list(messages), metrics

            # 4. Decide quanto comprimir
            # Precisa economizar: original - target
            # Mas o resumo também consome tokens, então comprime um pouco mais
            tokens_to_save = original_tokens - self.config.target_max_tokens
            summary_cost = self.config.summary_target_tokens
            target_saving = tokens_to_save + summary_cost + 200  # margem

            # Acumula turnos do meio até atingir economia necessária
            accumulated_tokens = 0
            compress_until_idx = len(messages)

            for idx in compressible:
                msg_tokens = self._count_message_tokens(messages[idx])
                accumulated_tokens += msg_tokens
                if accumulated_tokens >= target_saving:
                    compress_until_idx = idx + 1
                    break

            # Região a comprimir: compressible[0] até compress_until_idx
            start_idx = compressible[0]
            end_idx = compress_until_idx

            # 5. Extrai conteúdo e gera resumo
            content = self._extract_content_for_summary(messages, start_idx, end_idx)
            summary = self._generate_summary(content, llm_client)

            # 6. Reconstrói trajetória
            # Cabeça: antes de start_idx
            new_messages = []

            # Adiciona cabeça
            for i in range(start_idx):
                new_messages.append(dict(messages[i]))

            # Adiciona aviso de sumarização no system prompt (se existir)
            if new_messages and new_messages[0].get("role") == "system":
                notice = (
                    "[NOTA: Respostas anteriores podem ter sido resumidas para preservar contexto. "
                    "Referências específicas podem estar no resumo abaixo.]"
                )
                original_system = new_messages[0].get("content", "")
                new_messages[0]["content"] = original_system + "\n" + notice

            # Adiciona resumo como turno human
            new_messages.append({
                "role": "human",
                "content": summary,
            })

            # Adiciona cauda: após end_idx
            for i in range(end_idx, len(messages)):
                new_messages.append(dict(messages[i]))

            # 7. Calcula métricas
            compressed_tokens = self._count_total_tokens(new_messages)
            metrics.compressed_tokens = compressed_tokens
            metrics.tokens_saved = original_tokens - compressed_tokens
            metrics.turns_removed = original_turns - len(new_messages)
            metrics.was_compressed = True
            metrics.still_over_limit = compressed_tokens > self.config.target_max_tokens
            metrics.summary_length = len(summary)

            _logger.info(
                "[COMPRESS] %d -> %d tokens (economia: %d, turnos: %d -> %d)",
                original_tokens, compressed_tokens, metrics.tokens_saved,
                original_turns, len(new_messages),
            )

            return new_messages, metrics


# Instância global
compressor = TrajectoryCompressor()
