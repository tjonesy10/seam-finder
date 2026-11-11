# ADR 0013: Refresh before private lobby capture

## Title

Run the nflverse refresh inside the capture execution before verifying schedule proof and fetching salaries.

## Status

Proposed (2026-11-11 America/New_York). Planning request relayed by dr eggbot as approved by Cosmo; this is not independent approval of this architecture or production rollout. Owner approval is required before forge handoff. No code, workflow, migration, dispatch or production change is made by these docs.

## Context

Independent GitHub cron events are not an ordering mechanism. The [evidence snapshot](../features/F014-refresh-before-capture/EVIDENCE.md) inventories all five workflows and cites source lines. The daily refresh is 11:00 UTC (`refresh.yml:3–15`); observed run creation was 5h40m–10h10m late on November 6–10. The capture is Wednesday 10:07 America/New_York (`dk-lobby-capture.yml:7–11`). Its body invokes capture alone (`:70–110`). Two cron offsets cannot guarantee refresh-before-capture.

Refresh loads teams, players, games and stats (`loader/run.py:676–718`). Games ingestion attempts an ADR 0007 raw-source receipt in the publication transaction (`:554–576`), but receipt production is optional for public loading (`loader/schedule_proof.py:766–808,835–858`). Capture needs schedule coverage, exact Sunday identities/kickoffs and a verified authority/raw/receipt/current-PG chain, not refreshed stats. Today's freshness test admits a matching receipt retrieved within 24 hours, with five minutes skew (`loader/schedule_proof.py:245–252,424–475`); yesterday's evidence can pass even if today's refresh has not run. If it expires or disagrees, capture already fails closed. A success flag alone cannot prove completeness or same-execution ordering.

The reported external dispatch received 403. Both workflows have workflow_dispatch; caller authorization, likely Actions:write, is unresolved, not absence of the trigger. See evidence for REST requirements; do not equate the target contents:read permission with the caller's grant. Fixing that 403 is out of scope: option (b) never dispatches another workflow.

Main has ADRs through 0011; open PR #42 reserves [ADR 0012](https://github.com/tjonesy10/seam-finder/blob/2a89f83fb3cc15eeb6c7becc768190c576199ebe/docs/adr/0012-dk-discovery-object-cap.md) and F005 R10–R14/AT17–AT31. F013 is the highest feature on both trees. This proposal uses the next free numbers. Main's constitution still says 10:00; this patch proposes the narrow 10:07 alignment with live #41 and #42, effective only on owner merge. Accepted ADR 0005 remains historical, not silently rewritten.

## Decision

Choose **(b): one capture execution runs the existing full nflverse refresh first**, using the same checked-out revision and existing loader identity/configuration. Keep the independent daily refresh for public data. Do not dispatch a second workflow, poll its status, or add actions:write to the capture token. No separate scheduler or service.

Use **(c) as a complementary precondition**, not a replacement: the immediately preceding refresh must succeed, and active-season capture must consume a valid receipt bound to that execution's successful games load for the relevant season. Existing independent authority and current full-season equality checks remain mandatory. No fallback to an older otherwise-fresh receipt when this execution fails or omits proof. Full-refresh failure, including an unrelated dataset failure, blocks this capture conservatively; narrowing to games-only can be considered later, not hidden in this pass.

Serialize the entire refresh→proof→capture sequence against standalone normal refresh and direct capture with one new database session coordination lock, distinct from CAPTURE_LOCK. Acquire coordination before migration and before private storage/capture locks; nested operations share ownership without reacquiring on another connection. Release on completion or connection loss; stop work on ownership loss. Preserve the existing capture workflow concurrency group, cancel-in-progress:false; add standalone-refresh serialization without putting both workflows into one pending-slot group. Database coordination protects CLI invocations too. The 120-second coordination wait and 30-minute pipeline deadline are proposed engineering limits; DK's existing 180-second HTTP budget remains unchanged.

Keep Wednesday `7 10 * * 3`, America/New_York, REG-only automatic capture, exact upcoming Sunday 1:00–4:30 PM ET game set, existing manual alternate-slate rules, gates and F004 separation. No new Sunday capture/refresh cron. The existing ADR 0002 daily public refresh, including Sundays, is unchanged. This removes cross-cron ordering dependency, **not** GitHub's delay/drop risk for the capture's own trigger; no exact-time guarantee is claimed.

Preserve ADR 0005/0007 and ADR 0012 protections: gzip/identity exact decoded content; discovery-only 32 MiB decoded cap, other kinds 5 MiB, invocation 64 MiB decoded, 512 MiB private relations and 768 MiB DB write guards, actual free allowance checks, no deletion, no web grants or public salary exposure. PR #42's contract must be reconciled/merged before implementation handoff. No new schema, grant, Render setting, Neon plan or Neon infrastructure change is needed. F014's internal provenance fits existing private JSON metadata.

## Reasoning

Earlier refresh times are a slack heuristic against an unbounded delay, not causality. In-process ordering uses the loader and proof producer already present and avoids the external dispatch permission failure entirely. Binding evidence to the actual refresh is stronger than checking a recent success or letting an older receipt mask missing current proof. One lock prevents interleaved refreshes from replacing the verified schedule during capture, while existing transaction locks retain their budget/dedupe role. Full refresh reuses current behavior at the cost of one extra Wednesday refresh and conservative failure coupling.

## Rejected alternatives and why

- **(a) Move refresh earlier and hope.** Even ten hours of slack has no guarantee against delay/drop and does not fix the manual caller's permission. No cron time is changed here.
- **(c) Freshness-only gate.** Necessary but already largely present. It can allow yesterday's receipt and cannot make a late refresh happen. Keep proof and add same-execution binding instead.
- **workflow_dispatch refresh plus wait / workflow_run chaining.** Adds API authorization, cross-run correlation and independent scheduling/queue failure paths. No need when the same runner can invoke the loader directly.
- **External scheduler, Render cron or paid worker.** New infrastructure/cost and still needs runner availability. Outside this minimal ordering fix.
- **Hold CAPTURE_LOCK outside the refresh on another connection.** Receipt writing locks the same key (`loader/schedule_proof.py:728–729`); this can deadlock. Use a separate coordination lock and one acquisition order.
- **Treat refresh exit zero as proof, auto-approve authority, widen freshness, or capture stale on failure.** Weakens ADR 0007 and can select the wrong game set.
- **Skip audits on duplicate content or promise exactly-once HTTP.** F005 records each real attempt; crash/retry cannot guarantee exactly-once external reads. Reuse immutable artifacts/snapshots, serialize execution and retain honest attempts.

## Consequences

[F014](../features/F014-refresh-before-capture/SPEC.md) defines R1–R12 and AT1–AT18 for one later engineering pass. No production action or forge handoff until Cosmo approves. Documentation authoring for this decision is complete; READY follows owner approval.

The pipeline can fail because refresh, proof, locks, storage or DK fails; previous salary snapshots stay intact. Partial public refresh commits keep ADR 0002's per-dataset rollback behavior; no fake all-dataset atomicity is introduced. New internal correlation metadata requires no migration. Existing automatic migration paths remain gated and cannot apply an unapproved future revision just because F014 is merged. Every CI check must finish on the final head. Any implementation divergence needing Render/Neon changes must list exact changes before merge and obtain applicable approval; check the live site after any deploy. Initial approved production validation records ordering, proof binding and existing post-capture storage measurements without exposing salaries.
