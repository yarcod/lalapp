import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.home.models import HomeProfile
from app.models.game import GameAdmission, GameRequest, GameSession, GameStock
from app.models.lesson import Lesson
from app.models.study_plan import StudyPlan
from app.schemas.games import GameAnswer
from app.services import game_stock, games
from tests.conftest import make_study_plan
from tests.test_games import content, finish, ready_game

BUCKETS_FREE = 3  # detective, sentence-order, vocabulary-pairs


@pytest.fixture(autouse=True)
def clear_cooldowns():
    game_stock.bucket_cooldowns.clear()
    yield
    game_stock.bucket_cooldowns.clear()


@pytest.fixture
def gateway(monkeypatch):
    state = AsyncMock(return_value="off")
    monkeypatch.setattr(game_stock, "gateway_state", state)
    return state


@pytest.fixture
def generate(monkeypatch):
    mocked = AsyncMock(side_effect=lambda *a, **k: content())
    monkeypatch.setattr(game_stock, "generate_content", mocked)
    return mocked


async def stock_count(db, **where):
    query = select(func.count()).select_from(GameStock)
    for key, value in where.items():
        query = query.where(getattr(GameStock, key) == value)
    return await db.scalar(query)


async def age_rows(db, days=1):
    for row in (await db.scalars(select(GameStock))).all():
        row.created_at = row.created_at - timedelta(days=days)
    await db.commit()


async def test_refill_fills_to_target(
    db_session, test_user_with_plan, gateway, generate, monkeypatch
):
    monkeypatch.setattr(game_stock, "DAILY_NEW_GAMES_PER_PLAN", 100)
    total = 0
    for _ in range(10):
        made = await game_stock.refill_once(db_session)
        total += made
        if not made:
            break
    assert total == BUCKETS_FREE * game_stock.STOCK_TARGET
    assert await stock_count(db_session, is_stale=False) == total
    row = (await db_session.scalars(select(GameStock))).first()
    assert len(row.content) == 5
    assert row.is_child is False


async def test_child_flag_stored_and_passed(db_session, test_user_with_plan, gateway, generate):
    user, _ = test_user_with_plan
    db_session.add(HomeProfile(user_id=user.id, is_child=True))
    await db_session.commit()
    await game_stock.refill_once(db_session)
    assert generate.call_args_list[0].args[0].is_child is True
    assert (await db_session.scalars(select(GameStock))).first().is_child is True


async def test_daily_cap_holds(db_session, test_user_with_plan, gateway, generate):
    assert await game_stock.refill_once(db_session) == BUCKETS_FREE  # first fill
    assert await game_stock.refill_once(db_session) == 0
    await age_rows(db_session)
    assert await game_stock.refill_once(db_session) == game_stock.DAILY_NEW_GAMES_PER_PLAN
    assert await game_stock.refill_once(db_session) == 0


async def test_stale_replacement_not_capped(db_session, test_user_with_plan, gateway, generate):
    await game_stock.refill_once(db_session)
    victim = (await db_session.scalars(select(GameStock))).first()
    victim.is_stale = True
    await db_session.commit()
    assert await game_stock.refill_once(db_session) == 1
    replacement = (
        await db_session.scalars(select(GameStock).order_by(GameStock.id.desc()))
    ).first()
    assert replacement.counts_toward_cap is False
    assert (victim.mode, victim.game_type) == (replacement.mode, replacement.game_type)
    assert await game_stock.refill_once(db_session) == 0


async def test_lesson_progress_makes_review_stock_stale(
    db_session, test_user_with_plan, gateway, generate
):
    plan = await db_session.scalar(select(StudyPlan))

    def lesson(day):
        return Lesson(
            study_plan_id=plan.id,
            title=f"L{day}",
            lesson_type="grammar",
            cefr_level="A1",
            week_number=1,
            day_number=day,
            unit_id="a1-unit-1",
            content={"explanation": "x"},
            is_completed=True,
            completed_at=games.now_utc(),
        )

    db_session.add(lesson(1))
    await db_session.commit()
    await game_stock.refill_once(db_session)
    review = await stock_count(db_session, mode="review", is_stale=False)
    assert review == 3
    assert await stock_count(db_session, mode="free", is_stale=True) == 0
    db_session.add(lesson(2))
    await db_session.commit()
    await game_stock.refill_once(db_session)
    assert await stock_count(db_session, mode="review", is_stale=True) == 3


