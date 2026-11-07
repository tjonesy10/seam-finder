"""F007 acceptance tests. Fixtures are synthetic. No archive payloads."""

import csv
import hashlib
import io
import os
import shutil
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from loader.dknfl_archive import ATTRIBUTION, parse_number, reconcile, run
from loader.grants import apply_readonly_grant
from loader.salary_private import OBJECT_LIMIT

ROOT = Path(__file__).parents[1]
HEADER = [
    "Position",
    "Name + ID",
    "Name",
    "ID",
    "Roster Position",
    "Salary",
    "Game Info",
    "TeamAbbrev",
    "AvgPointsPerGame",
]
MANIFEST_COLUMNS = [
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
]
SOURCE_URL = "https://raw.githubusercontent.com/pureslurp/DKNFL/abc1234abc/2022/Week1/DKSalaries.csv"


def _rows(engine, sql, **params):
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(text(sql), params).mappings()]


def _scalar(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def _info(away, home, day="09/11/2022", clock="01:00PM"):
    return f"{away}@{home} {day} {clock} ET"


def _dk(**overrides):
    row = {
        "Position": "QB",
        "Name + ID": "Pat Sample (1001)",
        "Name": "Pat Sample",
        "ID": "1001",
        "Roster Position": "QB",
        "Salary": "5000",
        "Game Info": _info("BUF", "KC"),
        "TeamAbbrev": "KC",
        "AvgPointsPerGame": "10.5",
    }
    row.update(overrides)
    name = row["Name"]
    identifier = row["ID"]
    if name and identifier:
        row["Name + ID"] = f"{name} ({identifier})"
    return row


def _csv_bytes(records, header=None, *, bom=False, crlf=False):
    header = header or HEADER
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n" if crlf else "\n")
    writer.writerow(header)
    for record in records:
        writer.writerow([record.get(column, "") for column in header])
    body = buffer.getvalue().encode()
    return b"\xef\xbb\xbf" + body if bom else body


def _archive(tmp, specs):
    root = tmp / "archive"
    (root / "raw").mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    for spec in specs:
        header = spec.get("header", HEADER)
        body = spec.get("body")
        records = spec.get("rows", [])
        if body is None:
            body = _csv_bytes(records, header, bom=spec.get("bom", False), crlf=spec.get("crlf", False))
        relative = spec["path"]
        if ".." not in Path(relative).parts and not str(relative).startswith("/"):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        digest = spec.get("sha", hashlib.sha256(body).hexdigest())
        usable = spec.get("usable")
        if usable is None:
            usable = sum(1 for record in records if parse_number(str(record.get("Salary", "")), 2, 10))
        manifest_rows.append(
            {
                "path": relative,
                "season": str(spec["season"]),
                "week": str(spec["week"]),
                "rows": str(spec.get("row_count", len(records))),
                "usable_salary_rows": str(usable),
                "source": spec.get("source", "pureslurp/DKNFL"),
                "source_url": spec.get("source_url", SOURCE_URL),
                "format": "synthetic",
                "date": spec.get("date", "09/11/2022"),
                "unique_players_in_file": str(spec.get("players", len(records))),
                "min_salary": "0",
                "max_salary": "0",
                "columns": "|".join(spec.get("manifest_columns", header)),
                "sha256": digest,
                "quality_note": "synthetic",
            }
        )
        if spec.get("conflict"):
            extra = dict(manifest_rows[-1])
            extra["sha256"] = "0" * 64
            manifest_rows.append(extra)
    manifest_path = root / "MANIFEST.csv"
    with manifest_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(manifest_rows)
    return root, manifest_path


def _load(database_url, root, manifest, **kwargs):
    return run(database_url, root, manifest, "local", **kwargs)


def _team(conn, abbr):
    conn.execute(
        text(
            """
            INSERT INTO teams (
                team_abbr, team_name, team_nick, team_conf, team_division,
                team_id, team_color, team_color2, loaded_at
            ) VALUES (
                :abbr, :abbr, :abbr, 'NFC', 'East', '1', '#000000', '#ffffff', CURRENT_TIMESTAMP
            )
            ON CONFLICT DO NOTHING
            """
        ),
        {"abbr": abbr},
    )


def _game(conn, game_id, season, week, away, home, gameday, gametime="13:00", season_type="REG"):
    for abbr in (away, home):
        _team(conn, abbr)
    conn.execute(
        text(
            """
            INSERT INTO games (
                game_id, season, game_type, season_type, week, gameday, weekday, gametime,
                away_team, home_team, location, loaded_at
            ) VALUES (
                :game_id, :season, :season_type, :season_type, :week, :gameday, 'Sunday',
                :gametime, :away, :home, 'Home', CURRENT_TIMESTAMP
            )
            """
        ),
        {
            "game_id": game_id,
            "season": season,
            "season_type": season_type,
            "week": week,
            "gameday": gameday,
            "gametime": gametime,
            "away": away,
            "home": home,
        },
    )


def _pair(conn, season, week, gameday, season_type="REG", prefix="g"):
    _game(conn, f"{prefix}1", season, week, "BUF", "KC", gameday, "13:00", season_type)
    _game(conn, f"{prefix}2", season, week, "DAL", "PHI", gameday, "16:25", season_type)


def _two_players(day="09/11/2022"):
    return [
        _dk(**{"ID": "1001", "Game Info": _info("BUF", "KC", day, "01:00PM"), "TeamAbbrev": "KC"}),
        _dk(
            **{
                "ID": "1002",
                "Name": "Alex Sample",
                "Position": "RB",
                "Roster Position": "RB/FLEX",
                "Game Info": _info("DAL", "PHI", day, "04:25PM"),
                "TeamAbbrev": "PHI",
                "Salary": "6100",
            }
        ),
    ]


def _markers(conn):
    conn.execute(
        text(
            """
            INSERT INTO dk_classic_salaries (
                season, week, rotoguru_gid, name_raw, pos_raw, team_raw, home_away,
                opponent_raw, dk_points, dk_salary, source_url, source_fetched_at,
                source_sha256, loaded_at
            ) VALUES (
                2022, 1, 7, 'Marker', 'QB', 'KC', 'H', 'BUF', 1, 5000,
                'https://example.invalid/marker', CURRENT_TIMESTAMP, :sha, CURRENT_TIMESTAMP
            )
            """
        ),
        {"sha": "ab" * 32},
    )
    conn.execute(
        text(
            """
            INSERT INTO dk_classic_slate (
                season, week, dk_id, name_raw, position_raw, roster_position_raw,
                team_raw, salary, source_name, source_sha256, source_loaded_at, loaded_at
            ) VALUES (
                2022, 1, 'marker-id', 'Marker', 'QB', 'QB', 'KC', 5000,
                'marker.csv', :sha, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        ),
        {"sha": "cd" * 32},
    )


def test_at1_only_dknfl_rows_and_contracts(database_url, engine, tmp_path):
    with engine.begin() as conn:
        _markers(conn)
        _pair(conn, 2022, 1, date(2022, 9, 11))
    before = _scalar(engine, "SELECT count(*) FROM dk_classic_salaries")
    root, manifest = _archive(
        tmp_path,
        [
            {
                "path": "raw/dk.csv",
                "season": 2022,
                "week": 1,
                "rows": _two_players(),
            },
            {
                "path": "raw/dff.csv",
                "season": 2022,
                "week": 1,
                "source": "Daily Fantasy Fuel",
                "rows": [_dk(Name="NOT_LOADED_TOKEN")],
            },
        ],
    )
    assert _load(database_url, root, manifest) == 0
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dknfl_salaries") == 2
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_artifacts WHERE source = 'dff'") == 0
    bodies = b"".join(bytes(row["body"]) for row in _rows(engine, "SELECT body FROM salary_private.salary_artifacts"))
    assert b"NOT_LOADED_TOKEN" not in bodies
    columns = {
        row["column_name"]
        for row in _rows(
            engine,
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'salary_private' AND table_name = 'dknfl_salaries'
            """,
        )
    }
    assert "dk_id" in columns and "dff_player_id" not in columns and "gsis_id" not in columns
    indexes = {
        row["indexname"]
        for row in _rows(
            engine,
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'salary_private' AND tablename = 'dknfl_salaries'",
        )
    }
    assert {"dknfl_salaries_pkey", "ix_dknfl_salaries_status", "ix_dknfl_salaries_dk_id"} <= indexes
    assert _scalar(engine, "SELECT count(*) FROM dk_classic_salaries") == before
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dk_lobby_salaries") == 0


def test_at2_exact_bytes_and_duplicate_paths_share_bytes_only(database_url, engine, tmp_path):
    with engine.begin() as conn:
        _pair(conn, 2022, 1, date(2022, 9, 11))
    records = _two_players()
    records[0]["Name"] = 'Sam "Ace" Sample'
    root, manifest = _archive(
        tmp_path,
        [
            {"path": "raw/one.csv", "season": 2022, "week": 1, "rows": records, "bom": True, "crlf": True},
            {"path": "raw/two.csv", "season": 2022, "week": 1, "rows": records, "bom": True, "crlf": True},
        ],
    )
    body = (root / "raw/one.csv").read_bytes()
    assert _load(database_url, root, manifest) == 0
    artifacts = _rows(
        engine,
        """
        SELECT sha256, body FROM salary_private.salary_artifacts
        WHERE source = 'dknfl' AND artifact_kind = 'csv'
        """,
    )
    assert len(artifacts) == 1
    assert bytes(artifacts[0]["body"]) == body
    assert body.startswith(b"\xef\xbb\xbf") and b"\r\n" in body
    keys = {row["source_snapshot_key"] for row in _rows(engine, "SELECT source_snapshot_key FROM salary_private.salary_snapshots")}
    assert keys == {"raw/one.csv", "raw/two.csv"}
    observation = _rows(
        engine,
        """
        SELECT original_path, source_url, metadata, duration_ms, fetched_at, source_published_at
        FROM salary_private.salary_observations WHERE original_path = 'raw/one.csv'
        """,
    )[0]
    assert observation["source_url"] == SOURCE_URL
    assert observation["metadata"]["upstream_commit"] == "abc1234abc"
    assert observation["metadata"]["repository_path"] == "2022/Week1/DKSalaries.csv"
    assert observation["duration_ms"] is None
    assert observation["fetched_at"] is None
    assert observation["source_published_at"] is None
    ledger = _rows(engine, "SELECT raw_fields FROM salary_private.salary_source_rows ORDER BY row_number")
    assert ledger[0]["raw_fields"][2][1] == 'Sam "Ace" Sample'


def test_at3_blank_placeholders_stay_rejected(database_url, engine, tmp_path):
    with engine.begin() as conn:
        _pair(conn, 2022, 1, date(2022, 9, 11))
    blanks = [{column: "" if column != "AvgPointsPerGame" else "0" for column in HEADER} for _ in range(15)]
    root, manifest = _archive(
        tmp_path,
        [{"path": "raw/blanks.csv", "season": 2022, "week": 1, "rows": blanks + _two_players()}],
    )
    assert _load(database_url, root, manifest) == 0
    statuses = _rows(
        engine,
        "SELECT row_status, salary, dk_id FROM salary_private.dknfl_salaries ORDER BY row_number",
    )
    assert len(statuses) == 17
    assert sum(row["row_status"] == "rejected" for row in statuses) == 15
    assert [row["salary"] for row in statuses if row["row_status"] == "valid"] == [Decimal(5000), Decimal(6100)]
    assert all(row["salary"] is None and row["dk_id"] is None for row in statuses if row["row_status"] == "rejected")
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dknfl_salaries WHERE salary = 0") == 0


def test_at4_corrected_weeks_keep_original_paths(database_url, engine, tmp_path):
    with engine.begin() as conn:
        _pair(conn, 2021, 2, date(2021, 9, 19), prefix="w2")
        _game(conn, "tg1", 2023, 12, "GB", "DET", date(2023, 11, 23), "12:30")
        _game(conn, "tg2", 2023, 12, "WAS", "DAL", date(2023, 11, 23), "16:30")
        _pair(conn, 2024, 17, date(2024, 12, 25), prefix="xmas")
        _game(conn, "sat1", 2022, 16, "KC", "BUF", date(2022, 12, 24), "13:00")
    root, manifest = _archive(
        tmp_path,
        [
            {
                "path": "2022/Week2/DKSalaries-Week2.csv",
                "season": 2021,
                "week": 2,
                "date": "09/19/2021",
                "rows": _two_players("09/19/2021"),
            },
            {
                "path": "2023/WEEK11_5/DKSalaries.csv",
                "season": 2023,
                "week": 12,
                "date": "11/23/2023",
                "rows": [
                    _dk(**{"ID": "2001", "Game Info": _info("GB", "DET", "11/23/2023", "12:30PM"), "TeamAbbrev": "DET"}),
                    _dk(**{"ID": "2002", "Name": "Riley Sample", "Game Info": _info("WAS", "DAL", "11/23/2023", "04:30PM"), "TeamAbbrev": "DAL", "Roster Position": "WR/FLEX", "Position": "WR"}),
                ],
            },
            {
                "path": "2024/WEEK16/DKSalaries-christmas.csv",
                "season": 2024,
                "week": 17,
                "date": "12/25/2024",
                "rows": _two_players("12/25/2024"),
            },
        ],
    )
    assert _load(database_url, root, manifest) == 0
    stored = {
        row["source_snapshot_key"]: row
        for row in _rows(
            engine,
            "SELECT source_snapshot_key, season, week, season_type, games, draft_group_id FROM salary_private.salary_snapshots",
        )
    }
    assert stored["2022/Week2/DKSalaries-Week2.csv"]["season"] == 2021
    assert stored["2022/Week2/DKSalaries-Week2.csv"]["week"] == 2
    assert {game["game_id"] for game in stored["2023/WEEK11_5/DKSalaries.csv"]["games"]} == {"tg1", "tg2"}
    assert stored["2023/WEEK11_5/DKSalaries.csv"]["week"] == 12
    christmas = stored["2024/WEEK16/DKSalaries-christmas.csv"]
    assert christmas["week"] == 17
    assert "sat1" not in {game["game_id"] for game in christmas["games"]}
    assert all(row["draft_group_id"] is None for row in stored.values())


def test_at5_two_game_and_post_keep_unknown_rules(database_url, engine, tmp_path):
    with engine.begin() as conn:
        _pair(conn, 2023, 19, date(2024, 1, 14), season_type="POST", prefix="post")
        _pair(conn, 2022, 1, date(2022, 9, 12), prefix="mon")
    root, manifest = _archive(
        tmp_path,
        [
            {"path": "raw/monday.csv", "season": 2022, "week": 1, "date": "09/12/2022", "rows": _two_players("09/12/2022")},
            {"path": "raw/post.csv", "season": 2023, "week": 19, "date": "01/14/2024", "rows": _two_players("01/14/2024")},
        ],
    )
    assert _load(database_url, root, manifest) == 0
    rows = _rows(
        engine,
        """
        SELECT source_snapshot_key, season_type, draft_group_id, rules, source_pool_kind, metadata
        FROM salary_private.salary_snapshots ORDER BY source_snapshot_key
        """,
    )
    assert {row["source_snapshot_key"] for row in rows} == {"raw/monday.csv", "raw/post.csv"}
    post = next(row for row in rows if row["source_snapshot_key"] == "raw/post.csv")
    assert post["season_type"] == "POST"
    assert all(row["draft_group_id"] is None for row in rows)
    assert all(row["rules"]["roster_slots"] is None and row["rules"]["salary_cap"] is None for row in rows)
    assert all(row["source_pool_kind"] == "full_export" for row in rows)
    assert all(row["metadata"]["optimizer_ready"] is False for row in rows)


def test_at6_showdown_header_and_game_failures_keep_prior(database_url, engine, tmp_path):
    with engine.begin() as conn:
        _pair(conn, 2022, 1, date(2022, 9, 11))
    good, good_manifest = _archive(
        tmp_path / "good",
        [{"path": "raw/good.csv", "season": 2022, "week": 1, "rows": _two_players()}],
    )
    assert _load(database_url, good, good_manifest) == 0
    good_rows = _scalar(engine, "SELECT count(*) FROM salary_private.dknfl_salaries")
    cases = {
        "showdown": {
            "rows": [
                _dk(**{"Roster Position": "CPT", "Game Info": _info("BUF", "KC")}),
                _dk(**{"ID": "1002", "Roster Position": "FLEX", "Game Info": _info("BUF", "KC"), "TeamAbbrev": "BUF"}),
            ]
        },
        "single_game": {"rows": [_dk(), _dk(ID="1002", Name="Alex Sample", TeamAbbrev="BUF")]},
        "missing_core_header": {
            "header": [column for column in HEADER if column != "Salary"],
            "rows": [{key: value for key, value in _dk().items() if key != "Salary"}],
            "usable": 0,
        },
        "manifest_game_contradiction": {"week": 2, "rows": _two_players()},
        "game_evidence_missing": {
            "rows": [
                _dk(**{"Game Info": _info("NYJ", "NE")}),
                _dk(**{"ID": "1002", "Game Info": _info("SEA", "DEN"), "TeamAbbrev": "DEN"}),
            ]
        },
    }
    for reason, overrides in cases.items():
        spec = {"path": f"raw/{reason}.csv", "season": 2022, "week": 1, "rows": _two_players()}
        spec.update(overrides)
        root, manifest = _archive(tmp_path / reason, [spec])
        assert _load(database_url, root, manifest) == 1
        observed = _rows(
            engine,
            "SELECT reason_code, snapshot_id FROM salary_private.salary_observations WHERE original_path = :path",
            path=spec["path"],
        )[-1]
        assert observed["reason_code"] == reason
        assert observed["snapshot_id"] is None
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dknfl_salaries") == good_rows
    assert _scalar(
        engine,
        "SELECT count(*) FROM salary_private.salary_source_rows WHERE artifact_id = (SELECT artifact_id FROM salary_private.salary_observations WHERE original_path = 'raw/showdown.csv')",
    ) == 2


def test_at7_duplicate_ids_remain_non_ready(database_url, engine, tmp_path):
    with engine.begin() as conn:
        _pair(conn, 2022, 1, date(2022, 9, 11))
    rows = _two_players() + [
        _dk(ID="1001", Salary="4200", Name="Pat Sample"),
    ]
    root, manifest = _archive(tmp_path, [{"path": "raw/dup.csv", "season": 2022, "week": 1, "rows": rows}])
    assert _load(database_url, root, manifest) == 0
    dupes = _rows(
        engine,
        "SELECT reason_codes, salary FROM salary_private.dknfl_salaries WHERE dk_id = '1001' ORDER BY row_number",
    )
    assert len(dupes) == 2
    assert all("duplicate_dk_id" in row["reason_codes"] and "duplicate_conflict" in row["reason_codes"] for row in dupes)
    snapshot = _rows(engine, "SELECT metadata, source_pool_kind FROM salary_private.salary_snapshots")[0]
    assert snapshot["metadata"]["optimizer_ready"] is False
    assert snapshot["source_pool_kind"] == "full_export"
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dk_lobby_salaries") == 0


def test_at8_rerun_reuses_and_correction_appends(database_url, engine, tmp_path):
    with engine.begin() as conn:
        _pair(conn, 2022, 1, date(2022, 9, 11))
    spec = {"path": "raw/a.csv", "season": 2022, "week": 1, "rows": _two_players()}
    root, manifest = _archive(tmp_path, [spec])
    assert _load(database_url, root, manifest) == 0
    assert _load(database_url, root, manifest) == 0
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 1
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_observations WHERE source = 'dknfl'") == 2
    changed = _two_players()
    changed[0]["Salary"] = "7700"
    spec["rows"] = changed
    root, manifest = _archive(tmp_path, [spec])
    assert _load(database_url, root, manifest) == 0
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 2
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dknfl_salaries WHERE salary = 5000") == 1


def test_at9_neighbors_and_reconcile(database_url, engine, tmp_path, capsys):
    with engine.begin() as conn:
        _pair(conn, 2022, 1, date(2022, 9, 11), prefix="a")
        _pair(conn, 2022, 2, date(2022, 9, 18), prefix="b")
        _pair(conn, 2022, 3, date(2022, 9, 25), prefix="c")
    specs = []
    for week, day in ((1, "09/11/2022"), (2, "09/18/2022"), (3, "09/25/2022")):
        specs.append({"path": f"raw/w{week}.csv", "season": 2022, "week": week, "date": day, "rows": _two_players(day)})
    root, manifest = _archive(tmp_path, specs)
    assert _load(database_url, root, manifest, fault="normalized", fault_path="raw/w2.csv") == 1
    keys = {row["source_snapshot_key"] for row in _rows(engine, "SELECT source_snapshot_key FROM salary_private.salary_snapshots")}
    assert keys == {"raw/w1.csv", "raw/w3.csv"}
    failed = _rows(
        engine,
        "SELECT snapshot_id, reason_code FROM salary_private.salary_observations WHERE original_path = 'raw/w2.csv'",
    )[0]
    assert failed["snapshot_id"] is None and failed["reason_code"] == "injected_fault"
    root, manifest = _archive(
        tmp_path / "crash",
        [
            {"path": "raw/a.csv", "season": 2022, "week": 1, "rows": _two_players("09/11/2022")},
            {"path": "raw/b.csv", "season": 2022, "week": 2, "date": "09/18/2022", "rows": _two_players("09/18/2022")},
        ],
    )
    assert _load(database_url, root, manifest, fault="after_commit", fault_path="raw/b.csv") == 1
    statuses = [row["status"] for row in _rows(engine, "SELECT status FROM load_runs WHERE dataset = 'dknfl_salaries' AND season = 2022 ORDER BY id DESC LIMIT 2")]
    assert statuses == ["running", "succeeded"] or set(statuses) == {"running", "succeeded"}
    before = _scalar(engine, "SELECT count(*) FROM salary_private.dknfl_salaries")
    with engine.connect() as conn:
        reconcile(conn)
    assert _scalar(engine, "SELECT count(*) FROM load_runs WHERE dataset = 'dknfl_salaries' AND status = 'running'") == 0
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dknfl_salaries") == before
    capsys.readouterr()
    assert run("postgresql://seam@127.0.0.1:1/none", root, manifest) == 1
    assert capsys.readouterr().err.strip() == "database_unreachable"


def test_at10_boundaries_and_budget(database_url, engine, tmp_path, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network")))
    with engine.begin() as conn:
        _pair(conn, 2022, 1, date(2022, 9, 11))
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"OUTSIDE_TOKEN_zz")
    assert _load(database_url, tmp_path / "missing", tmp_path / "no-manifest.csv") == 1
    assert _rows(engine, "SELECT error FROM load_runs WHERE dataset = 'dknfl_salaries'")[-1]["error"] == "manifest_missing"
    root, manifest = _archive(
        tmp_path / "conflict",
        [{"path": "raw/a.csv", "season": 2022, "week": 1, "rows": [_dk(Name="UNREAD_TOKEN")], "conflict": True}],
    )
    assert _load(database_url, root, manifest) == 1
    assert _rows(engine, "SELECT error FROM load_runs ORDER BY id")[-1]["error"] == "manifest_conflict"
    link_root, link_manifest = _archive(
        tmp_path / "link",
        [{"path": "raw/a.csv", "season": 2022, "week": 1, "rows": _two_players()}],
    )
    target = link_root / "raw/a.csv"
    target.unlink()
    target.symlink_to(outside)
    assert _load(database_url, link_root, link_manifest) == 1
    assert _rows(engine, "SELECT error FROM load_runs ORDER BY id")[-1]["error"] == "unsafe_path"
    bad_root = tmp_path / "bad"
    bad_root.mkdir()
    row = {
        "path": "../outside.csv",
        "season": "2022",
        "week": "1",
        "rows": "1",
        "usable_salary_rows": "1",
        "source": "pureslurp/DKNFL",
        "source_url": SOURCE_URL,
        "format": "synthetic",
        "date": "09/11/2022",
        "unique_players_in_file": "1",
        "min_salary": "0",
        "max_salary": "0",
        "columns": "|".join(HEADER),
        "sha256": "ab" * 32,
        "quality_note": "synthetic",
    }
    manifest_path = bad_root / "MANIFEST.csv"
    with manifest_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)
    assert _load(database_url, bad_root, manifest_path) == 1
    root, manifest = _archive(
        tmp_path / "hash",
        [{"path": "raw/hash.csv", "season": 2022, "week": 1, "rows": _two_players(), "sha": "0" * 64}],
    )
    assert _load(database_url, root, manifest) == 1
    assert _rows(engine, "SELECT reason_code FROM salary_private.salary_observations WHERE original_path = 'raw/hash.csv'")[-1]["reason_code"] == "hash_mismatch"
    huge_root, huge_manifest = _archive(
        tmp_path / "huge",
        [{"path": "raw/huge.csv", "season": 2022, "week": 1, "body": b"x" * (OBJECT_LIMIT + 8), "rows": [], "row_count": 1, "usable": 1}],
    )
    before = _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots")
    assert _load(database_url, huge_root, huge_manifest) == 1
    obs = _rows(engine, "SELECT reason_code, metadata, snapshot_id FROM salary_private.salary_observations WHERE original_path = 'raw/huge.csv'")[0]
    assert obs["reason_code"] == "storage_guard_object" and obs["metadata"]["retained_artifact"] is False and obs["snapshot_id"] is None
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == before
    bodies = b"".join(bytes(row["body"]) for row in _rows(engine, "SELECT body FROM salary_private.salary_artifacts"))
    assert b"OUTSIDE_TOKEN_zz" not in bodies and b"UNREAD_TOKEN" not in bodies


