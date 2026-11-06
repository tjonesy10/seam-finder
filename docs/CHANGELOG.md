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
- F001 Pass A clarifications from build: validation ranges (season 1999-2100, week 1-22); players first_name/last_name nullable, no name splitting; FKs ON DELETE RESTRICT; `--trigger` default `local`.
- F001 Pass B handoff: numbered requirements R1-R13 mapped to every AT; AT27 (public URL) added; web app layout, Render settings, and read-only role setup specified; data dictionary READY.
- `docs/CONSTITUTION.md` drafted (separate PR, pending owner approval).

## 2026-11-06

- F003 closed on main (PRs #10 docs, #11 build). ADR 0003 Accepted. Documented oak→LV from 2020; opponent "-" still fails weeks pending Cosmo.
- F004 DRAFT: current-slate DraftKings Classic `DKSalaries.csv` (user-supplied). SPEC, HANDOFF, ADR 0004 (Proposed), data-dictionary section. Blocked on Cosmo license/exposure and remaining open questions.
- F004 Q1: Cosmo approved storing current-slate DK Classic CSV in Neon for personal/optimizer use; no public raw salary tables or CSV downloads; constitution Data section amended; ADR 0004 still Proposed until that amendment is on main.
- F004 Q2: Cosmo chose slate key `(season, week, dk_id)` with CLI `--season` / `--week`.

- F003 DRAFT: historical DraftKings Classic weekly salaries and points (2015–2021) via RotoGuru. SPEC, HANDOFF, ADR 0003 (Proposed), data-dictionary section, glossary terms. Blocked on Cosmo license/attribution and remaining open questions.
- F003 Q1: Cosmo approved RotoGuru historical DK Classic data in Neon and on the public site; attribution line set; constitution Data section amended; ADR 0003 still Proposed until that amendment is on main.
- F003 Q2: Cosmo chose data-load only for this pass (no read API / browse page); remaining open questions still block forge handoff.
- F003 Q3–Q7: Cosmo accepted defaults (keep null gsis_id + AT8 ≥98%; explicit team map; SCSV week discovery; workflow_dispatch only; keep salary=0). SPEC READY; analyze pass done; forge handoff.
