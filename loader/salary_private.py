"""Private salary persistence owned by F005.

Artifacts, attempts, snapshots, and the row ledger live here. Later archive
loaders can call this module. This file does not import lobby HTTP or F004.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

CAPTURE_LOCK = 582005
OBJECT_LIMIT = 5 * 1024 * 1024
INVOCATION_LIMIT = 64 * 1024 * 1024
CUMULATIVE_LIMIT = 128 * 1024 * 1024
DATABASE_LIMIT = 512 * 1024 * 1024
PARSER_VERSION = "f005.1"
DATASET = "dk_lobby_salaries"
PUBLIC_SOURCE_URL = "dk_lobby_salaries"


class Source(StrEnum):
    DK_LOBBY = "dk_lobby"
    DFF = "dff"
    DKNFL = "dknfl"
    F003_ADAPTER = "f003_adapter"
    F004_ADAPTER = "f004_adapter"
    CONTROL = "control"


class ArtifactKind(StrEnum):
    CSV = "csv"
    LOBBY_JSON = "lobby_json"
    RULES_JSON = "rules_json"
    HTML_GZIP = "html_gzip"
    MANIFEST = "manifest"
    SCHEDULE_RAW = "schedule_raw"
    SCHEDULE_REFERENCE = "schedule_reference"
    MAPPING = "mapping"
    ADAPTER_ROW_IMAGE = "adapter_row_image"
    REJECTED_BODY = "rejected_body"


class ObservationStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class ParseStatus(StrEnum):
    PARSED = "parsed"
    REJECTED = "rejected"


class RowStatus(StrEnum):
    VALID = "valid"
    REJECTED = "rejected"


class PoolKind(StrEnum):
    FULL_EXPORT = "full_export"
    SUBSET = "subset"
    LEGACY_UNKNOWN = "legacy_unknown"
    ADAPTER_CURRENT = "adapter_current"


class GuardBlock(StrEnum):
    OBJECT = "storage_guard_object"
    INVOCATION = "storage_guard_invocation"
    CUMULATIVE = "storage_guard_cumulative"
    DATABASE = "storage_guard_database"


class PrivateWriteError(Exception):
    def __init__(self, reason: str, private: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.private = private[:300]


@dataclass(frozen=True)
class StorageSizes:
    private_bytes: int
    database_bytes: int


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: int
    sha256: str
    byte_count: int
    reused: bool


@dataclass(frozen=True)
class LedgerRow:
    row_number: int
    raw_fields: tuple[tuple[str, str], ...]
    parse_status: ParseStatus
    reason_codes: tuple[str, ...]


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_sha256(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def lock_capture(conn) -> None:
    with conn.begin():
        conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": CAPTURE_LOCK})


def unlock_capture(conn) -> None:
    with conn.begin():
        conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": CAPTURE_LOCK})


def read_storage_sizes(conn) -> StorageSizes:
    private_bytes = conn.execute(
        text(
            """
            SELECT COALESCE(SUM(pg_total_relation_size(c.oid)), 0)
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'salary_private' AND c.relkind = 'r'
            """
        )
    ).scalar_one()
    database_bytes = conn.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
    return StorageSizes(int(private_bytes), int(database_bytes))


def cumulative_would_exceed(conn, incoming: int) -> bool:
    return bool(
        conn.execute(
            text(
                """
                SELECT COALESCE(SUM(pg_total_relation_size(c.oid)), 0) + :incoming > :limit
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'salary_private' AND c.relkind = 'r'
                """
            ),
            {"incoming": incoming, "limit": CUMULATIVE_LIMIT},
        ).scalar_one()
    )


def database_would_exceed(conn, incoming: int) -> bool:
    return bool(
        conn.execute(
            text(
                """
                SELECT pg_database_size(current_database()) + :incoming > :limit
                """
            ),
            {"incoming": incoming, "limit": DATABASE_LIMIT},
        ).scalar_one()
    )


def budget_block(
    conn,
    *,
    object_bytes: int,
    invocation_bytes: int,
    extra_bytes: int = 0,
) -> GuardBlock | None:
    growth = object_bytes + extra_bytes
    if object_bytes > OBJECT_LIMIT:
        return GuardBlock.OBJECT
    if invocation_bytes > INVOCATION_LIMIT:
        return GuardBlock.INVOCATION
    if cumulative_would_exceed(conn, growth):
        return GuardBlock.CUMULATIVE
    if database_would_exceed(conn, growth):
        return GuardBlock.DATABASE
    return None


# A payload-sized estimate does not bound Postgres growth. A 200-byte artifact
# extended the real database by 24,576 bytes (page, index, and tuple overhead).
# Publication therefore measures pg_database_size and pg_total_relation_size
# after the writes and rolls back before commit when the ceiling is crossed.
# AUDIT_HEADROOM stays free so a rolled-back attempt can still record failure.
AUDIT_HEADROOM = 256 * 1024


def actual_ceiling_block(conn) -> GuardBlock | None:
    conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CAPTURE_LOCK})
    sizes = read_storage_sizes(conn)
    if sizes.private_bytes > CUMULATIVE_LIMIT:
        return GuardBlock.CUMULATIVE
    if sizes.database_bytes + AUDIT_HEADROOM > DATABASE_LIMIT:
        return GuardBlock.DATABASE
    return None


def assert_actual_ceiling(conn) -> None:
    block = actual_ceiling_block(conn)
    if block is not None:
        raise PrivateWriteError(block.value)


def insert_running_load_run(
    conn,
    *,
    run_group: UUID,
    season: int | None,
    trigger: str,
    started_at: datetime,
) -> int:
    with conn.begin():
        row = conn.execute(
            text(
                """
                INSERT INTO load_runs
                    (run_group, dataset, season, status, trigger, started_at, source_url)
                VALUES
                    (:run_group, :dataset, :season, 'running', :trigger, :started_at, :source_url)
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


