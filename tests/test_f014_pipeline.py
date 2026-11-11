"""F014 refresh-before-capture. Synthetic bytes and temporary Postgres only."""

import json
import os
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import polars as pl
import pytest
from sqlalchemy import text

from loader.coordination import (
    COORDINATION_LOCK,
    COORDINATION_WAIT_S,
    PIPELINE_DEADLINE_S,
    CoordinationError,
    RefreshStopped,
    coordination,
)
from loader.dk_lobby import HTTP_BUDGET_S, capture_schedule_enabled, run_capture
from loader.run import run_load
from loader.salary_private import (
    CUMULATIVE_LIMIT,
    DATABASE_LIMIT,
    DISCOVERY_OBJECT_LIMIT,
    INVOCATION_LIMIT,
    OBJECT_LIMIT,
)
from loader.schedule_proof import (
    AUTHORITY_ENV,
    canonical_bytes,
    maybe_emit_schedule_receipt,
    project_raw_season,
    sha256_bytes,
)
from loader.source import DirSource

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[1]
CAPTURE_WORKFLOW = ROOT / ".github" / "workflows" / "dk-lobby-capture.yml"
REFRESH_WORKFLOW = ROOT / ".github" / "workflows" / "refresh.yml"
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
NOW = datetime(2026, 11, 4, 10, 0, tzinfo=ET)
VERSION = "2026-11-04 09:00:00 EST"
RETRIEVED = datetime(2026, 11, 4, 14, 0, tzinfo=UTC)


class Clock:
    def __init__(self, wall, mono=0.0):
        self.wall_now = wall
        self.mono_now = mono

    def wall(self):
        return self.wall_now

    def mono(self):
        return self.mono_now


class Transport(httpx.BaseTransport):
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def handle_request(self, request):
        self.calls.append(request)
        status, headers, body = self.handler(request)
        return httpx.Response(status, headers=headers, content=body, request=request)


def _et(year, month, day, hour, minute):
    return datetime(year, month, day, hour, minute, tzinfo=ET)


def _iso(moment):
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _info(away, home, moment):
    local = moment.astimezone(ET)
    hour = local.hour
    suffix = "AM"
    if hour >= 12:
        suffix = "PM"
        if hour > 12:
            hour -= 12
    if hour == 0:
        hour = 12
    return f"{away}@{home} {local.month}/{local.day}/{local.year} {hour:02d}:{local.minute:02d}{suffix} ET"


def _game(game_id, season, week, away, home, moment):
    local = moment.astimezone(ET)
    return {
        "game_id": game_id,
        "season": season,
        "week": week,
        "away_team": away,
        "home_team": home,
        "kickoff": moment,
        "gameday": local.date().isoformat(),
        "weekday": WEEKDAYS[local.weekday()],
        "gametime": local.strftime("%H:%M"),
        "game_type": "REG",
    }


def _sunday_plan():
    return [
        _game("2026_10_NYJ_NE", 2026, 10, "NYJ", "NE", _et(2026, 11, 8, 13, 0)),
        _game("2026_10_GB_CHI", 2026, 10, "GB", "CHI", _et(2026, 11, 8, 16, 25)),
    ]


def _holiday_plan():
    return [_game("2026_16_CIN_PIT", 2026, 16, "CIN", "PIT", _et(2026, 12, 26, 13, 0))]


def _prior_plan():
    return [_game("2026_17_KC_DEN", 2026, 17, "KC", "DEN", _et(2027, 1, 3, 13, 0))]


def _next_plan():
    return [_game("2027_01_BUF_MIA", 2027, 1, "BUF", "MIA", _et(2027, 9, 12, 13, 0))]


def _write_parquet(path: Path, frame: pl.DataFrame) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)
    return path.read_bytes()


def _teams_frame(abbreviations):
    rows = []
    for abbr in sorted(set(abbreviations)):
        rows.append(
            {
                "team_abbr": abbr,
                "team_name": abbr,
                "team_nick": abbr,
                "team_conf": "AFC",
                "team_division": "East",
                "team_id": abbr,
                "team_color": "#000000",
                "team_color2": "#ffffff",
            }
        )
    return pl.DataFrame(rows)


def _players_frame():
    return pl.DataFrame(
        [
            {
                "gsis_id": "00-0090001",
                "display_name": "Synthetic Quarterback",
                "first_name": None,
                "last_name": None,
                "position": "QB",
                "position_group": "QB",
                "birth_date": None,
                "height": None,
                "weight": None,
                "college_name": None,
                "rookie_season": None,
                "last_season": None,
                "latest_team": None,
                "status": None,
                "years_of_experience": None,
                "draft_year": None,
                "draft_round": None,
                "draft_pick": None,
                "draft_team": None,
                "pfr_id": None,
                "espn_id": None,
                "pff_id": None,
                "nfl_id": None,
                "esb_id": None,
                "otc_id": None,
            }
        ]
    )


def _games_frame(plan):
    rows = []
    for game in plan:
        rows.append(
            {
                "game_id": game["game_id"],
                "season": game["season"],
                "game_type": "REG",
                "week": game["week"],
                "gameday": date.fromisoformat(game["gameday"]),
                "weekday": game["weekday"],
                "gametime": game["gametime"],
                "away_team": game["away_team"],
                "home_team": game["home_team"],
                "away_score": None,
                "home_score": None,
                "result": None,
                "total": None,
                "overtime": None,
                "location": "Home",
                "roof": None,
                "surface": None,
                "stadium": None,
                "spread_line": None,
                "total_line": None,
                "old_game_id": None,
                "pfr": None,
                "espn": None,
            }
        )
    return pl.DataFrame(rows)


