from unittest.mock import AsyncMock, patch

import pytest

from app.lalapp.personas import registry, service
from app.lalapp.personas.compose import compose_system_prompt, humour_for
from app.services.prompts.common import TUTOR_DISPLAY_NAME
from app.services.prompts.tutor import (
    build_conversation_system_prompt,
    build_tutor_system_prompt,
)
from tests.conftest import make_study_plan

OPENAI_VOICES = {"alloy", "ash", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"}


def _chat_prompt():
    return build_tutor_system_prompt(
        student_name="Sam",
        cefr_level="B1",
        native_language="Swedish",
        target_language_name="Spanish",
        total_xp=0,
        streak=0,
        lessons_today=0,
        skills="none yet",
        user_context="",
        memory_context="",
    )


def _voice_prompt():
    return build_conversation_system_prompt(
        student_name="Sam",
        cefr_level="B1",
        native_language="Swedish",
        target_language_name="Spanish",
        user_context="",
        memory_context="",
    )


@pytest.mark.parametrize("build", [_chat_prompt, _voice_prompt])
def test_compose_replaces_upstream_identity_and_keeps_its_rules(build):
    persona = registry.get("es-peer-mateo")
    prompt = compose_system_prompt(
        build(), persona, target_language="es-ES", cefr_level="B1", native_language_name="Swedish"
    )

    assert prompt.startswith("You are Mateo, a conversation partner")
    assert TUTOR_DISPLAY_NAME not in prompt
    assert "CONTENT POLICY" in prompt and "PERSONA LOCK" in prompt
    assert "Mexican Spanish" in prompt
    assert "Spanish as spoken in Spain" in prompt
    assert "Do not correct mid-flow" in prompt
    assert "voiced by an AI" in prompt


def test_compose_survives_changed_upstream_identity_line():
    persona = registry.get("en-guide-erik")
    prompt = compose_system_prompt(
        f"Hello, I am {TUTOR_DISPLAY_NAME}.\nRules...",
        persona,
        target_language="en-GB",
        cefr_level="A2",
        native_language_name="Swedish",
    )
    assert prompt.startswith("You are Erik, a guide and explainer")
    assert TUTOR_DISPLAY_NAME not in prompt


def test_humour_follows_learner_level():
    lucia = registry.get("es-peer-lucia")
    assert humour_for(lucia, "A2") == "light"
    assert humour_for(lucia, "B2") == "playful teasing"
    assert humour_for(lucia, "C2") == "witty and ironic"
    assert humour_for(lucia, None) == "light"


@pytest.mark.parametrize("family", ["en", "es"])
def test_each_language_has_the_launch_cast(family):
    cast = registry.cast_for(f"{family}-XX")
    roles = sorted(p.role for p in cast)
    assert roles == ["examiner", "guide", "peer", "peer"]
    peers = [p for p in cast if p.role == "peer"]
    assert len({p.dialect for p in peers}) == 2
    assert "examiner" not in {p.role for p in registry.selectable_for(f"{family}-XX")}


def test_persona_voices_are_valid_for_both_providers():
    for persona in registry.PERSONAS.values():
        assert persona.voices["openai"] in OPENAI_VOICES, persona.id
        assert persona.voices["local"][:2] in {"af", "am", "bf", "bm", "ef", "em"}, persona.id


@pytest.mark.parametrize(
    ("target", "expected"),
    [("en-US", "en-peer-dan"), ("en-GB", "en-peer-amira"), ("es-ES", "es-peer-lucia")],
)
def test_default_peer_matches_target_dialect(target, expected):
    assert registry.default_peer(target).id == expected


def test_apply_is_a_no_op_without_an_active_persona():
    service._active.set(None)
    assert service.apply("unchanged") == "unchanged"


async def test_persona_api_lists_cast_and_stores_partner_choice(client, test_user):
    _, headers = test_user

    cast = (await client.get("/api/lalapp/personas", headers=headers)).json()
    assert cast["target_language"] == "en-US"
    assert cast["preferred_peer_id"] == "en-peer-dan"
    assert {p["id"] for p in cast["personas"]} == {"en-guide-erik", "en-peer-amira", "en-peer-dan"}

    chosen = await client.put(
        "/api/lalapp/personas/peer", headers=headers, json={"persona_id": "en-peer-amira"}
    )
    assert chosen.json()["preferred_peer_id"] == "en-peer-amira"

    for invalid in ("es-peer-lucia", "en-guide-erik", "en-examiner-margaret", "nobody"):
        response = await client.put(
            "/api/lalapp/personas/peer", headers=headers, json={"persona_id": invalid}
        )
        assert response.status_code == 422, invalid


def _stream():
    class Chunk:
        class Choice:
            class Delta:
                content = "Hi"

            delta = Delta()

        choices = [Choice()]

    async def gen():
        yield Chunk()

    return gen()


async def test_chat_uses_conversation_persona(client, db_session, test_user):
    user, headers = test_user
    await make_study_plan(
        db_session,
        user_id=user.id,
        cefr_level="B1",
        target_language="en-US",
        goals=["grammar"],
        duration_weeks=4,
        days_per_week=4,
        current_unit="",
        generated_plan={},
        is_active=True,
    )
    await db_session.commit()
    await client.put(
        "/api/lalapp/personas/peer", headers=headers, json={"persona_id": "en-peer-amira"}
    )

    with patch(
        "app.routers.chat.llm_adapter.chat", new_callable=AsyncMock, return_value=_stream()
    ) as chat:
        response = await client.post("/api/chat", headers=headers, json={"message": "Hello"})
        assert response.status_code == 200
        _ = response.text
    system_prompt = chat.await_args.args[0][0]["content"]
    assert system_prompt.startswith("You are Amira")
    assert TUTOR_DISPLAY_NAME not in system_prompt

    conversations = (await client.get("/api/chat/conversations", headers=headers)).json()
    conversation_id = (
        conversations[0]["id"]
        if isinstance(conversations, list)
        else conversations["items"][0]["id"]
    )
    current = await client.get(
        f"/api/lalapp/conversations/{conversation_id}/persona", headers=headers
    )
    assert current.json()["name"] == "Amira"

    switched = await client.put(
        f"/api/lalapp/conversations/{conversation_id}/persona",
        headers=headers,
        json={"persona_id": "en-guide-erik"},
    )
    assert switched.json()["name"] == "Erik"
    with patch(
        "app.routers.chat.llm_adapter.chat", new_callable=AsyncMock, return_value=_stream()
    ) as chat:
        await client.post(
            "/api/chat",
            headers=headers,
            json={"message": "Explain please", "conversation_id": conversation_id},
        )
    assert chat.await_args.args[0][0]["content"].startswith("You are Erik, a guide")


async def test_voice_session_returns_persona_voice(db_session, test_user, monkeypatch):
    from contextlib import asynccontextmanager

    from app.models.conversation import Conversation

    user, _ = test_user
    conversation = Conversation(user_id=user.id, title="t", source="voice", target_language="en-US")
    db_session.add(conversation)
    await db_session.commit()

    @asynccontextmanager
    async def session():
        yield db_session

    monkeypatch.setattr("app.utils.db.db_session", session)
    monkeypatch.setattr("app.core.config.settings.TTS_PROVIDER", "openai")

    voice = await service.activate_voice_session(
        user_id=user.id,
        conversation_id=conversation.id,
        target_language="en-US",
        cefr_level="B1",
        native_language="sv",
    )

    assert voice == "onyx"
    assert service.apply(_voice_prompt()).startswith("You are Dan")
    service._active.set(None)
