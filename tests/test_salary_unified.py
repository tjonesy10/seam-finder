"""F008 acceptance tests on real Postgres."""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from loader.salary_private import sha256_bytes
from loader.salary_unified import main, reconcile, revision_hash, run
from web.attribution import ROTOGURU_DK_CLASSIC_ATTRIBUTION

FUTURE = "2099-01-01T00:00:00+00:00"
RULES = {"roster_slots": ["QB", "RB", "WR", "TE", "FLEX", "DST"], "rules_id": "classic", "salary_cap": 50000}
GAMES = [{"away": "BUF", "home": "KC", "game_id": "2024_01_BUF_KC", "kickoff_at": "2024-09-08T17:00:00+00:00"}]
HOLIDAY = [{"away": "DAL", "home": "PHI", "game_id": "2024_16_DAL_PHI", "kickoff_at": "2024-12-25T17:00:00+00:00"}]
VIEW_COLUMNS = {
    "selection_id",
    "selection_scope",
    "is_current",
    "cutoff_at",
    "source",
    "source_snapshot_id",
    "source_row_number",
    "artifact_sha256",
    "raw_retained",
    "observation_id",
    "observed_at",
    "fetched_at",
    "effective_at",
    "draft_group_id",
    "season",
    "season_type",
    "week",
    "canonical_slate_key",
    "slate_revision_sha256",
    "games",
    "rules",
    "entity_key",
    "gsis_id",
    "team_abbr",
    "game_id",
    "dk_id",
    "dff_player_id",
    "salary_source",
    "salary_selected",
    "roster_position_raw",
    "source_pool_kind",
    "anchor_snapshot_id",
    "is_selected",
    "pool_ready",
    "optimizer_ready",
    "quality_flags",
    "alternative_refs",
    "parser_version",
    "mapping_version",
    "evidence_sha256",
    "source_url",
    "original_path",
    "attribution",
}


def _team(conn, abbr):
    conn.execute(
        text(
            """
            INSERT INTO teams (
                team_abbr, team_name, team_nick, team_conf, team_division,
                team_id, team_color, team_color2, loaded_at
            ) VALUES (
                :abbr, :abbr, :abbr, 'AFC', 'West', '1', '#000000', '#ffffff', CURRENT_TIMESTAMP
            ) ON CONFLICT DO NOTHING
            """
        ),
        {"abbr": abbr},
    )


def _player(conn, gsis, team="KC"):
    _team(conn, team)
    conn.execute(
        text(
            """
            INSERT INTO players (gsis_id, display_name, position, latest_team, is_stub, loaded_at)
            VALUES (:gsis, :gsis, 'QB', :team, false, CURRENT_TIMESTAMP)
            ON CONFLICT DO NOTHING
            """
        ),
        {"gsis": gsis, "team": team},
    )


def _game(conn, game_id, away, home, gameday="2024-09-08", week=1):
    _team(conn, away)
    _team(conn, home)
    conn.execute(
        text(
            """
            INSERT INTO games (
                game_id, season, game_type, season_type, week, gameday, weekday, gametime,
                away_team, home_team, location, loaded_at
            ) VALUES (
                :game_id, 2024, 'REG', 'REG', :week, :gameday, 'Sunday', '13:00',
                :away, :home, 'Home', CURRENT_TIMESTAMP
            ) ON CONFLICT DO NOTHING
            """
        ),
        {"game_id": game_id, "away": away, "home": home, "gameday": gameday, "week": week},
    )


def _world(conn):
    _player(conn, "00-0033873", "KC")
    _player(conn, "00-0034857", "BUF")
    _game(conn, "2024_01_BUF_KC", "BUF", "KC", "2024-09-08", 1)
    _game(conn, "2024_16_DAL_PHI", "DAL", "PHI", "2024-12-25", 16)


def _revision(games, week=1):
    return revision_hash(games, RULES, 2024, "REG", week)


def _snapshot(conn, *, source, pool, body, rows, observed_at, draft_group=None, season=2024, week=1, season_type="REG", games=None):
    digest = sha256_bytes(body)
    artifact = conn.execute(
        text(
            """
            INSERT INTO salary_private.salary_artifacts (
                source, sha256, body, byte_count, media_type, artifact_kind, stored_at, loaded_at
            ) VALUES (
                :source, :sha, :body, :byte_count, 'text/csv', 'csv', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            ) RETURNING artifact_id
            """
        ),
        {"source": source, "sha": digest, "body": body, "byte_count": len(body)},
    ).scalar_one()
    metadata = {"raw_retained": True, "optimizer_ready": False}
    meta_sha = sha256_bytes(body + b"|meta")
    snapshot = conn.execute(
        text(
            """
            INSERT INTO salary_private.salary_snapshots (
                snapshot_id, source, artifact_id, parser_version, metadata_sha256, source_snapshot_key,
                season, season_type, week, draft_group_id, games, rules, source_pool_kind, metadata,
                created_at, loaded_at
            ) VALUES (
                gen_random_uuid(), :source, :artifact, 't.1', :meta, :key,
                :season, :season_type, :week, :draft, CAST(:games AS jsonb), '{}'::jsonb, :pool,
                CAST(:metadata AS jsonb), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            ) RETURNING snapshot_id
            """
        ),
        {
            "source": source,
            "artifact": artifact,
            "meta": meta_sha,
            "key": f"{source}:{digest[:12]}",
            "season": season,
            "season_type": season_type,
            "week": week,
            "draft": draft_group,
            "pool": pool,
            "games": json.dumps(games or []),
            "metadata": json.dumps(metadata),
        },
    ).scalar_one()
    for index, row in enumerate(rows, start=1):
        conn.execute(
            text(
                """
                INSERT INTO salary_private.salary_source_rows (
                    artifact_id, parser_version, row_number, raw_fields, parse_status, reason_codes, loaded_at
                ) VALUES (
                    :artifact, 't.1', :row_number, '[]'::jsonb, 'parsed', '[]'::jsonb, CURRENT_TIMESTAMP
                )
                """
            ),
            {"artifact": artifact, "row_number": index},
        )
        table = {
            "dk_lobby": "dk_lobby_salaries",
            "dknfl": "dknfl_salaries",
            "dff": "dff_salaries",
        }[source]
        if source == "dff":
            conn.execute(
                text(
                    f"""
                    INSERT INTO salary_private.{table} (
                        snapshot_id, row_number, artifact_id, parser_version, row_status, reason_codes,
                        salary, dff_player_id, name_raw, team_raw, position_raw, loaded_at
                    ) VALUES (
                        :snapshot, :row_number, :artifact, 't.1', :status, CAST(:reasons AS jsonb),
                        :salary, :native, :name, :team, :position, CURRENT_TIMESTAMP
                    )
                    """
                ),
                {
                    "snapshot": snapshot,
                    "row_number": index,
                    "artifact": artifact,
                    "status": row["status"],
                    "reasons": json.dumps(row.get("reasons") or []),
                    "salary": row.get("salary"),
                    "native": row.get("native"),
                    "name": row.get("name"),
                    "team": row.get("team"),
                    "position": row.get("position") or row.get("roster"),
                },
            )
        else:
            conn.execute(
                text(
                    f"""
                    INSERT INTO salary_private.{table} (
                        snapshot_id, row_number, artifact_id, parser_version, row_status, reason_codes,
                        salary, dk_id, name_raw, roster_position_raw, team_raw, loaded_at
                    ) VALUES (
                        :snapshot, :row_number, :artifact, 't.1', :status, CAST(:reasons AS jsonb),
                        :salary, :native, :name, :roster, :team, CURRENT_TIMESTAMP
                    )
                    """
                ),
                {
                    "snapshot": snapshot,
                    "row_number": index,
                    "artifact": artifact,
                    "status": row["status"],
                    "reasons": json.dumps(row.get("reasons") or []),
                    "salary": row.get("salary"),
                    "native": row.get("native"),
                    "name": row.get("name"),
                    "roster": row.get("roster"),
                    "team": row.get("team"),
                },
            )
    run_id = conn.execute(
        text(
            """
            INSERT INTO load_runs (run_group, dataset, status, trigger, started_at, source_url)
            VALUES (gen_random_uuid(), 'dk_lobby_salaries', 'succeeded', 'local', CURRENT_TIMESTAMP, 'fixture')
            RETURNING id
            """
        )
    ).scalar_one()
    conn.execute(
        text(
            """
            INSERT INTO salary_private.salary_observations (
                observation_id, load_run_id, source, requested_at, started_at, observed_at,
                artifact_id, snapshot_id, metadata, status, loaded_at
            ) VALUES (
                gen_random_uuid(), :run_id, :source, :observed, :observed, :observed,
                :artifact, :snapshot, '{}'::jsonb, 'succeeded', CURRENT_TIMESTAMP
            )
            """
        ),
        {"run_id": run_id, "source": source, "observed": observed_at, "artifact": artifact, "snapshot": snapshot},
    )
    return snapshot, digest


