"""Store operator-supplied schedule authority bytes and read them back.

Installation keeps the supplied bytes. It does not read ``public.games``,
invent an inventory, emit a receipt, select ``DK_SCHEDULE_AUTHORITY_SHA256``,
or certify a season. The private migration flag must be exactly ``true``.
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from loader.salary_private import OBJECT_LIMIT, PrivateWriteError
from loader.schedule_proof import _artifact, _insert_control, sha256_bytes
from loader.url import normalize_database_url

_REVIEWED_TYPES = frozenset(
    {"authority_root_v1", "season_inventory_v1", "schedule_coverage_v1"}
)
_RECEIPT_TYPE = "schedule_source_receipt_v1"


def _fail(reason: str) -> int:
    print(reason, file=sys.stderr)
    return 1


def _review_reason(payload: dict) -> str | None:
    document_type = payload.get("document_type")
    if document_type == _RECEIPT_TYPE:
        return "receipt_not_installable"
    if document_type not in _REVIEWED_TYPES:
        return "document_type_unsupported"
    if document_type == "authority_root_v1":
        for field in ("approved_by", "approved_at", "approval_reference"):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                return "document_unreviewed"
        if not payload.get("season_inventories") or not payload.get("coverage_documents"):
            return "document_unreviewed"
        return None
    review = payload.get("review")
    if not isinstance(review, dict):
        return "document_unreviewed"
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        return "document_unreviewed"
    return None


def classify_reviewed_bytes(body: bytes, *, reference: bool) -> tuple[str, str, str] | str:
    """Return ``(document_type, kind, media_type)`` or a reason code."""
    if reference:
        return "schedule_reference", "schedule_reference", "application/octet-stream"
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return "document_type_unsupported"
    if not isinstance(payload, dict):
        return "document_type_unsupported"
    reason = _review_reason(payload)
    if reason is not None:
        return reason
    return str(payload["document_type"]), "manifest", "application/json"


def install_reviewed_bytes(conn, body: bytes, *, kind: str, media_type: str) -> int:
    return _insert_control(
        conn,
        body=body,
        kind=kind,
        media_type=media_type,
        stored_at=datetime.now(UTC),
    )


def readback_bytes(conn, digest: str) -> bytes | None:
    found = _artifact(conn, digest)
    if found is None:
        return None
    return found[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install reviewed schedule-authority bytes")
    parser.add_argument("--file", required=True)
    parser.add_argument("--expect-sha")
    parser.add_argument("--reference", action="store_true")
    args = parser.parse_args(argv)
    if os.environ.get("SALARY_PRIVATE_MIGRATION") != "true":
        return _fail("migration_gate_closed")
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        return _fail("database_unreachable")
    with open(args.file, "rb") as handle:
        body = handle.read()
    if len(body) > OBJECT_LIMIT:
        return _fail("storage_guard_object")
    digest = sha256_bytes(body)
    if args.expect_sha is not None and args.expect_sha != digest:
        return _fail("sha_mismatch")
    classified = classify_reviewed_bytes(body, reference=args.reference)
    if isinstance(classified, str):
        return _fail(classified)
    document_type, kind, media_type = classified
    engine = create_engine(normalize_database_url(database_url), pool_pre_ping=True)
    try:
        with engine.connect() as probe:
            present = probe.execute(
                text("SELECT to_regclass('salary_private.salary_artifacts')")
            ).scalar()
        if present is None:
            return _fail("private_schema_absent")
        with engine.begin() as conn:
            artifact_id = install_reviewed_bytes(conn, body, kind=kind, media_type=media_type)
        with engine.connect() as conn:
            stored = readback_bytes(conn, digest)
    except (OSError, SQLAlchemyError, PrivateWriteError):
        return _fail("install_failed")
    finally:
        engine.dispose()
    if stored != body:
        return _fail("readback_mismatch")
    print(
        f"installed sha256={digest} artifact_id={artifact_id} "
        f"document_type={document_type} kind={kind}"
    )
    print("installation_is_not_season_certification")
    print("pin_not_set")
    return 0


if __name__ == "__main__":
    sys.exit(main())
