import json
import os
import shutil
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from sqlalchemy import text

from loader.run import current_season, main, parse_seasons, run_load
from tests.conftest import FIXTURE_DIR


def _load(database_url, seasons, **kwargs):
    kwargs.setdefault("data_dir", FIXTURE_DIR)
    return run_load(database_url=database_url, seasons=seasons, **kwargs)


def _rows(engine, table, order):
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT * FROM {table} ORDER BY {order}")).mappings()
        return [dict(row) for row in result]


def _runs(engine):
    return _rows(engine, "load_runs", "id")


def _without_loaded_at(rows):
    return [{key: value for key, value in row.items() if key != "loaded_at"} for row in rows]


def _copy_fixture(tmp_path: Path) -> Path:
    dest = tmp_path / "nflverse"
    shutil.copytree(FIXTURE_DIR, dest)
    return dest


def test_current_season_march_boundary():
    assert current_season(date(2026, 1, 1)) == 2025
    assert current_season(date(2026, 2, 28)) == 2025
    assert current_season(date(2026, 3, 1)) == 2026
    assert current_season(date(2026, 11, 5)) == 2026
    assert parse_seasons(None, date(2026, 1, 15)) == [2025]
    assert parse_seasons("2024") == [2024]
    assert parse_seasons("2015-2017") == [2015, 2016, 2017]
    with pytest.raises(ValueError):
        parse_seasons("abc")
    with pytest.raises(ValueError):
        parse_seasons("2026-2015")


def test_at1_idempotent_load(database_url, engine):
    assert _load(database_url, [2024, 2025], trigger="local") is True
    first = {
        "teams": _without_loaded_at(_rows(engine, "teams", "team_abbr")),
        "players": _without_loaded_at(_rows(engine, "players", "gsis_id")),
        "games": _without_loaded_at(_rows(engine, "games", "game_id")),
        "player_week_stats": _without_loaded_at(
            _rows(engine, "player_week_stats", "gsis_id, season, week")
        ),
    }
    assert _load(database_url, [2024, 2025], trigger="local") is True
    second = {
        "teams": _without_loaded_at(_rows(engine, "teams", "team_abbr")),
        "players": _without_loaded_at(_rows(engine, "players", "gsis_id")),
        "games": _without_loaded_at(_rows(engine, "games", "game_id")),
        "player_week_stats": _without_loaded_at(
            _rows(engine, "player_week_stats", "gsis_id, season, week")
        ),
    }
    assert first == second
    runs = _runs(engine)
    groups = []
    for row in runs:
        if row["run_group"] not in groups:
            groups.append(row["run_group"])
    rerun = [row for row in runs if row["run_group"] == groups[-1]]
    assert rerun
    assert all(row["rows_deleted"] == 0 for row in rerun)


def _within_one_percent(actual, expected) -> bool:
    if expected == 0:
        return actual == 0
    return abs(actual - expected) / expected <= 0.01


@pytest.mark.network
@pytest.mark.skipif(os.environ.get("RUN_NETWORK_TESTS") != "1", reason="set RUN_NETWORK_TESTS=1")
def test_at2_network_current_season_within_one_percent(database_url, engine):
    from loader.source import HttpSource

    season = current_season()
    assert run_load(database_url=database_url, seasons=[season], trigger="local") is True
    source = HttpSource()
    try:
        teams = pl.read_parquet(source.fetch_parquet("teams", None))
        players = pl.read_parquet(source.fetch_parquet("players", None))
        games = pl.read_parquet(source.fetch_parquet("games", None)).filter(pl.col("season") == season)
        stats = pl.read_parquet(source.fetch_parquet("player_week_stats", season))
        stats = stats.filter((pl.col("season") == season) & pl.col("player_id").is_not_null())
    finally:
        source.close()
    with engine.connect() as conn:
        assert _within_one_percent(conn.execute(text("SELECT count(*) FROM teams")).scalar(), teams.height)
        assert _within_one_percent(
            conn.execute(text("SELECT count(*) FROM players")).scalar(), players.height
        )
        assert _within_one_percent(
            conn.execute(text("SELECT count(*) FROM games WHERE season = :season"), {"season": season}).scalar(),
            games.height,
        )
        assert _within_one_percent(
            conn.execute(
                text("SELECT count(*) FROM player_week_stats WHERE season = :season"),
                {"season": season},
            ).scalar(),
            stats.height,
        )


