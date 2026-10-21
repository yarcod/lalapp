from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.lalapp.adaptive import selector
from app.lalapp.adaptive import service as adaptive
from app.lalapp.learner import rating
from app.lalapp.learner.service import record_response
from app.lalapp.models import AdaptiveLesson, LearnerSkill
from app.models.lesson import Lesson
from app.schemas.lessons import ExerciseContent, LessonContent
from tests.conftest import make_study_plan

E = rating.Estimate
UNITS = [
    selector.Unit("u1", "Unit one", ("present-simple", "articles"), ("set1",)),
    selector.Unit("u2", "Unit two", ("past-simple",), ("set2",)),
    selector.Unit("u3", "Unit three", ("future",), ("set3",)),
]


def _at(level, offset=0.0, sd=0.3):
    return E(selector.mastery_theta(level) + offset, sd)


def _recommend(estimates, *, level="B1", goals=None, last_skill=None, current="u2", stats=None):
    return selector.recommend(
        estimates=estimates,
        plan_level=level,
        goals=goals,
        last_skill=last_skill,
        units=UNITS,
        current_unit_id=current,
        slug_stats=stats or {},
    )


def test_picks_the_goal_skill_furthest_below_mastery():
    estimates = {
        "grammar": _at("B1", 0.2),
        "vocabulary": _at("B1", -0.8),
        "reading": _at("B1", -0.3),
        "writing": _at("B1", -2.0),
    }
    goals = ["grammar", "vocabulary", "reading"]
    assert _recommend(estimates, goals=goals).skill == "vocabulary"
    # The previous lesson's skill is not repeated when another is nearly as weak.
    assert _recommend(estimates, goals=goals, last_skill="vocabulary").skill == "vocabulary"
    estimates["reading"] = _at("B1", -0.6)
    assert _recommend(estimates, goals=goals, last_skill="vocabulary").skill == "reading"


def test_unmeasured_skill_counts_as_plan_level_prior_with_wide_uncertainty():
    estimates = {"grammar": _at("B1", 0.0, sd=0.2)}
    # Vocabulary has no row: plan-level prior with sd 1.0 outranks a precise skill at mastery.
    assert _recommend(estimates, goals=["grammar", "vocabulary"]).skill == "vocabulary"


@pytest.mark.parametrize(
    "offset,expected_level",
    [(0.0, "B1"), (-1.0, "A2"), (1.6, "B2")],
)
def test_lesson_level_steps_down_when_struggling_and_up_when_far_ahead(offset, expected_level):
    estimate = _at("B1", offset)
    level, predicted = selector.choose_level(estimate, "B1", {})
    assert level == expected_level
    assert predicted >= selector.STEP_DOWN_BELOW


def test_lesson_level_uses_calibrated_difficulty():
    estimate = _at("B1", 0.0)
    # Generated B1 lessons turned out much harder than the anchor: step down.
    level, _ = selector.choose_level(estimate, "B1", {"B1": 0.8})
    assert level == "A2"


def test_level_is_clamped_at_scale_ends():
    assert selector.choose_level(_at("A1", -3.0), "A1", {})[0] == "A1"
    assert selector.choose_level(_at("C2", 3.0), "C2", {})[0] == "C2"


def test_weak_grammar_point_from_a_reached_unit_is_reviewed():
    stats = {
        "articles": selector.SlugStat(n=4, score_sum=1.0),
        "past-simple": selector.SlugStat(n=6, score_sum=5.5),
        "future": selector.SlugStat(n=5, score_sum=0.0),  # not reached yet: ignored
    }
    rec = _recommend({"grammar": _at("B1", -1.0, sd=0.5)}, goals=["grammar"], stats=stats)
    assert (rec.reason, rec.unit.id, rec.focus) == ("review", "u1", ("articles",))


