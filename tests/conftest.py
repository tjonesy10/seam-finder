import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "nflverse"


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


@pytest.fixture(scope="session")
def database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("DATABASE_URL is not set")
    return url


@pytest.fixture(scope="session")
def engine(database_url):
    cfg = Config("alembic.ini")
    # Rebuild from the migration on disk so a changed revision is what the tests see.
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")
    eng = create_engine(normalize_database_url(database_url), pool_pre_ping=True)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def clean_tables(engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE load_runs, player_week_stats, games, players, teams "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield
