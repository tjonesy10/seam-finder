"""Read-only grants.

The web role may SELECT the public allowlist only. ``dk_classic_slate`` and the
``salary_private`` schema stay closed, including after a later migrate. A
configured optimizer role receives SELECT on ``salary_private.dk_salary_unified``
only when that view exists. This module does not create that view.
"""

import os
import re

from sqlalchemy import text

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

PUBLIC_ALLOWLIST = (
    "teams",
    "players",
    "games",
    "player_week_stats",
    "load_runs",
    "dk_classic_salaries",
)

OPTIMIZER_VIEW = "dk_salary_unified"


def _role(name: str) -> str | None:
    role = os.environ.get(name, "").strip()
    if not role:
        return None
    if _IDENT.fullmatch(role) is None:
        raise RuntimeError(f"{name} must be a SQL identifier")
    return role


def _quote(role: str) -> str:
    return '"' + role + '"'


def _exists(connection, role: str) -> bool:
    row = connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :role"),
        {"role": role},
    ).first()
    return row is not None


def _regclass(connection, name: str):
    return connection.execute(text("SELECT to_regclass(:name)"), {"name": name}).scalar()


def _schema_exists(connection, name: str) -> bool:
    row = connection.execute(
        text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :name"),
        {"name": name},
    ).first()
    return row is not None


def _revoke_slate(connection, ident: str | None) -> None:
    if _regclass(connection, "public.dk_classic_slate") is None:
        return
    connection.execute(text("REVOKE ALL ON TABLE public.dk_classic_slate FROM PUBLIC"))
    if ident is not None:
        connection.execute(text(f"REVOKE ALL ON TABLE public.dk_classic_slate FROM {ident}"))


def _isolate_private(connection, ident: str | None) -> None:
    if not _schema_exists(connection, "salary_private"):
        return
    connection.execute(text("REVOKE ALL ON SCHEMA salary_private FROM PUBLIC"))
    connection.execute(text("REVOKE ALL ON ALL TABLES IN SCHEMA salary_private FROM PUBLIC"))
    connection.execute(
        text("REVOKE ALL ON ALL SEQUENCES IN SCHEMA salary_private FROM PUBLIC")
    )
    connection.execute(
        text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA salary_private "
            "REVOKE ALL ON TABLES FROM PUBLIC"
        )
    )
    if ident is None:
        return
    connection.execute(text(f"REVOKE ALL ON SCHEMA salary_private FROM {ident}"))
    connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA salary_private FROM {ident}"))
    connection.execute(
        text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA salary_private FROM {ident}")
    )
    connection.execute(
        text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA salary_private "
            f"REVOKE ALL ON TABLES FROM {ident}"
        )
    )


def _grant_optimizer(connection) -> None:
    optimizer = _role("OPTIMIZER_ROLE")
    if optimizer is None:
        return
    web = _role("READONLY_ROLE")
    if optimizer == web:
        raise RuntimeError("optimizer role must not be the web role")
    if not _exists(connection, optimizer):
        raise RuntimeError("OPTIMIZER_ROLE does not exist")
    if not _schema_exists(connection, "salary_private"):
        return
    ident = _quote(optimizer)
    connection.execute(text(f"REVOKE ALL ON SCHEMA salary_private FROM {ident}"))
    connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA salary_private FROM {ident}"))
    connection.execute(
        text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA salary_private FROM {ident}")
    )
    view = _regclass(connection, "salary_private.dk_salary_unified")
    if view is None:
        return
    connection.execute(text(f"GRANT USAGE ON SCHEMA salary_private TO {ident}"))
    connection.execute(
        text(f"GRANT SELECT ON TABLE salary_private.dk_salary_unified TO {ident}")
    )


def apply_readonly_grant(connection) -> None:
    role = _role("READONLY_ROLE")
    if role is not None and not _exists(connection, role):
        raise RuntimeError("READONLY_ROLE does not exist")
    ident = _quote(role) if role is not None else None
    _revoke_slate(connection, ident)
    _isolate_private(connection, ident)
    if ident is not None:
        connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ident}"))
        connection.execute(
            text(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                f"REVOKE SELECT ON TABLES FROM {ident}"
            )
        )
        for table in PUBLIC_ALLOWLIST:
            if _regclass(connection, f"public.{table}") is None:
                continue
            connection.execute(text(f"GRANT SELECT ON TABLE public.{table} TO {ident}"))
        _revoke_slate(connection, ident)
        _isolate_private(connection, ident)
    _grant_optimizer(connection)


def revoke_readonly_grant(connection) -> None:
    role = _role("READONLY_ROLE")
    if role is None or not _exists(connection, role):
        return
    ident = _quote(role)
    connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ident}"))
    connection.execute(
        text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"REVOKE SELECT ON TABLES FROM {ident}"
        )
    )
    _isolate_private(connection, ident)
