from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from app.core.config import settings
from app.home.models import HomeGameStock, HomeProfile

HOME_ALEMBIC = Path(__file__).resolve().parents[2] / "alembic_home"


@pytest.fixture
def migrated_engine(tmp_path, monkeypatch):
    db_file = tmp_path / "home.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    cfg = Config()
    cfg.set_main_option("script_location", str(HOME_ALEMBIC))
    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite:///{db_file}")
    yield engine
    engine.dispose()


def test_home_history_creates_only_home_tables(migrated_engine) -> None:
    tables = set(inspect(migrated_engine).get_table_names())
    assert {"home_profiles", "home_game_stock", "alembic_version_home"} <= tables
    assert "alembic_version" not in tables
    assert "users" not in tables


def test_home_revision_matches_models(migrated_engine) -> None:
    insp = inspect(migrated_engine)
    for model in (HomeProfile, HomeGameStock):
        table = model.__table__
        migrated = {c["name"] for c in insp.get_columns(table.name)}
        assert migrated == {c.name for c in table.columns}
