from typing import Any, List

from ..utils.logger import get_logger

_logger = get_logger("session_recap")
MODULE_VERSION = "1.1.0"


def build_session_recap(
    query: str,
    addon_name: str,
    step_results: List[Any],
    total_tokens: int,
    duration_seconds: float,
    success: bool,
) -> str:
    """
    Gera resumo da sessao (Hermes-inspired, sem LLM).

    Args:
        query: Query original do usuario
        addon_name: Nome do addon gerado
        step_results: Lista de StepResult do pipeline
        total_tokens: Total de tokens usados
        duration_seconds: Duracao total em segundos
        success: Se o pipeline teve sucesso

    Returns:
        String com resumo legivel
    """
    lines = [f"\n{'='*50}"]
    lines.append(f"Resumo da Sessao: {addon_name}")
    lines.append(f"{'='*50}\n")

    # Duracao
    mins = int(duration_seconds // 60)
    secs = int(duration_seconds % 60)
    lines.append(f"Duracao: {mins}m {secs}s")
    lines.append(f"Tokens usados: {total_tokens:,}")
    lines.append(f"Status: {'Sucesso' if success else 'Concluido com problemas'}\n")

    # Etapas
    lines.append("Etapas executadas:")
    for i, result in enumerate(step_results, 1):
        status_icon = "✓" if result.approved else "✗"
        step_name = result.step_type
        lines.append(f"  {status_icon} {i}. {step_name} (score: {result.score}/100)")
        if result.issues:
            for issue in result.issues[:2]:
                lines.append(f"    ⚠ {issue[:60]}")

    # Ferramentas usadas
    tools_used = _extract_tools(step_results)
    if tools_used:
        lines.append(f"\nTools utilizadas: {', '.join(tools_used)}")

    # Problema principal (se houver)
    failures = [r for r in step_results if not r.approved and r.issues]
    if failures:
        lines.append("\nProblemas enfrentados:")
        for f in failures[:3]:
            for issue in f.issues[:1]:
                lines.append(f"  • {issue[:80]}")

    # Aprendizados
    learnings = _extract_learnings(step_results, query)
    if learnings:
        lines.append("\nAprendizados:")
        for learning in learnings[:5]:
            lines.append(f"  • {learning}")

    lines.append(f"\n{'='*50}\n")

    return "\n".join(lines)


def _extract_tools(step_results: List[Any]) -> List[str]:
    """Extrai nomes de tools usadas nos steps."""
    tools = set()
    for result in step_results:
        # Detecta tool_calls nos resultados
        tool_calls = getattr(result, 'tool_calls', None) or []
        for tc in tool_calls:
            name = tc.get('function', {}).get('name') if isinstance(tc, dict) else str(tc)
            if name:
                tools.add(name)
    return sorted(tools)


def _extract_learnings(step_results: List[Any], query: str) -> List[str]:
    """Preserva problemas confirmados sem inferir categorias por palavras."""
    return [
        str(issue)[:160]
        for result in step_results if not result.approved
        for issue in result.issues[:2]
    ][:5]
