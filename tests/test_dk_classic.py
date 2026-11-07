import hashlib
import os
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from loader.dk_classic import (
    SCSV_HEADER,
    TEAM_MAP,
    DownloadError,
    RotoGuruHttpSource,
    display_name,
    gsis_for,
    main,
    name_key,
    parse_scsv,
    parse_weeks,
    run_dk_classic,
    team_abbr_for,
    week_url,
)
from loader.source import LoadError
from web.attribution import ROTOGURU_DK_CLASSIC_ATTRIBUTION

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "rotoguru" / "2015" / "week_01.scsv"
BLANK_SALARY = ROOT / "tests" / "fixtures" / "rotoguru" / "2015" / "week_06_blank_salary.scsv"
OPPONENT_DASH = ROOT / "tests" / "fixtures" / "rotoguru" / "2017" / "week_11_opponent_dash.scsv"
WORKFLOW = ROOT / ".github" / "workflows" / "dk-classic-salaries.yml"
BRADY = "00-0019596"
EXACT_ATTRIBUTION = (
    "Historical DraftKings Classic salaries and points via RotoGuru (rotoguru1.com). "
    "Not affiliated with DraftKings."
)

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


class MapSource:
    def __init__(self, files):
        self.files = files
        self.calls = []

    def fetch(self, season, week):
        self.calls.append((season, week))
        return self.files.get((season, week))


class FakeClient:
    def __init__(self, outcomes, body=b"ok"):
        self.outcomes = list(outcomes)
        self.body = body
        self.calls = 0
        self.urls = []

    def get(self, url):
        self.calls += 1
        self.urls.append(url)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _Response(outcome, self.body if outcome == 200 else b"")

    def close(self):
        return None


class _Response:
    def __init__(self, status_code, content):
        self.status_code = status_code
        self.content = content


def _week_file():
    return FIXTURE.read_bytes()


def _line(gid, name, pos, team, opp, points, salary, week=1, season=2015, home="h"):
    return (
        f"{week};{season};{gid};{name};{pos};{team};{home};{opp};{points};{salary}"
    )


def _scsv(*lines):
    return (SCSV_HEADER + "\n" + "\n".join(lines) + "\n").encode()


def _salaries(engine):
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM dk_classic_salaries ORDER BY season, week, rotoguru_gid")
        ).mappings()
        return [dict(row) for row in rows]


def _runs(engine):
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT * FROM load_runs WHERE dataset = 'dk_classic_salaries' ORDER BY id"
            )
        ).mappings()
        return [dict(row) for row in rows]


def _stable(rows):
    hidden = {"loaded_at", "source_fetched_at"}
    return [{key: value for key, value in row.items() if key not in hidden} for row in rows]


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


