"""Workflow bindings and reviewed authority installation. No live pin or season."""

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from loader.migrate import upgrade_target
from loader.schedule_authority import main
from loader.schedule_proof import (
    AUTHORITY_ENV,
    canonical_bytes,
    maybe_emit_schedule_receipt,
    sha256_bytes,
)

ROOT = Path(__file__).resolve().parents[1]
MAIN = "6417cd46f064abcb5a66b947d4204516ca75188f"


def _step(workflow: str, name: str) -> str:
    lines = workflow.splitlines()
    start = lines.index(f"      - name: {name}")
    block = []
    for line in lines[start + 1 :]:
        if line.startswith("      - name:"):
            break
        block.append(line)
    return "\n".join(block)


def _binding(block: str, name: str) -> str:
    prefix = f"          {name}: "
    found = [line for line in block.splitlines() if line.startswith(prefix)]
    assert len(found) == 1
    return found[0][len(prefix) :]


def test_refresh_load_binds_receipt_env_without_values():
    workflow = (ROOT / ".github" / "workflows" / "refresh.yml").read_text()
    load = _step(workflow, "Load")
    assert _binding(load, "SALARY_PRIVATE_MIGRATION") == "${{ vars.SALARY_PRIVATE_MIGRATION }}"
    assert _binding(load, "DK_SCHEDULE_AUTHORITY_SHA256") == "${{ vars.DK_SCHEDULE_AUTHORITY_SHA256 }}"
    assert "true" not in _binding(load, "SALARY_PRIVATE_MIGRATION")
    for line in load.splitlines():
        lowered = line.lower()
        assert not ("echo" in lowered and "database_url" in lowered)
        assert not ("echo" in lowered and "dk_schedule_authority_sha256" in lowered)
    migrate = _step(workflow, "Migrate")
    assert _binding(migrate, "SALARY_PRIVATE_MIGRATION") == "${{ vars.SALARY_PRIVATE_MIGRATION }}"


def test_capture_binds_authority_pin_and_stays_default_off():
    workflow = (ROOT / ".github" / "workflows" / "dk-lobby-capture.yml").read_text()
    assert "vars.DK_LOBBY_CAPTURE_ENABLED == 'true'" in workflow
    assert 'DK_LOBBY_CAPTURE_ENABLED: "true"' not in workflow
    capture = _step(workflow, "Capture")
    assert _binding(capture, "DK_SCHEDULE_AUTHORITY_SHA256") == "${{ vars.DK_SCHEDULE_AUTHORITY_SHA256 }}"
    for line in capture.splitlines():
        lowered = line.lower()
        assert "database_url" not in lowered or "secrets.database_url" in lowered
        assert "dk_schedule_authority_sha256" not in lowered or "vars.dk_schedule_authority_sha256" in lowered
    assert workflow.index("capture_schedule_enabled") < workflow.index("python -m loader.pipeline")


def test_f004_workflow_is_unchanged_from_main():
    current = (ROOT / ".github" / "workflows" / "dk-classic-slate.yml").read_text()
    committed = subprocess.check_output(
        ["git", "show", f"{MAIN}:.github/workflows/dk-classic-slate.yml"],
        cwd=ROOT,
        text=True,
    )
    assert current == committed
    assert "DK_SCHEDULE_AUTHORITY_SHA256" not in committed
    assert "scheduled" in committed


def test_one_alembic_head_and_flag_off_targets():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == ["0010"]
    assert script.get_revision("0010").down_revision == "0009"
    assert script.get_revision("0009").down_revision == "0008"
    assert script.get_revision("0008").down_revision == "0007"
    assert script.get_revision("0007").down_revision == "0006"
    assert script.get_revision("0006").down_revision == "0005"
    assert upgrade_target(None, None) == "0003"
    assert upgrade_target("0005", None) == "0005"
    assert upgrade_target("0008", None) == "0008"
    assert upgrade_target("0005", "TRUE") == "0005"
    assert upgrade_target("0005", "true") == "head"


def test_receipt_emission_is_default_off(monkeypatch):
    monkeypatch.delenv("SALARY_PRIVATE_MIGRATION", raising=False)
    monkeypatch.setenv(AUTHORITY_ENV, "ab" * 32)
    kwargs = {
        "run_id": 1,
        "season": 2099,
        "raw_body": b"synthetic",
        "media_type": "application/json",
        "source_url": "https://example.test/schedules",
        "source_version": "synthetic-version",
        "retrieved_at": datetime(2026, 11, 7, tzinfo=UTC),
    }
    assert maybe_emit_schedule_receipt(None, **kwargs) is False
    monkeypatch.setenv("SALARY_PRIVATE_MIGRATION", "TRUE")
    assert maybe_emit_schedule_receipt(None, **kwargs) is False
    monkeypatch.setenv("SALARY_PRIVATE_MIGRATION", "true")
    monkeypatch.delenv(AUTHORITY_ENV, raising=False)
    assert maybe_emit_schedule_receipt(None, **kwargs) is False


