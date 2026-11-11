# F005 test report

Date: 2026-11-06. Scope: migration `0004` (revises `0003`), `loader/salary_private.py`, `loader/dk_lobby.py`, `loader/grants.py` allowlist, and `.github/workflows/dk-lobby-capture.yml`. F006/F007/F008 tables, view, and CLIs are not in this change. No live DraftKings call, no production migration, and no schedule activation.

Synthetic CSV and JSON only. They are built in `tests/test_dk_lobby.py` and labeled synthetic. No salary archive is committed.

## Results

| AT | Result | Evidence |
|---|---|---|
| AT1 | PASS | `tests/test_dk_lobby.py::test_at1_exact_bytes_and_f004_untouched`. BOM CSV bytes and sha256 read back from `salary_private.salary_artifacts`. Ledger `raw_fields` keeps ordered pairs, including `Status`. Four `dk_lobby_salaries` rows. `dk_classic_slate` stays the seeded `f004-keep` row. `dk_classic_salaries` stays empty. |
| AT2 | PASS | `test_at2_sunday_set_excludes_saturday_and_explicit_is_not_main` stores only the Sunday pair as `sunday_main`. `test_sunday_hydrate_rejects_a_different_group_id` rejects a hydrated document whose `DraftGroupId` differs even when the games match. Explicit mode is covered by `test_hydrate_is_rechecked_and_explicit_id_must_match`. |
| AT3 | PASS | `test_at3_fail_closed_reasons` and `test_at3_wrong_week_and_holiday_do_not_substitute`. Reasons asserted with no new snapshot: `ambiguous_slate`, `slate_unavailable`, `inexact_game_set`, `missing_rules`, `captain_slot`, `one_game`, `duplicate_dk_id`, `mismatched_metadata`, `wrong_season_week`. The Dec 23 holiday clock makes no HTTP call. |
| AT4 | PASS | `test_at4_schedule_text_and_disabled_gate` and `test_nov11_wednesday_slot_stays_on_the_timezone_cron`. One cron, `7 10 * * 3`, with `timezone: 'America/New_York'`. 2026-11-11 10:07 America/New_York is 15:07 UTC. The file does not contain `0 10 * * 3`, `0 14 * * 3`, or `0 15 * * 3`. `next_wednesday_10_et` still checks hour 10 for a January and a July Wednesday. `capture_schedule_enabled('TRUE')` is false. The workflow calls that predicate before `python -m loader.migrate`. The test does not dispatch. |
| AT5 | PASS | Omission cases stay ordinary passes. `test_later_kickoff_receipt_wins_in_either_order` has two fresh receipts and Postgres matching the later kickoff; `choose_receipt` returns that receipt for both body orders and the capture exits 0. `test_multiseason_parquet_receipt_captures` selects the emitted parquet receipt (`PAR1`), not the seeded JSON receipt. `test_stale_and_wide_damage_keep_the_whole_observed_set` reads a private `schedule_verification_v1` artifact: the stale failure keeps all 9 observed ids and the receipt hash, and the 25-row damage keeps every observed id while the metadata diff stays at most 20. Public notes do not contain game ids. `test_capacity_guard_rolls_back_optional_evidence` forces the storage ceiling during the evidence insert: no verification artifact and no snapshot are committed, and the observation is still `failed`. `test_evidence_sql_error_leaves_the_outer_transaction_usable` runs `SELECT 1` in the same transaction after the optional write fails. The fixture reviewer is `synthetic-operator`. That is not a real season certification. |
| AT6 | PASS | `test_at6_repeat_content_and_identity_revision`. A, A, B, A produce 4 observations and 2 snapshots. The first snapshot's salary `loaded_at` values stay put. Reordered classic roster evidence adds a third snapshot and does not add a third CSV artifact. |
| AT7 | PASS | `test_at7_failures_keep_the_previous_snapshot`. After a good snapshot, a bad header, one `nope` salary, and a real check-constraint failure inside the publish transaction leave that snapshot's rows unchanged. Ledger keeps the `nope` token and `invalid_salary`. Reasons: `parse_failure`, `invalid_salary`, `constraint_failure`. Snapshot count stays 1. |
| AT8 | PASS | `test_at8_reconcile_does_not_double_ingest_or_promote_unrelated`. Crash after the normalized commit reconciles that `load_runs` row to `succeeded` without a second snapshot. A running `teams` load stays `running`. An unrelated running lobby observation becomes `failed`/`interrupted` with null `finished_at` and null `duration_ms`. |
| AT9 | PASS | `test_at9_denial_does_not_retry` and `test_challenge_on_5xx_is_not_retried` each make one call. `test_login_redirect_keeps_the_body` stores the redirect body `synthetic-login-body` in `salary_artifacts`. |
| AT10 | PASS | Before the iterator mapping, `BudgetHTTPTransport` plus a representative `NetworkBackend` failed as raw httpcore: `test_budget_transport_body_timeout_retries_then_succeeds` raised `httpcore.ReadTimeout: body` from the body read, and `test_budget_transport_body_exhaustion_is_budget_exhausted` raised `httpcore.ReadTimeout: budget`. After `_IterableStream` uses the same httpcore-to-httpx mapping as header setup, the body `ReadTimeout` is retried and the second connection returns `{}` (`connections == 2`). A deadline already spent on the body read is `CaptureFailure` reason `http_budget_exhausted`. The backend is not `MockTransport`. `test_tcp_then_tls_share_one_deadline`, the header-delay test, and the stalled-body test still pass. No DraftKings host is contacted. |
| AT11 | PASS | `test_at11_grants_hide_private_and_f004` on Postgres 16. Web role `seam_web_f005` can SELECT `teams`, `players`, `games`, `player_week_stats`, `load_runs`, and `dk_classic_salaries`. It cannot SELECT `dk_classic_slate`, `salary_private.salary_artifacts`, or a test-only `dk_salary_unified` view. Optimizer role `seam_opt_f005` can SELECT that view only after it exists, cannot SELECT `salary_artifacts`, and cannot INSERT. It is not a member of the web role. Granting slate SELECT and running `apply_readonly_grant` again removes that SELECT. `tests/test_schema.py::test_readonly_role_is_select_only` and `tests/test_readonly.py::test_at18_read_only_role` also pass. |
| AT12 | PASS | The publication guard is accepted. `assert_actual_ceiling` reads `pg_database_size` and `pg_total_relation_size` after the write and rolls back before commit. A rollback does not reclaim the physical file space Postgres already allocated, and the 256 KiB audit reserve is not guaranteed capacity. No vacuum or purge was added. `test_concurrent_actual_growth_rejects_one_writer` and `test_capture_over_the_ceiling_records_failure` passed. |
| AT13 | PASS | `test_at13_public_output_has_no_raw_salary` and `test_unexpected_database_error_stays_a_reason_code`. Public output stays reason codes. A raised `RuntimeError` containing `4242` prints `capture_failed` only. `GET /api/dk-lobby` and `GET /dk-lobby.csv` return 404. gitleaks 8.30.1 is part of the suite and passed. |
| AT14 | PASS | `test_at14_f004_scheduled_trigger_remains` plus the existing F003/F004 modules in the full pytest run. `loader.dk_slate` still accepts trigger `scheduled` and stores that literal. `dk-classic-slate.yml` and `loader/dk_slate.py` do not contain `draftkings.com`. A missing staged CSV exits 1. The full suite, including F003/F004 replacement, Classic rejection, and missing-file tests, passed. |
| AT15 | PASS | `test_at15_and_at16_timing`. Success, repeat, off-season skip, HTTP 403, and invalid salary each store `started_at`, `finished_at`, and `duration_ms >= 0`. The repeat links the same `snapshot_id`. Skip and failures leave `snapshot_id` null. Public notes do not contain the canary name. |
| AT16 | PASS | Same test, plus `test_at16_unreachable_database_claims_nothing`. A wall-clock jump of 1 hour stores `duration_ms=50` while `finished_at - started_at` is 3600000 ms. `failpoint=before_terminal` leaves `finished_at` and `duration_ms` null; reconcile sets `failed`/`interrupted` and still leaves both null. `DATABASE_URL=postgresql://seam@127.0.0.1:1/none` exits 1 with stderr exactly `database_unreachable` and adds no `load_runs` row. |

