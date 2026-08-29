import threading
from dataclasses import dataclass, field
from typing import Optional

from ..utils.logger import get_logger

MODULE_VERSION = "1.0.0"
_logger = get_logger("prompt_optimizer")


@dataclass
class PromptVariant:
    """Uma variante de prompt em teste."""
    name: str
    system_prompt: str
    user_prompt_template: str
    metrics: dict = field(default_factory=lambda: {
        "attempts": 0,
        "approvals": 0,
        "avg_score": 0.0,
        "avg_tokens": 0,
        "avg_latency_ms": 0,
    })


@dataclass
class OptimizationResult:
    """Resultado de uma otimizacao de prompt."""
    variant_name: str
    success_rate: float
    avg_score: float
    avg_tokens: int
    recommendation: str


class PromptOptimizer:
    """
    Otimizador de prompts com A/B testing.

    Mantem um registro de variantes de prompt e suas metricas.
    Recomenda a melhor variante baseado em taxa de aprovacao e custo.
    """

    def __init__(self):
        self._variants: dict[str, PromptVariant] = {}
        self._lock = threading.Lock()
        self._init_default_variants()

    def _init_default_variants(self):
        """Inicializa variantes padrao de prompt para code_generation."""
        self._variants["default"] = PromptVariant(
            name="default",
            system_prompt="Voce e um especialista em desenvolvimento de addons NVDA.",
            user_prompt_template="{query}\n\nContexto: {context}",
        )
        self._variants["detailed"] = PromptVariant(
            name="detailed",
            system_prompt=(
                "Voce e um especialista em desenvolvimento de addons NVDA. "
                "Siga rigorosamente as regras NVDA-001 a NVDA-061. "
                "Use config.conf para configuracoes. "
                "NUNCA hardcode API keys. "
                "Sempre use threading para I/O bloqueante."
            ),
            user_prompt_template=(
                "Tarefa: {query}\n\n"
                "Contexto de steps anteriores: {context}\n\n"
                "Regras criticas:\n"
                "- API keys em config.conf, nunca hardcoded\n"
                "- Threading para I/O pesado\n"
                "- wx.CallAfter para atualizar UI\n"
                "- super().__init__() obrigatorio\n"
                "- terminate() para limpar recursos"
            ),
        )
        self._variants["concise"] = PromptVariant(
            name="concise",
            system_prompt="NVDA addon dev. Regras: config.conf, threading, wx.CallAfter, terminate().",
            user_prompt_template="{query}",
        )

    def register_variant(self, variant: PromptVariant):
        """Registra uma nova variante de prompt."""
        with self._lock:
            self._variants[variant.name] = variant
            _logger.info("[PromptOpt] Variante registrada: %s", variant.name)

    def record_result(
        self, variant_name: str, approved: bool, score: int, tokens: int, latency_ms: int
    ):
        """Registra o resultado de uma execucao com uma variante."""
        with self._lock:
            variant = self._variants.get(variant_name)
            if variant is None:
                return
            m = variant.metrics
            m["attempts"] += 1
            if approved:
                m["approvals"] += 1
            # Media movel
            n = m["attempts"]
            m["avg_score"] = (m["avg_score"] * (n - 1) + score) / n
            m["avg_tokens"] = int((m["avg_tokens"] * (n - 1) + tokens) / n)
            m["avg_latency_ms"] = int((m["avg_latency_ms"] * (n - 1) + latency_ms) / n)

    def get_best_variant(self, min_attempts: int = 5) -> Optional[OptimizationResult]:
        """
        Retorna a melhor variante baseado em taxa de aprovacao.

        So considera variantes com pelo menos min_attempts tentativas.
        """
        with self._lock:
            candidates = []
            for name, variant in self._variants.items():
                m = variant.metrics
                if m["attempts"] < min_attempts:
                    continue
                success_rate = m["approvals"] / m["attempts"] if m["attempts"] > 0 else 0
                candidates.append((success_rate, m["avg_score"], m["avg_tokens"], name, variant))

            if not candidates:
                return None

            # Ordena por success_rate desc, avg_score desc, avg_tokens asc
            candidates.sort(key=lambda x: (-x[0], -x[1], x[2]))
            best = candidates[0]

            return OptimizationResult(
                variant_name=best[3],
                success_rate=best[0],
                avg_score=best[1],
                avg_tokens=best[2],
                recommendation=(
                    f"Variante '{best[3]}' tem {best[0]:.0%} de aprovacao "
                    f"(score medio {best[1]:.0f}, ~{best[2]} tokens)."
                ),
            )

    def get_variant_prompt(self, variant_name: str, query: str, context: str = "") -> tuple[str, str]:
        """
        Retorna (system_prompt, user_prompt) para uma variante.

        Fallback para 'default' se a variante nao existir.
        """
        variant = self._variants.get(variant_name, self._variants.get("default"))
        if variant is None:
            return "", query

        user_prompt = variant.user_prompt_template.format(query=query, context=context)
        return variant.system_prompt, user_prompt

    def get_all_metrics(self) -> dict:
        """Retorna metricas de todas as variantes."""
        with self._lock:
            return {
                name: dict(variant.metrics)
                for name, variant in self._variants.items()
            }


# Instancia global
prompt_optimizer = PromptOptimizer()
