"""Query-parameter rules shared by the JSON API and the HTML pages."""

import re
from dataclasses import dataclass

from web.errors import AppError
from web.grammar import (
    ADVANCED_KEYS,
    AdvancedQuery,
    parse_advanced,
    reject_advanced_size,
    reject_duplicate_advanced,
)
from web.resources import Resource

_OFFSET_MAX = 2_147_483_647


@dataclass(frozen=True)
class ListParams:
    limit: int
    offset: int
    sort: str
    order: str
    values: dict[str, str]
    advanced: AdvancedQuery | None = None


def reject_unknown(query, allowed: set[str]) -> None:
    for key in query:
        if key not in allowed:
            raise AppError(400, "unknown_parameter", f"unknown parameter: {key}", key)


def parse_resource(query, resource: Resource, *, advanced: bool = False) -> ListParams:
    allowed = {"limit", "offset", "sort", "order", *(item.name for item in resource.filters)}
    if advanced:
        allowed.update(ADVANCED_KEYS)
    reject_unknown(query, allowed)
    values: dict[str, str] = {}
    for item in resource.filters:
        parsed = _parse_filter(item.name, item.kind, query.get(item.name))
        if parsed is not None:
            values[item.name] = parsed
    params = ListParams(
        limit=_limit(query.get("limit")),
        offset=_offset(query.get("offset")),
        sort=_sort(query.get("sort"), resource),
        order=_order(query.get("order"), resource),
        values=values,
    )
    if not advanced or not any(key in query for key in ADVANCED_KEYS):
        return params
    reject_duplicate_advanced(query)
    reject_advanced_size(query)
    return ListParams(
        limit=params.limit,
        offset=params.offset,
        sort=params.sort,
        order=params.order,
        values=params.values,
        advanced=parse_advanced(query, resource.slug),
    )


def _parse_filter(name: str, kind: str, raw: str | None) -> str | None:
    if kind == "season":
        return _int_text(name, raw, 1999, 2100, "season must be an integer from 1999 to 2100")
    if kind == "week":
        return _int_text(name, raw, 1, 22, "week must be an integer from 1 to 22")
    if kind == "season_type":
        return _season_type(raw)
    if kind == "team":
        return _letters(name, raw, 2, 3, "team must be 2 to 3 letters", upper=True)
    if kind == "position":
        return _letters(name, raw, 1, 5, "position must be 1 to 5 letters", upper=True)
    if kind == "q":
        return _query_text(raw)
    if kind in {"fold", "exact"}:
        return _bounded(name, raw)
    raise AppError(500, "internal_error", "Something went wrong.")


def _blank(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        return None
    return text


def _bounded(name: str, raw: str | None, limit: int = 64) -> str | None:
    text = _blank(raw)
    if text is None:
        return None
    if len(text) > limit:
        raise AppError(400, "invalid_parameter", f"{name} is too long", name)
    return text


def _query_text(raw: str | None) -> str | None:
    text = _blank(raw)
    if text is None:
        return None
    if len(text) < 2 or len(text) > 50:
        raise AppError(400, "invalid_parameter", "q must be 2 to 50 characters", "q")
    return text


def _letters(name: str, raw: str | None, low: int, high: int, message: str, *, upper: bool) -> str | None:
    text = _blank(raw)
    if text is None:
        return None
    if re.fullmatch(rf"[A-Za-z]{{{low},{high}}}", text) is None:
        raise AppError(400, "invalid_parameter", message, name)
    return text.upper() if upper else text


def _season_type(raw: str | None) -> str | None:
    text = _blank(raw)
    if text is None:
        return None
    value = text.upper()
    if value not in {"REG", "POST"}:
        raise AppError(400, "invalid_parameter", "season_type must be REG or POST", "season_type")
    return value


def _int_text(name: str, raw: str | None, low: int, high: int, message: str) -> str | None:
    text = _blank(raw)
    if text is None:
        return None
    if re.fullmatch(r"\d{1,10}", text) is None:
        raise AppError(400, "invalid_parameter", message, name)
    value = int(text)
    if value < low or value > high:
        raise AppError(400, "invalid_parameter", message, name)
    return str(value)


def _limit(raw: str | None) -> int:
    parsed = _int_text("limit", raw, 1, 500, "limit must be an integer from 1 to 500")
    if parsed is None:
        return 50
    return int(parsed)


def _offset(raw: str | None) -> int:
    message = "offset must be an integer greater than or equal to 0"
    text = _blank(raw)
    if text is None:
        return 0
    if re.fullmatch(r"\d{1,10}", text) is None:
        raise AppError(400, "invalid_parameter", message, "offset")
    value = int(text)
    if value > _OFFSET_MAX:
        raise AppError(400, "invalid_parameter", message, "offset")
    return value


def _sort(raw: str | None, resource: Resource) -> str:
    text = _blank(raw)
    if text is None:
        return resource.default_sort
    if text not in resource.sorts:
        choices = ", ".join(resource.sorts)
        raise AppError(400, "invalid_parameter", f"sort must be one of: {choices}", "sort")
    return text


def _order(raw: str | None, resource: Resource) -> str:
    text = _blank(raw)
    if text is None:
        return resource.default_order
    value = text.lower()
    if value not in {"asc", "desc"}:
        raise AppError(400, "invalid_parameter", "order must be asc or desc", "order")
    return value
