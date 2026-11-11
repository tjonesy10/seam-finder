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
    ArtifactKind,
    decode_stored_body,
    encode_discovery,
    encoded_growth_block,
    sha256_bytes,
    storage_warning_percent,
    store_artifact,
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
    assert bytes(row.body) == stored
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
            body_check = conn.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_salary_artifacts_body'"
                )
            ).scalar()
            kind_check = conn.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_salary_artifacts_kind'"
                )
            ).scalar()
        assert columns is None
        assert version == "0008"
        assert "5242880" in body_check
        assert "33554432" not in body_check
        assert "lobby_discovery_json" not in kind_check
    finally:
        command.upgrade(cfg, "head")


def test_at31_kind_and_oversize_refuse_without_deleting(engine):
    cfg = Config("alembic.ini")
    kind_body = b"kind-only"
    kind_sha = sha256_bytes(kind_body)
    over_body = b"z"
    over_sha = sha256_bytes(b"decoded-over-five-mib")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO salary_private.salary_artifacts (
                    source, sha256, body, byte_count, media_type, artifact_kind,
                    stored_at, loaded_at, encoding, decoded_sha256, decoded_bytes,
                    compressed_sha256, compressed_bytes
                ) VALUES (
                    'control', :sha, :body, :count, 'application/json', 'lobby_discovery_json',
                    now(), now(), 'identity', :sha, :count, :sha, :count
                )
                """
            ),
            {"sha": kind_sha, "body": kind_body, "count": len(kind_body)},
        )
    with pytest.raises(Exception, match="downgrade refused"):
        command.downgrade(cfg, "0008")
    with engine.connect() as conn:
        still = conn.execute(
            text("SELECT count(*) FROM salary_private.salary_artifacts WHERE sha256 = :sha"),
            {"sha": kind_sha},
        ).scalar()
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert still == 1
    assert version == "0009"
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM salary_private.salary_artifacts WHERE sha256 = :sha"),
            {"sha": kind_sha},
        )
        conn.execute(
            text(
                """
                INSERT INTO salary_private.salary_artifacts (
                    source, sha256, body, byte_count, media_type, artifact_kind,
                    stored_at, loaded_at, encoding, decoded_sha256, decoded_bytes,
                    compressed_sha256, compressed_bytes
                ) VALUES (
                    'control', :sha, :body, 5242881, 'application/json', 'lobby_discovery_json',
                    now(), now(), 'gzip', :sha, 5242881, :compressed, 1
                )
                """
            ),
            {"sha": over_sha, "body": over_body, "compressed": sha256_bytes(over_body)},
        )
    with pytest.raises(Exception, match="downgrade refused"):
        command.downgrade(cfg, "0008")
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT encoding, decoded_bytes, octet_length(body) AS stored_len
                FROM salary_private.salary_artifacts WHERE sha256 = :sha
                """
            ),
            {"sha": over_sha},
        ).one()
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert row.encoding == "gzip"
    assert int(row.decoded_bytes) == 5242881
    assert int(row.stored_len) == 1
    assert version == "0009"
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM salary_private.salary_artifacts WHERE sha256 = :sha"),
            {"sha": over_sha},
        )


def test_at22_and_at25_identity_and_gzip_lengths(engine):
    with engine.connect() as conn:
        identity = store_discovery_artifact(
            conn,
            decoded=b"Q",
            media_type="application/json",
            stored_at=datetime.now(UTC),
            invocation_bytes=1,
        )
        gzipped = store_discovery_artifact(
            conn,
            decoded=b"a" * 4000,
            media_type="application/json",
            stored_at=datetime.now(UTC),
            invocation_bytes=4000,
        )
        rows = conn.execute(
            text(
                """
                SELECT artifact_id, encoding, body, sha256, byte_count, decoded_sha256,
                       decoded_bytes, compressed_sha256, compressed_bytes,
                       octet_length(body) AS stored_len
                FROM salary_private.salary_artifacts
                WHERE artifact_id IN (:identity, :gzipped)
                """
            ),
            {"identity": identity.artifact_id, "gzipped": gzipped.artifact_id},
        ).all()
    by_id = {row.artifact_id: row for row in rows}
    plain = by_id[identity.artifact_id]
    packed = by_id[gzipped.artifact_id]
    assert plain.encoding == "identity"
    assert bytes(plain.body) == b"Q"
    assert int(plain.compressed_bytes) == int(plain.decoded_bytes) == int(plain.stored_len)
    assert packed.encoding == "gzip"
    assert int(packed.compressed_bytes) == int(packed.stored_len)
    assert int(packed.compressed_bytes) < int(packed.decoded_bytes)
    for row in (plain, packed):
        assert row.decoded_sha256 and row.compressed_sha256
        assert row.sha256 == row.decoded_sha256
        assert int(row.byte_count) == int(row.decoded_bytes)


