from __future__ import annotations

from dataclasses import dataclass

from app.lalapp.personas.types import Persona


@dataclass(frozen=True)
class Mission:
    """A communicative goal the learner reaches in the scene."""

    id: str
    # Shown to the learner, by interface language ("en", "sv", "es").
    goal: dict[str, str]
    # For the judge, in English: what the learner must say or do to count.
    rubric: str


@dataclass(frozen=True)
class Scenario:
    """A role-play scene with one NPC, part of a story arc."""

    id: str
    version: int
    language: str  # Target-language family: "en" or "es".
    arc: str
    order: int  # Position in the arc; a scene unlocks when the previous one is completed.
    level: str  # CEFR level the scene is written for.
    # Conversation title, in the target language.
    title: str
    # Shown to the learner, by interface language.
    summary: dict[str, str]
    npc: Persona
    # For the NPC prompt, in English: the place and situation, and what the NPC wants.
    setting: str
    npc_goal: str
    # The NPC's first line, in the target language.
    opener: str
    missions: tuple[Mission, ...]
