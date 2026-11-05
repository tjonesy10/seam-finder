"""Pass B layout: package, Python version, and CI coverage."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_python_version_file_is_3_12():
    assert (ROOT / ".python-version").read_text().strip() == "3.12"


def test_web_package_is_installed_and_entrypoint_exists():
    text = (ROOT / "pyproject.toml").read_text()
    assert 'packages = ["loader", "web"]' in text
    for name in ("fastapi", "uvicorn", "jinja2", "pydantic-settings"):
        assert name in text
    from web.main import app, create_app

    assert app is not None
    assert callable(create_app)
    made = create_app("postgres://seam@127.0.0.1:9/seam_test")
    try:
        assert made.state.engine.url.drivername == "postgresql+psycopg"
    finally:
        made.state.engine.dispose()


def test_ci_ruff_checks_web():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "ruff check loader web tests migrations" in text


def test_no_render_config_committed():
    assert list(ROOT.rglob("render.yaml")) == []
    assert list(ROOT.rglob("render.yml")) == []


def test_blank_database_url_does_not_open_an_engine():
    from web.main import build_engine

    assert build_engine(None) is None
    assert build_engine("") is None
    assert build_engine("   ") is None


def test_app_engine_uses_psycopg(database_url):
    from web.main import app

    assert app.state.engine is not None
    assert app.state.engine.url.drivername == "postgresql+psycopg"
