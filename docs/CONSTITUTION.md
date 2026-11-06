# Seam Finder constitution

Status: Accepted (2026-11-05); amended 2026-11-06 (RotoGuru / F003). The non-negotiables every SPEC and ADR is checked against. Changed only through a PR the owner approves.

## Stack
- Python 3.12, FastAPI with Jinja2 pages, SQLAlchemy Core, Alembic, Postgres. Decided in [ADR 0001](adr/0001-stack-and-hosting.md).
- No ORM layer, pandas, JS framework, or bundler without a new ADR.

## Cost and accounts
- Free tiers only (Neon Free, Render Free, GitHub Actions on a public repo). Any paid plan, card on file, or new account needs the owner's approval first.

## Data and licensing
- Primary football data comes from nflverse-data under CC BY 4.0, with the attribution footer from [ADR 0002](adr/0002-nflverse-load-and-refresh.md) on every page.
- Historical DraftKings NFL Classic weekly salaries and points (REG, seasons 2015–2021) may be loaded from RotoGuru per [ADR 0003](adr/0003-rotoguru-dk-classic-salaries.md), stored in Neon, and shown on the public site with this exact attribution: "Historical DraftKings Classic salaries and points via RotoGuru (rotoguru1.com). Not affiliated with DraftKings."
- No team logos, player headshots, or share-alike (CC BY-SA) datasets without a new ADR. No other third-party salary feeds without a new ADR.

## Security
- The repo is public. Secrets live only in GitHub Actions secrets and Render environment variables, never in files, logs, or examples.
- The web app connects with a read-only database role. The loader is the only writer.

## Testing bar
- Every acceptance test in a SPEC has an automated test or a recorded hand check in TEST_REPORT.md.
- Tests run against a real Postgres, not mocks of it.
- CI (ruff, pytest, gitleaks) is green before a PR merges.

## Process
- `main` changes only by PR; the owner merges.
- A SPEC is READY with no open questions before code starts. When built work shows a spec was wrong, the docs are fixed first.
- Significant design decisions get an ADR. Accepted ADRs are superseded, not edited.

## Out of scope until planned
- Auth, user accounts, write APIs, live in-game data, and parts 2-5 (projections, valuation, DFS, live data) until each has its own SPEC.


