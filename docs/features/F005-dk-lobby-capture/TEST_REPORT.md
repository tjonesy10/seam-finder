# F005 test report

Date: 2026-11-06. Scope: migration `0004` (revises `0003`), `loader/salary_private.py`, `loader/dk_lobby.py`, `loader/grants.py` allowlist, and `.github/workflows/dk-lobby-capture.yml`. F006/F007/F008 tables, view, and CLIs are not in this change. No live DraftKings call, no production migration, and no schedule activation.

Synthetic CSV and JSON only. They are built in `tests/test_dk_lobby.py` and labeled synthetic. No salary archive is committed.

## Results

| AT | Result | Evidence |
|---|---|---|
| AT1 | PASS | `tests/test_dk_lobby.py::test_at1_exact_bytes_and_f004_untouched`. BOM CSV bytes and sha256 read back from `salary_private.salary_artifacts`. Ledger `raw_fields` keeps ordered pairs, including `Status`. Four `dk_lobby_salaries` rows. `dk_classic_slate` stays the seeded `f004-keep` row. `dk_classic_salaries` stays empty. |
| AT2 | PASS | `test_at2_sunday_set_excludes_saturday_and_explicit_is_not_main` stores only the Sunday pair as `sunday_main`. `test_sunday_hydrate_rejects_a_different_group_id` rejects a hydrated document whose `DraftGroupId` differs even when the games match. Explicit mode is covered by `test_hydrate_is_rechecked_and_explicit_id_must_match`. |
| AT3 | PASS | `test_at3_fail_closed_reasons` and `test_at3_wrong_week_and_holiday_do_not_substitute`. Reasons asserted with no new snapshot: `ambiguous_slate`, `slate_unavailable`, `inexact_game_set`, `missing_rules`, `captain_slot`, `one_game`, `duplicate_dk_id`, `mismatched_metadata`, `wrong_season_week`. The Dec 23 holiday clock makes no HTTP call. |
| AT4 | PASS | `test_at4_schedule_text_and_disabled_gate`. Cron `0 10 * * 3` with `timezone: 'America/New_York'`. Next Wednesday 10:00 is 15:00 UTC in January and 14:00 UTC in July. `capture_schedule_enabled('TRUE')` is false. The workflow calls that predicate before `python -m loader.migrate`. GitHub's own `==` was not executed; the AT forbids a live dispatch. |
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
