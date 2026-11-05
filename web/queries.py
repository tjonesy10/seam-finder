"""Read queries used by the JSON API and the HTML pages."""

from contextlib import contextmanager
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, text
from sqlalchemy.engine import Engine

from loader.tables import games, load_runs, player_week_stats, players, teams
from web.errors import AppError, is_db_unavailable
from web.params import ListParams
from web.resources import DATASETS
from web.serialize import to_jsonable

_ET = ZoneInfo("America/New_York")


def format_et(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(_ET).strftime("%Y-%m-%d %H:%M:%S ET")


@contextmanager
def connection(engine: Engine | None):
    if engine is None:
        raise AppError(503, "service_unavailable", "The database is unavailable.")
    try:
        with engine.connect() as conn:
            try:
                yield conn
            except AppError:
                raise
            except Exception as exc:
                if is_db_unavailable(exc):
                    raise AppError(503, "service_unavailable", "The database is unavailable.") from None
                raise
    except AppError:
        raise
    except Exception as exc:
        if is_db_unavailable(exc):
            raise AppError(503, "service_unavailable", "The database is unavailable.") from None
        raise


def _names(table) -> list[str]:
    return [column.name for column in table.columns]


def _dump(mapping, names: list[str]) -> dict:
    return {name: to_jsonable(mapping[name]) for name in names}


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _order(table, params: ListParams, tie_break: tuple[str, ...]):
    column = table.c[params.sort]
    clauses = [column.desc() if params.order == "desc" else column.asc()]
    for name in tie_break:
        if name != params.sort:
            clauses.append(table.c[name].asc())
    return clauses


def _page(conn, filtered, params: ListParams, tie_break: tuple[str, ...], table, names: list[str]):
    total = int(conn.execute(select(func.count()).select_from(filtered.subquery())).scalar_one())
    stmt = filtered.order_by(*_order(table, params, tie_break)).limit(params.limit).offset(params.offset)
    rows = [_dump(mapping, names) for mapping in conn.execute(stmt).mappings()]
    return rows, total


def fetch_teams(conn, params: ListParams):
    stmt = select(teams)
    if "conf" in params.values:
        stmt = stmt.where(func.lower(teams.c.team_conf) == params.values["conf"].lower())
    if "division" in params.values:
        stmt = stmt.where(func.lower(teams.c.team_division) == params.values["division"].lower())
    return _page(conn, stmt, params, ("team_abbr",), teams, _names(teams))


def fetch_players(conn, params: ListParams):
    stmt = select(players)
    if "q" in params.values:
        stmt = stmt.where(players.c.display_name.ilike(_like(params.values["q"]), escape="\\"))
    if "position" in params.values:
        stmt = stmt.where(func.upper(players.c.position) == params.values["position"])
    if "team" in params.values:
        stmt = stmt.where(func.upper(players.c.latest_team) == params.values["team"])
    if "status" in params.values:
        stmt = stmt.where(func.lower(players.c.status) == params.values["status"].lower())
    return _page(conn, stmt, params, ("gsis_id",), players, _names(players))


def fetch_games(conn, params: ListParams):
    stmt = select(games)
    if "season" in params.values:
        stmt = stmt.where(games.c.season == int(params.values["season"]))
    if "week" in params.values:
        stmt = stmt.where(games.c.week == int(params.values["week"]))
    if "season_type" in params.values:
        stmt = stmt.where(games.c.season_type == params.values["season_type"])
    if "team" in params.values:
        team = params.values["team"]
        stmt = stmt.where(or_(func.upper(games.c.home_team) == team, func.upper(games.c.away_team) == team))
    return _page(conn, stmt, params, ("game_id",), games, _names(games))


def _stats_columns():
    columns = []
    names = []
    for column in player_week_stats.columns:
        columns.append(column)
        names.append(column.name)
        if column.name == "gsis_id":
            columns.append(players.c.display_name.label("player_display_name"))
            names.append("player_display_name")
    return columns, names


def fetch_stats(conn, params: ListParams):
    columns, names = _stats_columns()
    joined = player_week_stats.join(players, players.c.gsis_id == player_week_stats.c.gsis_id)
    stmt = select(*columns).select_from(joined)
    if "season" in params.values:
        stmt = stmt.where(player_week_stats.c.season == int(params.values["season"]))
    if "week" in params.values:
        stmt = stmt.where(player_week_stats.c.week == int(params.values["week"]))
    if "season_type" in params.values:
        stmt = stmt.where(player_week_stats.c.season_type == params.values["season_type"])
    if "team" in params.values:
        stmt = stmt.where(func.upper(player_week_stats.c.team) == params.values["team"])
    if "position" in params.values:
        stmt = stmt.where(func.upper(player_week_stats.c.position) == params.values["position"])
    if "player" in params.values:
        stmt = stmt.where(player_week_stats.c.gsis_id == params.values["player"])
    if "game_id" in params.values:
        stmt = stmt.where(player_week_stats.c.game_id == params.values["game_id"])
    return _page(conn, stmt, params, ("gsis_id", "season", "week"), player_week_stats, names)


def fetch_load_runs(conn, params: ListParams):
    stmt = select(load_runs)
    if "dataset" in params.values:
        stmt = stmt.where(func.lower(load_runs.c.dataset) == params.values["dataset"].lower())
    if "status" in params.values:
        stmt = stmt.where(func.lower(load_runs.c.status) == params.values["status"].lower())
    if "season" in params.values:
        stmt = stmt.where(load_runs.c.season == int(params.values["season"]))
    return _page(conn, stmt, params, ("id",), load_runs, _names(load_runs))


FETCH = {
    "teams": fetch_teams,
    "players": fetch_players,
    "games": fetch_games,
    "stats": fetch_stats,
    "load-runs": fetch_load_runs,
}


def get_team(conn, team_abbr: str) -> dict:
    stmt = select(teams).where(func.upper(teams.c.team_abbr) == team_abbr.strip().upper())
    row = conn.execute(stmt).mappings().first()
    if row is None:
        raise AppError(404, "not_found", "team not found")
    return {"data": _dump(row, _names(teams))}


def get_player(conn, gsis_id: str) -> dict:
    stmt = select(players).where(players.c.gsis_id == gsis_id.strip())
    row = conn.execute(stmt).mappings().first()
    if row is None:
        raise AppError(404, "not_found", "player not found")
    return {"data": _dump(row, _names(players))}


def get_game(conn, game_id: str) -> dict:
    stmt = select(games).where(games.c.game_id == game_id.strip())
    row = conn.execute(stmt).mappings().first()
    if row is None:
        raise AppError(404, "not_found", "game not found")
    return {"data": _dump(row, _names(games))}


def _succeeded():
    return (load_runs.c.status == "succeeded") & load_runs.c.finished_at.is_not(None)


def latest_refresh(conn):
    stmt = (
        select(
            load_runs.c.dataset,
            load_runs.c.season,
            load_runs.c.finished_at,
            load_runs.c.source_version,
        )
        .where(_succeeded())
        .order_by(load_runs.c.finished_at.desc(), load_runs.c.id.desc())
        .limit(1)
    )
    return conn.execute(stmt).mappings().first()


def refresh_payload(row) -> dict | None:
    if row is None:
        return None
    return {
        "dataset": row["dataset"],
        "season": to_jsonable(row["season"]),
        "finished_at": to_jsonable(row["finished_at"]),
        "source_version": to_jsonable(row["source_version"]),
    }


def per_dataset(conn) -> list[dict]:
    stmt = (
        select(load_runs.c.dataset, load_runs.c.finished_at)
        .where(_succeeded())
        .order_by(load_runs.c.finished_at.desc(), load_runs.c.id.desc())
    )
    found: dict[str, datetime] = {}
    for row in conn.execute(stmt).mappings():
        if row["dataset"] not in found:
            found[row["dataset"]] = row["finished_at"]
    items = []
    for dataset in DATASETS:
        finished = found.get(dataset)
        items.append(
            {
                "dataset": dataset,
                "finished_at": format_et(finished) if finished is not None else "none",
            }
        )
    return items


def footer(conn) -> dict:
    row = latest_refresh(conn)
    label = "none"
    if row is not None and row["finished_at"] is not None:
        label = format_et(row["finished_at"])
    return {"last_refresh_et": label, "datasets": per_dataset(conn)}


def ping(conn) -> None:
    conn.execute(text("SELECT 1"))


def output_names(slug: str) -> list[str]:
    if slug == "stats":
        return _stats_columns()[1]
    table = {"teams": teams, "players": players, "games": games, "load-runs": load_runs}[slug]
    return _names(table)
