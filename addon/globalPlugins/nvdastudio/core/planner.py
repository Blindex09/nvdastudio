import json
import math
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, cast

from ..ai.llm_client import LLMClientError
from ..ai.llm_factory import create_llm_client
from ..ai.model_registry import ALTO_MODEL, get_provider_step_models, is_alto_model, resolve_provider_tier_model
from ..builder.nvda_context import NVDA_DOC_TOPICS
from ..sub_agents._base import _TOOL_PREAMBLE_INSTRUCTION, _FINAL_TOOL_INSTRUCTION
from ..utils.logger import get_logger, log_llm_call, log_llm_response, log_decision
from ..utils.engineering_principles import ENGINEERING_PLANNING_PROMPT_TEXT

MODULE_VERSION = "2.38.0"
_logger = get_logger("planner")

PLANNER_MODEL = "alto"

# Tipos de step que o planner pode gerar
STEP_CODE_GENERATION    = "code_generation"       # gera codigo Python do addon
STEP_MANIFEST           = "manifest_builder"      # gera manifest.ini
STEP_ACCESSIBILITY_AUDIT= "accessibility_audit"   # audita acessibilidade
STEP_TEST_GENERATION    = "test_generation"       # gera testes
STEP_WEB_RESEARCH       = "web_research"          # pesquisa web via WebResearcher
STEP_AGENT_TEMPLATE     = "agent_template"        # gera template MD agente
STEP_AGENT_RUNNER       = "agent_runner"          # gera AgentRunner embutido
STEP_ASSEMBLY           = "assembly"              # monta artefatos finais
STEP_DESIGN_REVIEW      = "design_review"         # revisao Challenger+Guardian (complexity=high)
STEP_DOCUMENTATION      = "documentation"         # gera userGuide.html acessivel para usuario final
STEP_USER_CLARIFICATION = "user_clarification"    # pausa pipeline e pergunta ao usuario
STEP_SYNTAX_VALIDATION  = "syntax_validation"     # valida sintaxe Python via code_interpreter (E2B)
STEP_ENGINEERING_REVIEW = "engineering_review"    # julga ENGENHARIA do codigo gerado (nao regra NVDA)

_DEFAULT_MODEL = "alto"

# Limites de contexto por subtarefa. Evitam que uma única chamada de
# code_generation tente implementar um mini-projeto inteiro de uma vez.
_MAX_CODE_STEP_DESCRIPTION_CHARS = 1800
_MAX_CODE_STEP_USER_MESSAGE_CHARS = 7000
# Quantos arquivos um unico code_generation pode produzir.
#
# 2 e deliberado, nao 1: um servico e o seu __init__.py de subpacote saem
# naturalmente juntos, e forcar 1 arquivo por step criaria steps triviais
# demais (um __init__.py vazio nao merece uma rodada de LLM). Acima de 2 o
# custo medido explode -- ver comentario em ExecutionStep.target_files.
_MAX_FILES_POR_CODE_STEP = 2




# Diretorios que o NVDA carrega por convencao. Fonte unica compartilhada com
# core/orchestrator.py::_missing_loadable_entry_point() -- se as duas listas
# divergirem, o planner declara um layout que o portao final recusa.
NVDA_ENTRY_POINT_DIRS: tuple[str, ...] = (
	"globalPlugins",
	"appModules",
	"synthDrivers",
	"brailleDisplayDrivers",
	"visionEnhancementProviders",
)


def _declara_ponto_de_entrada(arquivos: list[str]) -> bool:
	"""True se a lista ja contem um arquivo que o NVDA carregaria."""
	for caminho in arquivos:
		partes = caminho.split("/")
		if len(partes) < 2 or partes[0] not in NVDA_ENTRY_POINT_DIRS:
			continue
		if len(partes) == 2 or (len(partes) == 3 and partes[-1] == "__init__.py"):
			return True
	return False


def _normalize_expected_files(
	raw: object, addon_name: str, project_type: str = "addon",
) -> list[str]:
	"""
	Normaliza o layout declarado pela IA e GARANTE ponto de entrada.

	Normalizacao de FORMA apenas (mesmo tratamento que `dependencies` recebe):
	separador do Windows vira "/", barra inicial some, entradas vazias ou
	nao-string caem fora, duplicatas somem preservando a ordem declarada.

	REPARO DETERMINISTICO (README Regra 7): se o plano de um addon nao declara
	nenhum ponto de entrada, o codigo ACRESCENTA
	globalPlugins/<AddonName>/__init__.py. Isso nao e decisao semantica -- e
	invariante tecnica da plataforma: sem esse arquivo o NVDA nao carrega nada,
	entao nao existe layout valido sem ele. Deixar a IA "decidir" isso foi
	exatamente o que produziu os 9 addons quebrados dos relatorios.

	controller_client e um programa EXTERNO (sem globalPlugins/, sem
	addonHandler): nao recebe reparo nenhum.
	"""
	vistos: set[str] = set()
	saida: list[str] = []
	if isinstance(raw, list):
		for item in raw:
			if not isinstance(item, str):
				continue
			caminho = item.strip().replace("\\", "/").lstrip("/")
			if not caminho or caminho in vistos:
				continue
			vistos.add(caminho)
			saida.append(caminho)

	if project_type == "controller_client":
		return saida
	if _declara_ponto_de_entrada(saida):
		return saida

	# Usa o pacote que a IA JA declarou, quando houver. Adicionar um pacote novo
	# a partir de addon_name criaria DOIS pacotes em globalPlugins/ -- pior que o
	# problema original, porque o addon passaria a ter um ponto de entrada vazio
	# ao lado dos arquivos reais. So cai em addon_name quando nao ha pacote
	# nenhum declarado.
	pacote = ""
	for caminho in saida:
		partes = caminho.split("/")
		if len(partes) >= 3 and partes[0] == "globalPlugins":
			pacote = partes[1]
			break
	if not pacote:
		pacote = (addon_name or "").strip() or "MeuAddon"
	entrada = f"globalPlugins/{pacote}/__init__.py"
	if entrada not in vistos:
		_logger.warning(
			"[PLAN] Layout declarado sem ponto de entrada -- %s acrescentado "
			"deterministicamente (o NVDA nao carregaria o addon sem ele).",
			entrada,
		)
		saida.insert(0, entrada)
	return saida


def format_expected_files_for_prompt(arquivos: list[str]) -> str:
	"""
	Bloco de layout injetado nos prompts de geracao de codigo.

	Vazio quando nao ha layout declarado -- nunca inventa um esqueleto aqui;
	sem declaracao o gerador segue como antes.
	"""
	if not arquivos:
		return ""
	linhas = "\n".join(f"  {caminho}" for caminho in arquivos)
	return (
		"\nLAYOUT DE ARQUIVOS DECLARADO NO PLANO -- use EXATAMENTE estes caminhos "
		"na anotacao de cada bloco (```python:caminho/arquivo.py). Nao invente "
		"nomes novos e nao renomeie:\n" + linhas + "\n"
	)


def declara_ponto_de_entrada(alvos: list[str]) -> bool:
	"""
	Algum destes caminhos e um arquivo que o NVDA realmente carrega?

	Convencao de caminho da plataforma, nao heuristica: `<dir>/<nome>.py` solto
	(um appModule, um driver) ou `<dir>/<pacote>/__init__.py`. Um `.py` ao lado
	do `__init__.py` dentro de um pacote e ignorado pelo NVDA.
	"""
	for caminho in alvos:
		partes = caminho.split("/")
		if len(partes) < 2 or partes[0] not in NVDA_ENTRY_POINT_DIRS:
			continue
		if len(partes) == 2 or (len(partes) == 3 and partes[-1] == "__init__.py"):
			return True
	return False


def _normalize_nvda_topics(raw: object) -> list[str]:
	"""
	Filtra os topicos de contexto NVDA declarados pela IA contra o catalogo real.

	Um topico inventado e ignorado la na frente (get_docs_code_generation nao
	levanta), mas o efeito colateral e pior que o erro: se TODOS os topicos
	declarados forem invalidos, o step recebe so o grupo core -- contexto
	minimo, silenciosamente, justamente no step que mais precisa dele. Aqui a
	lista invalida vira lista VAZIA, que significa "documentacao completa": mais
	cara, e a direcao segura de errar.
	"""
	if not isinstance(raw, list):
		return []
	validos = [
		t.strip() for t in raw
		if isinstance(t, str) and t.strip() in NVDA_DOC_TOPICS
	]
	vistos: set[str] = set()
	saida: list[str] = []
	for t in validos:
		if t not in vistos:
			vistos.add(t)
			saida.append(t)
	return saida


# Teto de tentativas por tipo de step, quando MEDICAO mostra que retentar nao
# converte reprovacao em aprovacao. Decisao de ROTEAMENTO (Regra 7), baseada em
# numero, nao em julgamento.
#
# design_review: 58 execucoes reais nos relatorios E2E. As 30 aprovacoes
# aconteceram TODAS na primeira tentativa (retries=0). Das 18 execucoes que
# retentaram, ZERO foram aprovadas -- 3,7 milhoes de tokens gastos sem uma
# unica conversao. E o output e usado como contexto pelo code_generation mesmo
# reprovado (_NON_BLOCKING_STEP_TYPES no orchestrator), entao a retentativa nao
# desbloqueia nada: so consome o orcamento que os steps de codigo precisam.
_MAX_RETRIES_PADRAO = 3
_MAX_RETRIES_BY_STEP_TYPE = {
	STEP_DESIGN_REVIEW: 1,
}


def _topicos_com_piso(
	topicos: list[str], step_type: str, alvos: list[str],
) -> list[str]:
	"""
	Piso de contexto para o step que gera o ponto de entrada do addon.

	Medido em E2E: cortar o contexto NVDA de ~90 mil para ~23 mil tokens (so o
	grupo core) derrubou as notas de 52.0 para 15.7 e de 32.7 para 9.1. Contexto
	de menos nao economiza -- so faz falhar mais barato. O escopo por topico e
	diferente em natureza (recorta por relevancia ao arquivo, nao por
	sonegacao), mas a direcao do risco e a mesma, entao o arquivo que o NVDA
	carrega tem piso: ele registra gestos e/ou item de menu por definicao.

	Steps que declaram lista vazia continuam recebendo a documentacao COMPLETA
	-- este piso nao transforma "nao declarou" em "recebe pouco".
	"""
	if not topicos or step_type != STEP_CODE_GENERATION:
		return topicos
	if not declara_ponto_de_entrada(alvos):
		return topicos
	return sorted(set(topicos) | {"scripts", "gui"})


def _normalize_gestures(raw: object) -> list[str]:
	"""
	Normaliza a lista de gestures declarada pela IA para o formato canonico do
	NVDA, sem interpretar o PEDIDO do usuario (isso e decisao semantica, ja
	tomada pela LLM ao preencher o campo -- README Regra 7).

	Aqui so ha normalizacao de FORMA, o mesmo tipo de tratamento que
	`dependencies` recebe: minusculas nos modificadores, prefixo "kb:" quando
	ausente, descarte de entradas vazias ou nao-string. Um modelo que devolve
	"NVDA+H" em vez de "kb:NVDA+h" declarou o mesmo atalho -- reprovar por isso
	seria transformar uma diferenca de formatacao em falha de funcionalidade.

	Deduplica preservando a ordem de declaracao: a ordem e o que o usuario vai
	ouvir se o addon for reprovado por atalho faltando.
	"""
	if not isinstance(raw, list):
		return []
	vistos: set[str] = set()
	saida: list[str] = []
	for item in raw:
		if not isinstance(item, str):
			continue
		texto = item.strip()
		if not texto:
			continue
		if ":" not in texto:
			texto = "kb:" + texto
		fonte, _, combo = texto.partition(":")
		canonico = f"{fonte.strip().lower()}:{combo.strip().lower()}"
		if canonico in vistos:
			continue
		vistos.add(canonico)
		saida.append(canonico)
	return saida


def _arquivos_de_codigo(expected_files: list[str] | None) -> list[str]:
	"""Só os .py do layout -- manifest.ini e doc/ não saem de code_generation."""
	return [
		caminho for caminho in (expected_files or [])
		if caminho.lower().endswith(".py")
	]


def oversized_code_generation_steps(
	steps: list["ExecutionStep"], expected_files: list[str] | None = None,
) -> list[str]:
	"""
	Retorna ids de steps de código grandes demais para uma rodada.

	Três critérios, do mais forte ao mais fraco:

	1. NÚMERO DE ARQUIVOS DECLARADOS (`target_files`) acima do teto. É o sinal
	   direto, quando o planner preenche o campo.

	2. LAYOUT QUE NÃO CABE NOS STEPS -- 2.34.0. Achado ao vivo (E2E 2026-08-30):
	   o critério 1 NUNCA disparou em execução real, porque o planner
	   simplesmente não preencheu `target_files`. O campo é declarado como
	   obrigatório no schema, mas "obrigatório no schema" não é o mesmo que
	   "preenchido" -- e o guarda contava zero arquivos e deixava passar um step
	   que na prática produzia seis. Confiar que a IA preencheu um campo é o
	   mesmo erro de confiar que ela seguiu uma regra: precisa de verificação.

	   Aqui a verificação é ARITMÉTICA, não adivinhação: se o layout declara
	   mais arquivos .py do que os steps de code_generation conseguem cobrir no
	   teto máximo, então por contagem simples algum step está produzindo mais
	   que o permitido -- independentemente de qual. Não inferimos QUAL arquivo
	   vai em QUAL step (isso é decisão semântica, do planner); só constatamos
	   que a divisão declarada não fecha.

	3. COMPRIMENTO da descrição/mensagem. Rede de segurança do critério
	   original -- proxy fraco (descrição curta pode pedir 6 arquivos), mantido
	   porque ainda pega o caso do step com contexto excessivo.
	"""
	oversized: list[str] = []
	cg_steps = [s for s in steps if s.step_type == STEP_CODE_GENERATION]

	# Critério 2: o layout cabe nos steps que existem?
	arquivos = _arquivos_de_codigo(expected_files)
	capacidade = len(cg_steps) * _MAX_FILES_POR_CODE_STEP
	layout_nao_cabe = bool(arquivos) and bool(cg_steps) and len(arquivos) > capacidade

	for step in cg_steps:
		if (
			len(step.description) > _MAX_CODE_STEP_DESCRIPTION_CHARS
			or len(step.user_message) > _MAX_CODE_STEP_USER_MESSAGE_CHARS
			or len(step.target_files) > _MAX_FILES_POR_CODE_STEP
			# Só marca os que NÃO declararam: um step que declarou 2 arquivos
			# está dentro do contrato e não deve ser penalizado porque outro
			# step do plano se omitiu.
			or (layout_nao_cabe and not step.target_files)
		):
			oversized.append(step.step_id)
	return oversized

_PROVIDER_STEP_MODELS: dict[str, dict[str, str]] = {
	provider: get_provider_step_models(provider)
	for provider in ("ollama", "anthropic", "openai", "google", "gemini", "xai")
}

_HEAVY_STEPS: set[str] = {
	STEP_CODE_GENERATION,
}

def resolve_step_model(step_type: str, provider: str, configured_model: str = "alto") -> str:
	tier = "heavy" if step_type in _HEAVY_STEPS else "light"
	return resolve_provider_tier_model(provider, tier, configured_model)


# 2.22.0 (2026-08-08): heavy_budget era um percentual FIXO (20%) sem
# relacao nenhuma com a complexidade real do pedido -- ja classificada
# pela propria LLM no plano (campo complexity de plan_data, ver create_plan())
# mas nunca repassada aqui. Achado a pedido do Felipe apos comparar com
# C:\agentic (outro projeto do usuario): la, um roteador dedicado
# classifica a tarefa (fast/balanced/deep) via chamada de IA em contexto
# -- nunca palavra-chave -- e isso determina o tier/candidatos, seguindo
# o padrao 2026 documentado (OpenAI GPT-5 router, Anthropic adaptive-
# reasoning, OpenRouter Auto Router: classificacao por IA + estrutura,
# nao regra fixa). NVDAStudio ja tinha esse sinal (a complexidade do
# PROPRIO planner, tambem via IA) -- so nunca influenciava o orcamento
# de modelo. "high" agora usa o tier "frontier" (quando o provider tem
# um, ver model_registry.py -- cai pra "heavy" quando nao tem) e um
# percentual maior; "low"/"simple" usa percentual menor (menos custo
# pra tarefa que a propria IA ja avaliou como simples).
_HEAVY_BUDGET_BY_COMPLEXITY: dict[str, float] = {
	"low": 0.10, "simple": 0.10,
	"medium": 0.20,
	"high": 0.35,
}


