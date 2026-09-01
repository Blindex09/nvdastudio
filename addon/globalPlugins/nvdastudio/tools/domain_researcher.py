import json

from ..ai.llm_client import LLMClientError
from ..ai.llm_factory import create_llm_client
from ..utils.logger import get_logger, log_llm_call, log_llm_response
from ..core.orch_types import DomainContext
from .external_search import search_external, format_results_for_prompt

MODULE_VERSION = "1.5.0"
_logger = get_logger("domain_researcher")


# ---------------------------------------------------------------------------
# System prompt: o pesquisador de dominio
# ---------------------------------------------------------------------------

_DOMAIN_RESEARCH_SYSTEM = """Você é o DomainResearcher do NVDAStudio — especialista em analisar domínios de software.

Sua função: dado um pedido de addon NVDA, pesquisar e entender o DOMÍNIO do que está sendo construído.
Você NÃO gera código. Você analisa o contexto, APIs, boas práticas e requisitos de segurança.

Retorne APENAS JSON válido sem texto fora:
{
  "domain": "categoria principal (email, clima, audio, braille, leitura, automacao, etc.)",
  "description": "descrição clara do domínio em 1-2 frases",
  "apis_involved": ["API 1", "API 2"],
  "best_practices": ["boa prática 1", "boa prática 2"],
  "security_requirements": ["requisito 1", "requisito 2"],
  "architecture_patterns": ["padrão 1", "padrão 2"],
  "nvda_specific_notes": ["nota NVDA 1", "nota NVDA 2"]
}

Regras de análise de domínio:

1. IDENTIFIQUE O DOMÍNIO PRINCIPAL:
   - email → Gmail API, Outlook, IMAP, OAuth2
   - clima → OpenWeatherMap, WeatherAPI, cache, offline
   - áudio/síntese → SynthDriver, streaming, buffer, threading
   - braille → BrailleDisplayDriver, tabelas, serial/USB
   - leitura/texto → OCR, TTS, formatos de documento
   - automação → UI Automation, IAccessible, atalhos
   - internet/API → HTTP, REST, GraphQL, polling
   - produtividade → calendário, tarefas, notas
   - acessibilidade → WCAG, ARIA, contraste, navegação
   - jogo/entretenimento → áudio espacial, feedback, menus

2. APIs ENVOLVIDAS:
   - Liste APIs externas que o addon provavelmente vai usar
   - Ex: Gmail API, Google Calendar API, OpenWeatherMap, Spotify Web API
   - Se for API externa, SEMPRE inclua nota sobre autenticação (OAuth2, API key)

3. BOAS PRÁTICAS:
   - Pense em padrões específicos do domínio
   - Ex para email: "usar OAuth2 em vez de senha", "IMAP idle para notificações"
   - Ex para clima: "cache de previsão para offline", "geolocalização por IP ou GPS"
   - Ex para áudio: "buffer circular", "thread separada para síntese"

4. SEGURANÇA:
   - API keys: SEMPRE em config.conf ou variável de ambiente, NUNCA hardcoded
   - OAuth2: refresh token, escopos mínimos
   - Dados sensíveis: nunca logar, criptografar em repouso
   - Rede: HTTPS sempre, validar certificados

5. PADRÕES ARQUITETURAIS:
   - SettingsPanel: se tem API key ou configuração
   - Threading: se tem I/O bloqueante (rede, arquivo, síntese)
   - Service layer: se tem lógica complexa separada do __init__.py
   - Cache: se faz chamadas repetidas à mesma API

6. NOTAS ESPECÍFICAS NVDA:
   - SynthDriver requer: check(), speak(), pause(), cancel(), terminate()
   - BrailleDisplayDriver requer: numCells, display(), isThreadSafe
   - GlobalPlugin: __gestures dict, scripts com @script decorator
   - AppModule: escolher eventos certos, não todos
   - Tradução: _() com # Translators: comment
   - UI: wxPython acessível, ui.message() para feedback
"""

# ---------------------------------------------------------------------------
# Domain knowledge base — conhecimento estatico sobre dominios comuns
# ---------------------------------------------------------------------------

