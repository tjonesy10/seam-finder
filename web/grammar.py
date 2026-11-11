"""Allowlisted advanced list grammar. Validation only; no database access."""

import json
from dataclasses import dataclass
from decimal import Decimal

from web.errors import AppError

TEXT = "text"
MULTI = "multi"
RANGE = "range"
_MAX_DEPTH = 8
_BYTE_BUDGET = 8192
_TEXT_CHARS = 100
_MAX_SORTS = 3
_MAX_FILTERS = 16
_MAX_MULTI = 64
_ABS_BOUND = Decimal(1000000000000)
ADVANCED_KEYS = ("sorts", "filters", "search")

FIELDS: dict[str, dict[str, str]] = {
    "teams": {
        "team_abbr": TEXT,
        "team_name": TEXT,
        "team_nick": TEXT,
        "team_id": TEXT,
        "team_color": TEXT,
        "team_color2": TEXT,
        "loaded_at": TEXT,
        "team_conf": MULTI,
        "team_division": MULTI,
    },
    "players": {
        "gsis_id": TEXT,
        "display_name": TEXT,
        "first_name": TEXT,
        "last_name": TEXT,
        "birth_date": TEXT,
        "college_name": TEXT,
        "pfr_id": TEXT,
        "espn_id": TEXT,
        "pff_id": TEXT,
        "nfl_id": TEXT,
        "esb_id": TEXT,
        "otc_id": TEXT,
        "is_stub": TEXT,
        "loaded_at": TEXT,
        "position": MULTI,
        "position_group": MULTI,
        "latest_team": MULTI,
        "draft_team": MULTI,
        "status": MULTI,
        "height": RANGE,
        "weight": RANGE,
        "rookie_season": RANGE,
        "last_season": RANGE,
        "years_of_experience": RANGE,
        "draft_year": RANGE,
        "draft_round": RANGE,
        "draft_pick": RANGE,
    },
    "games": {
        "game_id": TEXT,
        "game_type": TEXT,
        "season_type": TEXT,
        "gameday": TEXT,
        "weekday": TEXT,
        "gametime": TEXT,
        "overtime": TEXT,
        "location": TEXT,
        "roof": TEXT,
        "surface": TEXT,
        "stadium": TEXT,
        "old_game_id": TEXT,
        "pfr": TEXT,
        "espn": TEXT,
        "loaded_at": TEXT,
        "away_team": MULTI,
        "home_team": MULTI,
        "season": RANGE,
        "week": RANGE,
        "away_score": RANGE,
        "home_score": RANGE,
        "result": RANGE,
        "total": RANGE,
        "spread_line": RANGE,
        "total_line": RANGE,
    },
    "stats": {
        "gsis_id": TEXT,
        "player_display_name": TEXT,
        "season_type": TEXT,
        "game_id": TEXT,
        "loaded_at": TEXT,
        "team": MULTI,
        "opponent_team": MULTI,
        "position": MULTI,
        "position_group": MULTI,
        "season": RANGE,
        "week": RANGE,
        "completions": RANGE,
        "attempts": RANGE,
        "passing_yards": RANGE,
        "passing_tds": RANGE,
        "passing_interceptions": RANGE,
        "sacks_suffered": RANGE,
        "sack_fumbles_lost": RANGE,
        "passing_2pt_conversions": RANGE,
        "carries": RANGE,
        "rushing_yards": RANGE,
        "rushing_tds": RANGE,
        "rushing_fumbles_lost": RANGE,
        "rushing_2pt_conversions": RANGE,
        "receptions": RANGE,
        "targets": RANGE,
        "receiving_yards": RANGE,
        "receiving_tds": RANGE,
        "receiving_fumbles_lost": RANGE,
        "receiving_2pt_conversions": RANGE,
        "target_share": RANGE,
        "special_teams_tds": RANGE,
        "fantasy_points": RANGE,
        "fantasy_points_ppr": RANGE,
    },
    "load-runs": {
        "id": TEXT,
        "run_group": TEXT,
        "trigger": TEXT,
        "started_at": TEXT,
        "finished_at": TEXT,
        "source_url": TEXT,
        "source_version": TEXT,
        "notes": TEXT,
        "error": TEXT,
        "dataset": MULTI,
        "status": MULTI,
        "season": RANGE,
        "rows_read": RANGE,
        "rows_upserted": RANGE,
        "rows_deleted": RANGE,
        "rows_skipped": RANGE,
    },
}

SEARCH: dict[str, tuple[str, ...]] = {
    "teams": ("team_abbr", "team_name", "team_nick", "team_conf", "team_division"),
    "players": (
        "display_name",
        "first_name",
        "last_name",
        "latest_team",
        "position",
        "position_group",
        "college_name",
    ),
    "games": ("away_team", "home_team", "stadium", "game_type", "season_type"),
    "stats": ("player_display_name", "team", "opponent_team", "position", "position_group"),
    "load-runs": ("dataset", "status", "trigger"),
}


@dataclass(frozen=True)
class SortKey:
    id: str
    desc: bool


@dataclass(frozen=True)
class TextFilter:
    op: str
    value: str


@dataclass(frozen=True)
class RangeFilter:
    min: Decimal | None
    max: Decimal | None


@dataclass(frozen=True)
class MultiFilter:
    values: tuple[str, ...]
    missing: bool


@dataclass(frozen=True)
class AdvancedQuery:
    sorts: tuple[SortKey, ...]
    filters: dict[str, TextFilter | RangeFilter | MultiFilter]
    search: str | None


def _invalid(param: str) -> AppError:
    return AppError(400, "invalid_parameter", f"invalid {param}", param)


