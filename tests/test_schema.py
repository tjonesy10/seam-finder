import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

EXPECTED = {
    "teams": {
        "team_abbr": ("text", False),
        "team_name": ("text", False),
        "team_nick": ("text", False),
        "team_conf": ("text", False),
        "team_division": ("text", False),
        "team_id": ("text", False),
        "team_color": ("text", False),
        "team_color2": ("text", False),
        "loaded_at": ("timestamp with time zone", False),
    },
    "players": {
        "gsis_id": ("text", False),
        "display_name": ("text", False),
        "first_name": ("text", True),
        "last_name": ("text", True),
        "position": ("text", True),
        "position_group": ("text", True),
        "birth_date": ("date", True),
        "height": ("smallint", True),
        "weight": ("smallint", True),
        "college_name": ("text", True),
        "rookie_season": ("smallint", True),
        "last_season": ("smallint", True),
        "latest_team": ("text", True),
        "status": ("text", True),
        "years_of_experience": ("smallint", True),
        "draft_year": ("smallint", True),
        "draft_round": ("smallint", True),
        "draft_pick": ("smallint", True),
        "draft_team": ("text", True),
        "pfr_id": ("text", True),
        "espn_id": ("text", True),
        "pff_id": ("text", True),
        "nfl_id": ("text", True),
        "esb_id": ("text", True),
        "otc_id": ("text", True),
        "is_stub": ("boolean", False),
        "loaded_at": ("timestamp with time zone", False),
    },
    "games": {
        "game_id": ("text", False),
        "season": ("smallint", False),
        "game_type": ("text", False),
        "season_type": ("text", False),
        "week": ("smallint", False),
        "gameday": ("date", False),
        "weekday": ("text", False),
        "gametime": ("text", True),
        "away_team": ("text", False),
        "home_team": ("text", False),
        "away_score": ("smallint", True),
        "home_score": ("smallint", True),
        "result": ("smallint", True),
        "total": ("smallint", True),
        "overtime": ("boolean", True),
        "location": ("text", False),
        "roof": ("text", True),
        "surface": ("text", True),
        "stadium": ("text", True),
        "spread_line": ("numeric", True),
        "total_line": ("numeric", True),
        "old_game_id": ("text", True),
        "pfr": ("text", True),
        "espn": ("text", True),
        "loaded_at": ("timestamp with time zone", False),
    },
    "player_week_stats": {
        "gsis_id": ("text", False),
        "season": ("smallint", False),
        "week": ("smallint", False),
        "season_type": ("text", False),
        "game_id": ("text", False),
        "team": ("text", False),
        "opponent_team": ("text", False),
        "position": ("text", True),
        "position_group": ("text", True),
        "completions": ("smallint", False),
        "attempts": ("smallint", False),
        "passing_yards": ("smallint", False),
        "passing_tds": ("smallint", False),
        "passing_interceptions": ("smallint", False),
        "sacks_suffered": ("smallint", False),
        "sack_fumbles_lost": ("smallint", False),
        "passing_2pt_conversions": ("smallint", False),
        "carries": ("smallint", False),
        "rushing_yards": ("smallint", False),
        "rushing_tds": ("smallint", False),
        "rushing_fumbles_lost": ("smallint", False),
        "rushing_2pt_conversions": ("smallint", False),
        "receptions": ("smallint", False),
        "targets": ("smallint", False),
        "receiving_yards": ("smallint", False),
        "receiving_tds": ("smallint", False),
        "receiving_fumbles_lost": ("smallint", False),
        "receiving_2pt_conversions": ("smallint", False),
        "target_share": ("double precision", True),
        "special_teams_tds": ("smallint", False),
        "fantasy_points": ("numeric", False),
        "fantasy_points_ppr": ("numeric", False),
        "loaded_at": ("timestamp with time zone", False),
    },
    "load_runs": {
        "id": ("bigint", False),
        "run_group": ("uuid", False),
        "dataset": ("text", False),
        "season": ("smallint", True),
        "status": ("text", False),
        "trigger": ("text", False),
        "started_at": ("timestamp with time zone", False),
        "finished_at": ("timestamp with time zone", True),
        "source_url": ("text", False),
        "source_version": ("text", True),
        "rows_read": ("integer", True),
        "rows_upserted": ("integer", True),
        "rows_deleted": ("integer", True),
        "rows_skipped": ("integer", True),
        "notes": ("text", True),
        "error": ("text", True),
    },
}


def test_upgrade_head_twice_is_safe():
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")