def _mapping(tmp_path, payload, name="mapping.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return path


def _slate(snapshot, games, *, key="main", group="dg-1", status="verified", complete=True, effective=None, equivalents=None, week=1, source="dk_lobby"):
    item = {
        "source": source,
        "snapshot_id": str(snapshot),
        "canonical_slate_key": key,
        "slate_revision_sha256": _revision(games, week),
        "status": status,
        "games": games,
        "rules": RULES,
        "draft_group_id": group,
        "equivalent_group_ids": equivalents or [],
        "complete_pool": complete,
        "effective_time_basis": "effective_at",
    }
    if effective is not None:
        item["effective_at"] = effective
    return item


def _entity(snapshot, row_number, *, gsis=None, team="KC", game="2024_01_BUF_KC", kind="player", status="verified", source="dk_lobby"):
    return {
        "source": source,
        "snapshot_id": str(snapshot),
        "row_number": row_number,
        "status": status,
        "kind": kind,
        "gsis_id": gsis,
        "team_abbr": team,
        "game_id": game,
        "method": "reviewed",
        "reason": "reviewed",
    }


def _publish(database_url, path, scope="slate", cutoff=FUTURE, fault=None):
    return run(database_url, scope, cutoff, path, "local", fault=fault)


def _view(conn, scope="slate"):
    return conn.execute(
        text("SELECT * FROM salary_private.dk_salary_unified WHERE selection_scope = :scope"),
        {"scope": scope},
    ).mappings().all()


def test_at1_view_columns_and_attribution(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        snapshot, _sha = _snapshot(
            conn,
            source="dk_lobby",
            pool="full_export",
            body=b"lobby-a",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC),
            draft_group="dg-1",
        )
    payload = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, GAMES)],
        "entities": [_entity(snapshot, 1, gsis="00-0033873")],
    }
    assert _publish(database_url, _mapping(tmp_path, payload)) == 0
    with engine.connect() as conn:
        rows = _view(conn)
        assert rows
        assert VIEW_COLUMNS <= set(rows[0].keys())
        assert rows[0]["attribution"].startswith("Unauthenticated DraftKings Classic lobby")
        assert rows[0]["dk_id"] == "111"
        assert rows[0]["dff_player_id"] is None
        assert rows[0]["optimizer_ready"] is True
    web = " ".join(path.read_text() for path in Path("web").rglob("*.py"))
    assert "salary_unified" not in web
    assert "optimizer" not in Path("loader/salary_unified.py").read_text().split("No API", 1)[0]


def test_at2_different_games_do_not_merge(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        main, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"main-slate",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-main",
        )
        holiday, _sha = _snapshot(
            conn, source="dknfl", pool="full_export", body=b"holiday-slate",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "PHI"}],
            observed_at=datetime(2024, 12, 1, tzinfo=UTC), draft_group="dg-holiday", week=16,
        )
    payload = {
        "mapping_version": "v1",
        "slates": [_slate(main, GAMES, key="main", group="dg-main"), _slate(holiday, HOLIDAY, key="holiday", group="dg-holiday", week=16, source="dknfl")],
        "entities": [
            _entity(main, 1, gsis="00-0033873"),
            _entity(holiday, 1, gsis="00-0033873", team="PHI", game="2024_16_DAL_PHI", source="dknfl"),
        ],
    }
    assert _publish(database_url, _mapping(tmp_path, payload)) == 0
    with engine.connect() as conn:
        rows = _view(conn)
        revisions = {row["slate_revision_sha256"] for row in rows}
        assert len(revisions) == 2
        main_rows = [row for row in rows if row["canonical_slate_key"] == "main" and row["is_selected"]]
        holiday_rows = [row for row in rows if row["canonical_slate_key"] == "holiday" and row["is_selected"]]
        assert {row["source_snapshot_id"] for row in main_rows} == {main}
        assert {row["source_snapshot_id"] for row in holiday_rows} == {holiday}


