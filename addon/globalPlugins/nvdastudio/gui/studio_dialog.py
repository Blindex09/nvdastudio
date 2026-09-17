import datetime
import json
import os
import queue
import re
import shutil
import tempfile
import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
	from ..core.orch_types import OrchestrationResult

import wx
import gui
import ui

try:
	import languageHandler as _language_handler  # type: ignore[import]
except ImportError:
	_language_handler = None  # type: ignore[assignment]

from .agent_progress import AgentProgress
from ..memory.conversation_manager import conversation
from ..memory.narration import narrate
from ..builder.addon_builder import (
	extract_code_blocks, save_addon_files, package_addon, AddonBuilderError,
	bundle_addon_dependencies,
	validate_addon_structure, fix_addon_structure,
	name_from_manifest_blocks,
	load_artifact_blocks,
)
from .settings_panel import get_output_dir
from ..ai.clarifier import (
	SAFE_CLARIFICATION_QUESTION,
	analyze_query,
	build_enriched_query,
)
from ..ai.llm_factory import create_llm_client, call_with_structured_output
from ..builder.addon_loader import (
	AddonContext, load_addon_from_blocks, load_addon_from_folder, load_addon_from_nvda_addon,
)
from ..builder.trajectory_compressor import compressor as trajectory_compressor
from ..memory.session_memory import memory, resolver_dir_do_banco
from ..builder.nvda_context import PROMPT_VERSION, NVDA_ADDON_CHAT_SYSTEM_LITE as NVDA_ADDON_CHAT_SYSTEM
from ..utils.logger import get_logger, log_decision
from ..utils.user_visible_text import sanitize_user_visible_text, summarize_generation_error
MODULE_VERSION = "6.1.0"

# Janela curta (nao unicidade global): uma frase legitima pode reaparecer
# muito depois numa sessao longa -- so o eco PROXIMO, das retentativas de um
# mesmo step, e ruido a descartar.
_JANELA_NARRACAO = 8

_VISIBLE_PROGRESS_LABELS = {
	"code_generation": "Gerando o código do addon.",
}


def _is_internal_agent_detail(detail: str) -> bool:
	"""Impede que prompt, contexto e código bruto entrem no chat acessível."""
	texto = (detail or "").strip()
	marcadores = (
		"MODO ITERATIVO", "ADDON EXISTENTE:", "--- manifest.ini ---",
		"--- globalPlugins/", "IMPORTANTE — plano minimo",
		"Mudancas solicitadas pelo usuario:", "Gere o addon modificado",
	)
	return any(texto.startswith(marcador) for marcador in marcadores)


def _natural_progress_detail(event: str, detail: str) -> str:
	"""Converte eventos internos em texto seguro para o histórico do usuário.

	O driver agentico pode emitir o nome do step ou o envelope JSON final do
	droid. Nenhum dos dois é uma mensagem de conversa e não deve vazar para a
	interface acessível.
	"""
	texto = (detail or "").strip()
	if not texto:
		return ""
	if event == "EXECUTANDO" and texto in _VISIBLE_PROGRESS_LABELS:
		return _VISIBLE_PROGRESS_LABELS[texto]
	if texto.startswith("{"):
		try:
			payload = json.loads(texto)
		except (json.JSONDecodeError, TypeError):
			payload = None
		if isinstance(payload, dict) and payload.get("type") == "result":
			return ""
		if isinstance(payload, dict):
			notificacao = payload.get("params", {}).get("notification", {})
			if isinstance(notificacao, dict):
				tipo = str(notificacao.get("type") or "").casefold()
				if tipo == "assistant_text_delta":
					return str(notificacao.get("textDelta") or "").strip()[:240]
				if tipo in {"tool_call", "tool_progress", "tool_progress_update", "tool_result", "tool_execution_phase_changed"}:
					tool = notificacao.get("toolUse")
					tool = tool if isinstance(tool, dict) else {}
					update = notificacao.get("update")
					update = update if isinstance(update, dict) else {}
					source = update or tool or notificacao
					name = (source.get("toolName") or source.get("tool_name") or
							notificacao.get("toolName") or source.get("name") or "ferramenta")
					if tipo == "tool_result":
						return f"A ferramenta {name} terminou a operação."
					if tipo == "tool_execution_phase_changed":
						phase = str(notificacao.get("phase") or update.get("phase") or "executando").casefold()
						fase = {"queued": "foi colocada na fila", "executing": "está executando", "completed": "concluiu"}.get(phase, "está trabalhando")
						return f"A ferramenta {name} {fase}."
					texto_update = update.get("text") or update.get("fullOutput")
					if isinstance(texto_update, str) and texto_update.strip():
						return f"A ferramenta {name}: {texto_update.strip()[:180]}"
					parameters = source.get("parameters") or source.get("input") or {}
					alvo = parameters.get("summary") or parameters.get("path") or parameters.get("filePath") or parameters.get("command") if isinstance(parameters, dict) else ""
					alvo_text = f" ({str(alvo)[:100]})" if alvo else ""
					return f"Vou usar a ferramenta {name}{alvo_text} para realizar esta etapa."
				if tipo == "agent_turn_completed":
					return "Turno do agente concluído."
				if tipo == "create_message":
					message = notificacao.get("message")
					if isinstance(message, dict):
						content = message.get("content", [])
						texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
						return "\n".join(t for t in texts if t).strip()
			# Eventos de stream variam entre versões do CLI. Extraímos somente
			# texto curto ou uma descrição de ferramenta; o envelope nunca vaza.
			for chave in ("text", "delta", "message", "content"):
				valor = payload.get(chave)
				if isinstance(valor, str) and valor.strip():
					return valor.strip()[:240]
			tipo = str(payload.get("type") or payload.get("event") or "").casefold()
			if "tool" in tipo:
				name = payload.get("toolName") or payload.get("tool_name") or payload.get("name") or "ferramenta"
				return f"Vou usar a ferramenta {name} para realizar esta etapa."
			return ""
	return texto


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



