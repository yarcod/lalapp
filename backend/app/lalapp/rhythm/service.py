"""A forgiving weekly rhythm, target-language turns, and informational milestones.

The learner picks how many active days a week they aim for. There is no daily streak to lose:
each week is judged on its own, and the summary counts how many recent weeks met the goal. The
main activity measure is turns the learner produced in the target language, with "stretch" turns
that are longer than the learner's usual turn.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.lalapp.models import LearnerResponse, Milestone, RhythmGoal
from app.models.chat_history import ChatHistory
from app.models.user_language import UserLanguage

DEFAULT_DAYS_PER_WEEK = 3
WEEKS_COUNTED = 8
STRETCH_BASELINE_WEEKS = 4
STRETCH_MIN_HISTORY = 10
TURN_MILESTONES = (25, 100, 500, 1000, 5000)
SKILL_MILESTONE_MIN_N = 10


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


async def add_milestone(
    db: AsyncSession, user_language_id: int, key: str, data: dict | None = None
) -> bool:
    """Record a first once; the caller commits. Returns False when it already exists."""
    exists = await db.scalar(
        select(Milestone.id).where(
            Milestone.user_language_id == user_language_id, Milestone.key == key
        )
    )
    if exists is not None:
        return False
    db.add(
        Milestone(user_language_id=user_language_id, key=key, data=data or {}, created_at=_now())
    )
    return True


async def get_goal(db: AsyncSession, user_language_id: int) -> int:
    goal = await db.get(RhythmGoal, user_language_id)
    return goal.days_per_week if goal else DEFAULT_DAYS_PER_WEEK


async def set_goal(db: AsyncSession, user_language_id: int, days_per_week: int) -> None:
    goal = await db.get(RhythmGoal, user_language_id)
    if goal is None:
        goal = RhythmGoal(user_language_id=user_language_id)
        db.add(goal)
    goal.days_per_week = days_per_week
    goal.updated_at = _now()
    await db.commit()


async def _active_days(db: AsyncSession, user_language: UserLanguage, since: datetime) -> set[date]:
    """Days with any scored practice or any learner turn in the target language."""
    practice = await db.scalars(
        select(LearnerResponse.created_at).where(
            LearnerResponse.user_language_id == user_language.id,
            LearnerResponse.created_at >= since,
        )
    )
    turns = await db.scalars(
        select(ChatHistory.created_at).where(
            ChatHistory.user_id == user_language.user_id,
            ChatHistory.target_language == user_language.target_language,
            ChatHistory.role == "user",
            ChatHistory.created_at >= since,
        )
    )
    return {moment.date() for moment in (*practice.all(), *turns.all())}


async def _turns(
    db: AsyncSession, user_language: UserLanguage, since: datetime
) -> list[tuple[datetime, str]]:
    rows = await db.execute(
        select(ChatHistory.created_at, ChatHistory.content).where(
            ChatHistory.user_id == user_language.user_id,
            ChatHistory.target_language == user_language.target_language,
            ChatHistory.role == "user",
            ChatHistory.created_at >= since,
        )
    )
    return [(created_at, content) for created_at, content in rows.all()]


def stretch_count(baseline: list[str], current: list[str]) -> int:
    """Turns longer than the learner's median turn; none until there is enough history."""
    if len(baseline) < STRETCH_MIN_HISTORY:
        return 0
    median = statistics.median(len(text.split()) for text in baseline)
    return sum(1 for text in current if len(text.split()) > median)


def weeks_kept(active_days: set[date], goal: int, this_week: date) -> int:
    """Completed weeks, among the last ``WEEKS_COUNTED``, that met the goal."""
    kept = 0
    for index in range(1, WEEKS_COUNTED + 1):
        start = this_week - timedelta(weeks=index)
        days = {d for d in active_days if start <= d < start + timedelta(days=7)}
        kept += len(days) >= goal
    return kept


@dataclass(frozen=True)
class Rhythm:
    days_per_week: int
    week_start: date
    active_days: list[date]
    weeks_kept: int
    weeks_counted: int
    turns_this_week: int
    stretch_turns_this_week: int
    milestones: list[Milestone]


async def summary(db: AsyncSession, user_language: UserLanguage) -> Rhythm:
    today = _now().date()
    this_week = week_start(today)
    history_start = datetime.combine(
        this_week - timedelta(weeks=WEEKS_COUNTED), datetime.min.time()
    )
    goal = await get_goal(db, user_language.id)
    active = await _active_days(db, user_language, history_start)

    week_begin = datetime.combine(this_week, datetime.min.time())
    baseline_begin = week_begin - timedelta(weeks=STRETCH_BASELINE_WEEKS)
    turns = await _turns(db, user_language, baseline_begin)
    current = [text for moment, text in turns if moment >= week_begin]
    baseline = [text for moment, text in turns if moment < week_begin]

    total_turns = await db.scalar(
        select(func.count(ChatHistory.id)).where(
            ChatHistory.user_id == user_language.user_id,
            ChatHistory.target_language == user_language.target_language,
            ChatHistory.role == "user",
        )
    )
    reached = [n for n in TURN_MILESTONES if total_turns >= n]
    if reached and await add_milestone(
        db, user_language.id, f"turns:{reached[-1]}", {"count": reached[-1]}
    ):
        await db.commit()

    milestones = list(
        (
            await db.scalars(
                select(Milestone)
                .where(Milestone.user_language_id == user_language.id, Milestone.seen_at.is_(None))
                .order_by(Milestone.created_at, Milestone.id)
            )
        ).all()
    )
    return Rhythm(
        days_per_week=goal,
        week_start=this_week,
        active_days=sorted(d for d in active if d >= this_week),
        weeks_kept=weeks_kept(active, goal, this_week),
        weeks_counted=WEEKS_COUNTED,
        turns_this_week=len(current),
        stretch_turns_this_week=stretch_count(baseline, current),
        milestones=milestones,
    )


async def mark_seen(db: AsyncSession, user_language_id: int, milestone_id: int) -> bool:
    milestone = await db.get(Milestone, milestone_id)
    if milestone is None or milestone.user_language_id != user_language_id:
        return False
    milestone.seen_at = milestone.seen_at or _now()
    await db.commit()
    return True
