import threading
import time
from dataclasses import dataclass
from typing import Optional

from .logger import get_logger

MODULE_VERSION = "1.0.0"
_logger = get_logger("evaluation")


@dataclass
class EvalMetric:
    """Metrica de uma execucao de pipeline."""
    timestamp: float
    addon_type: str  # "email", "clima", "audio", etc.
    complexity: str  # "simple", "medium", "complex"
    success: bool
    total_steps: int
    approved_steps: int
    total_retries: int
    total_tokens: int
    critic_avg_score: float
    duration_seconds: float
    had_api_key_violation: bool = False
    had_import_error: bool = False
    had_structural_issue: bool = False


@dataclass
class RegressionAlert:
    """Alerta de regressao detectada."""
    addon_type: str
    complexity: str
    previous_success_rate: float
    current_success_rate: float
    drop_percentage: float
    message: str


class EvaluationFramework:
    """
    Framework de avaliacao continua da qualidade dos addons gerados.

    Tracking:
    - Metricas por tipo de addon e complexidade
    - Deteccao de regressao (antes passava, agora falha)
    - Behavioral contracts (invariantes que nunca devem quebrar)
    """

    def __init__(self):
        self._metrics: list[EvalMetric] = []
        self._lock = threading.Lock()
        self._baseline: dict[str, dict] = {}  # (addon_type, complexity) -> metrics

    def record_pipeline_result(self, metric: Optional[EvalMetric] = None, **kwargs):
        """Registra o resultado de uma execucao de pipeline."""
        if metric is None:
            has_api_key = False
            if "issues" in kwargs:
                has_api_key = any("api_key" in str(i).lower() for i in kwargs["issues"])
            metric = EvalMetric(
                timestamp=time.time(),
                addon_type="unknown",
                complexity="complex",
                success=bool(kwargs.get("success", False)),
                total_steps=5,
                approved_steps=5 if kwargs.get("success") else 0,
                total_retries=0,
                total_tokens=int(kwargs.get("token_count", 0)),
                critic_avg_score=100.0,
                duration_seconds=float(kwargs.get("duration_seconds", 0.0)),
                had_api_key_violation=has_api_key,
            )

        with self._lock:
            self._metrics.append(metric)
            # Mantem apenas ultimas 500 metricas
            if len(self._metrics) > 500:
                self._metrics = self._metrics[-500:]

            # Atualiza baseline
            key = f"{metric.addon_type}:{metric.complexity}"
            if key not in self._baseline:
                self._baseline[key] = {"successes": 0, "total": 0, "avg_score": 0.0}
            b = self._baseline[key]
            b["total"] += 1
            if metric.success:
                b["successes"] += 1
            n = b["total"]
            b["avg_score"] = (b["avg_score"] * (n - 1) + metric.critic_avg_score) / n

    def get_success_rate(self, addon_type: str, complexity: str) -> Optional[float]:
        """Retorna taxa de sucesso para um tipo de addon e complexidade."""
        key = f"{addon_type}:{complexity}"
        b = self._baseline.get(key)
        if b is None or b["total"] == 0:
            return None
        return b["successes"] / b["total"]

    def check_regression(
        self, addon_type: str, complexity: str, threshold: float = 0.2
    ) -> Optional[RegressionAlert]:
        """
        Verifica se houve regressao na qualidade.

        Compara as ultimas 10 execucoes com o baseline historico.
        Alerta se a taxa de sucesso caiu mais que threshold (20%).
        """
        key = f"{addon_type}:{complexity}"
        baseline = self._baseline.get(key)
        if baseline is None or baseline["total"] < 10:
            return None

        # Ultimas 10 execucoes deste tipo
        recent = [
            m for m in self._metrics[-50:]
            if m.addon_type == addon_type and m.complexity == complexity
        ][-10:]

        if len(recent) < 5:
            return None

        recent_success_rate = sum(1 for m in recent if m.success) / len(recent)
        baseline_rate = baseline["successes"] / baseline["total"]
        drop = baseline_rate - recent_success_rate

        if drop > threshold:
            return RegressionAlert(
                addon_type=addon_type,
                complexity=complexity,
                previous_success_rate=baseline_rate,
                current_success_rate=recent_success_rate,
                drop_percentage=drop,
                message=(
                    f"[REGRESSAO] Addons do tipo '{addon_type}' ({complexity}) "
                    f"cairam de {baseline_rate:.0%} para {recent_success_rate:.0%} "
                    f"de taxa de sucesso (queda de {drop:.0%})."
                ),
            )

        return None

    def get_weakest_area(self) -> Optional[str]:
        """
        Identifica a area mais fraca (tipo + complexidade com menor taxa de sucesso).
        """
        weakest = None
        lowest_rate = 1.0

        for key, b in self._baseline.items():
            if b["total"] < 5:
                continue
            rate = b["successes"] / b["total"]
            if rate < lowest_rate:
                lowest_rate = rate
                weakest = key

        if weakest:
            return f"{weakest} (taxa de sucesso: {lowest_rate:.0%})"
        return None

    def get_summary(self) -> dict:
        """Retorna resumo de todas as metricas."""
        with self._lock:
            total = len(self._metrics)
            if total == 0:
                return {"total_pipelines": 0}

            successes = sum(1 for m in self._metrics if m.success)
            avg_tokens = sum(m.total_tokens for m in self._metrics) / total
            avg_duration = sum(m.duration_seconds for m in self._metrics) / total
            api_key_violations = sum(1 for m in self._metrics if m.had_api_key_violation)

            return {
                "total_pipelines": total,
                "success_rate": successes / total,
                "avg_tokens": int(avg_tokens),
                "avg_duration_seconds": int(avg_duration),
                "api_key_violations": api_key_violations,
                "weakest_area": self.get_weakest_area(),
            }

    def validate_behavioral_contracts(self, code: str) -> list[str]:
        """
        Valida contratos comportamentais (invariantes) no codigo gerado.

        Retorna lista de violacoes encontradas.
        """
        violations = []

        # Contrato 1: GlobalPlugin deve ter terminate()
        if "class GlobalPlugin" in code and "def terminate" not in code:
            violations.append("BEHAVIOR-001: GlobalPlugin sem terminate()")

        # Contrato 2: API key nunca hardcoded
        import re
        if re.search(r'(?:api_?key|API_?KEY)\s*=\s*["\'](?:AIza|sk-)', code):
            violations.append("BEHAVIOR-002: API key hardcoded")

        # Contrato 3: Sempre usar ui.message para feedback
        if "wx.MessageDialog" in code and "gui.message.MessageDialog" not in code:
            violations.append("BEHAVIOR-003: wx.MessageDialog em vez de gui.message.MessageDialog")

        # Contrato 4: Threading para I/O
        if "requests.get" in code and "threading.Thread" not in code:
            violations.append("BEHAVIOR-004: requests.get sem threading (pode travar NVDA)")

        return violations


# Alias para compatibilidade com orchestrator.py v2.1.0
class PipelineEvaluator(EvaluationFramework):
    """Alias da EvaluationFramework para wiring do orchestrator."""
    pass


# Instancia global
evaluation = EvaluationFramework()
