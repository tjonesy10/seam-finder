"""Load the public fixture database for the F009 Playwright suite."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from loader.run import run_load
from loader.url import normalize_database_url

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    os.chdir(ROOT)
    database_url = os.environ["DATABASE_URL"]
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_engine(normalize_database_url(database_url))
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE load_runs, player_week_stats, games, players, teams "
                "RESTART IDENTITY CASCADE"
            )
        )
    engine.dispose()
    assert run_load(
        database_url=database_url,
        seasons=[2024, 2025],
        data_dir=ROOT / "tests" / "fixtures" / "nflverse",
        trigger="local",
    )
    _seed_cin_week(database_url)


def _seed_cin_week(database_url: str) -> None:
    players = [
        {"gsis_id": f"99-{index:07d}", "display_name": f"Fictional Player {index:03d}"}
        for index in range(1, 111)
    ]
    stats = [
        {"gsis_id": f"99-{index:07d}", "yards": 500 if index == 1 else index}
        for index in range(1, 111)
    ]
    engine = create_engine(normalize_database_url(database_url))
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO players (gsis_id, display_name, position, is_stub, loaded_at)
                VALUES (:gsis_id, :display_name, 'WR', true, CURRENT_TIMESTAMP)
                """
            ),
            players,
        )
        conn.execute(
            text(
                """
                INSERT INTO player_week_stats (
                    gsis_id, season, week, season_type, game_id, team, opponent_team, position,
                    completions, attempts, passing_yards, passing_tds, passing_interceptions,
                    sacks_suffered, sack_fumbles_lost, passing_2pt_conversions,
                    carries, rushing_yards, rushing_tds, rushing_fumbles_lost,
                    rushing_2pt_conversions, receptions, targets, receiving_yards, receiving_tds,
                    receiving_fumbles_lost, receiving_2pt_conversions, special_teams_tds,
                    fantasy_points, fantasy_points_ppr, loaded_at
                ) VALUES (
                    :gsis_id, 2024, 10, 'REG', '2024_10_CIN_BAL', 'CIN', 'BAL', 'WR',
                    0, 0, 0, 0, 0,
                    0, 0, 0,
                    0, 0, 0, 0,
                    0, 0, 0, :yards, 0,
                    0, 0, 0,
                    0.50, 0.50, CURRENT_TIMESTAMP
                )
                """
            ),
            stats,
        )
    engine.dispose()


if __name__ == "__main__":
    main()
