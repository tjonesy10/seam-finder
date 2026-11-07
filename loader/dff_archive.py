"""Load a staged Daily Fantasy Fuel archive into salary_private.dff_salaries.

Offline only. This module does not fetch, schedule, or write lobby, DKNFL,
RotoGuru, or F004 rows. Hash, lock, and budget helpers come from the F005
persistence module. Snapshot and ledger writes stay here because those F005
functions are bound to the lobby source and parser.
"""

import argparse
import csv
import io
import json
import os
import re
import sys
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from loader.salary_private import (
    OBJECT_LIMIT,
    ArtifactKind,
    ObservationStatus,
    ParseStatus,
    PoolKind,
    PrivateWriteError,
    RowStatus,
    Source,
    assert_actual_ceiling,
    budget_block,
    canonical_sha256,
    finish_load_run,
    finish_observation,
    lock_capture,
    sha256_bytes,
    unlock_capture,
)
from loader.url import normalize_database_url

PARSER_VERSION = "f006.1"
DATASET = "dff_salaries"
PUBLIC_SOURCE_URL = "dff_salaries"
SOURCE_NAME = "Daily Fantasy Fuel"
ATTRIBUTION = (
    "Salary/projection subset via Daily Fantasy Fuel (dailyfantasyfuel.com). "
    "Not affiliated with DraftKings."
)
MANIFEST_COLUMNS = (
    "path",
    "season",
    "week",
    "rows",
    "usable_salary_rows",
    "source",
    "source_url",
    "format",
    "date",
    "unique_players_in_file",
    "min_salary",
    "max_salary",
    "columns",
    "sha256",
    "quality_note",
)
CORE = (
    "start_date",
    "week",
    "name",
    "pos",
    "team",
    "opp",
    "loc",
    "salary",
    "player_id",
    "ppg_proj",
)
REJECT_REASONS = {
    "blank_row",
    "invalid_salary",
    "missing_name",
    "missing_player_id",
    "invalid_date",
    "row_date_contradiction",
    "row_week_contradiction",
}
REASON_PRIORITY = (
    "storage_guard_object",
    "storage_guard_invocation",
    "storage_guard_cumulative",
    "storage_guard_database",
    "missing_file",
    "undecodable",
    "not_csv",
    "missing_header",
    "duplicate_header",
    "missing_core_header",
    "column_schema",
    "hash_mismatch",
    "count_mismatch",
    "usable_count_mismatch",
    "missing_companion",
    "companion_invalid",
    "row_date_contradiction",
    "row_week_contradiction",
    "manifest_game_contradiction",
    "manifest_entry",
    "zero_valid_rows",
    "injected_fault",
    "ledger_conflict",
    "artifact_conflict",
    "artifact_readback",
    "snapshot_readback",
    "constraint_failure",
    "load_failed",
)
_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
_INT = re.compile(r"-?\d+")


def _ready(conn) -> None:
    if conn.in_transaction():
        conn.rollback()


@contextmanager
def _tx(conn):
    _ready(conn)
    with conn.begin():
        yield


class PathReject(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class ManifestEntry:
    values: dict[str, str]
    path: str
    season: int
    week: int
    row_count: int
    usable_count: int
    slate_date: date
    columns: tuple[str, ...]
    digest: str
    source_url: str | None


@dataclass
class ParsedRow:
    number: int
    raw_fields: tuple[tuple[str, str], ...]
    reasons: list[str] = field(default_factory=list)
    salary: Decimal | None = None
    player_id: str | None = None
    start_date: date | None = None
    week_raw: str | None = None
    name: str | None = None
    position: str | None = None
    pos_alt: str | None = None
    team: str | None = None
    opponent: str | None = None
    location: str | None = None
    ppg_proj: Decimal | None = None

    @property
    def row_status(self) -> RowStatus:
        if any(reason in REJECT_REASONS for reason in self.reasons):
            return RowStatus.REJECTED
        return RowStatus.VALID

    @property
    def parse_status(self) -> ParseStatus:
        if self.row_status is RowStatus.REJECTED:
            return ParseStatus.REJECTED
        return ParseStatus.PARSED


@dataclass
class FileOutcome:
    status: str
    reason: str
    reused: bool = False
    rows_read: int = 0
    rows_valid: int = 0
    rows_rejected: int = 0
    hung: bool = False


def normalize_trigger(value: str) -> str | None:
    if value in {"local", "manual"}:
        return value
    if value == "scheduled":
        return "schedule"
    return None


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    text_value = value.strip()
    return text_value or None


def _priority(reasons: set[str]) -> str:
    for reason in REASON_PRIORITY:
        if reason in reasons:
            return reason
    return "load_failed"


def resolve_inside(root: Path, relative: str) -> Path:
    if relative is None:
        raise PathReject("unsafe_path")
    raw = relative.strip()
    if (
        raw == ""
        or raw.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:", raw)
        or "\x00" in raw
        or "\\" in raw
    ):
        raise PathReject("unsafe_path")
    parts = Path(raw).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise PathReject("unsafe_path")
    root_real = root.resolve()
    current = root_real
    for part in parts:
        current = current / part
        if current.is_symlink():
            target = current.resolve()
            try:
                target.relative_to(root_real)
            except ValueError as exc:
                raise PathReject("unsafe_path") from exc
            current = target
    try:
        current.resolve().relative_to(root_real)
    except ValueError as exc:
        raise PathReject("unsafe_path") from exc
    return current


def parse_number(token: str, scale: int, precision: int) -> Decimal | None:
    text_value = token.strip().replace("$", "").replace(",", "")
    if text_value == "":
        return None
    try:
        number = Decimal(text_value)
    except InvalidOperation:
        return None
    if not number.is_finite() or number < 0:
        return None
    number = number.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    _sign, digits, exponent = number.as_tuple()
    int_digits = 0 if digits == (0,) else max(0, len(digits) + int(exponent))
    if int_digits > precision - scale:
        return None
    return number


def parse_date(token: str) -> date | None:
    try:
        return datetime.strptime(token.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _pairs(value) -> tuple[tuple[str, str], ...]:
    return tuple((str(item[0]), str(item[1])) for item in value)


def _http_url(value: str) -> str | None:
    text_value = (value or "").strip()
    if not text_value.startswith("https://") or any(char.isspace() for char in text_value):
        return None
    host = text_value.split("/", 3)[2]
    if "@" in host:
        return None
    return text_value


def _read_manifest(path: Path) -> tuple[bytes, list[dict[str, str]]]:
    body = path.read_bytes()
    text_value = body.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text_value))
    if reader.fieldnames is None or not set(MANIFEST_COLUMNS) <= set(reader.fieldnames):
        raise ValueError("manifest_schema")
    rows = []
    for row in reader:
        rows.append({column: (row.get(column) or "") for column in MANIFEST_COLUMNS})
    return body, rows


