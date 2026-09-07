from typing import Optional

from .llm_client import LLMClientError, LLMClientProtocol, LLMResponse
from .model_registry import ALTO_MODEL, is_alto_model, resolve_alto_model
from ..utils.logger import get_logger

MODULE_VERSION = "5.5.0"
_logger = get_logger("llm_factory")

DEFAULT_MODEL = ALTO_MODEL

class LLMFactoryError(LLMClientError):
	"""Erro da factory de cliente LLM."""
	pass


def create_llm_client(
	model_id: str = DEFAULT_MODEL,
	provider: Optional[str] = None,
) -> LLMClientProtocol:
	"""
	Cria um cliente HTTP nativo conforme o provedor configurado.

	model_id no formato "<provider>::<model_id_real>" (ex:
	"opencode_go::gpt-5.6-luna") forca esse provider, ignorando tanto o
	parametro provider= explicito quanto get_llm_provider() -- convencao
	usada exclusivamente por ai/model_router.py::select_model_and_provider()
	pra escalacao cross-provider (5.2.0).
	"""
	if "::" in model_id:
		tagged_provider, _, tagged_model = model_id.partition("::")
		if tagged_provider:
			provider = tagged_provider
			model_id = tagged_model

	if provider is None:
		from ..gui.settings_panel import get_llm_provider
		provider = get_llm_provider()

	if is_alto_model(model_id):
		model_id = resolve_alto_model(provider)

	# --- Cliente nativo Ollama Cloud (system prompt real via HTTP) ---
	if provider == "ollama":
		from ..gui.settings_panel import get_api_key
		from .ollama_client import OllamaClient, OllamaClientError, _DEFAULT_MODEL
		api_key = get_api_key(provider)
		if not api_key:
			raise LLMFactoryError(
				f"Chave API para {provider} nao configurada. "
				f"Va em NVDA > Preferencias > Configuracoes > NVDAStudio."
			)
		try:
			actual_model = model_id
			if is_alto_model(actual_model):
				actual_model = _DEFAULT_MODEL
			client: LLMClientProtocol = OllamaClient(api_key=api_key, model_id=actual_model)
			_logger.info("[OK] OllamaClient nativo. model=%s", actual_model)
			return client
		except OllamaClientError as e:
			_logger.warning("[AVISO] OllamaClient nativo falhou: %s", e)
			raise LLMFactoryError(f"Provedor {provider} indisponivel: {e}")

	# --- Cliente nativo OpenCode Go (formato classico OpenAI chat/completions) ---
	if provider == "opencode_go":
		from ..gui.settings_panel import get_api_key
		from .opencode_go_client import OpenCodeGoClient, OpenCodeGoClientError, _DEFAULT_MODEL
		api_key = get_api_key(provider)
		if not api_key:
			# Chave AUSENTE nao pode INTERROMPER a geracao. O OpenCode Go e o
			# provedor de saida estruturada (Critic/Planner), nao o provedor
			# ATIVO do usuario (que pode ser a Factory, sem chave). Marca ele
			# indisponivel -- mesma degradacao que o disjuntor de 401/429 ja
			# faz -- para que quem reconsulta get_structured_output_model caia
			# na proxima perna da cadeia (Factory) em vez de estourar um
			# dialogo de erro. resetar_saida_estruturada() no inicio de cada
			# execucao volta a tentar o OpenCode Go, entao isto nao e permanente.
			try:
				from .model_registry import marcar_saida_estruturada_indisponivel
				marcar_saida_estruturada_indisponivel(
					motivo="chave nao configurada", provider="opencode_go",
				)
			except Exception as _exc:  # pragma: no cover - defesa
				# Ação secundária (o erro real é levantado logo abaixo); mas nunca
				# engolir sem log -- regra do metodologia-verificacao-arquitetura.md.
				_logger.debug("[LLM_FACTORY] falha ao marcar opencode_go indisponivel: %s", _exc)
			raise LLMFactoryError(
				f"Chave API para {provider} nao configurada. "
				f"Va em NVDA > Preferencias > Configuracoes > NVDAStudio."
			)
		try:
			actual_model = _DEFAULT_MODEL if is_alto_model(model_id) else model_id
			client = OpenCodeGoClient(api_key=api_key, model_id=actual_model)
			_logger.info("[OK] OpenCodeGoClient nativo. model=%s", actual_model)
			return client
		except OpenCodeGoClientError as e:
			_logger.warning("[AVISO] OpenCodeGoClient nativo falhou: %s", e)
			raise LLMFactoryError(f"Provedor {provider} indisponivel: {e}")

	# --- Factory Droid (terceiro provedor, via CLI headless) ---
	#
	# Diferente dos outros: a chave e OPCIONAL. O droid tambem autentica
	# pelo login do proprio CLI (~/.factory/auth.v2.keyring), entao exigir
	# chave configurada barraria o caso comum de quem ja fez `droid` login
	# na maquina. Quando a chave existe, ela vence.
	if provider == "factory":
		from ..gui.settings_panel import get_api_key
		from .factory_client import FactoryClient, FactoryClientError, _DEFAULT_MODEL
		try:
			actual_model = _DEFAULT_MODEL if is_alto_model(model_id) else model_id
			client = FactoryClient(api_key=get_api_key(provider), model_id=actual_model)
			_logger.info("[OK] FactoryClient (droid exec). model=%s", actual_model)
			return client
		except FactoryClientError as e:
			_logger.warning("[AVISO] FactoryClient indisponivel: %s", e)
			raise LLMFactoryError(f"Provedor {provider} indisponivel: {e}")

	# --- Clientes HTTP nativos para os demais provedores ---
	from ..gui.settings_panel import get_api_key
	from .provider_client import ProviderClient, ProviderClientError
	api_key = get_api_key(provider)
	if not api_key:
		raise LLMFactoryError(
			f"Chave API para {provider} nao configurada. "
			f"Va em NVDA > Preferencias > Configuracoes > NVDAStudio."
		)
	try:
		client = ProviderClient(provider=provider, api_key=api_key, model_id=model_id)
		_logger.info("[OK] Cliente nativo. provider=%s model=%s", provider, model_id)
		return client
	except ProviderClientError as e:
		raise LLMFactoryError(f"Provedor {provider} indisponivel: {e}") from e