def apply_model_budget(
	steps: list["ExecutionStep"], provider: str, configured_model: str,
	preserve_step_types: set[str] | None = None,
	complexity: str = "medium",
) -> None:
	"""
	Mantem entre 70% e 90% dos steps no modelo leve quando Alto esta ativo
	(percentual exato varia por complexidade -- ver _HEAVY_BUDGET_BY_COMPLEXITY).

	preserve_step_types: step_types cujo model_id ja foi atribuido
	deliberadamente antes (ex: cross-model escalation no replan, ver
	Planner._build_steps model_overrides) e NAO deve ser sobrescrito pelo
	orcamento heavy/light. Sem isso, apply_model_budget sempre reescrevia
	TODO step.model_id incondicionalmente, tornando qualquer override
	anterior um no-op silencioso.

	complexity: classificacao low/medium/high ja feita pela LLM do planner
	pro pedido inteiro (campo complexity de plan_data) -- high usa o tier
	frontier pra code_generation (modelo mais capaz que heavy, quando o
	provider tiver um registrado) e um percentual maior de steps no tier
	elevado; low usa percentual menor.
	"""
	if not steps:
		return
	preserve = preserve_step_types or set()
	if not is_alto_model(configured_model):
		for step in steps:
			if step.step_type not in preserve:
				step.model_id = configured_model
		return
	# 2.22.0: escolha do model_id passa a ser pontuada (ai/model_router.py),
	# nao mais um unico valor fixo por tier -- mesmo padrao de C:\agentic
	# (qualidade documentada + custo + velocidade + confiabilidade
	# OBSERVADA, nao so um nome de modelo hardcoded). Steps nao-elevados
	# (a maioria) sao pontuados como se complexity="low" (favorece custo de
	# proposito, preserva a garantia original de "a maioria fica barata"
	# independente da complexidade real do pedido -- so o slot elevado de
	# code_generation deve variar com a complexidade). O slot elevado usa a
	# complexidade REAL do pedido, entao "high" favorece qualidade.
	from ..ai.model_router import select_model
	elevated = select_model(provider, STEP_CODE_GENERATION, configured_model, complexity=complexity)
	for step in steps:
		if step.step_type not in preserve:
			step.model_id = select_model(provider, step.step_type, configured_model, complexity="low")
	candidates = [
		step for step in steps
		if step.step_type == STEP_CODE_GENERATION and step.step_type not in preserve
	]
	budget_pct = _HEAVY_BUDGET_BY_COMPLEXITY.get(complexity, 0.20)
	heavy_budget = max(1, math.floor(len(steps) * budget_pct))
	for step in candidates[:heavy_budget]:
		step.model_id = elevated
	_logger.info(
		"[MODEL_BUDGET] steps=%d elevated=%d light=%d provider=%s complexity=%s elevated_model=%s preserved=%d",
		len(steps), min(len(candidates), heavy_budget), len(steps) - min(len(candidates), heavy_budget),
		provider, complexity, elevated, sum(1 for s in steps if s.step_type in preserve),
	)

# Mapa de fallback deterministico para injected steps (safety-critical).
# Usado apenas quando o Planner injeta steps que a LLM nao incluiu.
#
# Achado de auditoria (2026-08-04, Felipe: "no alto para qualquer provider...
# tem que usar o cascata"): valores aqui eram hardcoded pro modelo heavy do
# Ollama ("kimi-k2.7-code") pra TODO tipo de step, independente do provedor
# configurado. Tracado ate o dispatch real: apply_model_budget() SEMPRE roda
# logo apos a injecao (create_plan() linha ~700, replan_with_feedback()
# linha ~1315) e sobrescreve step.model_id de forma provider-aware -- entao
# na pratica o valor hardcoded aqui nunca chegava a ser usado pra executar
# nada (dispatch real usa step.model_id, nao este dict). O unico efeito
# real era `plan.step_model_map` (campo so-metadata, nenhum consumidor em
# producao alem de testes -- confirmado via grep cruzado) mostrar
# "kimi-k2.7-code" mesmo rodando OpenAI/Anthropic/Gemini/xAI. Trocado pro
# sentinela ALTO_MODEL ("alto"), que resolve corretamente por provedor em
# TODO consumidor -- elimina o valor Ollama-especifico mesmo nesse caminho
# metadata-only, sem depender de apply_model_budget rodar depois pra estar
# certo.
_STEP_FALLBACK_MODEL: dict[str, str] = {
	STEP_CODE_GENERATION:     ALTO_MODEL,
	STEP_MANIFEST:            ALTO_MODEL,
	STEP_ACCESSIBILITY_AUDIT: ALTO_MODEL,
	STEP_TEST_GENERATION:     ALTO_MODEL,
	STEP_WEB_RESEARCH:        ALTO_MODEL,
	STEP_AGENT_TEMPLATE:      ALTO_MODEL,
	STEP_AGENT_RUNNER:        ALTO_MODEL,
	STEP_ASSEMBLY:            ALTO_MODEL,
	STEP_DESIGN_REVIEW:       ALTO_MODEL,
	STEP_DOCUMENTATION:       ALTO_MODEL,
	STEP_USER_CLARIFICATION:  ALTO_MODEL,
	STEP_SYNTAX_VALIDATION:   ALTO_MODEL,
	STEP_ENGINEERING_REVIEW:  ALTO_MODEL,
}

# Alias retrocompativel para modulos que ainda referenciam STEP_MODEL_MAP
STEP_MODEL_MAP: dict[str, str] = dict(_STEP_FALLBACK_MODEL)

# Mapa de reasoning_effort para injected steps (safety-critical).
# Quando o step vem do plano da LLM, o reasoning_effort ja vem no JSON.
# Para steps injetados, use _effort_for_complexity() em vez deste dict diretamente.
_STEP_FALLBACK_REASONING: dict[str, str | None] = {
	STEP_CODE_GENERATION:     "high",
	STEP_ACCESSIBILITY_AUDIT: "high",
	STEP_TEST_GENERATION:     "high",
	STEP_WEB_RESEARCH:        None,
	STEP_AGENT_TEMPLATE:      None,
	STEP_AGENT_RUNNER:        "high",
	STEP_ASSEMBLY:            None,
	STEP_DESIGN_REVIEW:       "high",
	STEP_DOCUMENTATION:       None,
	STEP_USER_CLARIFICATION:  None,
	STEP_SYNTAX_VALIDATION:   None,
	STEP_ENGINEERING_REVIEW:  "high",
}

# Deriva reasoning_effort dinamicamente pela complexity do plano.
# Steps criticos (design_review, accessibility_audit) recebem:
#   high   -> "high"   (raciocinio profundo, addon complexo)
#   medium -> "medium" (raciocinio moderado)
#   low    -> None     (sem thinking overhead para addons simples)
_EFFORT_BY_COMPLEXITY: dict[str, dict[str, str | None]] = {
	STEP_DESIGN_REVIEW:       {"high": "high", "medium": "medium", "low": None},
	STEP_ACCESSIBILITY_AUDIT: {"high": "high", "medium": "medium", "low": None},
	STEP_DOCUMENTATION:       {"high": None,   "medium": None,     "low": None},
	STEP_ASSEMBLY:            {"high": None,   "medium": None,     "low": None},
	STEP_SYNTAX_VALIDATION:   {"high": None,   "medium": None,     "low": None},
	STEP_ENGINEERING_REVIEW:  {"high": "high", "medium": "medium", "low": None},
}

def _effort_for_complexity(step_type: str, complexity: str) -> str | None:
	"""Retorna reasoning_effort dinamico para steps injetados baseado na complexity do plano."""
	if step_type in _EFFORT_BY_COMPLEXITY:
		return _EFFORT_BY_COMPLEXITY[step_type].get(complexity)
	# Para steps nao mapeados, cai no fallback estatico
	return _STEP_FALLBACK_REASONING.get(step_type)

# Aliases retrocompativeis para testes e modulos legados.
_STEP_REASONING_MAP_ALIAS: dict[str, dict] = {}
for k, v in _STEP_FALLBACK_REASONING.items():
	if v:
		_STEP_REASONING_MAP_ALIAS[k] = {"reasoning_effort": v}
	else:
		_STEP_REASONING_MAP_ALIAS[k] = {}
STEP_REASONING_MAP = _STEP_REASONING_MAP_ALIAS

# COMPLEXITY_MAP mantido como aliases retrocompativeis para testes legados.
# A LLM decide o roteamento; estes mapas nao sao mais usados em producao.
COMPLEXITY_MAP: dict[str, dict[str, str]] = {
	"low":    {
		STEP_CODE_GENERATION: "kimi-k2.7-code", STEP_MANIFEST: "kimi-k2.7-code",
		STEP_ACCESSIBILITY_AUDIT: "kimi-k2.7-code", STEP_TEST_GENERATION: "kimi-k2.7-code",
		STEP_WEB_RESEARCH: "kimi-k2.7-code", STEP_AGENT_TEMPLATE: "kimi-k2.7-code",
		STEP_AGENT_RUNNER: "kimi-k2.7-code",
		STEP_ASSEMBLY: "kimi-k2.7-code", STEP_DESIGN_REVIEW: "kimi-k2.7-code",
		STEP_DOCUMENTATION: "kimi-k2.7-code", STEP_USER_CLARIFICATION: "kimi-k2.7-code",
		STEP_SYNTAX_VALIDATION: "kimi-k2.7-code",
		STEP_ENGINEERING_REVIEW: "kimi-k2.7-code",
	},
	"medium": {
		STEP_CODE_GENERATION: "kimi-k2.7-code", STEP_MANIFEST: "kimi-k2.7-code",
		STEP_ACCESSIBILITY_AUDIT: "deepseek-v4-flash", STEP_TEST_GENERATION: "kimi-k2.7-code",
		STEP_WEB_RESEARCH: "kimi-k2.7-code", STEP_AGENT_TEMPLATE: "kimi-k2.7-code",
		STEP_AGENT_RUNNER: "kimi-k2.7-code",
		STEP_ASSEMBLY: "kimi-k2.7-code", STEP_DESIGN_REVIEW: "deepseek-v4-flash",
		STEP_DOCUMENTATION: "kimi-k2.7-code", STEP_USER_CLARIFICATION: "kimi-k2.7-code",
		STEP_SYNTAX_VALIDATION: "kimi-k2.7-code",
		STEP_ENGINEERING_REVIEW: "kimi-k2.7-code",
	},
	"high":   {
		STEP_CODE_GENERATION: "kimi-k2.7-code", STEP_MANIFEST: "kimi-k2.7-code",
		STEP_ACCESSIBILITY_AUDIT: "deepseek-v4-flash", STEP_TEST_GENERATION: "kimi-k2.7-code",
		STEP_WEB_RESEARCH: "kimi-k2.7-code", STEP_AGENT_TEMPLATE: "kimi-k2.7-code",
		STEP_AGENT_RUNNER: "kimi-k2.7-code",
		STEP_ASSEMBLY: "kimi-k2.7-code", STEP_DESIGN_REVIEW: "deepseek-v4-flash",
		STEP_DOCUMENTATION: "kimi-k2.7-code", STEP_USER_CLARIFICATION: "kimi-k2.7-code",
		STEP_SYNTAX_VALIDATION: "kimi-k2.7-code",
		STEP_ENGINEERING_REVIEW: "kimi-k2.7-code",
	},
}

# Aliases retrocompativeis para testes que importam os mapas antigos.
STEP_MODEL_MAP_LOW    = COMPLEXITY_MAP["low"]
STEP_MODEL_MAP_MEDIUM = STEP_MODEL_MAP
STEP_MODEL_MAP_HIGH   = COMPLEXITY_MAP["high"]

@dataclass
class ExecutionStep:
	"""Um passo do plano de execucao."""
	step_id: str
	step_type: str
	description: str
	model_id: str
	reasoning_params: dict = field(default_factory=dict)
	depends_on: list[str] = field(default_factory=list)
	dependencies: list[str] = field(default_factory=list)  # alias de depends_on (compatibilidade)
	context_from_steps: list[str] = field(default_factory=list)
	expected_output: str = ""
	max_retries: int = _MAX_RETRIES_PADRAO
	user_message: str = ""   # mensagem em linguagem natural gerada pela LLM para o usuario
	msg_evaluating: str = ""  # o que dizer ao checar o resultado deste step
	msg_retrying: str = ""    # o que dizer ao tentar novamente apos problema
	msg_escalating: str = ""  # o que dizer ao usar modelo mais potente
	# Arquivos que ESTE step deve produzir, do layout declarado em
	# ExecutionPlan.expected_files. Vazio para steps que nao escrevem arquivo.
	#
	# Motivo (E2E real, 2026-08-29): a decomposicao era por FEATURE, e o guarda
	# de tamanho media o comprimento da descricao -- um proxy fraco. Medido nas
	# 3 rodadas: os code_generation que FALHAM consomem sempre ~419 mil tokens
	# em 3 tentativas; o unico que PASSOU consumiu 127 mil nas mesmas 3
	# tentativas. A diferenca nao era o loop nem o modelo -- era quantos
	# arquivos o step tentava produzir de uma vez. Os caros eram reprovados por
	# entrega parcial ("nao foi gerado o arquivo solicitado gemini_service.py").
	target_files: list[str] = field(default_factory=list)
	# Topicos de contexto NVDA que ESTE step precisa (ver
	# builder/nvda_context.NVDA_DOC_TOPICS). Medido em 2026-08-30: injetar os
	# 26 arquivos-fonte do NVDA em toda chamada custava ~90 mil tokens FIXOS
	# por tentativa. Um code_generation que falhava 3x queimava 412 mil tokens
	# -- 41% do orcamento do addon -- antes de qualquer trabalho util, e o step
	# que geraria o __init__.py nunca chegava a rodar.
	#
	# Vazio = contexto COMPLETO (comportamento anterior). Contexto faltando
	# custa mais caro que contexto sobrando, entao o padrao seguro e tudo.
	nvda_topics: list[str] = field(default_factory=list)

	def __post_init__(self):
		# Sincroniza depends_on e dependencies — aceita ambos os nomes
		if self.dependencies and not self.depends_on:
			self.depends_on = self.dependencies
		elif self.depends_on and not self.dependencies:
			self.dependencies = self.depends_on
		# Caminho canonico para target_files, aqui e nao no _build_steps: steps
		# tambem nascem dos injetores (_inject_*) e de codigo de teste, e a
		# invariante 'target_files esta normalizado' precisa valer para todos --
		# senao o guarda de tamanho e o prompt do step veem formatos diferentes
		# conforme a origem do step.
		#
		# Sem reparo de ponto de entrada (ao contrario de ExecutionPlan.
		# expected_files): um step individual nao precisa declarar o __init__.py
		# do addon -- isso e propriedade do plano, nao do step.
		if self.target_files:
			self.target_files = _normalize_expected_files(
				self.target_files, "", "controller_client",
			)

