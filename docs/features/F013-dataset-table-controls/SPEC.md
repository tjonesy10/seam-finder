# F013: Dataset-wide table controls

Status: **READY** (2026-11-11 America/New_York). Planning only, based on main `f5324a4` and [F011](../F011-premium-tables/SPEC.md). Build separately after BOTH F011 and [F012](../F012-dataset-query/SPEC.md) implementations merge. Owner merges. No production action.

## Problem / job to be done

Make F011 controls useful across all matching public rows without silently changing old page-scoped URLs. Reuse its interaction and layout components; F012 provides server queries. Keep one explicit active scope, honest counts and page-only export rather than layering invisible local filters over server results.

## Requirements

- **R1** Provide explicit page/dataset scope on every public table, retaining F011 behavior and old URL meaning in page mode; no simultaneous hidden local refinement in dataset mode.
- **R2** Map normalized sort/filter/search state to F012 server params in dataset mode, using identical endpoint column/operator registry and bounded positive API serialization.
- **R3** Use manual server sorting/filtering/pagination in dataset mode, accurate dataset totals and existing virtual/layout/formatting controls without fetching all rows.
- **R4** Persist scope/query/layout/paging via Router, handle invalid URLs safely and restore back/forward; do not silently turn a page filter/search into a different dataset predicate.
- **R5** Bound requests with debounce/cancellation, stable cache keys and no automatic failure retry; preserve usable empty/error/loading/keyboard/mobile behavior.
- **R6** Keep only F011 formula-guarded visible-column page CSV; label its scope independently from dataset controls and disable unsafe/stale export.
- **R7** Preserve exact attribution, public/private boundaries, grants and F010 a11y/visual contract; no salary fields or dataset export.
- **R8** Extend unit/real-API E2E/visual/axe evidence for scopes without weakening prior backend or virtualization gates; record every AT in TEST_REPORT.md.

## User stories

- As an analyst, I want column filters and multi-sort before pagination, so that matches elsewhere in the dataset are not missed.
- As a viewer opening an older shared link, I want its page-scoped meaning retained, so that a number/identifier search is not silently lost.
- As a viewer exporting visible rows, I want page-only labeling even while dataset filtering, so that a small file is not mistaken for all matches.

## Observable behavior

### Modes and labels

Keep the six routes/five endpoints from F010 and [data dictionary](../../data-dictionary.md), with all current columns. Add labeled native selector/radio group “Refinement scope”: “This page” / “All matching rows”. Browser-only `ui_scope=page|dataset`; absent/invalid=>page, preserving all existing URLs including bare routes. After F013 new app-nav/home table links explicitly include `ui_scope=dataset` (route links that already carry query state preserve it); a viewer can still choose page mode. No localStorage or implicit migration.

Page mode is exactly F011: existing Dataset filters/order/pager plus “This page” controls, search across all explicit public scalars, separate filtered/loaded count and current-page CSV. No new API params in this mode. Existing page state never becomes dataset-wide merely on reload.

Dataset mode toolbar: “All matching rows”; helper “Sort and column filters apply before pagination. Search covers the listed text columns, including hidden columns. Export still contains this page only.” Display the endpoint's exact F012 global search column labels in a disclosure available to keyboard/touch; no claim all columns are searched. Remove “Showing {filtered} of {loaded} loaded rows”, local-empty copy and “Reset this page” from query controls. Show server `rows {start}-{end} of {total}` and “{total} matching rows”. Rename search “Search all matching rows”; Reset query clears rich filters/search/sorts and offset, leaving existing dataset form filters and layout alone. Separate “Reset layout” clears visibility/widths/density only.

Retain existing dataset form filters, visibly labeled “Dataset selection” with active summary; they AND with rich filters and are independently removable, even if contradictory on one column. Retain legacy Dataset order selectors only as fallback when advanced sort list is empty; disable with explanation while header/panel sorts are active, rather than letting a hidden legacy sort compete. Every dataset selection/order/limit/rich sort/filter/search change resets offset=0. Pager alone preserves query state and changes offset.