_DOMAIN_KNOWLEDGE: dict[str, dict] = {
	"email": {
		"apis": ["Gmail API (OAuth2)", "Microsoft Graph API (Outlook)", "IMAP/SMTP"],
		"security": ["OAuth2 obrigatório para Gmail/Outlook", "Nunca armazenar senha em plain text", "Refresh token com escopo mínimo"],
		"patterns": ["SettingsPanel para autenticação", "Thread separada para polling de e-mails", "Cache da última verificação"],
		"nvda_notes": ["ui.message() para notificar novos e-mails", "Atalho para ler e-mail atual", "Navegação por lista de e-mails com setas"],
	},
	"clima": {
		"apis": ["OpenWeatherMap API", "WeatherAPI.com", "Open-Meteo (gratuito, sem key)"],
		"security": ["API key em config.conf", "HTTPS para chamadas", "Cache para evitar rate limit"],
		"patterns": ["SettingsPanel para cidade e API key", "Thread para atualização periódica", "Cache com TTL (ex: 30min)"],
		"nvda_notes": ["ui.message() para anunciar previsão", "Atalho para previsão rápida", "Suporte a múltiplas cidades"],
	},
	"audio": {
		"apis": ["SynthDriver API (NVDA interno)", "winBindings.waveOut", "ctypes para DLLs de síntese"],
		"security": ["Validar input de áudio", "Buffer circular para evitar overflow", "Thread separada para síntese"],
		"patterns": ["SynthDriver com check() obrigatório", "speak() com speechSequence", "pause() e cancel() obrigatórios"],
		"nvda_notes": ["supportedNotifications: synthIndexReached + synthDoneSpeaking", "isThreadSafe=True para drivers modernos", "terminate() para limpar recursos"],
	},
	"braille": {
		"apis": ["BrailleDisplayDriver API (NVDA interno)", "Serial/USB/HID para displays", "LibLouis para tabelas de tradução"],
		"security": ["Validar dados do display", "Timeout de conexão", "Reconexão automática"],
		"patterns": ["BrailleDisplayDriver com numCells", "display() com células", "isThreadSafe e gestureMap"],
		"nvda_notes": ["Tabelas .utb em brailleTables/", "bdDetect para auto-detecção", "Terminate para desconectar"],
	},
	"leitura": {
		"apis": ["Tesseract OCR", "Windows OCR API", "Azure Cognitive Services"],
		"security": ["API key em config.conf se cloud", "Imagens processadas localmente se possível", "Não armazenar imagens sem permissão"],
		"patterns": ["Thread para OCR (bloqueante)", "Cache de resultados", "SettingsPanel para idioma e engine"],
		"nvda_notes": ["ui.message() para progresso do OCR", "Navegação por resultado com setas", "Copiar resultado para clipboard"],
	},
	"internet": {
		"apis": ["REST/GraphQL APIs", "WebSocket para tempo real", "Server-Sent Events"],
		"security": ["API key em config.conf", "HTTPS sempre", "Validar certificados SSL", "Rate limiting e backoff"],
		"patterns": ["SettingsPanel para URL/API key", "Thread para chamadas de rede", "Cache com TTL", "Tratamento de offline"],
		"nvda_notes": ["ui.message() para status de conexão", "Indicar loading durante chamadas", "Timeout com feedback ao usuário"],
	},
	"produtividade": {
		"apis": ["Google Calendar API", "Microsoft To Do/Planner", "Todoist API", "Notion API"],
		"security": ["OAuth2 para Google/Microsoft", "API key em config.conf", "Escopos mínimos"],
		"patterns": ["SettingsPanel para autenticação", "Thread para sincronização", "Cache local", "Conflito merge"],
		"nvda_notes": ["Lista navegável com setas", "Atalhos para criar/editar", "ui.message() para notificações"],
	},
	"automacao": {
		"apis": ["UI Automation", "IAccessible", "winUser para teclas", "Python subprocess"],
		"security": ["Não executar código arbitrário", "Confirmar ações destrutivas", "Validar paths"],
		"patterns": ["AppModule para apps específicos", "GlobalPlugin para atalhos globais", "Gesture map com conflitos resolvidos"],
		"nvda_notes": ["__gestures dict com descrição", "@script com description obrigatório", "ui.message() para feedback de ação"],
	},
	"acessibilidade": {
		"apis": ["WCAG 2.2 guidelines", "ARIA roles e properties", "NVDA object navigation"],
		"security": ["Não modificar DOM sem permissão", "Respeitar preferências do usuário"],
		"patterns": ["AppModule para web/navegador", "Virtual buffer para conteúdo web", "Live regions para atualizações"],
		"nvda_notes": ["browseMode para navegação web", "object navigation para elementos", "ui.message() para anunciar landmarks"],
	},

}


