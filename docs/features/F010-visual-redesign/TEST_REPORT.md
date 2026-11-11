# F010 visual redesign test report

Date: 2026-11-10. Branch `cursor/f010-visual-redesign-e2e4`, based on main `3b61fcd` (F009 PR #31 is merged). No API, schema, grant, Render, or secret changes. `SERVE_SPA` still defaults off.

Final tokens match the spec palette. Checked pairs are all above the floors: body text `#e8eef7` on canvas `#0b1220` is 16.05:1, muted `#a7b5ca` on raised `#1b2b42` is 6.87:1, accent `#70d6c5` on canvas is 10.80:1, on-accent `#0b1220` on accent is 10.80:1, and the control border `#70839f` on raised is 3.70:1. No token was changed.

## Results

| AT | Result | Evidence |
|---|---|---|
| AT1 | PASS | `frontend/src/tokens.ts` plus CSS Modules. `frontend/src/contrast.test.ts`. Visual snapshots use bundled Inter and show no theme switch. No external font request in the built CSS. |
| AT2 | PASS | `e2e/keyboard.spec.ts` reaches Home and Teams from the keyboard. Nav marks the current page with text "Current" and `aria-current`. One `h1` per page. Home shows the four dataset lines and the five table links. |
| AT3 | PASS | `e2e/pages.spec.ts` filters, sorts, and pages `/stats` against real Postgres. Columns, pager copy, and URLs stay the F009 contract. `DataTable.test.tsx` still virtualizes 500 rows. |
| AT4 | PASS | Vitest pending `/teams` shows "Loading data" and 8 `aria-hidden` skeleton rows, with no `rows 0-0 of 0`. Refetch keeps the polite "Updating data" status. |
| AT5 | PASS | Vitest: zero rows show "No results for these filters.", Clear filters, and `rows 0-0 of 0`. Offset 50 with total 1 shows "No rows on this page." and First page. |
| AT6 | PASS | Vitest list 503 shows the alert and Retry, and a second fetch, with no traceback. Playwright home outage shows "The database is unavailable." and `Last refresh: none`. Bad-parameter and Not found integration tests still pass. |
| AT7 | PASS | `e2e/keyboard.spec.ts` at 320px: the document does not scroll horizontally and the table region does. CSS zoom 2 on a 1440px viewport also keeps the document from overflowing. Mobile nav opens from the Menu button. |
| AT8 | PASS | Keyboard spec: skip link, nav Enter focuses the h1, Filter keeps focus, Next changes offset, Retry refetches, the table region is tabbable, and Escape returns focus to Menu. Zoom is the automated check above. Screen-reader status is the hand check below. |
| AT9 | PASS | Contrast test locks the 4.5:1 and 3:1 pairs. `@axe-core/playwright` with WCAG 2.1 A/AA tags reports zero violations on every visual route and state at both viewports. Reduced motion sets animation duration to `0s`. |
| AT10 | PASS | Attribution text and both links are in the shell before API success (existing Vitest) and in the visual/integration pages. Drift test `tests/test_spa.py::test_attribution_bundle_matches_web_attribution` passed inside the full pytest run. No RotoGuru line was added. |
| AT11 | PASS | No Python API, query, or grant edits. `tests/test_api.py` is unchanged. Full pytest with `SERVE_SPA` unset passed, including that file. `SERVE_SPA=true pytest tests/test_api.py` passed 12. Frontend allowlist is still the public `/api` paths. |
| AT12 | PASS | 22 committed baselines in `frontend/e2e/visual.spec.ts-snapshots/`. The visual projects passed twice locally on Ubuntu 24.04.5 with pinned Playwright Chromium, `maxDiffPixels: 100`, threshold 0.2. CI does not pass `--update-snapshots`. |
| AT13 | PASS | `.github/workflows/ci.yml` keeps ruff, both `tests/test_api.py` modes, full pytest, gitleaks, typecheck, lint, Vitest, build, and real-Postgres `npm run e2e`. A separate `ubuntu-24.04` job runs `npm run e2e:visual` twice and uploads only synthetic diffs on failure. |
| AT14 | PASS | `tests/test_spa.py` rollback, missing-build, and database-outage tests passed in the full suite. Jinja templates were not redesigned. |

Screen-reader hand check: list status is one `aria-live="polite"` region ("Loading data", "Updating data", or "Results updated"). Failures are `role="alert"`. The skeleton table is `aria-hidden`. I did not run a separate desktop screen reader.

## Commands

```text
ruff check loader web tests migrations
All checks passed!

unset SERVE_SPA && pytest -q --tb=line
292 passed, 2 skipped

SERVE_SPA=true pytest tests/test_api.py -q --tb=line
12 passed

npx vitest run
Test Files  3 passed (3)
Tests  14 passed (14)

npx playwright test --project=integration
11 passed

npx playwright test --project=visual-desktop --project=visual-mobile
12 passed
npx playwright test --project=visual-desktop --project=visual-mobile
12 passed
```

The two skips are `tests/test_dk_classic.py:940` and `tests/test_load.py:93` (`RUN_NETWORK_TESTS` unset). The unset `tests/test_api.py` run is inside the full pytest command; that file was not edited and the dedicated on-mode run is 12 passed.

## Mutation

UNKNOWN. `mutator` is not installed, and this task said not to install it.

## CI

Recorded after the push.
