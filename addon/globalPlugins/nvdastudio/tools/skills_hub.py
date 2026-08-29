import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger

MODULE_VERSION = "4.0.0"
_logger = get_logger("skills_hub")

# Paths
_SKILLS_DIR = Path(__file__).parent.parent / "skills"
_REGISTRY_PATH = Path(__file__).parent.parent / "skill_registry.json"

# Cache de skills catalogadas
_skills_cache: Dict[str, "SkillMeta"] = {}
_skills_lock = threading.Lock()


@dataclass
class SkillMeta:
    """Metadata de uma skill (catalogo, nao instancia executavel)."""
    name: str
    version: str
    description: str
    toolset: str
    trust_level: str
    handler_path: str
    inputs: List[Dict[str, Any]] = field(default_factory=list)
    outputs: List[Dict[str, Any]] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    enabled: bool = True
    is_native: bool = True
    is_dispatcher: bool = False
    source: str = "nvdastudio-native"


@dataclass
class SkillSearchResult:
    """Resultado de busca no catalogo de skills."""
    skills: List[SkillMeta]
    total: int
    query: str


def _parse_skill_md(md_path: Path) -> Optional[Dict[str, Any]]:
    """Parse de arquivo SKILL.md para extrair metadata YAML frontmatter."""
    if not md_path.exists():
        return None

    content = md_path.read_text(encoding="utf-8")

    # Extrai bloco YAML entre ---
    yaml_match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not yaml_match:
        return None

    yaml_content = yaml_match.group(1)
    metadata: Dict[str, Any] = {}

    # Parse simples de YAML (flat, sem aninhamento complexo)
    current_key: Optional[str] = None
    current_list: List[Any] = []
    in_list = False

    for line in yaml_content.split('\n'):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        # Detecta inicio de lista
        if stripped.startswith('- '):
            item = stripped[2:].strip()
            # Parse inline dict: "name: value, type: str"
            if ':' in item and not item.startswith('name:') and not item.startswith('type:'):
                # Item com multiplos campos
                dict_item = {}
                for pair in item.split(','):
                    if ':' in pair:
                        k, v = pair.split(':', 1)
                        dict_item[k.strip()] = v.strip().strip('"\'')
                current_list.append(dict_item)
            elif ':' in item and (item.startswith('name:') or item.startswith('type:') or item.startswith('description:')):
                # Item YAML inline (ex: "- name: spec, type: str")
                dict_item = {}
                for pair in item.split(','):
                    if ':' in pair:
                        k, v = pair.split(':', 1)
                        dict_item[k.strip()] = v.strip().strip('"\'')
                current_list.append(dict_item)
            else:
                current_list.append(item.strip('"\''))
            in_list = True
            continue

        # Fim de lista implicito quando encontra chave nova
        if ':' in stripped and in_list:
            if current_key is not None:
                metadata[current_key] = current_list
            current_list = []
            in_list = False

        # Chave: valor
        if ':' in stripped:
            key, value = stripped.split(':', 1)
            key = key.strip()
            value = value.strip().strip('"\'')

            if value.startswith('[') and value.endswith(']'):
                # Lista inline
                items = value[1:-1].split(',')
                metadata[key] = [item.strip().strip('"\'') for item in items if item.strip()]
            elif value.lower() in ('true', 'false'):
                metadata[key] = value.lower() == 'true'
            else:
                metadata[key] = value
            current_key = key

    # Salva lista pendente
    if in_list and current_list and current_key is not None:
        metadata[current_key] = current_list

    return metadata


def _load_registry_json() -> List[SkillMeta]:
    """Carrega skills do skill_registry.json (nativas)."""
    skills: List[SkillMeta] = []

    if not _REGISTRY_PATH.exists():
        _logger.warning("[AVISO] skill_registry.json nao encontrado: %s", _REGISTRY_PATH)
        return skills

    try:
        data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8-sig"))

        for skill_data in data.get("skills", []):
            schema = skill_data.get("schema", {})
            skill = SkillMeta(
                name=skill_data.get("name", ""),
                version=skill_data.get("version", "1.0.0"),
                description=skill_data.get("description", ""),
                toolset=skill_data.get("toolset", "core"),
                trust_level=skill_data.get("trust_level", "builtin"),
                handler_path=skill_data.get("handler_path", ""),
                inputs=schema.get("inputs", []),
                outputs=schema.get("outputs", []),
                dependencies=skill_data.get("dependencies", []),
                enabled=skill_data.get("enabled", True),
                is_native=True,
                is_dispatcher=skill_data.get("is_dispatcher", False),
                source=data.get("source", "nvdastudio-native"),
            )
            skills.append(skill)

        _logger.info("[OK] Registry carregado: %d skills nativas", len(skills))

    except Exception as e:
        _logger.error("[ERRO] Falha ao carregar skill_registry.json: %s", e)

    return skills


