# Glossary

| Term | Definition | Code / data name |
|---|---|---|
| nflverse | Open-source project publishing free NFL data files and loader libraries. | `nflverse-data` releases |
| nflverse-data release | A GitHub release in nflverse/nflverse-data holding one dataset's files (parquet, CSV) and a `timestamp.json`. | e.g. `stats_player`, `schedules` |
| nflreadpy | nflverse's Python loader library (MIT); allowed fallback, not the primary path. | `nflreadpy` |
| gsis_id | NFL player ID used by nflverse; our player key. Called `player_id` in the nflverse stats file. | `players.gsis_id`, `player_week_stats.gsis_id` |
| team abbreviation | Short team code; our team key. Includes historical codes (OAK, SD, STL). | `team_abbr`; `team`, `home_team`, `away_team`, `opponent_team` |
| game_id | nflverse game key, `{season}_{week}_{away}_{home}`. | `games.game_id` |
| season | NFL season year it starts in (the 2025 season's playoffs are in early 2026). | `season` |
| read-only role | The Postgres login the web app uses; it can only `SELECT`. Its name is set in the `READONLY_ROLE` Actions variable. | `READONLY_ROLE` |
| cold start | The wait (about a minute) when a sleeping Render free instance gets its first request. | n/a |
| secret | A credential (DB URL, key, token) stored only in GitHub Actions secrets or Render environment variables, never in the repo. | `DATABASE_URL` |
| week | Week number within a season; postseason weeks continue after the last regular-season week. | `week` |
| season type | REG (regular season) or POST (postseason). | `season_type` |
| game type | nflverse's finer game label: REG, WC, DIV, CON, SB. | `games.game_type` |
| standard scoring | Fantasy points with no points per reception, as computed by nflverse. | `fantasy_points` |
| PPR | Points per reception: standard scoring plus 1 point per catch, as computed by nflverse. | `fantasy_points_ppr` |
| placeholder row | A stats-file row named "Team" with no player ID; skipped by the loader. | `player_id IS NULL` in source |
| natural key | The source's own unique key for a row, used for upsert. | PKs in data-dictionary.md |
| upsert | Insert a row, or update it if its natural key already exists. | `INSERT ... ON CONFLICT DO UPDATE` |
| load run | One loader pass over one dataset (and season), recorded in `load_runs`. | `load_runs` |
| source version | The release's `last_updated` value at load time. | `load_runs.source_version` |
| refresh | A scheduled or manual load run of the current season plus teams and players. | `.github/workflows/refresh.yml` |
| backfill | A manual load run for a list of past seasons. | `workflow_dispatch` input `seasons` |
| attribution | The CC BY 4.0 credit line shown on every page. | page footer, `GET /api` |
| cold start | Wait while a spun-down free service starts again on the first request. | Render free web service |
| replacement level | Value of a freely available player at a position; used in part 3, not part 1. | (future) |
| DFS | Daily fantasy sports: pick a lineup under a salary cap for one slate; part 4, not part 1. | (future) |
| slate | The set of games one DFS contest covers; part 4, not part 1. | (future) |