@dataclass
class ExecutionPlan:
	"""Plano completo de execucao gerado pelo Planner."""
	plan_id: str
	original_query: str
	steps: list[ExecutionStep]
	addon_name: str = ""
	# "addon": addon NVDA tradicional, roda dentro do processo NVDA (GlobalPlugin/
	# AppModule/driver), empacotado como .nvda-addon, carregado por addonHandler.
	# "controller_client": programa EXTERNO (fora do processo NVDA) que fala/braile
	# pelo NVDA via nvdaControllerClient.dll (Controller Client API) -- nao tem
	# manifest.ini, nao e um addon, nao passa por addonHandler. Ver
	# builder/controller_client_context.py.
	project_type: str = "addon"
	requires_web_research: bool = False
	requires_agent_runner: bool = False
	estimated_complexity: str = "medium"
	step_model_map: dict[str, str] = field(default_factory=dict)
	intro_message: str = ""
	plan_presentation: str = ""
	approval_message: str = ""
	cancellation_message: str = ""
	modification_message: str = ""
	assembling_message: str = ""
	completed_message: str = ""
	replan_message: str = ""
	dependencies: list[str] = field(default_factory=list)
	# Atalhos de teclado que o addon DEVE expor, declarados pela IA a partir do
	# pedido do usuario -- nunca extraidos por regex do texto (README Regra 7: a
	# interpretacao do pedido e decisao SEMANTICA, da LLM). O codigo so VERIFICA
	# que o que foi declarado existe de verdade no addon gerado
	# (sub_agents/ast_validator.py::validate_declared_gestures). Fecha a lacuna
	# achada em 2026-08-29: o pipeline garantia que o addon importa, instancia,
	# passa no lint e empacota -- mas nada garantia que a FUNCIONALIDADE pedida
	# estava la. Formato NVDA: "kb:NVDA+h", "kb:control+shift+m".
	expected_gestures: list[str] = field(default_factory=list)
	# Layout de arquivos do addon, declarado pela IA ANTES da geracao.
	#
	# Motivo (achado 2026-08-29): sem layout declarado, os nomes de arquivo
	# nasciam da improvisacao do modelo bloco a bloco. Quando um bloco vinha
	# sem anotacao de caminho, addon_builder._infer_python_filename() caia no
	# fallback module_N.py -- justamente o unico nome que o NVDA NUNCA carrega
	# dentro de um pacote. E ninguem era dono do __init__.py que amarra as
	# features: nos 9 addons quebrados dos relatorios, cada arquivo estava
	# bom isoladamente e o conjunto nao formava um addon carregavel.
	#
	# Declarar o esqueleto antes muda a geracao de 'inventar arquivo' para
	# 'preencher arquivo declarado'.
	expected_files: list[str] = field(default_factory=list)
	# Pacotes pip que o addon gerado precisa — bundlados em lib/ automaticamente.
	# Ex: ["openai-whisper", "Pillow", "requests"]
	# Usuario nao precisa instalar nada — igual ao NVDAStudio em si.


_PLAN_SYSTEM_PROMPT = """Voce e o Planner do NVDAStudio, um sistema autonomo de criacao de addons para o NVDA.

Sua funcao: dado um pedido do usuario, decompor em steps de execucao.

REGRA CRITICA — NOME CANONICO DO ADDON (skill: software-architecture + llm-structured-output):
Antes de qualquer coisa, decida o nome canonico do addon em CamelCase.
Este nome sera usado em TODO o plano — na pasta globalPlugins/<addon_name>/, no manifest.ini,
nos imports e no completed_message.
Regras do nome (fonte: nvda-addon-dev §9 — manifest name conventions):
  - CamelCase sem espacos: GmailSummarizer, TranscriadorIA, AnuncioTitulo
  - Apenas letras e numeros (sem hifen, sem underscore, sem acentos)
  - Em ingles ou portugues sem acento — o que soar mais natural para o addon
  - UMA vez definido, use EXATAMENTE o mesmo em todos os steps do plano
  - NUNCA use nomes diferentes em steps diferentes (ex: GmailSummarizer em code_generation
    e GmailResumo em manifest_builder — isso cria dois GlobalPlugins conflitantes no NVDA)

PROJECT_TYPE (julgamento semantico, nao palavra-chave -- ver descricao do campo no schema):
'addon' e o caso comum: gera um addon NVDA tradicional (globalPlugins/<addon_name>/,
manifest.ini, carregado pelo addonHandler). So use 'controller_client' quando o pedido
for inequivocamente sobre um PROGRAMA SEPARADO, fora do processo do NVDA, que usa a
Controller Client API (nvdaControllerClient.dll) pra fazer o NVDA falar/exibir em
braile a partir de fora -- nunca um addon que roda dentro do NVDA.
Quando project_type='controller_client':
  - NAO inclua manifest_builder, accessibility_audit nem agent_template no plano --
    esses steps sao especificos de addon (manifest.ini, WCAG de dialogs NVDA,
    template de agente interno) e nao se aplicam a um programa externo.
  - Steps tipicos: code_generation (o programa cliente + wrapper da DLL),
    documentation (README de uso), test_generation (se fizer sentido), assembly.
  - code_generation deve seguir o contexto de Controller Client API (ver
    builder/controller_client_context.py), nunca as regras NVDA-XXX de addon.
  - addon_name continua sendo o nome do PROGRAMA (nao ha globalPlugins/<addon_name>/
    nesse caso, mas o nome ainda organiza os arquivos gerados).

MODELOS DISPONIVEIS (escolha o melhor para cada step):
- kimi-k2.6: geracao de codigo, pesquisa, chat rapido, manifest, documentacao, assembly
- deepseek-v4-flash: planejamento, revisao profunda, auditoria de acessibilidade, arbitro de consenso (140B, rapido)

REASONING EFFORT (use apenas onde o modelo suporta):
- "high": steps criticos que exigem raciocinio profundo (accessibility_audit, critique, design_review, code_generation complexo)
- "medium": steps que se beneficiam de raciocinio moderado (code_generation simples, test_generation, agent_runner)
- null (omitir): steps mecanicos que nao precisam de raciocinio extra (manifest_builder, assembly, documentation, web_research)

Retorne APENAS um JSON valido com esta estrutura:
{
  "addon_name": "NomeEmCamelCase",
  "project_type": "addon|controller_client",
  "complexity": "low|medium|high",
  "requires_web_research": true|false,
  "requires_agent_runner": true|false,
  "intro_message": "Frase natural confirmando o que você entendeu do pedido do usuário, em português, tom conversacional e caloroso. Ex: 'Beleza! Entendi que você quer um addon que resume e-mails do Gmail automaticamente.' NUNCA copie a query literalmente — reescreva como uma pessoa confirmando que entendeu.",
  "plan_presentation": "Mensagem completa que será mostrada ao usuário para apresentar o plano e pedir sua decisão",
  "approval_message": "Confirmação natural de que a criação vai começar",
  "cancellation_message": "Confirmação natural de que a criação foi cancelada",
  "modification_message": "Confirmação natural de que o plano será ajustado conforme o pedido do usuário",
  "assembling_message": "Mensagem natural para o usuário enquanto o addon é montado",
  "completed_message": "Mensagem natural descrevendo o que foi criado, ex: Pronto! Criei o TranscriadorIA com suporte a Whisper e Tesseract. O addon transcreve imagens e áudios diretamente pelo NVDA.",
  "replan_message": "Mensagem natural para o usuário quando o plano precisa ser revisado por problemas, ex: Encontramos um problema no código gerado. Estamos revisando a abordagem para garantir que funcione corretamente.",
  "dependencies": ["pacote-pip-1", "pacote-pip-2"],
  "steps": [
	{
	  "step_id": "s1",
	  "step_type": "code_generation|manifest_builder|accessibility_audit|test_generation|web_research|agent_template|agent_runner|assembly|user_clarification",
	  "model_id": "kimi-k2.6|deepseek-v4-flash",
	  "reasoning_effort": "high|medium|null",
	  "description": "O que este step deve fazer, detalhado",
	  "expected_output": "O que se espera como resultado deste step",
	  "user_message": "Mensagem curta e natural para o usuário sobre o que está acontecendo neste step, ex: Pesquisando as melhores bibliotecas para transcrição de áudio...",
	  "msg_evaluating": "Mensagem natural enquanto o resultado é verificado, ex: Conferindo se o código segue as diretrizes do NVDA...",
	  "msg_retrying": "Mensagem natural ao tentar novamente após problema, ex: Ajustando o código com base nos problemas encontrados...",
	  "msg_escalating": "Mensagem natural ao usar análise mais aprofundada, ex: Usando uma análise mais cuidadosa para resolver os problemas persistentes...",
	  "depends_on": [],
	  "context_from_steps": []
	}
  ]
}

Regras para mensagens de step (user_message, msg_evaluating, msg_retrying, msg_escalating):
- Linguagem natural, em português, primeira pessoa do plural (ex: Criando o manifesto do addon...)
- Curta: no máximo 90 caracteres
- Descreve o que está sendo feito, não o step_type técnico
- Sem palavras técnicas como manifest_builder, agent_runner, step_id, code_generation, etc.
- Sem emojis
- msg_evaluating: diz o que está sendo verificado no resultado específico deste step
  ex para código: "Verificando se o código funciona corretamente com o NVDA..."
  ex para manifesto: "Conferindo as informações do manifesto..."
  ex para documentação: "Checando se a documentação está completa e acessível..."
- msg_retrying: explica que houve um problema e o sistema está ajustando
  ex: "Ajustando o código para corrigir os problemas encontrados..."
  ex: "Refinando a documentação com base nas correções necessárias..."
- msg_escalating: indica que será feita uma análise mais profunda
  ex: "Aplicando análise mais aprofundada para superar os problemas persistentes..."
- replan_message (nível do plano): mensagem ao revisar o plano inteiro por falha crítica
  ex: "Encontramos um problema persistente. Revisando a estratégia de criação do addon..."
- intro_message: reescreva o pedido do usuário como uma confirmação natural e calorosa
  (nunca copie/cole trechos crus da query — especialmente se a query mencionar "addon",
  "NVDA" ou nomes de produto logo em seguida, isso pode gerar frases sem sentido gramatical)
- plan_presentation: escreva a apresentação INTEIRA do plano como uma conversa natural.
  Inclua o que você entendeu, explique todas as etapas em linguagem simples e termine
  convidando o usuário a aprovar, pedir mudanças ou cancelar com suas próprias palavras.
  Não use um texto padronizado. Adapte a explicação ao pedido e ao plano gerado.
  Pode numerar etapas quando isso facilitar a leitura, mas não use títulos, marcadores,
  Markdown, emojis, sequências decorativas como três hífens ou três asteriscos,
  nomes internos, classificações ou raciocínio privado.
- approval_message, cancellation_message e modification_message: respostas curtas,
  naturais e específicas para este addon. Sem texto de sistema, Markdown ou emojis.
- assembled_message e completed_message: mensagens em português, sem termos técnicos
- dependencies: lista de pacotes pip que o addon vai precisar em runtime
  * Use nomes exatos do PyPI: "openai-whisper", "Pillow", "requests", "google-generativeai", etc.
  * Inclua APENAS pacotes externos — nao inclua modulos do NVDA,
	nem stdlib Python, nem modulos do NVDA
  * Se o addon nao precisa de nada externo: lista vazia []
  * Prefira pacotes com wheels py3-none-any (puro Python) quando possivel
  * Os pacotes serao instalados automaticamente em lib/ junto com o addon
- completed_message: descrição rica do que foi entregue, mencionando funcionalidades específicas

REGRAS DE INFERENCIA ARQUITETURAL (aplique ANTES de compor os steps):
Leia o pedido do usuario e identifique os requisitos arquiteturais ANTES de definir os steps.
Cada regra abaixo define um GATILHO (quando aplicar) e uma ACAO OBRIGATORIA:
# NOTA DE MANUTENCAO (auditoria 2026-07-17): estes 6 GATILHO/ACAO sao a fonte de ensino
# detalhada para o Planner -- deliberadamente mais rica que a descricao de uma linha em
# rule_registry.py::ARCH_DESCRIPTIONS. Se o CONTEUDO de uma regra ARCH mudar (novo gatilho,
# nova acao obrigatoria), atualize as DUAS fontes juntas para nao dessincronizar.

ARCH-001 (API externa com chave):
  GATILHO: pedido menciona API, chave de API, token, servico web, OpenAI, Groq, Whisper,
           Google, Azure, ElevenLabs, DeepL, ou qualquer servico que exija autenticacao.
  ACAO: code_generation DEVE gerar dois arquivos:
    1. __init__.py — GlobalPlugin que registra SettingsPanel no __init__ e o remove no terminate()
    2. settings_panel.py — classe que estende SettingsPanel com campo para chave de API
       usando config.conf.spec para persistencia (nunca hardcode a chave, nunca arquivo manual).
  JUSTIFICATIVA: o usuario precisa de onde configurar a chave. Sem isso o addon nao funciona.

ARCH-002 (I/O ou processamento em background):
  GATILHO: pedido envolve transcricao, download, requisicao HTTP, processamento de arquivo,
           geracao de imagem, OCR, sintese de voz, ou qualquer operacao que demora mais de 1s.
  ACAO: code_generation DEVE usar threading.Thread (ou concurrent.futures) para a operacao
        pesada, e wx.CallAfter() para atualizar a UI com o resultado.
        NUNCA usar requests.get() / open() na thread principal do NVDA (viola NVDA-002).
  JUSTIFICATIVA: operacoes lentas na thread principal travam o leitor de tela inteiro.

ARCH-008 (multiplas funcionalidades):
  GATILHO: pedido descreve um addon com 2 ou mais funcoes distintas para o usuario
           (ex: transcrever audio + configurar idioma + ver historico).
	ACAO: code_generation DEVE definir ponto de entrada principal conforme contexto do pedido:
				(A) item no menu Ferramentas, OU
				(B) painel em Configuracoes (SettingsPanel), OU
				(C) ambos, quando o caso exigir.
		Se o pedido nao indicar preferencia explicita, perguntar ao usuario qual ponto de entrada prefere.
		Quando menu for escolhido: usar padrao robusto com fallback (mainFrame.toolsMenu OU
		mainFrame.sysTrayIcon.toolsMenu), retry curto no startup da UI e remocao no terminate().
		Bind/Unbind do wx.EVT_MENU DEVE ocorrer no mesmo owner do menu resolvido (mainFrame ou sysTray).
	JUSTIFICATIVA: addons multifuncionais precisam de descoberta acessivel, mas o melhor ponto de
	entrada depende do fluxo do usuario e do tipo de acao (comando rapido vs configuracao persistente).

ARCH-004 (separacao de camadas):
  GATILHO: o addon vai chamar uma API externa OU processar dados complexos.
  ACAO: code_generation DEVE separar em pelo menos 2 arquivos Python:
    - __init__.py: apenas GlobalPlugin (scripts, handlers, menu, ciclo de vida)
    - <nome_servico>.py: classe de servico que encapsula a chamada de API ou logica de negocio
      O GlobalPlugin importa e usa o servico, nunca chama a API diretamente.
  JUSTIFICATIVA (skill: software-architecture): misturar logica de negocio com codigo NVDA
  cria acoplamento rigido. Separar facilita testes, troca de API e manutencao.

ARCH-005 (configuracoes persistentes):
  GATILHO: addon tem qualquer dado que o usuario precisa configurar ou que deve persistir
           entre sessoes (idioma, endpoint, modelo, threshold, etc.).
  ACAO: code_generation DEVE definir config.conf.spec com os campos necessarios no __init__
        do GlobalPlugin. Usar config.conf["secao"]["chave"] para ler e salvar.
        Nunca usar shelve, pickle, open() manual ou variaveis globais para persistencia.
  JUSTIFICATIVA: config.conf e o mecanismo oficial do NVDA para configuracoes de addons.

ARCH-009 (menu ferramentas para qualquer addon com dialog):
  GATILHO: addon abre um wx.Dialog ou wx.Frame como interface principal.
	ACAO: SE o pedido pedir menu explicitamente, incluir item no menu Ferramentas com fallback
		de API (toolsMenu/systray toolsMenu). Se o pedido pedir apenas configuracoes,
		priorizar SettingsPanel. Se estiver ambiguo, perguntar ao usuario.
		Quando usar menu, bind/unbind sempre no owner correspondente ao menu efetivamente usado.
	JUSTIFICATIVA: atalhos podem conflitar, menu e util, mas nem todo addon precisa usar menu como
	padrao quando o caso de uso e majoritariamente de configuracao.

ARCH-007 (organizacao por funcionalidade, nao por arquivos soltos):
  GATILHO: pedido descreve 3 ou mais features/servicos substanciais e distintos (ex: um addon
           que integra Spotify + faz transcricao + gerencia playlists — 3 dominios diferentes,
           nao 3 metodos da mesma API).
  ACAO: code_generation DEVE organizar cada feature substancial em seu proprio subpacote
        nomeado pela funcionalidade dentro de globalPlugins/<addon_name>/ (ex: spotify/,
        transcricao/, playlists/ — cada um com __init__.py + os modulos daquela feature),
        em vez de arquivos soltos genericos (helper.py, utils.py, misc.py) ou todos os
        servicos direto na raiz do pacote. O GlobalPlugin (__init__.py na raiz) so orquestra
        — importa e usa cada subpacote, nunca implementa a logica da feature nele.
        Para 1-2 features (caso comum, coberto por ARCH-004), continua bastando arquivo(s)
        soltos — nao criar subpacote pra uma unica classe de servico.
  JUSTIFICATIVA (pesquisa dedicada 2026, vertical slice / feature-based organization):
    organizar por funcionalidade em vez de por camada tecnica facilita entender/mudar uma
    feature sem carregar partes nao relacionadas do sistema; e o padrao recomendado pra
    projetos com 3+ dominios distintos em 2026. Nomear a pasta pela funcionalidade (nao um
    nome tecnico generico) torna a estrutura auto-descritiva.

ARCH-010 (decomposicao paralela de features independentes):
  GATILHO: MESMO gatilho de ARCH-007 (3+ features/servicos substanciais e distintos, sem
           dependencia funcional entre si -- ex: descricao de imagem + transcricao de audio +
           transcricao de video, cada uma podendo funcionar sem as outras).
  ACAO: em vez de UM code_generation so cobrindo tudo, gere um code_generation SEPARADO por
        feature substancial (mesmo subpacote de ARCH-007 -- cada code_generation produz o
        __init__.py + modulos de UM subpacote, ex: globalPlugins/<addon>/imagem/, .../audio/,
        .../video/), com depends_on=[] entre eles (sao independentes -- o orchestrator ja roda
        steps sem dependencia mutua em PARALELO via ThreadPoolExecutor, isso NAO e algo que
        voce precisa configurar, so nao criar uma dependencia artificial entre eles). Adicione
        MAIS UM code_generation final (ex: step_id "cg_core") que depende de TODOS os
        code_generation de feature (depends_on=[ids das features], context_from_steps=[idem]) --
        esse ultimo gera SO o globalPlugins/<addon>/__init__.py raiz, que importa e orquestra
        os subpacotes ja prontos. Nao decomponha 1-2 features (seria overhead sem beneficio) --
        so quando ARCH-007 ja pede subpacotes separados.
  JUSTIFICATIVA (achado real, 2026-08-09): um pedido com 3 features grandes e independentes
  (assistente multimodal: imagem+audio+video) virou UM code_generation so, e o modelo REJEITOU
  a propria resposta (score 0, "nenhum codigo produzido") -- tarefa grande demais numa chamada
  so. Decompor em steps menores e independentes, cada um testavel/revisavel sozinho e
  executado em paralelo, e o padrao real que a industria de ferramentas de codificacao com IA
  usa em 2026 ("delegacao" em vez de "completar tudo de uma vez") -- reduz a chance de qualquer
  UM pedaco sobrecarregar o modelo, e os pedacos que falharem podem escalar/retry
  independentemente dos que ja passaram.

ARCH-011 (decomposicao do proprio step final "cg_core"):
  GATILHO: o step final (o que gera o __init__.py raiz e depende de TODOS os subpacotes de
           ARCH-010, ou o UNICO code_generation em pedidos sem decomposicao de feature) TAMBEM
           precisaria gerar, na MESMA chamada, um SettingsPanel substancial (multiplos campos,
           validacao, layout wx.BoxSizer) E o config.conf.spec correspondente E classes de erro/
           utilitarios compartilhados E a orquestracao do GlobalPlugin (menu, lifecycle,
           subpacotes) -- 3+ concerns substanciais e distintos empilhados numa unica chamada,
           mesmo criterio de ARCH-007/ARCH-010, so que dentro do proprio step final em vez de
           entre features.
  ACAO: separe um code_generation DEDICADO (ex: step_id "cg_settings") so para
        globalPlugins/<addon>/configSpec.py (config.conf.spec + apply_config_spec()) e
        globalPlugins/<addon>/settings_panel.py (o SettingsPanel completo). O step final
        ("cg_core") ganha cg_settings em depends_on/context_from_steps (alem dos subpacotes de
        feature, se houver) -- o __init__.py raiz so IMPORTA e CHAMA apply_config_spec() e a
        classe SettingsPanel ja prontos, nao os implementa. Isso NAO contradiz ARCH-005 ("code_
        generation DEVE definir config.conf.spec... no __init__ do GlobalPlugin"): a definicao
        do spec pode morar num modulo proprio desde que apply_config_spec() seja CHAMADA no
        __init__.py antes de qualquer acesso a config.conf -- mesmo padrao ja documentado nos
        exemplos de codigo (ver code_generator.py). Para addons SIMPLES (sem SettingsPanel
        substancial, so 1-2 opcoes triviais), nao separe -- overhead sem beneficio (mesma
        ressalva de ARCH-007/ARCH-010 pra 1-2 features).
  JUSTIFICATIVA (achado real, 2026-08-16, test_e36 GeminiMultimodal): mesmo o modelo mais forte
  disponivel (qwen3.5:397b, escolhido pelo router por pontuacao de qualidade) reprovou 3/3
  tentativas do step final -- violacoes reais (wx.MessageBox em vez de gui.message.MessageDialog,
  config.conf usado sem config.conf.spec visivel na MESMA chamada) que nunca convergiram porque
  a tarefa (root __init__.py + settings + config + errors, tudo de uma vez) sobrecarregava
  QUALQUER modelo, nao so os mais fracos. "Delegar" pra um modelo melhor nao resolve uma tarefa
  grande demais -- decompor resolve, mesmo racional ja validado em ARCH-010 (2.25.0), aplicado
  agora tambem DENTRO do step final, nao so entre features.

Regras de composicao:
- OBRIGATORIO: sempre inclua PELO MENOS UM code_generation. Para pedidos com 3+ features
  independentes (ARCH-007/ARCH-010), inclua VARIOS -- um por feature/subpacote, mais um final
  que gera o __init__.py raiz e depende de todos os outros. Para pedidos simples, um so
  code_generation gerando __init__.py (e o(s) modulo(s) de servico, se ARCH-004 aplicar) basta.
  Se o step final tambem acumular SettingsPanel substancial + config.conf.spec (ARCH-011),
  separe um code_generation dedicado ("cg_settings") pra isso, com o step final dependendo dele.
- OBRIGATORIO: sempre inclua manifest_builder
- OBRIGATORIO: sempre inclua documentation — gera doc/pt_BR/userGuide.html e doc/en/userGuide.html.
  O NVDA nao mostra ajuda ao usuario sem esse arquivo. documentation deve depender de
  code_generation e manifest_builder, e deve vir ANTES do assembly.
  assembly deve depender de documentation (nao apenas de code_generation e manifest_builder).
- OBRIGATORIO: sempre termine com assembly — e o step que monta e empacota todos os artefatos.
  Sem assembly o pipeline nao conclui. assembly deve ser SEMPRE o ultimo step da lista.
- OBRIGATORIO sobre code_generation: gera APENAS arquivos Python (.py).
  NUNCA gera HTML, nunca gera manifest.ini — isso e responsabilidade de outros steps.
  HTML de documentacao e responsabilidade EXCLUSIVA do step documentation.
  manifest.ini e responsabilidade EXCLUSIVA do step manifest_builder.
- OBRIGATORIO sobre requires_agent_runner: deve ser true quando o comportamento
  do addon gerado depender de um modelo de IA em tempo de execucao para atender
  o usuario. Decida pelo significado completo da solicitacao, nunca por termos isolados.
  Quando requires_agent_runner=true, os steps DEVEM incluir agent_runner e agent_template.
- OPCIONAL: use user_clarification quando precisar de informacao critica do usuario para continuar
  com seguranca. Inclua as perguntas no campo description (separadas por |).
  Exemplo: description = "Para qual aplicativo e o addon? | O atalho deve ser global ou apenas nessa janela?"
  user_clarification deve ser o primeiro step que depende dessas informacoes.
  Nao abuse: use apenas quando a ambiguidade puder comprometer o resultado.
- accessibility_audit deve depender de code_generation (nao o contrario)
- Se o addon tiver agentes internos: inclua agent_template e agent_runner
- Se precisar de informacao externa: inclua web_research ANTES dos outros steps
- assembly deve depender APENAS de code_generation e documentation (NUNCA de manifest_builder,
  agent_template, agent_runner ou design_review). manifest_builder e agent_template podem falhar
  sem bloquear assembly; assembly recebe o contexto deles via context_from_steps quando disponiveis.
- accessibility_audit e informativo — nao deve bloquear assembly
- depends_on lista step_ids que devem estar prontos antes deste step
- context_from_steps lista step_ids cujos outputs devem ser passados para este step
- Sem texto fora do JSON. Sem markdown. Apenas JSON puro.
"""