def test_at11_grants_leave_other_sources(database_url, engine, tmp_path, monkeypatch):
    with engine.begin() as conn:
        _markers(conn)
        _pair(conn, 2022, 1, date(2022, 9, 11))
    root, manifest = _archive(tmp_path, [{"path": "raw/a.csv", "season": 2022, "week": 1, "rows": _two_players()}])
    assert _load(database_url, root, manifest) == 0
    web = "seam_web_f007"
    optimizer = "seam_opt_f007"
    monkeypatch.setenv("READONLY_ROLE", web)
    monkeypatch.setenv("OPTIMIZER_ROLE", optimizer)
    with engine.begin() as conn:
        conn.execute(text(f"DROP ROLE IF EXISTS {optimizer}"))
        conn.execute(text(f"DROP ROLE IF EXISTS {web}"))
        conn.execute(text(f"CREATE ROLE {web}"))
        conn.execute(text(f"CREATE ROLE {optimizer}"))
        conn.execute(text(f"GRANT {web} TO CURRENT_USER"))
        conn.execute(text(f"GRANT {optimizer} TO CURRENT_USER"))
        apply_readonly_grant(conn)
        apply_readonly_grant(conn)
    try:
        with engine.connect() as conn:
            conn.execute(text(f"SET ROLE {web}"))
            conn.execute(text("SELECT count(*) FROM dk_classic_salaries"))
            conn.execute(text("SELECT count(*) FROM teams"))
            for table in ("salary_private.dknfl_salaries", "salary_private.salary_artifacts", "dk_classic_slate"):
                with pytest.raises(DBAPIError):
                    conn.execute(text(f"SELECT count(*) FROM {table}"))
                conn.rollback()
                conn.execute(text(f"SET ROLE {web}"))
            conn.execute(text("RESET ROLE"))
            conn.commit()
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"DROP OWNED BY {optimizer}"))
            conn.execute(text(f"DROP OWNED BY {web}"))
            conn.execute(text(f"DROP ROLE IF EXISTS {optimizer}"))
            conn.execute(text(f"DROP ROLE IF EXISTS {web}"))
    from loader.migrate import migrate_production, upgrade_target

    monkeypatch.delenv("READONLY_ROLE", raising=False)
    monkeypatch.delenv("OPTIMIZER_ROLE", raising=False)
    assert upgrade_target(None, None) == "0003"
    assert upgrade_target("0005", None) == "0005"
    assert upgrade_target("0005", "true") == "head"
    admin = create_engine(database_url)
    name = "seam_f007_gate"
    previous = os.environ.get("DATABASE_URL")
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {name}"))
            conn.execute(text(f"CREATE DATABASE {name}"))
        gated = make_url(database_url).set(database=name).render_as_string(hide_password=False)
        os.environ["DATABASE_URL"] = gated
        command.upgrade(Config("alembic.ini"), "0005")
        assert migrate_production(gated, None) == "0005"
        check = create_engine(gated)
        with check.connect() as conn:
            assert conn.execute(text("SELECT to_regclass('salary_private.dknfl_salaries')")).scalar() is None
        check.dispose()
        assert migrate_production(gated, "true") == "head"
        check = create_engine(gated)
        with check.connect() as conn:
            from alembic.script import ScriptDirectory

            head_revision = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == head_revision
            assert conn.execute(text("SELECT to_regclass('salary_private.dknfl_salaries')")).scalar() is not None
        check.dispose()
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :name AND pid <> pg_backend_pid()"),
                {"name": name},
            )
            conn.execute(text(f"DROP DATABASE IF EXISTS {name}"))
        admin.dispose()