def _stats_frame(plan, season):
    chosen = next(game for game in plan if game["season"] == season)
    return pl.DataFrame(
        [
            {
                "player_id": "00-0090001",
                "season": season,
                "week": chosen["week"],
                "season_type": "REG",
                "game_id": chosen["game_id"],
                "team": chosen["away_team"],
                "opponent_team": chosen["home_team"],
                "position": "QB",
                "position_group": "QB",
                "completions": 0,
                "attempts": 0,
                "passing_yards": 0,
                "passing_tds": 0,
                "passing_interceptions": 0,
                "sacks_suffered": 0,
                "sack_fumbles_lost": 0,
                "passing_2pt_conversions": 0,
                "carries": 0,
                "rushing_yards": 0,
                "rushing_tds": 0,
                "rushing_fumbles_lost": 0,
                "rushing_2pt_conversions": 0,
                "receptions": 0,
                "targets": 0,
                "receiving_yards": 0,
                "receiving_tds": 0,
                "receiving_fumbles_lost": 0,
                "receiving_2pt_conversions": 0,
                "target_share": None,
                "special_teams_tds": 0,
                "fantasy_points": 0,
                "fantasy_points_ppr": 0,
            }
        ]
    )


def _stamp(directory: Path, name: str, version: str) -> None:
    path = directory / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "timestamp.json").write_text(json.dumps({"last_updated": version}))


def write_source(root: Path, plan, *, retrieved_at, version=VERSION, seasons=None) -> bytes:
    seasons = seasons or sorted({game["season"] for game in plan})
    abbreviations = [team for game in plan for team in (game["away_team"], game["home_team"])]
    _write_parquet(root / "teams" / "teams_colors_logos.parquet", _teams_frame(abbreviations))
    _write_parquet(root / "players" / "players.parquet", _players_frame())
    body = _write_parquet(root / "schedules" / "games.parquet", _games_frame(plan))
    _stamp(root, "teams", version)
    _stamp(root, "players", version)
    _stamp(root, "schedules", version)
    _stamp(root, "stats_player", version)
    (root / "schedules" / "retrieval.json").write_text(
        json.dumps({"retrieved_at": retrieved_at.astimezone(UTC).isoformat()})
    )
    for season in seasons:
        _write_parquet(
            root / "stats_player" / f"stats_player_week_{season}.parquet",
            _stats_frame(plan, season),
        )
    os.utime(root / "schedules" / "games.parquet", None)
    return body


def _store(conn, body: bytes, kind: str, media: str, stored_at: datetime) -> None:
    conn.execute(
        text(
            """
            INSERT INTO salary_private.salary_artifacts (
                source, sha256, body, byte_count, media_type, artifact_kind, stored_at, loaded_at
            ) VALUES (
                'control', :sha, :body, :count, :media, :kind, :stored_at, :stored_at
            )
            ON CONFLICT (source, sha256) DO NOTHING
            """
        ),
        {
            "sha": sha256_bytes(body),
            "body": body,
            "count": len(body),
            "media": media,
            "kind": kind,
            "stored_at": stored_at,
        },
    )


def install_authority(
    conn,
    records,
    *,
    retrieved_at,
    closure="open",
    active=True,
    gap=False,
    covers_from="2026-09-01T04:00:00+00:00",
    covers_until="2027-02-10T05:00:00+00:00",
):
    """Operator pin for a synthetic season. Not a real NFL certification."""
    from loader.schedule_proof import projection_documents

    records, _projection, ids, id_sha = projection_documents(records)
    appearances: dict[str, int] = {}
    planned = []
    for row in records:
        planned.append(
            {
                "away_team": row["away_team"],
                "game_id": row["game_id"],
                "home_team": row["home_team"],
                "season": row["season"],
                "source_representation": "present",
                "status": "active",
                "week": row["week"],
            }
        )
        appearances[row["away_team"]] = appearances.get(row["away_team"], 0) + 1
        appearances[row["home_team"]] = appearances.get(row["home_team"], 0) + 1
    reference = b"synthetic league schedule reference fixture\n"
    inventory = {
        "closure": closure,
        "document_type": "season_inventory_v1",
        "league_reference_artifacts": [
            {"sha256": sha256_bytes(reference), "url": "https://example.test/synthetic-league-reference"}
        ],
        "nflverse_source_origin": "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.parquet",
        "original_scheduled_count": len(planned),
        "planned_fixtures": planned,
        "represented_count": len(ids),
        "represented_set_sha256": id_sha,
        "represented_source_ids": ids,
        "review": {
            "approved_at": "2026-11-01T15:00:00+00:00",
            "method": "synthetic-fixture",
            "reviewer": "synthetic-operator",
        },
        "schema_version": "season_inventory_v1",
        "season": int(records[0]["season"]),
        "season_type": "REG",
        "team_appearance_census": appearances,
    }
    inventory_body = canonical_bytes(inventory)
    inventory_sha = sha256_bytes(inventory_body)
    documents = []
    if active:
        documents.append(
            {
                "covers_from": covers_from,
                "covers_until": covers_until,
                "document_type": "schedule_coverage_v1",
                "mode": "active_season",
                "review": {"reviewer": "synthetic-operator"},
                "schema_version": "schedule_coverage_v1",
                "season_inventory_refs": [{"inventory_sha256": inventory_sha}],
            }
        )
    if gap:
        documents.append(
            {
                "covers_from": "2027-02-10T05:00:00+00:00",
                "covers_until": "2027-09-01T04:00:00+00:00",
                "document_type": "schedule_coverage_v1",
                "mode": "interseason_gap",
                "prior_closure_evidence_refs": [sha256_bytes(reference)],
                "league_evidence_refs": [sha256_bytes(reference)],
                "published_no_reg_through": "2027-09-01T04:00:00+00:00",
                "review": {"reviewer": "synthetic-operator"},
                "schema_version": "schedule_coverage_v1",
                "season_inventory_refs": [{"inventory_sha256": inventory_sha}],
            }
        )
    coverage_refs = []
    coverage_bodies = []
    for document in documents:
        body = canonical_bytes(document)
        coverage_bodies.append(body)
        coverage_refs.append({"coverage_sha256": sha256_bytes(body)})
    root = {
        "approval_reference": "synthetic-fixture-not-a-season-certification",
        "approved_at": "2026-11-01T15:00:00+00:00",
        "approved_by": "synthetic-operator",
        "coverage_documents": coverage_refs,
        "document_type": "authority_root_v1",
        "schema_version": "authority_root_v1",
        "season_inventories": [
            {"inventory_sha256": inventory_sha, "season": int(records[0]["season"])}
        ],
    }
    root_body = canonical_bytes(root)
    _store(conn, reference, "schedule_reference", "text/plain", retrieved_at)
    _store(conn, inventory_body, "manifest", "application/json", retrieved_at)
    for body in coverage_bodies:
        _store(conn, body, "manifest", "application/json", retrieved_at)
    _store(conn, root_body, "manifest", "application/json", retrieved_at)
    return sha256_bytes(root_body)


