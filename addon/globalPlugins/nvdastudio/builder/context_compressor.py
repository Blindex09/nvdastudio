import re
import time
from dataclasses import dataclass
from typing import Dict, List

from ..utils.logger import get_logger
from ..ai.model_registry import registry as _model_registry

MODULE_VERSION = "3.0.0"
_logger = get_logger("context_compressor")

# Tamanhos de seção (baseado em atenção do LLM)
_HEAD_CHARS = 1000    # Início (máxima atenção)
_MID_CHARS = 300      # Meio (menor atenção — lost-in-middle)
_TAIL_CHARS = 600     # Final (segunda posição privilegiada)

# Fallback pra modelo desconhecido (nao esta no model_registry.py -- ex:
# glm-5.1/qwen3.5, listados so em ollama_client.py._MODEL_CAPABILITIES).
# Conservador de proposito: melhor comprimir demais um modelo desconhecido
# do que estourar a janela real por otimismo.
_DEFAULT_TOKEN_LIMIT = 32000


def _model_token_limit(model_id: str) -> int:
	"""
	Consulta o context_window real do model_registry.py (fonte unica --
	evita a tabela hardcoded separada que existia antes de v3.0.0, que
	cobria so 3 dos ~20 modelos ativos e tinha deepseek-v4-flash ERRADO
	em 64000 tokens quando a janela real e 1M, comprimindo contexto de
	forma agressiva demais sem necessidade nesse modelo havia meses).
	"""
	info = _model_registry.get_model_info(model_id)
	if info and info.context_window:
		return info.context_window
	return _DEFAULT_TOKEN_LIMIT

# Tokens por caractere (estimativa conservadora)
_TOKENS_PER_CHAR = 0.25


@dataclass
class CompressedContext:
    """Contexto comprimido com seções estruturadas."""
    decision: str        # DECISAO_PRINCIPAL
    artifacts: str       # ARTEFATOS_GERADOS
    critical_points: str # PONTOS_CRITICOS
    full_text: str       # Texto completo comprimido
    compression_ratio: float
    tokens_estimated: int


@dataclass
class CompressionFeedback:
    """Feedback do usuário sobre compressão."""
    quality_score: int  # 1-5
    missing_info: str   # O que faltou
    timestamp: str


class StreamingContextScrubber:
    """
    Scrubber de contexto em streaming.

    Remove tags de pensamento, contexto de memória e system notes
    antes de mostrar ao usuário. Inspirado no Hermes StreamingContextScrubber.
    """

    _MEMORY_CONTEXT_RE = re.compile(r'<\s*memory-context\s*>[\s\S]*?</\s*memory-context\s*>', re.IGNORECASE)
    _THINKING_RE = re.compile(r'<\s*think\s*>[\s\S]*?</\s*think\s*>', re.IGNORECASE)
    _SYSTEM_NOTE_RE = re.compile(r'\[System note:[^\]]*\]\s*', re.IGNORECASE)
    _REASONING_RE = re.compile(r'<\s*reasoning\s*>[\s\S]*?</\s*reasoning\s*>', re.IGNORECASE)

    def sanitize(self, text: str) -> str:
        """Remove tags de contexto interno e pensamento."""
        original = text
        text = self._MEMORY_CONTEXT_RE.sub('', text)
        text = self._THINKING_RE.sub('', text)
        text = self._REASONING_RE.sub('', text)
        text = self._SYSTEM_NOTE_RE.sub('', text)

        if text != original:
            _logger.debug("[SCRUBBER] Removido conteúdo interno (%d -> %d chars)", len(original), len(text))

        return text

    def sanitize_stream(self, chunks: List[str]) -> List[str]:
        """Sanitiza stream de chunks (para streaming LLM)."""
        return [self.sanitize(chunk) for chunk in chunks]


