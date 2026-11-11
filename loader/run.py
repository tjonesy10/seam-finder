"""Load nflverse release files into Postgres."""

import argparse
import inspect
import math
import os
import re
import sys
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

import polars as pl
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from loader.coordination import (
    COORDINATION_WAIT_S,
    CoordinationError,
    coordination,
    ensure_pipeline_ownership,
)
from loader.source import DirSource, HttpSource, LoadError
from loader.tables import (
    GAMES_FIELDS,
    PLAYERS_FIELDS,
    STATS_FIELDS,
    TEAMS_FIELDS,
    Field,
    games,
    player_week_stats,
    players,
    teams,
)
from loader.url import normalize_database_url

DATASETS = ("teams", "players", "games", "player_week_stats")
TRIGGERS = ("local", "manual", "schedule")

# ADR 0002 says season and week must be "in range" and does not give bounds.
# The only bounds in the F001 spec are the API filter rules: season 1999-2100, week 1-22.
SEASON_MIN = 1999
SEASON_MAX = 2100
WEEK_MIN = 1
WEEK_MAX = 22

_DB_URL = re.compile(r"postgres(?:ql)?(?:\+[a-z0-9]+)?:\/\/\S+", re.IGNORECASE)
_SMALLINT_MIN = -32768
_SMALLINT_MAX = 32767


def redact(message: str, secret: str | None = None) -> str:
    cleaned = _DB_URL.sub("<database>", message)
    if secret:
        cleaned = cleaned.replace(secret, "<database>")
        if secret.startswith("postgres://"):
            cleaned = cleaned.replace("postgresql://" + secret[len("postgres://") :], "<database>")
        if secret.startswith("postgresql://"):
            cleaned = cleaned.replace(
                "postgresql+psycopg://" + secret[len("postgresql://") :], "<database>"
            )
    return cleaned[:4000]


def current_season(today: date | None = None) -> int:
    today = date.today() if today is None else today
    if today.month < 3:
        return today.year - 1
    return today.year


def parse_seasons(value: str | None, today: date | None = None) -> list[int]:
    if value is None or value.strip() == "":
        return [current_season(today)]
    text_value = value.strip()
    try:
        if "-" in text_value:
            left, right = text_value.split("-", 1)
            start, end = int(left.strip()), int(right.strip())
            if end < start:
                raise ValueError
            return list(range(start, end + 1))
        return [int(text_value)]
    except ValueError:
        raise ValueError(
            "seasons must be a year or a range, for example 2024 or 2015-2026"
        ) from None


def parse_datasets(value: str | None) -> list[str]:
    if value is None or value.strip() == "":
        return list(DATASETS)
    names = [part.strip() for part in value.split(",") if part.strip()]
    unknown = [name for name in names if name not in DATASETS]
    if unknown:
        raise ValueError(f"unknown dataset: {unknown[0]}")
    return [name for name in DATASETS if name in names]


def _missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _convert(value, field: Field):
    if _missing(value):
        if field.nullable:
            return None
        raise LoadError(f"null value: {field.source}")
    if field.kind == "text":
        return str(value)
    if field.kind == "smallint":
        if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
            raise LoadError(f"invalid integer: {field.source}")
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise LoadError(f"invalid integer: {field.source}") from exc
        if number < _SMALLINT_MIN or number > _SMALLINT_MAX:
            raise LoadError(f"smallint out of range: {field.source}")
        return number
    if field.kind == "date":
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value))
        except ValueError as exc:
            raise LoadError(f"invalid date: {field.source}") from exc
    if field.kind == "bool":
        if value in (0, 1, False, True):
            return bool(value)
        raise LoadError(f"invalid boolean: {field.source}")
    if field.kind == "float":
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise LoadError(f"invalid number: {field.source}") from exc
    if field.kind == "numeric":
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise LoadError(f"invalid number: {field.source}") from exc
        scale = field.scale if field.scale is not None else 0
        precision = field.precision if field.precision is not None else 0
        number = number.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
        _sign, digits, exponent = number.as_tuple()
        int_digits = 0 if digits == (0,) else max(0, len(digits) + int(exponent))
        if int_digits > precision - scale:
            raise LoadError(f"numeric overflow: {field.source}")
        return number
    raise LoadError(f"unknown field kind: {field.kind}")


