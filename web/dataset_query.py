"""Advanced list execution: snapshot, admission, and parameter-bound predicates."""

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    Text,
    case,
    cast,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from loader.tables import games, load_runs, player_week_stats, players, teams
from web.errors import AppError
from web.grammar import (
    FIELDS,
    SEARCH,
    AdvancedQuery,
    MultiFilter,
    RangeFilter,
    TextFilter,
)
from web.resources import RESOURCES

BUDGET_SECONDS = 3.0
TIMEOUT_MESSAGE = "The query took too long. Narrow filters and retry."
BUSY_MESSAGE = "Too many dataset queries. Try again shortly."
_ADMISSION = 2

_slots = threading.BoundedSemaphore(_ADMISSION)
_deadline: ContextVar[float] = ContextVar("dataset_query_deadline")


def _bind(table, fields: dict[str, str], overrides: dict | None = None) -> dict:
    overrides = overrides or {}
    bound = {}
    for name in fields:
        bound[name] = overrides[name] if name in overrides else table.c[name]
    return bound


COLUMNS = {
    "teams": _bind(teams, FIELDS["teams"]),
    "players": _bind(players, FIELDS["players"]),
    "games": _bind(games, FIELDS["games"]),
    "stats": _bind(
        player_week_stats,
        FIELDS["stats"],
        {"player_display_name": players.c.display_name},
    ),
    "load-runs": _bind(load_runs, FIELDS["load-runs"]),
}
_BY_SLUG = {resource.slug: resource for resource in RESOURCES}


def _timestamp_text(column):
    utc = func.timezone("UTC", column)
    whole = func.to_char(utc, 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')
    frac = func.to_char(utc, 'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"')
    return case((func.date_trunc("second", utc) == utc, whole), else_=frac)


def text_expr(column):
    """Deterministic filter text. Sort expressions keep the native column."""
    kind = column.type
    if isinstance(kind, Boolean):
        return case((column.is_(True), "true"), (column.is_(False), "false"))
    if isinstance(kind, DateTime):
        return _timestamp_text(column)
    if isinstance(kind, Date):
        return func.to_char(column, "YYYY-MM-DD")
    if isinstance(kind, UUID):
        return func.lower(cast(column, Text))
    if isinstance(kind, Integer):
        return cast(column, Text)
    return column


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _predicate(column, spec):
    if isinstance(spec, TextFilter):
        if spec.value == "":
            return None
        expr = text_expr(column)
        if spec.op == "equals":
            return func.lower(expr) == func.lower(spec.value)
        return expr.ilike(_like(spec.value), escape="\\")
    if isinstance(spec, RangeFilter):
        if spec.min is None and spec.max is None:
            return None
        expr = cast(column, Numeric)
        clauses = []
        if spec.min is not None:
            clauses.append(expr >= spec.min)
        if spec.max is not None:
            clauses.append(expr <= spec.max)
        return clauses[0] if len(clauses) == 1 else clauses[0] & clauses[1]
    if isinstance(spec, MultiFilter):
        clauses = []
        if spec.values:
            lowered = func.lower(column)
            clauses.append(lowered.in_([func.lower(value) for value in spec.values]))
        if spec.missing:
            clauses.append(column.is_(None))
        if not clauses:
            return None
        return or_(*clauses) if len(clauses) > 1 else clauses[0]
    raise AppError(500, "internal_error", "Something went wrong.")


def prepare_statement(slug: str, stmt, params):
    advanced: AdvancedQuery = params.advanced
    columns = COLUMNS[slug]
    if advanced.search:
        pattern = _like(advanced.search)
        stmt = stmt.where(
            or_(*[columns[name].ilike(pattern, escape="\\") for name in SEARCH[slug]])
        )
    for key, spec in advanced.filters.items():
        predicate = _predicate(columns[key], spec)
        if predicate is not None:
            stmt = stmt.where(predicate)
    return stmt


def order_clauses(slug: str, params):
    columns = COLUMNS[slug]
    advanced: AdvancedQuery = params.advanced
    if advanced.sorts:
        chosen = [(item.id, item.desc) for item in advanced.sorts]
    else:
        chosen = [(params.sort, params.order == "desc")]
    clauses = []
    seen: set[str] = set()
    for key, desc in chosen:
        column = columns[key]
        clauses.append(column.desc().nulls_last() if desc else column.asc().nulls_last())
        seen.add(key)
    for key in _BY_SLUG[slug].tie_break:
        if key not in seen:
            clauses.append(columns[key].asc().nulls_last())
            seen.add(key)
    return clauses


def count_and_page(slug: str, stmt, params):
    filtered = prepare_statement(slug, stmt, params)
    count = select(func.count()).select_from(filtered.subquery())
    page = filtered.order_by(*order_clauses(slug, params)).limit(params.limit).offset(params.offset)
    return count, page


def is_statement_timeout(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        sqlstate = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if sqlstate == "57014":
            return True
        orig = getattr(current, "orig", None)
        if orig is not None and orig is not current:
            current = orig
            continue
        current = current.__cause__ or current.__context__
    return False


def _timeout() -> AppError:
    return AppError(503, "query_timeout", TIMEOUT_MESSAGE)


def arm(conn) -> None:
    """Transaction-local statement_timeout for the remaining SQL budget."""
    remaining = _deadline.get() - time.monotonic()
    if remaining <= 0:
        raise _timeout()
    millis = max(1, int(remaining * 1000))
    conn.execute(
        text("SELECT set_config('statement_timeout', :value, true)"),
        {"value": f"{millis}ms"},
    )


@contextmanager
def admit():
    if not _slots.acquire(blocking=False):
        raise AppError(503, "query_busy", BUSY_MESSAGE)
    try:
        yield
    finally:
        _slots.release()


def run_advanced(engine, work):
    """One short read-only repeatable-read snapshot for count and page."""
    from web.queries import connection

    deadline = time.monotonic() + BUDGET_SECONDS
    token = _deadline.set(deadline)
    try:
        with admit():
            if time.monotonic() >= deadline:
                raise _timeout()
            with connection(engine) as conn:
                try:
                    snapshot = conn.execution_options(isolation_level="REPEATABLE READ")
                    with snapshot.begin():
                        if time.monotonic() >= deadline:
                            raise _timeout()
                        snapshot.execute(text("SET TRANSACTION READ ONLY"))
                        return work(snapshot)
                except AppError:
                    raise
                except Exception as exc:
                    if is_statement_timeout(exc):
                        raise _timeout() from None
                    raise
    finally:
        _deadline.reset(token)
