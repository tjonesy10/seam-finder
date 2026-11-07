"""Allow private schedule raw and reference artifacts.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-07

"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_OLD = (
    "csv",
    "lobby_json",
    "rules_json",
    "html_gzip",
    "manifest",
    "mapping",
    "adapter_row_image",
    "rejected_body",
)
_NEW = _OLD + ("schedule_raw", "schedule_reference")


def _constraint(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{item}'" for item in values)
    return f"artifact_kind IN ({quoted})"


def upgrade() -> None:
    op.drop_constraint(
        "ck_salary_artifacts_kind",
        "salary_artifacts",
        schema="salary_private",
        type_="check",
    )
    op.create_check_constraint(
        "ck_salary_artifacts_kind",
        "salary_artifacts",
        _constraint(_NEW),
        schema="salary_private",
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM salary_private.salary_artifacts
        WHERE artifact_kind IN ('schedule_raw', 'schedule_reference')
        """
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
        _constraint(_OLD),
        schema="salary_private",
    )
