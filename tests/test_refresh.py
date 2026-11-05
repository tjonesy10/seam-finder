import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFRESH = ROOT / ".github" / "workflows" / "refresh.yml"
PASSWORD_URL = re.compile(r"postgres(?:ql)?://[^\s:]+:[^\s@]+@", re.IGNORECASE)
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache"}


def test_refresh_workflow_schedule_and_dispatch():
    text = REFRESH.read_text()
    assert 'cron: "0 11 * * *"' in text
    assert "workflow_dispatch" in text
    assert "seasons:" in text
    assert "secrets.DATABASE_URL" in text
    assert "alembic upgrade head" in text
    assert "--trigger schedule" in text
    assert "--trigger manual" in text
    assert "python -m loader" in text
    assert "continue-on-error" not in text
    assert "|| true" not in text
    for line in text.splitlines():
        lowered = line.lower()
        assert not ("echo" in lowered and "database_url" in lowered), line
    assert "printenv" not in text


def test_at26_no_secrets_in_repo():
    gitignore = (ROOT / ".gitignore").read_text().splitlines()
    assert ".env" in gitignore
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".env"],
        cwd=ROOT,
        check=False,
    )
    assert ignored.returncode == 0
    example_ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".env.example"],
        cwd=ROOT,
        check=False,
    )
    assert example_ignored.returncode != 0
    example = (ROOT / ".env.example").read_text()
    assert "DATABASE_URL=<postgres connection url>" in example
    assert "READONLY_ROLE=<read-only role name>" in example
    assert "://" not in example
    assert PASSWORD_URL.search(example) is None

    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix in {".parquet", ".pyc"}:
            continue
        text = path.read_text(errors="ignore")
        match = PASSWORD_URL.search(text)
        assert match is None, f"{path}: {match.group(0)}"

    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        for line in path.read_text().splitlines():
            lowered = line.lower()
            assert not ("echo" in lowered and "database_url" in lowered), line
        assert "printenv" not in path.read_text()

    binary = shutil.which("gitleaks")
    assert binary, "gitleaks is not installed"
    scan = subprocess.run(
        [binary, "detect", "--source", str(ROOT), "--redact", "--log-opts=--all", "--no-banner"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert scan.returncode == 0, scan.stdout + scan.stderr