# 2026-08-29: o planner passa a decidir DECOMPOSICAO e ORDEM DE VERIFICACAO com
# criterio de engenharia explicito, nao so pelo formato do JSON. Fonte unica de
# verdade em utils/engineering_principles.py, compartilhada com critic,
# code_generator e engineering_reviewer -- nunca duplicar o texto aqui
# (README Regra 5).
_PLAN_SYSTEM_PROMPT += "\n\n" + ENGINEERING_PLANNING_PROMPT_TEXT


def _plan_json_from_tool_call(resp) -> str:
	"""
	Extrai o plano do argumento da tool call "entregar_plano" e devolve como
	string JSON -- mesmo contrato de retorno que o caminho json_schema
	(resp.content), pra _parse_plan()/_build_steps() nao precisarem saber
	qual dos dois caminhos gerou o plano. Fallback gracioso pro content
	bruto se o modelo nao chamou a tool (nao e forcado via tool_choice, so
	fortemente instruido).
	"""
	if not resp.tool_calls:
		return resp.content or ""
	tc = resp.tool_calls[0]
	fn = tc.function if hasattr(tc, "function") else tc.get("function", {})
	args = fn.arguments if hasattr(fn, "arguments") else fn.get("arguments", {})
	if isinstance(args, dict):
		return json.dumps(args)
	return args or resp.content or ""


