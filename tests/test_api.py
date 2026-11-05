"""AT9-AT18: read API."""

import re
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text

from loader.run import run_load
from tests.conftest import FIXTURE_DIR

ADR_TEXT = (
    "Data: nflverse (nflverse-data), licensed CC BY 4.0. "
    "Changes: subset of columns, loaded into a database. "
    "Not affiliated with or endorsed by the NFL or nflverse. "
    "NFL data belong to their respective owners."
)
ADR_LINKS = (
    "https://github.com/nflverse/nflverse-data",
    "https://creativecommons.org/licenses/by/4.0/",
)


def test_at9_root_and_attribution(client):
    response = client.get("/api")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "charset=utf-8" in response.headers["content-type"]
    assert response.headers["cache-control"] == "public, max-age=300"
    body = response.json()
    assert body["name"] == "Seam Finder"
    assert body["attribution"]["text"] == ADR_TEXT
    assert [link["url"] for link in body["attribution"]["links"]] == list(ADR_LINKS)
    assert body["endpoints"] == [
        "/api/teams",
        "/api/players",
        "/api/games",
        "/api/player-week-stats",
        "/api/load-runs",
    ]


def test_at10_health(client, database_url, engine):
    empty = client.get("/api/health")
    assert empty.status_code == 200
    assert empty.json() == {"status": "ok", "database": "ok", "last_refresh": None}
    assert empty.headers["cache-control"] == "public, max-age=300"

    assert run_load(
        database_url=database_url,
        seasons=[2024, 2025],
        data_dir=FIXTURE_DIR,
        trigger="local",
    )
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT dataset, season, finished_at, source_version
                FROM load_runs
                WHERE status = 'succeeded' AND finished_at IS NOT NULL
                ORDER BY finished_at DESC, id DESC
                LIMIT 1
                """
            )
        ).mappings().one()
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    last = body["last_refresh"]
    assert last["dataset"] == row["dataset"]
    assert last["season"] == row["season"]
    assert last["source_version"] == row["source_version"]
    assert datetime.fromisoformat(last["finished_at"]) == row["finished_at"]


def test_at10_health_when_database_is_down():
    from web.main import create_app

    app = create_app("postgresql://seam@127.0.0.1:1/seam_test")
    try:
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.get("/api/health")
            page = client.get("/teams")
    finally:
        app.state.engine.dispose()
    assert response.status_code == 503
    assert response.json() == {
        "error": {"code": "service_unavailable", "message": "The database is unavailable."}
    }
    assert "Traceback" not in response.text
    assert page.status_code == 503
    assert "The database is unavailable." in page.text
    assert "Traceback" not in page.text
    assert ADR_TEXT in page.text


def test_at11_teams(client, loaded, engine):
    with engine.connect() as conn:
        total = conn.execute(text("SELECT count(*) FROM teams")).scalar_one()
        afc = conn.execute(
            text("SELECT count(*) FROM teams WHERE team_conf = 'AFC'")
        ).scalar_one()
    response = client.get("/api/teams")
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == {"limit": 50, "offset": 0, "total": total}
    assert len(body["data"]) == total
    assert {row["team_abbr"] for row in body["data"]}
    assert "loaded_at" in body["data"][0]
    assert "+" in body["data"][0]["loaded_at"]

    filtered = client.get("/api/teams", params={"conf": "AFC"})
    assert filtered.status_code == 200
    rows = filtered.json()["data"]
    assert filtered.json()["page"]["total"] == afc
    assert rows
    assert {row["team_conf"] for row in rows} == {"AFC"}
    folded = client.get("/api/teams", params={"conf": "afc"})
    assert folded.json()["page"]["total"] == afc

    cin = client.get("/api/teams/CIN")
    assert cin.status_code == 200
    assert cin.json()["data"]["team_abbr"] == "CIN"
    assert cin.json()["data"]["team_conf"] == "AFC"
    lower = client.get("/api/teams/cin")
    assert lower.status_code == 200
    assert lower.json()["data"]["team_abbr"] == "CIN"

    missing = client.get("/api/teams/XYZ")
    assert missing.status_code == 404
    assert missing.json() == {"error": {"code": "not_found", "message": "team not found"}}
    assert "Traceback" not in missing.text


def test_at12_players(client, loaded):
    found = client.get("/api/players", params={"q": "chase"})
    assert found.status_code == 200
    assert "00-0036900" in [row["gsis_id"] for row in found.json()["data"]]
    upper = client.get("/api/players", params={"q": "CHASE"})
    assert "00-0036900" in [row["gsis_id"] for row in upper.json()["data"]]
    wildcard = client.get("/api/players", params={"q": "ch%"})
    assert wildcard.status_code == 200
    assert "00-0036900" not in [row["gsis_id"] for row in wildcard.json()["data"]]

    narrowed = client.get("/api/players", params={"position": "wr", "team": "cin"})
    assert narrowed.status_code == 200
    rows = narrowed.json()["data"]
    assert rows
    assert all(row["position"] == "WR" and row["latest_team"] == "CIN" for row in rows)
    assert any(row["gsis_id"] == "00-0036900" for row in rows)

    active = client.get("/api/players", params={"status": "act"})
    assert any(row["gsis_id"] == "00-0036900" for row in active.json()["data"])
    assert all(row["status"] == "ACT" for row in active.json()["data"])

    one = client.get("/api/players/00-0036900")
    assert one.status_code == 200
    assert one.json()["data"]["gsis_id"] == "00-0036900"
    assert one.json()["data"]["display_name"] == "Ja'Marr Chase"
    assert "loaded_at" in one.json()["data"]

    missing = client.get("/api/players/00-0000000")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert "param" not in missing.json()["error"]

    short = client.get("/api/players", params={"q": "a"})
    assert short.status_code == 400
    assert short.json()["error"] == {
        "code": "invalid_parameter",
        "message": "q must be 2 to 50 characters",
        "param": "q",
    }


def test_at13_games(client, loaded):
    week = client.get("/api/games", params={"season": 2025, "week": 1})
    assert week.status_code == 200
    ids = [row["game_id"] for row in week.json()["data"]]
    assert "2025_01_DAL_PHI" in ids
    assert all(row["season"] == 2025 and row["week"] == 1 for row in week.json()["data"])
    gamedays = [row["gameday"] for row in week.json()["data"]]
    assert gamedays == sorted(gamedays)

    phi = client.get("/api/games", params={"team": "phi", "season": 2025})
    assert phi.status_code == 200
    phi_rows = phi.json()["data"]
    assert "2025_01_DAL_PHI" in [row["game_id"] for row in phi_rows]
    assert all("PHI" in {row["home_team"], row["away_team"]} for row in phi_rows)

    post = client.get("/api/games", params={"season_type": "post", "season": 2024})
    assert post.status_code == 200
    assert post.json()["data"]
    assert {row["season_type"] for row in post.json()["data"]} == {"POST"}
    assert "2024_19_LAC_HOU" in [row["game_id"] for row in post.json()["data"]]

    one = client.get("/api/games/2025_01_DAL_PHI")
    assert one.status_code == 200
    game = one.json()["data"]
    assert game["gameday"] == "2025-09-04"
    assert game["away_team"] == "DAL"
    assert game["away_score"] == 20
    assert game["home_team"] == "PHI"
    assert game["home_score"] == 24
    assert game["result"] == 4
    assert game["total"] == 44
    assert game["season_type"] == "REG"

    missing = client.get("/api/games/nope")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert "param" not in missing.json()["error"]


def test_at14_player_week_stats(client, loaded):
    cin = client.get(
        "/api/player-week-stats",
        params={"season": 2024, "week": 10, "team": "CIN"},
    )
    assert cin.status_code == 200
    chase = next(row for row in cin.json()["data"] if row["gsis_id"] == "00-0036900")
    assert chase["player_display_name"] == "Ja'Marr Chase"
    assert chase["game_id"] == "2024_10_CIN_BAL"
    assert chase["team"] == "CIN"
    assert chase["opponent_team"] == "BAL"
    assert chase["receptions"] == 11
    assert chase["targets"] == 17
    assert chase["receiving_yards"] == 264
    assert chase["receiving_tds"] == 3
    assert chase["fantasy_points"] == 44.4
    assert chase["fantasy_points_ppr"] == 55.4
    detail = client.get(
        "/api/player-week-stats",
        params={"player": "00-0036900", "season": 2024, "week": 10},
    )
    assert re.search(r'"fantasy_points":\s*44\.4\b', detail.text)
    assert re.search(r'"fantasy_points_ppr":\s*55\.4\b', detail.text)

    own = client.get(
        "/api/player-week-stats",
        params={"player": "00-0036900", "season": 2024},
    )
    rows = own.json()["data"]
    assert rows
    assert all(row["gsis_id"] == "00-0036900" for row in rows)
    points = [row["fantasy_points_ppr"] for row in rows]
    assert points == sorted(points, reverse=True)

    ordered = client.get(
        "/api/player-week-stats",
        params={"sort": "receiving_yards", "order": "desc", "season": 2024, "week": 10},
    )
    yards = [row["receiving_yards"] for row in ordered.json()["data"]]
    assert yards
    assert yards == sorted(yards, reverse=True)
    assert ordered.json()["data"][0]["gsis_id"] == "00-0036900"

    by_game = client.get(
        "/api/player-week-stats",
        params={"game_id": "2024_10_CIN_BAL"},
    )
    assert any(row["gsis_id"] == "00-0036900" for row in by_game.json()["data"])
    assert all(row["game_id"] == "2024_10_CIN_BAL" for row in by_game.json()["data"])

    post = client.get(
        "/api/player-week-stats",
        params={"season_type": "POST", "season": 2024},
    )
    assert post.status_code == 200
    assert post.json()["page"]["total"] == 0
    receivers = client.get(
        "/api/player-week-stats",
        params={"season": 2024, "week": 10, "position": "WR"},
    )
    assert any(row["gsis_id"] == "00-0036900" for row in receivers.json()["data"])
    assert all(row["position"] == "WR" and row["season_type"] == "REG" for row in receivers.json()["data"])
    assert all(row["gsis_id"] != "00-0032445" for row in receivers.json()["data"])


def test_at15_load_runs(client, engine):
    group = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO load_runs (
                    run_group, dataset, season, status, trigger,
                    started_at, finished_at, source_url
                ) VALUES (
                    :run_group, :dataset, 2024, :status, 'manual',
                    :started_at, :finished_at, 'https://example.invalid/games'
                )
                """
            ),
            [
                {
                    "run_group": group,
                    "dataset": "games",
                    "status": "failed",
                    "started_at": datetime(2024, 6, 1, tzinfo=UTC),
                    "finished_at": datetime(2024, 6, 1, 0, 1, tzinfo=UTC),
                },
                {
                    "run_group": group,
                    "dataset": "games",
                    "status": "failed",
                    "started_at": datetime(2024, 6, 2, tzinfo=UTC),
                    "finished_at": datetime(2024, 6, 2, 0, 1, tzinfo=UTC),
                },
                {
                    "run_group": group,
                    "dataset": "teams",
                    "status": "succeeded",
                    "started_at": datetime(2024, 6, 3, tzinfo=UTC),
                    "finished_at": datetime(2024, 6, 3, 0, 1, tzinfo=UTC),
                },
            ],
        )
    response = client.get("/api/load-runs", params={"status": "failed"})
    assert response.status_code == 200
    rows = response.json()["data"]
    assert rows
    assert all(row["status"] == "failed" for row in rows)
    started = [row["started_at"] for row in rows]
    assert started == sorted(started, reverse=True)
    assert rows[0]["started_at"].startswith("2024-06-02")
    games_only = client.get("/api/load-runs", params={"dataset": "Games", "status": "failed"})
    assert games_only.json()["page"]["total"] == 2
    assert all(row["dataset"] == "games" for row in games_only.json()["data"])
    season = client.get("/api/load-runs", params={"season": 2024, "status": "failed"})
    assert [row["dataset"] for row in season.json()["data"]] == ["games", "games"]
    assert client.get("/api/load-runs", params={"season": 2025}).json()["page"]["total"] == 0