class ContextCompressor:
    """
    Compressor de contexto com preservação semântica.

    Estratégia (inspirada em Anchored Iterative Summarization):
    - DECISAO_PRINCIPAL: o que foi criado/decidido (início, máxima atenção)
    - ARTEFATOS_GERADOS: nomes de arquivo e tipo de conteúdo
    - PONTOS_CRITICOS: restrições, erros, alertas (final, segunda posição)

    Mitiga lost-in-the-middle: LLMs prestam mais atenção ao início e fim.
    """

    def __init__(self):
        self._scrubber = StreamingContextScrubber()
        self._feedback_history: List[CompressionFeedback] = []

    def compress(
        self,
        text: str,
        max_chars: int = 3000,
        model_id: str = "default",
    ) -> CompressedContext:
        """
        Comprime um texto preservando informação semântica crítica.

        Args:
            text: Texto a ser comprimido
            max_chars: Tamanho máximo do texto comprimido
            model_id: ID do modelo (para token budget)
        Returns:
            CompressedContext com seções estruturadas
        """
        start_time = time.time()

        # Sanitiza primeiro
        text = self._scrubber.sanitize(text)

        # Tenta utilizar headroom condicionalmente
        try:
            from headroom import compress as _headroom_compress
            compressed_text = _headroom_compress(text, max_tokens=int(max_chars * _TOKENS_PER_CHAR))
            elapsed_ms = int((time.time() - start_time) * 1000)
            ratio = len(compressed_text) / len(text) if text else 1.0
            _logger.info("[COMPRESS:headroom] %d -> %d chars (%.1f%%, %dms)", len(text), len(compressed_text), ratio * 100, elapsed_ms)
            return CompressedContext(
                decision=compressed_text,
                artifacts="",
                critical_points="",
                full_text=compressed_text,
                compression_ratio=ratio,
                tokens_estimated=int(len(compressed_text) * _TOKENS_PER_CHAR),
            )
        except ImportError:
            pass

        if len(text) <= max_chars:
            return CompressedContext(
                decision=text,
                artifacts="",
                critical_points="",
                full_text=text,
                compression_ratio=1.0,
                tokens_estimated=int(len(text) * _TOKENS_PER_CHAR),
            )

        # Extrai seções semânticas
        decision = self._extract_decision(text)
        artifacts = self._extract_artifacts(text)
        critical = self._extract_critical_points(text)

        # Monta texto comprimido com posicionamento estratégico
        parts = []

        # Início: DECISAO_PRINCIPAL (máxima atenção)
        if decision:
            parts.append(f"[DECISAO_PRINCIPAL]\n{decision[:_HEAD_CHARS]}")

        # Meio: ARTEFATOS (menor atenção)
        if artifacts:
            parts.append(f"[ARTEFATOS_GERADOS]\n{artifacts[:_MID_CHARS]}")

        # Final: PONTOS_CRITICOS (segunda posição privilegiada)
        if critical:
            parts.append(f"[PONTOS_CRITICOS]\n{critical[:_TAIL_CHARS]}")

        # Fallback: se não extraiu nada, usa head+tail
        if not parts:
            head = text[:_HEAD_CHARS]
            tail = text[-_TAIL_CHARS:] if len(text) > _HEAD_CHARS + 100 else ""
            parts.append(f"[INICIO]\n{head}")
            if tail:
                omitidos = len(text) - _HEAD_CHARS - _TAIL_CHARS
                parts.append(f"[... {omitidos} chars omitidos ...]")
                parts.append(f"[FINAL]\n{tail}")

        full = "\n\n".join(parts)

        # Respeita max_chars
        if len(full) > max_chars:
            full = full[:max_chars]

        compression_ratio = len(full) / len(text) if text else 1.0
        tokens_estimated = int(len(full) * _TOKENS_PER_CHAR)

        elapsed_ms = int((time.time() - start_time) * 1000)
        _logger.info(
            "[COMPRESS] %d -> %d chars (%.1f%%, %d tokens, %dms)",
            len(text), len(full), compression_ratio * 100, tokens_estimated, elapsed_ms
        )

        return CompressedContext(
            decision=decision,
            artifacts=artifacts,
            critical_points=critical,
            full_text=full,
            compression_ratio=compression_ratio,
            tokens_estimated=tokens_estimated,
        )

    def compress_for_model(
        self,
        text: str,
        model_id: str,
        current_tokens: int,
        safety_margin: float = 0.2,
    ) -> CompressedContext:
        """
        Comprime contexto respeitando token budget do modelo.

        Args:
            text: Texto a comprimir
            model_id: ID do modelo
            current_tokens: Tokens já usados no contexto
            safety_margin: Margem de segurança (0.2 = 20%)

        Returns:
            CompressedContext dentro do budget
        """
        # Calcula token budget restante
        max_tokens = _model_token_limit(model_id)
        available_tokens = int((max_tokens - current_tokens) * (1 - safety_margin))

        if available_tokens <= 0:
            _logger.warning("[COMPRESS] Sem tokens disponíveis (%d/%d)", current_tokens, max_tokens)
            return CompressedContext(
                decision="",
                artifacts="",
                critical_points="",
                full_text="[Contexto insuficiente — tokens excedidos]",
                compression_ratio=0.0,
                tokens_estimated=0,
            )

        # Converte tokens para chars
        max_chars = int(available_tokens / _TOKENS_PER_CHAR)

        return self.compress(text, max_chars=max_chars, model_id=model_id)

    def _extract_decision(self, text: str) -> str:
        """Extrai a decisão principal do texto."""
        patterns = [
            r'(?:decid[iu]|criado|gerado|implementado|definido|estabelecido)[^.]*\.',
            r'(?:o addon|o plugin|o sistema|a feature)[^.]*\.',
            r'(?:a estrutura|a arquitetura|o design)[^.]*\.',
            r'(?:concluido|finalizado|completo)[^.]*\.',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                return " ".join(matches[:5])

        # Fallback: primeiras linhas não-vazias
        lines = [line for line in text.split("\n") if line.strip()][:5]
        return "\n".join(lines)

    def _extract_artifacts(self, text: str) -> str:
        """Extrai nomes de artefatos gerados."""
        artifacts = []

        # Procura por nomes de arquivo
        file_patterns = [
            r'(?:arquivo|file|ficheiro)[:\s]*([^\s,]+\.(?:py|ini|html|md|txt|json|css|js))',
            r'(__init__\.py|manifest\.ini|userGuide\.html|settings_panel\.py)',
            r'(globalPlugins|appModules|synthDrivers|brailleDisplayDrivers)/[^\s]+',
            r'([a-zA-Z0-9_-]+\.py)',
        ]

        for pattern in file_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            artifacts.extend(matches)

        # Remove duplicatas e ordena
        unique = sorted(set(artifacts))
        return ", ".join(unique[:20]) if unique else ""

    def _extract_critical_points(self, text: str) -> str:
        """Extrai pontos críticos (erros, alertas, restrições)."""
        critical = []

        patterns = [
            r'(?:erro|error|falha|problema|issue|bug|warning|aviso|alerta|critico)[^.]*\.',
            r'(?:nao funciona|nao compila|quebra|incompativel|invalido)[^.]*\.',
            r'(?:obrigatorio|necessario|precisa|deve|exige)[^.]*\.',
            r'(?:importante|atencao|cuidado|nota)[^.]*\.',
            r'(?:restricao|limitacao|dependencia)[^.]*\.',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            critical.extend(matches)

        return "\n".join(critical[:10]) if critical else ""

    def add_feedback(self, feedback: CompressionFeedback):
        """Adiciona feedback de compressão para aprendizado."""
        self._feedback_history.append(feedback)
        _logger.info("[FEEDBACK] Compressão avaliada: %d/5", feedback.quality_score)

    def get_feedback_stats(self) -> Dict[str, float]:
        """Retorna estatísticas de feedback."""
        if not self._feedback_history:
            return {"avg_score": 0.0, "total": 0}

        avg = sum(f.quality_score for f in self._feedback_history) / len(self._feedback_history)
        return {
            "avg_score": avg,
            "total": len(self._feedback_history),
        }


# Instância global
compressor = ContextCompressor()
