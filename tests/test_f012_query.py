"""F012 dataset-wide query contract. Real Postgres; legacy tests stay in test_api.py."""

import json
import os
import threading
import time
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import event, text

from web.dataset_query import BUDGET_SECONDS, BUSY_MESSAGE, TIMEOUT_MESSAGE, admit
from web.errors import AppError
from web.queries import output_names, run_advanced_list

BUSY = "Too many dataset queries. Try again shortly."
TIMEOUT = "The query took too long. Narrow filters and retry."


def _js(value) -> str:
    return json.dumps(value, separators=(",", ":"))


def _params(**kwargs):
    encoded = {}
    for key, value in kwargs.items():
        if key in {"sorts", "filters"} and not isinstance(value, str):
            encoded[key] = _js(value)
        else:
            encoded[key] = value
    return encoded


def _error(response):
    assert response.headers["content-type"].startswith("application/json")
    assert "charset=utf-8" in response.headers["content-type"]
    assert "Traceback" not in response.text
    assert "SELECT" not in response.text
    return response.json()["error"]


def _insert_team(conn, abbr, name, nick, conf="NFC", division="East", loaded_at="2024-01-01T00:00:00+00:00"):
    conn.execute(
        text(
            """
            INSERT INTO teams (
                team_abbr, team_name, team_nick, team_conf, team_division,
                team_id, team_color, team_color2, loaded_at
            ) VALUES (
                :abbr, :name, :nick, :conf, :division, '1', '#000000', '#ffffff', :loaded_at
            )
            """
        ),
        {
            "abbr": abbr,
            "name": name,
            "nick": nick,
            "conf": conf,
            "division": division,
            "loaded_at": loaded_at,
        },
    )


def _ids(response, *keys):
    assert response.status_code == 200, response.text
    body = response.json()
    return [tuple(row[key] for key in keys) for row in body["data"]], body["page"]


def _oracle(conn, sql, params=None):
    rows = conn.execute(text(sql), params or {}).all()
    return [tuple(row) for row in rows]


def _order_sql(sorts, tie, qualify):
    parts = []
    seen = set()
    for key, desc in sorts:
        parts.append(f"{qualify(key)} {'DESC' if desc else 'ASC'} NULLS LAST")
        seen.add(key)
    for key in tie:
        if key not in seen:
            parts.append(f"{qualify(key)} ASC NULLS LAST")
    return ", ".join(parts)


def test_budget_constant():
    assert BUDGET_SECONDS == 3.0
    assert TIMEOUT_MESSAGE == TIMEOUT
    assert BUSY_MESSAGE == BUSY


def test_alembic_head_without_index_revision():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    path = Path("migrations/versions/0010_stats_public_query_indexes.py")
    if path.exists():
        assert script.get_heads() == ["0010"]
        revision = script.get_revision("0010")
        assert revision.down_revision == "0009"
        source = path.read_text()
        assert "ix_stats_public_ppr_order" in source
        assert "ix_stats_public_scope_ppr" in source
        assert "GRANT" not in source.upper()
        assert "salary_private" not in source
    else:
        assert script.get_heads() == ["0009"]
        assert script.get_revision("0009").down_revision == "0008"


