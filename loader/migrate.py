"""Production Alembic target.

Daily refresh and the other loader workflows call this module. Revision 0004
stays unapplied unless SALARY_PRIVATE_MIGRATION is exactly ``true``. A database
already past that revision is left where it is.
"""

import os
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from loader.url import normalize_database_url

PRODUCTION_CEILING = "0003"
_CHAIN = ("0001", "0002", "0003", "0004")


def upgrade_target(current: str | None, flag: str | None) -> str:
    if flag == "true":
        return "head"
    if current is None:
        return PRODUCTION_CEILING
    if current not in _CHAIN:
        return current
    if _CHAIN.index(current) > _CHAIN.index(PRODUCTION_CEILING):
        return current
    return PRODUCTION_CEILING


def current_revision(database_url: str) -> str | None:
    engine = create_engine(normalize_database_url(database_url), pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            present = conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar()
            if present is None:
                return None
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()


def migrate_production(database_url: str, flag: str | None = None) -> str:
    os.environ["DATABASE_URL"] = database_url
    target = upgrade_target(current_revision(database_url), flag)
    command.upgrade(Config("alembic.ini"), target)
    return target


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("database_unreachable", file=sys.stderr)
        return 1
    try:
        migrate_production(database_url, os.environ.get("SALARY_PRIVATE_MIGRATION"))
    except Exception:  # noqa: BLE001 - do not print the database URL or SQL
        print("migrate_failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