def _root_bytes() -> bytes:
    return canonical_bytes(
        {
            "approval_reference": "synthetic-fixture-not-a-season-certification",
            "approved_at": "2026-11-07T17:00:00+00:00",
            "approved_by": "synthetic-operator",
            "coverage_documents": [{"coverage_sha256": "ab" * 32}],
            "document_type": "authority_root_v1",
            "schema_version": "authority_root_v1",
            "season_inventories": [{"inventory_sha256": "cd" * 32, "season": 2099}],
        }
    )


def _artifact_count(engine) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(text("SELECT count(*) FROM salary_private.salary_artifacts")).scalar_one()
        )


def _game_count(engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT count(*) FROM games")).scalar_one())


def test_install_refuses_closed_gate_and_unreviewed_or_receipt_bytes(tmp_path, monkeypatch, engine, capsys):
    path = tmp_path / "root.json"
    path.write_bytes(_root_bytes())
    games = _game_count(engine)
    artifacts = _artifact_count(engine)
    monkeypatch.delenv("SALARY_PRIVATE_MIGRATION", raising=False)
    assert main(["--file", str(path)]) == 1
    assert capsys.readouterr().err.strip() == "migration_gate_closed"
    monkeypatch.setenv("SALARY_PRIVATE_MIGRATION", "true")
    unreviewed = dict(json.loads(_root_bytes()))
    unreviewed.pop("approved_by")
    path.write_bytes(canonical_bytes(unreviewed))
    assert main(["--file", str(path)]) == 1
    assert capsys.readouterr().err.strip() == "document_unreviewed"
    path.write_bytes(canonical_bytes({"document_type": "schedule_source_receipt_v1", "schema_version": "schedule_source_receipt_v1"}))
    assert main(["--file", str(path)]) == 1
    assert capsys.readouterr().err.strip() == "receipt_not_installable"
    path.write_bytes(_root_bytes())
    assert main(["--file", str(path), "--expect-sha", "00" * 32]) == 1
    assert capsys.readouterr().err.strip() == "sha_mismatch"
    assert _game_count(engine) == games
    assert _artifact_count(engine) == artifacts


def test_install_readback_of_synthetic_reviewed_root_does_not_certify(tmp_path, monkeypatch, engine, capsys, database_url):
    path = tmp_path / "root.json"
    body = _root_bytes()
    path.write_bytes(body)
    games = _game_count(engine)
    monkeypatch.setenv("SALARY_PRIVATE_MIGRATION", "true")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.delenv(AUTHORITY_ENV, raising=False)
    assert main(["--file", str(path), "--expect-sha", sha256_bytes(body)]) == 0
    out = capsys.readouterr().out
    assert f"sha256={sha256_bytes(body)}" in out
    assert "installation_is_not_season_certification" in out
    assert "pin_not_set" in out
    assert database_url not in out
    assert "synthetic-operator" not in out
    with engine.connect() as conn:
        stored = conn.execute(
            text(
                """
                SELECT body, artifact_kind FROM salary_private.salary_artifacts
                WHERE source = 'control' AND sha256 = :sha
                """
            ),
            {"sha": sha256_bytes(body)},
        ).one()
    assert bytes(stored.body) == body
    assert stored.artifact_kind == "manifest"
    assert _game_count(engine) == games
    assert os.environ.get(AUTHORITY_ENV) is None
    assert main(["--file", str(path)]) == 0
    again = capsys.readouterr().out
    assert again.splitlines()[0] == out.splitlines()[0]


def test_install_refuses_when_private_schema_is_absent(tmp_path, monkeypatch, database_url, capsys):
    name = "seam_authority_absent"
    admin = create_engine(database_url)
    path = tmp_path / "root.json"
    path.write_bytes(_root_bytes())
    try:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {name}"))
            conn.execute(text(f"CREATE DATABASE {name}"))
        gated = make_url(database_url).set(database=name).render_as_string(hide_password=False)
        monkeypatch.setenv("SALARY_PRIVATE_MIGRATION", "true")
        monkeypatch.setenv("DATABASE_URL", gated)
        assert main(["--file", str(path)]) == 1
        captured = capsys.readouterr()
        assert captured.err.strip() == "private_schema_absent"
        assert "postgres" not in captured.err.lower()
        assert gated not in captured.err
    finally:
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {name}"))
        admin.dispose()