def _entry(row: dict[str, str]) -> ManifestEntry:
    season = row["season"].strip()
    week = row["week"].strip()
    rows = row["rows"].strip()
    usable = row["usable_salary_rows"].strip()
    digest = row["sha256"].strip()
    if not (
        _INT.fullmatch(season)
        and _INT.fullmatch(week)
        and _INT.fullmatch(rows)
        and _INT.fullmatch(usable)
        and _HEX.fullmatch(digest)
    ):
        raise ValueError("manifest_entry")
    slate_date = parse_date(row["date"])
    columns = tuple(part.strip() for part in row["columns"].split("|") if part.strip())
    if slate_date is None or not columns:
        raise ValueError("manifest_entry")
    season_i = int(season)
    week_i = int(week)
    if not (1999 <= season_i <= 2100 and 1 <= week_i <= 22):
        raise ValueError("manifest_entry")
    return ManifestEntry(
        values=dict(row),
        path=row["path"].strip(),
        season=season_i,
        week=week_i,
        row_count=int(rows),
        usable_count=int(usable),
        slate_date=slate_date,
        columns=columns,
        digest=digest.lower(),
        source_url=_http_url(row["source_url"]),
    )


def parse_csv(body: bytes) -> tuple[list[str], list[tuple[tuple[str, str], ...]], str | None]:
    try:
        text_value = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], [], "undecodable"
    if text_value.lstrip().startswith("<"):
        return [], [], "not_csv"
    reader = csv.reader(io.StringIO(text_value))
    try:
        header_row = next(reader)
    except StopIteration:
        return [], [], "missing_header"
    headers = [cell.strip() for cell in header_row]
    if not any(headers):
        return [], [], "missing_header"
    if len(headers) != len(set(headers)):
        return [], [], "duplicate_header"
    records = []
    for cells in reader:
        pairs = []
        for index, header in enumerate(headers):
            raw = cells[index] if index < len(cells) else ""
            pairs.append((header, raw))
        records.append(tuple(pairs))
    return headers, records, None


def _lookup(raw_fields: tuple[tuple[str, str], ...], name: str) -> str:
    for key, value in raw_fields:
        if key == name:
            return value
    return ""


def classify(records, entry: ManifestEntry) -> tuple[list[ParsedRow], set[str]]:
    parsed: list[ParsedRow] = []
    file_reasons: set[str] = set()
    for number, raw_fields in enumerate(records, start=1):
        row = ParsedRow(number=number, raw_fields=raw_fields)
        if all(not cell.strip() for _key, cell in raw_fields):
            row.reasons.append("blank_row")
            parsed.append(row)
            continue
        row.week_raw = _lookup(raw_fields, "week")
        row.name = _blank(_lookup(raw_fields, "name"))
        row.position = _blank(_lookup(raw_fields, "pos"))
        row.pos_alt = _blank(_lookup(raw_fields, "pos_alt"))
        row.team = _blank(_lookup(raw_fields, "team"))
        row.opponent = _blank(_lookup(raw_fields, "opp"))
        row.location = _blank(_lookup(raw_fields, "loc"))
        row.player_id = _blank(_lookup(raw_fields, "player_id"))
        salary_token = _lookup(raw_fields, "salary")
        row.salary = parse_number(salary_token, 2, 10)
        if row.salary is None:
            row.reasons.append("invalid_salary")
        ppg_token = _lookup(raw_fields, "ppg_proj").strip()
        if ppg_token:
            row.ppg_proj = parse_number(ppg_token, 4, 12)
            if row.ppg_proj is None:
                row.reasons.append("invalid_ppg_proj")
        if row.name is None:
            row.reasons.append("missing_name")
        if row.player_id is None:
            row.reasons.append("missing_player_id")
        date_token = _lookup(raw_fields, "start_date")
        row.start_date = parse_date(date_token)
        if row.start_date is None:
            row.reasons.append("invalid_date")
        elif row.start_date != entry.slate_date:
            row.reasons.append("row_date_contradiction")
            file_reasons.add("row_date_contradiction")
        week_token = row.week_raw.strip()
        if not _INT.fullmatch(week_token) or int(week_token) != entry.week:
            row.reasons.append("row_week_contradiction")
            file_reasons.add("row_week_contradiction")
        parsed.append(row)
    counts = Counter(row.player_id for row in parsed if row.player_id)
    salaries: dict[str, set[Decimal]] = {}
    for row in parsed:
        if row.player_id and row.salary is not None:
            salaries.setdefault(row.player_id, set()).add(row.salary)
    for row in parsed:
        if row.player_id and counts[row.player_id] > 1:
            row.reasons.append("duplicate_vendor_id")
            if len(salaries.get(row.player_id, ())) > 1:
                row.reasons.append("duplicate_conflict")
    return parsed, file_reasons


