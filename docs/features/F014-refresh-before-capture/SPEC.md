# F014: Refresh before private lobby capture

Status: **DRAFT — Cosmo approval pending** (2026-11-11 America/New_York). Docs authoring only; not READY and not handed to forge. Request relayed by dr eggbot as Cosmo-approved planning. This is not an independently verified production authorization. Dependency: open PR #42's F005 R1–R14/AT1–AT31 and ADR 0012; do not overwrite that amendment.

## Problem / job to be done

Make refresh-before-capture a causal sequence rather than a bet on two GitHub cron events. Keep the independent schedule-completeness proof and existing private salary safety rules. GitHub can still delay/drop the capture event itself; this feature guarantees prerequisite order when an execution actually runs, not a clock-time SLA. [Evidence](EVIDENCE.md) records source lines, all workflows, the six returned schedule records, and the reported 403, which is out of scope because this design does not dispatch.

## Requirements

- **R1** Run one ordered capture pipeline on the existing capture job: validate inputs and exact-true gate, perform the existing gated migration once, run the normal full nflverse refresh, verify proof, then invoke capture. Use the same checked-out revision and existing loader configuration. Do not dispatch another workflow or proceed via continue-on-error/always after a failed prerequisite. When the capture gate is not exactly true, perform no migration, refresh, proof write or DK call.
- **R2** Keep manual season/week and selector validation, including existing alternate multi-game REG Classic rules, before refresh writes. Manual refresh loads that requested season. Automatic refresh uses the normal loader current-season default; derive capture season/week only from subsequently verified finite coverage and schedule evidence. If the relevant active season was not refreshed by this invocation, fail schedule_evidence_missing rather than infer it from month/week heuristics or reuse another season. A valid independently supported gap can still return off_season without DK calls.
- **R3** Fail closed if any full-refresh dataset fails, the refresh times out, is cancelled, or cannot produce required games evidence. Do not call DK or publish salary rows/snapshots. Use refresh_failed for refresh failure and schedule_evidence_missing for absent/invalid/misbound proof. Preserve prior salary data. Keep normal refresh per-dataset transactions: successful public dataset changes may remain after another fails; do not roll them back or claim whole-refresh atomicity.
- **R4** Require the complete ADR 0007 authority/raw/receipt/current whole-season PG and timing proof immediately before any DK request. For active capture, restrict eligible receipts to successful relevant-season games loads from the just-completed pipeline refresh run_group; missing current proof cannot fall back to yesterday's still-fresh receipt. Require actual upstream retrieval within 24 hours and at most five minutes future skew; preserve publisher version separately. A new load completion, copied file, self-hash or old cached bytes must not renew retrieval age. Normal standalone refresh without private gates remains valid public loading but cannot satisfy F014 capture without proof.
- **R5** Preserve F005/#42 R3/AT4: one Wednesday 10:07 America/New_York cron (7 10 * * 3), DST-correct, REG-only automatic capture. Keep upcoming Sunday-only 1:00–4:30 PM ET exact game-set matching, Classic checks, ambiguity failure, and manual alternate-slate labeling. Add no Sunday capture or extra refresh cron and leave ADR 0002's existing daily public refresh unchanged. A late/dropped capture trigger is not repaired by this ordering change; never claim on-time execution or substitute another slate.
- **R6** Serialize all participating normal-refresh and direct-capture entry points, including local CLI and manual dispatch, with a shared database session coordination lock distinct from CAPTURE_LOCK. Hold it from before the pipeline migration through terminal capture; acquire it before existing private locks. Pipeline children share a trusted in-process ownership context, not a user-controlled lock-skip flag. A standalone operation acquires/releases its own coordination ownership. Wait at most 120 seconds, then fail pipeline_busy before source work; impose a 30-minute pipeline deadline. Stop on lock-connection loss and do not publish afterward. Never cancel a running writer to make room. Keep capture workflow concurrency dk-lobby-capture, cancel-in-progress:false, and give standalone refresh its own non-cancelling serialization group; do not use a shared GitHub pending-slot group as the only ordering guard.
- **R7** Preserve idempotent normal refresh natural-key behavior and F005 decoded-content/identity/parser dedupe. Sequential genuine manual, scheduled or retry invocations remain distinct audited attempts, but cannot overlap and must not duplicate immutable salary artifacts, ledger rows or snapshots when their content and identity are unchanged. A crash after commit must reconcile matching durable evidence before retry; never infer success or fabricate completion from elapsed time. No exactly-once HTTP or guaranteed GitHub queue delivery claim.
- **R8** Keep workflow_dispatch as the manual entry point with existing validated inputs. Runtime GITHUB_TOKEN remains contents:read; orchestration makes no dispatch API call and needs no actions:write. Document that an external fine-grained/app caller needs repository access and Actions:write; classic/OAuth and repository policy requirements must be checked separately, with a repository-authorized user/browser as the manual fallback only after authorization. Do not collect credentials or expand grants to diagnose the prior 403. Fixing that 403 is a non-goal.
- **R9** Preserve ADR 0005/0007 and #42 ADR 0012 storage/privacy contracts: discovery-only 33,554,432 decoded bytes; other kinds 5,242,880; 67,108,864 decoded per invocation; cumulative private relation guard 536,870,912 and database guard 805,306,368; warnings, gzip/identity hashes/lengths, lower verified free allowance and audit headroom unchanged. No deletion, eviction, new public salary output, F004 ingestion changes, or seamfinder_web/PUBLIC/optimizer grant changes. Each actual loader/capture invocation keeps its own budget; do not reset a capture budget mid-attempt or use compression to evade decoded limits.
- **R10** Treat this as a proposed docs contract, not permission to build or roll out. Reconcile/merge PR #42, obtain Cosmo approval through Groko, then hand to forge. The reported-403 follow-up is non-blocking and is not a READY gate. Implementation uses synthetic source fixtures and real temporary Postgres; no live DK CI. Cloud-agent implementation/review stays running until every CI check on the final head finishes. Record all results, including failures/unknowns. Existing production-migration approval for ADR 0012 is not approval of a new revision or production dispatch.
- **R11** Use existing load_runs and private salary_observations lifecycle/audit shapes. Capture-stage success, failure, skip and repeats retain wall start/finish and monotonic duration. A pre-capture refresh failure gets a failed pipeline observation (reason refresh_failed) when the database is available, with snapshot_id null and no salary rows; its duration covers pipeline execution and is explicitly distinguished from capture duration. Add private metadata as specified below to bind refresh, proof and capture. If DB is unreachable, emit a sanitized failure and exit nonzero without claiming durable audit. Public logs/summary/notes/errors contain only stage/result codes, counts and permitted byte counts; never raw evidence, names, player identifiers, salary values or credentials.
- **R12** List exact infrastructure/configuration changes before merge: Render none (no service, plan, build/start command, environment, health path, domain or scheduler change); Neon none (no schema/migration, role/grant, branch, plan or compute setting change); GitHub reuses DATABASE_URL, READONLY_ROLE, SALARY_PRIVATE_MIGRATION, DK_SCHEDULE_AUTHORITY_SHA256 and DK_LOBBY_CAPTURE_ENABLED with unchanged values, and changes only orchestration/concurrency in the later implementation. If this inventory changes, update the docs/PR with exact old→new settings and obtain applicable approval before merge. After any deploy, check the live public site and /api/health, recording the result without private payloads; this docs task does not deploy or perform that production check.