def ensure_columns(frame: pl.DataFrame, mapped: tuple[Field, ...]) -> None:
    missing = [field.source for field in mapped if field.source not in frame.columns]
    if missing:
        raise LoadError("missing required column: " + ", ".join(missing))


def ensure_unique(frame: pl.DataFrame, columns: list[str]) -> None:
    if frame.height == 0:
        return
    for column in columns:
        if frame[column].null_count():
            raise LoadError(f"null key: {column}")
    if frame.select(columns).unique().height != frame.height:
        raise LoadError("duplicate key: " + ", ".join(columns))


def ensure_season_week(frame: pl.DataFrame) -> None:
    if frame.height == 0:
        return
    bad_season = frame.filter(
        pl.col("season").is_null()
        | (pl.col("season") < SEASON_MIN)
        | (pl.col("season") > SEASON_MAX)
    )
    if bad_season.height:
        raise LoadError("season out of range")
    bad_week = frame.filter(
        pl.col("week").is_null() | (pl.col("week") < WEEK_MIN) | (pl.col("week") > WEEK_MAX)
    )
    if bad_week.height:
        raise LoadError("week out of range")


def ensure_season_type(frame: pl.DataFrame) -> None:
    if frame.height == 0:
        return
    invalid = pl.col("season_type").is_null() | ~pl.col("season_type").is_in(["REG", "POST"])
    if frame.filter(invalid).height:
        raise LoadError("invalid season_type")


def convert_rows(frame: pl.DataFrame, mapped: tuple[Field, ...]) -> list[dict]:
    rows = []
    for record in frame.iter_rows(named=True):
        rows.append({field.dest: _convert(record[field.source], field) for field in mapped})
    return rows


def _read_frame(payload: bytes) -> pl.DataFrame:
    return pl.read_parquet(payload)


def _retrieved_at(source, dataset: str):
    method = getattr(source, "retrieved_at", None)
    if method is None:
        return None
    try:
        return method(dataset, None)
    except TypeError:
        return method(dataset)


def _succeeded_games(engine, run_group) -> list[int]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id FROM load_runs
                WHERE run_group = :run_group
                  AND dataset = 'games'
                  AND status = 'succeeded'
                ORDER BY id
                """
            ),
            {"run_group": run_group},
        ).scalars().all()
    return [int(row) for row in rows]


def _version(source, dataset: str) -> str | None:
    try:
        return source.fetch_version(dataset)
    except Exception:  # noqa: BLE001 - a missing release timestamp does not fail the load
        return None


def _start(engine, *, run_group, dataset, season, trigger, source_url) -> int:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO load_runs
                    (run_group, dataset, season, status, trigger, started_at, source_url)
                VALUES
                    (:run_group, :dataset, :season, 'running', :trigger, :started_at, :source_url)
                RETURNING id
                """
            ),
            {
                "run_group": run_group,
                "dataset": dataset,
                "season": season,
                "trigger": trigger,
                "started_at": datetime.now(UTC),
                "source_url": source_url,
            },
        ).one()
        return row.id


