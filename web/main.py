"""ASGI app. Entrypoint: web.main:app."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from starlette.exceptions import HTTPException as StarletteHTTPException

from loader.url import normalize_database_url
from web.attribution import attribution
from web.errors import AppError, error_body
from web.pages import load_footer, render_home, render_message, render_table
from web.params import parse_resource, reject_unknown
from web.queries import (
    FETCH,
    connection,
    footer,
    get_game,
    get_player,
    get_team,
    latest_refresh,
    output_names,
    ping,
    refresh_payload,
)
from web.resources import API_ENDPOINTS, GAMES, LOAD_RUNS, PLAYERS, RESOURCES, STATS, TEAMS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    database_url: str | None = None


def build_engine(database_url: str | None):
    if database_url is None or database_url.strip() == "":
        return None
    return create_engine(
        normalize_database_url(database_url.strip()),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
    )


def _json(payload, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        payload,
        status_code=status_code,
        media_type="application/json; charset=utf-8",
    )


def _is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def create_app(database_url: str | None = None) -> FastAPI:
    if database_url is None:
        database_url = Settings().database_url
    app = FastAPI(title="Seam Finder", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine = build_engine(database_url)

    @app.middleware("http")
    async def cache_api(request: Request, call_next):
        response = await call_next(request)
        if _is_api(request.url.path):
            response.headers["Cache-Control"] = "public, max-age=300"
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        if _is_api(request.url.path):
            return _json(error_body(exc), exc.status_code)
        return render_message(request, exc.message, exc.status_code, load_footer(request.app.state.engine))

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        if _is_api(request.url.path):
            return _json(
                {"error": {"code": "internal_error", "message": "Something went wrong."}},
                500,
            )
        return render_message(
            request,
            "Something went wrong.",
            500,
            load_footer(request.app.state.engine),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError):
        param = None
        problems = exc.errors()
        if problems:
            loc = problems[0].get("loc") or ()
            if loc:
                param = str(loc[-1])
        error = AppError(400, "invalid_parameter", "invalid parameter", param)
        if _is_api(request.url.path):
            return _json(error_body(error), error.status_code)
        return render_message(request, error.message, error.status_code, load_footer(request.app.state.engine))

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            error = AppError(404, "not_found", "Not found")
        else:
            error = AppError(exc.status_code, "internal_error", "Something went wrong.")
        if _is_api(request.url.path):
            return _json(error_body(error), error.status_code)
        return render_message(request, error.message, error.status_code, load_footer(request.app.state.engine))

    @app.get("/api")
    def api_root(request: Request):
        reject_unknown(request.query_params, set())
        return _json(
            {
                "name": "Seam Finder",
                "attribution": attribution(),
                "endpoints": list(API_ENDPOINTS),
            }
        )

    @app.get("/api/health")
    def api_health(request: Request):
        reject_unknown(request.query_params, set())
        with connection(request.app.state.engine) as conn:
            ping(conn)
            row = latest_refresh(conn)
        return _json({"status": "ok", "database": "ok", "last_refresh": refresh_payload(row)})

    def _list(request: Request, resource):
        params = parse_resource(request.query_params, resource)
        with connection(request.app.state.engine) as conn:
            rows, total = FETCH[resource.slug](conn, params)
        return _json(
            {
                "data": rows,
                "page": {"limit": params.limit, "offset": params.offset, "total": total},
            }
        )

    @app.get("/api/teams")
    def api_teams(request: Request):
        return _list(request, TEAMS)

    @app.get("/api/teams/{team_abbr}")
    def api_team(team_abbr: str, request: Request):
        reject_unknown(request.query_params, set())
        with connection(request.app.state.engine) as conn:
            return _json(get_team(conn, team_abbr))

    @app.get("/api/players")
    def api_players(request: Request):
        return _list(request, PLAYERS)

    @app.get("/api/players/{gsis_id}")
    def api_player(gsis_id: str, request: Request):
        reject_unknown(request.query_params, set())
        with connection(request.app.state.engine) as conn:
            return _json(get_player(conn, gsis_id))

    @app.get("/api/games")
    def api_games(request: Request):
        return _list(request, GAMES)

    @app.get("/api/games/{game_id}")
    def api_game(game_id: str, request: Request):
        reject_unknown(request.query_params, set())
        with connection(request.app.state.engine) as conn:
            return _json(get_game(conn, game_id))

    @app.get("/api/player-week-stats")
    def api_stats(request: Request):
        return _list(request, STATS)

    @app.get("/api/load-runs")
    def api_load_runs(request: Request):
        return _list(request, LOAD_RUNS)

    @app.get("/")
    def home(request: Request):
        reject_unknown(request.query_params, set())
        with connection(request.app.state.engine) as conn:
            footer_data = footer(conn)
        return render_home(request, footer_data)

    for resource in RESOURCES:
        app.add_api_route(resource.page_path, _page_route(resource), methods=["GET"])

    return app


def _page_route(resource):
    def route(request: Request):
        return _page_for(request, resource)

    route.__name__ = f"page_{resource.slug.replace('-', '_')}"
    return route


def _page_for(request: Request, resource):
    try:
        params = parse_resource(request.query_params, resource)
    except AppError as exc:
        return render_table(
            request,
            resource,
            params=None,
            rows=[],
                names=output_names(resource.slug),
            total=0,
            error=exc.message,
            status_code=exc.status_code,
            footer_data=load_footer(request.app.state.engine),
        )
    with connection(request.app.state.engine) as conn:
        rows, total = FETCH[resource.slug](conn, params)
        footer_data = footer(conn)
    return render_table(
        request,
        resource,
        params=params,
        rows=rows,
            names=output_names(resource.slug),
        total=total,
        error=None,
        status_code=200,
        footer_data=footer_data,
    )


app = create_app()
