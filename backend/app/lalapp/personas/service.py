"""Which character speaks in a conversation, and applying it to upstream's prompts.

Upstream builds tutor prompts in several places. Rather than hooking each one, the entry
points (text chat and the voice WebSocket) activate the conversation's character in a context
variable, and upstream's two prompt wrappers pass their output through ``apply``.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.lalapp.config import lalapp_settings
from app.lalapp.models import ConversationPersona, LanguagePreference
from app.lalapp.personas import registry
from app.lalapp.personas.compose import compose_system_prompt
from app.lalapp.personas.types import Persona
from app.models.conversation import Conversation
from app.models.user_language import UserLanguage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActivePersona:
    persona: Persona
    target_language: str
    cefr_level: str | None
    native_language_name: str
    scene: str | None = None


_active: ContextVar[ActivePersona | None] = ContextVar("lalapp_active_persona", default=None)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _user_language(
    db: AsyncSession, user_id: int, target_language: str
) -> UserLanguage | None:
    return await db.scalar(
        select(UserLanguage).where(
            UserLanguage.user_id == user_id, UserLanguage.target_language == target_language
        )
    )


async def preferred_peer(db: AsyncSession, user_id: int, target_language: str) -> Persona | None:
    user_language = await _user_language(db, user_id, target_language)
    if user_language is not None:
        preference = await db.get(LanguagePreference, user_language.id)
        if preference and registry.is_selectable(preference.peer_persona_id, target_language):
            persona = registry.get(preference.peer_persona_id)
            if persona and persona.role == "peer":
                return persona
    return registry.default_peer(target_language)


async def set_preferred_peer(
    db: AsyncSession, user_id: int, target_language: str, persona_id: str
) -> bool:
    persona = registry.get(persona_id)
    if persona is None or persona.role != "peer":
        return False
    if not registry.is_selectable(persona_id, target_language):
        return False
    user_language = await _user_language(db, user_id, target_language)
    if user_language is None:
        return False
    preference = await db.get(LanguagePreference, user_language.id)
    if preference is None:
        preference = LanguagePreference(user_language_id=user_language.id)
        db.add(preference)
    preference.peer_persona_id = persona_id
    preference.updated_at = _now()
    await db.commit()
    return True


async def _owned_conversation(
    db: AsyncSession, user_id: int, conversation_id: int
) -> Conversation | None:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user_id:
        return None
    return conversation


async def _scene(db: AsyncSession, conversation_id: int) -> tuple[Persona, str] | None:
    from app.lalapp.scenarios.service import npc_for_conversation  # noqa: PLC0415

    if not lalapp_settings.SCENARIOS_ENABLED:
        return None
    return await npc_for_conversation(db, conversation_id)


async def conversation_persona(
    db: AsyncSession, user_id: int, conversation_id: int, target_language: str
) -> Persona | None:
    """The conversation's character, assigning the preferred partner on first use.

    A role-play scene's conversation always has the scene's NPC.
    """
    scene = await _scene(db, conversation_id)
    if scene is not None:
        return scene[0]
    row = await db.get(ConversationPersona, conversation_id)
    if row is not None:
        persona = registry.get(row.persona_id)
        if persona and registry.language_family(target_language) == persona.language:
            return persona
    persona = await preferred_peer(db, user_id, target_language)
    if persona is None:
        return None
    if row is None:
        db.add(
            ConversationPersona(
                conversation_id=conversation_id,
                persona_id=persona.id,
                persona_version=persona.version,
                created_at=_now(),
            )
        )
    else:
        row.persona_id, row.persona_version = persona.id, persona.version
    await db.commit()
    return persona


async def set_conversation_persona(
    db: AsyncSession, user_id: int, conversation_id: int, persona_id: str
) -> Persona | None:
    conversation = await _owned_conversation(db, user_id, conversation_id)
    persona = registry.get(persona_id)
    if conversation is None or persona is None:
        return None
    if await _scene(db, conversation_id) is not None:
        return None
    if not registry.is_selectable(persona_id, conversation.target_language or ""):
        return None
    row = await db.get(ConversationPersona, conversation_id)
    if row is None:
        row = ConversationPersona(conversation_id=conversation_id)
        db.add(row)
    row.persona_id, row.persona_version, row.created_at = persona.id, persona.version, _now()
    await db.commit()
    return persona


async def activate(
    db: AsyncSession,
    *,
    user_id: int,
    conversation_id: int,
    target_language: str,
    cefr_level: str | None,
    native_language_name: str,
) -> Persona | None:
    """Make the conversation's character apply to prompts built in this request or session.

    Best-effort: on any failure the upstream tutor is used unchanged.
    """
    _active.set(None)
    if not lalapp_settings.PERSONAS_ENABLED:
        return None
    try:
        scene = await _scene(db, conversation_id)
        persona = (
            scene[0]
            if scene
            else await conversation_persona(db, user_id, conversation_id, target_language)
        )
    except Exception:
        logger.exception("Persona activation failed for conversation %s", conversation_id)
        await db.rollback()
        return None
    if persona is not None:
        _active.set(
            ActivePersona(
                persona,
                target_language,
                cefr_level,
                native_language_name,
                scene=scene[1] if scene else None,
            )
        )
    return persona


async def activate_voice_session(
    *,
    user_id: int,
    conversation_id: int | None,
    target_language: str,
    cefr_level: str | None,
    native_language: str,
) -> str:
    """Activate the character for a voice session and return its TTS voice ('' if none)."""
    from app.services.language_helpers import get_native_language_name  # noqa: PLC0415
    from app.utils.db import db_session  # noqa: PLC0415

    if conversation_id is None:
        _active.set(None)
        return ""
    async with db_session() as db:
        persona = await activate(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            target_language=target_language,
            cefr_level=cefr_level,
            native_language_name=get_native_language_name(native_language),
        )
    return voice_for(persona) if persona else ""


def voice_for(persona: Persona) -> str:
    provider = "openai" if settings.TTS_PROVIDER == "openai" else "local"
    return persona.voices.get(provider, "")


def apply(prompt: str) -> str:
    """Hook for upstream's prompt wrappers: rewrite the prompt for the active character."""
    active = _active.get()
    if active is None:
        return prompt
    return compose_system_prompt(
        prompt,
        active.persona,
        target_language=active.target_language,
        cefr_level=active.cefr_level,
        native_language_name=active.native_language_name,
        scene=active.scene,
    )
