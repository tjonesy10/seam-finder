from decimal import Decimal

import polars as pl
import pytest
from sqlalchemy import text

from loader.grants import revoke_readonly_grant
from loader.run import (
    _convert,
    ensure_season_type,
    ensure_season_week,
    ensure_unique,
    normalize_database_url,
    parse_datasets,
    parse_seasons,
    redact,
)
from loader.source import LoadError, file_name, release_url
from loader.tables import Field


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


def test_field_scale_stays_absent_when_the_tuple_stops_at_precision():
    from loader.tables import fields

    five = fields(("dk_points", "dk_points", "numeric", False, 8))
    assert five[0].precision == 8
    assert five[0].scale is None
    six = fields(("dk_points", "dk_points", "numeric", False, 8, 2))
    assert (six[0].precision, six[0].scale) == (8, 2)


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


def _field(source, kind, nullable=False, precision=None, scale=None):
    return Field(source, source, kind, nullable, precision, scale)


def test_smallint_accepts_whole_numbers_and_rejects_bools_and_fractions():
    week = _field("week", "smallint")
    assert _convert(10, week) == 10
    assert _convert(10.0, week) == 10
    assert _convert(-32768, week) == -32768
    assert _convert(32767, week) == 32767
    with pytest.raises(LoadError, match="invalid integer"):
        _convert(True, week)
    with pytest.raises(LoadError, match="invalid integer"):
        _convert(10.5, week)
    with pytest.raises(LoadError, match="smallint out of range"):
        _convert(-32769, week)
    with pytest.raises(LoadError, match="smallint out of range"):
        _convert(32768, week)


def test_overtime_zero_and_one_become_booleans():
    overtime = _field("overtime", "bool", nullable=True)
    assert _convert(0, overtime) is False
    assert _convert(1, overtime) is True
    assert _convert(None, overtime) is None
    with pytest.raises(LoadError, match="invalid boolean"):
        _convert(2, overtime)


def test_numeric_scale_and_overflow():
    points = _field("fantasy_points", "numeric", precision=6, scale=2)
    spread = _field("spread_line", "numeric", nullable=True, precision=4, scale=1)
    assert _convert(44.4, points) == Decimal("44.40")
    assert _convert(0, points) == Decimal("0.00")
    assert _convert(9999.99, points) == Decimal("9999.99")
    assert _convert(-10, spread) == Decimal("-10.0")
    assert _convert(None, spread) is None
    with pytest.raises(LoadError, match="numeric overflow"):
        _convert(10000, points)
    with pytest.raises(LoadError, match="numeric overflow"):
        _convert(1000, spread)


def test_null_required_value_fails():
    with pytest.raises(LoadError, match="null value"):
        _convert(None, _field("receptions", "smallint"))


def test_one_row_null_key_fails_and_empty_frame_does_not():
    ensure_unique(pl.DataFrame({"game_id": []}), ["game_id"])
    ensure_unique(pl.DataFrame({"game_id": ["2024_10_CIN_BAL"]}), ["game_id"])
    with pytest.raises(LoadError, match="null key"):
        ensure_unique(pl.DataFrame({"game_id": [None]}), ["game_id"])


def test_season_range_of_one_year_and_unknown_dataset():
    assert parse_seasons("2024-2024") == [2024]
    with pytest.raises(ValueError, match="nope"):
        parse_datasets("nope")


def test_postgres_scheme_and_redaction():
    rewritten = normalize_database_url("postgres://user@/dbname")
    assert rewritten.startswith("postgresql+psycopg://")
    secret = "".join(["postgres://", "user", ":", "hidden", "@/dbname"])  # noqa: FLY002
    assert "hidden" not in redact(secret, secret)
    assert "<database>" in redact(secret, secret)


def test_revoke_missing_readonly_role_is_a_no_op(engine, monkeypatch):
    monkeypatch.setenv("READONLY_ROLE", "seam_reader_missing")
    with engine.begin() as conn:
        conn.execute(text("DROP ROLE IF EXISTS seam_reader_missing"))
        revoke_readonly_grant(conn)
