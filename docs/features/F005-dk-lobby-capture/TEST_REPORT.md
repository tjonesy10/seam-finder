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
| AT5 | FAIL | Premise being replaced: a fresh `games` load, valid kickoffs on the rows that are present, and week 1 / week 18 (or the first and last loaded kickoff) prove a complete season. That cannot see a missing interior game. The March-to-July date shortcut is removed. The three counterexamples are still red, marked strict xfail so the suite can run: `test_deleted_interior_sunday_game_is_missing_evidence` publishes `captured` rows=2, `test_deleted_interior_week_is_missing_evidence` publishes `captured` rows=4, and `test_incomplete_prior_season_in_april_is_not_off_season` returns `off_season`. No authoritative completeness record was found in the repo or the merged SPEC/ADRs, so none was invented. |
| AT6 | PASS | `test_at6_repeat_content_and_identity_revision`. A, A, B, A produce 4 observations and 2 snapshots. The first snapshot's salary `loaded_at` values stay put. Reordered classic roster evidence adds a third snapshot and does not add a third CSV artifact. |
| AT7 | PASS | `test_at7_failures_keep_the_previous_snapshot`. After a good snapshot, a bad header, one `nope` salary, and a real check-constraint failure inside the publish transaction leave that snapshot's rows unchanged. Ledger keeps the `nope` token and `invalid_salary`. Reasons: `parse_failure`, `invalid_salary`, `constraint_failure`. Snapshot count stays 1. |
| AT8 | PASS | `test_at8_reconcile_does_not_double_ingest_or_promote_unrelated`. Crash after the normalized commit reconciles that `load_runs` row to `succeeded` without a second snapshot. A running `teams` load stays `running`. An unrelated running lobby observation becomes `failed`/`interrupted` with null `finished_at` and null `duration_ms`. |
| AT9 | PASS | `test_at9_denial_does_not_retry` and `test_challenge_on_5xx_is_not_retried` each make one call. `test_login_redirect_keeps_the_body` stores the redirect body `synthetic-login-body` in `salary_artifacts`. |
| AT10 | PASS | Premise replaced: a deadline check between calls does not cap a call that has already started. Connect, header, and each body read now use a timeout of at most the remaining budget, and each later socket read is capped the same way. Before the change, a stall with 1s left reached 189s on connect and 209s on the body read. `test_connect_with_one_second_left_stays_inside_budget` and `test_body_read_with_one_second_left_stays_inside_budget` now pass with the monotonic total at 180s. `test_at10_retries_redirects_and_budget`, `test_trickled_stream_stops_at_the_deadline`, and `test_body_read_timeout_is_retried` still pass. |
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
172 passed, 2 skipped, 3 xfailed, 1 warning in 12.20s

$ gitleaks detect --source . --redact --log-opts=--all --no-banner
11:05PM INF no leaks found
```

The new test is `tests/test_dk_lobby.py::test_draftables_contract_uses_csv_players_not_slot_rows`. Its fixture has three synthetic slot rows and two salary rows, using the real field names.

## What this run did not verify

| Item | Result | Reason |
|---|---|---|
| Draftables JSON contract vs Classic CSV | PASS | Offline read of the uploaded draftables document and matching CSV. No network. Output below. The private files were not committed. |
| GitHub's hosted evaluation of the skipped job | UNKNOWN | AT4 forbids a live dispatch. The file gate and the local predicate are tested. |
| Uncle Bob mutator | UNKNOWN | `mutator` is not on `PATH`. `../crapper` is not present. Go is installed. The mutator tool was not installed. This is not a pass. |
| Pull request CI | PASS | Both checks on `6c54c870ac284c7d9734fa005b23a0c809d3ab9f` succeeded: [run 42306824279](https://github.com/tjonesy10/seam-finder/actions/runs/42306824279) and [run 42306805264](https://github.com/tjonesy10/seam-finder/actions/runs/42306805264). |
