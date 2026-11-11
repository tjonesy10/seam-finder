# F009: React TypeScript frontend

Status: **DRAFT** (2026-11-10). Written against main `36636c2af8326a11ab3a4cbe4498df487fad78bd`. This package is docs only. It is not handed to forge. Groko gates the docs PR. Cosmo's go-ahead is pending. No implementation, production deploy, or live-site cutover is authorized by this draft.

Related: [constitution](../../CONSTITUTION.md), [pending constitution amendment](CONSTITUTION-AMENDMENT.md), [architecture](../../architecture.md), [glossary](../../GLOSSARY.md), [F001 SPEC](../F001-data-prototype/SPEC.md), [ADR 0001](../../adr/0001-stack-and-hosting.md), [ADR 0008](../../adr/0008-react-frontend-hosting.md).

## Problem / job to be done

The public site is server-rendered Jinja2 HTML from the same FastAPI process that serves JSON. Cosmo approved a React and TypeScript frontend so tables can grow into a future optimizer player pool without a second rewrite. Phase 1 must match today's pages, keep the live site unchanged until he turns the new app on, and leave `/api/health` and the public API working.

## Requirements

- **R1** Replace the Jinja pages with a Phase 1 React app that preserves today's routes, tables, filters, sort, paging, URL state, headings, labels, and pager copy. Do not add an optimizer UI, detail pages, or new public datasets.
- **R2** Show the exact current nflverse attribution text, its two links, and the "Last refresh" line on every page, including error views.
- **R3** Build the app as React, TypeScript, and Vite. Use TanStack Table and TanStack Virtual for every table, TanStack Query for fetching and caching, and TanStack Router for page routes and URL-persisted filter, sort, and paging state. Do not use TanStack Start or SSR.
- **R4** Put every table on one reusable data-table contract that can take a 500-plus row in-memory pool with sort, filter, virtualization, and a row-toggle hook point. Do not build lock or exclude controls in Phase 1.
- **R5** Serve the built static files from the existing FastAPI app on the existing Render free web service, per [ADR 0008](../../adr/0008-react-frontend-hosting.md). Keep JSON routes under `/api` and `/api/*` ahead of the SPA fallback. Leave `GET /api/health` behavior unchanged.
- **R6** Keep the live Jinja site as the default until Cosmo enables cutover. Provide a documented build artifact, a default-off switch, and a rollback path that restores Jinja or a prior Render deploy. Enabling the switch with a missing build must not break `/api/health`.
- **R7** The frontend must never read `salary_private` or any private salary data. Leave `seamfinder_web` grants unchanged. Add no endpoint that exposes private schema or F004 raw salaries. Prove the public API surface and the built bundle stay clear of that data.
- **R8** Keep the existing list and get-by-key JSON contracts. Add only the additive `GET /api` fields needed for the home page and footer, which have no complete JSON source today.
- **R9** Cover the app with Vitest and Testing Library unit tests, Playwright end-to-end tests against the built app plus FastAPI and real Postgres, and pytest API contract tests. Extend CI with a pinned Node 26 toolchain, `npm ci`, typecheck, lint, unit tests, build, and end-to-end tests, without dropping ruff, pytest, or gitleaks. Commit the npm lockfile.

## User stories

- As a viewer, I want the same home and table pages I use today, so that shared links and lookups still work after the frontend changes.
- As Cosmo, I want the live site to stay on Jinja until I enable the new app, so that a merge cannot surprise visitors.
- As a future optimizer UI author, I want one virtualized table contract that already supports hundreds of rows, sort, filter, and a toggle hook, so that a later player-pool page does not need a new table primitive.
- As a reviewer, I want frontend checks in CI next to the existing Python gates, so that a broken typecheck or bundle cannot merge unnoticed.

## Observable behavior

### Current pages and data sources, verified on main `36636c2`

Routes and templates live in `web/main.py`, `web/pages.py`, `web/resources.py`, and `web/templates`. JSON list handlers and HTML pages share `web/queries.py` and the same query parameters in `web/params.py`.