def test_at2_advanced_names_only_on_lists(client, monkeypatch):
    engine = client.app.state.engine
    calls = {"n": 0}
    original = engine.connect

    def counting(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    lists = (
        "/api/teams",
        "/api/players",
        "/api/games",
        "/api/player-week-stats",
        "/api/load-runs",
    )
    for path in lists:
        allowed = client.get(path, params={"sorts": "[]"})
        assert allowed.status_code == 200, path
        assert allowed.headers["cache-control"] == "public, max-age=300"

    monkeypatch.setattr(engine, "connect", counting)
    calls["n"] = 0
    blocked = [
        "/api",
        "/api/health",
        "/api/teams/AA",
        "/api/players/P1",
        "/api/games/G1",
    ]
    for path in blocked:
        for key in ("sorts", "filters", "search"):
            response = client.get(path, params={key: "[]"})
            assert response.status_code == 400, (path, key)
            assert _error(response) == {
                "code": "unknown_parameter",
                "message": f"unknown parameter: {key}",
                "param": key,
            }
            assert response.headers["cache-control"] == "public, max-age=300"
    for path in lists:
        for key in ("foo", "ui_sort", "ui_filters", "ui_search", "ui_scope", "ui_hidden"):
            response = client.get(path, params={key: "1"})
            assert response.status_code == 400, (path, key)
            assert _error(response)["message"] == f"unknown parameter: {key}"
            assert _error(response)["param"] == key
    assert calls["n"] == 0

    monkeypatch.undo()
    os.environ.pop("SERVE_SPA", None)
    for page in ("/teams", "/players", "/games", "/stats", "/load-runs"):
        page_response = client.get(page, params={"sorts": "[]"})
        assert page_response.status_code == 400
        assert "unknown parameter: sorts" in page_response.text
    monkeypatch.setenv("SERVE_SPA", "true")
    spa = client.get("/teams", params={"sorts": "[]"})
    assert spa.status_code in {200, 503}
    assert "unknown parameter: sorts" not in spa.text


def test_at7_validation_precedence_and_bounds(client, monkeypatch):
    engine = client.app.state.engine

    def boom(*args, **kwargs):
        raise AssertionError("invalid request reached the database")

    monkeypatch.setattr(engine, "connect", boom)

    def rejects(params, message, param, code="invalid_parameter"):
        response = client.get("/api/teams", params=_params(**params))
        assert response.status_code == 400, response.text
        assert _error(response) == {"code": code, "message": message, "param": param}
        assert response.headers["cache-control"] == "public, max-age=300"

    rejects(
        {"foo": "1", "sorts": "not-json"},
        "unknown parameter: foo",
        "foo",
        "unknown_parameter",
    )
    rejects(
        {"sort": "nope", "sorts": "[]"},
        "sort must be one of: team_abbr, team_name",
        "sort",
    )
    response = client.get("/api/teams?sorts=%5B%5D&sorts=%5B%5D")
    assert _error(response) == {
        "code": "invalid_parameter",
        "message": "duplicate parameter: sorts",
        "param": "sorts",
    }
    rejects({"sorts": "   "}, "invalid sorts", "sorts")
    rejects({"filters": ""}, "invalid filters", "filters")
    rejects({"sorts": "null"}, "invalid sorts", "sorts")
    rejects({"filters": "[]"}, "invalid filters", "filters")
    rejects({"sorts": "[" * 9 + "]" * 9}, "invalid sorts", "sorts")
    rejects({"filters": "{" * 20 + "}" * 20}, "invalid filters", "filters")
    deep = client.get("/api/players", params={"sorts": "[" * 4000 + "]" * 4000})
    assert deep.status_code == 400
    assert _error(deep)["message"] == "invalid sorts"
    rejects({"sorts": '{"id":"team_abbr","id":"team_name","desc":false}'}, "invalid sorts", "sorts")
    rejects({"sorts": [{"id": "team_abbr", "desc": False}] * 4}, "invalid sorts", "sorts")
    rejects(
        {"sorts": [{"id": "team_abbr", "desc": False}, {"id": "team_abbr", "desc": True}]},
        "invalid sorts",
        "sorts",
    )
    rejects({"sorts": [{"id": "team_abbr", "desc": 1}]}, "invalid sorts", "sorts")
    rejects({"sorts": [{"id": "salary", "desc": False}]}, "invalid sorts", "sorts")
    rejects({"sorts": [{"id": "team_abbr", "desc": False, "extra": 1}]}, "invalid sorts", "sorts")
    rejects({"filters": {"nope": {"kind": "text", "value": "a"}}}, "invalid filters", "filters")
    rejects(
        {"filters": {"team_name": {"kind": "range", "min": 1, "max": 2}}},
        "invalid filters",
        "filters",
    )
    rejects(
        {"filters": '{"team_name":{"kind":"text","kind":"text","value":"a"}}'},
        "invalid filters",
        "filters",
    )
    rejects({"filters": {"team_name": {"kind": "text", "op": "regex", "value": "a"}}}, "invalid filters", "filters")
    rejects({"filters": {"team_name": {"kind": "text", "value": "a" * 101}}}, "invalid filters", "filters")
    rejects({"filters": {"team_name": {"kind": "text", "value": "a\x00b"}}}, "invalid filters", "filters")
    rejects(
        {"filters": {"team_conf": {"kind": "multi", "values": ["A"] * 65, "missing": False}}},
        "invalid filters",
        "filters",
    )
    rejects(
        {"filters": {"team_conf": {"kind": "multi", "values": ["  "], "missing": False}}},
        "invalid filters",
        "filters",
    )
    rejects(
        {"filters": {"team_conf": {"kind": "multi", "values": [], "missing": "true"}}},
        "invalid filters",
        "filters",
    )
    too_many = {f"k{index}": {"kind": "text", "value": "a"} for index in range(17)}
    rejects({"filters": too_many}, "invalid filters", "filters")
    rejects({"filters": {"team_name": {"kind": "range", "min": True, "max": None}}}, "invalid filters", "filters")
    rejects({"filters": '{"team_name":{"kind":"range","min":NaN,"max":1}}'}, "invalid filters", "filters")
    rejects(
        {"filters": '{"team_name":{"kind":"range","min":Infinity,"max":null}}'},
        "invalid filters",
        "filters",
    )
    rejects({"filters": {"team_name": {"kind": "range", "min": 2, "max": 1}}}, "invalid filters", "filters")
    rejects(
        {"filters": {"team_name": {"kind": "range", "min": 1000000000001, "max": None}}},
        "invalid filters",
        "filters",
    )
    rejects(
        {"filters": {"team_name": {"kind": "range", "min": -1000000000001, "max": None}}},
        "invalid filters",
        "filters",
    )
    rejects({"search": "a" * 101}, "invalid search", "search")
    rejects({"search": "a\x00b"}, "invalid search", "search")
    rejects({"search": "é" * 101}, "invalid search", "search")
    over = client.get("/api/teams?search=" + "é" * 4097)
    assert _error(over) == {
        "code": "invalid_parameter",
        "message": "advanced query exceeds 8192 bytes",
        "param": "filters",
    }
    rejects({"sorts": "x" * 8193}, "advanced query exceeds 8192 bytes", "filters")
    # Size is checked before JSON parsing, so this still names filters.
    assert "é" not in over.text


def test_at7_exact_budget_is_accepted_when_otherwise_valid(client, engine):
    with engine.begin() as conn:
        _insert_team(conn, "AA", "Alpha", "A")
    response = client.get("/api/teams?search=" + "é" * 4096)
    assert response.status_code == 400
    assert _error(response)["message"] == "invalid search"
    blank = client.get("/api/teams?search=" + " " * 8192)
    assert blank.status_code == 200
    assert blank.json()["page"]["total"] == 1


def _seed_order(conn):
    _insert_team(conn, "AA", "M", "A")
    _insert_team(conn, "BB", "M", "B", conf="AFC", division="West")
    _insert_team(conn, "CC", "A", "B")
    _insert_team(conn, "DD", "Z", "A", conf="AFC", division="North")
    conn.execute(
        text(
            """
            INSERT INTO players (
                gsis_id, display_name, first_name, last_name, position, position_group,
                rookie_season, is_stub, loaded_at, height, status, latest_team, college_name
            ) VALUES
                ('P1', 'Ann', 'Ann', 'Alpha', 'QB', 'SPEC', 2020, false,
                 '2024-06-01T00:00:00+00', 70, 'ACT', 'AA', 'State'),
                ('P2', 'ann alpha', 'Ann', 'Beta', 'qb', 'spec', NULL, true,
                 '2024-06-01T00:00:01+00', 72, 'ACT', 'AA', 'State'),
                ('P3', 'Bob', 'Bob', 'Beta', 'WR', NULL, 2020, false,
                 '2024-06-01T00:00:02+00', NULL, 'CUT', 'BB', NULL),
                ('P4', 'Cara', 'Cara', 'Cole', NULL, NULL, 2019, false,
                 '2024-06-01T00:00:03+00', 70, NULL, NULL, 'Other')
            """
        )
    )
    conn.execute(
        text(
            """
            INSERT INTO games (
                game_id, season, game_type, season_type, week, gameday, weekday,
                gametime, away_team, home_team, away_score, home_score, result, total,
                overtime, location, roof, surface, stadium, spread_line, total_line, loaded_at
            ) VALUES
                ('G1', 2024, 'REG', 'REG', 10, '2024-11-10', 'Sunday', '10:00', 'AA', 'BB',
                 10, 20, 10, 30, false, 'Home', 'outdoor', 'grass', 'Only Stadium',
                 3.5, 40.5, '2024-11-10T00:00:00+00'),
                ('G2', 2024, 'REG', 'REG', 2, '2024-09-15', 'Sunday', NULL, 'BB', 'AA',
                 NULL, NULL, NULL, 41, true, 'Home', NULL, NULL, 'Other',
                 NULL, NULL, '2024-09-15T00:00:00+00'),
                ('G3', 2020, 'WC', 'POST', 9, '2020-02-01', 'Saturday', '01:00', 'AA', 'BB',
                 3, 7, 4, 10, NULL, 'Neutral', 'dome', 'turf', 'Dome',
                 -1.5, 37.0, '2020-02-01T00:00:00+00'),
                ('G4', 2020, 'REG', 'REG', 2, '2020-10-01', 'Thursday', '10:00', 'BB', 'AA',
                 14, 14, 0, 28, false, 'ONLYLOC', NULL, NULL, 'Night',
                 3.5, 41.0, '2020-10-01T00:00:00+00')
            """
        )
    )
    conn.execute(
        text(
            """
            INSERT INTO player_week_stats (
                gsis_id, season, week, season_type, game_id, team, opponent_team,
                position, position_group, completions, attempts, passing_yards, passing_tds,
                passing_interceptions, sacks_suffered, sack_fumbles_lost, passing_2pt_conversions,
                carries, rushing_yards, rushing_tds, rushing_fumbles_lost, rushing_2pt_conversions,
                receptions, targets, receiving_yards, receiving_tds, receiving_fumbles_lost,
                receiving_2pt_conversions, target_share, special_teams_tds, fantasy_points,
                fantasy_points_ppr, loaded_at
            ) VALUES
                ('P1', 2024, 2, 'REG', 'G2', 'AA', 'BB', 'QB', 'SPEC',
                 1, 2, 10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                 0.5, 0, 10.00, 12.50, '2024-09-15T00:00:00+00'),
                ('P3', 2024, 2, 'REG', 'G2', 'BB', 'AA', 'WR', NULL,
                 0, 0, 0, 0, 0, 0, 0, 0, 1, 5, 0, 0, 0, 1, 2, 9, 0, 0, 0,
                 NULL, 0, 1.00, 2.00, '2024-09-15T00:00:00+00'),
                ('P1', 2024, 10, 'REG', 'G1', 'AA', 'BB', 'QB', 'SPEC',
                 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                 0.5, 0, 10.00, 12.50, '2024-11-10T00:00:00+00'),
                ('P4', 2020, 2, 'REG', 'G4', 'BB', 'AA', NULL, NULL,
                 0, 0, 40, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                 NULL, 0, 0.00, 0.00, '2020-10-01T00:00:00+00')
            """
        )
    )
    conn.execute(
        text(
            """
            INSERT INTO load_runs (
                run_group, dataset, season, status, trigger, started_at, finished_at,
                source_url, source_version, rows_read, rows_upserted, rows_deleted,
                rows_skipped, notes, error
            ) VALUES
                ('11111111-1111-1111-1111-111111111111', 'players', 2024, 'succeeded',
                 'manual-token', '2024-01-02T03:04:05+00', '2024-01-02T04:00:00+00',
                 'https://example.invalid/a', 'v1', 10, 9, 0, 1, 'plain', NULL),
                ('22222222-2222-2222-2222-222222222222', 'games', NULL, 'failed',
                 'other', '2024-06-01T00:00:00+00', NULL,
                 'https://example.invalid/b', NULL, NULL, NULL, NULL, NULL,
                 'PRIVATE-NOTE', 'boom'),
                ('33333333-3333-3333-3333-333333333333', 'PLAYERS', 1999, 'running',
                 'Manual-Token', '2020-01-01T00:00:00+00', '2020-01-01T00:00:00+00',
                 'https://example.invalid/c', 'v1', 10, 1, 2, 3, NULL, NULL)
            """
        )
    )


def test_at3_sort_pages_match_sql(client, engine):
    with engine.begin() as conn:
        _seed_order(conn)
    endpoints = [
        (
            "/api/teams",
            "teams",
            ("team_abbr",),
            ("team_name", "team_nick", "team_abbr"),
            ("team_abbr",),
            lambda key: f'"{key}"',
            "SELECT {ids} FROM teams ORDER BY {order}",
        ),
        (
            "/api/players",
            "players",
            ("gsis_id",),
            ("rookie_season", "display_name", "is_stub"),
            ("gsis_id",),
            lambda key: f'"{key}"',
            "SELECT {ids} FROM players ORDER BY {order}",
        ),
        (
            "/api/games",
            "games",
            ("game_id",),
            ("week", "overtime", "total"),
            ("game_id",),
            lambda key: f'"{key}"',
            "SELECT {ids} FROM games ORDER BY {order}",
        ),
        (
            "/api/player-week-stats",
            "stats",
            ("gsis_id", "season", "week"),
            ("fantasy_points_ppr", "player_display_name", "week"),
            ("gsis_id", "season", "week"),
            lambda key: "p.display_name" if key == "player_display_name" else f's."{key}"',
            (
                "SELECT {ids} FROM player_week_stats s "
                "JOIN players p ON p.gsis_id = s.gsis_id ORDER BY {order}"
            ),
        ),
        (
            "/api/load-runs",
            "load-runs",
            ("id",),
            ("started_at", "season", "rows_read"),
            ("id",),
            lambda key: f'"{key}"',
            "SELECT {ids} FROM load_runs ORDER BY {order}",
        ),
    ]
    with engine.connect() as conn:
        for path, _slug, id_cols, keys, tie, qualify, template in endpoints:
            first, second, third = keys
            cases = [
                [(first, False)],
                [(first, True)],
                [(first, False), (second, True)],
                [(second, True), (first, False)],
                [(first, False), (second, True), (third, False)],
                [(third, True), (second, False), (first, True)],
            ]
            for sorts in cases:
                order = _order_sql(sorts, tie, qualify)
                expected = _oracle(
                    conn,
                    template.format(ids=", ".join(qualify(key) for key in id_cols), order=order),
                )
                seen = []
                for _ in range(3):
                    rows, page = _ids(
                        client.get(path, params=_params(sorts=[{"id": key, "desc": desc} for key, desc in sorts], limit=50)),
                        *id_cols,
                    )
                    seen.append(rows)
                    assert page["total"] == len(expected)
                assert seen[0] == seen[1] == seen[2] == expected
                paged = []
                for offset in range(0, len(expected), 2):
                    chunk, page = _ids(
                        client.get(
                            path,
                            params=_params(
                                sorts=[{"id": key, "desc": desc} for key, desc in sorts],
                                limit=2,
                                offset=offset,
                            ),
                        ),
                        *id_cols,
                    )
                    assert page["total"] == len(expected)
                    paged.extend(chunk)
                assert paged == expected
                assert len(paged) == len(set(paged))
            fourth = [
                {"id": keys[0], "desc": False},
                {"id": keys[1], "desc": False},
                {"id": keys[2], "desc": True},
                {"id": "loaded_at", "desc": False},
            ]
            assert client.get(path, params=_params(sorts=fourth)).status_code == 400
            duplicate = [
                {"id": keys[0], "desc": False},
                {"id": keys[0], "desc": True},
            ]
            assert client.get(path, params=_params(sorts=duplicate)).status_code == 400


def test_at4_legacy_sort_interaction(client, engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO players (gsis_id, display_name, rookie_season, is_stub, loaded_at)
                VALUES
                    ('P1', 'Ann', 2020, false, CURRENT_TIMESTAMP),
                    ('P2', 'Bob', NULL, false, CURRENT_TIMESTAMP),
                    ('P3', 'Cara', 2019, false, CURRENT_TIMESTAMP)
                """
            )
        )
        legacy_sql = _oracle(
            conn,
            "SELECT gsis_id FROM players ORDER BY rookie_season DESC, gsis_id ASC",
        )
        advanced_sql = _oracle(
            conn,
            "SELECT gsis_id FROM players ORDER BY rookie_season DESC NULLS LAST, gsis_id ASC NULLS LAST",
        )
    legacy, _ = _ids(
        client.get("/api/players", params={"sort": "rookie_season", "order": "desc", "limit": "10"}),
        "gsis_id",
    )
    assert legacy == legacy_sql
    assert legacy[0] == ("P2",)
    advanced, _ = _ids(
        client.get(
            "/api/players",
            params={"sort": "rookie_season", "order": "desc", "sorts": "[]", "limit": "10"},
        ),
        "gsis_id",
    )
    assert advanced == advanced_sql
    assert advanced[-1] == ("P2",)
    overridden, _ = _ids(
        client.get(
            "/api/players",
            params=_params(
                sort="display_name",
                order="desc",
                sorts=[{"id": "gsis_id", "desc": False}],
                limit=10,
            ),
        ),
        "gsis_id",
    )
    assert overridden == [("P1",), ("P2",), ("P3",)]
    invalid = client.get(
        "/api/players",
        params=_params(sort="nope", sorts=[{"id": "gsis_id", "desc": False}]),
    )
    assert invalid.status_code == 400
    assert _error(invalid)["param"] == "sort"
    invalid_order = client.get("/api/players", params={"order": "up", "search": "Ann"})
    assert invalid_order.status_code == 400
    assert _error(invalid_order)["message"] == "order must be asc or desc"


def test_at5_filters_and_legacy_and(client, engine):
    with engine.begin() as conn:
        _seed_order(conn)
        conn.execute(text("UPDATE player_week_stats SET fantasy_points_ppr = 0 WHERE gsis_id = 'P4'"))
        conn.execute(
            text(
                """
                UPDATE players SET display_name = '100% done' WHERE gsis_id = 'P3'
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO players (gsis_id, display_name, is_stub, loaded_at)
                VALUES
                    ('P5', 'A_B', false, CURRENT_TIMESTAMP),
                    ('P6', 'AXB', false, CURRENT_TIMESTAMP),
                    ('P7', 'A\\B', false, CURRENT_TIMESTAMP)
                """
            )
        )
    percent, _ = _ids(
        client.get(
            "/api/players",
            params=_params(filters={"display_name": {"kind": "text", "op": "contains", "value": "%"}}),
        ),
        "gsis_id",
    )
    assert percent == [("P3",)]
    underscore, _ = _ids(
        client.get(
            "/api/players",
            params=_params(filters={"display_name": {"kind": "text", "value": "_"}}),
        ),
        "gsis_id",
    )
    assert underscore == [("P5",)]
    slash, _ = _ids(
        client.get(
            "/api/players",
            params=_params(filters={"display_name": {"kind": "text", "op": "contains", "value": "\\"}}),
        ),
        "gsis_id",
    )
    assert slash == [("P7",)]
    equals, _ = _ids(
        client.get(
            "/api/players",
            params=_params(filters={"display_name": {"kind": "text", "op": "equals", "value": "ANN"}}),
        ),
        "gsis_id",
    )
    assert equals == [("P1",)]
    ranged, page = _ids(
        client.get(
            "/api/players",
            params=_params(filters={"rookie_season": {"kind": "range", "min": 2020, "max": 2020}}),
        ),
        "gsis_id",
    )
    assert ranged == [("P3",), ("P1",)]
    assert page["total"] == 2
    open_ended, _ = _ids(
        client.get(
            "/api/players",
            params=_params(filters={"height": {"kind": "range", "min": 70, "max": None}}),
        ),
        "gsis_id",
    )
    assert ("P1",) in open_ended and ("P2",) in open_ended and ("P3",) not in open_ended
    missing, _ = _ids(
        client.get(
            "/api/players",
            params=_params(
                filters={"position": {"kind": "multi", "values": ["qb"], "missing": True}}
            ),
        ),
        "gsis_id",
    )
    assert set(missing) == {("P1",), ("P2",), ("P4",), ("P5",), ("P6",), ("P7",)}
    only_null, _ = _ids(
        client.get(
            "/api/players",
            params=_params(filters={"position": {"kind": "multi", "values": [], "missing": True}}),
        ),
        "gsis_id",
    )
    assert ("P4",) in only_null
    assert ("P1",) not in only_null
    noop, noop_page = _ids(
        client.get(
            "/api/players",
            params=_params(
                filters={
                    "display_name": {"kind": "text", "value": "   "},
                    "height": {"kind": "range", "min": None, "max": None},
                    "status": {"kind": "multi", "values": [], "missing": False},
                }
            ),
        ),
        "gsis_id",
    )
    assert noop_page["total"] == 7
    assert len(noop) == 7
    contradicted = client.get(
        "/api/players",
        params=_params(q="Ann", filters={"display_name": {"kind": "text", "op": "equals", "value": "Bob"}}),
    )
    assert contradicted.status_code == 200
    assert contradicted.json()["data"] == []
    assert contradicted.json()["page"]["total"] == 0
    both, _ = _ids(
        client.get(
            "/api/players",
            params=_params(
                position="QB",
                filters={"rookie_season": {"kind": "range", "min": 2020, "max": None}},
            ),
        ),
        "gsis_id",
    )
    assert both == [("P1",)]
    huge = client.get(
        "/api/games",
        params=_params(filters={"week": {"kind": "range", "min": 40000, "max": None}}),
    )
    assert huge.status_code == 200
    assert huge.json()["data"] == []
    raw = client.get(
        "/api/games",
        params={"filters": '{"spread_line":{"kind":"range","min":3.5,"max":3.5}}'},
    )
    assert raw.status_code == 200
    assert {row["game_id"] for row in raw.json()["data"]} == {"G1", "G4"}
    games_and = client.get(
        "/api/games",
        params=_params(
            season=2024,
            filters={"season": {"kind": "range", "min": None, "max": 2020}},
        ),
    )
    assert games_and.json()["page"]["total"] == 0
    multi_and, _ = _ids(
        client.get(
            "/api/games",
            params=_params(
                team="AA",
                filters={"away_team": {"kind": "multi", "values": ["BB"], "missing": False}},
            ),
        ),
        "game_id",
    )
    assert set(multi_and) <= {("G2",), ("G4",)}
    assert ("G1",) not in multi_and
    overtime, _ = _ids(
        client.get(
            "/api/games",
            params=_params(filters={"overtime": {"kind": "text", "op": "equals", "value": "TRUE"}}),
        ),
        "game_id",
    )
    assert overtime == [("G2",)]
    date_rows, _ = _ids(
        client.get(
            "/api/games",
            params=_params(filters={"gameday": {"kind": "text", "op": "contains", "value": "2020-10"}}),
        ),
        "game_id",
    )
    assert date_rows == [("G4",)]


def test_at6_global_search_is_fixed_text(client, engine):
    with engine.begin() as conn:
        _seed_order(conn)
        conn.execute(text("UPDATE player_week_stats SET fantasy_points_ppr = 0 WHERE fantasy_points_ppr IS NULL"))
        conn.execute(text("UPDATE players SET display_name = '100% done' WHERE gsis_id = 'P3'"))
        conn.execute(
            text(
                """
                INSERT INTO players (gsis_id, display_name, first_name, last_name, is_stub, loaded_at, height)
                VALUES ('P9', 'Plain', 'Alpha', 'Beta', false, CURRENT_TIMESTAMP, 88)
                """
            )
        )
    teams, _ = _ids(client.get("/api/teams", params={"search": "north"}), "team_abbr")
    assert teams == [("DD",)]
    assert client.get("/api/teams", params={"search": "000000"}).json()["data"] == []
    names, _ = _ids(client.get("/api/players", params={"search": "SPEC"}), "gsis_id")
    assert ("P1",) in names and ("P2",) in names
    assert client.get("/api/players", params={"search": "P1"}).json()["page"]["total"] == 0
    phrase = client.get("/api/players", params={"search": "Alpha Beta"})
    assert phrase.json()["page"]["total"] == 0
    assert client.get("/api/players", params={"search": "Alpha"}).json()["page"]["total"] >= 1
    assert client.get("/api/players", params={"search": "88"}).json()["page"]["total"] == 0
    percent = client.get("/api/players", params={"search": "%"})
    assert {row["gsis_id"] for row in percent.json()["data"]} == {"P3"}
    stadium, _ = _ids(client.get("/api/games", params={"search": "Only Stadium"}), "game_id")
    assert stadium == [("G1",)]
    assert client.get("/api/games", params={"search": "ONLYLOC"}).json()["page"]["total"] == 0
    narrowed = client.get(
        "/api/games",
        params=_params(search="AA", filters={"week": {"kind": "range", "min": 10, "max": 10}}),
    )
    assert [row["game_id"] for row in narrowed.json()["data"]] == ["G1"]
    stats, _ = _ids(
        client.get("/api/player-week-stats", params={"search": "Ann"}),
        "gsis_id",
        "week",
    )
    assert stats
    assert all(row[0] == "P1" for row in stats)
    assert client.get("/api/player-week-stats", params={"search": "12.50"}).json()["page"]["total"] == 0
    runs, _ = _ids(client.get("/api/load-runs", params={"search": "manual-token"}), "trigger")
    assert {row[0] for row in runs} == {"manual-token", "Manual-Token"}
    assert client.get("/api/load-runs", params={"search": "PRIVATE-NOTE"}).json()["page"]["total"] == 0
    assert client.get("/api/load-runs", params={"search": "boom"}).json()["page"]["total"] == 0
    assert client.get("/api/load-runs", params={"search": "10"}).json()["page"]["total"] == 0


def test_at8_literals_and_private_names(client, engine, monkeypatch):
    with engine.begin() as conn:
        _insert_team(conn, "AA", "Alpha", "A")
        conn.execute(
            text(
                """
                INSERT INTO players (gsis_id, display_name, is_stub, loaded_at)
                VALUES
                    ('P1', :probe, false, CURRENT_TIMESTAMP),
                    ('P2', 'Safe Name', false, CURRENT_TIMESTAMP)
                """
            ),
            {"probe": "%' OR '1'='1"},
        )
    engine_calls = {"n": 0}
    original = client.app.state.engine.connect

    def counting(*args, **kwargs):
        engine_calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(client.app.state.engine, "connect", counting)
    for path in (
        "/api/teams",
        "/api/players",
        "/api/games",
        "/api/player-week-stats",
        "/api/load-runs",
    ):
        for params in (
            {"sorts": '[{"id":"salary","desc":false}]'},
            {"sorts": '[{"id":"dk_salary","desc":false}]'},
            {"filters": '{"salary_private":{"kind":"text","value":"x"}}'},
            {"filters": '{"dk_points":{"kind":"range","min":1,"max":1}}'},
        ):
            before = engine_calls["n"]
            response = client.get(path, params=params)
            assert response.status_code == 400, (path, params, response.text)
            assert "salary" not in _error(response)["message"]
            assert engine_calls["n"] == before
    monkeypatch.undo()
    captured = []

    def before(conn, cursor, statement, parameters, context, executemany):
        captured.append(statement)

    event.listen(client.app.state.engine, "before_cursor_execute", before)
    try:
        response = client.get(
            "/api/players",
            params=_params(filters={"display_name": {"kind": "text", "value": "%' OR '1'='1"}}),
        )
    finally:
        event.remove(client.app.state.engine, "before_cursor_execute", before)
    assert response.status_code == 200
    assert [row["gsis_id"] for row in response.json()["data"]] == ["P1"]
    assert response.json()["data"][0].keys() == set(output_names("players")) or set(
        response.json()["data"][0]
    ) == set(output_names("players"))
    joined = "\n".join(captured)
    assert "salary_private" not in joined
    assert "%' OR '1'='1" not in joined


def test_at9_snapshot_offset_and_later_read(client, engine):
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO players (gsis_id, display_name, is_stub, loaded_at)
                VALUES
                    ('P1', 'Ann', false, CURRENT_TIMESTAMP),
                    ('P2', 'Bob', false, CURRENT_TIMESTAMP)
                """
            )
        )
    state = {"done": False}

    def after(conn, cursor, statement, parameters, context, executemany):
        if state["done"] or "count(" not in statement.lower():
            return
        state["done"] = True
        with engine.begin() as other:
            other.execute(
                text(
                    """
                    INSERT INTO players (gsis_id, display_name, is_stub, loaded_at)
                    VALUES ('PNEW', 'New', false, CURRENT_TIMESTAMP)
                    """
                )
            )

    target = client.app.state.engine
    event.listen(target, "after_cursor_execute", after)
    try:
        response = client.get("/api/players", params={"sorts": "[]", "limit": "10"})
    finally:
        event.remove(target, "after_cursor_execute", after)
    assert state["done"] is True
    assert response.status_code == 200
    body = response.json()
    assert body["page"]["total"] == 2
    assert {row["gsis_id"] for row in body["data"]} == {"P1", "P2"}
    later = client.get("/api/players", params={"sorts": "[]", "limit": "10"})
    assert later.json()["page"]["total"] == 3
    assert "PNEW" in {row["gsis_id"] for row in later.json()["data"]}
    empty = client.get(
        "/api/players",
        params=_params(filters={"display_name": {"kind": "text", "op": "equals", "value": "missing"}}),
    )
    assert empty.json() == {"data": [], "page": {"limit": 50, "offset": 0, "total": 0}}
    past = client.get("/api/players", params={"sorts": "[]", "offset": "50"})
    assert past.json()["data"] == []
    assert past.json()["page"]["total"] == 3