def _orient(team: str | None, opponent: str | None, location: str | None):
    if not team or not opponent or not location:
        return None
    token = location.strip().lower()
    away_team = team.strip().upper()
    home_team = opponent.strip().upper()
    if token in {"@", "a", "away"}:
        return away_team, home_team
    if token in {"vs", "v", "h", "home"}:
        return home_team, away_team
    return None


def _games(conn, parsed: list[ParsedRow], entry: ManifestEntry) -> tuple[list[dict], str, set[str]]:
    observed: dict[tuple[str, str], dict] = {}
    for row in parsed:
        if row.start_date != entry.slate_date:
            continue
        oriented = _orient(row.team, row.opponent, row.location)
        if oriented is None:
            continue
        away, home = oriented
        observed.setdefault((away, home), {"away": away, "home": home})
    reasons: set[str] = set()
    season_types: set[str] = set()
    games = []
    for away, home in sorted(observed):
        matched = conn.execute(
            text(
                """
                SELECT game_id, season, week, season_type
                FROM games
                WHERE away_team = :away AND home_team = :home AND gameday = :gameday
                ORDER BY game_id
                """
            ),
            {"away": away, "home": home, "gameday": entry.slate_date},
        ).mappings().all()
        game_id = None
        if matched:
            seasons = {int(item["season"]) for item in matched}
            weeks = {int(item["week"]) for item in matched}
            types = {str(item["season_type"]) for item in matched}
            if seasons != {entry.season} or weeks != {entry.week} or len(types) != 1:
                reasons.add("manifest_game_contradiction")
            else:
                season_types.add(next(iter(types)))
                if len(matched) == 1:
                    game_id = str(matched[0]["game_id"])
        games.append(
            {"away": away, "home": home, "kickoff_at": None, "game_id": game_id}
        )
    if len(season_types) > 1:
        reasons.add("manifest_game_contradiction")
        season_type = "UNKNOWN"
    elif len(season_types) == 1:
        season_type = next(iter(season_types))
        if season_type not in {"REG", "POST", "UNKNOWN"}:
            reasons.add("manifest_game_contradiction")
            season_type = "UNKNOWN"
    else:
        season_type = "REG" if entry.week <= 18 else "UNKNOWN"
    return games, season_type, reasons


def _insert_run(conn, run_group: UUID, season: int | None, trigger: str, started_at: datetime) -> int:
    with _tx(conn):
        row = conn.execute(
            text(
                """
                INSERT INTO load_runs (
                    run_group, dataset, season, status, trigger, started_at, source_url
                ) VALUES (
                    :run_group, :dataset, :season, 'running', :trigger, :started_at, :source_url
                )
                RETURNING id
                """
            ),
            {
                "run_group": run_group,
                "dataset": DATASET,
                "season": season,
                "trigger": trigger,
                "started_at": started_at,
                "source_url": PUBLIC_SOURCE_URL,
            },
        ).one()
    return int(row.id)


def _insert_observation(conn, observation_id: UUID, run_id: int, started_at: datetime) -> None:
    with _tx(conn):
        conn.execute(
            text(
                """
                INSERT INTO salary_private.salary_observations (
                    observation_id, load_run_id, source, requested_at, started_at,
                    observed_at, source_url, metadata, status, loaded_at
                ) VALUES (
                    :observation_id, :load_run_id, :source, :requested_at, :started_at,
                    :observed_at, :source_url, CAST(:metadata AS jsonb), 'running', :loaded_at
                )
                """
            ),
            {
                "observation_id": observation_id,
                "load_run_id": run_id,
                "source": Source.DFF.value,
                "requested_at": started_at,
                "started_at": started_at,
                "observed_at": started_at,
                "source_url": PUBLIC_SOURCE_URL,
                "metadata": json.dumps({"parser_version": PARSER_VERSION}),
                "loaded_at": started_at,
            },
        )


