"""Load historical DraftKings Classic salaries and points from RotoGuru.

The public URL returns an HTML page. The SCSV sits in a preformatted block
under the header row. A header with no data rows is a missing REG week:
the loader skips it and leaves that week untouched.
"""

import argparse
import hashlib
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, text

from loader.run import _finish, _start, parse_seasons, redact, upsert
from loader.source import DownloadError, LoadError
from loader.tables import dk_classic_salaries
from loader.url import normalize_database_url

DATASET = "dk_classic_salaries"
TRIGGERS = ("local", "manual")
WEEK_MIN = 1
WEEK_MAX = 18
# RotoGuru kept writing Oppt=oak for the Raiders after the move to Las Vegas.
OAK_AS_LV_FROM = 2020
SCSV_HEADER = "Week;Year;GID;Name;Pos;Team;h/a;Oppt;DK points;DK salary"
_SUFFIX = re.compile(r"\b(?:jr|sr|ii|iii|iv|v)\b")
_INT_MIN = -2147483648
_INT_MAX = 2147483647

# Explicit RotoGuru code → nflverse team_abbr. Historical STL, SD, and OAK stay.
TEAM_MAP = {
    "ari": "ARI",
    "atl": "ATL",
    "bal": "BAL",
    "buf": "BUF",
    "car": "CAR",
    "chi": "CHI",
    "cin": "CIN",
    "cle": "CLE",
    "dal": "DAL",
    "den": "DEN",
    "det": "DET",
    "gnb": "GB",
    "hou": "HOU",
    "ind": "IND",
    "jac": "JAX",
    "kan": "KC",
    "lac": "LAC",
    "lar": "LAR",
    "lvr": "LV",
    "mia": "MIA",
    "min": "MIN",
    "nor": "NO",
    "nwe": "NE",
    "nyg": "NYG",
    "nyj": "NYJ",
    "oak": "OAK",
    "phi": "PHI",
    "pit": "PIT",
    "sdg": "SD",
    "sea": "SEA",
    "sfo": "SF",
    "stl": "STL",
    "tam": "TB",
    "ten": "TEN",
    "was": "WAS",
}


class MissingWeek(Exception):
    """This REG week has no SCSV rows. Skip it; do not fail the run."""


@dataclass(frozen=True)
class SalaryRow:
    week: int
    season: int
    rotoguru_gid: int
    name_raw: str
    pos_raw: str
    team_raw: str
    home_away: str
    opponent_raw: str
    dk_points: Decimal
    dk_salary: int


def week_url(season: int, week: int) -> str:
    return (
        "http://rotoguru1.com/cgi-bin/fyday.pl"
        f"?week={week}&year={season}&game=dk&scsv=1"
    )


def parse_weeks(value: str | None) -> list[int]:
    if value is None or value.strip() == "":
        return list(range(WEEK_MIN, WEEK_MAX + 1))
    text_value = value.strip()
    try:
        if "-" in text_value:
            left, right = text_value.split("-", 1)
            start, end = int(left.strip()), int(right.strip())
            if end < start:
                raise ValueError
            weeks = list(range(start, end + 1))
        else:
            weeks = [int(text_value)]
    except ValueError:
        raise ValueError(
            "weeks must be a week or a range from 1 to 18, for example 1 or 1-18"
        ) from None
    if any(week < WEEK_MIN or week > WEEK_MAX for week in weeks):
        raise ValueError(
            "weeks must be a week or a range from 1 to 18, for example 1 or 1-18"
        )
    return weeks


def team_abbr_for(code: str, season: int) -> str:
    key = code.strip().lower()
    if key == "oak" and season >= OAK_AS_LV_FROM:
        return "LV"
    abbr = TEAM_MAP.get(key)
    if abbr is None:
        raise LoadError(f"unmapped team code: {key}")
    return abbr


def _is_opponent_dash(code: str) -> bool:
    # RotoGuru writes Oppt=- for a bye or an unscheduled game. It is not a team code.
    return code.strip() == "-"


def _opponent_abbr(code: str, season: int) -> str | None:
    if _is_opponent_dash(code):
        return None
    return team_abbr_for(code, season)


def is_dst(pos_raw: str) -> bool:
    return pos_raw.strip().lower() == "def"


def display_name(name_raw: str) -> str:
    text_value = " ".join(name_raw.split())
    if "," in text_value:
        last, first = text_value.split(",", 1)
        text_value = f"{first} {last}"
    return " ".join(text_value.split())


def name_key(name: str) -> str:
    text_value = display_name(name).lower()
    text_value = text_value.replace(".", "").replace("'", "").replace("’", "").replace("`", "")
    text_value = _SUFFIX.sub(" ", text_value)
    return " ".join(text_value.split())


