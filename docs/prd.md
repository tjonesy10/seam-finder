# PRD: Seam Finder, Part 1 (data prototype)

Status: READY (2026-11-05)

## Problem

Seam Finder will do projections, valuation, a DFS optimizer, and live data (parts 2-5). All of those need the same base: clean NFL players, teams, games, and weekly player stats in one database with stable keys. Today the repo has only a README. Cosmo also wants a hosted site he can share that shows the data.

## Goals

1. Load four nflverse datasets into Postgres: players, teams, games (schedule + results), and player weekly stats. See [data-dictionary.md](data-dictionary.md).
2. Keep the data current with a scheduled refresh, and record every load run.
3. Serve the data through read-only JSON APIs with filters and pagination.
4. Show each table on a web page with filter, sort, and paginate.
5. Host it online on free tiers, with nflverse attribution on every page.
6. Use stable keys (gsis_id, team_abbr, game_id) and a season/week grain so parts 2-5 can add tables without reshaping these.

## Non-goals

- Parts 2-5: projections, simulations, valuation (replacement level), DFS optimizer, salaries, slates, live injuries or live scoring.
- Auth, user accounts, saved settings.
- Write APIs of any kind. The only writer is the loader.
- Live (in-game) data. Data is as fresh as the last refresh.
- Datasets beyond the four above (play-by-play, rosters, snap counts, FTN charting, injuries).
- Team logos and player headshots on the site (see [ADR 0002](adr/0002-nflverse-load-and-refresh.md)).
- Paid hosting.

## Users

- Cosmo (owner): loads and checks data, shares the site.
- Viewer: anyone Cosmo sends the link to. Browses tables, no login.
- Engineer/agent building parts 2-5: reads the database and APIs.

## User stories and acceptance criteria

### US1. Load the data
As Cosmo, I want the four datasets loaded for the chosen seasons, so that every later part starts from the same data.
1. Running the loader for seasons 2015-2026 fills `teams`, `players`, `games`, and `player_week_stats`.
2. For each loaded season, the row count of `games` and `player_week_stats` equals the source file's row count for that season.
3. Running the loader twice in a row with the same source leaves every table with identical contents.
4. Each run writes one `load_runs` row per dataset and season with status, row counts, times, and source version.

### US2. Keep it fresh
As Cosmo, I want the current season refreshed automatically, so that the site shows recent weeks without me doing anything.
1. A scheduled GitHub Actions workflow loads the current season once a day.
2. The same workflow can be started by hand with a seasons input (backfill).
3. A failed load leaves the previous data in place and records status `failed` with the error.
4. The database URL lives only in a GitHub Actions secret and the host's environment settings, never in the repo.

### US3. Read the data over an API
As an engineer building parts 2-5, I want JSON endpoints with filters and pagination, so that I can read the data without direct database access.
1. Each table has a list endpoint and (except stats and load runs) a get-by-key endpoint, as specified in [F001 SPEC](features/F001-data-prototype/SPEC.md).
2. List endpoints accept `limit` (default 50, max 500) and `offset`, and return the total count.
3. Bad parameters return HTTP 400 with the error shape in the spec; unknown keys return 404.

### US4. Browse the tables
As a viewer, I want a page per table with filters, sort, and paging, so that I can look up players, games, and weekly stats.
1. Pages exist for players, teams, games, player week stats, and load runs.
2. Each page filters by the same parameters as its API endpoint, sorts by clicking a column header, and pages with previous/next links.
3. Every page footer shows the nflverse attribution and the time of the last successful refresh.

### US5. Share it
As Cosmo, I want the site at a public URL, so that I can send it to friends.
1. The site is reachable over HTTPS at a host-provided URL with no login.
2. Monthly hosting cost is $0 on free tiers.

## Open questions

None. Answers recorded in the F001 SPEC Decisions section.
