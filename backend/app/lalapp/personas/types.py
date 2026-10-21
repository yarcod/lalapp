from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Role:
    """Pedagogical behaviour, independent of who is speaking."""

    id: str
    version: int
    title: str
    rules: tuple[str, ...]
    # How much of the learner's native language this role may use.
    native_language_policy: str
    selectable: bool = True


@dataclass(frozen=True)
class Persona:
    """A character: voice, background and personality. Never holds pedagogy."""

    id: str
    version: int
    name: str
    language: str  # Target language family this character teaches: "en" or "es".
    dialect: str  # The variety the character speaks, e.g. "es-MX".
    role: str
    age: int
    gender: str
    backstory: str
    personality: tuple[str, ...]
    speaking_style: str
    sample_lines: tuple[str, ...]
    # Per-provider TTS voices: {"openai": "...", "local": "..."}.
    voices: dict[str, str] = field(default_factory=dict)
    # Humour by learner level; the closest lower level applies.
    humour: dict[str, str] = field(default_factory=dict)