async def test_review_skipped_without_completed_lessons(
    db_session, test_user_with_plan, gateway, generate
):
    await game_stock.refill_once(db_session)
    assert await stock_count(db_session, mode="review") == 0
    assert await stock_count(db_session, mode="prepare") == 0


async def test_new_plan_filled_first(db_session, test_user_with_plan, gateway, generate):
    user, _ = test_user_with_plan
    await game_stock.refill_once(db_session)
    await age_rows(db_session)
    generate.reset_mock()
    await make_study_plan(
        db_session,
        user_id=user.id,
        target_language="es-ES",
        cefr_level="A1",
        goals=[],
        duration_weeks=4,
        days_per_week=4,
        current_unit="",
        generated_plan={},
        is_active=True,
    )
    await db_session.commit()
    made = await game_stock.refill_once(db_session)
    assert made == BUCKETS_FREE + game_stock.DAILY_NEW_GAMES_PER_PLAN
    first_calls = [c.args[0].target_language for c in generate.call_args_list[:BUCKETS_FREE]]
    assert first_calls == ["es-ES"] * BUCKETS_FREE


@pytest.mark.parametrize("state", ["shared", "ready", "switching", "busy", "away"])
async def test_refill_skips_when_not_full_tier(
    db_session, test_user_with_plan, gateway, generate, state
):
    gateway.return_value = state
    assert await game_stock.refill_once(db_session) == 0
    generate.assert_not_called()


async def test_refill_yields_during_speech_session(
    db_session, test_user_with_plan, gateway, generate
):
    gateway.side_effect = ["off", "off", "busy"]
    assert await game_stock.refill_once(db_session) == 1
    assert await stock_count(db_session) == 1


async def test_failed_generation_is_skipped(db_session, test_user_with_plan, gateway, generate):
    generate.side_effect = [games.LLMResponseError("bad"), content(), content()]
    assert await game_stock.refill_once(db_session) == 2


async def test_failed_bucket_is_skipped_for_an_hour(
    db_session, test_user_with_plan, gateway, generate, monkeypatch
):
    monkeypatch.setattr(game_stock, "DAILY_NEW_GAMES_PER_PLAN", 100)
    now = [1000.0]
    monkeypatch.setattr(game_stock, "_now", lambda: now[0])
    failed = "detective"

    async def fail_one(request, _deadline):
        if request.game_type == failed:
            raise games.LLMResponseError("bad")
        return content()

    generate.side_effect = fail_one
    await game_stock.refill_once(db_session)
    assert failed in [c.args[0].game_type for c in generate.call_args_list]

    generate.reset_mock()
    await game_stock.refill_once(db_session)
    assert failed not in [c.args[0].game_type for c in generate.call_args_list]

    now[0] += game_stock.FAILED_BUCKET_COOLDOWN_SECONDS + 1
    generate.reset_mock()
    await game_stock.refill_once(db_session)
    assert failed in [c.args[0].game_type for c in generate.call_args_list]


async def test_generation_cancelled_when_state_leaves_off(
    db_session, test_user_with_plan, gateway, generate, monkeypatch
):
    monkeypatch.setattr(game_stock, "STATE_POLL_SECONDS", 0.01)
    cancelled = asyncio.Event()

    async def hang(_request, _deadline):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    generate.side_effect = hang
    # The pass check, the item check, one poll while generating, then a session opens.
    gateway.side_effect = ["off", "off", "off", "switching"]
    assert await game_stock.refill_once(db_session) == 0
    assert cancelled.is_set()
    assert await stock_count(db_session) == 0
    assert not game_stock.bucket_cooldowns  # a preempted bucket did not fail


async def stock_item(db, plan, mode="free", game_type="detective", sentence_prefix="A"):
    item = GameStock(
        study_plan_id=plan.id,
        mode=mode,
        game_type=game_type,
        target_language=plan.target_language,
        native_language="es",
        level=plan.cefr_level,
        content=[
            {**c.model_dump(), "sentence": f"{sentence_prefix}{i}"}
            for i, c in enumerate(content().challenges)
        ],
        created_at=games.now_utc(),
    )
    db.add(item)
    await db.commit()
    return item


