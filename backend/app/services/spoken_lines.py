"""Tagged tutor replies: each line is spoken in exactly one language.

Tags: ``[sv]`` Swedish, ``[en]`` / ``[es]`` a full target-language sentence,
``[screen]`` text that is shown but never spoken.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SCREEN = "screen"
SWEDISH = "sv"

_TAG_RE = re.compile(r"\[(sv|en|es|screen)\]", re.IGNORECASE)
_QUOTE_RE = re.compile(r"\"[^\"]+\"|“[^”]+”|«[^»]+»|„[^“”]+[“”]")
_WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?", re.UNICODE)

# Common English and Spanish words that are not Swedish words.
_FOREIGN_WORDS = frozenset(
    {
        "the", "you", "your", "hello", "please", "thanks", "thank", "apple", "how", "are",
        "what", "my", "name", "good", "morning", "yes", "with", "this", "that",
        "i'm", "it's", "where", "when", "why", "who", "we", "they", "he", "she", "would",
        "could", "have", "has", "do", "does", "goodbye", "sorry", "welcome",
        "hola", "gracias", "buenos", "buenas", "días", "dias", "por", "favor", "cómo",
        "como", "está", "esta", "usted", "qué", "que", "señor", "bueno", "adiós", "adios",
        "me", "llamo", "tengo", "soy", "estoy", "muy", "bien", "casa", "perro", "gato",
    }
)  # fmt: skip
_FOREIGN_CHARS = frozenset("ñ¿¡áíóúÁÍÓÚ")


@dataclass
class SpokenLine:
    language: str  # "sv", a target iso code, or "screen"
    text: str
    spoken: bool


def parse_reply(text: str, target_code: str) -> list[SpokenLine]:
    """Split a reply into tagged lines. An untagged line is Swedish."""
    lines: list[SpokenLine] = []
    for raw in text.splitlines():
        matches = list(_TAG_RE.finditer(raw))
        segments: list[tuple[str, str]] = []
        if not matches:
            segments.append((SWEDISH, raw))
        else:
            if raw[: matches[0].start()].strip():
                segments.append((SWEDISH, raw[: matches[0].start()]))
            for idx, match in enumerate(matches):
                end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw)
                segments.append((match.group(1).lower(), raw[match.end() : end]))
        for tag, segment in segments:
            segment = segment.strip()
            if not segment:
                continue
            if tag == SCREEN:
                lines.append(SpokenLine(SCREEN, segment, False))
            elif tag == SWEDISH:
                lines.append(SpokenLine(SWEDISH, segment, True))
            else:
                lines.append(SpokenLine(target_code, segment, True))
    return lines


def _has_foreign_words(text: str) -> bool:
    if any(char in _FOREIGN_CHARS for char in text):
        return True
    return any(word.lower() in _FOREIGN_WORDS for word in _WORD_RE.findall(text))


def invalid_swedish_lines(lines: list[SpokenLine]) -> list[SpokenLine]:
    """Spoken Swedish lines that contain quoted text or target-language words."""
    return [
        line
        for line in lines
        if line.spoken
        and line.language == SWEDISH
        and (_QUOTE_RE.search(line.text) or _has_foreign_words(line.text))
    ]


def display_text(lines: list[SpokenLine]) -> str:
    """Text shown and saved: tags removed, screen and spoken lines included."""
    return " ".join(line.text for line in lines)
