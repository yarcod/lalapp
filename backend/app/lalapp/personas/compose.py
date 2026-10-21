"""Turn upstream's single-tutor system prompt into one for a Lalapp character.

Upstream's prompt keeps its mandatory rules, student context, memories and language overlay.
We only swap the identity line and the tutor name, then append the character and role
layers. Working on the finished prompt keeps upstream's prompt builders untouched.
"""

from __future__ import annotations

import re

from app.lalapp.learner.rating import CEFR_LEVELS, normalize_level
from app.lalapp.personas.registry import role_of
from app.lalapp.personas.types import Persona
from app.services.prompts.common import TUTOR_DISPLAY_NAME

_IDENTITY_LINE = re.compile(
    rf"^You are an? .*? named {re.escape(TUTOR_DISPLAY_NAME)}\.$", re.MULTILINE
)

DIALECT_NAMES = {
    "es-ES": "Spanish as spoken in Spain",
    "es-MX": "Mexican Spanish",
    "en-GB": "British English",
    "en-US": "American English",
}


def humour_for(persona: Persona, cefr_level: str | None) -> str:
    level = normalize_level(cefr_level) or "A1"
    reached = [lvl for lvl in CEFR_LEVELS[: CEFR_LEVELS.index(level) + 1] if lvl in persona.humour]
    return persona.humour[reached[-1]] if reached else "light"


def compose_system_prompt(
    base_prompt: str,
    persona: Persona,
    *,
    target_language: str,
    cefr_level: str | None,
    native_language_name: str,
) -> str:
    role = role_of(persona)
    identity = f"You are {persona.name}, a {role.title} in a language-learning app."
    prompt, replaced = _IDENTITY_LINE.subn(identity, base_prompt, count=1)
    if not replaced:
        prompt = f"{identity}\n{prompt}"
    prompt = prompt.replace(TUTOR_DISPLAY_NAME, persona.name)

    dialect = DIALECT_NAMES.get(persona.dialect, persona.dialect)
    target = DIALECT_NAMES.get(target_language, target_language)
    rules = "\n".join(f"- {rule}" for rule in role.rules)
    samples = "\n".join(f'- "{line}"' for line in persona.sample_lines)
    return f"""{prompt}

Your character (stay consistent with it for the whole conversation):
- Name: {persona.name}, {persona.age} years old.
- Background: {persona.backstory}
- Personality: {", ".join(persona.personality)}.
- How you speak: {persona.speaking_style} You naturally speak {dialect}. The learner is studying \
{target}: accept their {target} forms as correct and mention differences only as interesting facts.
- Humour: {humour_for(persona, cefr_level)}, always kind and never at the learner's expense.
- Example lines, for style only (never repeat them verbatim):
{samples}

Your role as {role.title}:
{rules}
- Learner's native language ({native_language_name}): {role.native_language_policy}

Honesty and care: you are a fictional character in an app, voiced by an AI. If the learner \
sincerely asks whether you are a human or an AI, say so briefly and carry on in character. Never \
claim to be a real person, never flirt, and never make the learner feel guilty about practice.

Where the character and role instructions above differ from the earlier guidelines, follow these, \
but the mandatory rules always come first.
"""