def _is_path_within(base_path: str, candidate_path: str) -> bool:
	"""True se candidate estiver dentro de base, sem falhar entre unidades."""
	base = os.path.abspath(base_path)
	candidate = os.path.abspath(candidate_path)
	try:
		return os.path.commonpath((base, candidate)) == base
	except ValueError:
		return False


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
					"description": (
						"Use run_pipeline quando o usuario pedir explicitamente para criar, "
						"corrigir, modificar, testar, documentar ou empacotar o addon. Uma "
						"ordem explicita do usuario autoriza o encaminhamento ao pipeline."
					),
				},
				"message": {
					"type": "string",
					"description": (
						"Resposta natural ao usuario, coerente com a action escolhida e com "
						"a autorizacao expressa na mensagem atual."
					),
				},
				"task_specification": {
					"type": "string",
					"description": (
						"Em run_pipeline, descreva todas as alteracoes e o empacotamento "
						"solicitados; nos demais casos, use string vazia."
					),
				},
				"package_requested": {
					"type": "boolean",
					"description": (
						"True somente quando o usuario pediu que o resultado seja empacotado "
						"para instalacao depois das alteracoes e testes."
					),
				},
				"task_complexity": {
					"type": "string",
					"enum": ["low", "medium", "high"],
					"description": "Complexidade semântica do trabalho solicitado.",
				},
				"routing_preference": {
					"type": "string",
					"enum": ["balanced", "quality", "cost", "speed", "privacy"],
					"description": (
						"Use balanced por padrão. Só escolha outra prioridade quando o "
						"usuário a tiver indicado."
					),
				},
				"required_model_capabilities": {
					"type": "array",
					"items": {
						"type": "string",
						"enum": ["vision", "audio", "video"],
					},
					"description": (
						"Capacidades necessárias somente para dados multimodais "
						"entregues ao agente nesta tarefa."
					),
				},
			},
			"required": [
				"action", "message", "task_specification", "package_requested",
				"task_complexity", "routing_preference",
				"required_model_capabilities",
			],
			"additionalProperties": False,
		},
	},
}

