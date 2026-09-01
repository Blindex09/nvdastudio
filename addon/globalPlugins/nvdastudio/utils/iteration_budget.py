import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .logger import get_logger

MODULE_VERSION = "1.5.0"
_logger = get_logger("iteration_budget")

# Custos por 1M tokens (USD) — atualizar conforme provider
_MODEL_COSTS = {
    "kimi-k2.6": {"input": 0.50, "output": 1.50},
    "deepseek-v4-flash": {"input": 0.10, "output": 0.30},
    "default": {"input": 1.00, "output": 3.00},
}

# Limites padrão
_DEFAULT_MAX_ITERATIONS = 50
_DEFAULT_TOKEN_BUDGET = 500000

# Teto de tokens por complexidade do plano (low/medium/high, decidida pela IA
# no Planner). 1.2.0 -- ate aqui existia UM teto fixo de 500 mil para tudo.
#
# Enquanto o medidor nao era alimentado em voo (corrigido em orchestrator
# 5.59.0) o numero era decorativo e ninguem notou que estava errado. Ao ligar
# o freio de verdade, o teto virou o fator limitante -- e a medicao dos 379
# relatorios mostrou que ele estava calibrado so para o caso simples:
#
#   addon simples que deu certo ..... mediana   204 mil / maximo   621 mil
#   addon COMPLEXO que deu certo .... mediana   821 mil / maximo 4,6 milhoes
#
# Ou seja: NENHUM addon complexo jamais teve sucesso dentro de 500 mil. Com o
# freio funcionando, o teto antigo transformava 'caro e as vezes funciona' em
# 'para cedo e nunca funciona' -- confirmado ao vivo em 2026-08-29, dois
# pedidos complexos mortos aos ~800 mil com 1 de 11 e 1 de 14 steps aprovados.
#
# Os valores abaixo dao folga sobre a MEDIANA real de cada classe, nao sobre o
# maximo: o objetivo e nao matar execucao que ia dar certo, sem virar cheque em
# branco para a que entrou em loop.
_TOKEN_BUDGET_BY_COMPLEXITY: dict[str, int] = {
	"low": 300_000,
	"medium": 700_000,
	"high": 1_000_000,
}
# Custo MEDIDO de uma passada aprovada, por tipo de step: mediana dos steps
# aprovados sem retentativa nos 391 relatorios E2E (n entre 3 e 132 por tipo).
# Serve para dimensionar o teto pelo plano que foi realmente aprovado, em vez de
# por uma constante por complexidade -- ver apply_plan().
_CUSTO_MEDIDO_POR_STEP: dict[str, int] = {
	"design_review":       90_000,
	"code_generation":     35_000,
	"accessibility_audit": 35_000,
	"agent_template":      29_000,
	"agent_runner":        35_000,
	"documentation":       27_000,
	"test_generation":     26_000,
	"assembly":            24_000,
	"manifest_builder":    22_000,
	"web_research":         3_000,
	"user_clarification":       0,
	"syntax_validation":        0,
}
_CUSTO_PADRAO_POR_STEP = 25_000

# Tentativas esperadas por step. Medido: code_generation e agent_runner sao os
# unicos que retentam com frequencia (produzem codigo que o Critic reprova); os
# demais passam de primeira na maioria das vezes.
_TENTATIVAS_ESPERADAS: dict[str, float] = {
	"code_generation": 2.5,
	"agent_runner":    2.5,
}
_TENTATIVAS_PADRAO = 1.4

# Teto absoluto, independente do tamanho do plano. Existe para cortar loop: o
# caso extremo dos relatorios sao 41 retentativas e 4,6 milhoes de tokens sem
# entregar nada.
#
# 1.5.0 -- recalibrado de 2 para 2,5 milhoes. O numero anterior veio da
# observacao "execucao acima de ~1,5 milhao nunca entregou", contada no
# `total_tokens` do relatorio -- que, medido em 2026-09-01, SUBESTIMA o consumo
# real em 1,14x a 1,71x, porque so soma os steps que sobreviveram ao
# replanejamento. Na unidade que o medidor usa, aquela observacao equivale a
# algo entre 1,7 e 2,5 milhoes. Manter 2 milhoes seria aplicar um limite
# calibrado numa regua e cobrado noutra.
#
# Cortar loop continua sendo feito com mais precisao pela deteccao de repeticao
# (_same_as_previous_attempt) e pelos tetos de retentativa; este numero e a
# ultima linha, nao a primeira.
_TETO_ABSOLUTO = 2_500_000

