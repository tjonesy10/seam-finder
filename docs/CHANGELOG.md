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




### F005–F008 docs package (2026-11-06; drafted before PR #17; superseded by the status sync below)

- Added F005 live private DK capture, F006 offline DFF archive, F007 offline DKNFL archive and F008 slate-safe unified surface SPECs. The 16:56 EST HANDOFF lines remain BLOCKED history; later lines record decisions. No implementation, migration files, TEST_REPORT/run-log edits, schedule activation, or production actions.
- Proposed ADR 0005 for bounded unauthenticated capture/new attributed sources, partial supersession only of ADR 0004's blanket auto-download ban; F004 official-export CLI/staged workflow preserved. Added explicit pending constitution amendment, not an implied exception.
- Proposed ADR 0006 for verified entity+exact-slate equivalence, coherent anchor snapshots, retained alternatives/disagreement, source-specific attribution and conservative legacy/subset/current adapters.
- Added private bytea artifact/row/attempt retention, idempotence, failure atomicity, storage guards and grants contracts; minimal product stories, architecture and glossary updates. Each F005 capture attempt also stores private wall-clock `started_at`/`finished_at` and monotonic `duration_ms`. Elapsed time is not wall-clock subtraction.
- 2026-11-06 16:59 EST: Cosmo approved Wednesday 10:00 America/New_York during REG season, DST-correct, with the GitHub delay/drop caveat. Planned schedule only; not activated. No Sunday refresh.
- 2026-11-06 17:00 EST: Cosmo approved automatic capture of only the upcoming Sunday-afternoon Classic slate whose game set is exactly all REG games kicking off 1:00–4:30 PM America/New_York, including holiday weeks. No Saturday or holiday substitution. Missing or ambiguous candidates fail closed.
- At drafting, ADR 0005/0006 were Proposed, the constitution amendment was not yet operative, and handoff was held for docs approval. Owner merge of PR #17 superseded that pending state. See the status sync below.
- At drafting, ADR 0004's file still said Proposed despite its earlier merged F004 amendment. Status-only acceptance is recorded in the status sync below. Its decision substance was not rewritten.
- Existing F003 build correction already on main via PR #16 treats opponent '-' as null; older historical changelog entries above remain historical and are not current implementation claims. No F003 source behavior changes in this package.
- Wording fix: the shared dictionary is an evidence-retention superset, and per-source rules govern promotion. F005 publishes no usable snapshot when any salary is invalid; raw artifact and parseable ledger remain. F006/F007 may keep parsed non-ready snapshots and rejected rows under their own contracts. Successful parsing is not optimizer-ready, and F008 cannot bypass that gate. No new requirement or acceptance-test numbers.

### F005–F008 status sync (2026-11-06; docs approval recorded)

- Owner merge of PR #17 (`6c26e8dad1f0261a29febaa2cd8311bb36aa893a`) is the docs approval. Specs are READY. ADR 0005 and ADR 0006 are Accepted. The constitution amendment is operative. ADR 0004 is Accepted on status only; ADR 0005 supersedes only its blanket auto-download ban. No requirement or acceptance-test numbers changed (28 requirements / 56 acceptance tests).
- Parent merged-main analyze found no open markers or blocker. Parent SendToAgent forge delivery succeeded at about 17:16 EST: build F005 first, then F006 and F007, then F008, in separate PRs, each with all of its acceptance tests and a Mutator report. A later feature waits for its dependency PRs to merge. That order is not permission to skip those merges and is not a new docs gate. Groko was notified. Schedule activation and production migration or deploy remain unapproved. This entry does not claim a production change.

### F005 schedule completeness (2026-11-06; ADR 0007 Proposed)

- Cosmo approved, directly at 19:14 EST, independent season-schedule verification reviewed each season and when games change, failing closed without valid evidence. No product question remains. ADR 0007 is Proposed until this docs PR merges. That is a docs-merge gate, not a new product question.
- Freshness, endpoint presence, row count, and a self-hash do not prove a complete season. The contract is an operator-reviewed league reference, a pinned authority root, exact retained nflverse bytes, an automatic source-to-PG receipt, and a whole REG partition comparison, including timing changes and cancellation evidence, before any DK call. Positive cases are a verified in-season capture and a finite supported off-season gap. Incomplete prior-year evidence and an unsupported gap fail closed.
- No season inventory is certified. No new automatic league-schedule scraper. Cadence, Sunday window, monotonic capture timing, F004, and private-source rules are unchanged. Requirement and acceptance-test numbers stay 28 / 56. AT5 gains subcases and also covers R4 and R5.
- PR #19 head `81c43e8cf9619d04ef198772c4b2b23dfd35927a` recorded AT5 FAIL and three strict xfails: deleted interior Sunday game, deleted interior week, and April with an incomplete prior season reported as off-season. This entry does not claim those tests passed or that a Mutator run was added. Implementation merge stays held until this docs amendment is approved. Later features still wait for their dependency PRs to merge.