def gsis_for(
    name_raw: str,
    pos_raw: str,
    team_abbr: str,
    week: int,
    week_index: dict,
    fallback: dict,
) -> str | None:
    """Prefer the player who already played that team-week.

    An ambiguous team-week set stays unmapped. An empty set falls back to the
    one player with that name and position tied to the team (latest team, or
    any REG week that season).
    """
    if is_dst(pos_raw):
        return None
    key = (name_key(name_raw), pos_raw.strip().upper(), team_abbr, week)
    hits = week_index.get(key, set())
    if len(hits) == 1:
        return next(iter(hits))
    if len(hits) > 1:
        return None
    choices = fallback.get((key[0], key[1], team_abbr), set())
    if len(choices) == 1:
        return next(iter(choices))
    return None


def _integer(value: str, label: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise LoadError(f"invalid scsv integer: {label}") from exc
    if number < _INT_MIN or number > _INT_MAX:
        raise LoadError(f"invalid scsv integer: {label}")
    return number


def _points(value: str) -> Decimal:
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise LoadError("invalid number: DK points") from exc
    number = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    _sign, digits, exponent = number.as_tuple()
    int_digits = 0 if digits == (0,) else max(0, len(digits) + int(exponent))
    if int_digits > 6:
        raise LoadError("numeric overflow: DK points")
    return number


def _parse_row(line: str, seen: set[int]) -> SalaryRow:
    parts = [part.strip() for part in line.split(";")]
    if len(parts) != 10:
        raise LoadError("invalid scsv row")
    week_s, year_s, gid_s, name, pos, team, home_away, opponent, points_s, salary_s = parts
    if not name or not pos or not team or not home_away or not opponent:
        raise LoadError("invalid scsv row")
    week = _integer(week_s, "Week")
    season = _integer(year_s, "Year")
    gid = _integer(gid_s, "GID")
    # A trailing semicolon with nothing after it is a blank DK salary. Load it as 0.
    salary = 0 if salary_s == "" else _integer(salary_s, "DK salary")
    if gid in seen:
        raise LoadError("duplicate key: rotoguru_gid")
    seen.add(gid)
    return SalaryRow(
        week=week,
        season=season,
        rotoguru_gid=gid,
        name_raw=name,
        pos_raw=pos,
        team_raw=team,
        home_away=home_away,
        opponent_raw=opponent,
        dk_points=_points(points_s),
        dk_salary=salary,
    )


def parse_scsv(body: bytes) -> list[SalaryRow]:
    if body is None or body.strip() == b"":
        raise MissingWeek("empty scsv")
    try:
        text_value = body.decode("utf-8")
    except UnicodeDecodeError:
        text_value = body.decode("latin-1")
    text_value = text_value.removeprefix("\ufeff")
    lines = text_value.splitlines()
    header_at = None
    for index, line in enumerate(lines):
        if SCSV_HEADER in line:
            header_at = index
            break
    if header_at is None:
        raise LoadError("missing header")
    rows: list[SalaryRow] = []
    seen: set[int] = set()
    # The live page puts the header on the same line as <pre>.
    suffix = lines[header_at].split(SCSV_HEADER, 1)[1].strip()
    if suffix and not suffix.startswith("<"):
        rows.append(_parse_row(suffix, seen))
    for line in lines[header_at + 1 :]:
        stripped = line.strip()
        if stripped == "":
            continue
        if stripped.startswith("<") or stripped.lower().startswith("</pre"):
            break
        rows.append(_parse_row(stripped, seen))
    if not rows:
        raise MissingWeek("header only")
    return rows


def _notes(week: int, unmapped: int, opponent_dash: int) -> str:
    parts = [f"week={week}"]
    if unmapped:
        parts.append(f"unmapped_skill={unmapped}")
    if opponent_dash:
        parts.append(f"opponent_dash={opponent_dash}")
    return "; ".join(parts)


def _skipped(week: int) -> dict:
    return {
        "rows_read": 0,
        "rows_upserted": 0,
        "rows_deleted": 0,
        "rows_skipped": 1,
        "notes": f"week={week}; skipped=missing scsv",
    }


def _player_indexes(conn, season: int) -> tuple[dict, dict]:
    records = conn.execute(
        text(
            """
            SELECT p.gsis_id, p.display_name, p.position, p.latest_team,
                   s.week AS week, s.team AS stat_team, s.position AS stat_position
            FROM players p
            LEFT JOIN player_week_stats s
              ON s.gsis_id = p.gsis_id
             AND s.season = :season
             AND s.season_type = 'REG'
            """
        ),
        {"season": season},
    ).mappings()
    week_index: dict[tuple, set[str]] = defaultdict(set)
    teams_for: dict[str, set[str]] = defaultdict(set)
    players: dict[str, tuple[str, str]] = {}
    for record in records:
        gsis_id = record["gsis_id"]
        position = (record["position"] or "").upper()
        key = name_key(record["display_name"] or "")
        players[gsis_id] = (key, position)
        if record["latest_team"]:
            teams_for[gsis_id].add(record["latest_team"])
        if record["week"] is not None and record["stat_team"]:
            teams_for[gsis_id].add(record["stat_team"])
            stat_position = (record["stat_position"] or record["position"] or "").upper()
            week_index[(key, stat_position, record["stat_team"], int(record["week"]))].add(gsis_id)
    fallback: dict[tuple, set[str]] = defaultdict(set)
    for gsis_id, (key, position) in players.items():
        for team in teams_for[gsis_id]:
            fallback[(key, position, team)].add(gsis_id)
    return week_index, fallback


def _missing_team_abbrs(conn, abbrs: set[str]) -> list[str]:
    if not abbrs:
        return []
    found = set(
        conn.execute(
            text("SELECT team_abbr FROM teams WHERE team_abbr = ANY(:abbrs)"),
            {"abbrs": list(abbrs)},
        ).scalars()
    )
    return sorted(abbrs - found)


def _reg_games(conn, season: int, week: int, teams: set[str]) -> dict[str, str | None]:
    found: dict[str, list[str]] = {team: [] for team in teams}
    if not teams:
        return {}
    rows = conn.execute(
        text(
            """
            SELECT game_id, home_team, away_team
            FROM games
            WHERE season = :season
              AND week = :week
              AND season_type = 'REG'
              AND (home_team = ANY(:teams) OR away_team = ANY(:teams))
            """
        ),
        {"season": season, "week": week, "teams": list(teams)},
    )
    for game_id, home, away in rows:
        if home in found:
            found[home].append(game_id)
        if away in found:
            found[away].append(game_id)
    return {team: (ids[0] if len(ids) == 1 else None) for team, ids in found.items()}


def _delete_missing(conn, season: int, week: int, gids: list[int]) -> int:
    result = conn.execute(
        text(
            """
            DELETE FROM dk_classic_salaries
            WHERE season = :season
              AND week = :week
              AND NOT (rotoguru_gid = ANY(:gids))
            """
        ),
        {"season": season, "week": week, "gids": gids},
    )
    return result.rowcount or 0


def _load_week_data(engine, source, season: int, week: int) -> dict:
    body = source.fetch(season, week)
    if body is None:
        return _skipped(week)
    try:
        parsed = parse_scsv(body)
    except MissingWeek:
        return _skipped(week)
    for row in parsed:
        if row.season != season or row.week != week:
            raise LoadError("scsv season or week does not match the request")
    digest = hashlib.sha256(body).hexdigest()
    url = week_url(season, week)
    fetched_at = datetime.now(UTC)
    team_of = {row.rotoguru_gid: team_abbr_for(row.team_raw, season) for row in parsed}
    opponent_dash = sum(_is_opponent_dash(row.opponent_raw) for row in parsed)
    opponent_of = {row.rotoguru_gid: _opponent_abbr(row.opponent_raw, season) for row in parsed}
    loaded_at = datetime.now(UTC)
    with engine.begin() as conn:
        missing = _missing_team_abbrs(conn, set(team_of.values()))
        if missing:
            raise LoadError("unresolved team_abbr: " + ", ".join(missing))
        week_index, fallback = _player_indexes(conn, season)
        games = _reg_games(conn, season, week, set(team_of.values()))
        records = []
        unmapped = 0
        for row in parsed:
            team_abbr = team_of[row.rotoguru_gid]
            gsis_id = gsis_for(
                row.name_raw, row.pos_raw, team_abbr, week, week_index, fallback
            )
            if not is_dst(row.pos_raw) and gsis_id is None:
                unmapped += 1
            records.append(
                {
                    "season": season,
                    "week": week,
                    "rotoguru_gid": row.rotoguru_gid,
                    "name_raw": row.name_raw,
                    "pos_raw": row.pos_raw,
                    "team_raw": row.team_raw,
                    "home_away": row.home_away,
                    "opponent_raw": row.opponent_raw,
                    "dk_points": row.dk_points,
                    "dk_salary": row.dk_salary,
                    "gsis_id": gsis_id,
                    "team_abbr": team_abbr,
                    "opponent_abbr": opponent_of[row.rotoguru_gid],
                    "game_id": games.get(team_abbr),
                    "source_url": url,
                    "source_fetched_at": fetched_at,
                    "source_sha256": digest,
                    "loaded_at": loaded_at,
                }
            )
        upserted = upsert(conn, dk_classic_salaries, records, ["season", "week", "rotoguru_gid"])
        deleted = _delete_missing(conn, season, week, [row.rotoguru_gid for row in parsed])
    return {
        "rows_read": len(parsed),
        "rows_upserted": upserted,
        "rows_deleted": deleted,
        "rows_skipped": 0,
        "notes": _notes(week, unmapped, opponent_dash),
    }


def _report(season: int, week: int, status: str, error: str | None, secret: str) -> None:
    print(f"dk_classic_salaries season={season} week={week} status={status}", flush=True)
    if error:
        print(redact(error, secret), file=sys.stderr, flush=True)


def load_week(engine, source, run_group, season: int, week: int, trigger: str, secret: str) -> bool:
    url = week_url(season, week)
    run_id = None
    try:
        run_id = _start(
            engine,
            run_group=run_group,
            dataset=DATASET,
            season=season,
            trigger=trigger,
            source_url=url,
        )
        counts = _load_week_data(engine, source, season, week)
    except Exception as exc:  # noqa: BLE001 - record the failure; the data transaction rolled back
        message = str(exc)
        if run_id is not None:
            _finish(
                engine,
                run_id,
                status="failed",
                secret=secret,
                notes=f"week={week}",
                error=message,
            )
        _report(season, week, "failed", message, secret)
        return False
    _finish(engine, run_id, status="succeeded", secret=secret, **counts)
    _report(season, week, "succeeded", None, secret)
    return True


class RotoGuruDirSource:
    """Read `{root}/{season}/week_{week:02}.scsv`. A missing file is a missing week."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def fetch(self, season: int, week: int) -> bytes | None:
        path = self.root / str(season) / f"week_{week:02d}.scsv"
        if not path.is_file():
            return None
        return path.read_bytes()


class RotoGuruHttpSource:
    """GET the public SCSV URL. A 404 is a missing week. Other failures retry 3 times."""

    def __init__(self, client=None, sleeper=time.sleep, retries: int = 3):
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=60.0,
            follow_redirects=True,
            headers={"User-Agent": "seam-finder-loader"},
        )
        self.sleeper = sleeper
        self.retries = retries

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def fetch(self, season: int, week: int) -> bytes | None:
        url = week_url(season, week)
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.client.get(url)
            except Exception as exc:  # noqa: BLE001 - network errors are retried
                last = exc
            else:
                if response.status_code == 404:
                    return None
                if response.status_code >= 400:
                    last = DownloadError(f"HTTP {response.status_code} for {url}")
                else:
                    return response.content
            if attempt == self.retries:
                break
            self.sleeper(2**attempt)
        raise DownloadError(f"download failed after {self.retries} retries: {last}")


def run_dk_classic(
    *,
    database_url: str,
    seasons: list[int],
    weeks: list[int] | None = None,
    trigger: str = "local",
    data_dir: Path | None = None,
    source=None,
) -> bool:
    if trigger not in TRIGGERS:
        raise LoadError(f"invalid trigger: {trigger}")
    selected = list(range(WEEK_MIN, WEEK_MAX + 1) if weeks is None else weeks)
    if any(week < WEEK_MIN or week > WEEK_MAX for week in selected):
        raise LoadError("weeks must be from 1 to 18")
    owns_source = source is None
    if source is None:
        if data_dir is None and os.environ.get("SEAM_ROTOGURU_DIR"):
            data_dir = Path(os.environ["SEAM_ROTOGURU_DIR"])
        source = RotoGuruDirSource(data_dir) if data_dir is not None else RotoGuruHttpSource()
    engine = create_engine(normalize_database_url(database_url), pool_pre_ping=True)
    run_group = uuid4()
    ok = True
    try:
        for season in seasons:
            for week in selected:
                if not load_week(engine, source, run_group, season, week, trigger, database_url):
                    ok = False
        return ok
    finally:
        engine.dispose()
        if owns_source and hasattr(source, "close"):
            source.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loader.dk_classic")
    parser.add_argument("--seasons", default="2015-2021")
    parser.add_argument("--weeks", default=None)
    parser.add_argument("--trigger", choices=list(TRIGGERS), default="local")
    args = parser.parse_args(argv)
    try:
        seasons = parse_seasons(args.seasons)
        weeks = parse_weeks(args.weeks)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    raw_dir = os.environ.get("SEAM_ROTOGURU_DIR")
    try:
        ok = run_dk_classic(
            database_url=database_url,
            seasons=seasons,
            weeks=weeks,
            trigger=args.trigger,
            data_dir=Path(raw_dir) if raw_dir else None,
        )
    except Exception as exc:  # noqa: BLE001 - the CLI exits non-zero on any unexpected failure
        print(redact(str(exc), database_url), file=sys.stderr)
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
