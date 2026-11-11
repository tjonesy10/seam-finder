"""Discovery gzip-at-rest, revision 0009, and the storage guards.

Synthetic bytes only. No live DraftKings call and no production database.
"""

from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from loader.salary_private import (
    CUMULATIVE_LIMIT,
    DATABASE_LIMIT,
    DISCOVERY_OBJECT_LIMIT,
    OBJECT_LIMIT,
    decode_stored_body,
    encode_discovery,
    encoded_growth_block,
    sha256_bytes,
    storage_warning_percent,
    store_discovery_artifact,
)


def _constraint(engine, name: str) -> str:
    with engine.connect() as conn:
        found = conn.execute(
            text(
                """
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conname = :name
                """
            ),
            {"name": name},
        ).scalar()
    assert found
    return found


def _insert(conn, **fields):
    conn.execute(
        text(
            """
            INSERT INTO salary_private.salary_artifacts (
                source, sha256, body, byte_count, media_type, artifact_kind,
                stored_at, loaded_at, encoding, decoded_sha256, decoded_bytes,
                compressed_sha256, compressed_bytes
            ) VALUES (
                :source, :sha256, :body, :byte_count, :media_type, :kind,
                now(), now(), :encoding, :decoded_sha256, :decoded_bytes,
                :compressed_sha256, :compressed_bytes
            )
            """
        ),
        fields,
    )


def test_revision_0009_is_head_and_quotes_the_body_check(engine):
    script_head = _constraint(engine, "ck_salary_artifacts_body")
    assert "33554432" in script_head
    assert "5242880" in script_head
    assert "lobby_discovery_json" in script_head
    assert "octet_length(body)" in script_head
    kind = _constraint(engine, "ck_salary_artifacts_kind")
    assert "lobby_discovery_json" in kind
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_revision("0009").down_revision == "0008"
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == script.get_current_head()
    assert CUMULATIVE_LIMIT == 536_870_912
    assert DATABASE_LIMIT == 805_306_368
    assert DISCOVERY_OBJECT_LIMIT == 33_554_432
    assert OBJECT_LIMIT == 5_242_880


