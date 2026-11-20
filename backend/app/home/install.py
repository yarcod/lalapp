import asyncio
from contextlib import asynccontextmanager, suppress

from alembic.config import Config
from fastapi import FastAPI

from alembic import command
from app.home import games_router, models, profile, speech_session  # noqa: F401  — home tables
from app.home.context import LearnerScopeMiddleware


def run_home_migrations() -> None:
    command.upgrade(Config("/app/alembic_home.ini"), "head")


def install_home(app: FastAPI) -> None:
    """Attach the home routers and lifecycle work to the upstream app."""
    from app.home import game_stock

    app.add_middleware(LearnerScopeMiddleware)
    app.include_router(speech_session.router)
    app.include_router(profile.router)
    app.include_router(games_router.router)

    upstream_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        async with upstream_lifespan(app):
            await asyncio.to_thread(run_home_migrations)
            stock_task = None
            if game_stock.stock_enabled():
                stock_task = asyncio.create_task(game_stock.stock_loop())
            try:
                yield
            finally:
                if stock_task is not None:
                    stock_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await stock_task

    app.router.lifespan_context = lifespan
