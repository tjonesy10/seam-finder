# ADR 0001: Stack and hosting for the data prototype

## Status

Proposed (2026-11-05)

## Context

Part 1 needs a database, a loader, read APIs, and a web page per table, hosted online so Cosmo can share it, on free tiers. Later parts (projections, simulations, DFS optimizer) will be Python-heavy (statistics, integer programming). Data size is small: about 208,000 player-week rows for 2015-2026 (measured from nflverse-data files on 2026-11-05), 3,300 games, 24,864 players, 36 teams. A CSV of the stats columns we keep is about 23 MB; in Postgres with indexes the whole database is estimated at 50-150 MB (estimate, not measured).

Free-tier facts (read 2026-11-05):

- **Neon Free** ([pricing](https://neon.com/pricing)): no card; 100 CU-hours per project per month, up to 2 CU, 1 GB storage per project, 5 GB egress per project per month, scales to zero after 5 minutes idle and resumes in "a few hundred milliseconds"; not paused for inactivity. Going over CU-hours or egress suspends compute until the next month; over 1 GB storage blocks writes.
- **Render free web service** ([docs](https://render.com/docs/free), [pricing](https://render.com/pricing)): 0.1 CPU / 512 MB, 750 free instance hours per workspace per month, spins down after 15 minutes idle, about one minute to spin back up, ephemeral disk. Without a payment method, going over the free bandwidth (5 GB/month on Hobby) suspends free services instead of billing.
- **Render free Postgres** ([docs](https://render.com/docs/free)): 1 GB, expires 30 days after creation (14-day grace, then deleted), no backups.
- **Supabase Free** ([pricing](https://supabase.com/pricing)): 500 MB database, 5 GB egress, projects pause after 1 week of inactivity.
- **Fly.io** ([pricing](https://fly.io/docs/about/pricing/)): no free tier; card required.
- **Railway** ([pricing](https://railway.com/pricing)): trial credit, then $1/month of free usage on one project.
- **Vercel Hobby** ([docs](https://vercel.com/docs/plans/hobby)): non-commercial personal use only; serverless functions.
- **GitHub Actions** ([billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)): free for public repos; for a private repo on GitHub Free, a monthly included allowance ($12 of compute, which at the listed $0.006/min Linux 2-core rate is about 2,000 minutes, derived). Without a payment method, runs stop when the allowance is used.

## Decision

- **Language**: Python 3.12+ for loader, API, and pages.
- **Database**: Postgres on **Neon Free**.
- **Web**: one **FastAPI** app serving JSON under `/api/*` and server-rendered **Jinja2** HTML pages for each table, with plain HTML forms and links for filter/sort/paging. No JS framework and no build step. Hosted as one **Render free web service**.
- **DB access**: SQLAlchemy Core (no ORM) with `psycopg` 3; migrations with Alembic.
- **Refresh**: GitHub Actions (see [ADR 0002](0002-nflverse-load-and-refresh.md)).

## Reasoning

- Python everywhere means parts 2-5 (stats, solvers) reuse the same code and models.
- Neon is the only free Postgres option found that is permanent, needs no card, does not pause a project for inactivity, and has room (1 GB) for this data many times over.
- Render runs a normal long-lived Python web process from the repo, free, with no card, so FastAPI runs unchanged.
- Server-rendered pages from the same app reuse the API's query code, need no CORS, no second deploy, and no frontend toolchain. Filter/sort/paginate are just query parameters, which match the API's.
- SQLAlchemy Core keeps SQL explicit and testable without an ORM layer the read-only app doesn't need.

## Rejected alternatives and why

- **Render free Postgres**: deleted after 30 days + 14-day grace.
- **Supabase**: pauses after 1 week without activity, which breaks a site shared now and viewed later; 500 MB cap.
- **Fly.io**: no free tier and needs a card.
- **Railway**: free usage is $1/month of credit on one project; easy to run out.
- **Vercel Hobby / Cloudflare Workers**: serverless model, Vercel Hobby is non-commercial only, and FastAPI would need adapting; no gain for one small app.
- **SPA frontend (React/Vite) on a static host**: second deploy, build tooling, CORS, and nothing part 1 needs beyond what HTML forms do.
- **SQLite file in the repo or on disk**: Render's free disk is ephemeral, and GitHub Actions would have to commit data to update it.
- **Streamlit / Datasette**: fast to start, but a second stack to replace once the API matters for parts 2-5; Datasette exposes raw SQL by default.

## Consequences

- First page view after 15 minutes idle waits about a minute for Render to start; Neon adds a sub-second wake. Fine for a shared prototype; a paid Render instance removes it if needed later.
- Cosmo must create Neon and Render accounts (flagged as an open question, not decided here).
- Expected cost $0/month. What would push to paid: Neon over 100 CU-hours or 5 GB egress (service suspends, no bill, unless upgraded); Render over 750 instance hours or 5 GB bandwidth (suspends without a payment method); GitHub Actions over the private-repo allowance (runs stop without a payment method). At this size none is expected (estimate).
- Keeping the repo private uses Actions minutes; making it public removes that limit.
