import csv
import hashlib
import io
import json
import shutil
import subprocess
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from loader.dk_slate import (
    REQUIRED,
    fetch_staged_artifact,
    main,
    parse_dk_csv,
)
from loader.source import LoadError
from web.resources import API_ENDPOINTS, PAGE_LINKS, RESOURCES

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "dk_slate" / "classic.csv"
WORKFLOW = ROOT / ".github" / "workflows" / "dk-classic-slate.yml"
PAT = "00-0001001"
PAT_LATEST = "00-0001002"
FALLBACK = "00-0001004"
GAME_NE = "2026_10_NE_KC"
GAME_DAL = "2026_10_DAL_PHI"
G_NE = "NE@KC 10/12/2026 04:20PM ET"
G_DAL = "DAL@PHI 10/12/2026 01:00PM ET"
COLUMNS = list(REQUIRED)
BANNED_HOST = "draftkings.com"

STAT_INSERT = """
INSERT INTO player_week_stats (
    gsis_id, season, week, season_type, game_id, team, opponent_team, position,
    completions, attempts, passing_yards, passing_tds, passing_interceptions,
    sacks_suffered, sack_fumbles_lost, passing_2pt_conversions,
    carries, rushing_yards, rushing_tds, rushing_fumbles_lost, rushing_2pt_conversions,
    receptions, targets, receiving_yards, receiving_tds,
    receiving_fumbles_lost, receiving_2pt_conversions, special_teams_tds,
    fantasy_points, fantasy_points_ppr, loaded_at
) VALUES (
    :gsis_id, :season, :week, 'REG', :game_id, :team, :opponent, :position,
    0, 0, 0, 0, 0,
    0, 0, 0,
    0, 0, 0, 0, 0,
    0, 0, 0, 0,
    0, 0, 0,
    1.00, 1.00, CURRENT_TIMESTAMP
)
"""


def _load(database_url, path, season=2026, week=10, trigger="local"):
    from loader.dk_slate import run_dk_slate

    return run_dk_slate(
        database_url=database_url,
        csv_path=Path(path),
        season=season,
        week=week,
        trigger=trigger,
    )


def _rows(engine):
    with engine.connect() as conn:
        found = conn.execute(
            text("SELECT * FROM dk_classic_slate ORDER BY season, week, dk_id")
        ).mappings()
        return [dict(row) for row in found]


def _runs(engine):
    with engine.connect() as conn:
        found = conn.execute(
            text("SELECT * FROM load_runs WHERE dataset = 'dk_classic_slate' ORDER BY id")
        ).mappings()
        return [dict(row) for row in found]


def _stable(rows):
    hidden = {"loaded_at", "source_loaded_at"}
    return [{key: value for key, value in row.items() if key not in hidden} for row in rows]


def _one(engine, dk_id, week=10):
    return next(row for row in _rows(engine) if row["dk_id"] == dk_id and row["week"] == week)


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


def _player(conn, gsis_id, display, position, latest_team):
    conn.execute(
        text(
            """
            INSERT INTO players (gsis_id, display_name, position, latest_team, is_stub, loaded_at)
            VALUES (:gsis_id, :display, :position, :latest_team, false, CURRENT_TIMESTAMP)
            """
        ),
        {
            "gsis_id": gsis_id,
            "display": display,
            "position": position,
            "latest_team": latest_team,
        },
    )


def _game(conn, game_id, season, week, away, home):
    conn.execute(
        text(
            """
            INSERT INTO games (
                game_id, season, game_type, season_type, week, gameday, weekday,
                away_team, home_team, location, loaded_at
            ) VALUES (
                :game_id, :season, 'REG', 'REG', :week, '2026-10-12',
                'Monday', :away, :home, 'Home', CURRENT_TIMESTAMP
            )
            """
        ),
        {"game_id": game_id, "season": season, "week": week, "away": away, "home": home},
    )


def _stat(conn, gsis_id, season, week, game_id, team, opponent, position):
    conn.execute(
        text(STAT_INSERT),
        {
            "gsis_id": gsis_id,
            "season": season,
            "week": week,
            "game_id": game_id,
            "team": team,
            "opponent": opponent,
            "position": position,
        },
    )


def _seed(conn):
    for abbr in ("NE", "KC", "DAL", "PHI"):
        _team(conn, abbr)
    _player(conn, PAT, "Pat Sample", "QB", "KC")
    _player(conn, PAT_LATEST, "Pat Sample", "QB", "NE")
    _player(conn, FALLBACK, "Fallback Sample", "RB", "DAL")
    _game(conn, GAME_NE, 2026, 10, "NE", "KC")
    _game(conn, GAME_DAL, 2026, 10, "DAL", "PHI")
    _stat(conn, PAT, 2026, 10, GAME_NE, "NE", "KC", "QB")


