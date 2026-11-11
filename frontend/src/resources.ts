import type { Row, Search } from "./api";

export type DatasetFilterKind = "season" | "week" | "season_type" | "team" | "position" | "q" | "fold" | "exact";

export type FilterField = { name: string; label: string; kind: DatasetFilterKind };

export type Resource = {
  apiPath: string;
  pagePath: string;
  title: string;
  filters: FilterField[];
  columns: string[];
  sorts: string[];
  defaultSort: string;
  defaultOrder: "asc" | "desc";
  rowId: (row: Row) => string;
};

const teamColumns = [
  "team_abbr",
  "team_name",
  "team_nick",
  "team_conf",
  "team_division",
  "team_id",
  "team_color",
  "team_color2",
  "loaded_at",
];

const playerColumns = [
  "display_name",
  "gsis_id",
  "first_name",
  "last_name",
  "position",
  "position_group",
  "birth_date",
  "height",
  "weight",
  "college_name",
  "rookie_season",
  "last_season",
  "latest_team",
  "status",
  "years_of_experience",
  "draft_year",
  "draft_round",
  "draft_pick",
  "draft_team",
  "pfr_id",
  "espn_id",
  "pff_id",
  "nfl_id",
  "esb_id",
  "otc_id",
  "is_stub",
  "loaded_at",
];

const gameColumns = [
  "game_id",
  "season",
  "game_type",
  "season_type",
  "week",
  "gameday",
  "weekday",
  "gametime",
  "away_team",
  "home_team",
  "away_score",
  "home_score",
  "result",
  "total",
  "overtime",
  "location",
  "roof",
  "surface",
  "stadium",
  "spread_line",
  "total_line",
  "old_game_id",
  "pfr",
  "espn",
  "loaded_at",
];

const statColumns = [
  "player_display_name",
  "gsis_id",
  "season",
  "week",
  "season_type",
  "game_id",
  "team",
  "opponent_team",
  "position",
  "position_group",
  "completions",
  "attempts",
  "passing_yards",
  "passing_tds",
  "passing_interceptions",
  "sacks_suffered",
  "sack_fumbles_lost",
  "passing_2pt_conversions",
  "carries",
  "rushing_yards",
  "rushing_tds",
  "rushing_fumbles_lost",
  "rushing_2pt_conversions",
  "receptions",
  "targets",
  "receiving_yards",
  "receiving_tds",
  "receiving_fumbles_lost",
  "receiving_2pt_conversions",
  "target_share",
  "special_teams_tds",
  "fantasy_points",
  "fantasy_points_ppr",
  "loaded_at",
];

const loadRunColumns = [
  "id",
  "run_group",
  "dataset",
  "season",
  "status",
  "trigger",
  "started_at",
  "finished_at",
  "source_url",
  "source_version",
  "rows_read",
  "rows_upserted",
  "rows_deleted",
  "rows_skipped",
  "notes",
  "error",
];

function textId(row: Row, key: string): string {
  const value = row[key];
  return value === null || value === undefined ? "" : String(value);
}

export const teams: Resource = {
  apiPath: "/api/teams",
  pagePath: "/teams",
  title: "Teams",
  filters: [
    { name: "conf", label: "Conference", kind: "fold" },
    { name: "division", label: "Division", kind: "fold" },
  ],
  columns: teamColumns,
  sorts: ["team_abbr", "team_name"],
  defaultSort: "team_abbr",
  defaultOrder: "asc",
  rowId: (row) => textId(row, "team_abbr"),
};

export const players: Resource = {
  apiPath: "/api/players",
  pagePath: "/players",
  title: "Players",
  filters: [
    { name: "q", label: "Name", kind: "q" },
    { name: "position", label: "Position", kind: "position" },
    { name: "team", label: "Team", kind: "team" },
    { name: "status", label: "Status", kind: "fold" },
  ],
  columns: playerColumns,
  sorts: ["display_name", "position", "latest_team", "rookie_season"],
  defaultSort: "display_name",
  defaultOrder: "asc",
  rowId: (row) => textId(row, "gsis_id"),
};