def test_at10_timeout_rollback_and_generic_500(client, engine, monkeypatch):
    lock = engine.connect()
    transaction = lock.begin()
    lock.execute(text("LOCK TABLE player_week_stats IN ACCESS EXCLUSIVE MODE"))
    monkeypatch.setattr("web.dataset_query.BUDGET_SECONDS", 0.4)
    try:
        started = time.monotonic()
        timed = client.get("/api/player-week-stats", params={"sorts": "[]"})
        elapsed = time.monotonic() - started
    finally:
        transaction.rollback()
        lock.close()
        monkeypatch.undo()
    assert timed.status_code == 503
    assert _error(timed) == {"code": "query_timeout", "message": TIMEOUT}
    assert "param" not in timed.json()["error"]
    assert timed.headers["cache-control"] == "no-store"
    assert elapsed < 3.0
    with engine.connect() as conn:
        assert conn.execute(text("SHOW statement_timeout")).scalar_one() == "0"
        assert conn.execute(text("SHOW transaction_read_only")).scalar_one() == "off"
        assert conn.execute(text("SHOW transaction_isolation")).scalar_one() == "read committed"
        conn.execute(text("SELECT pg_sleep(0.6)"))
    healthy = client.get("/api/teams", params={"sorts": "[]"})
    assert healthy.status_code == 200
    assert healthy.headers["cache-control"] == "public, max-age=300"

    def explode(*args, **kwargs):
        raise RuntimeError("boom secret traceback")

    monkeypatch.setattr("web.queries._page_advanced", explode)
    from fastapi.testclient import TestClient

    with TestClient(client.app, raise_server_exceptions=False) as raw:
        failed = raw.get("/api/teams", params={"sorts": "[]"})
    monkeypatch.undo()
    assert failed.status_code == 500
    assert failed.json() == {"error": {"code": "internal_error", "message": "Something went wrong."}}
    assert "boom" not in failed.text
    assert "query_timeout" not in failed.text
    follow = client.get("/api/teams")
    assert follow.status_code == 200
    first = admit()
    second = admit()
    first.__enter__()
    second.__enter__()
    try:
        with pytest.raises(AppError) as caught, admit():
            pass
        assert caught.value.code == "query_busy"
    finally:
        first.__exit__(None, None, None)
        second.__exit__(None, None, None)


