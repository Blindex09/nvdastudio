import copy
import os
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from typing import Callable

from .orch_types import StepResult, OrchestrationResult, compute_progress
from .planner import (
	Planner, ExecutionPlan, ExecutionStep, STEP_USER_CLARIFICATION,
	STEP_SYNTAX_VALIDATION, STEP_TEST_GENERATION, STEP_WEB_RESEARCH,
	STEP_ASSEMBLY, STEP_ENGINEERING_REVIEW, STEP_DESIGN_REVIEW,
	STEP_CODE_GENERATION,  # Slice 3: caminho agentico rotula o step de geracao
	format_expected_files_for_prompt,
	# tests/unit/test_syntax_validator.py::test_step_syntax_validation_importado
	# depende dele como re-export deste modulo (ver changelog v5.12.0 acima:
	# ja foi removido por engano num auto-fix de ruff antes, NAO REMOVER de novo).
	# 5.54.0: agora USADO de verdade (bypass deterministico do critic, ver
	# _evaluate_syntax_validation_deterministically) -- noqa removido.
)
from ..ai.model_registry import resetar_saida_estruturada
from ..ai.critic import Critic, CriticResult, Verdict
from ..utils.logger import get_logger, log_decision
from ..sub_agents.dispatcher import dispatch_step_with_tokens
from ..builder.addon_builder import (
	extract_code_blocks,
	garantir_init_translation,
	substituir_codigo_dos_blocos,
	validate_python_syntax,
	validate_python_imports,
)
from ..memory.narration import narrate, LiveNarrator, _truncate_at_word
from ..sub_agents._base import clear_client_cache
from ..memory.session_memory import memory
from ..utils.cost_tracker import estimate_pipeline_cost
from .orch_types import (
	PipelinePhase, DomainContext, PlanApproval, CheckpointResult,
)
from ..tools.domain_researcher import DomainResearcher
from ..builder.context_compressor import compressor as context_compressor
from ..builder.addon_builder import chama_gettext
from ..builder.nvda_context import nvda_topics_marker
from ..memory.agent_memory import agent_memory as agent_mem
# Novos módulos v2.1.0 (Hermes-inspired)
from ..tools.skills_hub import get_skill
from ..memory.memory_manager import memory_manager
from ..memory.session_recap import build_session_recap
from .checkpoint_manager import checkpoint_manager, CheckpointAction
from .execution_context import execution_context_store
from ..utils.task_tracker import task_tracker
from ..memory.conversation_manager import conversation
from ..tool_system.approval import ApprovalWorkflow
from ..utils.iteration_budget import budget as iteration_budget

MODULE_VERSION = "5.91.0"
_logger = get_logger("orchestrator")

# ---------------------------------------------------------------------------
# Caminho 3 (arquitetura agentica) -- Slice 3.5: o loop agentico
# (builder/agentic_driver.py) e o PADRAO da geracao. O pipeline staged continua
# como FALLBACK (quando o agentico nao produz nada) e para retomada (resume_plan).
# Opt-OUT explicito: NVDASTUDIO_AGENTIC_MODE in {0,false,off,no} volta pro staged.
# A suite de teste opta por staged por default (tests/conftest.py) porque o
# agentico depende do droid real -- producao, sem a env var, usa o agentico.
# Ver docs/arquitetura-agentica-caminho3-2026-09-06.md.
# ---------------------------------------------------------------------------
_AGENTIC_ENV = "NVDASTUDIO_AGENTIC_MODE"
_AGENTIC_CORRECTION_ROUNDS = 2
_AGENTIC_OFF_VALUES = ("0", "false", "off", "no")


def _agentic_mode_enabled() -> bool:
	"""Caminho 3 e o PADRAO. Retorna False so quando explicitamente DESLIGADO
	(NVDASTUDIO_AGENTIC_MODE in {0,false,off,no}) -- opt-OUT para o staged, nao
	mais opt-in. Sem a env var, o agentico esta ligado."""
	return os.environ.get(_AGENTIC_ENV, "").strip().lower() not in _AGENTIC_OFF_VALUES


def _agentic_files_to_blocks(workdir: str, files: list[str]) -> str:
	"""Converte os arquivos que o driver agentico produziu no disco para o
	formato de bloco cercado que builder/addon_builder.extract_code_blocks()
	consome -- assim a GUI empacota o resultado agentico pelo MESMO caminho
	(save_addon_files + portao final) do pipeline staged, sem duplicar entrega.
	"""
	partes: list[str] = []
	for rel in files:
		nome = rel.rsplit("/", 1)[-1].lower()
		if nome.endswith(".py"):
			lang = "python"
		elif nome.endswith(".ini"):
			lang = "ini"
		elif nome.endswith((".html", ".htm")):
			lang = "html"
		else:
			lang = "text"
		try:
			with open(os.path.join(workdir, rel), encoding="utf-8", errors="replace") as fh:
				conteudo = fh.read()
		except OSError:
			continue
		partes.append(f"```{lang}:{rel}\n{conteudo}\n```")
	return "\n\n".join(partes)


_HEARTBEAT_INTERVAL_SECONDS = 2.5  # progresso periodico durante steps longos

# Timeout maximo por step (segundos)
# v2.1.0 (2026-06-09): Usar timeouts.py centralizado (Hermes-inspired)
# Periodo de graca depois do timeout global do as_completed (segundos).
_GRACE_PERIOD_SECONDS = 60


def _get_step_timeout(step_type: str) -> int:
	"""
	Timeout individual para o tipo de step. Fonte unica: utils/timeouts.py.

	5.68.0 -- havia aqui uma copia da tabela de timeouts.py com valores
	DIFERENTES (1200 aqui, 600 la). Esta copia era consultada DEPOIS e vencia,
	entao quem lesse timeouts.py acreditava num numero que nao era o aplicado.
	Duas tabelas para a mesma regra e a Regra 5 do README ao contrario, e a
	divergencia tinha consequencia: `documentation` -- que le o addon inteiro e
	e BLOQUEANTE -- nao estava em nenhuma das duas e morria no default de 180s.
	Medido nos relatorios: 9 steps mortos assim, incluindo dois addons SIMPLES
	que falharam so por isso.

	Os valores de la agora sao os que eram aplicados aqui; nada afrouxou.
	"""
	from ..utils.timeouts import get_step_timeout as _get_timeout
	return int(_get_timeout(step_type))


# Steps nao-bloqueantes: falha nao impede dependentes
# design_review: output (mesmo rejeitado) e passado como contexto ao code_generation;
# a reprovacao nao deve travar o pipeline — o codigo segue com o feedback disponivel.
# web_research: offline ou falha deve anunciar ao usuario, mas nunca bloquear o pipeline.
# agent_template: spec/documentacao do agente — util como contexto, mas code_generation
#   nao pode ser bloqueado por ausencia de template. Output armazenado mesmo sem aprovacao.
# manifest_builder: assembly pode regenerar manifest se necessario; armazenar output mesmo
#   quando rejeitado permite que assembly receba contexto e execute sempre.
# test_generation e documentation: sao BLOQUEANTES — IA retentar ate passar (decisao usuario).
_NON_BLOCKING_STEP_TYPES = {
	"accessibility_audit", "design_review", "syntax_validation", "web_research",
	"agent_template", "manifest_builder",
	# 5.80.0 -- engineering_review estava declarado CONSULTIVO no planner
	# (_STEPS_CONSULTIVOS, 2.42.0: o assembly nao depende dele) e ao mesmo
	# tempo BLOQUEANTE aqui. Duas listas descrevendo o mesmo conceito e
	# discordando -- a duplicacao de regra que a Regra 5 proibe. Introduzida
	# por mim em ef8a97b; ele julga engenharia e nao produz arquivo nenhum.
	"engineering_review",
	# 5.81.0 -- documentation deixa de bloquear a entrega.
	#
	# REVERSAO DELIBERADA de uma decisao anterior do usuario ("Q8.3: falha
	# em documentation agora BLOQUEIA o pipeline"), aprovada por ele em
	# 2026-09-02 depois da evidencia abaixo. Nao mexer sem falar com ele.
	#
	# Medido na rodada AssistenteEscrita: doc1 reprovado 3x deixou o assembly
	# eternamente nao-pronto (ele depende de documentation), e o codigo do
	# addon inteiro -- ja gerado e aprovado -- foi descartado por causa do
	# guia do usuario.
	#
	# So e seguro afrouxar porque agora existe rede deterministica:
	# addon_builder 4.22.0 injeta um guia minimo quando nenhum HTML chega aos
	# blocos -- mesmo criterio que ja tornava manifest_builder nao-bloqueante
	# (_generate_minimal_manifest). Quando o usuario decidiu pelo bloqueio,
	# essa rede NAO existia, e afrouxar teria trocado "nao entrega" por
	# "entrega sem ajuda nenhuma". Agora a troca e por "entrega com ajuda
	# simples", que e estritamente melhor que nao entregar.
	"documentation",
}

# Steps cujo output E arquivo do addon: sem eles nao ha o que entregar.
# Conceito diferente de _STEP_TYPES_DE_ENTREGA (reserva de orcamento) e de
# _CRITICAL_STEP_TYPES (dispara replanejamento) -- por isso set proprio, e
# nao reuso de um deles com outro significado (Regra 5).
_STEPS_QUE_PRODUZEM_ARQUIVO = {"code_generation"}

# Piso para aceitar por portoes verdes. 60 e o mesmo limite que o Critic ja
# usa para separar CORRIGIR (60-89) de REJEITAR (<60), em critic.py: abaixo
# disso ele esta dizendo que o output e irrecuperavel, e nao ha portao
# determinístico que compense isso.
_SCORE_MIN_ACEITACAO_POR_PORTOES = 60

# Steps que PRODUZEM a entrega -- so eles enxergam a reserva de orcamento.
_STEP_TYPES_DE_ENTREGA = {"assembly"}

# Steps criticos: falha dispara replanejamento e escalacao.
_CRITICAL_STEP_TYPES = {"code_generation", "agent_runner"}

# 5.26.0: web_research nunca escalava pro modelo resiliente apos falhar --
# achado real do golden eval set (test_e36, addon AssistenteLeituraGemini):
# o deepseek-v4-flash devolveu o MESMO output invalido (bloco ```python:
# em vez de texto de pesquisa) nas 3 tentativas seguidas, sempre no mesmo
# modelo, porque web_research nao esta em _CRITICAL_STEP_TYPES e portanto
# nunca troca de modelo entre tentativas. Deliberadamente NAO adicionado a
# _CRITICAL_STEP_TYPES em si -- esse set tambem controla replanejamento
# (_needs_replan/_diversify_failed_models) e web_research e projetado pra
# NUNCA bloquear o pipeline (ver _NON_BLOCKING_STEP_TYPES acima). Um set
# separado da a escalacao de modelo sem herdar o comportamento bloqueante.
_ESCALATION_ELIGIBLE_STEP_TYPES = _CRITICAL_STEP_TYPES | {"web_research"}

# Modelo de escalacao: resolvido dinamicamente por _get_resilience_model()
# (tier heavy do provider atual via model_registry). _ESCALATION_MODEL como
# constante fixa foi removida em 2026-07-20 (auditoria) por estar orfa —
# nenhuma logica a lia, so um teste desatualizado.
#
# reasoning_effort por tipo de step critico na escalacao.
# code_generation com reasoning_effort="high": o modelo heavy do Ollama
# (Kimi K2, ver model_registry.py) tem suporte nativo (thinking_native=True).
# agent_runner sem thinking: loop ReAct com tool use — thinking piora latencia sem ganho.
#
# Achado real (2026-08-09, investigacao de "gpt-5.6-sol devolveu resposta
# vazia" na escalacao cross-provider): a chave usada aqui era "think"
# (vocabulario ESPECIFICO do Ollama -- ollama_client.py mapeia pro payload
# nativo "think"), mas create_llm_client()/dispatch_step_with_tokens()
# passam reasoning_params pra QUALQUER provider via **reasoning_params.
# ollama_client.py, provider_client.py (openai/gemini/xai) e
# opencode_go_client.py tem TODOS o mesmo parametro real na assinatura de
# chat(): reasoning_effort. "think=True" nao bate com nenhum deles --
# client.chat(**kwargs) absorve silenciosamente a chave desconhecida (todos
# tem **kwargs no fim da assinatura), sem erro, mas SEM EFEITO NENHUM.
# Resultado real: toda escalacao de code_generation pra OpenAI/Gemini/xAI/
# OpenCode Go pedia reasoning_effort=None (nunca elevava o raciocinio de
# verdade), enquanto o modelo (gpt-5.6-sol, um modelo de raciocinio) usava
# o proprio default de reasoning da OpenAI SEM max_output_tokens explicito
# -- exatamente o padrao de falha documentado pela OpenAI pra modelos GPT-5:
# gasta o orcamento de tokens inteiro em "reasoning" invisivel e nunca emite
# uma mensagem visivel (content vazio, sem excecao). "reasoning_effort":
# "high" e o parametro universal certo -- ollama_client.py ja mapeia pro
# "think" nativo dele por baixo (com suporte a nivel, nao so booleano, ver
# MODULE_VERSION anterior "Support Ollama think levels"), e os outros 4
# clients ja usam esse nome real na propria assinatura de chat().
_ESCALATION_REASONING_BY_TYPE: dict[str, dict] = {
	"code_generation": {"reasoning_effort": "high"},
	"agent_runner":    {},
}
# Alias compativel com contratos antigos/tests que ainda referenciam
# _ESCALATION_REASONING diretamente.
_ESCALATION_REASONING = _ESCALATION_REASONING_BY_TYPE

# Modelo de fallback para erros transitorios (503, timeout persistente) E
# ultimo recurso de _get_resilience_model() se a resolucao dinamica falhar.
# Quando o modelo original falha com erro de infraestrutura (nao logica),
# retenta com este modelo antes de marcar como REJECTED.
# Regra 5: fallback deterministico — nao usa LLM para decidir.
_FALLBACK_MODEL = "kimi-k2.7-code"
_FALLBACK_REASONING: dict = {}

# 5.54.0: BUG REAL achado ao vivo (test_e38, pedido do Felipe apos rodar
# contra a API real do Ollama: "corrija esses erros que deu nesse teste").
# sub_agents/syntax_validator.py e 100% deterministico desde a v2.0.0
# (2026-04-28) -- so ast.parse() local, ZERO chamada de LLM, contrato de
# saida fixo "RESULTADO: PASS/FAIL/SKIP". Mas o Critic (ai/critic.py) nao
# tem NENHUMA regra especifica pra esse step_type -- avaliava
# "RESULTADO: SKIP" (resposta CORRETA e esperada quando o contexto nao tem
# nenhum bloco ```python:arquivo.py``` anotado pra validar) com criterio
# generico de qualidade, e rejeitava sistematicamente ("O agente retornou
# SKIP sem executar a validacao... "), gastando 3 retries + 1 escalacao por
# step syntax_validation, TODOS inuteis (o sub-agente e deterministico --
# reexecutar com um modelo mais forte nao muda o resultado de ast.parse()).
# Confirmado ao vivo: 3 steps sv_* consumiram retries/tokens de critic sem
# nenhum deles jamais aprovar, ajudando a estourar o orcamento de 500k
# tokens do pipeline inteiro. Regra 5 (roteamento/decisao deterministica
# nunca e trabalho de LLM): parseia o contrato PASS/FAIL/SKIP diretamente,
# SEM chamar o critic -- mais rapido, mais barato, 100% confiavel.
_SYNTAX_VALIDATOR_RESULTADO_RE = re.compile(r"^RESULTADO:\s*(PASS|FAIL|SKIP)\b", re.MULTILINE)


def _evaluate_syntax_validation_deterministically(output: str) -> CriticResult:
	"""
	Interpreta o contrato de saida de sub_agents/syntax_validator.py
	("RESULTADO: PASS/FAIL/SKIP") sem chamar o Critic (LLM). PASS e SKIP
	sao APROVADOS (SKIP = nao havia nada pra validar no contexto deste
	step, nao e falha do sub-agente); FAIL reporta os erros de sintaxe
	reais encontrados. Se o output nao seguir o contrato esperado (ex:
	sub-agente indisponivel, formato mudou), cai pra CORRIGIR neutro em
	vez de assumir sucesso silencioso.
	"""
	m = _SYNTAX_VALIDATOR_RESULTADO_RE.search(output or "")
	if m is None:
		return CriticResult(
			verdict=Verdict.NEEDS_FIX, score=50,
			issues=["syntax_validator: output nao segue o contrato RESULTADO: PASS/FAIL/SKIP esperado."],
			fix_instructions="Reexecute a validacao de sintaxe garantindo o formato RESULTADO: PASS/FAIL/SKIP.",
			stage="deterministic_syntax_validation",
		)
	resultado = m.group(1)
	if resultado in ("PASS", "SKIP"):
		return CriticResult(
			verdict=Verdict.APPROVED, score=100, issues=[],
			fix_instructions="", stage="deterministic_syntax_validation",
		)
	# FAIL: extrai as linhas de erro reais (formato "- Arquivo X: ...")
	erros = re.findall(r"^- (.+)$", output, re.MULTILINE)
	return CriticResult(
		verdict=Verdict.NEEDS_FIX, score=0,
		issues=erros or ["syntax_validator: erro de sintaxe encontrado (detalhe nao capturado)."],
		fix_instructions="Corrija os erros de sintaxe listados no codigo Python gerado.",
		stage="deterministic_syntax_validation",
	)


def _critic_context(step: "ExecutionStep", context: str, project_type: str = "addon") -> str:
	"""Prepende o objetivo do proprio step ao contexto que o Critic recebe.

	5.44.0: achado real ao vivo (test_e36, GeminiMultimodal, apos ARCH-010) --
	evaluate_two_stage() so recebia `context` (saida de steps anteriores),
	NUNCA `step.description`. A regra objetiva de code_generation em
	critic.py exige classe GlobalPlugin/AppModule/driver -- correta para o
	caso de UM code_generation so, mas ARCH-010 (planner.py 2.25.0) agora
	decompoe pedidos com 3+ features em VARIOS code_generation, onde so o
	step FINAL (ex: "cg_core") deve conter essa classe -- os demais geram
	SUBPACOTES legitimos (ex: globalPlugins/<addon>/video/__init__.py) sem
	ela. O Critic rejeitava TODOS os 6-7 steps de feature (score 0, 3
	retries cada) porque nunca sabia qual objetivo cada step tinha --
	1.036.310 tokens gastos, addon nunca fechou. Agora o Critic ve "Objetivo
	deste step: <description>" e pode aplicar a excecao ARCH-010 do proprio
	prompt (critic.py) sem keyword hardcoded -- julgamento semantico do
	modelo, nao regex (Regra do README: zero keywords pra decisao de
	conteudo).
	"""
	# 5.50.0: marcador de roteamento pra controller_client_context.py, mesmo
	# mecanismo de _build_step_prompt() -- critic.py precisa saber que este
	# step e de um projeto controller_client pra usar o catalogo de regras
	# certo (nao NVDA-XXX/manifest.ini, que nao se aplicam).
	marker = ""
	if project_type == "controller_client":
		from ..builder.controller_client_context import project_type_marker
		marker = project_type_marker()
	if not step.description:
		return marker + context
	objetivo = f"Objetivo deste step: {step.description}"
	if context:
		return f"{marker}{objetivo}\n\n{context}"
	return marker + objetivo


def _scope_output_to_step(step_type: str, output: str) -> str:
	"""Keep only artifacts owned by the current pipeline step.

	web_research NUNCA escreve arquivos do addon (sub_agents/web_researcher.py
	_SYSTEM: "Voce pesquisa e relata; nao escreve o addon") -- so tem, no
	maximo, um trecho curto de codigo SEM nome de arquivo dentro do campo
	"Exemplo minimo" (permitido de proposito pelo formato de resposta).
	extract_code_blocks() foi desenhado pra escanear artefatos de
	code_generation e INFERE um filename ate pra blocos ```python``` sem
	anotacao -- rodar essa inferencia aqui reconstroi o output como
	```python:modulo_inferido.py```, recriando exatamente o formato proibido
	que web_researcher.py 4.8.0 ja corrigiu ANTES de retornar. Achado real
	(test_e36, 2026-08-09): a pesquisa saia limpa de run() (confirmado via
	log -- nenhum guard disparava), mas o Critic ainda rejeitava por
	```python: -- causa raiz era aqui, nao no sub-agente. web_research
	nunca precisa de scoping (nao ha artefato pra isolar de outros steps).
	"""
	if step_type == "web_research":
		return output

	blocks = extract_code_blocks(output)
	if not blocks:
		return output

	def _belongs(block: dict) -> bool:
		filename = str(block.get("filename", "")).replace("\\", "/")
		basename = os.path.basename(filename).lower()
		language = str(block.get("language", "")).lower()
		if step_type in {"code_generation", "agent_runner"}:
			# Python and NVDA resources belong here. Manifest and user guides
			# have dedicated agents and must not contaminate this evaluation.
			return basename != "manifest.ini" and language != "html"
		if step_type == "manifest_builder":
			return basename == "manifest.ini"
		if step_type == "documentation":
			return language == "html" or basename.endswith((".html", ".htm"))
		return True

	owned = [block for block in blocks if _belongs(block)]
	return "\n\n".join(
		f"```{block.get('language', 'text')}:{block.get('filename', '')}\n"
		f"{block.get('code', '').rstrip()}\n```"
		for block in owned
	)


# Erro de CONTA do provedor: chave invalida, expirada, revogada ou sem saldo.
# Trocar de MODELO nao ajuda -- o problema e a conta, nao o modelo.
#
# 'insufficient balance'/'credits' entram aqui porque provedor devolve 401 para
# falta de saldo. Confirmado ao vivo em 2026-09-02 no OpenCode Go: GET /models
# respondeu 200 (chave VALIDA) e /chat/completions respondeu 401 com
# {"type":"CreditsError","message":"Insufficient balance"}. O correto seria 402,
# e sem esta deteccao o usuario ouviria 'chave invalida' e iria trocar uma chave
# que esta certa.
_ERRO_DE_AUTENTICACAO_RE = re.compile(
	r"401|403|unauthorized|forbidden|invalid.{0,12}(api.?key|token)"
	r"|api.?key.{0,20}invalid|insufficient.{0,10}balance|creditserror|quota",
	re.IGNORECASE,
)


# Falta de saldo, separada de chave invalida: sao acoes DIFERENTES para o
# usuario (recarregar credito x trocar a chave), e dizer a errada faz ele
# perder tempo no lugar errado.
_SEM_SALDO_RE = re.compile(
	r"insufficient.{0,10}balance|creditserror|quota.{0,20}exceeded|billing",
	re.IGNORECASE,
)


def _modelo_de_outro_provedor(provedor_atual: str) -> str:
	"""
	Modelo de um provedor DIFERENTE, para quando a CONTA atual nao atende.

	Delega para model_router.select_model_and_provider(), que ja existia e faz
	isto melhor do que uma lista propria: pontua candidatos de todos os
	provedores com chave, e -- quando o provedor principal do usuario e o
	ollama -- restringe o resgate a _OLLAMA_RESCUE_PROVIDERS, para nao cair num
	provedor pago em que ele pode nao ter assinatura.

	A primeira versao desta funcao percorria uma lista fixa de provedores
	escrita a mao. Era duplicacao de fluxo (Regra 5) e pior que o que ja
	existia -- ignorava pontuacao e podia escolher um provedor pago sem
	assinatura.

	Devolve "" quando nenhum outro provedor tem chave: ai nao ha o que tentar,
	e o erro segue como estava.
	"""
	try:
		from ..ai.model_router import select_model_and_provider
	except Exception:  # pragma: no cover - defesa
		return ""
	try:
		escolha = select_model_and_provider(
			step_type="code_generation",
			complexity="medium",
			exclude_provider=provedor_atual,
			active_provider=provedor_atual,
		)
	except Exception:  # pragma: no cover - defesa
		return ""
	if not escolha:
		return ""
	_provedor, modelo = escolha
	return modelo


def _get_resilience_model(step_type: str = "", complexity: str = "medium") -> str:
	"""Resolve modelo de fallback/escalacao a partir da configuracao atual.

	5.36.0: step_type/complexity novos -- achado real (test_e36, validacao
	da rodada anterior): a escolha INICIAL de modelo (apply_model_budget())
	ja pontuava entre todos os candidatos ativos (ai/model_router.py), mas
	a escalacao (este metodo, chamado 3x: _try_escalation(), o switch
	proativo dentro do loop de retry, e a checagem final de
	_execute_step_with_critique()) continuava presa no tier "heavy" fixo
	de resolve_provider_tier_model() -- confirmado ao vivo: um step que
	escalava no meio do retry voltava pro kimi-k2.7-code hardcoded mesmo
	quando o roteador tinha escolhido qwen3.5:397b pra ele originalmente.
	Sem step_type (chamador antigo/desconhecido), cai no comportamento
	anterior (tier "heavy" fixo) -- retrocompatibilidade garantida.
	"""
	try:
		from ..gui.settings_panel import get_llm_provider, get_llm_model
		provider = get_llm_provider()
		model = get_llm_model()
		if step_type:
			from ..ai.model_router import select_model
			return select_model(provider, step_type, model, complexity=complexity)
		from ..ai.model_registry import resolve_provider_tier_model
		return resolve_provider_tier_model(provider, "heavy", model)
	except Exception:
		return _FALLBACK_MODEL

# Regex para detectar erros de infraestrutura no output de sub-agentes.
# _run_sub_agent() retorna "[ERRO] Sub-agente nao conseguiu gerar resposta: ..."
# quando a API falha. Detectamos APENAS essas strings de erro — nunca aplicamos
# a regex ao codigo gerado, que pode conter "timeout=30", "status == 503", etc.
# v4.1.1 fix: regex restrita ao prefixo [ERRO], eliminando falsos positivos.
_IS_SUBAGENT_ERROR_RE = re.compile(r'^\s*\[ERRO\]\s', re.IGNORECASE)

# Maximo de replanos por pipeline (evita loop infinito)
_MAX_REPLANS = 2

