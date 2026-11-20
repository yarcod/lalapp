import pytest
from sqlalchemy import select

from app.home.models import HomeProfile
from tests.conftest import make_study_plan


@pytest.mark.asyncio
async def test_profile_defaults_without_row(client, test_user, db_session) -> None:
    user, headers = test_user
    response = await client.get("/api/home/profile", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"is_child": False, "tagged_languages": []}
    rows = (await db_session.execute(select(HomeProfile))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_put_sets_child_and_get_reads_it(client, test_user) -> None:
    _, headers = test_user
    put = await client.put("/api/home/profile", json={"is_child": True}, headers=headers)
    assert put.status_code == 200
    assert put.json()["is_child"] is True
    assert (await client.get("/api/home/profile", headers=headers)).json()["is_child"] is True
    await client.put("/api/home/profile", json={"is_child": False}, headers=headers)
    assert (await client.get("/api/home/profile", headers=headers)).json()["is_child"] is False


@pytest.mark.asyncio
async def test_profile_requires_auth(client) -> None:
    assert (await client.get("/api/home/profile")).status_code == 401
    response = await client.put("/api/home/profile", json={"is_child": True})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tagged_languages_for_swedish_a1_english(client, test_user, db_session) -> None:
    user, headers = test_user
    user.native_language = "sv"
    await make_study_plan(
        db_session,
        user_id=user.id,
        target_language="en-GB",
        cefr_level="A1",
        goals=[],
        duration_weeks=4,
        days_per_week=4,
        current_unit="",
        generated_plan={},
        is_active=True,
    )
    await db_session.commit()
    response = await client.get("/api/home/profile", headers=headers)
    assert response.json()["tagged_languages"] == ["en-GB"]