def test_too_little_evidence_is_not_weakness():
    stats = {"articles": selector.SlugStat(n=2, score_sum=0.0)}
    rec = _recommend({"grammar": _at("B1", -1.0)}, goals=["grammar"], stats=stats)
    assert (rec.reason, rec.unit.id, rec.focus) == ("practice", "u2", ("past-simple",))


def test_grammar_far_ahead_previews_the_next_unit():
    rec = _recommend({"grammar": _at("B1", 1.0, sd=0.2)}, goals=["grammar"])
    assert (rec.reason, rec.unit.id) == ("preview", "u3")


def test_level_up_needs_confident_evidence_on_two_goal_skills():
    goals = ["grammar", "vocabulary", "reading"]
    strong = (_at("B2", 0.5, sd=0.3), 30)
    assert selector.level_up({"grammar": strong, "vocabulary": strong}, "B1", goals) == "B2"
    # Too little evidence on the second skill.
    assert selector.level_up({"grammar": strong, "vocabulary": (strong[0], 5)}, "B1", goals) is None
    # Above the threshold, but not by a standard deviation.
    shaky = (_at("B2", 0.1, sd=0.3), 30)
    assert selector.level_up({"grammar": strong, "vocabulary": shaky}, "B1", goals) is None
    # A weak evidenced goal skill blocks; a non-goal skill does not count.
    weak = (_at("B1", 0.0), 30)
    assert (
        selector.level_up({"grammar": strong, "vocabulary": strong, "reading": weak}, "B1", goals)
        is None
    )
    assert (
        selector.level_up({"grammar": strong, "vocabulary": strong, "writing": weak}, "B1", goals)
        == "B2"
    )
    assert selector.level_up({"grammar": strong, "vocabulary": strong}, "C2", goals) is None


def _generated_plan():
    days = [
        {
            "day": 1,
            "lesson_type": "grammar",
            "title": "A",
            "objectives": [],
            "estimated_minutes": 10,
            "unit_id": "a1-unit-1",
        },
        {
            "day": 2,
            "lesson_type": "grammar",
            "title": "B",
            "objectives": [],
            "estimated_minutes": 10,
            "unit_id": "a1-unit-2",
        },
    ]
    return {"weekly_plan": [{"week": 1, "days": days}]}


async def _plan(db_session, user_id, **kwargs):
    defaults = dict(
        cefr_level="A1",
        target_language="en-US",
        goals=["grammar", "vocabulary"],
        duration_weeks=1,
        days_per_week=2,
        current_unit="a1-unit-1",
        generated_plan=_generated_plan(),
        is_active=True,
    )
    defaults.update(kwargs)
    plan = await make_study_plan(db_session, user_id=user_id, **defaults)
    await db_session.commit()
    return plan


def test_current_unit_follows_the_day_grid():
    class Plan:
        days_per_week = 2
        duration_weeks = 1
        progress_day = 1
        generated_plan = _generated_plan()
        current_unit = "a1-unit-1"

    assert adaptive.current_unit_id(Plan) == "a1-unit-2"
    Plan.generated_plan = {}
    assert adaptive.current_unit_id(Plan) == "a1-unit-1"


async def test_slug_stats_and_calibration_come_from_the_response_log(db_session, test_user):
    user, _ = test_user
    plan = await _plan(db_session, user.id)
    for score in (0.0, 0.0, 1.0):
        await record_response(
            db_session,
            study_plan_id=plan.id,
            skill="grammar",
            item_key="tpl:en-US:lesson:grammar:multiple_choice:A1:articles",
            item_level="A1",
            score=score,
            source="lesson",
        )
    stats = await adaptive.slug_stats(db_session, plan.user_language_id)
    assert stats["articles"].n == 3 and stats["articles"].score_sum == 1.0
    difficulty = await adaptive.lesson_difficulty(db_session, "en-US")
    # Mostly failed: calibrated above the anchor, but shrunk toward it.
    assert rating.CEFR_ITEM_DIFFICULTY["A1"] < difficulty["grammar"]["A1"] < -1.5


