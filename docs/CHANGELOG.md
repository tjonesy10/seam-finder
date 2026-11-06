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
- F004 Q3: Cosmo chose CLI file path only this pass (no private upload UI).
- F004 Q4: Cosmo accepted data-load only this pass (no read API / browse; skipped card → default).
- F004 Q5: Cosmo accepted keep null `gsis_id` + notes + ≥95% non-DST match (skipped card → default a).
- F004 Q6 (partial): Cosmo chose schedule something this pass (not manual-only); asked API vs CSV — source still user-supplied CSV via CLI. Schedule shape TBD.
- F004 Q7: Cosmo chose Showdown reject (c) — CPT in Roster Position or distinct Game Info ≤ 1; Classic-only error.
- F004 Q6b: Cosmo chose scheduled load from staged path/secret/artifact (not reminder-only; not DK auto-download). SPEC marked READY.
- F004 data-load: `dk_classic_slate` migration, `python -m loader.dk_slate`, and a Tuesday cron plus `workflow_dispatch` that loads a Cosmo-staged CSV. No read API and no public salary download.

- F003 DRAFT: historical DraftKings Classic weekly salaries and points (2015–2021) via RotoGuru. SPEC, HANDOFF, ADR 0003 (Proposed), data-dictionary section, glossary terms. Blocked on Cosmo license/attribution and remaining open questions.
- F003 Q1: Cosmo approved RotoGuru historical DK Classic data in Neon and on the public site; attribution line set; constitution Data section amended; ADR 0003 still Proposed until that amendment is on main.
- F003 Q2: Cosmo chose data-load only for this pass (no read API / browse page); remaining open questions still block forge handoff.
- F003 Q3–Q7: Cosmo accepted defaults (keep null gsis_id + AT8 ≥98%; explicit team map; SCSV week discovery; workflow_dispatch only; keep salary=0). SPEC READY; analyze pass done; forge handoff.




### F005–F008 docs package (2026-11-06; SPEC READY / DOCS APPROVAL PENDING)

- Added F005 live private DK capture, F006 offline DFF archive, F007 offline DKNFL archive and F008 slate-safe unified surface SPECs. The 16:56 EST HANDOFF lines remain BLOCKED history; later lines record decisions. No implementation, migration files, TEST_REPORT/run-log edits, schedule activation, or production actions.
- Proposed ADR 0005 for bounded unauthenticated capture/new attributed sources, partial supersession only of ADR 0004's blanket auto-download ban; F004 official-export CLI/staged workflow preserved. Added explicit pending constitution amendment, not an implied exception.
- Proposed ADR 0006 for verified entity+exact-slate equivalence, coherent anchor snapshots, retained alternatives/disagreement, source-specific attribution and conservative legacy/subset/current adapters.
- Added private bytea artifact/row/attempt retention, idempotence, failure atomicity, storage guards and grants contracts; minimal product stories, architecture and glossary updates. Each F005 capture attempt also stores private wall-clock `started_at`/`finished_at` and monotonic `duration_ms`. Elapsed time is not wall-clock subtraction.
- 2026-11-06 16:59 EST: Cosmo approved Wednesday 10:00 America/New_York during REG season, DST-correct, with the GitHub delay/drop caveat. Planned schedule only; not activated. No Sunday refresh.
- 2026-11-06 17:00 EST: Cosmo approved automatic capture of only the upcoming Sunday-afternoon Classic slate whose game set is exactly all REG games kicking off 1:00–4:30 PM America/New_York, including holiday weeks. No Saturday or holiday substitution. Missing or ambiguous candidates fail closed.
- ADR 0005/0006 remain Proposed. The constitution amendment is not effective until owner merge. Handoff is held for Cosmo docs approval. No forge handoff.
- ADR 0004 live status is Proposed despite prior merged amendment; status-only cleanup flagged, not silently reported as Accepted. Accepted ADR substance unchanged.
- Existing F003 build correction already on main via PR #16 treats opponent '-' as null; older historical changelog entries above remain historical and are not current implementation claims. No F003 source behavior changes in this package.
- Wording fix: the shared dictionary is an evidence-retention superset, and per-source rules govern promotion. F005 publishes no usable snapshot when any salary is invalid; raw artifact and parseable ledger remain. F006/F007 may keep parsed non-ready snapshots and rejected rows under their own contracts. Successful parsing is not optimizer-ready, and F008 cannot bypass that gate. No new requirement or acceptance-test numbers.
