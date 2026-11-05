"""List endpoints: filters, sort fields, and the pages that share them."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Filter:
    name: str
    label: str
    kind: str


@dataclass(frozen=True)
class Resource:
    slug: str
    api_path: str
    page_path: str
    title: str
    filters: tuple[Filter, ...]
    sorts: tuple[str, ...]
    default_sort: str
    default_order: str
    tie_break: tuple[str, ...]


TEAMS = Resource(
    slug="teams",
    api_path="/api/teams",
    page_path="/teams",
    title="Teams",
    filters=(
        Filter("conf", "Conference", "fold"),
        Filter("division", "Division", "fold"),
    ),
    sorts=("team_abbr", "team_name"),
    default_sort="team_abbr",
    default_order="asc",
    tie_break=("team_abbr",),
)

PLAYERS = Resource(
    slug="players",
    api_path="/api/players",
    page_path="/players",
    title="Players",
    filters=(
        Filter("q", "Name", "q"),
        Filter("position", "Position", "position"),
        Filter("team", "Team", "team"),
        Filter("status", "Status", "fold"),
    ),
    sorts=("display_name", "position", "latest_team", "rookie_season"),
    default_sort="display_name",
    default_order="asc",
    tie_break=("gsis_id",),
)

GAMES = Resource(
    slug="games",
    api_path="/api/games",
    page_path="/games",
    title="Games",
    filters=(
        Filter("season", "Season", "season"),
        Filter("week", "Week", "week"),
        Filter("season_type", "Season type", "season_type"),
        Filter("team", "Team", "team"),
    ),
    sorts=("gameday", "week", "season"),
    default_sort="gameday",
    default_order="asc",
    tie_break=("game_id",),
)

STATS = Resource(
    slug="stats",
    api_path="/api/player-week-stats",
    page_path="/stats",
    title="Player week stats",
    filters=(
        Filter("season", "Season", "season"),
        Filter("week", "Week", "week"),
        Filter("season_type", "Season type", "season_type"),
        Filter("team", "Team", "team"),
        Filter("position", "Position", "position"),
        Filter("player", "Player", "exact"),
        Filter("game_id", "Game", "exact"),
    ),
    sorts=(
        "fantasy_points_ppr",
        "fantasy_points",
        "passing_yards",
        "rushing_yards",
        "receiving_yards",
        "receptions",
        "targets",
        "week",
        "season",
    ),
    default_sort="fantasy_points_ppr",
    default_order="desc",
    tie_break=("gsis_id", "season", "week"),
)

LOAD_RUNS = Resource(
    slug="load-runs",
    api_path="/api/load-runs",
    page_path="/load-runs",
    title="Load runs",
    filters=(
        Filter("dataset", "Dataset", "fold"),
        Filter("status", "Status", "fold"),
        Filter("season", "Season", "season"),
    ),
    sorts=("started_at",),
    default_sort="started_at",
    default_order="desc",
    tie_break=("id",),
)

RESOURCES = (TEAMS, PLAYERS, GAMES, STATS, LOAD_RUNS)

API_ENDPOINTS = tuple(resource.api_path for resource in RESOURCES)

DATASETS = ("teams", "players", "games", "player_week_stats")

PAGE_LINKS = (
    {"href": "/teams", "label": "Teams"},
    {"href": "/players", "label": "Players"},
    {"href": "/games", "label": "Games"},
    {"href": "/stats", "label": "Player week stats"},
    {"href": "/load-runs", "label": "Load runs"},
)
