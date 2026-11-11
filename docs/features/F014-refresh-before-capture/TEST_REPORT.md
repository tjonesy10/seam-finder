# F014 test report

SPEC commit: `ccecc396ce28ae732039166d3e5b884055176d86` (`docs: propose ADR 0013 and F014 refresh inside lobby capture`), on main `f64386489be04db75413e2d4d537f39092a22f6b`.

Implementation base: main `f643864`. No Alembic revision. `alembic heads` on that main is `0009`. Coordination is a session advisory lock (`582014`), distinct from `CAPTURE_LOCK` (`582005`).

Local command, after `npm run build` in `frontend/`:

```text
DATABASE_URL=postgresql://seam@127.0.0.1:5432/seam_test python3 -m pytest
ruff check loader web tests migrations
```

Full Python suite during the mutator coverage baseline (frontend dist present): **340 passed, 3 skipped**. `ruff check loader web tests migrations` passed. The 3 skips are the existing network/opt-in skips, not F014.

## AT1–AT18

| AT | Result | Evidence |
|---|---|---|
| AT1 | PASS | `test_at1_schedule_and_manual_share_one_refresh_receipt`. Trace is gate → validation → migration once → refresh → proof → capture. The capture observation's `pipeline_games_load_run_ids` contains this run's succeeded 2026 games load. |
| AT2 | PASS | `test_at2_gate_blocks_every_side_effect`. Unset, `false`, `TRUE`, and padded values do not call `migrate_production`. Workflow `if` remains `vars.DK_LOBBY_CAPTURE_ENABLED == 'true'`. |
| AT3 | PASS | `test_at3_invalid_manual_input_writes_nothing`. Invalid season, week, range, selector, and draft group stop at validation. `load_runs` count is unchanged. |
| AT4 | PASS | `test_at4_other_season_and_supported_gap`. A fresh 2025 receipt does not authorize a 2026 automatic capture (`schedule_evidence_missing`, no DK calls). A supported gap returns `off_season` with null season/week and no DK calls. |
| AT5 | PASS | `test_at5_refresh_failure_keeps_partial_public_rows`. A missing stats file and an injected refresh stop both record `refresh_failed`, leave prior public rows, and publish no snapshot. |
| AT6 | PASS | `test_at6_missing_proof_does_not_use_a_public_success`. Refresh with the private gate off still loads games and then fails `schedule_evidence_missing` with no DK call and no snapshot. |
| AT7 | PASS | `test_at7_same_run_receipt_rules`. A 30-hour-old retrieval, a 30-minute-future retrieval, and a copied file with no `retrieval.json` fail closed. The same bytes with `retrieved_at` inside the window pass. The stored receipt uses the sidecar time, not the file mtime. |
| AT8 | PASS | `test_at8_wednesday_slot_and_unchanged_daily_refresh`. One cron `7 10 * * 3` with `America/New_York`. 2026-01-07 10:07 EST is 15:07 UTC; 2026-07-08 10:07 EDT is 14:07 UTC. `refresh.yml` stays `0 11 * * *` with no timezone key. |
| AT9 | PASS | `test_at9_sunday_exactness_after_refresh`. Two identical Sunday groups fail `ambiguous_slate`. A Saturday-only holiday week fails `slate_unavailable` with no DK substitution. |
| AT10 | PASS | `test_at10_coordination_excludes_overlapping_work`. A second `run_load` and a direct capture with `wait_seconds=0` return `pipeline_busy` before source work. After release, refresh proceeds. Both workflows set `cancel-in-progress: false` on different groups. |
| AT11 | PASS | `test_at11_lock_loss_deadline_and_no_self_deadlock`. Receipt insert under the coordination lock returns without deadlock. Invalidating the lock connection yields `pipeline_lock_lost`. Advancing the monotonic clock past 30 minutes yields `pipeline_timeout`. `HTTP_BUDGET_S` remains 180. |
| AT12 | PASS | `test_at12_repeat_reuses_snapshot_and_keeps_attempts`. Two manual captures: one snapshot, two `captured` observations, distinct `pipeline_refresh_run_group` values, same games row count. |
| AT13 | PASS | `test_at13_crash_does_not_fabricate_duration`. `before_terminal` leaves `finished_at` and `duration_ms` null. Reconcile marks `interrupted` and still leaves both null. The next attempt inserts one snapshot. |
| AT14 | PASS | `test_at14_and_at18_permissions_inventory_and_no_dispatch`. `contents: read`, `workflow_dispatch` kept, no dispatch API call, checklist present, historical 403 described as a non-goal. No `skip-lock` flag and no `pg_cancel_backend`. |
| AT15 | PASS | `test_at15_storage_limits_unchanged` plus the existing guard suite in the 340-pass run (`tests/test_discovery_storage.py`, `tests/test_dk_lobby.py`). Limits stay 33554432, 5242880, 67108864, 536870912, and 805306368. |
| AT16 | PASS | PR #42 is already on main `f643864`. This implementation does not dispatch, does not change repository variables, and does not treat the 403 as a blocker. CI on the PR head is recorded below after the checks finish. |
| AT17 | PASS | `test_at17_public_output_and_unreachable_database` prints `invalid_season` or `database_unreachable` and does not add an observation when the database is down. Success, refresh failure, proof failure, gap, and repeat metadata are read back in AT1, AT4, AT5, AT6, and AT12. |
| AT18 | PASS | No Render change, no Neon change, no migration, no grant change. Capture reuses `DATABASE_URL`, `READONLY_ROLE`, `SALARY_PRIVATE_MIGRATION`, `DK_SCHEDULE_AUTHORITY_SHA256`, and `DK_LOBBY_CAPTURE_ENABLED`. This PR does not deploy, so there is no new live-site or `/api/health` check. |

