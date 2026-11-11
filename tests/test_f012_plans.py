"""AT12 plan evidence on a fixed synthetic public-shaped workload.

Indexes are created in this test database and dropped afterward when revision
0009 is not installed. Production application is a separate approval.
"""

import json
import random
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, text

PLAYERS = 25_000
WEEKS = 10
STATS = PLAYERS * WEEKS
SEED = 12012
LOADED = datetime(2024, 1, 1, tzinfo=UTC)
PPR_ORDER = (
    "CREATE INDEX ix_stats_public_ppr_order ON public.player_week_stats "
    "(fantasy_points_ppr DESC NULLS LAST, gsis_id ASC, season ASC, week ASC)"
)
SCOPE_PPR = (
    "CREATE INDEX ix_stats_public_scope_ppr ON public.player_week_stats "
    "(season ASC, season_type ASC, week ASC, fantasy_points_ppr DESC NULLS LAST, gsis_id ASC)"
)
EVIDENCE = Path("/tmp/f012-plan-evidence.json")


def _copy(conn, statement, rows):
    raw = conn.connection.driver_connection
    with raw.cursor() as cursor, cursor.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)


def _players():
    for index in range(1, PLAYERS + 1):
        name = "ZZZSELECTIVE" if index == 12345 else f"Player {index:05d}"
        position = ("QB", "RB", "WR", "TE", "QB")[index % 5]
        team = "AA" if index % 2 == 0 else "BB"
        yield (f"P{index:05d}", name, position, position, team, False, LOADED)


def _stats():
    rng = random.Random(SEED)
    for index in range(1, PLAYERS + 1):
        gsis = f"P{index:05d}"
        team = "AA" if index % 2 == 0 else "BB"
        opponent = "BB" if team == "AA" else "AA"
        position = ("QB", "RB", "WR", "TE", "QB")[index % 5]
        yards = index % 80
        for week in range(1, WEEKS + 1):
            points = Decimal(rng.randrange(0, 5000)) / Decimal(100)
            ppr = points + Decimal(week % 3)
            row = (
                gsis,
                2024,
                week,
                "REG",
                f"G{week:02d}",
                team,
                opponent,
                position,
                position,
                0,
                0,
                yards,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                None,
                0,
                points,
                ppr,
                LOADED,
            )
            if index == 1 and week == 1:
                assert len(row) == 33
            yield row


def _existing(conn):
    rows = conn.execute(
        text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
    ).scalars()
    return set(rows)


def _plans(conn, statement, parameters):
    runs = []
    for label in ("first", "second"):
        started = time.perf_counter()
        lines = conn.exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS) " + statement,
            parameters,
        ).scalars().all()
        runs.append(
            {
                "label": label,
                "seconds": round(time.perf_counter() - started, 6),
                "plan": lines,
            }
        )
    return runs