def test_sort_ties_break_on_the_primary_key(client, engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO players (gsis_id, display_name, is_stub, loaded_at)
                VALUES (:gsis_id, :display_name, true, CURRENT_TIMESTAMP)
                """
            ),
            [
                {"gsis_id": "99-0000002", "display_name": "Same Name"},
                {"gsis_id": "99-0000001", "display_name": "Same Name"},
            ],
        )
    response = client.get("/api/players", params={"q": "Same Name"})
    assert response.status_code == 200
    assert [row["gsis_id"] for row in response.json()["data"]] == ["99-0000001", "99-0000002"]


def test_database_errors_that_are_not_disconnects_stay_internal():
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    from web.errors import is_db_unavailable

    programming = ProgrammingError("select 1", {}, Exception("permission denied"))
    assert is_db_unavailable(programming) is False
    disconnected = DBAPIError("select 1", {}, Exception("connection reset"))
    disconnected.connection_invalidated = True
    assert is_db_unavailable(disconnected) is True


def _insert_players(engine, count):
    rows = [
        {"gsis_id": f"99-{index:07d}", "display_name": f"Fictional Player {index:03d}"}
        for index in range(1, count + 1)
    ]
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO players (gsis_id, display_name, is_stub, loaded_at)
                VALUES (:gsis_id, :display_name, true, CURRENT_TIMESTAMP)
                """
            ),
            rows,
        )