_DEFAULT_COST_BUDGET_USD = 5.00
_RATE_LIMIT_CALLS_PER_MINUTE = 60


@dataclass
class BudgetState:
    """Estado atual do budget."""
    iterations_used: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    last_iteration_time: str = ""
    rate_limit_hits: int = 0


@dataclass
class BudgetLimits:
    """Limites do budget."""
    max_iterations: int = _DEFAULT_MAX_ITERATIONS
    max_tokens: int = _DEFAULT_TOKEN_BUDGET
    max_cost_usd: float = _DEFAULT_COST_BUDGET_USD
    rate_limit_calls_per_minute: int = _RATE_LIMIT_CALLS_PER_MINUTE


@dataclass
class IterationRecord:
    """Registro de uma iteração."""
    timestamp: str
    step_type: str
    model_id: str
    tokens_used: int
    cost_usd: float
    success: bool
    latency_ms: int


class RateLimiter:
    """
    Rate limiter para chamadas de API.

    Implementa token bucket algorithm simples.
    """

    def __init__(self, calls_per_minute: int):
        self._calls_per_minute = calls_per_minute
        self._interval_seconds = 60.0 / calls_per_minute
        self._last_call_time: float = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        """
        Adquire permissão para fazer chamada.

        Returns:
            True se pode prosseguir, False se rate limited
        """
        with self._lock:
            now = time.time()
            elapsed = now - self._last_call_time

            if elapsed >= self._interval_seconds:
                self._last_call_time = now
                return True
            else:
                # Rate limited
                wait_time = self._interval_seconds - elapsed
                _logger.warning(
                    "[RATE LIMIT] Aguarde %.1fs antes da próxima chamada",
                    wait_time
                )
                return False

    def wait_if_needed(self):
        """Aguarda se necessário (blocking)."""
        while not self.acquire():
            time.sleep(0.1)


def _teto_por_complexidade(complexity: str) -> int:
    """Teto base por complexidade. Complexidade desconhecida cai em 'medium',
    nunca no teto alto: na duvida o comportamento seguro e o mais restritivo."""
    return _TOKEN_BUDGET_BY_COMPLEXITY.get(
        (complexity or "").strip().lower(),
        _TOKEN_BUDGET_BY_COMPLEXITY["medium"],
    )


