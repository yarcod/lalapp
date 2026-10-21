"""Offline checks of the lalapp Alembic branch: shape of the chain and DDL matching the models.

Upstream's migration tests only look at upstream's chain, so this is the only coverage of ours.
"""

from io import StringIO
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from alembic import command
from app.core.config import settings
from app.core.database import Base
from app.lalapp import models  # noqa: F401  (registers the lalapp tables)

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def setup_db():
    """Override conftest's create_all fixture: these tests use Alembic offline."""


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    monkeypatch.setattr(
        settings, "DATABASE_URL", "postgresql+asyncpg://offline:offline@invalid.invalid/offline"
    )

    def reject_connection(*args, **kwargs):
        raise AssertionError("Offline migration checks must not create a database engine")

    monkeypatch.setattr("sqlalchemy.ext.asyncio.create_async_engine", reject_connection)


def _config(output):
    config = Config(str(BACKEND / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def _lalapp_tables():
    return sorted(name for name in Base.metadata.tables if name.startswith("lalapp_"))


def _body(sql, table):
    body = sql.split(f"CREATE TABLE {table} (", 1)[1].split("\n)", 1)[0]
    return sorted(line.strip().rstrip(",") for line in body.splitlines() if line.strip())


def test_lalapp_branch_is_one_linear_chain_on_top_of_upstream():
    scripts = ScriptDirectory.from_config(_config(StringIO()))
    lalapp_heads = [h for h in scripts.get_heads() if h.startswith("l0")]
    upstream_heads = [h for h in scripts.get_heads() if not h.startswith("l0")]
    assert len(lalapp_heads) == 1 and len(upstream_heads) == 1
    chain = list(scripts.iterate_revisions(lalapp_heads[0], "base"))
    lalapp = [r for r in chain if r.revision.startswith("l0")]
    base = lalapp[-1]
    assert base.branch_labels == {"lalapp"}
    assert base.down_revision is None
    depends = base.dependencies if isinstance(base.dependencies, tuple) else (base.dependencies,)
    assert all(not d.startswith("l0") for d in depends)
    for revision in lalapp:
        assert len(revision.revision) <= 32  # Fits Alembic's version_num column.


def test_upgrade_creates_lalapp_tables_matching_the_models():
    output = StringIO()
    command.upgrade(_config(output), "heads", sql=True)
    sql = output.getvalue()
    dialect = postgresql.dialect()
    tables = _lalapp_tables()
    assert tables, "no lalapp models registered"
    for name in tables:
        table = Base.metadata.tables[name]
        expected = str(CreateTable(table).compile(dialect=dialect))
        assert _body(sql, name) == _body(expected, name), name
        for index in table.indexes:
            assert str(CreateIndex(index).compile(dialect=dialect)).strip() in sql, index.name


def test_downgrade_removes_every_lalapp_table():
    scripts = ScriptDirectory.from_config(_config(StringIO()))
    head = next(h for h in scripts.get_heads() if h.startswith("l0"))
    output = StringIO()
    command.downgrade(_config(output), f"{head}:lalapp@base", sql=True)
    sql = output.getvalue()
    for name in _lalapp_tables():
        assert f"DROP TABLE {name}" in sql, name
