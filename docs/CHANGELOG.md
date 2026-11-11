# Changelog

## 2026-11-11

- Planned [F012 dataset query](features/F012-dataset-query/SPEC.md), READY R1–R10/AT1–AT16, and [F013 dataset table controls](features/F013-dataset-table-controls/SPEC.md), READY R1–R8/AT1–AT12, as separate one-pass builds after F011 (then F012 before F013). Cosmo's dataset-wide follow-up approval at 07:57 ET is relayed by Groko. No implementation, delivery, deployment or independent approval claimed.
- Proposed [ADR 0011](adr/0011-public-dataset-query-grammar.md): opt-in typed/allowlisted grammar, max-three stable sorts, fixed literal text search, exact snapshot count and bounded advanced SQL execution. Legacy-only parameters/errors remain unchanged; new unknown params still 400. Two specified public stats B-tree indexes, no pg_trgm/extension or grant change; forge authors migrations and production application requires separate Cosmo approval including automatic refresh-migration paths.
- Explicit page/dataset scopes preserve F011 links, map `ui_*` state to server params and bypass local sort/filter in dataset mode. Dataset-wide CSV deferred for boundedness/cost/abuse reasons; existing guarded page CSV remains explicitly page-only. No salary data/exposure, exact attribution preserved. Updated architecture/data dictionary/glossary and append-only handoff records; analyzed both R/AT mappings and constitution/all ADRs.
- ADR 0010 status-only sync to Accepted, owner-merged via PR #33 (`3b61fcd`, 2026-11-10); no decision substance changed.

## 2026-11-10

- F010/F011 planning split: [F010 visual redesign](features/F010-visual-redesign/SPEC.md) READY (R1–R9 / AT1–AT14) supplies dark tokens, CSS Modules, shell/states, responsive/a11y baseline and deterministic Playwright comparison/axe CI. [F011 premium tables](features/F011-premium-tables/SPEC.md) READY (R1–R10 / AT1–AT16) depends on F010 implementation merged; adds explicitly current-page interactions, URL state and guarded public-page CSV export without API changes.
- Added Proposed [ADR 0010](adr/0010-frontend-design-system-and-visual-checks.md): native controls and small bundled font, no UI framework/light theme; pinned synthetic visual baselines supplement real-Postgres integration. Updated architecture/glossary and new per-feature HANDOFF records; no data shape change, so data dictionary unchanged. Salary controls/exports are not applicable: no existing public page/API exposes salary. Static attribution and private isolation remain unchanged. This entry records docs planning only, not a forge delivery, completed implementation, owner approval or deployment.

