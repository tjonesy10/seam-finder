"""SQLAlchemy Core tables and the nflverse column map."""

from dataclasses import dataclass

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, UUID

metadata = MetaData()

teams = Table(
    "teams",
    metadata,
    Column("team_abbr", Text, primary_key=True),
    Column("team_name", Text, nullable=False),
    Column("team_nick", Text, nullable=False),
    Column("team_conf", Text, nullable=False),
    Column("team_division", Text, nullable=False),
    Column("team_id", Text, nullable=False),
    Column("team_color", Text, nullable=False),
    Column("team_color2", Text, nullable=False),
    Column("loaded_at", DateTime(timezone=True), nullable=False),
)

players = Table(
    "players",
    metadata,
    Column("gsis_id", Text, primary_key=True),
    Column("display_name", Text, nullable=False),
    Column("first_name", Text),
    Column("last_name", Text),
    Column("position", Text),
    Column("position_group", Text),
    Column("birth_date", Date),
    Column("height", SmallInteger),
    Column("weight", SmallInteger),
    Column("college_name", Text),
    Column("rookie_season", SmallInteger),
    Column("last_season", SmallInteger),
    Column("latest_team", Text),
    Column("status", Text),
    Column("years_of_experience", SmallInteger),
    Column("draft_year", SmallInteger),
    Column("draft_round", SmallInteger),
    Column("draft_pick", SmallInteger),
    Column("draft_team", Text),
    Column("pfr_id", Text),
    Column("espn_id", Text),
    Column("pff_id", Text),
    Column("nfl_id", Text),
    Column("esb_id", Text),
    Column("otc_id", Text),
    Column("is_stub", Boolean, nullable=False),
    Column("loaded_at", DateTime(timezone=True), nullable=False),
)

games = Table(
    "games",
    metadata,
    Column("game_id", Text, primary_key=True),
    Column("season", SmallInteger, nullable=False),
    Column("game_type", Text, nullable=False),
    Column("season_type", Text, nullable=False),
    Column("week", SmallInteger, nullable=False),
    Column("gameday", Date, nullable=False),
    Column("weekday", Text, nullable=False),
    Column("gametime", Text),
    Column("away_team", Text, nullable=False),
    Column("home_team", Text, nullable=False),
    Column("away_score", SmallInteger),
    Column("home_score", SmallInteger),
    Column("result", SmallInteger),
    Column("total", SmallInteger),
    Column("overtime", Boolean),
    Column("location", Text, nullable=False),
    Column("roof", Text),
    Column("surface", Text),
    Column("stadium", Text),
    Column("spread_line", Numeric(4, 1)),
    Column("total_line", Numeric(4, 1)),
    Column("old_game_id", Text),
    Column("pfr", Text),
    Column("espn", Text),
    Column("loaded_at", DateTime(timezone=True), nullable=False),
)

player_week_stats = Table(
    "player_week_stats",
    metadata,
    Column("gsis_id", Text, primary_key=True),
    Column("season", SmallInteger, primary_key=True),
    Column("week", SmallInteger, primary_key=True),
    Column("season_type", Text, nullable=False),
    Column("game_id", Text, nullable=False),
    Column("team", Text, nullable=False),
    Column("opponent_team", Text, nullable=False),
    Column("position", Text),
    Column("position_group", Text),
    Column("completions", SmallInteger, nullable=False),
    Column("attempts", SmallInteger, nullable=False),
    Column("passing_yards", SmallInteger, nullable=False),
    Column("passing_tds", SmallInteger, nullable=False),
    Column("passing_interceptions", SmallInteger, nullable=False),
    Column("sacks_suffered", SmallInteger, nullable=False),
    Column("sack_fumbles_lost", SmallInteger, nullable=False),
    Column("passing_2pt_conversions", SmallInteger, nullable=False),
    Column("carries", SmallInteger, nullable=False),
    Column("rushing_yards", SmallInteger, nullable=False),
    Column("rushing_tds", SmallInteger, nullable=False),
    Column("rushing_fumbles_lost", SmallInteger, nullable=False),
    Column("rushing_2pt_conversions", SmallInteger, nullable=False),
    Column("receptions", SmallInteger, nullable=False),
    Column("targets", SmallInteger, nullable=False),
    Column("receiving_yards", SmallInteger, nullable=False),
    Column("receiving_tds", SmallInteger, nullable=False),
    Column("receiving_fumbles_lost", SmallInteger, nullable=False),
    Column("receiving_2pt_conversions", SmallInteger, nullable=False),
    Column("target_share", DOUBLE_PRECISION),
    Column("special_teams_tds", SmallInteger, nullable=False),
    Column("fantasy_points", Numeric(6, 2), nullable=False),
    Column("fantasy_points_ppr", Numeric(6, 2), nullable=False),
    Column("loaded_at", DateTime(timezone=True), nullable=False),
)

