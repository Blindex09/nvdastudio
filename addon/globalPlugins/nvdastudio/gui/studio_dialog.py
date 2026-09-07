import datetime
import json
import os
import queue
import re
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
	from ..core.orch_types import OrchestrationResult

import wx
import gui
import ui

# Modulos NVDA opcionais (nao disponiveis fora do ambiente NVDA — testes)
try:
	import config as _nvda_config  # type: ignore[import]
except ImportError:
	_nvda_config = None  # type: ignore[assignment]

try:
	import languageHandler as _language_handler  # type: ignore[import]
except ImportError:
	_language_handler = None  # type: ignore[assignment]

from ..memory.conversation_manager import conversation
from ..core.checkpoint_manager import CheckpointAction, InteractiveCheckpoint
from ..memory.narration import narrate
from ..sub_agents.web_researcher import _USER_SOURCES_HEADER
from ..builder.addon_builder import (
	extract_code_blocks, save_addon_files, package_addon, AddonBuilderError,
	bundle_addon_dependencies,
	validate_addon_structure, fix_addon_structure,
	name_from_manifest_blocks,
)
from .settings_panel import get_output_dir
from ..ai.clarifier import analyze_query, build_enriched_query
from ..ai.llm_factory import create_llm_client, call_with_structured_output
from ..builder.addon_loader import (
	AddonContext, load_addon_from_blocks, load_addon_from_folder, load_addon_from_nvda_addon,
)
from ..builder.trajectory_compressor import compressor as trajectory_compressor
from ..memory.session_memory import memory
from ..builder.nvda_context import PROMPT_VERSION, NVDA_ADDON_CHAT_SYSTEM_LITE as NVDA_ADDON_CHAT_SYSTEM
from ..utils.logger import get_logger, log_decision
from ..utils.user_visible_text import sanitize_user_visible_text
from ..core.orch_types import (
	PipelinePhase, PlanApproval, CheckpointResult,
)
from ..core.planner import (
	ExecutionPlan, STEP_TEST_GENERATION,
	STEP_ACCESSIBILITY_AUDIT, STEP_DESIGN_REVIEW, STEP_ENGINEERING_REVIEW,
)

MODULE_VERSION = "5.51.0"

# Janela curta (nao unicidade global): uma frase legitima pode reaparecer
# muito depois numa sessao longa -- so o eco PROXIMO, das retentativas de um
# mesmo step, e ruido a descartar.
_JANELA_NARRACAO = 8


def _narracao_e_eco(message: str, janela: deque[str]) -> bool:
	"""True se `message` (normalizado: espacos colapsados, casefold) ja aparece
	na janela recente de narracoes -- eco a descartar. Se NAO for eco, registra
	a chave na janela e devolve False (pode exibir). Helper puro para permitir
	teste sem instanciar o dialogo (a classe herda de wx.Dialog, mockado na
	suite)."""
	chave = " ".join(message.split()).casefold()
	if chave in janela:
		return True
	janela.append(chave)
	return False
_logger = get_logger("studio_dialog")



def _collect_web_sources(step_results) -> str:
	"""
	Extrai so a secao "Fontes consultadas:" dos steps web_research, sem
	mostrar o resto do relatorio tecnico (que continua interno de proposito
	-- ver comentario em _display_result). web_researcher.py 4.2.0 ja anexa
	essa secao ao proprio output do step quando a busca encontrou URLs.
	"""
	blocks = []
	for r in step_results:
		if r.step_type != "web_research" or not r.output:
			continue
		idx = r.output.find(_USER_SOURCES_HEADER)
		if idx == -1:
			continue
		blocks.append(r.output[idx:].strip())
	return "\n\n".join(blocks)


def _collect_followup_suggestions(step_results) -> str:
	"""
	Sugestao curta de proximo passo, deterministica (nao e a IA inventando
	prosa generica) -- olha o que o plano JA sabia que podia incluir e
	NAO incluiu. test_generation e o unico step verdadeiramente opcional
	do pipeline (planner.py nao o injeta automaticamente como faz com
	documentation/assembly/syntax_validation/accessibility_audit -- fica a
	criterio do LLM do planner incluir ou nao). Se nao rodou, e uma
	sugestao concreta e grounded, nao um palpite.
	"""
	if not step_results:
		return ""  # nada foi construido ainda -- nao ha base pra sugerir proximo passo
	tipos_presentes = {r.step_type for r in step_results}
	if STEP_TEST_GENERATION not in tipos_presentes:
		return "Quer que eu gere testes automatizados para esse addon tambem?"
	return ""


# Steps de auditoria/qualidade de DOMINIO: sao _NON_BLOCKING_STEP_TYPES (a
# falha nao impede a entrega -- degradacao graciosa, doc secao 9), mas para um
# gerador de addon de LEITOR DE TELA a auditoria de acessibilidade e o eval de
# dominio mais critico (doc secao 22, "Accessibility/Domain Evals"). Entregar
# com success=True e CALAR que ela nao rodou mascara o agente nao ter rodado de
# verdade -- exatamente o que o E2E real via Factory expos (accessibility_audit,
# engineering_review falharam por o provedor nao ter tool use, e o usuario nao
# era avisado). A entrega continua (nao vira gate bloqueante), mas passa a ser
# HONESTA: checkpoint informacional (doc secao 8) nomeando a checagem que faltou.
_QUALITY_AUDIT_STEP_NAMES = {
	STEP_ACCESSIBILITY_AUDIT: "auditoria de acessibilidade",
	STEP_DESIGN_REVIEW: "revisão de design",
	STEP_ENGINEERING_REVIEW: "revisão de engenharia",
}


def _collect_quality_gaps(step_results) -> str:
	"""Aviso honesto quando um step de auditoria/qualidade de dominio foi
	TENTADO (esta em step_results) e NAO passou (approved=False).

	Deterministico -- olha o resultado real de cada step, nao a IA inventando.
	So avisa sobre o que o plano tentou e falhou; um step que o planner nem
	incluiu nao vira aviso (nao foi prometido). Nao bloqueia a entrega -- apenas
	a torna honesta sobre a checagem que ficou de fora.
	"""
	if not step_results:
		return ""
	faltantes = []
	for r in step_results:
		if r.step_type in _QUALITY_AUDIT_STEP_NAMES and not r.approved:
			nome = _QUALITY_AUDIT_STEP_NAMES[r.step_type]
			motivo = ""
			if getattr(r, "issues", None):
				motivo = str(r.issues[0]).strip().replace("\n", " ")
				if len(motivo) > 140:
					motivo = motivo[:137] + "..."
			faltantes.append((nome, motivo))
	if not faltantes:
		return ""
	linhas = [
		f"  - {nome}" + (f": {motivo}" if motivo else "")
		for nome, motivo in faltantes
	]
	plural = "verificações" if len(faltantes) > 1 else "verificação"
	return (
		f"⚠️ Atenção: {len(faltantes)} {plural} de qualidade não pôde ser "
		f"concluída, e o addon foi entregue SEM ela:\n"
		+ "\n".join(linhas)
		+ "\nA entrega não foi bloqueada, mas essa checagem não foi feita neste addon."
	)


def _is_path_within(base_path: str, candidate_path: str) -> bool:
	"""True se candidate estiver dentro de base, sem falhar entre unidades."""
	base = os.path.abspath(base_path)
	candidate = os.path.abspath(candidate_path)
	try:
		return os.path.commonpath((base, candidate)) == base
	except ValueError:
		return False


def _get_nvda_addons_dir() -> str:
	"""Retorna a pasta de addons do NVDA. Suporta instalacoes portables via config.getUserDataPath()."""
	if _nvda_config is not None:
		try:
			return os.path.join(_nvda_config.getUserDataPath(), "addons")
		except Exception as exc:
			_logger.debug("[DEBUG] getUserDataPath indisponivel: %s", exc)
	return os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "nvda", "addons")
# v3.8.0: CORRIGINDO, AVALIANDO, REPLANEJANDO, ESCALANDO, PARALELO agora tem mensagens
# concretas no orchestrator e sao anunciaveis — usuario cego ouve tudo que acontece.
_ANNOUNCE_EVENTS = {
	"PLANEJANDO", "PLANO_CRIADO", "EXECUTANDO",
	"CORRIGINDO", "AVALIANDO", "REPLANEJANDO", "ESCALANDO", "PARALELO",
	"AGUARDANDO_USUARIO",
	"MONTANDO", "CONCLUIDO", "ERRO",
}

# NVDA_ADDON_CHAT_SYSTEM: base de conhecimento completa (importada de nvda_context)

_CHAT_RESPONSE_SCHEMA = {
	"type": "json_schema",
	"json_schema": {
		"name": "nvda_studio_chat_turn",
		"strict": True,
		"schema": {
			"type": "object",
			"properties": {
				"action": {
					"type": "string",
					"enum": ["reply", "clarify", "run_pipeline"],
				},
				"message": {"type": "string"},
				"task_specification": {"type": "string"},
			},
			"required": ["action", "message", "task_specification"],
			"additionalProperties": False,
		},
	},
}

_ANNOUNCE_TIMER_MS = 600


# ---------------------------------------------------------------------------
# v2.0.0: PlanApprovalDialog removido. Aprovacao inline no chat.
# v5.28.0: os 2 dialogos modais de checkpoint tambem removidos, mesmo padrao
#   inline (_ask_checkpoint_inline).
# v5.29.0: PostGenerationDialog, _DiscardConfirmDialog, ClarificationDialog e
#   NVDAStudioStatsDialog tambem removidos (o primeiro par ja estava orfao;
#   ClarificationDialog virou _ask_clarification_inline; stats virou texto
#   direto no historico via _on_show_stats). Uma janela so: NVDAStudioDialog.
# ---------------------------------------------------------------------------


