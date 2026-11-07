"""Rebuild one private salary selection. No API, UI, or optimizer.

A live union view was rejected because a failed rebuild must leave the prior
batch in place. A refresh service was rejected for the same reason. This module
writes one immutable batch plus interpretations. The SQL view reads that batch.
F003 and F004 are copied into adapter snapshots. Their public tables are not
updated. Archive loaders are not imported.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from loader.salary_private import (
    OBJECT_LIMIT,
    PoolKind,
    PrivateWriteError,
    Source,
    assert_actual_ceiling,
    budget_block,
    canonical_sha256,
    finish_load_run,
    sha256_bytes,
)
from loader.url import normalize_database_url

ROTOGURU_DK_CLASSIC_ATTRIBUTION = (
    "Historical DraftKings Classic salaries and points via RotoGuru (rotoguru1.com). "
    "Not affiliated with DraftKings."
)

PARSER_VERSION = "f008.1"
DATASET = "dk_salary_unified"
PUBLIC_SOURCE_URL = "dk_salary_unified"
PUBLISH_LOCK = 582008
OFFICIAL = {Source.F004_ADAPTER.value, Source.DK_LOBBY.value}
ARCHIVE = {Source.DKNFL.value, Source.DFF.value}
PRIORITY = {
    Source.F004_ADAPTER.value: 0,
    Source.DK_LOBBY.value: 0,
    Source.DKNFL.value: 1,
    Source.DFF.value: 2,
}


class UnifiedError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def revision_hash(games, rules, season, season_type, week) -> str:
    ordered = sorted(
        games or [],
        key=lambda game: (game.get("away") or "", game.get("home") or "", game.get("kickoff_at") or ""),
    )
    return canonical_sha256(
        {
            "contest": "Classic",
            "games": ordered,
            "publisher": "DK",
            "rules": rules or {},
            "season": season,
            "season_type": season_type,
            "sport": "NFL",
            "week": week,
        }
    )


def _ready(conn) -> None:
    if conn.in_transaction():
        conn.rollback()


@contextmanager
def _tx(conn):
    _ready(conn)
    with conn.begin():
        yield


def _parse_cutoff(value: str) -> datetime:
    text_value = value.strip()
    if text_value.endswith("Z"):
        text_value = text_value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text_value)
    if parsed.tzinfo is None:
        raise UnifiedError("naive_cutoff")
    return parsed


def _instant(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise UnifiedError("naive_cutoff")
        return value
    return _parse_cutoff(str(value))


def _load_mapping(path: Path) -> tuple[bytes, dict]:
    body = path.read_bytes()
    if len(body) > OBJECT_LIMIT:
        raise UnifiedError("storage_guard_object")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise UnifiedError("mapping_schema") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("mapping_version"), str):
        raise UnifiedError("mapping_schema")
    for key in ("slates", "entities", "snapshot_choices", "resolutions"):
        payload.setdefault(key, [])
        if not isinstance(payload[key], list):
            raise UnifiedError("mapping_schema")
    seen_rows = set()
    for item in payload["entities"]:
        token = (str(item.get("snapshot_id")), int(item.get("row_number")))
        if token in seen_rows:
            raise UnifiedError("mapping_conflict")
        seen_rows.add(token)
    seen_slates = set()
    for item in payload["slates"]:
        token = str(item.get("snapshot_id"))
        if token in seen_slates:
            raise UnifiedError("mapping_conflict")
        seen_slates.add(token)
    anchors: dict[tuple, int] = defaultdict(int)
    for item in payload["snapshot_choices"]:
        if item.get("anchor") is True:
            key = (item.get("canonical_slate_key"), item.get("slate_revision_sha256"))
            anchors[key] += 1
            if anchors[key] > 1:
                raise UnifiedError("duplicate_anchor_choice")
    return body, payload


def _positive_integral(salary) -> bool:
    if salary is None:
        return False
    number = Decimal(salary)
    return number > 0 and number == number.to_integral_value()


def _pairs(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {str(item[0]): item[1] for item in raw}
    return {}


def _store_artifact(conn, *, source: str, body: bytes, kind: str, now: datetime) -> tuple[int, str]:
    digest = sha256_bytes(body)
    existing = conn.execute(
        text(
            """
            SELECT artifact_id, body FROM salary_private.salary_artifacts
            WHERE source = :source AND sha256 = :sha
            """
        ),
        {"source": source, "sha": digest},
    ).one_or_none()
    if existing is not None:
        if bytes(existing.body) != body:
            raise UnifiedError("artifact_conflict")
        return int(existing.artifact_id), digest
    block = budget_block(conn, object_bytes=len(body), invocation_bytes=len(body))
    if block is not None:
        raise UnifiedError(block.value)
    row = conn.execute(
        text(
            """
            INSERT INTO salary_private.salary_artifacts (
                source, sha256, body, byte_count, media_type, artifact_kind, stored_at, loaded_at
            ) VALUES (
                :source, :sha, :body, :byte_count, 'application/json', :kind, :stored_at, :stored_at
            ) RETURNING artifact_id
            """
        ),
        {
            "source": source,
            "sha": digest,
            "body": body,
            "byte_count": len(body),
            "kind": kind,
            "stored_at": now,
        },
    ).one()
    return int(row.artifact_id), digest


def _ensure_snapshot(conn, *, source, artifact_id, key, season, week, season_type, pool, metadata, now, games, rules) -> UUID:
    metadata_sha = canonical_sha256(
        {
            "games": games,
            "key": key,
            "metadata": metadata,
            "pool": pool,
            "rules": rules,
            "season": season,
            "week": week,
        }
    )
    found = conn.execute(
        text(
            """
            SELECT snapshot_id FROM salary_private.salary_snapshots
            WHERE source = :source AND source_snapshot_key = :key AND artifact_id = :artifact
              AND parser_version = :parser AND metadata_sha256 = :sha
            """
        ),
        {
            "source": source,
            "key": key,
            "artifact": artifact_id,
            "parser": PARSER_VERSION,
            "sha": metadata_sha,
        },
    ).one_or_none()
    if found is not None:
        return found.snapshot_id
    snapshot_id = uuid4()
    conn.execute(
        text(
            """
            INSERT INTO salary_private.salary_snapshots (
                snapshot_id, source, artifact_id, parser_version, metadata_sha256, source_snapshot_key,
                season, season_type, week, draft_group_id, games, rules, game_set_sha256, rules_sha256,
                source_pool_kind, metadata, created_at, loaded_at
            ) VALUES (
                :snapshot_id, :source, :artifact, :parser, :sha, :key,
                :season, :season_type, :week, NULL, CAST(:games AS jsonb), CAST(:rules AS jsonb),
                NULL, NULL, :pool, CAST(:metadata AS jsonb), :now, :now
            )
            """
        ),
        {
            "snapshot_id": snapshot_id,
            "source": source,
            "artifact": artifact_id,
            "parser": PARSER_VERSION,
            "sha": metadata_sha,
            "key": key,
            "season": season,
            "season_type": season_type,
            "week": week,
            "games": json.dumps(games),
            "rules": json.dumps(rules),
            "pool": pool,
            "metadata": json.dumps(metadata),
            "now": now,
        },
    )
    return snapshot_id


def _ledger(conn, artifact_id: int, rows: list[dict], now: datetime) -> None:
    existing = conn.execute(
        text(
            """
            SELECT count(*) FROM salary_private.salary_source_rows
            WHERE artifact_id = :artifact AND parser_version = :parser
            """
        ),
        {"artifact": artifact_id, "parser": PARSER_VERSION},
    ).scalar_one()
    if int(existing):
        return
    for index, row in enumerate(rows, start=1):
        conn.execute(
            text(
                """
                INSERT INTO salary_private.salary_source_rows (
                    artifact_id, parser_version, row_number, raw_fields, parse_status, reason_codes, loaded_at
                ) VALUES (
                    :artifact, :parser, :row_number, CAST(:raw AS jsonb), 'parsed', '[]', :now
                )
                """
            ),
            {
                "artifact": artifact_id,
                "parser": PARSER_VERSION,
                "row_number": index,
                "raw": json.dumps(list(row.items())),
                "now": now,
            },
        )


def _observe(conn, *, run_id, snapshot_id, source, now, artifact_id) -> UUID:
    observation_id = uuid4()
    conn.execute(
        text(
            """
            INSERT INTO salary_private.salary_observations (
                observation_id, load_run_id, source, requested_at, started_at, finished_at,
                observed_at, source_url, artifact_id, snapshot_id, metadata, status, loaded_at
            ) VALUES (
                :id, :run_id, :source, :now, :now, :now, :now, :url, :artifact, :snapshot,
                CAST(:metadata AS jsonb), 'succeeded', :now
            )
            """
        ),
        {
            "id": observation_id,
            "run_id": run_id,
            "source": source,
            "now": now,
            "url": PUBLIC_SOURCE_URL,
            "artifact": artifact_id,
            "snapshot": snapshot_id,
            "metadata": json.dumps({"parser_version": PARSER_VERSION, "raw_retained": False}),
        },
    )
    return observation_id


def _adapt_f003(conn, now: datetime) -> None:
    rows = conn.execute(
        text(
            """
            SELECT season, week, rotoguru_gid, name_raw, pos_raw, team_raw,
                   dk_salary, dk_points, gsis_id, game_id, source_sha256
            FROM dk_classic_salaries
            ORDER BY season, week, rotoguru_gid
            """
        )
    ).mappings().all()
    grouped: dict[tuple, list] = defaultdict(list)
    for row in rows:
        grouped[(int(row["season"]), int(row["week"]))].append(dict(row))
    rules = {"rules_id": None, "roster_slots": None, "salary_cap": None, "evidence_artifact_id": None}
    for (season, week), group in grouped.items():
        image = [
            {
                "dk_points": str(item["dk_points"]),
                "dk_salary": int(item["dk_salary"]),
                "game_id": item["game_id"],
                "gsis_id": item["gsis_id"],
                "name_raw": item["name_raw"],
                "pos_raw": item["pos_raw"],
                "rotoguru_gid": int(item["rotoguru_gid"]),
                "source_sha256": item["source_sha256"],
                "team_raw": item["team_raw"],
            }
            for item in group
        ]
        body = json.dumps(image, sort_keys=True).encode()
        artifact_id, _digest = _store_artifact(
            conn, source=Source.F003_ADAPTER.value, body=body, kind="adapter_row_image", now=now
        )
        _ledger(conn, artifact_id, image, now)
        _ensure_snapshot(
            conn,
            source=Source.F003_ADAPTER.value,
            artifact_id=artifact_id,
            key=f"f003:{season}:{week}",
            season=season,
            week=week,
            season_type="UNKNOWN",
            pool=PoolKind.LEGACY_UNKNOWN.value,
            metadata={
                "raw_retained": False,
                "attribution": ROTOGURU_DK_CLASSIC_ATTRIBUTION,
                "row_count": len(image),
            },
            now=now,
            games=[],
            rules=rules,
        )


def _adapt_f004(conn, now: datetime) -> None:
    rows = conn.execute(
        text(
            """
            SELECT season, week, dk_id, name_raw, position_raw, roster_position_raw, team_raw,
                   game_info_raw, salary, source_sha256, source_loaded_at
            FROM dk_classic_slate
            ORDER BY season, week, dk_id
            """
        )
    ).mappings().all()
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        grouped[str(row["source_sha256"])].append(dict(row))
    mixed = len(grouped) > 1
    rules = {"rules_id": None, "roster_slots": None, "salary_cap": None, "evidence_artifact_id": None}
    for digest, group in grouped.items():
        image = [
            {
                "dk_id": item["dk_id"],
                "game_info_raw": item["game_info_raw"],
                "name_raw": item["name_raw"],
                "position_raw": item["position_raw"],
                "roster_position_raw": item["roster_position_raw"],
                "salary": str(item["salary"]),
                "season": int(item["season"]),
                "source_loaded_at": item["source_loaded_at"].isoformat()
                if isinstance(item["source_loaded_at"], datetime)
                else str(item["source_loaded_at"]),
                "source_sha256": digest,
                "team_raw": item["team_raw"],
                "week": int(item["week"]),
            }
            for item in group
        ]
        body = json.dumps(image, sort_keys=True).encode()
        artifact_id, _sha = _store_artifact(
            conn, source=Source.F004_ADAPTER.value, body=body, kind="adapter_row_image", now=now
        )
        _ledger(conn, artifact_id, image, now)
        _ensure_snapshot(
            conn,
            source=Source.F004_ADAPTER.value,
            artifact_id=artifact_id,
            key=f"f004:{digest}",
            season=image[0]["season"],
            week=image[0]["week"],
            season_type="REG",
            pool=PoolKind.ADAPTER_CURRENT.value,
            metadata={"raw_retained": False, "mixed_hash_cohort": mixed, "row_count": len(image)},
            now=now,
            games=[],
            rules=rules,
        )


def _candidates(conn) -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT s.source, s.snapshot_id, s.artifact_id, a.sha256 AS artifact_sha, s.parser_version,
                   s.season, s.season_type, s.week, s.draft_group_id, s.games, s.rules, s.source_pool_kind,
                   s.metadata, src.row_number, src.row_status, src.salary, src.dk_id, src.dff_player_id,
                   src.roster_position_raw, src.name_raw, src.team_raw
            FROM salary_private.salary_snapshots s
            JOIN salary_private.salary_artifacts a ON a.artifact_id = s.artifact_id
            JOIN (
                SELECT snapshot_id, row_number, row_status, salary, dk_id, NULL::text AS dff_player_id,
                       roster_position_raw, name_raw, team_raw
                FROM salary_private.dk_lobby_salaries
                UNION ALL
                SELECT snapshot_id, row_number, row_status, salary, NULL::text, dff_player_id,
                       NULL::text, name_raw, team_raw
                FROM salary_private.dff_salaries
                UNION ALL
                SELECT snapshot_id, row_number, row_status, salary, dk_id, NULL::text,
                       roster_position_raw, name_raw, team_raw
                FROM salary_private.dknfl_salaries
            ) src ON src.snapshot_id = s.snapshot_id
            """
        )
    ).mappings().all()
    found = [dict(row) for row in rows]
    adapters = conn.execute(
        text(
            """
            SELECT s.source, s.snapshot_id, s.artifact_id, a.sha256 AS artifact_sha, s.parser_version,
                   s.season, s.season_type, s.week, s.draft_group_id, s.games, s.rules, s.source_pool_kind,
                   s.metadata, r.row_number, r.raw_fields
            FROM salary_private.salary_snapshots s
            JOIN salary_private.salary_artifacts a ON a.artifact_id = s.artifact_id
            JOIN salary_private.salary_source_rows r
              ON r.artifact_id = s.artifact_id AND r.parser_version = s.parser_version
            WHERE s.source IN ('f003_adapter', 'f004_adapter')
            """
        )
    ).mappings().all()
    for row in adapters:
        image = _pairs(row["raw_fields"])
        salary = image.get("dk_salary", image.get("salary"))
        found.append(
            {
                "source": row["source"],
                "snapshot_id": row["snapshot_id"],
                "artifact_id": row["artifact_id"],
                "artifact_sha": row["artifact_sha"],
                "parser_version": row["parser_version"],
                "season": row["season"],
                "season_type": row["season_type"],
                "week": row["week"],
                "draft_group_id": row["draft_group_id"],
                "games": row["games"],
                "rules": row["rules"],
                "source_pool_kind": row["source_pool_kind"],
                "metadata": row["metadata"],
                "row_number": row["row_number"],
                "row_status": "valid",
                "salary": None if salary is None else Decimal(str(salary)),
                "dk_id": image.get("dk_id"),
                "dff_player_id": None,
                "roster_position_raw": image.get("roster_position_raw") or image.get("pos_raw"),
                "name_raw": image.get("name_raw"),
                "team_raw": image.get("team_raw"),
                "preserved_gsis_id": image.get("gsis_id"),
                "preserved_game_id": image.get("game_id"),
            }
        )
    return found


