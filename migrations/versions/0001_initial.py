"""Initial schema: teams, players, games, player_week_stats, load_runs.

Revision ID: 0001
Revises:
Create Date: 2026-11-05

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, UUID

from loader.grants import apply_readonly_grant, revoke_readonly_grant

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("team_abbr", sa.Text, primary_key=True),
        sa.Column("team_name", sa.Text, nullable=False),
        sa.Column("team_nick", sa.Text, nullable=False),
        sa.Column("team_conf", sa.Text, nullable=False),
        sa.Column("team_division", sa.Text, nullable=False),
        sa.Column("team_id", sa.Text, nullable=False),
        sa.Column("team_color", sa.Text, nullable=False),
        sa.Column("team_color2", sa.Text, nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "players",
        sa.Column("gsis_id", sa.Text, primary_key=True),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("first_name", sa.Text),
        sa.Column("last_name", sa.Text),
        sa.Column("position", sa.Text),
        sa.Column("position_group", sa.Text),
        sa.Column("birth_date", sa.Date),
        sa.Column("height", sa.SmallInteger),
        sa.Column("weight", sa.SmallInteger),
        sa.Column("college_name", sa.Text),
        sa.Column("rookie_season", sa.SmallInteger),
        sa.Column("last_season", sa.SmallInteger),
        sa.Column("latest_team", sa.Text),
        sa.Column("status", sa.Text),
        sa.Column("years_of_experience", sa.SmallInteger),
        sa.Column("draft_year", sa.SmallInteger),
        sa.Column("draft_round", sa.SmallInteger),
        sa.Column("draft_pick", sa.SmallInteger),
        sa.Column("draft_team", sa.Text),
        sa.Column("pfr_id", sa.Text),
        sa.Column("espn_id", sa.Text),
        sa.Column("pff_id", sa.Text),
        sa.Column("nfl_id", sa.Text),
        sa.Column("esb_id", sa.Text),
        sa.Column("otc_id", sa.Text),
        sa.Column("is_stub", sa.Boolean, nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_players_position", "players", ["position"])
    op.create_index("ix_players_latest_team", "players", ["latest_team"])
    op.execute(
        "CREATE INDEX ix_players_lower_display_name "
        "ON players (lower(display_name) text_pattern_ops)"
    )
    op.create_table(
        "games",
        sa.Column("game_id", sa.Text, primary_key=True),
        sa.Column("season", sa.SmallInteger, nullable=False),
        sa.Column("game_type", sa.Text, nullable=False),
        sa.Column("season_type", sa.Text, nullable=False),
        sa.Column("week", sa.SmallInteger, nullable=False),
        sa.Column("gameday", sa.Date, nullable=False),
        sa.Column("weekday", sa.Text, nullable=False),
        sa.Column("gametime", sa.Text),
        sa.Column(
            "away_team",
            sa.Text,
            sa.ForeignKey("teams.team_abbr", name="fk_games_away_team", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "home_team",
            sa.Text,
            sa.ForeignKey("teams.team_abbr", name="fk_games_home_team", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("away_score", sa.SmallInteger),
        sa.Column("home_score", sa.SmallInteger),
        sa.Column("result", sa.SmallInteger),
        sa.Column("total", sa.SmallInteger),
        sa.Column("overtime", sa.Boolean),
        sa.Column("location", sa.Text, nullable=False),
        sa.Column("roof", sa.Text),
        sa.Column("surface", sa.Text),
        sa.Column("stadium", sa.Text),
        sa.Column("spread_line", sa.Numeric(4, 1)),
        sa.Column("total_line", sa.Numeric(4, 1)),
        sa.Column("old_game_id", sa.Text),
        sa.Column("pfr", sa.Text),
        sa.Column("espn", sa.Text),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_games_season_season_type_week",
        "games",
        ["season", "season_type", "week"],
    )
    op.create_index("ix_games_home_team_season", "games", ["home_team", "season"])
    op.create_index("ix_games_away_team_season", "games", ["away_team", "season"])
    op.create_table(
        "player_week_stats",
        sa.Column(
            "gsis_id",
            sa.Text,
            sa.ForeignKey(
                "players.gsis_id",
                name="fk_player_week_stats_gsis_id",
                ondelete="RESTRICT",
            ),
            primary_key=True,
        ),
        sa.Column("season", sa.SmallInteger, primary_key=True),
        sa.Column("week", sa.SmallInteger, primary_key=True),
        sa.Column("season_type", sa.Text, nullable=False),
        sa.Column(
            "game_id",
            sa.Text,
            sa.ForeignKey(
                "games.game_id",
                name="fk_player_week_stats_game_id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "team",
            sa.Text,
            sa.ForeignKey(
                "teams.team_abbr",
                name="fk_player_week_stats_team",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "opponent_team",
            sa.Text,
            sa.ForeignKey(
                "teams.team_abbr",
                name="fk_player_week_stats_opponent_team",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("position", sa.Text),
        sa.Column("position_group", sa.Text),
        sa.Column("completions", sa.SmallInteger, nullable=False),
        sa.Column("attempts", sa.SmallInteger, nullable=False),
        sa.Column("passing_yards", sa.SmallInteger, nullable=False),
        sa.Column("passing_tds", sa.SmallInteger, nullable=False),
        sa.Column("passing_interceptions", sa.SmallInteger, nullable=False),
        sa.Column("sacks_suffered", sa.SmallInteger, nullable=False),
        sa.Column("sack_fumbles_lost", sa.SmallInteger, nullable=False),
        sa.Column("passing_2pt_conversions", sa.SmallInteger, nullable=False),
        sa.Column("carries", sa.SmallInteger, nullable=False),
        sa.Column("rushing_yards", sa.SmallInteger, nullable=False),
        sa.Column("rushing_tds", sa.SmallInteger, nullable=False),
        sa.Column("rushing_fumbles_lost", sa.SmallInteger, nullable=False),
        sa.Column("rushing_2pt_conversions", sa.SmallInteger, nullable=False),
        sa.Column("receptions", sa.SmallInteger, nullable=False),
        sa.Column("targets", sa.SmallInteger, nullable=False),
        sa.Column("receiving_yards", sa.SmallInteger, nullable=False),
        sa.Column("receiving_tds", sa.SmallInteger, nullable=False),
        sa.Column("receiving_fumbles_lost", sa.SmallInteger, nullable=False),
        sa.Column("receiving_2pt_conversions", sa.SmallInteger, nullable=False),
        sa.Column("target_share", DOUBLE_PRECISION),
        sa.Column("special_teams_tds", sa.SmallInteger, nullable=False),
        sa.Column("fantasy_points", sa.Numeric(6, 2), nullable=False),
        sa.Column("fantasy_points_ppr", sa.Numeric(6, 2), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("gsis_id", "game_id", name="uq_player_week_stats_gsis_game"),
    )
    op.create_index(
        "ix_player_week_stats_season_season_type_week",
        "player_week_stats",
        ["season", "season_type", "week"],
    )
    op.create_index(
        "ix_player_week_stats_team_season",
        "player_week_stats",
        ["team", "season"],
    )
    op.create_index("ix_player_week_stats_game_id", "player_week_stats", ["game_id"])
    op.create_index(
        "ix_player_week_stats_season_position",
        "player_week_stats",
        ["season", "position"],
    )
    op.create_table(
        "load_runs",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("run_group", UUID(as_uuid=True), nullable=False),
        sa.Column("dataset", sa.Text, nullable=False),
        sa.Column("season", sa.SmallInteger),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("trigger", sa.Text, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("source_version", sa.Text),
        sa.Column("rows_read", sa.Integer),
        sa.Column("rows_upserted", sa.Integer),
        sa.Column("rows_deleted", sa.Integer),
        sa.Column("rows_skipped", sa.Integer),
        sa.Column("notes", sa.Text),
        sa.Column("error", sa.Text),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_load_runs_status",
        ),
    )
    op.create_index("ix_load_runs_status", "load_runs", ["status"])
    op.execute(
        "CREATE INDEX ix_load_runs_dataset_season_started_at "
        "ON load_runs (dataset, season, started_at DESC)"
    )
    apply_readonly_grant(op.get_bind())


def downgrade() -> None:
    revoke_readonly_grant(op.get_bind())
    op.drop_table("player_week_stats")
    op.drop_table("games")
    op.drop_table("load_runs")
    op.drop_table("players")
    op.drop_table("teams")
