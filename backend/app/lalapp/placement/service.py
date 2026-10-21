from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.assessment_bank import get_assessment_bank
from app.lalapp.learner.rating import SKILLS, Estimate
from app.lalapp.models import ItemRating, LearnerSkill, PlacementSession
from app.lalapp.placement import engine
from app.models.user_language import UserLanguage

# Skills the text bank cannot measure start from the overall estimate with at least this spread.
UNMEASURED_SKILL_MIN_SD = 0.8

_rng = random.SystemRandom()


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _bank(target_language: str) -> dict:
    return {item.id: item for item in get_assessment_bank(target_language)}


async def _estimates(db: AsyncSession, target_language: str, bank: dict) -> dict[str, Estimate]:
    keys = {engine.bank_item_key(target_language, item_id): item_id for item_id in bank}
    rows = (await db.scalars(select(ItemRating).where(ItemRating.item_key.in_(keys)))).all()
    stored = {keys[row.item_key]: Estimate(row.difficulty, row.difficulty_sd) for row in rows}
    return {
        item_id: stored.get(item_id) or engine.bank_item_prior(item)
        for item_id, item in bank.items()
    }


def skill_estimate(state: engine.PlacementState, skill: str) -> Estimate:
    if skill in state.skills:
        return state.skills[skill]
    return Estimate(state.overall.mean, max(state.overall.sd, UNMEASURED_SKILL_MIN_SD))


async def start(
    db: AsyncSession, user_id: int, target_language: str, self_level: str | None
) -> PlacementSession:
    bank = _bank(target_language)
    if not bank:
        raise HTTPException(status_code=404, detail="placement_bank_unavailable")
    skills = sorted({item.skill for item in bank.values()})
    state = engine.PlacementState.start(skills, self_level)
    first = engine.next_item(
        state, list(bank.values()), await _estimates(db, target_language, bank), _rng
    )
    session = PlacementSession(
        id=str(uuid.uuid4()),
        user_id=user_id,
        target_language=target_language,
        status="active",
        state=state.to_json(),
        pending_item_id=first.id if first else None,
        created_at=_now(),
    )
    db.add(session)
    await db.commit()
    return session


async def answer(
    db: AsyncSession, user_id: int, session_id: str, question_id: str, answer_text: str
) -> PlacementSession:
    session = await db.scalar(
        select(PlacementSession)
        .where(PlacementSession.id == session_id, PlacementSession.user_id == user_id)
        .with_for_update()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="placement_not_found")
    if session.status != "active":
        raise HTTPException(status_code=409, detail="placement_finished")
    if question_id != session.pending_item_id:
        raise HTTPException(status_code=409, detail="placement_question_mismatch")

    bank = _bank(session.target_language)
    item = bank[question_id]
    estimates = await _estimates(db, session.target_language, bank)
    state = engine.PlacementState.from_json(session.state)
    _, new_item = engine.record(state, item, estimates[item.id], answer_text)
    await _store_item(db, engine.bank_item_key(session.target_language, item.id), new_item)
    estimates[item.id] = new_item

    remaining = len(bank) - len(state.asked)
    next_question = None
    if not engine.is_finished(state, remaining):
        next_question = engine.next_item(state, list(bank.values()), estimates, _rng)
    session.state = state.to_json()
    session.pending_item_id = next_question.id if next_question else None
    if next_question is None:
        session.status = "done"
        session.result = engine.result(state)
        session.completed_at = _now()
        await _seed_learner_skills(db, user_id, session.target_language, state)
    await db.commit()
    return session


async def _store_item(db: AsyncSession, key: str, estimate: Estimate) -> None:
    row = await db.get(ItemRating, key, with_for_update=True)
    if row is None:
        row = ItemRating(item_key=key, n=0)
        db.add(row)
    row.difficulty, row.difficulty_sd = estimate.mean, estimate.sd
    row.n = (row.n or 0) + 1
    row.updated_at = _now()


async def _seed_learner_skills(
    db: AsyncSession, user_id: int, target_language: str, state: engine.PlacementState
) -> None:
    """A finished placement replaces the learner's estimates for that language."""
    user_language = await db.scalar(
        select(UserLanguage).where(
            UserLanguage.user_id == user_id, UserLanguage.target_language == target_language
        )
    )
    if user_language is None:
        return  # Seeded lazily from the stored result once the language exists.
    existing = {
        row.skill: row
        for row in await db.scalars(
            select(LearnerSkill).where(LearnerSkill.user_language_id == user_language.id)
        )
    }
    for skill in SKILLS:
        estimate = skill_estimate(state, skill)
        row = existing.get(skill)
        if row is None:
            row = LearnerSkill(user_language_id=user_language.id, skill=skill, n=0)
            db.add(row)
        row.theta, row.theta_sd = estimate.mean, estimate.sd
        row.updated_at = _now()


async def latest_placement_estimate(
    db: AsyncSession, user_id: int, target_language: str, skill: str
) -> Estimate | None:
    session = await db.scalar(
        select(PlacementSession)
        .where(
            PlacementSession.user_id == user_id,
            PlacementSession.target_language == target_language,
            PlacementSession.status == "done",
        )
        .order_by(PlacementSession.completed_at.desc())
        .limit(1)
    )
    if session is None:
        return None
    return skill_estimate(engine.PlacementState.from_json(session.state), skill)
