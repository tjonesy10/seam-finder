# Pending constitution amendment for F009

Status: **Pending**. This text is not operative. Do not copy it into [CONSTITUTION.md](../../CONSTITUTION.md) until Cosmo approves the F009 docs and this amendment. It is a separate amendment, not a silent edit of the accepted constitution.

The accepted constitution, on main `36636c2af8326a11ab3a4cbe4498df487fad78bd`, conflicts with F009 in two Stack sentences and needs a Testing bar addition. No Data and licensing, Security, Process, or Out of scope rule is changed.

## Stack, first bullet

Current:

> Python 3.12, FastAPI with Jinja2 pages, SQLAlchemy Core, Alembic, Postgres. Decided in [ADR 0001](../../adr/0001-stack-and-hosting.md).

Proposed:

> Python 3.12, FastAPI serving JSON under `/api/*` and the built React, TypeScript, and Vite static app, SQLAlchemy Core, Alembic, Postgres. The frontend uses TanStack Table, TanStack Virtual, and TanStack Query. It uses TanStack Router for page routes and URL-persisted filter, sort, and paging state. It does not use TanStack Start or SSR. Decided in [ADR 0001](../../adr/0001-stack-and-hosting.md), with the frontend and asset-hosting decision in [ADR 0008](../../adr/0008-react-frontend-hosting.md).

## Stack, second bullet

Current:

> No ORM layer, pandas, JS framework, or bundler without a new ADR.

Proposed:

> No ORM layer or pandas without a new ADR. The React, TypeScript, and Vite frontend and the TanStack libraries in [ADR 0008](../../adr/0008-react-frontend-hosting.md) are the allowed JS framework and bundler. No other JS framework, SSR framework, or bundler without a new ADR.

## Testing bar, third bullet

Current:

> CI (ruff, pytest, gitleaks) is green before a PR merges.

Proposed:

> CI (ruff, pytest, gitleaks, and the F009 frontend typecheck, lint, unit, build, and Playwright checks) is green before a PR merges. The new frontend checks do not replace ruff, pytest, or gitleaks.

## Status line of CONSTITUTION.md, after approval

When this amendment is merged, append a short note to the constitution Status line, such as: amended 2026-11-10 (React frontend / F009). Do not rewrite earlier amendment history.