def test_at2_row_counts_match_fixture(database_url, engine):
    assert _load(database_url, [2024, 2025]) is True
    teams = pl.read_parquet(FIXTURE_DIR / "teams" / "teams_colors_logos.parquet")
    players = pl.read_parquet(FIXTURE_DIR / "players" / "players.parquet")
    games = pl.read_parquet(FIXTURE_DIR / "schedules" / "games.parquet")
    stats_kept = 0
    source_players = set(players["gsis_id"].to_list())
    stat_players = set()
    game_rows = 0
    for season in (2024, 2025):
        game_rows += games.filter(pl.col("season") == season).height
        stats = pl.read_parquet(FIXTURE_DIR / "stats_player" / f"stats_player_week_{season}.parquet")
        stats = stats.filter(pl.col("season") == season)
        kept = stats.filter(pl.col("player_id").is_not_null())
        stats_kept += kept.height
        stat_players.update(value for value in kept["player_id"].to_list() if value)
    stubs = stat_players - source_players
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM teams")).scalar() == teams.height
        assert conn.execute(text("SELECT count(*) FROM players")).scalar() == players.height + len(stubs)
        assert (
            conn.execute(
                text("SELECT count(*) FROM games WHERE season IN (2024, 2025)")
            ).scalar()
            == game_rows
        )
        assert conn.execute(text("SELECT count(*) FROM player_week_stats")).scalar() == stats_kept
    assert len(stubs) == 1


