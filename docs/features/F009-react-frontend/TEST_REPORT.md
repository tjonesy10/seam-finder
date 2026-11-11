# F009 React frontend test report

Date: 2026-11-10. Branch `cursor/f009-react-frontend-e2e4`. The live site stays on Jinja. `SERVE_SPA` serves `frontend/dist` only when the value is exactly `true`.

## Results

| AT | Result | Evidence |
|---|---|---|
| AT1 | PASS | Playwright `e2e/pages.spec.ts` home test. Screenshot `/opt/cursor/artifacts/f009-home.png`. Vitest home render. |
| AT2 | PASS | Playwright table-page test visits `/teams`, `/players`, `/games`, `/stats` (including `game_id`), and `/load-runs`. Screenshot `/opt/cursor/artifacts/f009-teams.png`. |
| AT3 | PASS | Playwright stats test opens `/stats?season=2024&week=10&team=CIN`, sees Ja'Marr Chase, sorts `receiving_yards` (URL and Fictional Player 001), then Next at offset 50 with `rows 51-100 of `. Screenshots `f009-stats-sorted.png` and `f009-stats-page-2.png`. |
| AT4 | PASS | Playwright bad-week test: list API HTTP 400, text `week must be an integer from 1 to 22`, filter form still present, no traceback. Unknown path shows `Not found`. Screenshots `f009-bad-week.png` and `f009-not-found.png`. |
| AT5 | PASS | Vitest renders the shell while `fetch` is still pending and asserts the exact attribution text and both hrefs plus `Last refresh: none`. Playwright checks the same footer on `/`, every table, `/games?week=abc`, and `/not-a-page`. |
| AT6 | PASS | Playwright reads the document on those paths and rejects `<img`, `url(http`, and `url(//`. `tests/test_spa.py::test_attribution_bundle_matches_web_attribution` checks the built HTML and CSS. |
| AT7 | PASS | `tests/test_spa.py::test_at7_package_uses_the_named_libraries`. `frontend/src/pages.tsx` uses `DataTable` and `useQuery`. Vitest renders `/teams` through that table. No TanStack Start, Next, or Remix dependency. |
| AT8 | PASS | Vitest `DataTable` test: 500-row fixture, fewer than 500 `[data-row-id]` nodes, controlled sort and filter change the visible ids, `setRowToggle("499", { locked: true })` keeps that id. Column defs are unchanged. |
| AT9 | PASS | Unchanged `tests/test_api.py`: 12 passed with `SERVE_SPA` unset, and 12 passed with `SERVE_SPA=true`. CI runs both commands. `test_at10_health_when_database_is_down` is in that file and passed both times. |
| AT10 | PASS | `tests/test_spa.py::test_at10_spa_serves_the_shell_and_leaves_api_json`. `/api/health`, `/api/teams`, and `/api/missing` stay JSON. `/teams` and an unknown path serve the shell. Hashed assets use `public, max-age=31536000, immutable`. `index.html` does not. |
| AT11 | PASS | Full pytest with the switch unset: 278 passed, 2 skipped (`RUN_NETWORK_TESTS` only). `test_serve_spa_accepts_only_the_exact_true_string` keeps Jinja for `false`, `TRUE`, `1`, and `yes`. `test_at11_missing_build_fails_clearly_and_the_switch_restores_jinja`: missing `frontend/dist` returns `The frontend build is missing.` on `/` and HTTP 200 JSON on `/api/health`; setting the switch back to `false` on the same app restores the Jinja table. |
| AT12 | PASS | `tests/test_spa.py::test_at12_routes_and_web_role_stay_on_the_public_allowlist`. Route table is the existing public paths. `PUBLIC_ALLOWLIST` is unchanged. Role `seam_web_f009` can read the public tables and cannot read `dk_classic_slate`, `salary_private.dk_lobby_salaries`, or `salary_private.dk_salary_unified`. |
| AT13 | PASS | `tests/test_spa.py::test_at13_frontend_does_not_name_private_salary_data` scans `frontend/src`, `frontend/e2e`, `frontend/dist`, `package.json`, and `package-lock.json`. The fetch allowlist is `/api`, `/api/teams`, `/api/players`, `/api/games`, `/api/player-week-stats`, and `/api/load-runs`. |
| AT14 | PASS | `.github/workflows/ci.yml` pins Node 26, runs `npm ci`, typecheck, lint, `npm test`, `npm run build`, and `npm run e2e`, and still runs `ruff check loader web tests migrations`, both `pytest tests/test_api.py` modes, full `pytest`, and `gitleaks detect`. `frontend/package-lock.json` and `.nvmrc` (`26`) are committed. `tests/test_spa.py::test_at14_ci_runs_node_and_both_api_modes`. |
| AT15 | PASS | Playwright, 7 passed, against the built app, FastAPI with `SERVE_SPA=true`, and Postgres loaded from `tests/fixtures/nflverse` plus the synthetic CIN week-10 rows. Covers home, filter/sort/paging, the attribution footer, `GET /api/health`, and the bad-parameter message. |
| AT16 | PASS | Vitest: pending fetch, HTTP 503, HTTP 500, and a network error each show `ATTRIBUTION_TEXT`, both links, and `Last refresh: none`, including the 404 view. Playwright cold load with `GET /api` fulfilled as 503 shows that footer, `Last refresh: none`, and `The database is unavailable.` Screenshot `f009-api-down.png`. Drift: `tests/test_spa.py::test_attribution_bundle_matches_web_attribution` compares `web.attribution` to `frontend/src/attribution.ts` and `frontend/dist/assets/*.js`. |