| Page path | What it shows | Data endpoint today |
|---|---|---|
| `/` | Title "Seam Finder", links to the five table pages, heading "Last refresh per dataset", one line per dataset in `teams`, `players`, `games`, `player_week_stats` | No complete JSON source. `GET /api` already returns `name`, `attribution`, and `endpoints`. `GET /api/health` returns `last_refresh` as ISO timestamps for the latest successful run only, not per-dataset Eastern labels. |
| `/teams` | Title "Teams". Filters: Conference `conf`, Division `division`. Default sort `team_abbr` asc | `GET /api/teams` |
| `/players` | Title "Players". Filters: Name `q`, Position `position`, Team `team`, Status `status`. Default sort `display_name` asc | `GET /api/players` |
| `/games` | Title "Games". Filters: Season `season`, Week `week`, Season type `season_type`, Team `team`. Default sort `gameday` asc | `GET /api/games` |
| `/stats` | Title "Player week stats". Filters: Season `season`, Week `week`, Season type `season_type`, Team `team`, Position `position`, Player `player`, Game `game_id`. Default sort `fantasy_points_ppr` desc | `GET /api/player-week-stats` |
| `/load-runs` | Title "Load runs". Filters: Dataset `dataset`, Status `status`, Season `season`. Default sort `started_at` desc | `GET /api/load-runs` |

The stats filter `game_id` is defined on the `STATS` resource and rendered by `table.html`. The F001 pages table omitted it. Phase 1 follows the running code and keeps `game_id`.

There is no HTML page for `GET /api/teams/{team_abbr}`, `GET /api/players/{gsis_id}`, or `GET /api/games/{game_id}`. Phase 1 does not add detail pages. Those JSON endpoints stay as they are.

Error views use `web/templates/message.html` or the error branch of `table.html`. Copy comes from `web/errors.py` and `web/main.py`, including "Not found", "invalid parameter", "week must be an integer from 1 to 22", "The database is unavailable.", and "Something went wrong."

### Attribution and disclaimer strings, quoted from the current site

`web/templates/base.html` prints `{{ attribution.text }}`, the attribution links, and `Last refresh: {{ last_refresh_et }}` on every page. The text is not a literal in the template. It is `ATTRIBUTION_TEXT` from `web/attribution.py`, also required by [ADR 0002](../../adr/0002-nflverse-load-and-refresh.md). The exact current string is:

> Data: nflverse (nflverse-data), licensed CC BY 4.0. Changes: subset of columns, loaded into a database. Not affiliated with or endorsed by the NFL or nflverse. NFL data belong to their respective owners.

The two links are `nflverse-data` at `https://github.com/nflverse/nflverse-data` and `CC BY 4.0` at `https://creativecommons.org/licenses/by/4.0/`. The refresh label uses America/New_York as `%Y-%m-%d %H:%M:%S ET`, or `none`.

The DraftKings disclaimer is **not** in any current template and is **not** shown on the current site. `web/attribution.py` defines, but `attribution()` does not return, this exact unused constant:

> Historical DraftKings Classic salaries and points via RotoGuru (rotoguru1.com). Not affiliated with DraftKings.

Phase 1 pages do not mention DraftKings or RotoGuru, matching today's public pages. Keep that RotoGuru constant in the Python module. If a later approved page shows historical DraftKings Classic salaries, that page must use this exact string. Do not add it to Phase 1 footers.

### Additive `GET /api` contract

Extend `GET /api` with footer fields already computed by `web.queries.footer`. Existing keys stay. New keys are additive, so current clients can ignore them.

```json
{
  "name": "Seam Finder",
  "attribution": {
    "text": "Data: nflverse (nflverse-data), licensed CC BY 4.0. Changes: subset of columns, loaded into a database. Not affiliated with or endorsed by the NFL or nflverse. NFL data belong to their respective owners.",
    "links": [
      {"label": "nflverse-data", "url": "https://github.com/nflverse/nflverse-data"},
      {"label": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}
    ]
  },
  "endpoints": [
    "/api/teams",
    "/api/players",
    "/api/games",
    "/api/player-week-stats",
    "/api/load-runs"
  ],
  "last_refresh_et": "2026-11-05 12:00:00 ET",
  "datasets": [
    {"dataset": "teams", "finished_at": "2026-11-05 12:00:00 ET"},
    {"dataset": "players", "finished_at": "2026-11-05 12:00:00 ET"},
    {"dataset": "games", "finished_at": "2026-11-05 12:00:00 ET"},
    {"dataset": "player_week_stats", "finished_at": "none"}
  ]
}
```

`last_refresh_et` and each `datasets[].finished_at` use the same Eastern formatting as the HTML footer, including `none`. `GET /api/health` stays `{ "status", "database", "last_refresh" }` with ISO timestamps, and still returns 503 with `service_unavailable` when the database is down. List and get-by-key endpoints, error shape, `Cache-Control: public, max-age=300` on `/api` paths, and parameter rules stay as in the F001 SPEC.