def test_at11_admission_is_per_process_and_prompt(client, engine, monkeypatch):
    from web.grammar import AdvancedQuery
    from web.params import ListParams

    monkeypatch.setattr("web.dataset_query.BUDGET_SECONDS", 8.0)
    lock = engine.connect()
    transaction = lock.begin()
    lock.execute(text("LOCK TABLE player_week_stats IN ACCESS EXCLUSIVE MODE"))
    params = ListParams(
        limit=50,
        offset=0,
        sort="fantasy_points_ppr",
        order="desc",
        values={},
        advanced=AdvancedQuery((), {}, None),
    )
    results = []

    def blocked():
        try:
            run_advanced_list(engine, "stats", params)
            results.append("ok")
        except AppError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=blocked), threading.Thread(target=blocked)]
    for thread in threads:
        thread.start()
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with engine.connect() as seen:
                waiting = seen.execute(
                    text(
                        """
                        SELECT count(*) FROM pg_stat_activity
                        WHERE datname = current_database()
                          AND state = 'active'
                          AND query ILIKE '%player_week_stats%'
                          AND pid <> pg_backend_pid()
                        """
                    )
                ).scalar_one()
            if waiting >= 2:
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"advanced queries did not both start: {results}")
        started = time.monotonic()
        busy = client.get("/api/player-week-stats", params={"filters": "{}"})
        elapsed = time.monotonic() - started
        legacy = client.get("/api/teams")
        invalid = client.get("/api/player-week-stats", params={"sorts": "nope"})
    finally:
        transaction.rollback()
        lock.close()
        for thread in threads:
            thread.join(timeout=5)
        monkeypatch.undo()
    assert busy.status_code == 503
    assert _error(busy) == {"code": "query_busy", "message": BUSY}
    assert busy.headers["cache-control"] == "no-store"
    assert elapsed < 0.5
    assert legacy.status_code == 200
    assert legacy.headers["cache-control"] == "public, max-age=300"
    assert invalid.status_code == 400
    assert _error(invalid)["message"] == "invalid sorts"
    assert results.count("ok") == 2
    again = client.get("/api/player-week-stats", params={"sorts": "[]"})
    assert again.status_code == 200

    released = {"hit": False}

    def cancel_wait():
        with admit():
            released["hit"] = True
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError):
        cancel_wait()
    with admit():
        pass


