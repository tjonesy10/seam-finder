Status: READY (2026-11-05). Open questions answered. Pass A built; Pass B handed off.

# F001: Data prototype (Part 1)

Related: [PRD](../../prd.md), [architecture](../../architecture.md), [data dictionary](../../data-dictionary.md), [glossary](../../GLOSSARY.md).

## Problem / job to be done

Get nflverse players, teams, games, and player weekly stats into Postgres, keep them refreshed, and show them through read-only JSON APIs and simple web pages at a public URL, on free tiers, with attribution. Every later part (projections, valuation, DFS, live data) builds on these tables and keys.

## Requirements

- **R1** Load teams, players, games, and player week stats from nflverse for seasons 2015-2026, including postseason weeks.
- **R2** Loads are idempotent and match the source: upsert on the natural key and delete rows the source dropped.
- **R3** A failed load leaves the previous data in place, is recorded as failed, and fails the run.
- **R4** Every load run is recorded in `load_runs` and readable through the API.
- **R5** A daily scheduled refresh plus a manual refresh with a seasons input.
- **R6** Read-only JSON list and get-by-key endpoints for each table, with filters, sort, and pagination.
- **R7** Bad input returns a consistent error shape (400 or 404), never a stack trace.
- **R8** A root endpoint with attribution and a health endpoint that reports database status and last refresh.
- **R9** A server-rendered HTML page per table with filter, sort, and paging, all state in the URL.
- **R10** nflverse attribution and last refresh time on every page; no logos, headshots, or external images.
- **R11** The web app reads with a database role that can only `SELECT`.
- **R12** No secrets in the repo or in workflow logs.
- **R13** The site runs at a public URL on free tiers.

## User stories

1. As Cosmo, I want the four datasets loaded for 2015-2026, so that later parts start from the same data. (PRD US1)
2. As Cosmo, I want a daily refresh with a record of each load run, so that data stays current and I can see when it broke. (US2)
3. As an engineer, I want filtered, paginated JSON endpoints, so that I can read the data without DB access. (US3)
4. As a viewer, I want a page per table with filter, sort, and paging, so that I can look things up. (US4)
5. As Cosmo, I want it at a public URL for $0, so that I can share it. (US5)

## Observable behavior

### Loader (CLI)

Input: `python -m loader --seasons 2015-2026 [--datasets teams,players,games,player_week_stats] [--trigger local|manual|schedule]`. Default: current season, all four datasets. Current season = this calendar year from March on, last year in January-February (so playoff weeks land in the right season). `DATABASE_URL` from the environment. `--trigger` defaults to `local`; the refresh workflow always passes `schedule` or `manual`.

Output: tables in [data-dictionary.md](../../data-dictionary.md) filled; one `load_runs` row per dataset+season; exit code 0 if all succeeded, 1 if any failed.

Behavior (rules in [ADR 0002](../../adr/0002-nflverse-load-and-refresh.md)):
- Runs `alembic upgrade head` first in the workflow (separate step).
- Order: teams, players, games, player_week_stats.
- Per dataset+season, one transaction: upsert on the natural key, then delete that season's rows not in the batch. Teams and players are upsert-only.
- Skips stats placeholder rows (null `player_id`), counted in `rows_skipped`.
- Creates a stub player (`is_stub = true`) when a stats row names a gsis_id missing from players; counted in `notes`. The loader never derives `first_name` and `last_name` by splitting `display_name` (it breaks on suffixes like 'Jr.' and multi-word surnames).
- Derives `games.season_type`: `REG` if `game_type = REG`, else `POST`.
- Edge cases: unplayed games load with null scores; a season with no stats file yet (e.g. before week 1) is recorded `failed` with "source file not found", other datasets continue; source column missing or key duplicated → that dataset+season `failed`, nothing written for it; download retried 3 times.
- Validation ranges: `season` 1999-2100, `week` 1-22 (same bounds as the API filters). Rows outside fail validation for that dataset+season.