def _store_artifact(conn, *, body: bytes, source: str, kind: str, media_type: str, stored_at: datetime, invocation_bytes: int):
    digest = sha256_bytes(body)
    with _tx(conn):
        existing = conn.execute(
            text(
                """
                SELECT artifact_id, sha256, body, byte_count
                FROM salary_private.salary_artifacts
                WHERE source = :source AND sha256 = :sha256
                """
            ),
            {"source": source, "sha256": digest},
        ).one_or_none()
        block = budget_block(
            conn,
            object_bytes=len(body),
            invocation_bytes=invocation_bytes + len(body),
        )
        if block is not None:
            raise PrivateWriteError(block.value)
        if existing is not None:
            if bytes(existing.body) != body:
                raise PrivateWriteError("artifact_conflict")
            assert_actual_ceiling(conn)
            return int(existing.artifact_id), digest, True
        row = conn.execute(
            text(
                """
                INSERT INTO salary_private.salary_artifacts (
                    source, sha256, body, byte_count, media_type, artifact_kind,
                    stored_at, loaded_at
                ) VALUES (
                    :source, :sha256, :body, :byte_count, :media_type, :kind,
                    :stored_at, :loaded_at
                )
                RETURNING artifact_id, body, sha256, byte_count
                """
            ),
            {
                "source": source,
                "sha256": digest,
                "body": body,
                "byte_count": len(body),
                "media_type": media_type,
                "kind": kind,
                "stored_at": stored_at,
                "loaded_at": stored_at,
            },
        ).one()
        if bytes(row.body) != body or row.sha256 != digest or int(row.byte_count) != len(body):
            raise PrivateWriteError("artifact_readback")
        assert_actual_ceiling(conn)
    return int(row.artifact_id), digest, False


def _store_ledger(conn, artifact_id: int, parsed: list[ParsedRow], loaded_at: datetime) -> None:
    rows = [
        (
            row.number,
            row.raw_fields,
            row.parse_status.value,
            tuple(row.reasons),
        )
        for row in parsed
    ]
    with _tx(conn):
        existing = conn.execute(
            text(
                """
                SELECT row_number, raw_fields, parse_status, reason_codes
                FROM salary_private.salary_source_rows
                WHERE artifact_id = :artifact_id AND parser_version = :parser
                ORDER BY row_number
                """
            ),
            {"artifact_id": artifact_id, "parser": PARSER_VERSION},
        ).all()
        if existing:
            if len(existing) != len(rows):
                raise PrivateWriteError("ledger_conflict")
            for old, new in zip(existing, rows, strict=True):
                same = (
                    int(old.row_number) == new[0]
                    and _pairs(old.raw_fields) == new[1]
                    and old.parse_status == new[2]
                    and tuple(str(item) for item in old.reason_codes) == new[3]
                )
                if not same:
                    raise PrivateWriteError("ledger_conflict")
            assert_actual_ceiling(conn)
            return
        for number, raw_fields, parse_status, reasons in rows:
            conn.execute(
                text(
                    """
                    INSERT INTO salary_private.salary_source_rows (
                        artifact_id, parser_version, row_number, raw_fields,
                        parse_status, reason_codes, loaded_at
                    ) VALUES (
                        :artifact_id, :parser, :row_number, CAST(:raw_fields AS jsonb),
                        :parse_status, CAST(:reason_codes AS jsonb), :loaded_at
                    )
                    """
                ),
                {
                    "artifact_id": artifact_id,
                    "parser": PARSER_VERSION,
                    "row_number": number,
                    "raw_fields": json.dumps([list(pair) for pair in raw_fields]),
                    "parse_status": parse_status,
                    "reason_codes": json.dumps(list(reasons)),
                    "loaded_at": loaded_at,
                },
            )
        assert_actual_ceiling(conn)


def _close_run(
    conn,
    run_id: int,
    *,
    status: str,
    reason: str,
    outcome: FileOutcome,
    finished_at: datetime,
    season: int | None = None,
    week: int | None = None,
) -> None:
    _ready(conn)
    snapshot = "reused" if outcome.reused else ("published" if status == "succeeded" else "none")
    notes = (
        f"reason={reason};season={'' if season is None else season};"
        f"week={'' if week is None else week};rows_read={outcome.rows_read};"
        f"rows_valid={outcome.rows_valid};rows_rejected={outcome.rows_rejected};"
        f"snapshot={snapshot}"
    )
    finish_load_run(
        conn,
        run_id,
        status=status,
        finished_at=finished_at,
        notes=notes,
        error=None if status == "succeeded" else reason,
        rows_read=outcome.rows_read,
        rows_upserted=0 if outcome.reused or status != "succeeded" else outcome.rows_valid,
        rows_skipped=outcome.rows_rejected,
        source_version=PARSER_VERSION,
    )


def _fail_observation(conn, observation_id: UUID, *, reason: str, artifact_id: int | None, metadata: dict, finished_at: datetime) -> None:
    with _tx(conn):
        finish_observation(
            conn,
            observation_id=observation_id,
            status=ObservationStatus.REJECTED if reason not in {"load_failed", "constraint_failure"} else ObservationStatus.FAILED,
            finished_at=finished_at,
            duration_ms=None,
            artifact_id=artifact_id,
            snapshot_id=None,
            fetched_at=None,
            reason_code=reason,
            error_private=reason,
            metadata=metadata,
        )