def test_columns_match_data_dictionary(engine):
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT table_name, column_name, data_type, is_nullable,
                       numeric_precision, numeric_scale, identity_generation
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = ANY(:tables)
                """
            ),
            {"tables": list(EXPECTED)},
        ).mappings()
        found = {}
        for row in rows:
            found.setdefault(row["table_name"], {})[row["column_name"]] = row
    for table, columns in EXPECTED.items():
        assert set(found[table]) == set(columns)
        for name, (data_type, nullable) in columns.items():
            actual = found[table][name]
            assert actual["data_type"] == data_type, name
            assert (actual["is_nullable"] == "YES") is nullable, name
        fantasy = found["player_week_stats"]["fantasy_points"]
        assert (fantasy["numeric_precision"], fantasy["numeric_scale"]) == (6, 2)
        ppr = found["player_week_stats"]["fantasy_points_ppr"]
        assert (ppr["numeric_precision"], ppr["numeric_scale"]) == (6, 2)
        spread = found["games"]["spread_line"]
        assert (spread["numeric_precision"], spread["numeric_scale"]) == (4, 1)
        total_line = found["games"]["total_line"]
        assert (total_line["numeric_precision"], total_line["numeric_scale"]) == (4, 1)
        assert found["load_runs"]["id"]["identity_generation"] == "ALWAYS"


def test_keys_indexes_and_status_check(engine):
    with engine.connect() as conn:
        indexes = conn.execute(
            text(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                """
            )
        ).mappings()
        indexdefs = {row["indexname"]: row["indexdef"] for row in indexes}
        constraints = conn.execute(
            text(
                """
                SELECT conname, pg_get_constraintdef(oid) AS def
                FROM pg_constraint
                WHERE connamespace = 'public'::regnamespace
                """
            )
        ).mappings()
        defs = {row["conname"]: row["def"] for row in constraints}
    assert "lower(display_name) text_pattern_ops" in indexdefs["ix_players_lower_display_name"]
    assert "ix_players_position" in indexdefs
    assert "ix_players_latest_team" in indexdefs
    assert "(season, season_type, week)" in indexdefs["ix_games_season_season_type_week"]
    assert "(home_team, season)" in indexdefs["ix_games_home_team_season"]
    assert "(away_team, season)" in indexdefs["ix_games_away_team_season"]
    assert "ix_player_week_stats_season_season_type_week" in indexdefs
    assert "ix_player_week_stats_team_season" in indexdefs
    assert "ix_player_week_stats_game_id" in indexdefs
    assert "ix_player_week_stats_season_position" in indexdefs
    assert "started_at DESC" in indexdefs["ix_load_runs_dataset_season_started_at"]
    assert "ix_load_runs_status" in indexdefs
    assert "PRIMARY KEY (gsis_id, season, week)" in defs["player_week_stats_pkey"]
    assert "UNIQUE (gsis_id, game_id)" in defs["uq_player_week_stats_gsis_game"]
    fk_names = (
        "fk_games_away_team",
        "fk_games_home_team",
        "fk_player_week_stats_gsis_id",
        "fk_player_week_stats_game_id",
        "fk_player_week_stats_team",
        "fk_player_week_stats_opponent_team",
    )
    for name in fk_names:
        assert "FOREIGN KEY" in defs[name]
        assert "ON DELETE RESTRICT" in defs[name]
        assert "CASCADE" not in defs[name]
    assert "running" in defs["ck_load_runs_status"]
    assert "succeeded" in defs["ck_load_runs_status"]
    assert "failed" in defs["ck_load_runs_status"]
    with engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    """
                    INSERT INTO load_runs
                        (run_group, dataset, status, trigger, started_at, source_url)
                    VALUES
                        (gen_random_uuid(), 'teams', 'nope', 'local', now(), 'https://example.com')
                    """
                )
            )
        trans.rollback()


def test_downgrade_and_upgrade(engine):
    cfg = Config("alembic.ini")
    try:
        command.downgrade(cfg, "base")
        with engine.connect() as conn:
            present = conn.execute(
                text("SELECT to_regclass('public.teams'), to_regclass('public.load_runs')")
            ).one()
            assert present[0] is None
            assert present[1] is None
    finally:
        command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('public.player_week_stats')")).scalar()


def _drop_reader(engine):
    from loader.grants import revoke_readonly_grant

    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = 'seam_reader'")
        ).first()
        if exists is None:
            return
        revoke_readonly_grant(conn)
    with engine.begin() as conn:
        conn.execute(text("DROP OWNED BY seam_reader"))
        conn.execute(text("DROP ROLE seam_reader"))


def test_readonly_role_is_select_only(engine, monkeypatch):
    monkeypatch.setenv("READONLY_ROLE", "seam_reader")
    from loader.grants import apply_readonly_grant

    _drop_reader(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE ROLE seam_reader"))
        conn.execute(text("GRANT seam_reader TO CURRENT_USER"))
        apply_readonly_grant(conn)
    try:
        with engine.connect() as conn:
            conn.execute(text("SET ROLE seam_reader"))
            conn.execute(text("SELECT count(*) FROM teams"))
            conn.execute(text("RESET ROLE"))
            conn.commit()
        insert_team = (
            "INSERT INTO teams (team_abbr, team_name, team_nick, team_conf, team_division, "
            "team_id, team_color, team_color2, loaded_at) VALUES "
            "('ZZ', 'n', 'n', 'n', 'n', '1', '#000', '#111', now())"
        )
        denied = [
            insert_team,
            "UPDATE teams SET team_name = 'x'",
            "DELETE FROM teams",
            "CREATE TABLE should_fail (id int)",
        ]
        for statement in denied:
            with engine.connect() as conn:
                trans = conn.begin()
                try:
                    conn.execute(text("SET ROLE seam_reader"))
                    with pytest.raises(DBAPIError):
                        conn.execute(text(statement))
                finally:
                    trans.rollback()
                    conn.execute(text("RESET ROLE"))
                    conn.commit()
    finally:
        _drop_reader(engine)
        monkeypatch.delenv("READONLY_ROLE", raising=False)
