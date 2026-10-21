from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class LearnerSkill(Base):
    """Ability estimate for one skill in one of the user's languages.

    Owned by ``user_languages`` rather than a study plan, so it survives plan changes.
    """

    __tablename__ = "lalapp_learner_skills"
    __table_args__ = (
        UniqueConstraint("user_language_id", "skill", name="uq_lalapp_learner_skill"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_language_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user_languages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    skill: Mapped[str] = mapped_column(String(20), nullable=False)
    theta: Mapped[float] = mapped_column(Float, nullable=False)
    theta_sd: Mapped[float] = mapped_column(Float, nullable=False)
    n: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


class ItemRating(Base):
    """Difficulty estimate for an item or a pooled item template."""

    __tablename__ = "lalapp_item_ratings"

    item_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    difficulty: Mapped[float] = mapped_column(Float, nullable=False)
    difficulty_sd: Mapped[float] = mapped_column(Float, nullable=False)
    n: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


class LearnerResponse(Base):
    """Append-only evidence log, kept so ratings can be refitted offline."""

    __tablename__ = "lalapp_learner_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_language_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user_languages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    skill: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    expected: Mapped[float] = mapped_column(Float, nullable=False)
    theta_before: Mapped[float] = mapped_column(Float, nullable=False)
    difficulty_before: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)


class PlacementSession(Base):
    """An adaptive placement test in progress or completed."""

    __tablename__ = "lalapp_placement_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_language: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    state: Mapped[dict] = mapped_column(JSON, nullable=False)
    pending_item_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