dk_classic_salaries = Table(
    "dk_classic_salaries",
    metadata,
    Column("season", SmallInteger, primary_key=True),
    Column("week", SmallInteger, primary_key=True),
    Column("rotoguru_gid", Integer, primary_key=True),
    Column("name_raw", Text, nullable=False),
    Column("pos_raw", Text, nullable=False),
    Column("team_raw", Text, nullable=False),
    Column("home_away", Text, nullable=False),
    Column("opponent_raw", Text, nullable=False),
    Column("dk_points", Numeric(8, 2), nullable=False),
    Column("dk_salary", Integer, nullable=False),
    Column("gsis_id", Text),
    Column("team_abbr", Text),
    Column("opponent_abbr", Text),
    Column("game_id", Text),
    Column("source_url", Text, nullable=False),
    Column("source_fetched_at", DateTime(timezone=True), nullable=False),
    Column("source_sha256", Text, nullable=False),
    Column("loaded_at", DateTime(timezone=True), nullable=False),
)

load_runs = Table(
    "load_runs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("run_group", UUID(as_uuid=True), nullable=False),
    Column("dataset", Text, nullable=False),
    Column("season", SmallInteger),
    Column("status", Text, nullable=False),
    Column("trigger", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("source_url", Text, nullable=False),
    Column("source_version", Text),
    Column("rows_read", Integer),
    Column("rows_upserted", Integer),
    Column("rows_deleted", Integer),
    Column("rows_skipped", Integer),
    Column("notes", Text),
    Column("error", Text),
)


@dataclass(frozen=True)
class Field:
    source: str
    dest: str
    kind: str
    nullable: bool
    precision: int | None = None
    scale: int | None = None


def fields(*items: tuple) -> tuple[Field, ...]:
    mapped = []
    for item in items:
        source, dest, kind, nullable = item[:4]
        precision = item[4] if len(item) > 4 else None
        scale = item[5] if len(item) > 5 else None
        mapped.append(Field(source, dest, kind, nullable, precision, scale))
    return tuple(mapped)


TEAMS_FIELDS = fields(
    ("team_abbr", "team_abbr", "text", False),
    ("team_name", "team_name", "text", False),
    ("team_nick", "team_nick", "text", False),
    ("team_conf", "team_conf", "text", False),
    ("team_division", "team_division", "text", False),
    ("team_id", "team_id", "text", False),
    ("team_color", "team_color", "text", False),
    ("team_color2", "team_color2", "text", False),
)

PLAYERS_FIELDS = fields(
    ("gsis_id", "gsis_id", "text", False),
    ("display_name", "display_name", "text", False),
    ("first_name", "first_name", "text", True),
    ("last_name", "last_name", "text", True),
    ("position", "position", "text", True),
    ("position_group", "position_group", "text", True),
    ("birth_date", "birth_date", "date", True),
    ("height", "height", "smallint", True),
    ("weight", "weight", "smallint", True),
    ("college_name", "college_name", "text", True),
    ("rookie_season", "rookie_season", "smallint", True),
    ("last_season", "last_season", "smallint", True),
    ("latest_team", "latest_team", "text", True),
    ("status", "status", "text", True),
    ("years_of_experience", "years_of_experience", "smallint", True),
    ("draft_year", "draft_year", "smallint", True),
    ("draft_round", "draft_round", "smallint", True),
    ("draft_pick", "draft_pick", "smallint", True),
    ("draft_team", "draft_team", "text", True),
    ("pfr_id", "pfr_id", "text", True),
    ("espn_id", "espn_id", "text", True),
    ("pff_id", "pff_id", "text", True),
    ("nfl_id", "nfl_id", "text", True),
    ("esb_id", "esb_id", "text", True),
    ("otc_id", "otc_id", "text", True),
)

GAMES_FIELDS = fields(
    ("game_id", "game_id", "text", False),
    ("season", "season", "smallint", False),
    ("game_type", "game_type", "text", False),
    ("week", "week", "smallint", False),
    ("gameday", "gameday", "date", False),
    ("weekday", "weekday", "text", False),
    ("gametime", "gametime", "text", True),
    ("away_team", "away_team", "text", False),
    ("home_team", "home_team", "text", False),
    ("away_score", "away_score", "smallint", True),
    ("home_score", "home_score", "smallint", True),
    ("result", "result", "smallint", True),
    ("total", "total", "smallint", True),
    ("overtime", "overtime", "bool", True),
    ("location", "location", "text", False),
    ("roof", "roof", "text", True),
    ("surface", "surface", "text", True),
    ("stadium", "stadium", "text", True),
    ("spread_line", "spread_line", "numeric", True, 4, 1),
    ("total_line", "total_line", "numeric", True, 4, 1),
    ("old_game_id", "old_game_id", "text", True),
    ("pfr", "pfr", "text", True),
    ("espn", "espn", "text", True),
)

STATS_FIELDS = fields(
    ("player_id", "gsis_id", "text", False),
    ("season", "season", "smallint", False),
    ("week", "week", "smallint", False),
    ("season_type", "season_type", "text", False),
    ("game_id", "game_id", "text", False),
    ("team", "team", "text", False),
    ("opponent_team", "opponent_team", "text", False),
    ("position", "position", "text", True),
    ("position_group", "position_group", "text", True),
    ("completions", "completions", "smallint", False),
    ("attempts", "attempts", "smallint", False),
    ("passing_yards", "passing_yards", "smallint", False),
    ("passing_tds", "passing_tds", "smallint", False),
    ("passing_interceptions", "passing_interceptions", "smallint", False),
    ("sacks_suffered", "sacks_suffered", "smallint", False),
    ("sack_fumbles_lost", "sack_fumbles_lost", "smallint", False),
    ("passing_2pt_conversions", "passing_2pt_conversions", "smallint", False),
    ("carries", "carries", "smallint", False),
    ("rushing_yards", "rushing_yards", "smallint", False),
    ("rushing_tds", "rushing_tds", "smallint", False),
    ("rushing_fumbles_lost", "rushing_fumbles_lost", "smallint", False),
    ("rushing_2pt_conversions", "rushing_2pt_conversions", "smallint", False),
    ("receptions", "receptions", "smallint", False),
    ("targets", "targets", "smallint", False),
    ("receiving_yards", "receiving_yards", "smallint", False),
    ("receiving_tds", "receiving_tds", "smallint", False),
    ("receiving_fumbles_lost", "receiving_fumbles_lost", "smallint", False),
    ("receiving_2pt_conversions", "receiving_2pt_conversions", "smallint", False),
    ("target_share", "target_share", "float", True),
    ("special_teams_tds", "special_teams_tds", "smallint", False),
    ("fantasy_points", "fantasy_points", "numeric", False, 6, 2),
    ("fantasy_points_ppr", "fantasy_points_ppr", "numeric", False, 6, 2),
)