### Refresh workflow

`.github/workflows/refresh.yml`:
- Triggers: `schedule` cron `0 11 * * *` (daily) and `workflow_dispatch` with input `seasons` (string, e.g. `2024` or `2015-2026`, default current season).
- Steps: checkout, set up Python, install, `alembic upgrade head`, run loader with `--trigger schedule|manual`.
- Secret: `DATABASE_URL` (loader role). Nothing else.
- A failed load makes the job fail.

### HTTP API

Base path `/api`. JSON only, UTF-8. All endpoints are `GET`. Responses carry `Cache-Control: public, max-age=300`.

**Common list parameters**

| Param | Type | Default | Rule |
|---|---|---|---|
| `limit` | int | 50 | 1-500 |
| `offset` | int | 0 | >= 0 |
| `sort` | string | per endpoint | must be in the endpoint's sort list |
| `order` | `asc` \| `desc` | per endpoint | |

Filter value rules: `season` int 1999-2100; `week` int 1-22; `season_type` `REG` or `POST` (case-insensitive); `team` 2-3 letters (case-insensitive, matched to `team_abbr`); `position` 1-5 letters (case-insensitive). A valid filter that matches nothing returns 200 with an empty list. Unknown query parameters return 400.

**List response**

```json
{
  "data": [ { "...": "row object" } ],
  "page": { "limit": 50, "offset": 0, "total": 1234 }
}
```

**Error response** (every non-2xx)

```json
{ "error": { "code": "invalid_parameter", "message": "week must be an integer from 1 to 22", "param": "week" } }
```

| HTTP | `code` | When |
|---|---|---|
| 400 | `invalid_parameter` | bad type, range, enum, or sort field (`param` set) |
| 400 | `unknown_parameter` | query param not accepted by the endpoint (`param` set) |
| 404 | `not_found` | unknown key in a path, or unknown path (`param` omitted) |
| 503 | `service_unavailable` | database unreachable |
| 500 | `internal_error` | anything else; no stack trace in the body |

FastAPI's default 422 validation response is replaced by the 400 shape above.

**Endpoints**

| Path | Filters | Sort fields (default first) | Row object |
|---|---|---|---|
| `GET /api` | none | n/a | `{ "name", "attribution": { "text", "links": [ { "label", "url" } ] }, "endpoints": [ "/api/teams", ... ] }` |
| `GET /api/health` | none | n/a | `{ "status": "ok", "database": "ok", "last_refresh": { "dataset", "season", "finished_at", "source_version" } \| null }`; 503 error shape if DB down |
| `GET /api/teams` | `conf`, `division` | `team_abbr` asc, `team_name` | `teams` columns |
| `GET /api/teams/{team_abbr}` | none | n/a | `{ "data": team }` |
| `GET /api/players` | `q` (2-50 chars, case-insensitive substring of display_name), `position`, `team` (latest_team), `status` | `display_name` asc, `position`, `latest_team`, `rookie_season` | `players` columns |
| `GET /api/players/{gsis_id}` | none | n/a | `{ "data": player }` |
| `GET /api/games` | `season`, `week`, `season_type`, `team` (home or away) | `gameday` asc (then `game_id`), `week`, `season` | `games` columns |
| `GET /api/games/{game_id}` | none | n/a | `{ "data": game }` |
| `GET /api/player-week-stats` | `season`, `week`, `season_type`, `team`, `position`, `player` (gsis_id), `game_id` | `fantasy_points_ppr` desc, `fantasy_points`, `passing_yards`, `rushing_yards`, `receiving_yards`, `receptions`, `targets`, `week`, `season` | `player_week_stats` columns plus `player_display_name` (joined from players) |
| `GET /api/load-runs` | `dataset`, `status`, `season` | `started_at` desc | `load_runs` columns |

Ties in any sort are broken by the table's primary key, so pages are stable. Dates are ISO 8601 strings (`2025-09-04`); timestamps are ISO 8601 with offset; numerics are JSON numbers; nulls are `null`. `loaded_at` is included on data rows.

