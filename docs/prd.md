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




## Private salary workstream F005–F008 (approved; not deployed)

This extends the original Part 1 scope above, not its public-table/API commitments. Cadence and the Sunday-afternoon slate rule are answered. ADR 0005/0006 are Accepted and the constitution amendment is operative by owner merge of PR #17. The forge handoff for that approved scope was delivered. Build F005, then F006 and F007, then F008, in separate PRs, after each dependency PR merges. That order is not a new docs gate and is not permission to skip those merges. No schedule activation and no production migration or deploy.

- As Cosmo, I want automatic unauthenticated DK Classic salary capture into a new private append-only snapshot source, so I retain contemporaneous evidence without replacing my F004 official-export CLI/staged-path workflow ([F005](features/F005-dk-lobby-capture/SPEC.md)). Approved cadence is Wednesday 10:00 America/New_York during REG season (planned only; not activated; no Sunday refresh). Approved automatic slate is only the upcoming Sunday-afternoon Classic set of all REG games kicking off 1:00–4:30 PM America/New_York, including holiday weeks. Each capture attempt records private monotonic runtime in Neon.
- As Cosmo, I want the acquired Daily Fantasy Fuel historical salary/projection subsets loaded into their own private table, so I can use actual available gap coverage without claiming complete main slates or actual points ([F006](features/F006-dff-historical-archive/SPEC.md)).
- As Cosmo, I want original pureslurp/DKNFL archived DKSalaries loaded separately with corrected game-derived metadata and original paths, so holiday/alternate/mislabeled exports remain attributable ([F007](features/F007-dknfl-historical-archive/SPEC.md)).
- As a future optimizer consumer, I want one private, pinned salary surface with verified entity+exact-slate mappings, coherent anchor snapshots and flagged alternatives/disagreements, so unrelated slates/revisions never silently form a player pool ([F008](features/F008-unified-salary-surface/SPEC.md)).

Acceptance is in each SPEC's requirement-to-AT matrix. Sources/bytes/rows stay intact; current/raw salaries and the unified view are not public APIs/pages/downloads. Optimizer code, projections/scoring, APIs/UI, auth, broad scraping, and production changes are non-goals. Data permissions and conservative merge choices are [ADR 0005](adr/0005-private-salary-capture-and-archives.md), [ADR 0006](adr/0006-slate-safe-salary-unification.md), and the operative constitution amendment. Existing F003 RotoGuru attribution/public allowance is unchanged; new sources are never credited to RotoGuru.

Cosmo approved independent season-schedule verification on 2026-11-06 19:14 EST. Capture must not treat an incomplete database or a truncated upstream file as a smaller valid slate or as off-season. [ADR 0007](adr/0007-authoritative-schedule-completeness.md) is Accepted by the owner merge of PR #20 as a contract only. That acceptance is not acceptance of an implementation. The operator reviews a full published season inventory each season and when games change. The normal nflverse refresh retains exact source bytes and a source-to-PG receipt. F005 checks the whole REG partition and finite timing or gap coverage before any DK call. No new automatic schedule scraper is added. No season inventory is certified. Wednesday 10:00 America/New_York and the Sunday 1:00–4:30 PM America/New_York slate rule are unchanged.


## F009 React frontend (DRAFT)

Drafted 2026-11-10. Rev 2: the SPA footer attribution is a static bundle constant checked against `web/attribution.py`, including during an API or database outage. This extends Part 1's public browse goal (US4) without changing the public table or API commitments, except for additive `last_refresh_et` and `datasets` on `GET /api`. A missing refresh renders `Last refresh: none`.

- As a viewer, I want the current home and table pages in a React app, so that lookups and shareable filter URLs keep working.
- As Cosmo, I want the live Jinja site unchanged until I enable cutover, so that a docs or code merge cannot surprise visitors.
- As a future optimizer UI author, I want a reusable virtualized table contract, so that a later player pool of hundreds of rows can sort, filter, and hook lock or exclude toggles without a new table primitive.

Phase 1 does not build the optimizer UI, public salary pages, or a second host. Details and acceptance tests are in [F009 SPEC](features/F009-react-frontend/SPEC.md). Hosting is [ADR 0008](adr/0008-react-frontend-hosting.md), Proposed. The constitution amendment is pending. Groko gates the docs PR. Cosmo go-ahead is pending. This section does not authorize a forge build or a live cutover.