def test_at13_attribution_and_projection_unchanged(client, engine):
    from web.attribution import ATTRIBUTION_TEXT, ROTOGURU_DK_CLASSIC_ATTRIBUTION

    root = client.get("/api")
    assert root.json()["attribution"]["text"] == ATTRIBUTION_TEXT
    page = client.get("/teams")
    assert ATTRIBUTION_TEXT in page.text
    assert ROTOGURU_DK_CLASSIC_ATTRIBUTION not in page.text
    assert "salary" not in page.text.lower()
    with engine.begin() as conn:
        _insert_team(conn, "AA", "Alpha", "A")
    body = client.get("/api/teams", params={"search": "Alpha"}).json()
    assert set(body["data"][0]) == set(output_names("teams"))
    assert "dk_salary" not in body["data"][0]


def test_at14_no_dataset_export():
    from web.main import app

    paths = [getattr(route, "path", "") for route in app.routes]
    assert not any("csv" in path or "export" in path for path in paths)
    source = "\n".join(path.read_text() for path in Path("web").rglob("*.py"))
    assert "StreamingResponse" not in source
    assert "text/csv" not in source
    csv_source = Path("frontend/src/csv.ts").read_text()
    assert "fetch(" not in csv_source
    assert "/api/" not in csv_source


def test_at15_runtime_does_not_grant_or_scan_salary():
    source = "\n".join(
        Path(name).read_text()
        for name in (
            "web/grammar.py",
            "web/dataset_query.py",
            "web/queries.py",
            "web/params.py",
            "web/main.py",
        )
    )
    assert "salary_private" not in source
    assert "CREATE INDEX" not in source
    assert "apply_readonly_grant" not in source