def _startup(conn, run_group: UUID, trigger: str, reason: str) -> None:
    now = datetime.now(UTC)
    run_id = _insert_run(conn, run_group, None, trigger, now)
    observation_id = uuid4()
    _insert_observation(conn, observation_id, run_id, now)
    _fail_observation(
        conn,
        observation_id,
        reason=reason,
        artifact_id=None,
        metadata={"parser_version": PARSER_VERSION, "reason": reason},
        finished_at=now,
    )
    _close_run(conn, run_id, status="failed", reason=reason, outcome=FileOutcome("failed", reason), finished_at=now)


def reconcile(conn, *, finished_at: datetime | None = None) -> None:
    """Close a running DFF attempt only when its snapshot commit is durable."""
    moment = finished_at or datetime.now(UTC)
    with _tx(conn):
        runs = conn.execute(
            text(
                """
                SELECT id FROM load_runs
                WHERE dataset = :dataset AND status = 'running'
                """
            ),
            {"dataset": DATASET},
        ).all()
        for run in runs:
            obs = conn.execute(
                text(
                    """
                    SELECT observation_id, status, snapshot_id, reason_code
                    FROM salary_private.salary_observations
                    WHERE load_run_id = :id
                    ORDER BY loaded_at
                    """
                ),
                {"id": run.id},
            ).all()
            if len(obs) == 1 and obs[0].status == ObservationStatus.SUCCEEDED.value and obs[0].snapshot_id is not None:
                found = conn.execute(
                    text("SELECT 1 FROM salary_private.salary_snapshots WHERE snapshot_id = :id"),
                    {"id": obs[0].snapshot_id},
                ).first()
                if found is not None:
                    conn.execute(
                        text(
                            """
                            UPDATE load_runs SET
                                status = 'succeeded',
                                finished_at = :finished_at,
                                notes = 'reason=reconciled;snapshot=reused',
                                error = NULL
                            WHERE id = :id AND status = 'running'
                            """
                        ),
                        {"id": run.id, "finished_at": moment},
                    )
                    continue
            if obs and obs[0].status == ObservationStatus.RUNNING.value:
                conn.execute(
                    text(
                        """
                        UPDATE salary_private.salary_observations
                        SET status = 'failed', reason_code = 'interrupted'
                        WHERE observation_id = :observation_id AND status = 'running'
                        """
                    ),
                    {"observation_id": obs[0].observation_id},
                )
            reason = "interrupted"
            if obs and obs[0].status in {ObservationStatus.FAILED.value, ObservationStatus.REJECTED.value}:
                reason = obs[0].reason_code or obs[0].status
            conn.execute(
                text(
                    """
                    UPDATE load_runs SET
                        status = 'failed',
                        finished_at = :finished_at,
                        notes = :notes,
                        error = :error,
                        rows_read = COALESCE(rows_read, 0),
                        rows_upserted = COALESCE(rows_upserted, 0),
                        rows_deleted = COALESCE(rows_deleted, 0),
                        rows_skipped = COALESCE(rows_skipped, 0)
                    WHERE id = :id AND status = 'running'
                    """
                ),
                {
                    "id": run.id,
                    "finished_at": moment,
                    "notes": f"reason={reason}",
                    "error": reason,
                },
            )


def _emit(selected: int, not_selected: int, outcomes: list[FileOutcome]) -> None:
    print(f"attribution={ATTRIBUTION}")
    print(
        "selected={selected} succeeded={ok} failed={bad} reused={reused} "
        "not_selected={not_selected} rows_read={read} rows_valid={valid} "
        "rows_rejected={rejected}".format(
            selected=selected,
            ok=sum(item.status == "succeeded" for item in outcomes),
            bad=sum(item.status == "failed" for item in outcomes),
            reused=sum(item.reused for item in outcomes),
            not_selected=not_selected,
            read=sum(item.rows_read for item in outcomes),
            valid=sum(item.rows_valid for item in outcomes),
            rejected=sum(item.rows_rejected for item in outcomes),
        )
    )
    counts = Counter(item.reason for item in outcomes if item.status == "failed" and item.reason)
    if counts:
        print(
            "failed_reasons=" + ",".join(f"{key}:{counts[key]}" for key in sorted(counts)),
            file=sys.stderr,
        )


def _bounded(path: Path) -> tuple[bytes, bool]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > OBJECT_LIMIT:
            return handle.read(OBJECT_LIMIT + 1)[:OBJECT_LIMIT], True
        return handle.read(), False


def _control(conn, root: Path, manifest_path: Path, manifest_body: bytes, now: datetime, invocation: int) -> tuple[list[int], int]:
    ids = []
    artifact_id, _digest, _reused = _store_artifact(
        conn,
        body=manifest_body,
        source=Source.CONTROL.value,
        kind=ArtifactKind.MANIFEST.value,
        media_type="text/csv",
        stored_at=now,
        invocation_bytes=invocation,
    )
    ids.append(artifact_id)
    invocation += len(manifest_body)
    for name, kind, media in (
        ("COVERAGE.csv", ArtifactKind.CSV.value, "text/csv"),
        ("FINDINGS.md", ArtifactKind.MANIFEST.value, "text/markdown"),
    ):
        candidate = root / name
        if not candidate.is_file() or candidate.is_symlink():
            continue
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        body, truncated = _bounded(resolved)
        if truncated:
            raise PrivateWriteError("storage_guard_object")
        artifact_id, _digest, _reused = _store_artifact(
            conn,
            body=body,
            source=Source.CONTROL.value,
            kind=kind,
            media_type=media,
            stored_at=now,
            invocation_bytes=invocation,
        )
        ids.append(artifact_id)
        invocation += len(body)
    return ids, invocation


