import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.home import speech_session


def install_home(app: FastAPI) -> None:
    """Attach the home routers and lifecycle work to the upstream app."""
    from app.services import game_stock

    app.include_router(speech_session.router)

    upstream_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        async with upstream_lifespan(app):
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