The SPA reads attribution and refresh labels from `GET /api`, not from a second hardcoded copy, except tests may import the Python constant to check equality.

### URL state, paging, and errors

Filter, sort, order, limit, and offset stay in the query string on the same page paths, so today's links keep working. Default page size stays 50, and `limit` stays in 1 to 500 through the existing API. Phase 1 tables keep server-side filter, sort, and paging. They do not download an entire dataset in one request.

Pager copy stays `rows {start}-{end} of {total}`, with Previous and Next when those pages exist. An empty result stays `rows 0-0 of 0`.

Invalid query parameters still produce API HTTP 400 and the same `error.message` text. After cutover, the document request for that URL may be HTTP 200 because the server returns the SPA shell, and the UI shows the error on the table page with the filter form still present. That document-status change is accepted. Show no stack trace.

Unknown non-API paths show "Not found" in the same page chrome and footer. Unknown `/api/*` paths stay JSON 404.

### Reusable data-table contract

One component, used by every Phase 1 table, owns rendering. Call it `DataTable`. It must accept at least:

- `data`: the current row array
- `columns`: TanStack Table column defs, including `id` or `accessorKey`, a header label, and optional sort
- `getRowId`: a stable string id for each row
- controlled `sorting` and `onSortingChange`
- controlled `columnFilters` and `onColumnFiltersChange`
- optional controlled `rowToggles` and `onRowTogglesChange`, a map from row id to a small toggle record such as `{ locked?: boolean, excluded?: boolean }`
- a TanStack Virtual virtualizer for the row body, with a fixed or estimated row height

Phase 1 does not render lock or exclude controls. It may pass an empty toggle state or omit the optional props. The hook point must be callable from a unit test without changing the column-def shape.

A Vitest fixture of at least 500 rows must prove that the body is virtualized, so the DOM does not mount all 500 row nodes at once, that controlled sort and filter change which rows appear, and that toggling a row through the hook point keeps the row id stable.

### Frontend layout

Place the app in `frontend/` at the repository root. Pin Node 26, the Active LTS as of 2026-11-10, in `.nvmrc` and `frontend/package.json` `engines`. Commit `frontend/package-lock.json`. Ignore `node_modules` and the Vite output directory, which may stay under `frontend/dist` and is already covered by the root `dist/` ignore rule. The FastAPI process must be able to find the build output at a single documented path, for example `frontend/dist`.

Allowed TanStack libraries are Table, Virtual, Query, and Router. Router is in scope because the site already has multiple pages and already persists filter, sort, and paging in the URL. TanStack Start, any other SSR framework, and any other bundler are out of scope.

Keep the current plain layout: sans-serif body text, a "Seam Finder" home link, an `h1` title, a GET filter form, a horizontally scrollable table, pager links, and the footer. Add no `<img>` tags and no external images.

### Hosting, cutover, and rollback

Hosting is decided in ADR 0008: the existing Render free web service builds the Vite app and FastAPI serves the hashed assets plus `index.html`. There is still no committed `render.yaml`. `tests/test_web_layout.py` already forbids one. Dashboard settings stay outside the repo.

`GET /api` and `GET /api/*` are matched before any SPA fallback. Static hashed assets may be cached for a long time. `index.html` must not be cached as a long-lived immutable file, so a rollback or a later deploy is visible.

Cutover uses an environment variable `SERVE_SPA`. The switch is on only when the value is exactly `true`. Any other value, including unset, keeps today's Jinja routes. `/api/health` and the JSON API work in both modes. Existing F001 page tests keep passing while the switch is off.

Render's current documented settings from F001 are runtime Python, branch `main`, build `pip install .`, start `uvicorn web.main:app --host 0.0.0.0 --port $PORT`, health check `/api/health`. Do not change the production build command until Cosmo approves cutover. Until then, CI builds the frontend, and a production `pip install .` deploy keeps serving Jinja.

When Cosmo approves cutover, the dashboard build command installs Node 26, runs `npm ci` and `npm run build` in `frontend/`, then `pip install .`. The start command and health path stay the same. Then set `SERVE_SPA` to `true`. If the switch is on and the build output is missing, non-API page routes fail clearly, and `/api/health` still returns its normal JSON when the database is reachable.

Rollback: set `SERVE_SPA` to anything other than `true` to restore Jinja from the same deploy, or redeploy the previous Render release. Jinja templates stay in the tree for that first SPA release so the flag rollback works. A later cleanup feature may remove Jinja after Cosmo confirms the cutover.