def finish_load_run(
    conn,
    run_id: int,
    *,
    status: str,
    finished_at: datetime,
    notes: str,
    error: str | None,
    rows_read: int,
    rows_upserted: int,
    rows_skipped: int,
    source_version: str | None,
) -> None:
    with conn.begin():
        conn.execute(
            text(
                """
                UPDATE load_runs SET
                    status = :status,
                    finished_at = :finished_at,
                    source_version = :source_version,
                    rows_read = :rows_read,
                    rows_upserted = :rows_upserted,
                    rows_deleted = 0,
                    rows_skipped = :rows_skipped,
                    notes = :notes,
                    error = :error
                WHERE id = :id AND status = 'running'
                """
            ),
            {
                "id": run_id,
                "status": status,
                "finished_at": finished_at,
                "source_version": source_version,
                "rows_read": rows_read,
                "rows_upserted": rows_upserted,
                "rows_skipped": rows_skipped,
                "notes": notes,
                "error": error,
            },
        )


def insert_running_observation(
    conn,
    *,
    observation_id: UUID,
    load_run_id: int,
    requested_at: datetime,
    started_at: datetime,
    observed_at: datetime,
    loaded_at: datetime,
) -> None:
    with conn.begin():
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
                "load_run_id": load_run_id,
                "source": Source.DK_LOBBY.value,
                "requested_at": requested_at,
                "started_at": started_at,
                "observed_at": observed_at,
                "source_url": PUBLIC_SOURCE_URL,
                "metadata": json.dumps({"parser_version": PARSER_VERSION}),
                "loaded_at": loaded_at,
            },
        )


