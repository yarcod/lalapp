from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class HomeProfile(Base):
    """Per-user home settings. A missing row means the defaults."""

    __tablename__ = "home_profiles"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    is_child: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class HomeGameStock(Base):
    """Pre-generated game content per plan, mode and game type, refilled in the background."""

    __tablename__ = "home_game_stock"
    __table_args__ = (Index("ix_home_game_stock_bucket", "study_plan_id", "mode", "game_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    study_plan_id: Mapped[int] = mapped_column(
        ForeignKey("study_plans.id", ondelete="CASCADE"), index=False
    )
    mode: Mapped[str] = mapped_column(String(16))
    game_type: Mapped[str] = mapped_column(String(24))
    target_language: Mapped[str] = mapped_column(String(10))
    native_language: Mapped[str] = mapped_column(String(10))
    level: Mapped[str] = mapped_column(String(10))
    is_child: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    content: Mapped[list] = mapped_column(JSON, default=list)
    # Hash of the permitted source ids; review and prepare stock goes stale when it changes.
    source_hash: Mapped[str] = mapped_column(String(64), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    is_stale: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # A stale item is replaced once; replacements do not count toward the daily cap.
    replaced: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    counts_toward_cap: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    taken_at: Mapped[datetime | None] = mapped_column(DateTime)


Index("ix_home_game_stock_study_plan_id", HomeGameStock.study_plan_id)