async def test_recent_sentences_rejected_on_serve(db_session, test_user_with_plan):
    user, _ = test_user_with_plan
    plan = await db_session.scalar(select(StudyPlan))
    repeated = await stock_item(db_session, plan, sentence_prefix="R")
    fresh = await stock_item(db_session, plan, sentence_prefix="F")
    played = content().challenges
    db_session.add(
        GameSession(
            id="played",
            user_id=user.id,
            study_plan_id=plan.id,
            mode="free",
            target_language=plan.target_language,
            native_language="es",
            level="A1",
            status="completed",
            context={},
            challenges=[{**c.model_dump(), "sentence": "R0"} for c in played],
            answers=[{} for _ in played],
            created_at=games.now_utc(),
            deadline=games.now_utc(),
        )
    )
    await db_session.commit()
    taken = await game_stock.take_from_stock(db_session, plan, "free", "detective")
    assert taken.id == fresh.id
    await db_session.refresh(repeated)
    assert repeated.is_stale is True
    assert await game_stock.take_from_stock(db_session, plan, "free", "detective") is None


async def test_take_is_oldest_first_and_single_use(db_session, test_user_with_plan):
    plan = await db_session.scalar(select(StudyPlan))
    first = await stock_item(db_session, plan, sentence_prefix="A")
    first.created_at -= timedelta(hours=1)
    await stock_item(db_session, plan, sentence_prefix="B")
    await db_session.commit()
    one = await game_stock.take_from_stock(db_session, plan, "free", "detective")
    two = await game_stock.take_from_stock(db_session, plan, "free", "detective")
    assert one.id == first.id and two.id != first.id
    assert one.taken_at is not None
    assert await game_stock.take_from_stock(db_session, plan, "free", "detective") is None


async def test_take_loses_race_when_row_already_taken(db_session, test_user_with_plan, monkeypatch):
    plan = await db_session.scalar(select(StudyPlan))
    item = await stock_item(db_session, plan)

    real_claim = game_stock.claim_item

    async def claim_after_rival(db, row):
        row_id = row.id
        await db.execute(
            GameStock.__table__.update()
            .where(GameStock.id == row_id)
            .values(taken_at=games.now_utc())
        )
        return await real_claim(db, row)

    monkeypatch.setattr(game_stock, "claim_item", claim_after_rival)
    assert await game_stock.take_from_stock(db_session, plan, "free", "detective") is None
    assert item.id


async def test_refill_pass_skipped_when_lock_held(
    db_session, test_user_with_plan, gateway, generate, monkeypatch
):
    @asynccontextmanager
    async def held():
        yield False

    monkeypatch.setattr(game_stock, "pass_lock", held)
    assert await game_stock.run_pass() == 0
    generate.assert_not_called()


async def test_surplus_stale_rows_do_not_grant_uncapped_generation(
    db_session, test_user_with_plan, gateway, generate
):
    plan = await db_session.scalar(select(StudyPlan))
    for _ in range(game_stock.STOCK_TARGET):
        await stock_item(db_session, plan)
    old = await stock_item(db_session, plan)
    old.is_stale = True
    await db_session.commit()
    await game_stock.refill_once(db_session)
    await db_session.refresh(old)
    assert old.replaced is True
    assert await stock_count(db_session, game_type="detective", mode="free") == 4


def start_body(plan, mode="free"):
    return {"request_id": str(uuid4()), "study_plan_id": plan.id, "mode": mode}


async def test_serves_from_stock_without_llm(client, db_session, test_user_with_plan, monkeypatch):
    user, headers = test_user_with_plan
    plan = await db_session.scalar(select(StudyPlan))
    item = await stock_item(db_session, plan)
    boom = AsyncMock(side_effect=AssertionError("no LLM call when serving"))
    monkeypatch.setattr(games, "generate_content", boom)
    body = start_body(plan)
    res = await client.post("/api/games/detective", headers=headers, json=body)
    assert res.status_code == 202
    assert res.json()["status"] == "ready"
    assert res.json()["id"] == body["request_id"]
    assert len(res.json()["challenges"]) == 5
    boom.assert_not_awaited()
    session = await db_session.get(GameSession, body["request_id"])
    assert session.status == "ready" and session.answers == [{}] * 5
    assert session.is_child == item.is_child
    await db_session.refresh(item)
    assert item.taken_at is not None
    # An existing ready session is resumed before any further stock is touched.
    second = await stock_item(db_session, plan, sentence_prefix="B")
    again = await client.post("/api/games/detective", headers=headers, json=start_body(plan))
    assert again.json()["id"] == body["request_id"]
    await db_session.refresh(second)
    assert second.taken_at is None


