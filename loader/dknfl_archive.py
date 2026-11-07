"""Load a staged pureslurp/DKNFL archive into salary_private.dknfl_salaries.

Offline only. DK ids stay snapshot-scoped. A parsed snapshot is not an F005
usable snapshot and is not optimizer-ready. Schedule authority is the loaded
games table for the rows that are present; this module does not invent one.
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
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

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

PARSER_VERSION = "f007.1"
DATASET = "dknfl_salaries"
PUBLIC_SOURCE_URL = "dknfl_salaries"
SOURCE_NAME = "pureslurp/DKNFL"
ATTRIBUTION = (
    "Archived DraftKings salary export via pureslurp/DKNFL (GitHub). "
    "Not affiliated with DraftKings."
)
ET = ZoneInfo("America/New_York")
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
REQUIRED = (
    "Position",
    "Name + ID",
    "Name",
    "ID",
    "Roster Position",
    "Salary",
    "Game Info",
    "TeamAbbrev",
)
CLASSIC_TOKENS = {"QB", "RB", "WR", "TE", "FLEX", "DST"}
REJECT_REASONS = {
    "blank_row",
    "invalid_salary",
    "missing_name",
    "missing_dk_id",
    "missing_roster",
    "missing_team",
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
    "showdown",
    "unsupported_roster",
    "game_info_unparsed",
    "single_game",
    "game_evidence_missing",
    "game_evidence_ambiguous",
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
_GAME = re.compile(
    r"^([A-Z]{2,3})@([A-Z]{2,3}) (\d{2}/\d{2}/\d{4}) (\d{1,2}:\d{2}[AP]M) ET$"
)
_COMMIT = re.compile(r"githubusercontent.com/pureslurp/DKNFL/([0-9a-f]{7,40})/(.+)$")
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


class _Stop(Exception):
    def __init__(self, reasons: set[str]):
        super().__init__("stop")
        self.reasons = reasons


@dataclass
class ManifestEntry:
    values: dict[str, str]
    path: str
    season: int
    week: int
    row_count: int
    usable_count: int
    columns: tuple[str, ...]
    digest: str
    source_url: str | None
    commit: str | None
    repository_path: str | None


@dataclass
class ParsedRow:
    number: int
    raw_fields: tuple[tuple[str, str], ...]
    reasons: list[str] = field(default_factory=list)
    salary: Decimal | None = None
    dk_id: str | None = None
    name: str | None = None
    position: str | None = None
    roster: str | None = None
    team: str | None = None
    game_info: str | None = None
    avg_points: Decimal | None = None
    away: str | None = None
    home: str | None = None
    kickoff: datetime | None = None

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


def _source_url(value: str) -> tuple[str | None, str | None, str | None]:
    text_value = (value or "").strip()
    match = _COMMIT.search(text_value)
    if match is None or any(char.isspace() for char in text_value):
        return None, None, None
    return text_value, match.group(1), match.group(2)


def _read_manifest(path: Path) -> tuple[bytes, list[dict[str, str]]]:
    body = path.read_bytes()
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    if reader.fieldnames is None or not set(MANIFEST_COLUMNS) <= set(reader.fieldnames):
        raise ValueError("manifest_schema")
    return body, [{column: (row.get(column) or "") for column in MANIFEST_COLUMNS} for row in reader]


def _entry(row: dict[str, str]) -> ManifestEntry:
    season, week, rows, usable, digest = (
        row["season"].strip(),
        row["week"].strip(),
        row["rows"].strip(),
        row["usable_salary_rows"].strip(),
        row["sha256"].strip(),
    )
    columns = tuple(part.strip() for part in row["columns"].split("|") if part.strip())
    if not (
        _INT.fullmatch(season)
        and _INT.fullmatch(week)
        and _INT.fullmatch(rows)
        and _INT.fullmatch(usable)
        and _HEX.fullmatch(digest)
        and columns
    ):
        raise ValueError("manifest_entry")
    season_i, week_i = int(season), int(week)
    if not (1999 <= season_i <= 2100 and 1 <= week_i <= 22):
        raise ValueError("manifest_entry")
    source_url, commit, repo_path = _source_url(row["source_url"])
    return ManifestEntry(
        values=dict(row),
        path=row["path"].strip(),
        season=season_i,
        week=week_i,
        row_count=int(rows),
        usable_count=int(usable),
        columns=columns,
        digest=digest.lower(),
        source_url=source_url,
        commit=commit,
        repository_path=repo_path,
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
        records.append(tuple((header, cells[index] if index < len(cells) else "") for index, header in enumerate(headers)))
    return headers, records, None


def _lookup(raw_fields, name: str) -> str:
    for key, value in raw_fields:
        if key == name:
            return value
    return ""


def _kickoff(game_info: str):
    match = _GAME.match(game_info.strip())
    if match is None:
        return None
    away, home, day, clock = match.groups()
    parsed = datetime.strptime(f"{day} {clock}", "%m/%d/%Y %I:%M%p").replace(tzinfo=ET)
    return away, home, parsed


def classify(records, headers: list[str]) -> tuple[list[ParsedRow], set[str]]:
    parsed: list[ParsedRow] = []
    file_reasons: set[str] = set()
    has_avg = "AvgPointsPerGame" in headers
    for number, raw_fields in enumerate(records, start=1):
        row = ParsedRow(number=number, raw_fields=raw_fields)
        if all(not cell.strip() for _key, cell in raw_fields):
            row.reasons.append("blank_row")
            parsed.append(row)
            continue
        row.position = _blank(_lookup(raw_fields, "Position"))
        row.name = _blank(_lookup(raw_fields, "Name"))
        row.dk_id = _blank(_lookup(raw_fields, "ID"))
        row.roster = _blank(_lookup(raw_fields, "Roster Position"))
        row.team = _blank(_lookup(raw_fields, "TeamAbbrev"))
        row.game_info = _lookup(raw_fields, "Game Info").strip()
        row.salary = parse_number(_lookup(raw_fields, "Salary"), 2, 10)
        if has_avg:
            avg_token = _lookup(raw_fields, "AvgPointsPerGame").strip()
            if avg_token:
                row.avg_points = parse_number(avg_token, 4, 12)
                if row.avg_points is None:
                    row.reasons.append("invalid_avg")
        name_blank = row.name is None
        salary_blank = row.salary is None and not _lookup(raw_fields, "Salary").strip()
        if name_blank and salary_blank and row.dk_id is None:
            row.reasons.append("blank_row")
            parsed.append(row)
            continue
        if row.salary is None:
            row.reasons.append("invalid_salary")
        if name_blank:
            row.reasons.append("missing_name")
        if row.dk_id is None:
            row.reasons.append("missing_dk_id")
        if row.roster is None:
            row.reasons.append("missing_roster")
        elif "CPT" in row.roster.upper():
            file_reasons.add("showdown")
        else:
            tokens = [part.strip().upper() for part in row.roster.split("/") if part.strip()]
            if not tokens or any(token not in CLASSIC_TOKENS for token in tokens):
                file_reasons.add("unsupported_roster")
        if row.team is None:
            row.reasons.append("missing_team")
        located = _kickoff(row.game_info or "")
        if located is None:
            file_reasons.add("game_info_unparsed")
        else:
            row.away, row.home, row.kickoff = located
        parsed.append(row)
    counts = Counter(row.dk_id for row in parsed if row.dk_id)
    signatures: dict[str, set[tuple]] = {}
    for row in parsed:
        if row.dk_id:
            signatures.setdefault(row.dk_id, set()).add((row.salary, row.roster, row.team, row.game_info))
    for row in parsed:
        if row.dk_id and counts[row.dk_id] > 1:
            row.reasons.append("duplicate_dk_id")
            if len(signatures[row.dk_id]) > 1:
                row.reasons.append("duplicate_conflict")
    distinct = {(row.away, row.home, row.kickoff) for row in parsed if row.kickoff is not None}
    if (
        any(row.row_status is RowStatus.VALID for row in parsed)
        and len(distinct) <= 1
        and "game_info_unparsed" not in file_reasons
    ):
        file_reasons.add("single_game")
    return parsed, file_reasons


def _map_games(conn, parsed: list[ParsedRow], entry: ManifestEntry) -> tuple[list[dict], str, set[str]]:
    reasons: set[str] = set()
    grouped: dict[tuple, dict] = {}
    for row in parsed:
        if row.kickoff is None:
            continue
        key = (row.away, row.home, row.kickoff)
        grouped.setdefault(key, {"away": row.away, "home": row.home, "kickoff": row.kickoff})
    season_types: set[str] = set()
    games = []
    for key in sorted(grouped, key=lambda item: (item[2], item[0], item[1])):
        away, home, kickoff = key
        gameday = kickoff.astimezone(ET).date()
        clock = kickoff.astimezone(ET).strftime("%H:%M")
        matched = conn.execute(
            text(
                """
                SELECT game_id, season, week, season_type, gametime
                FROM games
                WHERE away_team = :away AND home_team = :home AND gameday = :gameday
                ORDER BY game_id
                """
            ),
            {"away": away, "home": home, "gameday": gameday},
        ).mappings().all()
        if not matched:
            reasons.add("game_evidence_missing")
            game_id = None
        elif len(matched) != 1:
            reasons.add("game_evidence_ambiguous")
            game_id = None
        else:
            item = matched[0]
            stored_time = (str(item["gametime"]).strip()[:5] if item["gametime"] else "")
            if stored_time and stored_time != clock:
                reasons.add("game_evidence_missing")
            if int(item["season"]) != entry.season or int(item["week"]) != entry.week:
                reasons.add("manifest_game_contradiction")
            else:
                season_types.add(str(item["season_type"]))
            game_id = str(item["game_id"])
        games.append(
            {
                "away": away,
                "home": home,
                "kickoff_at": kickoff.astimezone(UTC).isoformat(),
                "game_id": game_id,
            }
        )
    if len(season_types) != 1:
        if games and "game_evidence_missing" not in reasons and "game_evidence_ambiguous" not in reasons:
            reasons.add("manifest_game_contradiction")
        season_type = "UNKNOWN"
    else:
        season_type = next(iter(season_types))
        if season_type not in {"REG", "POST", "UNKNOWN"}:
            reasons.add("manifest_game_contradiction")
            season_type = "UNKNOWN"
    return games, season_type, reasons


def _pairs(value) -> tuple[tuple[str, str], ...]:
    return tuple((str(item[0]), str(item[1])) for item in value)


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
                "source": Source.DKNFL.value,
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
                SELECT artifact_id, body, byte_count
                FROM salary_private.salary_artifacts
                WHERE source = :source AND sha256 = :sha256
                """
            ),
            {"source": source, "sha256": digest},
        ).one_or_none()
        block = budget_block(conn, object_bytes=len(body), invocation_bytes=invocation_bytes + len(body))
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
    rows = [(row.number, row.raw_fields, row.parse_status.value, tuple(row.reasons)) for row in parsed]
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


