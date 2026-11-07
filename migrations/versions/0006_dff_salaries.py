"""Private Daily Fantasy Fuel salary rows.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-07

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from loader.grants import apply_readonly_grant

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dff_salaries",
        sa.Column(
            "snapshot_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "salary_private.salary_snapshots.snapshot_id",
                name="fk_dff_salaries_snapshot",
                ondelete="RESTRICT",
            ),
            primary_key=True,
        ),
        sa.Column("row_number", sa.Integer, primary_key=True),
        sa.Column("artifact_id", sa.BigInteger, nullable=False),
        sa.Column("parser_version", sa.Text, nullable=False),
        sa.Column("row_status", sa.Text, nullable=False),
        sa.Column("reason_codes", JSONB, nullable=False),
        sa.Column("salary", sa.Numeric(10, 2)),
        sa.Column("dff_player_id", sa.Text),
        sa.Column("start_date", sa.Date),
        sa.Column("week_raw", sa.Text),
        sa.Column("name_raw", sa.Text),
        sa.Column("position_raw", sa.Text),
        sa.Column("pos_alt_raw", sa.Text),
        sa.Column("team_raw", sa.Text),
        sa.Column("opponent_raw", sa.Text),
        sa.Column("location_raw", sa.Text),
        sa.Column("ppg_proj", sa.Numeric(12, 4)),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("row_number > 0", name="ck_dff_salaries_number"),
        sa.CheckConstraint(
            "row_status IN ('valid', 'rejected')",
            name="ck_dff_salaries_status",
        ),
        sa.CheckConstraint(
            "salary IS NULL OR salary >= 0",
            name="ck_dff_salaries_salary",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id", "parser_version", "row_number"],
            [
                "salary_private.salary_source_rows.artifact_id",
                "salary_private.salary_source_rows.parser_version",
                "salary_private.salary_source_rows.row_number",
            ],
            name="fk_dff_salaries_ledger",
            ondelete="RESTRICT",
        ),
        schema="salary_private",
    )
    op.create_index(
        "ix_dff_salaries_status",
        "dff_salaries",
        ["snapshot_id", "row_status"],
        schema="salary_private",
    )
    op.create_index(
        "ix_dff_salaries_player",
        "dff_salaries",
        ["dff_player_id", "snapshot_id"],
        schema="salary_private",
    )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA salary_private FROM PUBLIC")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA salary_private FROM PUBLIC")
    apply_readonly_grant(op.get_bind())


def downgrade() -> None:
    op.drop_index("ix_dff_salaries_player", table_name="dff_salaries", schema="salary_private")
    op.drop_index("ix_dff_salaries_status", table_name="dff_salaries", schema="salary_private")
    op.drop_table("dff_salaries", schema="salary_private")
