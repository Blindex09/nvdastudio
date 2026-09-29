"""Extração incremental de um campo string de um JSON que ainda está chegando.

A resposta estruturada do chat traz a fala para o usuário dentro de um campo
(``message``) ao lado da decisão (``action``). Esperar o JSON fechar para mostrar
a fala engole tudo de uma vez; este leitor entrega o texto decodificado do campo
assim que cada fragmento chega, sem interpretar o conteúdo.
"""
import json
import re
from typing import Callable

MODULE_VERSION = "1.1.0"

_SIMPLE_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
_HIGH_SURROGATES = range(0xD800, 0xDC00)
_LOW_SURROGATES = range(0xDC00, 0xE000)


class JsonFieldStreamer:
	"""Máquina de estados sobre os deltas; só olha o campo de topo ``field``."""

	def __init__(self, field: str, on_text: Callable[[str], None]):
		self._field = field
		self._on_text = on_text
		self.reset()

	def reset(self) -> None:
		"""Reinicia o parse (o provedor falhou e outro reenvia do começo)."""
		self._depth = 0
		self._in_string = False
		self._escape = ""
		self._high_surrogate = 0
		self._string_chars: list[str] = []
		self._last_key = ""
		self._expect_value_for = ""
		self._streaming_value = False
		self.emitted = False

	def feed(self, delta: str) -> None:
		out: list[str] = []
		for ch in delta or "":
			self._step(ch, out)
		if out:
			self.emitted = True
			self._on_text("".join(out))

	def _step(self, ch: str, out: list[str]) -> None:
		if self._in_string:
			self._step_in_string(ch, out)
			return
		if ch == '"':
			self._in_string = True
			self._string_chars = []
			self._streaming_value = (
				self._depth == 1 and self._expect_value_for == self._field
			)
		elif ch in "{[":
			self._depth += 1
		elif ch in "}]":
			self._depth -= 1
		elif ch == ":" and self._depth == 1:
			self._expect_value_for = self._last_key
		elif ch == ",":
			self._expect_value_for = ""

	def _step_in_string(self, ch: str, out: list[str]) -> None:
		if self._escape:
			decoded = self._decode_escape(ch)
			if decoded:
				self._emit_char(decoded, out)
			return
		if ch == "\\":
			self._escape = "\\"
			return
		if ch == '"':
			self._in_string = False
			if self._streaming_value:
				self._streaming_value = False
				self._expect_value_for = ""
			elif self._depth == 1:
				self._last_key = "".join(self._string_chars)
			return
		self._emit_char(ch, out)

	def _emit_char(self, ch: str, out: list[str]) -> None:
		if self._streaming_value:
			out.append(ch)
		else:
			self._string_chars.append(ch)

	def _decode_escape(self, ch: str) -> str:
		"""Devolve o caractere decodificado, ou "" enquanto a sequência está incompleta."""
		if self._escape == "\\":
			if ch == "u":
				self._escape = "\\u"
				return ""
			self._escape = ""
			return _SIMPLE_ESCAPES.get(ch, ch)
		self._escape += ch
		if len(self._escape) < 6:
			return ""
		code, self._escape = self._escape[2:], ""
		try:
			value = int(code, 16)
		except ValueError:
			return ""
		if value in _HIGH_SURROGATES:
			self._high_surrogate = value
			return ""
		if value in _LOW_SURROGATES and self._high_surrogate:
			value = 0x10000 + ((self._high_surrogate - 0xD800) << 10) + (value - 0xDC00)
		self._high_surrogate = 0
		return chr(value)


def extract_json_object(text: str) -> dict:
	"""Interpreta o objeto JSON de uma resposta de LLM que pode nao vir estrita.

	Achado ao vivo (2026-09-29, teste real via Ollama Cloud): providers sem
	structured output garantido (o proprio ai/ollama_client.py documenta que
	"Ollama Cloud nao suporta ... structured output real") por vezes cercam o
	JSON com crases de markdown ou deixam prosa antes/depois -- json.loads cru
	falhava com "Expecting value: line 1 column 1" mesmo com uma resposta boa
	e completa (confirmado: JsonFieldStreamer.feed extraiu o campo "message"
	corretamente da MESMA resposta que json.loads() rejeitava). Tenta, em
	ordem: JSON puro; sem cercas de markdown; do primeiro '{' ao ultimo '}'
	(com fechamento incremental se sobrar "Extra data" depois do objeto).
	Repete a logica ja provada em ai/clarifier.py::_extract_json_fallback,
	agora compartilhada -- nao uma heuristica nova.
	"""
	raw = (text or "").strip()
	if not raw:
		raise json.JSONDecodeError("texto vazio", raw, 0)
	try:
		return json.loads(raw)
	except json.JSONDecodeError:
		pass

	clean = re.sub(r"^```(?:json)?\n?", "", raw)
	clean = re.sub(r"\n?```$", "", clean).strip()
	if clean != raw:
		try:
			return json.loads(clean)
		except json.JSONDecodeError:
			pass

	start = clean.find("{")
	if start == -1:
		raise json.JSONDecodeError("sem { encontrado", clean, 0)
	end = clean.rfind("}")
	if end == -1 or start >= end:
		raise json.JSONDecodeError("sem } encontrado", clean, 0)
	candidate = clean[start:end + 1]
	try:
		return json.loads(candidate)
	except json.JSONDecodeError as exc:
		if "Extra data" not in str(exc):
			raise
		depth = 0
		for i, ch in enumerate(candidate):
			if ch == "{":
				depth += 1
			elif ch == "}":
				depth -= 1
				if depth == 0:
					return json.loads(candidate[:i + 1])
		raise