def _game(conn, game_id, season, week, away, home, season_type="REG"):
    conn.execute(
        text(
            """
            INSERT INTO games (
                game_id, season, game_type, season_type, week, gameday, weekday,
                away_team, home_team, location, loaded_at
            ) VALUES (
                :game_id, :season, :season_type, :season_type, :week, '2015-09-10',
                'Thursday', :away, :home, 'Home', CURRENT_TIMESTAMP
            )
            """
        ),
        {
            "game_id": game_id,
            "season": season,
            "season_type": season_type,
            "week": week,
            "away": away,
            "home": home,
        },
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


def _seed_brady(engine):
    with engine.begin() as conn:
        for abbr in ("NE", "PIT", "CAR", "JAX", "TB"):
            _team(conn, abbr)
        _player(conn, BRADY, "Tom Brady", "QB", "TB")
        _player(conn, "00-0099999", "Tom Brady", "QB", "NE")
        _game(conn, "2015_01_PIT_NE", 2015, 1, "PIT", "NE")
        _game(conn, "2015_01_CAR_JAX", 2015, 1, "CAR", "JAX")
        _stat(conn, BRADY, 2015, 1, "2015_01_PIT_NE", "NE", "PIT", "QB")


def _load(database_url, source, seasons=(2015,), weeks=(1,), trigger="local"):
    return run_dk_classic(
        database_url=database_url,
        seasons=list(seasons),
        weeks=list(weeks),
        trigger=trigger,
        source=source,
    )


def test_at1_parse_2015_week_1_fixture():
    rows = {row.rotoguru_gid: row for row in parse_scsv(_week_file())}
    brady = rows[1131]
    assert brady.dk_points == Decimal("27.62")
    assert brady.dk_salary == 7700
    assert brady.name_raw == "Brady, Tom"
    carolina = rows[7005]
    assert carolina.pos_raw == "Def"
    assert carolina.dk_points == Decimal(21)
    assert carolina.dk_salary == 3100
    assert [part.strip() for part in SCSV_HEADER.split(";")] == [
        "Week",
        "Year",
        "GID",
        "Name",
        "Pos",
        "Team",
        "h/a",
        "Oppt",
        "DK points",
        "DK salary",
    ]


def test_html_wrapper_uses_the_pre_block_not_the_page():
    page = (
        "<html><p>ignore; this; row</p><pre>"
        + SCSV_HEADER
        + "\n1;2015;1131;Brady, Tom;QB;nwe;h;pit;27.62;7700\n"
        + "<div>not a row</div>\n"
        + "</pre><p>1;2015;1;Not, Real;QB;nwe;h;pit;1;1</p></html>"
    ).encode()
    rows = parse_scsv(page)
    assert [row.rotoguru_gid for row in rows] == [1131]
    assert rows[0].dk_points == Decimal("27.62")
    same_line = (
        "preface"
        + SCSV_HEADER
        + "1;2015;1131;Brady, Tom;QB;nwe;h;pit;27.62;7700"
    ).encode()
    assert [row.rotoguru_gid for row in parse_scsv(same_line)] == [1131]


def test_header_only_and_empty_body_are_missing_weeks():
    from loader.dk_classic import MissingWeek

    with pytest.raises(MissingWeek):
        parse_scsv(b"")
    with pytest.raises(MissingWeek):
        parse_scsv((SCSV_HEADER + "\n").encode())
    with pytest.raises(MissingWeek):
        parse_scsv(f"<pre>{SCSV_HEADER}\n</pre>".encode())
    with pytest.raises(LoadError, match="missing header"):
        parse_scsv(b"<html>no salaries</html>")


def test_integer_and_points_bounds():
    assert parse_scsv(_scsv(_line(2147483647, "A, Max", "QB", "nwe", "pit", "999999.99", "-2147483648")))[
        0
    ].dk_salary == -2147483648
    with pytest.raises(LoadError, match="invalid scsv integer"):
        parse_scsv(_scsv(_line(1, "A, Max", "QB", "nwe", "pit", "1", "2147483648")))
    with pytest.raises(LoadError, match="invalid scsv integer"):
        parse_scsv(_scsv(_line(-2147483649, "A, Max", "QB", "nwe", "pit", "1", "1")))
    with pytest.raises(LoadError, match="numeric overflow"):
        parse_scsv(_scsv(_line(1, "A, Max", "QB", "nwe", "pit", "1000000.00", "1")))


def test_blank_scsv_fields_fail():
    base = ["1", "2015", "10", "A, B", "QB", "nwe", "h", "pit", "1", "100"]
    for index in (3, 4, 5, 6, 7):
        parts = list(base)
        parts[index] = ""
        with pytest.raises(LoadError, match="invalid scsv row"):
            parse_scsv(_scsv(";".join(parts)))


def test_negative_points_and_duplicate_gid():
    rows = parse_scsv(_scsv(_line(7001, "Arizona Defense", "Def", "ari", "sea", "-3", "3300")))
    assert rows[0].dk_points == Decimal("-3.00")
    with pytest.raises(LoadError, match="duplicate key"):
        parse_scsv(
            _scsv(
                _line(1, "A, One", "QB", "nwe", "pit", "1", "1"),
                _line(1, "B, Two", "QB", "nwe", "pit", "1", "1"),
            )
        )


def test_team_map_and_season_oak():
    expected = {
        "ari": "ARI",
        "atl": "ATL",
        "bal": "BAL",
        "buf": "BUF",
        "car": "CAR",
        "chi": "CHI",
        "cin": "CIN",
        "cle": "CLE",
        "dal": "DAL",
        "den": "DEN",
        "det": "DET",
        "gnb": "GB",
        "hou": "HOU",
        "ind": "IND",
        "jac": "JAX",
        "kan": "KC",
        "lac": "LAC",
        "lar": "LAR",
        "lvr": "LV",
        "mia": "MIA",
        "min": "MIN",
        "nor": "NO",
        "nwe": "NE",
        "nyg": "NYG",
        "nyj": "NYJ",
        "oak": "OAK",
        "phi": "PHI",
        "pit": "PIT",
        "sdg": "SD",
        "sea": "SEA",
        "sfo": "SF",
        "stl": "STL",
        "tam": "TB",
        "ten": "TEN",
        "was": "WAS",
    }
    assert TEAM_MAP == expected
    assert team_abbr_for("nwe", 2015) == "NE"
    assert team_abbr_for("GNB", 2015) == "GB"
    assert team_abbr_for("jac", 2015) == "JAX"
    assert team_abbr_for("sdg", 2016) == "SD"
    assert team_abbr_for("stl", 2015) == "STL"
    assert team_abbr_for("oak", 2015) == "OAK"
    assert team_abbr_for("oak", 2019) == "OAK"
    assert team_abbr_for("oak", 2020) == "LV"
    assert team_abbr_for("oak", 2021) == "LV"
    assert team_abbr_for("lvr", 2021) == "LV"
    with pytest.raises(LoadError, match="unmapped team code: zzz"):
        team_abbr_for("zzz", 2015)
    with pytest.raises(LoadError, match="unmapped team code: -"):
        team_abbr_for("-", 2017)


def test_name_key_normalizes_rotoguru_display_form():
    assert display_name("Brady, Tom") == "Tom Brady"
    assert name_key("Brady, Tom") == name_key("Tom Brady")
    assert name_key("Beckham Jr., Odell") == name_key("Odell Beckham Jr.")
    assert name_key("Mahomes II, Patrick") == name_key("Patrick Mahomes")
    assert name_key("St. Brown, Amon-Ra") == name_key("Amon-Ra St. Brown")
    assert name_key("Chase, Ja'Marr") == name_key("Ja'Marr Chase")
    assert gsis_for("Brady, Tom", "QB", "NE", 1, {}, {}) is None
    assert gsis_for("Carolina Defense", "Def", "CAR", 1, {("x",): {"00-1"}}, {}) is None
    week_index = {("tom brady", "QB", "NE", 1): {BRADY}}
    fallback = {("tom brady", "QB", "NE"): {BRADY, "00-0099999"}}
    assert gsis_for("Brady, Tom", "QB", "NE", 1, week_index, fallback) == BRADY
    ambiguous = {("tom brady", "QB", "NE", 1): {BRADY, "00-0099999"}}
    assert gsis_for("Brady, Tom", "QB", "NE", 1, ambiguous, fallback) is None
    assert gsis_for("Brady, Tom", "QB", "NE", 1, {}, {("tom brady", "QB", "NE"): {BRADY}}) == BRADY


def test_at2_dst_maps_to_team_and_null_gsis(database_url, engine):
    _seed_brady(engine)
    assert _load(database_url, MapSource({(2015, 1): _week_file()})) is True
    carolina = next(row for row in _salaries(engine) if row["rotoguru_gid"] == 7005)
    assert carolina["team_abbr"] == "CAR"
    assert carolina["gsis_id"] is None
    assert carolina["opponent_abbr"] == "JAX"
    assert carolina["game_id"] == "2015_01_CAR_JAX"
    assert carolina["team_raw"] == "car"
    assert carolina["pos_raw"] == "Def"


def test_at3_brady_maps_to_the_week_stat_not_latest_team(database_url, engine):
    _seed_brady(engine)
    assert _load(database_url, MapSource({(2015, 1): _week_file()})) is True
    brady = next(row for row in _salaries(engine) if row["rotoguru_gid"] == 1131)
    assert brady["gsis_id"] == BRADY
    assert brady["team_abbr"] == "NE"
    assert brady["opponent_abbr"] == "PIT"
    assert brady["game_id"] == "2015_01_PIT_NE"
    assert brady["dk_points"] == Decimal("27.62")
    assert brady["dk_salary"] == 7700
    assert brady["source_url"] == week_url(2015, 1)
    assert brady["source_sha256"] == hashlib.sha256(_week_file()).hexdigest()


def test_at4_second_load_is_idempotent_and_deletes_nothing(database_url, engine):
    _seed_brady(engine)
    source = MapSource({(2015, 1): _week_file()})
    assert _load(database_url, source) is True
    first = _stable(_salaries(engine))
    assert _load(database_url, source) is True
    assert _stable(_salaries(engine)) == first
    succeeded = [row for row in _runs(engine) if row["status"] == "succeeded"]
    assert succeeded[-1]["rows_deleted"] == 0
    assert succeeded[-1]["rows_upserted"] == 3


def test_at5_removed_gid_is_deleted_and_other_weeks_stay(database_url, engine):
    _seed_brady(engine)
    week2 = _scsv(_line(42, "Other, Player", "QB", "nwe", "pit", "1", "1000", week=2))
    with engine.begin() as conn:
        _game(conn, "2015_02_PIT_NE", 2015, 2, "PIT", "NE")
    source = MapSource({(2015, 1): _week_file(), (2015, 2): week2})
    assert _load(database_url, source, weeks=(1, 2)) is True
    trimmed = _scsv(
        _line(1131, "Brady, Tom", "QB", "nwe", "pit", "27.62", "7700"),
        _line(7005, "Carolina Defense", "Def", "car", "jac", "21", "3100", home="a"),
    )
    assert _load(database_url, MapSource({(2015, 1): trimmed}), weeks=(1,)) is True
    gids = {(row["week"], row["rotoguru_gid"]) for row in _salaries(engine)}
    assert (1, 9001) not in gids
    assert (1, 1131) in gids
    assert (2, 42) in gids
    assert _runs(engine)[-1]["rows_deleted"] == 1


def test_at6_bad_header_keeps_rows_and_exits_1(database_url, engine, monkeypatch, tmp_path):
    _seed_brady(engine)
    assert _load(database_url, MapSource({(2015, 1): _week_file()})) is True
    before = _salaries(engine)
    bad = tmp_path / "2015"
    bad.mkdir()
    (bad / "week_01.scsv").write_bytes(b"not,the,header\n")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SEAM_ROTOGURU_DIR", str(tmp_path))
    assert main(["--seasons", "2015", "--weeks", "1", "--trigger", "local"]) == 1
    assert _salaries(engine) == before
    failed = _runs(engine)[-1]
    assert failed["status"] == "failed"
    assert failed["season"] == 2015
    assert "week=1" in failed["notes"]
    assert "missing header" in failed["error"]


def test_at7_load_runs_record_week_trigger_and_unmapped_skill(database_url, engine):
    _seed_brady(engine)
    assert _load(database_url, MapSource({(2015, 1): _week_file()}), trigger="manual") is True
    run = _runs(engine)[-1]
    assert run["dataset"] == "dk_classic_salaries"
    assert run["season"] == 2015
    assert run["status"] == "succeeded"
    assert run["trigger"] == "manual"
    assert run["source_url"] == week_url(2015, 1)
    assert run["rows_read"] == 3
    assert run["rows_upserted"] == 3
    assert run["rows_deleted"] == 0
    assert run["rows_skipped"] == 0
    assert "week=1" in run["notes"]
    assert "unmapped_skill=1" in run["notes"]
    assert run["started_at"] is not None
    assert run["finished_at"] is not None


def test_at8_recorded_sample_matches_at_least_98_percent(database_url, engine):
    lines = []
    with engine.begin() as conn:
        for abbr in ("NE", "PIT", "CAR", "JAX"):
            _team(conn, abbr)
        _game(conn, "2015_01_PIT_NE", 2015, 1, "PIT", "NE")
        _game(conn, "2015_01_CAR_JAX", 2015, 1, "CAR", "JAX")
        for index in range(1, 50):
            gsis_id = f"99-{index:07d}"
            _player(conn, gsis_id, f"Player{index:02d} Fictional", "QB", "DAL")
            _stat(conn, gsis_id, 2015, 1, "2015_01_PIT_NE", "NE", "PIT", "QB")
            lines.append(
                _line(
                    10000 + index,
                    f"Fictional, Player{index:02d}",
                    "QB",
                    "nwe",
                    "pit",
                    "1.5",
                    str(4000 + index),
                )
            )
    lines.append(_line(10100, "Fictional, Unmatched", "QB", "nwe", "pit", "1.5", "5000"))
    lines.append(_line(10101, "Fictional, Zero", "WR", "nwe", "pit", "0", "0"))
    lines.append(_line(7005, "Carolina Defense", "Def", "car", "jac", "21", "3100", home="a"))
    assert _load(database_url, MapSource({(2015, 1): _scsv(*lines)})) is True
    rows = _salaries(engine)
    paid = [row for row in rows if row["pos_raw"] != "Def" and row["dk_salary"] > 0]
    matched = [row for row in paid if row["gsis_id"] is not None]
    assert len(paid) == 50
    assert len(matched) * 100 >= 98 * len(paid)
    unmatched = [row for row in rows if row["rotoguru_gid"] == 10100]
    assert unmatched[0]["gsis_id"] is None
    assert all(row["gsis_id"] is None for row in rows if row["pos_raw"] == "Def")
    assert "unmapped_skill=" in _runs(engine)[-1]["notes"]


def test_at9_no_nfldfs_or_draftkings_in_production_code():
    pyproject = (ROOT / "pyproject.toml").read_text().lower()
    assert "nfldfs" not in pyproject
    banned = "draftkings.com"
    allowed_host = ROOT / "loader" / "dk_lobby.py"
    for folder in ("loader", "web", "migrations"):
        for path in (ROOT / folder).rglob("*.py"):
            text_value = path.read_text().lower()
            assert "nfldfs" not in text_value, path
            if path.resolve() != allowed_host.resolve():
                assert banned not in text_value, path
    for path in (ROOT / ".github").rglob("*.yml"):
        text_value = path.read_text().lower()
        assert "nfldfs" not in text_value
        assert banned not in text_value


def test_at10_workflow_does_not_print_secrets():
    text_value = WORKFLOW.read_text()
    assert "printenv" not in text_value
    assert "continue-on-error" not in text_value
    for line in text_value.splitlines():
        lowered = line.lower()
        assert not ("echo" in lowered and "database_url" in lowered), line


def test_at11_backfill_requests_only_reg_weeks_and_skips_missing(database_url, engine):
    assert parse_weeks(None) == list(range(1, 19))
    assert parse_weeks("1-18") == list(range(1, 19))
    assert parse_weeks("1-1") == [1]
    assert parse_weeks("18-18") == [18]
    assert parse_weeks("1") == [1]
    with pytest.raises(ValueError):
        parse_weeks("19")
    with pytest.raises(ValueError):
        parse_weeks("1-19")
    with pytest.raises(ValueError):
        parse_weeks("0")
    source = MapSource({})
    assert _load(database_url, source, seasons=range(2015, 2022), weeks=parse_weeks(None)) is True
    expected = [(season, week) for season in range(2015, 2022) for week in range(1, 19)]
    assert source.calls == expected
    assert _salaries(engine) == []
    runs = _runs(engine)
    assert len(runs) == len(expected)
    assert {row["status"] for row in runs} == {"succeeded"}
    assert {row["rows_skipped"] for row in runs} == {1}
    assert {row["rows_read"] for row in runs} == {0}
    assert {row["rows_upserted"] for row in runs} == {0}
    assert {row["rows_deleted"] for row in runs} == {0}
    assert all("skipped=missing scsv" in row["notes"] for row in runs)
    assert all("week=" in row["notes"] for row in runs)
    workflow = WORKFLOW.read_text()
    assert 'default: "2015-2021"' in workflow
    assert "python -m loader.dk_classic" in workflow


def test_missing_header_only_week_does_not_delete_existing_rows(database_url, engine):
    _seed_brady(engine)
    assert _load(database_url, MapSource({(2015, 1): _week_file()})) is True
    before = _salaries(engine)
    header_only = (SCSV_HEADER + "\n").encode()
    assert _load(database_url, MapSource({(2015, 1): header_only})) is True
    assert _salaries(engine) == before
    assert _runs(engine)[-1]["rows_skipped"] == 1
    assert _runs(engine)[-1]["rows_deleted"] == 0
    assert _runs(engine)[-1]["status"] == "succeeded"


def test_at12_zero_salary_is_loaded(database_url, engine):
    _seed_brady(engine)
    assert _load(database_url, MapSource({(2015, 1): _week_file()})) is True
    zero = next(row for row in _salaries(engine) if row["rotoguru_gid"] == 9001)
    assert zero["dk_salary"] == 0
    assert zero["dk_points"] == Decimal(0)
    assert zero["gsis_id"] is None
    assert zero["name_raw"] == "Fictional, Zero"


def test_blank_dk_salary_is_loaded_as_zero(database_url, engine):
    body = BLANK_SALARY.read_bytes()
    assert b"6;2015;5295;Grant, Ryan;WR;was;a;nyj;4.2;" in body
    parsed = parse_scsv(body)
    assert len(parsed) == 1
    assert parsed[0].rotoguru_gid == 5295
    assert parsed[0].name_raw == "Grant, Ryan"
    assert parsed[0].week == 6
    assert parsed[0].dk_points == Decimal("4.2")
    assert parsed[0].dk_salary == 0
    with engine.begin() as conn:
        for abbr in ("WAS", "NYJ"):
            _team(conn, abbr)
    assert _load(database_url, MapSource({(2015, 6): body}), weeks=(6,)) is True
    stored = _salaries(engine)[0]
    assert stored["rotoguru_gid"] == 5295
    assert stored["dk_salary"] == 0
    assert stored["dk_points"] == Decimal("4.2")
    assert stored["team_abbr"] == "WAS"
    assert stored["opponent_abbr"] == "NYJ"
    assert stored["gsis_id"] is None
    run = _runs(engine)[-1]
    assert run["status"] == "succeeded"
    assert run["rows_read"] == 1
    assert run["rows_upserted"] == 1
    with pytest.raises(LoadError, match="invalid scsv integer: DK salary"):
        parse_scsv(_scsv(_line(5295, "Grant, Ryan", "WR", "was", "nyj", "4.2", "nope", week=6)))


def test_opponent_dash_is_null_and_week_succeeds(database_url, engine, monkeypatch, tmp_path):
    assert "-" not in TEAM_MAP
    with pytest.raises(LoadError, match="unmapped team code: -"):
        team_abbr_for("-", 2017)
    body = OPPONENT_DASH.read_bytes()
    parsed = {row.rotoguru_gid: row for row in parse_scsv(body)}
    assert len(parsed) == 3
    assert parsed[1242].opponent_raw == "-"
    assert parsed[1298].opponent_raw == "-"
    assert parsed[1412].opponent_raw == "atl"
    with engine.begin() as conn:
        for abbr in ("TB", "MIA", "SEA", "ATL"):
            _team(conn, abbr)
    week_dir = tmp_path / "2017"
    week_dir.mkdir()
    (week_dir / "week_11.scsv").write_bytes(body)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SEAM_ROTOGURU_DIR", str(tmp_path))
    assert main(["--seasons", "2017", "--weeks", "11", "--trigger", "local"]) == 0
    by_gid = {row["rotoguru_gid"]: row for row in _salaries(engine)}
    assert set(by_gid) == {1242, 1298, 1412}
    assert by_gid[1242]["name_raw"] == "Fitzpatrick, Ryan"
    assert by_gid[1242]["team_abbr"] == "TB"
    assert by_gid[1242]["opponent_raw"] == "-"
    assert by_gid[1242]["opponent_abbr"] is None
    assert by_gid[1242]["dk_points"] == Decimal("19.9")
    assert by_gid[1242]["dk_salary"] == 5300
    assert by_gid[1298]["team_abbr"] == "MIA"
    assert by_gid[1298]["opponent_abbr"] is None
    assert by_gid[1412]["team_abbr"] == "SEA"
    assert by_gid[1412]["opponent_abbr"] == "ATL"
    run = _runs(engine)[-1]
    assert run["status"] == "succeeded"
    assert run["rows_read"] == 3
    assert run["rows_upserted"] == 3
    assert run["rows_skipped"] == 0
    assert run["notes"] == "week=11; unmapped_skill=3; opponent_dash=2"
    kept = _salaries(engine)
    bad_opponent = _scsv(
        _line(1, "Bad, Opp", "QB", "mia", "zzz", "1", "1000", week=11, season=2017)
    )
    assert _load(database_url, MapSource({(2017, 11): bad_opponent}), seasons=(2017,), weeks=(11,)) is False
    assert _salaries(engine) == kept
    failed = _runs(engine)[-1]
    assert failed["status"] == "failed"
    assert "unmapped team code: zzz" in failed["error"]
    bad_team = _scsv(_line(1, "Dash, Team", "QB", "-", "atl", "1", "1000", week=11, season=2017))
    assert _load(database_url, MapSource({(2017, 11): bad_team}), seasons=(2017,), weeks=(11,)) is False
    assert _salaries(engine) == kept
    assert "unmapped team code: -" in _runs(engine)[-1]["error"]
    dash_dst = _scsv(
        _line(7001, "Miami Defense", "Def", "mia", "-", "5", "3000", week=12, season=2017)
    )
    assert _load(database_url, MapSource({(2017, 12): dash_dst}), seasons=(2017,), weeks=(12,)) is True
    dst = next(row for row in _salaries(engine) if row["rotoguru_gid"] == 7001)
    assert dst["opponent_abbr"] is None
    assert dst["opponent_raw"] == "-"
    assert dst["team_abbr"] == "MIA"
    assert dst["gsis_id"] is None
    assert _runs(engine)[-1]["status"] == "succeeded"
    assert _runs(engine)[-1]["notes"] == "week=12; opponent_dash=1"


def test_at13_attribution_constant_is_exact():
    assert ROTOGURU_DK_CLASSIC_ATTRIBUTION == EXACT_ATTRIBUTION
    assert ROTOGURU_DK_CLASSIC_ATTRIBUTION.count("Historical DraftKings") == 1


def test_at14_unmapped_team_keeps_previous_rows(database_url, engine):
    _seed_brady(engine)
    assert _load(database_url, MapSource({(2015, 1): _week_file()})) is True
    before = _salaries(engine)
    bad = _scsv(_line(1131, "Brady, Tom", "QB", "zzz", "pit", "27.62", "7700"))
    assert _load(database_url, MapSource({(2015, 1): bad})) is False
    assert _salaries(engine) == before
    failed = _runs(engine)[-1]
    assert failed["status"] == "failed"
    assert "unmapped team code: zzz" in failed["error"]
    assert "week=1" in failed["notes"]


def test_at15_workflow_is_dispatch_only():
    text_value = WORKFLOW.read_text()
    assert "workflow_dispatch:" in text_value
    assert "schedule" not in text_value
    assert "cron" not in text_value
    assert "--trigger manual" in text_value
    assert "--trigger schedule" not in text_value


def test_oak_in_2021_maps_to_lv_and_game_id_needs_one_reg_game(database_url, engine):
    body = _scsv(
        _line(1552, "Herbert, Justin", "QB", "lac", "oak", "31.42", "7100", week=18, season=2021)
    )
    with engine.begin() as conn:
        for abbr in ("LAC", "LV", "OAK"):
            _team(conn, abbr)
        _player(conn, "00-0036355", "Justin Herbert", "QB", "LAC")
        _game(conn, "2021_18_LAC_LV", 2021, 18, "LAC", "LV")
        _game(conn, "2021_18_LAC_OAK_POST", 2021, 18, "LAC", "OAK", season_type="POST")
        _stat(conn, "00-0036355", 2021, 18, "2021_18_LAC_LV", "LAC", "LV", "QB")
    assert _load(database_url, MapSource({(2021, 18): body}), seasons=(2021,), weeks=(18,)) is True
    row = _salaries(engine)[0]
    assert row["team_abbr"] == "LAC"
    assert row["opponent_abbr"] == "LV"
    assert row["gsis_id"] == "00-0036355"
    assert row["game_id"] == "2021_18_LAC_LV"


def test_two_reg_games_leave_game_id_null(database_url, engine):
    _seed_brady(engine)
    with engine.begin() as conn:
        _team(conn, "BUF")
        _game(conn, "2015_01_NE_BUF", 2015, 1, "NE", "BUF")
    assert _load(database_url, MapSource({(2015, 1): _week_file()})) is True
    brady = next(row for row in _salaries(engine) if row["rotoguru_gid"] == 1131)
    assert brady["gsis_id"] == BRADY
    assert brady["game_id"] is None


def test_fallback_matches_another_reg_week_on_the_same_team(database_url, engine):
    body = _scsv(_line(10, "Only, Skill", "RB", "nwe", "pit", "2", "4000"))
    with engine.begin() as conn:
        for abbr in ("NE", "PIT"):
            _team(conn, abbr)
        _player(conn, "00-0000010", "Skill Only", "RB", "DAL")
        _game(conn, "2015_02_PIT_NE", 2015, 2, "PIT", "NE")
        _stat(conn, "00-0000010", 2015, 2, "2015_02_PIT_NE", "NE", "PIT", "RB")
    assert _load(database_url, MapSource({(2015, 1): body})) is True
    assert _salaries(engine)[0]["gsis_id"] == "00-0000010"


def test_failed_download_keeps_rows_and_retries(database_url, engine):
    _seed_brady(engine)
    assert _load(database_url, MapSource({(2015, 1): _week_file()})) is True
    before = _salaries(engine)
    sleeps = []
    client = FakeClient([500, 500, 500, 500])
    source = RotoGuruHttpSource(client=client, sleeper=lambda delay: sleeps.append(delay), retries=3)
    assert _load(database_url, source) is False
    assert client.calls == 4
    assert sleeps == [1, 2, 4]
    assert _salaries(engine) == before
    assert "download failed after 3 retries" in _runs(engine)[-1]["error"]


def test_http_400_is_retried_not_loaded():
    client = FakeClient([400, 400, 400, 400])
    source = RotoGuruHttpSource(client=client, sleeper=lambda delay: None, retries=3)
    with pytest.raises(DownloadError):
        source.fetch(2015, 1)
    assert client.calls == 4


def test_default_weeks_and_explicit_directory(database_url, engine, monkeypatch, tmp_path):
    _seed_brady(engine)
    source = MapSource({})
    assert run_dk_classic(database_url=database_url, seasons=[2015], source=source) is True
    assert source.calls == [(2015, week) for week in range(1, 19)]
    with pytest.raises(LoadError, match="1 to 18"):
        run_dk_classic(
            database_url=database_url,
            seasons=[2015],
            weeks=[19],
            source=MapSource({}),
        )
    monkeypatch.setenv("SEAM_ROTOGURU_DIR", str(tmp_path))
    assert (
        run_dk_classic(
            database_url=database_url,
            seasons=[2015],
            weeks=[1],
            data_dir=ROOT / "tests" / "fixtures" / "rotoguru",
        )
        is True
    )
    assert {row["rotoguru_gid"] for row in _salaries(engine)} == {1131, 7005, 9001}


def test_dst_is_not_an_unmapped_skill_and_week_position_wins(database_url, engine):
    _seed_brady(engine)
    mapped = _scsv(
        _line(1131, "Brady, Tom", "QB", "nwe", "pit", "27.62", "7700"),
        _line(7005, "Carolina Defense", "Def", "car", "jac", "21", "3100", home="a"),
    )
    assert _load(database_url, MapSource({(2015, 1): mapped})) is True
    assert _runs(engine)[-1]["notes"] == "week=1"
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM dk_classic_salaries"))
        conn.execute(text("DELETE FROM load_runs"))
        _player(conn, "00-0000088", "Wide Out", "QB", "DAL")
        _player(conn, "00-0000087", "Wide Out", "QB", "NE")
        _stat(conn, "00-0000088", 2015, 1, "2015_01_PIT_NE", "NE", "PIT", None)
        _player(conn, "00-0000089", "Slot Only", "QB", "DAL")
        _stat(conn, "00-0000089", 2015, 1, "2015_01_PIT_NE", "NE", "PIT", "WR")
    body = _scsv(
        _line(88, "Out, Wide", "QB", "nwe", "pit", "1", "1000"),
        _line(89, "Only, Slot", "WR", "nwe", "pit", "2", "2000"),
    )
    assert _load(database_url, MapSource({(2015, 1): body})) is True
    by_gid = {row["rotoguru_gid"]: row["gsis_id"] for row in _salaries(engine)}
    assert by_gid[88] == "00-0000088"
    assert by_gid[89] == "00-0000089"


def test_missing_team_row_names_the_abbreviation(database_url, engine):
    with engine.begin() as conn:
        _team(conn, "NE")
    body = _scsv(_line(1, "A, Player", "QB", "was", "nwe", "1", "1000"))
    assert _load(database_url, MapSource({(2015, 1): body})) is False
    assert _salaries(engine) == []
    assert "unresolved team_abbr: WAS" in _runs(engine)[-1]["error"]


def test_http_404_is_a_skipped_week_and_success_retries():
    sleeps = []
    missing = RotoGuruHttpSource(
        client=FakeClient([404, 200]),
        sleeper=lambda delay: sleeps.append(delay),
        retries=3,
    )
    assert missing.fetch(2015, 18) is None
    assert missing.client.calls == 1
    body = _week_file()
    flaky = FakeClient([TimeoutError("timed out"), TimeoutError("timed out"), 200], body=body)
    source = RotoGuruHttpSource(client=flaky, sleeper=lambda delay: None, retries=3)
    assert source.fetch(2015, 1) == body
    assert flaky.calls == 3
    assert flaky.urls[0] == "http://rotoguru1.com/cgi-bin/fyday.pl?week=1&year=2015&game=dk&scsv=1"
    assert flaky.urls[0].startswith("http://")
    with pytest.raises(DownloadError):
        RotoGuruHttpSource(client=FakeClient([500]), sleeper=lambda delay: None, retries=0).fetch(
            2015, 1
        )


def test_dir_source_and_cli_load_the_committed_fixture(database_url, engine, monkeypatch):
    _seed_brady(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SEAM_ROTOGURU_DIR", str(ROOT / "tests" / "fixtures" / "rotoguru"))
    assert main(["--seasons", "2015", "--weeks", "1", "--trigger", "local"]) == 0
    assert {row["rotoguru_gid"] for row in _salaries(engine)} == {1131, 7005, 9001}
    run = _runs(engine)[-1]
    assert run["status"] == "succeeded"
    assert run["trigger"] == "local"
    assert "unmapped_skill=1" in run["notes"]


def test_opponent_abbr_has_no_team_foreign_key(engine):
    with engine.begin() as conn:
        _team(conn, "NE")
        conn.execute(
            text(
                """
                INSERT INTO dk_classic_salaries (
                    season, week, rotoguru_gid, name_raw, pos_raw, team_raw, home_away,
                    opponent_raw, dk_points, dk_salary, team_abbr, opponent_abbr,
                    source_url, source_fetched_at, source_sha256, loaded_at
                ) VALUES (
                    2015, 1, 1, 'Fictional, Row', 'QB', 'nwe', 'h',
                    'zzz', 1, 1, 'NE', 'ZZZ',
                    'http://rotoguru1.com/cgi-bin/fyday.pl?week=1&year=2015&game=dk&scsv=1',
                    CURRENT_TIMESTAMP, 'abc', CURRENT_TIMESTAMP
                )
                """
            )
        )
    with engine.connect() as conn:
        assert conn.execute(text("SELECT opponent_abbr FROM dk_classic_salaries")).scalar() == "ZZZ"
    with engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    """
                    INSERT INTO dk_classic_salaries (
                        season, week, rotoguru_gid, name_raw, pos_raw, team_raw, home_away,
                        opponent_raw, dk_points, dk_salary, gsis_id, team_abbr,
                        source_url, source_fetched_at, source_sha256, loaded_at
                    ) VALUES (
                        2015, 1, 2, 'Fictional, Missing', 'QB', 'nwe', 'h',
                        'pit', 1, 1, '00-0000000', 'NE',
                        'http://rotoguru1.com/example', CURRENT_TIMESTAMP, 'abc',
                        CURRENT_TIMESTAMP
                    )
                    """
                )
            )
        trans.rollback()


