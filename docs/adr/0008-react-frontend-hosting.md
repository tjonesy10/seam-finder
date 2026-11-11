# ADR 0008: React frontend and asset hosting

## Status

Accepted (2026-11-10 20:05 America/New_York) by owner merge of PR #26, commit `2a72ed0b1b2620cf399218765f5e326a0af69763`. Acceptance is the contract only. No implementation is built, and this acceptance does not authorize a forge build or a live cutover.

Constitution amendment approval: Cosmo (repo owner), 2026-11-10 20:03 America/New_York, captured on a Groko question card and relayed by Groko. Exact words: "I approve the constitution amendment for the React + TypeScript + Vite frontend." The approved text is applied in `docs/CONSTITUTION.md` and takes effect when the F009 follow-up PR merges.

## Context

Cosmo approved a React and TypeScript frontend on 2026-11-10, with TanStack Table and TanStack Virtual for tables, and other TanStack libraries when they help. The site today is one FastAPI process on a Render free web service. It serves JSON under `/api/*` and Jinja2 HTML for `/`, `/teams`, `/players`, `/games`, `/stats`, and `/load-runs`. [ADR 0001](0001-stack-and-hosting.md) chose that shape, with no JS framework and no build step, and rejected a React or Vite SPA on a separate static host because of a second deploy, CORS, and tooling that Part 1 did not need.

Phase 1 still has to be shareable on free tiers, keep `/api/health` as the Render health check, and leave the live site unchanged until Cosmo cuts over. Filter, sort, and paging already live in the URL. A later optimizer player pool is expected to hold hundreds of rows with sort, filter, and lock or exclude toggles, but that UI is not in this feature.

The two hosting options in scope are a separate Render static site and the existing FastAPI process serving the Vite build.

## Decision

Build one React, TypeScript, and Vite SPA in `frontend/`. Use TanStack Table and TanStack Virtual for every table, TanStack Query for fetching and caching, and TanStack Router for routes and URL-persisted filter, sort, and paging state. Do not use TanStack Start or SSR.

Host the built files from the existing FastAPI app on the existing Render free web service. JSON routes under `/api` and `/api/*` are registered first. Remaining non-file routes fall back to `index.html` only when cutover is on. Do not add a second Render service for this feature.

## Reasoning

The same origin removes CORS and a public API origin setting. One web service stays inside the current 750 free instance-hours and the current cold-start model. `/api/health` can keep its path, contract, and Render health-check setting. Hashed assets can be cached for a long time, while `index.html` stays short-lived, so deploys and rollbacks are visible. SPA fallback is straightforward if API routes always win.

TanStack Router earns its dependency because Phase 1 already has six routes and already stores table state in the query string. A hand-rolled history wrapper would duplicate that work. An SSR framework would not, because the API remains FastAPI and the approved direction is a static Vite build.

## Rejected alternatives and why

- **Render static site plus the current web service.** A second service, a second deploy, CORS or a proxy, and a frontend API base URL. `/api/health` would stay on the web service, but the public site origin would split from the API unless more DNS and proxy work is added. That is more moving parts than Phase 1 needs, and it reopens the ADR 0001 cost of a second host.
- **Keeping Jinja as the long-term UI.** This conflicts with Cosmo's approved React direction and would not give the shared virtualized table contract.
- **TanStack Start or another SSR host.** Out of scope in the approved direction. It would add a second server runtime next to FastAPI.
- **No TanStack Router.** Workable for a single page, but this app already has multiple pages and shareable filter URLs. Router is the smaller way to keep those URLs honest.
- **Committing built assets so Render can keep `pip install .` forever.** Possible as an emergency fallback, but the lockfile and CI build are the source of truth, and generated bundles do not belong on `main` as the normal path.

## Consequences

- ADR 0001 remains accepted for Python 3.12, Neon Free, FastAPI JSON, SQLAlchemy Core, Alembic, the Render free web service, and GitHub Actions refresh. Its Jinja2 pages, "no JS framework", and "no build step" decisions are superseded by this ADR.
- The Render dashboard build command must eventually install Node 26 and run the Vite build before `pip install .`. That dashboard change happens only at Cosmo-approved cutover. No `render.yaml` is added.
- A `SERVE_SPA` flag, default off, keeps Jinja live until Cosmo turns the SPA on. FastAPI gains a static-file mount and a catch-all that must never swallow `/api` or `/api/health`.
- CI grows a Node 26 path and a lockfile. Free GitHub Actions minutes on the public repo remain the test runner.
- Cosmo approved the F009 constitution amendment on 2026-11-10 20:03 America/New_York. The approved Stack and Testing bar text is applied in `docs/CONSTITUTION.md` and takes effect when the F009 follow-up PR merges. This ADR is the contract for the framework and bundler. It is not a silent constitution change and it does not build the frontend.