def _prepare(engine):
    with engine.begin() as conn:
        _seed(conn)


def _person(dk_id, name, position, roster, salary, team, game, avg=""):
    return {
        "Position": position,
        "Name + ID": f"{name} ({dk_id})",
        "Name": name,
        "ID": str(dk_id),
        "Roster Position": roster,
        "Salary": str(salary),
        "Game Info": game,
        "TeamAbbrev": team,
        "AvgPointsPerGame": str(avg),
    }


def _write(path: Path, rows: list[dict], columns: list[str] | None = None) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns or COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def test_at1_parse_fixture_salary_and_id(database_url, engine):
    header = FIXTURE.read_text().splitlines()[0].split(",")
    for column in REQUIRED:
        assert column in header
    assert "Ignored" in header
    parsed = parse_dk_csv(FIXTURE.read_bytes())
    pat = next(row for row in parsed if row.dk_id == "1001")
    assert pat.name_raw == "Pat Sample"
    assert pat.salary == Decimal("7000.00")
    assert pat.team_raw == "ne"
    assert pat.avg_points_per_game == Decimal("21.50")
    blank = next(row for row in parsed if row.dk_id == "1002")
    assert blank.avg_points_per_game is None

    flipped = list(reversed(COLUMNS)) + ["Extra"]
    path_bytes = io.StringIO()
    writer = csv.DictWriter(path_bytes, fieldnames=flipped)
    writer.writeheader()
    writer.writerow(
        {
            "Position": "QB",
            "Name + ID": "Pat Sample (1001)",
            "Name": "Pat Sample",
            "ID": "1001",
            "Roster Position": "QB",
            "Salary": "$7,000",
            "Game Info": G_NE,
            "TeamAbbrev": "ne",
            "AvgPointsPerGame": "21.5",
            "Extra": "skip",
        }
    )
    writer.writerow(_person("1003", "Chiefs", "dst", "dst", "3000", "kc", G_DAL, "1"))
    again = parse_dk_csv(path_bytes.getvalue().encode())
    assert again[0].salary == Decimal("7000.00")
    assert again[0].dk_id == "1001"

    _prepare(engine)
    assert _load(database_url, FIXTURE) is True
    stored = _one(engine, "1001")
    assert stored["salary"] == Decimal("7000.00")
    assert stored["dk_id"] == "1001"
    assert stored["team_raw"] == "ne"
    assert stored["team_abbr"] == "NE"
    assert stored["avg_points_per_game"] == Decimal("21.50")
    assert stored["source_name"] == "classic.csv"
    assert stored["source_sha256"] == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert _one(engine, "1002")["avg_points_per_game"] is None


def test_at2_dst_maps_to_team_and_null_gsis(database_url, engine):
    _prepare(engine)
    assert _load(database_url, FIXTURE) is True
    chiefs = _one(engine, "1003")
    assert chiefs["position_raw"] == "dst"
    assert chiefs["team_abbr"] == "KC"
    assert chiefs["gsis_id"] is None
    assert chiefs["opponent_abbr"] == "NE"
    assert chiefs["game_id"] == GAME_NE
    assert chiefs["salary"] == Decimal("3000.00")


def test_at3_skill_player_maps_to_gsis_id(database_url, engine):
    _prepare(engine)
    assert _load(database_url, FIXTURE) is True
    pat = _one(engine, "1001")
    assert pat["gsis_id"] == PAT
    assert pat["gsis_id"] != PAT_LATEST
    assert pat["team_abbr"] == "NE"
    assert pat["opponent_abbr"] == "KC"
    assert pat["game_id"] == GAME_NE
    fallback = _one(engine, "1004")
    assert fallback["gsis_id"] == FALLBACK
    assert fallback["team_abbr"] == "DAL"
    assert fallback["opponent_abbr"] == "PHI"
    assert fallback["game_id"] == GAME_DAL
    assert _one(engine, "1002")["gsis_id"] is None


def test_at4_second_load_is_idempotent(database_url, engine):
    _prepare(engine)
    assert _load(database_url, FIXTURE) is True
    first = _stable(_rows(engine))
    assert _load(database_url, FIXTURE) is True
    assert _stable(_rows(engine)) == first
    assert _runs(engine)[-1]["rows_deleted"] == 0
    assert _runs(engine)[-1]["status"] == "succeeded"