## User stories

- As Cosmo, I want capture to refresh its prerequisite itself, so a late daily cron cannot determine whether it runs against yesterday's schedule.
- As a reviewer, I want the exact refresh/proof linkage and failures retained privately, so a green public refresh cannot hide missing certification.
- As an operator, I want manual recovery and concurrent invocations to keep the same safety rules without broader runtime token permissions.

## Observable behavior

### Inputs and ordered execution

Existing workflow schedule/manual inputs, existing repository gate, loader DB identity, private migration gate and authority pin remain the inputs. Add no arbitrary URL, credential, public API, upload or bypass input. Manual invalid input fails before writes. After validation/gate, run migration once through the existing gated path; then an internal pipeline invokes the full existing loader and the capture in order. No child Actions run or dispatch polling. The full refresh uses the existing four datasets, order, source URLs, natural keys and per-dataset transactions; it is not a new games-only loader.

The pipeline passes the actual refresh run_group and successful relevant-season games load identifiers internally to proof selection. It cannot manufacture a success by querying whichever old load happened to be latest. Keep ADR 0007's consistent whole-season comparison and independent authority. Retrieval freshness refers to the actual upstream retrieval; a locally staged/cached input must retain its real original retrieval evidence or fail the capture precondition. Automatic season derivation must agree with a season actually loaded in this invocation. A verified finite gap has no DK fetch and follows existing off_season semantics.