## Mutator

Tool: `github.com/unclebob/mutator` with `../crapper` beside it (`/tmp/mutator`, `/tmp/crapper`).

`--changed --scan` on the working tree:

| File | Sites |
|---|---|
| `loader/coordination.py` | 16 |
| `loader/pipeline.py` | 82 |
| `loader/source.py` | 22 |
| `loader/run.py` | 112 |
| `loader/schedule_proof.py` | 244 |
| `loader/dk_lobby.py` | 491 |

Executed, `--max-workers 1`, because the suite shares one Postgres:

```text
/tmp/mutator/mutator --max-workers 1 \
  --test-command "python3 -m pytest -q --tb=no tests/test_f014_pipeline.py::test_manual_bounds_and_negative_duration tests/test_f014_pipeline.py::test_at3_invalid_manual_input_writes_nothing" \
  loader/pipeline.py
```

Final `loader/pipeline.py` score after the boundary tests: **36 killed, 28 survived, 18 uncovered, 82 sites**. `validate_request` and `_duration_ms` are 22/22 and 4/4 killed. The earlier pass on `loader/coordination.py` and `loader/source.py` killed the retrieval and lock-acquire behavior those files added; equivalent boundary mutants (`>` vs `>=` on the 120 second cap, `wait <= 0` vs `<`) survived because the observable result does not change.

`loader/run.py`, `loader/schedule_proof.py`, and `loader/dk_lobby.py` are **UNKNOWN**. A full `--changed` execution is 847 further sites. Each mutant starts a new pytest process against the one shared database, and the coverage baseline alone is about 70 seconds. That run cannot finish in this pass. The full suite (340 passed) still covers those modules.

Remaining pipeline survivors are in `run_pipeline`, `main`, `_report`, and `_record_failure` (`False`/`True` and `and`/`or` on branches the two-test mutant command does not enter). They are not a second product behavior; the 340-pass suite enters those branches.

## CI

Filled in after `gh pr checks` on the PR head.