def test_empty_games_fail_closed(database_url, engine, tmp_path):
    assert _scalar(engine, "SELECT count(*) FROM games") == 0
    root, manifest = _archive(
        tmp_path,
        [{"path": "raw/empty-games.csv", "season": 2022, "week": 1, "rows": _two_players()}],
    )
    assert _load(database_url, root, manifest) == 1
    observed = _rows(
        engine,
        """
        SELECT reason_code, snapshot_id FROM salary_private.salary_observations
        WHERE original_path = 'raw/empty-games.csv'
        """,
    )[0]
    assert observed["reason_code"] == "game_evidence_missing"
    assert observed["snapshot_id"] is None
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dknfl_salaries") == 0
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_source_rows") == 2


def test_at12_attribution_and_scanner(database_url, engine, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("network")))
    with engine.begin() as conn:
        _pair(conn, 2022, 1, date(2022, 9, 11))
    root, manifest = _archive(
        tmp_path,
        [{"path": "raw/zzprivpathzz.csv", "season": 2022, "week": 1, "rows": [_two_players()[0] | {"Salary": "880011"}, _two_players()[1]]}],
    )
    assert _load(database_url, root, manifest) == 0
    captured = capsys.readouterr()
    assert ATTRIBUTION in captured.out
    assert "RotoGuru" not in captured.out and "dailyfantasyfuel" not in captured.out.lower()
    assert "880011" not in captured.out + captured.err
    assert "zzprivpathzz" not in captured.out + captured.err
    public = _rows(engine, "SELECT notes, source_url FROM load_runs WHERE dataset = 'dknfl_salaries'")[0]
    assert public["source_url"] == "dknfl_salaries"
    assert "880011" not in (public["notes"] or "")
    module = (ROOT / "loader" / "dknfl_archive.py").read_text()
    assert "urlopen" not in module and "httpx" not in module and "requests" not in module
    assert list((ROOT / ".github" / "workflows").glob("*dknfl*")) == []
    web = "\n".join(path.read_text() for path in (ROOT / "web").rglob("*.py"))
    assert "dknfl_salaries" not in web
    binary = shutil.which("gitleaks")
    assert binary
    scan = subprocess.run(
        [binary, "detect", "--source", str(ROOT), "--redact", "--no-banner", "--no-git"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert scan.returncode == 0, scan.stdout + scan.stderr