def test_at24_storage_limits_fail_closed_without_a_snapshot(engine):
    with engine.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM salary_private.salary_snapshots")).scalar()
    with engine.connect() as conn:
        kept = store_discovery_artifact(
            conn,
            decoded=b"a" * DISCOVERY_OBJECT_LIMIT,
            media_type="application/json",
            stored_at=datetime.now(UTC),
            invocation_bytes=DISCOVERY_OBJECT_LIMIT,
        )
        assert kept.byte_count == DISCOVERY_OBJECT_LIMIT
        with pytest.raises(Exception, match="storage_guard_object"):
            store_discovery_artifact(
                conn,
                decoded=b"b" * (DISCOVERY_OBJECT_LIMIT + 1),
                media_type="application/json",
                stored_at=datetime.now(UTC),
                invocation_bytes=DISCOVERY_OBJECT_LIMIT + 1,
            )
        csv_body = b"c" * OBJECT_LIMIT
        stored_csv = store_artifact(
            conn,
            body=csv_body,
            kind=ArtifactKind.CSV,
            media_type="text/csv",
            stored_at=datetime.now(UTC),
            invocation_bytes=len(csv_body),
        )
        assert stored_csv.byte_count == OBJECT_LIMIT
        with pytest.raises(Exception, match="storage_guard_object"):
            store_artifact(
                conn,
                body=b"d" * (OBJECT_LIMIT + 1),
                kind=ArtifactKind.CSV,
                media_type="text/csv",
                stored_at=datetime.now(UTC),
                invocation_bytes=OBJECT_LIMIT + 1,
            )
        after = conn.execute(text("SELECT count(*) FROM salary_private.salary_snapshots")).scalar()
    assert after == before


def test_at27_upgrade_backfills_legacy_rows_without_rewriting_bodies(engine):
    cfg = Config("alembic.ini")
    plain = b"pre-encoding-row"
    companion = b"html-gz-companion-bytes"
    plain_sha = sha256_bytes(plain)
    companion_sha = sha256_bytes(companion)
    try:
        command.downgrade(cfg, "0008")
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO salary_private.salary_artifacts (
                        source, sha256, body, byte_count, media_type, artifact_kind,
                        stored_at, loaded_at
                    ) VALUES
                        ('dk_lobby', :plain_sha, :plain, :plain_len, 'application/json', 'lobby_json', now(), now()),
                        ('dknfl', :companion_sha, :companion, :companion_len, 'application/gzip', 'html_gzip', now(), now())
                    """
                ),
                {
                    "plain_sha": plain_sha,
                    "plain": plain,
                    "plain_len": len(plain),
                    "companion_sha": companion_sha,
                    "companion": companion,
                    "companion_len": len(companion),
                },
            )
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT sha256, body, encoding, decoded_sha256, decoded_bytes,
                           compressed_sha256, compressed_bytes, media_type
                    FROM salary_private.salary_artifacts
                    WHERE sha256 IN (:plain_sha, :companion_sha)
                    """
                ),
                {"plain_sha": plain_sha, "companion_sha": companion_sha},
            ).all()
        by_sha = {row.sha256: row for row in rows}
        for digest, payload in ((plain_sha, plain), (companion_sha, companion)):
            row = by_sha[digest]
            assert bytes(row.body) == payload
            assert row.encoding == "identity"
            assert row.decoded_sha256 == digest
            assert int(row.decoded_bytes) == len(payload)
            assert row.compressed_sha256 == digest
            assert int(row.compressed_bytes) == len(payload)
        assert by_sha[companion_sha].media_type == "application/gzip"
    finally:
        command.upgrade(cfg, "head")


def test_at30_identity_trigger_and_explicit_writer(engine):
    payload = b"trigger-row"
    digest = sha256_bytes(payload)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO salary_private.salary_artifacts (
                    source, sha256, body, byte_count, media_type, artifact_kind,
                    stored_at, loaded_at, encoding, decoded_sha256, decoded_bytes
                ) VALUES (
                    'control', :sha, :body, :count, 'text/plain', 'manifest',
                    now(), now(), NULL, :sha, :count
                )
                """
            ),
            {"sha": digest, "body": payload, "count": len(payload)},
        )
        triggered = conn.execute(
            text(
                """
                SELECT encoding, decoded_sha256, decoded_bytes, compressed_sha256, compressed_bytes
                FROM salary_private.salary_artifacts WHERE sha256 = :sha
                """
            ),
            {"sha": digest},
        ).one()
    assert triggered.encoding == "identity"
    assert triggered.compressed_sha256 == triggered.decoded_sha256 == digest
    assert int(triggered.compressed_bytes) == int(triggered.decoded_bytes) == len(payload)
    explicit_body = b"explicit-gzip-ish"
    explicit_sha = sha256_bytes(explicit_body)
    compressed_sha = sha256_bytes(b"x")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO salary_private.salary_artifacts (
                    source, sha256, body, byte_count, media_type, artifact_kind,
                    stored_at, loaded_at, encoding, decoded_sha256, decoded_bytes,
                    compressed_sha256, compressed_bytes
                ) VALUES (
                    'control', :sha, :body, 2, 'application/json', 'lobby_discovery_json',
                    now(), now(), 'gzip', :sha, 2, :compressed_sha, 1
                )
                """
            ),
            {"sha": explicit_sha, "body": b"x", "compressed_sha": compressed_sha},
        )
        explicit = conn.execute(
            text(
                """
                SELECT encoding, body, decoded_bytes, compressed_bytes, compressed_sha256
                FROM salary_private.salary_artifacts WHERE sha256 = :sha
                """
            ),
            {"sha": explicit_sha},
        ).one()
    assert explicit.encoding == "gzip"
    assert bytes(explicit.body) == b"x"
    assert int(explicit.decoded_bytes) == 2
    assert int(explicit.compressed_bytes) == 1
    assert explicit.compressed_sha256 == compressed_sha
