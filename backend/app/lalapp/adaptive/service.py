from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.curriculum import COMPLETION_UNIT_IDS, get_curriculum_units
from app.lalapp.adaptive import selector
from app.lalapp.learner import rating
from app.lalapp.models import AdaptiveLesson, ItemRating, LearnerResponse, LearnerSkill
from app.models.lesson import Exercise, Lesson
from app.models.study_plan import StudyPlan
from app.services.lesson_generator import generate_lesson

logger = logging.getLogger(__name__)

# Adaptive lessons are stored after every possible plan week, so upstream's day grid, pending
# counts and completion gate never see them; day_number numbers them within the plan.
ADAPTIVE_WEEK = 1000

SLUG_HISTORY = 300
# Calibrated lesson difficulty is shrunk toward the CEFR anchor with this many pseudo-responses.
DIFFICULTY_PRIOR_N = 10.0


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def skill_estimates(
    db: AsyncSession, user_language_id: int
) -> dict[str, tuple[rating.Estimate, int]]:
    rows = (
        await db.scalars(
            select(LearnerSkill).where(LearnerSkill.user_language_id == user_language_id)
        )
    ).all()
    now = _now()
    return {
        row.skill: (
            rating.drift(
                rating.Estimate(row.theta, row.theta_sd),
                (now - row.updated_at).total_seconds() / 86400,
            ),
            row.n,
        )
        for row in rows
    }


async def slug_stats(db: AsyncSession, user_language_id: int) -> dict[str, selector.SlugStat]:
    """Recent lesson results per grammar point, read from the learner response log."""
    rows = (
        await db.execute(
            select(LearnerResponse.item_key, LearnerResponse.score)
            .where(
                LearnerResponse.user_language_id == user_language_id,
                LearnerResponse.source == "lesson",
            )
            .order_by(LearnerResponse.id.desc())
            .limit(SLUG_HISTORY)
        )
    ).all()
    totals: dict[str, list[float]] = {}
    for item_key, score in rows:
        # tpl:{language}:lesson:{lesson_type}:{exercise_type}:{cefr}:{grammar}
        slug = item_key.rsplit(":", 1)[-1]
        if slug and slug != "-":
            totals.setdefault(slug, []).append(score)
    return {slug: selector.SlugStat(len(s), sum(s)) for slug, s in totals.items()}


async def lesson_difficulty(db: AsyncSession, target_language: str) -> dict[str, dict[str, float]]:
    """Calibrated difficulty of generated lessons per lesson type and CEFR level."""
    prefix = f"tpl:{target_language}:lesson:"
    rows = (
        await db.execute(
            select(ItemRating.item_key, ItemRating.difficulty, ItemRating.n).where(
                ItemRating.item_key.startswith(prefix, autoescape=True), ItemRating.n > 0
            )
        )
    ).all()
    sums: dict[tuple[str, str], tuple[float, float]] = {}
    for item_key, difficulty, n in rows:
        parts = item_key[len(prefix) :].split(":")
        if len(parts) < 3 or parts[2] not in rating.CEFR_ITEM_DIFFICULTY:
            continue
        key = (parts[0], parts[2])
        total, weight = sums.get(key, (0.0, 0.0))
        sums[key] = (total + difficulty * n, weight + n)
    result: dict[str, dict[str, float]] = {}
    for (lesson_type, level), (total, weight) in sums.items():
        anchor = rating.CEFR_ITEM_DIFFICULTY[level]
        result.setdefault(lesson_type, {})[level] = (total + anchor * DIFFICULTY_PRIOR_N) / (
            weight + DIFFICULTY_PRIOR_N
        )
    return result


def plan_units(plan: StudyPlan) -> list[selector.Unit]:
    return [
        selector.Unit(
            id=u.id,
            title=u.title,
            grammar_points=tuple(u.grammar_points),
            vocabulary_set_ids=tuple(u.vocabulary_set_ids),
        )
        for u in get_curriculum_units(plan.cefr_level, plan.target_language)
        if u.id not in COMPLETION_UNIT_IDS
    ]


def plan_position(plan: StudyPlan) -> tuple[int, int]:
    """Current week and day of the plan, clamped to its last day."""
    days_per_week = max(plan.days_per_week, 1)
    total = max(plan.duration_weeks * days_per_week, 1)
    progress = min(plan.progress_day, total - 1)
    return progress // days_per_week + 1, progress % days_per_week + 1


def current_unit_id(plan: StudyPlan) -> str | None:
    """The unit scheduled for the plan's current day, falling back to the plan's current unit."""
    week_number, day_number = plan_position(plan)
    generated = plan.generated_plan if isinstance(plan.generated_plan, dict) else {}
    for week in generated.get("weekly_plan") or []:
        if not isinstance(week, dict) or week.get("week") != week_number:
            continue
        for day in week.get("days") or []:
            unit_id = day.get("unit_id") if isinstance(day, dict) else None
            if day.get("day") == day_number and unit_id and unit_id not in COMPLETION_UNIT_IDS:
                return unit_id
    return plan.current_unit or None


