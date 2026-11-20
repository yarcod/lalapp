from unittest.mock import AsyncMock, patch

import pytest

from app.home.chat import TaggedChatStream
from tests.conftest import make_study_plan


@pytest.mark.asyncio
async def test_chat_reply_has_no_tags_shown(client, test_user, db_session):
    """Tagged Swedish A1 replies are streamed and saved without their tags."""
    from sqlalchemy import select

    from app.models.chat_history import ChatHistory
    from tests.conftest import make_study_plan

    user, headers = test_user
    user.native_language = "sv"
    await db_session.commit()
    await make_study_plan(
        db_session,
        user_id=user.id,
        cefr_level="A1",
        target_language="en-GB",
        goals=["grammar"],
        duration_weeks=4,
        days_per_week=4,
        current_unit="",
        generated_plan={},
        is_active=True,
    )

    async def fake_stream():
        for token in ("[sv] Bra jobbat!\n[e", "n] I went home.\n[screen] go", " → went"):
            yield token

    with patch(
        "app.routers.chat.llm_adapter.chat",
        new_callable=AsyncMock,
        return_value=fake_stream(),
    ):
        response = await client.post("/api/chat", headers=headers, json={"message": "I goed"})

    assert response.status_code == 200
    for tag in ("[sv]", "[en]", "[screen]", "[e"):
        assert tag not in response.text
    assert "I went home." in response.text
    rows = (
        (await db_session.execute(select(ChatHistory).where(ChatHistory.role == "assistant")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert "[" not in rows[0].content
    assert "I went home." in rows[0].content
    assert "Bra jobbat!\nI went home.\ngo → went" == rows[0].content


@pytest.mark.asyncio
async def test_non_tagged_target_keeps_streaming(client, test_user, db_session):
    """A Swedish A1 learner of a non en/es target gets raw, token-by-token streaming."""
    user, headers = test_user
    user.native_language = "sv"
    await db_session.commit()

    async def fake_stream():
        for token in ("Bonjour", "\n- ami"):
            yield token

    with (
        patch(
            "app.routers.chat._resolve_chat_context",
            new_callable=AsyncMock,
            return_value=("A1", "fr-FR", None),
        ),
        patch(
            "app.routers.chat.llm_adapter.chat",
            new_callable=AsyncMock,
            return_value=fake_stream(),
        ),
    ):
        response = await client.post("/api/chat", headers=headers, json={"message": "Salut"})

    assert response.status_code == 200
    assert '"token": "Bonjour"' in response.text
    assert '"token": "\\n- ami"' in response.text


@pytest.mark.asyncio
async def test_chat_unavailable_llm_returns_error_code(client, test_user):
    """With no LLM the stream carries a code so the page can say Lingu is away."""
    from app.services.llm_adapter import LLMUnavailableError

    _, headers = test_user
    with patch(
        "app.routers.chat.llm_adapter.chat",
        new_callable=AsyncMock,
        side_effect=LLMUnavailableError("down"),
    ):
        response = await client.post("/api/chat", headers=headers, json={"message": "Hi"})

    assert response.status_code == 200
    assert '"error_code": "llm_unavailable"' in response.text


@pytest.mark.asyncio
async def test_chat_other_llm_error_has_no_away_code(client, test_user):
    from app.services.llm_adapter import LLMError

    _, headers = test_user
    with patch(
        "app.routers.chat.llm_adapter.chat",
        new_callable=AsyncMock,
        side_effect=LLMError("boom"),
    ):
        response = await client.post("/api/chat", headers=headers, json={"message": "Hi"})

    assert "error_code" not in response.text


@pytest.mark.asyncio
async def test_profile_reports_tagged_languages_per_plan(client, test_user, db_session):
    """Swedish speakers at A1/A2 learning English or Spanish get tagged replies."""
    user, headers = test_user
    user.native_language = "sv"
    await db_session.commit()
    for language, cefr in (("en-GB", "A1"), ("es-ES", "B1")):
        await make_study_plan(
            db_session,
            user_id=user.id,
            cefr_level=cefr,
            target_language=language,
            goals=["grammar"],
            duration_weeks=4,
            days_per_week=4,
            current_unit="",
            generated_plan={},
            is_active=language == "en-GB",
        )

    res = await client.get("/api/home/profile", headers=headers)

    assert res.json()["tagged_languages"] == ["en-GB"]


def test_stream_passes_tokens_through_when_not_tagged():
    stream = TaggedChatStream("en", "A1", "en-GB")
    assert stream.token("[sv] hej") == "[sv] hej"
    assert stream.final() is None


def test_stream_buffers_and_cleans_when_tagged():
    stream = TaggedChatStream("sv", "A1", "en-GB")
    assert stream.token("[sv] Bra!\n[e") is None
    assert stream.token("n] I went.") is None
    assert stream.final() == "Bra!\nI went."


def test_stream_reset_drops_buffered_text():
    stream = TaggedChatStream("sv", "A1", "en-GB")
    stream.token("[sv] old")
    stream.reset()
    stream.token("[sv] new")
    assert stream.final() == "new"


def test_stream_final_is_empty_for_tagged_reply_with_only_tags():
    stream = TaggedChatStream("sv", "A1", "en-GB")
    stream.token("[sv] \n[en]")
    assert stream.final() == ""
    assert TaggedChatStream("sv", "A1", "en-GB").final() == ""


@pytest.mark.asyncio
async def test_tagged_reply_that_cleans_to_empty_is_saved_empty(client, test_user, db_session):
    """A tagged reply with only tags sends no token and is saved as '' (not the raw tags)."""
    from sqlalchemy import select

    from app.models.chat_history import ChatHistory

    user, headers = test_user
    user.native_language = "sv"
    await db_session.commit()

    async def fake_stream():
        for token in ("[sv] \n[e", "n]  "):
            yield token

    with (
        patch(
            "app.routers.chat._resolve_chat_context",
            new_callable=AsyncMock,
            return_value=("A1", "en-GB", None),
        ),
        patch(
            "app.routers.chat.llm_adapter.chat",
            new_callable=AsyncMock,
            return_value=fake_stream(),
        ),
    ):
        response = await client.post("/api/chat", headers=headers, json={"message": "Hej"})

    assert response.status_code == 200
    assert '"token"' not in response.text
    rows = (
        (await db_session.execute(select(ChatHistory).where(ChatHistory.role == "assistant")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].content == ""
