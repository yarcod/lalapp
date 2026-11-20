from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.home.models import HomeProfile
from app.models.user import User


@dataclass(frozen=True)
class HomeLearner:
    is_child: bool = False
    native_code: str = ""


DEFAULT_LEARNER = HomeLearner()

_learner: ContextVar[HomeLearner] = ContextVar("home_learner", default=DEFAULT_LEARNER)


def current_learner() -> HomeLearner:
    return _learner.get()


async def load_learner(db: AsyncSession, user: User) -> HomeLearner:
    """Read the learner for a user without touching the context variable."""
    profile = await db.get(HomeProfile, user.id)
    return HomeLearner(
        is_child=bool(profile.is_child) if profile else False,
        native_code=user.native_language or "",
    )


async def enter_user(db: AsyncSession, user: User) -> HomeLearner:
    """Load the learner for the authenticated user and make it current for this request."""
    learner = await load_learner(db, user)
    _learner.set(learner)
    return learner


@contextmanager
def use_learner(learner: HomeLearner) -> Iterator[None]:
    """Run background work as a given learner, restoring the previous one on exit."""
    token = _learner.set(learner)
    try:
        yield
    finally:
        _learner.reset(token)


class LearnerScopeMiddleware:
    """Start every HTTP or websocket request from the default learner and restore it after."""

    def __init__(self, app) -> None:  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        token = _learner.set(DEFAULT_LEARNER)
        try:
            await self.app(scope, receive, send)
        finally:
            _learner.reset(token)
