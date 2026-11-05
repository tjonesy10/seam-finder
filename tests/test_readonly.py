"""AT18: the web role has only the SELECT grants from loader.grants."""

import psycopg
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from loader.grants import apply_readonly_grant, revoke_readonly_grant
from loader.url import normalize_database_url

ROLE = "seam_web_reader"

WRITES = (
    """
    INSERT INTO teams (
        team_abbr, team_name, team_nick, team_conf, team_division,
        team_id, team_color, team_color2, loaded_at
    ) VALUES (
        'ZZ', 'Fictional', 'Fictional', 'AFC', 'AFC East',
        '0', '#000000', '#111111', CURRENT_TIMESTAMP
    )
    """,
    "UPDATE teams SET team_name = team_name",
    "DELETE FROM teams",
    "CREATE TABLE seam_reader_blocked (id integer)",
)


def test_at18_read_only_role(database_url, engine, monkeypatch):
    from fastapi.testclient import TestClient

    from web.main import create_app

    monkeypatch.setenv("READONLY_ROLE", ROLE)
    with engine.begin() as conn:
        revoke_readonly_grant(conn)
        conn.execute(text("DROP TABLE IF EXISTS seam_reader_blocked"))
        conn.execute(text(f"DROP ROLE IF EXISTS {ROLE}"))
        conn.execute(text(f"CREATE ROLE {ROLE} LOGIN"))
        apply_readonly_grant(conn)

    parsed = make_url(normalize_database_url(database_url))
    reader_url = parsed.set(username=ROLE, password=None).render_as_string(hide_password=False)
    app = create_app(reader_url)
    try:
        with TestClient(app) as client:
            health = client.get("/api/health")
            teams = client.get("/api/teams")
        assert health.status_code == 200
        assert health.json()["database"] == "ok"
        assert teams.status_code == 200

        with app.state.engine.connect() as conn:
            for table in ("teams", "players", "games", "player_week_stats", "load_runs"):
                count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                assert isinstance(count, int)
            for statement in WRITES:
                with pytest_raises_privilege(conn, statement):
                    pass
    finally:
        app.state.engine.dispose()
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS seam_reader_blocked"))
            revoke_readonly_grant(conn)
            conn.execute(text(f"DROP ROLE IF EXISTS {ROLE}"))


def pytest_raises_privilege(conn, statement):
    import pytest

    try:
        with pytest.raises(DBAPIError) as caught:
            conn.execute(text(statement))
        assert isinstance(caught.value.orig, psycopg.errors.InsufficientPrivilege)
        assert caught.value.orig.sqlstate == "42501"
    finally:
        conn.rollback()
    return _NullContext()


class _NullContext:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False