export const games: Resource = {
  apiPath: "/api/games",
  pagePath: "/games",
  title: "Games",
  filters: [
    { name: "season", label: "Season", kind: "season" },
    { name: "week", label: "Week", kind: "week" },
    { name: "season_type", label: "Season type", kind: "season_type" },
    { name: "team", label: "Team", kind: "team" },
  ],
  columns: gameColumns,
  sorts: ["gameday", "week", "season"],
  defaultSort: "gameday",
  defaultOrder: "asc",
  rowId: (row) => textId(row, "game_id"),
};

export const stats: Resource = {
  apiPath: "/api/player-week-stats",
  pagePath: "/stats",
  title: "Player week stats",
  filters: [
    { name: "season", label: "Season", kind: "season" },
    { name: "week", label: "Week", kind: "week" },
    { name: "season_type", label: "Season type", kind: "season_type" },
    { name: "team", label: "Team", kind: "team" },
    { name: "position", label: "Position", kind: "position" },
    { name: "player", label: "Player", kind: "exact" },
    { name: "game_id", label: "Game", kind: "exact" },
  ],
  columns: statColumns,
  sorts: [
    "fantasy_points_ppr",
    "fantasy_points",
    "passing_yards",
    "rushing_yards",
    "receiving_yards",
    "receptions",
    "targets",
    "week",
    "season",
  ],
  defaultSort: "fantasy_points_ppr",
  defaultOrder: "desc",
  rowId: (row) => `${textId(row, "gsis_id")}-${textId(row, "season")}-${textId(row, "week")}`,
};

export const loadRuns: Resource = {
  apiPath: "/api/load-runs",
  pagePath: "/load-runs",
  title: "Load runs",
  filters: [
    { name: "dataset", label: "Dataset", kind: "fold" },
    { name: "status", label: "Status", kind: "fold" },
    { name: "season", label: "Season", kind: "season" },
  ],
  columns: loadRunColumns,
  sorts: ["started_at"],
  defaultSort: "started_at",
  defaultOrder: "desc",
  rowId: (row) => textId(row, "id"),
};

export const resources = [teams, players, games, stats, loadRuns];

export const pageLinks = [
  { href: "/teams", label: "Teams" },
  { href: "/players", label: "Players" },
  { href: "/games", label: "Games" },
  { href: "/stats", label: "Player week stats" },
  { href: "/load-runs", label: "Load runs" },
] as const;

export function toHref(path: string, search?: Search): string {
  if (!search) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) {
    if (value !== "") params.append(key, value);
  }
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

export function parseSearch(search: Record<string, unknown>): Search {
  const result: Search = {};
  for (const [key, value] of Object.entries(search)) {
    if (typeof value === "string") result[key] = value;
    else if (typeof value === "number" || typeof value === "boolean") result[key] = String(value);
  }
  return result;
}

export function keptFilters(search: Search, resource: Resource): Search {
  const next: Search = {};
  for (const field of resource.filters) {
    const value = search[field.name];
    if (value) next[field.name] = value;
  }
  if (search.limit && search.limit !== "50") next.limit = search.limit;
  return next;
}

export function currentSort(search: Search, resource: Resource): { sort: string; order: string } {
  return {
    sort: search.sort || resource.defaultSort,
    order: search.order || resource.defaultOrder,
  };
}

export function sortSearch(search: Search, resource: Resource, column: string): Search {
  const current = currentSort(search, resource);
  const order = column === current.sort ? (current.order === "desc" ? "asc" : "desc") : resource.defaultOrder;
  return { ...keptFilters(search, resource), sort: column, order };
}

export function formSearch(search: Search, resource: Resource): Search {
  const current = currentSort(search, resource);
  return { ...keptFilters(search, resource), sort: current.sort, order: current.order };
}

export function pagerSearch(search: Search, resource: Resource, offset: number): Search {
  const current = currentSort(search, resource);
  const next: Search = { ...keptFilters(search, resource), sort: current.sort, order: current.order };
  if (offset > 0) next.offset = String(offset);
  return next;
}