def reject_duplicate_advanced(query) -> None:
    for key in ADVANCED_KEYS:
        if len(query.getlist(key)) > 1:
            raise AppError(400, "invalid_parameter", f"duplicate parameter: {key}", key)


def reject_advanced_size(query) -> None:
    total = 0
    for key in ADVANCED_KEYS:
        values = query.getlist(key)
        if values:
            total += len(values[-1].encode("utf-8"))
    if total > _BYTE_BUDGET:
        raise AppError(
            400,
            "invalid_parameter",
            "advanced query exceeds 8192 bytes",
            "filters",
        )


def parse_advanced(query, slug: str) -> AdvancedQuery:
    fields = FIELDS[slug]
    sorts = _parse_sorts(query.get("sorts") if "sorts" in query else None, fields)
    filters = _parse_filters(query.get("filters") if "filters" in query else None, fields)
    search = _parse_search(query.get("search") if "search" in query else None)
    return AdvancedQuery(sorts=sorts, filters=filters, search=search)


def _container_depth(raw: str) -> int:
    depth = 0
    maximum = 0
    in_string = False
    escape = False
    for char in raw:
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
            maximum = max(maximum, depth)
        elif char in "}]":
            depth = max(0, depth - 1)
    return maximum


def _pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate member")
        obj[key] = value
    return obj


def _reject_constant(_name: str):
    raise ValueError("nonfinite")


def _loads(raw: str, param: str):
    if _container_depth(raw) > _MAX_DEPTH:
        raise _invalid(param)
    try:
        return json.loads(
            raw,
            object_pairs_hook=_pairs,
            parse_float=Decimal,
            parse_int=int,
            parse_constant=_reject_constant,
        )
    except (ValueError, TypeError, json.JSONDecodeError, RecursionError):
        raise _invalid(param) from None


def _nul(value: str, param: str) -> None:
    if "\x00" in value:
        raise _invalid(param)


def _parse_sorts(raw: str | None, fields: dict[str, str]) -> tuple[SortKey, ...]:
    if raw is None:
        return ()
    value = _loads(raw, "sorts")
    if not isinstance(value, list) or len(value) > _MAX_SORTS:
        raise _invalid("sorts")
    seen: set[str] = set()
    keys: list[SortKey] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"id", "desc"}:
            raise _invalid("sorts")
        ident = item["id"]
        desc = item["desc"]
        if not isinstance(ident, str) or not isinstance(desc, bool):
            raise _invalid("sorts")
        _nul(ident, "sorts")
        if ident not in fields or ident in seen:
            raise _invalid("sorts")
        seen.add(ident)
        keys.append(SortKey(ident, desc))
    return tuple(keys)


def _parse_filters(raw: str | None, fields: dict[str, str]):
    if raw is None:
        return {}
    value = _loads(raw, "filters")
    if not isinstance(value, dict) or len(value) > _MAX_FILTERS:
        raise _invalid("filters")
    parsed = {}
    for key in sorted(value):
        parsed[key] = _one_filter(key, value[key], fields)
    return parsed


def _one_filter(key, body, fields: dict[str, str]):
    if not isinstance(key, str):
        raise _invalid("filters")
    _nul(key, "filters")
    if not isinstance(body, dict) or "kind" not in body or not isinstance(body["kind"], str):
        raise _invalid("filters")
    kind = body["kind"]
    if kind == TEXT:
        parsed = _text_filter(body)
    elif kind == RANGE:
        parsed = _range_filter(body)
    elif kind == MULTI:
        parsed = _multi_filter(body)
    else:
        raise _invalid("filters")
    if key not in fields or fields[key] != kind:
        raise _invalid("filters")
    return parsed


def _text_filter(body: dict) -> TextFilter:
    if set(body) - {"kind", "op", "value"} or "value" not in body:
        raise _invalid("filters")
    if "op" in body:
        op = body["op"]
        if op not in {"contains", "equals"}:
            raise _invalid("filters")
    else:
        op = "contains"
    value = body["value"]
    if not isinstance(value, str):
        raise _invalid("filters")
    _nul(value, "filters")
    value = value.strip()
    if len(value) > _TEXT_CHARS:
        raise _invalid("filters")
    return TextFilter(op, value)


def _bound(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise _invalid("filters")
    if isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, Decimal):
        number = value
    else:
        raise _invalid("filters")
    if not number.is_finite() or abs(number) > _ABS_BOUND:
        raise _invalid("filters")
    return number


def _range_filter(body: dict) -> RangeFilter:
    if set(body) != {"kind", "min", "max"}:
        raise _invalid("filters")
    low = _bound(body["min"])
    high = _bound(body["max"])
    if low is not None and high is not None and low > high:
        raise _invalid("filters")
    return RangeFilter(low, high)


def _multi_filter(body: dict) -> MultiFilter:
    if set(body) != {"kind", "values", "missing"}:
        raise _invalid("filters")
    values = body["values"]
    missing = body["missing"]
    if not isinstance(values, list) or not isinstance(missing, bool):
        raise _invalid("filters")
    if len(values) > _MAX_MULTI:
        raise _invalid("filters")
    cleaned: list[str] = []
    for item in values:
        if not isinstance(item, str):
            raise _invalid("filters")
        _nul(item, "filters")
        text = item.strip()
        if text == "" or len(text) > _TEXT_CHARS:
            raise _invalid("filters")
        cleaned.append(text)
    return MultiFilter(tuple(cleaned), missing)


def _parse_search(raw: str | None) -> str | None:
    if raw is None:
        return None
    _nul(raw, "search")
    text = raw.strip()
    if text == "":
        return None
    if len(text) > _TEXT_CHARS:
        raise _invalid("search")
    return text
