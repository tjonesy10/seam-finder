# F001 Pass A test report

Date: 2026-11-05. Scope: schema, Alembic migrations, nflverse loader, `.github/workflows/refresh.yml`. Pass B (API and pages, AT9–AT23) was not built.

## Results

| AT | Result | Evidence |
|---|---|---|
| AT1 | PASS | `tests/test_load.py::test_at1_idempotent_load` |
| AT2 | PASS | `tests/test_load.py::test_at2_row_counts_match_fixture`; live check `test_at2_network_current_season_within_one_percent` |
| AT3 | PASS | `tests/test_load.py::test_at3_chase_week` |
| AT4 | PASS | `tests/test_load.py::test_at4_allen_and_dal_phi` |
| AT5 | PASS | `tests/test_load.py::test_at5_removed_source_row_is_deleted` |
| AT6 | PASS | `tests/test_load.py::test_at6_placeholder_rows_skipped` |
| AT7 | PASS | `tests/test_load.py::test_at7_failed_load_keeps_old_data` |
| AT8 | PASS | `tests/test_load.py::test_at8_load_runs_recorded` |
| AT24 | BLOCKED | `DATABASE_URL` secret is not set, so the live refresh run was not started. The workflow file checks in `tests/test_refresh.py::test_refresh_workflow_schedule_and_dispatch` passed. |
| AT25 | PASS | `tests/test_load.py::test_missing_stats_file_records_failure_and_other_datasets_continue`, `tests/test_load.py::test_cli_module_and_bad_season`, and the workflow has no `continue-on-error` |
| AT26 | PASS | `tests/test_refresh.py::test_at26_no_secrets_in_repo` and a gitleaks scan of history |

## Command

```text
python3 -m pytest tests -v --tb=no
37 passed, 1 skipped in 2.82s
```

The skipped test is the optional network check. It is off unless `RUN_NETWORK_TESTS=1`. Run on its own against a fresh download of the current season:

```text
1 passed in 16.01s
```

Excerpt:

```text
tests/test_load.py::test_at1_idempotent_load PASSED
tests/test_load.py::test_at2_row_counts_match_fixture PASSED
tests/test_load.py::test_at3_chase_week PASSED
tests/test_load.py::test_at4_allen_and_dal_phi PASSED
tests/test_load.py::test_at5_removed_source_row_is_deleted PASSED
tests/test_load.py::test_at6_placeholder_rows_skipped PASSED
tests/test_load.py::test_at7_failed_load_keeps_old_data PASSED
tests/test_load.py::test_at8_load_runs_recorded PASSED
tests/test_load.py::test_cli_module_and_bad_season PASSED
tests/test_refresh.py::test_refresh_workflow_schedule_and_dispatch PASSED
tests/test_refresh.py::test_at26_no_secrets_in_repo PASSED
tests/test_schema.py::test_upgrade_head_twice_is_safe PASSED
======================== 37 passed, 1 skipped in 2.82s =========================
```

Gitleaks (`gitleaks detect --source . --redact --log-opts=--all --no-banner`), exit 0:

```text
INF 7 commits scanned.
INF scanned ~161063 bytes (161.06 KB) in 158ms
INF no leaks found
```

CI workflow: `.github/workflows/ci.yml` (Postgres 16 service, `ruff check`, `pytest`). After push, GitHub reported no check runs on PR #3 (`gh pr checks` → "no checks reported"). The live `refresh.yml` run is the blocked AT24 check.

## Mutation

`./mutator --changed` from the repo root selected nothing: the loader and migrations were already committed, and that flag only sees uncommitted files.

The run that executed was:

```text
/tmp/side/mutator/mutator --no-coverage --max-workers 1 \
  --test-command "/usr/bin/python3 -m pytest -q --tb=no" \
  loader migrations
```

`--max-workers 1` keeps the suite off a shared Postgres. Exit 0.

```text
Total                                                       226         0          0    226  100.0%
```

226 killed, 0 survived, 0 uncovered. No survivors left to add tests for.

Before that run, tests were added for the edges the scan was about to leave open: season/week bounds (`test_season_and_week_bounds`), display-name splitting (`test_split_name_one_and_many_tokens`), release file names, and a missing read-only role. The session fixture rebuilds the schema from the migration on disk so a mutated `0001_initial` is what the column checks see.

## Open questions

1. Season and week bounds. ADR 0002 says "keys non-null and unique; season and week in range; season_type in {REG, POST}" and does not give numbers. The only numbers in the F001 spec are the API rules: "season int 1999-2100; week int 1-22". The loader uses those bounds.

2. Stub player names. ADR 0002 says a missing player gets "a minimal players row (gsis_id, display name, position from the stats file)". The data dictionary marks `first_name` and `last_name` NOT NULL. The loader splits `player_display_name` on the last space. A one-token name is stored in both columns.

3. Game delete versus stats. The data dictionary says `player_week_stats.game_id` is an FK to `games` and does not say `ON DELETE`. The migration uses `ON DELETE CASCADE` so a games reload can remove a game that previous stats still reference. The stats load then rewrites that season.

4. CLI trigger default. The spec lists `--trigger local|manual|schedule` and says "Default: current season, all four datasets." It does not say the default trigger. The CLI uses `local` when the flag is omitted. The workflow always passes `schedule` or `manual`.
