import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

import app.home.models  # noqa: F401  — registers the home tables in Base.metadata
import app.models  # noqa: F401  — registers upstream models so foreign keys resolve
from alembic import context
from app.core.config import settings
from app.core.database import Base

target_metadata = Base.metadata
VERSION_TABLE = "alembic_version_home"


def include_object(object, name, type_, reflected, compare_to):  # noqa: ANN001, A002
    """Manage only home_* tables (and their indexes); never touch upstream tables."""
    if type_ == "table":
        return name.startswith("home_")
    table = getattr(object, "table", None)
    return table is None or table.name.startswith("home_")


def run_migrations_offline():
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    connectable = create_async_engine(settings.DATABASE_URL)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
