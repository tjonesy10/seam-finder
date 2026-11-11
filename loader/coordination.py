"""Session coordination lock for refresh and private capture.

Distinct from CAPTURE_LOCK. Held on one connection for the whole critical
section. Children in this process reuse that ownership; there is no skip flag.
"""

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import text

COORDINATION_LOCK = 582014
COORDINATION_WAIT_S = 120
PIPELINE_DEADLINE_S = 30 * 60

_owner: ContextVar["Ownership | None"] = ContextVar("f014_coordination", default=None)


class CoordinationError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class RefreshStopped(Exception):
    """A refresh stage stopped before the remaining datasets. Not a lock failure."""

    def __init__(self, reason: str = "refresh_failed"):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Ownership:
    conn: object
    clock: object | None
    deadline_mono: float | None
    started_mono: float


def _mono(clock) -> float:
    if clock is None:
        return time.monotonic()
    return float(clock.mono())


def _lock_timeout(exc: BaseException | None) -> bool:
    if exc is None:
        return False
    if getattr(exc, "sqlstate", None) == "55P03":
        return True
    origin = getattr(exc, "orig", None)
    if origin is not None and origin is not exc and _lock_timeout(origin):
        return True
    message = str(exc).lower()
    return "lock timeout" in message or "locknotavailable" in message


def _lock_sql(name: str) -> str:
    return f"SELECT {name}(CAST(:key AS bigint))"


def _acquire(engine, wait_seconds: float):
    wait = COORDINATION_WAIT_S if wait_seconds is None else float(wait_seconds)
    if wait > COORDINATION_WAIT_S:
        wait = float(COORDINATION_WAIT_S)
    try:
        conn = engine.connect()
    except Exception as exc:
        raise CoordinationError("database_unreachable") from exc
    try:
        if wait <= 0:
            got = conn.execute(
                text(_lock_sql("pg_try_advisory_lock")),
                {"key": COORDINATION_LOCK},
            ).scalar()
            conn.commit()
            if not got:
                raise CoordinationError("pipeline_busy")
            return conn
        ms = max(1, int(wait * 1000))
        conn.execute(text(f"SET lock_timeout = {ms}"))
        conn.commit()
        conn.execute(text(_lock_sql("pg_advisory_lock")), {"key": COORDINATION_LOCK})
        conn.commit()
        return conn
    except CoordinationError:
        conn.close()
        raise
    except Exception as exc:
        conn.close()
        if _lock_timeout(exc):
            raise CoordinationError("pipeline_busy") from exc
        raise CoordinationError("database_unreachable") from exc


def _release(conn) -> None:
    try:
        conn.execute(text(_lock_sql("pg_advisory_unlock")), {"key": COORDINATION_LOCK})
        conn.commit()
    except Exception:  # noqa: BLE001 - a dropped session already released the lock
        conn.invalidate()
    finally:
        conn.close()


def _touch(ownership: Ownership) -> None:
    if ownership.deadline_mono is not None and _mono(ownership.clock) >= ownership.deadline_mono:
        raise CoordinationError("pipeline_timeout")
    try:
        held = ownership.conn.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_locks
                    WHERE locktype = 'advisory'
                      AND pid = pg_backend_pid()
                      AND granted
                      AND classid = 0
                      AND objid = CAST(:key AS bigint)
                )
                """
            ),
            {"key": COORDINATION_LOCK},
        ).scalar()
        ownership.conn.commit()
    except CoordinationError:
        raise
    except Exception as exc:
        raise CoordinationError("pipeline_lock_lost") from exc
    if not held:
        raise CoordinationError("pipeline_lock_lost")


def ensure_pipeline_ownership() -> None:
    """Stop child work when this process no longer holds the coordination lock."""
    current = _owner.get()
    if current is None:
        return
    _touch(current)


@contextmanager
def coordination(
    engine,
    *,
    wait_seconds: float = COORDINATION_WAIT_S,
    clock=None,
    deadline_mono: float | None = None,
    started_mono: float | None = None,
):
    """Acquire the session lock, or reuse the lock this process already holds."""
    current = _owner.get()
    if current is not None:
        _touch(current)
        yield current
        return
    conn = _acquire(engine, wait_seconds)
    ownership = Ownership(
        conn=conn,
        clock=clock,
        deadline_mono=deadline_mono,
        started_mono=_mono(clock) if started_mono is None else started_mono,
    )
    token = _owner.set(ownership)
    try:
        yield ownership
    finally:
        _owner.reset(token)
        _release(conn)
