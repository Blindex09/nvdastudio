"""Guia de desenvolvimento de addons NVDA, servido por topico.

O texto vem de nvda_context.NVDA_GUIDE (herdado do projeto anterior).
Aqui ele e so FATIADO nos cabecalhos que ele proprio tem, para o Claude ler o
topico que precisa em vez de 19 mil tokens de uma vez. Nenhuma decisao de
significado: o corte e por cabecalho em maiusculas terminado em dois pontos.
"""

import re
from dataclasses import dataclass

from . import nvda_context

# Cabecalho de formato de resposta (texto puro para leitor de telas), que
# nao se aplica a quem consome o guia.
_SKIP = ("REGRA ABSOLUTA DE FORMATO",)
_HEADING = re.compile(r"^(?=[^a-z\n]*[A-Z]{4})[^a-z\n]{8,}:\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Section:
    title: str
    text: str


def _parse(text: str) -> list[Section]:
    matches = list(_HEADING.finditer(text))
    sections: list[Section] = []
    for index, match in enumerate(matches):
        title = match.group(0).strip().rstrip(":").strip()
        if any(title.startswith(skip) for skip in _SKIP):
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append(Section(title, text[match.start():end].strip()))
    return sections


SECTIONS: tuple[Section, ...] = tuple(_parse(nvda_context.NVDA_GUIDE))


def list_topics() -> list[dict[str, object]]:
    return [{"topico": s.title, "caracteres": len(s.text)} for s in SECTIONS]


def read_topic(query: str) -> list[Section]:
    """Secoes cujo titulo contem `query` (sem diferenciar maiusculas)."""
    needle = query.strip().lower()
    return [s for s in SECTIONS if needle and needle in s.title.lower()]
