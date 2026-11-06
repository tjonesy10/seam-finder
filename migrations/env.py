import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from loader.grants import apply_readonly_grant

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def get_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def run_migrations_offline() -> None:
    context.configure(url=get_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    # Grant changes ship with the salary-private migration. A flag-off refresh
    # must not revoke or regrant anything, including on a no-op upgrade.
    if os.environ.get("SALARY_PRIVATE_MIGRATION") == "true":
        with connectable.begin() as connection:
            apply_readonly_grant(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
