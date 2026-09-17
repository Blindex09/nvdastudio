import re
import unicodedata

MODULE_VERSION = "1.1.0"

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
	cleaned = cleaned.replace("**", "")
	cleaned = cleaned.replace("*", "").replace("`", "").replace("~", "")

	# Remove emojis e simbolos decorativos, preservando letras acentuadas,
	# numeros e pontuacao linguistica comum.
	cleaned = "".join(ch for ch in cleaned if ch in "+=" or not unicodedata.category(ch).startswith("S"))
	cleaned = re.sub(r"[ \t]+", " ", cleaned)
	cleaned = re.sub(r" *\r?\n *", "\n", cleaned)
	cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
	return cleaned.strip()


def summarize_generation_error(error: str) -> str:
	"""Transforma relatorios tecnicos do gate em uma falha curta e acionavel."""
	clean = sanitize_user_visible_text(error)
	if not clean:
		return "Não foi possível concluir a geração do addon."
	if "timeout" in clean.lower() or "término inesperado" in clean.lower():
		return (
			"O agente atingiu o limite desta execução antes de concluir. "
			"Os arquivos de trabalho foram preservados para continuar sem recomeçar."
		)

	labels: list[str] = []
	for line in clean.splitlines():
		upper = line.upper()
		if "RUFF" in upper:
			labels.append("qualidade do código")
		elif "MYPY" in upper:
			labels.append("consistência de tipos")
		elif "TESTES" in upper:
			labels.append("testes automatizados")
		elif "EXECUCAO" in upper or "EXECUÇÃO" in upper:
			labels.append("execução do addon")
		elif any(code in upper for code in ("ESTRUTURA-", "MANIFEST-", "NVDA-", "WX-A11Y-")):
			labels.append("estrutura ou compatibilidade com o NVDA")

	unique = list(dict.fromkeys(labels))
	if unique:
		return (
			"O addon não passou nas verificações automáticas. Foram encontrados "
			"problemas em " + ", ".join(unique[:4]) + ". "
			"Os arquivos foram preservados para correção; os detalhes técnicos estão no log."
		)
	return clean if len(clean) <= 300 else clean[:297].rstrip() + "..."
