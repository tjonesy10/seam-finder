import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from loader.url import normalize_database_url

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "nflverse"


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


@pytest.fixture
def loaded(database_url, clean_tables):
    from loader.run import run_load

    assert run_load(
        database_url=database_url,
        seasons=[2024, 2025],
        data_dir=FIXTURE_DIR,
        trigger="local",
    )


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from web.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_tables(engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE salary_private.salary_selection_rows, "
                "salary_private.salary_selection_batches, salary_private.salary_interpretations, "
                "salary_private.dk_lobby_salaries, "
                "salary_private.salary_source_rows, salary_private.salary_observations, "
                "salary_private.salary_snapshots, salary_private.salary_artifacts, "
                "load_runs, dk_classic_slate, dk_classic_salaries, "
                "player_week_stats, games, players, teams "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield
