import type { Resource } from "./resources";

export type ValueKind =
  | "text"
  | "identifier"
  | "boolean"
  | "date"
  | "timestamp"
  | "integer"
  | "year"
  | "points"
  | "line"
  | "percent";

export type PageFilterKind = "text" | "range" | "multi";

export type ColumnMeta = {
  key: string;
  label: string;
  kind: ValueKind;
  filter: PageFilterKind;
  width: number;
};

const MULTI = new Set([
  "latest_team",
  "position",
  "position_group",
  "away_team",
  "home_team",
  "team",
  "opponent_team",
]);

const POINTS = new Set(["fantasy_points", "fantasy_points_ppr"]);
const LINES = new Set(["spread_line", "total_line"]);
const PERCENT = new Set(["target_share"]);
const YEARS = new Set(["season", "week", "rookie_season", "last_season", "draft_year", "years_of_experience"]);
const BOOLEANS = new Set(["is_stub", "overtime"]);
const DATES = new Set(["birth_date", "gameday"]);
const TIMESTAMPS = new Set(["loaded_at", "started_at", "finished_at"]);
const IDENTIFIERS = new Set([
  "team_abbr",
  "team_id",
  "gsis_id",
  "game_id",
  "old_game_id",
  "pfr",
  "espn",
  "pfr_id",
  "espn_id",
  "pff_id",
  "nfl_id",
  "esb_id",
  "otc_id",
  "id",
  "run_group",
]);

const INTEGERS = new Set([
  "height",
  "weight",
  "draft_round",
  "draft_pick",
  "away_score",
  "home_score",
  "result",
  "total",
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
  "special_teams_tds",
  "rows_read",
  "rows_upserted",
  "rows_deleted",
  "rows_skipped",
]);

const LABELS: Record<string, string> = {
  team_abbr: "Team abbreviation",
  team_name: "Team name",
  team_nick: "Team nickname",
  team_conf: "Conference",
  team_division: "Division",
  team_id: "Team id",
  team_color: "Team color",
  team_color2: "Team color 2",
  loaded_at: "Loaded at",
  display_name: "Display name",
  gsis_id: "gsis_id",
  first_name: "First name",
  last_name: "Last name",
  position: "Position",
  position_group: "Position group",
  birth_date: "Birth date",
  height: "Height",
  weight: "Weight",
  college_name: "College name",
  rookie_season: "Rookie season",
  last_season: "Last season",
  team: "Team",
  latest_team: "Latest team",
  status: "Status",
  years_of_experience: "Years of experience",
  draft_year: "Draft year",
  draft_round: "Draft round",
  draft_pick: "Draft pick",
  draft_team: "Draft team",
  pfr_id: "pfr_id",
  espn_id: "espn_id",
  pff_id: "pff_id",
  nfl_id: "nfl_id",
  esb_id: "esb_id",
  otc_id: "otc_id",
  is_stub: "Stub",
  game_id: "game_id",
  season: "Season",
  game_type: "Game type",
  season_type: "Season type",
  week: "Week",
  gameday: "Gameday",
  weekday: "Weekday",
  gametime: "Gametime",
  away_team: "Away team",
  home_team: "Home team",
  away_score: "Away score",
  home_score: "Home score",
  result: "Result",
  total: "Total",
  overtime: "Overtime",
  location: "Location",
  roof: "Roof",
  surface: "Surface",
  stadium: "Stadium",
  spread_line: "Spread line",
  total_line: "Total line",
  old_game_id: "Old game_id",
  pfr: "pfr",
  espn: "espn",
  player_display_name: "Player display name",
  opponent_team: "Opponent team",
  completions: "Completions",
  attempts: "Attempts",
  passing_yards: "Passing yards",
  passing_tds: "Passing touchdowns",
  passing_interceptions: "Passing interceptions",
  sacks_suffered: "Sacks suffered",
  sack_fumbles_lost: "Sack fumbles lost",
  passing_2pt_conversions: "Passing two-point conversions",
  carries: "Carries",
  rushing_yards: "Rushing yards",
  rushing_tds: "Rushing touchdowns",
  rushing_fumbles_lost: "Rushing fumbles lost",
  rushing_2pt_conversions: "Rushing two-point conversions",
  receptions: "Receptions",
  targets: "Targets",
  receiving_yards: "Receiving yards",
  receiving_tds: "Receiving touchdowns",
  receiving_fumbles_lost: "Receiving fumbles lost",
  receiving_2pt_conversions: "Receiving two-point conversions",
  target_share: "Target share",
  special_teams_tds: "Special teams touchdowns",
  fantasy_points: "Standard scoring",
  fantasy_points_ppr: "PPR",
  id: "Load run id",
  run_group: "Run group",
  dataset: "Dataset",
  trigger: "Trigger",
  started_at: "Started at",
  finished_at: "Finished at",
  source_url: "Source URL",
  source_version: "Source version",
  rows_read: "Rows read",
  rows_upserted: "Rows upserted",
  rows_deleted: "Rows deleted",
  rows_skipped: "Rows skipped",
  notes: "Notes",
  error: "Error",
};

export function columnLabel(key: string): string {
  return LABELS[key] ?? key.replaceAll("_", " ");
}

export function initialWidth(key: string): number {
  if (key === "notes" || key === "error" || key.includes("name")) return 240;
  return 160;
}

export function valueKind(key: string): ValueKind {
  if (POINTS.has(key)) return "points";
  if (LINES.has(key)) return "line";
  if (PERCENT.has(key)) return "percent";
  if (YEARS.has(key)) return "year";
  if (INTEGERS.has(key)) return "integer";
  if (BOOLEANS.has(key)) return "boolean";
  if (DATES.has(key)) return "date";
  if (TIMESTAMPS.has(key)) return "timestamp";
  if (IDENTIFIERS.has(key)) return "identifier";
  return "text";
}

/** Page-column kinds. Dataset filters in resources.ts are a separate allowlist. */
export function filterKind(key: string): PageFilterKind {
  if (MULTI.has(key)) return "multi";
  const kind = valueKind(key);
  if (kind === "integer" || kind === "year" || kind === "points" || kind === "line" || kind === "percent") return "range";
  return "text";
}

export function columnMeta(key: string): ColumnMeta {
  return {
    key,
    label: columnLabel(key),
    kind: valueKind(key),
    filter: filterKind(key),
    width: initialWidth(key),
  };
}

export function resourceColumns(resource: Resource): ColumnMeta[] {
  return resource.columns.map((key) => columnMeta(key));
}

export function columnMap(resource: Resource): Map<string, ColumnMeta> {
  return new Map(resourceColumns(resource).map((meta) => [meta.key, meta]));
}

export function isNumericKind(kind: ValueKind): boolean {
  return kind === "integer" || kind === "year" || kind === "points" || kind === "line" || kind === "percent";
}

export function clampWidth(value: number): number {
  return Math.min(480, Math.max(96, Math.round(value)));
}
