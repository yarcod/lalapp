from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.lalapp.config import lalapp_settings
from app.lalapp.learner import hooks, rating
from app.lalapp.learner.service import record_response
from app.lalapp.models import ItemRating, LearnerResponse, LearnerSkill
from tests.conftest import make_study_plan


async def _plan(db_session, user_id, *, level="B1", target_language="en-US"):
    plan = await make_study_plan(
        db_session,
        user_id=user_id,
        cefr_level=level,
        target_language=target_language,
        goals=["grammar"],
        duration_weeks=4,
        days_per_week=4,
        current_unit="",
        generated_plan={},
        is_active=True,
    )
    await db_session.commit()
    return plan


async def _skill(db_session, plan, skill):
    user_language_id = plan.user_language_id
    db_session.expire_all()
    return await db_session.scalar(
        select(LearnerSkill).where(
            LearnerSkill.user_language_id == user_language_id, LearnerSkill.skill == skill
        )
    )


async def test_first_response_creates_rows_from_plan_level_prior(db_session, test_user):
    user, _ = test_user
    plan = await _plan(db_session, user.id, level="B1")

    await record_response(
        db_session,
        study_plan_id=plan.id,
        skill="grammar",
        item_key="tpl:en-US:test:B1",
        item_level="B1",
        score=1.0,
        source="lesson",
    )

    skill = await _skill(db_session, plan, "grammar")
    assert skill.n == 1
    assert skill.theta > rating.learner_prior("B1").mean
    assert skill.theta_sd < rating.LEARNER_PRIOR_SD
    item = await db_session.get(ItemRating, "tpl:en-US:test:B1")
    assert item.n == 1
    assert item.difficulty < rating.item_prior("B1").mean
    log = (await db_session.scalars(select(LearnerResponse))).all()
    assert [(r.skill, r.source, r.score) for r in log] == [("grammar", "lesson", 1.0)]
    assert log[0].expected == pytest.approx(rating.MASTERY_PROBABILITY)


async def test_skill_survives_new_study_plan(db_session, test_user):
    user, _ = test_user
    first = await _plan(db_session, user.id, level="A2")
    for _ in range(3):
        await record_response(
            db_session,
            study_plan_id=first.id,
            skill="vocabulary",
            item_key="tpl:en-US:vocab:A2",
            item_level="A2",
            score=0.0,
            source="lesson",
        )
    # Plan-owned rows cascade away with the plan; the learner model must not.
    await db_session.delete(first)
    await db_session.commit()
    second = await _plan(db_session, user.id, level="B2")

    await record_response(
        db_session,
        study_plan_id=second.id,
        skill="vocabulary",
        item_key="tpl:en-US:vocab:B2",
        item_level="B2",
        score=1.0,
        source="lesson",
    )

    skill = await _skill(db_session, second, "vocabulary")
    assert skill.n == 4
    count = await db_session.scalar(select(func.count()).select_from(LearnerSkill))
    assert count == 1


async def test_failures_are_swallowed_and_disabled_flag_skips(
    db_session, test_user, monkeypatch, caplog
):
    user, _ = test_user
    plan = await _plan(db_session, user.id)

    await record_response(
        db_session,
        study_plan_id=plan.id,
        skill="juggling",
        item_key="x",
        item_level=None,
        score=1.0,
        source="lesson",
    )
    assert "Learner model update failed" in caplog.text

    monkeypatch.setattr(lalapp_settings, "LEARNER_MODEL_ENABLED", False)
    await record_response(
        db_session,
        study_plan_id=plan.id,
        skill="grammar",
        item_key="x",
        item_level=None,
        score=1.0,
        source="lesson",
    )
    assert await db_session.scalar(select(func.count()).select_from(LearnerResponse)) == 0


async def test_lesson_hook_maps_skill_and_pools_template_key(db_session, test_user):
    user, _ = test_user
    plan = await _plan(db_session, user.id)
    lesson = SimpleNamespace(
        study_plan_id=plan.id,
        lesson_type="grammar",
        cefr_level="B1",
        content={"grammar_refs": ["present-perfect"]},
    )

    await hooks.on_lesson_exercise_answered(
        db_session,
        lesson=lesson,
        exercise=SimpleNamespace(score=0.8, exercise_type="free_write"),
        target_language="en-US",
    )

    response = await db_session.scalar(select(LearnerResponse))
    assert response.skill == "writing"
    assert response.item_key == "tpl:en-US:lesson:grammar:free_write:B1:present-perfect"


async def test_practice_hook_skips_replays_and_scores_fraction(db_session, test_user):
    user, _ = test_user
    plan = await _plan(db_session, user.id)
    exercise = SimpleNamespace(
        questions=[{}, {}, {}, {}, {}],
        target_language="en-US",
        exercise_type="dialogue",
        level="B1",
    )
    attempt = SimpleNamespace(study_plan_id=plan.id, score=4)

    await hooks.on_practice_attempt(
        db_session, kind="listening", attempt=attempt, exercise=exercise, is_replay=True
    )
    assert await db_session.scalar(select(func.count()).select_from(LearnerResponse)) == 0

    await hooks.on_practice_attempt(
        db_session, kind="listening", attempt=attempt, exercise=exercise, is_replay=False
    )
    response = await db_session.scalar(select(LearnerResponse))
    assert (response.skill, response.score) == ("listening", 0.8)


async def test_flashcard_review_endpoint_feeds_learner_model(client, db_session, test_user):
    from app.models.flashcard import Flashcard

    user, headers = test_user
    plan = await _plan(db_session, user.id, level="A1")
    card = Flashcard(
        user_id=user.id,
        study_plan_id=plan.id,
        word="test",
        definition="a test",
        example_sentence="Test.",
        translation="prueba",
    )
    db_session.add(card)
    await db_session.commit()

    response = await client.post(
        f"/api/flashcards/{card.id}/review",
        headers=headers,
        json={"quality": 5, "review_id": str(uuid4())},
    )
    assert response.status_code == 200

    learner = await client.get("/api/lalapp/learner", headers=headers)
    assert learner.status_code == 200
    [language] = learner.json()
    assert language["target_language"] == "en-US"
    [skill] = language["skills"]
    assert skill["skill"] == "vocabulary"
    assert skill["n"] == 1
    assert skill["cefr"] == "A1"