def _lesson_content():
    return LessonContent(
        lesson_type="grammar",
        title="Articles again",
        cefr_level="A1",
        explanation={"text": "x"},
        exercises=[
            ExerciseContent(
                type="multiple_choice", question="a or an?", options=["a", "an"], correct="an"
            )
        ],
        grammar_refs=["articles"],
    )


async def test_next_api_generates_once_outside_the_day_grid(client, db_session, test_user):
    user, headers = test_user
    plan = await _plan(db_session, user.id)
    plan_id = plan.id

    empty = await client.get("/api/lalapp/next", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["lesson"] is None
    assert empty.json()["unit_title"]

    generator = AsyncMock(return_value=_lesson_content())
    with patch("app.lalapp.adaptive.service.generate_lesson", generator):
        created = await client.post("/api/lalapp/next", headers=headers)
        again = await client.post("/api/lalapp/next", headers=headers)
    assert created.status_code == 200
    assert generator.await_count == 1
    lesson = created.json()["lesson"]
    assert again.json()["lesson"]["id"] == lesson["id"]
    assert lesson["title"] == "Articles again"
    kwargs = generator.await_args.kwargs
    assert kwargs["target_language"] == "en-US" and kwargs["native_language"] == "es"

    row = await db_session.get(Lesson, lesson["id"])
    assert (row.week_number, row.day_number) == (adaptive.ADAPTIVE_WEEK, 1)
    meta = await db_session.get(AdaptiveLesson, lesson["id"])
    assert meta.study_plan_id == plan_id and 0 < meta.predicted_success < 1

    # Upstream's plan views do not count it as pending or as part of today.
    with patch("app.routers.study_plan.generate_lesson", AsyncMock(return_value=_lesson_content())):
        today = (await client.get("/api/study-plan/today", headers=headers)).json()
    assert today["pending_count"] == 0
    assert lesson["id"] not in [item["id"] for item in today["lessons"]]
    pending = (await client.get("/api/study-plan/pending-lessons", headers=headers)).json()
    assert pending == []

    # Once completed, the next request generates a new one with the next number.
    await client.post(f"/api/lessons/{lesson['id']}/complete", headers=headers)
    with patch("app.lalapp.adaptive.service.generate_lesson", generator):
        newer = (await client.post("/api/lalapp/next", headers=headers)).json()["lesson"]
    assert newer["id"] != lesson["id"]
    db_session.expire_all()
    assert (await db_session.get(Lesson, newer["id"])).day_number == 2


async def test_next_api_reports_generation_failure(client, db_session, test_user):
    user, headers = test_user
    await _plan(db_session, user.id)
    with patch(
        "app.lalapp.adaptive.service.generate_lesson",
        AsyncMock(side_effect=RuntimeError("model down")),
    ):
        response = await client.post("/api/lalapp/next", headers=headers)
    assert response.status_code == 503
    assert (await db_session.scalars(select(AdaptiveLesson))).all() == []


async def test_next_api_offers_level_up(client, db_session, test_user):
    user, headers = test_user
    plan = await _plan(db_session, user.id)
    for skill in ("grammar", "vocabulary"):
        db_session.add(
            LearnerSkill(
                user_language_id=plan.user_language_id,
                skill=skill,
                theta=selector.mastery_theta("A2") + 0.6,
                theta_sd=0.25,
                n=40,
            )
        )
    await db_session.commit()
    data = (await client.get("/api/lalapp/next", headers=headers)).json()
    assert data["level_up"]["next_level"] == "A2"
    assert data["level_up"]["days_per_week"] == 2


async def test_next_api_without_plan_or_when_disabled(client, test_user, monkeypatch):
    _, headers = test_user
    assert (await client.get("/api/lalapp/next", headers=headers)).json() is None
    monkeypatch.setattr("app.lalapp.config.lalapp_settings.ADAPTIVE_ENABLED", False)
    assert (await client.get("/api/lalapp/next", headers=headers)).status_code == 404
