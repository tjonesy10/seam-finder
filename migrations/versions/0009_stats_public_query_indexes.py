"""Public stats order and cohort indexes.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-11

Performance-only. Merging this revision causes refresh workflows to run
alembic upgrade head against production and needs separate approval.
CREATE INDEX blocks writes on player_week_stats until the build finishes.
ADR 0011 does not require CONCURRENTLY. Downgrade drops both indexes.

"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_stats_public_ppr_order ON public.player_week_stats (fantasy_points_ppr DESC NULLS LAST, gsis_id ASC, season ASC, week ASC)"
    )
    op.execute(
        "CREATE INDEX ix_stats_public_scope_ppr ON public.player_week_stats (season ASC, season_type ASC, week ASC, fantasy_points_ppr DESC NULLS LAST, gsis_id ASC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX public.ix_stats_public_scope_ppr")
    op.execute("DROP INDEX public.ix_stats_public_ppr_order")