_ANNOUNCE_TIMER_MS = 600


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
		self._last_blocks: list[dict] = []
		self._last_addon_folder: str = ""
		self._current_addon_name: str = ""
		self._last_query: str = ""  # fluxos 14.2 R:c: armazenado para retry em caso de falha
		self._session_count = memory.get_session_count()
		# Modo conversacional/iterativo
		self._loaded_addon_context: AddonContext | None = None
		self._chat_history: list[dict] = []   # [{"role": "user"|"assistant", "text": str}]
		self._waiting_for_packaging_approval = False
		self._package_after_current_build = False
		self._pending_redirect_query = None  # interrupcao ativa: nova instrucao enquanto roda
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
				dlg = gui.message.MessageDialog(
					parent=self, message=message, title="Aprovacao necessaria",
					dialogType=gui.message.DialogType.WARNING,
					buttons=gui.message.DefaultButtonSet.YES_NO,
				)
				result = dlg.ShowModal()
				dlg.Destroy()
				self._tool_approval_result = (result == gui.message.ReturnCode.YES)
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
			)
			conversation.set_callbacks(
				on_status=lambda msg: wx.CallAfter(self._handle_status, msg),
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
		# Interface principal: criação, conversa e histórico no mesmo painel.
		outer.Add(self._build_left_panel(self), proportion=1, flag=wx.EXPAND | wx.ALL, border=6)
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
		row_run = wx.BoxSizer(wx.HORIZONTAL)
		self._btn_run = wx.Button(panel, label="&Criar Addon")
		self._btn_run.Bind(wx.EVT_BUTTON, self._on_run)
		row_run.Add(self._btn_run, flag=wx.RIGHT, border=6)
		# Direcao ao vivo: manda um ajuste SEM parar -- o agente incorpora na
		# proxima rodada, mantendo o que ja fez (estilo ferramenta de ponta).
		# Escondido fora de um build; aparece quando o Criar vira Parar.
		self._btn_steer = wx.Button(panel, label="&Enviar ajuste")
		self._btn_steer.Bind(wx.EVT_BUTTON, self._on_steer)
		self._btn_steer.SetToolTip(
			"Envia o texto do campo acima como ajuste para a geração em andamento, "
			"sem interrompê-la. O agente incorpora na próxima rodada."
		)
		self._btn_steer.Hide()
		row_run.Add(self._btn_steer)
		sizer.Add(row_run, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=6)
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
		self._btn_close = wx.Button(panel, wx.ID_CLOSE, label="&Fechar")
		self._btn_close.Bind(wx.EVT_BUTTON, lambda e: self.Close())
		row_buttons.Add(self._btn_close)
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
		btn_load = wx.Button(panel, label="&Carregar Addon")
		btn_load.Bind(wx.EVT_BUTTON, self._on_load_addon)
		btn_load.SetToolTip("Carrega um addon empacotado ou uma pasta de addon para análise")
		row_addon.Add(btn_load)
		sizer.Add(row_addon, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM, border=6)

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
		# Fora de um build nao ha o que ajustar: esconde o botao de steer.
		if getattr(self, "_btn_steer", None) is not None:
			self._btn_steer.Hide()
			self._btn_steer.GetParent().Layout()
		self._update_input_label("Descreva o addon que deseja criar ou modificar:")

	def _on_steer(self, _event):
		"""Direcao ao vivo: envia o texto do campo como AJUSTE para a geracao em
		andamento, sem interromper. O orchestrator o incorpora na proxima rodada
		(mantem o que ja foi gerado -- diferente do Parar+texto, que reinicia)."""
		ajuste = self._input.GetValue().strip()
		if not ajuste:
			ui.message("Digite o ajuste no campo antes de enviar.")
			return
		self._input.SetValue("")
		self._orchestrator.steer_pipeline(ajuste)
		self._chat_append(f"Você (ajuste):\n{ajuste}")
		self._chat_append("Sistema:\nAjuste enviado. A sessão vai continuar com sua nova instrução.")
		ui.message("Ajuste enviado para a geração em andamento.")

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
		self._input.Enable()
		self._btn_run.SetLabel("&Parar")
		self._btn_run.Enable()
		# Durante o build o campo vira canal de ajuste ao vivo: mostra o botao.
		if getattr(self, "_btn_steer", None) is not None:
			self._btn_steer.Show()
			self._btn_steer.GetParent().Layout()
		self._update_input_label("Progresso (ou digite um ajuste e clique Enviar ajuste):")

	def _on_run(self, _event):
		"""Botao Criar Addon ou Parar: pipeline conversacional v2.0.0."""
		if self._btn_run.GetLabel() in ("Parar", "&Parar", "Cancelar", "&Cancelar"):
			redirect_query = self._input.GetValue().strip()
			if redirect_query:
				# Redirecionamento ativo: a sessão RPC interrompe o turno atual,
				# preserva o workdir/contexto e entrega a nova instrução ao agente.
				self._input.SetValue("")
				self._chat_append(f"Você:\n{redirect_query}")
				self._orchestrator.steer_pipeline(redirect_query)
				self._chat_append("Sistema:\nA sessão recebeu a nova instrução e vai continuar com o contexto atual.")
				ui.message("Nova instrução enviada; o agente continuará com o contexto atual.")
				self._disable_run_btn_as_cancel()
				return
			else:
				self._chat_append("Sistema:\nParada solicitada pelo usuário.")
				ui.message("Parada solicitada.")
				self._btn_run.SetLabel("Parando...")
			if not redirect_query:
				self._orchestrator.cancel_pipeline()
			self._btn_run.Disable()
			return

		query = self._input.GetValue().strip()
		if not query:
			ui.message("Por favor, descreva o addon que deseja criar ou modificar.")
			return

		# Limpar o campo de texto
		self._input.SetValue("")

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

	def _ask_clarification_inline(self, questions: list[str], timeout: float | None = None) -> list[str]:
		"""
		Pergunta(s) de esclarecimento inline no chat -- sem dialogo modal. As
		perguntas em si vem da IA (clarifier.analyze_query); aqui apenas
		apresenta no historico, aguarda uma resposta livre do usuario e usa
		uma IA para extrair uma resposta por pergunta, sem exigir formato
		fixo (o usuario pode responder tudo numa frase so ou uma por linha).
		Chamado de thread daemon; a UI e atualizada via wx.CallAfter.
		"""
		self._clarification_event.clear()
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
		if getattr(self._orchestrator, "_cancel_requested", False):
			return ["" for _ in questions]

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
			self._disable_run_btn_as_cancel()
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
					user_level=clarification.user_level,
					addon_architecture=clarification.addon_architecture,
					task_complexity=clarification.task_complexity,
						routing_preference=clarification.routing_preference,
						required_model_capabilities=clarification.required_model_capabilities,
				)
			else:
				enriched = build_enriched_query(
					query, [], [],
					user_level=clarification.user_level,
					addon_architecture=clarification.addon_architecture,
					task_complexity=clarification.task_complexity,
					routing_preference=clarification.routing_preference,
					required_model_capabilities=clarification.required_model_capabilities,
				)

			# Q13.3: injeta locale do NVDA para que doc_generator gere no idioma certo
			nvda_locale = _get_nvda_locale()
			enriched += f"\n\n[NVDA_LOCALE: {nvda_locale}]"

			wx.CallAfter(self._set_status, "Iniciando pipeline autonoma...")
			self._orchestrator.run_async(
				enriched,
				package_requested=clarification.package_requested,
			)
		except Exception as exc:
			wx.CallAfter(self._show_error, str(exc))
			wx.CallAfter(self._enable_run_btn)

	# ------------------------------------------------------------------
	# Handlers do modo conversacional (Aba 2)
	# ------------------------------------------------------------------

	def _on_load_addon(self, _event):
		"""Carrega um addon empacotado ou uma pasta escolhida pelo usuário."""
		choice = wx.SingleChoiceDialog(
			self,
			"Escolha como deseja carregar o addon:",
			"NVDAStudio - Carregar addon",
			["Arquivo .nvda-addon", "Pasta do addon"],
		)
		gui.mainFrame.prePopup()
		try:
			if choice.ShowModal() != wx.ID_OK:
				return
			load_folder = choice.GetSelection() == 1
		finally:
			choice.Destroy()
			gui.mainFrame.postPopup()

		if load_folder:
			dlg = wx.DirDialog(
				self,
				message="Selecione a pasta raiz do addon (onde está o manifest.ini)",
				defaultPath=os.path.join(os.environ.get("APPDATA", ""), "nvda", "addons"),
				style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST,
			)
		else:
			dlg = wx.FileDialog(
				self,
				message="Selecione o arquivo .nvda-addon",
				defaultDir=get_output_dir(),
				wildcard="Addons NVDA (*.nvda-addon)|*.nvda-addon|Todos os arquivos (*.*)|*.*",
				style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
			)
		gui.mainFrame.prePopup()
		try:
			if dlg.ShowModal() != wx.ID_OK:
				return
			path = dlg.GetPath()
		finally:
			dlg.Destroy()
			gui.mainFrame.postPopup()
		try:
			ctx = load_addon_from_folder(path) if load_folder else load_addon_from_nvda_addon(path)
			self._load_addon_context(ctx)
		except Exception as exc:
			self._show_error(f"Nao foi possivel carregar o addon: {exc}")

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
			package_requested = bool(payload.get("package_requested", False))
			task_complexity = str(payload.get("task_complexity", "medium")).lower()
			if task_complexity not in ("low", "medium", "high"):
				task_complexity = "medium"
			routing_preference = str(payload.get("routing_preference", "balanced")).lower()
			if routing_preference not in ("balanced", "quality", "cost", "speed", "privacy"):
				routing_preference = "balanced"
			required_model_capabilities = [
				str(capability).lower()
				for capability in payload.get("required_model_capabilities", [])
				if str(capability).lower() in {"vision", "audio", "video"}
			]

			if not message:
				raise ValueError("A IA retornou uma mensagem vazia.")

			self._chat_history.append({"role": "assistant", "text": message})
			wx.CallAfter(self._chat_finish, f"Assistente:\n{message}")

			if action == "run_pipeline":
				self._package_after_current_build = package_requested
				if not task_specification:
					raise ValueError("A IA solicitou execução sem especificação técnica.")
				task_specification += (
					f"\n[TASK-COMPLEXITY: {task_complexity}]"
					f"\n[ROUTING-PREFERENCE: {routing_preference}]"
				)
				if required_model_capabilities:
					task_specification += (
						"\n[MODEL-CAPABILITIES: "
						+ ",".join(sorted(set(required_model_capabilities)))
						+ "]"
					)
				if self._loaded_addon_context:
					wx.CallAfter(self._trigger_iterative_pipeline, task_specification)
				else:
					wx.CallAfter(self._trigger_creation_pipeline, task_specification)

		except Exception as exc:
			_logger.error("[ERRO] chat: %s", exc)
			# Falha fechada: indisponibilidade do roteador semântico nunca vira
			# autorização para gerar por suposição. Mantemos a conversa utilizável
			# com uma pergunta simples que um usuário iniciante consegue responder.
			self._chat_history.append({
				"role": "assistant",
				"text": SAFE_CLARIFICATION_QUESTION,
			})
			wx.CallAfter(
				self._chat_finish,
				f"Assistente:\n{SAFE_CLARIFICATION_QUESTION}",
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

		# A copia de trabalho ja contem o addon completo. O agente deve editar
		# somente o necessario e provar que o conjunto final continua valido.
		enriched_query = (
			f"MODO ITERATIVO — Modifique o addon no diretorio de trabalho atual.\n"
			f"O caminho Origem abaixo e apenas referencia; nao edite nem empacote a origem.\n\n"
			f"{addon_ctx_text}"
			f"{past_chat_text}\n\n"
			f"Mudancas solicitadas pelo usuario: {change_description}\n\n"
			f"Preserve os arquivos e comportamentos nao relacionados. Edite apenas "
			f"o necessario, rode as verificacoes relevantes e conclua somente quando "
			f"o addon completo estiver valido."
		)

		# Pipeline de modificacao: sem troca de aba (UI unificada v5.0.0)
		ui.message("NVDAStudio: iniciando pipeline de modificacao.")
		self._disable_run_btn_as_cancel()
		self._current_addon_name = addon_name
		self._set_status("Pipeline de modificacao iniciado...")
		self._agent_progress = AgentProgress()
		from ..builder.iteration_workspace import prepare_iteration_workspace
		workdir = prepare_iteration_workspace(self._loaded_addon_context)
		self._orchestrator.run_async(
			enriched_query,
			workdir=workdir,
			package_requested=self._package_after_current_build,
		)


	def _trigger_creation_pipeline(self, change_description: str):
		"""Dispara o mesmo agente usado para criacao e modificacao."""
		ui.message("NVDAStudio: iniciando pipeline de criacao.")
		self._disable_run_btn_as_cancel()
		self._set_status("Pipeline de criacao iniciado...")
		self._agent_progress = AgentProgress()
		self._orchestrator.run_async(
			change_description,
			package_requested=self._package_after_current_build,
		)

	def _on_progress(self, event: str, detail: str):
		"""Entrega apenas eventos conversacionais tipados do agente."""
		if event == "EXECUTANDO" and detail.lstrip().startswith("{"):
			progress = getattr(self, "_agent_progress", None)
			if progress is None:
				progress = self._agent_progress = AgentProgress()
			for message in progress.consume(detail):
				wx.CallAfter(self._chat_append, message)
			return
		if _is_internal_agent_detail(detail):
			return
		clean = sanitize_user_visible_text(_natural_progress_detail(event, detail))
		if clean:
			wx.CallAfter(self._chat_append, clean)
			wx.CallAfter(self._set_status, clean)

	def _on_complete(self, result):
		"""Callback final do Orchestrator. Chamado de thread — usa CallAfter (Regra 15)."""
		wx.CallAfter(self._display_result, result)

	def _record_result_session(
		self, result, addon_name: str, *, success: bool, summary: str,
	) -> None:
		"""Registra a conclusao somente no marco de entrega correspondente.

		Quando o pedido inclui pacote, fontes validados ainda nao significam
		entrega concluida. Nesse caso o chamador usa este metodo apenas depois do
		quality gate do arquivo final (ou para registrar uma falha desse gate).
		"""
		status = "success" if success else "failed"
		if getattr(result, "_recorded_delivery_status", "") == status:
			return
		result._recorded_delivery_status = status
		step_results = list(getattr(result, "step_results", []) or [])
		steps_ok = sum(1 for step in step_results if getattr(step, "approved", False))
		total_tokens = getattr(result, "total_tokens", 0)
		memory.save_session(
			query=getattr(result, "query", ""),
			addon_name=addon_name,
			plan_id=getattr(result, "plan_id", "agentic"),
			steps_ok=steps_ok,
			steps_total=len(step_results),
			retries=getattr(result, "total_retries", 0),
			success=success,
			summary=summary,
			prompt_version=PROMPT_VERSION,
			step_issues=[
				issue
				for step in step_results
				for issue in (getattr(step, "issues", []) or [])
			],
			total_tokens=total_tokens,
		)
		log_decision(
			_logger, "sessao_salva",
			f"plan={getattr(result, 'plan_id', 'agentic')} steps_ok={steps_ok} "
			f"prompt_version={PROMPT_VERSION} delivery={status}",
		)

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
			# Prefere o contrato estruturado do agente; a extracao de texto fica
			# apenas como degradacao para resultados aprovados sem lista de arquivos.
			artifact_files = list(getattr(result, "artifact_files", []) or [])
			if result.artifact_dir and artifact_files:
				# O agente ja entregou nomes/caminhos estruturados. Ler esses arquivos
				# diretamente evita interpretar fences presentes em readme.html como
				# novos module_N.py.
				blocks = load_artifact_blocks(result.artifact_dir, artifact_files)
			else:
				blocks = self._collect_all_blocks(result)
			if not blocks:
				source = result.final_output
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
			# porque o manifest não veio na resposta. Só a ausência de código Python
			# é irrecuperável; um addon sem manifest recebe o fallback mínimo.
			if not python_ok:
				result.success = False
				result.error = (
					"A criação não produziu um addon completo: falta código Python válido."
				)
				self._last_blocks = []
				return self._display_result(result)
			self._last_blocks = blocks
			_logger.info("[OK] _last_blocks: %d bloco(s) coletado(s): %s",
						 len(blocks), [b.get("filename","?") for b in blocks])

			# Monta display limpo: mensagem natural do LLM + lista de arquivos gerados.
			# O final_output (uso interno para extracao de blocos) nunca e mostrado
			# diretamente — ele continha outputs de todos os steps (web_research, etc.)
			# que nao tem valor para o usuario final.
			completed_msg = getattr(result, "completed_message", "") or "Arquivos do addon validados."
			addon_name = self._current_addon_name or "addon_gerado"
			steps_ok = sum(1 for r in result.step_results if r.approved)
			# Prefere o nome declarado no manifest.ini gerado (v5.12.0)
			manifest_name = name_from_manifest_blocks(blocks)
			if manifest_name:
				addon_name = manifest_name
			self._current_addon_name = addon_name
			self._last_addon_folder = ""
			package_requested = bool(
				getattr(result, "package_requested", False)
				or self._package_after_current_build
			)

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
			if result.artifact_dir and os.path.isdir(result.artifact_dir):
				self._loaded_addon_context = load_addon_from_folder(result.artifact_dir)
			wx.CallAfter(
				self._lbl_addon_loaded.SetLabel,
				f"Addon carregado: {addon_name} (modo iterativo ativo)",
			)
			log_decision(
				_logger, "addon_auto_carregado_pos_criacao",
				f"nome={addon_name} arquivos={len(self._loaded_addon_context.python_files)}",
			)

			if not package_requested:
				self._record_result_session(
					result,
					addon_name,
					success=True,
					summary=f"{steps_ok}/{len(result.step_results)} steps aprovados; fontes validados",
				)
			pergunta_final = "Quer ajustar mais alguma coisa ou posso empacotar o addon?"
			if package_requested:
				pergunta_final = "Vou gerar o pacote solicitado com os arquivos validados."
			if blocks:
				file_lines = "\n".join(
					f"  {b.get('filename') or b.get('language', 'arquivo')}"
					for b in blocks
				)
				self._chat_append(
					f"{completed_msg}"
					"\n\n"
					f"Arquivos gerados ({len(blocks)}):\n{file_lines}"
					"\n\n"
					f"{pergunta_final}"
				)
			else:
				self._chat_append(
					f"{completed_msg}"
					"\n\n"
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
			if package_requested:
				self._package_after_current_build = False
				self._waiting_for_packaging_approval = False
				self._chat_append(
					"Assistente:\nOs testes e as correções solicitadas foram processados. "
					"Agora vou empacotar o addon."
				)
				# Ja estamos na thread da UI. Iniciar agora torna o empacotamento
				# parte da mesma entrega, em vez de deixa-lo numa fila que pode nao
				# executar antes de a sessao ser considerada concluida.
				self._run_packaging_process()
				return

			ui.message(
				"Desenvolvimento concluído. Quer ajustar mais alguma coisa ou posso empacotar o addon?"
			)
		else:
			raw_err = result.error or "Nao foi possivel completar o plano."
			err = summarize_generation_error(raw_err)
			self._set_status(f"Erro: {err}")
			# 7.3 R:a+c: inclui sugestao de reformulacao + fluxos 14.2 R:c: botao Tentar Novamente
			err_msg = (
				f"{err}\n\n"
				"Dica: os detalhes tecnicos foram registrados no log. Tente novamente; "
				"se o problema persistir, envie o log para analise."
			)
			dlg = gui.message.MessageDialog(
				parent=self, message=err_msg, title="NVDAStudio - Erro na geracao",
				dialogType=gui.message.DialogType.ERROR,
				buttons=(
					gui.message.Button(gui.message.ReturnCode.YES, "&Tentar Novamente"),
					gui.message.Button(gui.message.ReturnCode.NO, "&Fechar", fallbackAction=True),
				),
			)
			gui.mainFrame.prePopup()
			resp = dlg.ShowModal()
			dlg.Destroy()
			gui.mainFrame.postPopup()
			ui.message(f"NVDAStudio: erro na geracao. {err[:80]}")
			if resp == gui.message.ReturnCode.YES and self._last_query:
				self._disable_run_btn_as_cancel()
				self._set_status("Repetindo o pedido...")
				thread = threading.Thread(
					target=self._clarify_and_run,
					args=(self._last_query,),
					daemon=True,
				)
				thread.start()


	def _process_packaging_decision(self, query: str):
		"""
		Classifica a resposta do usuario sobre o empacotamento em thread background.
		Intent pode ser:
		- "package": O usuario quer empacotar/concluir.
		- "modify": O usuario quer fazer mais alteracoes/continuar.
		"""
		intent = "modify"  # default
		package_after_modification = False
		try:
			system_prompt = (
				"Interprete semanticamente a resposta livre do usuário à pergunta final. "
				"Classifique como package quando ele considera o trabalho pronto e autoriza "
				"criar o pacote agora, ou modify quando ainda deseja conversar, testar ou "
				"alterar algo. Se ele pedir alterações e também o pacote ao final, marque "
				"package_after_modification=true. Não decida por palavras isoladas."
			)
			response_schema = {
				"type": "json_schema",
				"json_schema": {
					"name": "packaging_decision",
					"strict": True,
					"schema": {
						"type": "object",
						"properties": {
							"intent": {"type": "string", "enum": ["package", "modify"]},
							"package_after_modification": {"type": "boolean"},
						},
						"required": ["intent", "package_after_modification"],
						"additionalProperties": False,
					},
				},
			}
			resp = call_with_structured_output(
				f"Resposta do usuário: {query}",
				response_schema,
				system_override=system_prompt,
			)
			content = (resp.content or "").strip()
			data = json.loads(content)
			parsed_intent = data.get("intent", "modify")
			intent = parsed_intent if parsed_intent in {"package", "modify"} else "modify"
			package_after_modification = bool(data.get("package_after_modification", False))
		except Exception as e:
			_logger.warning("[IntentClassifier] Falha na chamada da IA para empacotamento: %s", e)
			intent = "modify"

		if intent == "package":
			wx.CallAfter(self._run_packaging_process)
		else:
			self._package_after_current_build = package_after_modification
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
		"""Extrai artefatos dos resultados aprovados sem inferir tipos de etapa."""
		seen: set[str] = set()
		blocks: list[dict] = []
		for step in getattr(result, "step_results", []) or []:
			if not getattr(step, "approved", False) or not getattr(step, "output", ""):
				continue
			for block in extract_code_blocks(step.output):
				filename = str(block.get("filename", "")).strip()
				if filename and filename in seen:
					continue
				if filename:
					seen.add(filename)
				blocks.append(block)
		return blocks

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
		staging_dir = ""
		try:
			output_dir = get_output_dir()
			os.makedirs(output_dir, exist_ok=True)

			# A pasta configurada e uma pasta de ENTREGA. Fontes, testes e o
			# pacote pendente ficam em workspaces privados/temporarios.
			output_abs = os.path.abspath(output_dir)

			def _inside_public_output(path: str) -> bool:
				try:
					return os.path.commonpath((os.path.abspath(path), output_abs)) == output_abs
				except ValueError:
					return False

			# Reutiliza pasta existente quando ela ja e privada.
			if self._last_addon_folder and os.path.isdir(self._last_addon_folder):
				if _inside_public_output(self._last_addon_folder):
					from ..builder.iteration_workspace import prepare_iteration_workspace
					context = load_addon_from_folder(self._last_addon_folder)
					addon_folder = prepare_iteration_workspace(context)
					self._last_addon_folder = addon_folder
				else:
					addon_folder = self._last_addon_folder
				_logger.info("[OK] _on_package: reutilizando pasta %s", addon_folder)
			elif getattr(self._last_result, "artifact_dir", ""):
				from ..builder.iteration_workspace import prepare_iteration_workspace
				artifact_dir = self._last_result.artifact_dir
				if _inside_public_output(artifact_dir):
					context = load_addon_from_folder(artifact_dir)
					addon_folder = prepare_iteration_workspace(context)
				else:
					addon_folder = artifact_dir
				self._last_addon_folder = addon_folder
			else:
				# Blocos sem artifact_dir ganham workspace privado, nunca a pasta
				# publica escolhida pelo usuario.
				nvda_dir = tempfile.mkdtemp(prefix="nvdastudio_sources_")
				addon_folder, _ = save_addon_files(
					self._last_blocks, nvda_dir, addon_name, use_timestamp=True,
				)
				self._last_addon_folder = addon_folder
				_logger.info("[OK] _on_package: pasta criada em %s", addon_folder)

			safe_name = addon_name.replace(" ", "_")
			if self._instalar_dependencias_se_preciso(addon_folder, addon_name):
				return  # instalacao em andamento; reentra por _on_package ao terminar
			fix_addon_structure(addon_folder)
			_fix_actions, _remaining_problems = self._auto_fix_structural_issues(addon_folder, addon_name)
			if _remaining_problems:
				problems_txt = "\n".join(f"- {p}" for p in _remaining_problems)
				if self._last_result is not None:
					self._last_result.success = False
					self._last_result.error = "Problemas estruturais nao resolvidos impediram a entrega."
					self._record_result_session(
						self._last_result, addon_name, success=False,
						summary="Pacote nao liberado: problemas estruturais nao resolvidos",
					)
				self._chat_append(
					f"Assistente:\nAinda restam {len(_remaining_problems)} problema(s) estrutural(is):\n"
					f"{problems_txt}\n\nO pacote nao foi liberado. Os fontes de trabalho foram "
					"preservados fora da pasta de entrega para uma nova correcao."
				)
				ui.message("NVDAStudio: pacote bloqueado por problemas estruturais. Veja o historico.")
				_logger.error(
					"[QUALITY_GATE] Entrega bloqueada por %d problema(s) estrutural(is).",
					len(_remaining_problems),
				)
				return

			staging_dir = tempfile.mkdtemp(prefix="nvdastudio_package_")
			nvda_addon_path = package_addon(
				addon_folder,
				os.path.join(staging_dir, f"{safe_name}.pending.nvda-addon")
			)
			# Quality gate final: valida o arquivo empacotado, não apenas a pasta
			# intermediária. O ZIP é aberto, verificado e executado em isolamento.
			from ..builder.code_sandbox import CodeSandbox
			final_check = CodeSandbox(timeout_sec=15).validate_final_package(nvda_addon_path)
			if not final_check.success:
				evidence = final_check.error or final_check.stderr or final_check.stdout
				_logger.error("[QUALITY_GATE] Pacote final rejeitado: %s", evidence[:1000])
				if self._last_result is not None:
					self._last_result.success = False
					self._last_result.error = "O pacote final foi rejeitado pelo quality gate."
					self._record_result_session(
						self._last_result,
						addon_name,
						success=False,
						summary="Fontes preservados; pacote final rejeitado pelo quality gate",
					)
				self._chat_append(
					"Assistente:\nA validação final falhou. O pacote não foi liberado; "
					"os arquivos foram preservados e os detalhes estão no log."
				)
				ui.message("NVDAStudio: pacote rejeitado na validação final.")
				return
			final_path = os.path.join(output_dir, f"{safe_name}.nvda-addon")
			os.replace(nvda_addon_path, final_path)
			nvda_addon_path = final_path
			if self._last_result is not None:
				self._last_result.package_path = nvda_addon_path
				self._last_result.success = True
				self._record_result_session(
					self._last_result,
					addon_name,
					success=True,
					summary=f"Addon empacotado, validado e entregue: {nvda_addon_path}",
				)
			self._set_status(f"Empacotado: {nvda_addon_path}")
			self._chat_append(f"Assistente:\nAddon empacotado e validado. Arquivo: {nvda_addon_path}")
			ui.message(f"NVDAStudio: addon empacotado com sucesso. Arquivo: {safe_name}.nvda-addon")
			_logger.info("[OK] _on_package: %s", nvda_addon_path)
		except AddonBuilderError as exc:
			if self._last_result is not None:
				self._last_result.success = False
				self._last_result.error = f"Erro ao empacotar: {exc}"
				self._record_result_session(
					self._last_result, addon_name, success=False,
					summary="Fontes preservados; empacotamento falhou",
				)
			self._show_error(f"Erro ao empacotar: {exc}")
		except Exception as exc:
			if self._last_result is not None:
				self._last_result.success = False
				self._last_result.error = f"Erro inesperado ao empacotar: {exc}"
				self._record_result_session(
					self._last_result, addon_name, success=False,
					summary="Fontes preservados; empacotamento falhou inesperadamente",
				)
			self._show_error(f"Erro inesperado ao empacotar: {exc}")
		finally:
			if staging_dir:
				shutil.rmtree(staging_dir, ignore_errors=True)

	def _on_reset(self, _event):
		"""Nova Sessao: salva historico de chat (arquivo + session_memory) e limpa tudo."""
		if self._chat_history:
			try:
				history_dir = os.path.join(resolver_dir_do_banco(), "historicos")
				os.makedirs(history_dir, exist_ok=True)
				sess_name = self._current_addon_name or "sessao"
				ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
				hist_path = os.path.join(history_dir, f"historico_{sess_name}_{ts}.txt")
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
		self._set_status("Nova sessao iniciada. Descreva o addon que deseja criar.")
		ui.message("NVDAStudio: nova sessao.")

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
			dlg = gui.message.MessageDialog(
				parent=self,
				message=f"Encontrei {n} mensagem(ns) de uma sessao anterior sobre '{addon_name}'.\n"
				"Deseja restaurar esse historico no chat?",
				title="NVDAStudio - Restaurar Historico",
				buttons=gui.message.DefaultButtonSet.YES_NO,
			)
			restore = dlg.ShowModal() == gui.message.ReturnCode.YES
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
		dlg = gui.message.MessageDialog(
			parent=self,
			message=f"O arquivo '{safe_name}.nvda-addon' ja existe em addons_gerados.\n\n"
			"Clique em Sim para substituir ou Nao para salvar com nome diferente (sufixo de data/hora).",
			title="NVDAStudio - Arquivo ja existe",
			buttons=gui.message.DefaultButtonSet.YES_NO,
		)
		gui.mainFrame.prePopup()
		resp = dlg.ShowModal()
		dlg.Destroy()
		gui.mainFrame.postPopup()
		if resp == gui.message.ReturnCode.YES:
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
		self._orchestrator.cancel_pipeline()
		self._raw_clarification_input = None
		self._clarification_event.set()
		self._tool_approval_result = False
		self._tool_approval_event.set()
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

	Funcao de modulo -- testavel sem instancia de dialog: wx.Dialog e mockado
	na suite, entao metodo de instancia nao da para exercitar diretamente.

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
