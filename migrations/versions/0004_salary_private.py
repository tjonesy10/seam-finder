"""Private salary artifacts, attempts, snapshots, ledger, and lobby rows.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-06

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from loader.grants import apply_readonly_grant

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_SHA = r"^[0-9a-f]{64}$"
_SOURCES = (
    "dk_lobby",
    "dff",
    "dknfl",
    "f003_adapter",
    "f004_adapter",
    "control",
)
_KINDS = (
    "csv",
    "lobby_json",
    "rules_json",
    "html_gzip",
    "manifest",
    "mapping",
    "adapter_row_image",
    "rejected_body",
)
_SOURCE_SQL = ", ".join(f"'{item}'" for item in _SOURCES)
_KIND_SQL = ", ".join(f"'{item}'" for item in _KINDS)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS salary_private")
    op.execute("REVOKE ALL ON SCHEMA salary_private FROM PUBLIC")
    op.create_table(
        "salary_artifacts",
        sa.Column("artifact_id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("body", sa.LargeBinary, nullable=False),
        sa.Column("byte_count", sa.Integer, nullable=False),
        sa.Column("media_type", sa.Text, nullable=False),
        sa.Column("artifact_kind", sa.Text, nullable=False),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"source IN ({_SOURCE_SQL})", name="ck_salary_artifacts_source"),
        sa.CheckConstraint(f"sha256 ~ '{_SHA}'", name="ck_salary_artifacts_sha256"),
        sa.CheckConstraint(
            "byte_count = octet_length(body) AND byte_count >= 0 AND octet_length(body) <= 5242880",
            name="ck_salary_artifacts_body",
        ),
        sa.CheckConstraint(
            f"artifact_kind IN ({_KIND_SQL})",
            name="ck_salary_artifacts_kind",
        ),
        sa.UniqueConstraint("source", "sha256", name="uq_salary_artifacts_source_sha256"),
        schema="salary_private",
    )
    op.create_table(
        "salary_snapshots",
        sa.Column("snapshot_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column(
            "artifact_id",
            sa.BigInteger,
            sa.ForeignKey(
                "salary_private.salary_artifacts.artifact_id",
                name="fk_salary_snapshots_artifact",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("parser_version", sa.Text, nullable=False),
        sa.Column("metadata_sha256", sa.Text, nullable=False),
        sa.Column("source_snapshot_key", sa.Text, nullable=False),
        sa.Column("season", sa.SmallInteger),
        sa.Column("season_type", sa.Text, nullable=False),
        sa.Column("week", sa.SmallInteger),
        sa.Column("draft_group_id", sa.Text),
        sa.Column("games", JSONB, nullable=False),
        sa.Column("rules", JSONB, nullable=False),
        sa.Column("game_set_sha256", sa.Text),
        sa.Column("rules_sha256", sa.Text),
        sa.Column("source_pool_kind", sa.Text, nullable=False),
        sa.Column("metadata", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"source IN ({_SOURCE_SQL})", name="ck_salary_snapshots_source"),
        sa.CheckConstraint(
            f"metadata_sha256 ~ '{_SHA}'",
            name="ck_salary_snapshots_metadata_sha",
        ),
        sa.CheckConstraint(
            "season IS NULL OR season BETWEEN 1999 AND 2100",
            name="ck_salary_snapshots_season",
        ),
        sa.CheckConstraint(
            "week IS NULL OR week BETWEEN 1 AND 22",
            name="ck_salary_snapshots_week",
        ),
        sa.CheckConstraint(
            "season_type IN ('REG', 'POST', 'UNKNOWN')",
            name="ck_salary_snapshots_season_type",
        ),
        sa.CheckConstraint(
            f"game_set_sha256 IS NULL OR game_set_sha256 ~ '{_SHA}'",
            name="ck_salary_snapshots_game_sha",
        ),
        sa.CheckConstraint(
            f"rules_sha256 IS NULL OR rules_sha256 ~ '{_SHA}'",
            name="ck_salary_snapshots_rules_sha",
        ),
        sa.CheckConstraint(
            "source_pool_kind IN ('full_export', 'subset', 'legacy_unknown', 'adapter_current')",
            name="ck_salary_snapshots_pool",
        ),
        sa.UniqueConstraint(
            "source",
            "source_snapshot_key",
            "artifact_id",
            "parser_version",
            "metadata_sha256",
            name="uq_salary_snapshots_identity",
        ),
        schema="salary_private",
    )
    op.create_index(
        "ix_salary_snapshots_season_week",
        "salary_snapshots",
        ["source", "season", "season_type", "week"],
        schema="salary_private",
    )
    op.create_index(
        "ix_salary_snapshots_draft_group",
        "salary_snapshots",
        ["draft_group_id"],
        schema="salary_private",
    )
    op.create_index(
        "ix_salary_snapshots_game_rules",
        "salary_snapshots",
        ["game_set_sha256", "rules_sha256"],
        schema="salary_private",
    )
    op.create_table(
        "salary_observations",
        sa.Column("observation_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "load_run_id",
            sa.BigInteger,
            sa.ForeignKey(
                "load_runs.id",
                name="fk_salary_observations_load_run",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("source_published_at", sa.DateTime(timezone=True)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.Text),
        sa.Column("original_path", sa.Text),
        sa.Column(
            "artifact_id",
            sa.BigInteger,
            sa.ForeignKey(
                "salary_private.salary_artifacts.artifact_id",
                name="fk_salary_observations_artifact",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column(
            "snapshot_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "salary_private.salary_snapshots.snapshot_id",
                name="fk_salary_observations_snapshot",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column("metadata", JSONB, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("reason_code", sa.Text),
        sa.Column("error_private", sa.Text),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"source IN ({_SOURCE_SQL})", name="ck_salary_observations_source"),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'rejected', 'skipped')",
            name="ck_salary_observations_status",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_salary_observations_duration",
        ),
        schema="salary_private",
    )
    op.execute(
        "CREATE INDEX ix_salary_observations_source_observed "
        "ON salary_private.salary_observations (source, observed_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_salary_observations_snapshot_observed "
        "ON salary_private.salary_observations (snapshot_id, observed_at DESC)"
    )
    op.create_index(
        "ix_salary_observations_load_run",
        "salary_observations",
        ["load_run_id"],
        schema="salary_private",
    )
    op.create_table(
        "salary_source_rows",
        sa.Column(
            "artifact_id",
            sa.BigInteger,
            sa.ForeignKey(
                "salary_private.salary_artifacts.artifact_id",
                name="fk_salary_source_rows_artifact",
                ondelete="RESTRICT",
            ),
            primary_key=True,
        ),
        sa.Column("parser_version", sa.Text, primary_key=True),
        sa.Column("row_number", sa.Integer, primary_key=True),
        sa.Column("raw_fields", JSONB, nullable=False),
        sa.Column("parse_status", sa.Text, nullable=False),
        sa.Column("reason_codes", JSONB, nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("row_number > 0", name="ck_salary_source_rows_number"),
        sa.CheckConstraint(
            "parse_status IN ('parsed', 'rejected')",
            name="ck_salary_source_rows_status",
        ),
        schema="salary_private",
    )
    op.create_table(
        "dk_lobby_salaries",
        sa.Column(
            "snapshot_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "salary_private.salary_snapshots.snapshot_id",
                name="fk_dk_lobby_salaries_snapshot",
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
        sa.Column("dk_id", sa.Text),
        sa.Column("name_raw", sa.Text),
        sa.Column("position_raw", sa.Text),
        sa.Column("roster_position_raw", sa.Text),
        sa.Column("team_raw", sa.Text),
        sa.Column("game_info_raw", sa.Text),
        sa.Column("avg_points_per_game", sa.Numeric(12, 4)),
        sa.Column("status_raw", sa.Text),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("row_number > 0", name="ck_dk_lobby_salaries_number"),
        sa.CheckConstraint(
            "row_status IN ('valid', 'rejected')",
            name="ck_dk_lobby_salaries_status",
        ),
        sa.CheckConstraint(
            "salary IS NULL OR salary >= 0",
            name="ck_dk_lobby_salaries_salary",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id", "parser_version", "row_number"],
            [
                "salary_private.salary_source_rows.artifact_id",
                "salary_private.salary_source_rows.parser_version",
                "salary_private.salary_source_rows.row_number",
            ],
            name="fk_dk_lobby_salaries_ledger",
            ondelete="RESTRICT",
        ),
        schema="salary_private",
    )
    op.create_index(
        "ix_dk_lobby_salaries_status",
        "dk_lobby_salaries",
        ["snapshot_id", "row_status"],
        schema="salary_private",
    )
    op.create_index(
        "ix_dk_lobby_salaries_dk_id",
        "dk_lobby_salaries",
        ["dk_id", "snapshot_id"],
        schema="salary_private",
    )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA salary_private FROM PUBLIC")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA salary_private FROM PUBLIC")
    apply_readonly_grant(op.get_bind())


def downgrade() -> None:
    op.drop_index(
        "ix_dk_lobby_salaries_dk_id",
        table_name="dk_lobby_salaries",
        schema="salary_private",
    )
    op.drop_index(
        "ix_dk_lobby_salaries_status",
        table_name="dk_lobby_salaries",
        schema="salary_private",
    )
    op.drop_table("dk_lobby_salaries", schema="salary_private")
    op.drop_index(
        "ix_salary_observations_load_run",
        table_name="salary_observations",
        schema="salary_private",
    )
    op.execute("DROP INDEX IF EXISTS salary_private.ix_salary_observations_snapshot_observed")
    op.execute("DROP INDEX IF EXISTS salary_private.ix_salary_observations_source_observed")
    op.drop_table("salary_observations", schema="salary_private")
    op.drop_table("salary_source_rows", schema="salary_private")
    op.drop_index(
        "ix_salary_snapshots_game_rules",
        table_name="salary_snapshots",
        schema="salary_private",
    )
    op.drop_index(
        "ix_salary_snapshots_draft_group",
        table_name="salary_snapshots",
        schema="salary_private",
    )
    op.drop_index(
        "ix_salary_snapshots_season_week",
        table_name="salary_snapshots",
        schema="salary_private",
    )
    op.drop_table("salary_snapshots", schema="salary_private")
    op.drop_table("salary_artifacts", schema="salary_private")
    op.execute("DROP SCHEMA IF EXISTS salary_private RESTRICT")
