"""Gzip getcontests artifacts at rest and raise their decoded cap.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-11

PR #38 also uses revision id 0009 on another branch and will renumber.
This revision is the one that revises 0008 for the discovery cap.

PRODUCTION MIGRATION. Refresh runs alembic upgrade head when the private
flag is on. Merging applies this to production and needs Cosmo's approval.

No grant changes. Legacy bodies are not rewritten. Downgrade refuses when a
gzip row, a lobby_discovery_json row, or a decoded body over 5 MiB exists,
and it deletes nothing.
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_KINDS = (
    "csv",
    "lobby_json",
    "rules_json",
    "html_gzip",
    "manifest",
    "mapping",
    "adapter_row_image",
    "rejected_body",
    "schedule_raw",
    "schedule_reference",
    "lobby_discovery_json",
)
_PRIOR_KINDS = _KINDS[:-1]

_BODY_CHECK = """
byte_count = decoded_bytes
AND sha256 = decoded_sha256
AND compressed_bytes = octet_length(body)
AND decoded_bytes >= 0
AND compressed_bytes >= 0
AND decoded_sha256 ~ '^[0-9a-f]{64}$'
AND compressed_sha256 ~ '^[0-9a-f]{64}$'
AND (
    (encoding = 'identity' AND compressed_bytes = decoded_bytes AND compressed_sha256 = decoded_sha256)
    OR (encoding = 'gzip' AND compressed_bytes < decoded_bytes)
)
AND (
    (artifact_kind = 'lobby_discovery_json' AND decoded_bytes <= 33554432)
    OR (artifact_kind <> 'lobby_discovery_json' AND decoded_bytes <= 5242880)
)
"""

_PRIOR_BODY_CHECK = (
    "byte_count = octet_length(body) AND byte_count >= 0 AND octet_length(body) <= 5242880"
)


def _kind_sql(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{item}'" for item in values)
    return f"artifact_kind IN ({quoted})"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE salary_private.salary_artifacts
            ADD COLUMN encoding text,
            ADD COLUMN decoded_sha256 text,
            ADD COLUMN decoded_bytes integer,
            ADD COLUMN compressed_sha256 text,
            ADD COLUMN compressed_bytes integer
        """
    )
    op.execute(
        """
        UPDATE salary_private.salary_artifacts
        SET encoding = 'identity',
            decoded_sha256 = sha256,
            decoded_bytes = byte_count,
            compressed_sha256 = sha256,
            compressed_bytes = byte_count
        """
    )
    op.execute(
        """
        ALTER TABLE salary_private.salary_artifacts
            ALTER COLUMN encoding SET NOT NULL,
            ALTER COLUMN decoded_sha256 SET NOT NULL,
            ALTER COLUMN decoded_bytes SET NOT NULL,
            ALTER COLUMN compressed_sha256 SET NOT NULL,
            ALTER COLUMN compressed_bytes SET NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE salary_private.salary_artifacts
            ADD CONSTRAINT ck_salary_artifacts_encoding
            CHECK (encoding IN ('identity', 'gzip'))
        """
    )
    op.drop_constraint(
        "ck_salary_artifacts_body",
        "salary_artifacts",
        schema="salary_private",
        type_="check",
    )
    op.create_check_constraint(
        "ck_salary_artifacts_body",
        "salary_artifacts",
        _BODY_CHECK,
        schema="salary_private",
    )
    op.drop_constraint(
        "ck_salary_artifacts_kind",
        "salary_artifacts",
        schema="salary_private",
        type_="check",
    )
    op.create_check_constraint(
        "ck_salary_artifacts_kind",
        "salary_artifacts",
        _kind_sql(_KINDS),
        schema="salary_private",
    )
    op.execute(
        """
        CREATE FUNCTION salary_private.fill_identity_encoding()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.encoding IS NULL THEN
                NEW.encoding := 'identity';
                NEW.decoded_sha256 := NEW.sha256;
                NEW.decoded_bytes := NEW.byte_count;
                NEW.compressed_sha256 := NEW.sha256;
                NEW.compressed_bytes := NEW.byte_count;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER salary_artifacts_identity_encoding
        BEFORE INSERT ON salary_private.salary_artifacts
        FOR EACH ROW
        EXECUTE FUNCTION salary_private.fill_identity_encoding()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM salary_private.salary_artifacts
                WHERE encoding = 'gzip'
                   OR artifact_kind = 'lobby_discovery_json'
                   OR decoded_bytes > 5242880
            ) THEN
                RAISE EXCEPTION
                    'downgrade refused: gzip rows, lobby_discovery_json rows, or decoded bodies over 5242880 bytes exist; nothing was deleted';
            END IF;
        END $$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS salary_artifacts_identity_encoding ON salary_private.salary_artifacts"
    )
    op.execute("DROP FUNCTION IF EXISTS salary_private.fill_identity_encoding()")
    op.drop_constraint(
        "ck_salary_artifacts_body",
        "salary_artifacts",
        schema="salary_private",
        type_="check",
    )
    op.execute(
        "ALTER TABLE salary_private.salary_artifacts DROP CONSTRAINT IF EXISTS ck_salary_artifacts_encoding"
    )
    op.execute(
        """
        ALTER TABLE salary_private.salary_artifacts
            DROP COLUMN encoding,
            DROP COLUMN decoded_sha256,
            DROP COLUMN decoded_bytes,
            DROP COLUMN compressed_sha256,
            DROP COLUMN compressed_bytes
        """
    )
    op.create_check_constraint(
        "ck_salary_artifacts_body",
        "salary_artifacts",
        _PRIOR_BODY_CHECK,
        schema="salary_private",
    )
    op.drop_constraint(
        "ck_salary_artifacts_kind",
        "salary_artifacts",
        schema="salary_private",
        type_="check",
    )
    op.create_check_constraint(
        "ck_salary_artifacts_kind",
        "salary_artifacts",
        _kind_sql(_PRIOR_KINDS),
        schema="salary_private",
    )
