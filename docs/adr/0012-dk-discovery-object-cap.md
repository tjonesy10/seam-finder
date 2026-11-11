# ADR 0012: Larger object cap for DK lobby discovery

## Status

Proposed (2026-11-11). The discovery cap was decided by the owner 2026-11-11 10:59 AM ET (relayed by Groko: "Raise the limit"). The storage plan was decided by the owner 2026-11-11 11:10 AM ET (relayed by Groko: "Stay on current plan for now. Remind me after the next data comes through and evaluate what our best options are."). The contract is accepted on owner merge.

The production migration of `salary_private.salary_artifacts` is approved. Cosmo approved it on 2026-11-11 at 11:10 AM ET, relayed by Groko: "Yes, approve the salary_artifacts migration for production." This docs change does not contain the revision and does not run it. Schedule activation and a live capture are not approved.

On acceptance, this ADR supersedes [ADR 0005](0005-private-salary-capture-and-archives.md) for the discovery object cap, the stored encoding of private artifacts, and the cumulative and database guard numbers in ADR 0005's limits bullet. ADR 0005 keeps a short amended-by note there. Its other decisions stand, including no automatic deletion. The 5 MiB decoded cap remains for every artifact kind except `lobby_discovery_json`.

## Context

F005 capture run [43049995926](https://github.com/tjonesy10/seam-finder/actions/runs/43049995926) failed closed. The public log was `storage_guard_object` and `rows=0`, then exit 1. Open PR #41, test-report section "2026-11-11 week-10 capture", records the triage: the reason is the 5 MiB per-object cap, the public log names no URL and no byte length, and the private observation was not read. The live body is unknown. The leading explanation is the discovery GET.

Reviewed for this proposal:

- ADR 0005 stores a body that fits in 5 MiB. A larger body stops at limit+1, keeps a truncated-prefix diagnostic, stores no full artifact, and publishes no snapshot. The reason code is `storage_guard_object`. ADR 0005 also forbids automatic deletion. Its limits bullet sets 64 MiB per invocation, 128 MiB cumulative private artifacts, and a 512 MiB database write guard.
- `loader/salary_private.py` sets `OBJECT_LIMIT` to 5,242,880. `store_artifact` rejects a longer body. The invocation raw-bytes guard is 64 MiB. `AUDIT_HEADROOM` is 256 KiB. After writes, the capture lock remeasures real relation and database size.
- `loader/dk_lobby.py` reads the discovery URL with `_read_capped`, which stops at 5 MiB. `_accepted` then raises `storage_guard_object` when the read is truncated. The same 5 MiB read is used for `draftgroups/v1`, the rules URL, and the salary CSV. Discovery and `draftgroups/v1` are both stored today as `artifact_kind=lobby_json`.
- `salary_private.salary_artifacts.body` is `bytea NOT NULL`. Check `ck_salary_artifacts_body` (migration `0004`) requires `octet_length(body) <= 5242880` for every artifact. Check `ck_salary_artifacts_kind` (migration `0005`) has no discovery-only kind. Unique `(source, sha256)` dedups stored bytes. There is no encoding column.
- Production workflows on `main` run `python -m loader.migrate`. A revision merged to `main` is applied on the next production migrate.
- Alembic head on this docs branch's base is `0008`. Forge's revision is `0009_discovery_gzip_at_rest`, which revises `0008`, in [PR #41](https://github.com/tjonesy10/seam-finder/pull/41) at `ee688b77`. This docs change does not add that file.

No week-10 snapshot exists. No getcontests body has been measured. This proposal does not invent one.

## Decision

### Discovery cap

Apply a larger object cap only to `GET https://www.draftkings.com/lobby/getcontests?sport=NFL`.

`DISCOVERY_OBJECT_LIMIT` is 32 MiB, 33,554,432 decoded bytes. Store the full decoded response. Stop reading at limit+1. A discovery body that reaches byte 33,554,433 fails closed with `storage_guard_object`, with ADR 0005's truncated-prefix diagnostic (`truncated=true`, hash and length of the retained prefix, `retained_artifact=false`), no salary snapshot, and zero salary rows.

`draftgroups/v1`, the lineups rules document, and the `getavailableplayerscsv` salary CSV stay at 5,242,880 decoded bytes. A larger body on those URLs still fails closed with `storage_guard_object`.

A discovery body of 5,242,880 decoded bytes or fewer is still stored in full and still follows today's success path.

The stored discovery row uses new `artifact_kind=lobby_discovery_json` and `media_type=application/json`. `draftgroups/v1` remains `lobby_json`. `body` stays `bytea NOT NULL`.

Record the discovery body's decoded length on the private observation (`salary_observations.metadata.discovery_body_bytes`). Add byte counts to the public log. The public log carries no body, no URL that contains a secret, and no response content.

### Retention

Keep every accepted response byte-exact. No eviction, no purge, and no separate discovery quota. When a guard is reached, block new writes only and fail closed with zero salary rows and no snapshot. Existing data is never touched.

### Encoding at rest

Stored bodies use gzip level 9 with `mtime=0`. That encoding is deterministic and in the Python 3.12 standard library. If gzip is not smaller, the body is stored as identity. Allowed encodings are `identity` and `gzip`. zstd is a reserved future option, rejected for now because it needs a new dependency or Python 3.14.

Decoded means the HTTP content-decoded bytes, before this application compression.

For every artifact, record `decoded_sha256`, `decoded_bytes`, `compressed_sha256`, and `compressed_bytes`. `sha256` stays equal to `decoded_sha256`, and `byte_count` stays equal to `decoded_bytes`. Those two existing columns are compatibility aliases. Dedup is on source plus decoded SHA-256, which is the existing unique `(source, sha256)` once `sha256` is the decoded hash.

The writer verifies the encoded hash and length, decompresses within the decoded limit, verifies the decoded hash and length, and reads back exactly the bytes it stored.

Legacy rows stay `identity`. Their new columns are backfilled from the existing `sha256` and `byte_count`. No body is rewritten.

Stored `.html.gz` archive companions remain `identity` with media type `application/gzip`. Their stored bytes stay the file as acquired. They are not uncompressed and compressed again.

PostgreSQL TOAST (`pglz`) is not relied on for any limit.

### Limits apply to decoded bytes

- `lobby_discovery_json`: decoded length up to 33,554,432.
- Every other kind: decoded length up to 5,242,880.

The check `ck_salary_artifacts_body` is rewritten to tie the stored body to those rules:

- `compressed_bytes = octet_length(body)`
- `identity` requires `compressed_bytes = decoded_bytes`
- `gzip` requires `compressed_bytes < decoded_bytes`
- `sha256 = decoded_sha256` and `byte_count = decoded_bytes`
- `body` is not null

### Guards

This amends the limits bullet in ADR 0005.

- Per invocation stays 64 MiB decoded. The four-request maximum is 32 + 5 + 5 + 5 = 47 MiB.
- Cumulative `salary_private` rises from 128 MiB to 512 MiB (536,870,912 bytes).
- The `pg_database_size` write guard rises from 512 MiB to 768 MiB (805,306,368 bytes).

The cumulative guard measures `pg_total_relation_size` across all `salary_private` tables, including indexes and TOAST. It is not the sum of artifact byte lengths. Preflight uses the encoded length plus a relational allowance. The post-write remeasure under the capture lock stays authoritative. The 256 KiB audit headroom stays.

Warn at 70% and 85% of either guard. A warning does not fail the attempt and does not delete anything. The public log may add `storage_warn=70` or `storage_warn=85` and no body. If both thresholds are crossed, report 85.

Crossing either guard blocks the new write, fails closed with the existing cumulative or database reason, leaves zero new salary rows and no new snapshot, and leaves existing rows in place.

### Capacity

The project stays on the Neon Free plan, 1 GiB per project.

Planning estimate, not a measurement: about 6.65 MiB gzip per capture at the full discovery cap with a 20% ratio. The rest of 2026 plus 2027 is 27 captures, about 470 MiB private and about 582 MiB total, which fits the guards above and the free plan.

It does not fit if bodies are incompressible: 9 captures at 47 MiB raw would be about 666 MiB private.

No getcontests body has been measured yet. After the first successful discovery capture, record the measured size and reforecast. Cosmo then evaluates options. His words, relayed by Groko on 2026-11-11 at 11:10 AM ET: "Stay on current plan for now. Remind me after the next data comes through and evaluate what our best options are."

A paid Launch plan is an alternative not chosen now: pay-as-you-go, no minimum, $0.35/GB-month storage and $0.106/CU-hour compute, per <https://neon.com/pricing> (updated 2026-11-04), with 8 GiB private and 12 GiB database guards for a five-season envelope.

## Reasoning

The owner chose to raise the discovery cap, keep every accepted byte, and stay on the current free plan until a real discovery body has been measured. Gzip level 9 with a fixed `mtime` is deterministic, needs no new dependency, and shrinks the planning case enough to fit. The decoded hash remains the identity of the response, so dedup and the exact-byte rule survive the wrapper. Guards fail closed by refusing the new write. They do not make room by deleting history.

## Rejected alternatives and why

- **(b) DraftGroups projection.** Not the owner's choice. It would drop the rest of the response and lose full-response provenance.
- **(c) A narrower endpoint.** None is verified, and one cannot be checked before the Sunday 15 November 2026 1:00 PM America/New_York lock.
- **Raise the cap for every fetch.** The CSV, rules, and `draftgroups/v1` documents do not need it.
- **Eviction or a separate discovery quota.** Rejected by the owner 2026-11-11: keep all data.
- **zstd.** Reserved for later. It needs a new dependency or Python 3.14.
- **Rely on TOAST.** `pglz` is not a limit the application can treat as its budget.
- **Paid Launch now.** Not chosen. The free plan remains the plan until Cosmo evaluates the measured body.

## Consequences

F005 R10–R14 and AT17–AT31 are the behavioral contract once this ADR is accepted. The revision itself is forge's file in PR #41, not in this docs change.

Production application is approved, as recorded in Status. The next production `python -m loader.migrate` after `0009_discovery_gzip_at_rest` is merged will apply it. Merging this docs change does not apply it.

ADR 0005's no-deletion rule remains. Schedule proof, F004, the public site, and the Wednesday cadence are unchanged. The free-tier constitution rule remains: Launch is not chosen.

## Migration

Revision `0009_discovery_gzip_at_rest` revises `0008`. Forge built it in [PR #41](https://github.com/tjonesy10/seam-finder/pull/41) at `ee688b77`. The Neon-branch rehearsal is in that PR's [TEST_REPORT](https://github.com/tjonesy10/seam-finder/blob/ee688b77/docs/features/F005-dk-lobby-capture/TEST_REPORT.md). This docs change does not copy that report and does not add the revision file.

On `salary_private.salary_artifacts` the upgrade:

- Adds five `NOT NULL` columns: `encoding`, `decoded_sha256`, `decoded_bytes`, `compressed_sha256`, and `compressed_bytes`. Legacy rows are backfilled as `identity` from the existing `sha256` and `byte_count`. No body is rewritten.
- Adds `ck_salary_artifacts_encoding`: `encoding IN ('identity', 'gzip')`.
- Replaces `ck_salary_artifacts_body`. It requires `byte_count = decoded_bytes`, `sha256 = decoded_sha256`, `compressed_bytes = octet_length(body)`, and both SHA-256 values as 64-character lowercase hex. `identity` requires `compressed_bytes = decoded_bytes` and `compressed_sha256 = decoded_sha256`. `gzip` requires `compressed_bytes < decoded_bytes`. `decoded_bytes` is capped at 33,554,432 for `lobby_discovery_json` and at 5,242,880 for every other kind.
- Adds `lobby_discovery_json` to `ck_salary_artifacts_kind`.
- Adds a `BEFORE INSERT` trigger, `salary_artifacts_identity_encoding`, that fills `identity` when `encoding` is null so old writers keep working. That trigger is a compatibility shim. New writers set every field explicitly.
- Changes no grants.

The downgrade refuses when any `gzip` row, any `lobby_discovery_json` row, or any decoded body over 5,242,880 bytes exists. It deletes nothing. Otherwise it restores the `0004` and `0005` checks exactly.

Production application is approved, as recorded in Status. This docs change does not run the migrate.
