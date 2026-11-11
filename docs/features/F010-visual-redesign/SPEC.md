# F010: Dark-first visual redesign

Status: **READY** (2026-11-10). Planning only; no implementation or deployment claimed. Read against main `0ab6132` (includes F009 PR #31). Build F010 separately; [F011](../F011-premium-tables/SPEC.md) waits for F010's implementation PR to merge. Owner merges all PRs.

## Problem / job to be done

F009 deliberately preserved the old layout. Make the existing public analytics site feel considered and readable: strong hierarchy, restrained dark surfaces, clear navigation and useful feedback, without changing the data or API. This pass delivers the shared visual foundation; richer table behavior belongs to F011.

## Requirements

- **R1** Use one semantic token system and CSS Modules for a polished dark-first design on all existing SPA pages. Use the palette, type, spacing and radius contract below. No theme toggle or light theme in this pass.
- **R2** Provide a consistent app shell, six-route navigation, current-page indication, page title and compact context area. Home uses dataset-refresh cards and table entry links, not invented analytics or counts.
- **R3** Restyle all five tables and their existing dataset filters/pagers using the same surfaces, borders and type hierarchy. Preserve existing columns, server filtering/sort/paging and URLs. Preserve TanStack Table/Virtual and its reusable contract. This feature supersedes only F009's plain-layout/parity appearance requirement.
- **R4** Provide skeleton, empty, fetching, error, retry and not-found states that preserve shell and attribution and distinguish no results from failure.
- **R5** Make the shell/forms work from 320 CSS px wide through desktop, including 200% zoom. Table overflow stays inside a named, keyboard-scrollable region, never the whole document.
- **R6** Target WCAG 2.1 AA: semantic landmarks, labels, keyboard operation, visible focus, contrast and reduced-motion support. Verify automated accessibility plus recorded keyboard/zoom checks.
- **R7** Preserve exact attribution and refresh behavior, including first-load failures. Never hide the footer in a collapsed region. No salary display or DraftKings line is added.
- **R8** Leave every API contract, backend query, grants, private-data boundary, hosting and cutover behavior unchanged. Add no public dataset or request outside the existing frontend API allowlist.
- **R9** Add deterministic Playwright screenshot comparisons and axe accessibility scans to CI alongside existing checks. Commit reviewed baselines and record requirement evidence in TEST_REPORT.md; do not replace real-Postgres integration coverage with mocks.

## User stories

- As a viewer, I want a clear dark workspace, so that dense data is readable rather than visually exhausting.
- As a mobile or keyboard viewer, I want navigation and filters I can operate, so that the site works without a mouse or wide display.
- As a reviewer, I want stable visual and accessibility checks, so that later table work does not undo the redesign.

## Observable behavior

### Existing routes and unchanged data

Implementation is in `frontend/`, not `web/` JavaScript. `frontend/src/resources.ts` defines tables; `web/resources.py`, `web/params.py`, `web/queries.py` define the public API. Shapes are in [data-dictionary](../../data-dictionary.md): `teams`, `players`, `games`, `player_week_stats`, `load_runs`. Lists remain `{data: row[], page: {limit, offset, total}}`; metadata remains `GET /api` with `last_refresh_et` and `datasets`. No data-dictionary change is needed.

| Route | Data | Existing filters | Default sort |
|---|---|---|---|
| `/` | `GET /api` refresh labels | none | none |
| `/teams` | `/api/teams` | `conf`, `division` | `team_abbr` asc |
| `/players` | `/api/players` | `q`, `position`, `team`, `status` | `display_name` asc |
| `/games` | `/api/games` | `season`, `week`, `season_type`, `team` | `gameday` asc |
| `/stats` | `/api/player-week-stats` | `season`, `week`, `season_type`, `team`, `position`, `player`, `game_id` | `fantasy_points_ppr` desc |
| `/load-runs` | `/api/load-runs` | `dataset`, `status`, `season` | `started_at` desc |

No current page or public endpoint exposes salary fields, including historical RotoGuru `dk_salary` or `dk_points`. Stats points are nflverse `fantasy_points` / `fantasy_points_ppr`, not DK scores. Do not manufacture salary controls or a new salary page.

### Design contract

Use CSS custom properties in one global token sheet; CSS Modules own component styles. Global CSS is limited to tokens, bundled font faces, reset/base and shared accessibility utilities. No new runtime styling library. Dark mode is fixed (`color-scheme: dark`), independent of OS theme, to keep this build small.

| Token family | Initial values / purpose |
|---|---|
| Surface | `--color-canvas: #0b1220`; `--color-surface: #111c2e`; `--color-raised: #1b2b42` |
| Text | `--color-text: #e8eef7`; `--color-muted: #a7b5ca`; muted text is still readable body text |
| Interaction | `--color-accent: #70d6c5`; `--color-on-accent: #0b1220`; `--color-focus: #9bc9ff`; links visibly underlined |
| State | `--color-success: #87d7a4`; `--color-warning: #f3cf82`; `--color-danger: #ffb0b8`; always paired with text |
| Border | `--color-control-border: #70839f` for control boundaries; `--color-divider: #304159` decorative only |
| Type | Bundled Latin normal-weight Inter 400/500/600/700 via `@fontsource/inter`; sans-serif fallback; tabular numerals for tables; body 16px/1.5, table 14px/1.45, labels 14px, h1 28px/1.2, h2 20px/1.3 |
| Space | `--space-1..8`: 4, 8, 12, 16, 20, 24, 32, 48px (use rem equivalents) |
| Radius | `--radius-control: 6px`; `--radius-panel: 12px`; no pill-shaped data tables |
| Motion | 120ms color/opacity only; no layout animation, shimmer or parallax; disable transitions for reduced motion |

Body text contrast is at least 4.5:1; large text at least 3:1; essential control borders/focus indicators at least 3:1 against adjacent surfaces. Verify all actual foreground/background pairs, not just nominal tokens. Correct a failing pair and record the final tokens in TEST_REPORT.md, rather than waive AA. Active nav uses text/marker as well as color. Avoid gradients behind data, logos, headshots, remote images and marketing claims.

At widths >=1024px use a 224px navigation rail and flexible main region. Below that, use a compact header with a native disclosure button for navigation; `aria-expanded`/`aria-controls`, Escape closes and returns focus to its trigger. Closing nav never traps focus or leaves hidden links tabbable. Main padding 24–32px desktop, 16px mobile. The footer follows main in normal flow (not fixed). Forms wrap; labels stay above controls. Home preserves “Last refresh per dataset” and the four dataset labels with their API-supplied Eastern strings.

Table content stays available through horizontal and vertical scrolling. Use restrained panel borders and row hover/focus treatments; row heights remain consistent with the virtualizer. Sticky behavior, density controls and conditional scales are F011. Do not reorder or hide columns in F010.

### States and accessibility

- Initial list load: shell, title, filters, static footer and a table-shaped skeleton (8 decorative rows, `aria-hidden`); named region `aria-busy=true`, one polite “Loading data” status. No fake row counts.
- Refetch: retain current rows with “Updating data”; mark busy. A terminal failed request shows the error and does not label old rows as current success. Retry repeats the same query, not a full navigation.
- Successful zero rows: “No results for these filters.”, a “Clear filters” action, and `rows 0-0 of 0`. Clear returns to route defaults. Zero-row offset beyond total: explain “No rows on this page.” and offer first page, keeping dataset filters.
- 503: “The database is unavailable.” Other network/5xx: “Something went wrong.” Preserve meaningful existing 400 API messages and editable filters, no traceback. Error is an alert with Retry; retry is not an infinite loop. Metadata failure does not erase a successful table, but displays its own error and `Last refresh: none`.
- Unknown SPA route: “Not found”, same navigation/footer and home link.
- Skip link targets main. One h1, header/nav/main/footer landmarks, label every control, logical tab order, no hover-only actions. Minimum interactive target 44x44 CSS px except inline prose links. 2px visible focus ring with offset; focus never clipped. Skeleton is not announced row by row. Status changes are announced once. After route navigation focus main heading; after form submit retain control focus and announce completion.
- At 320px and 200% zoom only table regions may scroll horizontally. Do not replace tables with inaccessible card piles. Reduced motion removes even decorative animation.

### URL contract in this pass

Reuse TanStack Router's existing search parsing/navigation in `resources.ts` / `router.tsx`. No new parameters. Each route accepts its filter names above plus `sort` (current resource allowlist), `order=asc|desc`, `limit` (integer 1–500, default 50), `offset` (integer 0–2147483647, default 0). Strings use URLSearchParams percent encoding. Filter defaults are absent; sort/order defaults are in the route table. Keep F009 bad-parameter error behavior for existing URLs in F010. F011 specifies the new forgiving client-state schema and its explicit UI-only change; API validation remains unchanged in both features.

### Attribution, privacy and fallback

The static frontend constant must continue to equal `web/attribution.py` `ATTRIBUTION_TEXT` and `ATTRIBUTION_LINKS`:

> Data: nflverse (nflverse-data), licensed CC BY 4.0. Changes: subset of columns, loaded into a database. Not affiliated with or endorsed by the NFL or nflverse. NFL data belong to their respective owners.

Links: `nflverse-data` → `https://github.com/nflverse/nflverse-data`; `CC BY 4.0` → `https://creativecommons.org/licenses/by/4.0/`. Show this on all routes and states before any API success. Keep API-provided Eastern refresh label, otherwise exactly `Last refresh: none`.

If a separately authorized future feature displays historical DK salary data, it must use `ROTOGURU_DK_CLASSIC_ATTRIBUTION` exactly:

> Historical DraftKings Classic salaries and points via RotoGuru (rotoguru1.com). Not affiliated with DraftKings.

That condition does not authorize such a display here. No `salary_private` access, no private salary fields in the bundle/fixtures/reports, and no change to `seamfinder_web` grants. Jinja rollback and the server's pre-SPA database-unavailable/missing-build fallback remain unchanged; redesign targets the SPA, not legacy templates. The fallback still carries exact attribution. No Render configuration changes.

### Deterministic CI visual and accessibility contract

Extend existing `frontend/playwright.config.ts`, `frontend/e2e/` and `.github/workflows/ci.yml`, not a second test stack. Existing Playwright uses real FastAPI plus Postgres and currently writes screenshots only; it has no screenshot comparison gate. Keep those integration tests and the unchanged `tests/test_api.py` on/off runs.

Add a separate Chromium visual project on a fixed Ubuntu 24.04 runner (not moving ubuntu-latest for baseline comparison), lockfile-pinned Playwright/browser, Node 26, deviceScaleFactor 1, locale en-US, timezone America/New_York, dark scheme, reduced motion, viewports 1440x1000 and 390x844. Install/use bundled Inter fonts, wait for `document.fonts.ready`, freeze time to a fixed November 2026 instant, fixed scrollbar/environment and stable row order. Route-mock all browser `/api` data requests with small synthetic fixtures before navigation; no live data/screenshots, no real names or private payloads. Real Postgres integration remains a separate path, satisfying the constitution.

Commit full-page baselines under `frontend/e2e/visual.spec.ts-snapshots/`. Snapshot all six routes at both viewports, plus stats loading/empty/503, home metadata-outage, and not-found at both viewports. Capture by explicit ready-state locators, not sleeps; the loading case holds the fixture response until after capture. Disable animations/caret in screenshot options; no broad masks over content or attribution. Comparison: per-pixel threshold 0.2, `maxDiffPixels: 100`, no ratio allowance. Missing baseline or larger diff fails CI. No auto-update in CI; review expected/actual/diff in an intentional PR, generating baselines only in the same pinned environment. Upload synthetic-only failure diffs/traces on failure, 7-day retention.

Run `@axe-core/playwright` WCAG2A/WCAG2AA/WCAG21A/WCAG21AA tags on every route plus loading/empty/error/not-found, both viewports: zero violations (no blanket exclusions). Supplement with keyboard, zoom, focus and token-contrast checks because axe is not proof of full AA. Keep typecheck, lint, Vitest, build, ruff, pytest, gitleaks, API on/off, and real-Postgres E2E gates. Implementation TEST_REPORT.md maps every AT to evidence; no passing test claim in this planning doc.

## Acceptance tests

- **AT1 (R1)** Given all routes in a built SPA, when inspected at both target viewports, then shared token families/CSS Modules are used, bundled Inter loads without external font requests, dark surfaces/type hierarchy match the contract and no theme switch appears.
- **AT2 (R2)** Given home and each table route, when navigating by mouse and keyboard, then all six destinations are reachable, current page is marked, one h1 exists, and home shows only existing dataset refresh information and table links.
- **AT3 (R3)** Given all five table pages and a real Postgres fixture, when filtering, sorting and paging using existing controls/URLs, then columns and API results match F009, pager remains accurate and virtualization is retained under the restyle.
- **AT4 (R4)** Given delayed and then successful requests, when initially loading and refetching, then skeleton/busy/status behavior follows the state contract without fake data or duplicate announcements.
- **AT5 (R4)** Given zero results and an offset beyond total, when each response renders, then their distinct messages and clear/first-page actions work and do not invent results.
- **AT6 (R4)** Given list 400/503/network failure, metadata-only failure and unknown route, when rendered and retried, then correct messages, shell, editable filters and retry behavior remain; no traceback or stale-success presentation appears.
- **AT7 (R5)** Given 320px, 390px, 1440px and 200% browser zoom, when visiting all routes and opening mobile nav, then controls/footer remain usable, no document horizontal overflow occurs, and only the table region scrolls horizontally.
- **AT8 (R6)** Given keyboard-only input, when using skip link, desktop/mobile nav, filters, pager, Retry and scroll region, then all actions work, focus is visible/not trapped, disclosure Escape restores focus and route changes focus the h1. Record zoom/screen-reader-status hand checks.
- **AT9 (R1, R6)** Given each rendered text/control/focus/state token pair, when contrast is calculated and axe scans all stated route/state/viewport combinations, then required 4.5:1 / 3:1 thresholds and zero WCAG-tagged violations hold; reduced-motion mode removes transitions.
- **AT10 (R7)** Given every route, initial loading and cold metadata 503, when opened before API success, then exact nflverse text/links are present, failure reads `Last refresh: none`, and the drift test against Python constants passes. No RotoGuru line appears without historical salary display.
- **AT11 (R8)** Given implementation diff, frontend request inventory, bundle and real-Postgres boundary tests, when checked, then API shapes/status/headers/validation and allowlisted requests are unchanged, grants unchanged and private reads still denied. Existing API suite passes unchanged with SPA off/on.
- **AT12 (R9)** Given committed synthetic baselines, when visual CI runs twice in the pinned environment, then all listed route/state/viewport captures compare within threshold; an intentional >100-pixel fixture style change fails and yields synthetic-only diffs. Missing baselines fail rather than create themselves.
- **AT13 (R9)** Given CI configuration and TEST_REPORT.md, when reviewed and run, then visual/axe gates supplement every existing check, retain real-Postgres E2E, and evidence is mapped to each AT. Baseline updates occur only in reviewed PRs.
- **AT14 (R8)** Given SPA off, missing-build and pre-SPA DB-outage cases, when server fallback tests run, then F009 rollback, error copy, exact attribution and `/api/health` behavior remain unchanged without requiring redesigned Jinja templates.

## Non-goals

Light mode/theme persistence, new table interactions (F011), new routes/datasets/API fields, salary UI, optimizer controls, auth, imagery, remote fonts, charting, a new host, Jinja redesign, deployment or changing SERVE_SPA.

## Allowed dependencies

Existing React/TS/Vite, TanStack Table/Virtual/Query/Router and test tools unchanged. CSS Modules are built into Vite. Add only `@fontsource/inter` (runtime build asset, normal Latin weights only, self-hosted OFL font/license retained) and `@axe-core/playwright` (dev-only accessibility runner); exact resolved versions and lockfile required. No new UI framework, Tailwind, headless primitives, CSS-in-JS or icon package. Native controls and CSS suffice. See ADR 0010 for alternatives.

## Open questions

None. Dark-only, static navigation disclosure and local bundled typography are explicit technical defaults. The live Render setting is relayed context, not independently checked; no production setting change is part of this plan.

## ADRs

[0001](../../adr/0001-stack-and-hosting.md) as amended by [0008](../../adr/0008-react-frontend-hosting.md); [0002](../../adr/0002-nflverse-load-and-refresh.md) attribution; [0003](../../adr/0003-rotoguru-dk-classic-salaries.md) conditional historical attribution; [0004](../../adr/0004-dk-current-slate-csv.md), [0005](../../adr/0005-private-salary-capture-and-archives.md), [0006](../../adr/0006-slate-safe-salary-unification.md) privacy; Proposed [0010](../../adr/0010-frontend-design-system-and-visual-checks.md).

## Analyze pass

| Requirement | Tests |
|---|---|
| R1 | AT1, AT9 |
| R2 | AT2 |
| R3 | AT3 |
| R4 | AT4, AT5, AT6 |
| R5 | AT7 |
| R6 | AT8, AT9 |
| R7 | AT10 |
| R8 | AT11, AT14 |
| R9 | AT12, AT13 |

R1–R9 all covered; AT1–AT14 none orphaned; ADR/constitution conflicts none. The stack allows CSS Modules and bundled fonts; axe is dev-only. Screenshot route mocks supplement, not replace, real Postgres tests. No constitution amendment or data change. F009 appearance parity is intentionally replaced, not its privacy/API/hosting contract.
