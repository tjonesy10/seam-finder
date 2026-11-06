"""Load one current-slate DraftKings NFL Classic CSV into ``dk_classic_slate``.

Cosmo stages ``DKSalaries.csv``. This module reads that file from disk. It does
not download a salary file.
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

from sqlalchemy import create_engine, text

from loader.dk_classic import _missing_team_abbrs, _player_indexes, _reg_games, gsis_for
from loader.run import SEASON_MAX, SEASON_MIN, _finish, _start, redact, upsert
from loader.source import LoadError
from loader.tables import dk_classic_slate
from loader.url import normalize_database_url

DATASET = "dk_classic_slate"
TRIGGERS = ("local", "manual", "scheduled")
WEEK_MIN = 1
WEEK_MAX = 18
REQUIRED = (
    "Position",
    "Name + ID",
    "Name",
    "ID",
    "Roster Position",
    "Salary",
    "Game Info",
    "TeamAbbrev",
    "AvgPointsPerGame",
)
CLASSIC_ONLY = "Showdown slate rejected: Classic-only"
_GAME_TEAMS = re.compile(r"^\s*([A-Za-z]{2,3})\s*@\s*([A-Za-z]{2,3})\b")


@dataclass(frozen=True)
class SlateRow:
    dk_id: str
    name_raw: str
    position_raw: str
    roster_position_raw: str
    team_raw: str
    game_info_raw: str
    salary: Decimal
    avg_points_per_game: Decimal | None


def _decode(body: bytes) -> str:
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return body.decode("latin-1")


def _number(value: str, label: str, *, blank_none: bool, precision: int, scale: int):
    text_value = value.strip().replace("$", "").replace(",", "")
    if text_value == "":
        if blank_none:
            return None
        raise LoadError(f"invalid number: {label}")
    try:
        number = Decimal(text_value)
    except InvalidOperation as exc:
        raise LoadError(f"invalid number: {label}") from exc
    number = number.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    _sign, digits, exponent = number.as_tuple()
    int_digits = 0 if digits == (0,) else max(0, len(digits) + int(exponent))
    if int_digits > precision - scale:
        raise LoadError(f"numeric overflow: {label}")
    return number


def parse_dk_csv(body: bytes) -> list[SlateRow]:
    """Parse a Classic export. Extra columns are ignored. Header order may vary."""
    if body is None or body.strip() == b"":
        raise LoadError("missing header")
    reader = csv.reader(io.StringIO(_decode(body)))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise LoadError("missing header") from exc
    fields = [cell.strip() for cell in header]
    if not any(fields):
        raise LoadError("missing header")
    missing = [name for name in REQUIRED if name not in fields]
    if missing:
        raise LoadError("missing required column: " + ", ".join(missing))
    index = {name: fields.index(name) for name in REQUIRED}
    rows: list[SlateRow] = []
    seen: set[str] = set()
    for cells in reader:
        if not any(cell.strip() for cell in cells):
            continue
        values = {name: _cell(cells, index, name) for name in REQUIRED}
        dk_id = values["ID"]
        name = values["Name"]
        position = values["Position"]
        roster = values["Roster Position"]
        team = values["TeamAbbrev"]
        if not dk_id or not name or not position or not roster or not team:
            raise LoadError("invalid dk csv row")
        if dk_id in seen:
            raise LoadError("duplicate key: dk_id")
        seen.add(dk_id)
        rows.append(
            SlateRow(
                dk_id=dk_id,
                name_raw=name,
                position_raw=position,
                roster_position_raw=roster,
                team_raw=team,
                game_info_raw=values["Game Info"],
                salary=_number(values["Salary"], "Salary", blank_none=False, precision=10, scale=2),
                avg_points_per_game=_number(
                    values["AvgPointsPerGame"],
                    "AvgPointsPerGame",
                    blank_none=True,
                    precision=8,
                    scale=2,
                ),
            )
        )
    return rows


def _cell(cells: list[str], index: dict[str, int], name: str) -> str:
    pos = index[name]
    if pos >= len(cells):
        return ""
    return cells[pos].strip()


def reject_showdown(rows: list[SlateRow]) -> None:
    """Classic slates have many games and no captain slot. Anything else fails."""
    reasons = []
    if any("CPT" in row.roster_position_raw.upper() for row in rows):
        reasons.append("Roster Position contains CPT")
    game_count = len({row.game_info_raw for row in rows})
    if game_count <= 1:
        reasons.append(f"distinct Game Info values is {game_count}")
    if reasons:
        raise LoadError(CLASSIC_ONLY + "; " + "; ".join(reasons))


def normalize_team(code: str) -> str:
    key = code.strip().upper()
    if key == "":
        raise LoadError("invalid team: TeamAbbrev")
    return key


def is_dst(row: SlateRow) -> bool:
    return "DST" in f"{row.position_raw} {row.roster_position_raw}".upper()


def opponent_abbr(team_abbr: str, game_info: str) -> str | None:
    match = _GAME_TEAMS.match(game_info)
    if match is None:
        return None
    away = match.group(1).upper()
    home = match.group(2).upper()
    if team_abbr == away and team_abbr != home:
        return home
    if team_abbr == home and team_abbr != away:
        return away
    return None


def _notes(week: int, unmapped: int) -> str:
    if unmapped:
        return f"week={week}; unmapped_skill={unmapped}"
    return f"week={week}"


def _delete_missing(conn, season: int, week: int, dk_ids: list[str]) -> int:
    result = conn.execute(
        text(
            """
            DELETE FROM dk_classic_slate
            WHERE season = :season
              AND week = :week
              AND NOT (dk_id = ANY(:dk_ids))
            """
        ),
        {"season": season, "week": week, "dk_ids": dk_ids},
    )
    return result.rowcount or 0


def _load_slate_data(engine, path: Path, season: int, week: int) -> dict:
    body = path.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    parsed = parse_dk_csv(body)
    reject_showdown(parsed)
    source_name = path.name or "DKSalaries.csv"
    loaded_at = datetime.now(UTC)
    team_of = {row.dk_id: normalize_team(row.team_raw) for row in parsed}
    with engine.begin() as conn:
        missing = _missing_team_abbrs(conn, set(team_of.values()))
        if missing:
            raise LoadError("unresolved team_abbr: " + ", ".join(missing))
        week_index, fallback = _player_indexes(conn, season)
        games = _reg_games(conn, season, week, set(team_of.values()))
        records = []
        unmapped = 0
        for row in parsed:
            team_abbr = team_of[row.dk_id]
            if is_dst(row):
                gsis_id = None
            else:
                gsis_id = gsis_for(
                    row.name_raw,
                    row.position_raw,
                    team_abbr,
                    week,
                    week_index,
                    fallback,
                )
                if gsis_id is None:
                    unmapped += 1
            records.append(
                {
                    "season": season,
                    "week": week,
                    "dk_id": row.dk_id,
                    "name_raw": row.name_raw,
                    "position_raw": row.position_raw,
                    "roster_position_raw": row.roster_position_raw,
                    "team_raw": row.team_raw,
                    "game_info_raw": row.game_info_raw or None,
                    "salary": row.salary,
                    "avg_points_per_game": row.avg_points_per_game,
                    "gsis_id": gsis_id,
                    "team_abbr": team_abbr,
                    "opponent_abbr": opponent_abbr(team_abbr, row.game_info_raw),
                    "game_id": games.get(team_abbr),
                    "source_name": source_name,
                    "source_sha256": digest,
                    "source_loaded_at": loaded_at,
                    "loaded_at": loaded_at,
                }
            )
        upserted = upsert(conn, dk_classic_slate, records, ["season", "week", "dk_id"])
        deleted = _delete_missing(conn, season, week, [row.dk_id for row in parsed])
    return {
        "rows_read": len(parsed),
        "rows_upserted": upserted,
        "rows_deleted": deleted,
        "rows_skipped": 0,
        "notes": _notes(week, unmapped),
        "source_version": digest,
    }


def _report(season: int, week: int, status: str, error: str | None, secret: str) -> None:
    print(f"dk_classic_slate season={season} week={week} status={status}", flush=True)
    if error:
        print(redact(error, secret), file=sys.stderr, flush=True)


def load_slate(engine, path: Path, run_group, season: int, week: int, trigger: str, secret: str) -> bool:
    source_name = path.name or "DKSalaries.csv"
    run_id = _start(
        engine,
        run_group=run_group,
        dataset=DATASET,
        season=season,
        trigger=trigger,
        source_url=f"file:{source_name}",
    )
    try:
        if not path.is_file():
            raise LoadError(
                f"staged DKSalaries.csv is missing ({source_name}); refusing to fetch DraftKings"
            )
        counts = _load_slate_data(engine, path, season, week)
    except Exception as exc:  # noqa: BLE001 - record the failure; the data transaction rolled back
        message = str(exc)
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


def _csv_member(archive: zipfile.ZipFile) -> str | None:
    names = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        parts = info.filename.split("/")
        if info.filename.startswith("/") or ".." in parts:
            continue
        if info.filename.lower().endswith(".csv"):
            names.append(info.filename)
    if not names:
        return None
    preferred = [name for name in names if name.rsplit("/", 1)[-1].lower() == "dksalaries.csv"]
    return preferred[0] if preferred else names[0]


def _read_url(url: str, headers: dict) -> bytes:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=60) as response:
        return response.read()


def fetch_staged_artifact(name: str, dest: str) -> bool:
    """Write the newest Actions artifact CSV of this name to ``dest``.

    ``GH_TOKEN`` and ``GH_REPO`` come from the environment. A missing artifact
    or a failed request returns False and writes nothing. The token and file
    bytes are not printed.
    """
    label = (name or "").strip()
    token = os.environ.get("GH_TOKEN", "").strip()
    repo = os.environ.get("GH_REPO", "").strip()
    if label == "" or token == "" or repo == "":
        return False
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "User-Agent": "seam-finder-loader",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        listing = _read_url(
            f"https://api.github.com/repos/{repo}/actions/artifacts?per_page=100",
            headers,
        )
        payload = json.loads(listing.decode("utf-8"))
        matches = [
            item
            for item in payload.get("artifacts", [])
            if item.get("name") == label and not item.get("expired")
        ]
        if not matches:
            return False
        matches.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        blob = _read_url(matches[0]["archive_download_url"], headers)
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            chosen = _csv_member(archive)
            if chosen is None:
                return False
            data = archive.read(chosen)
        Path(dest).write_bytes(data)
    except Exception:  # noqa: BLE001 - a missing artifact must fall through to the CLI failure
        return False
    return True


def run_dk_slate(
    *,
    database_url: str,
    csv_path: Path,
    season: int,
    week: int,
    trigger: str = "local",
) -> bool:
    if trigger not in TRIGGERS:
        raise LoadError(f"invalid trigger: {trigger}")
    if season < SEASON_MIN or season > SEASON_MAX:
        raise LoadError("season out of range")
    if week < WEEK_MIN or week > WEEK_MAX:
        raise LoadError("week must be from 1 to 18")
    engine = create_engine(normalize_database_url(database_url), pool_pre_ping=True)
    try:
        return load_slate(engine, Path(csv_path), uuid4(), season, week, trigger, database_url)
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loader.dk_slate")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--season", required=True)
    parser.add_argument("--week", required=True)
    parser.add_argument("--trigger", choices=list(TRIGGERS), default="local")
    args = parser.parse_args(argv)
    try:
        season = int(str(args.season).strip())
        week = int(str(args.week).strip())
    except ValueError:
        print("season and week must be integers", file=sys.stderr)
        return 1
    if season < SEASON_MIN or season > SEASON_MAX:
        print("season out of range", file=sys.stderr)
        return 1
    if week < WEEK_MIN or week > WEEK_MAX:
        print("week must be from 1 to 18", file=sys.stderr)
        return 1
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    try:
        ok = run_dk_slate(
            database_url=database_url,
            csv_path=Path(args.csv),
            season=season,
            week=week,
            trigger=args.trigger,
        )
    except Exception as exc:  # noqa: BLE001 - the CLI exits non-zero on any unexpected failure
        print(redact(str(exc), database_url), file=sys.stderr)
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
