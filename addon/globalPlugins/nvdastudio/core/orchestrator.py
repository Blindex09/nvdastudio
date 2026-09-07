import os
import threading
from typing import Callable

from .orch_types import StepResult, OrchestrationResult, compute_progress
# Staged removido (demolicao 2026-09-06): planner/critic/dispatcher/_base saíram.
from ..ai.model_registry import resetar_saida_estruturada
from ..utils.logger import get_logger
from ..builder.addon_builder import extract_code_blocks
from .orch_types import (
	PipelinePhase, DomainContext, PlanApproval, CheckpointResult,
)
# Novos módulos v2.1.0 (Hermes-inspired)
from ..memory.memory_manager import memory_manager
from ..memory.session_recap import build_session_recap
from ..memory.conversation_manager import conversation
from ..tool_system.approval import ApprovalWorkflow
from ..utils.iteration_budget import budget as iteration_budget

MODULE_VERSION = "5.92.0"
_logger = get_logger("orchestrator")

# ---------------------------------------------------------------------------
# Caminho 3 (arquitetura agentica): o loop agentico (builder/agentic_driver.py) e
# o UNICO caminho de geracao. O pipeline staged foi REMOVIDO (demolicao 2026-09-06,
# Fatia C) -- nao ha mais flag/opt-out nem fallback. Ver
# docs/arquitetura-agentica-caminho3-2026-09-06.md.
# ---------------------------------------------------------------------------
_AGENTIC_CORRECTION_ROUNDS = 2
# Label do unico step que o caminho agentico produz (inlinado; planner deletado).
STEP_CODE_GENERATION = "code_generation"


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



# Timeout maximo por step (segundos)
# v2.1.0 (2026-06-09): Usar timeouts.py centralizado (Hermes-inspired)
# Periodo de graca depois do timeout global do as_completed (segundos).




# Steps nao-bloqueantes: falha nao impede dependentes
# design_review: output (mesmo rejeitado) e passado como contexto ao code_generation;
# a reprovacao nao deve travar o pipeline — o codigo segue com o feedback disponivel.
# web_research: offline ou falha deve anunciar ao usuario, mas nunca bloquear o pipeline.
# agent_template: spec/documentacao do agente — util como contexto, mas code_generation
#   nao pode ser bloqueado por ausencia de template. Output armazenado mesmo sem aprovacao.
# manifest_builder: assembly pode regenerar manifest se necessario; armazenar output mesmo
#   quando rejeitado permite que assembly receba contexto e execute sempre.
# test_generation e documentation: sao BLOQUEANTES — IA retentar ate passar (decisao usuario).

# Steps cujo output E arquivo do addon: sem eles nao ha o que entregar.
# Conceito diferente de _STEP_TYPES_DE_ENTREGA (reserva de orcamento) e de
# _CRITICAL_STEP_TYPES (dispara replanejamento) -- por isso set proprio, e
# nao reuso de um deles com outro significado (Regra 5).

# Piso para aceitar por portoes verdes. 60 e o mesmo limite que o Critic ja
# usa para separar CORRIGIR (60-89) de REJEITAR (<60), em critic.py: abaixo
# disso ele esta dizendo que o output e irrecuperavel, e nao ha portao
# determinístico que compense isso.

# Steps que PRODUZEM a entrega -- so eles enxergam a reserva de orcamento.

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
# Modelo de fallback para erros transitorios (503, timeout persistente) E
# ultimo recurso de _get_resilience_model() se a resolucao dinamica falhar.
# Quando o modelo original falha com erro de infraestrutura (nao logica),
# retenta com este modelo antes de marcar como REJECTED.
# Regra 5: fallback deterministico — nao usa LLM para decidir.
_FALLBACK_MODEL = "kimi-k2.7-code"

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








# Erro de CONTA do provedor: chave invalida, expirada, revogada ou sem saldo.
# Trocar de MODELO nao ajuda -- o problema e a conta, nao o modelo.
#
# 'insufficient balance'/'credits' entram aqui porque provedor devolve 401 para
# falta de saldo. Confirmado ao vivo em 2026-09-02 no OpenCode Go: GET /models
# respondeu 200 (chave VALIDA) e /chat/completions respondeu 401 com
# {"type":"CreditsError","message":"Insufficient balance"}. O correto seria 402,
# e sem esta deteccao o usuario ouviria 'chave invalida' e iria trocar uma chave
# que esta certa.


# Falta de saldo, separada de chave invalida: sao acoes DIFERENTES para o
# usuario (recarregar credito x trocar a chave), e dizer a errada faz ele
# perder tempo no lugar errado.




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

# Maximo de replanos por pipeline (evita loop infinito)

