# F005: Scheduled private DraftKings NFL Classic lobby snapshots

Status: **SPEC READY / DOCS APPROVAL PENDING** (2026-11-06). Q1 cadence and Q2 Sunday-afternoon slate rule are answered. ADR 0005/0006 remain Proposed and the constitution amendment is not effective until Cosmo merges this docs PR. Handoff is held for that docs approval. No forge handoff and no schedule activation.

Related: [constitution](../../CONSTITUTION.md), [architecture](../../architecture.md), [data dictionary](../../data-dictionary.md#proposed-f005f008-private-salary-contract-draft-not-deployed), [glossary](../../GLOSSARY.md), [F004](../F004-dk-current-slate/SPEC.md).

## Problem / job to be done

Capture upcoming Classic prices automatically while they exist, without replacing Cosmo's official-export path or exposing raw salaries. The current lobby is not a historical archive. Keep each source snapshot and each capture attempt attributable for later private tooling.

## Requirements

- **R1** Add a bounded unauthenticated live-lobby CSV capture CLI and a new append-only private source table; never feed captures through F004's replacement loader.
- **R2** Automatically capture only the unique upcoming Sunday-afternoon NFL Classic draft group whose verified game set equals all REG games kicking off 1:00–4:30 PM America/New_York, including holiday weeks, with verified Classic rules. Do not substitute a Saturday, holiday, or other slate. Fail closed when the candidate is missing, ambiguous, non-Classic, or not an exact game-set match. A manual explicit id may target another multi-game REG Classic slate and must not be labeled Sunday main.
- **R3** Use in-repo GitHub Actions at Cosmo's approved cadence plus manual dispatch: Wednesday 10:00 America/New_York during REG season only, DST-correct, no Sunday refresh. GitHub may delay or drop scheduled runs, and a public repository disables schedules after 60 days without activity. This docs package records the schedule and does not activate it.
- **R4** Preserve exact bounded raw bytes/rows, source metadata, independent attempt timestamps and content hashes; repeated identical bytes/identity/parser do not duplicate parsed rows.
- **R5** Retain the raw artifact, observation, and parseable ledger for invalid evidence. Publish a usable snapshot and its `dk_lobby_salaries` rows atomically only when every salary is valid and the other F005 validity rules pass. Any invalid salary rejects that usable snapshot. Failures leave previous good snapshots untouched. Every invocation that can reach the database has a sanitized load_runs audit. An unreachable database exits nonzero and does not claim a persisted audit row.
- **R6** Stop cleanly on denial/rate limit/challenge, use bounded transient retries/timeouts only, no credentials or bypass.
- **R7** Implement private-schema isolation and storage guards from the shared dictionary, including F004 web-grant hardening; no public salary API/page/download or raw logs/fixtures.
- **R8** Preserve F004 CLI/staged workflow and F003 data/attribution unchanged; no optimizer, mappings to fabricated players, or production rollout in this feature's planning package.
- **R9** Persist every capture attempt in private Neon with wall-clock `started_at` and `finished_at` plus monotonic `duration_ms`, for success, failure, skip, and repeated identical content. Link the attempt to its snapshot and source rows when they exist. Do not infer elapsed time by subtracting clocks, do not fabricate completion after a crash, and do not put secrets or raw bodies in public logs.

## User stories

- As Cosmo, I want prices captured regularly without manually exporting, so that private future tooling has contemporaneous evidence.
- As Cosmo, I want my staged official export kept separate, so that an unavailable unofficial endpoint does not remove my fallback.
- As a reviewer, I want each failed and repeated attempt recorded without mutating prior prices, so that I can reproduce source selection.

## Observable behavior

### Inputs and CLI contract (proposed for the later build)

`python -m loader.dk_lobby --season YYYY --week N [--draft-group-id ID | --selection sunday-afternoon] [--trigger local|manual|schedule]`

`--season/--week` identify a requested REG week, not a slate. Positive numeric draft-group ID is validated against live metadata and the requested week; no arbitrary request URL/path input. `--selection sunday-afternoon` is the approved automatic rule: the **unique** group whose verified games equal exactly all REG games kicking off on the upcoming Sunday from 1:00–4:30 PM America/New_York (inclusive), contest type 21, and verified Classic roster/rules. This includes holiday weeks. It is not "most games" or "most contests", and it does not switch to a Saturday or other holiday slate when that Sunday set is missing. A manual explicit ID may target another multi-game REG Classic slate with exact evidence; it must not be labeled Sunday main. No file upload/API/UI.

The approved rule is planned behavior only. This docs package does not enable or activate the schedule. Two groups satisfying the rule are ambiguous unless explicit reviewed equivalence evidence chooses one; no lowest-ID tie-break. No candidate inside the REG season → failed reason `slate_unavailable`; never silently use another slate, week, Saturday package, or holiday substitute. Off-season is a successful skipped attempt with no DK fetch only when a verified complete season schedule establishes today is outside its first-to-final REG kickoff window; absence of Sunday games alone is not off-season, and an in-season holiday week is not off-season. Inside that window, no exact Sunday-afternoon candidate is a `slate_unavailable` failure. Missing/stale nflverse games or unknown local kickoff timezone → fail `schedule_evidence_missing`, not an off-season success.

### Evidence and HTTP boundary

Static local experiment reviewed, not executed: `/workspace/dk-experiment/reproduce.sh`, `DKSalaries-classic-dg155994.csv`, raw draftables JSON and sample JSON. CSV: 59,802 bytes; SHA `b05fcd4cb1851c76388ddbd123c2ad6c11833166962b777e7e02f6d3dd188903`; 586 salary records / 11 distinct Game Info values, games Sunday November 8, 2026 1:00–4:25 PM ET. CSV contains UTF-8 BOM and optional Status. Draftables has slot-expanded entries; never substitute its 1,077 entry count for CSV player count. Evidence shows one successful unauthenticated experiment, not endpoint stability, terms clearance, or archived-week retention.

Allowlisted discovery origin/path: `https://www.draftkings.com/lobby/getcontests` with NFL filter as demonstrated by the experiment client. Allowlisted salary URL: `https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId=21&draftGroupId={validated_id}`. If discovery lacks full games/rules, bounded public metadata reads on `https://api.draftkings.com/draftgroups/v1/{id}` and `/lineups/v1/gametypes/{validated_game_type_id}/rules` may supply them; these routes are visible in the local experiment package, **not independently proven successful in this planning pass**. Validate against fixture responses in build; missing contracts fail closed, no undocumented alternative route or crawler. Do not install the experiment's draft-kings package in the app.

Max four logical GETs per invocation: lobby, group metadata, rules, salary CSV; no per-player calls. Only known HTTPS origins/paths; reject off-allowlist redirects (at most one same-allowlist redirect), no persistent cookie jar, no auth headers, no identity-spoofing to bypass blocks. Use a transparent application User-Agent. Connect timeout 10s, read timeout 30s, total job HTTP budget 180s; at most 2 retries after initial request for timeout/5xx, backoff 1s then 2s within budget. 401/403/429, HTML/JS challenge, login redirect, unexpected response media/header, or CAPTCHA: retain bounded body privately, record reason, stop entire invocation without retry or alternate access method. Record Retry-After metadata only. Do not print salary/response bodies.

### Validation and persistence

Use the shared dictionary for actual types/keys and evidence retention. F005 builds artifacts/observations/snapshots/source-row ledger and `dk_lobby_salaries` only. The dictionary's nullable salary column does not let F005 publish a usable snapshot. Required DK headers: Position, Name + ID, Name, ID, Roster Position, Salary, Game Info, TeamAbbrev; AvgPointsPerGame may be blank; BOM allowed, column order free, extra Status/unknown columns preserved. Parse exact bytes, keep ordered raw tokens. No inferred DK ID from name or draftables player_id. Duplicate DK IDs, contradictory rows, any invalid salary, missing names, missing team/game evidence, or mismatched metadata reject the usable snapshot. Raw artifact, observation, and parseable ledger remain; `dk_lobby_salaries` gets no rows for that capture. A null salary stored only in the ledger is not a valid captured salary. Distinct parsed games >1 and no CPT in any Roster Position required. Validate complete CSV game set against selected group, kickoffs, requested season/week and Classic rules. Unknown roster rule cannot be "verified" from merely seeing FLEX.

Source scope includes group ID and game/rule evidence, content SHA, parser version; fetched_at is an observation timestamp, not a dedupe key. Same content creates a new observation linking existing parsed snapshot. A→B→A must remain three observations and two content snapshots. Changed game/kickoff/rules evidence makes a different metadata revision even with same bytes. No delete/update of successful source rows. F008 will own identity/slate mappings, not this loader.

Durable raw/attempt transaction precedes validation, per-file normalized transaction publishes only complete valid snapshot, and audit finalization follows shared crash-recovery contract. Storage guard violation → failed reason, no snapshot, prior state intact; under-limit rejected CSV/body retained. Structural parse failure may have no row ledger but always has bounded artifact evidence. Failed DB connection exits nonzero; do not claim an audit row was persisted if DB could not be reached. Public load_runs contains only dataset/counts/reason codes, private observation contains detailed path/status evidence.

### Attempt timing

Each capture attempt, including success, fetch failure, validation failure, off-season skip, and repeated identical content, is one `salary_observations` row. `started_at` and `finished_at` are wall-clock `timestamptz` values. `duration_ms` is milliseconds measured with a monotonic timer between the start and the terminal write. It is never `finished_at - started_at` and never `load_runs.finished_at - load_runs.started_at`. Public `load_runs` may store compatible wall times and has no duration column. When a snapshot is published, or when repeated content reuses one, `snapshot_id` links the attempt to that snapshot and its source rows. A failed or skipped attempt that publishes no snapshot still stores timing and leaves `snapshot_id` null. Status plus a sanitized reason/error are stored privately. Public logs, workflow output, and `load_runs.notes`/`error` contain reason codes and counts only: no secrets, raw bodies, or salary rows. If the process crashes or is interrupted before the terminal timing write, `finished_at` and `duration_ms` stay null. Recovery must not invent them or mark that attempt completed. Reconcile a running attempt only with matching durable commit evidence; otherwise mark it interrupted/failed, leave the missing monotonic duration null, and start a new attempt. If the database cannot be reached, exit nonzero and do not claim a timing or audit row exists.

### Approved schedule, not activation

New workflow separate from `dk-classic-slate.yml`; contents:read only; existing loader secret, no DK credentials. Migration/production dispatch waits for separately approved build/rollout. In-repo schedule uses the current documented GHA timezone field:

```yaml
on:
  schedule:
    - cron: '0 10 * * 3'
      timezone: 'America/New_York'
  workflow_dispatch: # validated season, week and optional explicit group inputs
```

Cosmo approved this cadence via Groko on 2026-11-06 16:59 EST as planned schedule text only. It does not activate the workflow. This is DST-aware 10:00 ET, not fixed 15:00 UTC. 10:00 is outside the DST spring-forward gap, so the local clock time stays 10:00; GitHub's skipped-hour advance does not move this cron. GitHub defaults to UTC **without** timezone. Official docs checked 2026-11-06: [workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule), [schedule event](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule). Scheduled workflows run default-branch code, can be delayed/dropped, and public-repo schedules disable after 60 days without activity. It is not a guaranteed salary lock capture. No optional Sunday cron. Derive upcoming season/week from the loaded games with timezone-aware ET conversion; a manual dispatch supplies explicit values. Concurrency group serializes this workflow with cancel-in-progress false; database locks still protect concurrent CLI runs. No Grok Bot routine, no calendar event.

## Acceptance tests

Use synthetic HTTP fixtures and a real temporary Postgres with Alembic, never live DK in CI. Each Given/When/Then can be automated. Production validation is a separate owner-approved step, not a test that must run to merge docs.

- **AT1 (R1, R4)** Given a BOM/extra-column Classic CSV and valid metadata, when captured, then exact bytes/hash read back and every row/header extra is recoverable in new private tables; F004 has zero writes.
- **AT2 (R2)** Given a valid unique Sunday-afternoon candidate, including a holiday week that also contains a Saturday slate, when selected, then only the exact Sunday 1:00–4:30 PM America/New_York group/game/kickoff/rules evidence is stored; the Saturday slate is not captured or labeled main; an explicit alternate ID is not labeled main.
- **AT3 (R2)** Given two qualifying groups, no candidate, a Saturday-only in-season holiday package, missing rules, wrong season/week, one game, CPT, duplicate ID, inexact game set, or mismatched CSV games, when run, then reason-specific failure, no Saturday/holiday substitution, retained evidence, and no usable snapshot.
- **AT4 (R3)** Given the approved workflow schedule and winter/summer sample dates, when the cron and timezone are parsed and the next execution is evaluated, then the local time is Wednesday 10:00 America/New_York in both EST and EDT; no Sunday cron, no fixed-UTC cron, and no bot routine exists. Tests assert the schedule text only and do not dispatch a live capture.
- **AT5 (R3, R2)** Given off-season verified games, stale games, an in-season holiday week with no Sunday 1:00–4:30 PM game set, and an in-season absent group, when scheduled selection runs, then only genuine off-season skips without DK calls; holiday and missing-slate cases fail `slate_unavailable` without substitution; dispatch validates season/week/ID.
- **AT6 (R4)** Given A→A→B→A captures of same identity, when ingested, then four observation timestamps, two immutable parsed snapshots and unchanged original source rows exist; identity-evidence change produces a distinct revision.
- **AT7 (R5)** Given known prior success, when a parse failure, insert constraint, mid-transaction failure, or a capture whose only defect is one invalid salary is injected, then previous rows stay unchanged, no usable or half snapshot is published, the raw artifact and any parseable ledger row for that salary remain, and a failed audit/reason appears when the DB is available.
- **AT8 (R5)** Given crash after normalized commit but before public audit finalization, when resumed, then matching commit evidence reconciles running audit without double ingest; unrelated running attempts are not marked successful.
- **AT9 (R6)** Given 403, 429 with Retry-After, login redirect, and challenge HTML, when fetched, then no retries/bypass/alternate host occurs, bounded evidence retained, previous success unchanged.
- **AT10 (R6)** Given timeouts/5xx then success/exhaustion, when fetched, then at most initial+2 transient attempts per logical request, total HTTP budget ≤180s, no off-allowlist redirects or cookies, correct failure on exhaustion.
- **AT11 (R7)** Given real PG web/optimizer roles and migrated schema, when SET ROLE queries are attempted, then web cannot read private schema or F004, optimizer can only read approved view once it exists, public nflverse/RotoGuru remain readable; rerunning grants does not restore F004 access.
- **AT12 (R7, R5)** Given object/invocation/cumulative/database limits, including concurrent inserts, when guard is exceeded, then no successful snapshot, no automatic eviction, previous data unchanged; oversized response diagnostics explicitly truncated, not a full-artifact claim.
- **AT13 (R7)** Given logs, workflow outputs and fixtures after denied/invalid loads, when inspected plus gitleaks, then no raw salaries, secrets, private paths or bodies leak; public audit contains only codes/counts, no new endpoint/page/download.
- **AT14 (R8, R1)** Given existing F003/F004 fixture regressions, when their loaders and staged-path workflow tests run after F005, then their CLI keys/replacement semantics, Classic rejects and missing-staged-file failures still pass; no live auto-fetch in F004. F004's stored trigger value `scheduled` is unchanged.
- **AT15 (R9)** Given success, off-season skip, repeated identical content, failed fetch, and failed validation, when the database is available, then each attempt stores status, a sanitized reason/error, `started_at`, terminal `finished_at`, and monotonic `duration_ms`; repeated content links the existing snapshot and source rows without duplicating them; failed attempts that publish no snapshot still store timing; public logs and `load_runs` contain no secrets or raw bodies.
- **AT16 (R9, R5)** Given a wall-clock jump during a capture, when timing is stored, then `duration_ms` equals the monotonic elapsed interval and is not `finished_at - started_at`. Given a crash before the terminal timing write, when recovery runs, then `finished_at` and `duration_ms` stay null and the attempt is not marked completed. Given no database, when the attempt cannot be written, then the process exits nonzero and does not claim a durable timing row.

## Non-goals

Historical lobby retrieval, all-slate harvesting, Showdown, postseason automatic selection, other sports/sites, optimizer/projections, API/UI/upload, paid plans, public raw downloads, changing F003/F004 source semantics. This docs package contains no implementation, migration execution, schedule activation or production data load.

## Allowed dependencies

Existing Python 3.12, SQLAlchemy Core/psycopg, Alembic, existing HTTP client, stdlib csv/hashlib/json/time/zoneinfo/uuid. Real PG test service. No draft-kings package, nfldfs, pandas, ORM, browser scraping, account or paid feed.

## Decisions

1. Q1(a), already answered: new append-only live table; keep the F004 CLI and staged-path workflow. Do not re-ask it.
2. Q1 cadence, answered by Cosmo via Groko on 2026-11-06 16:59 EST: automatic capture Wednesdays at 10:00 America/New_York during REG season. DST-correct via the GitHub Actions timezone field. Scheduled runs can be delayed or dropped, and public-repo schedules disable after 60 days without activity. This approves the planned schedule only. It does not activate a workflow. No Sunday refresh.
3. Q2 slate, answered by Cosmo via Groko on 2026-11-06 17:00 EST: automatically capture only the upcoming Sunday-afternoon Classic slate whose verified game set is exactly all REG games kicking off 1:00–4:30 PM America/New_York, including holiday weeks. No automatic Saturday or holiday substitution. Exact game set plus Classic rules must match. A missing or ambiguous candidate fails clearly.
4. Capture runtime, required by Cosmo via Groko on 2026-11-06: each attempt stores private wall-clock `started_at`/`finished_at` and monotonic `duration_ms` in Neon. Elapsed time is not inferred by subtracting clocks.

## Open questions

None. ADR 0005/0006 stay Proposed, and the constitution amendment is not in force until Cosmo merges this docs PR. That approval gate is not a product question. No forge handoff. Production changes need a later, separate approval.

## Analyze matrix

| Requirement | Acceptance tests |
|---|---|
| R1 | AT1, AT14 |
| R2 | AT2, AT3, AT5 |
| R3 | AT4, AT5 |
| R4 | AT1, AT6 |
| R5 | AT7, AT8, AT12, AT16 |
| R6 | AT9, AT10 |
| R7 | AT11, AT12, AT13 |
| R8 | AT14 |
| R9 | AT15, AT16 |

R1–R9 all covered; AT1–AT16 none orphaned. ADR 0005/0006 remain Proposed and the constitution amendment is pending owner merge. SPEC READY / DOCS APPROVAL PENDING is not a forge handoff and does not activate the schedule.

## ADRs

[0001](../../adr/0001-stack-and-hosting.md), [0002](../../adr/0002-nflverse-load-and-refresh.md), [0003](../../adr/0003-rotoguru-dk-classic-salaries.md), [0004 (live Proposed, preserved)](../../adr/0004-dk-current-slate-csv.md), [0005 (Proposed)](../../adr/0005-private-salary-capture-and-archives.md), [0006 (Proposed)](../../adr/0006-slate-safe-salary-unification.md).