class Planner:
	"""Gera planos de execucao estruturados usando modelo de raciocinio."""

	def __init__(self):
		pass

	def create_plan(self, user_query: str, domain_ctx=None, on_narration_chunk=None) -> ExecutionPlan:
		log_llm_call(_logger, f"planner_v{MODULE_VERSION}", user_query)

		raw_plan = self._call_planner_llm(user_query, domain_ctx, on_narration_chunk)
		log_llm_response(_logger, f"planner_v{MODULE_VERSION}", raw_plan)

		plan_data = self._parse_plan(raw_plan)
		complexity = plan_data.get("complexity", "medium")
		project_type = plan_data.get("project_type", "addon")
		steps = self._build_steps(plan_data.get("steps", []), complexity)

		# Uma tarefa grande demais degrada a qualidade mesmo quando o modelo é
		# forte. Pede uma nova decomposição uma única vez, antes de injetar os
		# steps obrigatórios, para não gerar um loop de replanejamento.
		_layout_declarado = _normalize_expected_files(
			plan_data.get("expected_files", []),
			plan_data.get("addon_name", ""),
			project_type,
		)
		oversized = oversized_code_generation_steps(steps, _layout_declarado)
		if oversized:
			_logger.warning("[PLAN] Subtarefas grandes detectadas: %s. Replanejando.", oversized)
			decomposition_prompt = (
				f"{user_query}\n\n"
				"REPLANEJAMENTO OBRIGATORIO: a tarefa deve ser quebrada em subtarefas "
				"menores. Divida por ARQUIVO, nao por funcionalidade: cada step de "
				"code_generation deve produzir no maximo 2 arquivos, declarados em "
				"target_files. Medido em execucao real: um step que tenta uma feature "
				"inteira de uma vez (servico + dialogo + painel + testes) e reprovado "
				"por entrega parcial e custa 3x mais que um step focado. Use depends_on "
				"para encadear os arquivos que dependem uns dos outros, e termine com um "
				"step de integracao. Retorne o mesmo JSON estruturado do planner."
			)
			try:
				decomposed_raw = self._call_planner_llm(
					decomposition_prompt, domain_ctx, on_narration_chunk,
				)
				decomposed_data = self._parse_plan(decomposed_raw)
				decomposed_steps = self._build_steps(
					decomposed_data.get("steps", []), decomposed_data.get("complexity", complexity),
				)
				_layout_decomposto = _normalize_expected_files(
					decomposed_data.get("expected_files", []),
					decomposed_data.get("addon_name", ""),
					decomposed_data.get("project_type", project_type),
				)
				if not oversized_code_generation_steps(decomposed_steps, _layout_decomposto):
					plan_data = decomposed_data
					complexity = plan_data.get("complexity", complexity)
					project_type = plan_data.get("project_type", project_type)
					steps = decomposed_steps
				else:
					_logger.error(
						"[PLAN] Replanejamento ainda gerou subtarefas grandes: %s",
						oversized_code_generation_steps(decomposed_steps, _layout_decomposto),
					)
			except Exception as exc:
				_logger.error("[PLAN] Falha ao decompor subtarefas grandes: %s", exc)

		# Injecao deterministica de steps obrigatorios.
		# A LLM NAO decide roteamento — ela decide CONTEUDO e ESTRATEGIA.
		# Roteamento e validacao de modelo sao deterministicos (Regra 5).
		# 2.26.0: design_review/accessibility_audit/manifest_builder sao
		# EXCLUSIVOS de project_type=="addon" -- injeta-los num projeto
		# controller_client (programa externo, sem manifest.ini nem
		# globalPlugins/) reintroduziria exatamente os steps que
		# _PLAN_SYSTEM_PROMPT ja instrui o LLM a NAO incluir nesse caso.

		if complexity == "high" and project_type == "addon":
			steps = self._inject_design_review(steps, user_query, complexity)

		if project_type == "addon":
			steps = self._inject_accessibility_audit(steps, user_query, complexity)
			steps = self._inject_manifest(steps, user_query, complexity)
			steps = self._inject_core_step(steps, user_query, complexity)

		steps = self._inject_documentation(steps, complexity)

		steps = self._inject_syntax_validation(steps, complexity)

		if project_type == "addon":
			steps = self._inject_engineering_review(steps, complexity)

		steps = self._inject_assembly(steps, complexity)

		# Normaliza modelos de todos os steps:
		# - modelo concreto escolhido pelo usuario sobrescreve os defaults;
		# - "alto" resolve pelo provider e tier do step;
		# - valores invalidos caem no resolvedor atual.
		from ..gui.settings_panel import get_llm_provider, get_llm_model
		provider = get_llm_provider()
		configured_model = get_llm_model()
		apply_model_budget(steps, provider, configured_model, complexity=complexity)

		# Popula step_model_map retrocompativel (testes verificam este campo).
		# Em producao, cada step usa seu proprio model_id definido pela LLM.
		if complexity == "low":
			step_model_map = dict(COMPLEXITY_MAP["low"])
		elif complexity == "high":
			step_model_map = dict(COMPLEXITY_MAP["high"])
		else:
			step_model_map = dict(COMPLEXITY_MAP["medium"])

		# Fallback: preenche entries que a LLM esqueceu
		for stype in _STEP_FALLBACK_MODEL:
			if stype not in step_model_map:
				step_model_map[stype] = _STEP_FALLBACK_MODEL[stype]

		# Gap C (skill: software-architecture + llm-structured-output):
		# addon_name canonico fixado pelo planner — mesmo nome em TODOS os steps.
		# Se o modelo nao retornou addon_name, deriva das primeiras palavras da query.
		raw_addon_name = plan_data.get("addon_name", "").strip()
		if not raw_addon_name:
			raw_addon_name = re.sub(r"[^\w]", "_", user_query[:30]).strip("_") or "MeuAddon"
			_logger.warning("[AVISO] addon_name ausente no plano — derivado da query: %s", raw_addon_name)

		plan = ExecutionPlan(
			plan_id=str(uuid.uuid4())[:8],
			original_query=user_query,
			steps=steps,
			addon_name=raw_addon_name,
			project_type=plan_data.get("project_type", "addon"),
			requires_web_research=plan_data.get("requires_web_research", False),
			requires_agent_runner=plan_data.get("requires_agent_runner", False),
			estimated_complexity=complexity,
			step_model_map=step_model_map,
			intro_message=plan_data.get("intro_message", ""),
			plan_presentation=plan_data.get("plan_presentation", ""),
			approval_message=plan_data.get("approval_message", ""),
			cancellation_message=plan_data.get("cancellation_message", ""),
			modification_message=plan_data.get("modification_message", ""),
			assembling_message=plan_data.get("assembling_message", "Montando o addon..."),
			completed_message=plan_data.get("completed_message", "Addon criado com sucesso!"),
			replan_message=plan_data.get("replan_message", "Encontramos problemas. Revisando a abordagem..."),
			expected_files=_normalize_expected_files(
				plan_data.get("expected_files", []),
				plan_data.get("addon_name", ""),
				plan_data.get("project_type", "addon"),
			),
			expected_gestures=_normalize_gestures(plan_data.get("expected_gestures", [])),
			dependencies=plan_data.get("dependencies", []),
		)
		log_decision(
			_logger, "plano_criado",
			f"id={plan.plan_id} steps={len(steps)} "
			f"complexity={plan.estimated_complexity} "
			f"design_review={'sim' if complexity == 'high' else 'nao'}"
		)
		return plan

	def _inject_design_review(
		self, steps: list[ExecutionStep], user_query: str, complexity: str = "high",
	) -> list[ExecutionStep]:
		"""
		Injeta um step design_review antes do primeiro code_generation.

		Logica deterministica (Regra 5):
		- So ativa para complexity=high
		- Se ja existe design_review no plano, nao duplica
		- design_review recebe depends_on=[] e context_from_steps=[]
		- code_generation passa a depender de design_review e recebe seu contexto

		O conteudo e gerado pela LLM (Challenger + Constraint Guardian).
		"""
		if any(s.step_type == STEP_DESIGN_REVIEW for s in steps):
			_logger.info("[PLAN] design_review ja presente no plano. Sem injecao.")
			return steps

		reasoning_params: dict = {}
		re_effort = _effort_for_complexity(STEP_DESIGN_REVIEW, complexity)
		if re_effort:
			reasoning_params["reasoning_effort"] = re_effort

		dr_step = ExecutionStep(
			step_id="dr0",
			step_type=STEP_DESIGN_REVIEW,
			description=(
				"Revisao de design antes da codificacao: "
				"Challenger identifica riscos e suposicoes; "
				"Constraint Guardian mapeia restricoes NVDA/WX criticas."
			),
			model_id=_STEP_FALLBACK_MODEL.get(STEP_DESIGN_REVIEW, _DEFAULT_MODEL),
			reasoning_params=reasoning_params,
			depends_on=[],
			context_from_steps=[],
			expected_output="Documento de revisao com riscos e restricoes para guiar code_generation",
			max_retries=1,
			user_message="Analisando os requisitos e identificando riscos antes de começar...",
			msg_evaluating="Verificando se a análise de requisitos está completa...",
			msg_retrying="Refinando a análise de requisitos...",
			msg_escalating="Aprofundando a análise de requisitos com maior precisão...",
		)

		# Atualiza code_generation steps para depender e receber contexto do design_review
		updated = []
		for step in steps:
			if step.step_type == STEP_CODE_GENERATION:
				if "dr0" not in step.depends_on:
					step.depends_on = ["dr0"] + step.depends_on
				if "dr0" not in step.context_from_steps:
					step.context_from_steps = ["dr0"] + step.context_from_steps
			updated.append(step)

		log_decision(_logger, "design_review_injetado",
					 f"dr0 injetado antes de {len(updated)} steps")
		return [dr_step] + updated

	def _inject_accessibility_audit(
		self, steps: list[ExecutionStep], original_query: str, complexity: str = "medium",
	) -> list[ExecutionStep]:
		"""
		Injeta accessibility_audit em todo addon que contenha geração de código.
		"""
		if any(s.step_type == STEP_ACCESSIBILITY_AUDIT for s in steps):
			_logger.info("[PLAN] accessibility_audit ja presente no plano. Sem injecao.")
			return steps

		cg_ids = [s.step_id for s in steps if s.step_type == STEP_CODE_GENERATION]
		if not cg_ids:
			return steps

		reasoning_params: dict = {}
		re_effort = _effort_for_complexity(STEP_ACCESSIBILITY_AUDIT, complexity)
		if re_effort:
			reasoning_params["reasoning_effort"] = re_effort

		aa_step = ExecutionStep(
			step_id="aa_inj",
			step_type=STEP_ACCESSIBILITY_AUDIT,
			description=(
				"Auditar acessibilidade da interface wx gerada: "
				"verificar SetName() em controles sem label visivel, "
				"BoxSizer para layout, aceleradores & nos botoes, "
				"uso correto de wx.CallAfter() e regras WX-A11Y-001 a WX-A11Y-014."
			),
			model_id=_STEP_FALLBACK_MODEL.get(STEP_ACCESSIBILITY_AUDIT, _DEFAULT_MODEL),
			reasoning_params=reasoning_params,
			depends_on=cg_ids,
			context_from_steps=cg_ids,
			expected_output="Relatorio de auditoria de acessibilidade da interface wx.",
			max_retries=1,
			user_message="Verificando acessibilidade da interface gráfica...",
			msg_evaluating="Conferindo se todos os controles são acessíveis...",
			msg_retrying="Revisando a auditoria de acessibilidade...",
			msg_escalating="Aprofundando a auditoria de acessibilidade...",
		)

		# Atualiza assembly para depender de accessibility_audit (mesmo padrao
		# de _inject_documentation) -- achado real no teste E2E de 2026-08-04:
		# o append cego abaixo colocava aa_inj DEPOIS de assembly sempre que
		# o plano bruto do LLM ja incluia seu proprio step de assembly,
		# quebrando a invariante "assembly e sempre o ultimo step" e fazendo
		# o addon ser empacotado antes da auditoria de acessibilidade rodar.
		updated: list[ExecutionStep] = []
		asm_updated = False
		for step in steps:
			if step.step_type == STEP_ASSEMBLY:
				if "aa_inj" not in step.depends_on:
					step.depends_on = step.depends_on + ["aa_inj"]
				if "aa_inj" not in step.context_from_steps:
					step.context_from_steps = step.context_from_steps + ["aa_inj"]
				asm_updated = True
			updated.append(step)

		log_decision(_logger, "accessibility_audit_injetado",
					 f"aa_inj injetado para addon com geracao de codigo. assembly_atualizado={asm_updated}")

		# Insere accessibility_audit imediatamente antes do assembly
		result: list[ExecutionStep] = []
		for step in updated:
			if step.step_type == STEP_ASSEMBLY:
				result.append(aa_step)
			result.append(step)

		# Fallback: se nao ha assembly, adiciona no final antes de retornar
		if not any(s.step_type == STEP_ASSEMBLY for s in updated):
			result.append(aa_step)

		return result

	def _inject_manifest(self, steps: list[ExecutionStep],
		                    user_query: str, complexity: str = "medium") -> list[ExecutionStep]:
		"""
		Garante que o step manifest_builder esteja sempre presente no plano.

		Bug real achado no teste E2E complexo real (2026-08-07, addon
		AssistenteLeituraGemini): diferente de documentation/assembly/
		accessibility_audit, manifest_builder NUNCA teve rede de seguranca de
		injecao -- se o plano bruto do LLM esquecesse esse step, nada
		corrigia, e o pipeline so descobria isso no FINAL (depois de gastar
		todos os outros steps), com o erro generico "manifest.ini nao foi
		gerado e aprovado". manifest.ini e um dos 2 arquivos absolutamente
		obrigatorios de qualquer addon NVDA (junto de __init__.py) -- essa
		lacuna era mais grave que as ja cobertas por _inject_documentation/
		_inject_assembly/_inject_accessibility_audit. Mesmo padrao de
		insercao (imediatamente antes do assembly, com fallback se assembly
		nao existir).
		"""
		if any(s.step_type == STEP_MANIFEST for s in steps):
			_logger.info("[PLAN] manifest_builder ja presente no plano. Sem injecao.")
			return self._sanitize_manifest_dependencies(steps)

		reasoning_params: dict = {}
		re_effort = _effort_for_complexity(STEP_MANIFEST, complexity)
		if re_effort:
			reasoning_params["reasoning_effort"] = re_effort

		manifest_step = ExecutionStep(
			step_id="mf_inj",
			step_type=STEP_MANIFEST,
			description=(
				f"Gerar manifest.ini do addon a partir do pedido original: {user_query}"
			),
			model_id=_STEP_FALLBACK_MODEL.get(STEP_MANIFEST, _DEFAULT_MODEL),
			reasoning_params=reasoning_params,
			depends_on=[],
			context_from_steps=[],
			expected_output="manifest.ini",
			user_message="Preparando o manifesto do addon...",
			msg_evaluating="Conferindo os campos obrigatorios do manifesto...",
			msg_retrying="Ajustando o manifesto com base nas correções necessárias...",
			msg_escalating="Revisando o manifesto com análise mais aprofundada...",
		)

		# Atualiza assembly para depender de manifest_builder
		updated: list[ExecutionStep] = []
		asm_updated = False
		for step in steps:
			if step.step_type == STEP_ASSEMBLY:
				if "mf_inj" not in step.depends_on:
					step.depends_on = step.depends_on + ["mf_inj"]
				if "mf_inj" not in step.context_from_steps:
					step.context_from_steps = step.context_from_steps + ["mf_inj"]
				asm_updated = True
			updated.append(step)

		log_decision(_logger, "manifest_injetado",
					 f"mf_inj injetado. assembly_atualizado={asm_updated}")

		# Insere manifest_builder imediatamente antes do assembly
		result: list[ExecutionStep] = []
		for step in updated:
			if step.step_type == STEP_ASSEMBLY:
				result.append(manifest_step)
			result.append(step)

		# Fallback: se nao ha assembly, adiciona no final antes de retornar
		if not any(s.step_type == STEP_ASSEMBLY for s in updated):
			result.append(manifest_step)

		return result

	def _sanitize_manifest_dependencies(self, steps: list[ExecutionStep]) -> list[ExecutionStep]:
		"""
		Remove de manifest_builder qualquer depends_on/context_from_steps
		apontando pra steps de CONTEUDO (code_generation, agent_runner,
		agent_template, design_review, web_research) -- manifest.ini so
		precisa do nome/descricao do addon (ja no prompt do step), nunca do
		codigo gerado.

		Bug real achado no teste E2E complexo real (2026-08-09, addon
		AssistenteLeituraGemini, apos generalizar a escalacao cross-provider
		em orchestrator.py 5.37.0): o prompt do planner ja instrui "manifest.ini
		e responsabilidade EXCLUSIVA do step manifest_builder" e "assembly NUNCA
		deve depender de manifest_builder, agent_template, agent_runner ou
		design_review" -- mas nao ha garantia simetrica pro caso oposto: nada
		impedia o plano bruto do LLM de colocar manifest_builder.depends_on=
		[code_generation_id]. Quando isso acontece e code_generation esgota
		TODAS as tentativas (incluindo a escalacao cross-provider, que agora
		tenta ate 5 providers), manifest_builder fica bloqueado pra sempre --
		o pipeline encerra com "steps bloqueados por dependencia" e
		manifest.ini nunca e gerado, mesmo ele nao precisando de nada do
		codigo. So aqui _inject_manifest() ja garantia a PRESENCA do step;
		esta funcao fecha a lacuna simetrica garantindo a INDEPENDENCIA dele.
		"""
		content_step_types = {
			STEP_CODE_GENERATION, STEP_AGENT_RUNNER, STEP_AGENT_TEMPLATE,
			STEP_DESIGN_REVIEW, STEP_WEB_RESEARCH,
		}
		content_ids = {s.step_id for s in steps if s.step_type in content_step_types}
		if not content_ids:
			return steps

		for step in steps:
			if step.step_type != STEP_MANIFEST:
				continue
			removidos = [d for d in step.depends_on if d in content_ids]
			if not removidos:
				continue
			step.depends_on = [d for d in step.depends_on if d not in content_ids]
			step.context_from_steps = [c for c in step.context_from_steps if c not in content_ids]
			step.dependencies = step.depends_on
			log_decision(
				_logger, "manifest_dependencia_removida",
				f"manifest_builder ({step.step_id}) dependia de step(s) de conteudo "
				f"{removidos} -- removido pra evitar deadlock se code_generation/"
				f"agent_runner esgotarem todas as tentativas.",
			)
		return steps

	def _inject_core_step(self, steps: list[ExecutionStep],
		                    user_query: str, complexity: str = "medium") -> list[ExecutionStep]:
		"""
		Garante que exista um step code_generation FINAL que integra todos os
		outros code_generation do plano (o que gera globalPlugins/<addon>/
		__init__.py com a classe GlobalPlugin) -- quando ARCH-010 decompoe o
		pedido em 2+ steps code_generation independentes por feature.

		BUG REAL achado ao vivo (test_e36, GeminiMultimodal, 2026-08-17,
		pedido do Felipe: "corrige isso ai, de uma vez por todas"): o plano
		bruto do LLM tinha manifest_builder + varios code_generation por
		feature (imagem/video/audio) + steps de fix/retry, mas NENHUM deles
		dependia de TODOS os outros -- ou seja, nenhum step assumia o papel
		de "cg_core" que ARCH-010 exige (a mensagem do proprio prompt de
		planejamento ja instrui isso, mas nada verificava se o LLM seguiu).
		O addon final saiu sem __init__.py -- ESTRUTURA-008, o NVDA nunca
		carrega. Diferente de manifest_builder (_inject_manifest, que tem
		step_type proprio e checagem trivial), "e o step core" nao e um
		step_type distinto -- e definido estruturalmente (depende de TODOS
		os outros code_generation). Por isso a deteccao aqui e estrutural,
		nao por step_type: se ha 2+ code_generation E nenhum deles cobre
		todos os outros em depends_on, falta o step core -- injeta um novo,
		dependente de TODOS os code_generation ja planejados, com a lista
		dos subpacotes/modulos que ele deve importar e orquestrar (extraida
		das descricoes/expected_output dos steps ja planejados, disponivel
		em tempo de planejamento, antes de qualquer execucao real).

		Quando ha 0 ou 1 code_generation so, nao ha decomposicao ARCH-010
		acontecendo -- nada a garantir aqui (o unico step, se existir, ja e
		o "core" por definicao, mesmo sem depends_on de irmaos).
		"""
		cg_steps = [s for s in steps if s.step_type == STEP_CODE_GENERATION]
		if len(cg_steps) <= 1:
			return steps

		cg_ids = {s.step_id for s in cg_steps}

		# 2.36.0 -- A CHECAGEM ESTRUTURAL SOZINHA ERA FALSO POSITIVO.
		#
		# Ate aqui bastava um step depender de todos os irmaos para o injetor
		# concluir "core ja presente". Medido nos logs de 22 planejamentos
		# reais: ele NUNCA injetou -- em TODOS os casos achou um integrador e
		# saiu. E os addons sairam sem __init__.py assim mesmo.
		#
		# Motivo: um step que o modelo chamou de `cg_leitura_core` e que
		# depende dos irmaos satisfaz a condicao ESTRUTURAL sem gerar o ponto
		# de entrada. Integrar features e produzir o arquivo que o NVDA carrega
		# sao coisas diferentes, e a checagem so via a primeira.
		#
		# Agora que os steps declaram `target_files` (2.33.0), da para verificar
		# o que importa de verdade: ALGUEM produz o __init__.py na raiz do
		# pacote? Estrutura + alvo declarado, nao um ou outro.
		algum_declara_entrada = any(
			declara_ponto_de_entrada(getattr(s, "target_files", []) or [])
			for s in cg_steps
		)
		algum_integra = any(
			(cg_ids - {s.step_id}) <= set(s.depends_on)
			for s in cg_steps
		)

		# Sem target_files declarado em NENHUM step, a checagem estrutural e
		# tudo que temos -- e o comportamento anterior, preservado para nao
		# injetar um step duplicado em planos que ja funcionavam.
		algum_declara_algo = any(getattr(s, "target_files", []) for s in cg_steps)
		ja_tem_core = (
			algum_declara_entrada if algum_declara_algo else algum_integra
		)

		if ja_tem_core:
			_logger.info(
				"[PLAN] Step core presente (%d code_generation, entrada declarada=%s). "
				"Sem injecao.", len(cg_steps), algum_declara_entrada,
			)
			return steps

		_logger.warning(
			"[PLAN] Nenhum dos %d code_generation gera o ponto de entrada do "
			"addon. Injetando cg_core_inj -- sem ele o NVDA nao carrega nada.",
			len(cg_steps),
		)

		subpacotes = "; ".join(
			f"{s.step_id}: {s.description}" for s in cg_steps
		)

		# Caminho REAL do ponto de entrada, tirado do pacote que os irmaos ja
		# declararam. Deixar o placeholder `<addon>` aqui seria pedir ao modelo
		# que adivinhasse, com o bloco de layout do plano dizendo ao lado o
		# caminho verdadeiro -- duas instrucoes conflitantes no mesmo prompt.
		# Mesma logica de _normalize_expected_files: usa o pacote declarado, e
		# nunca inventa um segundo pacote a partir do nome do addon.
		pacote = ""
		for s in cg_steps:
			for caminho in getattr(s, "target_files", []) or []:
				partes = caminho.split("/")
				if len(partes) >= 3 and partes[0] in NVDA_ENTRY_POINT_DIRS:
					pacote = f"{partes[0]}/{partes[1]}"
					break
			if pacote:
				break
		entrada = f"{pacote}/__init__.py" if pacote else "globalPlugins/<addon>/__init__.py"

		# Contexto NVDA do step injetado. Sem isto ele cai no fallback "sem
		# topicos declarados -> documentacao COMPLETA" (~90k tokens medidos),
		# e este e justamente o step que nao pode falhar por estouro de
		# orcamento. O core importa e orquestra os modulos dos irmaos, entao o
		# contexto de que ele precisa e a UNIAO do que eles declararam, mais o
		# que todo ponto de entrada usa por definicao: scripts (os gestos) e
		# gui (o menu). Uniao, nao intersecao: faltar contexto custa uma
		# tentativa perdida, sobrar custa alguns milhares de tokens.
		topicos_core = {"scripts", "gui"}
		for s in cg_steps:
			topicos_core.update(getattr(s, "nvda_topics", []) or [])

		reasoning_params: dict = {}
		re_effort = _effort_for_complexity(STEP_CODE_GENERATION, complexity)
		if re_effort:
			reasoning_params["reasoning_effort"] = re_effort

		core_step = ExecutionStep(
			step_id="cg_core_inj",
			step_type=STEP_CODE_GENERATION,
			description=(
				f"Gerar SOMENTE {entrada} com a classe GlobalPlugin -- "
				"importa e orquestra os modulos/"
				"subpacotes ja gerados pelos steps a seguir, NAO reimplementa "
				f"a logica deles: {subpacotes}. Pedido original: {user_query}"
			),
			model_id=_STEP_FALLBACK_MODEL.get(STEP_CODE_GENERATION, _DEFAULT_MODEL),
			reasoning_params=reasoning_params,
			depends_on=list(cg_ids),
			context_from_steps=list(cg_ids),
			expected_output=entrada,
			target_files=[entrada] if pacote else [],
			nvda_topics=sorted(topicos_core),
			user_message="Integrando os módulos gerados no ponto de entrada do addon...",
			msg_evaluating="Conferindo se o __init__.py orquestra tudo corretamente...",
			msg_retrying="Ajustando a integração com base nas correções necessárias...",
			msg_escalating="Revisando a integração final com análise mais aprofundada...",
		)

		# Steps que ja dependiam de TODOS os code_generation de feature
		# (ex: assembly, documentation) devem passar a depender tambem do
		# core injetado -- mesmo padrao de _inject_manifest atualizando assembly.
		updated: list[ExecutionStep] = []
		for step in steps:
			if step.step_type in (STEP_ASSEMBLY, STEP_DOCUMENTATION) and cg_ids <= set(step.depends_on):
				if "cg_core_inj" not in step.depends_on:
					step.depends_on = step.depends_on + ["cg_core_inj"]
				if "cg_core_inj" not in step.context_from_steps:
					step.context_from_steps = step.context_from_steps + ["cg_core_inj"]
			updated.append(step)

		log_decision(
			_logger, "core_step_injetado",
			f"cg_core_inj injetado -- {len(cg_steps)} code_generation sem "
			f"nenhum integrando todos os outros (ARCH-010 nao seguido pelo "
			f"plano bruto).",
		)

		# Insere logo apos o ULTIMO code_generation de feature, antes de
		# qualquer step que ja dependa deles (ex: assembly/documentation).
		result: list[ExecutionStep] = []
		inserted = False
		for i, step in enumerate(updated):
			result.append(step)
			is_last_cg = step.step_type == STEP_CODE_GENERATION and not any(
				s.step_type == STEP_CODE_GENERATION for s in updated[i + 1:]
			)
			if is_last_cg and not inserted:
				result.append(core_step)
				inserted = True
		if not inserted:
			result.append(core_step)

		return result

	def _inject_documentation(self, steps: list[ExecutionStep],
		                         complexity: str = "medium") -> list[ExecutionStep]:
		"""
		Garante que o step documentation esteja sempre presente no plano.
		"""
		if any(s.step_type == STEP_DOCUMENTATION for s in steps):
			_logger.info("[PLAN] documentation ja presente no plano. Sem injecao.")
			return steps

		cg_ids = [s.step_id for s in steps if s.step_type == STEP_CODE_GENERATION]
		mf_ids = [s.step_id for s in steps if s.step_type == STEP_MANIFEST]
		doc_depends = cg_ids + mf_ids

		reasoning_params: dict = {}
		re_effort = _effort_for_complexity(STEP_DOCUMENTATION, complexity)
		if re_effort:
			reasoning_params["reasoning_effort"] = re_effort

		doc_step = ExecutionStep(
			step_id="doc_inj",
			step_type=STEP_DOCUMENTATION,
			description=(
				"Gerar guia do usuario em HTML acessivel (pt_BR + en). "
				"O NVDA nao exibe ajuda sem esse arquivo."
			),
			model_id=_STEP_FALLBACK_MODEL.get(STEP_DOCUMENTATION, _DEFAULT_MODEL),
			reasoning_params=reasoning_params,
			depends_on=doc_depends,
			context_from_steps=doc_depends,
			expected_output="doc/pt_BR/userGuide.html",
			user_message="Escrevendo a documentação para o usuário...",
			msg_evaluating="Conferindo se a documentação está completa e acessível...",
			msg_retrying="Ajustando a documentação com base nas correções necessárias...",
			msg_escalating="Revisando a documentação com análise mais aprofundada...",
		)

		# Atualiza assembly para depender de documentation
		updated: list[ExecutionStep] = []
		asm_updated = False
		for step in steps:
			if step.step_type == STEP_ASSEMBLY:
				if "doc_inj" not in step.depends_on:
					step.depends_on = step.depends_on + ["doc_inj"]
				if "doc_inj" not in step.context_from_steps:
					step.context_from_steps = step.context_from_steps + ["doc_inj"]
				asm_updated = True
			updated.append(step)

		log_decision(_logger, "documentation_injetado",
					 f"doc_inj injetado. assembly_atualizado={asm_updated}")

		# Insere documentation imediatamente antes do assembly
		result: list[ExecutionStep] = []
		for step in updated:
			if step.step_type == STEP_ASSEMBLY:
				result.append(doc_step)
			result.append(step)

		# Fallback: se nao ha assembly, adiciona no final antes de retornar
		if not any(s.step_type == STEP_ASSEMBLY for s in updated):
			result.append(doc_step)

		return result

	def _inject_assembly(self, steps: list[ExecutionStep],
	                     complexity: str = "medium") -> list[ExecutionStep]:
		"""
		Garante que assembly seja sempre o ultimo step do plano.
		"""
		if any(s.step_type == STEP_ASSEMBLY for s in steps):
			_logger.info("[PLAN] assembly ja presente no plano. Sem injecao.")
			return steps

		all_ids = [s.step_id for s in steps]
		reasoning_params: dict = {}
		re_effort = _effort_for_complexity(STEP_ASSEMBLY, complexity)
		if re_effort:
			reasoning_params["reasoning_effort"] = re_effort

		asm = ExecutionStep(
			step_id="asm_inj",
			step_type=STEP_ASSEMBLY,
			description=(
				"Montar e empacotar todos os artefatos do addon em estrutura "
				"NVDA-compativel: globalPlugins/, manifest.ini e doc/."
			),
			model_id=_STEP_FALLBACK_MODEL.get(STEP_ASSEMBLY, _DEFAULT_MODEL),
			reasoning_params=reasoning_params,
			depends_on=all_ids,
			context_from_steps=all_ids,
			expected_output=(
				"Estrutura completa do addon com globalPlugins/, manifest.ini e doc/. "
				"Pronto para instalacao no NVDA."
			),
			max_retries=3,
			user_message="Empacotando todos os arquivos do addon...",
			msg_evaluating="Verificando se todos os arquivos foram incluídos corretamente...",
			msg_retrying="Reajustando o empacotamento após corrigir os erros...",
			msg_escalating="Aplicando análise mais profunda ao empacotamento final...",
		)
		log_decision(
			_logger, "assembly_injetado",
			f"asm_inj injetado ao final do plano ({len(steps)} steps anteriores)"
		)
		return steps + [asm]

	def _inject_engineering_review(
		self, steps: list[ExecutionStep], complexity: str = "medium",
	) -> list[ExecutionStep]:
		"""
		Injeta engineering_review depois de TODOS os code_generation, antes do
		assembly.

		POR QUE ESTE STEP EXISTE (auditoria 2026-08-29): todo o julgamento de
		qualidade do pipeline era conformidade a REGRA CATALOGADA -- as ~50
		regras NVDA/WX-A11Y/ARCH do rule_registry. Isso cobre o que e
		catalogavel, mas engenharia e o que sobra quando o catalogo acaba:
		fronteira de modulo errada, abstracao prematura, erro engolido,
		recurso sem dono, codigo impossivel de testar. Nenhum ID descreve
		esses defeitos e nenhum agente os procurava.

		Logica deterministica (Regra 5), igual aos outros injetores:
		- so injeta se existe code_generation no plano (sem codigo, nada a
		  revisar);
		- nao duplica se ja houver engineering_review;
		- depende de TODOS os code_generation, nao de um so -- um defeito de
		  engenharia tipico (duas features gravando a mesma config, camada
		  duplicada entre modulos) so e visivel olhando o conjunto. E a
		  diferenca deliberada em relacao a _inject_syntax_validation, que
		  injeta um sv_ POR step porque sintaxe e local por natureza.

		Roda com o modelo leve: apply_model_budget() so eleva
		code_generation, e critica/auditoria usam o leve por decisao do
		README Regra 8 -- este step nao consome o orcamento de 20%.
		"""
		if any(s.step_type == STEP_ENGINEERING_REVIEW for s in steps):
			_logger.info("[PLAN] engineering_review ja presente no plano. Sem injecao.")
			return steps

		cg_ids = [s.step_id for s in steps if s.step_type == STEP_CODE_GENERATION]
		if not cg_ids:
			return steps

		reasoning_params: dict = {}
		re_effort = _effort_for_complexity(STEP_ENGINEERING_REVIEW, complexity)
		if re_effort:
			reasoning_params["reasoning_effort"] = re_effort

		er_step = ExecutionStep(
			step_id="er_inj",
			step_type=STEP_ENGINEERING_REVIEW,
			description=(
				"Revisar a ENGENHARIA do codigo gerado, nao a conformidade a regras "
				"(essa ja e auditada em outros steps): defeitos de estrutura, erro "
				"engolido, operacao externa sem timeout, recurso criado sem fim de "
				"vida, complexidade que o addon nao precisa, logica impossivel de "
				"testar sem o NVDA real e risco na proxima mudanca."
			),
			model_id=_STEP_FALLBACK_MODEL.get(STEP_ENGINEERING_REVIEW, _DEFAULT_MODEL),
			reasoning_params=reasoning_params,
			depends_on=cg_ids,
			context_from_steps=cg_ids,
			expected_output=(
				"Revisao de engenharia com DEFEITOS DE ENGENHARIA, COMPLEXIDADE "
				"DESNECESSARIA, TESTABILIDADE, RISCO DE EVOLUCAO e "
				"VEREDITO_ENGENHARIA (SOLIDO | AJUSTES_RECOMENDADOS | REESTRUTURAR)."
			),
			max_retries=1,
			user_message="Revisando a qualidade de engenharia do código...",
			msg_evaluating="Conferindo se a revisão de engenharia está completa...",
			msg_retrying="Refinando a revisão de engenharia...",
			msg_escalating="Aprofundando a revisão de engenharia...",
		)

		# Assembly passa a depender do review -- mesmo padrao (e mesmo motivo)
		# de _inject_accessibility_audit: sem isso, um plano que ja trouxesse
		# assembly proprio faria o addon ser empacotado ANTES da revisao rodar,
		# quebrando a invariante "assembly e sempre o ultimo step".
		updated: list[ExecutionStep] = []
		asm_updated = False
		for step in steps:
			if step.step_type == STEP_ASSEMBLY:
				if "er_inj" not in step.depends_on:
					step.depends_on = step.depends_on + ["er_inj"]
				if "er_inj" not in step.context_from_steps:
					step.context_from_steps = step.context_from_steps + ["er_inj"]
				asm_updated = True
			updated.append(step)

		log_decision(
			_logger, "engineering_review_injetado",
			f"er_inj injetado apos {len(cg_ids)} code_generation. assembly_atualizado={asm_updated}",
		)

		# Insere imediatamente antes do assembly.
		result: list[ExecutionStep] = []
		for step in updated:
			if step.step_type == STEP_ASSEMBLY:
				result.append(er_step)
			result.append(step)

		# Sem assembly no plano, entra no fim -- ainda depois de todo
		# code_generation, que e a unica ordem que importa aqui.
		if not asm_updated:
			result.append(er_step)
		return result

	def _inject_syntax_validation(self, steps: list[ExecutionStep],
	                                    complexity: str = "medium") -> list[ExecutionStep]:
		"""
		Injeta syntax_validation imediatamente apos cada code_generation step.
		"""
		result: list[ExecutionStep] = []
		sv_counter = 0
		sv_id_map: dict[str, str] = {}

		for step in steps:
			result.append(step)
			if step.step_type == STEP_CODE_GENERATION:
				sv_counter += 1
				sv_id = f"sv_{sv_counter}"
				sv_id_map[step.step_id] = sv_id
				reasoning_params: dict = {}
				re_effort = _effort_for_complexity(STEP_SYNTAX_VALIDATION, complexity)
				if re_effort:
					reasoning_params["reasoning_effort"] = re_effort
				sv_step = ExecutionStep(
					step_id=sv_id,
					step_type=STEP_SYNTAX_VALIDATION,
					description=(
						f"Validar sintaxe Python do codigo gerado em {step.step_id}. "
						"Usa AST local (ast.parse) — zero chamadas de rede. "
						"Verifica SyntaxError — nao executa o addon."
					),
					model_id=_STEP_FALLBACK_MODEL.get(STEP_SYNTAX_VALIDATION, _DEFAULT_MODEL),
					reasoning_params=reasoning_params,
					depends_on=[step.step_id],
					context_from_steps=[step.step_id],
					expected_output=(
						"RESULTADO: PASS — codigo sintaticamente valido. "
						"OU RESULTADO: FAIL com lista de erros. "
						"OU RESULTADO: SKIP — nenhum bloco Python encontrado."
					),
					max_retries=1,
					user_message="Verificando sintaxe do código gerado...",
					msg_evaluating="Analisando resultado da validação de sintaxe...",
					msg_retrying="Revalidando código corrigido...",
					msg_escalating="Aplicando validação mais rigorosa...",
				)
				result.append(sv_step)

		# Atualiza steps que dependem de code_generation para tambem depender de sv_
		# para que o contexto do relatorio de validacao chegue a eles
		final: list[ExecutionStep] = []
		for step in result:
			if step.step_type not in (STEP_CODE_GENERATION, STEP_SYNTAX_VALIDATION):
				new_depends = list(step.depends_on)
				new_ctx = list(step.context_from_steps)
				for cg_id, sv_id in sv_id_map.items():
					if cg_id in step.depends_on and sv_id not in new_depends:
						new_depends.append(sv_id)
					if cg_id in step.context_from_steps and sv_id not in new_ctx:
						new_ctx.append(sv_id)
				step.depends_on = new_depends
				step.context_from_steps = new_ctx
			final.append(step)

		log_decision(_logger, "syntax_validation_injetado",
					 f"{sv_counter} step(s) sv_ injetados apos code_generation(s)")
		return final

	def _call_planner_llm(self, query: str, domain_ctx=None, on_narration_chunk=None) -> str:
		"""
		Chama LLM do planner. Dois caminhos:

		- on_narration_chunk=None (default): json_schema structured output.
		  json_schema garante que os campos obrigatorios estejam sempre
		  presentes, sem precisar de parsing extra ou fallback por campos
		  ausentes. Mas json_schema forca a resposta INTEIRA a seguir o
		  schema -- nao da pra misturar narracao solta no meio, entao esse
		  caminho fica mudo.
		- on_narration_chunk=<callback>: pede o plano via TOOL CALL
		  obrigatoria ("entregar_plano") em vez de json_schema. O modelo
		  narra livre no content (visivel ao vivo via on_narration_chunk,
		  como on_chunk normal) ANTES de chamar a tool, e o plano
		  estruturado vem do argumento dela -- mesmo padrao "final answer as
		  tool call" usado pelos sub-agentes de prosa crua
		  (sub_agents/_base.py final_tool). O parametro da tool reusa o
		  MESMO dict de schema que o caminho json_schema ja usa, entao o
		  contrato de retorno (JSON string) e identico nos dois caminhos --
		  _parse_plan()/_build_steps() nao sabem nem precisam saber qual
		  caminho foi usado.
		"""
		from ..gui.settings_panel import get_llm_provider, get_llm_model
		provider = get_llm_provider()
		model = get_llm_model()

		# 2026-08-26: create_plan() exige JSON estrito (_PLAN_SCHEMA, o maior e
		# mais critico schema do projeto -- a estrutura inteira do plano
		# depende dele), mas seguia o tier "heavy" do provider ATIVO do
		# usuario. No Ollama (default), NENHUM modelo da conta segue
		# json_schema de verdade (auditoria ao vivo, ver model_registry.py::
		# get_structured_output_model()) -- so heavy_model/light_model
		# (usados nas DESCRICOES de model_id dentro do proprio schema, pra
		# os STEPS do plano gerado) continuam seguindo o provider ativo do
		# usuario, sem mudanca: isso e sobre qual modelo executa os steps,
		# nao sobre qual modelo gera o JSON do plano.
		from ..ai.model_registry import get_structured_output_model
		planner_model = get_structured_output_model(0)

		# Descreve os modelos efetivos do provider atual, ja passando pelo catalogo
		# Hermes quando "Alto" esta ativo.
		heavy_model = resolve_provider_tier_model(provider, "heavy", model)
		light_model = resolve_provider_tier_model(provider, "light", model)

		if not is_alto_model(model):
			model_description = f"Modelo LLM para este step. Use obrigatoriamente: {model}"
		else:
			model_description = (
				f"Modelo LLM para este step. Use {heavy_model} somente para code_generation e {light_model} "
				f"para os demais passos. A aplicação aplicará um orçamento máximo de 20% de steps pesados."
			)

		# Explainability (2026-08-03): domain_ctx era calculado na fase PESQUISA
		# do orchestrator mas nunca chegava ate aqui -- create_plan() so recebia
		# user_query, entao o plano era montado cego pra pesquisa que acabou de
		# rodar. Injeta o mesmo domain_text ja usado em replan_with_feedback()
		# (arquitetura/boas praticas/seguranca reais, nao inventadas) e pede pro
		# plan_presentation explicar o "porque" das escolhas grounded nisso, em
		# vez de so listar passos.
		domain_text = ""
		if domain_ctx:
			domain_text = (
				f"\n\nContexto do dominio (pesquisado nesta sessao):\n"
				f"Dominio: {domain_ctx.domain}\n"
				f"Descricao: {domain_ctx.description}\n"
				f"APIs envolvidas: {', '.join(domain_ctx.apis_involved)}\n"
				f"Boas praticas aplicaveis: {', '.join(domain_ctx.best_practices)}\n"
				f"Requisitos de seguranca: {', '.join(domain_ctx.security_requirements)}\n"
				f"Padroes de arquitetura recomendados: {', '.join(domain_ctx.architecture_patterns)}\n"
			)

		full_prompt = _PLAN_SYSTEM_PROMPT + domain_text + "\n\nPedido do usuario: " + query

		# Schema JSON obrigatorio para o Planner
		_PLAN_SCHEMA = {
			"type": "json_schema",
			"json_schema": {
				"name": "execution_plan",
				"schema": {
					"type": "object",
					"properties": {
						"addon_name":             {"type": "string", "description": "Nome canonico do addon em CamelCase sem espacos, sem acentos, sem hifen. Ex: GmailSummarizer, TranscriadorIA, AnuncioTitulo. ESTE NOME SERA USADO EM TODOS OS STEPS — globalPlugins/<addon_name>/, campo name do manifest.ini, e completed_message. Nunca use nomes diferentes em steps diferentes. Mesmo quando project_type='controller_client' (nao ha globalPlugins/ nem manifest.ini nesse caso), ainda use este campo como o nome do PROGRAMA/PROJETO."},
						"project_type":           {"type": "string", "enum": ["addon", "controller_client"], "description": "Julgamento semantico, nao por palavra-chave: 'addon' (padrao, quase sempre correto) e um addon NVDA tradicional que RODA DENTRO do processo do NVDA (GlobalPlugin/AppModule/driver de sintese ou braille), carregado pelo addonHandler via manifest.ini. 'controller_client' e um PROGRAMA EXTERNO E SEPARADO -- um .exe/script Windows que roda FORA do NVDA e usa a Controller Client API (nvdaControllerClient.dll) para mandar o NVDA falar/exibir em braile a partir de outro processo (o mesmo mecanismo usado por apps reais como TWBlue). So escolha 'controller_client' quando o pedido do usuario for inequivoco sobre querer um programa/aplicativo SEPARADO do NVDA que controla a fala do NVDA de fora -- nao um addon que roda dentro dele. Na duvida, 'addon' e o caso comum."},
						"complexity":             {"type": "string", "enum": ["low", "medium", "high"], "description": "Complexidade estimada do addon: low=script simples sem GUI, medium=addon com dialog ou API, high=multi-arquivo com agente IA ou driver NVDA"},
						"requires_web_research":  {"type": "boolean", "description": "True se o addon integrar com uma biblioteca, API ou servico externo cujos detalhes exatos (endpoints, parametros, formato de autenticacao, SDK) voce nao tem certeza absoluta de conhecer atualizados -- isso inclui provedores de IA/LLM, especialmente os menos difundidos ou lancados/atualizados recentemente, onde o conhecimento de treinamento pode estar desatualizado ou incompleto. Na duvida, prefira true: pesquisar custa pouco, inventar um endpoint ou parametro errado gera codigo que nao funciona."},
						"requires_agent_runner":  {"type": "boolean", "description": "True se o addon incluir um agente IA que processa solicitacoes em runtime (usa LLM/IA internamente)"},
						"intro_message":          {"type": "string", "description": "Frase natural e calorosa confirmando o que foi entendido do pedido do usuário, em português. Reescreva com as próprias palavras — nunca copie trechos crus da query original. Ex: 'Beleza! Entendi que você quer um addon que resume e-mails do Gmail automaticamente.'"},
						"plan_presentation":      {"type": "string", "description": "Mensagem completa, natural e específica que será mostrada ao usuário. Confirme o entendimento, explique todas as etapas em linguagem simples e convide a aprovar, pedir mudanças ou cancelar com palavras livres. Pode numerar etapas quando ajudar. Quando o contexto de domínio (pesquisado nesta sessão) tiver padrões de arquitetura, boas práticas ou requisitos de segurança relevantes, inclua uma frase curta explicando POR QUE essas escolhas foram feitas (ex: 'vou separar a lógica da API num arquivo próprio porque isso facilita trocar de provedor depois') — grounded no que foi pesquisado de verdade, nunca invente uma justificativa genérica. Não use molde genérico, títulos, marcadores, Markdown, emojis, três hífens, três asteriscos, nomes internos, classificações ou raciocínio privado."},
						"approval_message":       {"type": "string", "description": "Confirmação curta, natural e específica de que a criação deste addon vai começar. Sem Markdown, emojis ou texto de sistema."},
						"cancellation_message":   {"type": "string", "description": "Confirmação curta e natural de que a criação deste addon foi cancelada. Sem Markdown, emojis ou texto de sistema."},
						"modification_message":   {"type": "string", "description": "Confirmação curta e natural de que o plano deste addon será ajustado conforme o pedido do usuário. Não invente o ajuste futuro. Sem Markdown ou emojis."},
						"assembling_message":     {"type": "string", "description": "Mensagem em português, max 90 chars, para o usuário enquanto os arquivos são reunidos. Ex: 'Reunindo os arquivos do addon...'"},
						"completed_message":      {"type": "string", "description": "Mensagem em português descrevendo o que foi criado. Ex: 'Pronto! Criei o TranscriadorIA com suporte a Whisper.'"},
						"replan_message":         {"type": "string", "description": "Mensagem em portugues para quando o plano precisa ser revisado. Ex: 'Encontramos problemas. Revisando a abordagem...'"},
						"expected_files":         {"type": "array", "items": {"type": "string"}, "description": "Lista COMPLETA dos arquivos que o addon vai ter, com caminho relativo a raiz do addon. Declare o esqueleto ANTES da geracao -- os steps de code_generation vao preencher exatamente estes arquivos, em vez de inventar nomes. OBRIGATORIO para project_type='addon': incluir o ponto de entrada que o NVDA carrega, que e SEMPRE um destes: globalPlugins/<AddonName>/__init__.py (o caso comum), appModules/<executavel>.py, synthDrivers/<nome>.py ou brailleDisplayDrivers/<nome>.py. O NVDA carrega addon por convencao de caminho: num pacote em globalPlugins/, SO o __init__.py e carregado e qualquer outro .py ao lado dele e ignorado -- um addon sem esse arquivo instala sem erro e simplesmente nao faz nada. Inclua tambem manifest.ini e os modulos auxiliares (servicos, dialogos, configSpec.py, settings_panel.py) que o addon precisar. Nunca use nomes genericos como module_1.py."},
						"expected_gestures":      {"type": "array", "items": {"type": "string"}, "description": "Lista dos atalhos de teclado que o addon DEVE expor, no formato de gesture do NVDA (ex: \"kb:NVDA+h\", \"kb:control+shift+m\"). Preencha SOMENTE com atalhos que o usuario realmente pediu ou que sao inequivocamente necessarios para a funcionalidade solicitada -- este campo vira uma VERIFICACAO OBRIGATORIA: o codigo gerado sera reprovado se um atalho declarado aqui nao existir como @script(gesture=...) no addon. Nunca liste um atalho que o usuario pediu para NAO usar, nem invente atalhos 'extras' que ninguem pediu. Lista vazia quando o addon nao tem atalho de teclado (ex: so um item de menu, so um AppModule que reage a eventos, ou project_type='controller_client')."},
						"dependencies":           {"type": "array", "items": {"type": "string", "description": "Nome EXATO do pacote no PyPI — NAO o nome do modulo Python. Ex: 'google-api-python-client' (NAO 'googleapiclient'), 'google-auth-oauthlib' (NAO 'google.auth'), 'Pillow' (NAO 'PIL'). Nunca inclua stdlib (os, sys, webbrowser, json, threading), modulos NVDA (nvda, nvdaHelper, ui, api, wx, addonHandler) nem submódulos (google.auth.transport.requests — isso nao e pacote pip)."}, "description": "Pacotes pip externos para bundle em runtime. Lista vazia se nenhum pacote externo for necessario."},
						"steps": {
							"type": "array",
							"description": "Lista ordenada de steps de execucao. Sempre incluir code_generation, manifest_builder, documentation e assembly (nesta ordem logica).",
							"items": {
								"type": "object",
								"properties": {
									"step_id":           {"type": "string", "description": "ID unico do step, ex: 's1', 'cg1', 'asm1'. Usado em depends_on de outros steps."},
									"step_type":         {"type": "string", "description": "Tipo do step. Bug real: sem enum, um sinonimo/typo alucinado pela IA (ex: 'test_generator' em vez de 'test_generation') derrubava o dispatcher com ValueError sem chance de retry, abortando o pipeline inteiro.", "enum": ["code_generation", "manifest_builder", "documentation", "assembly", "accessibility_audit", "test_generation", "web_research", "design_review", "agent_template", "agent_runner", "syntax_validation", "user_clarification"]},
									"model_id":          {"type": "string", "description": model_description},
									"reasoning_effort":  {"type": ["string", "null"], "description": "Nivel de raciocinio: 'high' (auditoria, critica, design_review, codigo complexo), 'medium' (codigo simples, testes, agent_runner), null (manifest, assembly, doc). Omita se null."},
									"description":       {"type": "string", "description": "O que este step deve fazer, detalhado. Inclui qual arquivo gerar, quais APIs usar, quais regras seguir."},
									"expected_output":   {"type": "string", "description": "O que se espera como resultado. Ex: 'Codigo Python do GlobalPlugin com SettingsPanel' ou 'manifest.ini correto'"},
									"user_message":      {"type": "string", "description": "Mensagem curta e natural em portugues para o usuario. Max 90 chars. Ex: 'Gerando o codigo principal do addon...'"},
									"msg_evaluating":    {"type": "string", "description": "Mensagem enquanto o resultado e verificado. Ex: 'Conferindo se o codigo segue as diretrizes do NVDA...'"},
									"msg_retrying":      {"type": "string", "description": "Mensagem ao tentar novamente. Ex: 'Ajustando o codigo com base nos problemas encontrados...'"},
									"msg_escalating":    {"type": "string", "description": "Mensagem ao usar analise mais aprofundada. Ex: 'Aplicando revisao mais cuidadosa para resolver os problemas...'"},
									"nvda_topics":      {"type": "array", "items": {"type": "string"}, "description": "Topicos de contexto NVDA que ESTE step precisa para gerar seu(s) arquivo(s). Valores validos: scripts (atalhos, @script, captura de teclado), gui (dialogos wx, SettingsPanel), config (persistir preferencias em config.conf), objects (arvore de objetos e eventos do NVDA), speech (fala, prioridades, tons), appmodule (addon de aplicativo especifico), system (timers, restart, extension points). Declare SO os que o arquivo realmente usa: cada topico a mais custa dezenas de milhares de tokens em TODA tentativa deste step, e um step que estoura o orcamento impede os seguintes de rodar. Um cliente HTTP puro geralmente nao precisa de nenhum; um settings_panel.py precisa de gui e config; o __init__.py do plugin costuma precisar de scripts e gui. Lista vazia faz o step receber o contexto COMPLETO (mais caro, use so se estiver realmente em duvida)."},
									"target_files":      {"type": "array", "items": {"type": "string"}, "description": "Arquivos que ESTE step deve produzir, escolhidos de expected_files. OBRIGATORIO para step_type='code_generation': liste no MAXIMO 2 arquivos por step. Um step que tenta produzir uma feature inteira de uma vez (servico + dialogo + painel de configuracao + testes) e reprovado por entrega parcial e custa 3x mais que um step focado -- medido em execucao real. Divida por ARQUIVO, nao por funcionalidade: cada arquivo do layout vira um step, e os steps dependem uns dos outros via depends_on. Deixe vazio para steps que nao escrevem arquivo (web_research, design_review, accessibility_audit)."},
									"depends_on":        {"type": "array", "items": {"type": "string"}, "description": "IDs dos steps que devem estar prontos antes deste. Ex: ['s1', 's2']"},
									"context_from_steps":{"type": "array", "items": {"type": "string"}, "description": "IDs cujos outputs sao passados como contexto para este step. Geralmente igual a depends_on."},
								},
								# 2026-09-01: `target_files` e `nvda_topics` estavam declarados
								# nas properties e FORA do required. Com additionalProperties=False,
								# campo fora do required e opcional -- e o modelo simplesmente
								# omitia os dois. Medido nos 486 prompts logados de 2 rodadas E2E:
								# o marcador [NVDA-TOPICS:...] nunca apareceu, e o guarda de
								# decomposicao contava zero arquivos. Duas correcoes ficaram INERTES
								# por isso -- declarar no schema nao e o mesmo que ser preenchido.
								"required": ["step_id", "step_type", "model_id",
											 "description", "expected_output", "user_message",
											 "msg_evaluating", "msg_retrying", "msg_escalating",
											 "depends_on", "context_from_steps",
											 "target_files", "nvda_topics"],
								"additionalProperties": False,
							}
						}
					},
					"required": ["addon_name", "project_type", "complexity", "requires_web_research", "requires_agent_runner",
								 "intro_message", "plan_presentation", "approval_message",
								 "cancellation_message", "modification_message", "assembling_message",
								 "completed_message", "replan_message",
								 "expected_files", "expected_gestures", "dependencies", "steps"],                    "additionalProperties": False,
				}
			}
		}

		try:
			client = create_llm_client(model_id=planner_model)
			if on_narration_chunk:
				tool_name = "entregar_plano"
				tool = {
					"type": "function",
					"function": {
						"name": tool_name,
						"description": "Entrega o plano de execucao completo, com todos os campos obrigatorios preenchidos.",
						"parameters": cast(dict[str, Any], _PLAN_SCHEMA["json_schema"])["schema"],
					},
				}
				narrated_prompt = (
					full_prompt + "\n" + _TOOL_PREAMBLE_INSTRUCTION
					+ "\n" + _FINAL_TOOL_INSTRUCTION.format(tool_name=tool_name)
				)
				resp = client.chat(
					narrated_prompt,
					reasoning_effort="high",
					tools=[tool],
					on_chunk=on_narration_chunk,
				)
				return _plan_json_from_tool_call(resp)
			resp = client.chat(
				full_prompt,
				reasoning_effort="high",
				response_format=_PLAN_SCHEMA,
			)
			return resp.content or ""
		except LLMClientError as exc:
			_logger.warning("[AVISO] Planner: falhou com modelo %s. %s", planner_model, exc)
			raise

	def _parse_plan(self, raw: str) -> dict:
		clean = raw.strip()
		# Remove markdown se presente
		clean = re.sub(r"^```(?:json)?\n?", "", clean)
		clean = re.sub(r"\n?```$", "", clean)
		try:
			return json.loads(clean)
		except json.JSONDecodeError as exc:
			_logger.error("[ERRO] Planner: JSON invalido recebido. Usando plano minimo. Erro: %s", exc)
			return self._minimal_plan()

	def _build_steps(
		self, raw_steps: list, complexity: str = "medium",
		model_overrides: dict[str, str] | None = None,
	) -> list[ExecutionStep]:
		from ..gui.settings_panel import get_llm_provider, get_llm_model
		provider = get_llm_provider()
		configured_model = get_llm_model()

		steps: list[ExecutionStep] = []
		for raw in raw_steps:
			stype = raw.get("step_type", STEP_CODE_GENERATION)
			raw_model = raw.get("model_id", "").strip()

			if model_overrides and stype in model_overrides:
				# Cross-model escalation (replan pos-falha): forca um modelo
				# diferente do que ja falhou, em vez da resolucao dinamica
				# normal -- modelos diferentes tem modos de falha
				# complementares (pratica 2026 validada).
				raw_model = model_overrides[stype]
			elif complexity == "low":
				raw_model = resolve_provider_tier_model(provider, "light", configured_model)
			elif stype not in _STEP_FALLBACK_MODEL:
				# Fallback deterministico para tipos desconhecidos (retrocompatibilidade)
				raw_model = _DEFAULT_MODEL
			elif is_alto_model(configured_model) or is_alto_model(raw_model):
				raw_model = resolve_step_model(stype, provider, configured_model)
			else:
				raw_model = configured_model

			raw_reasoning = raw.get("reasoning_effort")
			if raw_reasoning and raw_reasoning not in ("high", "medium"):
				raw_reasoning = None
			reasoning_params: dict = {}
			if raw_reasoning:
				reasoning_params["reasoning_effort"] = raw_reasoning
			steps.append(ExecutionStep(
				step_id=raw.get("step_id", f"s{len(steps)+1}"),
				step_type=stype,
				description=raw.get("description", ""),
				model_id=raw_model,
				reasoning_params=reasoning_params,
				depends_on=raw.get("depends_on", []),
				context_from_steps=raw.get("context_from_steps", []),
				expected_output=raw.get("expected_output", ""),
				target_files=raw.get("target_files", []),
				# 2.37.0 -- `nvda_topics` era declarado no dataclass, exigido no
				# schema e consumido pelo orchestrator, mas NUNCA lido aqui: o
				# escopo de contexto por topico ficava inerte em todo step vindo
				# do plano do modelo. Mesmo padrao que ja mordeu duas vezes nesta
				# sessao -- a peca certa existe e esta desligada de quem decide.
				nvda_topics=_topicos_com_piso(
					_normalize_nvda_topics(raw.get("nvda_topics", [])),
					stype, raw.get("target_files", []) or [],
				),
				max_retries=_MAX_RETRIES_BY_STEP_TYPE.get(stype, _MAX_RETRIES_PADRAO),
				user_message=raw.get("user_message", ""),
				msg_evaluating=raw.get("msg_evaluating", ""),
				msg_retrying=raw.get("msg_retrying", ""),
				msg_escalating=raw.get("msg_escalating", ""),
			))
		return steps

	def format_plan_for_user(self, plan: ExecutionPlan, domain_ctx=None) -> str:
		"""
		Retorna a apresentação conversacional escrita pelo próprio Planner.

		O programa não remonta a resposta com um template fixo. Planos antigos ou
		degradados recebem apenas um fallback seguro e legível.
		"""
		presentation = plan.plan_presentation.strip() if plan.plan_presentation else ""
		if presentation:
			return presentation

		intro = plan.intro_message.strip() if plan.intro_message else ""
		step_messages = [
			step.user_message.strip()
			for step in plan.steps
			if step.user_message and step.user_message.strip()
		]
		parts = [part for part in [intro, *step_messages] if part]
		return "\n\n".join(parts) or "O plano está pronto para sua decisão."

	def replan_with_feedback(
		self,
		original_query: str,
		user_feedback: str,
		domain_ctx=None,
		on_narration_chunk=None,
	) -> ExecutionPlan:
		"""
		Replaneja o addon com base no feedback do usuario sobre o plano anterior.

		Diferente de replan() — que e chamado quando um step falha —
		este metodo e chamado quando o usuario quer MODIFICAR o plano
		antes da execucao comecar.

		v2.0.0 (2026-05-15): Pipeline conversacional.
		"""
		_logger.info("[Planner] Replanejando com feedback do usuario: %s", user_feedback[:100])

		domain_text = ""
		if domain_ctx:
			domain_text = (
				f"\n\nContexto do dominio (pesquisado anteriormente):\n"
				f"Dominio: {domain_ctx.domain}\n"
				f"Descricao: {domain_ctx.description}\n"
				f"APIs: {', '.join(domain_ctx.apis_involved)}\n"
				f"Boas praticas: {', '.join(domain_ctx.best_practices)}\n"
				f"Seguranca: {', '.join(domain_ctx.security_requirements)}\n"
			)

		replan_prompt = (
			f"Tarefa original do usuario: {original_query}\n\n"
			f"O usuario revisou o plano anterior e pediu as seguintes mudancas:\n"
			f"{user_feedback}\n"
			f"{domain_text}\n\n"
			f"Gere um NOVO plano completo que incorpore o feedback do usuario.\n"
			f"Mantenha o que o usuario gostou e ajuste apenas o que ele pediu para mudar.\n"
			f"Retorne o JSON completo do plano (todos os campos obrigatorios)."
		)

		try:
			raw = self._call_planner_llm(replan_prompt, on_narration_chunk)
			plan_data = self._parse_plan(raw)
			steps = self._build_steps(plan_data.get("steps", []))
			complexity = plan_data.get("complexity", "medium")
			project_type = plan_data.get("project_type", "addon")

			# Injeta steps obrigatorios (2.26.0: so pra project_type=="addon",
			# mesmo motivo do create_plan() acima)
			if complexity == "high" and project_type == "addon":
				steps = self._inject_design_review(steps, original_query, complexity)
			if project_type == "addon":
				steps = self._inject_accessibility_audit(steps, original_query, complexity)
				steps = self._inject_manifest(steps, original_query, complexity)
				steps = self._inject_core_step(steps, original_query, complexity)
			steps = self._inject_documentation(steps, complexity)
			steps = self._inject_syntax_validation(steps, complexity)
			if project_type == "addon":
				steps = self._inject_engineering_review(steps, complexity)
			steps = self._inject_assembly(steps, complexity)

			from ..gui.settings_panel import get_llm_provider, get_llm_model
			provider = get_llm_provider()
			configured_model = get_llm_model()

			apply_model_budget(steps, provider, configured_model, complexity=complexity)

			raw_addon_name = plan_data.get("addon_name", "").strip()
			if not raw_addon_name:
				raw_addon_name = re.sub(r"[^\w]", "_", original_query[:30]).strip("_") or "MeuAddon"

			plan = ExecutionPlan(
				plan_id=str(uuid.uuid4())[:8],
				original_query=original_query,
				steps=steps,
				addon_name=raw_addon_name,
				project_type=project_type,
				requires_web_research=plan_data.get("requires_web_research", False),
				requires_agent_runner=plan_data.get("requires_agent_runner", False),
				estimated_complexity=complexity,
				step_model_map=dict(COMPLEXITY_MAP.get(complexity, COMPLEXITY_MAP["medium"])),
				intro_message=plan_data.get("intro_message", ""),
				plan_presentation=plan_data.get("plan_presentation", ""),
				approval_message=plan_data.get("approval_message", ""),
				cancellation_message=plan_data.get("cancellation_message", ""),
				modification_message=plan_data.get("modification_message", ""),
				assembling_message=plan_data.get("assembling_message", "Montando o addon..."),
				completed_message=plan_data.get("completed_message", "Addon criado com sucesso!"),
				replan_message=plan_data.get("replan_message", "Encontramos problemas. Revisando a abordagem..."),
				expected_files=_normalize_expected_files(
					plan_data.get("expected_files", []),
					plan_data.get("addon_name", ""),
					plan_data.get("project_type", "addon"),
				),
				expected_gestures=_normalize_gestures(plan_data.get("expected_gestures", [])),
				dependencies=plan_data.get("dependencies", []),
			)
			log_decision(_logger, "replan_com_feedback", f"novos_steps={len(steps)}")
			return plan
		except Exception as exc:
			_logger.error("[ERRO] Planner.replan_with_feedback falhou: %s", exc)
			raise

	@staticmethod
	def _minimal_plan() -> dict:
		"""Plano minimo de fallback caso o JSON falhe."""
		return {
			"complexity": "medium",
			"requires_web_research": False,
			"requires_agent_runner": False,
			"intro_message": "Beleza! Vamos criar o addon que você pediu.",
			"plan_presentation": "Vou preparar o addon solicitado e verificar se ele funciona corretamente com o NVDA. O plano está pronto para sua decisão.",
			"approval_message": "Entendido. Vou iniciar a criação do addon.",
			"cancellation_message": "Entendido. A criação do addon foi cancelada.",
			"modification_message": "Entendido. Vou ajustar o plano conforme você pediu.",
			"assembling_message": "Montando...",
			"completed_message": "Pronto!",
			"replan_message": "Encontramos problemas. Revisando a abordagem...",            "dependencies": [],
			"steps": [
				{"step_id": "s1", "step_type": STEP_CODE_GENERATION,
				 "description": "Gerar codigo do addon NVDA", "expected_output": "codigo Python",
				 "user_message": "Gerando o codigo do addon...",
				 "depends_on": [], "context_from_steps": []},
				{"step_id": "s2", "step_type": STEP_MANIFEST,
				 "description": "Gerar manifest.ini", "expected_output": "manifest.ini",
				 "user_message": "Criando o manifesto do addon...",
				 "depends_on": [], "context_from_steps": []},
				{"step_id": "s3", "step_type": STEP_ACCESSIBILITY_AUDIT,
				 "description": "Auditar acessibilidade", "expected_output": "relatorio",
				 "user_message": "Verificando acessibilidade para usuarios de leitor de telas...",
				 "depends_on": ["s1"], "context_from_steps": ["s1"]},
				{"step_id": "s4", "step_type": STEP_DOCUMENTATION,
				 "description": "Gerar guia do usuario em HTML acessivel",
				 "expected_output": "doc/pt_BR/userGuide.html",
				 "user_message": "Gerando documentacao para o usuario final...",
				 "depends_on": ["s1", "s2"], "context_from_steps": ["s1", "s2"]},
				{"step_id": "s5", "step_type": STEP_ASSEMBLY,
				 "description": "Montar artefatos finais", "expected_output": "addon completo",
				 "user_message": "Reunindo todos os arquivos do addon...",
				 "depends_on": ["s1", "s2", "s4"], "context_from_steps": ["s1", "s2", "s3", "s4"]},
			],
		}

	def replan(
		self,
		original_query: str,
		outputs_summary: dict[str, str],
		remaining_steps: list[ExecutionStep],
		issues: list[str],
		model_map: dict[str, str] | None = None,
		complexity: str = "medium",
	) -> list[ExecutionStep]:
		"""
		Gera um plano revisado para os steps restantes do pipeline.

		Chamado pelo Orchestrator quando _needs_replan() detecta que step critico falhou.
		Nao refaz steps ja concluidos — apenas planeja o que ainda precisa ser feito.

		Regra 5: LLM decide nova estrategia (semantico).
				 Planner atribui modelos corretos (deterministico via _build_steps).

		model_map: override de model_id por step_type (cross-model escalation
		-- pratica 2026 validada: apos falha + escalacao ja terem esgotado o
		modelo padrao para um step critico, forcar um modelo DIFERENTE tem
		chance real de sucesso onde repetir o mesmo modelo nao teria, porque
		modelos diferentes tem modos de falha complementares). Populado por
		Orchestrator._diversify_failed_models(). Antes desta versao o
		parametro era aceito mas nunca chegava a _build_steps() nem escapava
		de apply_model_budget() (que reescrevia todo model_id
		incondicionalmente) -- era um no-op silencioso.
		"""
		log_decision(_logger, "replan_iniciado",
					 f"remaining={len(remaining_steps)} issues={len(issues)}")

		completed_text = "\n".join(
			f"- {sid}: {out[:150]}{'...' if len(out) > 150 else ''}"
			for sid, out in outputs_summary.items()
		) or "(nenhum step concluido ainda)"

		failed_text = (
			"\n".join(f"- {issue}" for issue in issues[:10])
			or "(sem falhas registradas)"
		)

		remaining_text = "\n".join(
			f"- [{s.step_type}] {s.description[:80]}"
			for s in remaining_steps
		) or "(nenhum step restante)"

		replan_prompt = (
			f"Tarefa original do usuario: {original_query}\n\n"
			f"O que ja foi concluido ate agora:\n{completed_text}\n\n"
			f"Problemas encontrados nos steps que falharam:\n{failed_text}\n\n"
			f"Steps que ainda precisam ser executados:\n{remaining_text}\n\n"
			f"Gere um plano REVISADO apenas para completar os steps restantes.\n"
			f"Corrija os problemas identificados na nova geracao.\n"
			f"Use os mesmos step_types do plano original.\n"
			f"Retorne apenas o JSON com os novos steps necessarios."
		)

		try:
			raw = self._call_planner_llm(replan_prompt)
			plan_data = self._parse_plan(raw)
			new_steps = self._build_steps(plan_data.get("steps", []), model_overrides=model_map)
			from ..gui.settings_panel import get_llm_provider, get_llm_model
			provider = get_llm_provider()
			configured_model = get_llm_model()
			apply_model_budget(
				new_steps, provider, configured_model,
				preserve_step_types=set(model_map) if model_map else None,
				complexity=complexity,
			)
			if not new_steps:
				_logger.warning("[AVISO] Replan retornou lista vazia. Mantendo steps originais.")
				return list(remaining_steps)
			log_decision(_logger, "replan_concluido",
						 f"novos_steps={len(new_steps)}")
			return new_steps
		except Exception as exc:
			_logger.error("[ERRO] Planner.replan falhou: %s. Mantendo steps originais.", exc)
			return list(remaining_steps)
