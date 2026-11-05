"""Server-rendered pages. Filter, sort, and paging state stays in the URL."""

from pathlib import Path
from urllib.parse import urlencode

from fastapi import Request
from fastapi.templating import Jinja2Templates

from web.attribution import attribution
from web.errors import AppError
from web.params import ListParams
from web.queries import connection, footer
from web.resources import PAGE_LINKS, Resource
from web.serialize import cell_text

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _href(path: str, pairs: list[tuple[str, str]]) -> str:
    kept = [(key, value) for key, value in pairs if value != ""]
    if not kept:
        return path
    return path + "?" + urlencode(kept)


def _filter_pairs(resource: Resource, params: ListParams) -> list[tuple[str, str]]:
    pairs = []
    for item in resource.filters:
        value = params.values.get(item.name, "")
        if value != "":
            pairs.append((item.name, value))
    if params.limit != 50:
        pairs.append(("limit", str(params.limit)))
    return pairs


def _columns(resource: Resource, names: list[str], params: ListParams) -> list[dict]:
    base = _filter_pairs(resource, params)
    columns = []
    for name in names:
        href = None
        if name in resource.sorts:
            if name == params.sort:
                order = "asc" if params.order == "desc" else "desc"
            else:
                order = resource.default_order
            href = _href(resource.page_path, [*base, ("sort", name), ("order", order)])
        columns.append({"key": name, "label": name, "href": href})
    return columns


def _page_href(resource: Resource, params: ListParams, offset: int) -> str:
    pairs = _filter_pairs(resource, params)
    pairs.append(("sort", params.sort))
    pairs.append(("order", params.order))
    if offset > 0:
        pairs.append(("offset", str(offset)))
    return _href(resource.page_path, pairs)


def _fields(resource: Resource, raw, params: ListParams | None) -> list[dict]:
    fields = []
    for item in resource.filters:
        if params is None:
            value = raw.get(item.name, "") if raw is not None else ""
        else:
            value = params.values.get(item.name, "")
        fields.append({"name": item.name, "label": item.label, "value": value})
    return fields


def _base(extra: dict | None = None) -> dict:
    context = {"attribution": attribution(), "last_refresh_et": "none", "datasets": []}
    if extra:
        context.update(extra)
    return context


def load_footer(engine) -> dict:
    try:
        with connection(engine) as conn:
            return footer(conn)
    except AppError:
        return {"last_refresh_et": "none", "datasets": []}


def render_home(request: Request, footer_data: dict, *, status_code: int = 200):
    context = _base(footer_data)
    context.update({"title": "Seam Finder", "pages": PAGE_LINKS})
    return TEMPLATES.TemplateResponse(request, "home.html", context, status_code=status_code)


def render_table(
    request: Request,
    resource: Resource,
    *,
    params: ListParams | None,
    rows: list[dict],
    names: list[str],
    total: int,
    error: str | None,
    status_code: int,
    footer_data: dict,
):
    active = params
    if active is None:
        active = ListParams(50, 0, resource.default_sort, resource.default_order, {})
    if total == 0 or error:
        start, end = 0, 0
    else:
        start = active.offset + 1
        end = active.offset + len(rows)
    next_href = None
    prev_href = None
    if error is None and active.offset + active.limit < total:
        next_href = _page_href(resource, active, active.offset + active.limit)
    if error is None and active.offset > 0:
        prev_href = _page_href(resource, active, max(0, active.offset - active.limit))
    context = _base(footer_data)
    context.update(
        {
            "title": resource.title,
            "action": resource.page_path,
            "fields": _fields(resource, request.query_params, params),
            "sort": resource.default_sort if params is None else params.sort,
            "order": resource.default_order if params is None else params.order,
            "columns": _columns(resource, names, active) if error is None else [
                {"key": name, "label": name, "href": None} for name in names
            ],
            "rows": [{key: cell_text(row.get(key)) for key in names} for row in rows],
            "error": error,
            "range_start": start,
            "range_end": end,
            "total": total,
            "next_href": next_href,
            "prev_href": prev_href,
        }
    )
    return TEMPLATES.TemplateResponse(request, "table.html", context, status_code=status_code)


def render_message(request: Request, message: str, status_code: int, footer_data: dict):
    context = _base(footer_data)
    context.update({"title": "Seam Finder", "message": message})
    return TEMPLATES.TemplateResponse(request, "message.html", context, status_code=status_code)
