# Changelog

## 2026-11-05

Added (planning docs, Part 1 data prototype, all DRAFT):
- `docs/prd.md`: problem, goals, non-goals, user stories with acceptance criteria.
- `docs/architecture.md`: components, data flow, deployment, future extension points.
- `docs/adr/0001-stack-and-hosting.md`: Python, Postgres on Neon Free, FastAPI + Jinja2 on Render Free (Proposed).
- `docs/adr/0002-nflverse-load-and-refresh.md`: nflverse-data release files, idempotent upsert, daily GitHub Actions refresh, load_runs, CC BY 4.0 attribution (Proposed).
- `docs/data-dictionary.md`: teams, players, games, player_week_stats, load_runs; migration plan.
- `docs/GLOSSARY.md`: terms used across the docs.
- `docs/features/F001-data-prototype/SPEC.md`: behavior, API contract, acceptance tests AT1-AT26, decisions.
- `docs/features/F001-data-prototype/HANDOFF.md`: status log.
- Open questions answered; SPEC, PRD, architecture READY; ADR 0001 and 0002 Accepted.
- Repo is public: Actions-minutes note updated; Secrets rule added to the F001 SPEC.
- F001 split into build passes A (data) and B (API and pages).