async def test_stock_child_flag_carried(client, db_session, test_user_with_plan):
    _, headers = test_user_with_plan
    plan = await db_session.scalar(select(StudyPlan))
    item = await stock_item(db_session, plan)
    item.is_child = True
    await db_session.commit()
    body = start_body(plan)
    await client.post("/api/games/detective", headers=headers, json=body)
    assert (await db_session.get(GameSession, body["request_id"])).is_child is True


async def test_empty_stock_returns_happy_status(client, db_session, test_user_with_plan):
    user, headers = test_user_with_plan
    plan = await db_session.scalar(select(StudyPlan))
    finished = []
    for i in range(7):
        session = await ready_game(db_session, user, plan)
        await finish(db_session, user, session)
        session.completed_at = games.now_utc() - timedelta(hours=7 - i)
        finished.append(session.id)
    await db_session.commit()
    body = start_body(plan)
    res = await client.post("/api/games/detective", headers=headers, json=body)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "empty"
    assert data["first_games_pending"] is False
    assert [g["id"] for g in data["replayable"]] == finished[::-1][:5]
    assert {"id", "completed_at", "score", "total"} <= set(data["replayable"][0])
    assert data["replayable"][0]["score"] == 5
    # The request id is not consumed, so it may be used again once stock arrives.
    assert await db_session.get(GameRequest, body["request_id"]) is None
    other = await client.post("/api/games/sentence-order", headers=headers, json=start_body(plan))
    assert other.json()["replayable"] == []


async def test_new_plan_empty_is_first_games_pending(client, db_session, test_user_with_plan):
    _, headers = test_user_with_plan
    plan = await db_session.scalar(select(StudyPlan))
    res = await client.post("/api/games/detective", headers=headers, json=start_body(plan))
    assert res.status_code == 200
    assert res.json() == {"status": "empty", "replayable": [], "first_games_pending": True}


async def test_replay_creates_new_session_no_xp_change_beyond_cap(
    client, db_session, test_user_with_plan
):
    user, headers = test_user_with_plan
    plan = await db_session.scalar(select(StudyPlan))
    original = await ready_game(db_session, user, plan)
    await finish(db_session, user, original)
    xp = []
    previous = original
    for _ in range(4):
        path = f"/api/games/sessions/{previous.id}/replay"
        res = await client.post(path, headers=headers)
        assert res.status_code == 200
        assert res.json()["id"] != previous.id and res.json()["status"] == "ready"
        # A ready replay is returned instead of creating another.
        assert (await client.post(path, headers=headers)).json()["id"] == res.json()["id"]
        replay = await db_session.get(GameSession, res.json()["id"])
        assert replay.answers == [{}] * 5 and replay.study_plan_id == plan.id
        for i, challenge in enumerate(replay.challenges):
            for step, choice in (("detect", 1), ("correct", challenge["correct_index"])):
                await games.answer_game(
                    db_session,
                    user.id,
                    replay.id,
                    GameAnswer(challenge=i, step=step, choice=choice),
                )
        await db_session.refresh(replay)
        xp.append(replay.xp_earned)
        previous = replay
    await db_session.refresh(original)
    assert [original.xp_earned, *xp] == [15, 15, 15, 0, 0]
    shown = (await client.get("/api/games/detective", headers=headers)).json()
    assert shown["total"] == 5


async def test_replay_rejects_unfinished_and_foreign(
    client, db_session, test_user_with_plan, admin_user
):
    user, headers = test_user_with_plan
    _, foreign = admin_user
    plan = await db_session.scalar(select(StudyPlan))
    session = await ready_game(db_session, user, plan)
    path = f"/api/games/sessions/{session.id}/replay"
    assert (await client.post(path, headers=headers)).status_code == 409
    await finish(db_session, user, session)
    assert (await client.post(path, headers=foreign)).status_code == 404