class IterationBudget:
    """
    Gerenciador de budget de iterações.

    Thread-safe via lock interno.
    """

    def __init__(self, limits: Optional[BudgetLimits] = None):
        self._limits = limits or BudgetLimits()
        self._state = BudgetState()
        self._iterations: List[IterationRecord] = []
        self._lock = threading.Lock()
        self._rate_limiter = RateLimiter(self._limits.rate_limit_calls_per_minute)
        self._paused = False
        self._stopped = False

    def apply_complexity(self, complexity: str) -> int:
        """
        Ajusta o teto de tokens a complexidade do plano e devolve o valor.

        Chamado pelo orchestrator assim que o plano existe -- reset() roda
        ANTES disso (no inicio da execucao, quando ainda nao ha plano), entao
        nao teria como saber a complexidade.

        Complexidade desconhecida cai em 'medium', nunca no teto alto: na
        duvida o comportamento seguro e o mais restritivo.
        """
        with self._lock:
            teto = _teto_por_complexidade(complexity)
            self._limits.max_tokens = teto
            _logger.info(
                "[BUDGET] Teto ajustado para complexity=%s: %d tokens",
                complexity or "?", teto,
            )
            return teto

    def apply_plan(self, step_types: list[str], complexity: str) -> int:
        """
        Dimensiona o teto pelo PLANO aprovado, nao so pela complexidade.

        Motivo medido (2026-09-01): o plano real de um addon complexo tinha 27
        steps, dos quais 8 de code_generation. Somando o custo medido de UMA
        passada de cada um, o piso do plano era ~755 mil tokens -- contra um
        teto de 1 milhao. Ou seja: o orcamento so caberia se absolutamente
        nenhum step precisasse de uma segunda tentativa, o que nunca acontece.
        A execucao morreu com 18 steps sem executar, e nao por desperdicio: por
        aritmetica.

        Um teto constante nao consegue servir ao mesmo tempo um plano de 7
        steps e um de 27. Este calculo usa o custo medido por tipo e as
        tentativas esperadas por tipo, e nunca fica ABAIXO do teto por
        complexidade -- planos pequenos continuam com a folga que ja tinham.

        O teto absoluto preserva o papel de disjuntor: um plano gigante nao
        vira cheque em branco.
        """
        with self._lock:
            piso = _teto_por_complexidade(complexity)
            estimado = 0.0
            custo_codigo = 0.0
            for tipo in step_types or []:
                custo = _CUSTO_MEDIDO_POR_STEP.get(tipo, _CUSTO_PADRAO_POR_STEP)
                estimado += custo * _TENTATIVAS_ESPERADAS.get(tipo, _TENTATIVAS_PADRAO)
                if tipo in _TENTATIVAS_ESPERADAS:
                    custo_codigo += custo
            # Folga para UMA rodada de replanejamento.
            #
            # Medido em 2026-09-01 comparando o medidor do orcamento com o
            # total do relatorio, nas duas execucoes que morreram por teto:
            #
            #   AssistenteLeituraGemini   medidor 1.181.971   relatorio 1.041.202
            #   GeminiMultimodal          medidor 1.207.312   relatorio   707.841
            #
            # O relatorio so soma os steps que SOBREVIVERAM. Replanejamento
            # substitui os steps que falharam, e o que eles gastaram some da
            # conta final -- mas nao do consumo real. Estimar o teto pela soma
            # dos steps do plano ignora exatamente esse gasto, e foi por isso
            # que as duas execucoes pararam com o plano ainda pela metade.
            #
            # Replanejamento e disparado por code_generation/agent_runner
            # reprovado (_CRITICAL_STEP_TYPES), entao a folga e uma passada a
            # mais nesses steps -- mecanismo, nao numero magico.
            estimado += custo_codigo
            teto = min(_TETO_ABSOLUTO, max(piso, int(estimado)))
            self._limits.max_tokens = teto
            _logger.info(
                "[BUDGET] Teto pelo plano: %d steps, complexity=%s, "
                "estimado=%d, piso=%d -> %d tokens",
                len(step_types or []), complexity or "?", int(estimado), piso, teto,
            )
            return teto

    def reset(self):
        """Reseta budget para nova sessão."""
        with self._lock:
            self._state = BudgetState()
            self._iterations.clear()
            self._paused = False
            self._stopped = False
            # 1.2.0: o teto tambem volta ao padrao. Sem isso, uma sessao
            # anterior com complexity=high deixaria o teto alto valendo para
            # a proxima -- o singleton e de processo inteiro.
            self._limits.max_tokens = _DEFAULT_TOKEN_BUDGET
            _logger.info("[BUDGET] Resetado para nova sessão")

    def record_iteration(
        self,
        step_type: str,
        model_id: str = "",
        tokens_used: int = 0,
        success: bool = True,
        latency_ms: int = 0,
        **kwargs,  # Aceita argumentos extras (model_used, etc.)
    ):
        """Registra uma iteração."""
        with self._lock:
            # Fallback para model_used se model_id não fornecido
            if not model_id and "model_used" in kwargs:
                model_id = kwargs["model_used"]

            # Calcula custo
            cost_config = _MODEL_COSTS.get(model_id or "default", _MODEL_COSTS["default"])
            # Assume 50% input / 50% output como estimativa
            cost_usd = (tokens_used * 0.5 * cost_config["input"] + tokens_used * 0.5 * cost_config["output"]) / 1_000_000

            record = IterationRecord(
                timestamp=datetime.now().isoformat(),
                step_type=step_type,
                model_id=model_id or "unknown",
                tokens_used=tokens_used,
                cost_usd=cost_usd,
                success=success,
                latency_ms=latency_ms,
            )

            self._iterations.append(record)
            self._state.iterations_used += 1
            self._state.tokens_used += tokens_used
            self._state.cost_usd += cost_usd
            self._state.last_iteration_time = record.timestamp

            # Verifica limites
            self._check_limits()

    def _check_limits(self):
        """Verifica se algum limite foi excedido."""
        exceeded = []

        if self._state.iterations_used >= self._limits.max_iterations:
            exceeded.append(f"iterações ({self._state.iterations_used}/{self._limits.max_iterations})")
            self._stopped = True

        if self._state.tokens_used >= self._limits.max_tokens:
            exceeded.append(f"tokens ({self._state.tokens_used}/{self._limits.max_tokens})")
            self._stopped = True

        if self._state.cost_usd >= self._limits.max_cost_usd:
            exceeded.append(f"custo (${self._state.cost_usd:.2f}/${self._limits.max_cost_usd:.2f})")
            self._stopped = True

        if exceeded:
            _logger.warning(
                "[BUDGET] Limites excedidos: %s. Pipeline será parado.",
                ", ".join(exceeded)
            )

    def can_continue(self) -> tuple[bool, str]:
        """
        Verifica se pode continuar.

        Returns:
            (can_continue, reason)
        """
        with self._lock:
            if self._stopped:
                return False, "Budget excedido — pipeline parado"

            if self._paused:
                return False, "Budget pausado pelo usuário"

            if self._state.iterations_used >= self._limits.max_iterations:
                return False, f"Max iterações atingido ({self._state.iterations_used})"

            if self._state.tokens_used >= self._limits.max_tokens:
                return False, f"Budget de tokens excedido ({self._state.tokens_used})"

            if self._state.cost_usd >= self._limits.max_cost_usd:
                return False, f"Budget de custo excedido (${self._state.cost_usd:.2f})"

            return True, "OK"

    def check_rate_limit(self) -> bool:
        """
        Verifica rate limit.

        Returns:
            True se pode fazer chamada, False se rate limited
        """
        return self._rate_limiter.acquire()

    def wait_for_rate_limit(self):
        """Aguarda rate limit (blocking)."""
        self._rate_limiter.wait_if_needed()

    def pause(self):
        """Pausa budget."""
        with self._lock:
            self._paused = True
            _logger.info("[BUDGET] Pausado")

    def resume(self):
        """Retoma budget."""
        with self._lock:
            self._paused = False
            _logger.info("[BUDGET] Retomado")

    def stop(self):
        """Para budget permanentemente (até reset)."""
        with self._lock:
            self._stopped = True
            _logger.info("[BUDGET] Parado permanentemente")

    def get_state(self) -> BudgetState:
        """Retorna estado atual."""
        with self._lock:
            return BudgetState(
                iterations_used=self._state.iterations_used,
                tokens_used=self._state.tokens_used,
                cost_usd=self._state.cost_usd,
                start_time=self._state.start_time,
                last_iteration_time=self._state.last_iteration_time,
                rate_limit_hits=self._state.rate_limit_hits,
            )

    def get_limits(self) -> BudgetLimits:
        """Retorna limites."""
        return self._limits

    def get_remaining(self) -> Dict[str, Any]:
        """Retorna recursos restantes."""
        with self._lock:
            return {
                "iterations": max(0, self._limits.max_iterations - self._state.iterations_used),
                "tokens": max(0, self._limits.max_tokens - self._state.tokens_used),
                "cost_usd": max(0.0, self._limits.max_cost_usd - self._state.cost_usd),
                "percentage": {
                    "iterations": (self._state.iterations_used / self._limits.max_iterations) * 100,
                    "tokens": (self._state.tokens_used / self._limits.max_tokens) * 100,
                    "cost": (self._state.cost_usd / self._limits.max_cost_usd) * 100,
                }
            }

    def get_iteration_history(self, limit: int = 50) -> List[IterationRecord]:
        """Retorna histórico de iterações."""
        with self._lock:
            return self._iterations[-limit:]

    def get_summary(self) -> str:
        """Retorna resumo do budget."""
        remaining = self.get_remaining()
        return (
            f"Budget: {self._state.iterations_used}/{self._limits.max_iterations} iterações, "
            f"{self._state.tokens_used}/{self._limits.max_tokens} tokens, "
            f"${self._state.cost_usd:.2f}/${self._limits.max_cost_usd:.2f} — "
            f"Restante: {remaining['iterations']:.0f} iters, {remaining['tokens']:.0f} tokens, "
            f"${remaining['cost_usd']:.2f}"
        )


# Budget global para uso compartilhado
budget = IterationBudget()
