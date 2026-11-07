"""Independent schedule inventory, raw nflverse bytes, and source-to-PG receipt.

Capture trusts a pinned authority root. It does not treat a games load, a row
count, or a hash of the rows it already stored as proof that the season is
complete. This module does not certify a real NFL season.
"""

import hashlib
import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from loader.salary_private import PrivateWriteError

AUTHORITY_ENV = "DK_SCHEDULE_AUTHORITY_SHA256"
PROOF_VERSION = "f005.schedule.1"
FRESH_HOURS = 24
FUTURE_SKEW = timedelta(minutes=5)
_CLOCK = re.compile(r"^(\d{2}):(\d{2})(?::(\d{2}))?$")


class ProjectionError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ScheduleVerdict:
    evidence: str
    subreason: str
    games: tuple[dict, ...]
    metadata: dict


def canonical_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _sha(value) -> str:
    return sha256_bytes(canonical_bytes(value))


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _day(value) -> str:
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()
    return str(value)


def _clock(value) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if text_value == "":
        return None
    match = _CLOCK.fullmatch(text_value)
    if match is None:
        raise ProjectionError("malformed_time")
    hour, minute = int(match.group(1)), int(match.group(2))
    second = int(match.group(3) or 0)
    if hour > 23 or minute > 59 or second > 59:
        raise ProjectionError("malformed_time")
    if match.group(3) is None:
        return f"{hour:02d}:{minute:02d}"
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def projection_record(row: dict, *, from_raw: bool) -> dict:
    game_type = row.get("game_type")
    if game_type is None or str(game_type) == "":
        raise ProjectionError("malformed_type")
    game_type = str(game_type)
    if from_raw:
        season_type = "REG" if game_type == "REG" else "POST"
    else:
        season_type = row.get("season_type")
        if season_type not in {"REG", "POST"}:
            raise ProjectionError("malformed_type")
    return {
        "away_team": str(row["away_team"]).upper(),
        "game_id": str(row["game_id"]),
        "game_type": game_type,
        "gameday": _day(row["gameday"]),
        "gametime": _clock(row.get("gametime")),
        "home_team": str(row["home_team"]).upper(),
        "season": int(row["season"]),
        "season_type": str(season_type),
        "week": int(row["week"]),
        "weekday": str(row["weekday"]),
    }


def projection_documents(rows: list[dict], *, from_raw: bool = True) -> tuple[list[dict], str, list[str], str]:
    records = sorted(
        (projection_record(row, from_raw=from_raw) for row in rows),
        key=lambda item: item["game_id"],
    )
    ids = [item["game_id"] for item in records]
    return records, _sha(records), ids, _sha(ids)


def parse_schedule_bytes(body: bytes, media_type: str) -> list[dict]:
    """Return normalized REG rows from the exact raw object. Season is not filtered here."""
    if media_type == "application/json" or body[:1] in (b"{", b"["):
        payload = json.loads(body)
        games = payload["games"] if isinstance(payload, dict) else payload
        return [
            projection_record(game, from_raw=True)
            for game in games
            if str(game.get("game_type", "REG")) == "REG"
        ]
    if body[:4] == b"PAR1" or "parquet" in media_type:
        import polars as pl

        frame = pl.read_parquet(body)
        rows = [record for record in frame.iter_rows(named=True) if str(record.get("game_type")) == "REG"]
        return [projection_record(row, from_raw=True) for row in rows]
    raise ValueError("unsupported schedule media")


def project_raw_season(body: bytes, media_type: str, season: int) -> list[dict]:
    """Same season slice the games loader writes. The raw bytes themselves stay complete."""
    return [row for row in parse_schedule_bytes(body, media_type) if int(row["season"]) == int(season)]


def _artifact(conn, digest: str) -> tuple[int, bytes, str] | None:
    row = conn.execute(
        text(
            """
            SELECT artifact_id, body, artifact_kind
            FROM salary_private.salary_artifacts
            WHERE source = 'control' AND sha256 = :sha
            """
        ),
        {"sha": digest},
    ).one_or_none()
    if row is None:
        return None
    body = bytes(row.body)
    if sha256_bytes(body) != digest:
        return None
    return int(row.artifact_id), body, str(row.artifact_kind)