### Outputs, data shape and errors

Reuse [data dictionary](../../data-dictionary.md#transaction-and-audit-contract-for-all-four-features) load_runs and salary_observations, plus the existing [schedule proof](../../data-dictionary.md#f005-schedule-completeness-proof-adr-0007-accepted). No new relation or column. New optional private salary_observations.metadata keys:

| Key | Shape / meaning |
|---|---|
| pipeline_stage | migration / refresh / proof / capture / terminal |
| pipeline_refresh_run_group | UUID string of this invocation's normal refresh; null if it never started |
| pipeline_games_load_run_ids | array of bigint identifiers from that refresh, relevant season checked; empty before they exist |
| pipeline_timing_scope | capture for an actual F005 attempt; pipeline for a pre-capture failure observation |

Existing schedule proof references identify the selected receipt. A failure before capture creates a normal failed audit/observation when reachable, without invoking the DK HTTP stage, and uses pipeline timing scope. An actual capture retains its existing timing start and duration; refresh time is not mislabeled as capture HTTP runtime. Migration failure before tables are available may prevent observation creation; emit a safe failure, never invent persistence. Existing load_runs status vocabulary is unchanged; off-season remains the existing public/private status mapping.

New orchestration reasons are refresh_failed, pipeline_busy, pipeline_lock_lost and pipeline_timeout; missing proof stays schedule_evidence_missing. Migration or database-unreachable failure uses the existing safe reason and nonzero exit. Cancellation (when controllably finalized), lock loss (pipeline_lock_lost) and the total deadline (pipeline_timeout) stop all downstream work and cannot claim successful completion; interrupted attempts may retain null finish/duration. Successful F005 validation may publish/reuse one snapshot; failed prerequisites publish zero salary rows and no new snapshot. Partial public-refresh commits remain legitimate ADR 0002 results, never a successful salary capture.

### Concurrency, repeats and boundaries

Database coordination is authoritative across all normal-refresh and capture entry points, not merely GitHub runners. Use a new coordination lock distinct from private storage locking. Never hold the private CAPTURE_LOCK on an outer connection while another connection's receipt producer needs it. Keep one acquisition order (coordination then private), release via finally/connection termination, and terminate child work when ownership is lost. The pipeline owns coordination once across both stages. Standalone CLI operations use the same boundary, without a public bypass flag.

GitHub concurrency does not guarantee FIFO or delivery of every queued event. Keep separate non-cancelling workflow groups and use the database lock for cross-workflow exclusion. Each real sequential request can refresh again and creates a new attempt, as F005 requires; content-level idempotence prevents duplicate salary data. This is not a new durable exactly-once task queue. No new automatic DK retries, alternate host, evasion, Sunday capture cron, freshness widening or salary fallback.

### Infrastructure and rollout inventory

Render: **no changes**. Neon: **no new schema, migration, grants, branch, plan or compute changes**. Existing loader writes remain the only writes. GitHub variable/secret names and values stay unchanged; implementation later changes pipeline invocation and standalone refresh concurrency/coordination only. The existing daily cron remains. Exact Render/Neon divergence must be listed in the PR before merge and approved where required; any deploy gets live public site and /api/health checks. This docs package runs none of those steps. Record first approved capture's existing ADR 0012 discovery/compressed-size/storage forecast measurements privately and send only safe counts through the coordinator.

## Acceptance tests

Use synthetic inputs and real temporary Postgres. These are proposed checks, not claims that tests were run by this docs-only task.

- **AT1 (R1, R2, R4)** Given an enabled pipeline with synthetic full-refresh success and valid current-run proof, when scheduled and manual executions run, then the event trace shows gate/validation → migration once → full refresh completion → proof → capture; all stages use one checkout, and only the selected relevant-season games loads satisfy capture.
- **AT2 (R1)** Given gate values unset, false or TRUE, when either trigger is evaluated, then the pipeline performs zero migration, refresh, proof writes and DK calls; exact true alone permits execution.
- **AT3 (R2)** Given missing or invalid manual season/week or conflicting/invalid selectors, when the job starts, then it rejects input before migration/refresh writes or DK requests with existing validation reasons.
- **AT4 (R2, R4)** Given an automatic refresh of one season and verified coverage requiring another, or a valid finite interseason gap, when selection runs, then the mismatch fails schedule_evidence_missing with no DK; the independently valid gap follows off_season with no DK and does not invent a current season.
- **AT5 (R3, R11)** Given a failed games load, a failed stats/teams/players load, timeout or cancellation after partial refresh commits, when pipeline control reaches the prerequisite result, then no DK request or salary publication occurs, prior salary snapshots remain, successful public dataset commits remain per ADR 0002, and available audit records refresh_failed; no stale fallback occurs.
- **AT6 (R3, R4)** Given refresh exits successfully but private gates are off, pin is missing, receipt persistence fails, or the raw/current-PG/inventory proof is invalid, when proof is evaluated, then schedule_evidence_missing occurs with no DK call or usable salary snapshot even if a public refresh row succeeded.
- **AT7 (R4)** Given an older valid receipt under 24 hours plus a just-completed refresh without a valid bound receipt, or a receipt for another run_group/season, when capture preconditions run, then the older/foreign receipt cannot satisfy them; a valid current-run receipt succeeds, stale retrieval and future skew over five minutes fail, and freshly retrieved unchanged publication/bytes can pass.
- **AT8 (R5)** Given winter and summer reference dates and the workflow text, when cron and timezone are parsed, then the single automatic slot is Wednesday 10:07 ET in each season; there is no new Sunday/dual-UTC cron or external scheduler, and the independent daily public refresh is unchanged; no live workflow dispatch is used.
- **AT9 (R5)** Given holiday Saturday alternatives, an exact upcoming Sunday set, ambiguous/wrong/non-Classic groups and manual explicit alternates, when selection is evaluated after refresh, then only the valid exact Sunday window is automatic, the existing alternate label is preserved, and ambiguity/missing/invalid candidates fail without substitution; delayed event delivery never asserts on-time success.
- **AT10 (R6)** Given two real Postgres sessions launching refresh/refresh, pipeline/refresh and direct-capture/pipeline concurrently, when they compete for coordination, then only one enters source/data work, the other waits at most 120 seconds then fails pipeline_busy if needed, and a queued operation re-verifies proof after acquiring ownership; GitHub workflow groups do not cancel active writers.
- **AT11 (R6)** Given a pipeline holding coordination while its child emits a receipt under CAPTURE_LOCK and an injected lock-connection loss or total deadline expiry, when the child executes or failure is injected, then no cross-connection self-deadlock occurs, no lock-skip input bypass is accepted, work stops without later salary publication on ownership loss, and locks release on termination; capture HTTP still obeys its separate 180-second budget.
- **AT12 (R7)** Given sequential unchanged-content refresh/capture invocations with matching identity and parser, when they complete, then normal public data is idempotent and immutable salary artifacts/ledger/snapshots are reused while each genuine capture receives its own observation, proof references and timing.
- **AT13 (R7, R11)** Given crashes before publication and after snapshot commit but before audit finalization, when recovery and a deliberate new attempt run, then only matching durable commit evidence reconciles success, no duplicate salary snapshot is inserted, old data remains, and interrupted finish/duration stay null rather than being fabricated.
- **AT14 (R8)** Given workflow files and a documented manual-dispatch authorization checklist, when a reviewer checks dispatch and permissions statically without submitting it, then workflow_dispatch and input validation remain, runtime contents:read is unchanged, no nested dispatch/polling or actions:write escalation is introduced, external caller permission is distinguished from runtime permission, and the historical 403 stays an unproven non-goal rather than a build-path blocker.
- **AT15 (R9, R11)** Given synthetic boundary/oversize bodies, concurrent guarded writes, denied requests and public-role queries, when F005/#42 guard, encoding, denial and privacy regressions run against real temporary Postgres, then all decoded limits, gzip/identity hashes, 512/768 MiB guards, warnings and no-deletion behavior remain; no grant changes or public raw data appear, and F003/F004 paths remain unchanged.
- **AT16 (R10, R12)** Given the proposed spec, dependency state and eventual implementation final head, when handoff or merge readiness is reviewed, then forge is held until Cosmo approves and #42 is reconciled; the reported-403 follow-up is non-blocking; every CI check must finish before readiness is claimed, and no production action is inferred from docs or CI.
- **AT17 (R11)** Given success, proof failure, pre-capture refresh failure, valid gap, repeated content and unreachable DB cases, when audit is read back or output inspected, then available private records bind the actual refresh and proof with correct stage-specific timing and null failed snapshot; public output contains only safe codes/counts/allowed byte counts; unreachable DB never claims an audit exists.
- **AT18 (R12)** Given the implementation PR and deployment checklist, when exact changes are compared with the approved inventory, then Render and Neon changes are explicitly none unless separately documented and approved before merge, existing GitHub variable values and grants remain, and any actual later deploy has a recorded live-site and /api/health check rather than a CI-only success claim.

## Non-goals

Exact-time execution or replacement of GitHub's scheduler; advancing either cron; paid infrastructure; general task queues; automatic authority approval/repair; changing upstream schedules or loaders' natural-key semantics; public salary outputs; F004 replacement; F007 archive tolerance changes; optimizer/unified-view rebuild; new accounts or credentials; production migration, dispatch or deployment from planning. Do not patch code, tests, workflows or migrations in this proposal.

Fixing agent-initiated `gh workflow run` (the reported 403) is out of scope; F014 does not need a dispatch. Likely cause: the caller's credential lacks repository Actions write permission (unproven).

## Allowed dependencies

Existing Python 3.12, stdlib, SQLAlchemy Core/psycopg, normal nflverse loader and source client, F005 capture/proof/privacy helpers, existing gated migration runner, GitHub Actions and real temporary Postgres. No new runtime package, scheduler, service, token, role or account. Engineering may refactor shared orchestration internals only after the contract is approved.

## Open questions

- **Non-blocking.** Follow-up: if agents need manual dispatch, record the caller identity and permission in a separate change.

## Analyze matrix

| Requirement | Acceptance tests |
|---|---|
| R1 | AT1, AT2 |
| R2 | AT1, AT3, AT4 |
| R3 | AT5, AT6 |
| R4 | AT1, AT4, AT6, AT7 |
| R5 | AT8, AT9 |
| R6 | AT10, AT11 |
| R7 | AT12, AT13 |
| R8 | AT14 |
| R9 | AT15 |
| R10 | AT16 |
| R11 | AT5, AT13, AT15, AT17 |
| R12 | AT16, AT18 |

R1–R12 all covered; AT1–AT18 all name existing requirements, none orphaned. Policy check: no new conflict with ADR 0002/0005/0006/0007/0009 or the PR #42 ADR 0012 contract. The proposed constitution cadence-text alignment is included explicitly, not silently assumed accepted; it changes no live schedule. The reported 403 is a non-blocking follow-up, not a build-path blocker. Implementation handoff waits on Cosmo approval. The capture's own GitHub trigger remains best-effort.

## ADRs

[0001](../../adr/0001-stack-and-hosting.md), [0002](../../adr/0002-nflverse-load-and-refresh.md), [0004](../../adr/0004-dk-current-slate-csv.md), [0005](../../adr/0005-private-salary-capture-and-archives.md), [0006](../../adr/0006-slate-safe-salary-unification.md), [0007](../../adr/0007-authoritative-schedule-completeness.md), [0009](../../adr/0009-dknfl-kickoff-tolerance-and-free-agent-rows.md), [0012 (pending PR #42)](https://github.com/tjonesy10/seam-finder/blob/2a89f83fb3cc15eeb6c7becc768190c576199ebe/docs/adr/0012-dk-discovery-object-cap.md), [0013 (Proposed)](../../adr/0013-refresh-before-lobby-capture.md).