def test_at3_chase_week(database_url, engine):
    assert _load(database_url, [2024]) is True
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT game_id, team, opponent_team, receptions, targets, receiving_yards,
                       receiving_tds, fantasy_points, fantasy_points_ppr
                FROM player_week_stats
                WHERE gsis_id = '00-0036900' AND season = 2024 AND week = 10
                """
            )
        ).mappings().one()
    assert row["game_id"] == "2024_10_CIN_BAL"
    assert row["team"] == "CIN"
    assert row["opponent_team"] == "BAL"
    assert row["receptions"] == 11
    assert row["targets"] == 17
    assert row["receiving_yards"] == 264
    assert row["receiving_tds"] == 3
    assert row["fantasy_points"] == Decimal("44.4")
    assert row["fantasy_points_ppr"] == Decimal("55.4")


def test_at4_allen_and_dal_phi(database_url, engine):
    assert _load(database_url, [2025]) is True
    with engine.connect() as conn:
        allen = conn.execute(
            text(
                """
                SELECT team, opponent_team, passing_yards, rushing_yards, rushing_tds,
                       fantasy_points
                FROM player_week_stats
                WHERE gsis_id = '00-0034857' AND season = 2025 AND week = 1
                """
            )
        ).mappings().one()
        game = conn.execute(
            text(
                """
                SELECT gameday, away_team, away_score, home_team, home_score, result, total,
                       season_type
                FROM games WHERE game_id = '2025_01_DAL_PHI'
                """
            )
        ).mappings().one()
    assert allen["team"] == "BUF"
    assert allen["opponent_team"] == "BAL"
    assert allen["passing_yards"] == 394
    assert allen["rushing_yards"] == 30
    assert allen["rushing_tds"] == 2
    assert allen["fantasy_points"] == Decimal("38.76")
    assert game["gameday"] == date(2025, 9, 4)
    assert game["away_team"] == "DAL"
    assert game["away_score"] == 20
    assert game["home_team"] == "PHI"
    assert game["home_score"] == 24
    assert game["result"] == 4
    assert game["total"] == 44
    assert game["season_type"] == "REG"


def test_at5_removed_source_row_is_deleted(database_url, engine, tmp_path):
    assert _load(database_url, [2024]) is True
    data_dir = _copy_fixture(tmp_path)
    path = data_dir / "stats_player" / "stats_player_week_2024.parquet"
    frame = pl.read_parquet(path)
    frame = frame.filter((pl.col("player_id") != "00-0032445") | pl.col("player_id").is_null())
    frame.write_parquet(path)
    assert _load(database_url, [2024], data_dir=data_dir, datasets=["player_week_stats"]) is True
    with engine.connect() as conn:
        gone = conn.execute(
            text(
                """
                SELECT count(*) FROM player_week_stats
                WHERE gsis_id = '00-0032445' AND season = 2024 AND week = 10
                """
            )
        ).scalar()
        chase = conn.execute(
            text(
                """
                SELECT count(*) FROM player_week_stats
                WHERE gsis_id = '00-0036900' AND season = 2024 AND week = 10
                """
            )
        ).scalar()
    assert gone == 0
    assert chase == 1
    stats_runs = [
        row
        for row in _runs(engine)
        if row["dataset"] == "player_week_stats" and row["status"] == "succeeded"
    ]
    assert stats_runs[-1]["rows_deleted"] == 1


def test_at6_placeholder_rows_skipped(database_url, engine):
    assert _load(database_url, [2024, 2025]) is True
    expected = {}
    for season in (2024, 2025):
        frame = pl.read_parquet(
            FIXTURE_DIR / "stats_player" / f"stats_player_week_{season}.parquet"
        )
        expected[season] = frame.filter(pl.col("player_id").is_null()).height
        assert expected[season] > 0
    runs = [
        row
        for row in _runs(engine)
        if row["dataset"] == "player_week_stats" and row["status"] == "succeeded"
    ]
    assert {row["season"]: row["rows_skipped"] for row in runs} == expected
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM player_week_stats WHERE gsis_id IS NULL")).scalar() == 0


def test_at7_failed_load_keeps_old_data(database_url, engine, tmp_path, monkeypatch):
    assert _load(database_url, [2024], trigger="manual") is True
    before = {
        "teams": _rows(engine, "teams", "team_abbr"),
        "players": _rows(engine, "players", "gsis_id"),
        "games": _rows(engine, "games", "game_id"),
        "player_week_stats": _rows(engine, "player_week_stats", "gsis_id, season, week"),
    }
    data_dir = _copy_fixture(tmp_path)
    path = data_dir / "stats_player" / "stats_player_week_2024.parquet"
    pl.read_parquet(path).drop("receptions").write_parquet(path)
    monkeypatch.setenv("SEAM_DATA_DIR", str(data_dir))
    code = main(["--seasons", "2024", "--datasets", "player_week_stats", "--trigger", "manual"])
    assert code == 1
    after = {
        "teams": _rows(engine, "teams", "team_abbr"),
        "players": _rows(engine, "players", "gsis_id"),
        "games": _rows(engine, "games", "game_id"),
        "player_week_stats": _rows(engine, "player_week_stats", "gsis_id, season, week"),
    }
    assert before == after
    failed = [row for row in _runs(engine) if row["status"] == "failed"]
    assert failed
    assert "missing required column" in failed[-1]["error"]
    assert "receptions" in failed[-1]["error"]


def test_at8_load_runs_recorded(database_url, engine):
    assert _load(database_url, [2024, 2025], trigger="schedule") is True
    runs = _runs(engine)
    assert {row["run_group"] for row in runs} == {runs[0]["run_group"]}
    by_key = {(row["dataset"], row["season"]): row for row in runs}
    assert set(by_key) == {
        ("teams", None),
        ("players", None),
        ("games", 2024),
        ("games", 2025),
        ("player_week_stats", 2024),
        ("player_week_stats", 2025),
    }
    versions = {
        "teams": json.loads((FIXTURE_DIR / "teams" / "timestamp.json").read_text())["last_updated"],
        "players": json.loads((FIXTURE_DIR / "players" / "timestamp.json").read_text())["last_updated"],
        "games": json.loads((FIXTURE_DIR / "schedules" / "timestamp.json").read_text())["last_updated"],
        "player_week_stats": json.loads((FIXTURE_DIR / "stats_player" / "timestamp.json").read_text())[
            "last_updated"
        ],
    }
    for row in runs:
        assert row["status"] == "succeeded"
        assert row["trigger"] == "schedule"
        assert row["started_at"] is not None
        assert row["finished_at"] is not None
        assert row["finished_at"] >= row["started_at"]
        assert row["source_url"].startswith(
            "https://github.com/nflverse/nflverse-data/releases/download/"
        )
        assert row["source_version"] == versions[row["dataset"]]
        assert row["rows_read"] is not None
        assert row["rows_upserted"] is not None
        assert row["rows_deleted"] is not None
        assert row["rows_skipped"] is not None
        assert row["error"] is None


def test_stub_player_created_and_real_player_is_not(database_url, engine):
    assert _load(database_url, [2024]) is True
    stats = pl.read_parquet(FIXTURE_DIR / "stats_player" / "stats_player_week_2024.parquet")
    display = stats.filter(pl.col("player_id") == "00-0039810")["player_display_name"][0]
    with engine.connect() as conn:
        stub = conn.execute(
            text(
                """
                SELECT display_name, first_name, last_name, is_stub
                FROM players WHERE gsis_id = '00-0039810'
                """
            )
        ).mappings().one()
        chase = conn.execute(
            text("SELECT is_stub FROM players WHERE gsis_id = '00-0036900'")
        ).scalar()
    assert stub["is_stub"] is True
    assert stub["display_name"] == display
    assert stub["first_name"] is None
    assert stub["last_name"] is None
    assert chase is False
    notes = [
        row["notes"]
        for row in _runs(engine)
        if row["dataset"] == "player_week_stats" and row["season"] == 2024
    ]
    assert notes == ["stub_players=1"]


def test_unplayed_game_keeps_null_scores(database_url, engine):
    assert _load(database_url, [2026], datasets=["teams", "games"]) is True
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT away_score, home_score, result, total, season_type
                FROM games WHERE game_id = '2026_09_JAX_BAL'
                """
            )
        ).mappings().one()
    assert row["away_score"] is None
    assert row["home_score"] is None
    assert row["result"] is None
    assert row["total"] is None
    assert row["season_type"] == "REG"