## Commands

Full Python suite, `SERVE_SPA` unset, gitleaks 8.30.1 on `PATH`, `DATABASE_URL=postgresql://seam@127.0.0.1:5432/seam_test`:

```text
pytest -q -rs --tb=no
278 passed, 2 skipped, 1 warning in 38.21s
SKIPPED tests/test_dk_classic.py:940: set RUN_NETWORK_TESTS=1
SKIPPED tests/test_load.py:93: set RUN_NETWORK_TESTS=1
```

`ruff check loader web tests migrations` reported `All checks passed!`

API contract, same database:

```text
unset SERVE_SPA && pytest tests/test_api.py -q --tb=line
12 passed

SERVE_SPA=true pytest tests/test_api.py -q --tb=line
12 passed
```

Frontend, Node v26.13.0:

```text
npx tsc --noEmit
npx eslint .
npx vitest run
Test Files  2 passed (2)
Tests  10 passed (10)

npx vite build
dist/index.html
dist/assets/index-B0K6-ujD.js
dist/assets/index-dCfqn3wj.css

npm run e2e
7 passed
```

An unreachable database still returns the existing HTTP 503 HTML page for `/teams`, including the attribution text, with the switch on or off. That is what the unchanged `test_at10_health_when_database_is_down` asserts, and TestClient does not run JavaScript. When the database is up, FastAPI serves the SPA shell. The shell renders the bundled attribution while `GET /api` is pending or failing.

## Packages

Installed from the spec: React, React DOM, TypeScript, Vite, `@tanstack/react-table`, `@tanstack/react-virtual`, `@tanstack/react-query`, `@tanstack/react-router`, Vitest, Testing Library (`@testing-library/react`), Playwright, ESLint.

Peers required by those tools: `@types/react`, `@types/react-dom`, `jsdom`, `typescript-eslint`, `@eslint/js`. No `@vitejs/plugin-react`. Vite 8 compiles TSX from `jsx: react-jsx` in `tsconfig.json`.

`@tanstack/react-table` 9.3.1 keeps the spec's column, sort, and filter contract on `useLegacyTable` (`@tanstack/react-table/legacy`). `DataTable` uses that hook.

## Mutation

UNKNOWN. `mutator` from github.com/unclebob/mutator is not on `PATH` and was not installed. The task said to run it only when it is already available.

## CI

The workflow on this branch is the one reviewed above. The GitHub Actions run for the PR head is recorded after the push.
