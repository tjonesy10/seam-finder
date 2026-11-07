"""F006 acceptance tests. Fixtures are synthetic. No archive payloads."""

import csv
import gzip
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

from loader.dff_archive import ATTRIBUTION, parse_number, reconcile, run
from loader.grants import apply_readonly_grant
from loader.salary_private import OBJECT_LIMIT

ROOT = Path(__file__).parents[1]
CORE = [
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


def _rows(engine, sql, **params):
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(text(sql), params).mappings()]


def _scalar(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def _csv_bytes(header, records, *, bom=False, crlf=False):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n" if crlf else "\n")
    writer.writerow(header)
    for record in records:
        writer.writerow([record.get(column, "") for column in header])
    body = buffer.getvalue().encode()
    if bom:
        return b"\xef\xbb\xbf" + body
    return body


def _player(**overrides):
    row = {
        "start_date": "2022-09-11",
        "week": "1",
        "name": "Pat Sample",
        "pos": "QB",
        "team": "KC",
        "opp": "ARI",
        "loc": "@",
        "salary": "5000",
        "player_id": "SYN01",
        "ppg_proj": "10.5",
    }
    row.update(overrides)
    return row


def _archive(tmp, specs, *, findings=False, coverage=False):
    root = tmp / "archive"
    (root / "raw").mkdir(parents=True, exist_ok=True)
    (root / "evidence").mkdir(exist_ok=True)
    manifest_rows = []
    for spec in specs:
        header = spec.get("header", CORE)
        body = spec.get("body")
        if body is None:
            body = _csv_bytes(
                header,
                spec.get("rows", []),
                bom=spec.get("bom", False),
                crlf=spec.get("crlf", False),
            )
        relative = spec["path"]
        target = root / relative
        if ".." not in Path(relative).parts and not Path(relative).is_absolute():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        source = spec.get("source", "Daily Fantasy Fuel")
        season = spec["season"]
        week = spec["week"]
        if spec.get("companion", source == "Daily Fantasy Fuel") and source == "Daily Fantasy Fuel":
            html = spec.get("html", b"<html>synthetic dailyfantasyfuel</html>")
            gzip_path = root / f"evidence/dff-{season}-week{week:02d}.html.gz"
            gzip_path.parent.mkdir(parents=True, exist_ok=True)
            gzip_path.write_bytes(gzip.compress(html, mtime=0))
        digest = hashlib.sha256(body).hexdigest()
        if "sha" in spec:
            digest = spec["sha"]
        records = spec.get("rows", [])
        usable = spec.get("usable")
        if usable is None:
            usable = sum(1 for record in records if parse_number(str(record.get("salary", "")), 2, 10))
        manifest_rows.append(
            {
                "path": relative,
                "season": str(season),
                "week": str(week),
                "rows": str(spec.get("row_count", len(records))),
                "usable_salary_rows": str(usable),
                "source": source,
                "source_url": spec.get(
                    "source_url",
                    f"https://www.dailyfantasyfuel.com/nfl/projections/draftkings/{spec['date']}",
                ),
                "format": "synthetic",
                "date": spec["date"],
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
    if findings:
        (root / "FINDINGS.md").write_text("synthetic findings\n")
    if coverage:
        (root / "COVERAGE.csv").write_text("source,files\nsynthetic,1\n")
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
                :abbr, :abbr, :abbr, 'NFC', 'East', '1', '#000000', '#ffffff',
                CURRENT_TIMESTAMP
            )
            ON CONFLICT DO NOTHING
            """
        ),
        {"abbr": abbr},
    )


def _game(conn, game_id, season, week, away, home, gameday, season_type="REG"):
    for abbr in (away, home):
        _team(conn, abbr)
    conn.execute(
        text(
            """
            INSERT INTO games (
                game_id, season, game_type, season_type, week, gameday, weekday,
                away_team, home_team, location, loaded_at
            ) VALUES (
                :game_id, :season, :season_type, :season_type, :week, :gameday,
                'Sunday', :away, :home, 'Home', CURRENT_TIMESTAMP
            )
            """
        ),
        {
            "game_id": game_id,
            "season": season,
            "season_type": season_type,
            "week": week,
            "gameday": gameday,
            "away": away,
            "home": home,
        },
    )


def _markers(conn):
    conn.execute(
        text(
            """
            INSERT INTO dk_classic_salaries (
                season, week, rotoguru_gid, name_raw, pos_raw, team_raw, home_away,
                opponent_raw, dk_points, dk_salary, source_url, source_fetched_at,
                source_sha256, loaded_at
            ) VALUES (
                2022, 1, 1, 'Marker', 'QB', 'KC', 'H', 'ARI', 1, 5000,
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


def test_at1_only_dff_rows_and_contracts(database_url, engine, tmp_path):
    with engine.begin() as conn:
        _markers(conn)
    before = {
        "f003": _scalar(engine, "SELECT count(*) FROM dk_classic_salaries"),
        "f004": _scalar(engine, "SELECT count(*) FROM dk_classic_slate"),
        "lobby": _scalar(engine, "SELECT count(*) FROM salary_private.dk_lobby_salaries"),
    }
    root, manifest = _archive(
        tmp_path,
        [
            {
                "path": "raw/dff.csv",
                "season": 2022,
                "week": 1,
                "date": "2022-09-11",
                "rows": [_player()],
            },
            {
                "path": "raw/other.csv",
                "season": 2022,
                "week": 1,
                "date": "2022-09-11",
                "source": "pureslurp/DKNFL",
                "rows": [_player(name="NOT_LOADED_TOKEN")],
                "companion": False,
            },
        ],
    )
    assert _load(database_url, root, manifest) == 0
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dff_salaries") == 1
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_artifacts WHERE source = 'dknfl'") == 0
    bodies = _rows(engine, "SELECT body FROM salary_private.salary_artifacts")
    assert all(b"NOT_LOADED_TOKEN" not in bytes(row["body"]) for row in bodies)
    columns = {
        row["column_name"]
        for row in _rows(
            engine,
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'salary_private' AND table_name = 'dff_salaries'
            """,
        )
    }
    assert "dff_player_id" in columns
    assert "dk_id" not in columns
    assert "gsis_id" not in columns
    indexes = {
        row["indexname"]
        for row in _rows(
            engine,
            """
            SELECT indexname FROM pg_indexes
            WHERE schemaname = 'salary_private' AND tablename = 'dff_salaries'
            """,
        )
    }
    assert {"dff_salaries_pkey", "ix_dff_salaries_status", "ix_dff_salaries_player"} <= indexes
    assert _scalar(engine, "SELECT count(*) FROM dk_classic_salaries") == before["f003"]
    assert _scalar(engine, "SELECT count(*) FROM dk_classic_slate") == before["f004"]
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dk_lobby_salaries") == before["lobby"]
    assert _scalar(engine, "SELECT count(*) FROM dk_classic_salaries WHERE rotoguru_gid = 1") == 1


def test_at2_exact_bytes_order_and_blank_row(database_url, engine, tmp_path):
    header = CORE + ["note"]
    records = [
        _player(name='Sam "Ace" Sample', note="extra"),
        {column: "" for column in header},
    ]
    root, manifest = _archive(
        tmp_path,
        [
            {
                "path": "raw/quoted.csv",
                "season": 2022,
                "week": 1,
                "date": "2022-09-11",
                "header": header,
                "rows": records,
                "bom": True,
                "crlf": True,
            }
        ],
        findings=True,
        coverage=True,
    )
    csv_body = (root / "raw/quoted.csv").read_bytes()
    gzip_body = (root / "evidence/dff-2022-week01.html.gz").read_bytes()
    manifest_body = manifest.read_bytes()
    assert _load(database_url, root, manifest) == 0
    stored = {
        row["artifact_kind"]: bytes(row["body"])
        for row in _rows(
            engine,
            """
            SELECT artifact_kind, body FROM salary_private.salary_artifacts
            WHERE source IN ('dff', 'control')
            """,
        )
    }
    assert stored["csv"] == csv_body
    assert stored["html_gzip"] == gzip_body
    assert stored["manifest"] in {manifest_body, (root / "FINDINGS.md").read_bytes()}
    control = _rows(
        engine,
        "SELECT body FROM salary_private.salary_artifacts WHERE source = 'control' ORDER BY artifact_id",
    )
    assert manifest_body in {bytes(row["body"]) for row in control}
    ledger = _rows(
        engine,
        """
        SELECT row_number, raw_fields, parse_status
        FROM salary_private.salary_source_rows
        ORDER BY row_number
        """,
    )
    assert [row["row_number"] for row in ledger] == [1, 2]
    assert ledger[0]["raw_fields"][0] == ["start_date", "2022-09-11"]
    assert ["note", "extra"] in ledger[0]["raw_fields"]
    assert ledger[0]["raw_fields"][2][1] == 'Sam "Ace" Sample'
    assert ledger[1]["parse_status"] == "rejected"
    assert b"\r\n" in csv_body and csv_body.startswith(b"\xef\xbb\xbf")
    observation = _rows(
        engine,
        """
        SELECT duration_ms, fetched_at, source_published_at, original_path, source_url
        FROM salary_private.salary_observations
        WHERE source = 'dff'
        """,
    )[0]
    assert observation["duration_ms"] is None
    assert observation["fetched_at"] is None
    assert observation["source_published_at"] is None
    assert observation["original_path"] == "raw/quoted.csv"
    assert observation["source_url"].startswith("https://www.dailyfantasyfuel.com/")


def test_at3_january_season_comes_from_manifest_not_path(database_url, engine, tmp_path):
    with engine.begin() as conn:
        _game(conn, "2025_18_BUF_NE", 2025, 18, "BUF", "NE", date(2026, 1, 4))
    root, manifest = _archive(
        tmp_path,
        [
            {
                "path": "raw/2026-mislabeled.csv",
                "season": 2025,
                "week": 18,
                "date": "2026-01-04",
                "rows": [_player(start_date="2026-01-04", week="18", team="BUF", opp="NE")],
            }
        ],
    )
    assert _load(database_url, root, manifest) == 0
    snapshot = _rows(
        engine,
        """
        SELECT season, week, season_type, source_snapshot_key, draft_group_id, source_pool_kind
        FROM salary_private.salary_snapshots
        """,
    )[0]
    assert snapshot["season"] == 2025
    assert snapshot["week"] == 18
    assert snapshot["season_type"] == "REG"
    assert snapshot["source_snapshot_key"] == "raw/2026-mislabeled.csv"
    assert snapshot["draft_group_id"] is None
    assert snapshot["source_pool_kind"] == "subset"


def test_at4_file_failures_keep_evidence_and_prior_success(database_url, engine, tmp_path):
    good_root, good_manifest = _archive(
        tmp_path / "good",
        [{"path": "raw/good.csv", "season": 2022, "week": 1, "date": "2022-09-11", "rows": [_player()]}],
    )
    assert _load(database_url, good_root, good_manifest) == 0
    good_rows = _scalar(engine, "SELECT count(*) FROM salary_private.dff_salaries")
    cases = {
        "hash_mismatch": {"sha": "0" * 64},
        "count_mismatch": {"row_count": 99},
        "missing_core_header": {
            "header": [column for column in CORE if column != "salary"],
            "rows": [{key: value for key, value in _player().items() if key != "salary"}],
        },
        "column_schema": {
            "header": CORE + ["note"],
            "manifest_columns": CORE,
            "rows": [_player(note="x")],
        },
        "row_date_contradiction": {
            "rows": [_player(), _player(player_id="SYN02", start_date="2022-09-12")]
        },
        "row_week_contradiction": {"rows": [_player(), _player(player_id="SYN02", week="9")]},
        "missing_companion": {"companion": False},
        "zero_valid_rows": {"rows": [_player(salary="nope")], "usable": 0},
        "not_csv": {"body": b"<html>challenge</html>", "rows": [], "usable": 0, "row_count": 0},
    }
    for reason, overrides in cases.items():
        spec = {
            "path": f"raw/{reason}.csv",
            "season": 2022,
            "week": 1,
            "date": "2022-09-11",
            "rows": [_player()],
        }
        spec.update(overrides)
        root, manifest = _archive(tmp_path / reason, [spec])
        assert _load(database_url, root, manifest) == 1
        observed = _rows(
            engine,
            """
            SELECT reason_code, snapshot_id FROM salary_private.salary_observations
            WHERE original_path = :path
            """,
            path=spec["path"],
        )
        assert observed[-1]["reason_code"] == reason
        assert observed[-1]["snapshot_id"] is None
    with engine.begin() as conn:
        _game(conn, "2022_01_KC_ARI_WRONG", 2022, 2, "KC", "ARI", date(2022, 9, 11))
    root, manifest = _archive(
        tmp_path / "game",
        [{"path": "raw/game.csv", "season": 2022, "week": 1, "date": "2022-09-11", "rows": [_player()]}],
    )
    assert _load(database_url, root, manifest) == 1
    assert (
        _rows(
            engine,
            """
            SELECT reason_code, snapshot_id FROM salary_private.salary_observations
            WHERE original_path = 'raw/game.csv'
            """,
        )[-1]["snapshot_id"]
        is None
    )
    assert _scalar(
        engine,
        """
        SELECT count(*) FROM salary_private.dff_salaries
        WHERE snapshot_id IN (
            SELECT snapshot_id FROM salary_private.salary_snapshots
            WHERE source_snapshot_key = 'raw/good.csv'
        )
        """,
    ) == good_rows
    assert _scalar(
        engine,
        "SELECT count(*) FROM salary_private.salary_artifacts WHERE source = 'dff' AND sha256 = :sha",
        sha=hashlib.sha256((tmp_path / "hash_mismatch/archive/raw/hash_mismatch.csv").read_bytes()).hexdigest(),
    ) == 1


def test_at5_rejected_salary_stays_non_ready_subset(database_url, engine, tmp_path):
    root, manifest = _archive(
        tmp_path,
        [
            {
                "path": "raw/mixed.csv",
                "season": 2022,
                "week": 1,
                "date": "2022-09-11",
                "rows": [_player(ppg_proj="12.25"), _player(player_id="SYN02", salary="nope")],
            }
        ],
    )
    assert _load(database_url, root, manifest) == 0
    salaries = _rows(
        engine,
        """
        SELECT row_status, salary, dff_player_id, ppg_proj
        FROM salary_private.dff_salaries
        ORDER BY row_number
        """,
    )
    assert salaries[0]["row_status"] == "valid"
    assert salaries[0]["dff_player_id"] == "SYN01"
    assert salaries[0]["ppg_proj"] == Decimal("12.25")
    assert salaries[1]["row_status"] == "rejected"
    assert salaries[1]["salary"] is None
    ledger = _rows(
        engine,
        "SELECT raw_fields FROM salary_private.salary_source_rows ORDER BY row_number",
    )
    assert ["salary", "nope"] in ledger[1]["raw_fields"]
    snapshot = _rows(
        engine,
        "SELECT source_pool_kind, metadata, draft_group_id FROM salary_private.salary_snapshots",
    )[0]
    assert snapshot["source_pool_kind"] == "subset"
    assert snapshot["draft_group_id"] is None
    assert snapshot["metadata"]["optimizer_ready"] is False
    assert snapshot["metadata"]["pool_ready"] is False
    assert snapshot["metadata"]["artifact_role"] == "html_row_extraction"
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dk_lobby_salaries") == 0


def test_at6_christmas_subset_keeps_duplicates_and_skips_saturday(database_url, engine, tmp_path):
    with engine.begin() as conn:
        _game(conn, "2022_16_GB_MIA", 2022, 16, "GB", "MIA", date(2022, 12, 25))
        _game(conn, "2022_16_TB_ARI", 2022, 16, "TB", "ARI", date(2022, 12, 25))
        _game(conn, "2022_16_DEN_LAR", 2022, 16, "DEN", "LAR", date(2022, 12, 25))
        _game(conn, "2022_16_KC_BUF_SAT", 2022, 16, "KC", "BUF", date(2022, 12, 24))
    rows = [
        _player(start_date="2022-12-25", week="16", team="MIA", opp="GB", loc="vs", player_id="DUP"),
        _player(start_date="2022-12-25", week="16", team="MIA", opp="GB", loc="vs", player_id="DUP", salary="4200"),
        _player(start_date="2022-12-25", week="16", team="TB", opp="ARI", loc="@", player_id="SYN02"),
        _player(start_date="2022-12-25", week="16", team="DEN", opp="LAR", loc="@", player_id="SYN03"),
    ]
    root, manifest = _archive(
        tmp_path,
        [{"path": "raw/christmas.csv", "season": 2022, "week": 16, "date": "2022-12-25", "rows": rows}],
    )
    assert _load(database_url, root, manifest) == 0
    snapshot = _rows(engine, "SELECT games, draft_group_id, source_pool_kind FROM salary_private.salary_snapshots")[0]
    game_ids = {game["game_id"] for game in snapshot["games"]}
    assert game_ids == {"2022_16_GB_MIA", "2022_16_TB_ARI", "2022_16_DEN_LAR"}
    assert "2022_16_KC_BUF_SAT" not in game_ids
    assert snapshot["draft_group_id"] is None
    assert snapshot["source_pool_kind"] == "subset"
    dupes = _rows(
        engine,
        """
        SELECT reason_codes FROM salary_private.dff_salaries
        WHERE dff_player_id = 'DUP'
        ORDER BY row_number
        """,
    )
    assert len(dupes) == 2
    assert all("duplicate_vendor_id" in row["reason_codes"] for row in dupes)
    assert all("duplicate_conflict" in row["reason_codes"] for row in dupes)


def test_at7_rerun_reuses_and_correction_appends(database_url, engine, tmp_path):
    spec = {
        "path": "raw/a.csv",
        "season": 2022,
        "week": 1,
        "date": "2022-09-11",
        "rows": [_player(salary="5000")],
    }
    root, manifest = _archive(tmp_path, [spec])
    assert _load(database_url, root, manifest) == 0
    assert _load(database_url, root, manifest) == 0
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 1
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_observations WHERE source = 'dff'") == 2
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dff_salaries") == 1
    spec["rows"] = [_player(salary="6100")]
    root, manifest = _archive(tmp_path, [spec])
    assert _load(database_url, root, manifest) == 0
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 2
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dff_salaries WHERE salary = 5000") == 1
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dff_salaries WHERE salary = 6100") == 1
    corrected = (root / "raw/a.csv").read_bytes()
    (root / "raw/b.csv").write_bytes(corrected)
    spec_b = dict(spec)
    spec_b["path"] = "raw/b.csv"
    root, manifest = _archive(tmp_path, [spec, spec_b])
    (root / "raw/a.csv").write_bytes(corrected)
    (root / "raw/b.csv").write_bytes(corrected)
    before_artifacts = _scalar(
        engine, "SELECT count(*) FROM salary_private.salary_artifacts WHERE source = 'dff' AND artifact_kind = 'csv'"
    )
    assert _load(database_url, root, manifest) == 0
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 3
    assert (
        _scalar(
            engine,
            "SELECT count(*) FROM salary_private.salary_artifacts WHERE source = 'dff' AND artifact_kind = 'csv'",
        )
        == before_artifacts
    )
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dff_salaries WHERE salary = 5000") == 1


def test_at8_neighbor_files_commit_when_middle_publish_rolls_back(database_url, engine, tmp_path):
    specs = []
    for week, name in ((1, "raw/a.csv"), (2, "raw/b.csv"), (3, "raw/c.csv")):
        specs.append(
            {
                "path": name,
                "season": 2022,
                "week": week,
                "date": "2022-09-11",
                "rows": [_player(player_id=f"SYN{week}", week=str(week))],
            }
        )
    root, manifest = _archive(tmp_path, specs)
    assert _load(database_url, root, manifest, fault="normalized", fault_path="raw/b.csv") == 1
    keys = {
        row["source_snapshot_key"]
        for row in _rows(engine, "SELECT source_snapshot_key FROM salary_private.salary_snapshots")
    }
    assert keys == {"raw/a.csv", "raw/c.csv"}
    failed = _rows(
        engine,
        """
        SELECT snapshot_id, reason_code FROM salary_private.salary_observations
        WHERE original_path = 'raw/b.csv'
        """,
    )[0]
    assert failed["snapshot_id"] is None
    assert failed["reason_code"] == "injected_fault"
    assert _scalar(
        engine,
        """
        SELECT count(*) FROM salary_private.salary_source_rows
        WHERE artifact_id = (
            SELECT artifact_id FROM salary_private.salary_observations
            WHERE original_path = 'raw/b.csv'
        )
        """,
    ) == 1


def test_at9_reconcile_after_commit_and_unreachable_database(database_url, engine, tmp_path, capsys):
    root, manifest = _archive(
        tmp_path,
        [
            {"path": "raw/a.csv", "season": 2022, "week": 1, "date": "2022-09-11", "rows": [_player()]},
            {
                "path": "raw/b.csv",
                "season": 2022,
                "week": 2,
                "date": "2022-09-18",
                "rows": [_player(player_id="SYN02", start_date="2022-09-18", week="2")],
            },
        ],
    )
    assert _load(database_url, root, manifest, fault="after_commit", fault_path="raw/b.csv") == 1
    running = _rows(
        engine,
        """
        SELECT status FROM load_runs
        WHERE dataset = 'dff_salaries' AND season = 2022
        ORDER BY id
        """,
    )
    assert [row["status"] for row in running] == ["succeeded", "running"]
    before = _scalar(engine, "SELECT count(*) FROM salary_private.dff_salaries")
    with engine.connect() as conn:
        reconcile(conn)
    assert _scalar(
        engine,
        "SELECT count(*) FROM load_runs WHERE dataset = 'dff_salaries' AND status = 'running'",
    ) == 0
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dff_salaries") == before
    assert _load(database_url, root, manifest) == 0
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == 2
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dff_salaries") == before
    capsys.readouterr()
    assert run("postgresql://seam@127.0.0.1:1/none", root, manifest) == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == "database_unreachable"
    assert "succeeded" not in captured.out
    assert _scalar(engine, "SELECT count(*) FROM salary_private.dff_salaries") == before


def test_at10_manifest_and_path_boundaries(database_url, engine, tmp_path, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network")))
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"OUTSIDE_TOKEN_zz")
    missing = tmp_path / "missing.csv"
    assert _load(database_url, tmp_path / "empty", missing) == 1
    assert _rows(engine, "SELECT error FROM load_runs WHERE dataset = 'dff_salaries'")[-1]["error"] == "manifest_missing"
    root, manifest = _archive(
        tmp_path / "conflict",
        [
            {
                "path": "raw/a.csv",
                "season": 2022,
                "week": 1,
                "date": "2022-09-11",
                "rows": [_player(name="UNREAD_TOKEN")],
                "conflict": True,
            }
        ],
    )
    assert _load(database_url, root, manifest) == 1
    assert _rows(engine, "SELECT error FROM load_runs ORDER BY id")[-1]["error"] == "manifest_conflict"
    assert all(b"UNREAD_TOKEN" not in bytes(row["body"]) for row in _rows(engine, "SELECT body FROM salary_private.salary_artifacts"))
    link_root, link_manifest = _archive(
        tmp_path / "link",
        [{"path": "raw/a.csv", "season": 2022, "week": 1, "date": "2022-09-11", "rows": [_player()]}],
    )
    target = link_root / "raw/a.csv"
    target.unlink()
    target.symlink_to(outside)
    assert _load(database_url, link_root, link_manifest) == 1
    assert _rows(engine, "SELECT error FROM load_runs ORDER BY id")[-1]["error"] == "unsafe_path"
    escape_root = tmp_path / "escape" / "archive"
    escape_root.mkdir(parents=True)
    rows = [
        {
            "path": "../outside.csv",
            "season": "2022",
            "week": "1",
            "rows": "1",
            "usable_salary_rows": "1",
            "source": "Daily Fantasy Fuel",
            "source_url": "https://www.dailyfantasyfuel.com/nfl/projections/draftkings/2022-09-11",
            "format": "synthetic",
            "date": "2022-09-11",
            "unique_players_in_file": "1",
            "min_salary": "0",
            "max_salary": "0",
            "columns": "|".join(CORE),
            "sha256": "ab" * 32,
            "quality_note": "synthetic",
        },
        {
            "path": str(outside),
            "season": "2022",
            "week": "1",
            "rows": "1",
            "usable_salary_rows": "1",
            "source": "Daily Fantasy Fuel",
            "source_url": "https://www.dailyfantasyfuel.com/nfl/projections/draftkings/2022-09-11",
            "format": "synthetic",
            "date": "2022-09-11",
            "unique_players_in_file": "1",
            "min_salary": "0",
            "max_salary": "0",
            "columns": "|".join(CORE),
            "sha256": "cd" * 32,
            "quality_note": "synthetic",
        },
    ]
    for index, row in enumerate(rows):
        manifest_path = escape_root / f"MANIFEST{index}.csv"
        with manifest_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerow(row)
        assert _load(database_url, escape_root, manifest_path) == 1
        assert _rows(engine, "SELECT error FROM load_runs ORDER BY id")[-1]["error"] == "unsafe_path"
    bodies = b"".join(bytes(row["body"]) for row in _rows(engine, "SELECT body FROM salary_private.salary_artifacts"))
    assert b"OUTSIDE_TOKEN_zz" not in bodies


def test_at11_grants_guards_and_gate(database_url, engine, tmp_path, monkeypatch):
    with engine.begin() as conn:
        _markers(conn)
    root, manifest = _archive(
        tmp_path / "good",
        [{"path": "raw/a.csv", "season": 2022, "week": 1, "date": "2022-09-11", "rows": [_player()]}],
    )
    assert _load(database_url, root, manifest) == 0
    before = _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots")
    huge = tmp_path / "huge"
    root, manifest = _archive(
        huge,
        [
            {
                "path": "raw/huge.csv",
                "season": 2022,
                "week": 3,
                "date": "2022-09-25",
                "body": b"x" * (OBJECT_LIMIT + 20),
                "rows": [],
                "row_count": 1,
                "usable": 1,
            }
        ],
    )
    assert _load(database_url, root, manifest) == 1
    obs = _rows(
        engine,
        """
        SELECT reason_code, metadata, snapshot_id
        FROM salary_private.salary_observations
        WHERE original_path = 'raw/huge.csv'
        """,
    )[0]
    assert obs["reason_code"] == "storage_guard_object"
    assert obs["metadata"]["truncated"] is True
    assert obs["metadata"]["retained_artifact"] is False
    assert obs["snapshot_id"] is None
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots") == before
    web = "seam_web_f006"
    optimizer = "seam_opt_f006"
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
            for table in (
                "salary_private.dff_salaries",
                "salary_private.salary_artifacts",
                "dk_classic_slate",
            ):
                with pytest.raises(DBAPIError):
                    conn.execute(text(f"SELECT count(*) FROM {table}"))
                conn.rollback()
                conn.execute(text(f"SET ROLE {web}"))
            conn.execute(text("RESET ROLE"))
            conn.commit()
        assert _load(database_url, tmp_path / "good/archive", tmp_path / "good/archive/MANIFEST.csv") == 0
        with engine.begin() as conn:
            apply_readonly_grant(conn)
        with engine.connect() as conn:
            conn.execute(text(f"SET ROLE {web}"))
            with pytest.raises(DBAPIError):
                conn.execute(text("SELECT count(*) FROM salary_private.dff_salaries"))
            conn.rollback()
            conn.execute(text("RESET ROLE"))
            conn.commit()
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"DROP OWNED BY {optimizer}"))
            conn.execute(text(f"DROP OWNED BY {web}"))
            conn.execute(text(f"DROP ROLE IF EXISTS {optimizer}"))
            conn.execute(text(f"DROP ROLE IF EXISTS {web}"))
    from loader.migrate import current_revision, migrate_production, upgrade_target

    monkeypatch.delenv("READONLY_ROLE", raising=False)
    monkeypatch.delenv("OPTIMIZER_ROLE", raising=False)
    assert upgrade_target(None, None) == "0003"
    assert upgrade_target("0005", None) == "0005"
    assert upgrade_target("0005", "true") == "head"
    assert upgrade_target("0003", "TRUE") == "0003"
    admin = create_engine(database_url)
    name = "seam_f006_gate"
    previous = os.environ.get("DATABASE_URL")
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {name}"))
            conn.execute(text(f"CREATE DATABASE {name}"))
        gated = make_url(database_url).set(database=name).render_as_string(hide_password=False)
        os.environ["DATABASE_URL"] = gated
        command.upgrade(Config("alembic.ini"), "0005")
        assert current_revision(gated) == "0005"
        assert migrate_production(gated, None) == "0005"
        check = create_engine(gated)
        with check.connect() as conn:
            assert conn.execute(text("SELECT to_regclass('salary_private.dff_salaries')")).scalar() is None
            assert conn.execute(text("SELECT to_regclass('salary_private.dk_lobby_salaries')")).scalar() is not None
        check.dispose()
        assert migrate_production(gated, "true") == "head"
        check = create_engine(gated)
        with check.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0006"
            assert conn.execute(text("SELECT to_regclass('salary_private.dff_salaries')")).scalar() is not None
        check.dispose()
        assert migrate_production(gated, None) == "0006"
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            conn.execute(text(f"DROP DATABASE IF EXISTS {name}"))
        admin.dispose()


def test_at12_logs_attribution_and_scanner(database_url, engine, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network")))
    root, manifest = _archive(
        tmp_path,
        [
            {
                "path": "raw/zzprivpathzz.csv",
                "season": 2022,
                "week": 1,
                "date": "2022-09-11",
                "rows": [_player(salary="880011")],
            }
        ],
    )
    assert _load(database_url, root, manifest) == 0
    captured = capsys.readouterr()
    assert ATTRIBUTION in captured.out
    assert "RotoGuru" not in captured.out
    assert "pureslurp" not in captured.out
    assert "880011" not in captured.out + captured.err
    assert "zzprivpathzz" not in captured.out + captured.err
    public = _rows(
        engine,
        "SELECT notes, error, source_url FROM load_runs WHERE dataset = 'dff_salaries'",
    )[0]
    assert public["source_url"] == "dff_salaries"
    assert "880011" not in (public["notes"] or "")
    assert "zzprivpathzz" not in (public["notes"] or "")
    module = (ROOT / "loader" / "dff_archive.py").read_text()
    assert "urlopen" not in module
    assert "httpx" not in module
    assert "requests" not in module
    workflows = list((ROOT / ".github" / "workflows").glob("*dff*"))
    assert workflows == []
    web = "\n".join(path.read_text() for path in (ROOT / "web").rglob("*.py"))
    assert "dff_salaries" not in web
    binary = shutil.which("gitleaks")
    assert binary, "gitleaks is not installed"
    scan = subprocess.run(
        [binary, "detect", "--source", str(ROOT), "--redact", "--no-banner", "--no-git"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert scan.returncode == 0, scan.stdout + scan.stderr


def test_corrected_manifest_reuses_intrinsic_ledger(database_url, engine, tmp_path):
    player = _player()
    body = _csv_bytes(CORE, [player])
    wrong, wrong_manifest = _archive(
        tmp_path / "wrong",
        [
            {
                "path": "raw/same.csv",
                "season": 2022,
                "week": 9,
                "date": "2022-09-11",
                "body": body,
                "rows": [player],
            }
        ],
    )
    assert _load(database_url, wrong, wrong_manifest) == 1
    failed = _rows(
        engine,
        """
        SELECT reason_code, snapshot_id FROM salary_private.salary_observations
        WHERE original_path = 'raw/same.csv'
        """,
    )
    assert failed[-1]["reason_code"] == "row_week_contradiction"
    assert failed[-1]["snapshot_id"] is None
    ledger = _rows(
        engine,
        """
        SELECT reason_codes FROM salary_private.salary_source_rows
        WHERE parser_version = 'f006.1'
        """,
    )
    assert ledger
    assert all("row_week_contradiction" not in codes for codes in (row["reason_codes"] for row in ledger))
    before = _scalar(engine, "SELECT count(*) FROM salary_private.salary_source_rows")
    corrected, corrected_manifest = _archive(
        tmp_path / "corrected",
        [
            {
                "path": "raw/same.csv",
                "season": 2022,
                "week": 1,
                "date": "2022-09-11",
                "body": body,
                "rows": [player],
            }
        ],
    )
    assert _load(database_url, corrected, corrected_manifest) == 0
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_source_rows") == before
    assert _scalar(engine, "SELECT count(*) FROM salary_private.salary_snapshots WHERE source = 'dff'") == 1
    retained = _rows(
        engine,
        """
        SELECT reason_code, snapshot_id FROM salary_private.salary_observations
        WHERE original_path = 'raw/same.csv'
        ORDER BY loaded_at
        """,
    )
    assert retained[0]["snapshot_id"] is None
    assert retained[-1]["snapshot_id"] is not None
