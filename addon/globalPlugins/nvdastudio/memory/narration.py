"""Narracao em tempo real -- helpers COMPARTILHADOS entre a GUI, o orchestrator
e (ate a demolicao terminar) os sub_agents staged.

Extraidos de sub_agents/_base.py na Fatia A da demolicao do staged (Caminho 3):
narrate/LiveNarrator/_truncate_at_word eram usados pela GUI agentica e pelo
orchestrator, mas viviam dentro de _base.py junto do maquinario staged. Mover
pra ca desacopla o caminho VIVO do staged, pre-requisito pra deletar sub_agents.
Sem dependencia de nenhum sub-agente -- so `conversation`.
"""
import re
import sys

from .conversation_manager import conversation


# Marcadores de plural "de codigo" que os call-sites de narrate() usam (a frase
# e montada em runtime com um numero: "3 ponto(s)"). Resolvidos aqui,
# deterministicamente, pelo numero que antecede -- irregulares do portugues
# ("item(ns)" -> "itens", "secao(oes)" -> "secoes") entram explicitos porque nao
# dao pra derivar por regra generica.
_PLURAIS_NARRACAO = {
	"ponto(s)": ("ponto", "pontos"),
	"arquivo(s)": ("arquivo", "arquivos"),
	"problema(s)": ("problema", "problemas"),
	"caso(s)": ("caso", "casos"),
	"item(ns)": ("item", "itens"),
	"secao(oes)": ("secao", "secoes"),
}
# Sufixo tecnico ", status searched/cached" que um call-site anexava cru --
# valor interno da tool de busca, sem significado pro usuario.
_STATUS_JARGAO_RE = re.compile(r",?\s*status\s+\w+\s*$", re.IGNORECASE)


def _expandir_plural(texto: str, marcador: str, singular: str, plural: str) -> str:
	def _sub(m: "re.Match[str]") -> str:
		n = m.group(1)
		return f"{n} {singular if n == '1' else plural}"
	return re.sub(rf"(\d+)\s+{re.escape(marcador)}", _sub, texto)


def _limpar_narracao(action_desc: str) -> str:
	"""Limpa a frase de narracao que o call-site JA escreveu (PT-BR, primeira
	pessoa, tempo presente), sem reescrever via uma segunda IA. Deterministico e
	de graca: colapsa espacos, resolve os marcadores de plural de codigo pelo
	numero ("3 ponto(s)" -> "3 pontos") e remove o sufixo ", status X" interno."""
	texto = " ".join(action_desc.split())
	texto = _STATUS_JARGAO_RE.sub("", texto)
	for marcador, (singular, plural) in _PLURAIS_NARRACAO.items():
		if marcador in texto:
			texto = _expandir_plural(texto, marcador, singular, plural)
	return texto.strip()


def _truncate_at_word(text: str, max_chars: int) -> str:
	"""Corta text em max_chars sem partir uma palavra ao meio -- narrate() ecoa
	detalhes quase verbatim, entao um slice bruto texto[:150] vazaria palavra
	quebrada pro usuario."""
	if len(text) <= max_chars:
		return text
	snippet = text[:max_chars]
	last_space = snippet.rfind(" ")
	if last_space > 0:
		snippet = snippet[:last_space]
	return snippet.rstrip()


def narrate(action_desc: str) -> None:
	"""Narra em tempo real, em linguagem natural, uma acao do agente. Emite
	direto via conversation.emit_status() -- o call-site ja escreve em PT-BR,
	primeira pessoa, presente; aqui so a limpeza deterministica (_limpar_narracao).
	Silenciosa em teste (pytest/unittest) pra nao poluir asserts de outros testes."""
	if not action_desc or not action_desc.strip():
		return
	if "pytest" in sys.modules or "unittest" in sys.modules:
		return
	conversation.emit_status(_limpar_narracao(action_desc))


_REASONING_CHUNK_MIN_CHARS = 60
_SENTENCE_END_CHARS = (".", "!", "?", "\n")


class _SentenceChunkBuffer:
	"""Acumula texto e libera em pedacos por frase (fecha em ./!/?/quebra de
	linha, so depois de _REASONING_CHUNK_MIN_CHARS acumulados). Subclasses
	definem _on_chunk()."""

	def __init__(self):
		self._buffer = ""

	def feed(self, delta: str) -> None:
		if not delta:
			return
		self._buffer += delta
		while len(self._buffer) >= _REASONING_CHUNK_MIN_CHARS:
			cut = -1
			for i, ch in enumerate(self._buffer):
				if ch in _SENTENCE_END_CHARS and i >= _REASONING_CHUNK_MIN_CHARS - 20:
					cut = i + 1
					break
			if cut == -1:
				break
			chunk, self._buffer = self._buffer[:cut].strip(), self._buffer[cut:]
			if chunk:
				self._on_chunk(chunk)

	def flush(self) -> None:
		chunk, self._buffer = self._buffer.strip(), ""
		if chunk:
			self._on_chunk(chunk)

	def _on_chunk(self, chunk: str) -> None:
		raise NotImplementedError


class LiveNarrator(_SentenceChunkBuffer):
	"""Acumula deltas de CONTEUDO real (nao reasoning) que o proprio agente
	escreve durante o trabalho (padrao "tool preamble"), emitindo por frase via
	conversation.emit_status(). feed() detecta blocos ``` (mesmo partidos entre
	deltas via _raw_tail) e SUPRIME o texto dentro deles -- so o que esta FORA de
	um fence vira narracao (senao o codigo do artefato vazava como fala)."""

	def __init__(self):
		super().__init__()
		self._raw_tail = ""
		self._in_fence = False

	def feed(self, delta: str) -> None:
		if not delta:
			return
		text = self._raw_tail + delta
		self._raw_tail = ""
		pos = 0
		while True:
			idx = text.find("```", pos)
			if idx == -1:
				remainder = text[pos:]
				if remainder.endswith("``"):
					self._raw_tail = remainder[-2:]
					remainder = remainder[:-2]
				elif remainder.endswith("`"):
					self._raw_tail = remainder[-1:]
					remainder = remainder[:-1]
				if not self._in_fence and remainder:
					super().feed(remainder)
				break
			chunk = text[pos:idx]
			if not self._in_fence and chunk:
				super().feed(chunk)
			self._in_fence = not self._in_fence
			pos = idx + 3

	def _on_chunk(self, chunk: str) -> None:
		conversation.emit_status(chunk)