def get_available_backends() -> dict[str, bool]:
	"""Retorna status dos backends disponiveis."""
	return {"native": True}


def call_with_structured_output(
	user_message: str,
	response_format: dict,
	system_override: Optional[str] = None,
	reasoning_effort: Optional[str] = None,
	step_type: str = "",
) -> LLMResponse:
	"""
	Chama .chat() com response_format usando a cadeia verificada ao vivo de
	prompt caching + json_schema reais (model_registry.py::
	STRUCTURED_OUTPUT_MODEL_CHAIN). Pedido explicito do Felipe 2026-08-26:
	"nunca pode ficar sem prompt caching nem sem structured output -- se
	algum modelo que tem essas capacidades nao tiver disponivel, deve ir
	rapidamente para outro". Tenta cada modelo da cadeia em ordem; um erro
	de API (outage, 4xx/5xx -- NAO validacao de conteudo, que e
	responsabilidade de quem chama) avanca pro proximo imediatamente, sem
	retry no mesmo modelo. So levanta excecao se a cadeia INTEIRA falhar.

	Usado pelos pontos do projeto que exigem JSON garantido e nao tem
	logica de escalacao propria: clarifier.py, core/agentic_loop.py
	(arbitro do ensemble_verify), gui/studio_dialog.py, memory/
	memory_manager.py. core/planner.py e ai/critic.py tem estrategia de
	retry propria (planner: narracao ao vivo via tool call; critic: dois
	estagios com log_decision) e chamam create_llm_client() direto com
	model_registry.py::get_structured_output_model(), sem passar por aqui.
	"""
	from .model_registry import STRUCTURED_OUTPUT_MODEL_CHAIN, get_structured_output_model
	last_exc: LLMClientError | None = None
	for idx in range(len(STRUCTURED_OUTPUT_MODEL_CHAIN)):
		model_id = get_structured_output_model(idx)
		try:
			client = create_llm_client(model_id=model_id)
			return client.chat(
				user_message,
				system_override=system_override,
				response_format=response_format,
				reasoning_effort=reasoning_effort,
				step_type=step_type,
			)
		except LLMClientError as exc:
			last_exc = exc
			_logger.warning(
				"[STRUCTURED_OUTPUT] %s indisponivel (%s). Tentando proximo da cadeia.",
				model_id, exc,
			)
			continue
	raise LLMFactoryError(
		f"Toda a cadeia de structured output (OpenCode Go) esta indisponivel. Ultimo erro: {last_exc}"
	) from last_exc