class DomainResearcher:
	"""
	Pesquisa o dominio do addon antes de planejar.

	Fluxo:
	1. Analisa a query do usuario para identificar o dominio
	2. Consulta a base de conhecimento estatica (_DOMAIN_KNOWLEDGE)
	3. Usa o LLM para raciocinio profundo sobre o dominio
	4. Retorna DomainContext estruturado para o Planner
	"""

	def __init__(self):
		from ..gui.settings_panel import get_llm_provider, get_llm_model
		from ..ai.model_registry import resolve_provider_tier_model
		provider = get_llm_provider()
		model = get_llm_model()
		model = resolve_provider_tier_model(provider, "light", model)
		self._client = create_llm_client(model)

	def research(self, query: str, enriched_query: str = "") -> DomainContext:
		"""
		Pesquisa o dominio do addon.

		Args:
			query: Query original do usuario
			enriched_query: Query enriquecida pelo Clarifier (opcional)

		Returns:
			DomainContext com analise completa do dominio
		"""
		_logger.info("[DomainResearcher] Iniciando pesquisa de dominio para: %s", query[:100])

		# 1. Pesquisa profunda com LLM (sem keywords ou heurísticas estáticas preliminares)
		llm_context = self._llm_research(query, enriched_query)

		# 2. Obter conhecimento estatico do dominio detectado pela IA
		domain_detected = (llm_context.domain or "geral").lower().strip()
		static_knowledge = _DOMAIN_KNOWLEDGE.get(domain_detected, {})

		# 3. Merge: conhecimento estatico + LLM
		return self._merge_context(llm_context, static_knowledge, domain_detected)

	def _llm_research(
		self, query: str, enriched_query: str
	) -> DomainContext:
		"""Pesquisa profunda com LLM sobre o dominio, com grounding real via
		Tavily/Exa quando as chaves estao configuradas (ver external_search.py)."""
		external_results = search_external(query)
		grounding_block = format_results_for_prompt(external_results)
		grounding_section = f"\n{grounding_block}" if grounding_block else ""

		user_prompt = f"""Analise o seguinte pedido de addon NVDA e pesquise o dominio:

PEDIDO DO USUARIO: {query}
{"CONTEXTO ADICIONAL: " + enriched_query if enriched_query else ""}
{grounding_section}

Com base no pedido, retorne o JSON com sua analise.
Seja ESPECIFICO para este addon — nao generico.
Pense em: quais APIs exatas este addon vai precisar? Quais boas praticas se aplicam?
Quais requisitos de seguranca sao criticos? Como isso se integra com o NVDA?"""

		try:
			log_llm_call(_logger, "domain_research", user_prompt)
			response = self._client.chat(
				user_message=user_prompt,
				system_override=_DOMAIN_RESEARCH_SYSTEM,
				response_format={"type": "json_object"},
			)
			log_llm_response(_logger, "domain_research", response.content)

			payload = json.loads(response.content)
			# research_sources vem das URLs REAIS da busca externa (deterministico,
			# nao confia no LLM reproduzir URLs certas) -- se nenhuma busca externa
			# rodou (chaves nao configuradas ou zero resultados), fica vazio em vez
			# de aceitar o que o LLM "lembra" do treinamento (achado de auditoria:
			# antes disso, research_sources era o proprio modelo inventando URLs
			# plausiveis sem nenhuma busca de verdade por tras).
			research_sources = [r["url"] for r in external_results]
			return DomainContext(
				domain=payload.get("domain", "geral"),
				description=payload.get("description", ""),
				apis_involved=payload.get("apis_involved", []),
				best_practices=payload.get("best_practices", []),
				security_requirements=payload.get("security_requirements", []),
				architecture_patterns=payload.get("architecture_patterns", []),
				nvda_specific_notes=payload.get("nvda_specific_notes", []),
				research_sources=research_sources,
				raw_research=response.content,
			)
		except (LLMClientError, json.JSONDecodeError) as e:
			_logger.warning("[DomainResearcher] LLM falhou, usando geral: %s", e)
			return DomainContext(
				domain="geral",
				description="Addon geral",
				apis_involved=[],
				best_practices=[],
				security_requirements=[],
				architecture_patterns=[],
				nvda_specific_notes=[],
				research_sources=["fallback apos erro LLM"],
			)

	def _merge_context(
		self, llm_context: DomainContext, static_knowledge: dict, domain_hint: str
	) -> DomainContext:
		"""Merge do conhecimento estatico com a pesquisa do LLM."""
		# Se o LLM retornou vazio, usa so o estatico
		if not llm_context.apis_involved and not llm_context.best_practices:
			return DomainContext(
				domain=domain_hint,
				description=f"Addon de {domain_hint}",
				apis_involved=static_knowledge.get("apis", []),
				best_practices=static_knowledge.get("patterns", []),
				security_requirements=static_knowledge.get("security", []),
				architecture_patterns=[],
				nvda_specific_notes=static_knowledge.get("nvda_notes", []),
				research_sources=["conhecimento estatico"],
			)

		# Merge: LLM tem prioridade, estatico preenche lacunas
		merged_apis = llm_context.apis_involved or static_knowledge.get("apis", [])
		merged_practices = llm_context.best_practices or static_knowledge.get("patterns", [])
		merged_security = llm_context.security_requirements or static_knowledge.get("security", [])
		merged_nvda = llm_context.nvda_specific_notes or static_knowledge.get("nvda_notes", [])

		return DomainContext(
			domain=llm_context.domain or domain_hint,
			description=llm_context.description or f"Addon de {domain_hint}",
			apis_involved=merged_apis,
			best_practices=merged_practices,
			security_requirements=merged_security,
			architecture_patterns=llm_context.architecture_patterns or [],
			nvda_specific_notes=merged_nvda,
			research_sources=llm_context.research_sources or ["conhecimento estatico + LLM"],
			raw_research=llm_context.raw_research,
		)
