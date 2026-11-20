from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.limiter import limiter
from app.home.models import HomeProfile
from app.home.spoken_lines import tagged_replies_enabled
from app.models.study_plan import StudyPlan
from app.models.user import User

router = APIRouter(prefix="/api/home/profile", tags=["home-profile"])


class ProfileUpdate(BaseModel):
    is_child: bool


class ProfileResponse(BaseModel):
    is_child: bool
    tagged_languages: list[str]


async def _build(db: AsyncSession, user: User, is_child: bool) -> ProfileResponse:
    plans = (
        await db.execute(
            select(StudyPlan.target_language, StudyPlan.cefr_level)
            .where(StudyPlan.user_id == user.id, StudyPlan.is_active.is_(True))
            .order_by(StudyPlan.target_language)
        )
    ).all()
    tagged = [
        target
        for target, level in plans
        if tagged_replies_enabled(user.native_language or "", level, target)
    ]
    return ProfileResponse(is_child=is_child, tagged_languages=tagged)


@router.get("", response_model=ProfileResponse)
@limiter.limit("30/minute")
async def get_profile(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    profile = await db.get(HomeProfile, current_user.id)
    return await _build(db, current_user, bool(profile.is_child) if profile else False)


@router.put("", response_model=ProfileResponse)
@limiter.limit("30/minute")
async def put_profile(
    request: Request,
    body: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    profile = await db.get(HomeProfile, current_user.id)
    if profile is None:
        db.add(HomeProfile(user_id=current_user.id, is_child=body.is_child))
    else:
        profile.is_child = body.is_child
    await db.commit()
    return await _build(db, current_user, body.is_child)
