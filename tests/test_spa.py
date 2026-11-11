"""F009: SPA cutover, additive GET /api fields, privacy, and the attribution bundle."""

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
FORBIDDEN = (
    "salary_private",
    "dk_salary_unified",
    "dk_lobby_salaries",
    "dff_salaries",
    "dknfl_salaries",
)
API_PATHS = [
    "/",
    "/api",
    "/api/games",
    "/api/games/{game_id}",
    "/api/health",
    "/api/load-runs",
    "/api/player-week-stats",
    "/api/players",
    "/api/players/{gsis_id}",
    "/api/teams",
    "/api/teams/{team_abbr}",
    "/games",
    "/load-runs",
    "/players",
    "/stats",
    "/teams",
]


def _latest_refresh_label(engine) -> str:
    with engine.connect() as conn:
        finished = conn.execute(
            text(
                """
                SELECT finished_at FROM load_runs
                WHERE status = 'succeeded' AND finished_at IS NOT NULL
                ORDER BY finished_at DESC, id DESC
                LIMIT 1
                """
            )
        ).scalar_one()
    return finished.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S ET")


def test_api_root_footer_is_none_before_a_load(client):
    body = client.get("/api").json()
    assert body["last_refresh_et"] == "none"
    assert [item["dataset"] for item in body["datasets"]] == [
        "teams",
        "players",
        "games",
        "player_week_stats",
    ]
    assert {item["finished_at"] for item in body["datasets"]} == {"none"}


def test_api_root_footer_matches_the_html_clock(client, loaded, engine):
    body = client.get("/api").json()
    assert body["name"] == "Seam Finder"
    assert body["last_refresh_et"] == _latest_refresh_label(engine)
    assert datetime.strptime(body["last_refresh_et"], "%Y-%m-%d %H:%M:%S ET")
    assert [item["dataset"] for item in body["datasets"]] == [
        "teams",
        "players",
        "games",
        "player_week_stats",
    ]
    assert all(item["finished_at"].endswith(" ET") for item in body["datasets"])


@pytest.mark.parametrize("value", ["false", "TRUE", "1", "yes"])
def test_serve_spa_accepts_only_the_exact_true_string(client, monkeypatch, value):
    monkeypatch.setenv("SERVE_SPA", value)
    page = client.get("/teams")
    assert page.status_code == 200
    assert "<form" in page.text
    assert 'method="get"' in page.text
    assert "<table" in page.text


def test_unknown_page_stays_not_found_while_the_switch_is_off(client):
    response = client.get("/not-a-page")
    assert response.status_code == 404
    assert "Not found" in response.text
    assert "Traceback" not in response.text


def test_at10_spa_serves_the_shell_and_leaves_api_json(client, monkeypatch):
    monkeypatch.setenv("SERVE_SPA", "true")
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.headers["content-type"].startswith("application/json")
    assert health.json()["status"] == "ok"
    assert "<html" not in health.text.lower()

    teams = client.get("/api/teams")
    assert teams.status_code == 200
    assert teams.headers["content-type"].startswith("application/json")
    assert "data" in teams.json()
    assert "page" in teams.json()

    missing = client.get("/api/missing")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/json")
    assert missing.json() == {"error": {"code": "not_found", "message": "Not found"}}

    page = client.get("/teams")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert 'id="root"' in page.text
    cache = page.headers["cache-control"]
    assert "immutable" not in cache
    assert "max-age=31536000" not in cache
    bad = client.get("/games", params={"week": "abc"})
    assert bad.status_code == 200
    assert 'id="root"' in bad.text
    assert client.get("/api/games", params={"week": "abc"}).status_code == 400

    assets = list((FRONTEND / "dist" / "assets").iterdir())
    assert assets
    served = client.get(f"/assets/{assets[0].name}")
    assert served.status_code == 200
    assert served.headers["cache-control"] == "public, max-age=31536000, immutable"
    unknown = client.get("/not-a-page")
    assert unknown.status_code == 200
    assert 'id="root"' in unknown.text


def test_at11_missing_build_fails_clearly_and_the_switch_restores_jinja(client, monkeypatch, tmp_path):
    monkeypatch.setenv("SERVE_SPA", "true")
    monkeypatch.setattr("web.main.SPA_DIST", tmp_path / "missing")
    missing = client.get("/")
    assert missing.status_code == 503
    assert "The frontend build is missing." in missing.text
    assert "Traceback" not in missing.text
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.headers["content-type"].startswith("application/json")

    monkeypatch.setenv("SERVE_SPA", "false")
    restored = client.get("/teams")
    assert restored.status_code == 200
    assert "<form" in restored.text
    assert 'method="get"' in restored.text
    assert "<table" in restored.text
    assert "The frontend build is missing." not in restored.text