### State mapping and switching

Continue F011 `ui_sort`, `ui_filters`, `ui_search`, `ui_hidden`, `ui_widths`, `ui_density`. The new `ui_scope` is frontend-only. Do not rename F011 state during its active build. F013 maps on the request boundary:

| Browser state | Dataset API serialization |
|---|---|
| Existing per-resource dataset form filters, `sort`, `order`, `limit`, `offset` | Same positive allowlist/legacy normalization as F011; never spread the browser query into a request |
| `ui_sort` | `sorts` JSON with identical ordered `{id,desc}` entries; always send `sorts=[]` when empty to opt into advanced semantics |
| `ui_filters` | `filters` JSON after F012 typed validation; omitted text op becomes explicit `contains`; omit empty object |
| `ui_search` | `search` trimmed text when nonblank |
| `ui_scope`, `ui_hidden`, `ui_widths`, `ui_density` and all other `ui_*` | NEVER sent to API |

Dataset field/kind metadata matches the exhaustive F012 registry; do not infer from response keys. A few fields change filter kind versus F011 (conference/division/status/dataset/draft_team become multi); page-mode metadata stays unchanged. Dataset text controls add a labeled contains/equals selector and optional `op` member; page mode never serializes equals into the local comparator (its only text operation remains contains). Numeric comparisons use raw values, null-last sorts are server authoritative and may differ from JS collation. Helper: “Text matching and ordering use the database locale.”

Switching scope clears rich `ui_sort`/`ui_filters`/`ui_search` and offset, retaining dataset selection/fallback order/limit and layout. Before switching with active rich state, show inline confirmation “Changing scope resets search, column filters and multi-sort.” with Continue/Cancel; Cancel changes neither URL nor requests. This explicit reset avoids semantic loss. Additionally offer “Apply these page controls to dataset” only when the complete active page state is representable: <=16 filters; all column kinds compatible; F012 numeric/text/multi bounds; empty page search (nonempty all-scalars search is NOT equivalent). Explain incompatible fields/search by labels and require clearing them first; never drop entries or approximate search. This action copies equivalent state, sets dataset scope and offset=0, one history action; M case normalization/server locale difference is disclosed. It must not auto-run from a URL migration.

Dataset multi-select options contain current loaded page values plus all active selections, with “Add value” text input/checkbox list to select values not loaded yet. Helper: “Suggestions are from this page; type another value to search the dataset.” No suggestion is advertised as an exhaustive facet. Missing checkbox remains separate; no new distinct-values endpoint or API crawl. Values follow F012 <=64 bound; selected absent values remain removable. Max 16 active column filters; disable further Apply with explanation. Range/typed invalid state retains last applied query with inline feedback.

### URL and request behavior

Reuse F011 compact JSON/URLSearchParams-once, canonical sorted filter keys and ordered sort array; defaults omitted except scope in explicitly dataset links. Page mode parsing remains exactly F011. In dataset mode validate F012 kinds/operators/size; malformed outer JSON resets that param, invalid entries drop individually with a visible “Some table settings were reset” notice if meaningful query state was lost. Invalid `ui_search` resets to empty, not truncation. Unknown browser keys drop on next write. Duplicate browser scalar keys use last occurrence as before. Browser `sorts`/`filters`/`search` are not accepted state aliases: only `ui_*` owns rich state, preventing two competing sources. Raw API remains strict 400.

If a dataset URL exceeds 16 active filters, the 8192 decoded-new-value budget, or the serialized complete API URL exceeds 7500 UTF-8 bytes, reset rich query state as a unit, offset=0, notify with the same reset notice and preserve layout/valid legacy selection. Do not automatically send an oversized query. Interactive Apply over these bounds is blocked with an inline reason, retaining last applied values; do not silently truncate. This conservative browser URL bound is below common proxy limits, not a guarantee about every deployment.

