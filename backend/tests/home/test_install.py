from unittest.mock import patch

import pytest

from app.main import app


def test_install_home_registers_speech_routes() -> None:
    paths = set(app.openapi()["paths"])
    assert {
        "/api/speech-session/open",
        "/api/speech-session/keepalive",
        "/api/speech-session/status",
    } <= paths


@pytest.mark.asyncio
async def test_lifespan_runs_upstream_then_home_migrations_then_stock_loop() -> None:
    import asyncio
    from contextlib import asynccontextmanager

    from fastapi import FastAPI

    from app.home.install import install_home

    events: list[str] = []

    @asynccontextmanager
    async def upstream(app: FastAPI):
        events.append("upstream")
        yield
        events.append("upstream-exit")

    async def fake_loop() -> None:
        events.append("loop-start")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            events.append("loop-cancelled")
            raise

    test_app = FastAPI(lifespan=upstream)
    with (
        patch("app.home.game_stock.stock_enabled", return_value=True),
        patch("app.home.game_stock.stock_loop", fake_loop),
        patch("app.home.install.run_home_migrations", lambda: events.append("home-migrations")),
    ):
        install_home(test_app)
        async with test_app.router.lifespan_context(test_app):
            await asyncio.sleep(0)
            assert events == ["upstream", "home-migrations", "loop-start"]
    assert events == [
        "upstream",
        "home-migrations",
        "loop-start",
        "loop-cancelled",
        "upstream-exit",
    ]
