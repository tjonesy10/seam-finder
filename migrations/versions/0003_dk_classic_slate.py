"""Current-slate DraftKings Classic salaries from DKSalaries.csv.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-06

"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dk_classic_slate",
        sa.Column("season", sa.SmallInteger, nullable=False),
        sa.Column("week", sa.SmallInteger, nullable=False),
        sa.Column("dk_id", sa.Text, nullable=False),
        sa.Column("name_raw", sa.Text, nullable=False),
        sa.Column("position_raw", sa.Text, nullable=False),
        sa.Column("roster_position_raw", sa.Text, nullable=False),
        sa.Column("team_raw", sa.Text, nullable=False),
        sa.Column("game_info_raw", sa.Text),
        sa.Column("salary", sa.Numeric(10, 2), nullable=False),
        sa.Column("avg_points_per_game", sa.Numeric(8, 2)),
        sa.Column(
            "gsis_id",
            sa.Text,
            sa.ForeignKey(
                "players.gsis_id",
                name="fk_dk_classic_slate_gsis_id",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column(
            "team_abbr",
            sa.Text,
            sa.ForeignKey(
                "teams.team_abbr",
                name="fk_dk_classic_slate_team_abbr",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column("opponent_abbr", sa.Text),
        sa.Column(
            "game_id",
            sa.Text,
            sa.ForeignKey(
                "games.game_id",
                name="fk_dk_classic_slate_game_id",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column("source_name", sa.Text, nullable=False),
        sa.Column("source_sha256", sa.Text, nullable=False),
        sa.Column("source_loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("season", "week", "dk_id", name="dk_classic_slate_pkey"),
    )
    op.create_index(
        "ix_dk_classic_slate_season_week",
        "dk_classic_slate",
        ["season", "week"],
    )
    op.create_index(
        "ix_dk_classic_slate_gsis_id_season_week",
        "dk_classic_slate",
        ["gsis_id", "season", "week"],
    )
    op.create_index(
        "ix_dk_classic_slate_team_abbr_season_week",
        "dk_classic_slate",
        ["team_abbr", "season", "week"],
    )


def downgrade() -> None:
    op.drop_table("dk_classic_slate")