class NVDAStudioDialog(wx.Dialog):
	"""
	Dialog principal do NVDAStudio.
	Abertura: NVDA+Shift+N (configurado no GlobalPlugin).

	O usuario descreve o que quer em linguagem natural.
	O Orchestrator decide autonomamente: agentes, modelos, retries, correcoes.
	O usuario nao escolhe nada disso (Invariante 1).
	"""

	def __init__(self, parent):
		super().__init__(
			parent,
			title="NVDAStudio - Criador Autonomo de Addons NVDA com IA",
			style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
		)
		from ..core.orchestrator import Orchestrator
		self._orchestrator = Orchestrator()
		self._last_result: OrchestrationResult | None = None
		self._deps_ja_tratadas = False
		self._current_phase: PipelinePhase | None = None
		self._last_blocks: list[dict] = []
		self._last_addon_folder: str = ""
		self._current_addon_name: str = ""
		self._last_query: str = ""  # fluxos 14.2 R:c: armazenado para retry em caso de falha
		self._session_count = memory.get_session_count()
		# Modo conversacional/iterativo
		self._loaded_addon_context: AddonContext | None = None
		self._chat_history: list[dict] = []   # [{"role": "user"|"assistant", "text": str}]
		self._waiting_for_plan_approval = False
		self._waiting_for_packaging_approval = False
		self._pending_redirect_query = None  # interrupcao ativa: nova instrucao enquanto roda
		self._plan_approval_event = threading.Event()
		self._plan_approval_result = None
		self._raw_plan_approval_input = None
		self._waiting_for_clarification = False
		self._clarification_event = threading.Event()
		self._raw_clarification_input = None
		self._tool_approval_event = threading.Event()
		self._tool_approval_result = False

		self._announce_queue: queue.Queue = queue.Queue()
		self._announce_timer = wx.Timer(self)
		self.Bind(wx.EVT_TIMER, self._process_announce, self._announce_timer)
		self._announce_timer.Start(_ANNOUNCE_TIMER_MS)
		self.Bind(wx.EVT_CLOSE, self._on_close)

		self._build_ui()
		self._init_orchestrator()
		self._restore_preferences()

		self.SetSize((960, 660))
		self.Centre()
		self._input.SetFocus()

		global _current_dialog
		_current_dialog = self

	def approve_tool(self, tool_name: str, arguments: dict, reason: str = "") -> bool:
		"""
		Gate de aprovacao humana para tools de alto risco (escrita/execucao).

		Chamado do worker thread do orchestrator -- bloqueia ate o usuario
		confirmar ou negar via wx.MessageDialog na thread principal.
		Fail-closed: qualquer excecao ou falta de resposta clara nega a tool.

		reason: motivo especifico do ApprovalWorkflow.analyze_risk() (ex:
		"Padrao perigoso detectado nos argumentos") -- mostrado ao usuario pra
		ele decidir com contexto real, nao so o nome generico da tool.
		"""
		self._tool_approval_event.clear()
		self._tool_approval_result = False

		def _ask():
			preview = ", ".join(f"{k}={v!r}" for k, v in list(arguments.items())[:3])
			motivo = f"\nMotivo: {reason}" if reason else ""
			message = (
				f"O NVDAStudio quer executar a ferramenta \"{tool_name}\" "
				f"({preview}).{motivo}\nPermitir?"
			)
			try:
				dlg = wx.MessageDialog(
					self, message, "Aprovacao necessaria",
					wx.YES_NO | wx.ICON_WARNING,
				)
				result = dlg.ShowModal()
				dlg.Destroy()
				self._tool_approval_result = (result == wx.ID_YES)
			finally:
				self._tool_approval_event.set()

		wx.CallAfter(_ask)
		self._tool_approval_event.wait()
		return self._tool_approval_result

	# ------------------------------------------------------------------
	# Inicializacao
	# ------------------------------------------------------------------

	def _get_quick_chat_model(self) -> str:
		"""Retorna o modelo adequado para tarefas rápidas do chat."""
		from .settings_panel import get_llm_provider, get_llm_model
		from ..ai.model_registry import resolve_provider_tier_model
		provider = get_llm_provider()
		model = get_llm_model()
		return resolve_provider_tier_model(provider, "light", model)

	def _init_orchestrator(self):
		try:
			self._orchestrator.initialize()
			self._orchestrator.set_callbacks(
				on_progress=self._on_progress,
				on_complete=self._on_complete,
				on_clarify=self._on_clarify_needed,
			)
			_logger.info("[OK] Orchestrator inicializado no dialog.")
		except Exception as exc:
			wx.CallAfter(self._show_error, str(exc))

	def _restore_preferences(self):
		count = self._session_count
		if count > 0:
			_msg = f"Bem-vindo de volta. {count} addon(s) criado(s) anteriormente."
			self._set_status(_msg)
			ui.message(f"NVDAStudio: {_msg}")

	# ------------------------------------------------------------------
	# Construcao da UI
	# ------------------------------------------------------------------

	def _build_ui(self):
		outer = wx.BoxSizer(wx.VERTICAL)
		# UI unificada (v5.0.0): sem notebook, painel unico com splitter horizontal.
		# Esquerdo: criacao + conversar. Direito: codigo gerado.
		splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
		left  = self._build_left_panel(splitter)
		right = self._build_right_panel(splitter)
		splitter.SplitVertically(left, right, sashPosition=420)
		outer.Add(splitter, proportion=1, flag=wx.EXPAND | wx.ALL, border=6)
		self._status = wx.StaticText(self, label="Pronto. Descreva o addon que deseja criar.")
		outer.Add(self._status, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=6)
		self.SetSizer(outer)

	def _build_left_panel(self, parent) -> wx.Panel:
		panel = wx.Panel(parent)
		sizer = wx.BoxSizer(wx.VERTICAL)
		self._input_label = wx.StaticText(panel, label="Descreva o addon que deseja criar ou modificar:")
		sizer.Add(self._input_label, flag=wx.LEFT | wx.TOP, border=6)
		self._input = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(-1, 100))
		self._input.SetName("Descreva o addon que deseja criar ou modificar:")
		self._input.SetHint(
			"Ex: Crie um addon que monitora o clipboard e anuncia mudancas pelo NVDA.\n"
			"Ex: Addon com agente IA que responde perguntas sobre o texto em foco."
		)
		self._input.Bind(wx.EVT_KEY_DOWN, self._on_input_key)
		sizer.Add(self._input, flag=wx.EXPAND | wx.ALL, border=6)
		self._btn_run = wx.Button(panel, label="&Criar Addon")
		self._btn_run.Bind(wx.EVT_BUTTON, self._on_run)
		sizer.Add(self._btn_run, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=6)
		self._log_label = wx.StaticText(panel, label="Histórico:")
		sizer.Add(self._log_label, flag=wx.LEFT, border=6)
		self._log = wx.TextCtrl(
			panel,
			style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.HSCROLL,
		)
		self._log.SetName("Histórico:")
		self._log.SetFont(wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
		sizer.Add(self._log, proportion=1, flag=wx.EXPAND | wx.ALL, border=6)
		row_buttons = wx.BoxSizer(wx.HORIZONTAL)
		self._btn_reset = wx.Button(panel, label="&Nova Sessao")
		self._btn_reset.Bind(wx.EVT_BUTTON, self._on_reset)
		row_buttons.Add(self._btn_reset, flag=wx.RIGHT, border=6)
		self._btn_stats = wx.Button(panel, label="Estatísticas de &IA")
		self._btn_stats.Bind(wx.EVT_BUTTON, self._on_show_stats)
		self._btn_stats.SetToolTip("Exibe estatísticas de desempenho e observabilidade dos agentes de IA")
		row_buttons.Add(self._btn_stats)
		sizer.Add(row_buttons, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=6)

		# --- Secao: Carregar Addon existente (v5.0.0) ----------------------------
		sizer.Add(wx.StaticLine(panel), flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, border=6)
		sizer.Add(
			wx.StaticText(panel, label="Addon carregado para modificação:"),
			flag=wx.LEFT | wx.TOP, border=6
		)
		row_addon = wx.BoxSizer(wx.HORIZONTAL)
		self._lbl_addon_loaded = wx.StaticText(
			panel, label="Nenhum addon carregado.")
		row_addon.Add(self._lbl_addon_loaded,
					  proportion=1, flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=6)
		btn_load_nvda = wx.Button(panel, label="Carregar &Addon (.nvda-addon)")
		btn_load_nvda.Bind(wx.EVT_BUTTON, self._on_load_addon_file)
		btn_load_nvda.SetToolTip("Carrega addon a partir de um arquivo .nvda-addon empacotado")
		row_addon.Add(btn_load_nvda, flag=wx.RIGHT, border=4)
		btn_load_folder = wx.Button(panel, label="Carregar &Pasta")
		btn_load_folder.Bind(wx.EVT_BUTTON, self._on_load_addon_folder)
		btn_load_folder.SetToolTip(
			"Carrega addon a partir de uma pasta (exclui lib/ e __pycache__ automaticamente)"
		)
		row_addon.Add(btn_load_folder, flag=wx.RIGHT, border=4)
		btn_load_last = wx.Button(panel, label="&Ultimo Gerado")
		btn_load_last.Bind(wx.EVT_BUTTON, self._on_load_last_addon)
		row_addon.Add(btn_load_last)
		sizer.Add(row_addon, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM, border=6)

		panel.SetSizer(sizer)
		return panel

	def _build_right_panel(self, parent) -> wx.Panel:
		panel = wx.Panel(parent)
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(
			wx.StaticText(panel, label="Codigo e artefatos gerados:"),
			flag=wx.LEFT | wx.TOP, border=6
		)
		self._code_view = wx.TextCtrl(
			panel,
			style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.HSCROLL,
		)
		self._code_view.SetFont(
			wx.Font(10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
		)
		sizer.Add(self._code_view, proportion=1, flag=wx.EXPAND | wx.ALL, border=6)
		action_row = wx.BoxSizer(wx.HORIZONTAL)
		self._btn_close = wx.Button(panel, wx.ID_CLOSE, label="&Fechar")
		self._btn_close.Bind(wx.EVT_BUTTON, lambda e: self.Close())
		action_row.Add(self._btn_close)
		sizer.Add(action_row, flag=wx.ALL, border=6)
		panel.SetSizer(sizer)
		return panel

	# ------------------------------------------------------------------
	# Handlers de eventos
	# ------------------------------------------------------------------

	def _on_input_key(self, event):
		"""Enter envia a mensagem; Shift+Enter insere uma nova linha."""
		key_code = event.GetKeyCode()
		if key_code == wx.WXK_RETURN:
			if event.ShiftDown():
				# Shift+Enter: insere nova linha (padrao do wx.TextCtrl)
				event.Skip()
			else:
				# Enter sozinho: envia a mensagem (dispara _on_run)
				# Impede que o enter seja inserido no campo de texto
				self._on_run(None)
		else:
			event.Skip()

	def _update_input_label(self, label_text):
		if hasattr(self, "_input_label"):
			self._input_label.SetLabel(label_text)
		if hasattr(self, "_input"):
			self._input.SetName(label_text)
		self.Layout()

	def _enable_run_btn(self):
		self._btn_run.SetLabel("&Criar Addon")
		self._btn_run.Enable()
		self._update_input_label("Descreva o addon que deseja criar ou modificar:")

	def _run_pending_redirect(self):
		"""Se o usuario redirecionou a IA enquanto ela processava (interrupcao ativa),
		dispara a nova instrucao assim que o cancelamento terminar."""
		redirect_query = getattr(self, "_pending_redirect_query", None)
		if not redirect_query:
			return
		self._pending_redirect_query = None
		self._input.SetValue(redirect_query)
		wx.CallAfter(self._on_run, None)

	def _disable_run_btn_as_cancel(self):
		self._btn_run.SetLabel("&Parar")
		self._btn_run.Enable()
		self._update_input_label("Progresso:")

	def _on_run(self, _event):
		"""Botao Criar Addon ou Parar: pipeline conversacional v2.0.0."""
		if self._btn_run.GetLabel() in ("Parar", "&Parar", "Cancelar", "&Cancelar"):
			redirect_query = self._input.GetValue().strip()
			if redirect_query:
				# Interrupcao ativa: usuario digitou algo novo enquanto a IA processava.
				# Cancela o trabalho atual e redireciona para a nova instrucao com seguranca.
				self._input.SetValue("")
				self._pending_redirect_query = redirect_query
				self._chat_append(f"Você:\n{redirect_query}")
				self._chat_append("Sistema:\nRedirecionando para a nova instrução.")
				ui.message("Redirecionando para a nova instrução.")
				self._btn_run.SetLabel("Redirecionando...")
			else:
				self._chat_append("Sistema:\nParada solicitada pelo usuário.")
				ui.message("Parada solicitada.")
				self._btn_run.SetLabel("Parando...")
			self._orchestrator.cancel_pipeline()
			self._btn_run.Disable()
			return

		query = self._input.GetValue().strip()
		if not query:
			ui.message("Por favor, descreva o addon que deseja criar ou modificar.")
			return

		# Limpar o campo de texto
		self._input.SetValue("")
		from ..utils.smart_retry import smart_retry
		smart_retry.reset()

		if self._waiting_for_packaging_approval:
			self._waiting_for_packaging_approval = False
			self._chat_append(f"Você:\n{query}")
			self._set_status("Processando resposta.")
			narrate("interpretando a resposta sobre empacotar ou ajustar mais alguma coisa")
			self._btn_run.Disable()
			self._btn_run.SetLabel("Processando...")
			self._input.Disable()
			self._update_input_label("Progresso:")
			thread = threading.Thread(
				target=self._process_packaging_decision,
				args=(query,), daemon=True
			)
			thread.start()
			return

		if self._waiting_for_plan_approval:
			self._raw_plan_approval_input = query
			self._chat_append(f"Você:\n{query}")
			self._set_status("Processando resposta.")
			narrate("interpretando a resposta sobre o plano de desenvolvimento")
			self._btn_run.Disable()
			self._btn_run.SetLabel("Processando...")
			self._input.Disable()
			self._update_input_label("Progresso:")
			self._plan_approval_event.set()
			return

		if self._waiting_for_clarification:
			self._raw_clarification_input = query
			self._chat_append(f"Você:\n{query}")
			self._set_status("Processando resposta.")
			narrate("interpretando as respostas do usuário sobre o pedido")
			self._btn_run.Disable()
			self._btn_run.SetLabel("Processando...")
			self._input.Disable()
			self._update_input_label("Progresso:")
			self._clarification_event.set()
			return

		# O nome real vem semanticamente do Planner e e aplicado no callback do
		# plano. Nao inventar nome a partir das primeiras palavras da solicitacao.
		self._current_addon_name = "addon_gerado"

		# Oferecer recuperacao de chat anterior se for nova sessao
		if not self._chat_history and not self._loaded_addon_context:
			self._offer_chat_restore(self._current_addon_name)

		self._chat_append(f"Você:\n{query}")
		self._chat_history.append({"role": "user", "text": query})
		ui.message(f"Mensagem enviada: {query[:80]}")
		self._disable_run_btn_as_cancel()
		self._set_status("Iniciando processamento da mensagem...")
		thread = threading.Thread(
			target=self._process_chat_message,
			args=(query,), daemon=True
		)
		thread.start()

	def _setup_conversational_callbacks(self):
		"""Configura os callbacks do pipeline conversacional v2.0.0."""
		self._orchestrator.set_conversational_callbacks(
			on_phase_change=self._on_conversational_phase,
			on_plan_ready=self._on_conversational_plan_ready,
			on_checkpoint=self._on_conversational_checkpoint,
		)
		# Configura callbacks do conversation_manager (Hermes-style UX)
		conversation.set_callbacks(
			on_status=lambda msg: wx.CallAfter(self._handle_status, msg),
			on_tool_progress=lambda msg, elapsed: wx.CallAfter(self._handle_tool_progress, msg, elapsed),
			on_content=lambda msg: wx.CallAfter(self._handle_content, msg),
		)

		# Configura callback do checkpoint_manager v2 (interativo com 3 opcoes)
		from ..core.checkpoint_manager import checkpoint_manager
		checkpoint_manager.set_callbacks(
			on_checkpoint=self._on_checkpoint_interactive,
			on_status=lambda msg: wx.CallAfter(self._handle_status, msg),
		)

		# Configura callbacks do tool_gateway (v2.2.0)
		from ..tools.tool_gateway import tool_gateway
		tool_gateway.register_builtin_tools()
		tool_gateway.set_callbacks(
			on_tool_start=lambda _name: wx.CallAfter(self._set_status, "Trabalhando."),
			on_tool_end=lambda name, success: wx.CallAfter(
				self._set_status,
				"Operacao concluida." if success else "Uma operacao nao foi concluida.",
			),
			on_approval_request=self._orchestrator._tool_approval_callback,
		)

	def _report_checkpoint_inline(self, summary: str, details: list[str] | None) -> None:
		"""
		Informa um checkpoint no historico sem parar o pipeline. Pedido
		explicito de Felipe: o pipeline nao deve parar e perguntar apos cada
		etapa -- a IA decide sozinha e continua, so avisando o que aconteceu.
		Chamado de thread daemon; a UI e atualizada via wx.CallAfter.
		"""
		msg_lines = [summary]
		if details:
			msg_lines.append("")
			msg_lines.append("Detalhes:")
			for d in details[:5]:
				msg_lines.append(f"  - {d}")
		message = "\n".join(msg_lines)
		wx.CallAfter(self._chat_append, f"Assistente:\n{message}")

	def _on_checkpoint_interactive(self, ic: InteractiveCheckpoint) -> CheckpointAction:
		"""
		Checkpoint automatico: nao pausa nem pergunta -- so informa no
		historico e segue em frente. Pedido explicito de Felipe: o pipeline
		nao deve parar apos cada etapa, a IA decide sozinha e continua.
		"""
		self._report_checkpoint_inline(ic.summary, ic.details)
		return CheckpointAction.CONTINUE

	def _on_conversational_phase(self, phase: PipelinePhase, detail: str):
		"""Callback de mudanca de fase do pipeline conversacional."""
		wx.CallAfter(self._handle_conversational_phase, phase, detail)

	def _handle_conversational_phase(self, phase: PipelinePhase, detail: str):
		"""Processa mudanca de fase na thread UI."""
		phase_labels = {
			PipelinePhase.CONVERSATION: "Conversando",
			PipelinePhase.RESEARCH: "Pesquisando",
			PipelinePhase.PLANNING: "Planejando",
			PipelinePhase.PLAN_APPROVAL: "Plano para Aprovação",
			PipelinePhase.EXECUTING: "Implementando",
			PipelinePhase.REVIEW: "Revisando",
			PipelinePhase.DONE: "Concluído",
		}
		label = phase_labels.get(phase, phase.name)

		if phase == PipelinePhase.CONVERSATION:
			return

		if self._current_phase != phase:
			self._current_phase = phase

		# Pesquisa produz contexto tecnico para os agentes. Mesmo que algum chamador
		# envie detalhes por engano, eles nunca pertencem ao historico conversacional.
		if phase == PipelinePhase.RESEARCH:
			self._set_status(label)
			return
		# A mensagem final completa e acrescentada por _display_result, junto com os
		# arquivos realmente validados. Nao repetir aqui o texto otimista do plano.
		if phase == PipelinePhase.DONE:
			self._set_status("Concluído")
			self._enable_run_btn()
			self._run_pending_redirect()
			return

		if detail and detail.strip() and detail != "...":
			self._chat_append(detail)

		if phase == PipelinePhase.PLAN_APPROVAL:
			# O plano ja foi acrescentado uma vez ao historico acima. Atualizar apenas
			# a visualizacao auxiliar; SetValue no log apagava a conversa anterior.
			clean_detail = self._clean_text(detail)
			self._code_view.SetValue(clean_detail)
			self._set_status("Revise o plano e responda com suas próprias palavras.")
		elif phase == PipelinePhase.EXECUTING:
			self._set_status(f"{label}: {detail}")
		else:
			self._set_status(f"{label}: {detail}")

	def _on_conversational_plan_ready(
		self, plan: ExecutionPlan, domain_ctx
	) -> PlanApproval:
		"""
		Callback: plano pronto para aprovacao.
		Chamado de thread daemon — envia o plano para a janela de conversa e aguarda resposta.
		"""
		plan_text = self._orchestrator._planner.format_plan_for_user(plan, domain_ctx)

		def _display():
			# A resposta do usuario aqui e classificada por IA de forma livre (ver
			# _process_plan_approval_response) -- nao ha palavras exatas obrigatorias.
			# O texto so precisa convidar a responder, sem sugerir uma lista fixa de
			# comandos (isso soava como um menu de keywords, nao uma conversa).
			self._current_addon_name = plan.addon_name
			self._waiting_for_plan_approval = True
			self._raw_plan_approval_input = None
			self._plan_approval_result = None
			self._plan_approval_event.clear()
			self._set_status("Aguardando aprovacao do plano...")
			self._input.Enable()
			self._btn_run.SetLabel("Enviar")
			self._btn_run.Enable()
			self._update_input_label("Digite sua resposta sobre o plano:")
			self._input.SetFocus()
			self._chat_append(f"Assistente:\n{plan_text}")
			ui.message("Plano de desenvolvimento pronto. Revise no histórico e responda com suas próprias palavras.")

		wx.CallAfter(_display)
		self._plan_approval_event.wait()
		self._waiting_for_plan_approval = False

		# Se cancelado ou sem input, retorna cancelado
		if getattr(self._orchestrator, "_cancel_requested", False) or not getattr(self, "_raw_plan_approval_input", None):
			self._plan_approval_result = PlanApproval(approved=False, modifications="cancelado")
			cancel_message = plan.cancellation_message.strip() or "A criação foi cancelada."
			def _cancel_ui():
				self._chat_append(f"Assistente:\n{cancel_message}")
				ui.message(cancel_message)
				self._enable_run_btn()
				self._input.Enable()
			wx.CallAfter(_cancel_ui)
			return self._plan_approval_result

		raw_query = self._raw_plan_approval_input.strip()
		intent = "modify"  # default fallback

		try:
			client = create_llm_client(model_id=self._get_quick_chat_model())
			system_prompt = (
				"Interprete semanticamente a resposta livre do usuário sobre o plano. "
				"Classifique como approve quando ele autoriza o desenvolvimento, cancel "
				"quando encerra a operação, ou modify quando pergunta, condiciona ou pede "
				"qualquer mudança. Não decida por palavras isoladas. Responda somente JSON "
				"com o campo intent."
			)
			user_msg = f"Resposta do usuário: \"{raw_query}\""
			resp = client.chat(
				user_message=user_msg,
				system_override=system_prompt,
				response_format={"type": "json_object"}
			)
			content = (resp.content or "").strip()
			data = json.loads(content)
			parsed_intent = data.get("intent", "modify")
			intent = parsed_intent if parsed_intent in {"approve", "cancel", "modify"} else "modify"
		except Exception as e:
			_logger.warning("[IntentClassifier] Falha na chamada da IA: %s", e)
			intent = "modify"

		if intent == "approve":
			self._plan_approval_result = PlanApproval(approved=True, modifications="")
			approval_message = plan.approval_message.strip() or "Entendido. Vou iniciar a criação."
			def _approve_ui():
				self._chat_append(f"Assistente:\n{approval_message}")
				ui.message(approval_message)
				self._disable_run_btn_as_cancel()
				self._input.Disable()
			wx.CallAfter(_approve_ui)
		elif intent == "cancel":
			self._plan_approval_result = PlanApproval(approved=False, modifications="cancelado")
			cancel_message = plan.cancellation_message.strip() or "A criação foi cancelada."
			def _cancel_ui():
				self._chat_append(f"Assistente:\n{cancel_message}")
				ui.message(cancel_message)
				self._enable_run_btn()
				self._input.Enable()
			wx.CallAfter(_cancel_ui)
		else:
			self._plan_approval_result = PlanApproval(approved=False, modifications=raw_query)
			modification_message = plan.modification_message.strip() or "Entendido. Vou ajustar o plano."
			def _modify_ui():
				self._chat_append(f"Assistente:\n{modification_message}")
				ui.message(modification_message)
				self._disable_run_btn_as_cancel()
				self._input.Disable()
			wx.CallAfter(_modify_ui)

		return self._plan_approval_result

	def _on_conversational_checkpoint(self, checkpoint: CheckpointResult) -> bool:
		"""
		Checkpoint automatico apos cada step importante: nao pausa nem
		pergunta -- so informa no historico e segue. Pedido explicito de
		Felipe: o pipeline nao deve parar, a IA decide sozinha e continua.
		"""
		self._report_checkpoint_inline(checkpoint.summary, None)
		return True

	def _ask_clarification_inline(self, questions: list[str], timeout: float | None = None) -> list[str]:
		"""
		Pergunta(s) de esclarecimento inline no chat -- sem dialogo modal. As
		perguntas em si vem da IA (clarifier.analyze_query); aqui apenas
		apresenta no historico, aguarda uma resposta livre do usuario e usa
		uma IA para extrair uma resposta por pergunta, sem exigir formato
		fixo (o usuario pode responder tudo numa frase so ou uma por linha).
		Chamado de thread daemon; a UI e atualizada via wx.CallAfter.
		"""
		def _display():
			perguntas_txt = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
			self._chat_append(f"Assistente:\n{perguntas_txt}")
			self._waiting_for_clarification = True
			self._raw_clarification_input = None
			self._clarification_event.clear()
			self._set_status("Aguardando suas respostas...")
			self._input.Enable()
			self._btn_run.SetLabel("Enviar")
			self._btn_run.Enable()
			self._update_input_label("Digite sua resposta:")
			self._input.SetFocus()
			self._speak_message(perguntas_txt)

		wx.CallAfter(_display)
		got_input = self._clarification_event.wait(timeout=timeout) if timeout is not None else self._clarification_event.wait()
		self._waiting_for_clarification = False

		empty_answers = ["" for _ in questions]
		if not got_input or not getattr(self, "_raw_clarification_input", None):
			def _timeout_ui():
				msg = "Sem resposta no momento -- vou continuar com o que já tenho."
				self._chat_append(f"Assistente:\n{msg}")
				self._speak_message(msg)
				self._enable_run_btn()
				self._input.Disable()
			wx.CallAfter(_timeout_ui)
			return empty_answers

		raw_reply = self._raw_clarification_input.strip()
		answers = list(empty_answers)
		try:
			client = create_llm_client(model_id=self._get_quick_chat_model())
			system_prompt = (
				"Extraia, da resposta livre do usuario, uma resposta para cada "
				"pergunta numerada, na mesma ordem. Se ele nao respondeu uma "
				"pergunta especifica, deixe a resposta como string vazia naquele "
				"indice. Responda somente JSON com o campo answers (lista de "
				"strings, mesmo tamanho e ordem das perguntas)."
			)
			perguntas_txt = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
			user_msg = f"Perguntas:\n{perguntas_txt}\n\nResposta do usuário: \"{raw_reply}\""
			resp = client.chat(
				user_message=user_msg,
				system_override=system_prompt,
				response_format={"type": "json_object"},
			)
			content = (resp.content or "").strip()
			data = json.loads(content)
			parsed = data.get("answers", [])
			if isinstance(parsed, list):
				for i in range(min(len(parsed), len(answers))):
					answers[i] = str(parsed[i] or "")
		except Exception as e:
			_logger.warning("[ClarificationAnswerExtractor] Falha na chamada da IA: %s", e)
			# Fallback: usa a resposta inteira como resposta da primeira pergunta.
			if answers:
				answers[0] = raw_reply

		def _after():
			self._enable_run_btn()
			self._input.Disable()
		wx.CallAfter(_after)

		return answers

	# ------------------------------------------------------------------
	# Hermes-style conversation callbacks (novo fluxo v2.1.0)
	# ------------------------------------------------------------------

	def _handle_status(self, message: str):
		"""
		Status curto da IA: vai para o historico (self._log, navegavel com as
		setas). Nao e falado automaticamente -- o usuario navega o historico
		quando quiser, o NVDA nao narra sozinho.

		Achado de auditoria 2026-08-04: `_set_status()` e um no-op desde a
		v5.35.0 (SetLabel() dispara EVENT_OBJECT_NAMECHANGE, NVDA narra
		sozinho) -- a chamada continua aqui sem custo real, mas nao existe
		mais "barra de status" pra truncar por largura. `emit_status()`
		(conversation_manager.py) parou de cortar por contagem de
		caracteres pelo mesmo motivo: a mensagem completa agora chega
		integra no historico navegavel, sem mutilar palavra no meio.
		"""
		message = sanitize_user_visible_text(message)
		if not message:
			return
		# Dedup de narracao repetida (5.51.0): cada retentativa de um step
		# re-narra a MESMA frase ("Estou pensando na estrutura do addon...")
		# e todas eram emitidas, empilhando texto identico no historico. A
		# dedup de _chat_append() so olhava a linha fisica imediatamente
		# anterior e NUNCA casava pro formato multilinha "Assistente:\n{msg}"
		# (sanitize preserva o \n). _narracao_e_eco() guarda uma janela curta
		# das ultimas narracoes normalizadas e descarta a repeticao -- a
		# narracao volta a fluir sem eco.
		janela: deque[str] | None = getattr(self, "_status_recentes", None)
		if janela is None:
			janela = deque(maxlen=_JANELA_NARRACAO)
			self._status_recentes = janela
		if _narracao_e_eco(message, janela):
			return
		self._chat_append(f"Assistente:\n{message}")
		self._set_status(message)

	# Rotulos em linguagem natural para o heartbeat -- os nomes reais em
	# _current_tool sao step_type internos (code_generation, manifest_builder,
	# ...), nunca falados diretamente ao usuario (ver planner.py STEP_*).
	_TOOL_PROGRESS_LABELS = {
		"code_generation": "Gerando o código",
		"manifest_builder": "Montando o manifesto do addon",
		"accessibility_audit": "Auditando acessibilidade",
		"test_generation": "Gerando os testes",
		"web_research": "Pesquisando",
		"agent_template": "Criando o template do agente",
		"agent_runner": "Gerando o executor do agente",
		"assembly": "Montando os artefatos finais",
		"design_review": "Revisando o design",
		"documentation": "Escrevendo a documentação",
		"syntax_validation": "Validando a sintaxe",
	}

	def _handle_tool_progress(self, tool_name: str, elapsed_ms: int):
		"""
		Heartbeat de progresso durante steps longos (chamado a cada
		_HEARTBEAT_INTERVAL_SECONDS pelo orchestrator). So atualiza a barra de
		status -- efemero por natureza (varios ticks por step) e nao falado
		automaticamente nem gravado no historico; o que marca o step no
		historico e o status pre-execucao (_emit_conversation kind="status")
		e o conteudo final do step.
		"""
		label = self._TOOL_PROGRESS_LABELS.get(tool_name, "Trabalhando")
		if elapsed_ms > 0:
			elapsed_s = elapsed_ms // 1000
			text = f"{label}... {elapsed_s} segundos."
		else:
			text = f"{label}..."
		self._set_status(text)

	def _handle_content(self, message: str):
		"""Conteudo longo: vai para historico (log) e historico de chat (para o usuario ler)."""
		self._chat_append(f"Assistente:\n{message}")

	def _clarify_and_run(self, query: str):
		"""Roda o Clarifier e inicia o Orchestrator. Executado em thread daemon."""
		self._last_query = query  # fluxos 14.2 R:c: armazena para eventual retry
		try:
			clarification = analyze_query(query)

			# Q14.5: pedido recusado por violar regras de seguranca
			if clarification.forbidden:
				def _show_refusal():
					msg = clarification.refusal_reason or "Este tipo de addon nao pode ser criado pelo NVDAStudio."
					ui.message(f"NVDAStudio: {msg}")
					self._set_status("Pedido nao permitido.")
					self._enable_run_btn()
					gui.messageBox(msg, "NVDAStudio - Pedido Nao Permitido",
								   wx.OK | wx.ICON_WARNING, self)
				wx.CallAfter(_show_refusal)
				return

			# surgical_edit: edicao cirurgica — nao aciona pipeline, entrega instrucao direta
			if clarification.intent == "surgical_edit" and clarification.surgical_description:
				desc = clarification.surgical_description
				log_decision(_logger, "surgical_edit_chat",
							 f"descricao={desc[:80]}")
				def _show_surgical(d=desc):
					resposta = (
						"Essa e uma mudanca pequena e especifica. "
						"Aqui esta exatamente o que precisa ser alterado:\n\n"
						f"{d}\n\n"
						"Se quiser que eu regenere o addon completo com essa e outras "
						"correcoes, descreva o que mais precisa mudar."
					)
					self._append_chat("Assistente", resposta)
					ui.message("NVDAStudio: edicao identificada.")
					self._set_status("Pronto.")
					self._enable_run_btn()
				wx.CallAfter(_show_surgical)
				return

			if clarification.needs_clarification and clarification.questions:
				# Sem timeout: _ask_clarification_inline aguarda resposta explicita
				# no proprio chat (nao um dialogo modal). Timeout de 120s causava o
				# pipeline iniciar sem as respostas do usuario (confirmado no log:
				# 01:37:54 perguntas -> 01:39:54 pipeline).
				answers = self._ask_clarification_inline(clarification.questions)
				enriched = build_enriched_query(
					query, clarification.questions, answers,
					user_level=clarification.user_level
				)
			else:
				enriched = build_enriched_query(
					query, [], [],
					user_level=clarification.user_level
				)

			# Q13.3: injeta locale do NVDA para que doc_generator gere no idioma certo
			nvda_locale = _get_nvda_locale()
			enriched += f"\n\n[NVDA_LOCALE: {nvda_locale}]"

			wx.CallAfter(self._set_status, "Iniciando pipeline autonoma...")
			self._orchestrator.run_async(enriched)
		except Exception as exc:
			wx.CallAfter(self._show_error, str(exc))
			wx.CallAfter(self._enable_run_btn)

	# ------------------------------------------------------------------
	# Handlers do modo conversacional (Aba 2)
	# ------------------------------------------------------------------

	def _on_load_addon_file(self, _event):
		"""
		Carrega addon a partir de um arquivo .nvda-addon empacotado.

		Novo (v5.4.0): permite carregar addon ja empacotado para analise/iteracao
		no modo conversacional, sem precisar descompactar manualmente.
		Usa load_addon_from_nvda_addon() do addon_loader.
		"""
		dlg = wx.FileDialog(
			self,
			message="Selecione o arquivo .nvda-addon",
			defaultDir=get_output_dir(),
			wildcard="Addons NVDA (*.nvda-addon)|*.nvda-addon|Todos os arquivos (*.*)|*.*",
			style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
		)
		gui.mainFrame.prePopup()
		if dlg.ShowModal() == wx.ID_OK:
			nvda_addon_path = dlg.GetPath()
			dlg.Destroy()
			gui.mainFrame.postPopup()
			try:
				ctx = load_addon_from_nvda_addon(nvda_addon_path)
				self._load_addon_context(ctx)
			except Exception as exc:
				self._show_error(f"Nao foi possivel carregar o addon: {exc}")
		else:
			dlg.Destroy()
			gui.mainFrame.postPopup()

	def _on_load_addon_folder(self, _event):
		"""
		Carrega addon a partir de uma pasta no disco.

		skill: nvda-addon-dev — estrutura de pasta do addon.
		Usa DirDialog para o usuario selecionar a pasta raiz do addon
		(a que contem manifest.ini e globalPlugins/).
		Chama load_addon_from_folder() que ja exclui lib/ e __pycache__.

		Util para:
		- Addons instalados em AppData/Roaming/nvda/addons/<nome>
		- Addons gerados pelo NVDAStudio em addons_gerados/<nome>
		- Qualquer pasta de addon no disco sem precisar empacotar
		"""
		dlg = wx.DirDialog(
			self,
			message="Selecione a pasta raiz do addon (onde esta o manifest.ini)",
			defaultPath=os.path.join(
				os.environ.get("APPDATA", ""), "nvda", "addons"
			),
			style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
		)
		gui.mainFrame.prePopup()
		if dlg.ShowModal() == wx.ID_OK:
			folder_path = dlg.GetPath()
			dlg.Destroy()
			gui.mainFrame.postPopup()
			try:
				ctx = load_addon_from_folder(folder_path)
				self._load_addon_context(ctx)
			except Exception as exc:
				self._show_error(f"Nao foi possivel carregar a pasta: {exc}")
		else:
			dlg.Destroy()
			gui.mainFrame.postPopup()

	def _on_load_last_addon(self, _event):
		"""Carrega o ultimo addon gerado nesta sessao (se disponivel)."""
		if self._last_addon_folder and os.path.isdir(self._last_addon_folder):
			ctx = load_addon_from_folder(self._last_addon_folder)
			self._load_addon_context(ctx)
		elif self._last_result:
			ui.message("NVDAStudio: o ultimo resultado ainda nao foi salvo em pasta. "
					   "Use Salvar Arquivos na aba Criar primeiro.")
		else:
			ui.message("NVDAStudio: nenhum addon foi gerado ainda nesta sessao.")

	def _load_addon_context(self, ctx: AddonContext):
		"""Armazena contexto do addon carregado e anuncia ao usuario."""
		self._loaded_addon_context = ctx
		self._chat_history = []
		if ctx.load_errors:
			msg = f"Addon '{ctx.addon_name}' carregado com {len(ctx.load_errors)} aviso(s): {ctx.load_errors[0]}"
		else:
			msg = (f"Addon '{ctx.addon_name}' v{ctx.version} carregado. "
				   f"{len(ctx.python_files)} arquivo(s) Python. "
				   "Agora voce pode fazer perguntas ou pedir mudancas.")
		wx.CallAfter(self._lbl_addon_loaded.SetLabel,
					 f"Addon carregado: {ctx.addon_name} v{ctx.version}")
		wx.CallAfter(self._log.SetValue, "")
		self._chat_append(f"Sistema:\n{msg}")
		ui.message(f"NVDAStudio: {msg}")
		log_decision(_logger, "addon_carregado",
					 f"nome={ctx.addon_name} arquivos={len(ctx.python_files)}")



	def _process_chat_message(self, msg: str):
		"""
		Processa uma mensagem usando saida estruturada. A decisao semantica vem
		em ``action`` validado pelo schema; nenhum marcador ou palavra-chave e
		procurado dentro do texto livre.
		"""
		try:
			# Monta prompt com contexto do addon (se carregado)
			addon_ctx_text = ""
			if self._loaded_addon_context:
				addon_ctx_text = self._loaded_addon_context.to_prompt_context()

			compression_client = create_llm_client(model_id=self._get_quick_chat_model())
			trajectory = [
				{
					"role": "human" if h["role"] == "user" else "gpt",
					"content": h["text"],
				}
				for h in self._chat_history
			]
			compressed_history, metrics = trajectory_compressor.compress(trajectory, llm_client=compression_client)
			if metrics.was_compressed:
				_logger.info("[CHAT] historico comprimido: %d tokens economizados", metrics.tokens_saved)
			hist_text = "\n".join(
				f"{h['role'].upper()}: {h['content']}" for h in compressed_history
			)

			full_prompt = ""
			if addon_ctx_text:
				full_prompt += f"{addon_ctx_text}\n\n"
			if hist_text:
				full_prompt += f"Historico recente:\n{hist_text}\n\n"
			full_prompt += f"Mensagem atual do usuario: {msg}"

			# 2026-08-26: esta chamada exige JSON estrito (_CHAT_RESPONSE_SCHEMA,
			# a decisao semantica action/message/task_specification), mas usava
			# o tier light do provider ATIVO do usuario. No Ollama (default),
			# nenhum modelo da conta segue json_schema de verdade (auditoria ao
			# vivo, ver model_registry.py::get_structured_output_model()). A
			# compressao de historico acima nao exige schema -- continua no
			# client leve do provider ativo, sem mudanca.
			resp = call_with_structured_output(
				full_prompt,
				_CHAT_RESPONSE_SCHEMA,
				system_override=NVDA_ADDON_CHAT_SYSTEM,
			)
			payload = json.loads(resp.content or "")
			action = payload["action"]
			message = sanitize_user_visible_text(payload["message"])
			task_specification = str(payload["task_specification"] or "").strip()

			if not message:
				raise ValueError("A IA retornou uma mensagem vazia.")

			self._chat_history.append({"role": "assistant", "text": message})
			wx.CallAfter(self._chat_finish, f"Assistente:\n{message}")

			if action == "run_pipeline":
				if not task_specification:
					raise ValueError("A IA solicitou execução sem especificação técnica.")
				if self._loaded_addon_context:
					wx.CallAfter(self._trigger_iterative_pipeline, task_specification)
				else:
					wx.CallAfter(self._trigger_creation_pipeline, task_specification)

		except Exception as exc:
			_logger.error("[ERRO] chat: %s", exc)
			wx.CallAfter(
				self._chat_finish,
				"Assistente:\nNão consegui interpretar a resposta com segurança. Por favor, tente novamente.",
			)

	def _clean_text(self, text: str) -> str:
		"""Aplica o contrato unico de texto simples da interface."""
		return sanitize_user_visible_text(text)

	def _chat_finish(self, reply: str):
		"""Exibe resposta no historico e anuncia pelo NVDA. Thread UI.

		Achado de auditoria 2026-08-04 (analise de log real + pesquisa
		dedicada de UX acessivel): esta funcao tinha SUA PROPRIA logica de
		preservar/restaurar posicao (capturava start_pos antes de TODA a
		troca, restaurava depois) e ainda chamava SetFocus() no historico --
		roubando o foco de onde o usuario estava (ex: campo de digitacao)
		toda vez que uma resposta terminava. `_chat_append()` agora
		preserva a posicao de forma uniforme e correta pra QUALQUER
		chamada (nao so a resposta final), entao essa logica duplicada e o
		roubo de foco foram removidos daqui.
		"""
		self._chat_append(reply)
		self._enable_run_btn()
		self._input.Enable()
		if "?" in reply:
			self._update_input_label("Digite sua resposta:")
		self._speak_message(reply[:200])

	def _chat_append(self, line: str):
		"""Adiciona linha ao historico unificado com de-duplicacao de linhas.

		Achado de auditoria 2026-08-04: chamado direto (sem essa protecao)
		de 15+ pontos do pipeline pra status/progresso ao vivo -- so
		`_chat_finish()` (resposta final do turno) preservava a posicao do
		cursor antes, entao a view pulava pro fim a CADA atualizacao de
		status durante o pipeline, nao so na resposta final. Preserva a
		posicao de insercao do usuario aqui, de forma uniforme, sem nunca
		mover o foco (SetFocus() nunca e chamado numa atualizacao ao vivo --
		rouba o usuario de onde ele estava, ex: campo de digitacao). Thread UI.
		"""
		line = self._clean_text(line)
		if not hasattr(self, "_log"):
			return
		val = self._log.GetValue()
		lines = [existing.strip() for existing in val.split("\n") if existing.strip()]
		if lines and lines[-1] == line.strip():
			return
		pos = self._log.GetInsertionPoint()
		self._log.AppendText(line + "\n")
		self._log.SetInsertionPoint(pos)

	def _speak_message(self, text: str):
		"""Anuncia a mensagem via ui.message se for diferente da última e houver intervalo."""
		text = self._clean_text(text)
		text_clean = text.strip()
		if not text_clean:
			return

		# Evita duplicado idêntico
		if getattr(self, "_last_spoken_message", "") == text_clean:
			return

		current_time = time.time()
		last_time = getattr(self, "_last_spoken_time", 0.0)
		last_msg = getattr(self, "_last_spoken_message", "")

		# Se o intervalo for muito curto (menos de 1.2s):
		if current_time - last_time < 1.2:
			# Se a mensagem atual contém a última mensagem ou vice-versa, cancela a fala repetitiva
			if last_msg and (last_msg in text_clean or text_clean in last_msg):
				self._last_spoken_message = text_clean
				return

		self._last_spoken_message = text_clean
		self._last_spoken_time = current_time
		ui.message(text)

	def _trigger_iterative_pipeline(self, change_description: str):
		"""
		Dispara o pipeline de modificacao com contexto do addon injetado.
		O addon existente e passado como contexto para o Planner gerar
		apenas os steps necessarios para as mudancas pedidas.
		Thread UI — move para thread daemon internamente.
		"""
		addon_ctx_text = ""
		addon_name = "meuAddon"
		if self._loaded_addon_context:
			addon_ctx_text = self._loaded_addon_context.to_prompt_context()
			addon_name = self._loaded_addon_context.addon_name

		# 2026-08-09: memoria POR ADDON, consultada automaticamente -- nao um
		# dialogo perguntando se quer restaurar (isso ja existe em
		# _offer_chat_restore(), mas so roda ANTES do nome do addon ser
		# conhecido, entao na pratica nunca casa nada util). session_memory
		# ja guarda chat_snippets por addon_name desde save_chat_snippet()
		# (ver _on_reset) -- so nao era lido de volta no fluxo iterativo.
		# Silencioso e automatico, igual ao que o Felipe pediu ("aprendendo
		# automaticamente, sempre").
		past_chat_text = ""
		if addon_name and addon_name != "meuAddon":
			try:
				previous_chat = memory.get_last_chat(addon_name)
			except Exception as exc:
				_logger.warning("[WARN] get_last_chat(%s) falhou: %s", addon_name, exc)
				previous_chat = []
			if previous_chat:
				past_lines = "\n".join(
					f"{m.get('role', '?').upper()}: {m.get('text', '')[:300]}"
					for m in previous_chat
				)
				past_chat_text = (
					f"\n\nHistorico de uma conversa anterior sobre este mesmo addon "
					f"(pode ter decisoes/preferencias relevantes -- use como contexto, "
					f"nao repita literalmente):\n{past_lines}\n"
				)

		# 2026-08-09: antes, o plano de um pedido tipo "conserta esse bug"
		# saia identico ao de uma criacao nova (design_review, agent_template,
		# manifest_builder, documentation, assembly de novo do zero) porque
		# nada aqui instruia o Planner a manter o plano minimo -- so o rotulo
		# "MODO ITERATIVO" sem orientacao concreta sobre steps. Instrucao
		# explicita (nao deteccao por palavra-chave: e o proprio codigo desta
		# funcao que decide entrar aqui, via self._loaded_addon_context ja
		# setado -- ver _process_chat_message()) reduz desperdicio de tempo/
		# tokens pra correcoes pequenas, mantendo o Planner livre pra incluir
		# os steps extras quando o pedido realmente precisar deles.
		enriched_query = (
			f"MODO ITERATIVO — Modifique o addon existente conforme descrito abaixo.\n\n"
			f"{addon_ctx_text}"
			f"{past_chat_text}\n\n"
			f"Mudancas solicitadas pelo usuario: {change_description}\n\n"
			f"Gere o addon modificado com todas as mudancas aplicadas.\n\n"
			f"IMPORTANTE — plano minimo: este NAO e um addon novo, e uma correcao/"
			f"ajuste pontual num addon que ja existe (codigo-fonte acima). Gere "
			f"APENAS os steps realmente necessarios pra essa mudanca especifica -- "
			f"normalmente so code_generation. So inclua manifest_builder se a "
			f"mudanca alterar nome/versao/descricao do addon; so inclua "
			f"documentation se a mudanca alterar o que o usuario final ve/faz; "
			f"so inclua design_review, agent_template, web_research ou "
			f"test_generation se a mudanca pedida genuinamente exigir isso. Nao "
			f"regenere do zero nada que a mudanca pedida nao afeta."
		)

		# Pipeline de modificacao: sem troca de aba (UI unificada v5.0.0)
		ui.message("NVDAStudio: iniciando pipeline de modificacao.")
		self._disable_run_btn_as_cancel()
		self._current_addon_name = addon_name
		self._set_status("Pipeline de modificacao iniciado...")
		self._orchestrator.run_async(enriched_query)


	def _trigger_creation_pipeline(self, change_description: str):
		"""
		Dispara o pipeline de criacao conversacional v2.0.0.
		"""
		ui.message("NVDAStudio: iniciando pipeline de criacao.")
		self._disable_run_btn_as_cancel()
		self._set_status("Pipeline de criacao iniciado...")
		self._setup_conversational_callbacks()
		self._orchestrator.run_conversational_async(change_description)

	def _on_clarify_needed(self, questions: list[str]) -> list[str]:
		"""
		Callback mid-pipeline: pergunta inline no chat quando o Planner
		inseriu um step user_clarification (sem dialogo modal).
		Chamado de thread daemon. Graceful degradation: timeout = continua.
		"""
		return self._ask_clarification_inline(questions, timeout=180)

	def _on_progress(self, event: str, detail: str):
		"""Callback de progresso do Orchestrator. Chamado de thread — usa fila (Regra 15).
		Exibe o detail diretamente — mensagens geradas pela LLM via user_message do step.
		Eventos sem mensagem (AVALIANDO, APROVADO, etc.) tem detail vazio e sao ignorados.

		BUGFIX (achado de auditoria 2026-08-04, fluxo de MODIFICAR addon
		existente -- _trigger_iterative_pipeline usa este callback via
		Orchestrator.run_async, diferente do fluxo de CRIAR addon novo que
		usa on_phase_change/_handle_conversational_phase): so mandava pra
		`_set_status()`, que e um no-op inerte desde a v5.35.0 (ver seu
		docstring). Dos 12 tipos de evento em _ANNOUNCE_EVENTS, so 4
		(PLANO_CRIADO/AGUARDANDO_USUARIO/CONCLUIDO/ERRO) chegavam a fala
		efemera via _announce_queue -- os outros 8 (PLANEJANDO, EXECUTANDO,
		CORRIGINDO, AVALIANDO, REPLANEJANDO, ESCALANDO, PARALELO, MONTANDO)
		nao iam nem pro log nem pra fala: silencio total durante uma
		correcao/geracao longa num addon ja carregado, sem nada navegavel no
		historico depois. `_chat_append()` (mesmo destino usado por
		_handle_conversational_phase, que sempre funcionou certo) fecha essa
		lacuna -- ja tem de-duplicacao de linha repetida embutida.
		"""
		if not detail:
			return
		clean_detail = sanitize_user_visible_text(detail)
		if not clean_detail:
			return
		wx.CallAfter(self._chat_append, clean_detail)
		wx.CallAfter(self._set_status, clean_detail)
		# Apenas enfileira para fala se for um evento critico (espera do usuario, conclusao ou erro).
		# Mensagens de progresso conversacional ficam apenas no historico para leitura com as setas.
		if event in _ANNOUNCE_EVENTS and event in {"PLANO_CRIADO", "AGUARDANDO_USUARIO", "CONCLUIDO", "ERRO"}:
			self._announce_queue.put(detail)

	def _on_complete(self, result):
		"""Callback final do Orchestrator. Chamado de thread — usa CallAfter (Regra 15)."""
		wx.CallAfter(self._display_result, result)

	def _display_result(self, result):
		"""
		Exibe resultado e pergunta inline no chat se o usuario quer ajustar
		mais alguma coisa ou empacotar (PostGenerationDialog removido ha
		varias versoes, ver v5.28.0). Executado no thread UI (chamado via
		CallAfter). Padrao: finishing-a-development-branch
		(c:\\skills\\finishing-a-development-branch\\SKILL.md)
		"""
		self._last_result = result
		self._enable_run_btn()
		self._run_pending_redirect()

		if result.success:
			total_tokens = getattr(result, "total_tokens", 0)
			token_info = f" | ~{total_tokens:,} tokens" if total_tokens else ""
			self._set_status(
				f"Concluido. Plano {result.plan_id} | {result.total_retries} retries{token_info}"
			)
			# Anuncia token count via ui.message para acessibilidade (S4)
			if total_tokens:
				ui.message(f"NVDAStudio: geracao concluida. {total_tokens:,} tokens usados nesta sessao.")
			# Coleta blocos de todos os steps aprovados em vez de depender
			# apenas do assembly_output (que pode omitir arquivos — Fix A).
			# Prioridade: code_generation > manifest_builder > documentation >
			# agent_runner > assembly. Arquivos duplicados sao descartados.
			blocks = self._collect_all_blocks(result)
			if not blocks:
				# Fallback: tenta assembly_output e final_output
				source = result.assembly_output or result.final_output
				blocks = extract_code_blocks(source)
			python_ok = any(
				(b.get("language") or "").lower() == "python"
				and (b.get("filename") or b.get("name") or "").lower().endswith(".py")
				for b in blocks
			)
			# manifest.ini AUSENTE nao e fatal: save_addon_files() gera o minimo
			# deterministico (addon_builder._generate_minimal_manifest). E a MESMA
			# decisao que o orchestrator ja tomou em _validate_minimum_addon_artifacts
			# (5.75.0), e este gate da GUI era o par ESQUECIDO daquele: continuava
			# derrubando uma entrega COMPLETA (todos os modulos Python gerados) so
			# porque o step do manifest falhou. Foi exatamente o que o droid em modo
			# read-only causou -- assembly e manifest_builder falharam por permissao,
			# o manifest sumiu, e o addon inteiro (4 modulos prontos) foi recusado.
			# So a ausencia de CODIGO PYTHON e irrecuperavel (manifest sem addon nao e
			# addon; addon sem manifest ganha o minimo). controller_client tambem nunca
			# teve manifest por design, entao a regra unica serve aos dois.
			if not python_ok:
				result.success = False
				result.error = (
					"A criação não produziu um addon completo: falta código Python válido."
				)
				# 2026-08-09: antes, blocos parcialmente aprovados (ex: manifest.ini
				# e design_review aprovados, so code_generation falhou) eram
				# DESCARTADOS aqui (self._last_blocks = []) e o usuario via so um
				# popup de erro com "Tentar Novamente" (recomeca do ZERO, gastando
				# tokens de novo) ou "Fechar" (perde tudo). Achado real: rodada de
				# GeminiMultimodal teve manifest_builder/design_review/agent_template
				# aprovados (score 95-100), so code_generation falhou -- e mesmo
				# assim o usuario nao via NADA disso. Padrao "graceful degradation"
				# (pesquisa dedicada 2026-08-09): entrega o que funcionou, avisa o
				# que falta, deixa o usuario continuar por chat em vez de recomecar.
				if blocks:
					return self._display_partial_result(result, blocks)
				self._last_blocks = []
				return self._display_result(result)
			self._last_blocks = blocks
			_logger.info("[OK] _last_blocks: %d bloco(s) coletado(s): %s",
						 len(blocks), [b.get("filename","?") for b in blocks])

			# Monta display limpo: mensagem natural do LLM + lista de arquivos gerados.
			# O final_output (uso interno para extracao de blocos) nunca e mostrado
			# diretamente — ele continha outputs de todos os steps (web_research, etc.)
			# que nao tem valor para o usuario final.
			completed_msg = getattr(result, "completed_message", "") or result.query[:120]
			web_sources = _collect_web_sources(result.step_results)
			if blocks:
				file_lines = "\n".join(
					f"  {b.get('filename') or b.get('language', 'arquivo')}"
					for b in blocks
				)
				display_text = (
					f"{completed_msg}\n\n"
					f"Arquivos gerados ({len(blocks)}):\n{file_lines}"
				)
			else:
				# Sem blocos extraidos: mostra apenas outputs de steps de codigo
				_SHOW_TYPES = {"code_generation", "manifest_builder",
							   "documentation", "agent_runner", "assembly"}
				code_parts = [
					r.output for r in result.step_results
					if r.step_type in _SHOW_TYPES and r.output
				]
				display_text = ("\n\n".join(code_parts)[:8000]
								if code_parts else result.final_output[:8000])
			if web_sources:
				display_text = f"{display_text}\n\n{web_sources}"
			self._code_view.SetValue(display_text)
			addon_name = self._current_addon_name or "addon_gerado"
			steps_ok = sum(1 for r in result.step_results if r.approved)
			# Prefere o nome declarado no manifest.ini gerado (v5.12.0)
			manifest_name = name_from_manifest_blocks(blocks)
			if manifest_name:
				addon_name = manifest_name

			# 2026-08-09: ativa o modo iterativo automaticamente apos uma
			# criacao bem-sucedida -- antes, so acao MANUAL ("Carregar
			# Pasta"/"Carregar Arquivo") setava _loaded_addon_context, entao
			# um pedido de ajuste na MESMA conversa ("conserta esse bug")
			# caia no fluxo de criacao NOVA do zero em vez do modo iterativo
			# (_process_chat_message escolhe o modo pelo estado desta
			# variavel). Nao chama _load_addon_context() (limparia o
			# historico do chat e anunciaria "addon carregado" por cima da
			# mensagem de conclusao que ja vai ser lida).
			self._loaded_addon_context = load_addon_from_blocks(
				blocks, addon_name, summary=completed_msg[:200],
			)
			wx.CallAfter(
				self._lbl_addon_loaded.SetLabel,
				f"Addon carregado: {addon_name} (modo iterativo ativo)",
			)
			log_decision(
				_logger, "addon_auto_carregado_pos_criacao",
				f"nome={addon_name} arquivos={len(self._loaded_addon_context.python_files)}",
			)

			memory.save_session(
				query=result.query,
				addon_name=addon_name,
				plan_id=result.plan_id,
				steps_ok=steps_ok,
				steps_total=len(result.step_results),
				retries=result.total_retries,
				success=result.success,
				summary=f"{steps_ok}/{len(result.step_results)} steps aprovados",
				prompt_version=PROMPT_VERSION,
				step_issues=getattr(result, "all_issues", []),
				total_tokens=total_tokens,
			)
			log_decision(_logger, "sessao_salva",
						 f"plan={result.plan_id} steps_ok={steps_ok} prompt_version={PROMPT_VERSION}")
			# Removido PostGenerationDialog por solicitação do usuário.
			# Agora pergunta diretamente no chat se deseja fazer mais algo ou se pode empacotar.
			sources_suffix = f"\n\n{web_sources}" if web_sources else ""
			# Aviso honesto: auditoria de qualidade/dominio que foi tentada e
			# nao passou (nao bloqueia a entrega, mas nao pode ficar silenciosa).
			quality_warning = _collect_quality_gaps(result.step_results)
			quality_suffix = f"\n\n{quality_warning}" if quality_warning else ""
			followup = _collect_followup_suggestions(result.step_results)
			pergunta_final = (
				f"{followup} Ou posso empacotar o addon assim mesmo."
				if followup else
				"Quer ajustar mais alguma coisa ou posso empacotar o addon?"
			)
			if blocks:
				file_lines = "\n".join(
					f"  {b.get('filename') or b.get('language', 'arquivo')}"
					for b in blocks
				)
				self._chat_append(
					f"{completed_msg}"
					f"{quality_suffix}\n\n"
					f"Arquivos gerados ({len(blocks)}):\n{file_lines}"
					f"{sources_suffix}\n\n"
					f"{pergunta_final}"
				)
			else:
				self._chat_append(
					f"{completed_msg}"
					f"{quality_suffix}"
					f"{sources_suffix}\n\n"
					f"{pergunta_final}"
				)

			self._waiting_for_packaging_approval = True
			self._enable_run_btn()
			self._input.Enable()
			self._update_input_label("Digite sua resposta:")
			# BUGFIX (achado de auditoria 2026-08-04): foco ficava no _log
			# (so leitura) bem no momento em que a proxima acao esperada do
			# usuario e DIGITAR a resposta ("ajustar ou empacotar?") no
			# _input -- um usuario de teclado/leitor de tela precisava dar
			# Tab manualmente antes de conseguir responder. O historico ja
			# foi anunciado pelo _chat_append() acima; o foco final deve ir
			# pro campo que o usuario realmente vai usar em seguida.
			self._input.SetFocus()

			# Fala o aviso de qualidade ANTES do prompt: um usuario de leitor de
			# tela precisa OUVIR que uma checagem ficou de fora, nao so ve-la no
			# historico. Sem emoji/quebras, que soam mal na sintese.
			_aviso_falado = ""
			if quality_warning:
				_aviso_falado = quality_warning.replace("⚠️", "").replace("\n", " ").strip() + " "
			ui.message(f"{_aviso_falado}Desenvolvimento concluído. Quer ajustar mais alguma coisa ou posso empacotar o addon?")
		else:
			err = result.error or "Nao foi possivel completar o plano."
			self._set_status(f"Erro: {err}")
			# 7.3 R:a+c: inclui sugestao de reformulacao + fluxos 14.2 R:c: botao Tentar Novamente
			err_msg = (
				f"{err}\n\n"
				"Dica: os detalhes tecnicos foram registrados no log. Tente novamente; "
				"se o problema persistir, envie o log para analise."
			)
			dlg = wx.MessageDialog(
				self,
				err_msg,
				"NVDAStudio - Erro na geracao",
				wx.YES_NO | wx.ICON_ERROR,
			)
			dlg.SetYesNoLabels("&Tentar Novamente", "&Fechar")
			gui.mainFrame.prePopup()
			resp = dlg.ShowModal()
			dlg.Destroy()
			gui.mainFrame.postPopup()
			ui.message(f"NVDAStudio: erro na geracao. {err[:80]}")
			if resp == wx.ID_YES and self._last_query:
				self._disable_run_btn_as_cancel()
				self._set_status("Repetindo o pedido...")
				thread = threading.Thread(
					target=self._clarify_and_run,
					args=(self._last_query,),
					daemon=True,
				)
				thread.start()

	def _display_partial_result(self, result, blocks: list[dict]):
		"""
		Entrega parcial (graceful degradation, 2026-08-09): quando o pipeline
		nao produz um addon COMPLETO (falta code_generation ou manifest_builder
		aprovado), mas OUTROS steps ja produziram artefatos validos (manifest,
		documentacao, design_review, agent_template etc), mostra o que
		funcionou em vez de descartar tudo com um popup de erro generico.
		Ativa o modo iterativo com o que ja existe -- o usuario pode pedir
		pra corrigir so a parte que faltou, pelo chat, sem recomecar do zero.

		Achado real: pesquisa dedicada 2026-08-09 (padrao "graceful
		degradation" de agentes de IA em producao) + rodada real do golden
		eval set (GeminiMultimodal) onde manifest_builder/design_review/
		agent_template foram aprovados (score 95-100) e so code_generation
		falhou -- mesmo assim o usuario nao via NENHUM desses artefatos.
		"""
		self._last_blocks = blocks
		addon_name = self._current_addon_name or "addon_gerado"
		manifest_name = name_from_manifest_blocks(blocks)
		if manifest_name:
			addon_name = manifest_name

		self._loaded_addon_context = load_addon_from_blocks(
			blocks, addon_name, summary=(result.error or "")[:200],
		)
		wx.CallAfter(
			self._lbl_addon_loaded.SetLabel,
			f"Addon carregado: {addon_name} (parcial -- modo iterativo ativo)",
		)

		file_lines = "\n".join(
			f"  {b.get('filename') or b.get('language', 'arquivo')}" for b in blocks
		)
		msg = (
			f"O addon nao ficou completo: {result.error}\n\n"
			f"Mas isto ja foi gerado com sucesso ({len(blocks)} arquivo(s)):\n{file_lines}\n\n"
			f"Pode me pedir pra corrigir so a parte que faltou -- nao precisa recomecar do zero."
		)
		self._code_view.SetValue(msg)
		self._chat_append(f"Sistema:\n{msg}")
		self._set_status(f"Parcial: {result.error}")
		self._input.SetFocus()
		ui.message(
			f"NVDAStudio: addon parcial. {len(blocks)} arquivo(s) gerados com sucesso. "
			f"{result.error}"
		)
		log_decision(
			_logger, "entrega_parcial",
			f"addon={addon_name} blocos={len(blocks)} motivo={result.error}",
		)

	def _process_packaging_decision(self, query: str):
		"""
		Classifica a resposta do usuario sobre o empacotamento em thread background.
		Intent pode ser:
		- "package": O usuario quer empacotar/concluir.
		- "modify": O usuario quer fazer mais alteracoes/continuar.
		"""
		intent = "modify"  # default
		try:
			client = create_llm_client(model_id=self._get_quick_chat_model())
			system_prompt = (
				"Interprete semanticamente a resposta livre do usuário à pergunta final. "
				"Classifique como package quando ele considera o trabalho pronto e autoriza "
				"criar o pacote, ou modify quando ainda deseja conversar ou alterar algo. "
				"Não decida por palavras isoladas. Responda somente JSON com o campo intent."
			)
			user_msg = f"Resposta do usuário: \"{query}\""
			resp = client.chat(
				user_message=user_msg,
				system_override=system_prompt,
				response_format={"type": "json_object"}
			)
			content = (resp.content or "").strip()
			import json
			data = json.loads(content)
			parsed_intent = data.get("intent", "modify")
			intent = parsed_intent if parsed_intent in {"package", "modify"} else "modify"
		except Exception as e:
			_logger.warning("[IntentClassifier] Falha na chamada da IA para empacotamento: %s", e)
			intent = "modify"

		if intent == "package":
			wx.CallAfter(self._run_packaging_process)
		else:
			wx.CallAfter(self._trigger_iterative_pipeline, query)

	def _run_packaging_process(self):
		"""Executa o processo de empacotamento do addon na thread UI."""
		self._set_status("Iniciando o empacotamento do addon.")
		self._chat_append("Assistente:\nIniciando o empacotamento do addon.")
		ui.message("Iniciando o empacotamento.")
		self._on_package(None)
		self._enable_run_btn()
		self._input.Enable()
		self._input.SetFocus()

	def _collect_all_blocks(self, result) -> list[dict]:
		"""
		Coleta blocos de codigo de TODOS os steps aprovados, em prioridade:
		code_generation > manifest_builder > documentation > agent_runner > assembly.

		Fix A: O assembly_output pode omitir arquivos quando o LLM nao reemite
		todos os blocos anotados. Este metodo coleta diretamente do output de
		cada step individual, garantindo que __init__.py, manifest.ini e
		userGuide.html cheguem completos a _last_blocks.

		Regra 9: apenas leitura de texto — nenhum codigo e executado.
		"""
		# 5.45.0: "agent_template" removido -- gera so TEMPLATE MD de agente
		# (documentacao/spec), nunca codigo de producao (ver
		# sub_agents/agent_template_agent.py: "quem escreve o codigo real do
		# addon e o step code_generation, separado deste"). Inclui-lo aqui
		# deixava um trecho ilustrativo sem anotacao de arquivo, embutido no
		# template aprovado, ser extraido como se fosse um modulo real do
		# addon (module_N.py) quando code_generation falhava -- exatamente
		# o bug real achado no caso GeminiMultimodal.
		_STEP_PRIORITY = [
			"code_generation", "manifest_builder", "documentation",
			"agent_runner", "assembly",
		]
		# 5.45.0: allowlist explicita de step_types elegiveis como FONTE de
		# arquivo -- antes, o filtro abaixo so exigia (approved OU non-blocking)
		# e usava _STEP_PRIORITY apenas pra ORDEM, nao pra inclusao/exclusao.
		# Um step como agent_template (gera so TEMPLATE MD, nunca codigo --
		# ver sub_agents/agent_template_agent.py) ainda passava pelo filtro
		# de inclusao normalmente por estar approved=True, e um trecho
		# ilustrativo sem anotacao de arquivo dentro do template virava
		# module_N.py "de verdade" quando code_generation falhava (bug real,
		# caso GeminiMultimodal). Agora so step_types que legitimamente
		# produzem arquivos do addon entram na extracao de blocos --
		# inclui test_generation (gera codigo de teste real, diferente de
		# design_review/accessibility_audit, que geram so texto de revisao).
		_CODE_SOURCE_STEP_TYPES = set(_STEP_PRIORITY) | {"test_generation"}
		seen_filenames: set[str] = set()
		all_blocks: list[dict] = []

		# Ordena step_results por prioridade definida acima
		def _priority(sr) -> int:
			try:
				return _STEP_PRIORITY.index(sr.step_type)
			except ValueError:
				return len(_STEP_PRIORITY)

		# Inclui steps aprovados + steps nao-bloqueantes (doc, accessibility) mesmo
		# se reprovados pelo Critic — eles sempre geram output util (ex: userGuide.html).
		_non_blocking = {"accessibility_audit", "test_generation", "documentation", "design_review"}
		sorted_results = sorted(
			[r for r in result.step_results
			 if r.step_type in _CODE_SOURCE_STEP_TYPES
			 and (r.approved or r.step_type in _non_blocking) and r.output],
			key=_priority,
		)

		for sr in sorted_results:
			blocks = extract_code_blocks(sr.output)
			for blk in blocks:
				fname = blk.get("filename", "").strip()
				if fname and fname not in seen_filenames:
					seen_filenames.add(fname)
					all_blocks.append(blk)
					_logger.info(
						"[BLOCO] step=%s lang=%s file=%s",
						sr.step_type, blk.get("language", "?"), fname,
					)
				elif not fname:
					# Bloco sem filename: inclui sempre (fallback sem anotacao)
					all_blocks.append(blk)

		if not all_blocks:
			_logger.warning(
				"[AVISO] _collect_all_blocks: nenhum bloco encontrado nos steps."
				" Fallback para assembly_output."
			)
		return all_blocks

	def _bundle_async(
		self,
		addon_folder: str,
		deps: list,
		addon_name: str,
		on_done: Callable[[bool, list, dict], None],
	):
		"""
		Roda bundle_addon_dependencies em thread daemon com timeout de 300s.

		B2: pip install bloqueava a thread UI indefinidamente — o NVDA travava.
		Solucao: thread separada + feedback falado em cada etapa.

		Anuncia cada pacote individualmente: "instalando X...", "X instalado" ou
		"falha ao instalar X" — o usuario cego ouve o historico completo.

		on_done(success: bool, installed: list, failed: dict) e chamado via wx.CallAfter
		na thread UI quando o bundle terminar ou falhar.

		Regra 15: ui.message() sempre via wx.CallAfter da thread UI.
		"""
		total = len(deps)
		ui.message(
			f"NVDAStudio: iniciando instalacao de {total} dependencia(s): "
			f"{', '.join(deps)}. Aguarde."
		)
		self._set_status(f"Instalando {total} dependencia(s): {', '.join(deps[:3])}...")

		_failed: dict[str, str] = {}  # pkg -> razao da falha

		def _progress_cb(pkg: str, status: str, detail: str | None = None):
			if status == "iniciando":
				wx.CallAfter(ui.message, f"NVDAStudio: instalando {pkg}...")
				wx.CallAfter(self._set_status, f"Instalando: {pkg}...")
			elif status == "ok":
				wx.CallAfter(ui.message, f"NVDAStudio: {pkg} instalado com sucesso.")
			elif status == "falha":
				_failed[pkg] = detail or "erro desconhecido"
				wx.CallAfter(ui.message,
							 f"NVDAStudio: falha ao instalar {pkg}. Pode ser instalado manualmente depois.")

		def _do_bundle():
			try:
				installed = bundle_addon_dependencies(
					addon_folder, deps, addon_name,
					on_package_progress=_progress_cb,
				)
				wx.CallAfter(on_done, len(_failed) == 0, installed, dict(_failed))
			except Exception as exc:
				_logger.error("[ERRO] bundle_async falhou: %s", exc)
				wx.CallAfter(on_done, False, [], {})

		t = threading.Thread(target=_do_bundle, daemon=True)
		t.start()

	def _collect_structural_context_files(
		self,
		addon_folder: str,
		problems: list[str],
	) -> dict[str, str]:
		"""Coleta arquivos relevantes para autocorrecao estrutural por IA."""
		refs: set[str] = set()
		name_pat = re.compile(r"([A-Za-z0-9_./\\-]+\.(?:py|ini|html|dic|utb))")
		for p in problems:
			for m in name_pat.findall(p):
				rel = m.replace("\\", "/").lstrip("/")
				if rel:
					refs.add(rel)

		manifest_rel = "manifest.ini"
		manifest_abs = os.path.join(addon_folder, manifest_rel)
		if os.path.isfile(manifest_abs):
			refs.add(manifest_rel)

		gp_dir = os.path.join(addon_folder, "globalPlugins")
		if os.path.isdir(gp_dir):
			for root, dirs, files in os.walk(gp_dir):
				dirs[:] = [d for d in dirs if d != "lib" and d != "__pycache__"]
				for fname in files:
					if not fname.endswith(".py") and not fname.endswith(".ini"):
						continue
					abs_path = os.path.join(root, fname)
					rel_path = os.path.relpath(abs_path, addon_folder).replace("\\", "/")
					refs.add(rel_path)

		context_files: dict[str, str] = {}
		for rel in sorted(refs):
			abs_path = os.path.normpath(os.path.join(addon_folder, rel))
			if not _is_path_within(addon_folder, abs_path):
				continue
			if not os.path.isfile(abs_path):
				continue
			try:
				with open(abs_path, encoding="utf-8", errors="replace") as fh:
					context_files[rel] = fh.read()
			except OSError:
				continue

		return context_files

	def _apply_structural_fix_blocks(
		self,
		addon_folder: str,
		blocks: list[dict],
	) -> list[str]:
		"""Aplica blocos extraidos da IA de forma segura dentro da pasta do addon."""
		actions: list[str] = []
		for blk in blocks:
			rel = (blk.get("filename") or "").replace("\\", "/").lstrip("/").strip()
			if not rel:
				continue
			if rel == "manifest.ini":
				dest_rel = rel
			elif "/" in rel:
				dest_rel = rel
			else:
				# Exige caminho relativo para evitar gravacao ambigua.
				continue

			dest_abs = os.path.normpath(os.path.join(addon_folder, dest_rel))
			if not _is_path_within(addon_folder, dest_abs):
				_logger.warning("[AUTO_FIX] path traversal bloqueado: %s", rel)
				continue

			code = str(blk.get("code") or "")
			if not code.strip():
				continue

			os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
			open_kwargs: dict = {"encoding": "utf-8"}
			if dest_abs.lower().endswith(".py") or dest_abs.lower().endswith(".ini"):
				code = code.replace("\r\n", "\n").replace("\r", "\n")
				open_kwargs["newline"] = "\n"
			with open(dest_abs, "w", **open_kwargs) as fh:
				fh.write(code)
			actions.append(f"atualizado: {dest_rel}")

		return actions

	def _auto_fix_structural_issues(
		self,
		addon_folder: str,
		addon_name: str,
		max_rounds: int = 2,
	) -> tuple[list[str], list[str]]:
		"""Executa rounds de autocorrecao para TODAS as regras de validate_addon_structure()."""
		actions: list[str] = []
		last_problems = validate_addon_structure(addon_folder)
		if not last_problems:
			return actions, last_problems

		for round_idx in range(1, max_rounds + 1):
			problem_count = len(last_problems)
			_logger.info(
				"[AUTO_FIX] Rodada %d/%d: %d problema(s) estrutural(is).",
				round_idx,
				max_rounds,
				problem_count,
			)

			context_files = self._collect_structural_context_files(addon_folder, last_problems)
			if not context_files:
				_logger.warning("[AUTO_FIX] Sem arquivos de contexto para corrigir.")
				break

			files_blob = []
			for rel, content in context_files.items():
				files_blob.append(f"```text:{rel}\n{content}\n```")
			prompt = (
				f"Addon: {addon_name}\n"
				"Corrija TODOS os problemas estruturais listados abaixo, sem remover funcionalidade.\n"
				"Siga estritamente as regras NVDA e WX-A11Y.\n\n"
				"PROBLEMAS:\n"
				+ "\n".join(f"- {p}" for p in last_problems)
				+ "\n\n"
				"ARQUIVOS ATUAIS:\n"
				+ "\n\n".join(files_blob)
				+ "\n\n"
				"SAIDA OBRIGATORIA:\n"
				"- Retorne APENAS blocos de codigo com caminho relativo no formato ```python:path ou ```ini:path.\n"
				"- Inclua SOMENTE arquivos que precisam mudar ou ser criados para resolver os problemas.\n"
				"- Mantenha TABS em Python e comentarios # Translators: imediatamente antes de cada _()."
			)

			try:
				client = create_llm_client(model_id=self._get_quick_chat_model())
				resp = client.chat(
					user_message=prompt,
					system_override=(
						"Voce e um corretor estrutural de addons NVDA. "
						"Corrija todos os problemas listados e devolva somente blocos de arquivo."
					),
				)
			except Exception as exc:
				_logger.warning("[AUTO_FIX] LLM indisponivel: %s", exc)
				break

			if not resp.content:
				_logger.warning("[AUTO_FIX] Resposta vazia do corretor estrutural.")
				break

			blocks = extract_code_blocks(resp.content)
			if not blocks:
				_logger.warning("[AUTO_FIX] Nenhum bloco extraido na rodada %d.", round_idx)
				break

			round_actions = self._apply_structural_fix_blocks(addon_folder, blocks)
			if not round_actions:
				_logger.warning("[AUTO_FIX] Nenhuma alteracao aplicavel na rodada %d.", round_idx)
				break

			actions.extend(round_actions)
			new_problems = validate_addon_structure(addon_folder)
			if not new_problems:
				_logger.info("[AUTO_FIX] Rodada %d resolveu todos os problemas.", round_idx)
				last_problems = new_problems
				break

			if len(new_problems) >= problem_count:
				_logger.warning(
					"[AUTO_FIX] Rodada %d nao reduziu problemas (%d -> %d).",
					round_idx,
					problem_count,
					len(new_problems),
				)
				last_problems = new_problems
				break

			last_problems = new_problems

		return actions, last_problems

	# ------------------------------------------------------------------
	# Empacotamento (fluxo inline pergunta "ajustar ou empacotar?" em
	# _display_result/_process_packaging_decision -- unico caminho real).
	# ------------------------------------------------------------------

	def _instalar_dependencias_se_preciso(self, addon_folder: str, addon_name: str) -> bool:
		"""Pergunta e instala as dependencias externas em lib/ antes de empacotar.

		Retorna True se a instalacao FOI INICIADA -- nesse caso o empacotamento e
		adiado e _on_package e reentrado quando ela terminar. Retorna False quando
		nao ha o que instalar ou o usuario recusou: segue empacotando na hora.

		Reentrar em _on_package e seguro: ele reutiliza self._last_addon_folder.
		A flag _deps_ja_tratadas evita a segunda pergunta (e o laco infinito).
		"""
		if getattr(self, '_deps_ja_tratadas', False):
			return False
		deps = deps_pendentes(
			getattr(self._last_result, 'dependencies', None),
			os.path.join(addon_folder, 'lib'),
		)
		if not deps:
			self._deps_ja_tratadas = True
			return False
		lista = ', '.join(deps)
		resposta = gui.messageBox(
			f"O addon '{addon_name}' usa {len(deps)} biblioteca(s) externa(s):\n"
			f"{lista}\n\n"
			"Incluir no pacote deixa o addon autossuficiente: funciona em qualquer "
			"computador onde for instalado, sem depender do NVDAStudio. Em troca, o "
			"arquivo fica maior.\n\n"
			"Sem as bibliotecas o addon instala e carrega, mas avisa que a "
			"funcionalidade esta indisponivel.\n\n"
			"Deseja incluir as bibliotecas no pacote?",
			"NVDAStudio: dependencias do addon",
			wx.YES_NO | wx.ICON_QUESTION,
		)
		if resposta != wx.YES:
			self._deps_ja_tratadas = True
			ui.message(
				"NVDAStudio: empacotando sem as bibliotecas. O addon vai avisar que "
				"a funcionalidade esta indisponivel."
			)
			_logger.info('[OK] dependencias recusadas pelo usuario: %s', lista)
			return False

		def _pronto(_sucesso: bool, instalados: list, falhas: dict) -> None:
			self._deps_ja_tratadas = True
			if falhas:
				detalhe = ', '.join(sorted(falhas))
				self._chat_append(
					f"Assistente:\nNao consegui instalar {len(falhas)} biblioteca(s): "
					f"{detalhe}. O addon sera empacotado assim mesmo e vai avisar que a "
					f"funcionalidade esta indisponivel."
				)
			else:
				self._chat_append(
					f"Assistente:\n{len(instalados)} biblioteca(s) incluida(s) no pacote."
				)
			# Segue o empacotamento que foi adiado.
			self._on_package(None)

		self._bundle_async(addon_folder, deps, addon_name, _pronto)
		return True

	def _on_package(self, _event):
		"""
		Botao Empacotar: empacota .nvda-addon a partir dos arquivos ja salvos.

		Fix B: antes chamava save_addon_files novamente, criando uma segunda
		pasta duplicada com timestamp diferente. Agora reutiliza
		self._last_addon_folder se existir, ou salva primeiro se ainda nao
		houver pasta (ex: usuario escolheu Manter no PostGenDialog).
		"""
		if not self._last_blocks:
			ui.message("Nenhum artefato disponivel. Execute o Criar Addon primeiro.")
			return
		addon_name = self._current_addon_name or "addon_gerado"
		# 5.50.0: controller_client (programa externo) nao e um addon --
		# fix_addon_structure()/_auto_fix_structural_issues() assumem
		# manifest.ini/globalPlugins/__init__.py e nao devem tentar
		# "corrigir" um programa standalone que nunca teve essa estrutura
		# por design. Empacota como .zip simples, nao .nvda-addon (extensao
		# enganosa pra algo que o addonHandler nunca vai carregar), e
		# save_addon_files() nao deve injetar um manifest.ini falso.
		_is_ctrl_client_pkg = getattr(self._last_result, "project_type", "addon") == "controller_client"
		try:
			output_dir = get_output_dir()
			os.makedirs(output_dir, exist_ok=True)

			# Reutiliza pasta existente — evita criar pasta duplicada
			if self._last_addon_folder and os.path.isdir(self._last_addon_folder):
				addon_folder = self._last_addon_folder
				_logger.info("[OK] _on_package: reutilizando pasta %s", addon_folder)
			else:
				# Ainda nao foi salvo — salva direto na pasta de addons do NVDA
				nvda_dir = _get_nvda_addons_dir()
				os.makedirs(nvda_dir, exist_ok=True)
				addon_folder, _ = save_addon_files(
					self._last_blocks, nvda_dir, addon_name, use_timestamp=False,
					require_manifest=not _is_ctrl_client_pkg,
				)
				self._last_addon_folder = addon_folder
				_logger.info("[OK] _on_package: pasta criada em %s", addon_folder)

			safe_name = addon_name.replace(" ", "_")
			if _is_ctrl_client_pkg:
				nvda_addon_path = package_addon(
					addon_folder,
					os.path.join(output_dir, f"{safe_name}.zip")
				)
				self._set_status(f"Empacotado: {nvda_addon_path}")
				self._chat_append(f"Assistente:\nPrograma empacotado com sucesso. Arquivo: {safe_name}.zip")
				ui.message(f"NVDAStudio: programa empacotado com sucesso. Arquivo: {safe_name}.zip")
				_logger.info("[OK] _on_package (controller_client): %s", nvda_addon_path)
				return

			# 6.x -- as dependencias detectadas viravam nada.
			#
			# O orchestrator ja detecta os imports externos e os envia em
			# OrchestrationResult.dependencies; esta tela ja tinha o instalador
			# pronto (_bundle_async -> bundle_addon_dependencies, com a ABI do
			# Python embarcado do NVDA fixada). Os dois lados existiam e estavam
			# corretos -- faltava a chamada: _bundle_async() nao tinha NENHUM
			# chamador, e esta tela nunca lia result.dependencies.
			#
			# Consequencia medida na entrega ResumoGemini (2026-09-02): o addon
			# saiu sem lib/, e sem google-generativeai ele carrega no NVDA e
			# avisa por voz, mas nao resume nada.
			if self._instalar_dependencias_se_preciso(addon_folder, addon_name):
				return  # instalacao em andamento; reentra por _on_package ao terminar
			fix_addon_structure(addon_folder)
			_fix_actions, _remaining_problems = self._auto_fix_structural_issues(addon_folder, addon_name)

			nvda_addon_path = package_addon(
				addon_folder,
				os.path.join(output_dir, f"{safe_name}.nvda-addon")
			)
			# Quality gate final: valida o arquivo empacotado, não apenas a pasta
			# intermediária. O ZIP é aberto, verificado e executado em isolamento.
			from ..builder.code_sandbox import CodeSandbox
			final_check = CodeSandbox(timeout_sec=15).validate_final_package(nvda_addon_path)
			if not final_check.success:
				evidence = final_check.error or final_check.stderr or final_check.stdout
				_logger.error("[QUALITY_GATE] Pacote final rejeitado: %s", evidence[:1000])
				self._chat_append(
					"Assistente:\nO pacote não foi liberado porque a validação final falhou:\n"
					+ evidence
				)
				ui.message("NVDAStudio: pacote rejeitado na validação final.")
				return
			self._set_status(f"Empacotado: {nvda_addon_path}")
			# 5.47.0: achado real ao vivo (test_e36, GeminiMultimodal) -- o retorno de
			# _auto_fix_structural_issues() (last_problems) era descartado aqui. Se as
			# 2 rodadas de autocorrecao nao resolvessem tudo (ex: __init__.py raiz
			# continua ausente), o codigo seguia direto pro "empacotado com sucesso"
			# INCONDICIONAL -- o usuario nunca ficava sabendo que o .nvda-addon
			# entregue estava estruturalmente quebrado (NVDA nem carrega sem
			# __init__.py). Agora reporta claramente quando sobra problema.
			if _remaining_problems:
				problems_txt = "\n".join(f"- {p}" for p in _remaining_problems)
				self._chat_append(
					f"Assistente:\nAddon empacotado, mas ainda tem {len(_remaining_problems)} "
					f"problema(s) estrutural(is) que a autocorrecao nao resolveu:\n{problems_txt}\n\n"
					f"O addon pode nao carregar corretamente no NVDA. Posso tentar corrigir de novo "
					f"se voce pedir, ou revise manualmente antes de instalar."
				)
				ui.message(
					f"NVDAStudio: addon empacotado, mas com {len(_remaining_problems)} "
					f"problema(s) estrutural(is) nao resolvido(s). Veja o historico para detalhes."
				)
				_logger.warning(
					"[AVISO] _on_package: %s empacotado com %d problema(s) estrutural(is) sem resolver.",
					nvda_addon_path, len(_remaining_problems),
				)
			else:
				self._chat_append(f"Assistente:\nAddon empacotado com sucesso. Arquivo: {safe_name}.nvda-addon")
				ui.message(f"NVDAStudio: addon empacotado com sucesso. Arquivo: {safe_name}.nvda-addon")
				_logger.info("[OK] _on_package: %s", nvda_addon_path)
		except AddonBuilderError as exc:
			self._show_error(f"Erro ao empacotar: {exc}")
		except Exception as exc:
			self._show_error(f"Erro inesperado ao empacotar: {exc}")

	def _on_reset(self, _event):
		"""Nova Sessao: salva historico de chat (arquivo + session_memory) e limpa tudo."""
		from ..utils.smart_retry import smart_retry
		smart_retry.reset()
		if self._chat_history:
			try:
				output_dir = get_output_dir()
				os.makedirs(output_dir, exist_ok=True)
				sess_name = self._current_addon_name or "sessao"
				ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
				hist_path = os.path.join(output_dir, f"historico_{sess_name}_{ts}.txt")
				with open(hist_path, "w", encoding="utf-8") as fh:
					for msg in self._chat_history:
						role = msg.get("role", "?")
						text = msg.get("text", "")
						fh.write(f"[{role}]\n{text}\n\n")
				_logger.info("[OK] _on_reset: historico salvo em %s", hist_path)
			except Exception as exc:
				_logger.warning("[WARN] _on_reset: falha ao salvar historico txt: %s", exc)
			# Gap B (skill: memory-systems Layer 3): persiste chat em TinyDB para recuperacao cross-session
			try:
				sess_name = self._current_addon_name or "sessao"
				memory.save_chat_snippet(sess_name, self._chat_history)
				_logger.info("[OK] _on_reset: chat_snippet salvo para '%s'", sess_name)
			except Exception as exc:
				_logger.warning("[WARN] _on_reset: falha ao salvar chat_snippet: %s", exc)
		self._last_result = None
		self._last_blocks = []
		self._last_addon_folder = ""
		self._current_addon_name = ""
		# 2026-08-09: sem isso, "Nova Sessao" preservava o modo iterativo do
		# addon anterior (carregado manualmente OU auto-carregado pos-criacao,
		# MODULE_VERSION addon_loader.py 1.3.0) -- um pedido de addon NOVO,
		# sem relacao nenhuma, seria tratado como ajuste do addon antigo.
		self._loaded_addon_context = None
		wx.CallAfter(self._lbl_addon_loaded.SetLabel, "Nenhum addon carregado.")
		self._chat_history = []
		self._input.SetValue("")
		self._log.SetValue("")
		self._code_view.SetValue("")
		self._set_status("Nova sessao iniciada. Descreva o addon que deseja criar.")
		ui.message("NVDAStudio: nova sessao.")

	def _on_show_stats(self, event):
		"""Estatisticas de desempenho e observabilidade -- inline no chat
		(sem dialogo modal). Dado real sob demanda, nao decisao da IA."""
		total_sessions = memory.get_session_count()
		successes = 0
		total_tokens = 0
		avg_tokens = 0
		try:
			with memory._lock:
				memory._init_db()
				if memory._db is not None:
					all_sessions = memory._db.table("sessions").all()
					for s in all_sessions:
						if s.get("success"):
							successes += 1
						total_tokens += s.get("total_tokens", 0) or 0
					if total_sessions > 0:
						avg_tokens = round(total_tokens / total_sessions)
		except Exception as exc:
			_logger.debug("[DEBUG] Falha ao agregar estatisticas de sessoes: %s", exc)
		success_rate = (successes / total_sessions * 100) if total_sessions > 0 else 0.0

		report = ["=== RESUMO GERAL ==="]
		report.append(f"Total de sessões de desenvolvimento: {total_sessions}")
		report.append(f"Taxa de sucesso na criação de addons: {success_rate:.1f}% ({successes} sucessos)")
		report.append(f"Total de tokens consumidos: {total_tokens:,} tokens")
		report.append(f"Consumo médio por sessão: {avg_tokens:,} tokens")
		report.append("")

		report.append("=== DESEMPENHO DOS AGENTES (ÚLTIMAS 50 ETAPAS) ===")
		rates = memory.get_step_success_rates(last_n=50)
		if rates:
			for r in rates:
				report.append(f"Agente: {r['step_type'].upper()}")
				report.append(f"  - Taxa de Sucesso Geral: {r['success_rate']*100:.1f}%")
				report.append(f"  - Sucesso de Primeira: {r['first_attempt_rate']*100:.1f}%")
				report.append(f"  - Latência Média: {r['avg_latency_ms']/1000:.2f}s")
				report.append(f"  - Tokens Médios: {r['avg_tokens']:,}")
				report.append("")
		else:
			report.append("Nenhuma métrica de etapa registrada ainda.")

		report.append("=== TESTES A/B DE PROMPTS ===")
		pvs = memory.get_stats_by_prompt_version()
		if pvs:
			for pv in pvs:
				report.append(f"Versão: '{pv['prompt_version'] or 'default'}'")
				report.append(f"  - Sessões: {pv['sessions']}")
				report.append(f"  - Taxa de Sucesso: {pv['success_rate']*100:.1f}%")
				report.append(f"  - Passos concluídos: {pv['steps_ok']}/{pv['steps_total']}")
				report.append("")
		else:
			report.append("Nenhum dado de versão de prompt registrado.")

		report.append("=== CUSTO ESTIMADO (ÚLTIMOS 500 REGISTROS) ===")
		cost = memory.get_cost_breakdown(last_n=500)
		if cost["by_model"]:
			report.append(f"Total: US$ {cost['total_usd']:.2f} (R$ {cost['total_brl']:.2f})")
			for model_id, m in sorted(cost["by_model"].items(), key=lambda kv: -kv[1]["usd"]):
				if m["usd"] <= 0:
					continue
				report.append(
					f"  - {model_id}: US$ {m['usd']:.4f} (R$ {m['brl']:.2f}) "
					f"em {m['calls']} chamadas, {m['tokens']:,} tokens"
				)
			report.append("")
		else:
			report.append("Nenhum dado de custo registrado ainda.")
			report.append("")

		report_text = "\n".join(report)
		self._chat_append(f"Assistente:\n{report_text}")
		self._speak_message(
			f"Estatísticas: {total_sessions} sessões, {success_rate:.0f}% de sucesso, "
			f"{total_tokens:,} tokens consumidos, custo estimado US$ {cost['total_usd']:.2f}. "
			f"Detalhes completos no histórico."
		)

	def _offer_chat_restore(self, addon_name: str) -> None:
		"""
		Verifica se ha historico de chat para o addon_name no banco.
		Se houver, exibe dialogo perguntando se o usuario quer restaurar.
		Executa obrigatoriamente no thread UI (chamado de _on_run, que e UI).

		skill: memory-systems (Layer 3 Long-term memory — cross-session context).
		"""
		try:
			previous = memory.get_last_chat(addon_name)
		except Exception:
			return
		if not previous:
			return
		try:
			n = len(previous)
			dlg = wx.MessageDialog(
				self,
				f"Encontrei {n} mensagem(ns) de uma sessao anterior sobre '{addon_name}'.\n"
				"Deseja restaurar esse historico no chat?",
				"NVDAStudio - Restaurar Historico",
				wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
			)
			restore = dlg.ShowModal() == wx.ID_YES
			dlg.Destroy()
		except Exception as exc:
			_logger.warning("[WARN] _offer_chat_restore: dialogo falhou: %s", exc)
			return
		if not restore:
			ui.message("Historico anterior ignorado.")
			return
		# Restaura mensagens no historico interno e no log unificado
		for msg in previous:
			role = msg.get("role", "?")
			text = msg.get("text", "")
			self._chat_history.append({"role": role, "text": text})
			prefix = "Você" if role == "user" else "NVDAStudio"
			self._chat_append(f"Restaurado. {prefix}: {text}")
		ui.message(f"Historico restaurado: {len(previous)} mensagem(ns) da sessao anterior.")
		_logger.info("[OK] _offer_chat_restore: %d msgs restauradas para '%s'",
					 len(previous), addon_name)

		# ------------------------------------------------------------------
		# Fila de anuncios NVDA (Regra 15: ui.message so do thread UI)
		# ------------------------------------------------------------------

	def _process_announce(self, _event):
		"""Drena 1 mensagem da fila por tick do Timer. Chama _speak_message no thread UI."""
		try:
			msg = self._announce_queue.get_nowait()
			self._speak_message(msg[:200])
		except queue.Empty:
			pass

		# ------------------------------------------------------------------
		# Utilidades
		# ------------------------------------------------------------------

	def _set_status(self, msg: str):
		"""
		Atualiza a barra de status visual. Deve ser chamado do thread UI.

		NAO atualiza mais o texto do widget (v5.35.0): o metodo de troca de
		rotulo do wx.StaticText muda o texto de um controle nativo Win32
		(SetWindowText por baixo) -- o Windows dispara EVENT_OBJECT_NAMECHANGE
		automaticamente, e o NVDA anuncia essa mudanca sozinho, INDEPENDENTE
		de qualquer ui.message() explicito do addon. Felipe reportou em
		live-test (varias vezes) que as narracoes do pipeline ("Pesquisando
		APIs...", "Criando o plano...", "Construindo X...") eram faladas
		automaticamente mesmo depois de toda a limpeza de auto-fala feita
		nesta sessao -- a causa raiz nao era nenhuma chamada ui.message()/
		_speak_message() (essas ja tinham sido removidas), era esse efeito
		colateral do proprio metodo de troca de rotulo do widget. Unico
		jeito confiavel de garantir "nunca falado automaticamente, sempre so
		historico" e nao tocar mais nesse widget a partir do canal de status/
		narracao. O widget continua existindo (mostra a mensagem inicial),
		so nao e mais atualizado dinamicamente.
		"""
		return

	def _confirm_or_rename_output(self, output_dir: str, safe_name: str) -> str | None:
		"""
		Verifica duplicata de .nvda-addon em output_dir antes de empacotar (5.5 R:b).
		Retorna:
		  - caminho original: usuario confirma substituicao (Sim)
		  - caminho com timestamp: usuario quer novo nome (Nao)
		  - None: apenas em caso de erro inesperado
		"""
		target = os.path.join(output_dir, f"{safe_name}.nvda-addon")
		if not os.path.exists(target):
			return target
		dlg = wx.MessageDialog(
			self,
			f"O arquivo '{safe_name}.nvda-addon' ja existe em addons_gerados.\n\n"
			"Clique em Sim para substituir ou Nao para salvar com nome diferente (sufixo de data/hora).",
			"NVDAStudio - Arquivo ja existe",
			wx.YES_NO | wx.ICON_QUESTION,
		)
		gui.mainFrame.prePopup()
		resp = dlg.ShowModal()
		dlg.Destroy()
		gui.mainFrame.postPopup()
		if resp == wx.ID_YES:
			return target
		ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
		return os.path.join(output_dir, f"{safe_name}_{ts}.nvda-addon")

	def _show_error(self, msg: str):
		"""Exibe erro inline no chat (sem popup modal). Deve ser chamado do thread UI.

		BUGFIX (achado de auditoria 2026-08-04): os 4 chamadores passam
		texto de excecao Python cru (`f"...: {exc}"`) -- diferente do
		caminho de erro estruturado de _display_result(), que usa
		`result.error` ja curado, este nunca passava por
		sanitize_user_visible_text(). Um usuario cego podia ouvir fragmento
		de stack/jargao tecnico lido palavra por palavra. Mesmo tratamento
		de _handle_status() (que ja sanitiza internamente, nao delega pro
		chamador).
		"""
		clean_msg = sanitize_user_visible_text(msg) or "Ocorreu um erro inesperado."
		self._chat_append(f"Assistente:\nErro: {clean_msg}")
		ui.message(f"NVDAStudio: erro. {clean_msg[:150]}")

	def _on_close(self, event):
		"""Para o timer antes de destruir o dialog (WX-A11Y-010)."""
		global _current_dialog
		if self._announce_timer.IsRunning():
			self._announce_timer.Stop()
		if _current_dialog is self:
			_current_dialog = None
		gui.mainFrame.postPopup()
		self.Destroy()


_current_dialog: "NVDAStudioDialog | None" = None


def get_current_dialog() -> "NVDAStudioDialog | None":
	"""Retorna o NVDAStudioDialog atualmente aberto, se houver algum."""
	return _current_dialog


def _get_nvda_locale() -> str:
	"""
	Detecta o locale do NVDA para uso na geracao de documentacao (Q13.3).
	Retorna o locale no formato "xx_XX" (ex: "pt_BR", "en_US", "es_ES").
	Fallback: "pt_BR" se nao for possivel detectar.
	Funcao de modulo - testavel sem instancia de dialog.
	Regra 5: deteccao deterministica, sem LLM.
	"""
	if _language_handler is None:
		return "pt_BR"
	try:
		lang = _language_handler.getLanguage()
		if lang and "_" not in lang and len(lang) == 2:
			_map = {"pt": "pt_BR", "en": "en_US", "es": "es_ES",
					"de": "de_DE", "fr": "fr_FR", "it": "it_IT"}
			return _map.get(lang.lower(), f"{lang}_{lang.upper()}")
		return lang or "pt_BR"
	except Exception:
		return "pt_BR"


def deps_pendentes(declaradas, lib_dir: str) -> list[str]:
	"""Dependencias que ainda precisam ser instaladas em lib/.

	Funcao de modulo -- testavel sem instancia de dialog (mesmo padrao de
	_save_instrucoes_txt): wx.Dialog e mockado na suite, entao metodo de
	instancia nao da para exercitar diretamente.

	Compara pelo nome do pacote normalizado: pip grava `google_generativeai`
	em lib/ para a dependencia declarada `google-generativeai`, e extras como
	`pacote[extra]` nao fazem parte do nome da pasta.
	"""
	pendentes = [d for d in (declaradas or []) if d and d.strip()]
	if not pendentes or not os.path.isdir(lib_dir):
		return pendentes
	try:
		presentes = {n.lower() for n in os.listdir(lib_dir)}
	except OSError:
		return pendentes
	def _raiz(nome: str) -> str:
		return nome.split('[')[0].strip().replace('-', '_').lower()
	return [d for d in pendentes if _raiz(d) not in presentes]

def _save_instrucoes_txt(addon_name: str, output_dir: str, nvda_addon_path: str) -> str:
	"""
	Gera arquivo de instrucoes simples junto com o .nvda-addon (Q5.6).
	Retorna o caminho do arquivo gerado, ou "" se falhar.
	Funcao de modulo - testavel sem instancia de dialog.
	Regra 9: apenas escrita de texto, sem execucao.
	"""
	try:
		safe_name = addon_name.replace(" ", "_")
		txt_path = os.path.join(output_dir, f"instrucoes_{safe_name}.txt")
		nvda_file = os.path.basename(nvda_addon_path) if nvda_addon_path else f"{safe_name}.nvda-addon"
		conteudo = (
			f"Instrucoes de instalacao e uso - {addon_name}\n"
			f"Gerado pelo NVDAStudio\n"
			f"{'=' * 50}\n\n"
			f"COMO INSTALAR\n"
			f"1. Localize o arquivo: {nvda_file}\n"
			f"2. Pressione Enter sobre o arquivo para abri-lo com o NVDA.\n"
			f"3. O NVDA ira perguntar se deseja instalar o addon. Confirme com Sim.\n"
			f"4. Reinicie o NVDA quando solicitado.\n\n"
			f"COMO USAR\n"
			f"Apos instalar e reiniciar o NVDA, o addon '{addon_name}' estara ativo.\n"
			f"Consulte o guia do usuario do addon pelo menu:\n"
			f"Menu NVDA > Ajuda > Guia do usuario de '{addon_name}'\n\n"
			f"REMOVER O ADDON\n"
			f"Menu NVDA > Ferramentas > Gerenciar addons > selecione '{addon_name}' > Remover.\n\n"
			f"SUPORTE\n"
			f"Este addon foi criado com o NVDAStudio - Criador Autonomo de Addons com IA.\n"
		)
		with open(txt_path, "w", encoding="utf-8") as fh:
			fh.write(conteudo)
		_logger.info("[OK] instrucoes.txt salvo: %s", txt_path)
		return txt_path
	except Exception as exc:
		_logger.warning("[AVISO] _save_instrucoes_txt falhou: %s", exc)
		return ""
