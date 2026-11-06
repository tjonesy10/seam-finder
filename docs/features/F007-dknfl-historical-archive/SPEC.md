# F007: Re-runnable private pureslurp/DKNFL original salary archive load

Status: **SPEC READY / DOCS APPROVAL PENDING** (2026-11-06). No open product questions. ADR 0005/0006 remain Proposed and the constitution amendment is not effective until Cosmo merges this docs PR. Implementation still waits on that docs approval and on the F005 shared persistence foundation. No forge handoff.

Related: [constitution](../../CONSTITUTION.md), [architecture](../../architecture.md), [dictionary](../../data-dictionary.md#proposed-f005f008-private-salary-contract-draft-not-deployed), [glossary](../../GLOSSARY.md).

## Problem / job to be done

Keep original archived DK salary exports independently attributable to pureslurp/DKNFL, including duplicate exports and alternate/holiday slates, without trusting mislabeled repository folders or overwriting Cosmo's current export table.

## Requirements

- **R1** Load manifest-selected pureslurp/DKNFL original CSVs from a staged archive into their own private `dknfl_salaries` source table; no automatic network refresh.
- **R2** Retain exact raw bytes/rows including blank and duplicate records, pinned original repository URL/commit/path, manifest labels, and corrected metadata/evidence separately.
- **R3** Validate Classic multi-game schema and Game Info; derive corrected season/type/week from game evidence, preserve holiday/alternate slates and reject ambiguous metadata rather than infer Sunday main.
- **R4** Reingestion is idempotent by bytes+source identity+parser; attempts are independently audited and revised source artifacts append without destructive updates.
- **R5** Publish one normalized file atomically; retain rejected evidence, continue independent files with nonzero overall on any failure, and keep previous successful data intact.
- **R6** Enforce private roles, budget guards, source-specific attribution, no secret/raw logs/public data exposure, and no changes to F003/F004/other source rows.

## User stories

- As Cosmo, I want archived DK IDs and salaries kept separately from vendor subsets, so that later analysis can trace what each export actually contained.
- As a researcher, I want game-date corrections and original folder labels both preserved, so that a mislabeled Thanksgiving file is not silently joined to Sunday main.
- As an operator, I want safe reruns and retained rejected rows, so that malformed records do not erase evidence or good files.

## Observable behavior

### CLI and archive boundary

`python -m loader.dknfl_archive --archive-root PATH --manifest PATH/MANIFEST.csv [--trigger local|manual]`

Same safe local manifest/path boundary as F006: filter exact `pureslurp/DKNFL`, reject absolute/traversal/escaping symlink/duplicate conflicting entries, no URL input, no automatic extraction/download. Required manifest columns and shared persistence schema are in the dictionary/F006. Keep manifest as private control artifact and each selected raw CSV under source dknfl. Missing archive/manifest/file fails clearly with sanitized audit if DB available. Zero selected entries is configuration error, exit 1. Manual/local only; no cron or implicit repo fetch. Source URL is pinned to upstream commit when present; record that commit, exact repository path and original URL. Do not relabel it as a Cosmo official export just because the CSV format is official.

### Inspected coverage and data contract

62 manifest files, **27,788** source rows / **2,819,068** raw CSV bytes, mainly 2022–2024 with two files actually from 2021 week 2 and postseason weeks up to 21 in 2023 / week 20 in 2024. Source row counts include repeated exports/alternate slates; not distinct player totals or every-slate coverage. All manifest hashes/counts validated in planning, not player mappings. One 2021 CSV includes 15 blank-name/blank-salary rows; retain them as rejected rows. Other duplicated exports remain independent path identities even if content hashes match. There is no required one-file-per-week cardinality.

Original headers: `Position,Name + ID,Name,ID,Roster Position,Salary,Game Info,TeamAbbrev,AvgPointsPerGame`. Support UTF-8 BOM, CRLF and varying column order; keep every additional source field. Required core fields match F005 except AvgPointsPerGame may be blank/missing. ID stays text `dk_id`; it may be a snapshot-scoped draftable ID, never assume it is stable across years or equals draftables player_id/GSIS. Salary numeric nonnegative; invalid raw value remains in ledger with null salary and rejection reason. AvgPointsPerGame is a source average, not realized DK points. DST remains source DST/team until F008 maps it.

No CPT anywhere; require >1 **parsed distinct games** on valid/nonblank Game Info, not multiple spellings of one game. Roster eligibility must be compatible with Classic and no unsupported contest structure. Single-game/Showdown file is rejected as a snapshot but raw bytes/parseable rows retained in ledger. A header-shaped HTML/challenge is not CSV and fails. Genuine blank placeholder records get rejected status, not fabricated salary=0/player rows. Nonblank conflicting duplicate native IDs are retained and flagged; the file may be retained as a non-ready source snapshot, but no optimizer interpretation is publishable until resolved. Malformed core header or contradictory season/week/game evidence is file-fatal.

### Metadata correction is explicit, not a new source

Parse Game Info opponent pair/kickoff using ET zone semantics and map to loaded NFL games, retaining raw strings and mapping method/version. Exact season/type/week must agree across parsed games and the reviewed corrected manifest. Games missing/ambiguous, unparseable kickoff or manifest contradiction → reject normalized file, retain evidence, report coordinator; do not guess week from Wednesday arithmetic or folder name. POST exports are retained as POST if verified; do not relabel them REG or pass through F004's REG-only CLI.

Examples from inspected manifest (preserve each original path, not edit source):
- `2022/Week2/*` actually 2021 week 2 per embedded September 19, 2021 games.
- `2023/WEEK11_5` → 2023 week 12 Thanksgiving; `WEEK13_9` → week 14; `WEEK14_9` → week 15.
- `2024/WEEK12/DKSalaries-week12.csv` → week 13 Thanksgiving, while `...week12_sunday.csv` remains week 12.
- Wednesday December 25, 2024 is week 17 by schedule evidence; it is not automatically the next week by weekday.

Persist corrected fields on the new snapshot metadata with original labels/evidence, never rename files or rewrite source. Preserve exact game set, kickoff instants, roster eligibility, unknown draft_group_id and unknown full roster/rules separately. `source_pool_kind=full_export` means original export format, **not automatic verification** of complete official main-slate identity. Standard rules/completeness and cross-group equivalence need evidence-backed F008 interpretation; unknowns stay flagged. Small two-/three-game Classic holiday or Monday slates are valid distinct archives, not rejected merely for not being Sunday main. Do not supplement their pools with other files.

### Transactions, audit and privacy

Use common raw-first and normalized-per-file transaction contracts. Dataset `dknfl_salaries`, one load_runs per selected file, shared run_group per invocation. Public notes/error are codes and counts, detailed paths/manifest/failed row diagnostics stay private. Record this ingestion observed_at; fetched_at null for local ingestion, source_published_at null unless historical evidence proves it. Never use upstream commit/retrieval time as salary effective time without evidence. Same file re-run reuses snapshot/source rows, creates new attempt. Changed bytes or identity metadata append new version. Continue good independent files after a failed one; final exit 1 if any failed. Bounds/genuine DB outage/recovery behavior as shared dictionary; do not claim a failure row survived an unreachable DB.

Attribution: "Archived DraftKings salary export via pureslurp/DKNFL (GitHub). Not affiliated with DraftKings." Not RotoGuru, not DFF. No public raw APIs/pages/downloads or committed acquired CSVs, no paid licenses inferred from GitHub availability. Existing F004 source remains separate and unchanged.

## Acceptance tests

Synthetic original-format fixtures with corrected manifest metadata; real Postgres/Alembic; no GitHub/DK network fetch in CI.

- **AT1 (R1)** Given mixed-source manifest, when invoked, then only DKNFL entries load into their own private source table and required PK/indexes exist; no other table's source rows are altered.
- **AT2 (R2)** Given BOM/CRLF/extra columns and duplicate export paths, when read back, then exact bytes/hash/path/commit/manifest and every ordered row ordinal survive; shared content dedupes bytes only, not attribution.
- **AT3 (R2, R3)** Given 15 synthetic blank placeholders plus valid players, when loaded, then blank records remain rejected/attributable, valid salary rows match, counts reconcile and no fake player/zero salary is created.
- **AT4 (R3)** Given mislabeled Week2 and Thanksgiving/Christmas examples with supporting games, when parsed, then corrected season/type/week and exact alternate-game set are stored, original paths remain, and no Sunday-main inference occurs.
- **AT5 (R3)** Given valid two-game and POST Classic files, when ingested, then each stays its own source snapshot with correct season type and unknown group/rules fields unguessed.
- **AT6 (R3, R5)** Given CPT/single-game, malformed headers, inconsistent manifest/game week or missing/ambiguous game evidence, when run, then file fails clearly, bounded raw evidence survives and no half normalized snapshot replaces prior success.
- **AT7 (R3)** Given native DK IDs, duplicate conflicting IDs and AvgPointsPerGame, when ingested, then IDs remain snapshot-scoped, duplicate conflicts retained/flagged and no GSIS mapping, merged pool or actual points are invented.
- **AT8 (R4)** Given identical rerun then corrected content under same path, when loaded, then new attempt per invocation, no duplicated parsed repeats, original snapshot immutable, corrected version appended.
- **AT9 (R5)** Given good/bad/good files and simulated mid-write failure/crash, when loaded/recovered, then good files persist, failing normalized transaction rolls back, audit finalization uses durable commit evidence, overall exit 1.
- **AT10 (R1, R6)** Given missing file, unsafe path, hash/count mismatch or oversized object/budget, when loaded, then controlled failure without remote fetch/outside-root read, false full-retention claim, eviction or previous-data mutation.
- **AT11 (R6)** Given web/private roles on real PG and repeated grant application, when queried, then web cannot read source/raw/F004 while public nflverse/RotoGuru reads work; F003/F004 data unchanged.
- **AT12 (R2, R6)** Given log capture and attribution output, when inspected with gitleaks, then correct DKNFL credit remains, no secrets/raw rows/private paths or new public endpoint/download, and no cron/network collector is added.

## Non-goals

New GitHub scraping, other archives, exhaustive historical coverage, Showdown, player mapping threshold or optimizer, source pool union/filling, public exposure, replacing F004, actual scoring/projections. This docs package adds no code/migration execution/production writes.

## Allowed dependencies

F005 approved shared persistence foundation, existing Python/SQLAlchemy Core/psycopg/Alembic, stdlib csv/json/hashlib/pathlib/zoneinfo. Existing games as read-only correction evidence. No nfldfs, pandas, ORM, scraper, new account or paid feed.

## Open questions

No open product questions. F005 cadence and the Sunday-afternoon slate rule were answered 2026-11-06 and are not reopened here. ADR 0005/0006 and the constitution amendment still require Cosmo's docs merge before any build. If a staged file's corrected manifest cannot be verified against games, report that bounded source exception to the coordinator and fail it rather than asking Cosmo to choose technical matching rules. No forge handoff.

## Analyze matrix

| Requirement | Acceptance tests |
|---|---|
| R1 | AT1, AT10 |
| R2 | AT2, AT3, AT12 |
| R3 | AT3, AT4, AT5, AT6, AT7 |
| R4 | AT8 |
| R5 | AT6, AT9 |
| R6 | AT10, AT11, AT12 |

R1–R6 all covered; AT1–AT12 none orphaned. ADR 0005/0006 remain Proposed and the constitution amendment is pending owner merge. SPEC READY / DOCS APPROVAL PENDING. No forge handoff.

## ADRs

[0001](../../adr/0001-stack-and-hosting.md), [0002](../../adr/0002-nflverse-load-and-refresh.md), [0003 (source separation)](../../adr/0003-rotoguru-dk-classic-salaries.md), [0004 (live Proposed, preserved)](../../adr/0004-dk-current-slate-csv.md), [0005 (Proposed)](../../adr/0005-private-salary-capture-and-archives.md), [0006 (Proposed)](../../adr/0006-slate-safe-salary-unification.md).
