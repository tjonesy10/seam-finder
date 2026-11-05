import polars as pl
import pytest
from sqlalchemy import text

from loader.grants import revoke_readonly_grant
from loader.run import ensure_season_type, ensure_season_week, split_name
from loader.source import LoadError, file_name, release_url


def test_split_name_one_and_many_tokens():
    assert split_name("Cher") == ("Cher", "Cher")
    assert split_name("Ja'Marr Chase") == ("Ja'Marr", "Chase")
    assert split_name("Travis Etienne Jr.") == ("Travis Etienne", "Jr.")


def test_season_and_week_bounds():
    ok = pl.DataFrame({"season": [1999, 2100], "week": [1, 22]})
    ensure_season_week(ok)
    ensure_season_week(pl.DataFrame({"season": [], "week": []}))
    with pytest.raises(LoadError, match="season out of range"):
        ensure_season_week(pl.DataFrame({"season": [1998], "week": [1]}))
    with pytest.raises(LoadError, match="season out of range"):
        ensure_season_week(pl.DataFrame({"season": [2101], "week": [1]}))
    with pytest.raises(LoadError, match="week out of range"):
        ensure_season_week(pl.DataFrame({"season": [2024], "week": [0]}))
    with pytest.raises(LoadError, match="week out of range"):
        ensure_season_week(pl.DataFrame({"season": [2024], "week": [23]}))


def test_season_type_must_be_reg_or_post():
    ensure_season_type(pl.DataFrame({"season_type": ["REG", "POST"]}))
    ensure_season_type(pl.DataFrame({"season_type": []}))
    with pytest.raises(LoadError, match="invalid season_type"):
        ensure_season_type(pl.DataFrame({"season_type": ["PRE"]}))
    with pytest.raises(LoadError, match="invalid season_type"):
        ensure_season_type(pl.DataFrame({"season_type": [None]}))


def test_release_file_names():
    assert file_name("teams", None) == "teams_colors_logos.parquet"
    assert file_name("players", None) == "players.parquet"
    assert file_name("games", None) == "games.parquet"
    assert file_name("player_week_stats", 2024) == "stats_player_week_2024.parquet"
    assert release_url("player_week_stats", 2024).endswith(
        "/stats_player/stats_player_week_2024.parquet"
    )
    with pytest.raises(LoadError, match="requires a season"):
        file_name("player_week_stats", None)
    with pytest.raises(LoadError, match="unknown dataset"):
        file_name("injuries", None)


def test_revoke_missing_readonly_role_is_a_no_op(engine, monkeypatch):
    monkeypatch.setenv("READONLY_ROLE", "seam_reader_missing")
    with engine.begin() as conn:
        conn.execute(text("DROP ROLE IF EXISTS seam_reader_missing"))
        revoke_readonly_grant(conn)