def test_at5_removed_dk_id_is_deleted(database_url, engine, tmp_path):
    _prepare(engine)
    assert _load(database_url, FIXTURE) is True
    other = tmp_path / "week11.csv"
    _write(
        other,
        [
            _person("2001", "Week Two", "QB", "QB", "5000", "NE", G_NE, "10"),
            _person("2002", "Week Two B", "RB", "RB/FLEX", "5100", "DAL", G_DAL, "11"),
        ],
    )
    assert _load(database_url, other, week=11) is True
    kept = tmp_path / "week10b.csv"
    _write(
        kept,
        [
            _person("1001", "Pat Sample", "QB", "QB", "7100", "ne", G_NE, "21.5"),
            _person("1003", "Chiefs", "dst", "dst", "3000", "kc", G_NE, "8.1"),
            _person("1004", "Fallback Sample", "RB", "RB/FLEX", "5500", "dal", G_DAL, "9"),
        ],
    )
    assert _load(database_url, kept) is True
    ids = {(row["week"], row["dk_id"]) for row in _rows(engine)}
    assert (10, "1002") not in ids
    assert (10, "1001") in ids
    assert (11, "2001") in ids
    assert (11, "2002") in ids
    assert _one(engine, "1001")["salary"] == Decimal("7100.00")
    assert _runs(engine)[-1]["rows_deleted"] == 1


def test_at6_bad_header_keeps_rows_and_exits_1(database_url, engine, tmp_path):
    _prepare(engine)
    assert main(["--csv", str(FIXTURE), "--season", "2026", "--week", "10"]) == 0
    before = _rows(engine)
    bad = tmp_path / "bad.csv"
    bad.write_text("Name,Salary\nPat Sample,7000\n", encoding="utf-8")
    assert main(["--csv", str(bad), "--season", "2026", "--week", "10", "--trigger", "manual"]) == 1
    assert _rows(engine) == before
    failed = _runs(engine)[-1]
    assert failed["status"] == "failed"
    assert failed["trigger"] == "manual"
    assert "missing required column" in failed["error"]


def test_at7_load_runs_record(database_url, engine):
    _prepare(engine)
    assert _load(database_url, FIXTURE, trigger="manual") is True
    run = _runs(engine)[-1]
    digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert run["dataset"] == "dk_classic_slate"
    assert run["season"] == 2026
    assert run["status"] == "succeeded"
    assert run["trigger"] == "manual"
    assert run["source_url"] == "file:classic.csv"
    assert run["source_version"] == digest
    assert run["rows_read"] == 4
    assert run["rows_upserted"] == 4
    assert run["rows_deleted"] == 0
    assert run["rows_skipped"] == 0
    assert run["notes"] == "week=10; unmapped_skill=1"
    assert run["error"] is None


def test_at8_non_dst_match_rate_is_at_least_95_percent(database_url, engine, tmp_path):
    _prepare(engine)
    with engine.begin() as conn:
        for index in range(19):
            gsis_id = f"88-{index:07d}"
            _player(conn, gsis_id, f"Skill{index:02d}", "QB", "NE")
            _stat(conn, gsis_id, 2026, 10, GAME_NE, "NE", "KC", "QB")
    rows = [
        _person(str(3000 + index), f"Skill{index:02d}", "QB", "QB", 4000 + index, "NE", G_NE, "1")
        for index in range(20)
    ]
    rows.append(_person("9000", "Dallas", "DST", "DST", "2800", "DAL", G_DAL, "6"))
    path = tmp_path / "rate.csv"
    _write(path, rows)
    assert _load(database_url, path) is True
    stored = _rows(engine)
    non_dst = [
        row
        for row in stored
        if "DST" not in row["position_raw"].upper() and "DST" not in row["roster_position_raw"].upper()
    ]
    matched = [row for row in non_dst if row["gsis_id"] is not None]
    assert len(non_dst) == 20
    assert len(matched) * 100 >= 95 * len(non_dst)
    assert _one(engine, "3019")["gsis_id"] is None
    assert _one(engine, "9000")["gsis_id"] is None
    assert _one(engine, "9000")["team_abbr"] == "DAL"
    assert _runs(engine)[-1]["notes"] == "week=10; unmapped_skill=1"