def test_legacy_insert_stays_identity_and_body_is_not_rewritten(engine):
    payload = b"legacy-html-gz-companion"
    digest = sha256_bytes(payload)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO salary_private.salary_artifacts (
                    source, sha256, body, byte_count, media_type, artifact_kind,
                    stored_at, loaded_at
                ) VALUES (
                    'dknfl', :sha, :body, :count, 'application/gzip', 'html_gzip',
                    now(), now()
                )
                """
            ),
            {"sha": digest, "body": payload, "count": len(payload)},
        )
        row = conn.execute(
            text(
                """
                SELECT body, encoding, decoded_sha256, decoded_bytes, compressed_bytes
                FROM salary_private.salary_artifacts
                WHERE sha256 = :sha
                """
            ),
            {"sha": digest},
        ).one()
    assert bytes(row.body) == payload
    assert row.encoding == "identity"
    assert row.decoded_sha256 == digest
    assert int(row.decoded_bytes) == len(payload)
    assert int(row.compressed_bytes) == len(payload)


def test_constraint_boundaries(engine):
    digest = "ab" * 32
    compressed = sha256_bytes(b"a")
    with engine.begin() as conn:
        _insert(
            conn,
            source="dk_lobby",
            sha256=digest,
            body=b"a",
            byte_count=33_554_432,
            media_type="application/json",
            kind="lobby_discovery_json",
            encoding="gzip",
            decoded_sha256=digest,
            decoded_bytes=33_554_432,
            compressed_sha256=compressed,
            compressed_bytes=1,
        )
    with engine.begin() as conn, pytest.raises(IntegrityError):
        _insert(
            conn,
            source="dk_lobby",
            sha256="cd" * 32,
            body=b"a",
            byte_count=33_554_433,
            media_type="application/json",
            kind="lobby_discovery_json",
            encoding="gzip",
            decoded_sha256="cd" * 32,
            decoded_bytes=33_554_433,
            compressed_sha256=compressed,
            compressed_bytes=1,
        )
    big = b"n" * (OBJECT_LIMIT + 1)
    big_sha = sha256_bytes(big)
    with engine.begin() as conn, pytest.raises(IntegrityError):
        _insert(
            conn,
            source="dk_lobby",
            sha256=big_sha,
            body=big,
            byte_count=len(big),
            media_type="text/csv",
            kind="csv",
            encoding="identity",
            decoded_sha256=big_sha,
            decoded_bytes=len(big),
            compressed_sha256=big_sha,
            compressed_bytes=len(big),
        )
    exact = b"m" * OBJECT_LIMIT
    exact_sha = sha256_bytes(exact)
    with engine.begin() as conn:
        _insert(
            conn,
            source="dff",
            sha256=exact_sha,
            body=exact,
            byte_count=len(exact),
            media_type="text/csv",
            kind="csv",
            encoding="identity",
            decoded_sha256=exact_sha,
            decoded_bytes=len(exact),
            compressed_sha256=exact_sha,
            compressed_bytes=len(exact),
        )


def test_gzip_and_identity_round_trip(engine):
    repetitive = b"a" * 4000
    encoding, stored, _decoded_sha, decoded_len, compressed_sha, compressed_len = encode_discovery(
        repetitive
    )
    assert encoding == "gzip"
    assert compressed_len < decoded_len
    assert sha256_bytes(stored) == compressed_sha
    assert decode_stored_body(stored, encoding) == repetitive
    encoding_i, stored_i, *_rest = encode_discovery(b"Q")
    assert encoding_i == "identity"
    assert stored_i == b"Q"
    with engine.connect() as conn:
        ref = store_discovery_artifact(
            conn,
            decoded=repetitive,
            media_type="application/json",
            stored_at=datetime.now(UTC),
            invocation_bytes=len(repetitive),
        )
    with engine.connect() as conn:
        again = store_discovery_artifact(
            conn,
            decoded=repetitive,
            media_type="application/json",
            stored_at=datetime.now(UTC),
            invocation_bytes=len(repetitive),
        )
    assert again.reused is True
    assert again.artifact_id == ref.artifact_id
    with engine.connect() as conn:
        count = conn.execute(
            text(
                """
                SELECT count(*) FROM salary_private.salary_artifacts
                WHERE artifact_kind = 'lobby_discovery_json'
                """
            )
        ).scalar()
        row = conn.execute(
            text(
                """
                SELECT body, encoding FROM salary_private.salary_artifacts
                WHERE artifact_id = :id
                """
            ),
            {"id": ref.artifact_id},
        ).one()
    assert count == 1
    assert decode_stored_body(bytes(row.body), row.encoding) == repetitive


def test_warning_percents_and_preflight(engine):
    assert storage_warning_percent(69, 100) is None
    assert storage_warning_percent(70, 100) == 70
    assert storage_warning_percent(85, 100) == 85
    assert storage_warning_percent(100, 100) is None
    with engine.connect() as conn:
        assert encoded_growth_block(conn, CUMULATIVE_LIMIT) is not None
        assert encoded_growth_block(conn, 10) is None


def test_downgrade_refuses_gzip_and_deletes_nothing(engine):
    cfg = Config("alembic.ini")
    with engine.connect() as conn:
        ref = store_discovery_artifact(
            conn,
            decoded=b"z" * 3000,
            media_type="application/json",
            stored_at=datetime.now(UTC),
            invocation_bytes=3000,
        )
    with engine.connect() as conn:
        before = conn.execute(
            text("SELECT count(*) FROM salary_private.salary_artifacts WHERE artifact_id = :id"),
            {"id": ref.artifact_id},
        ).scalar()
    assert before == 1
    with pytest.raises(Exception, match="downgrade refused"):
        command.downgrade(cfg, "0008")
    with engine.connect() as conn:
        still = conn.execute(
            text("SELECT body, encoding FROM salary_private.salary_artifacts WHERE artifact_id = :id"),
            {"id": ref.artifact_id},
        ).one()
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert still.encoding == "gzip"
    assert version == ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM salary_private.salary_artifacts WHERE artifact_id = :id"),
            {"id": ref.artifact_id},
        )
    try:
        command.downgrade(cfg, "0008")
        with engine.connect() as conn:
            columns = conn.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'salary_private'
                      AND table_name = 'salary_artifacts'
                      AND column_name = 'encoding'
                    """
                )
            ).scalar()
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert columns is None
        assert version == "0008"
    finally:
        command.upgrade(cfg, "head")
