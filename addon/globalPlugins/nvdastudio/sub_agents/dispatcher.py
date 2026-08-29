import importlib
from typing import Any, Callable
from ..core.planner import (
	STEP_CODE_GENERATION, STEP_MANIFEST, STEP_ACCESSIBILITY_AUDIT,
	STEP_TEST_GENERATION, STEP_WEB_RESEARCH, STEP_AGENT_TEMPLATE,
	STEP_AGENT_RUNNER, STEP_ASSEMBLY, STEP_DESIGN_REVIEW,
	STEP_DOCUMENTATION, STEP_SYNTAX_VALIDATION,
)
from ..utils.logger import get_logger
from ..tools.skills_hub import get_skill

MODULE_VERSION = "2.3.0"
_logger = get_logger("dispatcher")


# Cache de handlers importados dinamicamente
_handler_cache: dict[str, Callable[..., Any]] = {}


def _import_handler(handler_path: str) -> Callable[..., Any] | None:
    """
    Importa um handler dinamicamente a partir de um path absoluto.

    Ex: "globalPlugins.nvdastudio.sub_agents.code_generator" → função run()
    Ex: "globalPlugins.nvdastudio.tools.web_search" → função search()
    """
    if handler_path in _handler_cache:
        return _handler_cache[handler_path]

    try:
        # Quebra path: modulo.funcao
        parts = handler_path.split(".")
        module_path = ".".join(parts[:-1])
        func_name = parts[-1]

        # O registry historicamente usa globalPlugins.nvdastudio.*, que so e
        # importavel quando a raiz "addon" esta no sys.path. Nos testes e em
        # outros hosts o mesmo pacote e carregado como nvdastudio.* ou
        # addon.globalPlugins.nvdastudio.*. Para skills nativas, ancora o
        # modulo no pacote que carregou este dispatcher; skills externas
        # continuam usando o path declarado sem alteracao.
        native_marker = "nvdastudio."
        marker_idx = module_path.find(native_marker)
        if marker_idx != -1:
            native_root = __package__.rsplit(".", 1)[0]
            native_suffix = module_path[marker_idx + len(native_marker):]
            module_path = f"{native_root}.{native_suffix}" if native_suffix else native_root

        # Importa o módulo
        module = importlib.import_module(module_path)

        # Obtém a função
        handler = getattr(module, func_name, None)

        if handler is None:
            # Fallback: tenta 'run' como padrão
            handler = getattr(module, "run", None)

        if handler:
            _handler_cache[handler_path] = handler
            _logger.debug("[DISPATCH] Handler importado: %s", handler_path)

        return handler

    except Exception as e:
        _logger.error("[ERRO] Falha ao importar handler %s: %s", handler_path, e)
        return None


def _get_builtin_handler(step_type: str) -> Callable[..., Any] | None:
    """Retorna o agente nativo correspondente a um tipo conhecido."""
    from . import (
        code_generator, manifest_builder, accessibility_auditor,
        test_generator, web_researcher, agent_template_agent,
        agent_runner_agent, assembler, design_review_agent, doc_generator,
        syntax_validator,
    )

    handlers: dict[str, Callable[..., Any]] = {
        STEP_CODE_GENERATION:     code_generator.run,
        STEP_MANIFEST:            manifest_builder.run,
        STEP_ACCESSIBILITY_AUDIT: accessibility_auditor.run,
        STEP_TEST_GENERATION:     test_generator.run,
        STEP_WEB_RESEARCH:        web_researcher.run,
        STEP_AGENT_TEMPLATE:      agent_template_agent.run,
        STEP_AGENT_RUNNER:        agent_runner_agent.run,
        STEP_ASSEMBLY:            assembler.run,
        STEP_DESIGN_REVIEW:       design_review_agent.run,
        STEP_DOCUMENTATION:       doc_generator.run,
        STEP_SYNTAX_VALIDATION:   syntax_validator.run,
    }

    return handlers.get(step_type)


def dispatch_step(
	step_type: str,
	prompt: str,
	model_id: str,
	reasoning_params: dict,
	cache_key: str | None = None,
) -> str:
    """
    Roteia o step dinamicamente via skills_hub e sub-agents fixos conhecidos.

    Fluxo:
    1. Consulta skills_hub por step_type
    2. Se encontrar, importa handler dinamicamente via handler_path
    3. Se não encontrar ou falhar, usa sub-agents fixos conhecidos
    4. Se o step_type continua desconhecido, falha sem chamar outro agente
    """
    _logger.info("[DISPATCH] step_type=%s model=%s", step_type, model_id)

    # 1. Consulta skills_hub (dinâmico)
    skill = get_skill(step_type)
    handler = None

    if skill and skill.handler_path:
        handler = _import_handler(skill.handler_path)
        if handler:
            _logger.info("[DISPATCH] Skill dinâmica: %s (handler=%s)", skill.name, skill.handler_path)

    # 2. Agentes nativos conhecidos.
    if not handler:
        handler = _get_builtin_handler(step_type)
        if handler:
            _logger.info("[DISPATCH] Agente nativo: %s", step_type)

    # 3. Sem fallback generico: step desconhecido nao deve acionar outro agente.
    if not handler:
        message = (
            f"step_type sem agente especializado: {step_type}. "
            "O dispatcher nao chama code_generator como fallback generico."
        )
        _logger.error("[DISPATCH] %s", message)
        raise ValueError(message)

    # 2.3.0: injecao de step_type em reasoning_params REMOVIDA -- causava
    # TypeError real ("got multiple values for keyword argument 'step_type'")
    # nos sub-agentes que ja passam step_type explicitamente pra
    # client.chat()/_run_sub_agent() (agent_runner_agent.py, code_generator.py).
    # Nenhum sub-agente le reasoning_params["step_type"] de proposito.
    return handler(
        prompt=prompt,
        model_id=model_id,
        reasoning_params=reasoning_params,
		cache_key=cache_key,
    )


def dispatch_step_with_tokens(
	step_type: str,
	prompt: str,
	model_id: str,
	reasoning_params: dict,
	cache_key: str | None = None,
) -> tuple[str, int]:
	"""
	Roteia o step e retorna (content: str, tokens_used: int).

	cache_key identifica opcionalmente o namespace do cache local.
	"""
	from ._base import get_last_tokens
	content = dispatch_step(step_type, prompt, model_id, reasoning_params, cache_key=cache_key)
	tokens = get_last_tokens()
	return content, tokens
