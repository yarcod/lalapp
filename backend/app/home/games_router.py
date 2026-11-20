"""Home game routes: replay a finished game."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, require_not_maintenance
from app.core.limiter import limiter
from app.home.games import replay_game
from app.models.user import User
from app.services.games import game_output

router = APIRouter(prefix="/api/games", tags=["games"])


@router.post("/sessions/{session_id}/replay")
@limiter.limit("10/minute")
async def replay_session(
    request: Request,
    session_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _maintenance: None = Depends(require_not_maintenance),
) -> dict:
    return game_output(await replay_game(db, user, str(session_id)))
