from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.lalapp.learner.service import record_response
from app.lalapp.models import LearnerResponse, Milestone
from app.lalapp.rhythm import service as rhythm
from app.models.chat_history import ChatHistory
from app.models.user_language import UserLanguage
from tests.conftest import make_study_plan

NOW = datetime(2026, 10, 21, 12, 0)  # A Wednesday.
MONDAY = date(2026, 10, 19)


def test_week_starts_on_monday():
    assert rhythm.week_start(NOW.date()) == MONDAY
    assert rhythm.week_start(MONDAY) == MONDAY


def test_weeks_kept_counts_completed_weeks_only():
    active = {MONDAY - timedelta(weeks=1, days=-d) for d in range(3)}  # 3 days last week
    active |= {MONDAY - timedelta(weeks=2)}  # 1 day two weeks ago
    active |= {MONDAY, MONDAY + timedelta(days=1), MONDAY + timedelta(days=2)}  # this week
    assert rhythm.weeks_kept(active, 3, MONDAY) == 1
    assert rhythm.weeks_kept(active, 1, MONDAY) == 2


def test_stretch_turns_need_history_and_beat_the_median():
    short = ["hola"] * 5 + ["hola qué tal"] * 5
    assert rhythm.stretch_count(short[:9], ["uno dos tres cuatro"]) == 0
    assert rhythm.stretch_count(short, ["uno dos tres cuatro", "hola", "uno dos"]) == 1  # median 2


@pytest.fixture
def fixed_now(monkeypatch):
    monkeypatch.setattr(rhythm, "_now", lambda: NOW)


async def _user_language(db_session, user_id):
    return await db_session.scalar(select(UserLanguage).where(UserLanguage.user_id == user_id))


def _turn(user_language, text, when):
    return ChatHistory(
        user_id=user_language.user_id,
        role="user",
        content=text,
        target_language=user_language.target_language,
        created_at=when,
    )


async def test_rhythm_api_summarises_the_week(client, db_session, test_user, fixed_now):
    user, headers = test_user
    ul = await _user_language(db_session, user.id)
    default = (await client.get("/api/lalapp/rhythm", headers=headers)).json()
    assert default["days_per_week"] == 3
    assert default["active_days"] == [] and default["turns_this_week"] == 0

    for day in (MONDAY - timedelta(days=6), MONDAY - timedelta(days=5)):
        db_session.add(
            LearnerResponse(
                user_language_id=ul.id,
                item_key="tpl:x",
                skill="grammar",
                source="lesson",
                score=1.0,
                expected=0.7,
                theta_before=0.0,
                difficulty_before=0.0,
                created_at=datetime.combine(day, datetime.min.time()),
            )
        )
    last_week = datetime.combine(MONDAY - timedelta(days=3), datetime.min.time())
    for _ in range(10):
        db_session.add(_turn(ul, "hi there", last_week))
    db_session.add(_turn(ul, "I would like a large tea please", NOW - timedelta(days=1)))
    db_session.add(_turn(ul, "ok", NOW))
    other = _turn(ul, "this assistant line does not count", NOW)
    other.role = "assistant"
    db_session.add(other)
    await db_session.commit()

    state = (await client.get("/api/lalapp/rhythm", headers=headers)).json()
    assert state["week_start"] == "2026-10-19"
    assert state["active_days"] == ["2026-10-20", "2026-10-21"]
    assert state["weeks_kept"] == 1 and state["weeks_counted"] == 8
    assert state["turns_this_week"] == 2
    assert state["stretch_turns_this_week"] == 1

    keys = [m["key"] for m in state["milestones"]]
    assert keys == []  # 12 turns: no milestone yet

    updated = await client.put("/api/lalapp/rhythm", headers=headers, json={"days_per_week": 2})
    assert updated.json()["days_per_week"] == 2
    assert updated.json()["weeks_kept"] == 1
    bad = await client.put("/api/lalapp/rhythm", headers=headers, json={"days_per_week": 0})
    assert bad.status_code == 422


async def test_milestones_are_shown_until_seen(client, db_session, test_user, fixed_now):
    user, headers = test_user
    ul = await _user_language(db_session, user.id)
    for _ in range(25):
        db_session.add(_turn(ul, "hola", NOW))
    await db_session.commit()

    state = (await client.get("/api/lalapp/rhythm", headers=headers)).json()
    assert [m["key"] for m in state["milestones"]] == ["turns:25"]
    assert state["milestones"][0]["data"] == {"count": 25}
    milestone_id = state["milestones"][0]["id"]

    seen = await client.post(f"/api/lalapp/milestones/{milestone_id}/seen", headers=headers)
    assert seen.status_code == 204
    again = (await client.get("/api/lalapp/rhythm", headers=headers)).json()
    assert again["milestones"] == []  # Recorded once, never repeated.
    missing = await client.post(f"/api/lalapp/milestones/{milestone_id + 99}/seen", headers=headers)
    assert missing.status_code == 404


async def test_skill_level_milestone_after_enough_evidence(db_session, test_user):
    user, _ = test_user
    plan = await make_study_plan(
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
    await db_session.commit()
    for _ in range(30):
        await record_response(
            db_session,
            study_plan_id=plan.id,
            skill="grammar",
            item_key="tpl:en-US:lesson:grammar:mc:A2:x",
            item_level="A2",
            score=1.0,
            source="lesson",
        )
    db_session.expire_all()
    rows = (await db_session.scalars(select(Milestone))).all()
    keys = [row.key for row in rows]
    assert keys and all(k.startswith("skill_level:grammar:") for k in keys)
    assert "skill_level:grammar:A1" not in keys  # Only levels above the plan's.
    assert len(keys) == len(set(keys))
    assert rows[0].data["skill"] == "grammar"


async def test_rhythm_can_be_switched_off(client, test_user, monkeypatch):
    _, headers = test_user
    monkeypatch.setattr("app.lalapp.config.lalapp_settings.RHYTHM_ENABLED", False)
    assert (await client.get("/api/lalapp/rhythm", headers=headers)).status_code == 404