async def open_lesson(db: AsyncSession, plan_id: int) -> tuple[Lesson, AdaptiveLesson] | None:
    """The newest adaptive lesson of the plan that is not completed yet."""
    row = (
        await db.execute(
            select(Lesson, AdaptiveLesson)
            .join(AdaptiveLesson, AdaptiveLesson.lesson_id == Lesson.id)
            .where(AdaptiveLesson.study_plan_id == plan_id, Lesson.is_completed.is_(False))
            .order_by(Lesson.id.desc())
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def recommend(db: AsyncSession, plan: StudyPlan) -> selector.Recommendation:
    estimates = await skill_estimates(db, plan.user_language_id)
    last_skill = await db.scalar(
        select(AdaptiveLesson.skill)
        .where(AdaptiveLesson.study_plan_id == plan.id)
        .order_by(AdaptiveLesson.created_at.desc(), AdaptiveLesson.lesson_id.desc())
        .limit(1)
    )
    return selector.recommend(
        estimates={skill: estimate for skill, (estimate, _) in estimates.items()},
        plan_level=plan.cefr_level,
        goals=plan.goals,
        last_skill=last_skill,
        units=plan_units(plan),
        current_unit_id=current_unit_id(plan),
        slug_stats=await slug_stats(db, plan.user_language_id),
        difficulty=await lesson_difficulty(db, plan.target_language),
    )


async def level_up(db: AsyncSession, plan: StudyPlan) -> str | None:
    if plan.cefr_level not in rating.CEFR_LEVELS:
        return None
    return selector.level_up(
        await skill_estimates(db, plan.user_language_id), plan.cefr_level, plan.goals
    )


def _topic(recommendation: selector.Recommendation) -> str:
    unit = recommendation.unit
    if unit is None:
        return f"{recommendation.skill} practice"
    if recommendation.reason == "review":
        return f"{unit.title}: review of {', '.join(recommendation.focus)}"
    return unit.title


async def create_lesson(
    db: AsyncSession, plan: StudyPlan, *, native_language: str | None
) -> tuple[Lesson, AdaptiveLesson]:
    """Generate the recommended lesson, or return the open one if the plan already has it.

    Raises when generation fails; the caller turns that into an HTTP error.
    """
    existing = await open_lesson(db, plan.id)
    if existing:
        return existing

    plan_id = plan.id
    recommendation = await recommend(db, plan)
    unit = recommendation.unit
    unit_id = unit.id if unit else ""
    previous = (
        (
            await db.scalars(
                select(Lesson)
                .where(Lesson.study_plan_id == plan_id, Lesson.unit_id == unit_id)
                .order_by(Lesson.week_number, Lesson.day_number, Lesson.id)
            )
        ).all()
        if unit_id
        else []
    )
    week_number, day_number = plan_position(plan)
    content = await generate_lesson(
        cefr_level=recommendation.cefr_level,
        lesson_type=recommendation.skill,
        topic=_topic(recommendation),
        week=week_number,
        day=day_number,
        unit_id=unit_id,
        grammar_points=list(recommendation.focus),
        vocabulary_set_ids=list(unit.vocabulary_set_ids) if unit else [],
        target_language=plan.target_language,
        native_language=native_language,
        previous_lessons=[
            {"title": p.title, "lesson_type": p.lesson_type, "content": p.content} for p in previous
        ],
    )
    content_dict = content.model_dump()
    exercises = content_dict.get("exercises") or []
    if not exercises:
        raise ValueError("Lesson generated with no exercises")

    sequence = (
        await db.scalar(
            select(func.coalesce(func.max(Lesson.day_number), 0)).where(
                Lesson.study_plan_id == plan_id, Lesson.week_number == ADAPTIVE_WEEK
            )
        )
    ) + 1
    lesson = Lesson(
        study_plan_id=plan_id,
        title=(content_dict.get("title") or _topic(recommendation))[:255],
        lesson_type=recommendation.skill,
        cefr_level=recommendation.cefr_level,
        week_number=ADAPTIVE_WEEK,
        day_number=sequence,
        unit_id=unit_id or None,
        content=content_dict,
    )
    try:
        db.add(lesson)
        await db.flush()
        for ex in exercises:
            db.add(
                Exercise(
                    lesson_id=lesson.id,
                    exercise_type=ex.get("type", "multiple_choice"),
                    question=ex.get("question", ""),
                    options=ex.get("options"),
                    correct_answer=ex.get("correct", ""),
                    explanation=ex.get("explanation"),
                )
            )
        meta = AdaptiveLesson(
            lesson_id=lesson.id,
            study_plan_id=plan_id,
            skill=recommendation.skill,
            cefr_level=recommendation.cefr_level,
            unit_id=unit_id or None,
            focus=list(recommendation.focus),
            reason=recommendation.reason,
            predicted_success=round(recommendation.predicted_success, 4),
            created_at=_now(),
        )
        db.add(meta)
        await db.commit()
    except IntegrityError:
        # A concurrent request created a lesson with the same number first; use that one.
        await db.rollback()
        existing = await open_lesson(db, plan_id)
        if existing:
            return existing
        raise
    await db.refresh(lesson)
    return lesson, meta