def store_artifact(
    conn,
    *,
    body: bytes,
    kind: ArtifactKind,
    media_type: str,
    stored_at: datetime,
    invocation_bytes: int,
) -> ArtifactRef:
    digest = sha256_bytes(body)
    with conn.begin():
        existing = conn.execute(
            text(
                """
                SELECT artifact_id, sha256, body, byte_count
                FROM salary_private.salary_artifacts
                WHERE source = :source AND sha256 = :sha256
                """
            ),
            {"source": Source.DK_LOBBY.value, "sha256": digest},
        ).one_or_none()
        if len(body) > OBJECT_LIMIT:
            raise PrivateWriteError(GuardBlock.OBJECT.value)
        if invocation_bytes > INVOCATION_LIMIT:
            raise PrivateWriteError(GuardBlock.INVOCATION.value)
        if existing is not None:
            if bytes(existing.body) != body:
                raise PrivateWriteError("artifact_conflict")
            assert_actual_ceiling(conn)
            return ArtifactRef(int(existing.artifact_id), digest, int(existing.byte_count), True)
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
                "source": Source.DK_LOBBY.value,
                "sha256": digest,
                "body": body,
                "byte_count": len(body),
                "media_type": media_type,
                "kind": kind.value,
                "stored_at": stored_at,
                "loaded_at": stored_at,
            },
        ).one()
        if bytes(row.body) != body or row.sha256 != digest or int(row.byte_count) != len(body):
            raise PrivateWriteError("artifact_readback")
        assert_actual_ceiling(conn)
    return ArtifactRef(int(row.artifact_id), digest, len(body), False)


def _pairs(value) -> tuple[tuple[str, str], ...]:
    return tuple((str(item[0]), str(item[1])) for item in value)


def store_ledger(
    conn,
    *,
    artifact_id: int,
    rows: tuple[LedgerRow, ...],
    loaded_at: datetime,
) -> None:
    with conn.begin():
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
                    int(old.row_number) == new.row_number
                    and _pairs(old.raw_fields) == new.raw_fields
                    and old.parse_status == new.parse_status.value
                    and tuple(old.reason_codes) == new.reason_codes
                )
                if not same:
                    raise PrivateWriteError("ledger_conflict")
            assert_actual_ceiling(conn)
            return
        for row in rows:
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
                    "row_number": row.row_number,
                    "raw_fields": json.dumps(list(map(list, row.raw_fields))),
                    "parse_status": row.parse_status.value,
                    "reason_codes": json.dumps(list(row.reason_codes)),
                    "loaded_at": loaded_at,
                },
            )
        assert_actual_ceiling(conn)


def find_snapshot(
    conn,
    *,
    artifact_id: int,
    source_snapshot_key: str,
    metadata_sha256: str,
) -> UUID | None:
    row = conn.execute(
        text(
            """
            SELECT snapshot_id
            FROM salary_private.salary_snapshots
            WHERE source = :source
              AND source_snapshot_key = :source_snapshot_key
              AND artifact_id = :artifact_id
              AND parser_version = :parser
              AND metadata_sha256 = :metadata_sha256
            """
        ),
        {
            "source": Source.DK_LOBBY.value,
            "source_snapshot_key": source_snapshot_key,
            "artifact_id": artifact_id,
            "parser": PARSER_VERSION,
            "metadata_sha256": metadata_sha256,
        },
    ).one_or_none()
    if row is None:
        return None
    return row.snapshot_id


def insert_snapshot(conn, *, snapshot_id: UUID, fields: dict, salary_rows: list[dict]) -> None:
    conn.execute(
        text(
            """
            INSERT INTO salary_private.salary_snapshots (
                snapshot_id, source, artifact_id, parser_version, metadata_sha256,
                source_snapshot_key, season, season_type, week, draft_group_id,
                games, rules, game_set_sha256, rules_sha256, source_pool_kind,
                metadata, created_at, loaded_at
            ) VALUES (
                :snapshot_id, :source, :artifact_id, :parser_version, :metadata_sha256,
                :source_snapshot_key, :season, :season_type, :week, :draft_group_id,
                CAST(:games AS jsonb), CAST(:rules AS jsonb), :game_set_sha256, :rules_sha256,
                :source_pool_kind, CAST(:metadata AS jsonb), :created_at, :loaded_at
            )
            """
        ),
        fields,
    )
    for row in salary_rows:
        conn.execute(
            text(
                """
                INSERT INTO salary_private.dk_lobby_salaries (
                    snapshot_id, row_number, artifact_id, parser_version, row_status,
                    reason_codes, salary, dk_id, name_raw, position_raw,
                    roster_position_raw, team_raw, game_info_raw, avg_points_per_game,
                    status_raw, loaded_at
                ) VALUES (
                    :snapshot_id, :row_number, :artifact_id, :parser_version, :row_status,
                    CAST(:reason_codes AS jsonb), :salary, :dk_id, :name_raw, :position_raw,
                    :roster_position_raw, :team_raw, :game_info_raw, :avg_points_per_game,
                    :status_raw, :loaded_at
                )
                """
            ),
            row,
        )


