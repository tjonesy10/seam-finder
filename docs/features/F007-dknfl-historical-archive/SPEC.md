# F007: Re-runnable private pureslurp/DKNFL original salary archive load

Status: **DRAFT amendment** (2026-11-10). The merged R1–R6 contract is unchanged. This draft adds R7–R8 (bounded kickoff tolerance and audited free-agent row skips) and AT13–AT21. The decision is pending Cosmo approval via Groko's gate. Not handed to forge. No production load, migration, or schedule activation.

Related: [constitution](../../CONSTITUTION.md), [architecture](../../architecture.md), [dictionary](../../data-dictionary.md#f005f008-private-salary-contract-approved-not-deployed), [glossary](../../GLOSSARY.md).

## Problem / job to be done

Keep original archived DK salary exports independently attributable to pureslurp/DKNFL, including duplicate exports and alternate/holiday slates, without trusting mislabeled repository folders or overwriting Cosmo's current export table.

## Requirements

- **R1** Load manifest-selected pureslurp/DKNFL original CSVs from a staged archive into their own private `dknfl_salaries` source table; no automatic network refresh.
- **R2** Retain exact raw bytes/rows including blank and duplicate records, pinned original repository URL/commit/path, manifest labels, and corrected metadata/evidence separately.
- **R3** Validate Classic multi-game schema and Game Info; derive corrected season/type/week from game evidence, preserve holiday/alternate slates and reject ambiguous metadata rather than infer Sunday main. A parsed non-ready snapshot kept under this contract, including flagged conflicting duplicate IDs, is not an F005 usable snapshot and is not optimizer-ready. Kickoff matching and unparsed Game Info follow R7 and R8; they do not weaken any other R3 fail-closed rule.
- **R4** Reingestion is idempotent by bytes+source identity+parser; attempts are independently audited and revised source artifacts append without destructive updates.
- **R5** Publish one normalized file atomically; retain rejected evidence, continue independent files with nonzero overall on any failure, and keep previous successful data intact.
- **R6** Enforce private roles, budget guards, source-specific attribution, no secret/raw logs/public data exposure, and no changes to F003/F004/other source rows.
- **R7** A parsed Game Info game matches a loaded schedule row when, after the loader's documented team-token aliasing to schedule abbreviations, the home and away teams and the America/New_York calendar date identify exactly one `games` row, that row's season and week agree with the reviewed manifest, and `|file kickoff − schedule kickoff| ≤ 30` minutes. An exact (0-minute) match is unchanged and writes no discrepancy record. A tolerated nonzero match still loads, uses the schedule kickoff as the snapshot's canonical `kickoff_at`, and records an auditable discrepancy (file kickoff, schedule kickoff, signed delta minutes, and `game_id`) on the snapshot and observation metadata. A delta over 30 minutes, a date mismatch, no schedule row, or more than one schedule row still fails the file closed (`game_evidence_missing` or `game_evidence_ambiguous`).
- **R8** Skip a data row, and still load the file, only when `TeamAbbrev` is exactly `FA` and `Game Info` is exactly `-`. Retain the source file bytes and hash unchanged. Keep the row in the ledger as `rejected` with reason `free_agent_no_game`. Record each skipped row in observation (and published snapshot) metadata with original path, 1-based data `row_number`, and the DK id, name, and salary as given. Count it in the load summary. Do not silently drop it or write it as a valid `dknfl_salaries` row. Any other unparsed Game Info, including `FA` with a value other than `-` and `-` with a `TeamAbbrev` other than `FA`, still fails the file closed as `game_info_unparsed`. If those skippable free-agent rows are more than 2% of the file's data rows, the file fails closed as `free_agent_row_bound`. Existing blank-placeholder rejection (AT3) is unchanged and is not this skip.

## User stories

- As Cosmo, I want archived DK IDs and salaries kept separately from vendor subsets, so that later analysis can trace what each export actually contained.
- As a researcher, I want game-date corrections and original folder labels both preserved, so that a mislabeled Thanksgiving file is not silently joined to Sunday main.
- As an operator, I want safe reruns and retained rejected rows, so that malformed records do not erase evidence or good files.
- As an operator, I want a 15-minute archive-versus-schedule kickoff difference to load with an audit trail, so that a Wild Card file is not rejected for broadcast-clock rounding while a larger mismatch still fails closed.
- As an operator, I want a free-agent row with no game to be skipped and counted, so that one placeholder does not fail a whole Sunday file and no row disappears without a record.

## Observable behavior

### CLI and archive boundary

`python -m loader.dknfl_archive --archive-root PATH --manifest PATH/MANIFEST.csv [--trigger local|manual]`

Same safe local manifest/path boundary as F006: filter exact `pureslurp/DKNFL`, reject absolute/traversal/escaping symlink/duplicate conflicting entries, no URL input, no automatic extraction/download. Required manifest columns and shared persistence schema are in the dictionary/F006. Keep manifest as private control artifact and each selected raw CSV under source dknfl. Missing archive/manifest/file fails clearly with sanitized audit if DB available. Zero selected entries is configuration error, exit 1. Manual/local only; no cron or implicit repo fetch. Source URL is pinned to upstream commit when present; record that commit, exact repository path and original URL. Do not relabel it as a Cosmo official export just because the CSV format is official.

### Inspected coverage and data contract

62 manifest files, **27,788** source rows / **2,819,068** raw CSV bytes, mainly 2022–2024 with two files actually from 2021 week 2 and postseason weeks up to 21 in 2023 / week 20 in 2024. Source row counts include repeated exports/alternate slates; not distinct player totals or every-slate coverage. All manifest hashes/counts validated in planning, not player mappings. One 2021 CSV includes 15 blank-name/blank-salary rows; retain them as rejected rows. Other duplicated exports remain independent path identities even if content hashes match. There is no required one-file-per-week cardinality.

Original headers: `Position,Name + ID,Name,ID,Roster Position,Salary,Game Info,TeamAbbrev,AvgPointsPerGame`. Support UTF-8 BOM, CRLF and varying column order; keep every additional source field. Required core fields match F005 except AvgPointsPerGame may be blank/missing. ID stays text `dk_id`; it may be a snapshot-scoped draftable ID, never assume it is stable across years or equals draftables player_id/GSIS. Salary numeric nonnegative; invalid raw value remains in ledger with null salary and rejection reason. AvgPointsPerGame is a source average, not realized DK points. DST remains source DST/team until F008 maps it.

No CPT anywhere; require >1 **parsed distinct games** on valid/nonblank Game Info, not multiple spellings of one game. Roster eligibility must be compatible with Classic and no unsupported contest structure. Single-game/Showdown file is rejected as a snapshot but raw bytes/parseable rows retained in ledger. A header-shaped HTML/challenge is not CSV and fails. Genuine blank placeholder records get rejected status, not fabricated salary=0/player rows. Nonblank conflicting duplicate native IDs are retained and flagged; the file may be retained as a non-ready source snapshot, but no optimizer interpretation is publishable until resolved. That parsed snapshot is this archive's explicit contract, not an F005 usable capture. Successful parsing is not optimizer-ready completeness, and F008 cannot bypass the quality gate. Malformed core header or contradictory season/week/game evidence is file-fatal.

### Metadata correction is explicit, not a new source

Parse Game Info opponent pair/kickoff using ET zone semantics and map to loaded NFL games, retaining raw strings and mapping method/version. Exact season/type/week must agree across parsed games and the reviewed corrected manifest. Team tokens are compared after the loader's documented aliasing to schedule abbreviations (the archive writes `LAR`; the games table stores those Rams games as `LA`). POST exports are retained as POST if verified; do not relabel them REG or pass through F004's REG-only CLI. Week 19 and later postseason files are in scope when their games verify as POST.

Game matching (R7): after aliasing, look up `public.games` by home team, away team, and the file kickoff's America/New_York calendar date. No row is `game_evidence_missing`. More than one row is `game_evidence_ambiguous`. The single row's season and week must equal the reviewed manifest, or the file fails as `manifest_game_contradiction`. Compare file kickoff to that row's `gametime` in America/New_York. A 0-minute difference is an exact match: the snapshot `games[]` entry is unchanged, and no discrepancy is recorded. If `0 < |delta| ≤ 30` minutes, the file may still load: write `kickoff_at` from the schedule kickoff (not the file clock) so F008 exact game/kickoff slate identity stays aligned with the loaded schedule, and append one `kickoff_discrepancies` object to snapshot and observation metadata with `away`, `home`, `game_id`, `file_kickoff_at`, `schedule_kickoff_at`, and signed `delta_minutes` (file minus schedule, whole minutes). A delta over 30 minutes or a date mismatch is `game_evidence_missing`. Do not rewrite source bytes, ledger `Game Info`, or invent a schedule row. Implementing R7/R8 requires a new `parser_version` because match results and metadata shape change.

Unparsed Game Info and free-agent rows (R8): a row whose Game Info does not match the documented `AWAY@HOME MM/DD/YYYY H:MMAM|PM ET` pattern is unparsed, except (1) existing blank-placeholder rows already rejected under AT3, which must not be classified as `game_info_unparsed`, and (2) a row with `TeamAbbrev` exactly `FA` and `Game Info` exactly `-`, which is skipped under R8. The skip is recorded and counted; the file loads unless those skippable rows are more than 2% of the file's data rows (`free_agent_row_bound`). Public `load_runs` notes carry only the reason code and counts. A scan of all 62 manifest files against nflverse `schedules/games.parquet` found one kickoff mismatch (`2023/WEEK19/DKSalaries-Week19.csv`, `LAR@DET` 8:15PM ET vs schedule `2023_19_LA_DET` 20:00, +15 minutes, Wild Card / POST) and one skippable free-agent row (`2024/WEEK1/DKSalaries-Week1.csv`, 1 of 712 rows ≈ 0.14%). No other kickoff delta, no ambiguous team-date match, and no other unscheduled `TeamAbbrev` appeared. That evidence supports the 30-minute bound and the 2% free-agent bound; it is not a certified season.

Games that are missing, ambiguous, over the kickoff bound, date-mismatched, or (outside R8) unparseable, or a manifest contradiction, still reject the normalized file, retain evidence, and report the coordinator; do not guess week from Wednesday arithmetic or folder name.

Examples from inspected manifest (preserve each original path, not edit source):
- `2022/Week2/*` actually 2021 week 2 per embedded September 19, 2021 games.
- `2023/WEEK11_5` → 2023 week 12 Thanksgiving; `WEEK13_9` → week 14; `WEEK14_9` → week 15.
- `2024/WEEK12/DKSalaries-week12.csv` → week 13 Thanksgiving, while `...week12_sunday.csv` remains week 12.
- Wednesday December 25, 2024 is week 17 by schedule evidence; it is not automatically the next week by weekday.
- `2023/WEEK19/DKSalaries-Week19.csv` is a Wild Card (POST) Classic file. Under R7 it loads with a kickoff-discrepancy audit for `LA@DET`. It is not out of scope.
- `2024/WEEK1/DKSalaries-Week1.csv` loads under R8 with one audited free-agent skip.

Persist corrected fields on the new snapshot metadata with original labels/evidence, never rename files or rewrite source. Preserve exact game set, kickoff instants, roster eligibility, unknown draft_group_id and unknown full roster/rules separately. Canonical `kickoff_at` values are schedule instants after a tolerated match. `source_pool_kind=full_export` means original export format, **not automatic verification** of complete official main-slate identity. Standard rules/completeness and cross-group equivalence need evidence-backed F008 interpretation; unknowns stay flagged. Small two-/three-game Classic holiday or Monday slates are valid distinct archives, not rejected merely for not being Sunday main. Do not supplement their pools with other files.

### Transactions, audit and privacy

Use common raw-first and normalized-per-file transaction contracts. Dataset `dknfl_salaries`, one load_runs per selected file, shared run_group per invocation. Public notes/error are codes and counts, detailed paths/manifest/failed row diagnostics stay private. Record this ingestion observed_at; fetched_at null for local ingestion, source_published_at null unless historical evidence proves it. Never use upstream commit/retrieval time as salary effective time without evidence. Same file re-run reuses snapshot/source rows, creates new attempt. Changed bytes or identity metadata append new version. Continue good independent files after a failed one; final exit 1 if any failed. Bounds/genuine DB outage/recovery behavior as shared dictionary; do not claim a failure row survived an unreachable DB.

Kickoff discrepancies and free-agent skips use existing jsonb metadata and ledger `reason_codes`. No new table or column is required. See the data dictionary.

Attribution: "Archived DraftKings salary export via pureslurp/DKNFL (GitHub). Not affiliated with DraftKings." Not RotoGuru, not DFF. No public raw APIs/pages/downloads or committed acquired CSVs, no paid licenses inferred from GitHub availability. Existing F004 source remains separate and unchanged.

## Acceptance tests

Synthetic original-format fixtures with corrected manifest metadata; real Postgres/Alembic; no GitHub/DK network fetch in CI. Do not commit acquired archive CSVs. Isolated offline runs may use the operator's staged archive; CI uses synthetic fixtures, including byte-faithful reproductions of the two real failing rows and schedule facts named in AT21.

- **AT1 (R1)** Given mixed-source manifest, when invoked, then only DKNFL entries load into their own private source table and required PK/indexes exist; no other table's source rows are altered.
- **AT2 (R2)** Given BOM/CRLF/extra columns and duplicate export paths, when read back, then exact bytes/hash/path/commit/manifest and every ordered row ordinal survive; shared content dedupes bytes only, not attribution.
- **AT3 (R2, R3)** Given 15 synthetic blank placeholders plus valid players, when loaded, then blank records remain rejected/attributable, valid salary rows match, counts reconcile and no fake player/zero salary is created. Blank Game Info on those placeholders is not `game_info_unparsed` and is not an R8 skip.
- **AT4 (R3)** Given mislabeled Week2 and Thanksgiving/Christmas examples with supporting games, when parsed, then corrected season/type/week and exact alternate-game set are stored, original paths remain, and no Sunday-main inference occurs.
- **AT5 (R3)** Given valid two-game and POST Classic files, when ingested, then each stays its own source snapshot with correct season type and unknown group/rules fields unguessed.
- **AT6 (R3, R5, R7)** Given CPT/single-game, malformed headers, inconsistent manifest/game week or missing/ambiguous/date-mismatched/over-tolerance game evidence, when run, then file fails clearly, bounded raw evidence survives and no half normalized snapshot replaces prior success.
- **AT7 (R3)** Given native DK IDs, duplicate conflicting IDs and AvgPointsPerGame, when ingested, then IDs remain snapshot-scoped, duplicate conflicts may remain a flagged non-ready snapshot, and no GSIS mapping, merged pool, actual points, F005 usable snapshot, or optimizer-ready promotion is invented.
- **AT8 (R4)** Given identical rerun then corrected content under same path, when loaded, then new attempt per invocation, no duplicated parsed repeats, original snapshot immutable, corrected version appended.
- **AT9 (R5)** Given good/bad/good files and simulated mid-write failure/crash, when loaded/recovered, then good files persist, failing normalized transaction rolls back, audit finalization uses durable commit evidence, overall exit 1.
- **AT10 (R1, R6)** Given missing file, unsafe path, hash/count mismatch or oversized object/budget, when loaded, then controlled failure without remote fetch/outside-root read, false full-retention claim, eviction or previous-data mutation.
- **AT11 (R6)** Given web/private roles on real PG and repeated grant application, when queried, then web cannot read source/raw/F004 while public nflverse/RotoGuru reads work; F003/F004 data unchanged.
- **AT12 (R2, R6)** Given log capture and attribution output, when inspected with gitleaks, then correct DKNFL credit remains, no secrets/raw rows/private paths or new public endpoint/download, and no cron/network collector is added.
- **AT13 (R7)** Given a multi-game Classic file whose every parsed game matches exactly one schedule row at a 0-minute kickoff difference, when loaded, then the file succeeds, snapshot `games[].kickoff_at` equals the schedule kickoff, and `kickoff_discrepancies` is absent or empty.
- **AT14 (R7)** Given otherwise identical evidence whose one game is 15 minutes later than the unique same-date schedule row, when loaded, then the file succeeds, that game's canonical `kickoff_at` is the schedule instant, and snapshot and observation metadata contain one discrepancy with file kickoff, schedule kickoff, `delta_minutes` of 15, and the schedule `game_id`. Source bytes and ledger `Game Info` still show the file clock.
- **AT15 (R7)** Given a 31-minute kickoff difference against the unique same-date schedule row, when loaded, then the file fails closed as `game_evidence_missing`, no new normalized snapshot is published, and raw artifact and ledger evidence remain.
- **AT16 (R7)** Given two schedule rows for the same aliased home/away teams on the file's America/New_York date, when loaded, then the file fails closed as `game_evidence_ambiguous` with no new normalized snapshot.
- **AT17 (R8)** Given a valid multi-game file plus one row with `TeamAbbrev` exactly `FA` and `Game Info` exactly `-`, when loaded, then the file succeeds, that row is ledger `rejected` with reason `free_agent_no_game`, it is absent from valid `dknfl_salaries` rows, metadata lists original path, `row_number`, DK id, name, and salary as given, and the load summary count equals the number of such rows. Source bytes and hash are unchanged.
- **AT18 (R8)** Given `TeamAbbrev` exactly `FA` and Game Info that is not exactly `-` and does not parse as a game, when loaded, then the file fails closed as `game_info_unparsed`.
- **AT19 (R8)** Given `Game Info` exactly `-` and a `TeamAbbrev` other than `FA`, when loaded, then the file fails closed as `game_info_unparsed`.
- **AT20 (R8)** Given skippable free-agent rows (`TeamAbbrev` `FA` and `Game Info` `-`) totaling more than 2% of the file's data rows, when loaded, then the file fails closed as `free_agent_row_bound`, no new normalized snapshot is published, and the rows remain in the ledger with reason `free_agent_no_game`.
- **AT21 (R7, R8)** Given fixtures that reproduce the two real staged archive files — `2023/WEEK19/DKSalaries-Week19.csv` (`GB@DAL 01/14/2024 04:30PM ET` and `PIT@BUF 01/15/2024 04:30PM ET` exact; `LAR@DET 01/14/2024 08:15PM ET` vs schedule `2023_19_LA_DET` `20:00`, week 19 POST) and `2024/WEEK1/DKSalaries-Week1.csv` (one row `TeamAbbrev=FA`, `Game Info=-`) — when loaded against the corresponding schedule rows, then WEEK19 succeeds as POST with a +15-minute discrepancy audit for `LA@DET` and exact matches for the other two games, and WEEK1 succeeds with one audited `free_agent_no_game` skip and no `game_info_unparsed`. An isolated offline run of the operator's staged files must show the same outcomes. This does not certify a season and does not commit those CSVs to the repository.

## Non-goals

New GitHub scraping, other archives, exhaustive historical coverage, Showdown, player mapping threshold or optimizer, source pool union/filling, public exposure, replacing F004, actual scoring/projections. This docs package adds no code/migration execution/production writes. No unbounded kickoff slop, no silent rewrite of archive bytes or ledger Game Info, no treating `FA` as a scheduled team, and no exclusion of verified POST weeks from F007.

## Allowed dependencies

F005 approved shared persistence foundation, existing Python/SQLAlchemy Core/psycopg/Alembic, stdlib csv/json/hashlib/pathlib/zoneinfo. Existing games as read-only correction evidence. No nfldfs, pandas, ORM, scraper, new account or paid feed.

## Open questions

Decision pending Cosmo approval via Groko's gate. No `[NEEDS CLARIFICATION]` markers. If the decision is rejected, keep current exact-kickoff and fail-closed unparsed behavior (WEEK19 and WEEK1 stay rejected). Production migration and deploy remain unapproved. Not handed to forge.

## Analyze matrix

| Requirement | Acceptance tests |
|---|---|
| R1 | AT1, AT10 |
| R2 | AT2, AT3, AT12 |
| R3 | AT3, AT4, AT5, AT6, AT7 |
| R4 | AT8 |
| R5 | AT6, AT9 |
| R6 | AT10, AT11, AT12 |
| R7 | AT6, AT13, AT14, AT15, AT16, AT21 |
| R8 | AT17, AT18, AT19, AT20, AT21 |

R1–R8 all covered; AT1–AT21 none orphaned. ADR 0005 and ADR 0006 are Accepted. ADR 0009 is Proposed and does not supersede them. The constitution amendment for F005–F008 is operative. This DRAFT does not approve production migration, deploy, schedule activation, or a forge handoff.

## ADRs

[0001](../../adr/0001-stack-and-hosting.md), [0002](../../adr/0002-nflverse-load-and-refresh.md), [0003 (source separation)](../../adr/0003-rotoguru-dk-classic-salaries.md), [0004 (Accepted; status only, substance preserved)](../../adr/0004-dk-current-slate-csv.md), [0005 (Accepted)](../../adr/0005-private-salary-capture-and-archives.md), [0006 (Accepted)](../../adr/0006-slate-safe-salary-unification.md), [0009 (Proposed; bounded DKNFL kickoff tolerance and free-agent row skips)](../../adr/0009-dknfl-kickoff-tolerance-and-free-agent-rows.md).
