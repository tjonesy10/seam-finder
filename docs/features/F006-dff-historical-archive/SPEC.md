# F006: Re-runnable private Daily Fantasy Fuel historical archive load

Status: **READY** (2026-11-06). Docs approval is the owner merge of PR #17. No open product questions. ADR 0005 and ADR 0006 are Accepted, and the constitution amendment is operative. This status sync is not another build gate. Build this feature in its own PR after the F005 foundation PR merges. Do not skip that merge. Include every acceptance test and a Mutator report. Schedule activation and production migration or deploy remain unapproved.

Related: [constitution](../../CONSTITUTION.md), [architecture](../../architecture.md), [dictionary](../../data-dictionary.md#f005f008-private-salary-contract-approved-not-deployed), [glossary](../../GLOSSARY.md).

## Problem / job to be done

Load the acquired Daily Fantasy Fuel dated salary/projection subsets into their own private Neon table without presenting them as original DK exports, complete player pools, actual points, or RotoGuru data.

## Requirements

- **R1** Ingest only manifest-selected DFF CSVs from a staged local archive into `salary_private.dff_salaries`, separate from DK lobby, DKNFL, F003 and F004.
- **R2** Preserve exact CSV extraction bytes, ordered source rows including rejects, original source URL/path, manifest and available accepted-page gzip evidence; record actual provenance and source attribution.
- **R3** Validate manifest hash/count/schema, row dates/weeks and numeric salary; keep vendor IDs and projection semantics distinct; unknown/partial slate evidence stays unknown/subset. A parsed snapshot that keeps rejected salary rows is non-ready evidence under this contract, not an F005 usable snapshot and not optimizer-ready.
- **R4** Repeated content+identity/parser ingestion is idempotent, every attempt audited independently, corrected/revised files append rather than replace original source rows.
- **R5** Commit one normalized file atomically, retain evidence on failure, continue independent files but exit nonzero for any file failure; log sanitized run counts and rejections.
- **R6** Enforce private roles, raw-retention/storage budgets and no-network/no-public-exposure policy, preserving other sources.

## User stories

- As Cosmo, I want the obtained 2022–2025 gap data available privately, so that later analysis can use its actual limited coverage.
- As a researcher, I want DFF IDs, projections and extraction origins retained, so that salary overlap does not become a false identity or actual-points match.
- As an operator, I want safe reruns and per-file errors, so that one bad archive entry does not overwrite good history.

## Observable behavior

### Inputs and outputs

Proposed build CLI:

`python -m loader.dff_archive --archive-root PATH --manifest PATH/MANIFEST.csv [--trigger local|manual]`

No cron, HTTP, browser, remote archive discovery or upload endpoint. PATH is a runner-local staged directory or local path, not a URL. Missing archive/manifest is a clear failed audit when DB is reachable. Source filter is exactly `Daily Fantasy Fuel`; unrelated manifest rows are counted as not-selected, not loaded. Validate all file paths are relative and resolve under archive-root; reject absolute paths, traversal, escaping symlinks and duplicate/conflicting manifest entries. Do not unpack arbitrary zip paths; stage/unpack archive outside loader with safe tooling first. Production staging is a later deliberate owner-approved run, not part of this docs package.

Manifest columns are `path,season,week,rows,usable_salary_rows,source,source_url,format,date,unique_players_in_file,min_salary,max_salary,columns,sha256,quality_note`. Keep the manifest bytes and exact selected manifest row in private artifacts/observations. Snapshot metadata uses corrected season/week from manifest only after consistency validation against row dates/week and NFL games where available. Never infer season from calendar year alone (January regular-season dates belong to prior season). `source_published_at` is unknown unless evidence explicitly establishes it; page header "Updated At" and file mtime are not historical salary timestamps.

For each accepted DFF entry, require its acquired companion `evidence/dff-{season}-week{week:02}.html.gz`; retain exact gzip bytes, computed hash and link to CSV artifact. Missing required companion fails the file before publication rather than silently claiming retained original HTML. Store manifest plus COVERAGE.csv/FINDINGS.md when supplied as control provenance, bounded under shared limits. Do not ingest unrelated research pages, paid samples, empty 2021 results, or full logs into salary tables. A portable staged archive must include selected CSVs, manifest, and these accepted-page companions; do not commit them into the public repository or rely only on expiring Actions artifacts.

Each file outputs one immutable snapshot and every parseable row under `dff_salaries`/source ledger, plus a new observation/load audit. Source URL points to DFF dated HTML, artifact_kind csv is marked `html_row_extraction` in snapshot metadata; it is **not** a native website CSV endpoint or original DK export. Identical file re-run reuses raw/parsed data while retaining new attempt. Retained bytes/hash and row ordinals make all source values recoverable.

### Verified archive, not a complete coverage promise

Local evidence inspected: FINDINGS.md, MANIFEST.csv, COVERAGE.csv, sample raw CSVs. The manifest has **80** DFF files, **17,026** source rows, **1,888,193** CSV bytes: 18 Sunday-default dates each in 2022–2025; eight in 2026 weeks 1–8. DFF 2021 not verified. These are file/row counts including recurring players, not distinct source players or complete slate/player counts. All 142 combined-source file hashes/counts matched the acquired manifest during planning; that integrity check does not verify identity or license.

DFF required core columns: `start_date,week,name,pos,team,opp,loc,salary,player_id,ppg_proj`; observed additional fields: `fn,ln,pos_alt,spread,ou,rest,inj,proj_score,opp_rank,l5_avg,l10_avg,szn_avg,value_proj,starter_flag,depth_rank`. Column order can differ; extras preserved. Source schema per file is compared to manifest; missing required core fields is fatal. `salary` numeric nonnegative; invalid value gets rejected row with null normalized salary and raw value retained. Missing name/vendor ID or invalid date gets rejected reason. Row dates/week contradicting the manifest, a nonempty file with no valid salary rows, or unsupported structural changes fail the file. Count every rejected row and keep it.

DFF `player_id` e.g. vendor alphanumeric is only `dff_player_id`. Do not place it in DK ID or gsis_id columns. No new stub players. `ppg_proj` remains projection; actual fantasy points are not supplied by this archive. DST rows keep vendor position/team strings; F008 will map to team keys. Duplicate IDs/records remain in source and are flagged, not silently de-duplicated into a complete pool. This archive may keep a parsed snapshot that contains rejected rows. Successful parsing is not optimizer-ready completeness, and F008 cannot bypass that gate. The stricter F005 rule, which rejects the usable snapshot on any invalid salary, does not apply to this table.

Keep `source_pool_kind=subset` always. A dated Sunday-default page may be a holiday alternate: 2022 week 16, December 25, 2022 has only 60 DFF source rows/three Sunday games while the week's large slate was Saturday. `start_date`, team/opponent/location can provide **observed** game evidence but not prove missing games or roster rules. `draft_group_id=null`; no guessed main-slate ID. Snapshot games/rules fields retain unknown components; only later evidence-backed F008 mappings can verify slate equivalence. All DFF anchors remain subset/not optimizer-ready even if every present identity maps.

### Atomicity, audit, privacy

Use F005's shared schema/contracts: raw artifact/observation first; one transaction per normalized file; status running/succeeded/failed in public load_runs, private rejected-row counts/details. Dataset `dff_salaries`, one load_runs per selected file (or one failed startup run for a missing/unreadable manifest), same run_group per invocation. Notes contain season/week/counts/reason codes, not raw rows/paths/salary values. No fabricated historical fetch timestamp: observed_at is this load, fetched_at null, original research retrieval metadata preserved as evidence only if present. Overall exit 0 if all selected entries succeed, 1 otherwise, including zero selected files as a configuration error. Per-source summary counts files selected/succeeded/failed/reused, rows read/valid/rejected; no false total distinct-player claim.

Manual/local only; no live DFF fetch. Source rows append-only and identity mapping happens later in F008, never inherited from salary-equality crosschecks. Source-specific attribution: "Salary/projection subset via Daily Fantasy Fuel (dailyfantasyfuel.com). Not affiliated with DraftKings." Public availability does not establish redistribution rights; no public exposure authorized.

## Acceptance tests

Use tiny synthetic archive snippets with manifest/gzip companions plus a real Postgres/Alembic service; no production data committed or network CI dependency.

- **AT1 (R1)** Given mixed DFF/DKNFL manifest, when loaded, then only DFF-selected rows appear in dff_salaries and no other source table changes; required private schema/PK/index contracts hold.
- **AT2 (R2)** Given BOM/CRLF/quotes/extra columns and rejected blank row, when ingested, then exact CSV/gzip/manifest bytes and hashes read back, ordered raw tokens and reject ordinal remain attributable.
- **AT3 (R3)** Given matching manifest/row dates/weeks, including a January season boundary, when parsed, then corrected NFL season/week is validated and preserved; path label is not authority.
- **AT4 (R3, R5)** Given bad hash/count/missing core header, conflicting row date/week, missing companion, or zero valid rows, when loaded, then file fails, retained bounded evidence remains, no half normalized snapshot and previous success unchanged.
- **AT5 (R3)** Given vendor player_id, ppg_proj, and one invalid salary beside valid rows, when read back, then the invalid salary is a rejected row with null normalized salary and raw token, a parsed snapshot may exist and stays subset and not optimizer-ready, and no DK/GSIS ID, actual points, or F005-style usable-snapshot rejection is applied.
- **AT6 (R3)** Given the synthetic 2022 Christmas-like small Sunday subset and duplicate vendor rows, when ingested, then no Saturday main mapping or deduplication is inferred; duplicate/rejected rows retained and counted.
- **AT7 (R4)** Given same bytes/identity/parser twice and a corrected third file, when loaded, then two distinct content snapshots plus three observations exist; original source rows remain unchanged; same bytes under another source path preserve that distinct source identity.
- **AT8 (R5)** Given good/bad/good files and injected transaction failure in the middle, when invoked, then both independent good files commit, failed normalized file rolls back, audit identifies each result, invocation exits 1.
- **AT9 (R5)** Given crash after durable normalized commit, when audit reconciles, then no double ingest and previous normalized rows unchanged; DB outage yields nonzero and no false durable-audit claim.
- **AT10 (R1, R6)** Given missing manifest, unsafe path, escaping symlink or conflicting duplicate entry, when run, then clear failure without reading outside archive root and without remote access.
- **AT11 (R6)** Given web role and storage boundaries on real PG, when loading/querying or rerunning grants, then private data remains unreadable to web, guards stop publication without eviction, and F003/F004/lobby rows are unchanged.
- **AT12 (R2, R6)** Given captured logs and source attribution, when inspected plus gitleaks, then only DFF credit string is used, no raw data/secrets/path logs or public route/download/fixture is added, no HTTP call or cron exists.

## Non-goals

DFF live scraper/schedule, 2021 coverage, complete main-slate/player claims, projection modeling or actual scoring, GSIS mapping threshold, public API/UI/download, optimizer, changes to F003/F004 or other source tables. No implementation/migration/production load in this planning PR.

## Allowed dependencies

F005's approved shared persistence foundation, existing Python/SQLAlchemy Core/Alembic/psycopg, stdlib csv/gzip/hashlib/json/pathlib. No HTTP client invocation, pandas, ORM, scraper package or paid feed.

## Open questions

No open product questions. F005 cadence and the Sunday-afternoon slate rule were answered 2026-11-06. Docs approval is PR #17. Archive staging is an operational prerequisite, not a new product question. Missing evidence must be reported to the coordinator, never silently fetched. Build after the F005 foundation PR merges. That dependency is not a new docs gate and is not permission to skip the merge. Production migration and deploy remain unapproved.

## Analyze matrix

| Requirement | Acceptance tests |
|---|---|
| R1 | AT1, AT10 |
| R2 | AT2, AT12 |
| R3 | AT3, AT4, AT5, AT6 |
| R4 | AT7 |
| R5 | AT4, AT8, AT9 |
| R6 | AT10, AT11, AT12 |

R1–R6 all covered; AT1–AT12 none orphaned. ADR 0005 and ADR 0006 are Accepted. The constitution amendment is operative. READY does not approve production migration, deploy, or schedule activation.

## ADRs

[0001](../../adr/0001-stack-and-hosting.md), [0002](../../adr/0002-nflverse-load-and-refresh.md), [0003 (existing attribution separation)](../../adr/0003-rotoguru-dk-classic-salaries.md), [0004 (Accepted; status only, substance preserved)](../../adr/0004-dk-current-slate-csv.md), [0005 (Accepted)](../../adr/0005-private-salary-capture-and-archives.md), [0006 (Accepted)](../../adr/0006-slate-safe-salary-unification.md).