### Privacy

No new HTTP path may read or return `salary_private`, `dk_classic_slate`, lobby or archive salaries, or `dk_salary_unified`. `loader/grants.py` and the public allowlist stay unchanged. The frontend source, its tests, and the production bundle must not mention `salary_private`, `dk_salary_unified`, `dk_lobby_salaries`, `dff_salaries`, or `dknfl_salaries`. The only HTTP requests the frontend makes are the documented public `/api` paths above.

### Constitution

The accepted constitution pins "FastAPI with Jinja2 pages" and "No ORM layer, pandas, JS framework, or bundler without a new ADR." This feature conflicts with those two sentences. The pending amendment is [CONSTITUTION-AMENDMENT.md](CONSTITUTION-AMENDMENT.md). It is not operative until Cosmo approves and it is merged into `docs/CONSTITUTION.md`. ADR 0008 is the required ADR for the framework and bundler. Do not treat this SPEC as a silent exception.

## Acceptance tests

Automate each case. Pages and end-to-end checks run against the built Vite app served by FastAPI with `SERVE_SPA=true`, unless a case names the switch off. API and grant tests use real Postgres, as today.

- **AT1 (R1)** Given a loaded database, when the built app is served and you open `/`, then the document title or `h1` is "Seam Finder", the five links `/teams`, `/players`, `/games`, `/stats`, and `/load-runs` are present, the heading "Last refresh per dataset" is present, and each of `teams`, `players`, `games`, and `player_week_stats` has a refresh line.
- **AT2 (R1)** Given a loaded database, when you open `/teams`, `/players`, `/games`, `/stats`, and `/load-runs`, then each page returns a rendered table and the filter fields listed in the route table, including `game_id` on `/stats`.
- **AT3 (R1)** Given the F001 CIN week-10 fixture data, when you open `/stats?season=2024&week=10&team=CIN`, then Ja'Marr Chase appears, sorting by `receiving_yards` updates the URL and row order, and Next keeps the filters and moves to offset 50 with `rows 51-100 of ` visible.
- **AT4 (R1)** Given `/games?week=abc`, when the app loads that URL, then the text "week must be an integer from 1 to 22" is visible, the filter form is still present, and no traceback is shown. The list API request for those params is HTTP 400. An unknown non-API path shows "Not found".
- **AT5 (R2)** Given `/`, each table path, `/games?week=abc`, and a not-found path, then the footer contains the exact nflverse attribution string quoted above, both attribution hrefs, and `Last refresh: ` followed by the Eastern timestamp or `none`.
- **AT6 (R1)** Given those same paths, then the document contains no `<img>` tag and no `url(http` or `url(//` stylesheet image.
- **AT7 (R3)** Given the `frontend/` package and the built output, when inspected by tests, then the app depends on React, TypeScript, Vite, TanStack Table, TanStack Virtual, TanStack Query, and TanStack Router, and it does not depend on TanStack Start or an SSR framework. Table pages use the shared `DataTable`. List data is fetched with TanStack Query.
- **AT8 (R4)** Given a synthetic fixture of at least 500 rows, when `DataTable` renders in Vitest, then the row body is virtualized so fewer than 500 row nodes are in the DOM, controlled sort and filter change the visible set, `getRowId` stays stable, and a test can set a lock or exclude toggle on one row through the hook point without changing column defs.
- **AT9 (R8)** Given the database is up, when `GET /api` is called, then the response keeps `name`, `attribution.text`, both links, and `endpoints`, and it also returns `last_refresh_et` and `datasets` in the footer shape. `GET /api/health` still returns `{status, database, last_refresh}` and still returns 503 `service_unavailable` when the database is down. One existing list or get-by-key contract, including pagination limits, is unchanged.
- **AT10 (R5)** Given `SERVE_SPA=true` and a successful frontend build, when you request `GET /api/health`, `GET /api/teams`, and an unknown `/api/missing`, then the responses are JSON with the current contracts and status codes, not `index.html`. A non-API app path serves the SPA shell. Hashed asset responses may be long-cached. `index.html` is not marked immutable with a long max-age.
- **AT11 (R6)** Given `SERVE_SPA` is unset or not exactly `true`, when the existing F001 page tests run, then they still pass against Jinja, and `GET /api/health` is 200 when the database is up. Given `SERVE_SPA=true` and a missing build output, when you request `/` and `/api/health`, then `/` fails clearly and `/api/health` still returns its normal JSON when the database is up. Turning the switch off again restores Jinja from the same app.
- **AT12 (R7)** Given the FastAPI route table and a real Postgres role granted by `loader/grants.py`, when tests inventory `/api` routes and query as the web role, then the only API paths are the current public F001 endpoints, grants for the web role are unchanged, and that role still cannot read `salary_private` or `dk_classic_slate`.
- **AT13 (R7)** Given the frontend source and the production bundle, when searched, then they do not contain `salary_private`, `dk_salary_unified`, `dk_lobby_salaries`, `dff_salaries`, or `dknfl_salaries`, and the app's HTTP client is limited to the documented public `/api` paths.
- **AT14 (R9)** Given `.github/workflows/ci.yml`, when reviewed and run, then the workflow pins Node 26, runs `npm ci` from the lockfile, typecheck, lint, frontend unit tests, the production build, and Playwright end-to-end tests, and it still runs `ruff check loader web tests migrations`, pytest, and gitleaks. The lockfile is committed.
- **AT15 (R9)** Given Playwright running against the built app, FastAPI with `SERVE_SPA=true`, and real Postgres, when the suite runs, then it covers the home page, one table's filter, sort, and paging, the attribution footer, `GET /api/health`, and the bad-parameter message.

