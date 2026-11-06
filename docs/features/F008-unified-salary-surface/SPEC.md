# F008: One private, slate-safe salary surface with preserved alternatives

Status: **SPEC READY / DOCS APPROVAL PENDING** (2026-11-06). No open product questions. F005 cadence and the Sunday-afternoon slate rule are answered. ADR 0005/0006 remain Proposed and the constitution amendment is not effective until Cosmo merges this docs PR. No forge build or production merge is authorized by this proposal.

Related: [constitution](../../CONSTITUTION.md), [architecture](../../architecture.md), [dictionary](../../data-dictionary.md#proposed-f005f008-private-salary-contract-draft-not-deployed), [glossary](../../GLOSSARY.md), [F003](../F003-dk-classic-salaries/SPEC.md), [F004](../F004-dk-current-slate/SPEC.md).

## Problem / job to be done

Offer a future private optimizer one explicit read contract across independently attributable sources without confusing week with slate, vendor IDs with player identity, or independent snapshots with a real eligible pool. Preserve uncertain/legacy/subset rows so gaps are visible, not silently filled.

## Requirements

- **R1** Provide one private SQL view `salary_private.dk_salary_unified` with dictionary-defined candidate, provenance, selection, quality and readiness columns; no optimizer code/API/UI.
- **R2** Version player/DST mappings and slate equivalence with evidence. Verified slate requires exact game/kickoff set and compatible roster/rules; season/week/name/ID similarity alone never merges records.
- **R3** Select one coherent anchor snapshot per verified slate revision, deterministic within-source latest/as-of and then reviewed source priority; never build a player pool by row-wise snapshot union or missing-player fallback.
- **R4** Retain all comparable source alternatives and salary/eligibility disagreements with references; ambiguous/unresolved/subset/incomplete cases are explicitly not optimizer-ready, not silently discarded or resolved.
- **R5** Adapt F003 as legacy/unknown slate and F004 only from currently retained row evidence, without asserting historical snapshots or rewriting either source.
- **R6** Publish selection batches atomically and idempotently, audited with counts/mapping coverage, failure leaving prior active batch unchanged.
- **R7** Enforce private grants/storage/provenance attribution and no public raw exposure; preserve every original source artifact/row.

## User stories

- As an engineer, I want one pinned private salary selection to query, so that a later optimizer cannot accidentally mix revisions or holiday slates.
- As Cosmo, I want disagreements and coverage gaps visible with their sources, so that a plausible but wrong price does not silently win.
- As a researcher, I want legacy weekly evidence preserved without false main-slate fidelity, so that backtests know what is and is not verified.

## Observable behavior

### One-pass deliverable and input contract

Later build adds only the interpretation/selection tables, current-row adapters, a rebuild CLI and the private view from the dictionary, with real-PG tests. Dependencies are F005 shared persistence and F006/F007 source tables (approved independent builds). No optimizer, solver, app wiring, API, upload, remote source collector or public route. It may work with empty source tables and must report empty coverage, not fabricate data.

Proposed CLI:

`python -m loader.salary_unified --selection-scope LABEL --as-of ISO8601_WITH_OFFSET --mapping-file PATH [--trigger local|manual]`

Mapping-file is bounded local JSON stored verbatim as private `mapping` artifact, with SHA and a `mapping_version` string. Top-level shape:

```json
{
  "mapping_version": "reviewed-v1",
  "slates": [],
  "entities": [],
  "snapshot_choices": [],
  "resolutions": []
}
```

- `slates[]`: `{source,snapshot_id,canonical_slate_key,slate_revision_sha256,status,games,rules,draft_group_id,equivalent_group_ids,evidence_artifact_id,reason,complete_pool,effective_at,effective_time_basis}`. Hash is recomputed from canonical games/rules, not trusted input; kickoff times must be explicit-offset instants. `status=verified` requires exact whole game set, rules and evidence, not just games involving present players. Different native groups require explicit evidence for equivalence; equality of a hash or matching a few players is insufficient.
- `entities[]`: `{source,snapshot_id,row_number,status,gsis_id,team_abbr,game_id,candidates,method,evidence_artifact_id,reason}`. Skill verified only on unique GSIS with team/game/position context; DST key requires correct season team mapping. Record method/version and evidence hash for name/team joins or explicit reviewed crosswalks. No fuzzy auto-accept, salary-only join, stub player, or bare vendor/native-ID join. Unlisted candidates become unresolved, not guessed.
- `snapshot_choices[]`: optional explicit `{source,canonical_slate_key,slate_revision_sha256,snapshot_id,anchor,evidence_artifact_id,reason}` to resolve archives lacking reliable effective chronology. It must refer to a successful candidate available by cutoff and verified equivalent slate, never to a different source/slate. At most one verified `anchor=true` choice per slate revision may choose the whole anchor across sources when effective-time comparison is unknown; this does not permit per-player overrides. No invented source timestamp.
- `resolutions[]`: optional `{canonical_slate_key,slate_revision_sha256,entity_key,candidate_refs,chosen_ref,evidence_artifact_id,reason}` for salary/eligibility disagreements. Chosen ref must belong to the same anchor snapshot under this version's no-pool-mixing rule; overriding to another source requires choosing that whole anchor snapshot in a new selection. Resolved disagreement still retains flag, alternatives and resolution evidence; unresolved disagreement blocks readiness.

All supplied IDs must exist and agree with publisher/snapshot/row/game context; evidence may reference newly stored control mapping bytes or acquired private artifacts, not a public unaudited note. Validate references and 5 MiB mapping-object limit before publish. Conflicting duplicate mapping entries/version+hash keys fail. Same version label with different evidence yields new immutable interpretation, not a source update. Mapping updates are loader-local review inputs, not user account/auth/UI features.

As-of requires an explicit timezone offset; CLI rejects naive time. View timestamps are instants; reports show ET. Cutoff is a reproducibility boundary, not a license to claim unknown source publication time. Rebuild captures a consistent DB input snapshot (REPEATABLE READ or equivalent explicit snapshot IDs) including adapters, records its ordered inputs/mapping SHA, then publishes atomically. File/network source data are never modified.

### Selection algorithm and quality behavior

1. Read all candidate source rows/successful observations visible in the consistent DB input as of cutoff. Local archive observations must exist by cutoff; their retrieval times do not rank historical salary versions. Retain candidate/rejected/legacy records with quality flags in the output, including ones excluded by cutoff (`after_cutoff`) if present in the rebuild's input; they never affect a chosen pool.
2. Apply versioned slate and entity interpretations. Unverified or ambiguous slate/identity remains flagged, `is_selected=false`, `optimizer_ready=false`. Known slates never match `legacy_unknown`. Native DFF ID stays DFF ID; DK draftable IDs remain source/snapshot-scoped.
3. Per source and verified equivalent slate revision choose the latest successfully parsed snapshot as of cutoff, then evaluate its completeness/readiness; never silently skip a newer successful but incomplete snapshot to resurrect an older ready pool. F005 uses latest successful observation at/before cutoff; repeated A→B→A selects A at the final observation. Live/owner effective-time evidence is used only as actually known; F004 `source_loaded_at` is import observation, not original publication time. Equal known times tie-break by artifact SHA then snapshot UUID lexicographically. Historical archive snapshots with different bytes and no source chronology are flagged `chronology_unknown`; no arbitrary filename or later download wins. Use evidence-backed snapshot_choices or leave no ready anchor. Byte-identical duplicate exports may be folded as equivalent alternatives, retaining each path reference.
4. Only after equivalent entity+slate verification, choose an anchor among those latest source snapshots; unverified completeness blocks readiness rather than permitting fallback to an older revision. Proposed order: verified official DK family first (F004 owner export/F005 lobby), then DKNFL, then DFF. Within official family latest verified effective time wins, owner export before lobby only for equal times/equal fidelity. Unknown competing effective times need an explicit snapshot choice; never prioritize an old owner load over a later live price by label alone. Priority is an ADR review choice, not a claim Cosmo selected it.
5. Anchor alone defines pool membership, salaries and native IDs. Do not fill an anchor's missing or unresolved entity from another snapshot, source or slate. Lower-source data attaches only as verified-equivalent alternatives to anchor members; extra entities remain `alternative_not_in_anchor`, not selected additions. A credible eligible-member difference between verified-equivalent full exports also sets `pool_membership_disagreement` and blocks pool readiness until evidence resolves it; a subset is never evidence that absent players are ineligible. No second snapshot from the same source can patch it. This conservative version does not permit per-player salary overrides from lower-ranked sources.
6. For each anchor member compare verified equivalent alternatives: differing salary or roster eligibility → `disagreement` with candidate refs/values. All values and mapping evidence remain queryable. Without explicit evidence-backed resolution, the affected pool is not ready. Never compare as disagreement if slate/entity equivalence is not proven; flag the unresolved mapping instead. Never drop a low salary or zero salary to force agreement.
7. `pool_ready=true` requires verified complete source pool, verified whole slate/rules, unambiguous mapping for **every valid eligible anchor member**, positive integral salaries, no unhandled duplicate/conflict, and no unresolved disagreement. A raw placeholder rejected for blank name/salary is excluded with evidence, not a pool member; any rejected record plausibly representing an eligible player makes completeness unverified. `optimizer_ready` on selected rows requires both that whole-pool condition and verified entity. DFF is a subset and never a ready complete anchor. Distinct complete exports may have different eligible pools at different times; no synthetic union is permitted.
8. Source rows not selected are still visible with flags and full refs. A consumer pins `selection_id` and a verified canonical_slate_key+revision, filters `is_selected AND optimizer_ready AND pool_ready`. An unqualified query by season/week/player is explicitly unsafe. An empty ready set is a truthful result, not permission to lower standards.

### Existing-source adapters, not imaginary archives

F003 key `(season,week,rotoguru_gid)`, source salary/actual DK points and current nullable mapped IDs are preserved in a derived row-image artifact with provenance. Snapshot kind `legacy_unknown`, no known slate revision or group; existing `game_id` per row does not prove the intended complete game set. Always false optimizer readiness for known slates; no F003 fallback into DFF/DKNFL/live main. Keep original RotoGuru attribution exact.

F004 key `(season,week,dk_id)` is destructive weekly replacement; mixed `source_sha256` cohorts and missing historical raw bytes cannot be repaired by this adapter. Read the **currently retained** rows as one coherent source-hash cohort only, keeping source_loaded_at, name, raw Game Info/roster strings and row-level provenance. Store a derived current row image; `raw_retained=false`, kind `adapter_current`; no old snapshot enumeration or invented fetch timestamp. Derive available observed game-set/kickoffs from all current rows. If unknown/ambiguous kickoff/rules, mixed cohorts or unverified full eligible pool, flag and keep not ready. A reviewed original export/evidence with matching source SHA may establish fidelity for current rows; restaging/verification is a later manual input, not a new F004 data-model rewrite in this feature. Existing F004 default upsert/delete keys and staged workflow do not change.

### Publication and audit

Dictionary defines view columns, immutable interpretation keys and batch partial uniqueness for selected entity. Dataset `dk_salary_unified`; one public load_runs per rebuild invocation (season null if multi-season); safe counts/reason codes only. Detailed per-source/snapshot coverage report stays private in batch summary and optional local operator output, not public Actions logs.

Report denominators separately: raw records; parsed records; valid salary records; skill and DST; skill uniquely mapped/unresolved/ambiguous; DST mapped/unresolved; slate verified/unknown; subset/full/legacy; excluded duplicates; disagreement count; selected rows; ready pool/row counts. Percentages use explicit numerator/denominator, null for zero denominator. Never inherit F003 ≥98% or F004 ≥95% targets here; no mapping coverage has yet been measured for these sources. The earlier 9,379 name+team salary overlaps are a salary crosscheck, not entity/slate equivalence or GSIS coverage.

Batch+all selection rows insert in one transaction; current batch is latest committed per selection_scope. Repeated identical input/mapping/cutoff reuses batch key but audits a new attempt. A crash, bad mapping reference, duplicate selected entity, constraint failure or missing source table gives a failed run and leaves prior current batch/sources intact. Shared locks prevent partial/concurrent publication and storage-guard races. Private role can read view; web has neither schema USAGE nor view/source SELECT. No new public resource registration; sanitize source details from public load_runs. Raw retained in private Neon, not attached to public test reports.

## Acceptance tests

Tiny synthetic PG source fixtures cover exact slates, alternate games, timestamps, mappings and all source adapters. Run migrations against real temporary Postgres, use actual SQL view/grants and transaction failures, not mock-only tests. No live source fetch needed.

- **AT1 (R1)** Given populated independent source fixtures, when rebuilding/querying view, then required dictionary columns/PK join semantics and source-specific attribution are present; one private read contract and no API/UI/optimizer code is added.
- **AT2 (R2)** Given same week/player with different draft groups/games/kickoffs/rules, when mapped, then no equivalence is inferred; only explicit verified compatible group evidence may relate the exact matching slate revision.
- **AT3 (R2)** Given identical-looking DFF/DK IDs, name collision, team transfer, DST historical team alias and an unresolved player, when interpreted, then namespace/context checks prevent false GSIS join, DST maps by team and every candidate/evidence version remains traceable.
- **AT4 (R3)** Given live observations A→B→A, same-time ties and cutoff before final A, when rebuilt, then deterministic correct source snapshot/observation is pinned; no per-player latest row mix occurs.
- **AT5 (R3)** Given differing historical files with no reliable chronology, when selected without/with explicit evidence-backed snapshot choice, then no false latest-by-download/path is used and only the reviewed valid choice may become anchor.
- **AT6 (R3, R4)** Given one complete anchor missing an alternative-only player, an unresolved anchor member, a DFF subset and a holiday slate, when rebuilt, then no pool-filling/union occurs; incomplete/subset pools stay not ready and alternate-only rows stay flagged.
- **AT7 (R3)** Given verified equivalent official-family, DKNFL and DFF records, when priorities apply, then newer verified official effective time wins, equal-time owner tie is deterministic, and all selected pool members come from exactly one anchor snapshot. Non-equivalent records never participate in priority.
- **AT8 (R4)** Given comparable salary/eligibility disagreement, when built without/with valid resolution evidence, then alternatives/values/refs persist, unresolved disagreement blocks ready pool, resolved flag/evidence remain; cross-source per-player override is rejected.
- **AT9 (R4)** Given duplicate/conflicting entities, zero salary, unverified rules, ambiguous slate or a rejected plausible player, when built, then reason flags appear and optimizer-ready filter excludes unsafe pool; genuine blank placeholders are retained/countable but not fabricated eligible members.
- **AT10 (R5)** Given F003 weekly records plus known live slate, when adapted, then legacy_unknown never fills/joins the known slate; raw source and RotoGuru points/attribution remain unchanged and no original CSV bytes are invented.
- **AT11 (R5)** Given F004 current single-hash and mixed-hash cohorts with missing historical raw bytes, when adapted, then only current row images/evidence exist, raw_retained=false, incomplete/mixed evidence prevents readiness, no replaced historical rows or fetched timestamp is asserted; F004 loader contract remains unchanged.
- **AT12 (R6)** Given identical rebuild twice then changed mapping evidence, when published, then identical batch reused with independent audits, new evidence appends interpretations/new batch, and old pinned batch remains reproducible.
- **AT13 (R6)** Given prior current selection and injected failure/crash/duplicate-key/concurrent rebuild, when run, then no partial batch appears, current prior selection remains until complete commit, source rows unchanged and audit reflects durable evidence only.
- **AT14 (R6)** Given mixed mapped/unmapped/DST/subset/legacy fixtures, when coverage computed, then explicit denominators/counts reconcile to source rows, zero-denominator rates are null and no unsupported target/coverage claim appears publicly.
- **AT15 (R7)** Given actual PG web and optimizer roles, when view/raw queries and repeated grants run, then web is denied private sources/view/F004; approved optimizer can SELECT view only, not write; original artifacts hash-readback unchanged, public nflverse/RotoGuru access still works.
- **AT16 (R7, R6)** Given bad mapping reference, naive cutoff, oversized evidence or storage guard, when rebuilt and logs/gitleaks inspected, then bounded controlled failure, unchanged prior batch, no raw/private diagnostics/secrets/public routes/downloads or automatic deletion.

## Non-goals

Optimizer/solver/projections/scoring, APIs/UI, public exposure, new historical retrieval, rewriting F003/F004, claiming full DFF/legacy coverage, automatic fuzzy identity resolution, roster-pool patching, materialized-view refresh service, production migrations/dispatch in this planning package.

## Allowed dependencies

Approved F005–F007 tables/contracts, existing Python/SQLAlchemy Core/psycopg/Alembic, stdlib JSON/hash/zoneinfo. Read-only existing players/teams/games and F003/F004 adapters. No ORM/pandas/solver/paid feed/new account or live network access.

## Open questions

No open product questions. Priority, anchor, evidence, and privacy choices are ADR review decisions recorded in Proposed ADR 0006, not unanswered user questions. F005 cadence and the Sunday-afternoon slate rule were answered 2026-11-06. ADR 0005/0006 and the explicit constitution amendment still require Cosmo's docs merge before any build. Unresolved actual source identity/slate mappings are expected flagged data, not permission to mark optimizer-ready or a reason to guess. Coordinator supplies missing evidence if needed. No forge handoff.

## Analyze matrix

| Requirement | Acceptance tests |
|---|---|
| R1 | AT1 |
| R2 | AT2, AT3 |
| R3 | AT4, AT5, AT6, AT7 |
| R4 | AT6, AT8, AT9 |
| R5 | AT10, AT11 |
| R6 | AT12, AT13, AT14, AT16 |
| R7 | AT15, AT16 |

R1–R7 all covered; AT1–AT16 none orphaned. ADR 0005/0006 remain Proposed and the constitution amendment is pending owner merge. SPEC READY / DOCS APPROVAL PENDING. No build handoff or production change.

## ADRs

[0001](../../adr/0001-stack-and-hosting.md), [0002](../../adr/0002-nflverse-load-and-refresh.md), [0003](../../adr/0003-rotoguru-dk-classic-salaries.md), [0004 (live Proposed; preserved)](../../adr/0004-dk-current-slate-csv.md), [0005 (Proposed)](../../adr/0005-private-salary-capture-and-archives.md), [0006 (Proposed)](../../adr/0006-slate-safe-salary-unification.md).