def _process_file(conn, entry: ManifestEntry, root: Path, *, trigger: str, run_group: UUID, control_ids: list[int], invocation: int, fault: str | None, fault_path: str | None) -> tuple[FileOutcome, int]:
    now = datetime.now(UTC)
    run_id = _insert_run(conn, run_group, entry.season, trigger, now)
    observation_id = uuid4()
    _insert_observation(conn, observation_id, run_id, now)
    reasons: set[str] = set()
    artifact_id = None
    metadata: dict = {
        "parser_version": PARSER_VERSION,
        "manifest_row": entry.values,
        "control_artifact_ids": control_ids,
        "artifact_role": "html_row_extraction",
    }
    outcome = FileOutcome("failed", "load_failed")
    try:
        csv_path = resolve_inside(root, entry.path)
        if not csv_path.is_file() or csv_path.is_symlink():
            reasons.add("missing_file")
        else:
            body, truncated = _bounded(csv_path)
            if truncated or csv_path.stat().st_size > OBJECT_LIMIT:
                reasons.add("storage_guard_object")
                metadata.update({"truncated": True, "retained_artifact": False, "prefix_sha256": sha256_bytes(body)})
            else:
                artifact_id, digest, _reused = _store_artifact(
                    conn,
                    body=body,
                    source=Source.DFF.value,
                    kind=ArtifactKind.CSV.value,
                    media_type="text/csv",
                    stored_at=now,
                    invocation_bytes=invocation,
                )
                invocation += len(body)
                if digest != entry.digest:
                    reasons.add("hash_mismatch")
                headers, records, parse_error = parse_csv(body)
                if parse_error:
                    reasons.add(parse_error)
                else:
                    if any(name not in headers for name in CORE):
                        reasons.add("missing_core_header")
                    if set(headers) != set(entry.columns):
                        reasons.add("column_schema")
                    parsed, row_reasons = classify(records, entry)
                    reasons.update(row_reasons)
                    if len(parsed) != entry.row_count:
                        reasons.add("count_mismatch")
                    usable = sum(1 for row in parsed if row.salary is not None)
                    if usable != entry.usable_count:
                        reasons.add("usable_count_mismatch")
                    _store_ledger(conn, artifact_id, parsed, now)
                    valid = sum(row.row_status is RowStatus.VALID for row in parsed)
                    rejected = len(parsed) - valid
                    outcome.rows_read = len(parsed)
                    outcome.rows_valid = valid
                    outcome.rows_rejected = rejected
                    if valid == 0:
                        reasons.add("zero_valid_rows")
                    games, season_type, game_reasons = _games(conn, parsed, entry)
                    reasons.update(game_reasons)
                    companion_rel = f"evidence/dff-{entry.season}-week{entry.week:02d}.html.gz"
                    companion_path = resolve_inside(root, companion_rel)
                    companion_id = None
                    companion_sha = None
                    if not companion_path.is_file() or companion_path.is_symlink():
                        reasons.add("missing_companion")
                    else:
                        companion, companion_truncated = _bounded(companion_path)
                        if companion_truncated or not companion.startswith(b"\x1f\x8b"):
                            reasons.add("companion_invalid" if not companion_truncated else "storage_guard_object")
                        else:
                            companion_id, companion_sha, _reused = _store_artifact(
                                conn,
                                body=companion,
                                source=Source.DFF.value,
                                kind=ArtifactKind.HTML_GZIP.value,
                                media_type="application/gzip",
                                stored_at=now,
                                invocation_bytes=invocation,
                            )
                            invocation += len(companion)
                    if reasons:
                        raise _Stop(reasons)
                    identity = {
                        "season": entry.season,
                        "season_type": season_type,
                        "week": entry.week,
                        "draft_group_id": None,
                        "source_pool_kind": PoolKind.SUBSET.value,
                        "manifest_row": entry.values,
                        "companion_sha256": companion_sha,
                        "headers": headers,
                        "games": games,
                        "rules": {
                            "rules_id": None,
                            "roster_slots": None,
                            "salary_cap": None,
                            "evidence_artifact_id": None,
                        },
                        "parser_version": PARSER_VERSION,
                    }
                    metadata_sha = canonical_sha256(identity)
                    snapshot_meta = {
                        "raw_retained": True,
                        "artifact_role": "html_row_extraction",
                        "optimizer_ready": False,
                        "pool_ready": False,
                        "attribution": ATTRIBUTION,
                        "parser_version": PARSER_VERSION,
                        "headers": headers,
                        "row_count": len(parsed),
                        "valid_count": valid,
                        "rejected_count": rejected,
                        "duplicate_count": sum("duplicate_vendor_id" in row.reasons for row in parsed),
                        "companion_sha256": companion_sha,
                        "companion_artifact_id": companion_id,
                        "start_date": entry.slate_date.isoformat(),
                        "identity": identity,
                    }
                    with _tx(conn):
                        existing = conn.execute(
                            text(
                                """
                                SELECT snapshot_id FROM salary_private.salary_snapshots
                                WHERE source = :source
                                  AND source_snapshot_key = :key
                                  AND artifact_id = :artifact_id
                                  AND parser_version = :parser
                                  AND metadata_sha256 = :metadata_sha256
                                """
                            ),
                            {
                                "source": Source.DFF.value,
                                "key": entry.path,
                                "artifact_id": artifact_id,
                                "parser": PARSER_VERSION,
                                "metadata_sha256": metadata_sha,
                            },
                        ).one_or_none()
                        reused = existing is not None
                        snapshot_id = existing.snapshot_id if reused else uuid4()
                        if not reused:
                            conn.execute(
                                text(
                                    """
                                    INSERT INTO salary_private.salary_snapshots (
                                        snapshot_id, source, artifact_id, parser_version,
                                        metadata_sha256, source_snapshot_key, season,
                                        season_type, week, draft_group_id, games, rules,
                                        game_set_sha256, rules_sha256, source_pool_kind,
                                        metadata, created_at, loaded_at
                                    ) VALUES (
                                        :snapshot_id, :source, :artifact_id, :parser,
                                        :metadata_sha256, :key, :season, :season_type,
                                        :week, NULL, CAST(:games AS jsonb), CAST(:rules AS jsonb),
                                        NULL, NULL, :pool, CAST(:metadata AS jsonb),
                                        :created_at, :loaded_at
                                    )
                                    """
                                ),
                                {
                                    "snapshot_id": snapshot_id,
                                    "source": Source.DFF.value,
                                    "artifact_id": artifact_id,
                                    "parser": PARSER_VERSION,
                                    "metadata_sha256": metadata_sha,
                                    "key": entry.path,
                                    "season": entry.season,
                                    "season_type": season_type,
                                    "week": entry.week,
                                    "games": json.dumps(games),
                                    "rules": json.dumps(identity["rules"]),
                                    "pool": PoolKind.SUBSET.value,
                                    "metadata": json.dumps(snapshot_meta),
                                    "created_at": now,
                                    "loaded_at": now,
                                },
                            )
                            for row in parsed:
                                conn.execute(
                                    text(
                                        """
                                        INSERT INTO salary_private.dff_salaries (
                                            snapshot_id, row_number, artifact_id, parser_version,
                                            row_status, reason_codes, salary, dff_player_id,
                                            start_date, week_raw, name_raw, position_raw,
                                            pos_alt_raw, team_raw, opponent_raw, location_raw,
                                            ppg_proj, loaded_at
                                        ) VALUES (
                                            :snapshot_id, :row_number, :artifact_id, :parser,
                                            :row_status, CAST(:reasons AS jsonb), :salary,
                                            :player_id, :start_date, :week_raw, :name,
                                            :position, :pos_alt, :team, :opponent, :location,
                                            :ppg, :loaded_at
                                        )
                                        """
                                    ),
                                    {
                                        "snapshot_id": snapshot_id,
                                        "row_number": row.number,
                                        "artifact_id": artifact_id,
                                        "parser": PARSER_VERSION,
                                        "row_status": row.row_status.value,
                                        "reasons": json.dumps(row.reasons),
                                        "salary": row.salary,
                                        "player_id": row.player_id,
                                        "start_date": row.start_date,
                                        "week_raw": row.week_raw,
                                        "name": row.name,
                                        "position": row.position,
                                        "pos_alt": row.pos_alt,
                                        "team": row.team,
                                        "opponent": row.opponent,
                                        "location": row.location,
                                        "ppg": row.ppg_proj,
                                        "loaded_at": now,
                                    },
                                )
                            stored = conn.execute(
                                text(
                                    """
                                    SELECT count(*) FROM salary_private.dff_salaries
                                    WHERE snapshot_id = :id
                                    """
                                ),
                                {"id": snapshot_id},
                            ).scalar_one()
                            if int(stored) != len(parsed):
                                raise PrivateWriteError("snapshot_readback")
                        finish_metadata = dict(metadata)
                        finish_metadata.update(snapshot_meta)
                        finish_observation(
                            conn,
                            observation_id=observation_id,
                            status=ObservationStatus.SUCCEEDED,
                            finished_at=now,
                            duration_ms=None,
                            artifact_id=artifact_id,
                            snapshot_id=snapshot_id,
                            fetched_at=None,
                            reason_code="reused" if reused else "published",
                            error_private=None,
                            metadata=finish_metadata,
                        )
                        conn.execute(
                            text(
                                """
                                UPDATE salary_private.salary_observations
                                SET source_url = :source_url, original_path = :original_path,
                                    source_published_at = NULL
                                WHERE observation_id = :observation_id
                                """
                            ),
                            {
                                "source_url": entry.source_url,
                                "original_path": entry.path,
                                "observation_id": observation_id,
                            },
                        )
                        assert_actual_ceiling(conn)
                        if fault == "normalized" and fault_path == entry.path:
                            raise PrivateWriteError("injected_fault")
                    outcome.status = "succeeded"
                    outcome.reason = "reused" if reused else "published"
                    outcome.reused = reused
                    if fault == "after_commit" and fault_path == entry.path:
                        outcome.hung = True
                        return outcome, invocation
                    _close_run(
                        conn,
                        run_id,
                        status="succeeded",
                        reason=outcome.reason,
                        outcome=outcome,
                        finished_at=now,
                        season=entry.season,
                        week=entry.week,
                    )
                    return outcome, invocation
    except _Stop as stopped:
        reasons.update(stopped.reasons)
    except PrivateWriteError as exc:
        reasons.add(exc.reason)
    except IntegrityError:
        reasons.add("constraint_failure")
    except (SQLAlchemyError, OSError, UnicodeError, csv.Error, ValueError):
        reasons.add("load_failed")
    reason = _priority(reasons)
    metadata["reason"] = reason
    _fail_observation(
        conn,
        observation_id,
        reason=reason,
        artifact_id=artifact_id,
        metadata=metadata,
        finished_at=datetime.now(UTC),
    )
    with _tx(conn):
        conn.execute(
            text(
                """
                UPDATE salary_private.salary_observations
                SET original_path = :original_path, source_url = :source_url
                WHERE observation_id = :observation_id
                """
            ),
            {
                "original_path": entry.path,
                "source_url": entry.source_url,
                "observation_id": observation_id,
            },
        )
    outcome.status = "failed"
    outcome.reason = reason
    _close_run(
        conn,
        run_id,
        status="failed",
        reason=reason,
        outcome=outcome,
        finished_at=datetime.now(UTC),
        season=entry.season,
        week=entry.week,
    )
    return outcome, invocation