- F007 amendment (ready for build pending merge of PR #30; not handed to forge until Cosmo merges): bounded 30-minute kickoff tolerance and audited free-agent row skips. Added R7–R8 and AT13–AT21 in `docs/features/F007-dknfl-historical-archive/SPEC.md`, [ADR 0009](adr/0009-dknfl-kickoff-tolerance-and-free-agent-rows.md) accepted per Cosmo approval 2026-11-10 20:32 ET (relayed by Groko), effective when PR #30 merges, glossary terms, and data-dictionary metadata shapes (`kickoff_discrepancies`, `free_agent_rows`). No new column. No implementation, no production load, and no season certification. The only archive kickoff mismatch is 2023 WEEK19 `LAR@DET` 8:15PM ET vs schedule `20:00` (+15 minutes, Wild Card / POST, in scope). The only skippable free-agent row is 2024 WEEK1 (`FA` / `-`, 1 of 712 rows). Week 19 is not excluded from scope.

- F009 DRAFT: replace the Jinja public pages with a React, TypeScript, and Vite SPA. Added `docs/features/F009-react-frontend/SPEC.md` (R1-R9, AT1-AT15), `HANDOFF.md` (DRAFT, not handed to forge), pending `CONSTITUTION-AMENDMENT.md`, and Proposed [ADR 0008](adr/0008-react-frontend-hosting.md). ADR 0001 status note records that Jinja, no-JS-framework, and no-build-step clauses are superseded by 0008 once 0008 is accepted. Architecture, PRD, and glossary updated. No implementation, no production deploy, and no live cutover.
- Hosting choice: FastAPI serves the built assets on the existing Render free web service. A separate Render static site is rejected. Cutover is `SERVE_SPA=true`, default off.
- Constitution conflict recorded, not silently applied: the accepted Stack bullets still name Jinja2 pages and a blanket bundler ban until Cosmo approves the amendment.
- Phase 1 keeps the exact current nflverse footer string. The RotoGuru DraftKings disclaimer exists in `web/attribution.py` but is not on the current site, so Phase 1 does not display it.
- F009 SPEC rev 2: footer attribution is a static attribution fallback in the bundle, generated from or checked against `web/attribution.py` `ATTRIBUTION_TEXT` and `ATTRIBUTION_LINKS`, including a first visit during an outage, loading, every error view, and the 404 shell. `GET /api` supplies `last_refresh_et` and `datasets` only as the fields the page reads. A missing value renders `Last refresh: none`. AT16 covers the outage footer, and a drift test locks the bundled constant. AT9 runs unchanged `tests/test_api.py` with `SERVE_SPA` off and on. Phase 1 shows no DraftKings line; any future public historical-salary display must use `ROTOGURU_DK_CLASSIC_ATTRIBUTION`. Counts: R1-R9 (9), AT1-AT16 (16).
- F009 follow-up: Cosmo approved the constitution amendment on 2026-11-10 20:03 America/New_York ("I approve the constitution amendment for the React + TypeScript + Vite frontend."). The approved Stack and Testing bar text is applied in `docs/CONSTITUTION.md` and takes effect when this follow-up PR merges. ADR 0008 is Accepted as a contract by the PR #26 merge `2a72ed0` at 2026-11-10 20:05 America/New_York. No implementation is built. ADR 0001's Jinja and no-bundler clauses are superseded by ADR 0008.


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

- Cosmo approved, directly at 19:14 EST, independent season-schedule verification reviewed each season and when games change, failing closed without valid evidence. No product question remains. ADR 0007 was Proposed until PR #20 merged. See the acceptance entry below.
- Freshness, endpoint presence, row count, and a self-hash do not prove a complete season. The contract is an operator-reviewed league reference, a pinned authority root, exact retained nflverse bytes, an automatic source-to-PG receipt, and a whole REG partition comparison, including timing changes and cancellation evidence, before any DK call. Positive cases are a verified in-season capture and a finite supported off-season gap. Incomplete prior-year evidence and an unsupported gap fail closed.
- No season inventory is certified. No new automatic league-schedule scraper. Cadence, Sunday window, monotonic capture timing, F004, and private-source rules are unchanged. Requirement and acceptance-test numbers stay 28 / 56. AT5 gains subcases and also covers R4 and R5.
- At that time, PR #19 head `81c43e8cf9619d04ef198772c4b2b23dfd35927a` recorded AT5 FAIL and three strict xfails: deleted interior Sunday game, deleted interior week, and April with an incomplete prior season reported as off-season. This entry did not claim those tests had passed or that a Mutator run was added. The implementation had not merged. Later features still wait for their dependency PRs to merge.

### F005 ADR 0007 accepted (2026-11-06)

- Owner merge of PR #20 (`dc72cc544b575a35420dd1f550babcacb31a248f` at 2026-11-06 20:10:55 EST) accepts ADR 0007. No requirement or acceptance-test text was weakened. Numbers stay 28 requirements / 56 acceptance tests.
- Acceptance of ADR 0007 is the contract only. It is not independent acceptance of the implementation. The engineer [test report](https://github.com/tjonesy10/seam-finder/blob/6464faa7aa1e3956d6b00e1b54be5a0270f11d51/docs/features/F005-dk-lobby-capture/TEST_REPORT.md) at open PR #19 head `6464faa7aa1e3956d6b00e1b54be5a0270f11d51` reports AT5 PASS on synthetic fixtures only. The independent acceptance gate at that head remains BLOCK. Two findings were sent to the implementation author: an optional failed-evidence insert has no rollback savepoint after a capacity rejection, and HTTPS TCP/TLS setup can pass the total deadline because closing the client does not close an httpcore connection that has not been assigned. Implementation merge stays held. No season is certified. Schedule activation and production migration or deploy remain unapproved.
