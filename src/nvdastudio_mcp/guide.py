"""NVDA add-on development guide, served by topic.

The text comes from nvda_context.NVDA_GUIDE (inherited from the previous
project). Here it is only SLICED at the headings it already has, so Claude
reads the topic it needs instead of 19 thousand tokens at once. No decision
about meaning: the cut is by an all-caps heading ending in a colon.
"""

import re
from dataclasses import dataclass

from . import nvda_context

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
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append(Section(title, text[match.start():end].strip()))
    return sections


SECTIONS: tuple[Section, ...] = tuple(_parse(nvda_context.NVDA_GUIDE))


def list_topics() -> list[dict[str, object]]:
    return [{"topic": s.title, "characters": len(s.text)} for s in SECTIONS]


def read_topic(query: str) -> list[Section]:
    """Sections whose title contains `query` (case-insensitive)."""
    needle = query.strip().lower()
    return [s for s in SECTIONS if needle and needle in s.title.lower()]