# Achado de auditoria full-stack 2026-08-04 (rastreamento de addons grandes/
# complexos, "addons de qualquer magnitude"): _MAX_CONTEXT_CHARS_PER_STEP
# limitava cada dependencia INDIVIDUAL, mas nao existia teto AGREGADO --
# um step com muitas dependencias (comum em addons ARCH-007 com varias
# features) podia concatenar N * 3000 chars sem limite, indo pro prompt
# final sem nenhum orcamento de tamanho antes de chegar no LLM. ~12000 chars
# cobre confortavelmente 4 dependencias no teto individual; alem disso,
# comprime o AGREGADO com a mesma ferramenta (context_compressor).

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
# Teto proprio, e alto: um addon complexo inteiro cabe. Nao e ausencia de
# orcamento -- e orcamento dimensionado para o que o step precisa ver.






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




ProgressCallback = Callable[[str, str], None]
# Callback mid-pipeline: recebe lista de perguntas, retorna lista de respostas.
# Se nao definido, Orchestrator continua sem as respostas (graceful degradation).
ClarifyCallback = Callable[[list[str]], list[str]]



# Teto de problemas carregados entre tentativas. Alto o bastante para o modelo
# ver tudo que ja foi apontado num step de addon multi-arquivo, baixo o
# bastante para o prompt do retry nao virar um despejo que dilui a atencao --
# o proprio motivo pelo qual conhecimento em prompt tem retorno decrescente.






