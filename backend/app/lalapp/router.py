from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.limiter import limiter
from app.lalapp.learner.rating import cefr_from_theta
from app.lalapp.models import LearnerSkill, PlacementSession
from app.lalapp.placement import engine
from app.lalapp.placement import service as placement
from app.models.user import User
from app.models.user_language import UserLanguage
from app.schemas.auth import SUPPORTED_TARGET_LANGUAGES

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


class PlacementStartRequest(BaseModel):
    language: str = Field(max_length=10)
    self_level: str | None = Field(default=None, max_length=2)


class PlacementAnswerRequest(BaseModel):
    question_id: str = Field(max_length=50)
    answer: str = Field(max_length=500)


class PlacementQuestion(BaseModel):
    id: str
    skill: str
    difficulty: str
    question: str
    options: list[str]


class PlacementStep(BaseModel):
    session_id: str
    question_number: int
    max_questions: int
    question: PlacementQuestion | None
    result: dict | None


def _step(session: PlacementSession) -> PlacementStep:
    question = None
    if session.pending_item_id:
        item = placement._bank(session.target_language)[session.pending_item_id]
        # The correct option never leaves the server.
        question = PlacementQuestion(
            id=item.id,
            skill=item.skill,
            difficulty=item.difficulty,
            question=item.question,
            options=list(item.options),
        )
    return PlacementStep(
        session_id=session.id,
        question_number=len(session.state["asked"]) + (1 if question else 0),
        max_questions=engine.MAX_QUESTIONS,
        question=question,
        result=session.result,
    )


@router.post("/placement/start", response_model=PlacementStep)
@limiter.limit("10/minute")
async def start_placement(
    request: Request,
    data: PlacementStartRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlacementStep:
    if data.language not in SUPPORTED_TARGET_LANGUAGES:
        raise HTTPException(status_code=422, detail="unsupported_language")
    session = await placement.start(db, current_user.id, data.language, data.self_level)
    return _step(session)


@router.post("/placement/{session_id}/answer", response_model=PlacementStep)
@limiter.limit("60/minute")
async def answer_placement(
    request: Request,
    session_id: str,
    data: PlacementAnswerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlacementStep:
    session = await placement.answer(db, current_user.id, session_id, data.question_id, data.answer)
    return _step(session)