History follows F011: committed actions push, intermediate typing/resize replace; back/forward/reload restores scope/query/layout/pager without loops. Dataset cache keys include endpoint + normalized legacy params + sorts/filters/search, never layout. Page keys include only legacy params. Switching scope must not reuse a legacy cached page as authoritative advanced data.

Dataset text/search debounce 250ms, Enter applies immediately; multi/range/sort apply immediately. Pass cancellation signal through existing request layer; cancel superseded fetches, and ignore stale completion/error from an older key. Query only chosen page, limit<=500; no all-pages prefetch, per-keystroke facets or endless polling. Disable automatic TanStack Query retries for timeout/busy/400 and other list failures in dataset mode; Retry is a deliberate action. Avoid refetch-on-focus storms (dataset mode refetchOnWindowFocus=false); set dataset-list staleTime=300000ms; leave page-mode caching unchanged. This supplements API caching, not a promise of refresh-fresh snapshots.

Set table to manual sorting/filtering/pagination in dataset mode; remove local sorted/filtered row-model transforms from that path. The core/virtual row model renders API rows in API order. No second client pager. Layout/visibility/resizing/sticky header/column/density/number formatting remain F011. Points color scales remain relative to the returned page, not dataset-wide; retain the page-relative legend. Export includes the successful returned page's visible columns, never a locally resorted/filtered alternative.

Initial/refetch/error follow F010. Empty total=0: “No results for these filters.” with rich reset plus explicit dataset-selection clear action. Offset>=total>0: “No rows on this page.” with First page, preserving selection. Show query_timeout/query_busy messages from F012 with Narrow filters and/or Retry; no stale-success count or stale export. Pending/refetch disables export until current-key success. Keep controls editable, static attribution visible, status announcements once, focus retained on committed control and returned after panel dismissal.

### CSV, safety and evidence

Button always “Export this page CSV ({returned row count})” in dataset mode. Snapshot only current successful rows/visible columns, <=500, including virtual offscreen rows, in API order. Follow F011 filename/ET timestamp, UTF-8/no BOM, CRLF, raw values, RFC 4180 quoting and apostrophe formula guard including negative numeric text. No hidden/unlisted fields, attribution/comment rows, dataset-export button or extra fetch, even when total<=500. Disabled for pending/error/zero rows; metadata-only error does not invalidate successful list data. Keep attribution anchor nearby.

Exact static text/links/fallback are inherited unchanged from F010 and fully quoted in F012. Every scope/loading/error/empty route retains them; no historical salary display means no RotoGuru line. No salary_private/salary data/API expansion, grants, hosting/cutover or runtime dependency change.

Extend pinned F010/F011 synthetic visual baselines for dataset sort/filter chips, missing/multi input, narrow-search disclosure, scope-switch confirmation, reset notice and timeout/busy states, desktop 1440x1000/mobile 390x844. Same 0.2/100-pixel threshold, axe zero tagged violations, keyboard/touch/forced-colors checks. Real FastAPI/Postgres E2E proves rows not loaded in the first page can become first matches after server controls. Keep F011 5,000-row/<=80 mounted-row component checks, all legacy API on/off, backend/grant gates and per-AT TEST_REPORT evidence. Do not publish real records/screenshots/private data in artifacts.

## Acceptance tests

