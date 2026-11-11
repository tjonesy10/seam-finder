# F011 premium tables test report

Date: 2026-11-11. Branch `cursor/f011-premium-tables-1db1`, from main `f5324a4` (F010 PR #34 merge). Frontend only. No API, schema, grant, Render, secret, or `SERVE_SPA` change. No salary UI. No conflict with SPEC.md: the four follow-up seams keep the spec's `ui_*` names, page-only refinement, and public CSV scope.

## Seams

| Seam | Where |
|---|---|
| `ui_sort` / `ui_filters` / `ui_search` encoding, and stripping `ui_*` before the API | `frontend/src/pageState.ts` (`writeTableState`, `listRequest`) |
| Page-only sort/filter/search adapter. `DataTable` stays manual and does not call it | `frontend/src/refine.ts` (`pageManualRows`, `pageExport`) |
| Scope, count, helper, and export labels. Export reads the last successful page | `frontend/src/tableCopy.ts`; `PremiumTable` export uses `successfulRows` |
| Explicit column field and kind. Dataset filters stay a separate allowlist | `frontend/src/columns.ts`; dataset filters remain `frontend/src/resources.ts` |

## Results

| AT | Result | Evidence |
|---|---|---|
| AT1 | PASS | Vitest `premium.page.test.tsx` shows the scope sentence, separate "Showing m of n loaded rows" and `rows start-end of total`, and no extra `/api/player-week-stats` fetch after a local sort. `ui_*` is absent from those URLs. `listRequest` test checks the query key is only the dataset search. |
| AT2 | PASS | `refine.test.ts` covers null-last numeric order, identity tie A before B, the three-priority cap, and panel move/remove. The page test Shift-adds Week and disables a fourth add in the Sort panel. Header and panel share `cycleHeaderSort` / `addSort`. |
| AT3 | PASS | `refine.test.ts` checks inclusive ranges, OR within team/position, AND across columns, and literal text. The page test rejects a reversed typed range, keeps the previous rows, then applies min 1. No salary control and no DK points label: body text has neither "salary" nor "RotoGuru". |
| AT4 | PASS | Page test hides Player display name, searches "Alpha" (the name is not on screen), keeps the removable search chip on the next server page, shows "No rows match on this page.", and Clear page filters leaves `offset=50`. |
| AT5 | PASS | Column chooser lists field keys. Hiding the name keeps the row and the search. `columns.ts` still lists every current public field. Sticky first cell is the first visible column because hidden columns are not rendered. |
| AT6 | PASS | `virtual.test.tsx` resizes Player display name with ArrowRight to 256 and Home back to 240, at both densities, with mounted rows still <= 80. Long values use a "Full value" button that opens a dialog outside the row. Sticky header and first column use opaque `--color-surface` (`DataTable.module.css`). |
| AT7 | PASS | `format.test.ts`: grouped integers, ungrouped years, two-decimal points and lines, one-decimal percent, em dash plus accessible "Missing", identifiers ungrouped, ET timestamps. Points scale contrast against `#e8eef7` is >= 4.5:1 for every scale swatch. Zero-range and null stay unpainted. Legend text is "Points intensity, relative to this page". Forced-colors CSS clears the decorative background. |
| AT8 | PASS | Page test reloads compact density, width 320, and ascending standard scoring from the URL, then Back restores compact. Local sort does not add an API request. `datasetQuery` / `listRequest` omit every `ui_*` key. |
| AT9 | PASS | `pageState.test.ts` drops malformed JSON, unknown keys, wrong kinds, reversed ranges, over-long text, all-hidden columns, and invalid scalars, and keeps season 2024 plus a valid week range and width. `/games?week=abc` in Vitest and Playwright loads games and does not send `week`. `request.get("/api/games?week=abc")` is still HTTP 400. |
| AT10 | PASS | `csv.test.ts` checks header keys, visible columns only, CRLF, no BOM, no attribution row, and filename `seam-finder-stats-20261110-120000-ET.csv`. The page test exports three sorted rows and the file starts with `player_display_name`. `pageExport` uses the passed loaded rows and the visible key list. |
| AT11 | PASS | `csv.test.ts` parses comma, quote, CR/LF, formula, tab, spaced `=`, negative `-2.5` as `' -2.5` text, null, and false. Source objects are unchanged. Export is disabled with "Export is unavailable because the list failed." on a 503, and the button count is disabled at zero filtered rows. |
| AT12 | PASS | Attribution text and both links stay on the page tests, the 503 export test, and integration `pages.spec.ts`. `pytest` includes `tests/test_spa.py::test_attribution_bundle_matches_web_attribution` in the 292 passed. No RotoGuru line. `tests/test_api.py` passed 12 with `SERVE_SPA` unset and 12 with `SERVE_SPA=true`. |
| AT13 | PASS | `virtual.test.tsx`: 5,000 synthetic stats rows, 512px client height, overscan 8, both densities, after scroll to `P4999-2026-14`, sort, team filter, and resize. Mounted `[data-row-id]` count stays <= 80, starts meet previous ends, and padding plus row heights equals `data-virtual-total`. Real routes still use limit 1–500. |
| AT14 | PASS | Ubuntu 24.04.5, `npm run e2e:visual` passed twice (14 tests each) after the baseline update. Threshold stays 0.2 and `maxDiffPixels` 100. New synthetic shots: `stats-refined`, `stats-columns`, `stats-compact`, `stats-sticky` at both viewports. Axe WCAG 2.1 A/AA violations were zero on those states. |
| AT15 | PASS | `e2e/keyboard.spec.ts`: skip link, Filter (exact), Next, table region, Menu Escape, 320px document overflow false, reduced motion. Forced-colors test keeps the points legend and a `fantasy_points` cell. Sort, filter, chooser, resize keys, density, and export are covered by the Vitest page and virtual tests. No hover-only action. |
| AT16 | PASS | Raw API and Jinja are untouched. The only frontend URL-behavior change is the spec's forgiving `/games?week=abc`. `tests/test_spa.py` still requires `DataTable` in `frontend/src/*.tsx` and `useQuery` in `pages.tsx`. This report maps AT1–AT16. No deploy or configuration change. |

## Baseline updates

Home, home-outage, and not-found snapshots were not regenerated. These changed because the table chrome now includes the dataset fieldset, the "This page" toolbar, and 44px comfortable rows:

- `teams`, `players`, `games`, `stats`, `load-runs` at desktop and mobile
- `stats-loading`, `stats-empty`, `stats-unavailable` at desktop and mobile

Added, same tolerance: `stats-refined`, `stats-columns`, `stats-compact`, `stats-sticky` at desktop and mobile.

## Commands

```text
ruff check loader web tests migrations
All checks passed!

unset SERVE_SPA && pytest -q --tb=line
292 passed, 2 skipped

unset SERVE_SPA && pytest tests/test_api.py -q
12 passed

SERVE_SPA=true pytest tests/test_api.py -q
12 passed

npx vitest run
Test Files  9 passed (9)
Tests  33 passed (33)

npx playwright test --project=integration
11 passed
plus e2e/keyboard.spec.ts forced-colors: 1 passed

npm run e2e:visual
14 passed
npm run e2e:visual
14 passed
```

The two skips are the existing network-marked tests (`RUN_NETWORK_TESTS` unset).

## Mutation

UNKNOWN for the killed/survived score. `github.com/unclebob/mutator` installed with `crapper` checked out beside it. `mutator --scan --changed` listed 887 sites. `mutator --changed --max-workers 3` started; its baseline Vitest coverage run passed 32 tests and then selected 179 covered sites in `PremiumTable.tsx`. No killed/survived total had been printed when this report was written. Advisory only; it does not block the PR.

## Unverified

A desktop screen reader was not run. Forced colors were checked with Playwright `emulateMedia({ forcedColors: "active" })` plus the CSS rule, not with a Windows high-contrast theme. Visual baselines were generated on this Ubuntu 24.04.5 machine with the repo's Playwright Chromium, which is the CI image family, and then compared twice locally.