## Non-goals

Optimizer UI, lock and exclude controls in the product pages, public salary pages or downloads, new auth, a custom domain, a paid plan, a visual redesign, a committed `render.yaml`, removing Jinja in the first SPA release, schedule activation, production migration, and a live cutover from this docs package.

## Allowed dependencies

Frontend runtime: React, TypeScript, Vite, TanStack Table, TanStack Virtual, TanStack Query, TanStack Router.

Frontend test and CI: Vitest, Testing Library, Playwright, ESLint or an equivalent lint already wired in CI, `npm` with a committed lockfile, Node 26.

Backend, unchanged except for serving static files, the `SERVE_SPA` switch, and the additive `GET /api` fields: Python 3.12, FastAPI, uvicorn, Jinja2 kept for the rollback path, SQLAlchemy Core, psycopg, pydantic-settings.

Not allowed: TanStack Start, Next.js or another SSR host, a second JS framework, an ORM, pandas, a new paid service, and any library whose job is to read private salary data from the browser.

## Decisions

1. TanStack Router is in scope. The site already has multiple pages, and filter, sort, and paging already live in the URL. That is the justification the brief asked for. TanStack Start and SSR stay out.
2. Hosting is FastAPI serving the built assets on the existing Render web service, not a separate Render static site. Reasons are in ADR 0008.
3. Cutover is `SERVE_SPA` exactly equal to `true`. The default is off so an auto-deploy from `main` cannot change the live HTML until Cosmo sets the variable and updates the Render build command.
4. Home and footer data come from an additive `GET /api` extension, not a new `/api/meta` route and not client-side Eastern formatting of `/api/health`.
5. Phase 1 does not display the unused RotoGuru DraftKings disclaimer, because the current templates do not display it.
6. Node is pinned to 26, Active LTS as of 2026-11-10.

## Open questions

None. The choices above are reversible technical defaults, not product questions that block a docs PR.

## Analyze matrix

| Requirement | Acceptance tests |
|---|---|
| R1 | AT1, AT2, AT3, AT4, AT6 |
| R2 | AT5 |
| R3 | AT7 |
| R4 | AT8 |
| R5 | AT10 |
| R6 | AT11 |
| R7 | AT12, AT13 |
| R8 | AT9 |
| R9 | AT14, AT15 |

R1-R9 all covered. AT1-AT15 none orphaned. This feature conflicts with two constitution stack sentences until the pending amendment is approved. ADR 0008 records the hosting and frontend decision and, once accepted, partially supersedes ADR 0001. No other ADR or constitution privacy rule is contradicted. No clarification markers are open.

## ADRs

- [ADR 0001: Stack and hosting](../../adr/0001-stack-and-hosting.md), Jinja and no-bundler clauses superseded by 0008
- [ADR 0002: nflverse source and attribution](../../adr/0002-nflverse-load-and-refresh.md)
- [ADR 0003: RotoGuru DK Classic salaries](../../adr/0003-rotoguru-dk-classic-salaries.md), string preserved, not shown in Phase 1
- [ADR 0005: Private salary capture and archives](../../adr/0005-private-salary-capture-and-archives.md), privacy and web-role isolation
- [ADR 0008: React frontend and asset hosting](../../adr/0008-react-frontend-hosting.md) (Proposed)