class _Stop(Exception):
    def __init__(self, reasons: set[str]):
        super().__init__("stop")
        self.reasons = reasons


def run(database_url: str, archive_root, manifest, trigger: str = "local", *, fault: str | None = None, fault_path: str | None = None) -> int:
    root = Path(archive_root)
    manifest_path = Path(manifest)
    try:
        engine = create_engine(normalize_database_url(database_url), pool_pre_ping=True)
        with engine.connect() as probe:
            probe.execute(text("SELECT 1"))
            probe.commit()
    except (SQLAlchemyError, OSError):
        print("database_unreachable", file=sys.stderr)
        return 1
    run_group = uuid4()
    outcomes: list[FileOutcome] = []
    selected_count = 0
    not_selected = 0
    try:
        with engine.connect() as conn:
            lock_capture(conn)
            try:
                reconcile(conn)
                if not manifest_path.is_file():
                    _startup(conn, run_group, trigger, "manifest_missing")
                    _emit(0, 0, [])
                    return 1
                try:
                    manifest_body, rows = _read_manifest(manifest_path)
                except (OSError, UnicodeError, csv.Error, ValueError):
                    _startup(conn, run_group, trigger, "manifest_schema")
                    _emit(0, 0, [])
                    return 1
                selected_rows = [row for row in rows if row["source"] == SOURCE_NAME]
                not_selected = len(rows) - len(selected_rows)
                if not selected_rows:
                    _startup(conn, run_group, trigger, "no_selected_files")
                    _emit(0, not_selected, [])
                    return 1
                if not root.is_dir():
                    _startup(conn, run_group, trigger, "archive_missing")
                    _emit(len(selected_rows), not_selected, [])
                    return 1
                paths = [row["path"].strip() for row in selected_rows]
                if len(paths) != len(set(paths)):
                    _startup(conn, run_group, trigger, "manifest_conflict")
                    _emit(len(selected_rows), not_selected, [])
                    return 1
                entries = []
                for row in selected_rows:
                    try:
                        entries.append(_entry(row))
                    except ValueError:
                        _startup(conn, run_group, trigger, "manifest_entry")
                        _emit(len(selected_rows), not_selected, [])
                        return 1
                try:
                    for entry in entries:
                        resolve_inside(root, entry.path)
                        resolve_inside(root, f"evidence/dff-{entry.season}-week{entry.week:02d}.html.gz")
                except PathReject:
                    _startup(conn, run_group, trigger, "unsafe_path")
                    _emit(len(entries), not_selected, [])
                    return 1
                selected_count = len(entries)
                now = datetime.now(UTC)
                try:
                    control_ids, invocation = _control(conn, root, manifest_path, manifest_body, now, 0)
                except PrivateWriteError as exc:
                    _startup(conn, run_group, trigger, exc.reason)
                    _emit(selected_count, not_selected, [])
                    return 1
                entries.sort(key=lambda item: item.path)
                hung = False
                failed = False
                for entry in entries:
                    outcome, invocation = _process_file(
                        conn,
                        entry,
                        root,
                        trigger=trigger,
                        run_group=run_group,
                        control_ids=control_ids,
                        invocation=invocation,
                        fault=fault,
                        fault_path=fault_path,
                    )
                    outcomes.append(outcome)
                    hung = hung or outcome.hung
                    failed = failed or outcome.status != "succeeded"
                _emit(selected_count, not_selected, outcomes)
                if hung or failed:
                    return 1
                return 0
            finally:
                _ready(conn)
                unlock_capture(conn)
    except Exception:  # noqa: BLE001 - public output is a reason code, never SQL or paths
        print("load_failed", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loader.dff_archive")
    parser.add_argument("--archive-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--trigger", default="local")
    args = parser.parse_args(argv)
    trigger = normalize_trigger(args.trigger)
    if trigger is None:
        print("trigger_rejected", file=sys.stderr)
        return 1
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("database_unreachable", file=sys.stderr)
        return 1
    return run(database_url, args.archive_root, args.manifest, trigger)


if __name__ == "__main__":
    sys.exit(main())