def test_at12_synthetic_plans(client, engine):
    created = []
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO teams (
                    team_abbr, team_name, team_nick, team_conf, team_division,
                    team_id, team_color, team_color2, loaded_at
                ) VALUES
                    ('AA', 'Alpha', 'A', 'NFC', 'East', '1', '#000000', '#ffffff', :loaded),
                    ('BB', 'Beta', 'B', 'AFC', 'West', '2', '#111111', '#eeeeee', :loaded)
                """
            ),
            {"loaded": LOADED},
        )
        for week in range(1, WEEKS + 1):
            conn.execute(
                text(
                    """
                    INSERT INTO games (
                        game_id, season, game_type, season_type, week, gameday, weekday,
                        away_team, home_team, location, loaded_at
                    ) VALUES (
                        :game_id, 2024, 'REG', 'REG', :week, '2024-09-08', 'Sunday',
                        'AA', 'BB', 'Home', :loaded
                    )
                    """
                ),
                {"game_id": f"G{week:02d}", "week": week, "loaded": LOADED},
            )
        _copy(
            conn,
            """
            COPY players (gsis_id, display_name, position, position_group, latest_team, is_stub, loaded_at)
            FROM STDIN
            """,
            _players(),
        )
        _copy(
            conn,
            """
            COPY player_week_stats (
                gsis_id, season, week, season_type, game_id, team, opponent_team,
                position, position_group, completions, attempts, passing_yards, passing_tds,
                passing_interceptions, sacks_suffered, sack_fumbles_lost, passing_2pt_conversions,
                carries, rushing_yards, rushing_tds, rushing_fumbles_lost, rushing_2pt_conversions,
                receptions, targets, receiving_yards, receiving_tds, receiving_fumbles_lost,
                receiving_2pt_conversions, target_share, special_teams_tds, fantasy_points,
                fantasy_points_ppr, loaded_at
            ) FROM STDIN
            """,
            _stats(),
        )
        present = _existing(conn)
        for name, statement in (
            ("ix_stats_public_ppr_order", PPR_ORDER),
            ("ix_stats_public_scope_ppr", SCOPE_PPR),
        ):
            if name not in present:
                conn.execute(text(statement))
                created.append(name)
        conn.execute(text("ANALYZE teams"))
        conn.execute(text("ANALYZE players"))
        conn.execute(text("ANALYZE games"))
        conn.execute(text("ANALYZE player_week_stats"))
        version = conn.execute(text("SHOW server_version")).scalar_one()
        counts = {
            "players": conn.execute(text("SELECT count(*) FROM players")).scalar_one(),
            "stats": conn.execute(text("SELECT count(*) FROM player_week_stats")).scalar_one(),
        }
        sizes = dict(
            conn.execute(
                text(
                    """
                    SELECT
                        pg_relation_size('ix_stats_public_ppr_order') AS ppr_order_bytes,
                        pg_relation_size('ix_stats_public_scope_ppr') AS scope_ppr_bytes,
                        pg_database_size(current_database()) AS database_bytes,
                        (SELECT avg(pg_column_size(player_week_stats))::int
                         FROM player_week_stats) AS avg_stats_row_bytes
                    """
                )
            ).mappings().one()
        )
        definitions = {
            row.indexname: row.indexdef
            for row in conn.execute(
                text(
                    """
                    SELECT indexname, indexdef FROM pg_indexes
                    WHERE indexname IN ('ix_stats_public_ppr_order', 'ix_stats_public_scope_ppr')
                    """
                )
            )
        }
    assert counts == {"players": PLAYERS, "stats": STATS}
    assert "fantasy_points_ppr DESC NULLS LAST" in definitions["ix_stats_public_ppr_order"]
    assert "gsis_id" in definitions["ix_stats_public_ppr_order"]
    assert "season" in definitions["ix_stats_public_scope_ppr"]
    assert "week" in definitions["ix_stats_public_scope_ppr"]
    scenarios = {
        "default_order": {"sorts": "[]", "limit": "50"},
        "cohort": {"season": "2024", "week": "1", "season_type": "REG", "sorts": "[]", "limit": "50"},
        "team_position_range_three_sorts": {
            "filters": json.dumps(
                {
                    "team": {"kind": "multi", "values": ["AA"], "missing": False},
                    "position": {"kind": "multi", "values": ["QB"], "missing": False},
                    "passing_yards": {"kind": "range", "min": 10, "max": 40},
                },
                separators=(",", ":"),
            ),
            "sorts": json.dumps(
                [
                    {"id": "fantasy_points_ppr", "desc": True},
                    {"id": "week", "desc": False},
                    {"id": "passing_yards", "desc": True},
                ],
                separators=(",", ":"),
            ),
            "limit": "50",
        },
        "selective_contains": {
            "filters": json.dumps(
                {"player_display_name": {"kind": "text", "op": "contains", "value": "ZZZSELECTIVE"}},
                separators=(",", ":"),
            ),
            "sorts": "[]",
            "limit": "50",
        },
        "nonselective_contains": {
            "filters": json.dumps(
                {"player_display_name": {"kind": "text", "value": "Player"}},
                separators=(",", ":"),
            ),
            "sorts": "[]",
            "limit": "50",
        },
        "display_name_search": {"search": "ZZZSELECTIVE", "sorts": "[]", "limit": "50"},
        "zero_matches": {"search": "NO-SUCH-TOKEN", "sorts": "[]", "limit": "50"},
        "deep_offset": {"sorts": "[]", "limit": "50", "offset": "240000"},
    }
    evidence = {
        "seed": SEED,
        "players": PLAYERS,
        "stats": STATS,
        "postgres": version,
        "sizes": {key: int(value) for key, value in sizes.items()},
        "index_definitions": definitions,
        "created_in_test": created,
        "note": (
            "first/second are back-to-back EXPLAIN ANALYZE after ANALYZE on a warm "
            "post-load cache, not a restarted server. Contains scans are not claimed "
            "to be index-backed. LIMIT does not bound scan or count work."
        ),
        "scenarios": {},
    }
    try:
        for name, params in scenarios.items():
            captured = []

            def before(conn, cursor, statement, parameters, context, executemany, bucket=captured):
                bucket.append((statement, parameters))

            event.listen(client.app.state.engine, "before_cursor_execute", before)
            started = time.perf_counter()
            try:
                response = client.get("/api/player-week-stats", params=params)
            finally:
                event.remove(client.app.state.engine, "before_cursor_execute", before)
            elapsed = time.perf_counter() - started
            scenario = {
                "status": response.status_code,
                "api_seconds": round(elapsed, 6),
                "statements": [],
            }
            if response.status_code == 200:
                scenario["total"] = response.json()["page"]["total"]
                scenario["returned"] = len(response.json()["data"])
            else:
                scenario["error"] = response.json()["error"]
            with engine.connect() as conn:
                conn.exec_driver_sql("SET statement_timeout = '20s'")
                try:
                    for statement, parameters in captured:
                        folded = " ".join(statement.split())
                        if "set_config" in folded or not folded.upper().startswith("SELECT"):
                            continue
                        kind = "count" if "count(" in folded.lower() else "page"
                        scenario["statements"].append(
                            {
                                "kind": kind,
                                "sql": folded[:500],
                                "runs": _plans(conn, statement, parameters),
                            }
                        )
                finally:
                    conn.rollback()
                    conn.exec_driver_sql("SET statement_timeout = '0'")
            evidence["scenarios"][name] = scenario
        EVIDENCE.write_text(json.dumps(evidence, indent=2, default=str))
        selective = evidence["scenarios"]["selective_contains"]
        assert selective["status"] == 200
        assert selective["total"] >= 1
        search = evidence["scenarios"]["display_name_search"]
        assert search["status"] == 200 and search["total"] >= 1
        assert evidence["scenarios"]["zero_matches"]["status"] == 200
        assert evidence["scenarios"]["zero_matches"]["total"] == 0

        def page_plan(name):
            statements = evidence["scenarios"][name]["statements"]
            pages = [item for item in statements if item["kind"] == "page"]
            assert pages, name
            return "\n".join(pages[0]["runs"][0]["plan"])

        assert "ix_stats_public_ppr_order" in page_plan("default_order")
        assert "ix_stats_public_scope_ppr" in page_plan("cohort")
        assert evidence["sizes"]["ppr_order_bytes"] > 0
        assert evidence["sizes"]["scope_ppr_bytes"] > 0
    finally:
        if created:
            with engine.begin() as conn:
                for name in created:
                    conn.execute(text(f"DROP INDEX public.{name}"))


def test_index_revision_roundtrip_when_present(database_url):
    path = Path("migrations/versions/0009_stats_public_query_indexes.py")
    if not path.exists():
        pytest.skip("index revision is the stacked PR and is not on this branch")
    source = path.read_text()
    assert PPR_ORDER in source
    assert SCOPE_PPR in source
    url = "postgresql://seam@127.0.0.1:5432/seam_migrate"
    previous = database_url
    cfg = Config("alembic.ini")
    import os

    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0008")
        from sqlalchemy import create_engine

        from loader.url import normalize_database_url

        check = create_engine(normalize_database_url(url))
        with check.connect() as conn:
            names = set(_existing(conn))
            assert "ix_stats_public_ppr_order" not in names
            assert "ix_stats_public_scope_ppr" not in names
        check.dispose()
        command.upgrade(cfg, "head")
        check = create_engine(normalize_database_url(url))
        with check.connect() as conn:
            names = set(_existing(conn))
            assert "ix_stats_public_ppr_order" in names
            assert "ix_stats_public_scope_ppr" in names
        check.dispose()
        command.downgrade(cfg, "base")
    finally:
        os.environ["DATABASE_URL"] = previous