def test_at16_pagination(client, engine):
    _insert_players(engine, 120)
    first = client.get("/api/players", params={"limit": 50, "offset": 0})
    second = client.get("/api/players", params={"limit": 50, "offset": 50})
    hundred = client.get("/api/players", params={"limit": 100})
    assert first.status_code == second.status_code == hundred.status_code == 200
    page0 = first.json()
    page1 = second.json()
    wide = hundred.json()
    assert page0["page"]["total"] == page1["page"]["total"] == wide["page"]["total"] == 120
    ids0 = [row["gsis_id"] for row in page0["data"]]
    ids1 = [row["gsis_id"] for row in page1["data"]]
    ids100 = [row["gsis_id"] for row in wide["data"]]
    assert len(ids0) == len(ids1) == 50
    assert len(ids100) == 100
    assert set(ids0).isdisjoint(ids1)
    assert set(ids0) | set(ids1) == set(ids100)
    again = client.get("/api/players", params={"limit": 50, "offset": 0}).json()
    assert [row["gsis_id"] for row in again["data"]] == ids0

    assert client.get("/api/players", params={"limit": 1}).json()["page"]["limit"] == 1
    assert len(client.get("/api/players", params={"limit": 1}).json()["data"]) == 1
    capped = client.get("/api/players", params={"limit": 500})
    assert capped.status_code == 200
    assert capped.json()["page"]["limit"] == 500
    assert len(capped.json()["data"]) == 120

    for params, name in (({"limit": "0"}, "limit"), ({"limit": "501"}, "limit"), ({"offset": "-1"}, "offset")):
        response = client.get("/api/players", params=params)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_parameter"
        assert response.json()["error"]["param"] == name