_MAX_CONTEXT_CHARS_PER_STEP = 3000
# Achado de auditoria full-stack 2026-08-04 (rastreamento de addons grandes/
# complexos, "addons de qualquer magnitude"): _MAX_CONTEXT_CHARS_PER_STEP
# limitava cada dependencia INDIVIDUAL, mas nao existia teto AGREGADO --
# um step com muitas dependencias (comum em addons ARCH-007 com varias
# features) podia concatenar N * 3000 chars sem limite, indo pro prompt
# final sem nenhum orcamento de tamanho antes de chegar no LLM. ~12000 chars
# cobre confortavelmente 4 dependencias no teto individual; alem disso,
# comprime o AGREGADO com a mesma ferramenta (context_compressor).
_MAX_TOTAL_CONTEXT_CHARS = 12000

# Steps cujo TRABALHO e julgar ou montar o codigo dos outros. Para eles,
# resumir o contexto nao economiza: destroi o objeto da avaliacao.
#
# Medido na rodada AssistenteEscrita (2026-09-03): `__init__.py` tinha
# ~8.900 chars e chegava ao assembly comprimido em 3.000. O veredito
# reprovou 3x (113.070 tokens) alegando que o arquivo "usa
# api.getFocusObject(), config.conf e log.exception sem importar esses
# modulos" -- os imports estao nas linhas 1 a 9, e tinham sido comidos
# pela compressao. Citou tambem `correct_text` e `simplify_text`, nomes
# que nao existem em arquivo nenhum: o resumo em prosa vira material de
# alucinacao quando lido como se fosse codigo.
#
# O mesmo aconteceu no test_generation (141.577 tokens, 3 reprovacoes
# citando `correct_grammar`) e no engineering_review, que reclamou
# explicitamente dos "snippets comprimidos". Somados, 310.336 tokens --
# 32% da rodada -- gastos julgando um codigo que ninguem mostrou.
#
# Quem JULGA codigo recebe o codigo. Quem recebe resumo, resume palpite.
_STEPS_QUE_JULGAM_CODIGO = frozenset({
	STEP_ASSEMBLY, STEP_ENGINEERING_REVIEW, STEP_DESIGN_REVIEW,
	STEP_TEST_GENERATION,
})
# Teto proprio, e alto: um addon complexo inteiro cabe. Nao e ausencia de
# orcamento -- e orcamento dimensionado para o que o step precisa ver.
_MAX_CONTEXT_CHARS_CODIGO = 60000
_MAX_PARALLEL_WORKERS = 3

# Paralelismo adaptativo por provider.
# Cada provider tem seu proprio limite de concorrencia. Quando varios steps
# paralelos usam o mesmo modelo, reduzimos workers para evitar rate limit 429.
_PROVIDER_MAX_CONCURRENCY: dict[str, int] = {
	"kimi-k2.7-code":    3,  # Kimi K2.7-code: mesma familia/capacidade do K2.6
	"kimi-k2.6":         3,  # Kimi K2.6: 232K downloads — alta capacidade
	"deepseek-v4-flash": 4,  # DeepSeek V4 Flash: 140GB, otimizado para velocidade
}


def _adaptive_max_workers(steps: list) -> int:
	"""
	Calcula o numero otimo de workers paralelos baseado nos modelos usados.

	Se todos os steps usam o mesmo modelo, o max_workers e o menor entre
	_MAX_PARALLEL_WORKERS e o limite de concorrencia do provider.
	Se usam modelos diferentes, o limite e _MAX_PARALLEL_WORKERS.
	"""
	if len(steps) <= 1:
		return 1
	models = {s.model_id for s in steps}
	if len(models) == 1:
		provider_limit = _PROVIDER_MAX_CONCURRENCY.get(
			next(iter(models)), _MAX_PARALLEL_WORKERS
		)
		return min(_MAX_PARALLEL_WORKERS, provider_limit)
	return _MAX_PARALLEL_WORKERS


def _sandbox_failure_evidence(result) -> str:
	"""Consolida toda evidência disponível de uma falha de subprocesso."""
	parts = [
		getattr(result, "error", ""),
		getattr(result, "stderr", ""),
		getattr(result, "stdout", ""),
	]
	return " | ".join(part for part in parts if part) or "subprocesso retornou falha sem detalhes"


# 5.55.0: Existia um SEGUNDO classificador de complexidade aqui, baseado em
# IA (uma chamada de LLM extra por step, so para rotular metrica), com
# vocabulario proprio (simple/medium/complex) desalinhado do vocabulario do
# Planner (low/medium/high em estimated_complexity, ja decidido pela IA na
# etapa de planejamento e ja usado por model_router.py para escalacao real).
# Achado de auditoria 2026-08-25: os dois nunca eram reconciliados -- a
# metrica registrada em session_memory podia dizer "complex" enquanto o
# roteamento de modelo, para o MESMO step, operava sob "high"/"low", sem
# nenhum dos dois nunca ler o outro. Alem do custo/latencia desperdicados
# (uma chamada de rede por step so para um label de log), a duplicacao viola
# a regra do projeto de fonte unica por decisao. Fix: reusa a complexidade
# JA decidida pelo Planner (self._current_complexity()) como fonte unica,
# mapeada para o vocabulario esperado pelas metricas existentes.
_PLAN_COMPLEXITY_TO_METRIC_LEVEL: dict[str, str] = {
	"low": "simple", "medium": "medium", "high": "complex",
}


def classify_query_complexity(complexity: str) -> str:
	"""Mapeia a complexidade do plano (low/medium/high) para o vocabulario
	de metricas (simple/medium/complex). Deterministico -- sem chamada de IA.

	5.55.0: renomeado de fato de "classificador por IA da query" para
	"tradutor de vocabulario da complexidade ja decidida pelo Planner" (ver
	nota acima). O parametro mudou de `query: str` para `complexity: str`
	(a saida de self._current_complexity()); chamadores atualizados.
	"""
	return _PLAN_COMPLEXITY_TO_METRIC_LEVEL.get(complexity, "medium")


ProgressCallback = Callable[[str, str], None]
# Callback mid-pipeline: recebe lista de perguntas, retorna lista de respostas.
# Se nao definido, Orchestrator continua sem as respostas (graceful degradation).
ClarifyCallback = Callable[[list[str]], list[str]]



# Teto de problemas carregados entre tentativas. Alto o bastante para o modelo
# ver tudo que ja foi apontado num step de addon multi-arquivo, baixo o
# bastante para o prompt do retry nao virar um despejo que dilui a atencao --
# o proprio motivo pelo qual conhecimento em prompt tem retorno decrescente.
_MAX_ISSUES_ACUMULADOS = 25


def _acumular_issues(acumulados: list[str], novos: list[str]) -> None:
	"""
	Acrescenta problemas novos a lista acumulada, sem duplicar.

	Deduplica pelo texto EXATO: o Critic reporta o mesmo defeito com a mesma
	frase entre tentativas, e repetir a linha tres vezes no prompt nao aumenta
	a chance de correcao -- so gasta contexto.

	Preserva a ORDEM de descoberta: o problema apontado primeiro costuma ser o
	mais estrutural, e e o que deve chegar primeiro na leitura do modelo.
	"""
	vistos = set(acumulados)
	for item in novos or []:
		texto = str(item).strip()
		if not texto or texto in vistos:
			continue
		vistos.add(texto)
		acumulados.append(texto)
	if len(acumulados) > _MAX_ISSUES_ACUMULADOS:
		# Descarta os mais ANTIGOS, nao os recentes: um problema apontado ha 3
		# tentativas e que nunca mais voltou provavelmente ja foi resolvido.
		del acumulados[: len(acumulados) - _MAX_ISSUES_ACUMULADOS]


def _alvos_nao_entregues(step: object, py_files: dict) -> list[str]:
	"""
	Arquivos que o step declarou em `target_files` e nao apareceram na saida.

	Comparacao por nome de arquivo: o caminho errado e problema de colocacao,
	que `addon_builder` ja resolve, e bloquear por isso seria falso positivo. O
	que nao da para recuperar e o arquivo que simplesmente nao foi escrito.

	Step sem alvo declarado nao e cobrado -- e o caso de todo plano antigo, e
	exigir entrega sem ter pedido nada especifico nao ajudaria ninguem.
	"""
	if getattr(step, "step_type", "") not in ("code_generation", "agent_runner"):
		return []
	alvos = getattr(step, "target_files", []) or []
	if not alvos:
		return []
	entregues = {
		nome.replace("\\", "/").rsplit("/", 1)[-1].lower()
		for nome in py_files
	}
	return [
		alvo for alvo in alvos
		if alvo.replace("\\", "/").rsplit("/", 1)[-1].lower() not in entregues
	]


# Conteudo do modulo que representa um arquivo que OUTRO step do plano ainda vai
# gerar, usado so na verificacao de execucao.
#
# Modulo VAZIO nao basta: `from .configSpec import apply_config_spec` falha com
# "cannot import name" em vez de "no module named" -- medido na rodada 7, o
# cg_core foi reprovado assim mesmo com o placeholder ja no lugar. O
# `__getattr__` de modulo (PEP 562) faz qualquer nome importar, que e o que se
# espera de um contrato ainda nao implementado.
_MODULO_PENDENTE = chr(10).join((
	"# Placeholder: outro step do plano ainda vai gerar este arquivo.",
	"# Aceita qualquer nome para que o import do contrato resolva.",
	"",
	"",
	"class _Pendente:",
	"	def __call__(self, *a, **k): return self",
	"	def __getattr__(self, _n): return self",
	"	def __iter__(self): return iter(())",
	"	def __bool__(self): return False",
	"",
	"",
	"def __getattr__(_nome):",
	"	return _Pendente()",
	"",
))


def _output_com_ressalva(resultado: "StepResult", step_type: str) -> str:
	"""
	Output de step nao-bloqueante REPROVADO, marcado como nao verificado.

	Nao-bloqueante quer dizer "nao para o pipeline". Nao pode querer dizer
	"passa adiante como se fosse fato". Ate 2026-09-01 o output cru de um step
	reprovado era guardado em `outputs` e injetado nos steps seguintes sem
	nenhuma marca, e os `issues` do Critic -- que costumam CONTER a correcao --
	eram descartados.

	Medido na rodada de 12:26 (AssistenteLeituraGemini): `web_research` foi
	reprovado com "o output pesquisa o pacote legado google-generativeai, mas o
	objetivo exige o SDK atual". Essa pesquisa reprovada virou contexto, e
	`cg_core_service` gastou 419 mil tokens em 3 tentativas para ser reprovado
	por "o objetivo exige o uso do SDK confirmado pela pesquisa
	(google-generativeai), mas o codigo...". O gerador seguiu a pesquisa errada
	porque nada dizia que ela estava errada -- embora o proprio pipeline ja
	soubesse, por escrito, uma etapa antes.

	Degradacao graciosa e entregar o que deu certo, nao propagar em silencio o
	que foi reprovado.
	"""
	corpo = resultado.output or ""
	motivos = [str(i) for i in (resultado.issues or []) if str(i).strip()]
	if not motivos:
		return corpo
	return (
		f"[NAO VERIFICADO] O step {step_type} abaixo foi REPROVADO na "
		"verificacao. Use com desconfianca: onde ele contradisser o pedido do "
		"usuario ou os motivos listados a seguir, os motivos valem mais." + "\n"
		+ "Motivos da reprovacao:" + "\n"
		+ ("\n").join(f"  - {m}" for m in motivos)
		+ "\n\nConteudo produzido pelo step (nao confirmado):" + "\n"
		+ corpo
	)


