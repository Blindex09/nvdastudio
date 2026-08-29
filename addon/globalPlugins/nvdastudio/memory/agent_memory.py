import threading
from collections import defaultdict
from dataclasses import dataclass

from ..utils.logger import get_logger
from .relevance import rank_relevant

MODULE_VERSION = "2.0.0"
_logger = get_logger("agent_memory")

_MAX_MEMORIES_PER_AGENT = 50


@dataclass
class AgentMemoryEntry:
    """Uma entrada na memoria de um agente."""
    pattern: str         # Padrao de erro ou situacao
    fix: str             # Como foi resolvido
    success: bool        # Se a correcao funcionou
    frequency: int = 1   # Quantas vezes ocorreu
    last_seen: float = 0.0
    outcome: str = ""    # Preview do output real (steps de sucesso sem "fix" explicito)


class AgentMemory:
    """
    Memoria procedural por tipo de agente.

    Cada agente (code_generator, manifest_builder, etc.) tem seu proprio
    espaco de memoria. Isso evita que o code_generator receba dicas
    irrelevantes sobre manifestos ou documentacao.
    """

    def __init__(self):
        self._memories: dict[str, list[AgentMemoryEntry]] = defaultdict(list)
        self._lock = threading.Lock()

    def remember(self, agent_type: str, pattern: str, fix: str = "", success: bool = True, outcome: str = ""):
        """
        Registra uma experiencia na memoria do agente.

        Args:
            agent_type: Tipo do agente (code_generation, manifest_builder, etc.)
            pattern: Padrao de erro ou situacao encontrada
            fix: Como foi resolvido (ou tentativa de resolucao)
            success: Se a correcao funcionou
        """
        import time
        with self._lock:
            memories = self._memories[agent_type]

            # Verifica se ja existe entrada similar
            for entry in memories:
                if self._same_pattern(pattern, entry.pattern):
                    entry.frequency += 1
                    entry.last_seen = time.time()
                    if success:
                        entry.fix = fix  # atualiza com a correcao que funcionou
                        if outcome:
                            entry.outcome = outcome[:200]
                    return

            # Nova entrada
            memories.append(AgentMemoryEntry(
                pattern=pattern[:200],
                fix=fix[:200],
                success=success,
                last_seen=time.time(),
                outcome=outcome[:200],
            ))

            # Limita tamanho
            if len(memories) > _MAX_MEMORIES_PER_AGENT:
                # Remove menos frequentes
                memories.sort(key=lambda e: (-e.frequency, -e.last_seen))
                self._memories[agent_type] = memories[:_MAX_MEMORIES_PER_AGENT]

    def recall(
        self,
        agent_type: str,
        context: str,
        limit: int = 5,
        semantic_client=None,
    ) -> list[AgentMemoryEntry]:
        """
        Recupera memorias relevantes para um contexto.

        Args:
            agent_type: Tipo do agente
            context: Contexto atual (para matching semantico simples)
            limit: Numero maximo de memorias a retornar

        Returns:
            Lista de memorias relevantes, ordenadas por relevancia
        """
        with self._lock:
            memories = self._memories.get(agent_type, [])
            if not memories:
                return []

            candidates = [
                (
                    "\n".join(filter(None, (entry.pattern, entry.fix, entry.outcome))),
                    entry,
                )
                for entry in memories
            ]
        return rank_relevant(
            context,
            candidates,
            limit,
            client=semantic_client,
        )

    def get_common_mistakes(self, agent_type: str, limit: int = 5) -> list[str]:
        """
        Retorna os erros mais comuns de um tipo de agente.

        Util para injetar no system prompt como "EVITE estes erros".
        """
        with self._lock:
            memories = self._memories.get(agent_type, [])
            # Filtra apenas erros (success=False), ordena por frequencia
            failures = [m for m in memories if not m.success]
            failures.sort(key=lambda m: -m.frequency)
            return [f"ERRO COMUM: {m.pattern} → CORRECAO: {m.fix}" for m in failures[:limit]]

    def get_successful_patterns(self, agent_type: str, limit: int = 5) -> list[str]:
        """
        Retorna os padroes de sucesso de um tipo de agente.

        Util para injetar no system prompt como "SIGA estes padroes".
        """
        with self._lock:
            memories = self._memories.get(agent_type, [])
            successes = [m for m in memories if m.success]
            successes.sort(key=lambda m: -m.frequency)
            # fix fica vazio quando o step so teve sucesso (sem correcao explicita) --
            # nesse caso usa outcome (preview do output real) para a dica nao vir vazia.
            return [f"PADRAO: {m.pattern} → SOLUCAO: {m.fix or m.outcome}" for m in successes[:limit]]

    @staticmethod
    def _same_pattern(a: str, b: str) -> bool:
        """Deduplica somente o mesmo texto normalizado, sem matching lexical."""
        return " ".join(a.casefold().split()) == " ".join(b.casefold().split())


# Instancia global
agent_memory = AgentMemory()
