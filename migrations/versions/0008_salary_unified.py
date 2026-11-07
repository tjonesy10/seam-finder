"""Private unified salary selection.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-07

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from loader.grants import apply_readonly_grant

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "salary_interpretations",
        sa.Column("interpretation_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "snapshot_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "salary_private.salary_snapshots.snapshot_id",
                name="fk_salary_interpretations_snapshot",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer),
        sa.Column("mapping_version", sa.Text, nullable=False),
        sa.Column("evidence_sha256", sa.Text, nullable=False),
        sa.Column(
            "evidence_artifact_id",
            sa.BigInteger,
            sa.ForeignKey(
                "salary_private.salary_artifacts.artifact_id",
                name="fk_salary_interpretations_evidence",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("entity_key", sa.Text),
        sa.Column(
            "gsis_id",
            sa.Text,
            sa.ForeignKey("players.gsis_id", name="fk_salary_interpretations_gsis", ondelete="RESTRICT"),
        ),
        sa.Column(
            "team_abbr",
            sa.Text,
            sa.ForeignKey("teams.team_abbr", name="fk_salary_interpretations_team", ondelete="RESTRICT"),
        ),
        sa.Column(
            "game_id",
            sa.Text,
            sa.ForeignKey("games.game_id", name="fk_salary_interpretations_game", ondelete="RESTRICT"),
        ),
        sa.Column("canonical_slate_key", sa.Text),
        sa.Column("slate_revision_sha256", sa.Text),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column("details", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('verified', 'unresolved', 'ambiguous', 'rejected', 'legacy_unknown')",
            name="ck_salary_interpretations_status",
        ),
        sa.CheckConstraint(
            "row_number IS NULL OR row_number > 0",
            name="ck_salary_interpretations_row",
        ),
        schema="salary_private",
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_salary_interpretations_row
        ON salary_private.salary_interpretations
        (snapshot_id, row_number, mapping_version, evidence_sha256)
        WHERE row_number IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_salary_interpretations_slate
        ON salary_private.salary_interpretations
        (snapshot_id, mapping_version, evidence_sha256)
        WHERE row_number IS NULL
        """
    )
    op.create_index(
        "ix_salary_interpretations_slate",
        "salary_interpretations",
        ["canonical_slate_key", "slate_revision_sha256"],
        schema="salary_private",
    )
    op.create_index(
        "ix_salary_interpretations_entity",
        "salary_interpretations",
        ["entity_key"],
        schema="salary_private",
    )
    op.create_table(
        "salary_selection_batches",
        sa.Column("selection_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("selection_scope", sa.Text, nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mapping_version", sa.Text, nullable=False),
        sa.Column("input_sha256", sa.Text, nullable=False),
        sa.Column(
            "load_run_id",
            sa.BigInteger,
            sa.ForeignKey("load_runs.id", name="fk_salary_selection_batches_run", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", JSONB, nullable=False),
        sa.UniqueConstraint(
            "selection_scope",
            "cutoff_at",
            "mapping_version",
            "input_sha256",
            name="uq_salary_selection_batches_identity",
        ),
        schema="salary_private",
    )
    op.execute(
        """
        CREATE INDEX ix_salary_selection_batches_current
        ON salary_private.salary_selection_batches
        (selection_scope, committed_at DESC, selection_id DESC)
        """
    )
    op.create_table(
        "salary_selection_rows",
        sa.Column(
            "selection_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "salary_private.salary_selection_batches.selection_id",
                name="fk_salary_selection_rows_batch",
                ondelete="RESTRICT",
            ),
            primary_key=True,
        ),
        sa.Column(
            "snapshot_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "salary_private.salary_snapshots.snapshot_id",
                name="fk_salary_selection_rows_snapshot",
                ondelete="RESTRICT",
            ),
            primary_key=True,
        ),
        sa.Column("row_number", sa.Integer, primary_key=True),
        sa.Column(
            "interpretation_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "salary_private.salary_interpretations.interpretation_id",
                name="fk_salary_selection_rows_entity",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column(
            "slate_interpretation_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "salary_private.salary_interpretations.interpretation_id",
                name="fk_salary_selection_rows_slate",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column(
            "observation_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "salary_private.salary_observations.observation_id",
                name="fk_salary_selection_rows_observation",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column(
            "anchor_snapshot_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "salary_private.salary_snapshots.snapshot_id",
                name="fk_salary_selection_rows_anchor",
                ondelete="RESTRICT",
            ),
        ),
        sa.Column("canonical_slate_key", sa.Text),
        sa.Column("slate_revision_sha256", sa.Text),
        sa.Column("entity_key", sa.Text),
        sa.Column("is_selected", sa.Boolean, nullable=False),
        sa.Column("pool_ready", sa.Boolean, nullable=False),
        sa.Column("optimizer_ready", sa.Boolean, nullable=False),
        sa.Column("salary_selected", sa.Numeric(10, 2)),
        sa.Column("quality_flags", JSONB, nullable=False),
        sa.Column("alternative_refs", JSONB, nullable=False),
        schema="salary_private",
    )
    op.create_index(
        "ix_salary_selection_rows_slate",
        "salary_selection_rows",
        ["selection_id", "canonical_slate_key", "slate_revision_sha256"],
        schema="salary_private",
    )
    op.create_index(
        "ix_salary_selection_rows_entity",
        "salary_selection_rows",
        ["selection_id", "entity_key"],
        schema="salary_private",
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_salary_selection_selected_entity
        ON salary_private.salary_selection_rows
        (selection_id, canonical_slate_key, slate_revision_sha256, entity_key)
        WHERE is_selected AND entity_key IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE VIEW salary_private.dk_salary_unified AS
        SELECT
            b.selection_id,
            b.selection_scope,
            (b.committed_at, b.selection_id) = (
                SELECT b2.committed_at, b2.selection_id
                FROM salary_private.salary_selection_batches b2
                WHERE b2.selection_scope = b.selection_scope
                ORDER BY b2.committed_at DESC, b2.selection_id DESC
                LIMIT 1
            ) AS is_current,
            b.cutoff_at,
            s.source,
            r.snapshot_id AS source_snapshot_id,
            r.row_number AS source_row_number,
            a.sha256 AS artifact_sha256,
            COALESCE((s.metadata->>'raw_retained')::boolean, true) AS raw_retained,
            r.observation_id,
            o.observed_at,
            o.fetched_at,
            si.effective_at,
            s.draft_group_id,
            s.season,
            s.season_type,
            s.week,
            r.canonical_slate_key,
            r.slate_revision_sha256,
            s.games,
            s.rules,
            r.entity_key,
            ei.gsis_id,
            ei.team_abbr,
            ei.game_id,
            CASE s.source
                WHEN 'dk_lobby' THEN lobby.dk_id
                WHEN 'dknfl' THEN dknfl.dk_id
                WHEN 'f004_adapter' THEN r.quality_flags #>> '{native,dk_id}'
                ELSE NULL
            END AS dk_id,
            CASE s.source WHEN 'dff' THEN dff.dff_player_id ELSE NULL END AS dff_player_id,
            CASE s.source
                WHEN 'dk_lobby' THEN lobby.salary
                WHEN 'dff' THEN dff.salary
                WHEN 'dknfl' THEN dknfl.salary
                WHEN 'f003_adapter' THEN NULLIF(r.quality_flags #>> '{native,salary}', '')::numeric
                WHEN 'f004_adapter' THEN NULLIF(r.quality_flags #>> '{native,salary}', '')::numeric
                ELSE NULL
            END AS salary_source,
            r.salary_selected,
            CASE s.source
                WHEN 'dk_lobby' THEN lobby.roster_position_raw
                WHEN 'dknfl' THEN dknfl.roster_position_raw
                ELSE r.quality_flags #>> '{native,roster_position_raw}'
            END AS roster_position_raw,
            s.source_pool_kind,
            r.anchor_snapshot_id,
            r.is_selected,
            r.pool_ready,
            r.optimizer_ready,
            r.quality_flags,
            r.alternative_refs,
            s.parser_version,
            b.mapping_version,
            COALESCE(ei.evidence_sha256, si.evidence_sha256) AS evidence_sha256,
            o.source_url,
            o.original_path,
            CASE s.source
                WHEN 'dff' THEN 'Salary/projection subset via Daily Fantasy Fuel (dailyfantasyfuel.com). Not affiliated with DraftKings.'
                WHEN 'dknfl' THEN 'Archived DraftKings salary export via pureslurp/DKNFL (GitHub). Not affiliated with DraftKings.'
                WHEN 'f004_adapter' THEN 'Owner-supplied DraftKings Classic export. Not affiliated with DraftKings.'
                WHEN 'dk_lobby' THEN 'Unauthenticated DraftKings Classic lobby capture (private experiment). Not affiliated with DraftKings.'
                WHEN 'f003_adapter' THEN 'Historical DraftKings Classic salaries and points via RotoGuru (rotoguru1.com). Not affiliated with DraftKings.'
                ELSE NULL
            END AS attribution
        FROM salary_private.salary_selection_rows r
        JOIN salary_private.salary_selection_batches b ON b.selection_id = r.selection_id
        JOIN salary_private.salary_snapshots s ON s.snapshot_id = r.snapshot_id
        JOIN salary_private.salary_artifacts a ON a.artifact_id = s.artifact_id
        LEFT JOIN salary_private.salary_observations o ON o.observation_id = r.observation_id
        LEFT JOIN salary_private.salary_interpretations ei ON ei.interpretation_id = r.interpretation_id
        LEFT JOIN salary_private.salary_interpretations si ON si.interpretation_id = r.slate_interpretation_id
        LEFT JOIN salary_private.dk_lobby_salaries lobby
            ON s.source = 'dk_lobby' AND lobby.snapshot_id = r.snapshot_id AND lobby.row_number = r.row_number
        LEFT JOIN salary_private.dff_salaries dff
            ON s.source = 'dff' AND dff.snapshot_id = r.snapshot_id AND dff.row_number = r.row_number
        LEFT JOIN salary_private.dknfl_salaries dknfl
            ON s.source = 'dknfl' AND dknfl.snapshot_id = r.snapshot_id AND dknfl.row_number = r.row_number
        """
    )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA salary_private FROM PUBLIC")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA salary_private FROM PUBLIC")
    apply_readonly_grant(op.get_bind())


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS salary_private.dk_salary_unified")
    op.execute("DROP INDEX IF EXISTS salary_private.uq_salary_selection_selected_entity")
    op.drop_index(
        "ix_salary_selection_rows_entity",
        table_name="salary_selection_rows",
        schema="salary_private",
    )
    op.drop_index(
        "ix_salary_selection_rows_slate",
        table_name="salary_selection_rows",
        schema="salary_private",
    )
    op.drop_table("salary_selection_rows", schema="salary_private")
    op.execute("DROP INDEX IF EXISTS salary_private.ix_salary_selection_batches_current")
    op.drop_table("salary_selection_batches", schema="salary_private")
    op.drop_index(
        "ix_salary_interpretations_entity",
        table_name="salary_interpretations",
        schema="salary_private",
    )
    op.drop_index(
        "ix_salary_interpretations_slate",
        table_name="salary_interpretations",
        schema="salary_private",
    )
    op.execute("DROP INDEX IF EXISTS salary_private.uq_salary_interpretations_slate")
    op.execute("DROP INDEX IF EXISTS salary_private.uq_salary_interpretations_row")
    op.drop_table("salary_interpretations", schema="salary_private")
