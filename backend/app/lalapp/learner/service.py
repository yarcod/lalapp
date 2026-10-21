from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.lalapp.config import lalapp_settings
from app.lalapp.learner import rating
from app.lalapp.models import ItemRating, LearnerResponse, LearnerSkill
from app.lalapp.placement.service import latest_placement_estimate
from app.lalapp.rhythm.service import SKILL_MILESTONE_MIN_N, add_milestone
from app.models.study_plan import StudyPlan

logger = logging.getLogger(__name__)

SKILLS = rating.SKILLS


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def record_response(
    db: AsyncSession,
    *,
    study_plan_id: int,
    skill: str,
    item_key: str,
    item_level: str | None,
    score: float,
    source: str,
) -> None:
    """Fold one scored response into the learner's skill and the item's difficulty.

    Best-effort: callers invoke this after their own commit. The update runs in its own
    session on the caller's engine, so a failure here is logged and rolled back without
    expiring or otherwise affecting the caller's objects.
    """
    if not lalapp_settings.LEARNER_MODEL_ENABLED or db.bind is None:
        return
    try:
        async with AsyncSession(db.bind, expire_on_commit=False) as session:
            await _record(session, study_plan_id, skill, item_key, item_level, score, source)
            await session.commit()
    except Exception:
        logger.exception("Learner model update failed for item %s", item_key)


async def _record(
    db: AsyncSession,
    study_plan_id: int,
    skill: str,
    item_key: str,
    item_level: str | None,
    score: float,
    source: str,
) -> None:
    if skill not in SKILLS:
        raise ValueError(f"Unknown skill: {skill}")
    plan = await db.get(StudyPlan, study_plan_id)
    if plan is None:
        return
    now = _now()

    learner_row = await db.scalar(
        select(LearnerSkill)
        .where(
            LearnerSkill.user_language_id == plan.user_language_id,
            LearnerSkill.skill == skill,
        )
        .with_for_update()
    )
    if learner_row is None:
        prior = await latest_placement_estimate(
            db, plan.user_id, plan.target_language, skill
        ) or rating.learner_prior(plan.cefr_level)
        learner_row = LearnerSkill(
            user_language_id=plan.user_language_id,
            skill=skill,
            theta=prior.mean,
            theta_sd=prior.sd,
            n=0,
            updated_at=now,
        )
        db.add(learner_row)
    learner = rating.drift(
        rating.Estimate(learner_row.theta, learner_row.theta_sd),
        (now - learner_row.updated_at).total_seconds() / 86400,
    )

    item_row = await db.scalar(
        select(ItemRating).where(ItemRating.item_key == item_key).with_for_update()
    )
    if item_row is None:
        prior = rating.item_prior(item_level)
        item_row = ItemRating(
            item_key=item_key, difficulty=prior.mean, difficulty_sd=prior.sd, n=0, updated_at=now
        )
        db.add(item_row)
    item = rating.Estimate(item_row.difficulty, item_row.difficulty_sd)

    new_learner, new_item = rating.update(learner, item, score)
    db.add(
        LearnerResponse(
            user_language_id=plan.user_language_id,
            item_key=item_key,
            skill=skill,
            source=source,
            score=score,
            expected=rating.expected_score(learner, item),
            theta_before=learner.mean,
            difficulty_before=item.mean,
            created_at=now,
        )
    )
    learner_row.theta, learner_row.theta_sd = new_learner.mean, new_learner.sd
    learner_row.n += 1
    learner_row.updated_at = now
    # Informational first: the skill's estimate is above the plan's level for the first time at
    # this level, once there is enough evidence.
    level_after = rating.cefr_from_theta(new_learner.mean)
    plan_level = rating.normalize_level(plan.cefr_level)
    if (
        learner_row.n >= SKILL_MILESTONE_MIN_N
        and plan_level is not None
        and rating.CEFR_LEVELS.index(level_after) > rating.CEFR_LEVELS.index(plan_level)
    ):
        await add_milestone(
            db,
            plan.user_language_id,
            f"skill_level:{skill}:{level_after}",
            {"skill": skill, "level": level_after},
        )
    item_row.difficulty, item_row.difficulty_sd = new_item.mean, new_item.sd
    item_row.n += 1
    item_row.updated_at = now
