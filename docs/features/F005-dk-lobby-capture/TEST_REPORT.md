# F005 test report

Date: 2026-11-06. Scope: migration `0004` (revises `0003`), `loader/salary_private.py`, `loader/dk_lobby.py`, `loader/grants.py` allowlist, and `.github/workflows/dk-lobby-capture.yml`. F006/F007/F008 tables, view, and CLIs are not in this change. No live DraftKings call, no production migration, and no schedule activation.

Synthetic CSV and JSON only. They are built in `tests/test_dk_lobby.py` and labeled synthetic. No salary archive is committed.

## Results

| AT | Result | Evidence |
|---|---|---|
| AT1 | PASS | `tests/test_dk_lobby.py::test_at1_exact_bytes_and_f004_untouched`. BOM CSV bytes and sha256 read back from `salary_private.salary_artifacts`. Ledger `raw_fields` keeps ordered pairs, including `Status`. Four `dk_lobby_salaries` rows. `dk_classic_slate` stays the seeded `f004-keep` row. `dk_classic_salaries` stays empty. |
| AT2 | PASS | `test_at2_sunday_set_excludes_saturday_and_explicit_is_not_main`. Sunday capture stores draft group `90001`, `slate_label=sunday_main`, and only NYJ@NE plus GB@CHI. Explicit id `90002` stores `explicit_group` for the Saturday pair. |
| AT3 | PASS | `test_at3_fail_closed_reasons` and `test_at3_wrong_week_and_holiday_do_not_substitute`. Reasons asserted with no new snapshot: `ambiguous_slate`, `slate_unavailable`, `inexact_game_set`, `missing_rules`, `captain_slot`, `one_game`, `duplicate_dk_id`, `mismatched_metadata`, `wrong_season_week`. The Dec 23 holiday clock makes no HTTP call. |
| AT4 | PASS | `test_at4_schedule_text_and_disabled_gate`. Workflow cron is `0 10 * * 3` with `timezone: 'America/New_York'`. `next_wednesday_10_et` returns 2026-01-07 15:00 UTC and 2026-07-08 14:00 UTC, both Wednesday 10:00 Eastern. One cron. No Sunday cron and no fixed-UTC cron. `capture_schedule_enabled` is true only for the exact string `true`. The job `if` is `vars.DK_LOBBY_CAPTURE_ENABLED == 'true'`. `bash -n` on the capture script passed. No live dispatch. |
| AT5 | PASS | `test_at5_off_season_stale_and_absent_group`. August 1 is `skipped`/`off_season` with `duration_ms` set and zero HTTP calls. A null games `source_version` is `schedule_evidence_missing` with zero HTTP calls. A lobby without the Sunday group is `slate_unavailable` and publishes no snapshot. The workflow script checks `invalid_season`, `invalid_week`, `invalid_draft_group`, and `invalid_selector`. |
| AT6 | PASS | `test_at6_repeat_content_and_identity_revision`. A, A, B, A produce 4 observations and 2 snapshots. The first snapshot's salary `loaded_at` values stay put. Reordered classic roster evidence adds a third snapshot and does not add a third CSV artifact. |
| AT7 | PASS | `test_at7_failures_keep_the_previous_snapshot`. After a good snapshot, a bad header, one `nope` salary, and a real check-constraint failure inside the publish transaction leave that snapshot's rows unchanged. Ledger keeps the `nope` token and `invalid_salary`. Reasons: `parse_failure`, `invalid_salary`, `constraint_failure`. Snapshot count stays 1. |
| AT8 | PASS | `test_at8_reconcile_does_not_double_ingest_or_promote_unrelated`. Crash after the normalized commit reconciles that `load_runs` row to `succeeded` without a second snapshot. A running `teams` load stays `running`. An unrelated running lobby observation becomes `failed`/`interrupted` with null `finished_at` and null `duration_ms`. |
| AT9 | PASS | `test_at9_denial_does_not_retry`. 403, 429 with `Retry-After: 30`, a login redirect, and HTML containing `captcha` each make one wire call. Private `error_private` stores `retry_after=30`. The prior snapshot count stays 1. |
| AT10 | PASS | `test_at10_retries_redirects_and_budget`. Two HTTP 500s then success sleep 1s then 2s and issue 3 lobby calls. Three timeouts stop at `http_timeout` with 3 calls. An off-allowlist redirect makes 1 call and `http_redirect_rejected`. A later request carries no `Cookie` or `Authorization` header. A monotonic jump past 180s stops at `http_budget_exhausted` after the response that crossed the budget. |
| AT11 | PASS | `test_at11_grants_hide_private_and_f004` on Postgres 16. Web role `seam_web_f005` can SELECT `teams`, `players`, `games`, `player_week_stats`, `load_runs`, and `dk_classic_salaries`. It cannot SELECT `dk_classic_slate`, `salary_private.salary_artifacts`, or a test-only `dk_salary_unified` view. Optimizer role `seam_opt_f005` can SELECT that view only after it exists, cannot SELECT `salary_artifacts`, and cannot INSERT. It is not a member of the web role. Granting slate SELECT and running `apply_readonly_grant` again removes that SELECT. `tests/test_schema.py::test_readonly_role_is_select_only` and `tests/test_readonly.py::test_at18_read_only_role` also pass. |
| AT12 | PASS | `test_at12_storage_guards_and_concurrent_lock`. A body of 5 MiB + 1 byte is `storage_guard_object` with `truncated=true` and `retained_artifact=false`. The prior snapshot remains. `read_storage_sizes` reads live `pg_total_relation_size` and `pg_database_size`. `budget_block` rejects invocation bytes above 64 MiB. `cumulative_would_exceed(conn, 128 MiB)` and `database_would_exceed(conn, 512 MiB)` are true on this database because its measured size is already above zero. A 100-byte incoming value does not trip them. Two threads insert manifest artifacts under `pg_advisory_lock` and both rows remain. |
| AT13 | PASS | `test_at13_public_output_has_no_raw_salary`. Stdout, stderr, and `load_runs.notes`/`error` do not contain canary salary `4242`, `Synthetic Quarterback`, or the denied body. `GET /api/dk-lobby` and `GET /dk-lobby.csv` return 404. gitleaks 8.30.1 exit 0. |
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

## What this run did not verify

| Item | Result | Reason |
|---|---|---|
| Live DraftKings JSON field names | UNKNOWN | `/workspace/dk-experiment/reproduce.sh`, the sample lobby/draftables JSON, and `DKSalaries-classic-dg155994.csv` are on Cosmo's computer, not this VM. The parser fail-closes unless the synthetic contract fields are present. No live GET was sent. |
| GitHub's hosted evaluation of the skipped job | UNKNOWN | AT4 forbids a live dispatch. The file gate and the local predicate are tested. |
| Uncle Bob mutator | UNKNOWN | `mutator` is not on `PATH`. `../crapper` is not present. Go is installed. The mutator tool was not installed. This is not a pass. |
| Pull request CI | PASS | Both checks on `6c54c870ac284c7d9734fa005b23a0c809d3ab9f` succeeded: [run 42306824279](https://github.com/tjonesy10/seam-finder/actions/runs/42306824279) and [run 42306805264](https://github.com/tjonesy10/seam-finder/actions/runs/42306805264). |
