import pytest
from fastapi import Depends

from app.core.deps import get_current_user
from app.home.context import (
    DEFAULT_LEARNER,
    HomeLearner,
    current_learner,
    use_learner,
)
from app.home.models import HomeProfile
from app.main import app
from app.models.user import User


def test_default_learner_outside_request() -> None:
    assert current_learner() == DEFAULT_LEARNER


@pytest.mark.asyncio
async def test_get_current_user_sets_learner(client, test_user, db_session) -> None:
    user, headers = test_user
    db_session.add(HomeProfile(user_id=user.id, is_child=True))
    await db_session.commit()

    async def probe(current_user: User = Depends(get_current_user)) -> dict:
        learner = current_learner()
        return {"is_child": learner.is_child, "native_code": learner.native_code}

    async def anonymous() -> dict:
        return {"is_child": current_learner().is_child}

    app.add_api_route("/api/_probe_user", probe)
    app.add_api_route("/api/_probe_anon", anonymous)
    try:
        authed = await client.get("/api/_probe_user", headers=headers)
        assert authed.json() == {"is_child": True, "native_code": "es"}
        assert (await client.get("/api/_probe_anon")).json() == {"is_child": False}
    finally:
        app.router.routes[:] = [
            r for r in app.router.routes if not getattr(r, "path", "").startswith("/api/_probe_")
        ]


def test_use_learner_resets() -> None:
    with use_learner(HomeLearner(True, "sv")):
        assert current_learner() == HomeLearner(True, "sv")
    assert current_learner() == DEFAULT_LEARNER