async def test_replay_reshuffles_pairs(db_session, test_user_with_plan):
    user, _ = test_user_with_plan
    plan = await db_session.scalar(select(StudyPlan))
    pairs = [
        {
            "term": f"t{i}",
            "meaning": f"m{i}",
            "sentence": f"s{i}",
            "translation": f"x{i}",
            "source_id": "vocabulary:a",
            "choice_index": i,
        }
        for i in range(5)
    ]
    db_session.add(
        GameSession(
            id="done-pairs",
            user_id=user.id,
            study_plan_id=plan.id,
            mode="free",
            game_type="vocabulary-pairs",
            target_language=plan.target_language,
            native_language="es",
            level="A1",
            status="completed",
            context={},
            challenges=pairs,
            answers=[{"matched": True}] * 5,
            created_at=games.now_utc(),
            deadline=games.now_utc(),
        )
    )
    await db_session.commit()
    replay = await games.replay_game(db_session, user, "done-pairs")
    assert sorted(c["term"] for c in replay.challenges) == [f"t{i}" for i in range(5)]
    assert sorted(c["choice_index"] for c in replay.challenges) == list(range(5))
    assert replay.game_type == "vocabulary-pairs" and replay.status == "ready"
    assert replay.answers == [{}] * 5


async def test_stock_game_playable_when_llm_away(
    client, db_session, test_user_with_plan, monkeypatch
):
    user, headers = test_user_with_plan
    plan = await db_session.scalar(select(StudyPlan))
    await stock_item(db_session, plan)
    away = AsyncMock(side_effect=ConnectionError("llm away"))
    monkeypatch.setattr(games.llm_adapter, "structured_output", away)
    body = start_body(plan)
    res = await client.post("/api/games/detective", headers=headers, json=body)
    assert res.json()["status"] == "ready"
    session = await db_session.get(GameSession, body["request_id"])
    await finish(db_session, user, session)
    await db_session.refresh(session)
    assert session.status == "completed" and session.xp_earned == 15
    away.assert_not_awaited()


async def test_second_tab_losing_the_slot_keeps_its_item(
    client, db_session, test_user_with_plan, monkeypatch
):
    user, headers = test_user_with_plan
    plan = await db_session.scalar(select(StudyPlan))
    item = await stock_item(db_session, plan)
    rival = {}

    real = game_stock.take_from_stock

    async def taker_after_rival(db, p, mode, game_type):
        # The other tab's game appears after our active check and before our insert.
        winner = await ready_game(db, user, p)
        rival["id"] = winner.id
        return await real(db, p, mode, game_type)

    monkeypatch.setattr("app.routers.games.take_from_stock", taker_after_rival)
    res = await client.post("/api/games/detective", headers=headers, json=start_body(plan))
    assert res.status_code == 202
    assert res.json()["id"] == rival["id"]
    await db_session.refresh(item)
    assert item.taken_at is None


async def test_limited_user_at_quota_gets_402_and_stock_game_consumes_admission(
    client, db_session, test_user_with_plan, monkeypatch
):
    user, headers = test_user_with_plan
    monkeypatch.setattr(settings, "STRIPE_ENABLED", True)
    monkeypatch.setattr(settings, "FREEMIUM_GAMES_DAILY", 1)
    plan = await db_session.scalar(select(StudyPlan))
    item = await stock_item(db_session, plan)
    body = start_body(plan)
    res = await client.post("/api/games/detective", headers=headers, json=body)
    assert res.status_code == 202
    admission = await db_session.get(GameAdmission, body["request_id"])
    assert admission.status == "consumed"
    assert (await games.game_quota(db_session, user.id))["remaining"] == 0
    session = await db_session.get(GameSession, body["request_id"])
    session.status = "abandoned"
    other = await stock_item(db_session, plan, sentence_prefix="B")
    await db_session.commit()
    blocked = await client.post("/api/games/detective", headers=headers, json=start_body(plan))
    assert blocked.status_code == 402
    await db_session.refresh(other)
    assert other.taken_at is None and item.id
