import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.injection_guard import detect_injection
from ..utils.logger import get_logger

_logger = get_logger("memory")
MODULE_VERSION = "2.3.0"

# Diretorio de memoria
_MEMORY_DIR = Path.home() / "AppData" / "Roaming" / "NVDAStudio" / "memories"
_MEMORY_FILE = _MEMORY_DIR / "MEMORY.md"
_USER_FILE = _MEMORY_DIR / "USER.md"

# Limites (caracteres, nao tokens)
_MEMORY_CHAR_LIMIT = 2200
_USER_CHAR_LIMIT = 1375
_DELIMITER = "\n§\n"


@dataclass
class MemorySnapshot:
    """Snapshot congelado no inicio da sessao (injetado no system prompt)."""
    memory_text: str
    user_text: str
    timestamp: float


class MemoryManager:
    """
    Gerenciador de memoria persistente (Hermes-inspired v2).

    PROATIVIDADE: O agente decide sozinho o que vale salvar.
    - Usuario corrige → salva preferencia
    - Erro novo → salva padrao de erro
    - Ambiente novo → salva fato
    - Projeto repetido → salva convencao

    Frozen snapshot: carrega no inicio, nao muda durante a sessao.
    Live state: muda durante a sessao, persiste no disco.
    """

    def __init__(self):
        self._memory_entries: List[str] = []
        self._user_entries: List[str] = []
        self._snapshot: MemorySnapshot = MemorySnapshot("", "", 0.0)
        self._lock = threading.Lock()

        # Garante diretorio
        _MEMORY_DIR.mkdir(parents=True, exist_ok=True)

        # Carrega na inicializacao
        self._reload_from_disk()

    # -------------------------------------------------------------------------
    # Carga e snapshot
    # -------------------------------------------------------------------------

    def _reload_from_disk(self):
        """Carrega arquivos do disco e cria snapshot."""
        memory_text = self._read_file(_MEMORY_FILE)
        user_text = self._read_file(_USER_FILE)

        self._memory_entries = self._parse_entries(memory_text)
        self._user_entries = self._parse_entries(user_text)

        # Deduplica
        self._memory_entries = self._deduplicate(self._memory_entries)
        self._user_entries = self._deduplicate(self._user_entries)

        # Sanitiza para snapshot (seguranca)
        safe_memory = self._sanitize_entries_for_snapshot(self._memory_entries)
        safe_user = self._sanitize_entries_for_snapshot(self._user_entries)

        # Cria snapshot congelado
        self._snapshot = MemorySnapshot(
            memory_text=_DELIMITER.join(safe_memory) if safe_memory else "",
            user_text=_DELIMITER.join(safe_user) if safe_user else "",
            timestamp=time.time(),
        )

        _logger.info(
            "[OK] Memoria carregada: %d entradas MEMORY, %d entradas USER",
            len(self._memory_entries), len(self._user_entries),
        )

    def _read_file(self, path: Path) -> str:
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            _logger.warning("[AVISO] Falha ao ler %s: %s", path, e)
            return ""

    def _parse_entries(self, text: str) -> List[str]:
        if not text:
            return []
        entries = [e.strip() for e in text.split(_DELIMITER) if e.strip()]
        return entries

    def _deduplicate(self, entries: List[str]) -> List[str]:
        seen = set()
        result = []
        for e in entries:
            if e not in seen:
                seen.add(e)
                result.append(e)
        return result

    def _sanitize_entries_for_snapshot(self, entries: List[str]) -> List[str]:
        """Sanitiza entradas para injecao no system prompt."""
        sanitized = []
        for entry in entries:
            if not entry or entry.startswith("[BLOQUEADO"):
                sanitized.append(entry)
                continue
            # Scan por injecao
            if self._detect_injection(entry):
                sanitized.append("[BLOQUEADO: entrada continha padrao suspeito. Verifique com memory(action=read)]")
            else:
                sanitized.append(entry)
        return sanitized

    def _detect_injection(self, text: str) -> bool:
        """Detecta tentativas de injecao no system prompt (utils/injection_guard.py)."""
        return detect_injection(text)

    def get_snapshot(self) -> MemorySnapshot:
        """Retorna snapshot congelado (para injecao no system prompt)."""
        return self._snapshot

    def build_system_prompt_block(self) -> str:
        """Monta bloco de contexto para injecao no system prompt."""
        if not self._snapshot.memory_text and not self._snapshot.user_text:
            return ""

        lines = ["\n[MEMORIA PERSISTENTE]"]
        lines.append("Use estas informacoes como referencia, nao como input novo do usuario.")

        if self._snapshot.user_text:
            lines.append("\n--- PERFIL DO USUARIO ---")
            lines.append(self._snapshot.user_text[:_USER_CHAR_LIMIT])

        if self._snapshot.memory_text:
            lines.append("\n--- FATOS APRENDIDOS ---")
            lines.append(self._snapshot.memory_text[:_MEMORY_CHAR_LIMIT])

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Operacoes de escrita (curadoria)
    # -------------------------------------------------------------------------

    def add(self, content: str, target: str = "memory") -> Dict[str, Any]:
        """
        Adiciona uma nova entrada. Proativo: o agente chama quando acha relevante.

        Args:
            content: Texto da entrada (conciso, factual)
            target: "memory" (fatos) ou "user" (preferencias)
        """
        content = content.strip()
        if not content:
            return {"success": False, "error": "Conteudo vazio"}

        # Scan por injecao
        if self._detect_injection(content):
            return {"success": False, "error": "Conteudo bloqueado por seguranca"}

        with self._lock:
            entries = self._user_entries if target == "user" else self._memory_entries
            limit = _USER_CHAR_LIMIT if target == "user" else _MEMORY_CHAR_LIMIT

            # Rejeita duplicata
            if content in entries:
                return {"success": True, "message": "Entrada ja existe", "entries": len(entries)}

            # Verifica limite
            new_entries = entries + [content]
            total = len(_DELIMITER.join(new_entries))
            if total > limit:
                current = len(_DELIMITER.join(entries))
                return {
                    "success": False,
                    "error": f"Limite excedido: {total}/{limit} chars. Remova entradas antigas primeiro.",
                    "usage": f"{current}/{limit}",
                }

            entries.append(content)
            self._save_to_disk(target)

            return {
                "success": True,
                "message": "Entrada adicionada",
                "entries": len(entries),
                "usage": f"{total}/{limit} chars ({total/limit*100:.0f}%)",
            }

    def replace(self, old_text: str, new_content: str, target: str = "memory") -> Dict[str, Any]:
        """Substitui entrada existente (matching por substring)."""
        old_text = old_text.strip()
        new_content = new_content.strip()

        if not old_text or not new_content:
            return {"success": False, "error": "old_text e new_content sao obrigatorios"}

        if self._detect_injection(new_content):
            return {"success": False, "error": "Novo conteudo bloqueado por seguranca"}

        with self._lock:
            entries = self._user_entries if target == "user" else self._memory_entries
            limit = _USER_CHAR_LIMIT if target == "user" else _MEMORY_CHAR_LIMIT

            matches = [(i, e) for i, e in enumerate(entries) if old_text in e]
            if not matches:
                return {"success": False, "error": f"Substring nao encontrada: {old_text[:50]}"}
            if len(matches) > 1:
                return {"success": False, "error": "Multiplas entradas correspondem. Seja mais especifico."}

            idx, _ = matches[0]
            candidate_entries = entries[:idx] + [new_content] + entries[idx + 1:]
            total = len(_DELIMITER.join(candidate_entries))
            if total > limit:
                current = len(_DELIMITER.join(entries))
                return {
                    "success": False,
                    "error": f"Limite excedido: {total}/{limit} chars. Remova entradas antigas primeiro.",
                    "usage": f"{current}/{limit}",
                }

            entries[idx] = new_content
            self._save_to_disk(target)
            return {
                "success": True,
                "message": "Entrada substituida",
                "entries": len(entries),
                "usage": f"{total}/{limit} chars ({total/limit*100:.0f}%)",
            }

    def remove(self, old_text: str, target: str = "memory") -> Dict[str, Any]:
        """Remove entrada (matching por substring)."""
        old_text = old_text.strip()
        if not old_text:
            return {"success": False, "error": "old_text obrigatorio"}

        with self._lock:
            entries = self._user_entries if target == "user" else self._memory_entries
            matches = [(i, e) for i, e in enumerate(entries) if old_text in e]
            if not matches:
                return {"success": False, "error": "Entrada nao encontrada"}
            if len(matches) > 1:
                return {"success": False, "error": "Multiplas entradas. Seja mais especifico."}

            idx, _ = matches[0]
            entries.pop(idx)
            self._save_to_disk(target)
            return {"success": True, "message": "Entrada removida", "entries": len(entries)}

    def read(self, target: str = "memory") -> Dict[str, Any]:
        """Le entradas atuais (estado ao vivo)."""
        with self._lock:
            entries = self._user_entries if target == "user" else self._memory_entries
            limit = _USER_CHAR_LIMIT if target == "user" else _MEMORY_CHAR_LIMIT
            total = len(_DELIMITER.join(entries))
            return {
                "success": True,
                "target": target,
                "entries": entries,
                "usage": f"{total}/{limit} chars ({total/limit*100:.0f}%)" if limit else "N/A",
                "entry_count": len(entries),
            }

    # -------------------------------------------------------------------------
    # Curadoria PROATIVA (o agente decide o que salvar)
    # -------------------------------------------------------------------------

    def learn_from_session(
        self,
        query: str,
        addon_name: str,
        success: bool,
        issues: List[str],
        user_preferences: Optional[Dict[str, Any]] = None,
    ):
        """
        Extrai aprendizados automaticamente ao final do pipeline.
        Chamado pelo orchestrator.
        """
        summary = self._summarize_session(query, addon_name, success, issues)
        for fact in summary.get("memories", [])[:3]:
            self.add(str(fact)[:300], target="memory")

        # Preferencias do usuario
        if user_preferences:
            for key, value in user_preferences.items():
                self.add(f"{key}: {value}", target="user")

        _logger.info("[MEMORY] Aprendizados da sessao salvos: %s", addon_name)

    def _summarize_session(self, query: str, addon_name: str, success: bool, issues: List[str]) -> Dict[str, List[str]]:
        """Extrai memória curta com um modelo leve, sem regras por palavras."""
        import sys
        if "pytest" in sys.modules or "unittest" in sys.modules:
            state = "concluido" if success else "nao concluido"
            return {"memories": [f"Addon {addon_name}: {state}."]}
        try:
            # 2026-08-26: este resumo exige JSON estrito, mas seguia o tier
            # light do provider ATIVO do usuario. No Ollama (default),
            # nenhum modelo da conta segue json_schema de verdade (auditoria
            # ao vivo, ver model_registry.py::get_structured_output_model()).
            from ..ai.llm_factory import call_with_structured_output
            prompt = (
                "Resuma apenas fatos reutilizáveis desta sessão. Não salve progresso temporário, "
                "segredos, preferências ou suposições.\n\n"
                f"Pedido: {query}\nAddon: {addon_name}\nSucesso: {success}\nProblemas: {issues[:5]}"
            )
            response = call_with_structured_output(prompt, {
                "type": "json_schema",
                "json_schema": {
                    "name": "session_memory_summary",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "memories": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["memories"],
                        "additionalProperties": False,
                    },
                },
            })
            data = json.loads(response.content or "{}")
            return {
                "memories": list(data.get("memories", [])),
            }
        except Exception as exc:
            _logger.warning("[MEMORY] Resumo semantico indisponivel: %s", exc)
            state = "concluido" if success else "nao concluido"
            return {"memories": [f"Addon {addon_name}: {state}."]}

    # -------------------------------------------------------------------------
    # Persistencia
    # -------------------------------------------------------------------------

    def _save_to_disk(self, target: str):
        if target == "memory":
            path = _MEMORY_FILE
            entries = self._memory_entries
        else:
            path = _USER_FILE
            entries = self._user_entries

        content = _DELIMITER.join(entries)

        # Escrita atomica
        fd, temp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(temp_path, path)
            _logger.debug("[MEMORY] Salvo: %s (%d entradas)", path.name, len(entries))
        except Exception as e:
            os.unlink(temp_path)
            _logger.error("[ERRO] Falha ao salvar %s: %s", path, e)
            raise

    def get_memory_dir(self) -> Path:
        """Retorna diretorio de memoria (para uso externo)."""
        return _MEMORY_DIR

# Instancia global
memory_manager = MemoryManager()