def _scan_community_skills() -> List[SkillMeta]:
    """Scan de skills da comunidade em skills/*/SKILL.md."""
    skills: List[SkillMeta] = []

    if not _SKILLS_DIR.exists():
        return skills

    for skill_dir in _SKILLS_DIR.iterdir():
        if not skill_dir.is_dir():
            continue

        md_path = skill_dir / "SKILL.md"
        metadata = _parse_skill_md(md_path)

        if not metadata:
            continue

        # Ignora skills que ja estao no registry (nativas)
        name = metadata.get("name", skill_dir.name)

        skill = SkillMeta(
            name=name,
            version=metadata.get("version", "1.0.0"),
            description=metadata.get("description", ""),
            toolset=metadata.get("toolset", "community"),
            trust_level=metadata.get("trust_level", "community"),
            handler_path=metadata.get("handler", ""),
            inputs=metadata.get("inputs", []),
            outputs=metadata.get("outputs", []),
            dependencies=metadata.get("dependencies", []),
            enabled=metadata.get("enabled", True),
            is_native=False,
            is_dispatcher=metadata.get("is_dispatcher", False),
            source="community",
        )
        skills.append(skill)

    return skills


def refresh_skills_cache() -> Dict[str, SkillMeta]:
    """Recarrega o catalogo de skills (hot-reload de metadados)."""
    global _skills_cache

    with _skills_lock:
        _skills_cache.clear()

        # Carrega skills nativas do registry
        for skill in _load_registry_json():
            _skills_cache[skill.name] = skill

        # Carrega skills da comunidade
        for skill in _scan_community_skills():
            if skill.name not in _skills_cache:
                _skills_cache[skill.name] = skill
            else:
                _logger.warning("[AVISO] Skill duplicada ignorada: %s (nativa prevalece)", skill.name)

        _logger.info(
            "[OK] Skills catalogo atualizado: %d skills (%d nativas, %d comunidade)",
            len(_skills_cache),
            sum(1 for s in _skills_cache.values() if s.is_native),
            sum(1 for s in _skills_cache.values() if not s.is_native),
        )

        return dict(_skills_cache)


def get_skill(name: str) -> Optional[SkillMeta]:
    """Obtem metadata de uma skill por nome."""
    with _skills_lock:
        if not _skills_cache:
            refresh_skills_cache()
        return _skills_cache.get(name)


def list_skills(enabled_only: bool = False, toolset: Optional[str] = None) -> List[SkillMeta]:
    """Lista todas as skills disponiveis no catalogo."""
    with _skills_lock:
        if not _skills_cache:
            refresh_skills_cache()

        result = list(_skills_cache.values())

        if enabled_only:
            result = [s for s in result if s.enabled]

        if toolset:
            result = [s for s in result if s.toolset == toolset]

        return result


def search_skills(query: str, limit: int = 10) -> SkillSearchResult:
    """Busca skills no catalogo por substring (nome ou descricao)."""
    with _skills_lock:
        if not _skills_cache:
            refresh_skills_cache()

        query_lower = query.lower()
        matches = []

        for skill in _skills_cache.values():
            if query_lower in skill.name.lower() or query_lower in skill.description.lower():
                matches.append(skill)
                if len(matches) >= limit:
                    break

        return SkillSearchResult(skills=matches, total=len(matches), query=query)


def enable_skill(name: str) -> bool:
    """Ativa uma skill no catalogo."""
    with _skills_lock:
        if name not in _skills_cache:
            return False
        _skills_cache[name].enabled = True
        _logger.info("[SKILL] Ativada: %s", name)
        return True


def disable_skill(name: str) -> bool:
    """Desativa uma skill no catalogo."""
    with _skills_lock:
        if name not in _skills_cache:
            return False
        _skills_cache[name].enabled = False
        _logger.info("[SKILL] Desativada: %s", name)
        return True


def get_skill_definitions(tool_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Retorna definicoes de skills no formato OpenAI function schema.
    Usado pelo orchestrator para montar o prompt de tool-calling.
    """
    with _skills_lock:
        if not _skills_cache:
            refresh_skills_cache()

        result = []
        skills_to_export = tool_names if tool_names else list(_skills_cache.keys())

        for name in skills_to_export:
            skill = _skills_cache.get(name)
            if not skill or not skill.enabled:
                continue

            # Monta schema OpenAI
            properties = {}
            required = []

            for inp in skill.inputs:
                prop = {
                    "type": inp.get("type", "string"),
                    "description": inp.get("description", ""),
                }
                properties[inp.get("name", "arg")] = prop
                if inp.get("required", True):
                    required.append(inp.get("name", "arg"))

            definition = {
                "type": "function",
                "function": {
                    "name": skill.name,
                    "description": skill.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
            result.append(definition)

        return result


def get_skill_registry() -> Dict[str, Dict[str, Any]]:
    """Retorna o catalogo completo como dict serializavel."""
    with _skills_lock:
        if not _skills_cache:
            refresh_skills_cache()

        return {
            name: {
                "version": skill.version,
                "description": skill.description,
                "toolset": skill.toolset,
                "trust_level": skill.trust_level,
                "enabled": skill.enabled,
                "is_native": skill.is_native,
                "is_dispatcher": skill.is_dispatcher,
                "handler_path": skill.handler_path,
                "dependencies": skill.dependencies,
                "inputs": skill.inputs,
                "outputs": skill.outputs,
            }
            for name, skill in _skills_cache.items()
        }


# Inicializa cache na primeira importacao
refresh_skills_cache()