## Commands

Local Postgres 16.15, database `seam_test`, role `ubuntu`. `DATABASE_URL=postgresql:///seam_test`. No production credentials.

```text
$ python3 -m ruff check loader web tests migrations
All checks passed!

$ python3 -m pytest -q --tb=line
153 passed, 2 skipped, 1 warning in 11.10s

$ gitleaks version
8.30.1

$ gitleaks detect --source . --redact --log-opts=--all --no-banner
10:42PM INF 39 commits scanned.
10:42PM INF scanned ~604117 bytes (604.12 KB) in 155ms
10:42PM INF no leaks found
```

The two skips are `tests/test_load.py` and `tests/test_dk_classic.py` network tests, gated on `RUN_NETWORK_TESTS=1`. They were not run. They do not call DraftKings.

`bash -n` on the capture step is inside `test_at4_schedule_text_and_disabled_gate`.

## Migration

Alembic head is `0004`, down revision `0003`. `0004` creates schema `salary_private` and tables `salary_artifacts`, `salary_observations`, `salary_snapshots`, `salary_source_rows`, and `dk_lobby_salaries`. It does not create `dff_salaries`, `dknfl_salaries`, interpretations, selection tables, or `dk_salary_unified`.

## Disabled gate

`.github/workflows/dk-lobby-capture.yml` contains the approved cron and timezone. Its only job is skipped unless the repository variable `DK_LOBBY_CAPTURE_ENABLED` is exactly `true`. That variable is not set in the repo. This run did not dispatch the workflow. GitHub's own scheduler was not executed here.

## Privacy and grants

Web SELECT is an allowlist: `teams`, `players`, `games`, `player_week_stats`, `load_runs`, `dk_classic_salaries`. `public.dk_classic_slate` is revoked from the web role and from `PUBLIC` on each grant pass. `salary_private` has no web or `PUBLIC` usage. Optimizer SELECT is applied only to `salary_private.dk_salary_unified` when that view exists and `OPTIMIZER_ROLE` is set. The workflow does not set `OPTIMIZER_ROLE`. No production optimizer grant was made.

## Offline real contract

`parse_draftables` reads `draftables` and `competitions`. Slot rows stay out of `dk_lobby_salaries`. CSV `ID` is `draftableId`. The same `playerId` may have a second slot row. `reproduce.sh` was not executed.