def test_postseason_game_type_becomes_post(database_url, engine):
    assert _load(database_url, [2024], datasets=["teams", "games"]) is True
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT game_type, season_type FROM games WHERE game_id = '2024_19_LAC_HOU'")
        ).mappings().one()
    assert row["game_type"] == "WC"
    assert row["season_type"] == "POST"


def test_missing_stats_file_records_failure_and_other_datasets_continue(database_url, engine):
    assert _load(database_url, [1800], trigger="manual") is False
    runs = _runs(engine)
    by_key = {(row["dataset"], row["season"]): row for row in runs}
    assert by_key[("teams", None)]["status"] == "succeeded"
    assert by_key[("players", None)]["status"] == "succeeded"
    assert by_key[("games", 1800)]["status"] == "succeeded"
    assert by_key[("games", 1800)]["rows_read"] == 0
    failed = by_key[("player_week_stats", 1800)]
    assert failed["status"] == "failed"
    assert "source file not found" in failed["error"]
    assert failed["trigger"] == "manual"
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM player_week_stats")).scalar() == 0


def test_duplicate_key_writes_nothing(database_url, engine, tmp_path):
    assert _load(database_url, [2024], datasets=["teams", "games"]) is True
    before = _rows(engine, "games", "game_id")
    data_dir = _copy_fixture(tmp_path)
    path = data_dir / "schedules" / "games.parquet"
    frame = pl.read_parquet(path)
    extra = frame.filter(pl.col("game_id") == "2024_10_CIN_BAL")
    pl.concat([frame, extra]).write_parquet(path)
    assert _load(database_url, [2024], data_dir=data_dir, datasets=["games"]) is False
    assert _rows(engine, "games", "game_id") == before
    failed = [row for row in _runs(engine) if row["status"] == "failed"][-1]
    assert failed["dataset"] == "games"
    assert "duplicate key" in failed["error"]


