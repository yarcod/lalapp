from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.limiter import limiter
from app.lalapp.learner.rating import cefr_from_theta
from app.lalapp.models import LearnerSkill
from app.models.user import User
from app.models.user_language import UserLanguage

router = APIRouter(prefix="/api/lalapp", tags=["lalapp"])


class LearnerSkillOut(BaseModel):
    skill: str
    theta: float
    theta_sd: float
    cefr: str
    n: int


class LearnerLanguageOut(BaseModel):
    target_language: str
    skills: list[LearnerSkillOut]


@router.get("/learner", response_model=list[LearnerLanguageOut])
@limiter.limit("30/minute")
async def get_learner_model(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LearnerLanguageOut]:
    """The current user's per-language skill estimates (shadow mode, read-only)."""
    rows = (
        await db.execute(
            select(UserLanguage.target_language, LearnerSkill)
            .join(LearnerSkill, LearnerSkill.user_language_id == UserLanguage.id)
            .where(UserLanguage.user_id == current_user.id)
            .order_by(UserLanguage.target_language, LearnerSkill.skill)
        )
    ).all()
    languages: dict[str, list[LearnerSkillOut]] = {}
    for target_language, skill in rows:
        languages.setdefault(target_language, []).append(
            LearnerSkillOut(
                skill=skill.skill,
                theta=round(skill.theta, 3),
                theta_sd=round(skill.theta_sd, 3),
                cefr=cefr_from_theta(skill.theta),
                n=skill.n,
            )
        )
    return [LearnerLanguageOut(target_language=k, skills=v) for k, v in languages.items()]