def test_later_week_still_loads_after_an_earlier_failure(database_url, engine):
    _seed_brady(engine)
    bad = b"no header here\n"
    good = _scsv(_line(42, "Other, Player", "QB", "nwe", "pit", "1", "1000", week=2))
    with engine.begin() as conn:
        _game(conn, "2015_02_PIT_NE", 2015, 2, "PIT", "NE")
    assert (
        _load(database_url, MapSource({(2015, 1): bad, (2015, 2): good}), weeks=(1, 2)) is False
    )
    assert [row["rotoguru_gid"] for row in _salaries(engine)] == [42]
    statuses = [row["status"] for row in _runs(engine)]
    assert statuses == ["failed", "succeeded"]


def test_season_week_mismatch_does_not_write_post_rows(database_url, engine):
    _seed_brady(engine)
    post = _scsv(_line(1131, "Brady, Tom", "QB", "nwe", "pit", "1", "1", week=19))
    assert _load(database_url, MapSource({(2015, 1): post})) is False
    assert _salaries(engine) == []
    assert "does not match" in _runs(engine)[-1]["error"]


@pytest.mark.network
@pytest.mark.skipif(os.environ.get("RUN_NETWORK_TESTS") != "1", reason="set RUN_NETWORK_TESTS=1")
def test_live_2015_week_1_scsv_contains_brady_and_carolina():
    source = RotoGuruHttpSource()
    try:
        body = source.fetch(2015, 1)
    finally:
        source.close()
    assert body
    rows = {row.rotoguru_gid: row for row in parse_scsv(body)}
    assert rows[1131].dk_points == Decimal("27.62")
    assert rows[1131].dk_salary == 7700
    assert rows[7005].pos_raw == "Def"
    assert rows[7005].dk_salary == 3100
    assert b"Week;Year;GID;Name;Pos;Team;h/a;Oppt;DK points;DK salary" in body