# Conteudo do modulo que representa um arquivo que OUTRO step do plano ainda vai
# gerar, usado so na verificacao de execucao.
#
# Modulo VAZIO nao basta: `from .configSpec import apply_config_spec` falha com
# "cannot import name" em vez de "no module named" -- medido na rodada 7, o
# cg_core foi reprovado assim mesmo com o placeholder ja no lugar. O
# `__getattr__` de modulo (PEP 562) faz qualquer nome importar, que e o que se
# espera de um contrato ainda nao implementado.




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
		# Staged removido: nao ha mais Planner/Critic -- o agente (droid) planeja,
		# gera e o gate deterministico (code_sandbox) julga.
		self._on_progress: ProgressCallback | None = None
		self._on_complete: Callable[[OrchestrationResult], None] | None = None
		self._on_clarify: ClarifyCallback | None = None
		self._running = False
		self._cancel_requested = False
		# Direcao ao vivo do build agentico: Event que o driver checa para
		# INTERROMPER, e um buffer para o usuario REDIRECIONAR na proxima rodada.
		self._agentic_cancel = threading.Event()
		self._steer_lock = threading.Lock()
		self._pending_steer = ""
		self._outputs_lock = threading.Lock()
		self._tokens_by_model: dict[str, tuple[int, int]] = {}
		self._previous_issues: list[str] = []  # v2.1.0 fix: inicializado para agentic_loop
		self._last_result: OrchestrationResult | None = None  # v2.1.0 fix: inicializado
		self._current_plan = None  # vestigial (staged removido); alguns getters ainda leem
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
		# Direcao ao vivo: sinaliza o driver agentico a matar o processo em curso.
		self._agentic_cancel.set()

	def steer_pipeline(self, texto: str):
		"""Direcao ao vivo: enfileira um ajuste que o usuario digitou durante a
		geracao. O driver agentico o incorpora na PROXIMA rodada de correcao (o
		droid exec e one-shot -- redirecionar acontece na fronteira da rodada, com
		o workdir preservado). Chamadas se acumulam ate serem consumidas."""
		if not texto or not texto.strip():
			return
		with self._steer_lock:
			self._pending_steer = (self._pending_steer + "\n" + texto.strip()).strip()
		_logger.info("[STEER] ajuste do usuario enfileirado para a proxima rodada.")

	def _drenar_steer(self) -> str:
		"""Devolve e LIMPA o ajuste pendente (consumido por rodada)."""
		with self._steer_lock:
			texto, self._pending_steer = self._pending_steer, ""
		return texto

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
		# Staged removido (Fatia C): a geracao e 100% agentica -- o agente direto,
		# com o gate deterministico + auto-correcao (Slice 2). Sem AgenticLoop nem
		# fallback: se o agente nao produzir, erro honesto.
		self._last_result = None
		self._suppress_complete_callback = True
		try:
			entregou = self._run_pipeline_agentic(user_query)
			result = self._last_result
			if not entregou or result is None:
				result = OrchestrationResult(
					plan_id="agentic", query=user_query, step_results=[],
					final_output="", success=False,
					error="O agente nao conseguiu gerar o addon.",
				)
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
	_on_plan_ready: Callable[[object, DomainContext | None], PlanApproval] | None = None
	_on_checkpoint: Callable[[CheckpointResult], bool] | None = None

	def set_conversational_callbacks(
		self,
		on_phase_change: Callable[[PipelinePhase, str], None] | None = None,
		on_plan_ready: Callable[[object, DomainContext | None], PlanApproval] | None = None,
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
		"""Caminho 3 (staged removido): o fluxo de MODIFICAR addon tambem e 100%
		AGENTICO. Sem staged: se o agente nao produzir, erro honesto."""
		if self._run_pipeline_agentic(user_query):
			return
		result = OrchestrationResult(
			plan_id="agentic", query=user_query, step_results=[],
			final_output="", success=False,
			error="O agente nao conseguiu gerar o addon.",
		)
		self._last_result = result
		if self._on_complete and not self._suppress_complete_callback:
			self._on_complete(result)

	def _emit(self, event: str, detail: str):
		_logger.info("[PROGRESS] %s: %s", event, detail)
		if self._on_progress:
			self._on_progress(event, detail)

	# ------------------------------------------------------------------
	# Pipeline principal
	# ------------------------------------------------------------------

	def _run_pipeline_agentic(self, user_query: str) -> bool:
		"""Caminho 3 (UNICO caminho, pos-demolicao do staged): gera o addon pelo
		driver AGENTICO (o backend dirige editar->rodar->corrigir).

		Retorna True se ENTREGOU (disparou on_complete), False se nao produziu nada
		-- sem fallback staged (nao existe mais); False vira erro honesto no
		chamador. O gate deterministico (code_sandbox + acessibilidade) e a
		auto-correcao vivem DENTRO de run_agentic_build; aqui o resultado vira o
		formato de blocos que a GUI ja empacota -- mesma entrega + portao final.

		O progresso do agente e transmitido AO VIVO: cada linha relevante da saida
		do motor vira um evento EXECUTANDO, para o usuario nao ficar minutos no
		silencio durante uma geracao complexa (aproxima a UX das ferramentas de ponta).
		"""
		self._running = True
		self._last_result = None
		try:
			from ..builder.agentic_driver import run_agentic_build
		except Exception as exc:  # pragma: no cover - defesa
			_logger.error("[AGENTIC] driver indisponivel: %s", exc)
			return False

		self._emit("PLANEJANDO", "")
		self._emit("EXECUTANDO", "code_generation")

		# Direcao ao vivo: zera o sinal de cancelamento e qualquer ajuste antigo
		# antes de comecar (uma execucao nao herda o estado da anterior).
		self._agentic_cancel.clear()
		self._drenar_steer()

		def _ao_vivo(linha: str) -> None:
			# Progresso do motor agentico em tempo real -- best-effort.
			self._emit("EXECUTANDO", linha)

		try:
			build = run_agentic_build(
				user_query,
				correction_rounds=_AGENTIC_CORRECTION_ROUNDS,
				use_nvda_context=True,
				progress_callback=_ao_vivo,
				cancel_event=self._agentic_cancel,
				steer_provider=self._drenar_steer,
			)
		except Exception as exc:  # pragma: no cover - defesa
			_logger.error("[AGENTIC] falha inesperada: %s", exc)
			return False

		if getattr(build, "cancelled", False):
			# O usuario INTERROMPEU -- nao e falha; erro honesto e claro.
			_logger.info("[AGENTIC] build interrompida pelo usuario.")
			self._emit("CANCELADO", "")
			result = OrchestrationResult(
				plan_id="agentic", query=user_query, step_results=[],
				final_output="", success=False,
				error="Geracao interrompida pelo usuario.",
			)
			self._last_result = result
			if self._on_complete and not self._suppress_complete_callback:
				self._on_complete(result)
			return True

		if not build.files:
			_logger.warning("[AGENTIC] nenhum arquivo produzido -- erro honesto.")
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
			total_tokens=getattr(build, "tokens", 0),
		)
		self._emit("MONTANDO", "")
		self._emit("CONCLUIDO", "")
		self._last_result = orch_result
		if self._on_complete and not self._suppress_complete_callback:
			self._on_complete(orch_result)
		return True

	def _run_pipeline(self, user_query):
		"""Caminho 3 (staged removido): a geracao e 100% AGENTICA. Os antigos
		`resume_plan`/`resume_completed` (retomada/replan do FSM staged) saíram da
		assinatura com a demolicao -- nenhum chamador os passava. Sem fallback
		staged: se o agente nao produzir nada, erro honesto."""
		if self._run_pipeline_agentic(user_query):
			return
		result = OrchestrationResult(
			plan_id="agentic", query=user_query, step_results=[],
			final_output="", success=False,
			error="O agente nao conseguiu gerar o addon.",
		)
		self._last_result = result
		if self._on_complete and not self._suppress_complete_callback:
			self._on_complete(result)

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




	# ------------------------------------------------------------------
	# Execucao paralela
	# ------------------------------------------------------------------




	# ------------------------------------------------------------------
	# Execucao de step com critica, retry e escalacao
	# ------------------------------------------------------------------



	# ------------------------------------------------------------------
	# Helpers
	# ------------------------------------------------------------------





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



	# Step types cujos outputs vao para final_output (fonte para extracao de blocos)
	_CODE_OUTPUT_STEP_TYPES: frozenset = frozenset({
		"code_generation", "manifest_builder", "documentation",
		"agent_runner", "agent_template", "assembly",
		"syntax_validation",  # relatorio de validacao vai para o assembler como contexto
	})

	@staticmethod

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
