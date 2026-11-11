export const meta = {
  name: "Seam Finder",
  attribution: { text: "synthetic", links: [] },
  endpoints: ["/api/teams"],
  last_refresh_et: "2026-11-05 12:00:00 ET",
  datasets: [
    { dataset: "teams", finished_at: "2026-11-05 12:00:00 ET" },
    { dataset: "players", finished_at: "2026-11-05 12:00:00 ET" },
    { dataset: "games", finished_at: "2026-11-05 12:00:00 ET" },
    { dataset: "player_week_stats", finished_at: "none" },
  ],
};

export const unavailable = {
  error: { code: "service_unavailable", message: "The database is unavailable." },
};

function page(total: number, rows: Record<string, unknown>[]) {
  return { data: rows, page: { limit: 50, offset: 0, total } };
}

export const teams = page(1, [{ team_abbr: "XX", team_name: "Sample Team" }]);
export const players = page(1, [{ gsis_id: "99-0000001", display_name: "Sample Player" }]);
export const games = page(1, [{ game_id: "2026_01_XX_YY", gameday: "2026-09-01" }]);
export const stats = page(1, [
  { gsis_id: "99-0000001", season: 2026, week: 1, player_display_name: "Sample Athlete", receiving_yards: 10 },
]);
export const emptyStats = page(0, []);
export const loadRuns = page(1, [{ id: 1, dataset: "teams", status: "succeeded", started_at: "2026-11-05T17:00:00+00:00" }]);

export function bodyFor(pathname: string): unknown {
  if (pathname === "/api") return meta;
  if (pathname === "/api/teams") return teams;
  if (pathname === "/api/players") return players;
  if (pathname === "/api/games") return games;
  if (pathname === "/api/player-week-stats") return stats;
  if (pathname === "/api/load-runs") return loadRuns;
  return meta;
}