def test_at9_no_nfldfs_or_draftkings_fetch():
    pyproject = (ROOT / "pyproject.toml").read_text().lower()
    assert "nfldfs" not in pyproject
    allowed_host = ROOT / "loader" / "dk_lobby.py"
    for folder in ("loader", "web", "migrations"):
        for path in (ROOT / folder).rglob("*.py"):
            text_value = path.read_text().lower()
            assert "nfldfs" not in text_value, path
            if path.resolve() != allowed_host.resolve():
                assert BANNED_HOST not in text_value, path
    for path in (ROOT / ".github").rglob("*.yml"):
        text_value = path.read_text().lower()
        assert "nfldfs" not in text_value
        assert BANNED_HOST not in text_value
    module = (ROOT / "loader" / "dk_slate.py").read_text().lower()
    assert "urlopen" in module
    assert "api.github.com" in module
    assert BANNED_HOST not in module


def test_at10_gitleaks_and_workflow_do_not_leak_secrets():
    workflow = WORKFLOW.read_text()
    assert "printenv" not in workflow
    assert "continue-on-error" not in workflow
    assert "|| true" not in workflow
    for line in workflow.splitlines():
        lowered = line.lower()
        assert not ("echo" in lowered and "database_url" in lowered), line
        assert not ("echo" in lowered and "dk_slate_csv" in lowered), line
    binary = shutil.which("gitleaks")
    assert binary, "gitleaks is not installed"
    scan = subprocess.run(
        [binary, "detect", "--source", str(ROOT), "--redact", "--log-opts=--all", "--no-banner"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert scan.returncode == 0, scan.stdout + scan.stderr


def test_at11_showdown_is_rejected(database_url, engine, tmp_path, capsys):
    _prepare(engine)
    assert main(["--csv", str(FIXTURE), "--season", "2026", "--week", "10"]) == 0
    before = _rows(engine)
    capsys.readouterr()
    captain = tmp_path / "captain.csv"
    _write(
        captain,
        [
            _person("1", "Captain", "QB", "CPT", "8000", "NE", G_NE, "20"),
            _person("2", "Flex", "WR", "FLEX", "4000", "DAL", G_DAL, "10"),
        ],
    )
    assert main(["--csv", str(captain), "--season", "2026", "--week", "10"]) == 1
    captured = capsys.readouterr()
    assert "Classic-only" in captured.err
    assert "CPT" in captured.err
    assert _rows(engine) == before
    assert _runs(engine)[-1]["status"] == "failed"
    assert "Classic-only" in _runs(engine)[-1]["error"]

    single = tmp_path / "single.csv"
    _write(
        single,
        [
            _person("3", "Only", "QB", "QB", "7000", "NE", G_NE, "20"),
            _person("4", "Mate", "RB", "RB/FLEX", "6000", "KC", G_NE, "12"),
        ],
    )
    assert main(["--csv", str(single), "--season", "2026", "--week", "10"]) == 1
    captured = capsys.readouterr()
    assert "Classic-only" in captured.err
    assert "Game Info" in captured.err
    assert _rows(engine) == before
    assert _runs(engine)[-1]["status"] == "failed"


def test_at12_scheduled_workflow_and_missing_file(database_url, engine, tmp_path, capsys):
    workflow = WORKFLOW.read_text().lower()
    assert "workflow_dispatch" in workflow
    assert "schedule:" in workflow
    assert "cron:" in workflow
    assert 'cron: "0 15 * * 2"' in WORKFLOW.read_text()
    assert "python -m loader.dk_slate" in workflow
    assert "--trigger" in workflow
    assert "scheduled" in workflow
    assert "manual" in workflow
    assert "secrets.dk_slate_csv" in workflow
    assert "dk_slate_season" in workflow
    assert "dk_slate_week" in workflow
    assert "dk_slate_artifact" in workflow
    assert "fetch_staged_artifact" in workflow
    assert BANNED_HOST not in workflow
    assert "continue-on-error" not in workflow
    assert "|| true" not in workflow

    _prepare(engine)
    assert _load(database_url, FIXTURE) is True
    before = _rows(engine)
    missing = tmp_path / "DKSalaries.csv"
    assert missing.exists() is False
    code = main(
        ["--csv", str(missing), "--season", "2026", "--week", "10", "--trigger", "scheduled"]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert "missing" in captured.err.lower()
    assert _rows(engine) == before
    failed = _runs(engine)[-1]
    assert failed["status"] == "failed"
    assert failed["trigger"] == "scheduled"
    assert "missing" in failed["error"]
    assert "DKSalaries.csv" in failed["error"]


def test_at13_no_public_salary_endpoint(client):
    listed = " ".join(API_ENDPOINTS).lower()
    assert "salary" not in listed
    assert "slate" not in listed
    assert "dk_classic_slate" not in listed
    for resource in RESOURCES:
        assert "salary" not in resource.slug
        assert "slate" not in resource.slug
    for link in PAGE_LINKS:
        assert "salary" not in link["href"]
        assert "slate" not in link["href"]
    for folder in ("web",):
        for path in (ROOT / folder).rglob("*"):
            if path.suffix not in {".py", ".html"}:
                continue
            text_value = path.read_text().lower()
            assert "dk_classic_slate" not in text_value, path
            assert "dksalaries" not in text_value, path
    for path in (
        "/api/dk-classic-slate",
        "/api/dk_classic_slate",
        "/api/salaries",
        "/api/dk-salaries",
        "/dk-salaries.csv",
        "/DKSalaries.csv",
        "/salaries",
        "/slate",
    ):
        response = client.get(path)
        assert response.status_code == 404, path
        assert "7000" not in response.text
    root = client.get("/api")
    assert root.status_code == 200
    assert "dk_classic_slate" not in root.text.lower()
    assert "dksalaries" not in root.text.lower()


def test_duplicate_dk_id_is_rejected():
    rows = [
        _person("7", "One", "QB", "QB", "1000", "NE", G_NE, "1"),
        _person("7", "Two", "RB", "RB", "1000", "DAL", G_DAL, "1"),
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    with pytest.raises(LoadError, match="duplicate key: dk_id"):
        parse_dk_csv(buffer.getvalue().encode())


def test_unresolved_team_keeps_prior_slate(database_url, engine, tmp_path):
    _prepare(engine)
    assert _load(database_url, FIXTURE) is True
    before = _rows(engine)
    path = tmp_path / "zzz.csv"
    _write(
        path,
        [
            _person("1", "Known", "QB", "QB", "1000", "NE", G_NE, "1"),
            _person("2", "Unknown", "QB", "QB", "1000", "ZZZ", G_DAL, "1"),
        ],
    )
    assert _load(database_url, path) is False
    assert _rows(engine) == before
    assert "unresolved team_abbr" in _runs(engine)[-1]["error"]
    assert _runs(engine)[-1]["status"] == "failed"


def test_week_out_of_range_exits_before_load(tmp_path):
    missing = tmp_path / "unused.csv"
    assert main(["--csv", str(missing), "--season", "2026", "--week", "19"]) == 1
    assert main(["--csv", str(missing), "--season", "1800", "--week", "1"]) == 1


def test_fetch_staged_artifact_writes_csv_and_skips_when_unset(monkeypatch, tmp_path):
    def boom(*_args, **_kwargs):
        raise AssertionError("network")

    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GH_REPO", raising=False)
    monkeypatch.setattr("loader.dk_slate.urlopen", boom)
    dest = tmp_path / "missing.csv"
    assert fetch_staged_artifact("", str(dest)) is False
    assert fetch_staged_artifact("slate", str(dest)) is False
    assert dest.exists() is False

    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w") as archive:
        archive.writestr("nested/notes.txt", "nope")
        archive.writestr("nested/DKSalaries.csv", "Position,Name\n")
    calls = {"n": 0}

    class _Body:
        def __init__(self, payload):
            self.payload = payload

        def read(self):
            return self.payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def urlopen(_request, timeout=60):
        assert timeout == 60
        calls["n"] += 1
        if calls["n"] == 1:
            payload = {
                "artifacts": [
                    {
                        "name": "old",
                        "expired": False,
                        "created_at": "2026-11-01T00:00:00Z",
                        "archive_download_url": "https://example.test/old",
                    },
                    {
                        "name": "slate",
                        "expired": True,
                        "created_at": "2026-11-06T00:00:00Z",
                        "archive_download_url": "https://example.test/expired",
                    },
                    {
                        "name": "slate",
                        "expired": False,
                        "created_at": "2026-11-05T00:00:00Z",
                        "archive_download_url": "https://example.test/slate",
                    },
                ]
            }
            return _Body(json.dumps(payload).encode())
        return _Body(blob.getvalue())

    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setenv("GH_REPO", "tjonesy10/seam-finder")
    monkeypatch.setattr("loader.dk_slate.urlopen", urlopen)
    written = tmp_path / "out.csv"
    assert fetch_staged_artifact("slate", str(written)) is True
    assert written.read_text() == "Position,Name\n"
    assert calls["n"] == 2