def _observations(conn, cutoff: datetime) -> dict:
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT ON (snapshot_id)
                   observation_id, snapshot_id, observed_at, source_url, original_path
            FROM salary_private.salary_observations
            WHERE status = 'succeeded' AND snapshot_id IS NOT NULL AND observed_at <= :cutoff
            ORDER BY snapshot_id, observed_at DESC, observation_id DESC
            """
        ),
        {"cutoff": cutoff},
    ).mappings().all()
    return {row["snapshot_id"]: dict(row) for row in rows}


def _known_ids(conn) -> set[str]:
    rows = conn.execute(text("SELECT snapshot_id::text FROM salary_private.salary_snapshots")).all()
    return {row[0] for row in rows}


def _exists(conn, table: str, column: str, value) -> bool:
    if value is None:
        return True
    row = conn.execute(
        text(f"SELECT 1 FROM {table} WHERE {column} = :value"),
        {"value": value},
    ).first()
    return row is not None


def _blank_placeholder(row: dict) -> bool:
    return (
        row["row_status"] == "rejected"
        and row.get("salary") is None
        and not (row.get("name_raw") or "").strip()
        and not (row.get("dk_id") or "").strip()
        and not (row.get("dff_player_id") or "").strip()
    )


def _plausible_reject(row: dict) -> bool:
    if row["row_status"] != "rejected" or _blank_placeholder(row):
        return False
    return bool(
        (row.get("name_raw") or "").strip()
        or row.get("dk_id")
        or row.get("dff_player_id")
        or row.get("salary") is not None
    )


def _groups_link(left: dict, right: dict) -> bool:
    left_group = left.get("group")
    right_group = right.get("group")
    if not left_group or not right_group or left_group == right_group:
        return True
    return right_group in left["equivalents"] and left_group in right["equivalents"]


def _validate_refs(conn, mapping: dict, rows: list[dict]) -> None:
    known = _known_ids(conn)
    present = {(str(row["snapshot_id"]), int(row["row_number"])) for row in rows}
    for slate in mapping["slates"]:
        if str(slate.get("snapshot_id")) not in known:
            raise UnifiedError("bad_mapping_reference")
    for item in mapping["entities"]:
        token = (str(item.get("snapshot_id")), int(item.get("row_number")))
        if token[0] not in known or token not in present:
            raise UnifiedError("bad_mapping_reference")
        if item.get("gsis_id") and not _exists(conn, "players", "gsis_id", item.get("gsis_id")):
            raise UnifiedError("bad_mapping_reference")
        if item.get("team_abbr") and not _exists(conn, "teams", "team_abbr", item.get("team_abbr")):
            raise UnifiedError("bad_mapping_reference")
        if item.get("game_id") and not _exists(conn, "games", "game_id", item.get("game_id")):
            raise UnifiedError("bad_mapping_reference")
    for choice in mapping["snapshot_choices"]:
        if str(choice.get("snapshot_id")) not in known:
            raise UnifiedError("bad_mapping_reference")
    for resolution in mapping["resolutions"]:
        chosen = resolution.get("chosen_ref") or {}
        if str(chosen.get("snapshot_id")) not in known:
            raise UnifiedError("bad_mapping_reference")
        if (str(chosen.get("snapshot_id")), int(chosen.get("row_number"))) not in present:
            raise UnifiedError("bad_mapping_reference")


def _entity_status(row: dict, spec: dict | None) -> dict:
    if row["source"] == Source.F003_ADAPTER.value:
        return {
            "status": "legacy_unknown",
            "entity_key": None,
            "gsis_id": row.get("preserved_gsis_id"),
            "team_abbr": None,
            "game_id": row.get("preserved_game_id"),
        }
    status = "unresolved"
    entity_key = None
    gsis = None
    team = None
    game = None
    if spec is None:
        return {"status": status, "entity_key": None, "gsis_id": None, "team_abbr": None, "game_id": None}
    kind = spec.get("kind") or ("dst" if spec.get("team_abbr") and not spec.get("gsis_id") else "player")
    native = row.get("dff_player_id") or row.get("dk_id")
    team_raw = (row.get("team_raw") or "").strip()
    mapped_team = spec.get("team_abbr")
    team_ok = not team_raw or not mapped_team or team_raw == mapped_team
    if spec.get("status") == "verified" and kind == "player" and spec.get("gsis_id") and mapped_team and spec.get("game_id"):
        if (native and spec.get("gsis_id") == native) or not team_ok:
            status = "unresolved"
        else:
            status = "verified"
            gsis = spec["gsis_id"]
            team = mapped_team
            game = spec["game_id"]
            entity_key = f"player:{gsis}"
    elif spec.get("status") == "verified" and kind == "dst" and mapped_team and team_ok:
        status = "verified"
        team = mapped_team
        entity_key = f"dst:{team}"
    elif spec.get("status") in {"ambiguous", "rejected", "unresolved", "legacy_unknown"}:
        status = spec["status"]
    return {
        "status": status,
        "entity_key": entity_key,
        "gsis_id": gsis,
        "team_abbr": team,
        "game_id": game,
    }


def _latest(items: list[dict], key) -> dict:
    return max(items, key=key)


def _pick_anchor(nodes: list[dict], choice: dict | None) -> dict | None:
    if choice is not None:
        chosen = next((node for node in nodes if str(node["snapshot_id"]) == str(choice["snapshot_id"])), None)
        if chosen is None or chosen.get("observed") is None:
            raise UnifiedError("bad_mapping_reference")
        return chosen
    by_source: dict[str, list] = defaultdict(list)
    for node in nodes:
        if node.get("observed") is None:
            continue
        by_source[node["source"]].append(node)
    picked = {}
    blocked = set()
    for source, items in by_source.items():
        shas = {item["sha"] for item in items}
        if source in ARCHIVE and len(shas) > 1:
            blocked.add(source)
            continue
        if source == Source.DK_LOBBY.value:
            picked[source] = _latest(items, lambda item: (item["observed"], item["sha"], str(item["snapshot_id"])))
        elif source == Source.F004_ADAPTER.value:
            known = [item for item in items if item["effective"] is not None]
            if len(items) > 1 and len(known) != len(items):
                blocked.add(source)
                continue
            if known:
                picked[source] = _latest(known, lambda item: (item["effective"], item["sha"], str(item["snapshot_id"])))
            else:
                picked[source] = items[0]
        else:
            picked[source] = items[0]
    official = [picked[source] for source in OFFICIAL if source in picked]
    if len(official) > 1:
        times = []
        for item in official:
            when = item["effective"] if item["source"] != Source.DK_LOBBY.value else (item["effective"] or item["observed"])
            if when is None:
                return None
            times.append((when, item))
        times.sort(key=lambda pair: (pair[0], 1 if pair[1]["source"] == Source.F004_ADAPTER.value else 0, pair[1]["sha"]))
        return times[-1][1]
    if len(official) == 1:
        return official[0]
    for source in (Source.DKNFL.value, Source.DFF.value):
        if source in picked and source not in blocked:
            return picked[source]
    return None


def _build(conn, mapping: dict, cutoff: datetime) -> tuple[list[dict], dict, list[dict]]:
    observations = _observations(conn, cutoff)
    rows = _candidates(conn)
    _validate_refs(conn, mapping, rows)
    by_snapshot: dict[UUID, list[dict]] = defaultdict(list)
    for row in rows:
        by_snapshot[row["snapshot_id"]].append(row)
    slate_of = {str(item["snapshot_id"]): item for item in mapping["slates"]}
    entity_of = {(str(item["snapshot_id"]), int(item["row_number"])): item for item in mapping["entities"]}
    interpretations = []
    nodes = []
    slate_meta = {}
    for snapshot_id, snapshot_rows in by_snapshot.items():
        sample = snapshot_rows[0]
        claim = slate_of.get(str(snapshot_id))
        status = "unresolved"
        revision = None
        key = None
        effective = None
        complete = False
        group = sample.get("draft_group_id")
        equivalents = set()
        if sample["source"] == Source.F003_ADAPTER.value:
            status = "legacy_unknown"
        elif claim is not None:
            games = claim.get("games") if claim.get("games") is not None else sample["games"]
            rules = claim.get("rules") if claim.get("rules") is not None else sample["rules"]
            revision = revision_hash(games, rules, sample["season"], sample["season_type"], sample["week"])
            supplied = claim.get("slate_revision_sha256")
            group = claim.get("draft_group_id") or group
            equivalents = set(claim.get("equivalent_group_ids") or [])
            if group:
                equivalents.add(group)
            basis = claim.get("effective_time_basis")
            if basis != "source_loaded_at":
                effective = _instant(claim.get("effective_at"))
            hash_ok = supplied == revision
            explicit_games = bool(games)
            if (
                claim.get("status") == "verified"
                and hash_ok
                and claim.get("complete_pool") is True
                and explicit_games
            ):
                status = "verified"
                complete = True
            key = claim.get("canonical_slate_key")
        slate_meta[snapshot_id] = {
            "status": status,
            "key": key,
            "revision": revision,
            "effective": effective,
            "complete": complete,
            "group": group,
            "equivalents": equivalents,
        }
        interpretations.append(
            {
                "snapshot_id": snapshot_id,
                "row_number": None,
                "status": status,
                "entity_key": None,
                "gsis_id": None,
                "team_abbr": None,
                "game_id": None,
                "canonical_slate_key": key if status != "legacy_unknown" else None,
                "slate_revision_sha256": revision if status != "legacy_unknown" else None,
                "effective_at": effective,
                "details": {"complete_pool": complete, "method": None if claim is None else claim.get("reason")},
            }
        )
        if status == "verified" and observations.get(snapshot_id) is not None:
            nodes.append(
                {
                    "snapshot_id": snapshot_id,
                    "source": sample["source"],
                    "sha": sample["artifact_sha"],
                    "pool": sample["source_pool_kind"],
                    "observed": observations[snapshot_id]["observed_at"],
                    "effective": effective,
                    "key": key,
                    "revision": revision,
                    "group": group,
                    "equivalents": equivalents,
                    "complete": complete,
                    "mixed": bool((sample.get("metadata") or {}).get("mixed_hash_cohort")),
                }
            )
    parent = list(range(len(nodes)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left_index, left in enumerate(nodes):
        for right_index in range(left_index + 1, len(nodes)):
            right = nodes[right_index]
            if left["key"] == right["key"] and left["revision"] == right["revision"] and _groups_link(left, right):
                parent[find(left_index)] = find(right_index)
    components: dict[int, list] = defaultdict(list)
    for index, node in enumerate(nodes):
        components[find(index)].append(node)
    occupied: dict[tuple, int] = defaultdict(int)
    for members in components.values():
        if members:
            occupied[(members[0]["key"], members[0]["revision"])] += 1
    choices = {
        (item.get("canonical_slate_key"), item.get("slate_revision_sha256")): item
        for item in mapping["snapshot_choices"]
        if item.get("anchor") is True
    }
    family_of: dict[UUID, dict] = {}
    for members in components.values():
        token = (members[0]["key"], members[0]["revision"])
        if occupied[token] > 1:
            for node in members:
                family_of[node["snapshot_id"]] = {"anchor": None, "ambiguous": True, "key": token[0], "revision": token[1], "nodes": members}
            continue
        choice = choices.get(token)
        anchor = _pick_anchor(members, choice)
        for node in members:
            family_of[node["snapshot_id"]] = {
                "anchor": None if anchor is None else anchor["snapshot_id"],
                "ambiguous": False,
                "key": token[0],
                "revision": token[1],
                "nodes": members,
                "anchor_node": anchor,
            }
    entity_for = {}
    for row in rows:
        spec = entity_of.get((str(row["snapshot_id"]), int(row["row_number"])))
        entity = _entity_status(row, spec)
        entity_for[(row["snapshot_id"], row["row_number"])] = entity
        meta = slate_meta[row["snapshot_id"]]
        interpretations.append(
            {
                "snapshot_id": row["snapshot_id"],
                "row_number": row["row_number"],
                "status": entity["status"],
                "entity_key": entity["entity_key"],
                "gsis_id": entity["gsis_id"],
                "team_abbr": entity["team_abbr"],
                "game_id": entity["game_id"],
                "canonical_slate_key": None if meta["status"] == "legacy_unknown" else meta["key"],
                "slate_revision_sha256": None if meta["status"] == "legacy_unknown" else meta["revision"],
                "effective_at": None,
                "details": {"method": None if spec is None else spec.get("method"), "reason": None if spec is None else spec.get("reason")},
            }
        )
    output = []
    disagreement_count = 0
    for snapshot_id, snapshot_rows in by_snapshot.items():
        family = family_of.get(snapshot_id)
        anchor_id = None if family is None else family.get("anchor")
        anchor_rows = by_snapshot.get(anchor_id, []) if anchor_id else []
        anchor_source = anchor_rows[0]["source"] if anchor_rows else None
        anchor_pool = anchor_rows[0]["source_pool_kind"] if anchor_rows else None
        anchor_node = None if family is None else family.get("anchor_node")
        members = []
        member_keys = set()
        for row in anchor_rows:
            if row["row_status"] != "valid" or _blank_placeholder(row):
                continue
            entity = entity_for[(row["snapshot_id"], row["row_number"])]
            if entity["entity_key"]:
                members.append(row)
                member_keys.add(entity["entity_key"])
        alternatives = defaultdict(list)
        other_pools = []
        if family is not None and anchor_id is not None:
            for node in family["nodes"]:
                if node["snapshot_id"] == anchor_id:
                    continue
                other = []
                for row in by_snapshot[node["snapshot_id"]]:
                    if row["row_status"] != "valid":
                        continue
                    entity = entity_for[(row["snapshot_id"], row["row_number"])]
                    if entity["status"] == "verified" and entity["entity_key"]:
                        other.append(entity["entity_key"])
                        alternatives[entity["entity_key"]].append(row)
                if node["pool"] == PoolKind.FULL_EXPORT.value and node["source"] != Source.DFF.value:
                    other_pools.append(set(other))
        anchor_keys = {
            entity_for[(row["snapshot_id"], row["row_number"])]["entity_key"]
            for row in members
            if entity_for[(row["snapshot_id"], row["row_number"])]["status"] == "verified"
        }
        membership = any(pool != anchor_keys for pool in other_pools)
        plausible = any(_plausible_reject(row) for row in anchor_rows)
        mixed = bool(anchor_node and anchor_node.get("mixed"))
        ambiguous = bool(family and family.get("ambiguous"))
        chronology = False
        if family is not None:
            for source in ARCHIVE:
                shas = {node["sha"] for node in family["nodes"] if node["source"] == source}
                chosen = any(
                    item.get("anchor") is True and str(item.get("snapshot_id")) == str(anchor_id)
                    for item in mapping["snapshot_choices"]
                )
                if len(shas) > 1 and not chosen:
                    chronology = True
        unresolved_member = any(
            entity_for[(row["snapshot_id"], row["row_number"])]["status"] != "verified"
            for row in anchor_rows
            if row["row_status"] == "valid" and not _blank_placeholder(row)
        )
        entity_counts = defaultdict(int)
        for row in anchor_rows:
            if row["row_status"] != "valid" or _blank_placeholder(row):
                continue
            key = entity_for[(row["snapshot_id"], row["row_number"])]["entity_key"]
            if key:
                entity_counts[key] += 1
        duplicate_pool = any(count > 1 for count in entity_counts.values())
        flags_for = {}
        disagreement = False
        nonpositive = False
        for row in members:
            entity = entity_for[(row["snapshot_id"], row["row_number"])]
            flags = []
            refs = []
            if entity["status"] != "verified":
                flags.append("unresolved_entity")
            for other in alternatives.get(entity["entity_key"], []):
                refs.append(
                    {
                        "snapshot_id": str(other["snapshot_id"]),
                        "row_number": other["row_number"],
                        "salary": None if other["salary"] is None else str(other["salary"]),
                        "roster_position_raw": other.get("roster_position_raw"),
                    }
                )
                roster_diff = (other.get("roster_position_raw") or "") != (row.get("roster_position_raw") or "")
                if other["salary"] != row["salary"] or roster_diff:
                    disagreement = True
                    flags.append("disagreement")
            if not _positive_integral(row["salary"]):
                nonpositive = True
                flags.append("nonpositive_salary")
            flags_for[(row["snapshot_id"], row["row_number"])] = (flags, refs)
        if disagreement:
            disagreement_count += 1
        resolved = False
        cross_source = False
        for resolution in mapping["resolutions"]:
            if (resolution.get("canonical_slate_key"), resolution.get("slate_revision_sha256")) != (
                None if family is None else family.get("key"),
                None if family is None else family.get("revision"),
            ):
                continue
            chosen = resolution.get("chosen_ref") or {}
            if str(chosen.get("snapshot_id")) != str(anchor_id):
                cross_source = True
            else:
                resolved = True
        blocked = (
            anchor_id is None
            or ambiguous
            or plausible
            or mixed
            or chronology
            or unresolved_member
            or duplicate_pool
            or nonpositive
            or membership
            or anchor_source == Source.DFF.value
            or anchor_pool in {PoolKind.SUBSET.value, PoolKind.LEGACY_UNKNOWN.value}
            or (disagreement and not resolved)
            or cross_source
            or not (anchor_node and anchor_node.get("complete"))
        )
        seen = set()
        for row in snapshot_rows:
            obs = observations.get(row["snapshot_id"])
            after = obs is None
            entity = entity_for[(row["snapshot_id"], row["row_number"])]
            flags, refs = flags_for.get((row["snapshot_id"], row["row_number"]), ([], []))
            flags = list(flags)
            if after:
                flags.append("after_cutoff")
            if _blank_placeholder(row):
                flags.append("blank_placeholder")
            if _plausible_reject(row):
                flags.append("plausible_reject")
            if chronology and row["source"] in ARCHIVE:
                flags.append("chronology_unknown")
            if membership and row["snapshot_id"] == anchor_id:
                flags.append("pool_membership_disagreement")
            if ambiguous:
                flags.append("ambiguous_slate")
            if cross_source and row["snapshot_id"] == anchor_id:
                flags.append("cross_source_override")
            duplicate = False
            if (
                row["snapshot_id"] == anchor_id
                and row["row_status"] == "valid"
                and entity["entity_key"]
                and entity["entity_key"] in seen
            ):
                duplicate = True
                flags.append("duplicate_entity")
            selected = (
                row["snapshot_id"] == anchor_id
                and row["row_status"] == "valid"
                and not after
                and not _blank_placeholder(row)
                and entity["status"] == "verified"
                and not duplicate
            )
            if selected and entity["entity_key"]:
                seen.add(entity["entity_key"])
            if (
                family is not None
                and row["snapshot_id"] != anchor_id
                and entity["entity_key"]
                and entity["entity_key"] not in member_keys
            ):
                flags.append("alternative_not_in_anchor")
            pool_ok = selected and not blocked and not duplicate
            shown_key = None if family is None else family.get("key")
            shown_rev = None if family is None else family.get("revision")
            if family is None and slate_meta[snapshot_id]["status"] != "legacy_unknown":
                shown_key = slate_meta[snapshot_id]["key"]
                shown_rev = slate_meta[snapshot_id]["revision"]
            output.append(
                {
                    "snapshot_id": row["snapshot_id"],
                    "row_number": row["row_number"],
                    "observation_id": None if obs is None else obs["observation_id"],
                    "anchor_snapshot_id": anchor_id,
                    "canonical_slate_key": shown_key,
                    "slate_revision_sha256": shown_rev,
                    "entity_key": entity["entity_key"],
                    "is_selected": selected,
                    "pool_ready": pool_ok,
                    "optimizer_ready": pool_ok and anchor_source != Source.DFF.value,
                    "salary_selected": row["salary"] if selected else None,
                    "quality_flags": {
                        "flags": sorted(set(flags)),
                        "native": {
                            "dk_id": None if row["source"] == Source.DFF.value else row.get("dk_id"),
                            "roster_position_raw": row.get("roster_position_raw"),
                            "salary": None if row.get("salary") is None else str(row.get("salary")),
                        },
                    },
                    "alternative_refs": refs,
                    "source": row["source"],
                }
            )
    summary = _summary(rows, output, disagreement_count)
    return output, summary, interpretations


def _summary(rows, output, disagreement_count) -> dict:
    valid = [row for row in rows if row["row_status"] == "valid"]
    skill = [
        row
        for row in valid
        if "DST" not in f"{row.get('roster_position_raw') or ''}"
    ]
    ready = [row for row in output if row["optimizer_ready"]]

    def rate(num, den):
        if den == 0:
            return None
        return {"numerator": num, "denominator": den}

    return {
        "raw_records": len(rows),
        "parsed_records": len(rows),
        "valid_salary_records": len(valid),
        "skill_records": len(skill),
        "dst_records": len(valid) - len(skill),
        "selected_rows": sum(1 for row in output if row["is_selected"]),
        "ready_rows": len(ready),
        "disagreement_count": disagreement_count,
        "blank_placeholders": sum(_blank_placeholder(row) for row in rows),
        "rates": {"skill_mapped": rate(len(ready), len(skill))},
    }


def _insert_interpretation(conn, item, version, evidence_sha, evidence_artifact, now) -> UUID:
    found = conn.execute(
        text(
            """
            SELECT interpretation_id FROM salary_private.salary_interpretations
            WHERE snapshot_id = :snapshot AND mapping_version = :version AND evidence_sha256 = :sha
              AND row_number IS NOT DISTINCT FROM :row_number
            """
        ),
        {
            "snapshot": item["snapshot_id"],
            "version": version,
            "sha": evidence_sha,
            "row_number": item["row_number"],
        },
    ).one_or_none()
    if found is not None:
        return found.interpretation_id
    interpretation_id = uuid4()
    conn.execute(
        text(
            """
            INSERT INTO salary_private.salary_interpretations (
                interpretation_id, snapshot_id, row_number, mapping_version, evidence_sha256,
                evidence_artifact_id, status, entity_key, gsis_id, team_abbr, game_id,
                canonical_slate_key, slate_revision_sha256, effective_at, details, created_at
            ) VALUES (
                :id, :snapshot, :row_number, :version, :sha, :artifact, :status, :entity,
                :gsis, :team, :game, :slate_key, :slate_sha, :effective, CAST(:details AS jsonb), :now
            )
            """
        ),
        {
            "id": interpretation_id,
            "snapshot": item["snapshot_id"],
            "row_number": item["row_number"],
            "version": version,
            "sha": evidence_sha,
            "artifact": evidence_artifact,
            "status": item["status"],
            "entity": item["entity_key"],
            "gsis": item["gsis_id"],
            "team": item["team_abbr"],
            "game": item["game_id"],
            "slate_key": item["canonical_slate_key"],
            "slate_sha": item["slate_revision_sha256"],
            "effective": item["effective_at"],
            "details": json.dumps(item["details"]),
            "now": now,
        },
    )
    return interpretation_id


def _input_sha(version: str, evidence_sha: str, rows: list[dict]) -> str:
    return canonical_sha256(
        {
            "mapping": evidence_sha,
            "rows": sorted(
                (
                    str(row["snapshot_id"]),
                    row["row_number"],
                    row["is_selected"],
                    row["pool_ready"],
                    None if row["salary_selected"] is None else str(row["salary_selected"]),
                )
                for row in rows
            ),
            "version": version,
        }
    )


def run(database_url: str, selection_scope: str, as_of: str, mapping_file, trigger: str = "local", *, fault: str | None = None) -> int:
    try:
        cutoff = _parse_cutoff(as_of)
    except (UnifiedError, ValueError):
        print("naive_cutoff", file=sys.stderr)
        return 1
    path = Path(mapping_file)
    try:
        engine = create_engine(normalize_database_url(database_url), pool_pre_ping=True)
        with engine.connect() as probe:
            probe.execute(text("SELECT 1"))
            probe.commit()
    except (SQLAlchemyError, OSError):
        print("database_unreachable", file=sys.stderr)
        return 1
    now = datetime.now(cutoff.tzinfo)
    run_id = None
    summary = {"selected_rows": 0, "ready_rows": 0, "raw_records": 0}
    try:
        if not path.is_file():
            with engine.connect() as conn:
                run_id = _open_run(conn, trigger, now)
                _fail(conn, run_id, "mapping_missing", now)
            print("reason=mapping_missing")
            return 1
        try:
            body, mapping = _load_mapping(path)
        except UnifiedError as exc:
            with engine.connect() as conn:
                run_id = _open_run(conn, trigger, now)
                _fail(conn, run_id, exc.reason, now)
            print(f"reason={exc.reason}")
            return 1
        evidence_sha = sha256_bytes(body)
        with engine.connect() as conn:
            run_id = _open_run(conn, trigger, now)
            with _tx(conn):
                conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PUBLISH_LOCK})
                artifact_id, _digest = _store_artifact(
                    conn, source=Source.CONTROL.value, body=body, kind="mapping", now=now
                )
                _adapt_f003(conn, now)
                _adapt_f004(conn, now)
                _observe_new_adapters(conn, run_id, now)
                built, summary, interpretations = _build(conn, mapping, cutoff)
                version = str(mapping["mapping_version"])
                input_sha = _input_sha(version, evidence_sha, built)
                existing = conn.execute(
                    text(
                        """
                        SELECT selection_id FROM salary_private.salary_selection_batches
                        WHERE selection_scope = :scope AND cutoff_at = :cutoff
                          AND mapping_version = :version AND input_sha256 = :sha
                        """
                    ),
                    {"scope": selection_scope, "cutoff": cutoff, "version": version, "sha": input_sha},
                ).one_or_none()
                if existing is None:
                    selection_id = uuid4()
                    ids = {}
                    for item in interpretations:
                        ids[(item["snapshot_id"], item["row_number"])] = _insert_interpretation(
                            conn, item, version, evidence_sha, artifact_id, now
                        )
                    conn.execute(
                        text(
                            """
                            INSERT INTO salary_private.salary_selection_batches (
                                selection_id, selection_scope, cutoff_at, mapping_version, input_sha256,
                                load_run_id, committed_at, summary
                            ) VALUES (
                                :id, :scope, :cutoff, :version, :sha, :run_id, :now, CAST(:summary AS jsonb)
                            )
                            """
                        ),
                        {
                            "id": selection_id,
                            "scope": selection_scope,
                            "cutoff": cutoff,
                            "version": version,
                            "sha": input_sha,
                            "run_id": run_id,
                            "now": now,
                            "summary": json.dumps(summary),
                        },
                    )
                    for row in built:
                        if fault == "force_duplicate" and row["is_selected"]:
                            row = dict(row)
                        conn.execute(
                            text(
                                """
                                INSERT INTO salary_private.salary_selection_rows (
                                    selection_id, snapshot_id, row_number, interpretation_id, slate_interpretation_id,
                                    observation_id, anchor_snapshot_id, canonical_slate_key, slate_revision_sha256,
                                    entity_key, is_selected, pool_ready, optimizer_ready, salary_selected,
                                    quality_flags, alternative_refs
                                ) VALUES (
                                    :selection, :snapshot, :row_number, :entity, :slate, :observation, :anchor,
                                    :slate_key, :slate_sha, :entity_key, :selected, :pool, :ready, :salary,
                                    CAST(:flags AS jsonb), CAST(:alts AS jsonb)
                                )
                                """
                            ),
                            {
                                "selection": selection_id,
                                "snapshot": row["snapshot_id"],
                                "row_number": row["row_number"],
                                "entity": ids.get((row["snapshot_id"], row["row_number"])),
                                "slate": ids.get((row["snapshot_id"], None)),
                                "observation": row["observation_id"],
                                "anchor": row["anchor_snapshot_id"],
                                "slate_key": row["canonical_slate_key"],
                                "slate_sha": row["slate_revision_sha256"],
                                "entity_key": row["entity_key"],
                                "selected": row["is_selected"],
                                "pool": row["pool_ready"],
                                "ready": row["optimizer_ready"],
                                "salary": row["salary_selected"],
                                "flags": json.dumps(row["quality_flags"]),
                                "alts": json.dumps(row["alternative_refs"]),
                            },
                        )
                        if fault == "force_duplicate" and row["is_selected"]:
                            conn.execute(
                                text(
                                    """
                                    INSERT INTO salary_private.salary_selection_rows (
                                        selection_id, snapshot_id, row_number, is_selected, pool_ready,
                                        optimizer_ready, quality_flags, alternative_refs, entity_key,
                                        canonical_slate_key, slate_revision_sha256
                                    ) VALUES (
                                        :selection, :snapshot, :row_number, true, false,
                                        false, '{}'::jsonb, '[]'::jsonb, :entity_key, :slate_key, :slate_sha
                                    )
                                    """
                                ),
                                {
                                    "selection": selection_id,
                                    "snapshot": row["snapshot_id"],
                                    "row_number": row["row_number"],
                                    "entity_key": row["entity_key"],
                                    "slate_key": row["canonical_slate_key"],
                                    "slate_sha": row["slate_revision_sha256"],
                                },
                            )
                if fault == "mid_batch":
                    raise UnifiedError("injected_fault")
                assert_actual_ceiling(conn)
            _succeed(conn, run_id, summary, now)
        print(
            f"reason=published;selected={summary['selected_rows']};ready={summary['ready_rows']};rows={summary['raw_records']}"
        )
        return 0
    except UnifiedError as exc:
        _mark_failed(engine, run_id, exc.reason, cutoff)
        print(f"reason={exc.reason}", file=sys.stderr)
        return 1
    except IntegrityError:
        _mark_failed(engine, run_id, "duplicate_selected_entity", cutoff)
        print("reason=duplicate_selected_entity", file=sys.stderr)
        return 1
    except PrivateWriteError as exc:
        _mark_failed(engine, run_id, exc.reason, cutoff)
        print(f"reason={exc.reason}", file=sys.stderr)
        return 1
    except (SQLAlchemyError, OSError):
        print("database_unreachable", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


def _mark_failed(engine, run_id, reason: str, cutoff: datetime) -> None:
    if run_id is None:
        return
    try:
        with engine.connect() as conn:
            _fail(conn, run_id, reason, datetime.now(cutoff.tzinfo))
    except SQLAlchemyError:
        print("database_unreachable", file=sys.stderr)


def _observe_new_adapters(conn, run_id: int, now: datetime) -> None:
    rows = conn.execute(
        text(
            """
            SELECT s.snapshot_id, s.source, s.artifact_id
            FROM salary_private.salary_snapshots s
            WHERE s.source IN ('f003_adapter', 'f004_adapter')
              AND NOT EXISTS (
                SELECT 1 FROM salary_private.salary_observations o WHERE o.snapshot_id = s.snapshot_id
              )
            """
        )
    ).all()
    for row in rows:
        _observe(conn, run_id=run_id, snapshot_id=row.snapshot_id, source=row.source, now=now, artifact_id=row.artifact_id)


def _open_run(conn, trigger: str, now: datetime) -> int:
    with _tx(conn):
        row = conn.execute(
            text(
                """
                INSERT INTO load_runs (run_group, dataset, season, status, trigger, started_at, source_url)
                VALUES (:run_group, :dataset, NULL, 'running', :trigger, :now, :url)
                RETURNING id
                """
            ),
            {"run_group": uuid4(), "dataset": DATASET, "trigger": trigger, "now": now, "url": PUBLIC_SOURCE_URL},
        ).one()
    return int(row.id)


def _fail(conn, run_id: int, reason: str, now: datetime) -> None:
    _ready(conn)
    finish_load_run(
        conn,
        run_id,
        status="failed",
        finished_at=now,
        notes=f"reason={reason}",
        error=reason,
        rows_read=0,
        rows_upserted=0,
        rows_skipped=0,
        source_version=PARSER_VERSION,
    )


def _succeed(conn, run_id: int, summary: dict, now: datetime) -> None:
    _ready(conn)
    finish_load_run(
        conn,
        run_id,
        status="succeeded",
        finished_at=now,
        notes=(
            f"reason=published;selected={summary['selected_rows']};"
            f"ready={summary['ready_rows']};rows={summary['raw_records']}"
        ),
        error=None,
        rows_read=summary["raw_records"],
        rows_upserted=summary["selected_rows"],
        rows_skipped=summary["raw_records"] - summary["selected_rows"],
        source_version=PARSER_VERSION,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loader.salary_unified")
    parser.add_argument("--selection-scope", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--mapping-file", required=True)
    parser.add_argument("--trigger", default="local")
    args = parser.parse_args(argv)
    trigger = {"local": "local", "manual": "manual", "scheduled": "schedule"}.get(args.trigger)
    if trigger is None:
        print("trigger_rejected", file=sys.stderr)
        return 1
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("database_unreachable", file=sys.stderr)
        return 1
    return run(database_url, args.selection_scope, args.as_of, args.mapping_file, trigger)


if __name__ == "__main__":
    sys.exit(main())
