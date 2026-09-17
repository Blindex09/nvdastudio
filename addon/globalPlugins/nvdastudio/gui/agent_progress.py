"""Conversa do agente: separa mensagens do assistente de dados do protocolo."""
import json
import re

from ..utils.user_visible_text import sanitize_user_visible_text

MODULE_VERSION = "1.1.0"

_COMPLETION_CLAIM_RE = re.compile(
	r"\b(?:an[aá]lise\s+conclu[ií]da|trabalho\s+conclu[ií]do|addon\s+(?:est[aá]\s+)?(?:completo|pronto)|"
	r"corre[cç][oõ]es?\s+conclu[ií]das?|verifica[cç][oõ]es?\s+finais|todos\s+os\s+\d+\s+testes\s+passaram)\b",
	re.IGNORECASE,
)


def _execute_result_message(content: str) -> str:
	"""Traduz o resultado sem confundir stderr do unittest com teste vermelho."""
	last_ran = content.rfind("Ran ")
	last_ok = content.rfind("\nOK")
	last_failed = content.rfind("FAILED (")
	if last_ran >= 0 and last_ok > last_ran and last_ok > last_failed:
		return (
			"Os testes terminaram com resultado OK. O executor informou um código de saída "
			"inconsistente, então o NVDAStudio continuará com suas validações independentes."
		)
	if last_failed > last_ran >= 0 or "Traceback (most recent call last)" in content:
		return "Os testes encontraram problemas. O agente recebeu o relatório e continuará a correção."
	return "O comando não foi concluído nessa tentativa. O agente recebeu os detalhes e avaliará a correção."


def _tool_error_message(name: str, content: str) -> str:
	if name == "Execute":
		return _execute_result_message(content)
	if name == "Edit":
		return "A edição não pôde ser aplicada nessa tentativa. O agente ajustará a alteração e tentará novamente."
	return f"A ferramenta {name} não concluiu essa tentativa. O agente recebeu os detalhes para avaliar a correção."


def conversation_text(text: str) -> str:
	# Código cercado é um artefato, não narração. Remover antes da limpeza
	# visual, que apaga a sintaxe Markdown e tornaria o bloco indistinguível.
	text = re.sub(r"```[^\n]*\n.*?(?:```|\Z)", "", text, flags=re.S)
	return sanitize_user_visible_text(text).strip()


class AgentProgress:
	"""Uma mensagem por bloco completo; nunca ecoa mensagens role=user.

	Os deltas são acumulados até assistant_text_complete, que acontece entre
	chamadas de ferramentas, não apenas ao terminar a execução inteira.
	"""
	def __init__(self):
		self.buffers: dict[tuple[str, int], str] = {}
		self.delivered: set[tuple[str, int]] = set()
		self.tools: dict[str, str] = {}
		self.started: set[str] = set()
		self.error_notices: set[tuple[str, str]] = set()
		self.completed_turns: set[str] = set()

	def consume(self, detail: str) -> list[str]:
		try:
			payload = json.loads(detail)
		except (ValueError, TypeError):
			return []
		if not isinstance(payload, dict):
			return []
		params = payload.get("params")
		if not isinstance(params, dict):
			return []
		n = params.get("notification")
		if not isinstance(n, dict):
			return []
		kind = n.get("type")
		key = (str(n.get("messageId", "")), n.get("blockIndex", 0))
		if kind == "assistant_text_delta":
			if key not in self.delivered:
				self.buffers[key] = self.buffers.get(key, "") + str(n.get("textDelta") or "")
			return []
		if kind == "assistant_text_complete":
			return self._deliver(key, self.buffers.pop(key, ""))
		if kind == "create_message":
			message = n.get("message")
			if not isinstance(message, dict) or message.get("role") != "assistant":
				return []
			out = []
			for index, block in enumerate(message.get("content") or []):
				if isinstance(block, dict) and block.get("type") == "text":
					block_key = (str(message.get("id", "")), index)
					self.buffers.pop(block_key, None)
					out.extend(self._deliver(block_key, str(block.get("text") or "")))
			return out
		if kind == "agent_turn_completed":
			out = []
			for block_key, text in list(self.buffers.items()):
				out.extend(self._deliver(block_key, text))
			self.buffers.clear()
			turn_id = str(n.get("turnId") or n.get("messageId") or "")
			if turn_id not in self.completed_turns:
				self.completed_turns.add(turn_id)
				out.append(
					"A rodada do agente terminou. Agora o NVDAStudio executará validações "
					"independentes antes de considerar a entrega concluída."
				)
			return out
		if kind == "tool_call":
			tool = n.get("toolUse") or {}
			if not isinstance(tool, dict):
				return []
			tool_id = str(tool.get("id") or n.get("toolUseId") or "")
			name = str(tool.get("name") or n.get("toolName") or "")
			if not tool_id or tool_id in self.started:
				return []
			self.started.add(tool_id)
			self.tools[tool_id] = name
			args = tool.get("input") or {}
			path = (args.get("file_path") or args.get("path") or args.get("directory_path")) if isinstance(args, dict) else None
			action = {
				"Read": "Lendo arquivo", "Edit": "Editando arquivo", "Create": "Criando arquivo",
				"LS": "Verificando a pasta", "Glob": "Localizando arquivos", "Grep": "Pesquisando no código",
				"Execute": "Executando comando", "TodoWrite": "Atualizando as etapas do trabalho",
			}.get(name, "Usando a ferramenta " + name)
			return [f"{action} ({name})" + (f": {path}" if path else ".")]
		if kind == "tool_result" and n.get("isError"):
			name = self.tools.get(str(n.get("toolUseId") or ""), "solicitada")
			content = str(n.get("content") or "")
			message = _tool_error_message(name, content)
			signature = (name, message)
			if signature in self.error_notices:
				return []
			self.error_notices.add(signature)
			return [message]
		# stdout, comandos, argumentos, thinking e eventos de fila ficam no log.
		return []

	def _deliver(self, key: tuple[str, int], text: str) -> list[str]:
		if key in self.delivered or not text:
			return []
		self.delivered.add(key)
		text = conversation_text(text)
		if text and _COMPLETION_CLAIM_RE.search(text):
			text += (
				"\n\nObservação do NVDAStudio: esta é a avaliação da rodada do agente executor. "
				"A entrega só será considerada concluída depois dos gates independentes"
				" e, quando solicitado, do empacotamento."
			)
		return [text] if text else []