def test_failed_games_skip_stats(database_url, engine, tmp_path):
    assert _load(database_url, [2024, 2025]) is True
    before = _rows(engine, "player_week_stats", "gsis_id, season, week")
    data_dir = _copy_fixture(tmp_path)
    path = data_dir / "schedules" / "games.parquet"
    pl.read_parquet(path).drop("game_id").write_parquet(path)
    assert _load(database_url, [2024, 2025], data_dir=data_dir) is False
    assert _rows(engine, "player_week_stats", "gsis_id, season, week") == before
    failed = [row for row in _runs(engine) if row["run_group"] == _runs(engine)[-1]["run_group"]]
    games_failed = [row for row in failed if row["dataset"] == "games"]
    stats_failed = [row for row in failed if row["dataset"] == "player_week_stats"]
    assert games_failed and all(row["status"] == "failed" for row in games_failed)
    assert {row["season"] for row in stats_failed} == {2024, 2025}
    assert all("skipped because the games load failed" in row["error"] for row in stats_failed)


def test_players_are_not_deleted(database_url, engine, tmp_path):
    assert _load(database_url, [2024]) is True
    data_dir = _copy_fixture(tmp_path)
    path = data_dir / "players" / "players.parquet"
    frame = pl.read_parquet(path).filter(pl.col("gsis_id") != "00-0036900")
    frame.write_parquet(path)
    assert _load(database_url, [2024], data_dir=data_dir, datasets=["players"]) is True
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM players WHERE gsis_id = '00-0036900'")
        ).scalar() == 1
    rerun = [row for row in _runs(engine) if row["dataset"] == "players"][-1]
    assert rerun["rows_deleted"] == 0


def test_upsert_updates_changed_player(database_url, engine, tmp_path):
    assert _load(database_url, [2024], datasets=["players"]) is True
    data_dir = _copy_fixture(tmp_path)
    path = data_dir / "players" / "players.parquet"
    frame = pl.read_parquet(path).with_columns(
        pl.when(pl.col("gsis_id") == "00-0036900")
        .then(pl.lit("XX"))
        .otherwise(pl.col("position"))
        .alias("position")
    )
    frame.write_parquet(path)
    assert _load(database_url, [2024], data_dir=data_dir, datasets=["players"]) is True
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT position FROM players WHERE gsis_id = '00-0036900'")
        ).scalar() == "XX"


def test_rekeyed_stat_replaces_old_week(database_url, engine, tmp_path):
    assert _load(database_url, [2024]) is True
    data_dir = _copy_fixture(tmp_path)
    path = data_dir / "stats_player" / "stats_player_week_2024.parquet"
    frame = pl.read_parquet(path).with_columns(
        pl.when(pl.col("player_id") == "00-0036900")
        .then(pl.lit(11))
        .otherwise(pl.col("week"))
        .alias("week")
    )
    frame.write_parquet(path)
    assert _load(database_url, [2024], data_dir=data_dir, datasets=["player_week_stats"]) is True
    with engine.connect() as conn:
        assert conn.execute(
            text(
                "SELECT count(*) FROM player_week_stats "
                "WHERE gsis_id = '00-0036900' AND season = 2024 AND week = 10"
            )
        ).scalar() == 0
        assert conn.execute(
            text(
                "SELECT week FROM player_week_stats "
                "WHERE gsis_id = '00-0036900' AND season = 2024"
            )
        ).scalar() == 11