def _close_run(conn, run_id, *, status, reason, outcome: FileOutcome, finished_at, season=None, week=None):
    _ready(conn)
    snapshot = "reused" if outcome.reused else ("published" if status == "succeeded" else "none")
    notes = (
        f"reason={reason};season={'' if season is None else season};"
        f"week={'' if week is None else week};rows_read={outcome.rows_read};"
        f"rows_valid={outcome.rows_valid};rows_rejected={outcome.rows_rejected};snapshot={snapshot}"
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


def _fail_observation(conn, observation_id, *, reason, artifact_id, metadata, finished_at, source_url, original_path):
    status = ObservationStatus.FAILED if reason in {"load_failed", "constraint_failure"} else ObservationStatus.REJECTED
    with _tx(conn):
        finish_observation(
            conn,
            observation_id=observation_id,
            status=status,
            finished_at=finished_at,
            duration_ms=None,
            artifact_id=artifact_id,
            snapshot_id=None,
            fetched_at=None,
            reason_code=reason,
            error_private=reason,
            metadata=metadata,
        )
        conn.execute(
            text(
                """
                UPDATE salary_private.salary_observations
                SET original_path = :original_path, source_url = :source_url,
                    source_published_at = NULL
                WHERE observation_id = :observation_id
                """
            ),
            {"original_path": original_path, "source_url": source_url, "observation_id": observation_id},
        )


def _startup(conn, run_group, trigger, reason) -> None:
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
        source_url=None,
        original_path=None,
    )
    _close_run(conn, run_id, status="failed", reason=reason, outcome=FileOutcome("failed", reason), finished_at=now)