def test_at17_bad_parameters(client, loaded):
    cases = [
        ({"week": "abc"}, "week", "week must be an integer from 1 to 22"),
        ({"week": "23"}, "week", "week must be an integer from 1 to 22"),
        ({"season_type": "XYZ"}, "season_type", "season_type must be REG or POST"),
        ({"sort": "bogus"}, "sort", "sort must be one of: gameday, week, season"),
        ({"order": "up"}, "order", "order must be asc or desc"),
        ({"limit": "abc"}, "limit", "limit must be an integer from 1 to 500"),
    ]
    for params, name, message in cases:
        response = client.get("/api/games", params=params)
        assert response.status_code == 400, params
        assert response.json()["error"] == {
            "code": "invalid_parameter",
            "message": message,
            "param": name,
        }
        assert "Traceback" not in response.text

    unknown = client.get("/api/games", params={"foo": "1"})
    assert unknown.status_code == 400
    assert unknown.json()["error"] == {
        "code": "unknown_parameter",
        "message": "unknown parameter: foo",
        "param": "foo",
    }
    assert unknown.headers["cache-control"] == "public, max-age=300"
    assert client.get("/api", params={"foo": "1"}).status_code == 400
    detail = client.get("/api/teams/CIN", params={"foo": "1"})
    assert detail.status_code == 400
    assert detail.json()["error"]["code"] == "unknown_parameter"
    assert detail.json()["error"]["param"] == "foo"

    missing = client.get("/api/not-a-resource")
    assert missing.status_code == 404
    assert missing.json() == {"error": {"code": "not_found", "message": "Not found"}}
    assert missing.headers["content-type"].startswith("application/json")

    assert client.get("/api/games", params={"week": "1"}).status_code == 200
    assert client.get("/api/games", params={"week": "22"}).status_code == 200
    assert client.get("/api/games", params={"week": "0"}).status_code == 400
    assert client.get("/api/games", params={"season": "1999"}).status_code == 200
    assert client.get("/api/games", params={"season": "2100"}).status_code == 200
    assert client.get("/api/games", params={"season": "1998"}).status_code == 400
    assert client.get("/api/games", params={"season": "2101"}).status_code == 400
    assert client.get("/api/games", params={"team": "AB"}).status_code == 200
    assert client.get("/api/games", params={"team": "A"}).status_code == 400
    assert client.get("/api/games", params={"team": "ABCD"}).status_code == 400
    assert client.get("/api/players", params={"position": "W"}).status_code == 200
    assert client.get("/api/players", params={"position": "TOOLONG"}).status_code == 400
    assert client.get("/api/players", params={"q": "ab"}).status_code == 200
    assert client.get("/api/players", params={"q": "b" * 50}).status_code == 200
    assert client.get("/api/players", params={"q": "a" * 51}).status_code == 400
    far = client.get("/api/players", params={"offset": "2147483647"})
    assert far.status_code == 200
    assert far.json()["data"] == []
    assert client.get("/api/teams", params={"conf": "a" * 64}).status_code == 200
    too_long = client.get("/api/teams", params={"conf": "a" * 65})
    assert too_long.status_code == 400
    assert too_long.json()["error"]["param"] == "conf"
    assert client.get("/api/games", params={"order": "DESC"}).status_code == 200
    assert client.get("/api/games", params={"season": "", "week": ""}).status_code == 200
    division = client.get("/api/teams", params={"division": "afc north"})
    assert division.status_code == 200
    assert division.json()["data"]
    assert {row["team_division"] for row in division.json()["data"]} == {"AFC North"}
