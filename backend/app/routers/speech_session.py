from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.core.app_logger import get_logger
from app.core.config import settings
from app.core.deps import get_current_user
from app.core.limiter import limiter
from app.models.user import User

router = APIRouter(prefix="/api/speech-session", tags=["speech-session"])
logger = get_logger(__name__)

SpeechState = Literal["off", "switching", "ready", "busy", "shared", "away"]
_VALID_STATES = {"off", "switching", "ready", "busy", "shared"}
_GATEWAY_TIMEOUT = httpx.Timeout(3.0)


class SpeechSessionState(BaseModel):
    state: SpeechState


async def _gateway(method: str, path: str) -> SpeechSessionState:
    """Forward a session call to the speech gateway; an unreachable gateway is `away`."""
    if settings.STT_PROVIDER != "local":
        return SpeechSessionState(state="ready")
    url = f"{settings.STT_BASE_URL.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=_GATEWAY_TIMEOUT) as client:
            response = await client.request(method, url)
        response.raise_for_status()
        state = response.json().get("state")
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        logger.warning("speech_session_gateway_unreachable", error=type(exc).__name__)
        return SpeechSessionState(state="away")
    if state not in _VALID_STATES:
        return SpeechSessionState(state="away")
    return SpeechSessionState(state=state)


@router.post("/open", response_model=SpeechSessionState)
@limiter.limit("30/minute")
async def open_session(
    request: Request, current_user: User = Depends(get_current_user)
) -> SpeechSessionState:
    return await _gateway("POST", "/session/open")


@router.post("/keepalive", response_model=SpeechSessionState)
@limiter.limit("30/minute")
async def keepalive_session(
    request: Request, current_user: User = Depends(get_current_user)
) -> SpeechSessionState:
    return await _gateway("POST", "/session/keepalive")


@router.get("/status", response_model=SpeechSessionState)
@limiter.limit("60/minute")
async def session_status(
    request: Request, current_user: User = Depends(get_current_user)
) -> SpeechSessionState:
    return await _gateway("GET", "/session/status")