def _rows(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).mappings().all()


def _scalar(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def _csv(rows):
    header = (
        "Position,Name + ID,Name,ID,Roster Position,Salary,Game Info,"
        "TeamAbbrev,AvgPointsPerGame,Status"
    )
    return b"\xef\xbb\xbf" + "\n".join([header, *rows]).encode()


def _sunday_csv():
    sun1 = _info("NYJ", "NE", _et(2026, 11, 8, 13, 0))
    sun2 = _info("GB", "CHI", _et(2026, 11, 8, 16, 25))
    return _csv(
        [
            f"QB,Synthetic Quarterback (900001),Synthetic Quarterback,900001,QB,4242,{sun1},NYJ,1.5,Active",
            f"WR,Synthetic Wideout (900002),Synthetic Wideout,900002,WR/FLEX,4343,{sun1},NE,,Active",
            f"RB,Synthetic Rusher (900003),Synthetic Rusher,900003,RB/FLEX,4444,{sun2},GB,2,Active",
            f"DST,Synthetic Defense (900004),Synthetic Defense,900004,DST,4545,{sun2},CHI,3,Active",
        ]
    )


def _group(draft_id, games):
    return {
        "DraftGroupId": draft_id,
        "ContestTypeId": 21,
        "GameTypeId": 7,
        "Games": [
            {"AwayTeamAbbrev": game["away_team"], "HomeTeamAbbrev": game["home_team"], "StartDate": _iso(game["kickoff"])}
            for game in games
        ],
    }


def _handler(plan, *, groups=None):
    slots = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"]
    payload = {
        "DraftGroups": groups if groups is not None else [_group(90001, plan)],
    }

    def handle(request):
        path = request.url.path
        if path.endswith("/getcontests"):
            return 200, {"content-type": "application/json"}, json.dumps(payload).encode()
        if path.endswith("/rules"):
            body = json.dumps({"salaryCap": 50000, "rosterSlots": slots}).encode()
            return 200, {"content-type": "application/json"}, body
        if path.endswith("/getavailableplayerscsv"):
            return 200, {"content-type": "text/csv"}, _sunday_csv()
        return 404, {"content-type": "text/plain"}, b"missing"

    return handle


def _arm(monkeypatch, database_url):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SALARY_PRIVATE_MIGRATION", "true")
    monkeypatch.setenv("DK_LOBBY_CAPTURE_ENABLED", "true")


def _install(monkeypatch, engine, records, **kwargs):
    with engine.begin() as conn:
        pin = install_authority(conn, records, **kwargs)
    monkeypatch.setenv(AUTHORITY_ENV, pin)


def _run(database_url, engine, root, transport, clock, **kwargs):
    from loader.pipeline import run_pipeline

    return run_pipeline(
        database_url=database_url,
        engine=engine,
        data_dir=root,
        transport=transport,
        clock=clock,
        sleeper=lambda _seconds: None,
        gate="true",
        **kwargs,
    )


def test_manual_bounds_and_negative_duration():
    from loader.pipeline import _duration_ms, validate_request

    accepted, problem = validate_request(
        trigger="manual",
        season="1999",
        week="1",
        draft_group_id=None,
        selection="sunday-afternoon",
    )
    assert problem is None
    assert accepted["season"] == 1999 and accepted["week"] == 1
    accepted, problem = validate_request(
        trigger="manual",
        season="2100",
        week="18",
        draft_group_id="1",
        selection=None,
    )
    assert problem is None
    assert accepted["draft_group_id"] == "1"
    assert (
        validate_request(
            trigger="manual",
            season="1998",
            week="1",
            draft_group_id=None,
            selection="sunday-afternoon",
        )[1]
        == "season_out_of_range"
    )
    assert (
        validate_request(
            trigger="manual",
            season="2101",
            week="18",
            draft_group_id=None,
            selection="sunday-afternoon",
        )[1]
        == "season_out_of_range"
    )
    clock = Clock(NOW, 0)
    assert _duration_ms(clock, 0) == 0
    assert _duration_ms(clock, 1) is None
    scheduled, problem = validate_request(
        trigger="schedule",
        season=None,
        week=None,
        draft_group_id=None,
        selection=None,
    )
    assert problem is None and scheduled["automatic"] is True
    assert (
        validate_request(
            trigger="schedule",
            season=None,
            week=None,
            draft_group_id="4",
            selection=None,
        )[1]
        == "invalid_selector"
    )
    assert (
        validate_request(
            trigger="schedule",
            season=None,
            week=None,
            draft_group_id=None,
            selection="other",
        )[1]
        == "invalid_selector"
    )
    manual, problem = validate_request(
        trigger="manual",
        season="2026",
        week="10",
        draft_group_id=None,
        selection="sunday-afternoon",
    )
    assert problem is None and manual["automatic"] is False


def test_at2_gate_blocks_every_side_effect(monkeypatch, database_url, engine):
    calls = {"migrate": 0}

    def _migrate(*_args, **_kwargs):
        calls["migrate"] += 1
        raise AssertionError("migrate")

    monkeypatch.setattr("loader.pipeline.migrate_production", _migrate)
    from loader.pipeline import run_pipeline

    for flag in (None, "false", "TRUE", " true", "true "):
        result = run_pipeline(
            database_url=database_url,
            engine=engine,
            trigger="schedule",
            gate=flag,
        )
        assert result.ok is False
        assert result.trace == ("gate",)
        assert result.persisted is False
    assert calls["migrate"] == 0
    assert capture_schedule_enabled("true") is True
    workflow = CAPTURE_WORKFLOW.read_text()
    assert "vars.DK_LOBBY_CAPTURE_ENABLED == 'true'" in workflow
    assert "continue-on-error" not in workflow
    assert "actions: write" not in workflow


def test_at3_invalid_manual_input_writes_nothing(monkeypatch, database_url, engine):
    calls = {"migrate": 0}

    def _migrate(*_args, **_kwargs):
        calls["migrate"] += 1

    monkeypatch.setattr("loader.pipeline.migrate_production", _migrate)
    from loader.pipeline import run_pipeline

    cases = [
        ({"season": "", "week": "10"}, "invalid_season"),
        ({"season": "2026", "week": "nope"}, "invalid_week"),
        ({"season": "1800", "week": "10"}, "season_out_of_range"),
        ({"season": "2026", "week": "19"}, "week_out_of_range"),
        ({"season": "2026", "week": "10", "selection": "sunday-afternoon", "draft_group_id": "9"}, "invalid_selector"),
        ({"season": "2026", "week": "10", "draft_group_id": "0"}, "invalid_draft_group"),
        ({"season": "2026", "week": "10"}, "invalid_selector"),
    ]
    before = _scalar(engine, "SELECT count(*) FROM load_runs")
    for fields, reason in cases:
        result = run_pipeline(
            database_url=database_url,
            engine=engine,
            trigger="manual",
            gate="true",
            selection=fields.get("selection"),
            draft_group_id=fields.get("draft_group_id"),
            season=fields.get("season"),
            week=fields.get("week"),
        )
        assert result.reason == reason, fields
        assert result.trace == ("gate", "validation")
    assert calls["migrate"] == 0
    assert _scalar(engine, "SELECT count(*) FROM load_runs") == before


def test_at8_wednesday_slot_and_unchanged_daily_refresh():
    capture = CAPTURE_WORKFLOW.read_text()
    refresh = REFRESH_WORKFLOW.read_text()
    assert capture.count("cron:") == 1
    assert "cron: '7 10 * * 3'" in capture
    assert "timezone: 'America/New_York'" in capture
    assert "0 10 * * 3" not in capture
    assert "0 14 * * 3" not in capture
    assert "0 15 * * 3" not in capture
    winter = datetime(2026, 1, 7, 10, 7, tzinfo=ET)
    summer = datetime(2026, 7, 8, 10, 7, tzinfo=ET)
    assert winter.weekday() == 2 and summer.weekday() == 2
    assert winter.utcoffset() == timedelta(hours=-5)
    assert summer.utcoffset() == timedelta(hours=-4)
    assert winter.astimezone(UTC) == datetime(2026, 1, 7, 15, 7, tzinfo=UTC)
    assert summer.astimezone(UTC) == datetime(2026, 7, 8, 14, 7, tzinfo=UTC)
    assert 'cron: "0 11 * * *"' in refresh
    assert "timezone:" not in refresh
    assert "cancel-in-progress: false" in capture
    assert "cancel-in-progress: false" in refresh
    assert "group: dk-lobby-capture" in capture
    assert "group: nflverse-refresh" in refresh
    assert "group: dk-lobby-capture" not in refresh


def test_at14_and_at18_permissions_inventory_and_no_dispatch():
    capture = CAPTURE_WORKFLOW.read_text()
    refresh = REFRESH_WORKFLOW.read_text()
    assert "permissions:\n  contents: read" in capture
    assert "actions: write" not in capture
    assert "workflow_dispatch" in capture
    assert "repository_dispatch" not in capture
    assert "gh workflow run" not in capture
    assert "Manual dispatch authorization checklist" in capture
    assert "Actions: write" in capture
    assert "non-goal" in capture
    assert "secrets.DATABASE_URL" in capture
    assert "vars.READONLY_ROLE" in capture
    assert "vars.SALARY_PRIVATE_MIGRATION" in capture
    assert "vars.DK_SCHEDULE_AUTHORITY_SHA256" in capture
    assert "vars.DK_LOBBY_CAPTURE_ENABLED" in capture
    pipeline = (ROOT / "loader" / "pipeline.py").read_text()
    coordination = (ROOT / "loader" / "coordination.py").read_text()
    assert "skip-lock" not in pipeline
    assert "skip_lock" not in pipeline
    assert "pg_cancel_backend" not in coordination
    assert "pg_terminate_backend" not in coordination
    assert COORDINATION_LOCK != 582005
    assert COORDINATION_WAIT_S == 120
    assert PIPELINE_DEADLINE_S == 1800
    assert HTTP_BUDGET_S == 180
    assert not list((ROOT / "migrations" / "versions").glob("0010*"))
    assert "render.yaml" not in capture
    assert "fromDatabase" not in refresh
    for name in ("loader/pipeline.py", "loader/dk_lobby.py", "loader/run.py"):
        assert "actions:write" not in (ROOT / name).read_text()


def test_at15_storage_limits_unchanged():
    assert DISCOVERY_OBJECT_LIMIT == 33_554_432
    assert OBJECT_LIMIT == 5_242_880
    assert INVOCATION_LIMIT == 64 * 1024 * 1024
    assert CUMULATIVE_LIMIT == 536_870_912
    assert DATABASE_LIMIT == 805_306_368


def test_dir_source_retrieval_ignores_mtime(tmp_path):
    root = tmp_path / "mirror"
    body = write_source(root, _sunday_plan(), retrieved_at=RETRIEVED)
    parquet = root / "schedules" / "games.parquet"
    future = datetime(2030, 1, 1, tzinfo=UTC).timestamp()
    os.utime(parquet, (future, future))
    source = DirSource(root)
    assert source.retrieved_at("games") == RETRIEVED
    assert sha256_bytes(source.fetch_parquet("games", None)) == sha256_bytes(body)
    (root / "schedules" / "retrieval.json").unlink()
    assert DirSource(root).retrieved_at("games") is None


def test_at1_schedule_and_manual_share_one_refresh_receipt(
    monkeypatch, database_url, engine, tmp_path
):
    _arm(monkeypatch, database_url)
    plan = _sunday_plan()
    root = tmp_path / "mirror"
    body = write_source(root, plan, retrieved_at=RETRIEVED)
    records = project_raw_season(body, "application/vnd.apache.parquet", 2026)
    migrations = {"n": 0}
    from loader.migrate import migrate_production

    def _wrapped(url, flag):
        migrations["n"] += 1
        return migrate_production(url, flag)

    monkeypatch.setattr("loader.pipeline.migrate_production", _wrapped)
    _install(monkeypatch, engine, records, retrieved_at=RETRIEVED)
    transport = Transport(_handler(plan))
    clock = Clock(NOW, 0)
    scheduled = _run(
        database_url,
        engine,
        root,
        transport,
        clock,
        trigger="schedule",
    )
    assert scheduled.trace == ("gate", "validation", "migration", "refresh", "proof", "capture")
    assert scheduled.ok is True, scheduled.reason
    assert migrations["n"] == 1
    assert transport.calls
    assert scheduled.capture.season == 2026
    assert scheduled.capture.week == 10
    obs = _rows(
        engine,
        """
        SELECT metadata, snapshot_id, duration_ms, status, reason_code
        FROM salary_private.salary_observations
        ORDER BY loaded_at DESC
        LIMIT 1
        """,
    )[0]
    meta = obs["metadata"]
    assert meta["pipeline_timing_scope"] == "capture"
    assert meta["pipeline_stage"] == "capture"
    assert meta["pipeline_refresh_run_group"]
    assert obs["snapshot_id"] is not None
    assert obs["duration_ms"] is not None
    assert obs["duration_ms"] >= 0
    games_ids = [int(item) for item in meta["pipeline_games_load_run_ids"]]
    assert games_ids
    bound = _rows(
        engine,
        """
        SELECT id, run_group::text AS run_group
        FROM load_runs
        WHERE dataset = 'games' AND season = 2026 AND status = 'succeeded'
        ORDER BY id DESC
        LIMIT 1
        """,
    )[0]
    assert int(bound["id"]) in games_ids
    assert bound["run_group"] == meta["pipeline_refresh_run_group"]
    manual_transport = Transport(_handler(plan))
    manual = _run(
        database_url,
        engine,
        root,
        manual_transport,
        Clock(NOW + timedelta(minutes=5), 10),
        trigger="manual",
        season="2026",
        week="10",
        selection="sunday-afternoon",
    )
    assert manual.ok is True, manual.reason
    assert manual.trace[-1] == "capture"
    assert migrations["n"] == 2
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 1
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dk_lobby_salaries") > 0


def test_at4_other_season_and_supported_gap(monkeypatch, database_url, engine, tmp_path):
    _arm(monkeypatch, database_url)
    older = [
        _game("2025_01_NYJ_NE", 2025, 1, "NYJ", "NE", _et(2025, 9, 7, 13, 0)),
        _game("2025_01_GB_CHI", 2025, 1, "GB", "CHI", _et(2025, 9, 7, 16, 25)),
    ]
    older_root = tmp_path / "older"
    older_body = write_source(older_root, older, retrieved_at=RETRIEVED)
    older_records = project_raw_season(older_body, "application/vnd.apache.parquet", 2025)
    _install(
        monkeypatch,
        engine,
        older_records,
        retrieved_at=RETRIEVED,
        covers_from="2025-09-01T04:00:00+00:00",
        covers_until="2027-02-10T05:00:00+00:00",
    )
    assert run_load(
        database_url=database_url,
        seasons=[2025],
        data_dir=older_root,
        trigger="manual",
        wait_seconds=5,
    )
    current = _sunday_plan()
    root = tmp_path / "current"
    write_source(root, current, retrieved_at=RETRIEVED)
    transport = Transport(_handler(current))
    mismatch = _run(
        database_url,
        engine,
        root,
        transport,
        Clock(NOW, 0),
        trigger="schedule",
    )
    assert mismatch.reason == "schedule_evidence_missing"
    assert transport.calls == []
    assert mismatch.persisted is True
    gap_root = tmp_path / "gap"
    prior = _prior_plan() + _next_plan()
    prior_body = write_source(gap_root, prior, retrieved_at=datetime(2027, 1, 3, 18, 0, tzinfo=UTC))
    prior_records = project_raw_season(prior_body, "application/vnd.apache.parquet", 2026)
    _install(
        monkeypatch,
        engine,
        prior_records,
        retrieved_at=RETRIEVED,
        closure="final",
        gap=True,
    )
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE player_week_stats"))
    assert run_load(
        database_url=database_url,
        seasons=[2026],
        data_dir=gap_root,
        trigger="manual",
        wait_seconds=5,
    )
    gap_transport = Transport(_handler(prior))
    gap_clock = Clock(datetime(2027, 4, 15, 10, 0, tzinfo=ET), 0)
    (gap_root / "schedules" / "retrieval.json").write_text(
        json.dumps({"retrieved_at": "2027-04-15T12:00:00+00:00"})
    )
    gap = _run(
        database_url,
        engine,
        gap_root,
        gap_transport,
        gap_clock,
        trigger="schedule",
    )
    assert gap.ok is True, gap.reason
    assert gap.reason == "off_season"
    assert gap_transport.calls == []
    assert gap.capture.season is None
    assert gap.capture.week is None


def test_at5_refresh_failure_keeps_partial_public_rows(
    monkeypatch, database_url, engine, tmp_path
):
    _arm(monkeypatch, database_url)
    root = tmp_path / "mirror"
    write_source(root, _sunday_plan(), retrieved_at=RETRIEVED)
    (root / "stats_player" / "stats_player_week_2026.parquet").unlink()
    transport = Transport(_handler(_sunday_plan()))
    before_snap = _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots")
    result = _run(database_url, engine, root, transport, Clock(NOW, 0), trigger="schedule")
    assert result.reason == "refresh_failed"
    assert transport.calls == []
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == before_snap
    assert _scalar(engine, "SELECT count(*) FROM teams") > 0
    assert _scalar(engine, "SELECT count(*) FROM games") > 0
    obs = _rows(
        engine,
        """
        SELECT reason_code, snapshot_id, metadata, duration_ms, status
        FROM salary_private.salary_observations
        ORDER BY loaded_at DESC LIMIT 1
        """,
    )[0]
    assert obs["reason_code"] == "refresh_failed"
    assert obs["snapshot_id"] is None
    assert obs["metadata"]["pipeline_timing_scope"] == "pipeline"
    assert obs["metadata"]["pipeline_stage"] == "refresh"
    assert obs["duration_ms"] is not None
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dk_lobby_salaries") == 0

    def _stop():
        raise RefreshStopped("refresh_failed")

    root2 = tmp_path / "cancel"
    write_source(root2, _sunday_plan(), retrieved_at=RETRIEVED)
    cancelled = _run(
        database_url,
        engine,
        root2,
        Transport(_handler(_sunday_plan())),
        Clock(NOW, 0),
        trigger="schedule",
        checkpoint=_stop,
    )
    assert cancelled.reason == "refresh_failed"
    assert _scalar(engine, "SELECT count(*) FROM teams") > 0


def test_at6_missing_proof_does_not_use_a_public_success(
    monkeypatch, database_url, engine, tmp_path
):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DK_LOBBY_CAPTURE_ENABLED", "true")
    monkeypatch.delenv("SALARY_PRIVATE_MIGRATION", raising=False)
    monkeypatch.delenv(AUTHORITY_ENV, raising=False)
    root = tmp_path / "mirror"
    write_source(root, _sunday_plan(), retrieved_at=RETRIEVED)
    transport = Transport(_handler(_sunday_plan()))
    result = _run(database_url, engine, root, transport, Clock(NOW, 0), trigger="schedule")
    assert result.reason == "schedule_evidence_missing"
    assert transport.calls == []
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 0
    assert _scalar(engine, "SELECT count(*) FROM games") > 0
    obs = _rows(
        engine,
        """
        SELECT snapshot_id, metadata, reason_code
        FROM salary_private.salary_observations ORDER BY loaded_at DESC LIMIT 1
        """,
    )[0]
    assert obs["snapshot_id"] is None
    assert obs["reason_code"] == "schedule_evidence_missing"
    assert obs["metadata"]["pipeline_timing_scope"] == "pipeline"


def test_at7_same_run_receipt_rules(monkeypatch, database_url, engine, tmp_path):
    _arm(monkeypatch, database_url)
    plan = _sunday_plan()
    root = tmp_path / "mirror"
    body = write_source(root, plan, retrieved_at=RETRIEVED - timedelta(hours=30))
    records = project_raw_season(body, "application/vnd.apache.parquet", 2026)
    _install(monkeypatch, engine, records, retrieved_at=RETRIEVED)
    stale = _run(
        database_url,
        engine,
        root,
        Transport(_handler(plan)),
        Clock(NOW, 0),
        trigger="schedule",
    )
    assert stale.reason == "schedule_evidence_missing"
    stored = _rows(
        engine,
        """
        SELECT body FROM salary_private.salary_artifacts
        WHERE artifact_kind = 'manifest'
        """,
    )
    found_old = False
    for row in stored:
        try:
            payload = json.loads(bytes(row["body"]))
        except json.JSONDecodeError:
            continue
        if payload.get("document_type") == "schedule_source_receipt_v1":
            found_old = True
            assert payload["retrieved_at"].startswith("2026-11-03")
    assert found_old
    (root / "schedules" / "retrieval.json").write_text(
        json.dumps({"retrieved_at": "2026-11-04T15:30:00+00:00"})
    )
    future = _run(
        database_url,
        engine,
        root,
        Transport(_handler(plan)),
        Clock(NOW, 5),
        trigger="manual",
        season="2026",
        week="10",
        selection="sunday-afternoon",
    )
    assert future.reason == "schedule_evidence_missing"
    (root / "schedules" / "retrieval.json").write_text(
        json.dumps({"retrieved_at": RETRIEVED.isoformat()})
    )
    fresh = _run(
        database_url,
        engine,
        root,
        Transport(_handler(plan)),
        Clock(NOW, 20),
        trigger="manual",
        season="2026",
        week="10",
        selection="sunday-afternoon",
    )
    assert fresh.ok is True, fresh.reason
    copied = tmp_path / "copied"
    write_source(copied, plan, retrieved_at=RETRIEVED)
    (copied / "schedules" / "retrieval.json").unlink()
    missing = _run(
        database_url,
        engine,
        copied,
        Transport(_handler(plan)),
        Clock(NOW, 30),
        trigger="manual",
        season="2026",
        week="10",
        selection="sunday-afternoon",
    )
    assert missing.reason == "schedule_evidence_missing"


def test_at9_sunday_exactness_after_refresh(monkeypatch, database_url, engine, tmp_path):
    _arm(monkeypatch, database_url)
    plan = _sunday_plan()
    root = tmp_path / "sunday"
    body = write_source(root, plan, retrieved_at=RETRIEVED)
    records = project_raw_season(body, "application/vnd.apache.parquet", 2026)
    _install(monkeypatch, engine, records, retrieved_at=RETRIEVED)
    ambiguous = Transport(
        _handler(plan, groups=[_group(90001, plan), _group(90002, plan)])
    )
    result = _run(
        database_url,
        engine,
        root,
        ambiguous,
        Clock(NOW, 0),
        trigger="schedule",
    )
    assert result.reason == "ambiguous_slate"
    assert result.capture.season == 2026
    holiday = _holiday_plan()
    holiday_root = tmp_path / "holiday"
    holiday_body = write_source(
        holiday_root,
        holiday,
        retrieved_at=datetime(2026, 12, 23, 14, 0, tzinfo=UTC),
    )
    holiday_records = project_raw_season(holiday_body, "application/vnd.apache.parquet", 2026)
    _install(monkeypatch, engine, holiday_records, retrieved_at=RETRIEVED)
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE player_week_stats"))
    holiday_transport = Transport(_handler(holiday))
    holiday_result = _run(
        database_url,
        engine,
        holiday_root,
        holiday_transport,
        Clock(_et(2026, 12, 23, 10, 0), 0),
        trigger="schedule",
    )
    assert holiday_result.reason == "slate_unavailable"
    assert holiday_transport.calls == []
    assert "on-time" not in CAPTURE_WORKFLOW.read_text()


def test_at10_coordination_excludes_overlapping_work(database_url, engine, tmp_path):
    root = tmp_path / "mirror"
    write_source(root, _sunday_plan(), retrieved_at=RETRIEVED)
    entered = []
    released = threading.Event()
    holding = threading.Event()

    def _hold():
        with coordination(engine, wait_seconds=5):
            holding.set()
            assert released.wait(timeout=5)

    thread = threading.Thread(target=_hold)
    thread.start()
    assert holding.wait(timeout=5)
    with pytest.raises(CoordinationError) as caught:
        run_load(
            database_url=database_url,
            seasons=[2026],
            data_dir=root,
            trigger="manual",
            wait_seconds=0,
            checkpoint=lambda: entered.append("refresh"),
        )
    assert caught.value.reason == "pipeline_busy"
    assert entered == []
    from loader.dk_lobby import run_capture as capture

    busy = capture(
        engine,
        season=2026,
        week=10,
        trigger="manual",
        selection="sunday-afternoon",
        draft_group_id=None,
        wait_seconds=0,
        clock=Clock(NOW, 0),
        sleeper=lambda _seconds: None,
    )
    assert busy.reason == "pipeline_busy"
    assert busy.persisted is False
    released.set()
    thread.join(timeout=5)
    follow = run_load(
        database_url=database_url,
        seasons=[2026],
        data_dir=root,
        trigger="manual",
        wait_seconds=5,
    )
    assert follow is True
    capture_text = CAPTURE_WORKFLOW.read_text()
    refresh_text = REFRESH_WORKFLOW.read_text()
    assert "cancel-in-progress: false" in capture_text
    assert "cancel-in-progress: false" in refresh_text
    assert "group: dk-lobby-capture" in capture_text
    assert "group: nflverse-refresh" in refresh_text


def test_at11_lock_loss_deadline_and_no_self_deadlock(monkeypatch, database_url, engine, tmp_path):
    _arm(monkeypatch, database_url)
    done = threading.Event()

    def _child():
        with coordination(engine, wait_seconds=5), engine.begin() as conn:
            assert (
                maybe_emit_schedule_receipt(
                    conn,
                    run_id=1,
                    season=2026,
                    raw_body=b"not-a-schedule",
                    media_type="application/json",
                    source_url="https://example.test/schedules",
                    source_version=None,
                    retrieved_at=RETRIEVED,
                )
                is False
            )
        done.set()

    worker = threading.Thread(target=_child)
    worker.start()
    worker.join(timeout=5)
    assert done.is_set()
    root = tmp_path / "mirror"
    write_source(root, _sunday_plan(), retrieved_at=RETRIEVED)

    def _drop():
        from loader.coordination import _owner

        owner = _owner.get()
        owner.conn.invalidate()

    lost = _run(
        database_url,
        engine,
        root,
        Transport(_handler(_sunday_plan())),
        Clock(NOW, 0),
        trigger="schedule",
        checkpoint=_drop,
    )
    assert lost.reason == "pipeline_lock_lost"
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 0
    clock = Clock(NOW, 0)

    def _expire():
        clock.mono_now = PIPELINE_DEADLINE_S + 1

    expired = _run(
        database_url,
        engine,
        root,
        Transport(_handler(_sunday_plan())),
        clock,
        trigger="schedule",
        checkpoint=_expire,
    )
    assert expired.reason == "pipeline_timeout"
    assert expired.capture is None
    with engine.connect() as conn:
        held = conn.execute(
            text("SELECT pg_try_advisory_lock(CAST(:key AS bigint))"),
            {"key": COORDINATION_LOCK},
        ).scalar()
        assert held is True
        conn.execute(
            text("SELECT pg_advisory_unlock(CAST(:key AS bigint))"),
            {"key": COORDINATION_LOCK},
        )
        conn.commit()


def test_at12_repeat_reuses_snapshot_and_keeps_attempts(
    monkeypatch, database_url, engine, tmp_path
):
    _arm(monkeypatch, database_url)
    plan = _sunday_plan()
    root = tmp_path / "mirror"
    body = write_source(root, plan, retrieved_at=RETRIEVED)
    records = project_raw_season(body, "application/vnd.apache.parquet", 2026)
    _install(monkeypatch, engine, records, retrieved_at=RETRIEVED)
    first = _run(
        database_url,
        engine,
        root,
        Transport(_handler(plan)),
        Clock(NOW, 0),
        trigger="manual",
        season="2026",
        week="10",
        selection="sunday-afternoon",
    )
    assert first.ok is True, first.reason
    games_after = _scalar(engine, "SELECT count(*) FROM games")
    second = _run(
        database_url,
        engine,
        root,
        Transport(_handler(plan)),
        Clock(NOW + timedelta(minutes=1), 50),
        trigger="manual",
        season="2026",
        week="10",
        selection="sunday-afternoon",
    )
    assert second.ok is True, second.reason
    assert _scalar(engine, "SELECT count(*) FROM games") == games_after
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 1
    attempts = _rows(
        engine,
        """
        SELECT observation_id::text AS observation_id, metadata
        FROM salary_private.salary_observations
        WHERE reason_code = 'captured'
        """,
    )
    assert len(attempts) == 2
    assert attempts[0]["metadata"]["pipeline_refresh_run_group"] != attempts[1]["metadata"][
        "pipeline_refresh_run_group"
    ]


def test_at13_crash_does_not_fabricate_duration(monkeypatch, database_url, engine, tmp_path):
    _arm(monkeypatch, database_url)
    plan = _sunday_plan()
    root = tmp_path / "mirror"
    body = write_source(root, plan, retrieved_at=RETRIEVED)
    records = project_raw_season(body, "application/vnd.apache.parquet", 2026)
    _install(monkeypatch, engine, records, retrieved_at=RETRIEVED)
    from loader.dk_lobby import Crash

    with pytest.raises(Crash):
        _run(
            database_url,
            engine,
            root,
            Transport(_handler(plan)),
            Clock(NOW, 0),
            trigger="manual",
            season="2026",
            week="10",
            selection="sunday-afternoon",
            failpoint="before_terminal",
        )
    interrupted = _rows(
        engine,
        """
        SELECT status, finished_at, duration_ms, snapshot_id
        FROM salary_private.salary_observations
        ORDER BY loaded_at DESC LIMIT 1
        """,
    )[0]
    assert interrupted["finished_at"] is None
    assert interrupted["duration_ms"] is None
    assert interrupted["snapshot_id"] is None
    from loader.dk_lobby import reconcile_open_attempts

    reconcile_open_attempts(engine, clock=Clock(NOW + timedelta(minutes=1), 10))
    recovered = _rows(
        engine,
        """
        SELECT status, finished_at, duration_ms, reason_code
        FROM salary_private.salary_observations
        ORDER BY loaded_at DESC LIMIT 1
        """,
    )[0]
    assert recovered["status"] == "failed"
    assert recovered["reason_code"] == "interrupted"
    assert recovered["finished_at"] is None
    assert recovered["duration_ms"] is None
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 0
    replay = _run(
        database_url,
        engine,
        root,
        Transport(_handler(plan)),
        Clock(NOW + timedelta(minutes=2), 20),
        trigger="manual",
        season="2026",
        week="10",
        selection="sunday-afternoon",
    )
    assert replay.ok is True, replay.reason
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 1


def test_at17_public_output_and_unreachable_database(monkeypatch, database_url, engine, capsys):
    from loader.pipeline import main

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DK_LOBBY_CAPTURE_ENABLED", "true")
    assert main(["--trigger", "manual", "--season", "nope", "--week", "10"]) == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == "invalid_season"
    assert "postgresql://" not in captured.err
    monkeypatch.setenv("DATABASE_URL", "postgresql://seam@127.0.0.1:1/none")
    before = _scalar(engine, "SELECT count(*) FROM salary_private.salary_observations")
    assert (
        main(
            [
                "--trigger",
                "manual",
                "--season",
                "2026",
                "--week",
                "10",
                "--selection",
                "sunday-afternoon",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.err.strip() == "database_unreachable"
    assert "audit" not in captured.err.lower()
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_observations") == before


def test_queued_capture_rechecks_proof_after_the_lock(engine):
    started = threading.Event()
    release = threading.Event()

    def _hold():
        with coordination(engine, wait_seconds=5):
            started.set()
            assert release.wait(timeout=5)

    thread = threading.Thread(target=_hold)
    thread.start()
    assert started.wait(timeout=5)
    outcome = {}

    def _capture():
        outcome["result"] = run_capture(
            engine,
            season=2026,
            week=10,
            trigger="manual",
            selection="sunday-afternoon",
            draft_group_id=None,
            wait_seconds=5,
            clock=Clock(NOW, 0),
            sleeper=lambda _seconds: None,
        )

    waiter = threading.Thread(target=_capture)
    waiter.start()
    release.set()
    waiter.join(timeout=10)
    thread.join(timeout=5)
    assert outcome["result"].reason == "schedule_evidence_missing"
    assert outcome["result"].persisted is True