def reconcile(conn, *, finished_at: datetime | None = None) -> None:
    moment = finished_at or datetime.now(UTC)
    with _tx(conn):
        runs = conn.execute(
            text("SELECT id FROM load_runs WHERE dataset = :dataset AND status = 'running'"),
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
            if len(obs) == 1 and obs[0].status == "succeeded" and obs[0].snapshot_id is not None:
                found = conn.execute(
                    text("SELECT 1 FROM salary_private.salary_snapshots WHERE snapshot_id = :id"),
                    {"id": obs[0].snapshot_id},
                ).first()
                if found is not None:
                    conn.execute(
                        text(
                            """
                            UPDATE load_runs SET status = 'succeeded', finished_at = :finished_at,
                                notes = 'reason=reconciled;snapshot=reused', error = NULL
                            WHERE id = :id AND status = 'running'
                            """
                        ),
                        {"id": run.id, "finished_at": moment},
                    )
                    continue
            if obs and obs[0].status == "running":
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
            reason = obs[0].reason_code if obs and obs[0].status in {"failed", "rejected"} and obs[0].reason_code else "interrupted"
            conn.execute(
                text(
                    """
                    UPDATE load_runs SET status = 'failed', finished_at = :finished_at,
                        notes = :notes, error = :error,
                        rows_read = COALESCE(rows_read, 0), rows_upserted = COALESCE(rows_upserted, 0),
                        rows_deleted = COALESCE(rows_deleted, 0), rows_skipped = COALESCE(rows_skipped, 0)
                    WHERE id = :id AND status = 'running'
                    """
                ),
                {"id": run.id, "finished_at": moment, "notes": f"reason={reason}", "error": reason},
            )


def _emit(selected: int, not_selected: int, outcomes: list[FileOutcome]) -> None:
    print(f"attribution={ATTRIBUTION}")
    print(
        "selected={selected} succeeded={ok} failed={bad} reused={reused} not_selected={not_selected} "
        "rows_read={read} rows_valid={valid} rows_rejected={rejected}".format(
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
        print("failed_reasons=" + ",".join(f"{key}:{counts[key]}" for key in sorted(counts)), file=sys.stderr)


def _bounded(path: Path) -> tuple[bytes, bool]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > OBJECT_LIMIT:
            return handle.read(OBJECT_LIMIT + 1)[:OBJECT_LIMIT], True
        return handle.read(), False


def _control(conn, root: Path, manifest_body: bytes, now: datetime) -> tuple[list[int], int]:
    ids = []
    invocation = 0
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
        try:
            candidate.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        body, truncated = _bounded(candidate)
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


def _process_file(conn, entry: ManifestEntry, root: Path, *, trigger, run_group, control_ids, invocation, fault, fault_path):
    now = datetime.now(UTC)
    run_id = _insert_run(conn, run_group, entry.season, trigger, now)
    observation_id = uuid4()
    _insert_observation(conn, observation_id, run_id, now)
    reasons: set[str] = set()
    artifact_id = None
    metadata = {
        "parser_version": PARSER_VERSION,
        "manifest_row": entry.values,
        "control_artifact_ids": control_ids,
        "upstream_commit": entry.commit,
        "repository_path": entry.repository_path,
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
                    source=Source.DKNFL.value,
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
                    if any(name not in headers for name in REQUIRED):
                        reasons.add("missing_core_header")
                    expected = set(entry.columns)
                    if set(headers) != expected:
                        reasons.add("column_schema")
                    parsed, row_reasons = classify(records, headers)
                    reasons.update(row_reasons)
                    if len(parsed) != entry.row_count:
                        reasons.add("count_mismatch")
                    usable = sum(1 for row in parsed if row.salary is not None)
                    if usable != entry.usable_count:
                        reasons.add("usable_count_mismatch")
                    _store_ledger(conn, artifact_id, parsed, now)
                    valid = sum(row.row_status is RowStatus.VALID for row in parsed)
                    outcome.rows_read = len(parsed)
                    outcome.rows_valid = valid
                    outcome.rows_rejected = len(parsed) - valid
                    if valid == 0:
                        reasons.add("zero_valid_rows")
                    games, season_type, game_reasons = _map_games(conn, parsed, entry)
                    reasons.update(game_reasons)
                    if reasons:
                        raise _Stop(reasons)
                    identity = {
                        "season": entry.season,
                        "season_type": season_type,
                        "week": entry.week,
                        "draft_group_id": None,
                        "source_pool_kind": PoolKind.FULL_EXPORT.value,
                        "manifest_row": entry.values,
                        "upstream_commit": entry.commit,
                        "repository_path": entry.repository_path,
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
                        "optimizer_ready": False,
                        "pool_ready": False,
                        "attribution": ATTRIBUTION,
                        "parser_version": PARSER_VERSION,
                        "duplicate_count": sum("duplicate_dk_id" in row.reasons for row in parsed),
                        "rejected_count": outcome.rows_rejected,
                        "identity": identity,
                    }
                    with _tx(conn):
                        existing = conn.execute(
                            text(
                                """
                                SELECT snapshot_id FROM salary_private.salary_snapshots
                                WHERE source = :source AND source_snapshot_key = :key
                                  AND artifact_id = :artifact_id AND parser_version = :parser
                                  AND metadata_sha256 = :metadata_sha256
                                """
                            ),
                            {
                                "source": Source.DKNFL.value,
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
                                        snapshot_id, source, artifact_id, parser_version, metadata_sha256,
                                        source_snapshot_key, season, season_type, week, draft_group_id,
                                        games, rules, game_set_sha256, rules_sha256, source_pool_kind,
                                        metadata, created_at, loaded_at
                                    ) VALUES (
                                        :snapshot_id, :source, :artifact_id, :parser, :metadata_sha256,
                                        :key, :season, :season_type, :week, NULL,
                                        CAST(:games AS jsonb), CAST(:rules AS jsonb), NULL, NULL, :pool,
                                        CAST(:metadata AS jsonb), :created_at, :loaded_at
                                    )
                                    """
                                ),
                                {
                                    "snapshot_id": snapshot_id,
                                    "source": Source.DKNFL.value,
                                    "artifact_id": artifact_id,
                                    "parser": PARSER_VERSION,
                                    "metadata_sha256": metadata_sha,
                                    "key": entry.path,
                                    "season": entry.season,
                                    "season_type": season_type,
                                    "week": entry.week,
                                    "games": json.dumps(games),
                                    "rules": json.dumps(identity["rules"]),
                                    "pool": PoolKind.FULL_EXPORT.value,
                                    "metadata": json.dumps(snapshot_meta),
                                    "created_at": now,
                                    "loaded_at": now,
                                },
                            )
                            for row in parsed:
                                conn.execute(
                                    text(
                                        """
                                        INSERT INTO salary_private.dknfl_salaries (
                                            snapshot_id, row_number, artifact_id, parser_version, row_status,
                                            reason_codes, salary, dk_id, name_raw, position_raw,
                                            roster_position_raw, team_raw, game_info_raw, avg_points_per_game,
                                            loaded_at
                                        ) VALUES (
                                            :snapshot_id, :row_number, :artifact_id, :parser, :row_status,
                                            CAST(:reasons AS jsonb), :salary, :dk_id, :name, :position,
                                            :roster, :team, :game_info, :avg_points, :loaded_at
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
                                        "dk_id": row.dk_id,
                                        "name": row.name,
                                        "position": row.position,
                                        "roster": row.roster,
                                        "team": row.team,
                                        "game_info": row.game_info,
                                        "avg_points": row.avg_points,
                                        "loaded_at": now,
                                    },
                                )
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
        source_url=entry.source_url,
        original_path=entry.path,
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
                try:
                    entries = [_entry(row) for row in selected_rows]
                except ValueError:
                    _startup(conn, run_group, trigger, "manifest_entry")
                    _emit(len(selected_rows), not_selected, [])
                    return 1
                try:
                    for entry in entries:
                        resolve_inside(root, entry.path)
                except PathReject:
                    _startup(conn, run_group, trigger, "unsafe_path")
                    _emit(len(entries), not_selected, [])
                    return 1
                try:
                    control_ids, invocation = _control(conn, root, manifest_body, datetime.now(UTC))
                except PrivateWriteError as exc:
                    _startup(conn, run_group, trigger, exc.reason)
                    _emit(len(entries), not_selected, [])
                    return 1
                hung = False
                failed = False
                for entry in sorted(entries, key=lambda item: item.path):
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
                _emit(len(entries), not_selected, outcomes)
                return 1 if hung or failed else 0
            finally:
                _ready(conn)
                unlock_capture(conn)
    except Exception:  # noqa: BLE001 - public output is a reason code, never SQL or paths
        print("load_failed", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loader.dknfl_archive")
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