def _document(conn, digest: str) -> tuple[int, dict] | None:
    found = _artifact(conn, digest)
    if found is None:
        return None
    artifact_id, body, _kind = found
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return artifact_id, payload


def _reject(subreason: str, **extra) -> ScheduleVerdict:
    metadata = {
        "schedule_verification_version": PROOF_VERSION,
        "schedule_verification_result": "rejected",
        "schedule_subreason": subreason,
    }
    metadata.update(extra)
    return ScheduleVerdict("schedule_evidence_missing", subreason, (), metadata)


def _pg_rows(conn, season: int) -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT game_id, season, game_type, season_type, week, gameday, weekday,
                   gametime, away_team, home_team
            FROM games
            WHERE season = :season AND game_type = 'REG'
            ORDER BY game_id
            """
        ),
        {"season": season},
    ).mappings().all()
    return [dict(row) for row in rows]


def _load_run(conn, run_id: int, season: int) -> dict | None:
    row = conn.execute(
        text(
            """
            SELECT id, status, source_version, finished_at, dataset, season
            FROM load_runs
            WHERE id = :id
            """
        ),
        {"id": run_id},
    ).mappings().one_or_none()
    if row is None:
        return None
    if row.dataset != "games" or int(row.season) != season or row.status != "succeeded":
        return None
    return dict(row)


def _retrieval_ok(retrieved: datetime, now: datetime, *, allow_historical: bool) -> str | None:
    if retrieved > now.astimezone(UTC) + FUTURE_SKEW:
        return "retrieval_in_future"
    if allow_historical:
        return None
    if retrieved < now.astimezone(UTC) - timedelta(hours=FRESH_HOURS):
        return "retrieval_stale"
    return None


def _interval_intersects_sunday(start: datetime, end: datetime, sunday) -> bool:
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    day_start = datetime(sunday.year, sunday.month, sunday.day, tzinfo=et)
    day_end = day_start + timedelta(days=1)
    return start < day_end.astimezone(UTC) and end > day_start.astimezone(UTC)


def _check_inventory(payload: dict, records: list[dict]) -> str | None:
    if payload.get("document_type") != "season_inventory_v1":
        return "inventory_type"
    planned = payload.get("planned_fixtures") or []
    represented = payload.get("represented_source_ids") or []
    if represented != sorted(represented):
        return "inventory_id_order"
    if int(payload.get("represented_count", -1)) != len(represented):
        return "inventory_count"
    if payload.get("represented_set_sha256") != _sha(represented):
        return "inventory_set_hash"
    if int(payload.get("original_scheduled_count", -1)) != len(planned):
        return "inventory_census"
    by_id = {item["game_id"]: item for item in planned}
    if len(by_id) != len(planned):
        return "inventory_duplicate"
    expected_ids = []
    appearances: dict[str, int] = {}
    for fixture in planned:
        for side in ("away_team", "home_team"):
            appearances[fixture[side]] = appearances.get(fixture[side], 0) + 1
        if fixture.get("status") == "cancelled" and fixture.get("source_representation") == "absent":
            continue
        expected_ids.append(fixture["game_id"])
    if sorted(expected_ids) != represented:
        return "inventory_representation"
    census = payload.get("team_appearance_census") or {}
    if {key: int(value) for key, value in census.items()} != appearances:
        return "inventory_appearances"
    observed = {item["game_id"]: item for item in records}
    if sorted(observed) != represented:
        return "source_id_mismatch"
    for game_id in represented:
        fixture = by_id[game_id]
        row = observed[game_id]
        if (
            row["away_team"] != fixture["away_team"]
            or row["home_team"] != fixture["home_team"]
            or int(row["week"]) != int(fixture["week"])
        ):
            return "source_matchup_mismatch"
    return None


def _timing(payload: dict, records: list[dict], sunday) -> str | None:
    planned = {item["game_id"]: item for item in payload.get("planned_fixtures") or []}
    for row in records:
        fixture = planned.get(row["game_id"], {})
        start_raw = fixture.get("possible_playing_from")
        end_raw = fixture.get("possible_playing_until")
        bounds = None
        if start_raw or end_raw:
            if not start_raw or not end_raw:
                return "timing_unbounded"
            bounds = (_parse_time(start_raw), _parse_time(end_raw))
            if bounds[1] <= bounds[0]:
                return "timing_unbounded"
        if row["gametime"] is None:
            on_target_sunday = row["gameday"] == sunday.isoformat()
            if on_target_sunday:
                return "timing_contradiction"
            if bounds is None or _interval_intersects_sunday(bounds[0], bounds[1], sunday):
                return "timing_unresolved"
            continue
        if bounds is None:
            continue
        kick = datetime.fromisoformat(f"{row['gameday']}T{row['gametime']}:00")
        from zoneinfo import ZoneInfo

        kick = kick.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)
        if kick < bounds[0] or kick > bounds[1]:
            return "timing_outside_bounds"
    return None


def _kickoff(row: dict) -> datetime:
    from zoneinfo import ZoneInfo

    text_time = row["gametime"]
    if len(text_time) == 5:
        text_time = f"{text_time}:00"
    local = datetime.fromisoformat(f"{row['gameday']}T{text_time}")
    return local.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)


def _gap_envelope(inventory: dict, records: list[dict], gap_start: datetime) -> str | None:
    by_id = {row["game_id"]: row for row in records}
    latest = None
    for fixture in inventory.get("planned_fixtures") or []:
        if fixture.get("status") == "cancelled" and fixture.get("source_representation") == "absent":
            continue
        until = fixture.get("possible_playing_until")
        row = by_id.get(fixture["game_id"])
        if until:
            instant = _parse_time(until)
        elif row is not None and row.get("gametime"):
            instant = _kickoff(row)
        else:
            return "unresolved_postponement"
        latest = instant if latest is None else max(latest, instant)
    if latest is not None and latest > gap_start:
        return "gap_envelope"
    return None


def _bind_receipt(conn, root_sha: str, inventory_sha: str, season: int, now: datetime, allow_historical: bool):
    rows = conn.execute(
        text(
            """
            SELECT body
            FROM salary_private.salary_artifacts
            WHERE source = 'control' AND artifact_kind = 'manifest'
            """
        )
    ).scalars().all()
    failure = "receipt_missing"
    for body in rows:
        try:
            receipt = json.loads(bytes(body))
        except json.JSONDecodeError:
            continue
        if receipt.get("document_type") != "schedule_source_receipt_v1":
            continue
        try:
            if int(receipt.get("season", -1)) != season:
                continue
            if receipt.get("authority_root_sha256") != root_sha or receipt.get("inventory_sha256") != inventory_sha:
                continue
            version = receipt.get("source_version")
            raw_sha = receipt.get("source_raw_sha256")
            if not version or version == raw_sha:
                failure = "publisher_version_missing"
                continue
            raw = _artifact(conn, raw_sha)
            if raw is None or raw[2] != "schedule_raw":
                failure = "raw_missing"
                continue
            parsed = project_raw_season(
                raw[1],
                receipt.get("media_type") or "application/json",
                season,
            )
            records, projection_sha, ids, id_sha = projection_documents(parsed)
            if projection_sha != receipt.get("normalized_projection_sha256") or ids != receipt.get("source_reg_ids"):
                failure = "receipt_projection_mismatch"
                continue
            if id_sha != receipt.get("source_reg_set_sha256"):
                failure = "receipt_projection_mismatch"
                continue
            run = _load_run(conn, int(receipt["games_load_run_id"]), season)
            if run is None or run.get("source_version") != version:
                failure = "load_run_mismatch"
                continue
            retrieved = _parse_time(receipt["retrieved_at"])
            stale = _retrieval_ok(retrieved, now, allow_historical=allow_historical)
            if stale:
                failure = stale
                continue
            pg_records, pg_sha, pg_ids, _pg_id_sha = projection_documents(
                _pg_rows(conn, season),
                from_raw=False,
            )
            if pg_sha != projection_sha or pg_ids != ids:
                return (
                    "fail",
                    "postgres_mismatch",
                    {
                        "schedule_raw_artifact_ids": [raw[0]],
                        "schedule_receipt_sha256s": [_sha(receipt)],
                        "expected_reg_count": len(ids),
                        "observed_reg_count": len(pg_ids),
                        "schedule_field_differences": _field_differences(records, pg_records),
                    },
                )
            return ("ok", receipt, records, raw[0])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, ProjectionError) as exc:
            failure = getattr(exc, "reason", None) or "receipt_unreadable"
            continue
    return ("fail", failure, {})


def _field_differences(expected: list[dict], observed: list[dict]) -> list[dict]:
    exp = {row["game_id"]: row for row in expected}
    obs = {row["game_id"]: row for row in observed}
    diffs = []
    for game_id in sorted(set(exp) - set(obs)):
        diffs.append({"game_id": game_id, "difference": "missing"})
    for game_id in sorted(set(obs) - set(exp)):
        diffs.append({"game_id": game_id, "difference": "extra"})
    for game_id in sorted(set(exp) & set(obs)):
        for field in ("season_type", "game_type", "week", "gametime", "gameday", "away_team", "home_team", "weekday"):
            if exp[game_id].get(field) != obs[game_id].get(field):
                diffs.append(
                    {
                        "game_id": game_id,
                        "field": field,
                        "expected": exp[game_id].get(field),
                        "observed": obs[game_id].get(field),
                    }
                )
                break
        if len(diffs) >= 20:
            break
    return diffs[:20]


@contextmanager
def repeatable_read(conn):
    """One snapshot for the authority, receipt, and Postgres reads."""
    if conn.in_transaction():
        conn.rollback()
    with conn.begin():
        conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        yield


def verify_schedule(conn, now: datetime) -> ScheduleVerdict:
    with repeatable_read(conn):
        return _verify_in_snapshot(conn, now)


def _verify_in_snapshot(conn, now: datetime) -> ScheduleVerdict:
    pin = os.environ.get(AUTHORITY_ENV)
    if not pin or len(pin) != 64:
        return _reject("authority_unpinned")
    root_found = _document(conn, pin)
    if root_found is None:
        return _reject("authority_missing", schedule_authority_root_sha256=pin)
    _root_id, root = root_found
    if root.get("document_type") != "authority_root_v1":
        return _reject("authority_type")
    if not root.get("approved_by") or not root.get("approval_reference") or not root.get("approved_at"):
        return _reject("authority_unapproved")
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    moment = now.astimezone(UTC)
    chosen = None
    for ref in root.get("coverage_documents") or []:
        found = _document(conn, ref.get("coverage_sha256", ""))
        if found is None:
            return _reject("coverage_missing")
        _cid, coverage = found
        if coverage.get("document_type") != "schedule_coverage_v1":
            return _reject("coverage_type")
        start = _parse_time(coverage["covers_from"])
        end = _parse_time(coverage["covers_until"])
        if start <= moment < end:
            if chosen is not None:
                return _reject("coverage_ambiguous")
            chosen = coverage
    if chosen is None:
        return _reject("coverage_missing", schedule_authority_root_sha256=pin)
    sunday = now.astimezone(et).date()
    sunday = sunday + timedelta(days=(6 - sunday.weekday()) % 7)
    inventory_shas = [item["inventory_sha256"] for item in chosen.get("season_inventory_refs") or []]
    allowed = {item["inventory_sha256"] for item in root.get("season_inventories") or []}
    if not inventory_shas or any(item not in allowed for item in inventory_shas):
        return _reject("coverage_inventory_unpinned")
    mode = chosen.get("mode")
    allow_historical = mode == "interseason_gap"
    seen = {"schedule_authority_root_sha256": pin, "schedule_coverage_sha256": _sha(chosen)}
    if mode == "interseason_gap":
        if not chosen.get("published_no_reg_through") and not chosen.get("next_earliest_possible_reg_at"):
            return _reject("gap_unbounded", **seen)
        bound = chosen.get("published_no_reg_through") or chosen.get("next_earliest_possible_reg_at")
        if _parse_time(bound) < moment:
            return _reject("gap_expired", **seen)
        support = list(chosen.get("prior_closure_evidence_refs") or []) + list(
            chosen.get("league_evidence_refs") or []
        )
        if not support or any(_artifact(conn, digest) is None for digest in support):
            return _reject("gap_reference_missing", **seen)
    elif mode != "active_season":
        return _reject("coverage_mode", **seen)
    games: list[dict] = []
    raw_ids: list[int] = []
    receipt_shas: list[str] = []
    observed = 0
    expected = 0
    for inventory_sha in inventory_shas:
        found = _document(conn, inventory_sha)
        if found is None:
            return _reject("inventory_missing")
        _iid, inventory = found
        for ref in inventory.get("league_reference_artifacts") or []:
            reference = _artifact(conn, ref.get("sha256", ""))
            if reference is None or reference[2] != "schedule_reference":
                return _reject("reference_missing")
        season = int(inventory["season"])
        if mode == "interseason_gap" and inventory.get("closure") != "final":
            return _reject("prior_not_final", schedule_inventory_sha256s=[inventory_sha], **seen)
        status, *bound = _bind_receipt(
            conn,
            pin,
            inventory_sha,
            season,
            now,
            allow_historical and inventory.get("closure") == "final",
        )
        if status != "ok":
            detail = bound[1] if len(bound) > 1 and isinstance(bound[1], dict) else {}
            return _reject(bound[0], schedule_inventory_sha256s=[inventory_sha], **seen, **detail)
        receipt, records, raw_id = bound
        if mode == "interseason_gap":
            envelope = _gap_envelope(inventory, records, _parse_time(chosen["covers_from"]))
            if envelope:
                return _reject(
                    envelope,
                    schedule_inventory_sha256s=[inventory_sha],
                    schedule_raw_artifact_ids=[raw_id],
                    **seen,
                )
        mismatch = _check_inventory(inventory, records)
        if mismatch:
            return _reject(
                mismatch,
                schedule_inventory_sha256s=[inventory_sha],
                schedule_raw_artifact_ids=[raw_id],
                **seen,
            )
        timing = _timing(inventory, records, sunday)
        if timing:
            return _reject(
                timing,
                schedule_inventory_sha256s=[inventory_sha],
                schedule_raw_artifact_ids=[raw_id],
                **seen,
            )
        games.extend(records)
        raw_ids.append(raw_id)
        receipt_shas.append(_sha(receipt))
        observed += len(records)
        expected += len(inventory.get("represented_source_ids") or [])
    evidence = "gap" if mode == "interseason_gap" else "verified"
    metadata = {
        "schedule_authority_root_sha256": pin,
        "schedule_inventory_sha256s": inventory_shas,
        "schedule_raw_artifact_ids": raw_ids,
        "schedule_receipt_sha256s": receipt_shas,
        "schedule_coverage_sha256": _sha(chosen),
        "schedule_verification_version": PROOF_VERSION,
        "schedule_verification_result": "verified_gap" if evidence == "gap" else "verified_active",
        "schedule_subreason": None,
        "expected_reg_count": expected,
        "observed_reg_count": observed,
        "projection_sha256": _sha(sorted(games, key=lambda item: item["game_id"])),
    }
    return ScheduleVerdict(evidence, "", tuple(games), metadata)


def _insert_control(conn, *, body: bytes, kind: str, media_type: str, stored_at: datetime) -> int:
    from loader.salary_private import CAPTURE_LOCK, assert_actual_ceiling

    conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CAPTURE_LOCK})
    digest = sha256_bytes(body)
    existing = conn.execute(
        text(
            """
            SELECT artifact_id FROM salary_private.salary_artifacts
            WHERE source = 'control' AND sha256 = :sha
            """
        ),
        {"sha": digest},
    ).scalar()
    if existing is not None:
        return int(existing)
    row = conn.execute(
        text(
            """
            INSERT INTO salary_private.salary_artifacts (
                source, sha256, body, byte_count, media_type, artifact_kind, stored_at, loaded_at
            ) VALUES (
                'control', :sha, :body, :count, :media, :kind, :stored_at, :stored_at
            )
            RETURNING artifact_id
            """
        ),
        {
            "sha": digest,
            "body": body,
            "count": len(body),
            "media": media_type,
            "kind": kind,
            "stored_at": stored_at,
        },
    ).one()
    assert_actual_ceiling(conn)
    return int(row.artifact_id)


def maybe_emit_schedule_receipt(
    conn,
    *,
    run_id: int,
    season: int,
    raw_body: bytes,
    media_type: str,
    source_url: str,
    source_version: str | None,
    retrieved_at: datetime,
) -> bool:
    """Write a receipt only when a pinned inventory already matches this raw object.

    A missing pin or a mismatch leaves the public games load untouched.
    """
    if os.environ.get("SALARY_PRIVATE_MIGRATION") != "true":
        return False
    pin = os.environ.get(AUTHORITY_ENV)
    if not pin or not source_version or source_version == sha256_bytes(raw_body):
        return False
    try:
        parsed = project_raw_season(raw_body, media_type, season)
        records, projection_sha, ids, id_sha = projection_documents(parsed)
        found = _document(conn, pin)
        if found is None:
            return False
        _root_id, root = found
        inventory_sha = next(
            (
                item["inventory_sha256"]
                for item in root.get("season_inventories") or []
                if int(item.get("season", -1)) == season
            ),
            None,
        )
        if inventory_sha is None:
            return False
        inventory_found = _document(conn, inventory_sha)
        if inventory_found is None:
            return False
        _iid, inventory = inventory_found
        if _check_inventory(inventory, records):
            return False
        raw_sha = sha256_bytes(raw_body)
        receipt = {
            "document_type": "schedule_source_receipt_v1",
            "schema_version": "schedule_source_receipt_v1",
            "authority_root_sha256": pin,
            "byte_count": len(raw_body),
            "committed_at": retrieved_at.astimezone(UTC).isoformat(),
            "games_load_run_id": run_id,
            "inventory_checks": "matched_pinned_inventory",
            "inventory_sha256": inventory_sha,
            "media_type": media_type,
            "normalized_projection_sha256": projection_sha,
            "parser_version": PROOF_VERSION,
            "projection_version": PROOF_VERSION,
            "publication_evidence_refs": [source_version],
            "retrieved_at": retrieved_at.astimezone(UTC).isoformat(),
            "retrieval_evidence": {"source_url": source_url, "status": 200},
            "season": season,
            "source_raw_sha256": raw_sha,
            "source_reg_count": len(ids),
            "source_reg_ids": ids,
            "source_reg_set_sha256": id_sha,
            "source_url": source_url,
            "source_version": source_version,
            "verification_version": PROOF_VERSION,
        }
        savepoint = conn.begin_nested()
        try:
            raw_id = _insert_control(
                conn,
                body=raw_body,
                kind="schedule_raw",
                media_type=media_type,
                stored_at=retrieved_at,
            )
            receipt["source_raw_artifact_id"] = raw_id
            _insert_control(
                conn,
                body=canonical_bytes(receipt),
                kind="manifest",
                media_type="application/json",
                stored_at=retrieved_at,
            )
            savepoint.commit()
        except (OSError, TypeError, ValueError, SQLAlchemyError, ProjectionError, PrivateWriteError):
            savepoint.rollback()
            return False
        return True
    except (OSError, TypeError, ValueError, SQLAlchemyError, ProjectionError, PrivateWriteError, json.JSONDecodeError):
        return False
