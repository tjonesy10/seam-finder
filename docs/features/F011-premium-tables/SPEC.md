# F011: Premium table interactions

Status: **READY** (2026-11-10). Planning only. Depends on the [F010](../F010-visual-redesign/SPEC.md) implementation PR merged to main; do not start this build before that merge. Read against main `0ab6132`. Owner merges all PRs.

## Problem / job to be done

The five public tables have only single-column server sort, text filter forms and paging. Add precise, discoverable table controls on F010's visual foundation without changing the API or downloading whole datasets. Keep the scope honest: existing dataset filters/paging work across the dataset; new rich operations refine the current API page only.

## Requirements

- **R1** Apply one TanStack Table/Virtual interaction contract to all five existing tables. Preserve existing server dataset filters/single-sort/paging and route links. Clearly distinguish dataset controls from current-page controls; no implied dataset-wide multi-sort or search.
- **R2** Add controlled multi-column sorting (up to three priorities), deterministic null/tie behavior, visible direction/priority indicators, mouse and keyboard controls.
- **R3** Add per-column text filters, numeric range filters for points and other numeric measures, multi-select filters for team/position, plus global search. Apply them together with documented null/comparison rules. Salary range is conditional on a separately authorized public salary field; no salary control exists now.
- **R4** Add column show/hide and resizing, a sticky header and sticky first visible column, plus comfortable/compact density. Keep at least one column visible; all functionality is usable without dragging or a mouse.
- **R5** Format numbers consistently and add restrained conditional color scales to points columns without changing underlying values. Meet F010 contrast and non-color-only rules.
- **R6** Persist dataset filters, current-page filters, sort and paging in TanStack Router search params. Restore on reload/back/forward. Validate at the frontend boundary, ignore invalid values and fall back to defaults without rendering a URL-validation error. Keep raw API validation unchanged.
- **R7** Export CSV of the currently displayed logical row set and visible columns, in current sorted order, not just mounted virtual rows. Export only explicit public column fields; protect spreadsheet consumers and keep CSV machine-readable.
- **R8** Preserve exact attribution in all states, no private data access/exposure, unchanged web-role grants, API contracts and hosting. No salary endpoint, field, page, data source or optimizer UI is authorized.
- **R9** Keep virtual DOM bounded and interaction state correct through scroll, filtering, resizing and density changes, including the largest current column set and a 5,000-row synthetic component fixture.
- **R10** Extend F010's unit/E2E/visual/axe checks for interactions, mobile and keyboard use; record every AT in TEST_REPORT.md and keep existing backend/API/boundary gates.

## User stories

- As an analyst, I want to refine and compare rows on my current page, so that I can examine data without losing my dataset selection.
- As a viewer, I want to show useful columns and adjust density, so that wide tables fit my task and device.
- As a viewer sharing a link or exporting a page, I want the state and row scope to be explicit, so that another viewer does not mistake a page subset for the whole dataset.

## Observable behavior

### Data inventory and scope

