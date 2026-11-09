from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.models.game import GameSession, GameStock
from app.models.lesson import Lesson
from app.models.study_plan import StudyPlan
from app.services import game_stock, games
from tests.conftest import make_study_plan
from tests.test_games import content

BUCKETS_FREE = 3  # detective, sentence-order, vocabulary-pairs


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
    user.is_child = True
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
