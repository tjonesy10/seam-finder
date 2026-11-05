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
.............s.......................................                    [100%]
52 passed, 1 skipped in 3.06s
```

The skip is `test_at2_network_current_season_within_one_percent` unless `RUN_NETWORK_TESTS=1`. That live check passed earlier on its own: `1 passed in 16.01s`.

The 37 passed / 1 skipped count did not change when two tests were added because two tests left in the same edit. Removed: `test_split_name_one_and_many_tokens` (display names are no longer split). Replaced: `test_removed_game_is_deleted` became `test_games_load_that_would_orphan_stats_rolls_back`. Added alongside that replacement: `test_stub_name_stays_null_until_players_file`. Net change zero. This pass adds the conversion and failure-path tests, so the suite is now 52 passed and 1 skipped.

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

Command, same three files (`--changed` is empty once they are committed):

```text
/tmp/side/mutator/mutator --no-coverage --max-workers 1 \
  --test-command "/usr/bin/python3 -m pytest -q --tb=no" \
  loader/run.py loader/tables.py migrations/versions/0001_initial.py
```

Exit 3.

```text
Total    Killed 168    Survived 18    Uncovered 0    Sites 186    Score 90.3%
```

Behavior tests now cover the spec edges that the first survivor list missed: smallint whole numbers, fractions, bools, and the −32768/32767 ends; overtime 0/1; `numeric(6,2)` and `numeric(4,1)` scale and overflow; a one-row null key; a one-year season range; an unknown dataset; `postgres://` URLs; stub counts of zero; a stub with no display name; unresolved team and game ids; an empty games upsert; a players-file failure; explicit data dir over `SEAM_DATA_DIR`; and a non-zero exit when the loader raises.

Skipped survivors, one line each:

- `loader/run.py:132` overtime `0` → `1` in `(0, 1, False, True)`: `False == 0`, so 0 and 1 still match.
- `loader/run.py:132` overtime `1` → `0`: `True == 1`, so 0 and 1 still match.
- `loader/run.py:132` `False` → `True` in that tuple: 0 and 1 are still members.
- `loader/run.py:132` `True` → `False` in that tuple: 0 and 1 are still members.
- `loader/run.py:145` numeric scale fallback `0` → `1`: every numeric field sets `scale`, so the fallback never runs.
- `loader/run.py:146` numeric precision fallback `0` → `1`: every numeric field sets `precision`, so the fallback never runs.
- `loader/run.py:147` `Decimal(1).scaleb` → `Decimal(0).scaleb`: both quantizers produce equal `44.40`, `0.00`, `9999.99`, and `-10.0`.
- `loader/run.py:149` zero-digit count `0` → `1`: 1 is still inside `numeric(6,2)` and `numeric(4,1)`.
- `loader/run.py:149` `digits == (0,)` → `(1,)`: the other branch still computes 0 integer digits for zero.
- `loader/run.py:149` `max(0, …)` → `max(1, …)`: a floor of 1 digit is still under the 3- and 4-digit budgets.
- `loader/run.py:445` stub `rowcount < 0` → `<= 0`: a successful insert returns a positive count, so both comparisons are false.
- `loader/run.py:445` stub `rowcount < 0` → `< 1`: that positive count is not `< 1` either, so the function still returns `rowcount`.
- `loader/run.py:277` status log `flush=True` → `False`: the line is logging only.
- `loader/run.py:279` error log `flush=True` → `False`: the line is logging only.
- `loader/run.py:684` `pool_pre_ping=True` → `False`: the suite uses a live connection either way.
- `loader/tables.py:172` `len(item) > 5` → `>= 5`: every numeric field tuple has length 6, so both expressions read `item[5]`.
- `migrations/versions/0001_initial.py:206` `Identity(always=True)` → `False`: a driver flag, not a load rule.
- `migrations/versions/0001_initial.py:207` `UUID(as_uuid=True)` → `False`: a driver flag, not a load rule. The column is still `uuid`.

## Decisions from the spec owner

1. Season 1999–2100 and week 1–22. Confirmed. No code change.
2. Do not split `player_display_name`. `first_name` and `last_name` are nullable. Confirmed in the migration and loader.
3. Every foreign key is `ON DELETE RESTRICT`. No `ON DELETE CASCADE`. Confirmed.
4. `--trigger` defaults to `local`. Confirmed. No code change.
