"""Read-only grants for the web role. The role name comes from READONLY_ROLE."""

import os
import re

from sqlalchemy import text

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _role() -> str | None:
    role = os.environ.get("READONLY_ROLE", "").strip()
    if not role:
        return None
    if _IDENT.fullmatch(role) is None:
        raise RuntimeError("READONLY_ROLE must be a SQL identifier")
    return role


def _exists(connection, role: str) -> bool:
    row = connection.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :role"),
        {"role": role},
    ).first()
    return row is not None


def apply_readonly_grant(connection) -> None:
    role = _role()
    if role is None:
        return
    if not _exists(connection, role):
        raise RuntimeError("READONLY_ROLE does not exist")
    ident = '"' + role + '"'
    connection.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {ident}"))
    connection.execute(
        text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {ident}")
    )


def revoke_readonly_grant(connection) -> None:
    role = _role()
    if role is None or not _exists(connection, role):
        return
    ident = '"' + role + '"'
    connection.execute(text(f"REVOKE SELECT ON ALL TABLES IN SCHEMA public FROM {ident}"))
    connection.execute(
        text(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM {ident}"
        )
    )