def test_at12_routes_and_web_role_stay_on_the_public_allowlist(engine, monkeypatch):
    from loader.grants import PUBLIC_ALLOWLIST, apply_readonly_grant
    from web.main import app

    paths = sorted(route.path for route in app.routes if isinstance(route, APIRoute))
    assert paths == API_PATHS
    for path in paths:
        lowered = path.lower()
        assert "salary" not in lowered
        assert "slate" not in lowered
        assert "dknfl" not in lowered
        assert "dff" not in lowered
        assert "lobby" not in lowered
    assert PUBLIC_ALLOWLIST == (
        "teams",
        "players",
        "games",
        "player_week_stats",
        "load_runs",
        "dk_classic_salaries",
    )

    role = "seam_web_f009"
    monkeypatch.setenv("READONLY_ROLE", role)
    with engine.begin() as conn:
        conn.execute(text(f"DROP ROLE IF EXISTS {role}"))
        conn.execute(text(f"CREATE ROLE {role}"))
        conn.execute(text(f"GRANT {role} TO CURRENT_USER"))
        apply_readonly_grant(conn)
    try:
        with engine.connect() as conn:
            conn.execute(text(f"SET ROLE {role}"))
            for table in ("teams", "players", "games", "player_week_stats", "load_runs"):
                conn.execute(text(f"SELECT count(*) FROM {table}"))
            for statement in (
                "SELECT count(*) FROM dk_classic_slate",
                "SELECT count(*) FROM salary_private.dk_lobby_salaries",
                "SELECT count(*) FROM salary_private.dk_salary_unified",
            ):
                with pytest.raises(DBAPIError):
                    conn.execute(text(statement))
                conn.rollback()
                conn.execute(text(f"SET ROLE {role}"))
            conn.execute(text("RESET ROLE"))
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"DROP OWNED BY {role}"))
            conn.execute(text(f"DROP ROLE IF EXISTS {role}"))


def test_at13_frontend_does_not_name_private_salary_data():
    roots = [
        FRONTEND / "src",
        FRONTEND / "e2e",
        FRONTEND / "dist",
        FRONTEND / "index.html",
        FRONTEND / "package.json",
        FRONTEND / "package-lock.json",
    ]
    for root in roots:
        paths = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
        for path in paths:
            text = path.read_text(errors="ignore")
            for name in FORBIDDEN:
                assert name not in text, f"{name} in {path}"
    client = (FRONTEND / "src" / "api.ts").read_text()
    found = set(re.findall(r'"(/api[^"]*)"', client))
    assert found == {
        "/api",
        "/api/teams",
        "/api/players",
        "/api/games",
        "/api/player-week-stats",
        "/api/load-runs",
    }


def test_attribution_bundle_matches_web_attribution():
    from web.attribution import ATTRIBUTION_LINKS, ATTRIBUTION_TEXT

    source = (FRONTEND / "src" / "attribution.ts").read_text()
    assert ATTRIBUTION_TEXT in source
    for link in ATTRIBUTION_LINKS:
        assert link["label"] in source
        assert link["url"] in source
    bundles = list((FRONTEND / "dist" / "assets").glob("*.js"))
    assert bundles, "frontend/dist is missing; run npm run build in frontend/"
    bundled = "\n".join(path.read_text(errors="ignore") for path in bundles)
    assert ATTRIBUTION_TEXT in bundled
    for link in ATTRIBUTION_LINKS:
        assert link["label"] in bundled
        assert link["url"] in bundled
    css = "\n".join(path.read_text(errors="ignore") for path in (FRONTEND / "dist").rglob("*.css"))
    html = (FRONTEND / "dist" / "index.html").read_text().lower()
    assert "<img" not in html
    assert "url(http" not in css
    assert "url(//" not in css


def test_at7_package_uses_the_named_libraries():
    pkg = json.loads((FRONTEND / "package.json").read_text())
    names = {**pkg["dependencies"], **pkg["devDependencies"]}
    for name in (
        "react",
        "react-dom",
        "typescript",
        "vite",
        "@tanstack/react-table",
        "@tanstack/react-virtual",
        "@tanstack/react-query",
        "@tanstack/react-router",
        "vitest",
        "@testing-library/react",
        "@playwright/test",
        "eslint",
    ):
        assert name in names
    assert "26" in pkg["engines"]["node"]
    joined = " ".join(names)
    for banned in ("@tanstack/react-start", "@tanstack/start", "next", "remix"):
        assert banned not in joined
    pages = (FRONTEND / "src" / "pages.tsx").read_text()
    frontend_tsx = " ".join(path.read_text() for path in (FRONTEND / "src").glob("*.tsx"))
    assert "DataTable" in frontend_tsx
    assert "useQuery" in pages
    assert (ROOT / ".nvmrc").read_text().strip() == "26"
    assert (FRONTEND / "package-lock.json").is_file()


def test_at14_ci_runs_node_and_both_api_modes():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert 'node-version: "26"' in workflow
    assert "npm ci" in workflow
    assert "npm run typecheck" in workflow
    assert "npm run lint" in workflow
    assert "npm test" in workflow
    assert "npm run build" in workflow
    assert "npm run e2e" in workflow
    assert "ruff check loader web tests migrations" in workflow
    assert "pytest tests/test_api.py" in workflow
    assert "SERVE_SPA=true pytest tests/test_api.py" in workflow
    assert "\n          pytest\n" in workflow
    assert "gitleaks detect" in workflow