def test_at3_identity_namespaces(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        _player(conn, "00-0033873", "KC")
        lobby, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"ident-lobby",
            rows=[
                {"status": "valid", "salary": "5000", "native": "1001", "name": "Patrick", "roster": "QB", "team": "KC"},
                {"status": "valid", "salary": "4000", "native": "2002", "name": "Defense", "roster": "DST", "team": "KC"},
                {"status": "valid", "salary": "4500", "native": "3003", "name": "Moved", "roster": "QB", "team": "BUF"},
            ],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
        dff, _sha = _snapshot(
            conn, source="dff", pool="subset", body=b"ident-dff",
            rows=[{"status": "valid", "salary": "5000", "native": "00-0033873", "name": "Patrick", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC),
        )
    payload = {
        "mapping_version": "v1",
        "slates": [
            _slate(lobby, GAMES),
            _slate(dff, GAMES, group=None, source="dff"),
        ],
        "entities": [
            _entity(dff, 1, gsis="00-0033873", source="dff"),
            _entity(lobby, 1, gsis="00-0033873"),
            _entity(lobby, 2, kind="dst", gsis=None, team="KC", game=None),
            _entity(lobby, 3, gsis="00-0033873", team="KC"),
        ],
    }
    payload["slates"][1]["draft_group_id"] = None
    assert _publish(database_url, _mapping(tmp_path, payload)) == 0
    with engine.connect() as conn:
        rows = _view(conn)
        dff_row = next(row for row in rows if row["source"] == "dff")
        assert dff_row["dff_player_id"] == "00-0033873"
        assert dff_row["dk_id"] is None
        assert dff_row["gsis_id"] is None
        dst = next(row for row in rows if row["source"] == "dk_lobby" and row["source_row_number"] == 2)
        assert dst["entity_key"] == "dst:KC"
        moved = next(row for row in rows if row["source_row_number"] == 3 and row["source"] == "dk_lobby")
        assert moved["entity_key"] is None
        assert moved["is_selected"] is False


def test_at4_observation_order_and_ties(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        first, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"obs-a",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
        second, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"obs-b",
            rows=[{"status": "valid", "salary": "5100", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 2, tzinfo=UTC), draft_group="dg-1",
        )
        conn.execute(
            text(
                """
                INSERT INTO salary_private.salary_observations (
                    observation_id, load_run_id, source, requested_at, started_at, observed_at,
                    artifact_id, snapshot_id, metadata, status, loaded_at
                )
                SELECT gen_random_uuid(), load_run_id, source, :observed, :observed, :observed,
                       artifact_id, snapshot_id, '{}'::jsonb, 'succeeded', CURRENT_TIMESTAMP
                FROM salary_private.salary_observations WHERE snapshot_id = :snapshot
                """
            ),
            {"observed": datetime(2024, 9, 3, tzinfo=UTC), "snapshot": first},
        )
        low, low_sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"tie-a",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 8, 1, tzinfo=UTC), draft_group="dg-tie",
        )
        high, high_sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"tie-b",
            rows=[{"status": "valid", "salary": "5200", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 8, 1, tzinfo=UTC), draft_group="dg-tie",
        )
    assert high_sha != low_sha
    winner = high if high_sha > low_sha else low
    payload = {
        "mapping_version": "v1",
        "slates": [
            _slate(first, GAMES, effective="2024-09-01T00:00:00+00:00"),
            _slate(second, GAMES, effective="2024-09-02T00:00:00+00:00"),
            _slate(low, GAMES, key="tie", group="dg-tie"),
            _slate(high, GAMES, key="tie", group="dg-tie"),
        ],
        "entities": [
            _entity(first, 1, gsis="00-0033873"),
            _entity(second, 1, gsis="00-0033873"),
            _entity(low, 1, gsis="00-0033873"),
            _entity(high, 1, gsis="00-0033873"),
        ],
    }
    path = _mapping(tmp_path, payload)
    assert _publish(database_url, path, cutoff="2024-09-02T12:00:00+00:00") == 0
    with engine.connect() as conn:
        rows = [row for row in _view(conn) if row["canonical_slate_key"] == "main" and row["is_selected"]]
        assert {row["source_snapshot_id"] for row in rows} == {second}
    assert _publish(database_url, path, scope="after", cutoff="2024-09-04T00:00:00+00:00") == 0
    with engine.connect() as conn:
        rows = [row for row in _view(conn, "after") if row["canonical_slate_key"] == "main" and row["is_selected"]]
        assert {row["source_snapshot_id"] for row in rows} == {first}
        tied = [row for row in _view(conn, "after") if row["canonical_slate_key"] == "tie" and row["is_selected"]]
        assert {row["source_snapshot_id"] for row in tied} == {winner}


def test_at5_archive_chronology_needs_a_choice(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        older, _sha = _snapshot(
            conn, source="dknfl", pool="full_export", body=b"arch-old",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 1, 2, tzinfo=UTC),
        )
        newer, _sha = _snapshot(
            conn, source="dknfl", pool="full_export", body=b"arch-new",
            rows=[{"status": "valid", "salary": "5300", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 1, 3, tzinfo=UTC),
        )
    base = {
        "mapping_version": "v1",
        "slates": [_slate(older, GAMES, group=None, source="dknfl"), _slate(newer, GAMES, group=None, source="dknfl")],
        "entities": [_entity(older, 1, gsis="00-0033873", source="dknfl"), _entity(newer, 1, gsis="00-0033873", source="dknfl")],
    }
    base["slates"][0]["draft_group_id"] = None
    base["slates"][1]["draft_group_id"] = None
    assert _publish(database_url, _mapping(tmp_path, base), scope="noch") == 0
    with engine.connect() as conn:
        rows = _view(conn, "noch")
        assert not any(row["is_selected"] for row in rows)
        assert any("chronology_unknown" in row["quality_flags"]["flags"] for row in rows)
    chosen = dict(base)
    chosen["snapshot_choices"] = [
        {
            "source": "dknfl",
            "canonical_slate_key": "main",
            "slate_revision_sha256": _revision(GAMES),
            "snapshot_id": str(older),
            "anchor": True,
            "reason": "reviewed",
        }
    ]
    assert _publish(database_url, _mapping(tmp_path, chosen, "choice.json"), scope="ch") == 0
    with engine.connect() as conn:
        selected = [row for row in _view(conn, "ch") if row["is_selected"]]
        assert {row["source_snapshot_id"] for row in selected} == {older}


def test_at6_no_pool_filling(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        anchor, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"anchor",
            rows=[
                {"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"},
                {"status": "valid", "salary": "4500", "native": "222", "name": "Unresolved", "roster": "RB", "team": "KC"},
            ],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
        extra, _sha = _snapshot(
            conn, source="dknfl", pool="full_export", body=b"extra-player",
            rows=[{"status": "valid", "salary": "3000", "native": "333", "name": "OnlyThere", "roster": "WR", "team": "BUF"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC),
        )
        dff, _sha = _snapshot(
            conn, source="dff", pool="subset", body=b"subset",
            rows=[{"status": "valid", "salary": "5000", "native": "dff1", "name": "Patrick", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC),
        )
        rejected, _sha = _snapshot(
            conn, source="dknfl", pool="full_export", body=b"rejected-player",
            rows=[
                {"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"},
                {"status": "rejected", "salary": "5000", "native": "444", "name": "Plausible", "roster": "RB", "team": "KC", "reasons": ["invalid_salary"]},
            ],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-bad",
        )
        body = b"ledger-only"
        digest = sha256_bytes(body)
        artifact = conn.execute(
            text(
                """
                INSERT INTO salary_private.salary_artifacts (
                    source, sha256, body, byte_count, media_type, artifact_kind, stored_at, loaded_at
                ) VALUES (
                    'dk_lobby', :sha, :body, :byte_count, 'text/csv', 'csv', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                ) RETURNING artifact_id
                """
            ),
            {"sha": digest, "body": body, "byte_count": len(body)},
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO salary_private.salary_source_rows (
                    artifact_id, parser_version, row_number, raw_fields, parse_status, reason_codes, loaded_at
                ) VALUES (
                    :artifact, 'f005.1', 1, '[]'::jsonb, 'parsed', '[]'::jsonb, CURRENT_TIMESTAMP
                )
                """
            ),
            {"artifact": artifact},
        )
    payload = {
        "mapping_version": "v1",
        "slates": [
            _slate(anchor, GAMES),
            _slate(extra, GAMES, group=None, source="dknfl"),
            _slate(dff, GAMES, group=None, source="dff"),
            _slate(rejected, GAMES, key="bad", group="dg-bad", source="dknfl"),
        ],
        "entities": [
            _entity(anchor, 1, gsis="00-0033873"),
            _entity(extra, 1, gsis="00-0034857", team="BUF", source="dknfl"),
            _entity(rejected, 1, gsis="00-0033873", source="dknfl"),
        ],
    }
    payload["slates"][1]["draft_group_id"] = None
    payload["slates"][1]["equivalent_group_ids"] = ["dg-1"]
    payload["slates"][2]["draft_group_id"] = None
    payload["slates"][2]["equivalent_group_ids"] = ["dg-1"]
    assert _publish(database_url, _mapping(tmp_path, payload)) == 0
    with engine.connect() as conn:
        rows = _view(conn)
        extra_row = next(row for row in rows if row["source_snapshot_id"] == extra)
        assert "alternative_not_in_anchor" in extra_row["quality_flags"]["flags"]
        assert extra_row["is_selected"] is False
        assert not any(row["optimizer_ready"] for row in rows if row["canonical_slate_key"] == "main")
        assert not any(row["optimizer_ready"] for row in rows if row["source"] == "dff")
        assert not any(row["optimizer_ready"] for row in rows if row["source_snapshot_id"] == rejected)
        assert conn.execute(text("SELECT count(*) FROM salary_private.dk_lobby_salaries")).scalar_one() == 2


def test_at7_official_priority(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        lobby, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"pri-lobby",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 2, tzinfo=UTC), draft_group="dg-1",
        )
        conn.execute(
            text(
                """
                INSERT INTO dk_classic_slate (
                    season, week, dk_id, name_raw, position_raw, roster_position_raw, team_raw,
                    game_info_raw, salary, source_name, source_sha256, source_loaded_at, loaded_at
                ) VALUES (
                    2024, 1, '111', 'Patrick', 'QB', 'QB', 'KC', 'BUF@KC', 5000,
                    'DKSalaries.csv', :sha, '2024-09-01T00:00:00+00:00', CURRENT_TIMESTAMP
                )
                """
            ),
            {"sha": "a" * 64},
        )
        other, _sha = _snapshot(
            conn, source="dknfl", pool="full_export", body=b"pri-other",
            rows=[{"status": "valid", "salary": "1000", "native": "999", "name": "Other", "roster": "QB", "team": "BUF"}],
            observed_at=datetime(2024, 9, 2, tzinfo=UTC), draft_group="dg-other", week=16,
        )
    later = {
        "mapping_version": "v1",
        "slates": [
            _slate(lobby, GAMES, effective="2024-09-03T00:00:00+00:00"),
            _slate(other, HOLIDAY, key="other", group="dg-other", week=16, source="dknfl"),
        ],
        "entities": [_entity(lobby, 1, gsis="00-0033873"), _entity(other, 1, gsis="00-0034857", team="BUF", game="2024_16_DAL_PHI", source="dknfl")],
    }
    assert _publish(database_url, _mapping(tmp_path, later)) == 0
    with engine.connect() as conn:
        f004 = conn.execute(text("SELECT snapshot_id FROM salary_private.salary_snapshots WHERE source = 'f004_adapter'")).scalar_one()
        rows = [row for row in _view(conn) if row["canonical_slate_key"] == "main" and row["is_selected"]]
        assert {row["source_snapshot_id"] for row in rows} == {lobby}
        assert all(row["anchor_snapshot_id"] == lobby for row in rows)
    equal = {
        "mapping_version": "v1",
        "slates": [
            _slate(lobby, GAMES, effective="2024-09-03T00:00:00+00:00"),
            {
                **_slate(f004, GAMES, effective="2024-09-03T00:00:00+00:00", source="f004_adapter"),
                "source": "f004_adapter",
                "draft_group_id": "dg-1",
            },
        ],
        "entities": [
            _entity(lobby, 1, gsis="00-0033873"),
            _entity(f004, 1, gsis="00-0033873", source="f004_adapter"),
        ],
    }
    assert _publish(database_url, _mapping(tmp_path, equal, "equal.json"), scope="equal") == 0
    with engine.connect() as conn:
        rows = [row for row in _view(conn, "equal") if row["canonical_slate_key"] == "main" and row["is_selected"]]
        assert {row["source"] for row in rows} == {"f004_adapter"}


def test_at8_disagreement_and_resolution(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        lobby, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"dis-lobby",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 2, tzinfo=UTC), draft_group="dg-1",
        )
        other, _sha = _snapshot(
            conn, source="dknfl", pool="full_export", body=b"dis-other",
            rows=[{"status": "valid", "salary": "5100", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC),
        )
    base = {
        "mapping_version": "v1",
        "slates": [_slate(lobby, GAMES, effective="2024-09-02T00:00:00+00:00"), _slate(other, GAMES, group=None, source="dknfl")],
        "entities": [_entity(lobby, 1, gsis="00-0033873"), _entity(other, 1, gsis="00-0033873", source="dknfl")],
    }
    base["slates"][1]["draft_group_id"] = None
    base["slates"][1]["equivalent_group_ids"] = ["dg-1"]
    assert _publish(database_url, _mapping(tmp_path, base), scope="open") == 0
    with engine.connect() as conn:
        selected = next(row for row in _view(conn, "open") if row["is_selected"])
        assert selected["pool_ready"] is False
        assert selected["alternative_refs"]
        assert "disagreement" in selected["quality_flags"]["flags"]
    resolved = dict(base)
    resolved["resolutions"] = [
        {
            "canonical_slate_key": "main",
            "slate_revision_sha256": _revision(GAMES),
            "entity_key": "player:00-0033873",
            "chosen_ref": {"snapshot_id": str(lobby), "row_number": 1},
            "reason": "reviewed",
        }
    ]
    assert _publish(database_url, _mapping(tmp_path, resolved, "res.json"), scope="res") == 0
    with engine.connect() as conn:
        selected = next(row for row in _view(conn, "res") if row["is_selected"])
        assert selected["optimizer_ready"] is True
        assert "disagreement" in selected["quality_flags"]["flags"]
    override = dict(base)
    override["resolutions"] = [
        {
            "canonical_slate_key": "main",
            "slate_revision_sha256": _revision(GAMES),
            "entity_key": "player:00-0033873",
            "chosen_ref": {"snapshot_id": str(other), "row_number": 1},
            "reason": "cross",
        }
    ]
    assert _publish(database_url, _mapping(tmp_path, override, "over.json"), scope="over") == 0
    with engine.connect() as conn:
        selected = next(row for row in _view(conn, "over") if row["is_selected"])
        assert selected["optimizer_ready"] is False
        assert "cross_source_override" in selected["quality_flags"]["flags"]


def test_at9_unsafe_pool_flags(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        snapshot, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"unsafe",
            rows=[
                {"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"},
                {"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"},
                {"status": "valid", "salary": "0", "native": "222", "name": "Zero", "roster": "RB", "team": "KC"},
                {"status": "rejected", "salary": None, "native": None, "name": "", "roster": "", "team": ""},
                {"status": "rejected", "salary": "4800", "native": "333", "name": "Maybe", "roster": "WR", "team": "KC", "reasons": ["bad"]},
            ],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
    payload = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, GAMES, status="verified")],
        "entities": [
            _entity(snapshot, 1, gsis="00-0033873"),
            _entity(snapshot, 2, gsis="00-0033873"),
            _entity(snapshot, 3, gsis="00-0034857", team="KC"),
        ],
    }
    assert _publish(database_url, _mapping(tmp_path, payload)) == 0
    with engine.connect() as conn:
        rows = _view(conn)
        assert not any(row["optimizer_ready"] for row in rows)
        flags = [flag for row in rows for flag in row["quality_flags"]["flags"]]
        assert "duplicate_entity" in flags
        assert "nonpositive_salary" in flags
        assert "blank_placeholder" in flags
        assert "plausible_reject" in flags
        summary = conn.execute(text("SELECT summary FROM salary_private.salary_selection_batches")).scalar_one()
        assert summary["blank_placeholders"] == 1


def test_at10_f003_stays_legacy(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        conn.execute(
            text(
                """
                INSERT INTO dk_classic_salaries (
                    season, week, rotoguru_gid, name_raw, pos_raw, team_raw, home_away, opponent_raw,
                    dk_points, dk_salary, gsis_id, team_abbr, game_id, source_url, source_fetched_at,
                    source_sha256, loaded_at
                ) VALUES (
                    2024, 1, 10, 'Patrick', 'QB', 'KC', 'H', 'BUF', 21.5, 5000, '00-0033873', 'KC',
                    '2024_01_BUF_KC', 'http://rotoguru1.com/example', CURRENT_TIMESTAMP, :sha, CURRENT_TIMESTAMP
                )
                """
            ),
            {"sha": "b" * 64},
        )
        lobby, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"live-near-f003",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
        before = conn.execute(text("SELECT count(*) FROM dk_classic_salaries")).scalar_one()
    payload = {
        "mapping_version": "v1",
        "slates": [_slate(lobby, GAMES)],
        "entities": [_entity(lobby, 1, gsis="00-0033873")],
    }
    assert _publish(database_url, _mapping(tmp_path, payload)) == 0
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM dk_classic_salaries")).scalar_one() == before
        legacy = next(row for row in _view(conn) if row["source"] == "f003_adapter")
        assert legacy["is_selected"] is False
        assert legacy["canonical_slate_key"] is None
        assert legacy["optimizer_ready"] is False
        assert legacy["raw_retained"] is False
        body = conn.execute(
            text(
                """
                SELECT body FROM salary_private.salary_artifacts
                WHERE source = 'f003_adapter'
                """
            )
        ).scalar_one()
        assert b"21.5" in bytes(body)
        assert legacy["attribution"] == ROTOGURU_DK_CLASSIC_ATTRIBUTION


def test_at11_f004_current_cohort_only(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        for digest, dk_id in (("c" * 64, "111"), ("d" * 64, "222")):
            conn.execute(
                text(
                    """
                    INSERT INTO dk_classic_slate (
                        season, week, dk_id, name_raw, position_raw, roster_position_raw, team_raw,
                        game_info_raw, salary, source_name, source_sha256, source_loaded_at, loaded_at
                    ) VALUES (
                        2024, 1, :dk_id, 'Player', 'QB', 'QB', 'KC', 'BUF@KC', 5000,
                        'DKSalaries.csv', :sha, '2020-01-01T00:00:00+00:00', CURRENT_TIMESTAMP
                    )
                    """
                ),
                {"dk_id": dk_id, "sha": digest},
            )
        before = conn.execute(text("SELECT count(*) FROM dk_classic_slate")).scalar_one()
    payload = {"mapping_version": "v1", "slates": [], "entities": []}
    assert _publish(database_url, _mapping(tmp_path, payload), scope="mixed") == 0
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM dk_classic_slate")).scalar_one() == before
        rows = _view(conn, "mixed")
        assert rows
        assert all(row["raw_retained"] is False for row in rows)
        assert all(row["optimizer_ready"] is False for row in rows)
        assert conn.execute(
            text("SELECT count(*) FROM salary_private.salary_snapshots WHERE source = 'f004_adapter'")
        ).scalar_one() == 2


def test_at12_reuse_then_new_evidence(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        snapshot, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"reuse",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
    payload = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, GAMES)],
        "entities": [_entity(snapshot, 1, gsis="00-0033873")],
    }
    path = _mapping(tmp_path, payload)
    assert _publish(database_url, path) == 0
    assert _publish(database_url, path) == 0
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM salary_private.salary_selection_batches")).scalar_one() == 1
        assert conn.execute(
            text("SELECT count(*) FROM load_runs WHERE dataset = 'dk_salary_unified' AND status = 'succeeded'")
        ).scalar_one() == 2
        pinned = conn.execute(text("SELECT selection_id FROM salary_private.salary_selection_batches")).scalar_one()
    payload["mapping_version"] = "v2"
    assert _publish(database_url, _mapping(tmp_path, payload, "v2.json")) == 0
    with engine.connect() as conn:
        current = conn.execute(
            text("SELECT selection_id FROM salary_private.dk_salary_unified WHERE is_current LIMIT 1")
        ).scalar_one()
        assert current != pinned
        old = conn.execute(
            text("SELECT is_current FROM salary_private.dk_salary_unified WHERE selection_id = :id LIMIT 1"),
            {"id": pinned},
        ).scalar_one()
        assert old is False


def test_at13_failure_keeps_prior_batch(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        snapshot, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"prior",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
    payload = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, GAMES)],
        "entities": [_entity(snapshot, 1, gsis="00-0033873")],
    }
    path = _mapping(tmp_path, payload)
    assert _publish(database_url, path) == 0
    with engine.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM salary_private.salary_selection_rows")).scalar_one()
        salaries = conn.execute(text("SELECT count(*) FROM salary_private.dk_lobby_salaries")).scalar_one()
    assert _publish(database_url, path, scope="fault", fault="mid_batch") == 1
    assert _publish(database_url, path, scope="dup", fault="force_duplicate") == 1
    results = []

    def _once():
        results.append(_publish(database_url, path, scope="conc"))

    threads = [threading.Thread(target=_once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [0, 0]
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM salary_private.salary_selection_rows WHERE selection_id IN (SELECT selection_id FROM salary_private.salary_selection_batches WHERE selection_scope = 'slate')")).scalar_one() == before
        assert conn.execute(text("SELECT count(*) FROM salary_private.dk_lobby_salaries")).scalar_one() == salaries
        assert conn.execute(text("SELECT count(*) FROM salary_private.salary_selection_batches WHERE selection_scope = 'conc'")).scalar_one() == 1
        assert conn.execute(
            text("SELECT count(*) FROM load_runs WHERE dataset = 'dk_salary_unified' AND status = 'failed'")
        ).scalar_one() >= 2


def test_at14_coverage_denominators(engine, database_url, tmp_path):
    path = _mapping(tmp_path, {"mapping_version": "v1"})
    assert _publish(database_url, path, scope="empty") == 0
    with engine.connect() as conn:
        summary = conn.execute(
            text("SELECT summary, notes FROM salary_private.salary_selection_batches b JOIN load_runs r ON r.id = b.load_run_id")
        ).one()
        assert summary.summary["rates"]["skill_mapped"] is None
        assert "98%" not in summary.notes
        assert "95%" not in summary.notes
        assert summary.summary["raw_records"] == 0


def test_at15_private_grants(engine, database_url, tmp_path, monkeypatch):
    import psycopg
    from sqlalchemy.exc import DBAPIError

    from loader.grants import apply_readonly_grant, revoke_readonly_grant

    def denied(conn, statement):
        conn.execute(text("SAVEPOINT grant_check"))
        try:
            conn.execute(text(statement))
        except DBAPIError as caught:
            conn.execute(text("ROLLBACK TO SAVEPOINT grant_check"))
            assert isinstance(caught.orig, psycopg.errors.InsufficientPrivilege)
            return True
        conn.execute(text("RELEASE SAVEPOINT grant_check"))
        return False

    with engine.begin() as conn:
        _world(conn)
        snapshot, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"grant",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
    payload = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, GAMES)],
        "entities": [_entity(snapshot, 1, gsis="00-0033873")],
    }
    assert _publish(database_url, _mapping(tmp_path, payload)) == 0
    monkeypatch.setenv("READONLY_ROLE", "seam_web_reader")
    monkeypatch.setenv("OPTIMIZER_ROLE", "seam_optimizer")
    with engine.connect() as conn:
        revoke_readonly_grant(conn)
        if conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'seam_optimizer'")).first():
            conn.execute(text("REVOKE ALL ON SCHEMA salary_private FROM seam_optimizer"))
            conn.execute(text("REVOKE ALL ON ALL TABLES IN SCHEMA salary_private FROM seam_optimizer"))
        conn.execute(text("DROP ROLE IF EXISTS seam_web_reader"))
        conn.execute(text("DROP ROLE IF EXISTS seam_optimizer"))
        conn.execute(text("CREATE ROLE seam_web_reader"))
        conn.execute(text("CREATE ROLE seam_optimizer"))
        apply_readonly_grant(conn)
        apply_readonly_grant(conn)
        conn.commit()
        conn.execute(text("SET ROLE seam_web_reader"))
        assert denied(conn, "SELECT 1 FROM salary_private.dk_salary_unified")
        assert denied(conn, "SELECT 1 FROM salary_private.dff_salaries")
        assert denied(conn, "SELECT 1 FROM dk_classic_slate")
        conn.execute(text("SET ROLE seam_web_reader"))
        assert conn.execute(text("SELECT count(*) FROM teams")).scalar_one() >= 1
        conn.execute(text("RESET ROLE"))
        conn.execute(text("SET ROLE seam_optimizer"))
        assert conn.execute(text("SELECT count(*) FROM salary_private.dk_salary_unified")).scalar_one() >= 1
        assert denied(conn, "SELECT 1 FROM salary_private.dff_salaries")
        assert denied(
            conn,
            "INSERT INTO salary_private.salary_selection_batches (selection_id, selection_scope, cutoff_at, mapping_version, input_sha256, load_run_id, committed_at, summary) VALUES (gen_random_uuid(), 'x', CURRENT_TIMESTAMP, 'v', repeat('a', 64), 1, CURRENT_TIMESTAMP, '{}')",
        )
        conn.execute(text("RESET ROLE"))
        revoke_readonly_grant(conn)
        conn.execute(text("REVOKE ALL ON SCHEMA salary_private FROM seam_optimizer"))
        conn.execute(text("REVOKE ALL ON ALL TABLES IN SCHEMA salary_private FROM seam_optimizer"))
        conn.execute(text("DROP ROLE IF EXISTS seam_web_reader"))
        conn.execute(text("DROP ROLE IF EXISTS seam_optimizer"))
        conn.commit()


def test_at16_bounded_failures(engine, database_url, tmp_path, capsys):
    with engine.begin() as conn:
        _world(conn)
        snapshot, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"guard",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
    good = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, GAMES)],
        "entities": [_entity(snapshot, 1, gsis="00-0033873")],
    }
    assert _publish(database_url, _mapping(tmp_path, good)) == 0
    with engine.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM salary_private.salary_selection_batches")).scalar_one()
    bad = dict(good)
    bad["slates"] = [_slate("00000000-0000-0000-0000-000000000099", GAMES)]
    assert _publish(database_url, _mapping(tmp_path, bad, "bad.json")) == 1
    assert _publish(database_url, _mapping(tmp_path, good), cutoff="2024-01-01T00:00:00") == 1
    huge = tmp_path / "huge.json"
    huge.write_bytes(b'{"mapping_version":"v1","pad":"' + (b"x" * (5 * 1024 * 1024)) + b'"}')
    assert run(database_url, "slate", FUTURE, huge, "local") == 1
    captured = capsys.readouterr()
    assert "5000" not in captured.out
    assert "5000" not in captured.err
    assert str(tmp_path) not in captured.out
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM salary_private.salary_selection_batches")).scalar_one() == before
        notes = " ".join(
            row[0] or ""
            for row in conn.execute(text("SELECT notes FROM load_runs WHERE dataset = 'dk_salary_unified'"))
        )
        assert "98%" not in notes
        assert str(tmp_path) not in notes


def test_slate_rules_kickoff_game_and_group_bridge(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        left, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"bridge-a",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-a",
        )
        unknown, _sha = _snapshot(
            conn, source="dknfl", pool="full_export", body=b"bridge-u",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC),
        )
        right, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"bridge-b",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-b",
        )
        naive = dict(GAMES[0])
        naive["kickoff_at"] = "2024-09-08T17:00:00"
    bad_rules = {
        "mapping_version": "v1",
        "slates": [_slate(left, GAMES) | {"rules": {"rules_id": None, "roster_slots": None, "salary_cap": None}}],
        "entities": [_entity(left, 1, gsis="00-0033873")],
    }
    assert _publish(database_url, _mapping(tmp_path, bad_rules), scope="rules") == 0
    naive_payload = {
        "mapping_version": "v1",
        "slates": [_slate(left, [naive])],
        "entities": [_entity(left, 1, gsis="00-0033873")],
    }
    assert _publish(database_url, _mapping(tmp_path, naive_payload, "naive.json"), scope="naive") == 0
    wrong_game = {
        "mapping_version": "v1",
        "slates": [_slate(left, GAMES)],
        "entities": [_entity(left, 1, gsis="00-0033873", team="KC", game="2024_16_DAL_PHI")],
    }
    assert _publish(database_url, _mapping(tmp_path, wrong_game, "wrong.json"), scope="wrong") == 0
    bridge = {
        "mapping_version": "v1",
        "slates": [
            _slate(left, GAMES, key="shared", group="dg-a"),
            _slate(unknown, GAMES, key="shared", group=None, source="dknfl"),
            _slate(right, GAMES, key="shared", group="dg-b"),
        ],
        "entities": [
            _entity(left, 1, gsis="00-0033873"),
            _entity(unknown, 1, gsis="00-0033873", source="dknfl"),
            _entity(right, 1, gsis="00-0033873"),
        ],
    }
    bridge["slates"][1]["draft_group_id"] = None
    assert _publish(database_url, _mapping(tmp_path, bridge, "bridge.json"), scope="bridge") == 0
    with engine.connect() as conn:
        for scope in ("rules", "naive", "wrong", "bridge"):
            assert not any(row["optimizer_ready"] for row in _view(conn, scope))


def test_newer_incomplete_blocks_older_ready(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        older, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"older-ready",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
        newer, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"newer-incomplete",
            rows=[{"status": "valid", "salary": "5100", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 3, tzinfo=UTC), draft_group="dg-1",
        )
        dupes, _sha = _snapshot(
            conn, source="dknfl", pool="full_export", body=b"dup-native",
            rows=[
                {"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"},
                {"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"},
            ],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-dup",
        )
    payload = {
        "mapping_version": "v1",
        "slates": [
            _slate(older, GAMES, effective="2024-09-01T00:00:00+00:00"),
            _slate(newer, GAMES, complete=False, effective="2024-09-03T00:00:00+00:00"),
        ],
        "entities": [_entity(older, 1, gsis="00-0033873"), _entity(newer, 1, gsis="00-0033873")],
    }
    assert _publish(database_url, _mapping(tmp_path, payload), scope="blockold") == 0
    dup_payload = {
        "mapping_version": "v1",
        "slates": [_slate(dupes, GAMES, key="dups", group="dg-dup", source="dknfl")],
        "entities": [
            _entity(dupes, 1, gsis="00-0033873", source="dknfl"),
            _entity(dupes, 2, gsis="00-0034857", team="BUF", source="dknfl"),
        ],
    }
    assert _publish(database_url, _mapping(tmp_path, dup_payload, "dups.json"), scope="dups") == 0
    with engine.connect() as conn:
        assert not any(row["optimizer_ready"] for row in _view(conn, "blockold"))
        assert not any(row["is_selected"] and row["source_snapshot_id"] == older for row in _view(conn, "blockold"))
        assert not any(row["optimizer_ready"] for row in _view(conn, "dups"))


def test_one_resolution_does_not_clear_every_dispute(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        lobby, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"two-disputes",
            rows=[
                {"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"},
                {"status": "valid", "salary": "4000", "native": "222", "name": "Josh", "roster": "QB", "team": "BUF"},
            ],
            observed_at=datetime(2024, 9, 2, tzinfo=UTC), draft_group="dg-1",
        )
        other, _sha = _snapshot(
            conn, source="dknfl", pool="full_export", body=b"two-disputes-other",
            rows=[
                {"status": "valid", "salary": "5100", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"},
                {"status": "valid", "salary": "4100", "native": "222", "name": "Josh", "roster": "QB", "team": "BUF"},
            ],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC),
        )
    payload = {
        "mapping_version": "v1",
        "slates": [
            _slate(lobby, GAMES, effective="2024-09-02T00:00:00+00:00"),
            _slate(other, GAMES, group=None, source="dknfl"),
        ],
        "entities": [
            _entity(lobby, 1, gsis="00-0033873"),
            _entity(lobby, 2, gsis="00-0034857", team="BUF"),
            _entity(other, 1, gsis="00-0033873", source="dknfl"),
            _entity(other, 2, gsis="00-0034857", team="BUF", source="dknfl"),
        ],
        "resolutions": [
            {
                "canonical_slate_key": "main",
                "slate_revision_sha256": _revision(GAMES),
                "entity_key": "player:00-0033873",
                "chosen_ref": {"snapshot_id": str(lobby), "row_number": 1},
                "reason": "one-only",
            }
        ],
    }
    payload["slates"][1]["draft_group_id"] = None
    payload["slates"][1]["equivalent_group_ids"] = ["dg-1"]
    assert _publish(database_url, _mapping(tmp_path, payload), scope="partialres") == 0
    with engine.connect() as conn:
        selected = [row for row in _view(conn, "partialres") if row["is_selected"]]
        assert selected
        assert all(row["optimizer_ready"] is False for row in selected)


def test_coverage_counts_skill_apart_from_dst(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        snapshot, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"coverage",
            rows=[
                {"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"},
                {"status": "valid", "salary": "3000", "native": "222", "name": "Chiefs", "roster": "DST", "team": "KC"},
                {"status": "valid", "salary": "4500", "native": "333", "name": "Unmapped", "roster": "RB", "team": "KC"},
            ],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
    payload = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, GAMES)],
        "entities": [
            _entity(snapshot, 1, gsis="00-0033873"),
            _entity(snapshot, 2, kind="dst", gsis=None, team="KC", game=None),
        ],
    }
    assert _publish(database_url, _mapping(tmp_path, payload), scope="cover") == 0
    with engine.connect() as conn:
        summary = conn.execute(text("SELECT summary FROM salary_private.salary_selection_batches WHERE selection_scope = 'cover'")).scalar_one()
        lobby = summary["by_source"]["dk_lobby"]
        assert lobby["skill"] == 2
        assert lobby["dst"] == 1
        assert lobby["mapped"] == 1
        assert lobby["dst_mapped"] == 1
        assert lobby["unmapped"] == 1
        assert summary["rates"]["skill_mapped"] == {"numerator": 1, "denominator": 2}
        assert summary["raw_records"] == lobby["raw"] == 3


def test_missing_table_fails_closed_and_audit_can_reconcile(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        snapshot, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"reconcile",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
        for table in ("salary_interpretations", "salary_selection_batches", "salary_selection_rows"):
            loaded = conn.execute(
                text(
                    """
                    SELECT is_nullable FROM information_schema.columns
                    WHERE table_schema = 'salary_private' AND table_name = :table AND column_name = 'loaded_at'
                    """
                ),
                {"table": table},
            ).scalar_one()
            assert loaded == "NO"
        checks = conn.execute(
            text(
                """
                SELECT conname FROM pg_constraint
                WHERE conname IN (
                    'ck_salary_interpretations_evidence_sha',
                    'ck_salary_selection_batches_input_sha',
                    'ck_salary_selection_rows_slate_sha'
                )
                """
            )
        ).all()
        assert len(checks) == 3
    payload = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, GAMES)],
        "entities": [_entity(snapshot, 1, gsis="00-0033873")],
    }
    path = _mapping(tmp_path, payload)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE salary_private.dff_salaries RENAME TO dff_salaries_hidden"))
    try:
        assert _publish(database_url, path, scope="missing") == 1
    finally:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE salary_private.dff_salaries_hidden RENAME TO dff_salaries"))
    with engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM load_runs WHERE dataset = 'dk_salary_unified' AND notes LIKE '%source_table_missing%'")
        ).scalar_one()
        assert status == "failed"
    assert _publish(database_url, path, scope="crash", fault="after_commit") == 2
    with engine.connect() as conn:
        assert reconcile(conn) >= 1
    with engine.connect() as conn:
        crashed = conn.execute(
            text(
                """
                SELECT r.status FROM load_runs r
                JOIN salary_private.salary_selection_batches b ON b.load_run_id = r.id
                WHERE b.selection_scope = 'crash'
                """
            )
        ).scalar_one()
        assert crashed == "succeeded"


def test_rebuild_waits_for_the_source_writer_lock(engine, database_url, tmp_path):
    import time

    with engine.begin() as conn:
        _world(conn)
        snapshot, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"locked",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
    payload = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, GAMES)],
        "entities": [_entity(snapshot, 1, gsis="00-0033873")],
    }
    path = _mapping(tmp_path, payload)
    held = threading.Event()
    release = threading.Event()
    marks = {}

    def writer():
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(582005)"))
            held.set()
            assert release.wait(5)
            marks["released"] = datetime.now(UTC)
            conn.execute(text("SELECT pg_advisory_unlock(582005)"))
            conn.commit()

    thread = threading.Thread(target=writer)
    thread.start()
    assert held.wait(3)

    def let_go():
        time.sleep(0.4)
        release.set()

    threading.Thread(target=let_go).start()
    assert _publish(database_url, path, scope="locked") == 0
    thread.join(5)
    assert marks["released"]
    with engine.connect() as conn:
        committed = conn.execute(
            text("SELECT committed_at FROM salary_private.salary_selection_batches WHERE selection_scope = 'locked'")
        ).scalar_one()
        assert committed >= marks["released"]


def test_mapping_must_match_retained_context(engine, database_url, tmp_path):
    known = [dict(game) for game in GAMES]
    shifted = [dict(game) for game in GAMES]
    shifted[0]["kickoff_at"] = "2024-09-08T18:00:00+00:00"
    with engine.begin() as conn:
        _world(conn)
        snapshot, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"context",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "RB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1", games=known,
        )
    wrong_source = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, known, source="dff")],
        "entities": [_entity(snapshot, 1, gsis="00-0033873", source="dff")],
    }
    assert _publish(database_url, _mapping(tmp_path, wrong_source), scope="badsource") == 1
    wrong_artifact = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, known) | {"evidence_artifact_id": 999999}],
        "entities": [_entity(snapshot, 1, gsis="00-0033873")],
    }
    assert _publish(database_url, _mapping(tmp_path, wrong_artifact, "badart.json"), scope="badart") == 1
    override = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, known, group="dg-other")],
        "entities": [_entity(snapshot, 1, gsis="00-0033873")],
    }
    assert _publish(database_url, _mapping(tmp_path, override, "override.json"), scope="override") == 0
    moved = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, shifted)],
        "entities": [_entity(snapshot, 1, gsis="00-0033873")],
    }
    assert _publish(database_url, _mapping(tmp_path, moved, "moved.json"), scope="moved") == 0
    as_dst = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, known)],
        "entities": [_entity(snapshot, 1, kind="dst", gsis=None, team="KC", game="2024_01_BUF_KC")],
    }
    assert _publish(database_url, _mapping(tmp_path, as_dst, "dst.json"), scope="rbdstd") == 0
    with engine.connect() as conn:
        assert not any(row["optimizer_ready"] for row in _view(conn, "override"))
        assert not any(row["optimizer_ready"] for row in _view(conn, "moved"))
        dst_rows = [row for row in _view(conn, "rbdstd") if row["entity_key"] == "dst:KC"]
        assert dst_rows == []


def test_unclaimed_newer_group_and_stale_f004_and_blank_reject(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        older, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"claimed-old",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
        _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"unclaimed-new",
            rows=[{"status": "valid", "salary": "5200", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 4, tzinfo=UTC), draft_group="dg-1",
        )
        blank, _sha = _snapshot(
            conn, source="dknfl", pool="full_export", body=b"blank-reject",
            rows=[
                {"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"},
                {"status": "rejected", "salary": None, "native": None, "name": "", "roster": "", "team": ""},
            ],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC),
        )
        conn.execute(
            text(
                """
                INSERT INTO dk_classic_slate (
                    season, week, dk_id, name_raw, position_raw, roster_position_raw, team_raw,
                    game_info_raw, salary, source_name, source_sha256, source_loaded_at, loaded_at
                ) VALUES
                    (2024, 1, '111', 'Patrick', 'QB', 'QB', 'KC', 'BUF@KC', 5000, 'DKSalaries.csv', :old_hash, '2024-09-01T00:00:00+00:00', CURRENT_TIMESTAMP),
                    (2024, 1, '222', 'Other', 'RB', 'RB', 'KC', 'BUF@KC', 4000, 'DKSalaries.csv', :old_hash, '2024-09-01T00:00:00+00:00', CURRENT_TIMESTAMP)
                """
            ),
            {"old_hash": "a" * 64},
        )
    first = {"mapping_version": "v1", "slates": [], "entities": []}
    assert _publish(database_url, _mapping(tmp_path, first), scope="cohort") == 0
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE dk_classic_slate SET source_sha256 = :new_hash WHERE dk_id = '222'"),
            {"new_hash": "b" * 64},
        )
        old_snapshot = conn.execute(
            text("SELECT snapshot_id FROM salary_private.salary_snapshots WHERE metadata->>'source_sha256' = :sha"),
            {"sha": "a" * 64},
        ).scalar_one()
    claimed = {
        "mapping_version": "v1",
        "slates": [_slate(older, GAMES)],
        "entities": [_entity(older, 1, gsis="00-0033873")],
    }
    assert _publish(database_url, _mapping(tmp_path, claimed, "claimed.json"), scope="unclaimed") == 0
    blank_map = {
        "mapping_version": "v1",
        "slates": [_slate(blank, GAMES, group=None, source="dknfl")],
        "entities": [_entity(blank, 1, gsis="00-0033873", source="dknfl")],
    }
    blank_map["slates"][0]["draft_group_id"] = None
    blank_map["slates"][0]["equivalent_group_ids"] = []
    assert _publish(database_url, _mapping(tmp_path, blank_map, "blank.json"), scope="blanked") == 0
    assert _publish(database_url, _mapping(tmp_path, first, "cohort2.json"), scope="cohort2") == 0
    with engine.connect() as conn:
        assert not any(row["is_selected"] and row["source_snapshot_id"] == older for row in _view(conn, "unclaimed"))
        assert not any(row["optimizer_ready"] for row in _view(conn, "blanked"))
        assert not any(row["source_snapshot_id"] == old_snapshot and row["is_selected"] for row in _view(conn, "cohort2"))


def test_reused_artifacts_count_toward_invocation_budget(engine, database_url, tmp_path, monkeypatch):
    with engine.begin() as conn:
        _world(conn)
        snapshot, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"budget",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
        conn.execute(
            text(
                """
                INSERT INTO dk_classic_slate (
                    season, week, dk_id, name_raw, position_raw, roster_position_raw, team_raw,
                    game_info_raw, salary, source_name, source_sha256, source_loaded_at, loaded_at
                ) VALUES (
                    2024, 1, '111', 'Patrick', 'QB', 'QB', 'KC', 'BUF@KC', 5000,
                    'DKSalaries.csv', :sha, '2024-09-01T00:00:00+00:00', CURRENT_TIMESTAMP
                )
                """
            ),
            {"sha": "c" * 64},
        )
    payload = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, GAMES)],
        "entities": [_entity(snapshot, 1, gsis="00-0033873")],
    }
    path = _mapping(tmp_path, payload)
    assert _publish(database_url, path, scope="budget") == 0
    monkeypatch.setattr("loader.salary_private.INVOCATION_LIMIT", len(path.read_bytes()) + 8)
    assert _publish(database_url, path, scope="budget2") == 1
    with engine.connect() as conn:
        reason = conn.execute(
            text("SELECT error FROM load_runs WHERE dataset = 'dk_salary_unified' AND status = 'failed' ORDER BY id DESC LIMIT 1")
        ).scalar_one()
        assert reason == "storage_guard_invocation"


def test_mixed_source_coverage_reconciles(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        conn.execute(
            text(
                """
                INSERT INTO dk_classic_salaries (
                    season, week, rotoguru_gid, name_raw, pos_raw, team_raw, home_away, opponent_raw,
                    dk_points, dk_salary, gsis_id, team_abbr, game_id, source_url, source_fetched_at,
                    source_sha256, loaded_at
                ) VALUES (
                    2024, 1, 10, 'Patrick', 'QB', 'KC', 'H', 'BUF', 21.5, 5000, '00-0033873', 'KC',
                    '2024_01_BUF_KC', 'http://rotoguru1.com/example', CURRENT_TIMESTAMP, :sha, CURRENT_TIMESTAMP
                )
                """
            ),
            {"sha": "d" * 64},
        )
        dff, _sha = _snapshot(
            conn, source="dff", pool="subset", body=b"dff-mix",
            rows=[
                {"status": "valid", "salary": "5000", "native": "D1", "name": "Patrick", "position": "QB", "team": "KC"},
                {"status": "valid", "salary": "3000", "native": "D2", "name": "Chiefs", "position": "DST", "team": "KC"},
            ],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC),
        )
        unknown, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"unknown-slate",
            rows=[{"status": "valid", "salary": "4500", "native": "333", "name": "Open", "roster": "RB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-open",
        )
    payload = {
        "mapping_version": "v1",
        "slates": [
            _slate(dff, GAMES, group=None, source="dff", status="unresolved", complete=False),
            _slate(unknown, GAMES, key="open", group="dg-open", status="unresolved", complete=False),
        ],
        "entities": [
            _entity(dff, 1, gsis="00-0033873", source="dff"),
            _entity(dff, 2, kind="dst", gsis=None, team="KC", game=None, source="dff"),
        ],
    }
    payload["slates"][0]["draft_group_id"] = None
    assert _publish(database_url, _mapping(tmp_path, payload), scope="mix") == 0
    with engine.connect() as conn:
        summary = conn.execute(
            text("SELECT summary FROM salary_private.salary_selection_batches WHERE selection_scope = 'mix'")
        ).scalar_one()
        dff_counts = summary["by_source"]["dff"]
        legacy = summary["by_source"]["f003_adapter"]
        assert dff_counts["skill"] == 1
        assert dff_counts["dst"] == 1
        assert dff_counts["subset"] >= 1
        assert dff_counts["slate_verified"] == 0
        assert dff_counts["slate_unknown"] == 2
        assert legacy["legacy_unknown"] >= 1
        assert summary["raw_records"] == sum(item["raw"] for item in summary["by_source"].values())


def test_reachable_sql_failure_and_entrypoint_reconcile(engine, database_url, tmp_path, monkeypatch):
    from sqlalchemy.exc import OperationalError

    with engine.begin() as conn:
        _world(conn)
        snapshot, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"entry",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
    payload = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, GAMES)],
        "entities": [_entity(snapshot, 1, gsis="00-0033873")],
    }
    path = _mapping(tmp_path, payload)

    def timed_out(*_args, **_kwargs):
        raise OperationalError("SELECT", {}, Exception("canceling statement due to statement timeout"))

    monkeypatch.setattr("loader.salary_unified._candidates", timed_out)
    assert run(database_url, "timeout", FUTURE, path, "local") == 1
    monkeypatch.undo()
    with engine.connect() as conn:
        status, error = conn.execute(
            text("SELECT status, error FROM load_runs WHERE dataset = 'dk_salary_unified' ORDER BY id DESC LIMIT 1")
        ).one()
        assert status == "failed"
        assert error == "statement_timeout"
    assert run(database_url, "crash", FUTURE, path, "local", fault="after_commit") == 2
    assert main(["--selection-scope", "crash", "--as-of", FUTURE, "--mapping-file", str(path), "--trigger", "local"]) == 0
    with engine.connect() as conn:
        statuses = conn.execute(
            text(
                """
                SELECT r.status FROM load_runs r
                JOIN salary_private.salary_selection_batches b ON b.load_run_id = r.id
                WHERE b.selection_scope = 'crash'
                ORDER BY r.id
                """
            )
        ).scalars().all()
        assert statuses[0] == "succeeded"


def test_latest_complete_history_and_separate_null_groups(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        early, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"hist-a",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
        _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"hist-b",
            rows=[{"status": "valid", "salary": "5100", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 2, tzinfo=UTC), draft_group="dg-1",
        )
        latest, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"hist-c",
            rows=[{"status": "valid", "salary": "5200", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 3, tzinfo=UTC), draft_group="dg-1",
        )
        lower, _sha = _snapshot(
            conn, source="dknfl", pool="full_export", body=b"hist-lower",
            rows=[{"status": "valid", "salary": "1000", "native": "999", "name": "Other", "roster": "QB", "team": "BUF"}],
            observed_at=datetime(2024, 9, 3, tzinfo=UTC), draft_group="dg-low", week=16,
        )
        week_one, _sha = _snapshot(
            conn, source="dknfl", pool="full_export", body=b"null-week1",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 8, 1, tzinfo=UTC),
        )
        week_sixteen, _sha = _snapshot(
            conn, source="dknfl", pool="full_export", body=b"null-week16",
            rows=[{"status": "valid", "salary": "4000", "native": "222", "name": "Josh", "roster": "QB", "team": "PHI"}],
            observed_at=datetime(2024, 12, 1, tzinfo=UTC), week=16,
        )
    lobby = {
        "mapping_version": "v1",
        "slates": [
            _slate(early, GAMES, effective="2024-09-01T00:00:00+00:00"),
            _slate(latest, GAMES, effective="2024-09-03T00:00:00+00:00"),
            _slate(lower, HOLIDAY, key="low", group="dg-low", week=16, source="dknfl", effective="2024-09-03T00:00:00+00:00"),
        ],
        "entities": [
            _entity(early, 1, gsis="00-0033873"),
            _entity(latest, 1, gsis="00-0033873"),
            _entity(lower, 1, gsis="00-0034857", team="BUF", game="2024_16_DAL_PHI", source="dknfl"),
        ],
    }
    # The middle lobby file is a successful snapshot with no verified claim.
    assert _publish(database_url, _mapping(tmp_path, lobby), scope="recovered") == 0
    archives = {
        "mapping_version": "v1",
        "slates": [
            _slate(week_one, GAMES, key="week1", group=None, source="dknfl"),
            _slate(week_sixteen, HOLIDAY, key="week16", group=None, week=16, source="dknfl", complete=False, status="unresolved"),
        ],
        "entities": [_entity(week_one, 1, gsis="00-0033873", source="dknfl")],
    }
    archives["slates"][0]["draft_group_id"] = None
    archives["slates"][1]["draft_group_id"] = None
    assert _publish(database_url, _mapping(tmp_path, archives, "archives.json"), scope="archives") == 0
    with engine.connect() as conn:
        selected = [row for row in _view(conn, "recovered") if row["is_selected"]]
        assert {row["source_snapshot_id"] for row in selected} == {latest}
        assert all(row["optimizer_ready"] for row in selected)
        week1 = [row for row in _view(conn, "archives") if row["source_snapshot_id"] == week_one and row["is_selected"]]
        assert week1
        assert all(row["optimizer_ready"] for row in week1)


def test_null_kickoff_can_be_enriched_without_becoming_ready(engine, database_url, tmp_path):
    stored = [{"away": "BUF", "home": "KC", "game_id": "2024_01_BUF_KC", "kickoff_at": None}]
    with engine.begin() as conn:
        _world(conn)
        snapshot, _sha = _snapshot(
            conn, source="dff", pool="subset", body=b"null-kick",
            rows=[{"status": "valid", "salary": "5000", "native": "D1", "name": "Patrick", "position": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), games=stored,
        )
    payload = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, GAMES, group=None, source="dff")],
        "entities": [_entity(snapshot, 1, gsis="00-0033873", source="dff")],
    }
    payload["slates"][0]["draft_group_id"] = None
    assert _publish(database_url, _mapping(tmp_path, payload), scope="enrich") == 0
    with engine.connect() as conn:
        status = conn.execute(
            text(
                """
                SELECT status FROM salary_private.salary_interpretations
                WHERE snapshot_id = :snapshot AND row_number IS NULL
                """
            ),
            {"snapshot": snapshot},
        ).scalar_one()
        rows = _view(conn, "enrich")
        assert status == "verified"
        assert rows
        assert all(row["source_pool_kind"] == "subset" for row in rows if row["source"] == "dff")
        assert not any(row["optimizer_ready"] for row in rows)


def test_reconcile_waits_for_the_active_attempt(engine, database_url, tmp_path):
    import time

    with engine.begin() as conn:
        _world(conn)
        snapshot, _sha = _snapshot(
            conn, source="dk_lobby", pool="full_export", body=b"active",
            rows=[{"status": "valid", "salary": "5000", "native": "111", "name": "Patrick", "roster": "QB", "team": "KC"}],
            observed_at=datetime(2024, 9, 1, tzinfo=UTC), draft_group="dg-1",
        )
    payload = {
        "mapping_version": "v1",
        "slates": [_slate(snapshot, GAMES)],
        "entities": [_entity(snapshot, 1, gsis="00-0033873")],
    }
    path = _mapping(tmp_path, payload)
    held = threading.Event()
    release = threading.Event()

    def holder():
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(582005)"))
            conn.execute(
                text(
                    """
                    INSERT INTO load_runs (run_group, dataset, season, status, trigger, started_at, source_url)
                    VALUES (gen_random_uuid(), 'dk_salary_unified', NULL, 'running', 'local', CURRENT_TIMESTAMP, 'dk_salary_unified')
                    """
                )
            )
            conn.commit()
            held.set()
            assert release.wait(5)
            conn.execute(text("SELECT pg_advisory_unlock(582005)"))
            conn.commit()

    threading.Thread(target=holder).start()
    assert held.wait(3)
    outcome = {}

    def second():
        outcome["code"] = _publish(database_url, path, scope="waited")

    follower = threading.Thread(target=second)
    follower.start()
    try:
        time.sleep(0.4)
        with engine.connect() as conn:
            status = conn.execute(
                text(
                    """
                    SELECT status FROM load_runs
                    WHERE dataset = 'dk_salary_unified'
                    ORDER BY id DESC
                    LIMIT 1
                    """
                )
            ).scalar()
        assert follower.is_alive()
        assert status == "running"
    finally:
        release.set()
    follower.join(5)
    assert outcome["code"] == 0


def test_stale_f004_quality_cannot_stay_ready(engine, database_url, tmp_path):
    with engine.begin() as conn:
        _world(conn)
        conn.execute(
            text(
                """
                INSERT INTO dk_classic_slate (
                    season, week, dk_id, name_raw, position_raw, roster_position_raw, team_raw,
                    game_info_raw, salary, source_name, source_sha256, source_loaded_at, loaded_at
                ) VALUES (
                    2024, 1, '111', 'Patrick', 'QB', 'QB', 'KC', 'BUF@KC', 5000,
                    'DKSalaries.csv', :sha, '2024-09-01T00:00:00+00:00', CURRENT_TIMESTAMP
                )
                """
            ),
            {"sha": "e" * 64},
        )
    assert _publish(database_url, _mapping(tmp_path, {"mapping_version": "v1"}), scope="seed") == 0
    with engine.connect() as conn:
        old = conn.execute(
            text(
                """
                SELECT s.snapshot_id, o.observed_at
                FROM salary_private.salary_snapshots s
                JOIN salary_private.salary_observations o ON o.snapshot_id = s.snapshot_id
                WHERE s.source = 'f004_adapter' AND s.metadata->>'source_sha256' = :sha
                """
            ),
            {"sha": "e" * 64},
        ).one()
    mapped = {
        "mapping_version": "v1",
        "slates": [_slate(old.snapshot_id, GAMES, source="f004_adapter")],
        "entities": [_entity(old.snapshot_id, 1, gsis="00-0033873", source="f004_adapter")],
    }
    assert _publish(database_url, _mapping(tmp_path, mapped, "ready.json"), scope="readyA") == 0
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO dk_classic_slate (
                    season, week, dk_id, name_raw, position_raw, roster_position_raw, team_raw,
                    game_info_raw, salary, source_name, source_sha256, source_loaded_at, loaded_at
                ) VALUES (
                    2024, 1, '222', 'Other', 'RB', 'RB/FLEX', 'BUF', 'BUF@KC', 4000,
                    'DKSalaries.csv', :sha, '2024-09-02T00:00:00+00:00', CURRENT_TIMESTAMP
                )
                """
            ),
            {"sha": "f" * 64},
        )
    assert _publish(
        database_url,
        _mapping(tmp_path, mapped, "stale.json"),
        scope="staleA",
        cutoff=old.observed_at.isoformat(),
    ) == 0
    with engine.connect() as conn:
        ready = [
            row for row in _view(conn, "staleA")
            if row["source_snapshot_id"] == old.snapshot_id and row["optimizer_ready"]
        ]
        assert ready == []
