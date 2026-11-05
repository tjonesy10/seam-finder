# F001 Pass A test report

Date: 2026-11-05. Scope: schema, Alembic migrations, nflverse loader, `.github/workflows/refresh.yml`. Pass B (API and pages, AT9–AT23) was not built.

Correction pass: season/week bounds and the `--trigger` default stay as built. `players.first_name` and `players.last_name` are nullable. A stats-only player stores `display_name` and leaves both name columns null until the players file supplies them. Every foreign key is `ON DELETE RESTRICT`. A games load that would delete a game still referenced by `player_week_stats` fails, rolls back, and records `load_runs.status = failed`.

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
| AT24 | BLOCKED | `DATABASE_URL` secret is not set, so the live refresh run was not started. `tests/test_refresh.py::test_refresh_workflow_schedule_and_dispatch` passed. |
| AT25 | PASS | `tests/test_load.py::test_missing_stats_file_records_failure_and_other_datasets_continue`, `tests/test_load.py::test_cli_module_and_bad_season`, and `refresh.yml` has no `continue-on-error` |
| AT26 | PASS | `tests/test_refresh.py::test_at26_no_secrets_in_repo` |

New tests for the correction:

- `tests/test_load.py::test_stub_name_stays_null_until_players_file` — gsis_id `00-0099991`, display name `Odell Beckham Jr.`, null `first_name` and `last_name` until a players-file load sets `Odell` and `Beckham Jr.`
- `tests/test_load.py::test_games_load_that_would_orphan_stats_rolls_back` — removing `2024_10_CIN_BAL` fails on `fk_player_week_stats_game_id`; games and stats are unchanged

## Command

```text
python3 -m pytest tests -q --tb=line
......s...............................                                   [100%]
37 passed, 1 skipped in 2.83s
```

The skip is `test_at2_network_current_season_within_one_percent` unless `RUN_NETWORK_TESTS=1`. That live check passed earlier on its own: `1 passed in 16.01s`.

## CI

`.github/workflows/ci.yml` triggers:

- `pull_request`
- `push` to `main` and to every other branch (`**`)

`actionlint` reports the file as valid. After pushing `2292a92` to `cursor/f001-pass-a-loader-210d`:

- `gh pr checks 3` → `no checks reported on the 'cursor/f001-pass-a-loader-210d' branch`
- `GET /repos/tjonesy10/seam-finder/actions/runs` → HTTP 200 `{"total_count":0,"workflow_runs":[]}`
- `GET /repos/tjonesy10/seam-finder/actions/workflows` → HTTP 200 `{"total_count":0,"workflows":[]}` (GitHub lists workflow files from the default branch only; `ci.yml` is not on `main`)
- `GET /repos/tjonesy10/seam-finder/actions/permissions` → HTTP 403 `{"message":"Resource not accessible by integration","status":"403"}`
- Commit `2292a92` check suites: Claude `queued`, Cursor `queued`. No GitHub Actions suite.

A repository with Actions disabled returns HTTP 403 and the message `Actions is disabled` from the workflows endpoint. This repo returns HTTP 200 and an empty list, so that endpoint does not say Actions is disabled. GitHub still created no workflow run for the push or the pull request. No CI run URL exists.

## Mutation

Command, explicit file list (`--changed` is empty once the files are committed):

```text
/tmp/side/mutator/mutator --no-coverage --max-workers 1 \
  --test-command "/usr/bin/python3 -m pytest -q --tb=no" \
  loader/run.py loader/tables.py migrations/versions/0001_initial.py
```

Exit 3.

```text
Total    Killed 141    Survived 46    Uncovered 0    Sites 187    Score 75.4%
```

Survivors by function:

| Function | Survived |
|---|---|
| `_convert` | 19 |
| `_create_stubs` | 5 |
| `run_load` | 3 |
| `_log` | 2 |
| `load_games` | 2 |
| `load_stats` | 2 |
| `main` | 2 |
| `upgrade` | 2 |
| `delete` path literals, `ensure_unique`, `fields`, `load_players`, `load_teams`, `normalize_database_url`, `parse_datasets`, `parse_seasons`, `redact`, `upsert` | 1 each |

They are coercion edges the fixtures do not hit (boolean and numeric boundary flips inside `_convert`), log `flush` flags, string-join operators, and two migration flags tests do not observe: `Identity(always=True)` and `UUID(as_uuid=True)`. No further tests were added after this run.

## Decisions from the spec owner

1. Season 1999–2100 and week 1–22. Confirmed. No code change.
2. Do not split `player_display_name`. `first_name` and `last_name` are nullable. Confirmed in the migration and loader.
3. Every foreign key is `ON DELETE RESTRICT`. No `ON DELETE CASCADE`. Confirmed.
4. `--trigger` defaults to `local`. Confirmed. No code change.