def _finish(engine, run_id: int, *, status: str, secret: str, **fields) -> None:
    error = fields.get("error")
    if error is not None:
        error = redact(error, secret)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE load_runs SET
                    status = :status,
                    finished_at = :finished_at,
                    source_version = :source_version,
                    rows_read = :rows_read,
                    rows_upserted = :rows_upserted,
                    rows_deleted = :rows_deleted,
                    rows_skipped = :rows_skipped,
                    notes = :notes,
                    error = :error
                WHERE id = :id
                """
            ),
            {
                "id": run_id,
                "status": status,
                "finished_at": datetime.now(UTC),
                "source_version": fields.get("source_version"),
                "rows_read": fields.get("rows_read"),
                "rows_upserted": fields.get("rows_upserted"),
                "rows_deleted": fields.get("rows_deleted"),
                "rows_skipped": fields.get("rows_skipped"),
                "notes": fields.get("notes"),
                "error": error,
            },
        )


def _log(dataset: str, season: int | None, status: str, error: str | None, secret: str) -> None:
    label = "-" if season is None else str(season)
    print(f"{dataset} season={label} status={status}", flush=True)
    if error:
        print(redact(error, secret), file=sys.stderr, flush=True)


def _run_one(engine, *, run_group, dataset, season, trigger, source_url, secret, work) -> bool:
    run_id = None
    try:
        run_id = _start(
            engine,
            run_group=run_group,
            dataset=dataset,
            season=season,
            trigger=trigger,
            source_url=source_url,
        )
        if "run_id" in inspect.signature(work).parameters:
            counts = work(run_id)
        else:
            counts = work()
    except Exception as exc:  # noqa: BLE001 - any failure is recorded and the data transaction rolls back
        message = str(exc)
        if run_id is not None:
            _finish(engine, run_id, status="failed", secret=secret, error=message)
        _log(dataset, season, "failed", message, secret)
        return False
    _finish(engine, run_id, status="succeeded", secret=secret, **counts)
    _log(dataset, season, "succeeded", None, secret)
    return True


def _stamp(rows: list[dict], loaded_at: datetime) -> None:
    for row in rows:
        row["loaded_at"] = loaded_at


def upsert(conn, table, rows: list[dict], pk: list[str]) -> int:
    if not rows:
        return 0
    update_cols = [column.name for column in table.columns if column.name not in pk]
    for start in range(0, len(rows), 500):
        chunk = rows[start : start + 500]
        stmt = pg_insert(table).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=pk,
            set_={name: stmt.excluded[name] for name in update_cols},
        )
        conn.execute(stmt)
    return len(rows)


def _absent(conn, table: str, column: str, values: set) -> list:
    if not values:
        return []
    conn.execute(text("CREATE TEMP TABLE key_check (val text PRIMARY KEY) ON COMMIT DROP"))
    conn.execute(
        text("INSERT INTO key_check (val) VALUES (:val) ON CONFLICT DO NOTHING"),
        [{"val": str(value)} for value in values],
    )
    missing = conn.execute(
        text(
            f"""
            SELECT k.val FROM key_check k
            WHERE NOT EXISTS (
                SELECT 1 FROM {table} AS src WHERE src.{column}::text = k.val
            )
            ORDER BY k.val
            """
        )
    ).scalars().all()
    conn.execute(text("DROP TABLE key_check"))
    return list(missing)


def delete_games_missing(conn, season: int, game_ids: list[str]) -> int:
    conn.execute(text("CREATE TEMP TABLE games_batch (game_id text PRIMARY KEY) ON COMMIT DROP"))
    if game_ids:
        conn.execute(
            text("INSERT INTO games_batch (game_id) VALUES (:game_id)"),
            [{"game_id": game_id} for game_id in game_ids],
        )
    result = conn.execute(
        text(
            """
            DELETE FROM games AS g
            WHERE g.season = :season
              AND NOT EXISTS (SELECT 1 FROM games_batch AS b WHERE b.game_id = g.game_id)
            """
        ),
        {"season": season},
    )
    return result.rowcount


def delete_stats_missing(conn, season: int, keys: list[tuple]) -> int:
    conn.execute(
        text(
            """
            CREATE TEMP TABLE stats_batch (
                gsis_id text,
                season smallint,
                week smallint,
                PRIMARY KEY (gsis_id, season, week)
            ) ON COMMIT DROP
            """
        )
    )
    if keys:
        conn.execute(
            text(
                "INSERT INTO stats_batch (gsis_id, season, week) VALUES (:gsis_id, :season, :week)"
            ),
            [{"gsis_id": gsis_id, "season": season_no, "week": week} for gsis_id, season_no, week in keys],
        )
    result = conn.execute(
        text(
            """
            DELETE FROM player_week_stats AS s
            WHERE s.season = :season
              AND NOT EXISTS (
                SELECT 1 FROM stats_batch AS b
                WHERE b.gsis_id = s.gsis_id AND b.season = s.season AND b.week = s.week
              )
            """
        ),
        {"season": season},
    )
    return result.rowcount


def _create_stubs(conn, frame: pl.DataFrame, loaded_at: datetime) -> int:
    ids = [value for value in frame["player_id"].unique().to_list() if value is not None]
    if not ids:
        return 0
    present = set(
        conn.execute(
            text("SELECT gsis_id FROM players WHERE gsis_id = ANY(:ids)"),
            {"ids": ids},
        ).scalars().all()
    )
    missing_ids = [gsis_id for gsis_id in ids if gsis_id not in present]
    if not missing_ids:
        return 0
    if "player_display_name" not in frame.columns:
        raise LoadError("missing required column: player_display_name")
    stubs = []
    seen = set()
    columns = ["player_id", "player_display_name", "position"]
    for record in frame.select(columns).iter_rows(named=True):
        gsis_id = record["player_id"]
        if gsis_id not in missing_ids or gsis_id in seen:
            continue
        seen.add(gsis_id)
        display = record["player_display_name"]
        if display is None or str(display).strip() == "":
            raise LoadError(f"stub player missing display name: {gsis_id}")
        display = str(display)
        position = None if record["position"] is None else str(record["position"])
        stubs.append(
            {
                "gsis_id": gsis_id,
                "display_name": display,
                "first_name": None,
                "last_name": None,
                "position": position,
                "is_stub": True,
                "loaded_at": loaded_at,
            }
        )
    stmt = pg_insert(players).values(stubs).on_conflict_do_nothing(index_elements=["gsis_id"])
    result = conn.execute(stmt)
    if result.rowcount is None or result.rowcount < 0:
        return len(stubs)
    return result.rowcount


def load_teams(engine, source, run_group, trigger: str, secret: str) -> bool:
    source_url = source.url("teams", None)

    def work():
        payload = source.fetch_parquet("teams", None)
        version = _version(source, "teams")
        frame = _read_frame(payload)
        ensure_columns(frame, TEAMS_FIELDS)
        ensure_unique(frame, ["team_abbr"])
        rows = convert_rows(frame, TEAMS_FIELDS)
        _stamp(rows, datetime.now(UTC))
        with engine.begin() as conn:
            upserted = upsert(conn, teams, rows, ["team_abbr"])
        return {
            "source_version": version,
            "rows_read": frame.height,
            "rows_upserted": upserted,
            "rows_deleted": 0,
            "rows_skipped": 0,
        }

    return _run_one(
        engine,
        run_group=run_group,
        dataset="teams",
        season=None,
        trigger=trigger,
        source_url=source_url,
        secret=secret,
        work=work,
    )


def load_players(engine, source, run_group, trigger: str, secret: str) -> bool:
    source_url = source.url("players", None)

    def work():
        payload = source.fetch_parquet("players", None)
        version = _version(source, "players")
        frame = _read_frame(payload)
        ensure_columns(frame, PLAYERS_FIELDS)
        ensure_unique(frame, ["gsis_id"])
        rows = convert_rows(frame, PLAYERS_FIELDS)
        loaded_at = datetime.now(UTC)
        for row in rows:
            row["is_stub"] = False
            row["loaded_at"] = loaded_at
        with engine.begin() as conn:
            upserted = upsert(conn, players, rows, ["gsis_id"])
        return {
            "source_version": version,
            "rows_read": frame.height,
            "rows_upserted": upserted,
            "rows_deleted": 0,
            "rows_skipped": 0,
        }

    return _run_one(
        engine,
        run_group=run_group,
        dataset="players",
        season=None,
        trigger=trigger,
        source_url=source_url,
        secret=secret,
        work=work,
    )


def load_games(engine, source, seasons: list[int], run_group, trigger: str, secret: str) -> set[int]:
    failed: set[int] = set()
    source_url = source.url("games", None)
    try:
        payload = source.fetch_parquet("games", None)
        retrieved_at = _retrieved_at(source, "games")
        version = _version(source, "games")
        frame = _read_frame(payload)
        ensure_columns(frame, GAMES_FIELDS)
    except Exception as exc:  # noqa: BLE001 - file-level failures are recorded per season
        message = str(exc)

        def fail(message=message):
            raise LoadError(message)

        for season in seasons:
            _run_one(
                engine,
                run_group=run_group,
                dataset="games",
                season=season,
                trigger=trigger,
                source_url=source_url,
                secret=secret,
                work=fail,
            )
            failed.add(season)
        return failed

    for season in seasons:
        def work(run_id, season=season):
            sliced = frame.filter(pl.col("season") == season)
            ensure_unique(sliced, ["game_id"])
            ensure_season_week(sliced)
            rows = convert_rows(sliced, GAMES_FIELDS)
            loaded_at = datetime.now(UTC)
            for row in rows:
                row["season_type"] = "REG" if row["game_type"] == "REG" else "POST"
                row["loaded_at"] = loaded_at
            with engine.begin() as conn:
                missing = _absent(
                    conn,
                    "teams",
                    "team_abbr",
                    {row["away_team"] for row in rows} | {row["home_team"] for row in rows},
                )
                if missing:
                    raise LoadError("unresolved team_abbr: " + ", ".join(missing))
                upserted = upsert(conn, games, rows, ["game_id"])
                deleted = delete_games_missing(conn, season, [row["game_id"] for row in rows])
                from loader.schedule_proof import maybe_emit_schedule_receipt

                maybe_emit_schedule_receipt(
                    conn,
                    run_id=run_id,
                    season=season,
                    raw_body=payload,
                    media_type="application/vnd.apache.parquet",
                    source_url=source_url,
                    source_version=version,
                    retrieved_at=retrieved_at,
                )
            return {
                "source_version": version,
                "rows_read": sliced.height,
                "rows_upserted": upserted,
                "rows_deleted": deleted,
                "rows_skipped": 0,
            }

        if not _run_one(
            engine,
            run_group=run_group,
            dataset="games",
            season=season,
            trigger=trigger,
            source_url=source_url,
            secret=secret,
            work=work,
        ):
            failed.add(season)
    return failed


def load_stats(engine, source, season: int, run_group, trigger: str, secret: str) -> bool:
    source_url = source.url("player_week_stats", season)

    def work():
        payload = source.fetch_parquet("player_week_stats", season)
        version = _version(source, "player_week_stats")
        frame = _read_frame(payload)
        ensure_columns(frame, STATS_FIELDS)
        sliced = frame.filter(pl.col("season") == season)
        skipped = sliced.filter(pl.col("player_id").is_null())
        kept = sliced.filter(pl.col("player_id").is_not_null())
        ensure_unique(kept, ["player_id", "season", "week"])
        ensure_unique(kept, ["player_id", "game_id"])
        ensure_season_week(kept)
        ensure_season_type(kept)
        rows = convert_rows(kept, STATS_FIELDS)
        loaded_at = datetime.now(UTC)
        _stamp(rows, loaded_at)
        with engine.begin() as conn:
            missing_teams = _absent(
                conn,
                "teams",
                "team_abbr",
                {row["team"] for row in rows} | {row["opponent_team"] for row in rows},
            )
            if missing_teams:
                raise LoadError("unresolved team_abbr: " + ", ".join(missing_teams))
            missing_games = _absent(conn, "games", "game_id", {row["game_id"] for row in rows})
            if missing_games:
                raise LoadError("unresolved game_id: " + ", ".join(missing_games))
            created = _create_stubs(conn, kept, loaded_at)
            # Delete re-keyed rows before upsert so (gsis_id, game_id) can move.
            deleted = delete_stats_missing(
                conn,
                season,
                [(row["gsis_id"], row["season"], row["week"]) for row in rows],
            )
            upserted = upsert(conn, player_week_stats, rows, ["gsis_id", "season", "week"])
        return {
            "source_version": version,
            "rows_read": sliced.height,
            "rows_upserted": upserted,
            "rows_deleted": deleted,
            "rows_skipped": skipped.height,
            "notes": f"stub_players={created}",
        }

    return _run_one(
        engine,
        run_group=run_group,
        dataset="player_week_stats",
        season=season,
        trigger=trigger,
        source_url=source_url,
        secret=secret,
        work=work,
    )


def _skip_stats(engine, source, season: int, run_group, trigger: str, secret: str) -> None:
    source_url = source.url("player_week_stats", season)

    def work():
        raise LoadError("skipped because the games load failed")

    _run_one(
        engine,
        run_group=run_group,
        dataset="player_week_stats",
        season=season,
        trigger=trigger,
        source_url=source_url,
        secret=secret,
        work=work,
    )


def run_load(
    *,
    database_url: str,
    seasons: list[int],
    datasets: list[str] | None = None,
    trigger: str = "local",
    data_dir: Path | None = None,
    source=None,
    checkpoint=None,
    out: dict | None = None,
    wait_seconds: float = COORDINATION_WAIT_S,
) -> bool:
    if trigger not in TRIGGERS:
        raise LoadError(f"invalid trigger: {trigger}")
    selected = parse_datasets(",".join(datasets) if datasets is not None else None)
    owns_source = source is None
    if source is None:
        if data_dir is None and os.environ.get("SEAM_DATA_DIR"):
            data_dir = Path(os.environ["SEAM_DATA_DIR"])
        source = DirSource(data_dir) if data_dir is not None else HttpSource()
    engine = create_engine(normalize_database_url(database_url), pool_pre_ping=True)
    run_group = uuid4()
    ok = True

    def _checkpoint() -> None:
        ensure_pipeline_ownership()
        if checkpoint is not None:
            checkpoint()

    try:
        with coordination(engine, wait_seconds=wait_seconds):
            if out is not None:
                out["run_group"] = str(run_group)
            try:
                _checkpoint()
                if "teams" in selected and not load_teams(
                    engine, source, run_group, trigger, database_url
                ):
                    ok = False
                _checkpoint()
                if "players" in selected and not load_players(
                    engine, source, run_group, trigger, database_url
                ):
                    ok = False
                _checkpoint()
                failed_games: set[int] = set()
                if "games" in selected:
                    failed_games = load_games(
                        engine, source, seasons, run_group, trigger, database_url
                    )
                    if failed_games:
                        ok = False
                if "player_week_stats" in selected:
                    for season in seasons:
                        _checkpoint()
                        if season in failed_games:
                            _skip_stats(engine, source, season, run_group, trigger, database_url)
                            ok = False
                            continue
                        if not load_stats(
                            engine, source, season, run_group, trigger, database_url
                        ):
                            ok = False
                _checkpoint()
            finally:
                if out is not None:
                    out["games_load_run_ids"] = _succeeded_games(engine, run_group)
                    out["ok"] = ok
            return ok
    finally:
        engine.dispose()
        if owns_source and hasattr(source, "close"):
            source.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loader")
    parser.add_argument("--seasons", default=None)
    parser.add_argument("--datasets", default=",".join(DATASETS))
    parser.add_argument("--trigger", choices=list(TRIGGERS), default="local")
    args = parser.parse_args(argv)
    try:
        seasons = parse_seasons(args.seasons)
        datasets = parse_datasets(args.datasets)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    try:
        ok = run_load(
            database_url=database_url,
            seasons=seasons,
            datasets=datasets,
            trigger=args.trigger,
        )
    except CoordinationError as exc:
        print(exc.reason, file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - the CLI exits non-zero on any unexpected failure
        print(redact(str(exc), database_url), file=sys.stderr)
        return 1
    return 0 if ok else 1