- **AT1 (R1, R4)** Given old F011 URLs/bare routes and new explicit dataset links on all tables, when opened/switched/reloaded, then page URLs retain prior semantics, dataset links use all-matching scope and scope confirmation Continue/Cancel resets or preserves state exactly.
- **AT2 (R2)** Given each valid sort/filter/search kind plus legacy dataset filters, when dataset mode serializes, then request matches F012 grammar, empty sorts opts in, layout/ui_* never reaches API, and all columns/kinds match fixed registries.
- **AT3 (R3, R8)** Given real Postgres data with desired matches beyond page one, when range/multi/text/search and three sorts apply, then server-wide matches/totals/order appear without client reordering/filtering, no fetch-all and limit<=500.
- **AT4 (R4)** Given compatible page controls and incompatible kind/global-search cases, when explicit transfer is attempted, then only complete representable state transfers with offset=0 and disclosure; incompatible state is explained, never silently dropped or reinterpreted.
- **AT5 (R2, R5)** Given absent-on-page selections, missing values, >64 options/>16 filters and invalid typed bounds, when using dataset filters, then type-add/current-page suggestions and removable selections work, bounds give inline feedback and last applied query survives.
- **AT6 (R4)** Given malformed/duplicate/unknown URL state and UTF-8/encoded length boundaries, when parsed/reloaded/back/forward, then safe independent defaults or prescribed whole-query reset/notice occur, canonicalization has no loops and oversized requests never send; raw API bad params still 400.
- **AT7 (R3, R5)** Given delayed overlapping queries and timeout/busy/400/503, when typing rapidly/Enter/applying/paging/focusing/retrying, then debounce/cancellation/cache keys prevent stale result/count overwrite and refetch/retry storms; errors remain editable and export disabled until current success.
- **AT8 (R3, R5)** Given total=0 and offset beyond positive total, when displayed/reset/first-page is used, then exact dataset counts/copy/offset semantics hold, all applicable filters are visible and no old local-filter count/empty state appears.
- **AT9 (R6)** Given >one page, hidden columns, virtual rows and spreadsheet-dangerous synthetic cells, when exporting in dataset mode, then precisely the returned page/visible columns/API order and F011 guard/format/filename hold with zero extra requests or attribution rows; stale/pending/error export is blocked.
- **AT10 (R3, R7)** Given both scopes and every route/state with metadata outage, when formatting/scaling/attribution/privacy tests run, then page-relative scale remains honest, exact text/links/fallback persist, no salary/RotoGuru display occurs and grants/private boundaries stay intact.
- **AT11 (R5, R7, R8)** Given desktop/mobile/keyboard/forced-colors and specified interaction/error states, when pinned visual/axe/hand checks run, then labels/targets/focus/status and existing comparison thresholds pass; deliberate visual regression fails without auto-updating baselines.
- **AT12 (R8)** Given CI/TEST_REPORT and the 5,000-row component fixture, when reviewed/run, then <=80 mounted rows at both densities and all prior real-Postgres/backend/frontend gates remain, every AT has evidence and no production action is claimed.

## Non-goals

Dataset CSV/facets, API/schema/index changes (F012), automatic migration of old global search, simultaneous local+server refinements, new packages, salary/optimizer UI, auth, deployment. No F011 in-flight scope expansion required.

## Allowed dependencies

Existing React/TypeScript/Vite and TanStack Table/Virtual/Query/Router, F010 CSS Modules/tokens/font, existing unit/Playwright/axe tools. Native controls and existing CSV code only. No new framework/package.

## Open questions

None. Page/dataset coexistence and explicit resets avoid silent semantic changes; limited suggestions plus typed values avoid a facet endpoint. Production rollout gates are not clarification markers.

## ADRs

F012's applicable accepted stack/attribution/privacy ADRs, [0008](../../adr/0008-react-frontend-hosting.md), Accepted [0010](../../adr/0010-frontend-design-system-and-visual-checks.md), Proposed [0011](../../adr/0011-public-dataset-query-grammar.md). Extends F011 only in opt-in dataset mode; page-mode acceptance remains intact.

## Analyze pass

| Requirement | Tests |
|---|---|
| R1 | AT1 |
| R2 | AT2, AT5 |
| R3 | AT3, AT7, AT8, AT10 |
| R4 | AT1, AT4, AT6 |
| R5 | AT5, AT7, AT8, AT11 |
| R6 | AT9 |
| R7 | AT10, AT11 |
| R8 | AT3, AT11, AT12 |

R1–R8 covered; AT1–AT12 none orphaned. Constitution/all ADRs checked: approved frontend stack, public-only data, exact attribution, unchanged grants/hosting, real-Postgres evidence; no conflicts/amendment. Sequence F011 merge -> F012 build/merge -> F013 build/merge, owner-approved rollout separately.