Example row, `GET /api/player-week-stats?player=00-0036900&season=2024&week=10`:

```json
{ "gsis_id": "00-0036900", "player_display_name": "Ja'Marr Chase", "season": 2024, "week": 10, "season_type": "REG",
  "game_id": "2024_10_CIN_BAL", "team": "CIN", "opponent_team": "BAL", "position": "WR",
  "receptions": 11, "targets": 17, "receiving_yards": 264, "receiving_tds": 3,
  "fantasy_points": 44.4, "fantasy_points_ppr": 55.4, "...": "other columns" }
```

### Web pages

Server-rendered HTML from the same FastAPI app, using the same query functions and the same parameters as the API.

| Path | Table | Filters shown |
|---|---|---|
| `/` | links to each page + last refresh per dataset | none |
| `/teams` | teams | conf, division |
| `/players` | players | name search, position, team, status |
| `/games` | games | season, week, season type, team |
| `/stats` | player week stats | season, week, season type, team, position, player |
| `/load-runs` | load runs | dataset, status, season |

- Filters are a `GET` form; the URL holds all state, so links are shareable.
- Clicking a sortable column header sorts by it; clicking again flips the order.
- Previous/next links and "rows X-Y of N". Page size 50.
- Invalid parameters render the page with the error message and HTTP 400.
- Footer on every page: the attribution text from [ADR 0002](../../adr/0002-nflverse-load-and-refresh.md) with both links, plus "Last refresh: {finished_at in ET}".
- No logos, headshots, or external images. No JavaScript required.

### Security and config

- The web app connects with a read-only role (`SELECT` only).
- Config only from environment variables; `.env` git-ignored; `.env.example` has placeholders only.

### Web app layout and deploy (Pass B)