def finish_observation(
    conn,
    *,
    observation_id: UUID,
    status: ObservationStatus,
    finished_at: datetime | None,
    duration_ms: int | None,
    artifact_id: int | None,
    snapshot_id: UUID | None,
    fetched_at: datetime | None,
    reason_code: str | None,
    error_private: str | None,
    metadata: dict,
) -> None:
    conn.execute(
        text(
            """
            UPDATE salary_private.salary_observations SET
                status = :status,
                finished_at = :finished_at,
                duration_ms = :duration_ms,
                artifact_id = :artifact_id,
                snapshot_id = :snapshot_id,
                fetched_at = :fetched_at,
                reason_code = :reason_code,
                error_private = :error_private,
                metadata = CAST(:metadata AS jsonb)
            WHERE observation_id = :observation_id
            """
        ),
        {
            "observation_id": observation_id,
            "status": status.value,
            "finished_at": finished_at,
            "duration_ms": duration_ms,
            "artifact_id": artifact_id,
            "snapshot_id": snapshot_id,
            "fetched_at": fetched_at,
            "reason_code": reason_code,
            "error_private": error_private,
            "metadata": json.dumps(metadata),
        },
    )


def _fail_run(conn, run_id: int, reason: str, finished_at: datetime) -> None:
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
            "id": run_id,
            "finished_at": finished_at,
            "notes": f"reason={reason};rows=0;snapshots=0",
            "error": reason,
        },
    )


def _succeed_run(conn, run_id: int, reason: str, finished_at: datetime, snapshots: int) -> None:
    conn.execute(
        text(
            """
            UPDATE load_runs SET
                status = 'succeeded',
                finished_at = COALESCE(finished_at, :finished_at),
                notes = :notes,
                error = NULL
            WHERE id = :id AND status = 'running'
            """
        ),
        {
            "id": run_id,
            "finished_at": finished_at,
            "notes": f"reason={reason};rows=0;snapshots={snapshots}",
        },
    )


def reconcile(conn, *, finished_at: datetime) -> None:
    """Close abandoned dk_lobby attempts. Do not invent duration or success."""
    with conn.begin():
        runs = conn.execute(
            text(
                """
                SELECT id
                FROM load_runs
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
                    """
                ),
                {"id": run.id},
            ).all()
            if not obs:
                _fail_run(conn, run.id, "interrupted", finished_at)
                continue
            row = obs[0]
            if row.status == ObservationStatus.SUCCEEDED.value and row.snapshot_id is not None:
                exists = conn.execute(
                    text(
                        """
                        SELECT 1 FROM salary_private.salary_snapshots
                        WHERE snapshot_id = :snapshot_id
                        """
                    ),
                    {"snapshot_id": row.snapshot_id},
                ).first()
                if exists is not None:
                    _succeed_run(conn, run.id, "reconciled", finished_at, 1)
                    continue
            if row.status == ObservationStatus.SKIPPED.value:
                _succeed_run(conn, run.id, row.reason_code or "off_season", finished_at, 0)
                continue
            if row.status in (ObservationStatus.FAILED.value, ObservationStatus.REJECTED.value):
                _fail_run(conn, run.id, row.reason_code or row.status, finished_at)
                continue
            conn.execute(
                text(
                    """
                    UPDATE salary_private.salary_observations
                    SET status = 'failed', reason_code = 'interrupted'
                    WHERE observation_id = :observation_id AND status = 'running'
                    """
                ),
                {"observation_id": row.observation_id},
            )
            _fail_run(conn, run.id, "interrupted", finished_at)


def snapshot_exists(conn, snapshot_id: UUID) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM salary_private.salary_snapshots WHERE snapshot_id = :id"),
        {"id": snapshot_id},
    ).first()
    return row is not None


def raise_private(exc: IntegrityError) -> None:
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None) or "constraint_failure"
    raise PrivateWriteError("constraint_failure", private=str(sqlstate)) from exc
