"""DraftKings Classic salaries from RotoGuru.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06

"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dk_classic_salaries",
        sa.Column("season", sa.SmallInteger, nullable=False),
        sa.Column("week", sa.SmallInteger, nullable=False),
        sa.Column("rotoguru_gid", sa.Integer, nullable=False),
        sa.Column("name_raw", sa.Text, nullable=False),
        sa.Column("pos_raw", sa.Text, nullable=False),
        sa.Column("team_raw", sa.Text, nullable=False),
        sa.Column("home_away", sa.Text, nullable=False),
        sa.Column("opponent_raw", sa.Text, nullable=False),
        sa.Column("dk_points", sa.Numeric(8, 2), nullable=False),
        sa.Column("dk_salary", sa.Integer, nullable=False),
        sa.Column(
            "gsis_id",
            sa.Text,
            sa.ForeignKey(
                "players.gsis_id",
                name="fk_dk_classic_salaries_gsis_id",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column(
            "team_abbr",
            sa.Text,
            sa.ForeignKey(
                "teams.team_abbr",
                name="fk_dk_classic_salaries_team_abbr",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column("opponent_abbr", sa.Text),
        sa.Column(
            "game_id",
            sa.Text,
            sa.ForeignKey(
                "games.game_id",
                name="fk_dk_classic_salaries_game_id",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("source_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_sha256", sa.Text, nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("season", "week", "rotoguru_gid", name="dk_classic_salaries_pkey"),
    )
    op.create_index(
        "ix_dk_classic_salaries_season_week",
        "dk_classic_salaries",
        ["season", "week"],
    )
    op.create_index(
        "ix_dk_classic_salaries_gsis_id_season_week",
        "dk_classic_salaries",
        ["gsis_id", "season", "week"],
    )
    op.create_index(
        "ix_dk_classic_salaries_team_abbr_season_week",
        "dk_classic_salaries",
        ["team_abbr", "season", "week"],
    )


def downgrade() -> None:
    op.drop_table("dk_classic_salaries")