Tables and lists are the six routes/five endpoints documented in [F010](../F010-visual-redesign/SPEC.md#existing-routes-and-unchanged-data), backed by [data-dictionary](../../data-dictionary.md). Public list shape stays `{data: row[], page: {limit, offset, total}}`; JSON numbers stay numeric, date/timestamp strings remain API originals, nulls stay null. `frontend/src/resources.ts` is the current explicit column inventory; unknown extra response keys are not rendered, searched or exported automatically.

- Teams: identity `team_abbr`; descriptive fields `team_name`, `team_nick`, `team_conf`, `team_division`, plus existing metadata columns.
- Players: show `display_name` first, retaining every other current column (including public identifier fields) in its prior relative order. Team=`latest_team`; position=`position` and `position_group`.
- Games: identity `game_id`; multi-selects on `away_team`, `home_team`; numeric game measures include scores, result, total, spread/total lines.
- Stats: show `player_display_name` first, retaining other columns in prior relative order. Teams=`team`, `opponent_team`; position=`position`, `position_group`; points=`fantasy_points`, `fantasy_points_ppr`; numeric production fields remain the current public nflverse measures.
- Load runs: identity `id`; numeric row counts; status/dataset/notes/error and existing source/timestamp fields stay public API fields, not private diagnostic expansion.

All existing columns are initially visible. No player names, identifier literals or real salary values are needed in public planning examples. Use synthetic fixtures only in visual artifacts.

No current API list or page exposes salaries or RotoGuru points. F003 `dk_salary`/`dk_points` exist in storage but have no public endpoint. Therefore salary range controls, salary scales and the RotoGuru line are not rendered in F010/F011. If a later approved feature exposes historical DK salaries, it must wire an explicit public-field allowlist, range filter and exact attribution; this plan is not that approval. Stats point controls use nflverse points, never relabel them DK.

### Dataset versus current-page controls

Keep the existing form under “Dataset filters”, existing server single-sort as labeled “Dataset order” field/direction selectors, page-size input (1–500), Previous/Next and server `rows {start}-{end} of {total}`. This preserves dataset-wide queries through the unchanged API, including old sort/order links. New header sorts do not rewrite dataset `sort`/`order`. Dataset filters reset offset to 0; dataset order/page size also reset offset to 0.

New toolbar says “This page” and permanently explains “Search, column filters, multi-sort and export apply to this page only.” Display “Showing {filtered} of {loaded} loaded rows” separately from server total; never claim the locally filtered count is a dataset total. No prefetch-all, API loops, hidden whole-dataset export or invented server multi-sort. Pagination fetches only the chosen API page with existing TanStack Query caching. Keep local filters/sorts when moving to the next API page; recompute them over the new rows. When dataset selection changes retain local preferences/filters, visibly list active filters, and offer “Reset this page” (local filters/sort/columns/widths/density defaults; dataset selection unchanged).

Initial/refetch/empty/error states follow F010. New local zero-result state: “No rows match on this page.” with “Clear page filters”; keep server pager available so another page is reachable. Export is disabled during pending/error data and when zero filtered rows; a text reason is available. A metadata-only error need not disable export of a successful public list. Never export retained stale rows after a failed list refetch.

### Sort/filter contract

Every current public column may be locally sorted. Header action cycles absent → ascending → descending → absent. Plain activation replaces other sorts; Shift+activation adds/changes a priority up to three. A labeled “Sort” panel provides equivalent keyboard/touch add/remove, direction and move-up/down controls; fourth add is disabled with an explanation. Indicators show priority number and direction. Set `aria-sort` on primary sort header; describe additional priorities in accessible text. No sorting when resize handles are used.

Compare raw numbers numerically (not formatted strings), booleans false before true, ISO dates/timestamps chronologically, other strings by fixed en-US case-insensitive comparison. Nulls are always last in either direction; final tie is existing stable resource row identity ascending. No randomized/client-locale tie breaks. Empty local sort preserves the server-provided row order.

Per-column controls appear from a labeled column filter button/panel:

- Team/position columns above: native checkbox multi-select of distinct non-null values on the loaded page. OR within a column, AND across columns; exact normalized uppercase match. A selected value not on a later page remains as a selected option/chip so it can be removed. Null option is a separate “Missing” checkbox.
- Numeric measures: inclusive min/max, either bound optional, finite signed decimal input, no currency/commas in input. Includes both points columns and numeric measure/count/year/week columns; identifiers that happen to be numeric (e.g. load-run `id`) are text/exact identifiers, not ranges. Null does not match a bounded range. Invalid/reversed typed bounds are not applied; show inline guidance and retain last applied values until corrected; this typed-input feedback is distinct from forgiving URL parsing.
- Remaining text/date/boolean/identifier columns: trimmed case-insensitive literal substring (no regex). Treat null as empty string. No raw HTML rendering. Maximum 100 characters per local text filter/search.
- Global “Search this page”: literal substring across the raw text of every explicit public column, including hidden columns (say so in helper text); one matching column suffices. Use raw scalar string forms, not rounded values; null is empty. Apply after dataset query, alongside all column filters, then local sort. Debounce text 250ms; Enter applies immediately. Multi-select/range Apply commits immediately. Hidden column filters remain active, with named removable chips; no invisible filter state.

### Column layout, density and formatting

Column chooser lists every current field with readable labels and field-key helper text, a Reset columns action, and blocks hiding the last visible column. Hiding a sorted/filtered column keeps its state and shows it in sort/filter summaries. No arbitrary column reorder UI. First visible column sticks to the inline start, header sticks at top of the same named scroll region, intersection has highest stacking order and opaque F010 surface; they must not cover focused controls/content.

Initial width 160px, name/notes/error 240px, minimum 96px, maximum 480px; user width stored as integer CSS px. Pointer drag and focusable separator with Left/Right ±16px, Home resets that column; labeled width number input provides touch/keyboard equivalent. Resize after drag end is acceptable; no dependency needed. Long values have keyboard-accessible wrap/details control or selectable full-value disclosure, not hover-only tooltips.

Comfortable (default): row height 44px; compact: 32px. Body row height is fixed and passed to the virtualizer; no wrapping inside virtual body. Controls remain at least 44px targets even in compact mode (outside row body where necessary). Density recalculates virtual measurements and keeps scroll anchored by stable row identity where possible. Header height may be larger than body rows.

Use en-US display formatting and right-aligned tabular numerals. Counts/yards/years/weeks are integers (years/weeks ungrouped; counts/yards grouped); points and spread/total lines show two decimals; target_share shows percent with one decimal. IDs stay ungrouped text; booleans show true/false; null is an em dash with accessible “Missing”. Dates remain date strings; timestamps display America/New_York with ET label, not viewer-local time. Do not derive new fantasy scores. Sorting/filtering/export use raw values, never rounded display strings.

Conditional color scales apply only to the two stats points columns: compute min/max across filtered logical rows on this page, diverge around zero when signs differ, otherwise low-to-high neutral/teal backgrounds; zero-range/all-null yields neutral. Text still shows signed numeric value and column header/legend explains “Points intensity, relative to this page”. Every cell text/background pair is >=4.5:1; no red/green-only meaning or “higher is always better” claims for turnovers. No scales for IDs, dates or unknown numeric fields. Under forced colors remove decorative backgrounds and retain values/legend.

### URL schema and API separation

Reuse existing TanStack Router `validateSearch` / URLSearchParams pattern, not localStorage or a second router. Browser-only `ui_*` params NEVER go to the API; construct dataset requests from the per-resource positive filter allowlist plus valid `sort`, `order`, `limit`, `offset`. This is necessary because the current API rejects unknown params.

| Param | Encoding / default |
|---|---|
| Existing route filter names | F010 route table; absent=no filter. Trim. `season`: integer 1999–2100; `week`: 1–22; `season_type`: REG/POST case-normalized; team: 2–3 letters uppercase; position: 1–5 letters uppercase; `q`: 2–50 characters; remaining existing bounded text <=64 characters. Same valid semantics as `web/params.py`. |
| `sort`, `order` | Existing resource server sort allowlist/default (F010 table), asc/desc; dataset order only. |
| `limit`, `offset` | Decimal integer 1–500/default 50; 0–2147483647/default 0. Server pagination only; no extra local page index. |
| `ui_sort` | Percent-encoded JSON array of `{id: columnKey, desc: boolean}`, ordered priorities, max 3. Default `[]` (server order). |
| `ui_filters` | Percent-encoded JSON object keyed by public column key. Text: `{kind:"text",value:string}`; range: `{kind:"range",min:number|null,max:number|null}`; multi: `{kind:"multi",values:string[],missing:boolean}`. Default `{}`. Keys/kinds must match column metadata; dedupe/sort multi values, max 64 values per column. |
| `ui_search` | Percent-encoded text <=100 characters, default empty. |
| `ui_hidden` | Percent-encoded JSON array of distinct column keys, default `[]`. If it hides all columns discard it. |
| `ui_widths` | Percent-encoded JSON object of column key to integer px 96–480; default `{}` (initial widths above). |
| `ui_density` | `comfortable` (default) or `compact`. |

JSON is serialized compactly, field keys lexically sorted except ordered sort entries; use URLSearchParams once (not double encoding). Omit defaults/empty entries when writing URLs. Unknown params ignored/dropped on next write; duplicate top-level keys use last occurrence, matching existing router behavior. Malformed JSON/wrong outer type resets that param; unknown column keys/wrong-kind entries are ignored individually; invalid/reversed ranges are ignored as one entry; invalid sort entries are dropped, duplicates keep first, valid entries beyond 3 discarded. Invalid text length uses default empty, not truncation; invalid width entries use column default. Invalid scalar values fall back independently without erasing valid unrelated state. Blank ranges/empty multi (missing=false) mean no filter. Canonicalize via replace only when normalization is needed; no redirect loops/history pollution. User Apply/sort/page/column actions create history; intermediate typing/resizing updates replace history until committed.

Reload/back/forward restores all this state, including visible-column widths and density. Reset page state leaves dataset params intact; route navigation starts target route defaults unless following an explicit stateful link. Query cache keys contain ONLY normalized dataset params, so local controls cause no extra API calls.

This intentionally changes F009's SPA bad-URL example: `/games?week=abc` now ignores invalid week and loads default games instead of issuing a 400. It does NOT change raw `/api/games?week=abc`, which still returns the original HTTP 400/message. Update only frontend expectations for this specified behavior, retain unchanged `tests/test_api.py` with both SERVE_SPA modes, and Jinja rollback parameter errors. An unexpected API 400 still renders its existing message in F010 chrome.

### CSV contract

Button label “Export this page CSV ({filtered row count})”. Filename `seam-finder-{route-slug}-{YYYYMMDD-HHmmss}-ET.csv` using America/New_York time; stats slug=`stats`, load-runs=`load-runs`. UTF-8 without BOM, comma delimiter, CRLF records, one header row of raw field keys in visible order, then every locally filtered/sorted row on the current server page, including virtualized off-screen rows. No hidden columns, unchecked response keys, all-pages fetch or private sources. Snapshot row/column state at click to avoid mixed downloads during subsequent edits.

RFC 4180 escaping: fields containing commas, double quotes, CR or LF are double-quoted; internal quotes doubled. Serialize raw finite numeric values in plain decimal, booleans true/false, null empty, strings unchanged, timestamps/date strings as API returned (not UI formatting). Formula injection guard applies to every cell including headers and numeric negative values: if its serialized text begins with `=`, `+`, `-`, `@`, tab, CR or LF, or the first non-whitespace character is one of `= + - @`, prefix an ASCII apostrophe before RFC escaping. This conservative rule deliberately makes negative spreadsheet cells text; it does not alter source values. Test that tradeoff, do not silently waive it for numeric fields.

No attribution comments, metadata rows, summary/trailing rows or appended JSON: keep CSV clean. Exact nflverse attribution remains visible next to the export action via the page footer with a nearby attribution anchor link. No historical salary export is included. Any future salary export needs its own rights/attribution decision; page-only attribution here does not preapprove it. Use a local Blob/download and revoke its URL after use; do not upload CSVs or add an export endpoint.

### Attribution, safety and tests

Inherit F010's exact static nflverse text, links, drift test, Eastern refresh label/failure fallback and conditional `ROTOGURU_DK_CLASSIC_ATTRIBUTION` rule, unchanged. No `salary_private` reads, no F004/private salary fields, no grants changes, no new API, backend query, auth, host, dashboard setting or production actions. Explicit public fields only in rendering/search/export.

For virtualization evidence, test both densities at desktop/mobile with a 5,000-row synthetic component fixture using the stats column set (largest current table by column count). At 512px body viewport and overscan 8, at most 80 mounted data rows (exclude spacer rows), including after scroll to end, sorting, filtering and density change; last logical row reachable, stable identities preserved, no gaps/overlap. Real API pages remain bounded to 500 rows. This is a DOM bound, not a claim of measured FPS or full-dataset performance.

Extend F010 pinned Chromium visual baselines with representative stats desktop/mobile captures: sorted/filtered toolbar and chips, column chooser, resize control, both densities, and horizontally/vertically scrolled sticky intersection. Use small synthetic route mocks and same 100-pixel/0.2 comparison tolerance. Axe scans these interactive states; manual keyboard/touch/forced-color checks supplement. Keep real-Postgres routes/API/grant tests and all existing CI steps; no runtime mocks or weakening API tests. Record per-AT evidence in TEST_REPORT.md.

## Acceptance tests

- **AT1 (R1)** Given each of the five public routes with two server pages, when dataset filter/order/size/pager controls change, then the original API query semantics hold, offset resets where specified, local operations remain labeled current-page-only, and server/local counts are separate. No all-pages/background fetch occurs.
- **AT2 (R2)** Given synthetic tied numeric/text/null rows, when header/Shift sorts and equivalent Sort-panel actions add, reorder, remove and try a fourth priority, then max-three stable priorities, null-last behavior and indicators match the contract and keyboard produces identical row order.
- **AT3 (R3)** Given stats points rows including null and signed values, when applying one-sided/two-sided ranges, text, team and position selections together, then inclusive ranges, OR-within/AND-across and literal matching work; invalid typed ranges retain last applied values with guidance. No salary filter or DK points label is rendered.
- **AT4 (R3)** Given hidden filtered columns and a selection absent on the next page, when searching/removing chips/moving pages, then global search includes hidden public columns, selections remain removable, row counts recompute and local-empty clear action retains server paging.
- **AT5 (R4)** Given column chooser and all-hide attempt, when toggling/resetting columns, then at least one remains visible, sorted/filtered hidden fields remain disclosed and sticky first column updates. Every current public field remains available.
- **AT6 (R4, R9)** Given long/wide data at both densities, when resizing by drag/separator keys/width input and scrolling on desktop/mobile, then bounds, opaque sticky header/first-column intersection, unclipped focus, full-value access and virtual measurements remain correct.
- **AT7 (R5)** Given counts, years, points, ratios, nulls, identifiers and timestamps, when rendered, then formatting follows metadata without modifying raw values; points scales keep numeric text, neutral edge cases, a page-relative legend, AA contrast and forced-color readability.
- **AT8 (R6)** Given a URL containing every valid dataset/UI state shape, when reloading, navigating pages and using back/forward, then state, column widths/density and identical row order restore; local changes issue no API requests and no `ui_*` field reaches an API URL.
- **AT9 (R6)** Given malformed JSON, unknown/duplicate keys, invalid scalar bounds, wrong column kinds, all-hidden state and reversed ranges, when opening each URL, then specified defaults/entry-dropping occur without a page error or redirect loop and valid unrelated state survives. `/games?week=abc` loads defaults; raw API bad week still returns unchanged 400.
- **AT10 (R7)** Given filtered/sorted data larger than the virtual viewport and hidden columns, when exporting, then download contains exactly the logical current-page filtered rows in sort/visible-column order, correct header/filename/CRLF/UTF-8, raw precision, and no extra attribution/comment rows or unlisted response fields.
- **AT11 (R7)** Given synthetic comma/quote/newline/formula/tab/whitespace-prefixed cells, negative numbers and null, when exporting and parsing with an RFC 4180 reader, then escaping and apostrophe guards match the contract including negative numeric text; source objects remain unchanged. Pending/error/zero-row lists cannot export stale data.
- **AT12 (R8)** Given every route/interactive/error/loading state and metadata outage, when checked, then exact F010 attribution/links/fallback remain and Python drift test passes; no salary UI/RotoGuru line appears, no private requests/data are exposed, and real-Postgres grants/boundary tests and unchanged API on/off suite pass.
- **AT13 (R9)** Given 5,000 synthetic rows and current widest stats columns at 512px body viewport, when testing both densities/viewports through scroll/end/filter/sort/resize, then <=80 data rows mount, last logical row is reachable, stable identity persists and no gaps/overlap appear. On real routes no request exceeds limit 500.
- **AT14 (R10)** Given F010 visual CI and committed synthetic interaction baselines, when all specified interaction/viewport captures and axe scans run, then screenshot tolerance and zero tagged accessibility violations hold; deliberate visual regression fails without automatic baseline update, and all prior CI gates remain.
- **AT15 (R4, R10)** Given keyboard-only, touch-width, reduced-motion and forced-color modes, when operating sort/filter/chooser/resize/density/export and mobile nav, then controls have labels/targets, focus is visible/restored on panel dismissal, no drag/hover/Shift-only action is required, and horizontal overflow stays inside table regions. Record hand-check evidence.
- **AT16 (R1, R8, R10)** Given implementation review and TEST_REPORT.md, when comparing to F009/F010, then only planned frontend URL-error expectations change, raw API/Jinja behavior and all existing backend gates remain intact, every AT has evidence and no deploy/configuration change is claimed.

## Non-goals

Dataset-wide client multi-sort/global search, fetching all rows, a new data API, salary display/export, charts, lock/exclude/optimizer controls, column reorder UI, saved accounts/localStorage preferences, backend changes, extra runtime dependencies or deployment. A later dataset-wide feature needs a separately planned efficient query contract, not hidden client crawling.

## Allowed dependencies

Existing React/TS/Vite and TanStack Table/Virtual/Query/Router; F010 CSS Modules/tokens/bundled font; existing Vitest/Testing Library/Playwright plus F010 dev-only axe. Use current installed TanStack interfaces (the repo currently uses Table's legacy adapter); no major-version migration required. Native inputs/checkboxes/disclosures and local CSV serialization; no new package or heavy UI framework.

## Open questions

None. Current-page-only refinement resolves rich interactions under the unchanged single-sort paginated API and bounded free-tier scope. Keep the scope label always visible; do not market it as dataset-wide. Historical salary controls are inapplicable, not blocked work.

## ADRs

[0001](../../adr/0001-stack-and-hosting.md) as amended by [0008](../../adr/0008-react-frontend-hosting.md); [0002](../../adr/0002-nflverse-load-and-refresh.md) attribution; [0003](../../adr/0003-rotoguru-dk-classic-salaries.md) conditional historical attribution; [0004](../../adr/0004-dk-current-slate-csv.md), [0005](../../adr/0005-private-salary-capture-and-archives.md), [0006](../../adr/0006-slate-safe-salary-unification.md) privacy; Proposed [0010](../../adr/0010-frontend-design-system-and-visual-checks.md).

## Analyze pass

| Requirement | Tests |
|---|---|
| R1 | AT1, AT16 |
| R2 | AT2 |
| R3 | AT3, AT4 |
| R4 | AT5, AT6, AT15 |
| R5 | AT7 |
| R6 | AT8, AT9 |
| R7 | AT10, AT11 |
| R8 | AT12, AT16 |
| R9 | AT6, AT13 |
| R10 | AT14, AT15, AT16 |

R1–R10 all covered; AT1–AT16 none orphaned; ADR/constitution conflicts none. No amendment/data change. Browser-only validation explicitly replaces F009 SPA bad-URL behavior, not API validation or real-Postgres coverage. Page scope avoids unapproved API expansion; no salary source is newly exposed. Build only after F010 merges.