- Code lives in a new `web/` package next to `loader/`; the ASGI app is `web.main:app`. Add `web` to `[tool.setuptools] packages` and the runtime dependencies listed below to `pyproject.toml`.
- Add a `.python-version` file containing `3.12` so Render builds with the same Python as CI.
- Config: `DATABASE_URL` only (the read-only role's URL). Accept `postgres://` and `postgresql://` and normalize to the psycopg driver the same way the loader does. The web app does not read `READONLY_ROLE`.
- Render settings (the owner provisions the service; nothing Render-specific is committed): runtime Python, free instance, branch `main`, build `pip install .`, start `uvicorn web.main:app --host 0.0.0.0 --port $PORT`, health check path `/api/health`.
- CI: extend `ruff check` to `web`. AT18 runs in CI by creating a login role with only the grants `loader/grants.py` applies, then connecting as it.
- Read-only role in production: created by the owner with SQL in Neon's SQL editor (not the Neon console, which adds `neon_superuser`), named in the `READONLY_ROLE` Actions variable so the next refresh's migrate step grants it `SELECT`.

## Secrets rule

The repo is public. No database URLs, passwords, API keys or tokens are ever committed, including in docs, examples, tests, fixtures or workflow files. The loader's `DATABASE_URL` lives only as a GitHub Actions secret; the web app's read-only `DATABASE_URL` lives only as a Render environment variable. `.env` is git-ignored and `.env.example` holds placeholders only. Workflow logs must not echo secrets.

## Acceptance tests

Tests run against a throwaway Postgres (CI service container). Fixtures are small parquet files cut from real nflverse files and committed under `tests/fixtures/`, plus one optional live test marked `network`.

Load
- **AT1 (R1, R2) Idempotent load.** Given an empty DB and fixture files, when the loader runs twice, then every table's contents (all columns except `loaded_at`) are identical after run 1 and run 2, and run 2 records `rows_deleted = 0`.
- **AT2 (R1, R2) Row counts match source.** Given a load of a season, then `games` rows for that season equal the source rows for that season, and `player_week_stats` rows equal source rows minus rows with null `player_id`; teams and players equal their source row counts plus stub players. Tolerance: exact against the file that was loaded. In the `network` test against a fresh download of the current season, within 1% (the source may update between download and check).
- **AT3 (R1) Known player-week values.** Given 2024 is loaded, when reading gsis_id `00-0036900` (Ja'Marr Chase), season 2024, week 10, then `game_id = 2024_10_CIN_BAL`, `team = CIN`, `opponent_team = BAL`, receptions 11, targets 17, receiving_yards 264, receiving_tds 3, fantasy_points 44.4, fantasy_points_ppr 55.4.
- **AT4 (R1) Second known row and a game.** Given 2025 is loaded, then gsis_id `00-0034857` (Josh Allen) 2025 week 1 has team BUF, opponent BAL, passing_yards 394, rushing_yards 30, rushing_tds 2, fantasy_points 38.76; and game `2025_01_DAL_PHI` has gameday 2025-09-04, away DAL 20, home PHI 24, result 4, total 44, season_type REG.
- **AT5 (R2) Removed source rows are deleted.** Given a season is loaded, when the loader runs on a fixture with one stats row removed, then that row is gone and `rows_deleted = 1`.
- **AT6 (R1) Placeholder rows skipped.** Given a stats fixture containing null-`player_id` "Team" rows, then none are loaded and `rows_skipped` equals their count.
- **AT7 (R3) Failed load keeps old data.** Given a season is loaded, when the loader runs on a fixture missing a required column, then the tables are unchanged, the `load_runs` row has status `failed` with an error message, and the exit code is 1.
- **AT8 (R3, R4) load_runs recorded.** After any run, each dataset+season has a row with status `succeeded` or `failed`, `started_at`, `finished_at`, `source_url`, `source_version`, row counts, and the trigger passed on the command line.

API
- **AT9 (R8, R10) Root and attribution.** When `GET /api`, then 200 and `attribution.text` matches the ADR 0002 text with both links.
- **AT10 (R8) Health.** Given the DB is up, `GET /api/health` returns 200 with `database = ok`. Given the DB is unreachable, it returns 503 with code `service_unavailable`.
- **AT11 (R6) Teams.** `GET /api/teams` returns all teams; `?conf=AFC` returns only AFC teams; `GET /api/teams/CIN` returns CIN; `GET /api/teams/XYZ` returns 404 `not_found`.
- **AT12 (R6, R7) Players.** `?q=chase` includes 00-0036900; `?position=WR&team=CIN` returns only WRs with latest_team CIN; `GET /api/players/00-0036900` returns him; `GET /api/players/00-0000000` returns 404; `?q=a` returns 400 (`param = q`).
- **AT13 (R6) Games.** `?season=2025&week=1` returns only 2025 week 1 games including `2025_01_DAL_PHI`; `?team=PHI&season=2025` returns only games with PHI home or away; `?season_type=post&season=2024` returns only POST games; `GET /api/games/2025_01_DAL_PHI` returns it; `GET /api/games/nope` returns 404.
- **AT14 (R6) Player week stats.** `?season=2024&week=10&team=CIN` includes Chase's row; `?player=00-0036900&season=2024` returns only his rows ordered by `fantasy_points_ppr` desc; `?sort=receiving_yards&order=desc&season=2024&week=10` puts the highest receiving_yards first.
- **AT15 (R4, R6) Load runs.** `?status=failed` returns only failed runs, newest first.
- **AT16 (R6, R7) Pagination.** Given more than 50 matching rows, `?limit=50&offset=0` and `?limit=50&offset=50` return disjoint rows with the same `page.total`, and the union equals `?limit=100`. `limit=0`, `limit=501`, `offset=-1` each return 400.
- **AT17 (R7) Bad parameters.** `week=abc`, `week=23`, `season_type=XYZ`, `sort=bogus`, `order=up` each return 400 `invalid_parameter` with `param` set; an unknown param (`?foo=1`) returns 400 `unknown_parameter`; an unknown path returns 404 in the error shape.
- **AT18 (R11) Read-only.** The web app's DB role cannot `INSERT`, `UPDATE`, `DELETE`, or `CREATE` (each raises a permission error).

Pages
- **AT19 (R9) Each table page renders.** `/teams`, `/players`, `/games`, `/stats`, `/load-runs` each return 200 with an HTML table and the filter form listed above.
- **AT20 (R9) Filters, sort, paging on pages.** `/stats?season=2024&week=10&team=CIN` shows Chase's row; clicking the receiving_yards header link reorders by it; the next link shows rows 51-100 and keeps the filters in the URL.
- **AT21 (R7, R9) Bad page params.** `/games?week=abc` returns 400 and shows the error message.
- **AT22 (R10) Attribution visible.** Every page's footer contains the attribution text, links to nflverse-data and the CC BY 4.0 license, and the last refresh time in ET.
- **AT23 (R10) No external images.** No page contains an `<img>` pointing outside the app.

Refresh and repo
- **AT24 (R5) Refresh workflow runs.** Given the `DATABASE_URL` secret is set, when `refresh.yml` is started by hand with `seasons=2024`, then the job succeeds and `load_runs` has new `succeeded` rows with trigger `manual` for teams, players, and 2024 games and stats. The workflow file contains a `schedule` trigger with cron `0 11 * * *`.
- **AT25 (R3, R5) Refresh failure fails the job.** Given a loader failure (e.g. a bad seasons input like `1800`), the job ends failed and `load_runs` records `failed` where a load started.
- **AT26 (R12) No secrets in repo.** A gitleaks scan of the full history finds nothing; no file contains a `postgres://` or `postgresql://` URL with a password; `.env` is in `.gitignore`; `.env.example` holds placeholders only, and no workflow step prints `DATABASE_URL`.

Deploy
- **AT27 (R13) Public URL.** Given the Render service is deployed from `main`, when `GET {public URL}/api/health` and `GET {public URL}/`, then both return 200 (allow about a minute for a cold start) and `/` shows the attribution footer. Checked by hand after deploy; the result goes in TEST_REPORT.md.

## Build passes

Built and handed off as two passes, each its own PR. **Pass A (F001a): schema, migrations, loader, refresh workflow** - AT1-AT8, AT24-AT26. **Pass B (F001b): read API and web pages** - AT9-AT23 (plus AT26 re-checked), then AT27 after the owner deploys. Pass A merged and loaded on 2026-11-05 (AT24 passed).

## Non-goals

Parts 2-5 (projections, valuation, DFS, live data, injuries, salaries), auth, write APIs, live in-game data, datasets beyond the four, logos and headshots, paid hosting, custom domain.

## Allowed dependencies

Runtime: Python 3.12+, `fastapi`, `uvicorn`, `jinja2`, `sqlalchemy` (Core only), `psycopg[binary]` 3, `alembic`, `polars`, `httpx`, `pydantic-settings`.
Dev/CI: `pytest`, `ruff`, gitleaks (CI action).
Fallback only, pinned, if release URLs change: `nflreadpy`.
Not allowed without asking: an ORM layer, pandas, a JS framework or bundler, any paid service.

## Decisions (answered 2026-11-05)

1. Neon and Render free accounts: approved, being set up by the owner.
2. Public, non-commercial site with the nflverse CC BY 4.0 footer credit; no logos or headshots.
3. Seasons 2015-2026.
4. Daily GitHub Actions refresh at 11:00 UTC year-round plus manual workflow_dispatch.
5. Include postseason (POST) weeks.
6. The repo is public.

Open questions: none.

## ADRs

- [ADR 0001: Stack and hosting](../../adr/0001-stack-and-hosting.md)
- [ADR 0002: nflverse source, idempotent load, and refresh](../../adr/0002-nflverse-load-and-refresh.md)
