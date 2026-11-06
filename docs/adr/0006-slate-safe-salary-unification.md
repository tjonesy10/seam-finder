# ADR 0006: Slate-safe, snapshot-coherent private salary unification

## Status

Proposed (2026-11-06). Depends on ADR 0005 and the proposed constitution amendment. No source tables, production schema, or optimizer are changed by this planning package.

## Context

Season/week/player is not slate identity. DKNFL includes small holiday/alternate Classic slates and mislabeled paths; DFF IDs are vendor-specific and files are projection-player subsets. RotoGuru F003 is historical weekly data without verified exact slate fidelity. F004 overwrites `(season, week, dk_id)` and does not retain historical snapshots/raw bytes. A naive coalesce/union with per-player precedence could fabricate a player pool, join unrelated players, or silently erase disagreement.

## Decision

Build F008 as one private SQL view `salary_private.dk_salary_unified` over explicit versioned mappings and atomically published selection batches. A verified slate requires exact sorted game identities/kickoffs plus verified Classic roster/rules identity; select one coherent anchor source snapshot for its player pool, and attach only verified-equivalent entity+slate alternatives for comparison, never fill pool gaps from another snapshot/slate.

- Preserve original source rows and artifacts unchanged. Mapping, corrections, and source/slate equivalence evidence live in separate append-only interpretation records with parser/mapping version and evidence hashes.
- DK `draft_group_id` remains a native identity, not a player ID or a globally sufficient game-set fingerprint. A changed game/kickoff/rules set creates a new slate revision; two groups with identical games are **not** merged without verified compatible rules and explicit equivalence evidence.
- For skill players require unambiguous `gsis_id` plus team/game context; for DST use season-correct `team_abbr`. Scope all native IDs to publisher and snapshot; DFF `player_id` never becomes `dk_id`. Ambiguity remains visible and not optimizer-ready.
- Choose latest successfully observed snapshot within a source at/before a selection cutoff deterministically by observation time, SHA, snapshot ID, using only known chronology. Archive retrieval time is not original publication time. Unknown chronology with competing differing artifacts is flagged, not resolved by a path name or fake timestamp; allow an explicit evidence-backed snapshot choice.
- After entity/slate equivalence verification, proposed anchor priority: official DK family (F004 owner export before F005 lobby **only at equal effective time and verified fidelity**), then DKNFL, then DFF. Within official family use the latest verified effective time first, not an older official export over a newer live capture. Publish one complete anchor snapshot's pool; lower-source rows remain alternatives, not additive fallback players. Record selected snapshot and observation IDs. DFF subset anchors remain `optimizer_ready=false` even when all present rows map.
- Any unresolved anchor member, duplicate/conflicting entity, missing rules/game evidence, inferred subset, unverified completeness, or differing salary/eligibility among comparable alternatives sets quality flags; unresolved identity/slate blocks that record, and an incomplete anchor blocks the **whole pool**. Salary/eligibility disagreements retain all values and provenance and conservatively make the affected pool not ready pending an explicit evidence-backed resolution. A resolution selects a value with reason/version without modifying source rows.
- F003 remains `legacy_unknown` slate with its weekly key and attribution, not a fallback for known slates. F004 adapters copy only the **current** coherent source-hash cohort and available Game Info/roster evidence; label `adapter_current`, `raw_retained=false`, no fabricated past snapshots. Mixed hashes, incomplete game/rules evidence, or unverified complete pool make it not ready. Restaging the original export/evidence is required to verify it, not inferred from `(season, week)`.
- The same view exposes selected, alternative, unresolved, legacy, and superseded candidates with flags. Consumers must filter one `selection_id`, `is_selected=true`, and `optimizer_ready=true` and verify `pool_ready=true`; no unqualified season/week query is an optimizer contract.

## Reasoning

An anchor snapshot prevents a collection of plausible prices from masquerading as an actual slate. Explicit evidence and flags are safer than a universal match threshold. One SQL view plus small durable mapping/selection tables is enough; no optimizer engine, API, queue, or materialized-view refresh service is needed. Failures leave the previously published selection intact.

## Rejected alternatives and why

- Coalesce by `(season, week, player)` and priority: cross-slate contamination and pooled revisions.
- Merge by normalized name/team alone: collision-prone, especially vendor IDs and DST; retain candidates but require verified entity mapping.
- Take the newest row per player: mixes snapshots and invents a pool.
- Fill missing main-slate players from holiday, RotoGuru, or DFF files: no verified equivalent pool; corrupts backtests.
- Treat game-set equality alone as equivalence: different roster/rules or draft groups can share games.
- Delete lower-priority sources, silently resolve disagreements, or relabel all history RotoGuru: loses evidence and attribution.
- Materialized table replacing raw sources: introduces destructive state and refresh complexity without need.

## Consequences

Coverage will be lower than the downloaded row count: honest unresolved/legacy/subset flags are expected, not loader failures. F008 must report mapping denominators per source/snapshot, no invented 95%/98% target inherited from F003/F004. First implementation has a local rebuild CLI and view, not production optimizer integration. Public site remains unchanged, including existing nflverse/RotoGuru attribution. Subsequent use of DFF projections or actual scores requires separate scope; `ppg_proj` and `AvgPointsPerGame` are not realized DK points.