class Orchestrator:
	"""
	Orquestrador autonomo do NVDAStudio.

	Novidades v2.0.0:
	- Replanejamento dinamico mid-pipeline quando step critico falha
	- Escalacao de modelo (handoff) antes de marcar step como REJECTED
	- Mensagens de status ricas para usuario cego durante avaliacao/correcao
	- Smoke test estrutural do addon gerado
	"""

	def __init__(self):
		self._planner: Planner = Planner()
		self._critic: Critic = Critic()
		self._on_progress: ProgressCallback | None = None
		self._on_complete: Callable[[OrchestrationResult], None] | None = None
		self._on_clarify: ClarifyCallback | None = None
		self._running = False
		self._cancel_requested = False
		self._outputs_lock = threading.Lock()
		self._tokens_by_model: dict[str, tuple[int, int]] = {}
		self._previous_issues: list[str] = []  # v2.1.0 fix: inicializado para agentic_loop
		self._last_result: OrchestrationResult | None = None  # v2.1.0 fix: inicializado
		self._current_plan: ExecutionPlan | None = None  # v2.1.0 fix: inicializado
		# 5.59.0: True assim que o orcamento passa a ser alimentado em voo --
		# faz o registro terminal parar de contar os mesmos tokens de novo.
		self._budget_recorded_in_flight: bool = False
		# 5.60.0: (motivo, steps_nao_executados) quando o pipeline para por
		# orcamento -- deixa a mensagem final dizer a causa REAL em vez de
		# "nenhum arquivo Python foi gerado", que manda investigar o lugar errado.
		self._parou_por_orcamento: tuple[str, int] | None = None
		self._current_plan_addon_name: str = ""  # 5.22.0: inicializado pra _learn_from_session() nunca dar AttributeError
		self._suppress_complete_callback = False
		# Hermes-inspired v2.1.0 (2026-06-09)
		# 5.72.0 -- ToolExecutor NAO e mais instanciado aqui.
		#
		# Ele era criado a cada Orchestrator e NUNCA chamado: nao existe uma
		# unica referencia a `self._tool_executor.<algo>` em todo o projeto. E o
		# construtor abre um ThreadPoolExecutor(max_workers=4), com um
		# shutdown() que ninguem chama -- ou seja, cada abertura do dialogo
		# deixava quatro threads paradas dentro do processo do NVDA, que fica
		# horas aberto na maquina do usuario.
		#
		# O caminho VIVO de ferramentas e tools/tool_gateway.py, que importa as
		# funcoes de tool_system/builtins/ direto (code_generator chama
		# tool_gateway.call("file_editor", ...)). ApprovalWorkflow, logo abaixo,
		# continua sendo usado de verdade em _tool_approval_callback.
		self._approval_workflow = ApprovalWorkflow()
		self._session_start_time: str = ""
		self._session_id: str = ""
	def initialize(self):
		self._planner = Planner()
		self._critic = Critic()
		_logger.info("[OK] Orchestrator v%s inicializado.", MODULE_VERSION)

	def _mensagem_de_falha(self, artifact_error: str) -> str:
		"""
		Ajusta a mensagem final quando o pipeline parou por ORCAMENTO.

		`_validate_minimum_addon_artifacts()` e estatica e so enxerga os
		artefatos: sem codigo Python, ela conclui "a IA nao gerou codigo". Mas
		quando o teto de tokens estourou no meio da geracao, essa frase manda o
		usuario -- e o proximo retry -- investigar o lugar errado. Confirmado ao
		vivo em 2026-08-29: dois pedidos complexos foram reportados como "nenhum
		arquivo Python valido" quando o que houve foi o orcamento acabar.

		A causa real tem precedencia sobre o sintoma.
		"""
		parou = getattr(self, "_parou_por_orcamento", None)
		if not parou:
			return artifact_error
		motivo, nao_rodados = parou
		return (
			f"A criação parou por limite de recursos ({motivo}) antes de concluir o "
			f"código do addon. {nao_rodados} etapa(s) não chegaram a ser executadas. "
			"O que foi aprovado até aqui está preservado no relatório desta execução."
		)

	def _aplicar_orcamento_por_complexidade(self, plan: ExecutionPlan) -> None:
		"""
		Ajusta o teto de tokens ao PLANO -- complexidade e tamanho.

		reset() roda no INICIO da execucao, antes de existir plano -- entao o
		teto so pode ser dimensionado aqui. Ate 2026-08-29 havia um unico teto
		fixo de 500 mil, calibrado (sem que ninguem notasse) para addon simples:
		enquanto o medidor nao era alimentado em voo, o numero nao tinha efeito.
		Ligado o freio, ele virou o fator limitante e matou dois pedidos
		complexos aos ~800 mil, com 1 de 11 e 1 de 14 steps aprovados.

		5.67.0: a constante por complexidade virou PISO, nao teto. Medido na
		rodada de 2026-09-01: o plano real do addon complexo tinha 27 steps, e
		somando o custo medido de UMA passada de cada um o piso do plano dava
		~755 mil tokens contra um teto de 1 milhao -- so caberia se nenhum step
		precisasse de segunda tentativa. A execucao morreu com 18 steps sem
		executar, por aritmetica, nao por desperdicio. Uma constante nao serve
		ao mesmo tempo um plano de 7 steps e um de 27; iteration_budget.
		apply_plan() dimensiona pelo plano aprovado, com teto absoluto para
		continuar sendo disjuntor.

		Nunca levanta: falha aqui nao pode derrubar um plano valido.
		"""
		try:
			complexidade = getattr(plan, "estimated_complexity", "") or "medium"
			tipos = [s.step_type for s in getattr(plan, "steps", []) or []]
			teto = iteration_budget.apply_plan(tipos, complexidade)
			_logger.info(
				"[BUDGET] Plano %s (complexity=%s, %d steps): teto de %d tokens.",
				plan.plan_id, complexidade, len(tipos), teto,
			)
		except Exception as exc:  # pragma: no cover - defesa
			_logger.warning("[BUDGET] Nao foi possivel ajustar o teto: %s", exc)

	def _track_model_tokens(self, model_id: str, tokens: int, step_type: str = "") -> None:
		"""
		Acumula tokens por modelo E alimenta o orcamento EM VOO.

		5.59.0 -- causa raiz da nao-convergencia. O circuit breaker existia
		(`iteration_budget.can_continue()` e consultado a cada tentativa desde
		a 5.28.0), mas o MEDIDOR so era alimentado nos pontos TERMINAIS do
		pipeline, via `_record_iteration_budget(step_results)`. Durante a
		execucao `tokens_used` ficava em zero, entao `can_continue()` sempre
		respondia True e nada parava: nos relatorios reais ha execucao com 41
		retries e 4,6 MILHOES de tokens contra um teto configurado de 500 mil.

		Perguntar sem medir e o mesmo padrao de "detecta e ignora" que ja
		apareceu no ESTRUTURA-008: a peca certa existia, desligada de quem
		decide. Este metodo ja e chamado em TODO ponto de consumo de token do
		pipeline, entao alimentar o orcamento aqui fecha o circuito sem risco
		de esquecer um caminho novo.

		Nunca levanta: falha no orcamento nao pode derrubar uma geracao que
		esta indo bem.
		"""
		prev = self._tokens_by_model.get(model_id, (0, 0))
		self._tokens_by_model[model_id] = (prev[0] + tokens // 2, prev[1] + tokens // 2)
		if tokens <= 0:
			return
		try:
			iteration_budget.record_iteration(
				step_type=step_type or "pipeline",
				model_id=model_id,
				tokens_used=tokens,
				success=True,
			)
			self._budget_recorded_in_flight = True
		except Exception as exc:  # pragma: no cover - defesa
			_logger.warning("[BUDGET] record_iteration em voo falhou: %s", exc)

	def set_callbacks(self, on_progress: ProgressCallback,
					  on_complete: Callable[[OrchestrationResult], None],
					  on_clarify: ClarifyCallback | None = None):
		self._on_progress = on_progress
		self._on_complete = on_complete
		self._on_clarify = on_clarify

	def cancel_pipeline(self):
		"""Cancela a execucao do pipeline em andamento."""
		_logger.info("[CANCEL] Solicitacao de cancelamento recebida.")
		self._cancel_requested = True

	def _check_cancel(self):
		if getattr(self, "_cancel_requested", False):
			raise Exception("Cancelado pelo usuário")

	def run_async(self, user_query: str):
		if self._running:
			_logger.warning("[AVISO] Orchestrator ja esta rodando.")
			return
		self._running = True
		# Ver comentario equivalente em run_conversational_async() -- mesmo motivo.
		iteration_budget.reset()
		# O limite do provedor de saida estruturada e por JANELA DE TEMPO
		# (5h / semana / mes), entao a indisponibilidade e temporaria: cada
		# execucao volta a tentar o provedor preferido em vez de ficar
		# degradada para sempre por uma falha de horas atras.
		resetar_saida_estruturada()
		self._budget_recorded_in_flight = False
		self._parou_por_orcamento = None
		thread = threading.Thread(
			target=self._run_async_worker, args=(user_query,), daemon=True
		)
		thread.start()

	def _run_async_worker(self, user_query: str):
		try:
			self._run_until_success(user_query)
		finally:
			self._running = False

	def _compute_progress(self, prev: OrchestrationResult | None, curr: OrchestrationResult) -> tuple[float, str]:
		return compute_progress(prev, curr)

	def _run_until_success(self, user_query: str) -> OrchestrationResult:
		from .agentic_loop import AgenticLoop

		self._last_result = None
		self._suppress_complete_callback = True
		try:
			result = AgenticLoop(self).run(user_query)
		finally:
			self._suppress_complete_callback = False

		# Ponto UNICO por onde todo OrchestrationResult passa antes de sair
		# daqui. A degradacao de planejamento e propagada aqui, e nao nos 5+
		# construtores de OrchestrationResult espalhados pelo modulo: copiar
		# em cinco lugares e a costura que quebra quando alguem adiciona o
		# sexto e esquece -- exatamente o defeito que esta sessao passou o dia
		# corrigindo. Deriva do plano vigente, nunca de copia manual.
		_plano = getattr(self, "_current_plan", None)
		if _plano is not None and result is not None:
			result.planejamento_degradado = bool(
				getattr(_plano, "planejamento_degradado", False)
			)

		self._last_result = result
		if self._on_complete:
			self._on_complete(result)
		return result

	# ------------------------------------------------------------------
	# v2.0.0: Pipeline Conversacional
	# ------------------------------------------------------------------

	# Callbacks do pipeline conversacional
	_on_phase_change: Callable[[PipelinePhase, str], None] | None = None
	_on_plan_ready: Callable[[ExecutionPlan, DomainContext | None], PlanApproval] | None = None
	_on_checkpoint: Callable[[CheckpointResult], bool] | None = None

	def set_conversational_callbacks(
		self,
		on_phase_change: Callable[[PipelinePhase, str], None] | None = None,
		on_plan_ready: Callable[[ExecutionPlan, DomainContext | None], PlanApproval] | None = None,
		on_checkpoint: Callable[[CheckpointResult], bool] | None = None,
	):
		"""Configura callbacks para o pipeline conversacional v2.0.0."""
		self._on_phase_change = on_phase_change
		self._on_plan_ready = on_plan_ready
		self._on_checkpoint = on_checkpoint

	def _emit_phase(self, phase: PipelinePhase, detail: str = ""):
		"""Emite mudanca de fase do pipeline conversacional."""
		_logger.info("[PHASE] %s: %s", phase.name, detail)
		if self._on_phase_change:
			self._on_phase_change(phase, detail)

	def _emit_conversation(self, role: str, message: str, kind: str = "content"):
		"""Emite mensagem conversacional para o usuario.

		kind: 'status' | 'content' — tipo de mensagem
			- status: curto, TTS automatico
			- content: longo, historico
		"""
		if kind == "status":
			conversation.emit_status(message)
		else:
			conversation.emit_content(message, role)

	def _emit_checkpoint(self, step: "ExecutionStep", summary: str) -> None:
		"""
		Avisa (nunca pausa) quando a confianca do pipeline caiu num step --
		hoje, so quando a escalacao normal ja falhou e o sistema esta
		prestes a tentar outro provider. 5.41.0.

		CheckpointResult/on_checkpoint (orch_types.py) ja existiam com o
		contrato inteiro pronto (studio_dialog.py ja tinha
		_on_conversational_checkpoint() implementado e conectado via
		set_conversational_callbacks()), mas o Orchestrator NUNCA disparava
		um checkpoint de verdade -- mecanismo desenhado e nunca ligado, mesmo
		padrao de outras lacunas achadas nesta sessao (validate_addon_imports,
		_offer_chat_restore). should_continue (retorno do callback) e
		IGNORADO de proposito: decisao explicita do Felipe, ja registrada em
		_on_conversational_checkpoint(), e que o pipeline nunca deve parar
		sozinho esperando resposta -- isso e so visibilidade, nao um gate.
		"""
		if not self._on_checkpoint:
			return
		try:
			self._on_checkpoint(CheckpointResult(
				phase=PipelinePhase.EXECUTING,
				step_id=step.step_id,
				step_type=step.step_type,
				summary=summary,
				should_continue=True,
			))
		except Exception as exc:
			_logger.debug("[CHECKPOINT] on_checkpoint falhou (ignorado, so informativo): %s", exc)

	def run_conversational_async(self, user_query: str):
		"""
		Pipeline conversacional v2.0.0.

		Fluxo completo:
		1. CONVERSATION — Entender o que o usuario quer (clarificacao inicial)
		2. RESEARCH — Pesquisar dominio, APIs, boas praticas
		3. PLANNING — Montar plano de implementacao
		4. PLAN_APPROVAL — Mostrar plano e aguardar aprovacao
		5. EXECUTING — Implementar com checkpoints
		6. REVIEW — Mostrar resultado final
		7. DONE — Pipeline concluido
		"""
		if self._running:
			_logger.warning("[AVISO] Orchestrator ja esta rodando.")
			return
		# self._running e setado AQUI, sincronamente, antes de iniciar a thread --
		# nao dentro de _run_conversational_pipeline. Setar so dentro da thread
		# cria uma race: duas chamadas de run_conversational_async() em sequencia
		# rapida (ex: um duplo-disparo qualquer na UI) veem self._running == False
		# nas duas e ambas iniciam thread, rodando o pipeline inteiro em paralelo
		# (dai fases/mensagens duplicadas no chat). run_async() ja fazia certo.
		self._running = True
		# Achado de auditoria 2026-08-04: `iteration_budget` e um singleton global
		# de PROCESSO INTEIRO, nunca resetado em lugar nenhum -- sem isso, gasto de
		# sessoes anteriores ficava acumulado pra sempre e uma query nova, sem
		# relacao nenhuma, podia nascer com o orcamento ja estourado.
		iteration_budget.reset()
		# O limite do provedor de saida estruturada e por JANELA DE TEMPO
		# (5h / semana / mes), entao a indisponibilidade e temporaria: cada
		# execucao volta a tentar o provedor preferido em vez de ficar
		# degradada para sempre por uma falha de horas atras.
		resetar_saida_estruturada()
		self._budget_recorded_in_flight = False
		self._parou_por_orcamento = None
		thread = threading.Thread(
			target=self._run_conversational_pipeline, args=(user_query,), daemon=True
		)
		thread.start()

	def _record_iteration_budget(self, step_results: list[StepResult]) -> None:
		"""
		Registra os steps desta tentativa em iteration_budget -- SEMPRE, mesmo
		quando a tentativa falha (artefato ausente ou excecao critica).

		Achado de auditoria 2026-08-04: antes so o caminho de SUCESSO de
		`_run_conversational_pipeline` chamava isso (bloco WIRING #4), e
		`_run_pipeline` (usado pelas estrategias do FSM em agentic_loop.py)
		NUNCA chamava -- ou seja, o custo real das tentativas mais caras
		(as que falham e disparam retry/replan/escalation) nunca era
		contabilizado. Como `AgenticLoop.run()` agora usa
		`iteration_budget.can_continue()` como circuit breaker entre
		estrategias (ver agentic_loop.py), gravar so no sucesso tornaria esse
		circuit breaker inutil -- e justamente a sequencia de falhas caras
		que ele precisa conseguir enxergar.
		"""
		# 5.59.0: com o medidor alimentado EM VOO por _track_model_tokens(),
		# repetir o registro aqui contaria os mesmos tokens duas vezes e
		# derrubaria o orcamento pela metade do gasto real. O registro
		# terminal so age quando nada foi contabilizado em voo -- caminhos que
		# terminam sem passar por _track_model_tokens (falha antes da primeira
		# chamada de LLM, por exemplo).
		if getattr(self, "_budget_recorded_in_flight", False):
			return
		try:
			for r in step_results:
				iteration_budget.record_iteration(
					step_type=r.step_type,
					model_id=r.model_id,
					tokens_used=r.tokens_used,
					success=r.approved,
					latency_ms=r.execution_time_ms,
				)
		except Exception as e:
			_logger.warning("[WIRING] iteration_budget falhou: %s. Continuando.", e)

	def _learn_from_session(self, user_query: str, success: bool, issues: list[str]) -> None:
		"""
		Registra a tentativa em memory_manager (Hermes-inspired MEMORY.md/
		USER.md) -- SEMPRE, mesmo em falha, e nos dois pipelines.

		Achado de auditoria full-stack 2026-08-04 (segunda rodada, "partes
		que nao estao integradas"): antes so o caminho de SUCESSO de
		`_run_conversational_pipeline` chamava isso -- falhas e execucoes via
		`_run_pipeline` (estrategias do FSM em agentic_loop.py) nunca
		ensinavam a memoria persistente. MEMORY.md so acumulava licoes de um
		subconjunto das sessoes reais. Usa `self._current_plan_addon_name`
		(via getattr, defensivo -- pode nao existir ainda se a excecao
		aconteceu ANTES da criacao do plano) em vez de `plan.addon_name`
		direto, pra funcionar nos 3 desfechos sem risco de NameError.
		"""
		try:
			memory_manager.learn_from_session(
				query=user_query,
				addon_name=getattr(self, "_current_plan_addon_name", "") or "",
				success=success,
				issues=issues,
			)
		except Exception as e:
			_logger.warning("[WIRING] memory_manager falhou: %s. Continuando.", e)

	def _log_session_recap(self, user_query: str, orch_result: OrchestrationResult, step_results: list) -> None:
		"""
		5.46.0: achado real de auditoria de integracao -- session_recap.py::
		build_session_recap() (resumo legivel, deterministico, sem custo de
		LLM) existia desde 1.0.0 mas nunca era chamado por ninguem, apesar do
		docstring dizer "chamado ao final do pipeline". So no log interno --
		nao exposto ao usuario (mesma decisao de UX do checkpoint 5.4.0:
		metricas tecnicas tipo score/tokens ficam no log, nunca na tela).
		"""
		try:
			recap = build_session_recap(
				query=user_query,
				addon_name=getattr(self, "_current_plan_addon_name", "") or "",
				step_results=step_results,
				total_tokens=orch_result.total_tokens,
				duration_seconds=sum(r.execution_time_ms for r in step_results) / 1000.0,
				success=orch_result.success,
			)
			_logger.info("[RECAP]%s", recap)
		except Exception as e:
			_logger.debug("[RECAP] indisponivel: %s", e)

	def _run_conversational_pipeline(self, user_query: str):
		"""Executa o pipeline conversacional completo."""
		# Slice 3.6: o pipeline conversacional (criar/modificar addon pela GUI) e
		# a SEGUNDA entrada de producao. Com o agente como padrao, roteia pra ele
		# tambem -- assim os DOIS fluxos de producao usam o agente. So cai no
		# staged conversacional abaixo se o agente nao produzir nada (fallback).
		if _agentic_mode_enabled():
			if self._run_pipeline_agentic(user_query):
				return
			_logger.info("[AGENTIC] fallback: pipeline conversacional staged.")

		self._tokens_by_model = {}
		self._cancel_requested = False
		step_results: list[StepResult] = []
		outputs: dict[str, str] = {}
		self._auto_detected_deps: list[str] = []
		replan_count = 0
		domain_ctx: DomainContext | None = None

		try:
			# ------------------------------------------------------------------
			# FASE 1: CONVERSATION — Entender o usuario
			# ------------------------------------------------------------------
			self._check_cancel()
			self._emit_phase(PipelinePhase.CONVERSATION, "...")

			# ------------------------------------------------------------------
			# FASE 2: RESEARCH — Pesquisar dominio
			# ------------------------------------------------------------------
			self._check_cancel()
			self._emit_phase(PipelinePhase.RESEARCH, "...")
			narrate(f"pesquisando informacoes atualizadas sobre apis e bibliotecas para: {_truncate_at_word(user_query, 150)}")
			researcher = DomainResearcher()
			domain_ctx = researcher.research(user_query)

			# O DomainContext e contexto interno para Planner e subagentes. Nao emitir
			# o relatorio tecnico na fase: detalhes de APIs, seguranca e arquitetura
			# poluiam o historico destinado ao usuario e quebravam a conversa.
			# EXCECAO (2026-08-03, pedido do Felipe): research_sources agora sao
			# URLs reais de busca externa (Tavily/Exa, ver domain_researcher.py
			# 1.4.0) quando configurada -- diferente do relatorio tecnico, uma
			# lista curta de fontes tem valor de confianca/verificacao pro
			# usuario. emit_content() (nao narrate()) pra nao arriscar o LLM
			# reescrevendo/errando as URLs.
			# 5.88.0: research_sources carrega placeholders INTERNOS
			# ("conhecimento estatico", "conhecimento estatico + LLM") quando
			# nenhuma busca externa real rodou (domain_researcher.py). Emitir
			# isso como "Fontes consultadas: - conhecimento estatico" nao diz
			# nada ao usuario -- e ruido interno vazando pra conversa. So
			# emitimos fontes que sejam referencias reais; se sobrar so
			# placeholder, nao ha bloco de fontes a mostrar.
			_FONTES_PLACEHOLDER = {"conhecimento estatico", "conhecimento estatico + llm"}
			fontes_reais = [
				s for s in domain_ctx.research_sources
				if s and s.strip().casefold() not in _FONTES_PLACEHOLDER
			]
			if fontes_reais:
				sources_text = "Fontes consultadas:\n" + "\n".join(
					f"- {url}" for url in fontes_reais
				)
				conversation.emit_content(sources_text)
			self._check_cancel()

			# ------------------------------------------------------------------
			# FASE 3: PLANNING — Montar plano
			# ------------------------------------------------------------------
			self._check_cancel()
			self._emit_phase(PipelinePhase.PLANNING, "...")
			# 5.28.0: _emit_phase() vai pro callback on_phase_change, nao pro
			# on_progress -- quem escuta eventos via _emit()/on_progress
			# (a maioria dos consumidores reais, ver test_fluxo_completo_nvda
			# / test_criacao_completa / test_3_addons_reais) nunca via a
			# fase de planejamento acontecer. self._emit("PLANEJANDO", "")
			# nunca existia nesta pipeline.
			self._emit("PLANEJANDO", "")
			narrate(f"organizando os passos do plano de desenvolvimento para: {_truncate_at_word(user_query, 150)}")

			_plan_narrator = LiveNarrator()
			try:
				plan: ExecutionPlan = self._planner.create_plan(user_query, domain_ctx=domain_ctx, on_narration_chunk=_plan_narrator.feed)
			finally:
				_plan_narrator.flush()
			self._current_plan_addon_name = plan.addon_name
			self._plan_dependencies = plan.dependencies
			self._aplicar_orcamento_por_complexidade(plan)

			# ------------------------------------------------------------------
			# FASE 4: PLAN_APPROVAL — Mostrar e aguardar aprovacao
			# ------------------------------------------------------------------
			self._check_cancel()
			plan_text = self._planner.format_plan_for_user(plan, domain_ctx)
			self._emit_phase(PipelinePhase.PLAN_APPROVAL, plan_text)

			approval: PlanApproval | None = None
			if self._on_plan_ready:
				approval = self._on_plan_ready(plan, domain_ctx)
			else:
				# Sem callback — aprova automaticamente
				approval = PlanApproval(approved=True)

			# Loop de replanejamento por feedback do usuario
			while approval and not approval.approved and approval.modifications:
				self._check_cancel()
				self._emit_phase(PipelinePhase.PLANNING, "")

				try:
					_replan_narrator = LiveNarrator()
					try:
						plan = self._planner.replan_with_feedback(
							original_query=user_query,
							user_feedback=approval.modifications,
							domain_ctx=domain_ctx,
							on_narration_chunk=_replan_narrator.feed,
						)
					finally:
						_replan_narrator.flush()
					self._plan_dependencies = plan.dependencies
					plan_text = self._planner.format_plan_for_user(plan, domain_ctx)
					self._check_cancel()
					self._emit_phase(PipelinePhase.PLAN_APPROVAL, plan_text)

					if self._on_plan_ready:
						approval = self._on_plan_ready(plan, domain_ctx)
					else:
						approval = PlanApproval(approved=True)
				except Exception as exc:
					self._check_cancel()
					_logger.error("[ERRO] Replan com feedback falhou: %s", exc)
					approval = PlanApproval(approved=True)

			if not approval or not approval.approved:
				self._emit_phase(PipelinePhase.DONE, "")
				self._running = False
				return

			self._check_cancel()
			# "Construindo" (nao "Executando") -- este e o momento de escrever o codigo
			# do addon, ele ainda nao existe/roda; dizer "executando" confundia o usuario.
			narrate(f"comecando a construir o {plan.addon_name}")

			# ------------------------------------------------------------------
			# FASE 5: EXECUTING — Implementar com checkpoints
			# ------------------------------------------------------------------
			self._check_cancel()
			self._emit_phase(PipelinePhase.EXECUTING, "")

			# 5.87.0 -- espelha o _run_pipeline (FSM, ver o `self._current_plan =
			# plan` na fase de planejamento dele). Este pipeline conversacional
			# so setava _current_plan_addon_name e esquecia o plano inteiro, entao
			# TODO metodo plan-aware (_project_type, _arquivos_de_outros_steps,
			# a complexidade do replan, a propagacao de planejamento_degradado,
			# e agora _descarte_condena_entrega) degradava para o default seguro
			# aqui -- inclusive tratando um controller_client como "addon". Setado
			# com o plano JA aprovado (original ou o replanejado por feedback do
			# usuario logo acima), antes de qualquer step rodar.
			self._current_plan = plan

			remaining = list(plan.steps)
			failed_step_ids: set[str] = set()

			while remaining:
				self._check_cancel()
				# 5.60.0 -- DEGRADACAO GRACIOSA quando o orcamento estoura.
				#
				# Ate aqui, com o teto atingido, o laco seguia chamando CADA step
				# restante so para ele devolver score=0 com 'Orcamento excedido'.
				# Efeito observado ao vivo (2026-08-29): a nota media do relatorio
				# desabou para 7.1 e 8.9 -- numeros que parecem colapso de
				# qualidade, quando na verdade um step foi aprovado com 98 e o
				# resto nunca chegou a rodar. Relatorio que mente sobre a causa e
				# pior que relatorio de falha: manda investigar o lugar errado.
				#
				# Parar aqui e o que o documento de metodologia do projeto chama de
				# graceful degradation: entregar o que funcionou e dizer por que
				# parou, em vez de descartar tudo.
				_orcamento_ok, _orcamento_motivo = self._saldo_permite_seguir(
					remaining, failed_step_ids, plan, outputs,
				)
				if not _orcamento_ok:
					_nao_rodados = [s.step_id for s in remaining]
					_logger.warning(
						"[BUDGET] Parando o pipeline: %s. %d step(s) nao executados: %s",
						_orcamento_motivo, len(_nao_rodados), _nao_rodados[:8],
					)
					self._parou_por_orcamento = (_orcamento_motivo, len(_nao_rodados))
					break
				ready = [s for s in remaining if self._deps_ready(s, outputs)]
				if not ready:
					partial_ready = [
						s for s in remaining
						if self._deps_partially_ready(s, outputs, failed_step_ids)
					]
					if partial_ready:
						for pstep in partial_ready:
							missing = [d for d in pstep.depends_on if d not in outputs]
							_logger.info(
								"[INFO] Step %s: tentando com contexto parcial "
								"(dependencias faltando: %s).",
								pstep.step_id, ", ".join(missing),
							)
							_presult = self._run_isolated_step(
								pstep, user_query, self._build_context(pstep, outputs),
							)
							step_results.append(_presult)
							if _presult.approved or pstep.step_type in _NON_BLOCKING_STEP_TYPES:
								with self._outputs_lock:
									outputs[pstep.step_id] = (
										_presult.output if _presult.approved
										else _output_com_ressalva(_presult, pstep.step_type)
									)
								remaining.remove(pstep)
								# Checkpoint apos step
								self._checkpoint_after_step(pstep, _presult, plan)
								continue
							else:
								# 5.49.0: achado real ao vivo (test_e36, GeminiMultimodal) --
								# faltava este else. Sem remover pstep de `remaining` nem
								# marcar em failed_step_ids, um step de contexto parcial que
								# falha (ex: cg_core esperando cg_image/cg_video que deram
								# timeout) ficava RETENTANDO PRA SEMPRE, silenciosamente, a
								# cada volta do while remaining -- nunca aparecia no relatorio
								# final, nunca liberava o loop, e inflava a duracao total (essa
								# rodada levou 89min contra 15-22min de rodadas normais). Mesmo
								# padrao ja usado nos outros 3 pontos que marcam falha
								# (single-ready, parallel, resume) -- so faltava aqui.
								remaining.remove(pstep)
								failed_step_ids.add(pstep.step_id)
								try:
									agent_mem.remember(
										agent_type=pstep.step_type,
										pattern=(_presult.issues[0] if _presult.issues else pstep.description)[:200],
										success=False,
									)
								except Exception as _mem_exc:
									_logger.debug("[DEBUG] agent_memory.remember(falha) nao disponivel: %s", _mem_exc)
								self._checkpoint_after_step(pstep, _presult, plan)

					blocked_ids = ", ".join(s.step_id for s in remaining[:5])
					_logger.info(
						"[INFO] Encerrando loop com %d step(s) bloqueados por dependencias: %s",
						len(remaining), blocked_ids
					)
					break

				level_results: list[StepResult] = []

				if len(ready) == 1:
					step = ready[0]
					if step.step_type == STEP_USER_CLARIFICATION:
						with ThreadPoolExecutor(max_workers=1) as _cx:
							_cfut = _cx.submit(
								self._handle_clarification_step,
								step, outputs
							)
							result = _cfut.result()
					else:
						result = self._execute_step_with_critique(
							step, user_query,
							self._build_context(step, outputs)
						)

					if (step.step_type == "web_research"
						and not result.approved):
						pass  # Mensagem de web_research indisponivel removida.

					step_results.append(result)
					level_results.append(result)
					if result.approved or step.step_type in _NON_BLOCKING_STEP_TYPES:
						with self._outputs_lock:
							outputs[step.step_id] = (
								result.output if result.approved
								else _output_com_ressalva(result, step.step_type)
							)
					else:
						failed_step_ids.add(step.step_id)
						# Grava o erro em agent_memory -- so o sucesso era gravado antes,
						# entao get_common_mistakes() (usado em _build_step_prompt) nunca
						# tinha nada pra mostrar como "EVITE ESTES ERROS".
						try:
							agent_mem.remember(
								agent_type=step.step_type,
								pattern=(result.issues[0] if result.issues else step.description)[:200],
								success=False,
							)
						except Exception as _mem_exc:
							_logger.debug("[DEBUG] agent_memory.remember(falha) nao disponivel: %s", _mem_exc)
					remaining.remove(step)

					# Checkpoint apos step
					should_continue = self._checkpoint_after_step(step, result, plan)
					if not should_continue:
						self._emit_phase(PipelinePhase.DONE, "")
						self._running = False
						return

				else:
					# Execucao paralela
					parallel_results = self._execute_parallel(ready, user_query, outputs)
					for r in parallel_results:
						step_results.append(r)
						level_results.append(r)
						step = next(s for s in ready if s.step_id == r.step_id)
						if r.approved or step.step_type in _NON_BLOCKING_STEP_TYPES:
							with self._outputs_lock:
								outputs[r.step_id] = (
									r.output if r.approved
									else _output_com_ressalva(r, step.step_type)
								)
						else:
							failed_step_ids.add(r.step_id)
							try:
								agent_mem.remember(
									agent_type=step.step_type,
									pattern=(r.issues[0] if r.issues else step.description)[:200],
									success=False,
								)
							except Exception as _mem_exc:
								_logger.debug("[DEBUG] agent_memory.remember(falha) nao disponivel: %s", _mem_exc)

					for s in ready:
						remaining.remove(s)

					# Checkpoint apos lote paralelo — mensagem "terminei X etapas" removida.

					# Deteccao de degradacao sistemica — mensagem removida.

					# Replanejamento por falha critica — mensagem removida.
					# 5.28.0: replan tambem consulta can_continue() -- sem isso,
					# um pipeline ja acima do orcamento continuava replanejando
					# (cada replan reexecuta steps do zero, mais gasto).
					if (remaining
						and self._needs_replan(level_results)
						and replan_count < _MAX_REPLANS
						and iteration_budget.can_continue()[0]):
						replan_count += 1
						self._emit_phase(PipelinePhase.PLANNING,
							"Replanejando apos falha critica...")
						self._emit("REPLANEJANDO", "")
						new_remaining = self._do_replan(
							user_query, outputs, remaining, level_results
						)
						remaining = new_remaining

			# ------------------------------------------------------------------
			# FASE 6: REVIEW — Montar e mostrar resultado
			# ------------------------------------------------------------------
			artifact_error = self._validate_minimum_addon_artifacts(plan, step_results, outputs)
			artifact_error = self._mensagem_de_falha(artifact_error)
			if artifact_error:
				_logger.error("[ERRO] Pipeline sem artefatos essenciais: %s", artifact_error)
				failure = OrchestrationResult(
					plan_id=plan.plan_id,
					query=user_query,
					step_results=step_results,
					final_output="",
					success=False,
					error=artifact_error,
					total_retries=sum(r.retries_used for r in step_results),
					total_tokens=sum(r.tokens_used for r in step_results),
					total_tokens_medidor=iteration_budget.get_state().tokens_used,
				)
				failure.all_issues = [issue for r in step_results for issue in r.issues]
				self._record_iteration_budget(step_results)
				self._learn_from_session(user_query, False, failure.all_issues)
				self._last_result = failure
				if self._on_complete:
					self._on_complete(failure)
				return

			self._emit_phase(PipelinePhase.REVIEW, "")
			# Mensagem "Estou terminando!" removida — vai direto ao resultado.

			self._emit("MONTANDO", "")
			final = self._assemble(plan, outputs)

			_CODE_STEP_TYPES = {"code_generation", "agent_runner", "manifest_builder"}
			_asm_step = next((s for s in plan.steps if s.step_type == "assembly"), None)
			if _asm_step and _asm_step.step_id in outputs:
				_assembly_out = outputs[_asm_step.step_id]
			else:
				_assembly_out = "\n\n".join(
					outputs[s.step_id] for s in plan.steps
					if s.step_type in _CODE_STEP_TYPES and s.step_id in outputs
				)

			merged_deps = list(plan.dependencies)
			for dep in self._auto_detected_deps:
				if dep not in merged_deps:
					merged_deps.append(dep)

			estimated_cost = estimate_pipeline_cost(dict(self._tokens_by_model))
			orch_result = OrchestrationResult(
				plan_id=plan.plan_id, query=user_query,
				step_results=step_results,
				final_output=final, success=True,
				total_retries=sum(r.retries_used for r in step_results),
				dependencies=merged_deps,
				assembly_output=_assembly_out,
				total_tokens=sum(r.tokens_used for r in step_results),
					total_tokens_medidor=iteration_budget.get_state().tokens_used,
				tokens_by_model=dict(self._tokens_by_model),
				estimated_cost_usd=estimated_cost,
				replan_count=replan_count,
				completed_message=plan.completed_message,
				project_type=plan.project_type,
			)
			orch_result.all_issues = [
				issue for r in step_results for issue in r.issues
			]

			# ------------------------------------------------------------------
			# WIRING: Conectar 7 módulos ao sucesso do pipeline
			# v2.1.0: evaluation_framework, web_search_tool, agent_memory, etc
			# ------------------------------------------------------------------
			try:
				# 1. Record metrics em evaluation_framework para trending
				# BUGFIX (achado de auditoria 2026-08-04): instanciava
				# PipelineEvaluator() do zero a cada chamada -- _metrics/
				# _baseline nasciam vazios toda vez e eram descartados no
				# fim do bloco (GC), entao check_regression()/
				# get_weakest_area() nunca tinham historico de verdade pra
				# analisar, mesmo com "WIRING" completando sem erro. Usa a
				# instancia global `evaluation` (mesmo modulo, unica pra
				# todo o processo) em vez de uma nova a cada pipeline.
				from ..utils.evaluation_framework import evaluation as evaluator
				evaluator.record_pipeline_result(
					pipeline_id=plan.plan_id,
					duration_seconds=sum(r.execution_time_ms for r in step_results) / 1000.0,
					success=True,
					token_count=orch_result.total_tokens,
					issues=orch_result.all_issues,
					final_model_used=step_results[-1].model_id if step_results else "unknown",
				)
				_logger.info("[WIRING] evaluation_framework.record_pipeline_result() completado.")
			except Exception as e:
				_logger.warning("[WIRING] evaluation_framework falhou: %s. Continuando.", e)

			try:
				# 2. Record memory em agent_memory para pattern learning
				# Bug real de auditoria: criava AgentMemory() nova (descartavel) em vez de
				# usar o singleton "agent_mem" ja importado no topo do arquivo -- toda
				# chamada .remember() gravava num objeto que morria logo em seguida, e
				# _build_step_prompt() (que LE do singleton certo via get_common_mistakes/
				# get_successful_patterns) nunca via nada gravado. Corrigido: usa agent_mem
				# diretamente (mesma instancia global de memory/agent_memory.py).
				for step in plan.steps:
					if step.step_id in outputs:
						agent_mem.remember(
							agent_type=step.step_type,
							pattern=f"Success on {step.user_message or step.description}",
							outcome=outputs[step.step_id][:100],  # primeiros 100 chars
						)
				_logger.info("[WIRING] agent_memory.remember() completado para %d steps.", len(plan.steps))
			except Exception as e:
				_logger.warning("[WIRING] agent_memory falhou: %s. Continuando.", e)

			# 3. Record em memory_manager (Hermes-inspired MEMORY.md/USER.md) --
			# helper compartilhado (_learn_from_session acima), tambem chamado
			# nos caminhos de FALHA e no outro pipeline (_run_pipeline), nao so
			# aqui no sucesso.
			self._learn_from_session(user_query, orch_result.success, orch_result.all_issues)
			self._log_session_recap(user_query, orch_result, step_results)

			# 4. Record em iteration_budget para controle de custo (helper
			# compartilhado -- ver _record_iteration_budget() acima, tambem
			# chamado nos caminhos de FALHA, nao so aqui no sucesso).
			self._record_iteration_budget(step_results)

			try:
				# 5. Skills usage stats via skills_hub
				for step in plan.steps:
					if step.step_id in outputs:
						skill = get_skill(step.step_type)
						if skill:
							_logger.debug("[WIRING] Skill %s usada com sucesso", skill.name)
				_logger.info("[WIRING] skills_hub usage stats atualizados.")
			except Exception as e:
				_logger.warning("[WIRING] skills_hub falhou: %s. Continuando.", e)

			# ------------------------------------------------------------------
			# FASE 7: DONE
			# ------------------------------------------------------------------
			self._emit_phase(PipelinePhase.DONE, plan.completed_message)
			# Mensagem de conclusao removida — resultado ja aparece na UI.

			# v2.2.0: Session Recap + Proactive Suggestions — removido para evitar spam.
			# O usuario ve o resultado diretamente, sem mensagens genericas de fechamento.

			self._emit("CONCLUIDO", "")
			self._last_result = orch_result
			if self._on_complete and not self._suppress_complete_callback:
				self._on_complete(orch_result)

		except Exception as exc:
			_logger.error("[ERRO] Orchestrator: falha critica: %s", exc)
			if str(exc) == "Cancelado pelo usuário":
				self._emit_conversation("ia", "Desenvolvimento cancelado.", kind="status")
				self._emit_phase(PipelinePhase.DONE, "Cancelado")
				failure = OrchestrationResult(
					plan_id="?", query=user_query, step_results=step_results,
					final_output="", success=False, error="Cancelado pelo usuário"
				)
			else:
				self._emit_conversation("ia",
					f"Erro: {exc}.",
					kind="status"
				)
				self._emit("ERRO", "")
				failure = OrchestrationResult(
					plan_id="?", query=user_query, step_results=step_results,
					final_output="", success=False, error=str(exc)
				)
			self._record_iteration_budget(step_results)
			self._learn_from_session(user_query, False, failure.all_issues or [str(exc)])
			self._last_result = failure
			if self._on_complete and not self._suppress_complete_callback:
				self._on_complete(failure)
		finally:
			self._running = False

	def _checkpoint_after_step(
		self, step: ExecutionStep, result: StepResult, plan: ExecutionPlan
	) -> bool:
		"""
		Checkpoint INTERATIVO v2.0 (Hermes-inspired).

		Apos cada step visivel, pergunta ao usuario:
		  - CONTINUAR → segue em frente
		  - REFAZER → restaura ultimo checkpoint e repete a fase
		  - PAUSAR → salva estado, usuario continua depois

		So ativa para steps de code_generation, assembly, manifest_builder.
		"""
		try:
			execution_context_store.save_step(plan, step, result)
		except Exception as exc:
			_logger.warning("[CONTEXT] Falha ao persistir contexto do step %s: %s", step.step_id, exc)

		_checkpoint_step_types = {"code_generation", "assembly", "agent_runner", "manifest_builder"}
		if step.step_type not in _checkpoint_step_types:
			return True

		# Determina diretorio de trabalho (output_dir do projeto)
		from ..gui.settings_panel import get_output_dir
		workdir = get_output_dir()

		# Resumo em linguagem simples para o usuario -- Score/Step type/Tokens usados
		# sao detalhes internos de engenharia (uteis pro log, nao pra conversa); o
		# usuario so precisa saber SE deu certo e, se nao, o que aconteceu.
		etapa_nome = step.user_message or step.description[:60]
		if result.approved:
			summary = f"Etapa concluida: {etapa_nome}"
		else:
			summary = f"Tivemos um problema nesta etapa: {etapa_nome}"
		details = []
		if result.issues:
			details.append(result.issues[0][:120])
		_logger.info(
			"[CHECKPOINT] step=%s aprovado=%s score=%s tokens=%s",
			step.step_id, result.approved, result.score, result.tokens_used,
		)
		# Usa o checkpoint_manager v2.0 (interativo com 3 opcoes)
		ic = checkpoint_manager.ask_checkpoint(
			phase=step.step_type,
			summary=summary,
			details=details,
			files_affected=[step.step_type],
			workdir=workdir,
		)

		if ic.action == CheckpointAction.PAUSE:
			_logger.info("[CHECKPOINT] Usuario pediu PAUSE na etapa %s", step.step_id)
			# Salva estado atual no task_tracker para recuperacao
			task_tracker.update_issues(step.step_id, ["Pausado pelo usuario"])
			self._emit_conversation("ia",
				"Tudo bem! Pausando aqui. Quando quiser continuar, e so pedir.",
				kind="status"
			)
			return False

		elif ic.action == CheckpointAction.REDO:
			_logger.info("[CHECKPOINT] Usuario pediu REDO na etapa %s", step.step_id)
			# O checkpoint_manager ja restaurou o estado automaticamente
			# Precisamos indicar ao caller que deve REPETIR este step
			self._emit_conversation("ia",
				"OK! Vou refazer esta etapa. Restaurando o estado anterior...",
				kind="status"
			)
			# Nota: retornar True aqui significa "continue o pipeline".
			# Para implementar REDO completo, precisariamos de um mecanismo
			# de retry no nivel do step. Por enquanto, informamos o usuario.
			return True

		# CONTINUE (default)
		return True

	def _emit(self, event: str, detail: str):
		_logger.info("[PROGRESS] %s: %s", event, detail)
		if self._on_progress:
			self._on_progress(event, detail)

	# ------------------------------------------------------------------
	# Pipeline principal
	# ------------------------------------------------------------------

	def _run_pipeline_agentic(self, user_query: str) -> bool:
		"""Slice 3 do Caminho 3: gera o addon pelo driver AGENTICO (droid dirige
		editar->rodar->corrigir) em vez do pipeline staged.

		Retorna True se ENTREGOU (disparou on_complete), False se nao conseguiu
		produzir nada -- ai o chamador (_run_pipeline) cai no staged (fallback).
		So roda com a flag NVDASTUDIO_AGENTIC_MODE ligada. O gate deterministico
		(code_sandbox) e a auto-correcao vivem DENTRO de run_agentic_build
		(Slice 2); aqui o resultado agentico vira o formato de blocos que a GUI
		ja empacota -- mesma entrega + portao final do staged, sem duplicar.
		"""
		self._running = True
		self._last_result = None
		try:
			from ..builder.agentic_driver import run_agentic_build
		except Exception as exc:  # pragma: no cover - defesa
			_logger.error("[AGENTIC] driver indisponivel (%s) -- caindo pro staged.", exc)
			return False

		self._emit("PLANEJANDO", "")
		self._emit("EXECUTANDO", "code_generation")
		try:
			build = run_agentic_build(
				user_query,
				correction_rounds=_AGENTIC_CORRECTION_ROUNDS,
				use_nvda_context=True,
			)
		except Exception as exc:  # pragma: no cover - defesa
			_logger.error("[AGENTIC] falha inesperada (%s) -- caindo pro staged.", exc)
			return False

		if not build.files:
			_logger.warning("[AGENTIC] nenhum arquivo produzido -- caindo pro staged.")
			return False

		blocks = _agentic_files_to_blocks(build.workdir, build.files)
		step = StepResult(
			step_id="agentic",
			step_type=STEP_CODE_GENERATION,
			output=blocks,
			approved=build.execution_ok,
			score=100 if build.execution_ok else 0,
			issues=[build.gate_report] if build.gate_report else [],
			model_used="factory::agentic",
		)
		orch_result = OrchestrationResult(
			plan_id="agentic",
			query=user_query,
			step_results=[step],
			final_output=blocks,
			success=build.execution_ok,
			error=None if build.execution_ok else (build.gate_report or "gate de execucao nao passou"),
			total_retries=max(build.rounds - 1, 0),
		)
		self._emit("MONTANDO", "")
		self._emit("CONCLUIDO", "")
		self._last_result = orch_result
		if self._on_complete and not self._suppress_complete_callback:
			self._on_complete(orch_result)
		return True

	def _run_pipeline(
		self,
		user_query: str,
		resume_plan: "ExecutionPlan | None" = None,
		resume_completed: "dict[str, StepResult] | None" = None,
	):
		"""
		resume_plan/resume_completed (achado de auditoria 2026-08-04): usados
		por core/agentic_loop.py::surgical_replan() pra retomar de verdade um
		plano ja criado, pulando os steps ja aprovados na tentativa anterior --
		antes disso, surgical_replan chamava create_plan() de novo (LLM, plano
		NOVO e nao-deterministico, step_ids podem nem bater) e reexecutava TUDO
		do zero, identico a qualquer outra estrategia do FSM, apesar do nome e
		do docstring prometerem preservar steps concluidos. Quando fornecidos,
		o plano e reaproveitado (mesmos step_ids) e os steps ja aprovados
		entram direto em `outputs`/`step_results` -- o motor de dependencias
		existente (_deps_ready) cuida do resto sozinho, reexecutando so o step
		que falhou e quem depende dele (dependentes nunca tiveram outputs[id]
		setado na tentativa anterior, entao ficam bloqueados ate isso rodar de
		novo aqui).
		"""
		# Slice 3 (Caminho 3): com a flag ligada e fora de retomada, tenta o
		# caminho AGENTICO primeiro. So segue pro staged abaixo se ele nao
		# produzir nada (fallback seguro -- o staged e o default comprovado).
		if resume_plan is None and _agentic_mode_enabled():
			if self._run_pipeline_agentic(user_query):
				return
			_logger.info("[AGENTIC] fallback: seguindo pelo pipeline staged.")

		self._tokens_by_model = {}
		self._last_result = None
		self._running = True
		self._cancel_requested = False
		step_results: list[StepResult] = list((resume_completed or {}).values())
		outputs: dict[str, str] = {sid: r.output for sid, r in (resume_completed or {}).items()}
		self._auto_detected_deps = []
		replan_count = 0

		try:
			self._check_cancel()
			# 5.28.0: mesmo gap de _run_conversational_pipeline -- este
			# pipeline (usado por agentic_loop.py/FSM) nunca emitia
			# "PLANEJANDO" via on_progress antes de criar/retomar o plano.
			self._emit("PLANEJANDO", "")
			plan: ExecutionPlan = resume_plan if resume_plan is not None else self._planner.create_plan(user_query)
			self._current_plan = plan
			self._current_plan_addon_name = plan.addon_name
			self._plan_dependencies = plan.dependencies
			self._aplicar_orcamento_por_complexidade(plan)

			remaining = [s for s in plan.steps if s.step_id not in (resume_completed or {})]
			failed_step_ids: set[str] = set()
			while remaining:
				self._check_cancel()
				# 5.60.0 -- DEGRADACAO GRACIOSA quando o orcamento estoura.
				#
				# Ate aqui, com o teto atingido, o laco seguia chamando CADA step
				# restante so para ele devolver score=0 com 'Orcamento excedido'.
				# Efeito observado ao vivo (2026-08-29): a nota media do relatorio
				# desabou para 7.1 e 8.9 -- numeros que parecem colapso de
				# qualidade, quando na verdade um step foi aprovado com 98 e o
				# resto nunca chegou a rodar. Relatorio que mente sobre a causa e
				# pior que relatorio de falha: manda investigar o lugar errado.
				#
				# Parar aqui e o que o documento de metodologia do projeto chama de
				# graceful degradation: entregar o que funcionou e dizer por que
				# parou, em vez de descartar tudo.
				_orcamento_ok, _orcamento_motivo = self._saldo_permite_seguir(
					remaining, failed_step_ids, plan, outputs,
				)
				if not _orcamento_ok:
					_nao_rodados = [s.step_id for s in remaining]
					_logger.warning(
						"[BUDGET] Parando o pipeline: %s. %d step(s) nao executados: %s",
						_orcamento_motivo, len(_nao_rodados), _nao_rodados[:8],
					)
					self._parou_por_orcamento = (_orcamento_motivo, len(_nao_rodados))
					break
				ready = [s for s in remaining if self._deps_ready(s, outputs)]
				if not ready:
					partial_ready = [
						s for s in remaining
						if self._deps_partially_ready(s, outputs, failed_step_ids)
					]
					if partial_ready:
						for pstep in partial_ready:
							missing = [d for d in pstep.depends_on if d not in outputs]
							_logger.info(
								"[INFO] Step %s: tentando com contexto parcial "
								"(dependencias faltando: %s).",
								pstep.step_id, ", ".join(missing),
							)
							_presult = self._run_isolated_step(
								pstep, user_query, self._build_context(pstep, outputs),
							)
							step_results.append(_presult)
							if _presult.approved or pstep.step_type in _NON_BLOCKING_STEP_TYPES:
								with self._outputs_lock:
									outputs[pstep.step_id] = (
										_presult.output if _presult.approved
										else _output_com_ressalva(_presult, pstep.step_type)
									)
								remaining.remove(pstep)
								# 5.44.0: achado real de auditoria de integracao --
								# este loop (usado por agentic_loop.py::surgical_replan()
								# pra retomar apos falha) tem estrutura identica ao de
								# _run_conversational_pipeline(), mas nunca chamava
								# _checkpoint_after_step(). O usuario perdia a chance
								# de PAUSAR/REFAZER especificamente nos steps que
								# rodam apos um replan cirurgico.
								self._checkpoint_after_step(pstep, _presult, plan)
								continue
							else:
								# 5.49.0: mesmo achado real do outro loop equivalente acima --
								# faltava remover pstep de `remaining`/marcar failed_step_ids
								# quando o contexto parcial nao resolve. Sem isso, um step
								# como cg_core ficava retentando pra sempre, silenciosamente,
								# tambem nesta variante (usada por surgical_replan()).
								remaining.remove(pstep)
								failed_step_ids.add(pstep.step_id)
								try:
									agent_mem.remember(
										agent_type=pstep.step_type,
										pattern=(_presult.issues[0] if _presult.issues else pstep.description)[:200],
										success=False,
									)
								except Exception as _mem_exc:
									_logger.debug("[DEBUG] agent_memory.remember(falha) nao disponivel: %s", _mem_exc)
								self._checkpoint_after_step(pstep, _presult, plan)

					blocked_ids = ", ".join(s.step_id for s in remaining[:5])
					_logger.info(
						"[INFO] Encerrando loop com %d step(s) bloqueados por dependencias: %s",
						len(remaining), blocked_ids
					)
					log_decision(
						_logger, "steps_bloqueados_dependencia",
						f"count={len(remaining)} ids={blocked_ids}"
					)
					break

				level_results: list[StepResult] = []

				if len(ready) == 1:
						if ready[0].step_type == STEP_USER_CLARIFICATION:
							with ThreadPoolExecutor(max_workers=1) as _cx:
								_cfut = _cx.submit(
									self._handle_clarification_step,
									ready[0], outputs
								)
								result = _cfut.result()
						else:
							result = self._execute_step_with_critique(
								ready[0], user_query,
								self._build_context(ready[0], outputs)
							)
						if (ready[0].step_type == "web_research"
							and not result.approved):
							# Mensagem de web_research indisponivel removida — evita spam.
							pass
						step_results.append(result)
						level_results.append(result)
						if result.approved or ready[0].step_type in _NON_BLOCKING_STEP_TYPES:
							with self._outputs_lock:
								outputs[ready[0].step_id] = (
									result.output if result.approved
									else _output_com_ressalva(result, ready[0].step_type)
								)
						else:
							failed_step_ids.add(ready[0].step_id)
							try:
								agent_mem.remember(
									agent_type=ready[0].step_type,
									pattern=(result.issues[0] if result.issues else ready[0].description)[:200],
									success=False,
								)
							except Exception as _mem_exc:
								_logger.debug("[DEBUG] agent_memory.remember(falha) nao disponivel: %s", _mem_exc)
						remaining.remove(ready[0])

						# 5.44.0: mesmo fix acima -- caminho single-ready deste loop
						# tambem nunca chamava _checkpoint_after_step(). Diferente de
						# _run_conversational_pipeline() (que aborta o pipeline inteiro
						# em PAUSE), aqui um PAUSE so interrompe o loop de retomada --
						# quem chamou _run_pipeline() (agentic_loop.py) trata o retorno
						# normalmente, sem crashar o FSM.
						should_continue = self._checkpoint_after_step(ready[0], result, plan)
						if not should_continue:
							self._emit_phase(PipelinePhase.DONE, "")
							self._running = False
							return
				else:
					parallel_results = self._execute_parallel(ready, user_query, outputs)
					for r in parallel_results:
						step_results.append(r)
						level_results.append(r)
						step = next(s for s in ready if s.step_id == r.step_id)
						if r.approved or step.step_type in _NON_BLOCKING_STEP_TYPES:
							with self._outputs_lock:
								outputs[r.step_id] = (
									r.output if r.approved
									else _output_com_ressalva(r, step.step_type)
								)
						else:
							failed_step_ids.add(r.step_id)
							try:
								agent_mem.remember(
									agent_type=step.step_type,
									pattern=(r.issues[0] if r.issues else step.description)[:200],
									success=False,
								)
							except Exception as _mem_exc:
								_logger.debug("[DEBUG] agent_memory.remember(falha) nao disponivel: %s", _mem_exc)

					for s in ready:
						remaining.remove(s)

					_done_blocking = [r for r in step_results if r.step_type not in _NON_BLOCKING_STEP_TYPES]
					if len(_done_blocking) >= 3:
						_retried_count = sum(1 for r in _done_blocking if r.retries_used > 0)
						if _retried_count / len(_done_blocking) >= 0.4:
							# Mensagem de degradacao removida — evita poluir o historico.
							log_decision(_logger, "degradacao_sistemica",
								f"steps_com_retry={_retried_count}/{len(_done_blocking)}")

					# 5.28.0: mesmo guard de orcamento do outro caminho (_run_pipeline).
					if (remaining
						and self._needs_replan(level_results)
						and replan_count < _MAX_REPLANS
						and iteration_budget.can_continue()[0]):
						replan_count += 1
						# Mensagem de status (narracao) removida — evita poluir o
						# historico. Evento discreto self._emit (5.30.0) mantido.
						self._emit("REPLANEJANDO", "")
						new_remaining = self._do_replan(
							user_query, outputs, remaining, level_results
						)
						remaining = new_remaining
						log_decision(_logger, "replan_aplicado",
							f"replan={replan_count} novos_steps={len(remaining)}")

			artifact_error = self._validate_minimum_addon_artifacts(plan, step_results, outputs)
			artifact_error = self._mensagem_de_falha(artifact_error)
			if artifact_error:
				_logger.error("[ERRO] Pipeline sem artefatos essenciais: %s", artifact_error)
				failure = OrchestrationResult(
					plan_id=plan.plan_id,
					query=user_query,
					step_results=step_results,
					final_output="",
					success=False,
					error=artifact_error,
					total_retries=sum(r.retries_used for r in step_results),
					total_tokens=sum(r.tokens_used for r in step_results),
					total_tokens_medidor=iteration_budget.get_state().tokens_used,
				)
				failure.all_issues = [issue for r in step_results for issue in r.issues]
				self._record_iteration_budget(step_results)
				self._learn_from_session(user_query, False, failure.all_issues)
				self._last_result = failure
				if self._on_complete and not self._suppress_complete_callback:
					self._on_complete(failure)
				return

			self._emit("MONTANDO", "")
			final = self._assemble(plan, outputs)

			_CODE_STEP_TYPES = {"code_generation", "agent_runner", "manifest_builder"}
			_asm_step = next((s for s in plan.steps if s.step_type == "assembly"), None)
			if _asm_step and _asm_step.step_id in outputs:
				_assembly_out = outputs[_asm_step.step_id]
			else:
				_assembly_out = "\n\n".join(
					outputs[s.step_id] for s in plan.steps
					if s.step_type in _CODE_STEP_TYPES and s.step_id in outputs
				)

			merged_deps = list(plan.dependencies)
			for dep in self._auto_detected_deps:
				if dep not in merged_deps:
					merged_deps.append(dep)
					_logger.info("[OK] Dependencia auto-detectada: %s", dep)

			estimated_cost = estimate_pipeline_cost(dict(self._tokens_by_model))
			orch_result = OrchestrationResult(
				plan_id=plan.plan_id, query=user_query,
				step_results=step_results,
				final_output=final, success=True,
				total_retries=sum(r.retries_used for r in step_results),
				dependencies=merged_deps,
				assembly_output=_assembly_out,
				total_tokens=sum(r.tokens_used for r in step_results),
					total_tokens_medidor=iteration_budget.get_state().tokens_used,
				tokens_by_model=dict(self._tokens_by_model),
				estimated_cost_usd=estimated_cost,
				replan_count=replan_count,
				completed_message=plan.completed_message,
				project_type=plan.project_type,
			)
			orch_result.all_issues = [
				issue for r in step_results for issue in r.issues
			]
			self._emit("CONCLUIDO", "")
			self._record_iteration_budget(step_results)
			self._learn_from_session(user_query, orch_result.success, orch_result.all_issues)
			self._log_session_recap(user_query, orch_result, step_results)
			self._last_result = orch_result
			if self._on_complete and not self._suppress_complete_callback:
				self._on_complete(orch_result)

		except Exception as exc:
			_logger.error("[ERRO] Orchestrator: falha critica: %s", exc)
			self._emit("ERRO", "")
			err_str = "Cancelado pelo usuário" if str(exc) == "Cancelado pelo usuário" else str(exc)
			failure = OrchestrationResult(
				plan_id="?", query=user_query, step_results=step_results,
				final_output="", success=False, error=err_str
			)
			self._record_iteration_budget(step_results)
			self._learn_from_session(user_query, False, failure.all_issues or [err_str])
			self._last_result = failure
			if self._on_complete and not self._suppress_complete_callback:
				self._on_complete(failure)
		finally:
			self._running = False

	# ------------------------------------------------------------------
	# Mid-pipeline clarification
	# ------------------------------------------------------------------

	def _handle_clarification_step(
		self,
		step: ExecutionStep,
		outputs: dict[str, str],
	) -> StepResult:
		"""
		Processa step user_clarification:
		1. Extrai perguntas do campo description (separadas por |)
		2. Chama on_clarify callback (bloqueante — aguarda resposta do usuario)
		3. Formata respostas como contexto e armazena no output do step
		4. Steps seguintes recebem esse contexto via context_from_steps

		Graceful degradation: se callback nao definido, continua sem perguntar.
		Regra 9: nao executa nenhum codigo — apenas texto.
		Regra 5: LLM decidiu incluir esse step; Orchestrator executa o fluxo.
		"""
		questions = [q.strip() for q in step.description.split("|") if q.strip()]
		if not questions:
			# Step mal formado — ignora silenciosamente
			return StepResult(
				step_id=step.step_id, step_type=step.step_type,
				output="", approved=True, score=100,
			)

		self._emit(
			"AGUARDANDO_USUARIO",
			f"Preciso de mais informacoes para continuar. "
			f"{len(questions)} pergunta(s) adicionais."
		)
		log_decision(_logger, "clarificacao_mid_pipeline",
					 f"step={step.step_id} perguntas={len(questions)}")

		answers: list[str] = []
		if self._on_clarify:
			try:
				answers = self._on_clarify(questions)
			except Exception as exc:
				_logger.warning("[AVISO] on_clarify falhou: %s. Continuando sem respostas.", exc)

		# Monta texto de contexto com perguntas + respostas
		ctx_lines = ["Informacoes adicionais coletadas mid-pipeline:"]
		for q, a in zip(questions, answers, strict=False):
			ctx_lines.append(f"- Pergunta: {q}")
			ctx_lines.append(f"  Resposta: {a.strip() if a.strip() else '(sem resposta)'}")
		context_output = "\n".join(ctx_lines)

		return StepResult(
			step_id=step.step_id, step_type=step.step_type,
			output=context_output, approved=True, score=100,
		)

	# ------------------------------------------------------------------
	# Replanejamento dinamico
	# ------------------------------------------------------------------

	def _needs_replan(self, level_results: list[StepResult]) -> bool:
		"""
		Verifica se o plano precisa ser refeito com base nos resultados do nivel atual.
		Replaneja apenas quando step critico foi rejeitado apos todas as tentativas e escalacao.
		Regra 5: decisao deterministica baseada em resultado — nao semantica.
		"""
		for r in level_results:
			if not r.approved and r.step_type in _CRITICAL_STEP_TYPES:
				_logger.info(
					"[REPLAN] Step critico nao aprovado: %s (%s). Replanejamento necessario.",
					r.step_id, r.step_type
				)
				return True
		return False

	def _diversify_failed_models(self, failed_level: list[StepResult]) -> dict[str, str] | None:
		"""
		Cross-model escalation para o replan (pratica 2026 validada): quando
		um step critico chega ao replan, ele ja esgotou retry normal E
		escalacao (_get_resilience_model()) sem sucesso -- repetir o MESMO
		modelo pela 3a vez tem retorno decrescente. Modelos diferentes tem
		modos de falha complementares (um erro que trava um modelo
		frequentemente esta fora da distribuicao de falhas de outro), entao
		o replan forca o proximo modelo na cadeia de fallback do provider
		(model_registry.get_fallback_chain) para cada step_type critico que
		falhou, em vez de deixar a resolucao dinamica normal escolher de novo
		o mesmo tier heavy que ja falhou.
		"""
		from ..ai.model_registry import registry
		model_map: dict[str, str] = {}
		for r in failed_level:
			if r.approved or r.step_type not in _CRITICAL_STEP_TYPES:
				continue
			failed_model = r.model_used or r.model_id
			if not failed_model:
				continue
			chain = registry.get_fallback_chain(failed_model)
			next_model = chain[1] if len(chain) > 1 else None
			if next_model:
				model_map[r.step_type] = next_model
				_logger.info(
					"[REPLAN] Diversificando modelo de %s: %s -> %s (cross-model escalation)",
					r.step_type, failed_model, next_model,
				)
		return model_map or None

	def _do_replan(
		self,
		original_query: str,
		outputs: dict[str, str],
		remaining: list[ExecutionStep],
		failed_level: list[StepResult],
	) -> list[ExecutionStep]:
		"""
		Chama planner.replan() para gerar novos steps para o restante do pipeline.
		Se o replan falhar, mantem os steps originais (sem crash do pipeline).
		"""
		outputs_summary = {
			sid: (out[:250] + "..." if len(out) > 250 else out)
			for sid, out in outputs.items()
		}
		all_issues = [
			f"[{r.step_type}] {issue}"
			for r in failed_level
			for issue in r.issues
			if not r.approved
		]
		try:
			new_steps = self._planner.replan(
				original_query=original_query,
				outputs_summary=outputs_summary,
				remaining_steps=remaining,
				issues=all_issues,
				model_map=self._diversify_failed_models(failed_level),
				complexity=getattr(self._current_plan, "estimated_complexity", "medium"),
			)
			return new_steps
		except Exception as exc:
			_logger.error("[ERRO] _do_replan falhou: %s. Mantendo steps originais.", exc)
			return list(remaining)

	# ------------------------------------------------------------------
	# Escalacao de modelo (handoff)
	# ------------------------------------------------------------------

	def _provedor_atual(self) -> str:
		"""Provedor configurado, ou "" quando nao da para saber."""
		try:
			from ..gui.settings_panel import get_llm_provider

			return get_llm_provider()
		except Exception:  # pragma: no cover - defesa
			return ""

	def _current_complexity(self) -> str:
		"""5.36.0: complexidade do plano atual, pra alimentar
		_get_resilience_model()/ai/model_router.py na escalacao -- sem
		plano ainda (chamado cedo demais) ou campo ausente, "medium" e o
		default seguro (mesmo default de apply_model_budget())."""
		return getattr(self._current_plan, "estimated_complexity", "medium")

	def get_resilience_model(self, step_type: str = "") -> str:
		"""Interface publica para "qual e o proximo modelo a tentar" para um
		step_type, usando a MESMA logica (ai/model_router.py::select_model,
		ponderada por step_type e pela complexidade do plano atual) que a
		escalacao interna do pipeline usa em _try_escalation().

		5.56.0: achado de auditoria 2026-08-25 -- core/agentic_loop.py::
		StrategyExecutor.swap_model() tinha sua PROPRIA logica de escalacao,
		cega a step_type e complexidade (so alternava entre tier "light" e
		"heavy"), duplicando com pior informacao a escolha que este metodo
		ja faz. As duas podiam divergir para o mesmo step_type: a escalacao
		interna do pipeline escolhendo um modelo pela pontuacao real de
		model_router.py, o SWAP_MODEL da FSM escolhendo outro so pelo tier.
		Agora ambas chamam este metodo -- fonte unica para essa decisao.
		"""
		return _get_resilience_model(step_type, self._current_complexity())

	def _try_cross_provider_rescue(
		self, step: ExecutionStep, prompt: str, context: str,
	) -> StepResult | None:
		"""
		5.37.0: generalizado de _try_web_research_cross_provider_rescue()
		(5.32.0, especifico do OpenCode Go pro web_research) pra qualquer
		step_type em _ESCALATION_ELIGIBLE_STEP_TYPES, chamado DEPOIS que a
		escalacao normal (mesmo provider, select_model() dentro dele) ja
		esgotou. Pesquisa dedicada 2026-08-09 (padrao de producao 2026,
		Bifrost/LiteLLM): failover entre providers e um degrau SEPARADO do
		roteamento normal, acionado so quando o provider ativo ja falhou --
		nao pontua todos os providers desde o inicio (isso e C:\\agentic,
		mais sofisticado que o padrao dominante do mercado).

		ai/model_router.py::select_model_and_provider() pontua candidatos de
		TODOS os providers com chave configurada (exceto o ja tentado) e
		retorna o melhor par (provider, model_id). O dispatch usa a
		convencao "<provider>::<model_id>" (llm_factory.py 5.2.0) pra forcar
		esse provider especifico SEM precisar mudar a assinatura de
		dispatch_step_with_tokens() nem de nenhum sub-agente -- o step roda
		pelo caminho normal (web_researcher.run(), code_generator.run(),
		etc.), so com o provider trocado nessa unica tentativa.

		Retorna None quando nao ha OUTRO provider com chave configurada
		(fail-open -- comportamento identico a antes deste mecanismo
		existir) ou o resgate tambem falhou a avaliacao.
		"""
		if step.step_type not in _ESCALATION_ELIGIBLE_STEP_TYPES:
			return None
		from ..gui.settings_panel import get_llm_provider
		from ..ai.model_router import select_model_and_provider
		current_provider = get_llm_provider()
		picked = select_model_and_provider(
			step.step_type, self._current_complexity(),
			exclude_provider=current_provider, active_provider=current_provider,
		)
		if picked is None:
			return None
		rescue_provider, rescue_model = picked
		try:
			output, rescue_tokens = dispatch_step_with_tokens(
				step_type=step.step_type,
				prompt=prompt,
				model_id=f"{rescue_provider}::{rescue_model}",
				reasoning_params=_ESCALATION_REASONING_BY_TYPE.get(step.step_type, {}),
			)
		except Exception as exc:
			_logger.warning(
				"[RESCUE] %s via %s (%s) falhou: %s",
				step.step_type, rescue_provider, rescue_model, exc,
			)
			return None
		crit = self._critic.evaluate_two_stage(step.step_type, output, _critic_context(step, context, project_type=self._project_type()))
		if crit.verdict != Verdict.APPROVED:
			_logger.info("[RESCUE] %s via %s (%s) nao resolveu.", step.step_type, rescue_provider, rescue_model)
			return None
		_logger.info("[RESCUE] %s resgatado via %s (%s).", step.step_type, rescue_provider, rescue_model)
		return StepResult(
			step_id=step.step_id, step_type=step.step_type,
			output=output, approved=True,
			score=crit.score, issues=[],
			retries_used=step.max_retries,
			tokens_used=rescue_tokens,
			model_used=f"{rescue_provider}/{rescue_model}",
		)

	def _infra_failure_result(
		self,
		step: ExecutionStep,
		output: str,
		tokens_used: int,
		retries_used: int,
	) -> StepResult:
		"""Step que morreu por falha de INFRAESTRUTURA, nao por qualidade.

		Reprovado, mas com a causa REAL registrada em issues. O Critic nao e
		consultado: julgar uma mensagem de erro custa uma passada de dois
		estagios a preco de modelo e devolve um veredito que culpa o conteudo
		por uma falha de conta ou de rede.

		Importa para o retry tambem: fix_instructions derivadas de um veredito
		desses mandariam o modelo consertar um problema que nao existe.
		"""
		motivo = (output or "").strip()[:300] or "provedor nao retornou resposta"
		return StepResult(
			step_id=step.step_id, step_type=step.step_type,
			output="", approved=False, score=0,
			issues=[
				"Falha de infraestrutura, nao de conteudo: o provedor nao devolveu "
				f"resposta para este step. {motivo}"
			],
			retries_used=retries_used,
			tokens_used=tokens_used,
			model_used=step.model_id,
		)

	def _try_escalation(
		self,
		step: ExecutionStep,
		original_query: str,
		context: str,
		last_issues: list[str],
		retries_used: int | None = None,
	) -> StepResult:
		"""
		Tenta re-executar step critico com o modelo de escalacao.
		Chamado quando step critico e rejeitado pelo modelo original apos max_retries.
		Regra 5: escalacao e deterministica (step critico + modelo != escalacao).

		5.52.0: retries_used agora aceita o numero REAL de tentativas
		consumidas antes de escalar (passado pelo chamador de
		_execute_step_with_critique, que tem essa contagem). Antes sempre
		usava step.max_retries (o TETO configurado, nao o que realmente foi
		gasto) -- inofensivo enquanto _try_escalation() quase nunca rodava de
		verdade (ver changelog do fix acima), mas exposto como uma inconsistencia
		real de report assim que a escalacao passou a disparar normalmente
		(achado pela propria suite de testes apos o fix, test_orchestrator.py
		TestOrchestratorPipelineComMock). default=None preserva o comportamento
		antigo (step.max_retries) pro chamador de timeout
		(_timeout_result_or_escalate), que nao tem uma contagem real de
		retries pra passar (o timeout pode acontecer na 1a tentativa).
		"""
		_retries_used = retries_used if retries_used is not None else step.max_retries
		esc_msg = step.msg_escalating or ""
		self._emit("ESCALANDO", esc_msg)
		self._emit_checkpoint(
			step,
			f"Confianca baixa em '{step.step_type}': as tentativas normais nao "
			f"aprovaram, escalando pra um modelo com raciocinio mais profundo.",
		)
		escalation_model = _get_resilience_model(step.step_type, self._current_complexity())
		escalated = copy.copy(step)
		escalated.model_id = escalation_model
		escalated.reasoning_params = _ESCALATION_REASONING_BY_TYPE.get(step.step_type, {})
		escalated.max_retries = 1

		prompt = self._build_step_prompt(
			escalated, original_query, context, previous_issues=last_issues
		)
		try:
			output, esc_tokens = dispatch_step_with_tokens(
				step_type=escalated.step_type,
				prompt=prompt,
				model_id=escalated.model_id,
				reasoning_params=escalated.reasoning_params,
			)
			# Mensagem de avaliacao removida — evita poluir o historico.
			crit = self._critic.evaluate_two_stage(step.step_type, output, _critic_context(step, context, project_type=self._project_type()))
			approved = crit.verdict == Verdict.APPROVED
			if not approved:
				_logger.info("[INFO] Escalacao nao resolveu step %s.", step.step_id)
				rescued = self._try_cross_provider_rescue(step, prompt, context)
				if rescued is not None:
					return rescued
				self._emit_checkpoint(
					step,
					f"Confianca ainda baixa em '{step.step_type}': escalacao e resgate "
					f"cross-provider nao resolveram. Seguindo com o melhor resultado "
					f"obtido ate agora (score {crit.score}).",
				)
			return StepResult(
				step_id=step.step_id, step_type=step.step_type,
				output=output, approved=approved,
				score=crit.score, issues=crit.issues,
				retries_used=_retries_used,
				model_used=escalation_model,
				tokens_used=esc_tokens,
			)
		except Exception as exc:
			_logger.error("[ERRO] Escalacao de %s falhou: %s", step.step_id, exc)
			return StepResult(
				step_id=step.step_id, step_type=step.step_type,
				output="", approved=False, score=0,
				issues=[f"Escalacao falhou: {exc}"],
				retries_used=_retries_used,
				model_used=escalation_model,
			)

	# ------------------------------------------------------------------
	# Execucao paralela
	# ------------------------------------------------------------------

	def _execute_parallel(
		self,
		steps: list[ExecutionStep],
		original_query: str,
		outputs: dict,
	) -> list[StepResult]:
		"""
		Executa steps independentes em paralelo.

		B1 fix: user_clarification nao pode ir para o ThreadPoolExecutor
		(precisa de interacao UI e nao chama LLM). Esses steps sao extraidos
		e tratados sequencialmente antes dos steps paralelos.
		"""
		# Separa steps de clarificacao dos steps que rodam em paralelo
		clarify_steps = [s for s in steps if s.step_type == STEP_USER_CLARIFICATION]
		parallel_steps = [s for s in steps if s.step_type != STEP_USER_CLARIFICATION]

		results: list[StepResult] = []

		# 1. Trata clarificacoes primeiro (bloqueante, sem LLM)
		for step in clarify_steps:
			result = self._handle_clarification_step(step, outputs)
			results.append(result)
			with self._outputs_lock:
				outputs[step.step_id] = result.output

		if not parallel_steps:
			return results

		# 2. Executa steps normais em paralelo
		# Mensagem "Trabalhando em paralelo" removida — evita duplicacao com conversation_manager.
		# Evento discreto self._emit (5.30.0) mantido -- so quando ha de fato
		# mais de 1 step rodando ao mesmo tempo (_adaptive_max_workers so
		# paraleliza com len(parallel_steps) > 1).
		if len(parallel_steps) > 1:
			self._emit("PARALELO", str(len(parallel_steps)))
		# 5.51.0: `with ThreadPoolExecutor(...) as executor:` foi trocado por
		# criacao manual + shutdown(wait=False) explicito em toda saida.
		# __exit__ do context manager chama shutdown(wait=True), que BLOQUEIA
		# ate toda thread submetida terminar -- inclusive as que ja demos
		# como perdidas via FuturesTimeout. Achado real ao vivo (test_e36,
		# GeminiMultimodal): o "timeout" reportado (1200s) nao era o teto
		# real de espera -- ao sair do bloco `with`, o processo ficava preso
		# esperando a thread travada terminar por conta propria (limitada so
		# pelo timeout HTTP do client, _OLLAMA_CLOUD_TIMEOUT=300s, multiplicado
		# pelas chamadas internas de _execute_step_with_critique). Isso
		# explica boa parte dos 79min de wall-clock pra so 9 steps.
		executor = ThreadPoolExecutor(max_workers=_adaptive_max_workers(parallel_steps))
		try:
			future_to_step = {
				executor.submit(
					self._execute_step_with_critique,
					step, original_query,
					self._build_context(step, outputs),
				): step
				for step in parallel_steps
			}
			# Timeout global = soma dos timeouts individuais (nao mais multiplicacao).
			# Sum respeita o tempo real necessario por step quando ha um step
			# pesado (design_review) misturado com leves (web_research, manifest_builder).
			_global_timeout = sum(_get_step_timeout(s.step_type) for s in parallel_steps)
			try:
				for future in as_completed(future_to_step, timeout=_global_timeout):
					step = future_to_step[future]
					try:
						result = future.result(timeout=_get_step_timeout(step.step_type))
						results.append(result)
					except FuturesTimeout:
						_logger.error("[ERRO] Step paralelo %s: timeout.", step.step_id)
						results.append(self._timeout_result_or_escalate(
							step, original_query, self._build_context(step, outputs),
							f"Timeout: step excedeu {_get_step_timeout(step.step_type)}s.",
						))
					except Exception as exc:
						_logger.error("[ERRO] Step paralelo %s falhou: %s", step.step_id, exc)
						results.append(StepResult(
							step_id=step.step_id, step_type=step.step_type,
							output="", approved=False, score=0,
							issues=[str(exc)], model_used=step.model_id,
						))
			except FuturesTimeout:
				# Periodo de graca pos-timeout (plano aa1600dd): aguarda mais
				# _GRACE_PERIOD_SECONDS para steps que estavam quase terminando.
				# Sem este buffer, design_review que completaria 30s depois era
				# descartado e substituido por score=0 mesmo com output valido.
				pending = [f for f in future_to_step if not f.done()]
				if pending:
					_logger.warning(
						"[AVISO] Timeout global apos %ds. Aguardando %ds extras "
						"para %d future(s) pendente(s).",
						_global_timeout, _GRACE_PERIOD_SECONDS, len(pending)
					)
				for fut in pending:
					step = future_to_step[fut]
					try:
						result = fut.result(timeout=_GRACE_PERIOD_SECONDS)
						_logger.info(
							"[OK] Step %s completou no periodo de graca pos-timeout.",
							step.step_id,
						)
						results.append(result)
					except FuturesTimeout:
						_logger.error(
							"[ERRO] Step paralelo %s: timeout global "
							"(pendente apos as_completed + graca).",
							step.step_id,
						)
						results.append(self._timeout_result_or_escalate(
							step, original_query, self._build_context(step, outputs),
							"Timeout global: step nao completou dentro do prazo.",
						))
					except Exception as exc:
						_logger.error(
							"[ERRO] Step paralelo %s falhou na graca: %s",
							step.step_id, exc,
						)
						results.append(StepResult(
							step_id=step.step_id, step_type=step.step_type,
							output="", approved=False, score=0,
							issues=[str(exc)], model_used=step.model_id,
						))
			return results
		finally:
			# wait=False: nao bloqueia esperando threads travadas -- elas ficam
			# orfas em segundo plano, limitadas pelo timeout HTTP do client.
			executor.shutdown(wait=False)

	def _timeout_result_or_escalate(
		self, step: ExecutionStep, original_query: str, context: str, message: str,
	) -> StepResult:
		"""
		5.51.0: decide o StepResult de um timeout. Antes, todo timeout virava
		score=0 direto -- achado real ao vivo (test_e36, GeminiMultimodal,
		s6 code_generation): retries_used=0, tokens_used=0, nenhuma segunda
		chance, mesmo o step sendo elegivel pro mesmo mecanismo de escalacao
		ja usado quando o critic rejeita apos max_retries (_try_escalation).
		Steps em _ESCALATION_ELIGIBLE_STEP_TYPES ganham essa segunda chance
		com o modelo de resiliencia; os demais mantem o comportamento antigo.
		_try_escalation() faz UMA chamada direta via dispatch_step_with_tokens
		(nao um ThreadPoolExecutor aninhado), limitada pelo timeout HTTP do
		client (_OLLAMA_CLOUD_TIMEOUT) -- nao reintroduz risco de travar
		indefinidamente.
		"""
		if step.step_type in _ESCALATION_ELIGIBLE_STEP_TYPES:
			_logger.info(
				"[INFO] Step %s (%s): tentando escalacao apos timeout.",
				step.step_id, step.step_type,
			)
			try:
				return self._try_escalation(step, original_query, context, last_issues=[message])
			except Exception as exc:
				_logger.error("[ERRO] Escalacao pos-timeout de %s falhou: %s", step.step_id, exc)
		return StepResult(
			step_id=step.step_id, step_type=step.step_type,
			output="", approved=False, score=0,
			issues=[message], model_used=step.model_id,
		)

	def _run_isolated_step(
		self, step: ExecutionStep, original_query: str, context: str,
	) -> StepResult:
		"""
		Executa um step isolado (worker dedicado) respeitando o timeout do
		step_type. Usado pelos loops de contexto parcial (partial_ready).

		5.51.0: substitui o padrao anterior `with ThreadPoolExecutor() as _pex:`.
		O __exit__ do context manager chama shutdown(wait=True) e BLOQUEIA ate
		a thread travada de fato terminar, mesmo apos o timeout logico ja ter
		sido reportado -- achado real ao vivo (test_e36): isso inflava o tempo
		total muito alem do timeout nominal (79min pra 9 steps). Agora o
		executor e criado manualmente e sempre fechado com shutdown(wait=False)
		no finally -- a thread travada fica orfa em segundo plano (limitada
		pelo timeout HTTP do client, nao pelo processo Python), e o pipeline
		segue sem esperar.
		"""
		timeout = _get_step_timeout(step.step_type)
		executor = ThreadPoolExecutor(max_workers=1)
		try:
			future = executor.submit(self._execute_step_with_critique, step, original_query, context)
			try:
				return future.result(timeout=timeout)
			except FuturesTimeout:
				_logger.error("[ERRO] Step %s: timeout de %ds.", step.step_id, timeout)
				return self._timeout_result_or_escalate(
					step, original_query, context, f"Timeout: step excedeu {timeout}s.",
				)
		finally:
			executor.shutdown(wait=False)

	# ------------------------------------------------------------------
	# Execucao de step com critica, retry e escalacao
	# ------------------------------------------------------------------

	def _dispatch_with_heartbeat(self, step_type: str, prompt: str, model_id: str, reasoning_params: dict) -> tuple[str, int]:
		"""
		Roda dispatch_step_with_tokens em thread separada e emite progresso
		periodico (heartbeat) enquanto aguarda, para o usuario nao ficar em
		silencio durante steps longos.
		"""
		with ThreadPoolExecutor(max_workers=1) as _hb_pool:
			_hb_future = _hb_pool.submit(
				dispatch_step_with_tokens,
				step_type=step_type,
				prompt=prompt,
				model_id=model_id,
				reasoning_params=reasoning_params,
			)
			conversation.emit_tool_start(step_type)
			_hb_last_emit = time.time()
			try:
				while not _hb_future.done():
					try:
						_hb_future.result(timeout=0.3)
					except FuturesTimeout:
						pass
					now = time.time()
					if now - _hb_last_emit >= _HEARTBEAT_INTERVAL_SECONDS:
						# emit_tool_progress calcula o elapsed sozinho a partir do
						# emit_tool_start acima -- nao aceita elapsed_ms explicito.
						conversation.emit_tool_progress()
						_hb_last_emit = now
				try:
					return _hb_future.result()
				except Exception as exc:
					# Bug real: step_type desconhecido (dispatcher.py levanta ValueError,
					# "sem agente especializado") ou qualquer outra falha no dispatch
					# subia sem tratamento ate o try/except do topo de
					# _run_conversational_pipeline, abortando o PIPELINE INTEIRO em vez
					# de falhar so este step. Convertido para o formato "[ERRO] ..." ja
					# reconhecido por _IS_SUBAGENT_ERROR_RE, entrando no mesmo fluxo de
					# retry/escalonamento/critica usado para falhas de infraestrutura.
					_logger.error(
						"[ERRO] Dispatch do step_type=%s falhou: %s", step_type, exc,
					)
					return f"[ERRO] Falha ao despachar o step: {exc}", 0
			finally:
				conversation.emit_tool_end()

	def _execute_step_with_critique(
		self, step: ExecutionStep, original_query: str, context: str
	) -> StepResult:
		msg = step.user_message or step.description[:80]
		self._emit_conversation("ia", msg, kind="status")  # pre_exec_msg: anuncia antes de executar
		retries = 0
		last_output = ""
		last_issues: list[str] = []
		# 5.61.0 -- PROBLEMAS ACUMULADOS ENTRE TENTATIVAS.
		#
		# Achado no E2E real de 2026-08-29: cada code_generation gastava ~420 mil
		# tokens em 3 tentativas e falhava nas tres, com motivo DIFERENTE a cada
		# vez. A causa nao era o modelo -- era `last_issues = crit.issues`, que
		# SUBSTITUI a lista a cada avaliacao. Na tentativa 2 o modelo recebia
		# apenas os problemas da avaliacao 2; os da tentativa 1 tinham sumido do
		# prompt. Ele corrigia o que acabara de ouvir e reintroduzia o que ja
		# tinha corrigido. Tres tentativas, tres conjuntos de problemas, nenhuma
		# convergencia.
		#
		# Esta lista existe SEPARADA de last_issues de proposito: a deteccao de
		# loop semantico (5.42.0) compara a assinatura de last_issues entre
		# tentativas consecutivas. Se ela passasse a acumular, a assinatura
		# cresceria sempre, nunca se repetiria, e a deteccao de loop morreria em
		# silencio -- trocando um defeito por outro.
		issues_acumulados: list[str] = []
		total_step_tokens = 0
		_step_start = time.perf_counter()
		_previous_issue_signature: str | None = None  # 5.42.0: deteccao de loop semantico
		_loop_broke_early = False  # 5.42.0: usado pro rotulo de trajectory (session_memory 3.3.0)
		# 5.44.0: exige 2 repeticoes consecutivas (3 tentativas identicas) antes
		# de desistir, nao 1 -- test_client_cache_por_tentativa.py documenta um
		# caso real (2 rejeicoes com o MESMO texto de issue, resolvido na 3a
		# tentativa apos clear_client_cache()) que e legitimo e nao deve ser
		# tratado como loop. So padroes REALMENTE repetitivos (3+ identicos
		# seguidos, como vimos em rodadas reais do test_e36 com 6-10 retries
		# identicos) devem escalar cedo.
		_consecutive_repeat_count = 0
		# 5.85.0: melhor tentativa que CHEGOU ao Critic com veredicto CORRIGIR.
		# Chegar ao Critic ja e informacao: todo portao deterministico do laco
		# (target_files entregues, syntax_check, ruff, execucao real em sandbox
		# com smoke dos comandos, fault injection) faz `retries += 1; continue`
		# quando reprova. Um output que chegou ao julgamento passou em todos.
		_melhor_com_portoes_verdes: tuple[int, str, list[str]] | None = None
		clear_client_cache()  # limpa cache entre steps — novo step, novo contexto

		for attempt in range(step.max_retries):
			# 5.32.0: achado real da suite e2e real (test_e36, agent_runner
			# falhando identicamente em retries sucessivos): clear_client_cache()
			# so rodava UMA VEZ, antes do loop -- _get_cached_client()/
			# _cache_client() (sub_agents/_base.py) cacheiam por model_id numa
			# unica entrada thread-local. Quando o attempt 2 escala pro modelo
			# resiliente e o attempt 3 continua no MESMO modelo (ja escalado),
			# ambos batem no MESMO OllamaClient cacheado -- cujo self._history
			# (ollama_client.py) acumula a resposta REJEITADA do attempt
			# anterior. O modelo via sua propria resposta ruim anterior no
			# historico ao tentar de novo, plausivelmente enviesando-o a
			# repetir o mesmo erro. Limpar a cada tentativa garante que cada
			# retry seja de fato uma conversa nova, isolada -- o contexto
			# corrigido ja chega via prompt (previous_issues), nao precisa
			# do historico bruto da tentativa anterior.
			clear_client_cache()
			# 5.28.0: achado real da suite e2e completa (217 casos reais) --
			# iteration_budget.can_continue() so era consultado em
			# agentic_loop.py (loop de estrategias da FSM de modificacao).
			# O pipeline principal de CRIACAO (_execute_step_with_critique,
			# usado por _run_pipeline/_run_conversational_pipeline) so
			# REGISTRAVA gasto via _record_iteration_budget() e nunca
			# perguntava can_continue() antes de tentar mais uma chamada --
			# _check_limits() logava "[BUDGET] ... Pipeline sera parado" a
			# cada record_iteration() acima do teto, mas nada de fato parava.
			# Confirmado ao vivo: um addon complexo (FocusTextAssistant) rodou
			# ate 278 iteracoes / $20.25 contra um teto configurado de
			# 50 iteracoes / $5.00 -- 4x-5x acima do orcamento, dinheiro real
			# gasto sem qualquer enforcement.
			# 5.82.0 -- este portao tambem precisa saber o que e ENTREGA.
			#
			# Erro meu na 5.81.0: instrumentei os dois portoes do laco de
			# escalonamento e nao este, que roda por TENTATIVA dentro do step.
			# Medido na rodada de 2026-09-02 17:20: o escalonamento fez a parte
			# dele -- descartou os consultivos e CHEGOU no assembly -- e entao
			# este portao o barrou com o teto reduzido, exatamente o teto que a
			# entrega nao deveria enxergar:
			#   "Step asm: orcamento excedido (Saldo reservado para a entrega
			#    (1378286/1278750; reserva de 120000))"
			# O medidor estava ABAIXO do teto real (1.398.750) e acima do
			# reduzido. A reserva existia e foi negada a quem ela protegia.
			_para_entrega = step.step_type in _STEP_TYPES_DE_ENTREGA
			_can_continue, _budget_reason = iteration_budget.can_continue(
				para_entrega=_para_entrega,
			)
			if not _can_continue:
				_logger.warning(
					"[BUDGET] Step %s: orcamento excedido (%s). Abortando "
					"tentativas restantes deste step.",
					step.step_id, _budget_reason,
				)
				return StepResult(
					step_id=step.step_id, step_type=step.step_type,
					output=last_output, approved=False, score=0,
					issues=[f"Orcamento excedido: {_budget_reason}"],
					retries_used=retries, tokens_used=total_step_tokens,
					model_used=step.model_id,
				)
			resilience_model = _get_resilience_model(step.step_type, self._current_complexity())
			# Se step critico (ou web_research, 5.26.0) ja falhou uma vez,
			# troca proativamente para modelo resiliente.
			if (attempt > 0
				and step.step_type in _ESCALATION_ELIGIBLE_STEP_TYPES
				and step.model_id != resilience_model):
				_logger.warning(
					"[FALLBACK] Step %s: retry %d com %s. "
					"Trocando para fallback %s antes de gastar outra tentativa longa.",
					step.step_id, attempt + 1, step.model_id, resilience_model,
				)
				step.model_id = resilience_model
				step.reasoning_params = _FALLBACK_REASONING
			prompt = self._build_step_prompt(
				step, original_query, context,
				previous_issues=issues_acumulados if attempt > 0 else []
			)
			self._emit("EXECUTANDO", step.step_type)
			last_output, step_tokens = self._dispatch_with_heartbeat(
				step_type=step.step_type,
				prompt=prompt,
				model_id=step.model_id,
				reasoning_params=step.reasoning_params,
			)
			total_step_tokens += step_tokens
			self._track_model_tokens(step.model_id, step_tokens)

			# Fallback de modelo: se o output e uma string de erro de infra
			# (comeca com [ERRO]) e o modelo atual difere do fallback, retenta
			# com modelo alternativo antes de desistir.
			# v4.1.1 fix: _IS_SUBAGENT_ERROR_RE so detecta prefixo [ERRO].
			# Antes, _INFRA_ERROR_RE causava falsos positivos em codigo que
			# continha "timeout=30", "status == 503" — descartando output valido.
			# Regra 5: decisao deterministica por regex — nao usa LLM.
			_alvo_fallback = resilience_model
			if _IS_SUBAGENT_ERROR_RE.search(last_output) and _ERRO_DE_AUTENTICACAO_RE.search(
				last_output
			):
				# 5.76.0 -- 401/403 e problema de CONTA, nao de modelo.
				#
				# O fallback abaixo troca de modelo dentro do MESMO provedor, o que
				# resolve timeout e 503 e nao resolve nada numa chave rejeitada.
				# Medido em 2026-09-02: duas execucoes perderam um step inteiro para
				# "OpenCode Go API falhou: 401 Unauthorized", com retries=0 e
				# tokens=0, enquanto o Ollama estava configurado e funcionando na
				# mesma maquina.
				#
				# A deteccao so roda DENTRO do ramo de erro de infraestrutura: o
				# projeto ja se queimou com regex de infra batendo em codigo gerado
				# que continha "status == 503" (nota do fix v4.1.1 logo acima).
				_outro = _modelo_de_outro_provedor(self._provedor_atual())
				if _outro:
					_motivo = (
						"esta sem saldo"
						if _SEM_SALDO_RE.search(last_output)
						else "rejeitou a autenticacao"
					)
					_logger.warning(
						"[FALLBACK] Step %s: o provedor %s. Trocando de PROVEDOR "
						"para %s.", step.step_id, _motivo, _outro,
					)
					_alvo_fallback = _outro

			if _IS_SUBAGENT_ERROR_RE.search(last_output) and step.model_id != _alvo_fallback:
				_logger.warning(
					"[FALLBACK] Step %s: erro de infra detectado com modelo %s. "
					"Tentando fallback %s...",
					step.step_id, step.model_id, _alvo_fallback,
				)
				fallback_step = copy.copy(step)
				fallback_step.model_id = _alvo_fallback
				fallback_step.reasoning_params = _FALLBACK_REASONING
				last_output, step_tokens = self._dispatch_with_heartbeat(
					step_type=fallback_step.step_type,
					prompt=prompt,
					model_id=fallback_step.model_id,
					reasoning_params=fallback_step.reasoning_params,
				)
				total_step_tokens += step_tokens
				self._track_model_tokens(fallback_step.model_id, step_tokens)
				if not _IS_SUBAGENT_ERROR_RE.search(last_output):
					_logger.info(
						"[FALLBACK] Step %s: fallback %s funcionou.",
						step.step_id, resilience_model,
					)
				else:
					_logger.warning(
						"[FALLBACK] Step %s: fallback %s tambem falhou com erro de infra.",
						step.step_id, resilience_model,
					)

			# A specialist can anticipate later stages and emit their files. Scope
			# the candidate before validation, critique, and persistence so each
			# stage is judged only against its declared artifact contract.
			last_output = _scope_output_to_step(step.step_type, last_output)

			# Validacao sintatica antes do Critic
			if step.step_type in ("code_generation", "agent_runner"):
				blocks = extract_code_blocks(last_output)
				local_modules = {
					os.path.splitext(os.path.basename(blk.get("filename", "")))[0].lower()
					for blk in blocks
					if blk.get("language") == "python" and blk.get("filename")
				}
				local_modules.discard("__init__")
				syntax_failed = False
				for blk in blocks:
					if blk.get("language") == "python":
						syntax_err = validate_python_syntax(blk["code"])
						if syntax_err:
							retries += 1
							# Mensagem de STATUS pro usuario removida — evita poluir o
							# historico. O erro em si (last_issues) e mantido: sem ele
							# o proximo _build_step_prompt(previous_issues=...) nao sabe
							# o que corrigir e tende a repetir o mesmo erro de sintaxe
							# (achado na auditoria de 2026-07-20).
							last_issues.append(f"Erro de sintaxe: {syntax_err}")
							log_decision(_logger, "syntax_error",
								f"step={step.step_id} err={syntax_err[:80]}")
							syntax_failed = True
							break
							# v2.1.0: Wiring code_sandbox para verificacao de runtime
						try:
							from ..builder.code_sandbox import CodeSandbox
							sandbox = CodeSandbox(timeout_sec=10)
							runtime_check = sandbox.syntax_check(blk["code"])
							if not runtime_check.success:
								_logger.warning("[SANDBOX] Syntax check falhou: %s", runtime_check.error)
								last_issues.append(f"Erro de sintaxe: {runtime_check.error}")
								retries += 1
								syntax_failed = True
								break
							_logger.info("[WIRING] code_sandbox.syntax_check() passou para bloco %s", blk.get("name", "?"))
						except Exception as e:
							_logger.error("[WIRING] code_sandbox indisponivel: %s", e)
							last_issues.append("Validação de sandbox indisponível: " + str(e))
							retries += 1
							syntax_failed = True
							break

						unknown_imports = validate_python_imports(
							blk["code"],
							bundled_packages=getattr(self, "_plan_dependencies", []),
							local_modules=local_modules,
						)
						if unknown_imports:
							log_decision(_logger, "unknown_imports",
								f"step={step.step_id} imports={unknown_imports[:5]}")
							for imp in unknown_imports:
								if imp not in self._auto_detected_deps:
									self._auto_detected_deps.append(imp)
							context = (
								context
								+ "\n\nAVISO: imports possivelmente nao bundlados: "
								+ ", ".join(unknown_imports[:5])
								+ ". Verifique se estao em dependencies[]."
							)
				if syntax_failed:
					continue

				# 5.39.0: verificacao de EXECUCAO real (nao so sintaxe) --
				# importa e instancia a classe principal de verdade, em
				# subprocesso isolado com os modulos NVDA simulados
				# (builder/nvda_runtime_stubs.py, code_sandbox.py 1.2.0).
				# Pega NameError/AttributeError/assinatura de construtor
				# errada que nem AST (syntax_check) nem "esperar o teste
				# gerado exercitar o bug por acaso" garantem pegar --
				# achado real desta sessao: testes gerados as vezes so
				# verificam "metodo foi chamado", nunca o comportamento
				# real do codigo.
				try:
					from ..builder.code_sandbox import CodeSandbox as _CodeSandboxExec
					py_files = {
						blk.get("filename", ""): blk["code"]
						for blk in blocks
						if blk.get("language") == "python" and blk.get("filename")
					}
					# 5.66.0 -- O STEP ENTREGOU O QUE DECLAROU?
					#
					# `target_files` era declarado pelo planner, injetado no
					# prompt ("produza EXATAMENTE estes") e nunca CONFERIDO. Quem
					# reclamava de entrega parcial era o Critic, em prosa, depois
					# de uma avaliacao de dois estagios -- caro e vago.
					#
					# Medido nos relatorios: 17 code_generation reprovados com
					# "Nenhum codigo Python foi produzido" (1,6 milhao de tokens)
					# e varios outros por entrega parcial. Sao os dois casos que
					# esta checagem resolve por comparacao de nomes, antes de
					# qualquer chamada de modelo.
					#
					# Compara por NOME DE ARQUIVO, nao pelo caminho inteiro: o
					# caminho errado e problema de colocacao (addon_builder ja
					# trata) e bloquear por isso criaria falso positivo. O que
					# nao da para recuperar e o arquivo que nao existe.
					faltando = _alvos_nao_entregues(step, py_files)
					if faltando:
						_logger.warning(
							"[ENTREGA] step %s nao produziu %s",
							step.step_id, faltando,
						)
						last_issues.append(
							"Entrega incompleta: este step declarou os arquivos "
							+ ", ".join(getattr(step, "target_files", []))
							+ " e nao produziu " + ", ".join(faltando)
							+ ". Responda com um bloco ```python:<caminho> por "
							"arquivo faltante, com o conteudo COMPLETO do "
							"arquivo -- nao descreva o que faria, nao entregue "
							"trecho parcial."
						)
						retries += 1
						continue

					if py_files:
						# 5.73.0 -- MODULOS QUE OUTRO STEP AINDA VAI PRODUZIR.
						#
						# Desde que o nucleo passou a ser gerado PRIMEIRO (planner
						# 2.40.0), o __init__.py legitimamente importa modulos de
						# feature que ainda nao existem -- e essa e a ordem correta,
						# porque e ele que declara o contrato que os outros
						# implementam. Medido na rodada 6: cg_core reprovado com
						# "Erro de execucao real" em `from .configSpec import ...`,
						# 344.333 tokens, por importar um arquivo que o plano ainda
						# ia gerar.
						#
						# Cobrar de um step a existencia de arquivo que NAO e dele e
						# testar uma condicao impossivel. Os arquivos que o plano
						# declara e ninguem produziu ainda entram como modulo vazio,
						# so para o import resolver -- o que continua sendo testado e
						# o arquivo DESTE step: ele importa, a classe instancia,
						# terminate() roda.
						_arquivos_exec = dict(py_files)
						for _pendente in self._arquivos_de_outros_steps(step, py_files):
							_arquivos_exec[_pendente] = _MODULO_PENDENTE
						exec_check = _CodeSandboxExec(timeout_sec=15).validate_addon_execution(
							_arquivos_exec
						)
						if not exec_check.success:
							# Falhas de subprocesso nem sempre aparecem em stderr:
							# timeout, Python indisponivel e falhas de infraestrutura
							# podem vir apenas em error ou stdout. Nunca tratar um
							# resultado falso como sucesso por causa de stderr vazio.
							evidence = _sandbox_failure_evidence(exec_check)
							_logger.warning("[SANDBOX] Execucao real falhou: %s", evidence[:500])
							last_issues.append(
								"Erro de execucao real (import/instanciacao): " + evidence[-500:]
							)
							retries += 1
							continue
						_logger.info("[SANDBOX] validate_addon_execution() passou para step %s", step.step_id)
						# Fault injection real: executa novamente o addon no subprocesso
						# com falhas controladas de rede, timeout e arquivo ausente.
						# O código do addon é o mesmo; só o ambiente isolado muda.
						resilience_check = _CodeSandboxExec(timeout_sec=3).validate_addon_resilience(
							py_files, timeout=3,
						)
						if not resilience_check.success:
							evidence = _sandbox_failure_evidence(resilience_check)
							_logger.warning("[SANDBOX] Fault injection falhou: %s", evidence[:500])
							last_issues.append("Falha de robustez sob fault injection: " + evidence[-500:])
							retries += 1
							continue
						_logger.info("[SANDBOX] Fault injection passou para step %s", step.step_id)
						# 5.44.0: verificacao de Keyboard/Focus Management -- bindGesture()
						# dinamico (self.bindGesture(...) fora do dict __gestures estatico)
						# sem removeGestureBinding() correspondente na classe acumula
						# gestures duplicados a cada rebind. Informacional -- nao bloqueia
						# o step (nem toda ocorrencia e um bug real; o modelo decide se
						# corrige), so entra no contexto pra o proximo retry considerar.
						if "AVISO_BINDGESTURE_SEM_UNBIND" in exec_check.stdout:
							_logger.info(
								"[SANDBOX] Possivel binding de gesture sem unbind em %s",
								step.step_id,
							)
							context = (
								context
								+ "\n\nAVISO (Keyboard/Focus Management): bindGesture() dinamico "
								"detectado sem removeGestureBinding() correspondente na classe -- "
								"rebind sem limpar acumula gestures duplicados para o mesmo script. "
								"Se o binding for dinamico (nao um dict __gestures estatico), "
								"chame self.removeGestureBinding(gesture) antes de rebindar."
							)

						# 5.56.0: ANALISE ESTATICA do addon gerado (ruff + mypy).
						# Fecha a assimetria historica do projeto -- o CI exige
						# `ruff check` e `mypy` limpos no codigo do NVDAStudio,
						# mas o addon ENTREGUE ao usuario nunca passava por
						# nenhum dos dois. Roda depois de execucao/resiliencia
						# de proposito: quando o addon nem importa, o erro de
						# import e o sinal util; lint em cima disso so
						# adicionaria ruido ao prompt do retry.
						#
						# ruff BLOQUEIA (retry): a config curada de
						# code_sandbox._GENERATED_RUFF_CONFIG so seleciona
						# F/E9/B -- defeito real, nunca estilo -- entao um
						# achado aqui e sempre corrigivel e vale o retry.
						# mypy e ADVISORY (so contexto): sem stubs dos modulos
						# do NVDA o resultado tem falso-positivo demais pra
						# bloquear um step; serve pra orientar o proximo passo.
						#
						# Ambos sao FAIL-OPEN por construcao (ver
						# _run_static_tool): ferramenta ausente devolve
						# success=True com error="*_indisponivel" -- o Python
						# embutido do NVDA normalmente nao tem ruff nem mypy, e
						# quebrar o addon de quem nao tem dev tooling instalado
						# seria pior que nao lintar.
						_static_sandbox = _CodeSandboxExec()

						# 5.71.0 -- corrige o MECANICO antes de cobrar do modelo.
						#
						# Medido nos relatorios: 9 steps reprovados por lint,
						# 3.298.179 tokens. Das 60 ocorrencias, 49 sao F401 (import
						# nao usado, 43x), F841 e B007 -- defeito real, mas sem
						# decisao semantica nenhuma: apagar uma linha. Pagar tres
						# tentativas a ~140 mil tokens para remover um import e o
						# mesmo erro que ja custou caro com indentacao e gettext.
						#
						# As 11 restantes (F821, F823) nao tem correcao mecanica --
						# sao bug de verdade e seguem para o modelo abaixo, agora sem
						# o ruido do que o codigo mesmo resolvia.
						#
						# A correcao volta para `last_output` de proposito: e ELE que
						# vai para o assembly e para o disco. Corrigir so a copia
						# extraida entregaria o addon ainda com o defeito.
						# 5.83.0 -- initTranslation tambem e corrigido ANTES do julgamento.
						#
						# garantir_init_translation() ja existia e ja era deterministica, mas
						# so rodava no addon_builder (linha ~782), na extracao dos blocos --
						# ou seja, DEPOIS do Critic. O Critic reprovava por um defeito que o
						# projeto consertava sozinho segundos depois.
						#
						# Medido em 2026-09-02 (AssistenteEscrita): o step cg3 gastou 3
						# tentativas e caiu para score 78 com um unico achado --
						# "NVDA-003: usa _('...') sem addonHandler.initTranslation()" num
						# atributo de classe. Exatamente o caso que a funcao resolve.
						#
						# Mesmo racional do lint_autofix logo abaixo: correcao mecanica nao
						# deve ser paga a preco de modelo.
						_corrigidos = {
							rel: garantir_init_translation(codigo)
							for rel, codigo in py_files.items()
						}
						_corrigidos = _static_sandbox.lint_autofix(_corrigidos)
						_mudados = {
							rel: novo for rel, novo in _corrigidos.items()
							if novo != py_files.get(rel)
						}
						if _mudados:
							_reescrito = substituir_codigo_dos_blocos(last_output, _mudados)
							if _reescrito != last_output:
								last_output = _reescrito
								py_files = _corrigidos
								_logger.info(
									"[LINT-FIX] %d arquivo(s) corrigidos mecanicamente no step %s: %s",
									len(_mudados), step.step_id, ", ".join(sorted(_mudados)),
								)

						lint_check = _static_sandbox.lint_check(py_files)
						if not lint_check.success and not lint_check.error:
							# success=False com error vazio == ruff rodou e
							# ACHOU defeito (infra sempre preenche error).
							findings = lint_check.stdout.strip()[:1200]
							_logger.warning("[LINT] ruff reprovou o addon gerado: %s", findings[:300])
							last_issues.append(
								"Lint do addon gerado (ruff) apontou defeitos reais -- "
								"corrija todos antes de seguir:\n" + findings
							)
							retries += 1
							continue
						if lint_check.error:
							_logger.info("[LINT] ruff nao aplicado: %s", lint_check.error)
						else:
							_logger.info("[LINT] ruff limpo para step %s", step.step_id)

						# 5.65.0 -- NVDA-003 no ponto onde ainda da para corrigir.
						#
						# `_()` so existe num modulo de addon depois de
						# addonHandler.initTranslation(); sem isso o modulo
						# levanta NameError na primeira string traduzida. E o
						# ruff nao pega: code_sandbox declara `_` e os irmaos
						# como builtins de proposito, senao TODO addon
						# gettext-correto seria reprovado com F821.
						#
						# validate_addon_structure ja emitia NVDA-003, mas so no
						# empacotamento -- tarde demais. Medido no E2E
						# AssistenteLeituraGemini (2026-08-30): o Critic reprovou
						# cg_settings por isso 3 vezes, 412 mil tokens, e o step
						# nunca passou. Um defeito deterministico devolvido como
						# instrucao concreta custa uma tentativa; devolvido como
						# nota do Critic custa todas.
						gettext_sem_init = [
							nome for nome, codigo in py_files.items()
							if chama_gettext(codigo)
							and "initTranslation" not in codigo
							and "import gettext" not in codigo
						]
						if gettext_sem_init:
							_logger.warning(
								"[NVDA-003] gettext sem initTranslation em %s",
								gettext_sem_init,
							)
							last_issues.append(
								"NVDA-003: os modulos a seguir chamam _(), ngettext(), "
								"pgettext() ou npgettext() sem inicializar a traducao, o "
								"que levanta NameError na primeira string traduzida: "
								+ ", ".join(gettext_sem_init)
								+ ". Adicione `import addonHandler` e "
								"`addonHandler.initTranslation()` no topo de CADA um "
								"deles -- a inicializacao vale so para o modulo que a "
								"chama, nao para o pacote inteiro."
							)
							retries += 1
							continue

						type_check = _static_sandbox.typecheck(py_files)
						if not type_check.success and not type_check.error and type_check.stdout.strip():
							_logger.info(
								"[TYPES] mypy apontou inconsistencias em %s (advisory)", step.step_id
							)
							context = (
								context
								+ "\n\nAVISO (checagem de tipos, nao bloqueante): mypy apontou "
								"as inconsistencias abaixo no codigo gerado. Avalie se sao "
								"defeitos reais -- modulos do NVDA nao tem stubs, entao parte "
								"pode ser falso-positivo. Corrija apenas o que for defeito de "
								"verdade:\n" + type_check.stdout.strip()[:800]
							)
				except Exception as e:
					_logger.error("[SANDBOX] validate_addon_execution indisponivel: %s", e)
					last_issues.append("Execução isolada indisponível: " + str(e))
					retries += 1
					continue

			# 5.79.0 -- falha de INFRAESTRUTURA nao vai a julgamento.
			#
			# Quando a chamada de LLM falha, _base.py::_run_sub_agent devolve
			# "[ERRO] Sub-agente nao conseguiu gerar resposta: ..." COMO SE fosse
			# a resposta. O fallback acima tenta outro modelo/provedor e, quando
			# ele tambem falha, apenas registra "fallback tambem falhou" e segue
			# em frente -- sem nenhuma guarda ate aqui. A string de erro chegava
			# ao Critic e era pontuada como se fosse conteudo.
			#
			# Medido em 2026-09-02 (rodada AssistenteEscrita): o step web_research
			# escalou para opencode_go, que esta sem saldo, e o Critic reprovou com
			# score=0 escrevendo "o output e apenas uma mensagem de erro de API
			# (401 Unauthorized), sem nenhuma informacao factual pesquisada". A
			# BUSCA tinha funcionado (paralelo: 1/3 fontes, exa); quem morreu foi a
			# sintese, no provedor derrubado. O veredito culpava a pesquisa por uma
			# falha de conta.
			#
			# Custo de deixar passar: uma passada inteira do Critic (dois estagios)
			# paga a preco de modelo para julgar uma mensagem de erro, mais um
			# veredito que aponta a causa errada -- para o usuario e para o retry,
			# que recebe fix_instructions sobre um problema que nao existe.
			#
			# Vale para os 11 sub-agentes, nao so a pesquisa. Deterministico por
			# regex (Regra 7): _IS_SUBAGENT_ERROR_RE ja existia e so era consultada
			# no ramo de fallback.
			if _IS_SUBAGENT_ERROR_RE.search(last_output or ""):
				_logger.warning(
					"[INFRA] Step %s: output e falha de infraestrutura, nao conteudo. "
					"Nao vai ao Critic. %s", step.step_id, (last_output or "")[:200],
				)
				# Consome uma retentativa em vez de abortar o step: o fallback de
				# modelo/provedor ja rodou logo acima, mas uma indisponibilidade
				# passageira ainda pode passar na tentativa seguinte. Abortar aqui
				# tornaria o pipeline MENOS resiliente do que era antes deste fix --
				# o objetivo e nao pagar o Critic por uma mensagem de erro, nao
				# desistir mais cedo.
				retries += 1
				last_issues = [
					"Falha de infraestrutura na tentativa anterior (provedor nao "
					"respondeu). Nao ha correcao de conteudo a fazer."
				]
				if attempt < step.max_retries - 1:
					continue
				return self._infra_failure_result(step, last_output, total_step_tokens, retries)

			# Critic em dois estagios — sem mensagem de status (evita spam).
			self._emit("AVALIANDO", step.step_type)
			if step.step_type == STEP_SYNTAX_VALIDATION:
				# 5.54.0: bypass deterministico -- ver
				# _evaluate_syntax_validation_deterministically acima.
				crit = _evaluate_syntax_validation_deterministically(last_output)
			else:
				crit = self._critic.evaluate_two_stage(step.step_type, last_output, _critic_context(step, context, project_type=self._project_type()))
			# Testes não executados não podem ser tratados como etapa aprovada
			# apenas porque o Critic gostou do texto gerado.
			if step.step_type == STEP_TEST_GENERATION and "[AVISO-TESTES" in last_output:
				crit.verdict = Verdict.NEEDS_FIX
				crit.score = min(crit.score, 0)
				crit.issues.append("Os testes gerados não foram executados com sucesso.")
				crit.fix_instructions = (
					"Corrija a causa da falha de execução dos testes e execute-os novamente "
					"antes de considerar esta etapa concluída."
				)
			last_issues = crit.issues
			_acumular_issues(issues_acumulados, crit.issues)

			# 5.42.0: deteccao de loop semantico -- achado real desta sessao
			# (rodadas de test_e36 com 1h+ de duracao): _MAX_REPLANS/
			# max_retries so limitam por NUMERO de tentativas, nunca detectam
			# quando a tentativa N repete o MESMO problema da tentativa N-1
			# (o fix_instructions do Critic nao resolveu, o modelo devolveu
			# essencialmente o mesmo erro). Continuar retentando o MESMO jeito
			# so queima tokens/tempo -- escalar mais cedo (pra outro modelo/
			# provider, que pode ter vies diferente) e estrategia melhor que
			# insistir identico. So compara quando ha PELO MENOS um issue real
			# (lista vazia nunca conta como "loop").
			_issue_signature = "|".join(sorted(str(i) for i in last_issues)) if last_issues else ""
			_repeated_now = (
				crit.verdict != Verdict.APPROVED
				and _issue_signature
				and _issue_signature == _previous_issue_signature
			)
			_consecutive_repeat_count = _consecutive_repeat_count + 1 if _repeated_now else 0
			# 2 repeticoes consecutivas = 3 tentativas identicas seguidas.
			_same_as_previous_attempt = _consecutive_repeat_count >= 2
			_previous_issue_signature = _issue_signature

			if crit.verdict == Verdict.APPROVED:
				# 5.70.0 -- so cacheia pesquisa que passou na verificacao.
				#
				# web_researcher gravava o resultado no fim do proprio run(),
				# ANTES de o Critic existir na historia: uma pesquisa que o
				# pipeline julgava errada virava "conhecimento" persistido por 7
				# dias e servido a toda execucao seguinte, inclusive a busca
				# proativa do code_generator. Medido: 15 relatorios com a MESMA
				# reprovacao (pacote legado google-generativeai). Quem conhece o
				# veredicto e este ponto, entao e daqui que a gravacao sai.
				if step.step_type == STEP_WEB_RESEARCH:
					try:
						from ..sub_agents.web_researcher import salvar_se_aprovado
						salvar_se_aprovado(prompt, last_output)
					except Exception as exc:  # pragma: no cover - defesa
						_logger.info("[CACHE] nao foi possivel salvar: %s", exc)
				self._emit("APROVADO", step.step_type)
				# skill: agent-orchestration-improve-agent (Performance Baseline)
				# skill: llm-app-patterns Section 4 (LLMOps): latency_ms completa o baseline
				# skill: evaluation (95% Finding): complexity_level estratifica por complexidade
				_latency_ms = int((time.perf_counter() - _step_start) * 1000)
				_complexity = classify_query_complexity(self._current_complexity())
				from ..gui.settings_panel import get_llm_provider
				memory.log_step_metric(step.step_type, success=True,
					retries=retries, tokens=total_step_tokens,
					trajectory="direct" if attempt == 0 else "retried",
					latency_ms=_latency_ms,
					complexity_level=_complexity,
					model_id=step.model_id, provider=get_llm_provider())
				return StepResult(
					step_id=step.step_id, step_type=step.step_type,
					output=last_output, approved=True,
					score=crit.score, issues=[], retries_used=retries,
					model_used=step.model_id, tokens_used=total_step_tokens,
				)
			elif crit.verdict == Verdict.REJECTED:
				# Um output irrecuperavel deve ser rejeitado, mas a tentativa seguinte
				# recebe os problemas concretos e pode gerar um candidato novo. Antes,
				# REJECT encerrava o step imediatamente e bloqueava todo o grafo, mesmo
				# quando ainda havia retries disponiveis.
				retries += 1
				_logger.info(
					"[INFO] Step %s rejeitado pelo Critic; preparando nova tentativa.",
					step.step_id,
				)
				if _same_as_previous_attempt:
					_logger.info(
						"[LOOP] Step %s: tentativa %d repetiu o MESMO problema da "
						"anterior -- escalando cedo em vez de insistir identico.",
						step.step_id, attempt + 1,
					)
					_loop_broke_early = True
					break
				targeted_fix = self._build_targeted_fix(crit)
				context = context + f"\n\nCORRECAO OBRIGATORIA tentativa {attempt + 1}: {targeted_fix}"
				continue
			else:
				retries += 1
				if (
					step.step_type in _STEPS_QUE_PRODUZEM_ARQUIVO
					and crit.score >= _SCORE_MIN_ACEITACAO_POR_PORTOES
					and (
						_melhor_com_portoes_verdes is None
						or crit.score > _melhor_com_portoes_verdes[0]
					)
				):
					_melhor_com_portoes_verdes = (
						crit.score, last_output, list(crit.issues),
					)
				if _same_as_previous_attempt:
					_logger.info(
						"[LOOP] Step %s: tentativa %d repetiu o MESMO problema da "
						"anterior -- escalando cedo em vez de insistir identico.",
						step.step_id, attempt + 1,
					)
					_loop_broke_early = True
					break
				# skill: llm-evaluation — usa dimension_scores para fix cirurgico
				targeted_fix = self._build_targeted_fix(crit)
				context = (context
					+ f"\n\nFIXME tentativa {attempt + 1}: {targeted_fix}")
				# So anuncia CORRIGINDO se ha proxima tentativa real.
				# Sem isso, a ultima iteracao emitia "tentativa 4 de 3" (attempt+2
				# quando attempt=max_retries-1), enganando o usuario.
				if attempt + 1 < step.max_retries:
					# Mensagem de retry removida — evita poluir o historico.
					# 5.30.0 tentou reintroduzir um evento discreto CORRIGINDO
					# aqui, mas ha teste que trava DE PROPOSITO a ausencia
					# desse evento (test_retry_nao_emite_mensagem_corrigindo_
					# por_tentativa, TestMensagensStatusRicas) -- decisao
					# deliberada anterior do Felipe, revertido nesta mesma
					# versao.
					pass

		# Todas as tentativas esgotadas — tenta escalacao se step critico ou web_research
		#
		# 5.52.0: BUG REAL achado ao vivo (test_e36, os 2 casos do golden eval
		# set, 2026-08-17) -- a checagem antiga so comparava step.model_id !=
		# resilience_model. Mas o switch PROATIVO dentro do loop de retry
		# (attempt>0, ver acima) TAMBEM troca step.model_id pro resilience_model
		# -- so que com reasoning_params=_FALLBACK_REASONING ({}), nunca com
		# _ESCALATION_REASONING_BY_TYPE (que pra code_generation e
		# {"reasoning_effort": "high"}, um esforco de raciocinio genuinamente
		# maior). Resultado: por essa checagem SO olhar o modelo, uma vez que
		# o switch proativo ja acontecia (o caso comum, no meio do loop de
		# retry), _try_escalation() nunca rodava de verdade -- o proprio
		# comentario abaixo ja documentava isso ("quase nunca dispara") mas
		# ninguem tinha corrigido. Consequencia real: cg_core (o step que gera
		# __init__.py raiz com a classe GlobalPlugin) esgotava os 3 retries
		# SEM NUNCA tentar com reasoning_effort=high, e o addon final saia sem
		# __init__.py -- o NVDA nunca carrega. Fix: compara tambem
		# reasoning_params contra o valor que a escalacao de verdade usaria
		# (_ESCALATION_REASONING_BY_TYPE) -- so considera "ja escalado" quando
		# AMBOS (modelo E reasoning_params) ja batem com o que _try_escalation()
		# aplicaria. Para step_types sem reasoning_params de escalacao
		# diferenciado (agent_runner: {}, web_research: nao em
		# _ESCALATION_REASONING_BY_TYPE -> tambem {}), o comportamento fica
		# IDENTICO ao anterior -- o fix so muda o caminho real para
		# code_generation, unico step_type com reasoning_params de escalacao
		# nao-vazio hoje.
		_resilience_model = _get_resilience_model(step.step_type, self._current_complexity())
		_escalation_reasoning = _ESCALATION_REASONING_BY_TYPE.get(step.step_type, {})
		_ja_escalado_de_verdade = (
			step.model_id == _resilience_model
			and step.reasoning_params == _escalation_reasoning
		)
		if step.step_type in _ESCALATION_ELIGIBLE_STEP_TYPES and not _ja_escalado_de_verdade:
			_esc_result = self._try_escalation(step, original_query, context, last_issues, retries_used=retries)
			# 5.52.0: BUG REAL exposto pela propria suite de testes apos o fix
			# acima -- memory.log_step_metric() so era chamado no caminho
			# "esgotado sem escalar" (ver mais abaixo); _try_escalation() em
			# si nunca loga metrica nenhuma. Enquanto a escalacao quase nunca
			# rodava de verdade (bug antigo), essa lacuna nunca aparecia --
			# agora que ela roda normalmente, steps escalados ficavam
			# INVISIVEIS pro tracking de metricas (session_memory), inclusive
			# pra rotular trajectory="loop_detected" corretamente. Loga aqui,
			# no CHAMADOR (que tem os locais _step_start/_loop_broke_early/
			# total_step_tokens que _try_escalation() nao tem -- ela tambem e
			# chamada por _timeout_result_or_escalate(), contexto diferente).
			_esc_latency_ms = int((time.perf_counter() - _step_start) * 1000)
			_esc_complexity = classify_query_complexity(self._current_complexity())
			from ..gui.settings_panel import get_llm_provider as _get_llm_provider_esc
			memory.log_step_metric(step.step_type, success=_esc_result.approved,
				retries=retries, tokens=total_step_tokens + _esc_result.tokens_used,
				trajectory="loop_detected" if _loop_broke_early else "exhausted",
				latency_ms=_esc_latency_ms,
				complexity_level=_esc_complexity,
				model_id=_esc_result.model_used, provider=_get_llm_provider_esc())
			if not _esc_result.approved and _melhor_com_portoes_verdes is not None:
				# A escalacao tambem nao convenceu o Critic. Antes de devolver
				# fracasso, ha um candidato que passou em toda verificacao
				# mecanica -- entregar ele com ressalva e melhor que nada.
				return self._aceitar_por_portoes_verdes(
					step, _melhor_com_portoes_verdes, retries,
					total_step_tokens + _esc_result.tokens_used,
				)
			return _esc_result

		# 5.32.0: web_research (e outros _ESCALATION_ELIGIBLE_STEP_TYPES)
		# trocam pro modelo resiliente PROATIVAMENTE dentro do proprio loop
		# de retry (attempt>0, ver inicio do loop). Antes da 5.52.0 isso fazia
		# a checagem acima quase nunca disparar _try_escalation() de verdade
		# (ver nota acima) -- agora que a checagem tambem olha
		# reasoning_params, o switch proativo (reasoning_params vazio) nao
		# conta mais como "ja escalado" pra step_types com escalacao real
		# (code_generation), entao chegar aqui significa que a escalacao
		# genuina (com reasoning_effort=high) tambem ja foi tentada e nao
		# resolveu. O resgate cross-provider e a ultima linha de defesa.
		last_prompt = self._build_step_prompt(step, original_query, context, previous_issues=last_issues)
		rescued = self._try_cross_provider_rescue(step, last_prompt, context)
		if rescued is not None:
			return rescued

		# skill: agent-orchestration-improve-agent (Performance Baseline)
		# skill: llm-app-patterns Section 4 (LLMOps): latency_ms tambem nas falhas
		# skill: evaluation (95% Finding): complexity_level estratifica por complexidade
		_latency_ms = int((time.perf_counter() - _step_start) * 1000)
		_complexity = classify_query_complexity(self._current_complexity())
		from ..gui.settings_panel import get_llm_provider
		memory.log_step_metric(step.step_type, success=False,
			retries=retries, tokens=total_step_tokens,
			trajectory="loop_detected" if _loop_broke_early else "exhausted",
			latency_ms=_latency_ms,
			complexity_level=_complexity,
			model_id=step.model_id, provider=get_llm_provider())
		if _melhor_com_portoes_verdes is not None:
			return self._aceitar_por_portoes_verdes(
				step, _melhor_com_portoes_verdes, retries, total_step_tokens,
			)
		return StepResult(
			step_id=step.step_id, step_type=step.step_type,
			output=last_output, approved=False,
			score=0, issues=last_issues, retries_used=retries,
			model_used=step.model_id, tokens_used=total_step_tokens,
		)

	# ------------------------------------------------------------------
	# Helpers
	# ------------------------------------------------------------------

	def _aceitar_por_portoes_verdes(
		self,
		step: ExecutionStep,
		melhor: tuple[int, str, list[str]],
		retries: int,
		tokens: int,
	) -> StepResult:
		"""Ultima linha antes de entregar NADA: aceita o melhor candidato que
		passou em TODOS os portoes deterministicos, com as objecoes do Critic
		registradas como ressalva.

		Medido na rodada de 2026-09-03 07:23. O `cg_core` -- o step que gera o
		__init__.py, sem o qual o NVDA nao carrega nada -- foi reprovado tres
		vezes e consumiu 635.658 tokens (55% da rodada) antes de estourar o
		orcamento. As objecoes eram REAIS e DIFERENTES a cada tentativa: a
		tentativa 2 corrigia a 1 e ganhava tres objecoes novas, score 82 contra
		um limiar de 90. O pipeline entregou zero arquivo.

		Nao converge por desenho: um juiz de linguagem natural sempre acha o
		que dizer sobre codigo real, e cada retry muda o codigo o suficiente
		para gerar objecoes novas. Numero de tentativas nao resolve isso --
		so troca "nao converge em 3" por "nao converge em 5, mais caro".

		Por que e seguro parar aqui, e so aqui:

		  - so vale para step que PRODUZ arquivo do addon, onde a alternativa
		    literal e nao entregar nada;
		  - so a partir de score 60, que e o proprio piso do Critic para
		    CORRIGIR: abaixo disso ele diz que o output e irrecuperavel;
		  - so para candidato que CHEGOU ao Critic, o que implica ter passado
		    em target_files, syntax_check, ruff, execucao real em sandbox com
		    o smoke dos comandos, e fault injection;
		  - so depois de a escalacao de modelo e o resgate cross-provider ja
		    terem falhado.

		E a mesma troca que o usuario ja aprovou para `documentation` na
		5.81.0 -- "entrega com ressalva" em vez de "nao entrega" -- e pela
		mesma razao: existe rede deterministica embaixo. A diferenca e que
		aqui a rede e mais forte do que era la, porque o smoke dos comandos e
		a NVDA-063 entraram depois.

		A ressalva NAO e cosmetica: vai nas issues do StepResult, aparece no
		relatorio, e o portao final ainda pode barrar o pacote.
		"""
		score, output, issues = melhor
		_logger.warning(
			"[PORTOES] Step %s: aceito com ressalva por score %d apos portoes "
			"deterministicos verdes -- a alternativa era entregar nada. %d objecao(oes) "
			"do Critic registradas.", step.step_id, score, len(issues),
		)
		ressalvas = [
			f"ACEITO COM RESSALVA (score {score}, limiar 90): o codigo passou em "
			"todos os portoes deterministicos (arquivos declarados entregues, "
			"sintaxe, lint, execucao real em sandbox com os comandos acionados, "
			"fault injection), e as tentativas de correcao se esgotaram. As "
			"objecoes abaixo do Critic NAO foram resolvidas:",
			*issues,
		]
		return StepResult(
			step_id=step.step_id, step_type=step.step_type,
			output=output, approved=True,
			score=score, issues=ressalvas, retries_used=retries,
			model_used=step.model_id, tokens_used=tokens,
		)

	def _arquivos_de_outros_steps(
		self, step: ExecutionStep, ja_produzidos: dict,
	) -> list[str]:
		"""
		Arquivos .py que o PLANO declara, outro step produz, e ainda nao existem.

		Serve para a verificacao de execucao nao reprovar um step por importar
		algo que, por desenho do plano, so vai existir depois. Sem plano em maos,
		devolve lista vazia -- e o comportamento anterior, e o seguro.
		"""
		plano = getattr(self, "_current_plan", None)
		if plano is None:
			return []
		declarados = [
			c for c in (getattr(plano, "expected_files", []) or [])
			if isinstance(c, str) and c.endswith(".py")
		]
		meus = set(getattr(step, "target_files", []) or [])
		return [
			c for c in declarados
			if c not in ja_produzidos and c not in meus
		]

	def _deps_ready(self, step: ExecutionStep, outputs: dict) -> bool:
		return all(dep in outputs for dep in step.depends_on)

	def _saldo_permite_seguir(
		self, remaining: list, failed_step_ids: set,
		plan: "ExecutionPlan | None" = None, outputs: "dict | None" = None,
	) -> tuple[bool, str]:
		"""Reserva de orcamento para a entrega (padrao 'budget backstop').

		Nas duas rodadas complexas de 2026-09-02 a UNICA etapa que ficou de fora
		foi o assembly: ResumoGemini estourou o teto por 2% (853.455/836.850) e
		AssistenteEscrita por 5% (1.272.721/1.209.750) -- as duas com TODO o
		codigo do addon ja gerado e aprovado. Steps que nao produzem arquivo
		gastaram o saldo que faltava para empacotar.

		Quando o saldo entra na reserva o pipeline NAO para: descarta o que nao
		entrega e segue direto para a entrega. Os descartados entram em
		failed_step_ids porque _deps_partially_ready() exige dependencia em
		failed_step_ids para liberar execucao com contexto parcial -- sem isso o
		assembly ficaria eternamente nao-pronto e o laco giraria em falso.

		Metodo unico de proposito: o portao de orcamento existe em DOIS pontos
		(execucao normal e retomada). Duplicar esta logica repetiria o defeito
		em um dos dois (Regra 5).
		"""
		ok, motivo = iteration_budget.can_continue()
		if ok:
			return True, ""
		entregaveis = [
			s for s in remaining if s.step_type in _STEP_TYPES_DE_ENTREGA
		]
		if not entregaveis or not iteration_budget.can_continue(para_entrega=True)[0]:
			return False, motivo
		descartados = [
			s for s in remaining if s.step_type not in _STEP_TYPES_DE_ENTREGA
		]
		# 5.87.0 -- NAO montar uma casca CONDENADA.
		#
		# Descartar um step que ainda deve um modulo Python DECLARADO nao e
		# "entregar algo": o portao de completude (_missing_declared_files,
		# 5.86.0) vai rejeitar o pacote montado sem ele. Antes do portao existir,
		# a casca era degradacao graciosa; agora e pagar a montagem (medido:
		# ~82.480 tokens na rodada de 2026-09-03) de um pacote que ja nasce
		# reprovado. Parar aqui e honesto -- o portao roda na FASE 6 e nomeia o
		# modulo que faltou -- e barato. So os steps PURAMENTE consultivos
		# (design_review, web_research, ...) seguem sendo descartados para dar
		# lugar a entrega. Sem plano em maos (chamador antigo/teste), o
		# comportamento e o anterior (nada condena) -- e o seguro.
		if self._descarte_condena_entrega(descartados, plan, outputs):
			return False, motivo
		_logger.warning(
			"[BUDGET] Saldo entrou na reserva de entrega (%s). Descartando %d "
			"step(s) que nao produzem arquivo e seguindo para a entrega: %s",
			motivo, len(descartados),
			", ".join(s.step_id for s in descartados[:8]) or "nenhum",
		)
		for d in descartados:
			failed_step_ids.add(d.step_id)
			remaining.remove(d)
		return True, ""

	@staticmethod
	def _python_files_produzidos(outputs: "dict | None") -> set:
		"""Nomes de arquivo .py ja gerados (qualquer step), lidos dos blocos de
		codigo dos outputs -- mesma leitura de _validate_minimum_addon_artifacts.

		Conservador de proposito: conta tudo que apareceu num output, aprovado
		ou nao. Um modulo presente mas reprovado sera tratado como 'ja existe' e
		NAO condenara o descarte -- no pior caso reproduz o comportamento antigo
		(monta e o portao rejeita), nunca o pior desfecho (parar uma entrega que
		na verdade estava completa)."""
		produzidos: set = set()
		for saida in (outputs or {}).values():
			for block in extract_code_blocks(saida or ""):
				filename = (block.get("filename") or block.get("name") or "").replace("\\", "/")
				if (block.get("language") or "").lower() == "python" and filename.lower().endswith(".py"):
					produzidos.add(filename.lstrip("/"))
		return produzidos

	@staticmethod
	def _nome_de_arquivo(caminho: str) -> str:
		return caminho.replace("\\", "/").rsplit("/", 1)[-1]

	def _descarte_condena_entrega(
		self, descartados: list, plan: "ExecutionPlan | None", outputs: "dict | None",
	) -> list:
		"""Steps entre os descartados que ainda devem um modulo Python DECLARADO
		e ainda nao produzido -- descarta-los faz o portao de completude
		(_missing_declared_files) reprovar o pacote montado sem eles.

		Compara por NOME DE ARQUIVO, exatamente como o portao decide o que falta:
		ele aceita um declarado cujo NOME bate um entregue, mesmo em caminho
		diferente (caminho divergente e colocacao, que o addon_builder resolve).
		Comparar por caminho aqui pararia uma entrega que o portao APROVARIA --
		o modulo existe, so noutro caminho -- que e o pior desfecho (falso
		positivo que recusa entrega boa).
		"""
		declarados = {
			self._nome_de_arquivo(c)
			for c in (getattr(plan, "expected_files", []) or [])
			if isinstance(c, str) and c.endswith(".py")
		}
		if not declarados:
			return []
		produzidos = {self._nome_de_arquivo(p) for p in self._python_files_produzidos(outputs)}
		pendentes = declarados - produzidos
		if not pendentes:
			return []
		condenam = []
		for s in descartados:
			if s.step_type not in _STEPS_QUE_PRODUZEM_ARQUIVO:
				continue
			alvos = {
				self._nome_de_arquivo(c)
				for c in (getattr(s, "target_files", []) or [])
			}
			if alvos & pendentes:
				condenam.append(s)
		return condenam

	def _deps_partially_ready(self, step: ExecutionStep, outputs: dict, failed_step_ids: set) -> bool:
		"""Verifica se pelo menos um dependente falhou mas outros estao disponiveis.

		Retorna True se:
		- Ha pelo menos uma dependencia em outputs (disponivel)
		- E pelo menos uma dependencia em failed_step_ids (falhou)
		Isso significa que o step pode tentar executar com contexto parcial
		em vez de ficar bloqueado indefinidamente.
		"""
		if not step.depends_on:
			return False
		available = sum(1 for dep in step.depends_on if dep in outputs)
		failed = sum(1 for dep in step.depends_on if dep in failed_step_ids)
		return available > 0 and failed > 0

	def _build_context(self, step: ExecutionStep, outputs: dict) -> str:
		"""
		Constrói contexto estruturado para o step a partir dos outputs anteriores.

		v5.0.0 (2026-05-15): Integrado context_compressor (G9).
		Substitui truncamento simples por compressao semantica com secoes:
		DECISAO_PRINCIPAL, ARTEFATOS_GERADOS, PONTOS_CRITICOS.

		skill: context-compression — Anchored summary preserves critical info.
		skill: context-degradation — Lost-in-middle: info no meio recebe menos atenção.

		5.84.0 (2026-09-03): steps que JULGAM codigo saem por outro caminho --
		ver _STEPS_QUE_JULGAM_CODIGO e _build_context_com_codigo_integro().
		"""
		if step.step_type in _STEPS_QUE_JULGAM_CODIGO:
			return self._build_context_com_codigo_integro(step, outputs)

		parts = []
		for sid in step.context_from_steps:
			if sid not in outputs:
				continue
			raw = outputs[sid]
			if len(raw) <= _MAX_CONTEXT_CHARS_PER_STEP:
				parts.append(f"--- Output do step {sid} ---\n{raw}")
			else:
				# G9: Compressao semantica em vez de truncamento simples
				compressed = context_compressor.compress(raw, _MAX_CONTEXT_CHARS_PER_STEP)
				parts.append(
					f"--- Output do step {sid} [COMPRIMIDO] ---\n"
					f"{compressed.full_text}\n"
					f"[FIM_COMPRIMIDO]"
				)
		joined = "\n\n".join(parts)

		# Teto AGREGADO (achado 2026-08-04, ver constante acima) -- cada
		# dependencia individual ja respeita _MAX_CONTEXT_CHARS_PER_STEP, mas
		# um step com muitas dependencias podia somar sem limite.
		if len(joined) > _MAX_TOTAL_CONTEXT_CHARS:
			_logger.warning(
				"[AVISO] Contexto agregado de %d dependencia(s) tem %d chars, "
				"acima do teto de %d -- comprimindo mais uma vez.",
				len(step.context_from_steps), len(joined), _MAX_TOTAL_CONTEXT_CHARS,
			)
			compressed_total = context_compressor.compress(joined, _MAX_TOTAL_CONTEXT_CHARS)
			return compressed_total.full_text

		return joined

	def _build_context_com_codigo_integro(self, step: ExecutionStep, outputs: dict) -> str:
		"""Contexto de quem julga codigo: o codigo vai INTEIRO, nunca resumido.

		A compressao semantica e boa para prosa (pesquisa, plano, decisao) e
		destrutiva para codigo: some com imports, renomeia funcao, e o proximo
		leitor nao tem como saber que o que ele esta lendo nao e o arquivo.
		Um revisor que recebe resumo reporta o resumo como se fosse o codigo --
		foi assim que o assembly reprovou o AssistenteEscrita 3x por imports
		que estavam nas 9 primeiras linhas.

		Regras deste caminho:
		  - bloco de codigo vai VERBATIM, com o nome do arquivo;
		  - output sem codigo (pesquisa, plano) segue comprimido -- nao ha
		    codigo para um resumo deturpar;
		  - se estourar o teto, OMITE arquivo inteiro e DIZ quais omitiu.
		    Um revisor que sabe que nao viu tudo cala sobre o que falta; um
		    que recebe resumo acha que viu.
		"""
		partes: list[str] = []
		omitidos: list[str] = []
		orcamento = _MAX_CONTEXT_CHARS_CODIGO

		for sid in step.context_from_steps:
			if sid not in outputs:
				continue
			raw = outputs[sid]
			blocos = [b for b in extract_code_blocks(raw) if b.get("code")]

			if not blocos:
				if len(raw) > _MAX_CONTEXT_CHARS_PER_STEP:
					raw = context_compressor.compress(raw, _MAX_CONTEXT_CHARS_PER_STEP).full_text
				trecho = f"--- Output do step {sid} ---\n{raw}"
				if len(trecho) <= orcamento:
					orcamento -= len(trecho)
					partes.append(trecho)
				continue

			for bloco in blocos:
				nome = bloco.get("filename") or "(arquivo sem nome)"
				linguagem = bloco.get("language") or "python"
				trecho = (
					f"--- Arquivo {nome} (gerado no step {sid}) ---\n"
					f"```{linguagem}\n{bloco['code']}\n```"
				)
				if len(trecho) > orcamento:
					omitidos.append(nome)
					continue
				orcamento -= len(trecho)
				partes.append(trecho)

		if omitidos:
			# Dizer o que falta e a diferenca entre um revisor cauteloso e um
			# que inventa. O custo de nao avisar ja foi medido em 310 mil tokens.
			partes.append(
				"--- AVISO DE CONTEXTO ---\n"
				f"{len(omitidos)} arquivo(s) NAO cabem neste contexto e NAO estao "
				f"acima: {', '.join(omitidos)}. Nao afirme nada sobre o conteudo "
				"deles -- avalie apenas o codigo literalmente presente aqui."
			)

		return "\n\n".join(partes)

	def _tool_approval_callback(self, tool_name: str, arguments: dict) -> bool:
		"""
		Callback de aprovação para tool_system.

		Defense-in-depth (pesquisa 2026, ver memoria de sessao): pre-filtro
		deterministico primeiro (ApprovalWorkflow.analyze_risk -- regex
		tecnico/sintatico pra hardline e padroes perigosos conhecidos, rapido
		e imune a prompt injection por nao ser probabilistico), humano depois
		pra qualquer coisa que sobrar. Um nao substitui o outro. Antes, esse
		callback so tinha uma allowlist fixa de 4 nomes de tool, sem nenhuma
		analise de argumento -- self._approval_workflow ja existia
		(instanciado no __init__) mas nunca era chamado.
		"""
		from ..gui.studio_dialog import get_current_dialog

		risk_level, reason, _patterns = self._approval_workflow.analyze_risk(tool_name, arguments)

		if risk_level == "critical":
			_logger.error("[BLOCKED] %s: %s", tool_name, reason)
			return False

		if risk_level == "low":
			return True

		# Risco medio/alto -- requer aprovacao humana explicita, com o motivo
		# especifico mostrado no dialog. Sem dialog ativo nao ha canal de
		# aprovacao -- nega por seguranca (fail-closed).
		dialog = get_current_dialog()
		if not dialog:
			_logger.warning("[AVISO] Nenhum dialog ativo para tool approval — negando %s", tool_name)
			return False

		return dialog.approve_tool(tool_name, arguments, reason=reason)

	def _project_type(self) -> str:
		"""project_type do plano atual ("addon" default, "controller_client").
		Helper pequeno pra nao repetir o guard contra self._current_plan
		None em cada call site (Regra 5: roteamento deterministico)."""
		plan = getattr(self, "_current_plan", None)
		return plan.project_type if plan else "addon"

	def _build_step_prompt(
		self, step: ExecutionStep, query: str, context: str, previous_issues: list
	) -> str:
		prompt = ""
		# 5.50.0: marcador de roteamento deterministico (Regra 5/9) pra
		# controller_client_context.py -- code_generator.py/critic.py checam
		# esse prefixo (is_controller_client_context()) pra usar o catalogo
		# de regras certo. Prependido ANTES de tudo (maxima primazia de
		# atencao do LLM, mesmo racional do fix 5.31.0 abaixo).
		if self._project_type() == "controller_client":
			from ..builder.controller_client_context import project_type_marker
			prompt += project_type_marker()
		prompt += f"Tarefa original do usuario: {query}\n\n"
		prompt += f"Seu objetivo neste step: {step.description}\n"
		prompt += f"Output esperado: {step.expected_output}\n"

		# 5.58.0: layout de arquivos declarado no plano. Sem ele os nomes de
		# arquivo nasciam da improvisacao do modelo, bloco a bloco -- e um bloco
		# sem anotacao de caminho caia no fallback module_N.py de
		# addon_builder._infer_python_filename(), justamente o unico nome que o
		# NVDA nunca carrega dentro de um pacote. Injetado so nos steps que
		# escrevem arquivo; nos demais seria ruido no contexto.
		# Marcador de topicos ANTES de tudo: code_generator.run() le do prompt
		# (nao recebe o objeto do step). Mesmo canal do project_type_marker.
		if step.step_type == "code_generation":
			# 5.64.0 -- REVERTIDA a reducao de contexto no retry (5.63.0).
			#
			# A hipotese era: "na tentativa 2 o modelo ja tem o codigo e a lista
			# de problemas; falta corrigir um import, nao reaprender a API do
			# NVDA". Enviar so o core no retry cortava 75% dos docs.
			#
			# MEDIDO EM E2E REAL e a hipotese caiu. O mecanismo funcionou como
			# projetado -- custo por tentativa caiu de ~103 mil para ~67 mil
			# tokens -- e o RESULTADO piorou muito:
			#
			#     AssistenteLeituraGemini   nota 52.0 -> 15.7
			#     GeminiMultimodal         nota 32.7 ->  9.1
			#
			# O modelo PRECISA do contexto para fazer a correcao que o Critic
			# pediu; sem a fonte do NVDA ele corrige no escuro. Economia de
			# tokens que reduz a taxa de acerto nao e economia -- e so falhar
			# mais barato. Nao retentar sem medir de novo.
			#
			# O escopo por TOPICO (declarado pelo planner) continua valendo: ali
			# o contexto e menor por ser irrelevante ao arquivo, nao por ser
			# sonegado ao modelo.
			prompt = nvda_topics_marker(getattr(step, "nvda_topics", []) or []) + prompt

		if step.step_type in ("code_generation", "agent_runner", "assembly"):
			_plano_atual = getattr(self, "_current_plan", None)
			if _plano_atual is not None:
				prompt += format_expected_files_for_prompt(
					getattr(_plano_atual, "expected_files", []) or []
				)

		# 5.62.0: alem do layout do addon INTEIRO, o step diz quais arquivos ELE
		# produz. Medido no E2E de 2026-08-29: os code_generation que falham
		# consomem ~419 mil tokens em 3 tentativas e sao reprovados por entrega
		# parcial; o unico aprovado gastou 127 mil. A diferenca era quantos
		# arquivos o step tentava produzir de uma vez. Dizer o escopo exato evita
		# que o modelo tente entregar a feature toda numa tacada.
		_alvos = getattr(step, "target_files", []) or []
		if _alvos and step.step_type in ("code_generation", "agent_runner"):
			prompt += (
				"\nARQUIVOS DESTE STEP -- produza EXATAMENTE estes, nenhum a mais:\n"
				+ "".join(f"  {caminho}\n" for caminho in _alvos)
				+ "Os demais arquivos do addon sao responsabilidade de outros steps. "
				"Gerar arquivo fora desta lista nao adianta o trabalho: o step e "
				"avaliado apenas pelo que foi pedido aqui.\n"
			)
		if context:
			prompt += f"\nContexto de steps anteriores:\n{context}\n"
		# Em retomadas, o contexto em memória pode não existir mais. Recupera
		# somente as dependências declaradas pelo planner, sem despejar a sessão
		# inteira no prompt.
		plan = getattr(self, "_current_plan", None)
		if plan:
			recovered = execution_context_store.get_context(
				plan.plan_id,
				list(dict.fromkeys(step.context_from_steps or step.depends_on)),
			)
			if recovered and recovered not in context:
				prompt += f"\nContexto recuperado do checkpoint desta execução:\n{recovered}\n"

		# G10 (2026-05-15): Agent-specific memory — cada agente aprende com seus proprios erros.
		# Memorias de sucesso e falha sao injetadas como dicas especificas.
		# 5.46.0: achado real de auditoria de integracao -- agent_mem.recall()
		# (recuperacao RANQUEADA POR RELEVANCIA ao contexto atual, via
		# rank_relevant()) existia desde 1.0.0, totalmente testado
		# (test_agent_memory.py), mas nunca era chamado aqui -- so
		# get_common_mistakes()/get_successful_patterns() (frequencia bruta,
		# sem nenhum filtro de relevancia ao contexto) eram usados. Um erro
		# comum mas IRRELEVANTE pro contexto atual (ex: erro de import numa
		# feature totalmente diferente) podia aparecer na dica antes de um
		# erro raro mas diretamente relevante. Complementa (nao substitui) a
		# ordenacao por frequencia: recall() roda primeiro, get_common_
		# mistakes/get_successful_patterns preenchem o que faltar ate o
		# limite, sem repetir entradas ja trazidas por relevancia.
		relevant = agent_mem.recall(step.step_type, step.description, limit=3)
		relevant_patterns = {r.pattern for r in relevant}
		if relevant:
			prompt += "\n\n[RELEVANTE AO CONTEXTO ATUAL — aprendido de execucoes anteriores]:\n"
			for r in relevant:
				dica = f"ERRO COMUM: {r.pattern} → CORRECAO: {r.fix}" if not r.success \
					else f"PADRAO: {r.pattern} → SOLUCAO: {r.fix or r.outcome}"
				prompt += f"- {dica}\n"

		common_mistakes_raw = agent_mem.get_common_mistakes(step.step_type, limit=3)
		common_mistakes = [m for m in common_mistakes_raw
			if not any(p in m for p in relevant_patterns)]
		if common_mistakes:
			prompt += "\n\n[EVITE ESTES ERROS — aprendido de execucoes anteriores]:\n"
			for m in common_mistakes:
				prompt += f"- {m}\n"

		successful_raw = agent_mem.get_successful_patterns(step.step_type, limit=2)
		successful = [s for s in successful_raw
			if not any(p in s for p in relevant_patterns)]
		if successful:
			prompt += "\n[SIGA ESTES PADROES — tecnicas que funcionaram antes]:\n"
			for s in successful:
				prompt += f"- {s}\n"

		# Feedback loop filtrado por step_type: cada sub-agente aprende apenas com
		# seus proprios erros historicos — nao com erros de outros sub-agentes.
		failures = memory.get_recent_failures(limit=3, step_type=step.step_type)
		if failures:
			prompt += "\n\nPadroes de erro de sessoes anteriores — EVITE repetir:\n"
			for f in failures:
				prompt += f"- {f}\n"
		# previous_issues fica no FINAL: lost-in-middle (context-degradation) — posicao
		# final recebe maxima atencao do LLM. Estes erros DEVEM ser corrigidos no retry.
		if previous_issues:
			prompt += "\nProblemas da tentativa anterior que DEVEM ser corrigidos:\n"
			prompt += "\n".join(f"- {issue}" for issue in previous_issues)

		# Hermes-inspired v2.1.0: Memory context (MEMORY.md + USER.md)
		try:
			memory_block = memory_manager.build_system_prompt_block()
			if memory_block:
				prompt += memory_block
				_logger.debug("[DEBUG] Memory context injetado no prompt (%d chars)", len(memory_block))
		except Exception as e:
			_logger.debug("[DEBUG] Memory context não disponível: %s", e)

		# 5.31.0: achado real do golden eval set (test_e36) -- web_research
		# devolvia repetidamente um addon Python generico em vez de pesquisa,
		# mesmo com o _SYSTEM do sub-agente proibindo explicitamente esse
		# formato. Causa provavel: "Tarefa original do usuario" (a query
		# INTEIRA de criacao de addon, longa e com foco explicito em
		# codigo) e a PRIMEIRA coisa do prompt, e "Seu objetivo neste step"
		# (a instrucao real e estreita) aparece uma unica vez, logo em
		# seguida, sem reforco. Pesquisa (2026-08-08, ver primacy/recency
		# bias e "lost in the middle" em LLMs -- intuitionlabs.ai,
		# dev.to/thousand_miles_ai): repetir a instrucao real perto do
		# final do prompt reduz a distancia posicional e evita que o
		# modelo "derive" pro topico mais saliente do inicio -- mesmo
		# raciocinio ja usado aqui pra previous_issues (linha acima).
		prompt += f"\n\nLEMBRETE FINAL — seu objetivo neste step e apenas: {step.description}"

		return prompt

	@staticmethod
	def _build_targeted_fix(crit: CriticResult) -> str:
		"""
		Usa dimension_scores para gerar instrucao de retry cirurgica.
		skill: llm-evaluation (Multi-Dimensional Scoring).

		Sem dimension_scores: retorna fix_instructions intacto.
		Com dimension_scores: prefixa com a dimensao mais fraca para focar o retry.
		"""
		dims: dict = getattr(crit, "dimension_scores", None) or {}
		if not dims or not isinstance(dims, dict):
			return crit.fix_instructions
		worst_dim, worst_score = min(dims.items(), key=lambda x: x[1])
		labels = {
			"completeness":   "completude (entregue tudo que foi pedido)",
			"format":         "formato de saida (sem HTML, sem texto extra, Python/INI puro)",
			"nvda_compliance": "conformidade NVDA/WX-A11Y (decorators, handlers, a11y)",
		}
		label = labels.get(worst_dim, worst_dim)
		return f"[FOCO: {label} — score {worst_score}/100] {crit.fix_instructions}"

	# Step types cujos outputs vao para final_output (fonte para extracao de blocos)
	_CODE_OUTPUT_STEP_TYPES: frozenset = frozenset({
		"code_generation", "manifest_builder", "documentation",
		"agent_runner", "agent_template", "assembly",
		"syntax_validation",  # relatorio de validacao vai para o assembler como contexto
	})

	@staticmethod
	def _validate_minimum_addon_artifacts(
		plan: ExecutionPlan,
		step_results: list[StepResult],
		outputs: dict[str, str],
	) -> str:
		"""Recusa conclusao falsa quando o addon essencial nao foi gerado."""
		approved_ids = {result.step_id for result in step_results if result.approved}
		python_files: set[str] = set()
		manifest_found = False
		for step in plan.steps:
			if step.step_id not in approved_ids or step.step_id not in outputs:
				continue
			for block in extract_code_blocks(outputs[step.step_id]):
				filename = (block.get("filename") or block.get("name") or "").replace("\\", "/")
				language = (block.get("language") or "").lower()
				if language == "python" and filename.lower().endswith(".py"):
					python_files.add(filename)
				if filename.lower() == "manifest.ini":
					manifest_found = True

		if not python_files:
			return (
				"A criação não foi concluída porque nenhum arquivo Python válido do addon "
				"foi gerado e aprovado. O manifesto e a documentação isolados não formam um addon."
			)
		# 5.50.0: manifest.ini nunca existe num projeto controller_client
		# (programa externo, sem addonHandler) -- exigi-lo aqui rejeitaria
		# TODA criacao bem-sucedida desse tipo.
		# 5.75.0 -- MANIFEST AUSENTE NAO E MAIS FATAL AQUI.
		#
		# addon_builder._generate_minimal_manifest() existe, e deterministica, e
		# foi escrita EXATAMENTE para este caso -- a docstring dela diz "gera
		# manifest.ini minimo quando manifest_builder falhou". Mas ela e chamada
		# dentro de save_addon_files(), no assembly, e esta validacao roda ANTES
		# do assembly: a execucao morria antes de o fallback ter chance de agir.
		#
		# E o proprio projeto ja declarava a intencao contraria: manifest_builder
		# esta em _NON_BLOCKING_STEP_TYPES com o comentario "assembly pode
		# regenerar manifest se necessario". A regra e o comentario discordavam, e
		# quem vencia era a regra.
		#
		# Medido na rodada 7 (AssistenteLeituraGemini): 4 steps aprovados,
		# 1.466.531 tokens, e a entrega descartada porque o step de manifest nao
		# foi aprovado -- sendo que o Critic tinha escrito, no primeiro achado,
		# "o manifest.ini atende aos campos obrigatorios". Um addon com manifest
		# minimo deterministico e codigo que funciona serve ao usuario; nenhum
		# addon nao serve.
		#
		# O que continua fatal e a ausencia de codigo Python, verificada acima:
		# manifest sem addon nao e addon.
		if plan.project_type != "controller_client" and not manifest_found:
			_logger.warning(
				"[MANIFEST] Nenhum manifest.ini aprovado. O assembly vai gerar o "
				"minimo deterministico (addon_builder._generate_minimal_manifest)."
			)

		# 5.57.0 -- PONTO DE ENTRADA CARREGAVEL.
		#
		# Achado real, medido nos 379 relatorios de tests/e2e/relatorios/:
		# TODOS os 11 addons Gemini marcados success=True estavam QUEBRADOS.
		# Exemplos com nome e data:
		#   2026-08-17 10:27 AssistenteLeituraGemini -- 16 arquivos Python,
		#     arquitetura por feature (qa/, summarizer/, web_search/), score
		#     64.7 ... e nenhum globalPlugins/<Addon>/__init__.py.
		#   2026-08-16 11:48 GeminiMultimodal -- so module_1.py, score 80.8.
		#   2026-08-17 19:49 AssistenteLeituraGemini -- 30 retries, 2.5M
		#     tokens, entregou APENAS manifest.ini (esse ja era pego pela
		#     checagem de python_files acima).
		#
		# O NVDA carrega addon por CONVENCAO DE CAMINHO, nao por conteudo: um
		# pacote em globalPlugins/ so e carregado pelo __init__.py; qualquer
		# outro .py ao lado dele e ignorado. Um addon sem ponto de entrada nao
		# falha com erro -- ele simplesmente NAO EXISTE para o usuario cego,
		# que instala, nao ouve nada e nao tem como descobrir por que.
		#
		# A deteccao ja existia: validate_addon_structure() emite ESTRUTURA-008
		# exatamente para isso, e a mensagem aparecia nos relatorios. Mas ela
		# roda no caminho de EMPACOTAMENTO da GUI (studio_dialog), nunca no
		# veredito do pipeline -- entao o defeito era detectado, registrado por
		# escrito, e ignorado. Esta funcao ja e o portao de "recusa conclusao
		# falsa"; faltava ela conhecer a regra de carregamento do NVDA.
		if plan.project_type != "controller_client":
			entry_error = Orchestrator._missing_loadable_entry_point(python_files)
			if entry_error:
				return entry_error

		# 5.86.0 -- O ADDON ESTA COMPLETO?
		#
		# O portao acima prova que o addon CARREGA. Nao prova que ele tem
		# tudo o que o plano declarou. Ver _missing_declared_files: a rodada
		# de 2026-09-03 17:26 entregou 1 dos 3 modulos Python declarados e
		# passou em TODOS os portoes, inclusive na execucao real.
		declared_error = Orchestrator._missing_declared_files(
			getattr(plan, "expected_files", []) or [], python_files,
		)
		if declared_error:
			return declared_error

		# 5.57.0 -- FUNCIONALIDADE PEDIDA vs FUNCIONALIDADE ENTREGUE.
		#
		# Ate aqui o portao so provava que o addon EXISTE e CARREGA. Faltava a
		# pergunta que o usuario realmente faz: ele faz o que eu pedi?
		#
		# A divisao segue a Regra 7 do README. Interpretar o pedido em
		# linguagem natural e decisao SEMANTICA: quem faz e a LLM, declarando
		# os atalhos em `plan.expected_gestures`. Extrair "NVDA+H" da frase do
		# usuario com regex seria exatamente o "simular entendimento semantico
		# com regex" que a regra proibe. Aqui so CONFERIMOS que o que foi
		# declarado existe no AST do codigo aprovado.
		#
		# Lista vazia (addon sem atalho: so item de menu, AppModule reagindo a
		# evento, driver) nao verifica nada -- validate_declared_gestures
		# devolve ok=True e o portao segue.
		if plan.expected_gestures:
			gesture_error = Orchestrator._missing_requested_gestures(
				plan.expected_gestures, step_results, outputs, approved_ids,
			)
			if gesture_error:
				return gesture_error

		# 5.58.0 -- COERENCIA ENTRE OS ARQUIVOS DO PROPRIO ADDON.
		#
		# Ate aqui cada arquivo era validado ISOLADAMENTE: sintaxe, regras NVDA,
		# lint, tipos, e ate execucao real. Ninguem perguntava se o CONJUNTO
		# fecha. Foi assim que os addons Gemini dos relatorios sairam com
		# `qa/service.py` e `summarizer/service.py` impecaveis e um __init__.py
		# importando de modulos que nenhum step chegou a gerar -- cada peca boa,
		# o addon morto.
		coherence_error = Orchestrator._broken_internal_imports(
			step_results, outputs, approved_ids,
		)
		if coherence_error:
			return coherence_error
		return ""

	@staticmethod
	def _broken_internal_imports(
		step_results: list[StepResult],
		outputs: dict[str, str],
		approved_ids: set[str],
	) -> str:
		"""
		Confere que os imports relativos entre arquivos do addon resolvem.

		Monta o conjunto {caminho: codigo} de tudo que foi aprovado e delega
		para validate_internal_imports(), que so julga import RELATIVO --
		import absoluto pode vir do stdlib, de lib/ bundlado ou dos modulos do
		NVDA, e ja e tratado por validate_python_imports() no addon_builder.

		Degrada em silencio se o validador nao estiver disponivel: falha de
		import aqui nunca deve derrubar uma criacao que deu certo.
		"""
		try:
			from ..sub_agents.ast_validator import validate_internal_imports
		except Exception:  # pragma: no cover - defesa de import
			return ""

		arquivos: dict[str, str] = {}
		for result in step_results:
			if result.step_id not in approved_ids or result.step_id not in outputs:
				continue
			for block in extract_code_blocks(outputs[result.step_id]):
				nome = (block.get("filename") or "").replace("\\", "/")
				if nome.endswith(".py"):
					arquivos[nome] = block.get("code") or ""
		if len(arquivos) < 2:
			# Com um arquivo so nao existe "entre arquivos" a verificar.
			return ""

		resultado = validate_internal_imports(arquivos)
		if resultado.ok:
			return ""
		return (
			"A criação não foi concluída porque os arquivos do addon não se encaixam: "
			+ " ".join(resultado.violacoes[:4])
		)

	@staticmethod
	def _missing_requested_gestures(
		esperados: list[str],
		step_results: list[StepResult],
		outputs: dict[str, str],
		approved_ids: set[str],
	) -> str:
		"""
		Confere que os atalhos declarados no plano existem no codigo aprovado.

		Junta TODOS os blocos Python aprovados antes de validar: um addon
		multi-arquivo pode declarar o script num modulo e o resto noutro, e
		validar bloco a bloco reprovaria addon correto por atalho "ausente" no
		arquivo errado -- falso positivo garantido.

		Degrada em silencio se o validador nao estiver disponivel: uma falha de
		import aqui nunca deve derrubar uma criacao que deu certo.
		"""
		try:
			from ..sub_agents.ast_validator import validate_declared_gestures
		except Exception:  # pragma: no cover - defesa de import
			return ""

		partes: list[str] = []
		for result in step_results:
			if result.step_id not in approved_ids or result.step_id not in outputs:
				continue
			for block in extract_code_blocks(outputs[result.step_id]):
				if (block.get("language") or "").lower() == "python":
					partes.append(block.get("code") or "")
		if not partes:
			return ""

		resultado = validate_declared_gestures("\n".join(partes), esperados)
		if resultado.ok:
			return ""
		return (
			"A criação não foi concluída porque o addon não expõe os atalhos que você pediu. "
			+ " ".join(resultado.violacoes)
		)

	# Diretorios que o NVDA carrega por convencao, com o padrao de arquivo que
	# ele reconhece como ponto de entrada em cada um. Fonte: addonHandler e a
	# estrutura oficial do AddonTemplate (nvda_docs_cache/).
	_ENTRY_POINT_DIRS: tuple[str, ...] = (
		"globalPlugins",
		"appModules",
		"synthDrivers",
		"brailleDisplayDrivers",
		"visionEnhancementProviders",
	)

	@staticmethod
	def _missing_declared_files(
		expected_files: list[str], python_files: set[str],
	) -> str:
		"""Confere que os modulos Python DECLARADOS no plano chegaram.

		Medido na rodada de 2026-09-03 17:26 (a primeira inteira pela Factory):
		o pedido tinha tres partes -- dois atalhos, um servico OpenAI e uma tela
		de configuracoes -- e o addon entregue tinha UM arquivo Python. O
		`__init__.py` importava `settings_panel` e `openai_service`, ausentes do
		pacote, com try/except tolerante (que e a pratica CORRETA da NVDA-022).

		Resultado: o addon carregava, registrava os dois atalhos, e ao apertar
		NVDA+shift+G falava "Chave de API nao configurada. Abra as
		configuracoes" -- apontando para uma tela que nao existia. Uma casca.

		Nenhum portao pegou, e cada um por um bom motivo:
		  - o ponto de entrada EXISTIA (__init__.py estava la);
		  - os gestos declarados EXISTIAM (os dois @script estavam la);
		  - a execucao real passou: o addon carrega e os comandos rodam;
		  - a NVDA-063 nao acusou: import ausente vira ImportError tratado,
		    nao discordancia de assinatura.

		Um addon que degrada com elegancia e, pela definicao de todos eles,
		um addon que funciona. Faltava perguntar se ele esta COMPLETO.

		Mesma divisao da Regra 7 usada em `expected_gestures`: declarar o
		layout e decisao semantica da LLM (campo `expected_files` do plano);
		aqui so CONFERIMOS que o declarado chegou. So olha .py -- doc, manifest
		e recursos ja tem portoes proprios.
		"""
		declarados = {
			c.replace("\\", "/").lstrip("/")
			for c in (expected_files or [])
			if isinstance(c, str) and c.endswith(".py")
		}
		if not declarados:
			return ""
		entregues = {c.replace("\\", "/").lstrip("/") for c in python_files}
		# Compara por NOME de arquivo tambem: caminho divergente e problema de
		# colocacao, que o addon_builder ja resolve -- reprovar por isso aqui
		# seria cobrar duas vezes pela mesma coisa.
		nomes_entregues = {c.rsplit("/", 1)[-1] for c in entregues}
		faltando = sorted(
			c for c in declarados
			if c not in entregues and c.rsplit("/", 1)[-1] not in nomes_entregues
		)
		if not faltando:
			return ""
		return (
			"A criação não foi concluída porque o addon ficou incompleto. O plano "
			f"declarou {len(declarados)} arquivo(s) Python e {len(faltando)} não "
			f"chegaram: {', '.join(faltando)}. O addon instalaria e carregaria "
			"normalmente — os imports que faltam são tratados com try/except, como "
			"manda a boa prática — mas a funcionalidade que depende deles "
			"simplesmente não existiria, sem erro visível para o usuário."
		)

	@staticmethod
	def _missing_loadable_entry_point(python_files: set[str]) -> str:
		"""
		Confere que existe pelo menos UM arquivo que o NVDA de fato carrega.

		Formas validas, todas por convencao de caminho:
		  <dir>/<nome>.py            -- modulo solto (appModules/notepad.py)
		  <dir>/<pacote>/__init__.py -- pacote (globalPlugins/MeuAddon/__init__.py)

		Devolve "" quando ha ponto de entrada, ou a mensagem de erro pro
		usuario quando nao ha. A mensagem nomeia os pacotes orfaos encontrados
		-- sem isso o retry seguinte nao sabe QUAL pacote precisa de
		__init__.py e tende a reescrever o addon inteiro do zero.
		"""
		orfaos: set[str] = set()
		for caminho in python_files:
			partes = caminho.replace("\\", "/").lstrip("/").split("/")
			if len(partes) < 2 or partes[0] not in Orchestrator._ENTRY_POINT_DIRS:
				continue
			if len(partes) == 2:
				# <dir>/<nome>.py -- modulo solto, carregavel por si so.
				return ""
			if partes[-1] == "__init__.py" and len(partes) == 3:
				# <dir>/<pacote>/__init__.py -- pacote carregavel.
				return ""
			# .py dentro de um pacote que ainda nao provou ter __init__.py.
			orfaos.add("/".join(partes[:2]))

		if orfaos:
			pacotes = ", ".join(sorted(orfaos))
			return (
				"A criação não foi concluída porque o addon não tem ponto de entrada que o "
				f"NVDA consiga carregar. Os arquivos Python ficaram em {pacotes}, mas sem "
				"__init__.py — o NVDA carrega um pacote de addon apenas pelo __init__.py, "
				"e ignora qualquer outro arquivo ao lado dele. Do jeito que está, o addon "
                "instalaria sem erro e simplesmente não faria nada."
			)
		return (
			"A criação não foi concluída porque nenhum arquivo Python ficou num diretório "
			"que o NVDA carrega (globalPlugins/, appModules/, synthDrivers/, "
			"brailleDisplayDrivers/ ou visionEnhancementProviders/)."
		)

	def _assemble(self, plan: ExecutionPlan, outputs: dict) -> str:
		"""Monta final_output apenas com steps que geram codigo/artefatos.

		Steps internos como web_research, design_review, accessibility_audit,
		test_generation sao excluidos — sao saidas de trabalho interno, nao
		artefatos para o usuario.
		"""
		parts = []
		for step in plan.steps:
			if step.step_id in outputs and step.step_type in self._CODE_OUTPUT_STEP_TYPES:
				parts.append(outputs[step.step_id])
		return "\n\n".join(parts)
