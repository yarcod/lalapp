"""Adapters from upstream FreeLingo events to learner-model evidence.

Each function is called from exactly one ``lalapp-hook`` line in upstream code, after that
code has committed its own work.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.lalapp.learner.service import record_response
from app.models.study_plan import StudyPlan

_LESSON_TYPE_SKILLS = {
    "grammar": "grammar",
    "vocabulary": "vocabulary",
    "reading": "reading",
    "writing": "writing",
    "listening": "listening",
    "speaking": "speaking",
}
_EXERCISE_TYPE_SKILLS = {"free_write": "writing", "pronunciation": "speaking"}
_GAME_SKILLS = {
    "detective": "grammar",
    "sentence-order": "grammar",
    "vocabulary-pairs": "vocabulary",
}


def _lesson_skill(lesson_type: str, exercise_type: str) -> str:
    return _EXERCISE_TYPE_SKILLS.get(exercise_type) or _LESSON_TYPE_SKILLS.get(
        lesson_type, "grammar"
    )


async def on_lesson_exercise_answered(
    db: AsyncSession, *, lesson: Any, exercise: Any, target_language: str
) -> None:
    if exercise.score is None:
        return
    grammar_refs = getattr(lesson, "grammar_refs", None) or (lesson.content or {}).get(
        "grammar_refs"
    )
    grammar = grammar_refs[0] if grammar_refs else "-"
    item_key = (
        f"tpl:{target_language}:lesson:{lesson.lesson_type}:{exercise.exercise_type}:"
        f"{lesson.cefr_level}:{grammar}"
    )
    await record_response(
        db,
        study_plan_id=lesson.study_plan_id,
        skill=_lesson_skill(lesson.lesson_type, exercise.exercise_type),
        item_key=item_key,
        item_level=lesson.cefr_level,
        score=float(exercise.score),
        source="lesson",
    )


async def on_practice_attempt(
    db: AsyncSession, *, kind: str, attempt: Any, exercise: Any, is_replay: bool
) -> None:
    """Listening or reading comprehension attempt; replays are skipped as memory effects."""
    questions = exercise.questions or []
    if is_replay or not questions or attempt.study_plan_id is None:
        return
    await record_response(
        db,
        study_plan_id=attempt.study_plan_id,
        skill=kind,
        item_key=f"tpl:{exercise.target_language}:{kind}:{exercise.exercise_type}:{exercise.level}",
        item_level=exercise.level,
        score=attempt.score / len(questions),
        source=kind,
    )


async def on_game_answer(db: AsyncSession, *, session: Any, correct: bool) -> None:
    skill = _GAME_SKILLS.get(session.game_type)
    if skill is None:
        return
    await record_response(
        db,
        study_plan_id=session.study_plan_id,
        skill=skill,
        item_key=f"tpl:{session.target_language}:game:{session.game_type}:{session.level}",
        item_level=session.level,
        score=1.0 if correct else 0.0,
        source="game",
    )


async def on_flashcard_review(db: AsyncSession, *, card: Any, quality: int) -> None:
    plan = await db.get(StudyPlan, card.study_plan_id)
    if plan is None:
        return
    await record_response(
        db,
        study_plan_id=card.study_plan_id,
        skill="vocabulary",
        item_key=f"flashcard:{plan.target_language}",
        item_level=None,
        score=min(quality / 5.0, 1.0),
        source="flashcard",
    )