```text
draftables_slots 1077
draftables_players 586
competitions 11
csv_rows 586
csv_file_reasons []
game_set_equal True
reconcile ok
showdown_rows 5
showdown_file_reasons ['one_game']
showdown_row_reasons ['captain_slot']
```

`game_set_equal` compares competition `awayTeam`/`homeTeam`/`startTime` with CSV Game Info. `reconcile ok` means every CSV id, salary, position, team, and display name matches a draftable, and the CSV row count is the player count rather than 1077. That check is an offline mapping of files already on disk. It is not a live fetch and not a hosted schedule run. The Showdown head is one game and its rows include `captain_slot`, so it does not become a usable snapshot.

Follow-up local run after the parser change was 154 passed. After the review fixes:

```text
$ python3 -m ruff check loader web tests migrations
All checks passed!

$ python3 -m pytest -q --tb=line
192 passed, 2 skipped, 1 warning in 23.59s

$ gitleaks detect --source . --redact --log-opts=--all --no-banner
11:05PM INF no leaks found
```

The new test is `tests/test_dk_lobby.py::test_draftables_contract_uses_csv_players_not_slot_rows`. Its fixture has three synthetic slot rows and two salary rows, using the real field names.

Migration head is still `0005`. No external request. No `xfail` is collected. The two new tests close their clients and keep their backends local. Reverse order, then `test_login_redirect_keeps_the_body` and `test_tcp_then_tls_share_one_deadline`, passed.

Red, before the iterator mapping. This is not a result of the fixed head:

```text
$ DATABASE_URL=postgresql:///seam_test python3 -m pytest -q --tb=line tests/test_dk_lobby.py::test_budget_transport_body_timeout_retries_then_succeeds tests/test_dk_lobby.py::test_budget_transport_body_exhaustion_is_budget_exhausted
FF
E   httpcore.ReadTimeout: body
E   httpcore.ReadTimeout: budget
2 failed in 0.59s
```

Green, after the mapping, rerun on `7275915590ecd822b1d5e61c0e2aa0cae1bec983`:

```text
$ DATABASE_URL=postgresql:///seam_test python3 -m pytest -v --tb=short tests/test_dk_lobby.py::test_budget_transport_body_timeout_retries_then_succeeds tests/test_dk_lobby.py::test_budget_transport_body_exhaustion_is_budget_exhausted
tests/test_dk_lobby.py::test_budget_transport_body_timeout_retries_then_succeeds PASSED [ 50%]
tests/test_dk_lobby.py::test_budget_transport_body_exhaustion_is_budget_exhausted PASSED [100%]
============================== 2 passed in 0.43s ===============================
```

Full suite on that same code, plus ruff and gitleaks:

```text
$ python3 -m ruff check loader web tests migrations
All checks passed!

$ DATABASE_URL=postgresql:///seam_test python3 -m pytest -q --tb=line
194 passed, 2 skipped, 1 warning in 22.36s

$ gitleaks detect --source . --redact --log-opts=--all --no-banner
2:17AM INF no leaks found
```

## What this run did not verify

