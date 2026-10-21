from __future__ import annotations

from app.lalapp.personas import cast_en, cast_es
from app.lalapp.personas.roles import ROLES
from app.lalapp.personas.types import Persona, Role

PERSONAS: dict[str, Persona] = {p.id: p for p in (*cast_en.CAST, *cast_es.CAST)}


def language_family(target_language: str) -> str:
    return target_language.split("-")[0].lower()


def role_of(persona: Persona) -> Role:
    return ROLES[persona.role]


def get(persona_id: str | None) -> Persona | None:
    return PERSONAS.get(persona_id or "")


def cast_for(target_language: str) -> list[Persona]:
    family = language_family(target_language)
    return [p for p in PERSONAS.values() if p.language == family]


def selectable_for(target_language: str) -> list[Persona]:
    return [p for p in cast_for(target_language) if role_of(p).selectable]


def is_selectable(persona_id: str | None, target_language: str) -> bool:
    return any(p.id == persona_id for p in selectable_for(target_language))


def default_peer(target_language: str) -> Persona | None:
    peers = [p for p in cast_for(target_language) if p.role == "peer"]
    same_dialect = [p for p in peers if p.dialect.lower() == target_language.lower()]
    return (same_dialect or peers or [None])[0]