def test_stub_name_stays_null_until_players_file(database_url, engine, tmp_path):
    data_dir = _copy_fixture(tmp_path)
    stats_path = data_dir / "stats_player" / "stats_player_week_2024.parquet"
    stats = pl.read_parquet(stats_path)
    template = stats.filter(pl.col("player_id") == "00-0036900")
    odell = template.with_columns(
        pl.lit("00-0099991").alias("player_id"),
        pl.lit("Odell Beckham Jr.").alias("player_display_name"),
    )
    pl.concat([stats, odell]).write_parquet(stats_path)
    assert _load(database_url, [2024], data_dir=data_dir) is True
    with engine.connect() as conn:
        stub = conn.execute(
            text(
                """
                SELECT display_name, first_name, last_name, is_stub
                FROM players WHERE gsis_id = '00-0099991'
                """
            )
        ).mappings().one()
    assert stub["display_name"] == "Odell Beckham Jr."
    assert stub["first_name"] is None
    assert stub["last_name"] is None
    assert stub["is_stub"] is True

    players_path = data_dir / "players" / "players.parquet"
    players = pl.read_parquet(players_path)
    filled = players.head(1).with_columns(
        pl.lit("00-0099991").alias("gsis_id"),
        pl.lit("Odell Beckham Jr.").alias("display_name"),
        pl.lit("Odell").alias("first_name"),
        pl.lit("Beckham Jr.").alias("last_name"),
    )
    pl.concat([players, filled]).write_parquet(players_path)
    assert _load(database_url, [2024], data_dir=data_dir, datasets=["players"]) is True
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT display_name, first_name, last_name, is_stub
                FROM players WHERE gsis_id = '00-0099991'
                """
            )
        ).mappings().one()
    assert row["display_name"] == "Odell Beckham Jr."
    assert row["first_name"] == "Odell"
    assert row["last_name"] == "Beckham Jr."
    assert row["is_stub"] is False


def test_games_load_that_would_orphan_stats_rolls_back(database_url, engine, tmp_path):
    assert _load(database_url, [2024, 2025]) is True
    before_games = _rows(engine, "games", "game_id")
    before_stats = _rows(engine, "player_week_stats", "gsis_id, season, week")
    data_dir = _copy_fixture(tmp_path)
    path = data_dir / "schedules" / "games.parquet"
    frame = pl.read_parquet(path).filter(pl.col("game_id") != "2024_10_CIN_BAL")
    frame.write_parquet(path)
    assert _load(database_url, [2024], data_dir=data_dir, datasets=["games"]) is False
    assert _rows(engine, "games", "game_id") == before_games
    assert _rows(engine, "player_week_stats", "gsis_id, season, week") == before_stats
    failed = [row for row in _runs(engine) if row["dataset"] == "games" and row["season"] == 2024]
    assert failed[-1]["status"] == "failed"
    assert "fk_player_week_stats_game_id" in failed[-1]["error"]


def test_cli_module_and_bad_season(database_url, monkeypatch):
    monkeypatch.setenv("SEAM_DATA_DIR", str(FIXTURE_DIR))
    assert main(["--seasons", "2024", "--trigger", "local"]) == 0
    assert main(["--seasons", "1800", "--trigger", "manual"]) == 1
    monkeypatch.delenv("DATABASE_URL")
    assert main(["--seasons", "2024"]) == 1


def test_cli_does_not_print_database_url(database_url):
    env = os_env_with_fixture()
    result = subprocess.run(
        [sys.executable, "-m", "loader", "--seasons", "2025", "--trigger", "local"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert env["DATABASE_URL"] not in result.stdout
    assert env["DATABASE_URL"] not in result.stderr


def test_connection_error_redacts_url(monkeypatch, capsys):
    password = "supersecret"
    url = "".join(["postgresql://", "user", ":", password, "@127.0.0.1:1/db"])  # noqa: FLY002
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("SEAM_DATA_DIR", str(FIXTURE_DIR))
    assert main(["--seasons", "2024", "--datasets", "teams"]) == 1
    captured = capsys.readouterr()
    assert password not in captured.out
    assert password not in captured.err
    assert url not in captured.out
    assert url not in captured.err


def os_env_with_fixture():
    env = os.environ.copy()
    env["SEAM_DATA_DIR"] = str(FIXTURE_DIR)
    return env
