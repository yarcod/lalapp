from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_chat_returns_sse_stream(client, test_user, db_session):
    user, headers = test_user

    from tests.conftest import make_study_plan

    _ = await make_study_plan(
        db_session,
        user_id=user.id,
        cefr_level="A1",
        target_language="en-US",
        goals=["grammar"],
        duration_weeks=4,
        days_per_week=4,
        current_unit="",
        generated_plan={},
        is_active=True,
    )

    class FakeChunk:
        class Choice:
            class Delta:
                content = "Hello"

            delta = Delta()

        choices = [Choice()]

    async def fake_stream():
        yield FakeChunk()

    with patch(
        "app.routers.chat.llm_adapter.chat",
        new_callable=AsyncMock,
        return_value=fake_stream(),
    ):
        response = await client.post(
            "/api/chat",
            headers=headers,
            json={"message": "Hi"},
        )
        assert response.status_code == 200
        body = response.text
        assert "token" in body or "Hello" in body


@pytest.mark.asyncio
async def test_chat_requires_auth(client):
    response = await client.post(
        "/api/chat",
        headers={"Authorization": "Bearer invalid"},
        json={"message": "Hi"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_history_empty(client, test_user_with_plan):
    user, headers = test_user_with_plan

    response = await client.get("/api/chat/history", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["messages"] == []


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