| Item | Result | Reason |
|---|---|---|
| Draftables JSON contract vs Classic CSV | PASS | Offline read of the uploaded draftables document and matching CSV. No network. Output below. The private files were not committed. |
| GitHub's hosted evaluation of the skipped job | UNKNOWN | AT4 forbids a live dispatch. The file gate and the local predicate are tested. |
| Uncle Bob mutator | UNKNOWN | `mutator` is not on `PATH`. `../crapper` is not present. Go is installed. The mutator tool was not installed. This is not a pass. |
| Pull request CI | PASS | Both checks on `7275915590ecd822b1d5e61c0e2aa0cae1bec983` succeeded: [run 42328553690](https://github.com/tjonesy10/seam-finder/actions/runs/42328553690) (`pull_request`) and [run 42328549429](https://github.com/tjonesy10/seam-finder/actions/runs/42328549429) (`push`). `mergeable` is `MERGEABLE` and `mergeStateStatus` is `CLEAN`. This does not claim the independent gate is cleared. |

## 2026-11-11 week-10 capture and Wednesday schedule

Date: 2026-11-11. Scope: the failed manual capture in Actions run [43049995926](https://github.com/tjonesy10/seam-finder/actions/runs/43049995926) and the missing Wednesday schedule run. No live DraftKings request, no production database read, no workflow dispatch, and no change to `OBJECT_LIMIT` or the cron.

### Symptom 1: `storage_guard_object`

`storage_guard_object` is the per-object cap in `loader/salary_private.py`: `OBJECT_LIMIT = 5 * 1024 * 1024` and `GuardBlock.OBJECT`. ADR 0005 and the data dictionary set that cap at 5 MiB per stored object, including a rejected body. An oversize HTTP body stops at limit+1, keeps a truncated prefix diagnostic, and does not publish a snapshot.

In `loader/dk_lobby.py`, `_read_capped` returns truncated once the decoded body passes 5 MiB. `_accepted` then raises `storage_guard_object` unless the body is already an HTML challenge (`http_challenge` is checked first). That happens before `parse_lobby`, before the salary CSV, and before any `dk_lobby_salaries` row. `store_artifact` repeats the same length check for a body that arrives whole. Sunday selection's first GET is `https://www.draftkings.com/lobby/getcontests?sport=NFL`. `parse_lobby` reads only `DraftGroups`.

Run 43049995926 was a `workflow_dispatch` of `main` at `1f6047647bbe896794a113c51778ae2b0cd1b3fd`. Checkout, Install, the gate (`DK_LOBBY_CAPTURE_ENABLED` exactly `true`), and Migrate succeeded. The Capture step's environment was `EVENT_NAME=workflow_dispatch`, `SEASON=2026`, `WEEK=10`, `SELECTION=sunday-afternoon`, empty `DRAFT_GROUP_ID`. The step then printed:

```text
storage_guard_object
dk_lobby_salaries season=2026 week=10 status=failed reason=storage_guard_object rows=0
```

and exited 1. Those two lines are `_report`: the status line on stdout, then the reason on stderr. The process window in the log is about 15:36:30.921Z to 15:36:34.022Z. A schedule-evidence failure would have been `schedule_evidence_missing` with no DK call. This reason means one allowlisted response decoded to more than 5,242,880 bytes and was not classified as a challenge.

The live payload shape is **UNKNOWN**. The public log has no URL, content-type, content-length, or byte count. The private observation would have `requests`, `prefix_bytes`, `prefix_sha256`, and `truncated`, and it was not read, because that row is in the production database. No live lobby fetch was made. What is known without that body: the reviewed experiment CSV is 59,802 bytes, so it is not this failure; an HTML challenge would have been `http_challenge`; salary-row validation never ran (`rows=0`). Which of the four allowlisted URLs was the large one, and whether a `Contests` array pushed `getcontests` over the cap, is not in the log.

The cap is the specified fail-closed behavior, not a parser bug that can be fixed from this evidence. Raising `OBJECT_LIMIT`, or reading past 5 MiB to store only `DraftGroups`, would change ADR 0005. That is a product question, recorded as BLOCKED on `HANDOFF.md`. No loader behavior changed.

### Symptom 2: no scheduled run on 2026-11-11

GitHub Actions does honour `timezone` under `on.schedule`. The workflow syntax page says schedules default to UTC and that an IANA `timezone` makes the cron local, including the `America/New_York` example and the spring-forward note. The same text is on the schedule-event page. The changelog entry is [GitHub Actions: Late March 2026 updates](https://github.blog/changelog/2026-03-19-github-actions-late-march-2026-updates) (2026-03-19), "Timezone support for scheduled workflows."

The other zero-run checks:

| Check | Result |
|---|---|
| Workflow file on the default branch | Yes. `main` is the default branch. `.github/workflows/dk-lobby-capture.yml` has been on `main` since `6c54c870` (2026-11-06 22:42:57Z). The last edit of that file on `main` is `0942b2ab` (2026-11-07 18:41:14Z). |
| Cron valid | Yes. `0 10 * * 3` is five-field POSIX. Day 3 is Wednesday. |
| Disabled for inactivity | No. The repository is public and was created 2026-10-21. Commits landed through 2026-11-11 09:41 ET. Workflow id 410530664 is `active`. `refresh.yml` (`0 11 * * *`, no timezone) has schedule runs on 2026-11-06 through 2026-11-10. |
| Added after today's 10:00 ET | No. The file was on `main` five days earlier. 2026-11-11 is the first Wednesday after that. 2026-11-01 was the DST fallback, so 10:00 America/New_York on 2026-11-11 is 15:00 UTC. |

At 15:36 UTC the lobby workflow had one run, the manual dispatch, and zero `schedule` events. That is 36 minutes after 15:00 UTC. GitHub's schedule-event note says runs can be delayed or dropped, and that the start of the hour is a high-load time. This repo's minute-0 refresh cron shows the same delay: its 11:00 UTC runs were created at 17:43Z, 16:40Z, 16:48Z, 21:10Z, and 18:21Z on Nov 6–10, and the Nov 11 11:00 UTC refresh had also not appeared by 15:36Z. A missing lobby event at T+36 minutes matches that delay. It does not show that `timezone` was ignored. If the key were ignored, the same cron would be 10:00 UTC, and this repo's delayed schedule runs would still not be expected at exactly 10:00 UTC.

The approved workflow text stays one cron, `0 10 * * 3`, with `timezone: 'America/New_York'`. Dual 14:00 and 15:00 UTC crons were rejected. AT4 forbids a fixed-UTC cron, and a second cron can double-capture unless a later guard skips one of them. The in-job guard was not added because the timezone key is the mechanism GitHub documents.

### Regression tests

`tests/test_dk_lobby.py::test_oversized_discovery_document_fails_closed` builds a synthetic `getcontests` JSON object. It is not a recorded salary payload. A `DraftGroups` array that `parse_lobby` accepts sits under the cap. The same group with a padded `Contests` string of `OBJECT_LIMIT + 1` bytes returns exit 1, stderr `storage_guard_object`, the same public status line as the run, `truncated=true`, `retained_artifact=false`, `prefix_bytes` equal to the cap, one request to `/lobby/getcontests`, and zero lobby artifacts, snapshots, and salary rows. A following under-cap capture of the same group still publishes 4 synthetic salary rows.

`tests/test_dk_lobby.py::test_nov11_wednesday_slot_stays_on_the_timezone_cron` asserts the single approved cron and timezone, asserts 2026-11-11 10:00 America/New_York is 15:00 UTC, and asserts `0 14 * * 3` and `0 15 * * 3` are absent.

### Commands

Local Postgres 16. The URL was a local role on `127.0.0.1`, not a repository secret and not production. The two skips are `RUN_NETWORK_TESTS` gates in `tests/test_load.py` and `tests/test_dk_classic.py`. They were not run. They do not call DraftKings.

```text
$ python3 -m ruff check loader web tests migrations
All checks passed!

$ DATABASE_URL=postgresql://seam@127.0.0.1:5432/seam_test python3 -m pytest -q --tb=line
294 passed, 2 skipped, 1 warning in 40.18s
```

The warning is Starlette's deprecation of the httpx test client. It is not a failure.

### Still unverified until Cosmo reruns the capture

| Item | Result | Reason |
|---|---|---|
| Live discovery body shape, URL, and length past 5 MiB | UNKNOWN | Public log has reason codes only. Production observation metadata was not read. No live GET. |
| Whether the 2026-11-11 10:00 ET schedule event was delayed or dropped | UNKNOWN | Not dispatched. GitHub may still create a late `schedule` run, or it may have dropped the minute-0 slot. |
| A successful week-10 salary snapshot | UNKNOWN | The object cap was not raised. A rerun hits the same guard if the same body is still over 5 MiB. |

## 2026-11-11 prep: guard log and minute 7

No ADR 0005 change. The object cap is still 5 MiB. The loader does not read past the cap, does not store a `DraftGroups` projection, and does not call a different endpoint.

### Diagnosable `storage_guard_object`

The status line still starts `dk_lobby_salaries season=... week=... status=... reason=storage_guard_object rows=...`. On that failure it now appends fields. Stderr stays the bare reason code. `load_runs` notes stay `reason=...;rows=...;snapshots=...`.

The fields are only what the reader knows when it stops:

| Field | Meaning |
|---|---|
| `path` | URL path of the allowlisted request. Query, fragment, headers, and cookies are not printed. A path that is not a plain path becomes `unknown`. |
| `bytes_read` | Decoded bytes pulled into the buffer when the read stopped. That can be one chunk past the cap. |
| `cap` | `OBJECT_LIMIT` (5242880). |
| `content_length` | Present only when the `Content-Length` header is a decimal integer. |
| `decoded_length` | Present only when the HTTP client already holds the whole decoded body. A stream that stopped at the cap does not get a guessed total. |

Synthetic example from `test_oversized_discovery_document_fails_closed`. The body is `s` padding plus a synthetic `DraftGroups` array, with `Content-Length` set to that length and a cookie the log must not show:

```text
dk_lobby_salaries season=2026 week=10 status=failed reason=storage_guard_object rows=0 path=/lobby/getcontests bytes_read=5242881 cap=5242880 content_length=5242881 decoded_length=5242881
```

The test asserts that line, stderr `storage_guard_object`, and that `sport=NFL`, the cookie, `DraftGroupId`, and `Contests` are absent.

### Schedule minute

`.github/workflows/dk-lobby-capture.yml` cron is now `7 10 * * 3` with `timezone: 'America/New_York'`. 2026-11-11 10:07 America/New_York is 15:07 UTC. `test_nov11_wednesday_slot_stays_on_the_timezone_cron` and `test_at4_schedule_text_and_disabled_gate` assert that text. The hour used for the winter/summer check is still 10. No second UTC cron was added. The workflow was not dispatched.

### Commands

Local Postgres 16 on `127.0.0.1`. Not a repository secret and not production.

```text
$ python3 -m ruff check loader web tests migrations
All checks passed!

$ DATABASE_URL=postgresql://seam@127.0.0.1:5432/seam_test python3 -m pytest -q --tb=line
294 passed, 2 skipped, 1 warning in 40.77s
```

The two skips are `RUN_NETWORK_TESTS` in `tests/test_load.py` and `tests/test_dk_classic.py`. They were not run. They do not call DraftKings. The warning is Starlette's deprecation of the httpx test client.

## 2026-11-11 ADR 0012 discovery cap and gzip at rest

PR #42 head `2a89f83fb3cc15eeb6c7becc768190c576199ebe` (`Merge origin/main into the ADR 0012 docs branch`) is the contract for R10–R14 and AT17–AT31. This replaces the earlier citation of `7a409f82e1df875f1d8c14521ee88434e283a635`. The verified constraint on main, created in `migrations/versions/0004_salary_private.py` lines 59-62 on `salary_private.salary_artifacts`, is:

```text
CONSTRAINT ck_salary_artifacts_body CHECK (
  byte_count = octet_length(body) AND byte_count >= 0 AND octet_length(body) <= 5242880
)
```

`lobby_json` is also the draft-group body, so that check could not single out discovery rows. Revision `0009` (down_revision `0008`) adds kind `lobby_discovery_json` and gzip-at-rest columns. PR #38 also uses revision id `0009` and will renumber; this file is the one that revises `0008`. There is no discovery slice and no PENDING constant. Nothing in the migration deletes a row.

| AT | Result | Evidence |
|---|---|---|
| AT4 | PASS | `test_at4_schedule_text_and_disabled_gate` and `test_nov11_wednesday_slot_stays_on_the_timezone_cron`. Cron text is `7 10 * * 3` with `timezone: 'America/New_York'`. One cron. 2026-11-11 10:07 America/New_York equals 15:07 UTC. |
| AT17 | PASS | `test_at17_six_mib_discovery_is_stored_and_round_trips`. A synthetic 6,291,456-byte getcontests body is stored as `lobby_discovery_json` with `encoding=gzip`, `decoded_bytes=6291456`, and `decode_stored_body` returns the same bytes. A snapshot and 4 salary rows are published. The public log has `discovery_body_bytes=6291456` and does not contain `CONTEST-PADDING-BLOCK`. |
| AT18 | PASS | `test_oversized_discovery_document_fails_closed` and `test_gzip_wire_past_discovery_cap_stops_at_limit_plus_one`. A prior successful snapshot is counted, then a decoded body of 33,554,433 bytes fails `storage_guard_object` with rows 0. Snapshot, salary, and artifact counts stay at the prior values. The truncated prefix is `prefix_bytes=33554432`. A gzip wire under 5 MiB whose decoded body passes the cap stops at 33,554,433 decoded bytes and stores nothing. |
| AT19 | PASS | `test_at19_other_urls_fail_just_over_five_mib`. `draftgroups/v1`, rules, and the salary CSV each fail `storage_guard_object` at 5,242,881 decoded bytes with `cap=5242880` and `bytes_read=5242881`. No snapshot. |
| AT20 | PASS | `test_at20_exact_five_mib_discovery_is_stored`. A discovery body of exactly 5,242,880 decoded bytes is stored and round-trips to those bytes. Gzip at rest means the `bytea` is the gzip member when that member is smaller; the decoded bytes equal the response. |
| AT21 | PASS | `test_gzip_and_identity_round_trip`. A repetitive body stores as `gzip`. `bytes(row.body)` equals the encoded member returned by the writer, and `decode_stored_body` equals the decoded bytes. |
| AT22 | PASS | `test_at22_and_at25_identity_and_gzip_lengths`. `store_discovery_artifact` of `b"Q"` stores `encoding=identity` and the `bytea` equals `b"Q"`. |
| AT23 | PASS | The same test, plus `test_gzip_and_identity_round_trip`. Both the identity row and the gzip row have `decoded_sha256`, `decoded_bytes`, `compressed_sha256`, and `compressed_bytes`. `sha256` equals `decoded_sha256`. `byte_count` equals `decoded_bytes`. |
| AT24 | PASS | `test_at24_storage_limits_fail_closed_without_a_snapshot`. `store_discovery_artifact` accepts 33,554,432 decoded bytes and raises `storage_guard_object` for 33,554,433. `store_artifact` of a CSV accepts 5,242,880 and raises `storage_guard_object` for 5,242,881. `salary_snapshots` count is unchanged. `test_constraint_boundaries` is the matching CHECK evidence. |
| AT25 | PASS | `test_at22_and_at25_identity_and_gzip_lengths`. For both stored rows, `compressed_bytes` equals `octet_length(body)`. The identity row has `compressed_bytes = decoded_bytes`. The gzip row has `compressed_bytes < decoded_bytes`. |
| AT26 | PASS | `test_gzip_and_identity_round_trip`. A second store of the same source and decoded SHA-256 reuses the row. The artifact count stays 1. |
| AT27 | PASS | `test_at27_upgrade_backfills_legacy_rows_without_rewriting_bodies`. Downgrade to `0008`, insert a `lobby_json` row and an `html_gzip` row with media type `application/gzip`, upgrade to head. Both stay `identity`. The new columns equal the pre-upgrade `sha256` and `byte_count`. Both bodies are unchanged. |
| AT28 | PASS | `test_at28_encoded_growth_block_keeps_the_prior_snapshot`. After one successful capture, `encoded_growth_block` is forced to the cumulative guard and then the database guard. Each new body fails closed (`storage_guard_cumulative`, then `storage_guard_database`). Snapshot count and salary count stay at the prior values. The preflight is the block under test. `assert_actual_ceiling` is not what this fixture trips. |
| AT29 | PASS | `test_at29_public_log_includes_storage_warn_tokens`. A successful capture whose private size is at 70% and still under 536,870,912 logs `storage_warn=70 guard=cumulative percent=70 bytes=... limit=536870912` on stderr. The same capture at 85% and still under the guard logs `storage_warn=85 guard=cumulative percent=85 bytes=... limit=536870912`. The 70% log does not contain `storage_warn=85`, and the 85% log does not contain `storage_warn=70`. Artifact count does not fall, and the four salary rows stay. |
| AT30 | PASS | `test_at30_identity_trigger_and_explicit_writer`. An insert with `encoding` NULL and the decoded hash and length supplied is stored as `identity`, and `compressed_sha256` equals `decoded_sha256` and `compressed_bytes` equals `decoded_bytes`, via trigger `salary_artifacts_identity_encoding`. A second insert that sets every field, including `encoding=gzip`, is stored as given. |
| AT31 | PASS | `test_downgrade_refuses_gzip_and_deletes_nothing` refuses a gzip row, leaves it, and stays on `0009`. After the test deletes that fixture, downgrade to `0008` restores a body check that contains `5242880` and not `33554432`, and a kind check that does not contain `lobby_discovery_json`. `test_at31_kind_and_oversize_refuse_without_deleting` refuses an identity `lobby_discovery_json` row and leaves it, then refuses a row with `decoded_bytes=5242881` and leaves that row and its one stored byte. The migration deletes nothing. A decoded body over 5,242,880 bytes that is neither gzip nor `lobby_discovery_json` cannot be inserted: `ck_salary_artifacts_body` rejects it. |
| First live capture body size | UNKNOWN | Record the first real capture's decoded discovery body size in this file once a capture succeeds. |

Mapped tests, local Postgres, no DraftKings call:

```text
$ DATABASE_URL=postgresql://seam@127.0.0.1:5432/seam_test python3 -m pytest -q --tb=line \
  tests/test_dk_lobby.py::test_at4_schedule_text_and_disabled_gate \
  tests/test_dk_lobby.py::test_nov11_wednesday_slot_stays_on_the_timezone_cron \
  tests/test_dk_lobby.py::test_at17_six_mib_discovery_is_stored_and_round_trips \
  tests/test_dk_lobby.py::test_oversized_discovery_document_fails_closed \
  tests/test_dk_lobby.py::test_gzip_wire_past_discovery_cap_stops_at_limit_plus_one \
  tests/test_dk_lobby.py::test_at19_other_urls_fail_just_over_five_mib \
  tests/test_dk_lobby.py::test_at20_exact_five_mib_discovery_is_stored \
  tests/test_dk_lobby.py::test_at28_encoded_growth_block_keeps_the_prior_snapshot \
  tests/test_dk_lobby.py::test_at29_warning_log_does_not_emit_storage_warn \
  tests/test_discovery_storage.py::test_gzip_and_identity_round_trip \
  tests/test_discovery_storage.py::test_at22_and_at25_identity_and_gzip_lengths \
  tests/test_discovery_storage.py::test_at24_storage_limits_fail_closed_without_a_snapshot \
  tests/test_discovery_storage.py::test_constraint_boundaries \
  tests/test_discovery_storage.py::test_at27_upgrade_backfills_legacy_rows_without_rewriting_bodies \
  tests/test_discovery_storage.py::test_at30_identity_trigger_and_explicit_writer \
  tests/test_discovery_storage.py::test_downgrade_refuses_gzip_and_deletes_nothing \
  tests/test_discovery_storage.py::test_at31_kind_and_oversize_refuse_without_deleting
.................                                                        [100%]
17 passed in 2.50s
```

That command is the mapping run from PR #44, where `test_at29_warning_log_does_not_emit_storage_warn` recorded the missing token and AT29 was FAIL. This branch replaces that test with `test_at29_public_log_includes_storage_warn_tokens`. The log line is now `storage_warn=70` or `storage_warn=85` plus `guard`, `percent`, `bytes`, and `limit`. AT29 is PASS.

```text
$ python3 -m ruff check loader web tests migrations
All checks passed!

$ DATABASE_URL=postgresql://seam@127.0.0.1:5432/seam_test python3 -m pytest -q --tb=line tests/test_dk_lobby.py::test_at29_public_log_includes_storage_warn_tokens
.                                                                        [100%]
1 passed in 0.76s

$ DATABASE_URL=postgresql://seam@127.0.0.1:5432/seam_test python3 -m pytest -q --tb=line
328 passed, 3 skipped, 1 warning in 57.44s
```

### Mutator (advisory)

Uncle Bob's mutator supports Python. Checkout `https://github.com/unclebob/mutator` at `830ec7e9c39664d753f8699015bc796df67727b9`, with `https://github.com/unclebob/crapper` beside it so `../crapper` resolves from `/tmp/mutator`. Neither tree is in this repo.

`--changed` on this branch selects nothing: `No source files to mutate.` The files PR #41 merged (`loader/dk_lobby.py`, `loader/salary_private.py`, `migrations/versions/0009_discovery_gzip_at_rest.py`) are already on main, and mutator skips tests. The run therefore named the two loader files.

`loader/salary_private.py`: 104 sites, 103 killed, 0 survived, 1 uncovered (`budget_block` `0 -> 1`), score 100.0%, exit 0. Test command: `python3 -m pytest -q --tb=no tests/test_discovery_storage.py`. The coverage baseline was the full suite: 311 passed, 2 skipped, 1 warning in 53.48s.

`loader/dk_lobby.py`: scan found 488 sites, 433 covered. A kill run with `--max-workers 1` and `python3 -m pytest -q --tb=line tests/test_discovery_storage.py tests/test_dk_lobby.py` was stopped after 7 minutes with no site outcome. Each site reruns those modules serially. Score UNKNOWN. The migration file was not mutated.

## Neon branch rehearsal — Alembic 0009 (`0009_discovery_gzip_at_rest.py`)

Overall: PASS. Run by forge on Wed Nov 11 2026, 10:46–10:48 AM CT, against PR #41 head 3768590ef908f7ad1cc6e722fef9a5c2be78d3c1.

The migration was rehearsed on a throwaway Neon branch, `rehearsal-0009-20261111`, made from production `main`. It used the real table with 8 legacy rows. Production `main` got no writes. The rehearsal branch was deleted afterwards and is recoverable until Sat Nov 14, 10:48 AM CT.

Method: the `upgrade()` and `downgrade()` code was translated to SQL and run through Neon `run_sql_transaction`, not the Alembic CLI. The database is Postgres 17.11.

| Check | Result | Evidence |
|---|---|---|
| Starting revision | PASS | `alembic_version` was 0008 and `salary_private.salary_artifacts` exists |
| Upgrade applies | PASS | 53 ms; `alembic_version` = 0009 |
| Legacy backfill | PASS | 8/8 rows are identity; 0 mismatches in decoded/compressed bytes and sha aliases |
| Bodies and counts untouched | PASS | 8 rows; sum(octet_length(body)) = 3,057,331 before and after; same counts per kind |
| Discovery row at 6 MiB, identity | PASS | accepted, with the aliases correct |
| Discovery row decoded to 33,554,433 bytes | PASS | rejected by `ck_salary_artifacts_body` |
| `lobby_json` at 5,242,881 bytes | PASS | rejected |
| gzip with compressed ≥ decoded | PASS | rejected for both 100=100 and 101>100 |
| Downgrade refuses on discovery or gzip rows | PASS | "downgrade refused: ... nothing was deleted" |
| Downgrade applies | PASS | 16 ms; constraints match the pre-upgrade definitions exactly; columns, trigger and function dropped |
| Upgrade re-applies after downgrade | PASS | 18 ms |
| No grant changes | PASS | no grant statements were run |
| Pre-upgrade sizes | n/a | relation 1,204,224 B; database 118,693,888 B |

Notes:
- Postgres stores the `IN (...)` checks in the form `= ANY (ARRAY[...])`. The meaning is the same.
- The migration also creates the trigger `salary_artifacts_identity_encoding`, which fills in identity encoding when an insert leaves it out.

### Production migration

Merging this revision makes a private-schema migrate run `alembic upgrade head`, which applies `0009` on production. That needs Cosmo's explicit approval. No grants change.

Upgrade, after the nullable add and the identity backfill (`encoding='identity'`, hashes and lengths copied from `sha256` and `byte_count`, body not rewritten):

```sql
ALTER TABLE salary_private.salary_artifacts
    ALTER COLUMN encoding SET NOT NULL,
    ALTER COLUMN decoded_sha256 SET NOT NULL,
    ALTER COLUMN decoded_bytes SET NOT NULL,
    ALTER COLUMN compressed_sha256 SET NOT NULL,
    ALTER COLUMN compressed_bytes SET NOT NULL;

ALTER TABLE salary_private.salary_artifacts
    ADD CONSTRAINT ck_salary_artifacts_encoding
    CHECK (encoding IN ('identity', 'gzip'));

ALTER TABLE salary_private.salary_artifacts DROP CONSTRAINT ck_salary_artifacts_body;
ALTER TABLE salary_private.salary_artifacts
    ADD CONSTRAINT ck_salary_artifacts_body CHECK (
        byte_count = decoded_bytes
        AND sha256 = decoded_sha256
        AND compressed_bytes = octet_length(body)
        AND decoded_bytes >= 0
        AND compressed_bytes >= 0
        AND decoded_sha256 ~ '^[0-9a-f]{64}$'
        AND compressed_sha256 ~ '^[0-9a-f]{64}$'
        AND (
            (encoding = 'identity' AND compressed_bytes = decoded_bytes
                AND compressed_sha256 = decoded_sha256)
            OR (encoding = 'gzip' AND compressed_bytes < decoded_bytes)
        )
        AND (
            (artifact_kind = 'lobby_discovery_json' AND decoded_bytes <= 33554432)
            OR (artifact_kind <> 'lobby_discovery_json' AND decoded_bytes <= 5242880)
        )
    );

ALTER TABLE salary_private.salary_artifacts DROP CONSTRAINT ck_salary_artifacts_kind;
ALTER TABLE salary_private.salary_artifacts
    ADD CONSTRAINT ck_salary_artifacts_kind CHECK (
        artifact_kind IN (
            'csv', 'lobby_json', 'rules_json', 'html_gzip', 'manifest', 'mapping',
            'adapter_row_image', 'rejected_body', 'schedule_raw', 'schedule_reference',
            'lobby_discovery_json'
        )
    );
```

Downgrade raises, and deletes nothing, when any row has `encoding = 'gzip'`, `artifact_kind = 'lobby_discovery_json'`, or `decoded_bytes > 5242880`. Otherwise it drops the trigger, the filler function, the new check, the five columns, and restores the 0004 body check and the 0005 kind list.

```text
$ python3 -m ruff check loader web tests migrations
All checks passed!

$ DATABASE_URL=postgresql://seam@127.0.0.1:5432/seam_test python3 -m pytest -q --tb=line
304 passed, 2 skipped, 1 warning in 43.90s
```

The two skips are still the `RUN_NETWORK_TESTS` gates. They do not call DraftKings.

AT17–AT31 mapping, same database, after the tests added for AT22–AT25, AT27, AT28, AT30, and AT31:

```text
$ python3 -m ruff check loader web tests migrations
All checks passed!

$ DATABASE_URL=postgresql://seam@127.0.0.1:5432/seam_test python3 -m pytest -q --tb=line
311 passed, 2 skipped, 1 warning in 45.16s
```
