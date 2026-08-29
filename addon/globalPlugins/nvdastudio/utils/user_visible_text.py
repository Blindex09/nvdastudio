import re
import unicodedata

MODULE_VERSION = "1.0.0"

_THOUGHT_NAMES = r"reasoning_scratchpad|reasoning|thinking|thought|think"


def sanitize_user_visible_text(text: str) -> str:
	"""Converte saida de IA em texto simples adequado a leitor de telas.

	O codigo e os artefatos tecnicos usam outro canal e nao passam por esta
	funcao. Aqui removemos raciocinio interno, markdown, linhas decorativas,
	marcadores de lista e simbolos visuais que nao acrescentam significado.
	"""
	if not text:
		return ""

	cleaned = re.sub(
		rf"<(?P<tag>{_THOUGHT_NAMES})\b[^>]*>.*?</(?P=tag)\s*>",
		"",
		text,
		flags=re.IGNORECASE | re.DOTALL,
	)

	# Se o provedor encerrou a resposta dentro de um bloco de raciocinio
	# incompleto, nada depois da abertura pertence ao usuario.
	open_blocks = list(re.finditer(rf"<(?:{_THOUGHT_NAMES})\b[^>]*>", cleaned, re.IGNORECASE))
	if open_blocks:
		cleaned = cleaned[:open_blocks[-1].start()]
	else:
		# Streaming interrompido pode deixar apenas o inicio da tag interna.
		partial = re.search(r"<(?:rea(?:s(?:o(?:n(?:i(?:n(?:g)?)?)?)?)?)?|thi(?:n(?:k(?:i(?:n(?:g)?)?)?)?)?|tho(?:u(?:g(?:h(?:t)?)?)?)?)$", cleaned, re.IGNORECASE)
		if partial:
			cleaned = cleaned[:partial.start()]

	cleaned = re.sub(rf"</?(?:{_THOUGHT_NAMES})\b[^>]*>", "", cleaned, flags=re.IGNORECASE)
	cleaned = re.sub(r"^\s*(```|~~~).*?$", "", cleaned, flags=re.MULTILINE)
	cleaned = re.sub(r"^\s*[-*_]{3,}\s*$", "", cleaned, flags=re.MULTILINE)
	cleaned = re.sub(r"^\s{0,3}(?:[-*+•▪◦]|>)\s+", "", cleaned, flags=re.MULTILINE)
	cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
	cleaned = cleaned.replace("**", "").replace("__", "")
	cleaned = cleaned.replace("*", "").replace("`", "").replace("~", "")

	# Remove emojis e simbolos decorativos, preservando letras acentuadas,
	# numeros e pontuacao linguistica comum.
	cleaned = "".join(ch for ch in cleaned if not unicodedata.category(ch).startswith("S"))
	cleaned = re.sub(r"[ \t]+", " ", cleaned)
	cleaned = re.sub(r" *\r?\n *", "\n", cleaned)
	cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
	return cleaned.strip()
