# ADR 0012: Larger object cap for DK lobby discovery

## Status

Proposed (2026-11-11). Decided by the owner 2026-11-11 10:59 AM ET (relayed by Groko: "Raise the limit"). Accepted on owner merge. This is a docs proposal. It does not approve a build, a migration, a capture, schedule activation, or a production change.

On acceptance, this ADR supersedes [ADR 0005](0005-private-salary-capture-and-archives.md) **only** for the per-object cap as applied to the allowlisted discovery URL `https://www.draftkings.com/lobby/getcontests?sport=NFL`. The cap for that URL becomes 32 MiB of decoded bytes, and a body within the cap is stored in full. Everything else in ADR 0005 stands, including the 5 MiB cap on every other fetch and the rule that nothing is automatically deleted. ADR 0005 is not edited.

## Context

F005 capture run [43049995926](https://github.com/tjonesy10/seam-finder/actions/runs/43049995926) failed closed. The public log was `storage_guard_object` and `rows=0`, then exit 1. Open PR #41, test-report section "2026-11-11 week-10 capture", records the triage: the reason is the 5 MiB per-object cap, the public log names no URL and no byte length, and the private observation was not read. The live body is unknown. The leading explanation is the discovery GET.

Reviewed for this proposal:

- ADR 0005 stores a body that fits in 5 MiB. A larger body stops at limit+1, keeps a truncated-prefix diagnostic, stores no full artifact, and publishes no snapshot. The reason code is `storage_guard_object`. ADR 0005 also forbids automatic deletion.
- `loader/salary_private.py` sets `OBJECT_LIMIT` to 5,242,880. `store_artifact` rejects a longer body. The invocation raw-bytes guard is 64 MiB.
- `loader/dk_lobby.py` reads the discovery URL with `_read_capped`, which stops at 5 MiB. `_accepted` then raises `storage_guard_object` when the read is truncated. The same 5 MiB read is used for `draftgroups/v1`, the rules URL, and the salary CSV. Discovery and `draftgroups/v1` are both stored today as `artifact_kind=lobby_json`.
- `salary_private.salary_artifacts.body` is `bytea NOT NULL`. Check `ck_salary_artifacts_body` requires `octet_length(body) <= 5242880` for every artifact. Check `ck_salary_artifacts_kind` (migration `0005`) has no discovery-only kind.

No week-10 snapshot exists. This proposal does not invent one.

## Decision

Apply a larger object cap only to `https://www.draftkings.com/lobby/getcontests?sport=NFL`.

`DISCOVERY_OBJECT_LIMIT` is 32 MiB, 33,554,432 decoded bytes. Store the full decoded body as a normal private artifact, exactly as ADR 0005 stores a body that fits its cap. Stop reading at limit+1. A discovery body that reaches byte 33,554,433 fails closed with `storage_guard_object`, with ADR 0005's truncated-prefix diagnostic (`truncated=true`, hash and length of the retained prefix, `retained_artifact=false`), no salary snapshot, and zero salary rows.

`draftgroups/v1`, the lineups rules document, and the `getavailableplayerscsv` salary CSV stay at `OBJECT_LIMIT` 5,242,880 decoded bytes. A larger body on those URLs still fails closed with `storage_guard_object`.

The 64 MiB per-invocation raw-bytes guard is unchanged. One discovery body at 32 MiB plus those three other fetches at 5 MiB each is 47 MiB, inside that guard.

Record the full discovery body's byte length on the private observation (`salary_observations.metadata.discovery_body_bytes`). Add byte counts to the public log. The public log carries no body, no URL that contains a secret, and no response content.

A discovery body of 5,242,880 bytes or fewer is still stored in full and still follows today's success path. It does not fail the object guard.

The stored discovery row uses `artifact_kind=lobby_discovery` and `media_type=application/json` so the database check can tell it from a `draftgroups/v1` row, which remains `lobby_json` and remains at 5 MiB. `body` stays `bytea NOT NULL`. `sha256` and `byte_count` are the full stored bytes. Existing content-hash dedupe stays.

Nothing is deleted. Salary CSVs, draft-group and rules bodies, snapshots, salary rows, and archive artifacts all stay.

## Storage at rest and budget: [NEEDS CLARIFICATION: compression encoding and new cumulative/DB guard values pending owner decision on Neon plan]

Exact values are not in this ADR. Cosmo will send them. Until then this ADR does not choose a compression encoding and does not set a new cumulative private-artifact guard or a new database write guard.

## Reasoning

The owner chose to raise the discovery cap and keep the full response. Salaries still come from the CSV, which stays on the 5 MiB cap. The discovery document is the full allowlisted response, stored like any other in-cap artifact. The read still stops, so an unbounded body cannot be pulled into memory or into Neon.

## Rejected alternatives and why

- **(b) DraftGroups projection.** Not the owner's choice. It would drop the rest of the response and lose full-response provenance.
- **(c) A narrower endpoint.** None is verified, and one cannot be checked before the Sunday 15 November 2026 1:00 PM America/New_York lock.
- **Raise the cap for every fetch.** The CSV, rules, and `draftgroups/v1` documents do not need it, and a wider cap on those objects widens the storage risk.
- **Eviction.** Rejected by the owner 2026-11-11: keep all data.

## Consequences

F005 R10 and AT17–AT20 are the behavioral contract once this ADR is accepted. Forge starts after that acceptance, in a separate code change. This proposal does not hand the work to forge by itself.

**A migration is required** before a discovery body larger than 5,242,880 bytes can be stored. `ck_salary_artifacts_body` caps every artifact at that size, and `ck_salary_artifacts_kind` does not list `lobby_discovery`. Forge widens the kind check and allows `lobby_discovery` bodies up to 33,554,432 bytes, leaving every other kind at 5,242,880. `body` stays `bytea NOT NULL`. No further columns. Production application needs Cosmo's separate approval. This docs change does not add a migration file.

ADR 0005's no-deletion rule remains. Schedule proof, F004, grants, the public site, and the Wednesday cadence are unchanged.

## Migration

See Consequences. The cap needs a check-constraint migration. `body` stays `bytea NOT NULL`. Production migration needs Cosmo's separate approval.
